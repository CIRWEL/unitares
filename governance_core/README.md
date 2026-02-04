# UNITARES Governance Core

**Version:** 2.0.1  
**Status:** Active  
**Last Updated:** 2026-02-04

---

## Overview

The `governance_core` module is the **canonical mathematical implementation** of UNITARES Phase-3 thermodynamic dynamics. It provides the shared foundation for the governance monitor.

This module contains **only math** — no infrastructure, no I/O, no MCP. Pure functions for state evolution, coherence calculation, and scoring.

---

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| **EISV Dynamics** | ✅ Implemented | `dynamics.py` — full differential equations |
| **Coherence Function** | ✅ Implemented | `coherence.py` — C(V,Θ) with tanh |
| **Φ Objective** | ✅ Implemented | `scoring.py` — weighted objective function |
| **Verdict Logic** | ✅ Implemented | `scoring.py` — safe/caution/high-risk |
| **Ethical Drift Vector** | ⚠️ Partial | `ethical_drift.py` — structure exists, oracle missing |

### About Ethical Drift (Δη)

The ethical drift vector Δη is **defined but not populated**:

```python
# The vector structure exists:
Δη = (
    calibration_deviation,    # |predicted_correct - actual_correct|
    complexity_divergence,    # |derived_complexity - self_complexity|
    coherence_deviation,      # |current_coherence - baseline_coherence|
    stability_deviation       # Decision pattern instability
)
```

**What's implemented:**
- `EthicalDriftVector` dataclass with 4 components
- `AgentBaseline` for tracking deviation from normal
- `compute_ethical_drift()` function that combines signals
- Integration into `governance_monitor.py`

**What's NOT implemented:**
- The *oracle* that would detect actual ethical violations
- External behavioral classifiers
- Ground-truth validation of "ethical" vs "unethical" behavior

In practice, `ethical_drift` defaults to `[0,0,0]` because there's no detection system feeding it real signals. The math works — we just don't have the input data.

---

## Module Structure

```
governance_core/
├── __init__.py          # Public API exports
├── parameters.py        # Parameter definitions and defaults
├── dynamics.py          # Core differential equations
├── coherence.py         # Coherence function C(V, Θ)
├── scoring.py           # Objective function Φ and verdicts
├── ethical_drift.py     # Δη vector (partially integrated)
├── phase_aware.py       # Phase-aware dynamics
├── utils.py             # Helper functions
└── README.md            # This file
```

---

## Core Components

### State Variables

```python
from governance_core import State

state = State(
    E=0.7,  # Energy (exploration/productive capacity) [0, 1]
    I=0.8,  # Information integrity [0, 1]
    S=0.2,  # Entropy (disorder/uncertainty) [0, 1]
    V=0.0,  # Void integral (E-I imbalance) [0, 1]
)
```

### Dynamics Engine

```python
from governance_core import step_state, DEFAULT_PARAMS, DEFAULT_THETA

new_state = step_state(
    state=state,
    theta=DEFAULT_THETA,
    delta_eta=[0.0, 0.0, 0.0],  # Ethical drift (usually zero)
    dt=0.1,
    params=DEFAULT_PARAMS,
    complexity=0.5,  # Agent-reported complexity
)
```

### Coherence Function

```python
from governance_core import coherence, DEFAULT_THETA, DEFAULT_PARAMS

C = coherence(V=0.5, theta=DEFAULT_THETA, params=DEFAULT_PARAMS)
# Returns coherence value in [0, Cmax]
```

### Objective Scoring

```python
from governance_core import phi_objective, verdict_from_phi, DEFAULT_WEIGHTS

phi = phi_objective(state, delta_eta=[0.0, 0.0, 0.0], weights=DEFAULT_WEIGHTS)
verdict = verdict_from_phi(phi)
# verdict ∈ {"safe", "caution", "high-risk"}
```

---

## Mathematical Framework

### Differential Equations

```
dE/dt = α(I - E) - βE·S + γE·‖Δη‖²
dI/dt = -k·S + βI·C(V,Θ) - γI·I·(1-I)
dS/dt = -μ·S + λ₁(Θ)·‖Δη‖² - λ₂(Θ)·C(V,Θ) + β_complexity·C
dV/dt = κ(E - I) - δ·V
```

**Parameter status:**
- ✅ `alpha`, `beta_E`, `gamma_E` — E dynamics active
- ✅ `k`, `beta_I`, `gamma_I` — I dynamics active  
- ✅ `mu`, `lambda1`, `lambda2`, `beta_complexity` — S dynamics active
- ✅ `kappa`, `delta` — V dynamics active
- ⚠️ `gamma_E = 0.05` enabled but `‖Δη‖² = 0` in practice (no drift oracle)

### Coherence Function

```
C(V, Θ) = Cmax · 0.5 · (1 + tanh(Θ.C₁ · V))
```

### Objective Function

```
Φ = wE·E - wI·(1-I) - wS·S - wV·|V| - wEta·‖Δη‖²
```

---

## Usage Examples

### Basic State Evolution

```python
from governance_core import (
    State, step_state,
    DEFAULT_PARAMS, DEFAULT_THETA
)

# Initial state
state = State(E=0.7, I=0.8, S=0.2, V=0.0)

# Evolve for 10 steps
for _ in range(10):
    state = step_state(
        state=state,
        theta=DEFAULT_THETA,
        delta_eta=[0.0, 0.0, 0.0],
        dt=0.1,
        params=DEFAULT_PARAMS,
        complexity=0.5,
    )
    print(f"E={state.E:.3f}, I={state.I:.3f}, S={state.S:.3f}, V={state.V:.3f}")
```

### Scoring and Verdicts

```python
from governance_core import phi_objective, verdict_from_phi, DEFAULT_WEIGHTS

phi = phi_objective(state, delta_eta=[0.0, 0.0, 0.0], weights=DEFAULT_WEIGHTS)
verdict = verdict_from_phi(phi)

print(f"Φ = {phi:.3f} → {verdict}")
# Example output: Φ = 0.42 → safe
```

---

## Design Principles

1. **Single Source of Truth** — All dynamics equations implemented once
2. **Mathematical Purity** — No infrastructure, I/O, or side effects
3. **Composable Functions** — Small, focused, easy to test
4. **Type Safety** — Type hints on all functions
5. **Honest Documentation** — Clear about what's implemented vs. aspirational

---

## Integration with governance_monitor.py

The production system uses this module:

```python
# src/governance_monitor.py

from governance_core import (
    State, Theta, step_state, coherence,
    phi_objective, verdict_from_phi,
    EthicalDriftVector, compute_ethical_drift, get_agent_baseline,
    DEFAULT_PARAMS, DEFAULT_THETA, DEFAULT_WEIGHTS,
)

class UNITARESMonitor:
    def update_dynamics(self, agent_state):
        # Use canonical dynamics
        self.state.unitaires_state = step_state(
            state=self.state.unitaires_state,
            theta=self.state.unitaires_theta,
            delta_eta=agent_state.get('ethical_drift', [0.0, 0.0, 0.0]),
            dt=config.DT,
            params=get_active_params(),
            complexity=agent_state.get('complexity', 0.5),
        )
```

---

## Testing

```bash
# Basic import test
python3 -c "from governance_core import *; print('✅ governance_core imported')"

# Dynamics test
python3 -c "
from governance_core import *
state = DEFAULT_STATE
new = step_state(state, DEFAULT_THETA, [0.0], 0.1, DEFAULT_PARAMS, 0.5)
print(f'✅ E={new.E:.3f}, I={new.I:.3f}, S={new.S:.3f}, V={new.V:.3f}')
"
```

---

## What Would Complete Ethical Drift Detection Require?

To make `Δη` actually useful, you'd need:

1. **Behavioral classifiers** — Detect harmful outputs, deceptive patterns, policy violations
2. **Ground truth labels** — Know which agent behaviors were actually problematic
3. **Real-time inference** — Run detection on agent outputs before scoring
4. **Calibration data** — Validate that high `‖Δη‖²` correlates with bad outcomes

This is a research problem, not an engineering task. The current system provides the *infrastructure* for ethical drift — the detection layer is what's missing.

---

## See Also

- `src/governance_monitor.py` — Production monitor using this module
- `src/cirs.py` — Oscillation detection (CIRS v0.1)
- `docs/guides/START_HERE.md` — Agent onboarding

---

**Maintainer:** @CIRWEL  
**Last Updated:** 2026-02-04
