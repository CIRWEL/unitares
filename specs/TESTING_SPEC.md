# UNITARES governance_core Test Coverage Spec

## Current State
- **Coverage: 13%** - critically low
- **Untested**: Core EISV dynamics, scoring, phase detection, ethical drift
- **Tested**: Only imports and basic smoke tests

## Goal
Raise `governance_core/` coverage to **80%+** with meaningful unit tests.

## Files to Test (Priority Order)

### 1. `governance_core/dynamics.py` (CRITICAL - 0% coverage)
Core EISV differential equations. This is the heart of UNITARES.

**Functions to test:**
- `compute_dynamics()` - Main dynamics step
- `step_state()` - Convenience wrapper
- `compute_equilibrium()` - Find equilibrium state
- `estimate_convergence()` - Convergence estimation
- `check_basin()` - Basin of attraction check
- `compute_saturation_diagnostics()` - Saturation analysis

**Test cases needed:**
```python
# Basic dynamics
def test_compute_dynamics_from_default_state():
    """Starting from DEFAULT_STATE, one step should produce valid EISV"""
    
def test_dynamics_preserves_bounds():
    """E, I, S, V should stay within physical bounds after any step"""
    
def test_dynamics_with_zero_drift():
    """With no ethical drift, system should relax toward equilibrium"""
    
def test_dynamics_with_high_drift():
    """High ethical drift should increase S (entropy)"""

def test_dynamics_complexity_affects_entropy():
    """Higher complexity should increase S via beta_complexity term"""

def test_dynamics_v_accumulates_ei_imbalance():
    """V should accumulate when E != I"""

# Linear vs logistic I dynamics (v4.1 vs v4.2-P)
def test_i_dynamics_logistic_mode():
    """Logistic mode: dI/dt = A - γ_I·I·(1-I)"""
    
def test_i_dynamics_linear_mode():
    """Linear mode: dI/dt = A - γ_I·I (prevents saturation)"""

# Edge cases
def test_dynamics_at_boundary_states():
    """Test dynamics when E=0, I=1, S=0, etc."""

def test_dynamics_numerical_stability():
    """Run 1000 steps, verify no NaN/Inf"""
```

### 2. `governance_core/coherence.py` (0% on functions)

**Functions to test:**
- `coherence(V, theta, params)` - C(V,Θ) = Cmax · 0.5 · (1 + tanh(Θ.C₁ · V))
- `lambda1(theta, params)` - Adaptive λ₁ via eta1 mapping
- `lambda2(theta, params)` - λ₂ base value

**Test cases:**
```python
def test_coherence_at_v_zero():
    """C(V=0) should equal 0.5 * Cmax"""

def test_coherence_monotonic_in_v():
    """C(V) should increase as V increases"""

def test_coherence_bounds():
    """C(V) should be in [0, Cmax] for any V"""

def test_lambda1_eta1_mapping():
    """eta1 in [0.1, 0.5] should map to lambda1 in [0.05, 0.20]"""

def test_lambda1_clamping():
    """eta1 outside [0.1, 0.5] should be clamped"""
```

### 3. `governance_core/scoring.py` (0% coverage)

**Functions to test:**
- `phi_objective()` - Compute Φ score
- `verdict_from_phi()` - Convert Φ to verdict

**Test cases:**
```python
def test_phi_default_healthy_state():
    """DEFAULT_STATE with zero drift should have positive Φ"""

def test_phi_high_entropy_penalized():
    """High S should decrease Φ"""

def test_phi_high_drift_penalized():
    """High ethical drift should decrease Φ"""

def test_verdict_thresholds():
    """Verify safe/caution/high-risk thresholds"""
    
def test_verdict_safe():
    """Φ >= 0.15 should be 'safe'"""

def test_verdict_caution():
    """0.0 <= Φ < 0.15 should be 'caution'"""

def test_verdict_high_risk():
    """Φ < 0.0 should be 'high-risk'"""
```

### 4. `governance_core/ethical_drift.py` (0% coverage)
Concrete ethical drift vector implementation.

**Classes/functions to test:**
- `EthicalDriftVector` dataclass
- `AgentBaseline` dataclass
- `compute_ethical_drift()` - Main computation
- `get_agent_baseline()` / `clear_baseline()`

**Test cases:**
```python
def test_drift_vector_norm():
    """Verify L2 norm calculation"""

def test_drift_vector_clipping():
    """Components should be clipped to [0, 1]"""

def test_drift_vector_to_list():
    """Conversion to list for dynamics compatibility"""

def test_baseline_ema_update():
    """EMA should smooth values correctly"""

def test_baseline_decision_consistency():
    """Decision stability tracking"""

def test_compute_ethical_drift_integration():
    """Full drift computation from baseline and signals"""
```

### 5. `governance_core/phase_aware.py` (0% coverage)
Phase detection and adaptive thresholds.

**Functions to test:**
- `detect_phase()` - Exploration vs integration
- `get_phase_detection_details()` - Transparency logging
- `get_phase_aware_thresholds()` - Context-appropriate thresholds
- `evaluate_health_with_phase()` - Health assessment
- `make_decision_with_phase()` - Governance decision

**Test cases:**
```python
def test_detect_phase_exploration():
    """I growing + S declining + high complexity = exploration"""

def test_detect_phase_integration():
    """Stable state = integration"""

def test_detect_phase_insufficient_history():
    """< window+1 samples should default to integration"""

def test_exploration_thresholds_more_forgiving():
    """Exploration phase should have lower coherence requirements"""

def test_make_decision_void_always_pauses():
    """void_active=True should always return pause"""

def test_make_decision_critical_coherence():
    """Below critical coherence should pause"""
```

### 6. `governance_core/parameters.py` (partial coverage)

**Functions to test:**
- `get_i_dynamics_mode()` - Environment variable parsing
- `get_params_profile_name()` - Profile selection
- `get_active_params()` - JSON override handling

**Test cases:**
```python
def test_get_i_dynamics_mode_default():
    """Default should be 'logistic'"""

def test_get_active_params_json_override(monkeypatch):
    """UNITARES_PARAMS_JSON should override specific fields"""

def test_get_active_params_invalid_json():
    """Invalid JSON should fall back to base params"""
```

### 7. `governance_core/utils.py` (0% coverage but simple)

```python
def test_clip_within_bounds():
def test_clip_below_min():
def test_clip_above_max():
def test_drift_norm_empty():
def test_drift_norm_pythagorean():
```

## Test Style Guidelines

1. **Use pytest** - existing tests use pytest
2. **Fixtures for common setup**:
```python
@pytest.fixture
def default_state():
    return State(E=0.7, I=0.8, S=0.2, V=0.0)

@pytest.fixture
def default_theta():
    return Theta(C1=1.0, eta1=0.3)

@pytest.fixture
def default_params():
    return DynamicsParams()
```

3. **Parameterized tests for boundaries**:
```python
@pytest.mark.parametrize("E,I,S,V", [
    (0.0, 0.5, 0.5, 0.0),  # E at min
    (1.0, 0.5, 0.5, 0.0),  # E at max
    (0.5, 0.0, 0.5, 0.0),  # I at min
    (0.5, 1.0, 0.5, 0.0),  # I at max
])
def test_dynamics_at_boundaries(E, I, S, V):
    ...
```

4. **Property-based tests for invariants**:
```python
from hypothesis import given, strategies as st

@given(st.floats(0, 1), st.floats(0, 1), st.floats(0, 2), st.floats(-2, 2))
def test_dynamics_preserves_bounds(E, I, S, V):
    state = State(E=E, I=I, S=S, V=V)
    new_state = compute_dynamics(state, [0.0], DEFAULT_THETA, DEFAULT_PARAMS)
    assert 0 <= new_state.E <= 1
    assert 0 <= new_state.I <= 1
    assert 0 <= new_state.S <= 2
    assert -2 <= new_state.V <= 2
```

## Running Tests

```bash
cd /Users/cirwel/projects/governance-mcp-v1

# Run with coverage
pytest tests/ --cov=governance_core --cov-report=html

# Run specific file
pytest tests/test_governance_core_comprehensive.py -v

# Run with hypothesis (property tests)
pytest tests/ --hypothesis-show-statistics
```

## File to Create

Create `tests/test_governance_core_comprehensive.py` with all the test cases above.

## Success Criteria

1. All functions in `governance_core/` have at least one test
2. Coverage reaches 80%+
3. All edge cases (boundaries, zero values, high values) covered
4. Property-based tests for invariants
5. Tests run in < 30 seconds

## Notes for Agent

- The math is well-documented in docstrings - use them
- Check the existing `tests/test_governance_core.py` for style reference
- Don't mock the core math - test real computations
- Focus on behavior, not implementation details
- Add regression tests for any bugs found
