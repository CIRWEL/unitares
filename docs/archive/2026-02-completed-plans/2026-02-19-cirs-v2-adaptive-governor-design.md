# CIRS v2: Adaptive Governor Design

**Date:** 2026-02-19
**Status:** Approved
**Scope:** Full redesign of CIRS — oscillation damping, phase adaptation, multi-agent coordination as one coherent system

## Problem Statement

CIRS v0.1 detects oscillations and computes damped thresholds but never applies them. Governance decisions use static config values regardless of oscillation state. Meanwhile, a phase-aware v1.0 implementation exists in `governance_core/cirs_damping.py` but is exported and never imported. The CIRS protocol (multi-agent coordination) shares branding but has no connection to damping.

Three failure modes are unaddressed:
1. **Threshold oscillation** — agents bounce between proceed/pause because rigid thresholds don't adapt
2. **Multi-agent interference** — agents destabilize each other with no awareness of neighbors
3. **Stale governance** — static thresholds punish exploration-phase agents with integration-mode strictness

## Architecture: Adaptive Threshold Controller with PID Math

### Core Principle

Thresholds are living per-agent state, not config constants. An `AdaptiveGovernor` owns threshold management, using PID-inspired control theory to adapt thresholds toward phase-appropriate reference points while damping oscillation through the derivative term.

### AdaptiveGovernor

One class replaces five scattered components:
- `src/cirs.py` OscillationDetector
- `src/cirs.py` ResonanceDamper
- `src/cirs.py` classify_response()
- `governance_core/cirs_damping.py` (phase-aware v1.0)
- Static threshold lookups from `config/governance_config.py`

#### Per-Agent State

```
tau: float          # Coherence threshold (starts at config default 0.40)
beta: float         # Risk threshold (starts at config default 0.60)
phase: Phase        # Exploration or Integration (detected from EISV dynamics)
reference: (float, float)  # Target (tau, beta) for current phase

# PID accumulators
error_integral_tau: float   # Accumulated tau deviation
error_integral_beta: float  # Accumulated beta deviation
prev_error_tau: float       # Previous tau error (for D-term)
prev_error_beta: float      # Previous beta error (for D-term)

# Oscillation tracking (kept for observability)
oi: float           # Oscillation Index
flips: int          # Route flip count in window
history: list       # Rolling window of observations
```

#### Update Cycle (called from process_agent_update)

```
1. Detect phase from recent EISV trajectory
   - Uses existing governance_core/phase_aware.detect_phase()

2. Set reference point based on phase
   - Exploration: tau_ref=0.35, beta_ref=0.55 (more forgiving)
   - Integration: tau_ref=0.40, beta_ref=0.60 (stricter)

3. Compute error signals
   - e_tau = tau_ref - current_tau
   - e_beta = beta_ref - current_beta

4. PID update for each threshold
   - P-term: K_p * error (proportional to current deviation)
   - I-term: K_i * integral(error) (accumulated sustained deviation)
   - D-term: K_d * d(error)/dt (rate of change — THIS IS THE DAMPING)
   - adjustment = P + I + D

5. Apply bounded threshold adjustment
   - tau_new = clamp(tau + adjustment_tau, tau_floor, tau_ceiling)
   - beta_new = clamp(beta + adjustment_beta, beta_floor, beta_ceiling)

6. Update oscillation metrics (OI, flips) for observability

7. Make verdict using ADAPTIVE thresholds
   - Safe: coherence >= tau_new AND risk < beta_approve
   - Caution: coherence >= tau_new AND risk < beta_new
   - High-risk: coherence < tau_new OR risk >= beta_new
   - Hard block: coherence < tau_floor OR risk > beta_ceiling
```

#### PID Gains (Initial Tuning)

```python
K_p = 0.05    # Gentle proportional — avoid snapping to reference
K_i = 0.005   # Very slow integral — only matters for sustained drift
K_d = 0.10    # Strongest term — prioritizes damping oscillation

# Phase modulation:
# Exploration: K_d *= 0.5 (tolerate more oscillation while learning)
# Integration: K_d *= 1.0 (full damping for stability)
```

#### Hard Safety Bounds (Cannot Be Overridden)

```python
tau_floor = 0.25      # Coherence can never drop below this
tau_ceiling = 0.75    # Coherence threshold can never exceed this
beta_floor = 0.20     # Risk threshold floor
beta_ceiling = 0.70   # Risk can never exceed this before hard block
```

#### Integral Wind-up Protection

The I-term is clamped to prevent runaway accumulation:
```python
integral_max = 0.10   # Max contribution from integral term
# Reset integral when error crosses zero (agent crossed reference)
```

#### Threshold Decay

When the agent is stable (no oscillation, phase unchanged), thresholds slowly decay back toward config defaults:
```python
decay_rate = 0.01  # Per update, thresholds move 1% toward config default
# Only applies when |OI| < 0.5 and flips == 0 in window
```

## Multi-Agent Coordination

### Connection to CIRS Protocol

The existing CIRS protocol (void_alert, state_announce, coherence_report, boundary_contract) gains two new signal types:

#### RESONANCE_ALERT

Emitted when an agent's governor detects sustained oscillation (OI above threshold for 3+ consecutive updates):

```python
{
    "type": "RESONANCE_ALERT",
    "agent_id": "...",
    "oi": 3.2,
    "phase": "integration",
    "tau_current": 0.43,
    "beta_current": 0.57,
    "flips": 4,
    "duration_updates": 5
}
```

#### STABILITY_RESTORED

Emitted when an agent exits resonance (OI drops below threshold):

```python
{
    "type": "STABILITY_RESTORED",
    "agent_id": "...",
    "oi": 0.8,
    "tau_settled": 0.41,
    "beta_settled": 0.59
}
```

### Neighbor Pressure

When an agent receives a RESONANCE_ALERT from a neighbor:

1. Check coherence_report similarity with the resonating agent
2. If similarity > 0.5 (shared state surface): apply defensive bias
   - Tighten own thresholds by `neighbor_pressure_factor * similarity`
   - `neighbor_pressure_factor = 0.02` (small, defensive)
3. If similarity <= 0.5: ignore (unrelated agent)
4. On STABILITY_RESTORED: decay the defensive bias over 5 updates

### Boundary Contracts (Extension)

Agents can declare their phase to neighbors:
```python
{
    "type": "BOUNDARY_CONTRACT",
    "agent_id": "...",
    "declared_phase": "exploration",
    "volatility_expected": true
}
```

Neighbors receiving this adjust their defensive reaction: exploration-declared agents get a higher similarity threshold before triggering neighbor pressure (0.7 instead of 0.5).

## Observability

### API Response (cirs block in process_agent_update)

```python
result['cirs'] = {
    # Adaptive thresholds (NEW — the core addition)
    'tau': 0.43,
    'beta': 0.57,
    'tau_default': 0.40,
    'beta_default': 0.60,
    'phase': 'exploration',

    # Controller state (NEW)
    'controller': {
        'p_tau': 0.02,
        'i_tau': 0.01,
        'd_tau': -0.03,
        'p_beta': -0.01,
        'i_beta': 0.00,
        'd_beta': 0.02,
    },

    # Oscillation metrics (kept from v0.1)
    'oi': 1.8,
    'flips': 2,
    'resonant': False,
    'trigger': None,
    'response_tier': 'safe',

    # Multi-agent (NEW)
    'neighbor_pressure': 0.00,
    'agents_in_resonance': 0,
}
```

### WebSocket Streaming

The existing `/ws/eisv` WebSocket endpoint (via EISVBroadcaster) broadcasts CIRS state changes alongside EISV updates. No new endpoint needed.

### Metrics Removal

- Remove `damping_applied_count` (was counting no-ops)
- Replace with actual threshold movement history (last 10 adjustments)

## File Changes

| Current File | Action | New File |
|---|---|---|
| `governance_core/cirs_damping.py` | **Replace** | `governance_core/adaptive_governor.py` |
| `src/cirs.py` | **Deprecate** | Thin re-export shim for backward compat |
| `governance_core/phase_aware.py` | **Keep** | Used by AdaptiveGovernor internally |
| `governance_core/__init__.py` | **Update** | Export AdaptiveGovernor, keep old names |
| `src/governance_monitor.py` | **Modify** | Swap detector+damper for AdaptiveGovernor |
| `src/mcp_handlers/cirs_protocol.py` | **Extend** | Add RESONANCE_ALERT, STABILITY_RESTORED |
| `config/governance_config.py` | **Keep** | Static defaults become initial values |

### Backward Compatibility

`src/cirs.py` becomes a thin shim:
```python
# Backward compatibility — canonical implementation moved to governance_core
from governance_core.adaptive_governor import (
    OscillationState, DampingResult, AdaptiveGovernor
)
# Legacy aliases
OscillationDetector = ...  # Wrapper that delegates to AdaptiveGovernor
ResonanceDamper = ...      # Wrapper that delegates to AdaptiveGovernor
classify_response = ...    # Delegates to governor.make_verdict()
CIRS_DEFAULTS = { ... }    # Kept for config readers
HCK_DEFAULTS = { ... }     # Kept for config readers
```

### Migration Strategy

1. Build `AdaptiveGovernor` in `governance_core/adaptive_governor.py`, test in isolation
2. Wire into `governance_monitor.py` behind feature flag (`ADAPTIVE_GOVERNOR_ENABLED = False`)
3. Run both old and new in parallel, log comparison (shadow mode)
4. Validate with Lumen (real agent traffic) for 24-48 hours
5. Flip flag to `True`, remove old code path
6. Clean up: remove feature flag, update shim

## Testing Strategy

### Unit Tests (governance_core/adaptive_governor.py)

- Initialization with config defaults
- Phase detection shifts reference point correctly
- P-term moves threshold toward reference under sustained deviation
- I-term accumulates under sustained deviation, resets on zero-crossing
- D-term produces damping under oscillating input
- D-term is larger during integration phase than exploration
- Hard bounds are never violated (fuzz test with extreme inputs)
- Threshold decay returns to defaults when input stabilizes
- Neighbor pressure biases thresholds within safe bounds
- Integral wind-up protection prevents runaway I-term

### Integration Tests (governance_monitor.py)

- `process_agent_update` uses adaptive thresholds, not static config
- Oscillating agent: thresholds adjust, verdict changes from caution to safe
- Exploration-phase agent gets wider bounds than integration-phase agent
- Feature flag off: behavior identical to current static thresholds
- Shadow mode: both paths run, outputs logged for comparison

### Multi-Agent Tests

- RESONANCE_ALERT emitted when OI sustained above threshold
- STABILITY_RESTORED emitted when OI drops below threshold
- Neighbor with high similarity tightens thresholds on RESONANCE_ALERT
- Neighbor with low similarity ignores RESONANCE_ALERT
- Defensive bias decays after STABILITY_RESTORED

### Regression Tests

- All existing `test_cirs.py` tests pass against backward-compat shim
- `process_agent_update` response still contains `cirs` block with existing keys
- `classify_response()` returns same tiers for same inputs (static mode)
- CIRS protocol existing signal types unchanged

## Open Questions

1. **PID gain tuning** — Initial values are educated guesses. Need real agent traffic to tune. Shadow mode comparison will inform this.
2. **Threshold persistence** — Should adaptive thresholds survive server restart? Current design: no (restart resets to config defaults). Could add DB persistence later.
3. **Per-agent vs global governor** — Current design: one governor instance per agent (in GovernanceMonitor). Could be global with per-agent state dict. Per-agent is simpler to reason about.
