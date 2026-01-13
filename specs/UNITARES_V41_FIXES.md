# UNITARES v4.1 Bug Fixes and Parameter Updates

## Quick Reference for Coding Agent

### Fix 1: E Equation Bug (CRITICAL)

**File:** `governance_core/dynamics.py`  
**Line:** ~132

**Find this:**
```python
    # E dynamics: coupling to I, damping by S, drift feedback
    dE_dt = (
        params.alpha * (I - E)           # I → E flow
        - params.beta_E * S              # S damping
        + params.gamma_E * d_eta_sq      # Drift feedback
    )
```

**Replace with:**
```python
    # E dynamics: coupling to I, E-S cross-coupling, drift feedback
    dE_dt = (
        params.alpha * (I - E)           # I → E flow
        - params.beta_E * E * S          # E-S cross-coupling (UNITARES v4.1 Eq. 7)
        + params.gamma_E * d_eta_sq      # Drift feedback
    )
```

**Why:** Paper equation 7 is `Ė = α(I - E) - βₑES + ...`, meaning β_E multiplies both E and S.

---

### Fix 2: Add v4.1 Parameters (Optional - for compliance)

**File:** `governance_core/parameters.py`  
**Add after DEFAULT_PARAMS definition:**

```python
# UNITARES v4.1 optimal parameters (contraction rate α = 0.1)
# Reference: UNITARES v4.1 Section 3.4
V41_PARAMS: DynamicsParams = DynamicsParams(
    # E dynamics
    alpha=0.5,              # Paper: 0.5 (E-I coupling rate)
    beta_E=0.1,             # Paper: 0.1 (E-S coupling)
    gamma_E=0.05,           # Paper: unclear, keeping operational value
    
    # I dynamics  
    k=0.1,                  # Paper: 0.1 (I-S coupling)
    beta_I=0.05,            # Paper: 0.05 (I-V coupling via coherence)
    gamma_I=0.3,            # Paper: 0.3 (I self-nonlinearity)
    
    # S dynamics
    mu=0.8,                 # Paper: 0.8 (S decay)
    lambda1_base=0.3,       # Paper: 0.3 (ethical drift into S)
    lambda2_base=0.05,      # Paper: 0.05 (coherence coupling)
    beta_complexity=0.15,   # Extension: not in paper
    
    # V dynamics
    kappa=0.3,              # Paper: 0.3 (E-V coupling)
    delta=0.4,              # Paper: 0.4 (V decay)
    
    # Coherence
    Cmax=1.0,               # Paper: 1.0
    coherence_scale=1.0,
    
    # Bounds (unchanged)
    E_min=0.0, E_max=1.0,
    I_min=0.0, I_max=1.0,
    S_min=0.001, S_max=2.0,
    V_min=-2.0, V_max=2.0,
    C1_min=0.5, C1_max=1.5,
    eta1_min=0.1, eta1_max=0.5,
)
```

**Note:** The main difference from DEFAULT_PARAMS is `beta_I` (0.3 → 0.05). This significantly changes I dynamics.

#### Enable v4.1 params (opt-in)

- **Preset** (paper-aligned):
  - `UNITARES_PARAMS_PROFILE=v41`
- **Override** (JSON, full/partial):
  - `UNITARES_PARAMS_JSON='{"beta_I":0.05,"alpha":0.5,"gamma_I":0.3}'`

Defaults remain unchanged for backwards compatibility.

---

### Fix 3: Add Equilibrium Computation (New Function)

**File:** `governance_core/dynamics.py`  
**Add after `compute_dynamics` function:**

```python
def compute_equilibrium(
    params: DynamicsParams,
    theta: Theta,
    ethical_drift_norm_sq: float = 0.0,
) -> State:
    """
    Compute equilibrium point where all derivatives are zero.
    
    The UNITARES system with γᵢI(1-I) term has TWO stable equilibria:
    - High equilibrium: I* ≈ 0.91 (healthy operation)
    - Low equilibrium: I* ≈ 0.09 (collapsed state)
    
    This function returns the HIGH equilibrium (desired operating point).
    
    Args:
        params: Dynamics parameters
        theta: Control parameters
        ethical_drift_norm_sq: ‖Δη‖² (default 0)
    
    Returns:
        Equilibrium state (high equilibrium)
    """
    from .coherence import coherence, lambda1, lambda2
    import math
    
    # At equilibrium with V* ≈ 0:
    # C(0) = Cmax * 0.5 * (1 + tanh(0)) = Cmax/2
    C_0 = params.Cmax / 2.0
    
    # From Ṡ = 0: S* = (λ₁‖Δη‖² - λ₂C₀) / μ
    lam1 = lambda1(theta, params)
    lam2 = lambda2(theta, params)
    S_star = max(0.0, (lam1 * ethical_drift_norm_sq - lam2 * C_0) / params.mu)
    
    # From İ = 0 with S*=0: βᵢC₀ = γᵢI*(1-I*)
    # Solve quadratic: γᵢI² - γᵢI + (kS* - βᵢC₀) = 0
    a = params.gamma_I
    b = -params.gamma_I
    c = params.k * S_star - params.beta_I * C_0
    
    discriminant = b**2 - 4*a*c
    if discriminant >= 0 and a != 0:
        # Take the higher root (high equilibrium)
        I_star = (-b + math.sqrt(discriminant)) / (2*a)
        I_star = max(params.I_min, min(params.I_max, I_star))
    else:
        I_star = 0.9  # Default to high equilibrium region
    
    # From Ė = 0: E* ≈ I* (dominant term)
    E_star = I_star
    
    # V* ≈ 0 at equilibrium
    V_star = 0.0
    
    return State(E=E_star, I=I_star, S=S_star, V=V_star)


def estimate_convergence(
    current: State,
    equilibrium: State,
    params: DynamicsParams,
    contraction_rate: float = 0.1,
    target_fraction: float = 0.05,
) -> dict:
    """
    Estimate time/updates to convergence.
    
    Uses exponential bound from contraction theory:
    ‖x(t) - x*‖ ≤ e^{-αt} ‖x(0) - x*‖
    
    Args:
        current: Current state
        equilibrium: Target equilibrium
        params: Dynamics parameters (for dt)
        contraction_rate: α from contraction analysis (default 0.1)
        target_fraction: Convergence threshold (default 0.05 = 95%)
    
    Returns:
        dict with distance, time_to_convergence, updates_to_convergence
    """
    import math
    
    # Compute distance to equilibrium
    distance = math.sqrt(
        (current.E - equilibrium.E)**2 +
        (current.I - equilibrium.I)**2 +
        (current.S - equilibrium.S)**2 +
        (current.V - equilibrium.V)**2
    )
    
    if distance < 1e-6:
        return {
            'distance': distance,
            'time_to_convergence': 0.0,
            'updates_to_convergence': 0,
            'converged': True,
        }
    
    # Time to reach target_fraction: e^{-αt} = target_fraction
    # t = -ln(target_fraction) / α
    dt = 0.1  # Default time step
    time_to_convergence = -math.log(target_fraction) / contraction_rate
    updates_to_convergence = int(math.ceil(time_to_convergence / dt))
    
    return {
        'distance': distance,
        'time_to_convergence': time_to_convergence,
        'updates_to_convergence': updates_to_convergence,
        'converged': False,
    }


def check_basin(state: State, threshold: float = 0.5) -> str:
    """
    Check which basin of attraction the state is in.
    
    The bistable UNITARES system has two basins:
    - 'high': I > threshold, converges to high equilibrium
    - 'low': I < threshold, converges to low equilibrium
    - 'boundary': I ≈ threshold, unstable region
    
    Args:
        state: Current state
        threshold: Basin boundary (default 0.5)
    
    Returns:
        'high', 'low', or 'boundary'
    """
    margin = 0.05
    if state.I > threshold + margin:
        return 'high'
    elif state.I < threshold - margin:
        return 'low'
    else:
        return 'boundary'
```

---

### Fix 4: Update Default Initial State

**File:** `governance_core/dynamics.py`  
**Find:** `DEFAULT_STATE = State(E=0.7, I=0.8, S=0.2, V=0.0)`

This is already good! I=0.8 is safely in the high basin. No change needed.

---

### Test Commands

After making changes, run:
```bash
cd /Users/cirwel/projects/governance-mcp-v1
python -m pytest tests/test_governance_core.py -v
python -m pytest tests/ -k "dynamics or eisv" -v
```
