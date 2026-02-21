# Resonance → CIRS Protocol Wiring Design

**Date:** 2026-02-21
**Status:** Approved
**Scope:** Wire AdaptiveGovernor resonance detection to CIRS auto-emit + neighbor pressure

## Problem

The AdaptiveGovernor (CIRS v2) detects oscillation via OI and verdict flips, setting `resonant=True` and `trigger` in its result dict. But nothing reads these fields:

- `RESONANCE_ALERT` is never auto-emitted to peers
- `apply_neighbor_pressure()` is never called on neighboring agents
- `decay_neighbor_pressure()` is never called when agents stabilize

The multi-agent distributed damping described in the paper (§8) is inert. The PID controller works locally but the network coupling loop is broken.

## Solution: Auto-Emit Hook Pattern (Approach A)

Follow the established pattern of `maybe_emit_void_alert` and `auto_emit_state_announce`:

### New Functions in `cirs_protocol.py`

#### 1. `maybe_emit_resonance_signal(agent_id, cirs_result, was_resonant)`

Detects resonance state *transitions* and emits the appropriate signal:

- `was_resonant=False → resonant=True`: emit `RESONANCE_ALERT` with OI, phase, tau, beta, flips
- `was_resonant=True → resonant=False`: emit `STABILITY_RESTORED` with settled tau/beta
- No transition: no-op (don't flood the buffer with repeated alerts)

Returns the emitted signal dict or None.

#### 2. `maybe_apply_neighbor_pressure(agent_id, governor)`

Reads recent `RESONANCE_ALERT` signals from other agents and applies defensive pressure:

1. Get recent resonance alerts (last 30 min) excluding self
2. For each alert source, look up coherence report similarity in `_coherence_report_buffer`
3. If similarity ≥ 0.5 (governor's default threshold): call `governor.apply_neighbor_pressure(similarity)`
4. Also check for `STABILITY_RESTORED` signals from previously-pressuring agents: call `governor.decay_neighbor_pressure()`

Conservative default: if no coherence report exists for a pair, skip pressure (don't guess similarity).

### State Tracking

Add `was_resonant: bool = False` to `GovernorState` in `adaptive_governor.py`. Updated in `_update_oscillation` before computing the new `resonant` value. This keeps the transition tracking close to where `resonant` is set.

### Wiring in `core.py`

Add two calls after the existing CIRS hooks (~line 1089):

```python
# CIRS Protocol: Auto-emit RESONANCE_ALERT / STABILITY_RESTORED on transitions
try:
    from .cirs_protocol import maybe_emit_resonance_signal
    cirs_resonance = maybe_emit_resonance_signal(
        agent_id=agent_id,
        cirs_result=cirs_result,
        was_resonant=was_resonant,
    )
except Exception as e:
    logger.debug(f"CIRS resonance auto-emit skipped: {e}")

# CIRS Protocol: Apply neighbor pressure from peer resonance alerts
try:
    from .cirs_protocol import maybe_apply_neighbor_pressure
    maybe_apply_neighbor_pressure(
        agent_id=agent_id,
        governor=monitor.adaptive_governor,
    )
except Exception as e:
    logger.debug(f"CIRS neighbor pressure skipped: {e}")
```

### Call Ordering

```
process_agent_update (core.py)
  │
  ├── monitor.process_update()          ← governor runs, sets resonant/trigger
  ├── maybe_emit_void_alert()           ← existing hook
  ├── auto_emit_state_announce()        ← existing hook
  ├── maybe_emit_resonance_signal()     ← NEW: emit on transitions
  └── maybe_apply_neighbor_pressure()   ← NEW: read peer alerts, apply pressure
```

Neighbor pressure is applied *after* the current update, so it takes effect on the *next* cycle. This avoids feedback within a single tick.

## Files Changed

| File | Change |
|------|--------|
| `governance_core/adaptive_governor.py` | Add `was_resonant: bool` to `GovernorState`, set it in `_update_oscillation` |
| `src/mcp_handlers/cirs_protocol.py` | Add `maybe_emit_resonance_signal()` and `maybe_apply_neighbor_pressure()` |
| `src/mcp_handlers/__init__.py` | Export the two new functions |
| `src/mcp_handlers/core.py` | Wire the two new hooks after existing CIRS hooks |
| `tests/test_adaptive_governor.py` | Test `was_resonant` transition tracking |
| `tests/test_cirs_resonance_wiring.py` | NEW: end-to-end wiring tests |

## Test Plan

1. **Unit: `was_resonant` tracking** — governor tracks previous resonant state across updates
2. **Unit: `maybe_emit_resonance_signal`** — RESONANCE_ALERT on False→True, STABILITY_RESTORED on True→False, no-op on same state
3. **Unit: `maybe_apply_neighbor_pressure`** — pressure applied when similarity ≥ 0.5, skipped when < 0.5, skipped when no coherence report
4. **Integration: full loop** — governor detects → alert emitted → peer reads → peer tightens
5. **Regression** — all existing tests pass

## Non-Goals

- Persistence of CIRS buffers to PostgreSQL (separate task, priority #2)
- New MCP tools (existing `resonance_alert` and `stability_restored` tools already work)
- Pub/sub event bus (justified: 4th hook in established pattern, 1:1 producer-consumer)
- Changes to PID math or oscillation detection thresholds
- Changes to coherence report computation

## Design Decision: Why Not Pub/Sub

The established auto-emit hook pattern (function call from `core.py`) is superior for this change because:

1. We have exactly 1 producer (governor) and 1 consumer (CIRS protocol)
2. The pattern is proven across 3 existing hooks
3. Python asyncio lacks a built-in event bus; we'd add abstraction for zero immediate benefit
4. The hook approach is trivially debuggable (step through `core.py` line by line)

Trigger for refactoring to pub/sub: when we're adding a 5th+ hook and `core.py` becomes hard to read. That's a concrete signal, not a speculative one.
