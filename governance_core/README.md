# UNITARES Governance Core

**Version:** 2.0.0
**Status:** Active
**Created:** November 22, 2025

---

## Overview

The `governance_core` module is the **canonical mathematical implementation** of UNITARES Phase-3 thermodynamic dynamics. It provides the shared foundation for both:

1. **UNITARES** (production governance monitor)
2. **unitaires** (research/exploration tools)

This eliminates code duplication and ensures both systems use identical dynamics.

---

## Module Structure

```
governance_core/
├── __init__.py          # Public API exports
├── parameters.py        # Parameter definitions and defaults
├── dynamics.py          # Core differential equations
├── coherence.py         # Coherence function C(V, Θ)
├── scoring.py           # Objective function Φ
├── utils.py             # Helper functions
└── README.md            # This file
```

---

## Core Components

### State Variables

```python
from governance_core import State

state = State(
    E=0.7,  # Ethical allocation [0, 1]
    I=0.8,  # Information integrity [0, 1]
    S=0.2,  # Semantic uncertainty [0, 2]
    V=0.0,  # Void integral [-2, 2]
)
```

### Dynamics Engine

```python
from governance_core import compute_dynamics, DEFAULT_PARAMS, DEFAULT_THETA

new_state = compute_dynamics(
    state=state,
    delta_eta=[0.1, 0.0, -0.05],  # Ethical drift vector
    theta=DEFAULT_THETA,           # Control parameters
    params=DEFAULT_PARAMS,         # Dynamics parameters
    dt=0.1,                        # Time step
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

phi = phi_objective(state, delta_eta=[0.1, 0.0], weights=DEFAULT_WEIGHTS)
verdict = verdict_from_phi(phi)
# verdict ∈ {"safe", "caution", "high-risk"}
```

---

## Mathematical Framework

### Differential Equations

```
dE/dt = α(I - E) - βE·S + γE·‖Δη‖²
dI/dt = -k·S + βI·C(V,Θ) - γI·I·(1-I)
dS/dt = -μ·S + λ₁(Θ)·‖Δη‖² - λ₂(Θ)·C(V,Θ) + noise
dV/dt = κ(E - I) - δ·V
```

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
    State, compute_dynamics,
    DEFAULT_PARAMS, DEFAULT_THETA
)

# Initial state
state = State(E=0.7, I=0.8, S=0.2, V=0.0)

# Ethical drift
delta_eta = [0.1, 0.0, -0.05]

# Evolve for 10 steps
for _ in range(10):
    state = compute_dynamics(
        state=state,
        delta_eta=delta_eta,
        theta=DEFAULT_THETA,
        params=DEFAULT_PARAMS,
        dt=0.1,
    )
    print(f"E={state.E:.3f}, I={state.I:.3f}, S={state.S:.3f}, V={state.V:.3f}")
```

### Custom Parameters

```python
from governance_core import DynamicsParams, Theta

# Custom dynamics parameters
params = DynamicsParams(
    alpha=0.5,      # Faster E-I coupling
    mu=1.0,         # Faster S decay
    beta_I=0.4,     # Stronger coherence boost
)

# Custom control parameters
theta = Theta(
    C1=1.2,         # Steeper coherence transition
    eta1=0.4,       # Higher drift sensitivity
)

state = compute_dynamics(state, delta_eta, theta, params, dt=0.1)
```

### Scoring and Verdicts

```python
from governance_core import phi_objective, verdict_from_phi, Weights

# Custom weights
weights = Weights(
    wE=0.6,    # More emphasis on E
    wI=0.7,    # More emphasis on I
    wS=0.4,    # Less penalty on S
    wV=0.5,
    wEta=0.3,  # Less penalty on drift
)

phi = phi_objective(state, delta_eta, weights)
verdict = verdict_from_phi(phi)

print(f"Φ = {phi:.3f} → {verdict}")
```

---

## Design Principles

### 1. Single Source of Truth
- All dynamics equations are implemented once
- Both UNITARES and unitaires import from here
- No code duplication

### 2. Mathematical Purity
- This module contains **only** math
- No infrastructure (MCP, persistence, etc.)
- No I/O or side effects

### 3. Composable Functions
- Small, focused functions
- Clear interfaces
- Easy to test

### 4. Type Safety
- All functions use type hints
- Dataclasses for structured data
- Clear parameter contracts

### 5. Documentation
- Every function has docstrings
- Mathematical equations in comments
- Usage examples provided

---

## Integration with UNITARES

The production UNITARES system uses this module for its dynamics:

```python
# src/governance_monitor.py (future integration)

from governance_core import compute_dynamics, DynamicsParams, Theta

class UNITARESMonitor:
    def update_dynamics(self, agent_state):
        # Convert to core state
        from governance_core import State

        core_state = State(
            E=self.state.E,
            I=self.state.I,
            S=self.state.S,
            V=self.state.V
        )

        # Use canonical dynamics
        new_state = compute_dynamics(
            state=core_state,
            delta_eta=agent_state.get('ethical_drift', []),
            theta=Theta(C1=1.0, eta1=0.3),
            params=DynamicsParams(),
            dt=0.1,
        )

        # Update internal state
        self.state.E = new_state.E
        self.state.I = new_state.I
        self.state.S = new_state.S
        self.state.V = new_state.V
```

---

## Integration with unitaires

The research unitaires system uses this module:

```python
# src/unitaires-server/unitaires_core.py (future integration)

from governance_core import compute_dynamics, DynamicsParams, State, Theta

def step_state(state: State, theta: Theta, delta_eta: List[float], dt: float):
    """Wrapper maintaining unitaires API"""
    return compute_dynamics(
        state=state,
        delta_eta=delta_eta,
        theta=theta,
        params=DynamicsParams(),
        dt=dt,
    )
```

---

## Testing

```bash
# Run basic import test
python3 -c "from governance_core import *; print('✅ governance_core imported successfully')"

# Run dynamics test
python3 -c "
from governance_core import *
state = DEFAULT_STATE
new_state = compute_dynamics(state, [0.1], DEFAULT_THETA, DEFAULT_PARAMS, 0.1)
print(f'✅ State evolution: E={new_state.E:.3f}, I={new_state.I:.3f}')
"
```

---

## Version History

### 2.0.0 (November 22, 2025)
- Initial release
- Extracted from unitaires_core.py
- Created modular structure
- Full documentation

---

## See Also

- `ARCHITECTURE.md` - Overall system architecture
- `src/unitaires-server/unitaires_core.py` - Original implementation
- `src/governance_monitor.py` - UNITARES production monitor
- `IMPLEMENTATION_COMPARISON.md` - Comparison of approaches

---

**Status:** Production Ready
**Maintainer:** claude_code_cli
**Last Updated:** November 22, 2025
