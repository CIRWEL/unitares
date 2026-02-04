"""
Comprehensive unit tests for governance_core module.

Target: 80%+ coverage with meaningful tests for all core functions.
"""

import pytest
import math
import os
import json
from typing import List

# Hypothesis is optional - use if available, skip property tests if not
try:
    from hypothesis import given, strategies as st
    from hypothesis import assume
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False
    # Create dummy decorator if hypothesis not available
    def given(*args, **kwargs):
        def decorator(func):
            return pytest.mark.skip(reason="hypothesis not installed")(func)
        return decorator
    st = None

from governance_core import (
    State, DynamicsParams, Theta, Weights,
    compute_dynamics, step_state,
    coherence, lambda1, lambda2,
    phi_objective, verdict_from_phi,
    clip, drift_norm,
    DEFAULT_PARAMS, DEFAULT_WEIGHTS, DEFAULT_THETA, DEFAULT_STATE,
    EthicalDriftVector, AgentBaseline, compute_ethical_drift,
    get_agent_baseline, clear_baseline,
)
from governance_core.dynamics import (
    compute_equilibrium, estimate_convergence, check_basin, compute_saturation_diagnostics,
)
from governance_core.phase_aware import (
    detect_phase, get_phase_detection_details,
    get_phase_aware_thresholds, evaluate_health_with_phase,
    make_decision_with_phase, Phase,
)
from governance_core.parameters import (
    get_i_dynamics_mode, get_params_profile_name, get_active_params,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def default_state():
    """Default state for testing."""
    return State(E=0.7, I=0.8, S=0.2, V=0.0)


@pytest.fixture
def default_theta():
    """Default theta for testing."""
    return Theta(C1=1.0, eta1=0.3)


@pytest.fixture
def default_params():
    """Default dynamics parameters."""
    return DynamicsParams()


@pytest.fixture
def default_weights():
    """Default weights for scoring."""
    return DEFAULT_WEIGHTS


# ============================================================================
# 1. DYNAMICS.PY TESTS
# ============================================================================

class TestDynamics:
    """Tests for dynamics.py - core EISV differential equations."""

    def test_compute_dynamics_from_default_state(self, default_state, default_theta, default_params):
        """Starting from DEFAULT_STATE, one step should produce valid EISV."""
        delta_eta = [0.1, 0.0, -0.05]
        new_state = compute_dynamics(
            state=default_state,
            delta_eta=delta_eta,
            theta=default_theta,
            params=default_params,
            dt=0.1,
        )
        
        # State should have changed
        assert new_state != default_state
        
        # State should remain in bounds
        assert 0.0 <= new_state.E <= 1.0
        assert 0.0 <= new_state.I <= 1.0
        assert 0.0 <= new_state.S <= 2.0
        assert -2.0 <= new_state.V <= 2.0

    def test_dynamics_preserves_bounds_manual(self):
        """E, I, S, V should stay within physical bounds after any step (manual test cases)."""
        test_cases = [
            (0.0, 0.5, 0.5, 0.0, [0.1]),
            (1.0, 0.5, 0.5, 0.0, [0.1]),
            (0.5, 0.0, 0.5, 0.0, [0.1]),
            (0.5, 1.0, 0.5, 0.0, [0.1]),
            (0.5, 0.5, 0.0, 0.0, [0.1]),
            (0.5, 0.5, 2.0, 0.0, [0.1]),
            (0.5, 0.5, 0.5, -2.0, [0.1]),
            (0.5, 0.5, 0.5, 2.0, [0.1]),
        ]
        
        for E, I, S, V, delta_eta in test_cases:
            state = State(E=E, I=I, S=S, V=V)
            new_state = compute_dynamics(
                state=state,
                delta_eta=delta_eta,
                theta=DEFAULT_THETA,
                params=DEFAULT_PARAMS,
                dt=0.1,
            )
            
            assert 0.0 <= new_state.E <= 1.0
            assert 0.0 <= new_state.I <= 1.0
            assert 0.0 <= new_state.S <= 2.0
            assert -2.0 <= new_state.V <= 2.0
    
    @pytest.mark.skipif(not HAS_HYPOTHESIS, reason="hypothesis not installed")
    def test_dynamics_preserves_bounds_property(self):
        """Property-based test for dynamics bounds preservation."""
        if not HAS_HYPOTHESIS:
            pytest.skip("hypothesis not installed")
        
        @given(
            st.floats(0, 1),  # E
            st.floats(0, 1),  # I
            st.floats(0, 2),  # S
            st.floats(-2, 2),  # V
            st.lists(st.floats(-1, 1), min_size=1, max_size=4),  # delta_eta
        )
        def _test(E, I, S, V, delta_eta):
            state = State(E=E, I=I, S=S, V=V)
            new_state = compute_dynamics(
                state=state,
                delta_eta=delta_eta,
                theta=DEFAULT_THETA,
                params=DEFAULT_PARAMS,
                dt=0.1,
            )
            
            assert 0.0 <= new_state.E <= 1.0
            assert 0.0 <= new_state.I <= 1.0
            assert 0.0 <= new_state.S <= 2.0
            assert -2.0 <= new_state.V <= 2.0
        
        _test()

    def test_dynamics_with_zero_drift(self, default_state, default_theta, default_params):
        """With no ethical drift, system should relax toward equilibrium."""
        delta_eta = [0.0]
        
        # Run multiple steps
        state = default_state
        for _ in range(10):
            state = compute_dynamics(
                state=state,
                delta_eta=delta_eta,
                theta=default_theta,
                params=default_params,
                dt=0.1,
            )
        
        # System should be moving toward equilibrium (E ≈ I)
        # V should be small (E-I imbalance reduced)
        assert abs(state.V) < 0.5  # Should be closer to equilibrium

    def test_dynamics_with_high_drift(self, default_state, default_theta, default_params):
        """High ethical drift should increase S (entropy)."""
        delta_eta_low = [0.1]
        delta_eta_high = [0.8, 0.7, 0.9]
        
        state_low = compute_dynamics(
            state=default_state,
            delta_eta=delta_eta_low,
            theta=default_theta,
            params=default_params,
            dt=0.1,
        )
        
        state_high = compute_dynamics(
            state=default_state,
            delta_eta=delta_eta_high,
            theta=default_theta,
            params=default_params,
            dt=0.1,
        )
        
        # High drift should increase S more than low drift
        assert state_high.S >= state_low.S

    def test_dynamics_complexity_affects_entropy(self, default_state, default_theta, default_params):
        """Higher complexity should increase S via beta_complexity term."""
        delta_eta = [0.1]
        
        state_low_complexity = compute_dynamics(
            state=default_state,
            delta_eta=delta_eta,
            theta=default_theta,
            params=default_params,
            dt=0.1,
            complexity=0.2,
        )
        
        state_high_complexity = compute_dynamics(
            state=default_state,
            delta_eta=delta_eta,
            theta=default_theta,
            params=default_params,
            dt=0.1,
            complexity=0.9,
        )
        
        # Higher complexity should increase S
        assert state_high_complexity.S >= state_low_complexity.S

    def test_dynamics_v_accumulates_ei_imbalance(self, default_state, default_theta, default_params):
        """V should accumulate when E != I."""
        # Start with E > I
        state = State(E=0.9, I=0.5, S=0.2, V=0.0)
        delta_eta = [0.0]
        
        new_state = compute_dynamics(
            state=state,
            delta_eta=delta_eta,
            theta=default_theta,
            params=default_params,
            dt=0.1,
        )
        
        # V should increase when E > I (positive imbalance)
        assert new_state.V > state.V

    @pytest.mark.parametrize("E,I,S,V", [
        (0.0, 0.5, 0.5, 0.0),  # E at min
        (1.0, 0.5, 0.5, 0.0),  # E at max
        (0.5, 0.0, 0.5, 0.0),  # I at min
        (0.5, 1.0, 0.5, 0.0),  # I at max
        (0.5, 0.5, 0.0, 0.0),  # S at min
        (0.5, 0.5, 2.0, 0.0),  # S at max
        (0.5, 0.5, 0.5, -2.0),  # V at min
        (0.5, 0.5, 0.5, 2.0),  # V at max
    ])
    def test_dynamics_at_boundary_states(self, E, I, S, V, default_theta, default_params):
        """Test dynamics when E=0, I=1, S=0, etc."""
        state = State(E=E, I=I, S=S, V=V)
        delta_eta = [0.1]
        
        new_state = compute_dynamics(
            state=state,
            delta_eta=delta_eta,
            theta=default_theta,
            params=default_params,
            dt=0.1,
        )
        
        # Should remain in bounds
        assert 0.0 <= new_state.E <= 1.0
        assert 0.0 <= new_state.I <= 1.0
        assert 0.0 <= new_state.S <= 2.0
        assert -2.0 <= new_state.V <= 2.0

    def test_dynamics_numerical_stability(self, default_state, default_theta, default_params):
        """Run 1000 steps, verify no NaN/Inf."""
        state = default_state
        delta_eta = [0.1, 0.05, -0.02]
        
        for _ in range(1000):
            state = compute_dynamics(
                state=state,
                delta_eta=delta_eta,
                theta=default_theta,
                params=default_params,
                dt=0.1,
            )
            
            # Check for NaN/Inf
            assert math.isfinite(state.E)
            assert math.isfinite(state.I)
            assert math.isfinite(state.S)
            assert math.isfinite(state.V)

    def test_step_state_wrapper(self, default_state, default_theta):
        """Test step_state convenience wrapper."""
        new_state = step_state(
            state=default_state,
            theta=default_theta,
            delta_eta=[0.1],
            dt=0.1,
        )
        
        assert new_state != default_state
        assert 0.0 <= new_state.E <= 1.0
        assert 0.0 <= new_state.I <= 1.0

    def test_compute_equilibrium(self, default_params):
        """Test equilibrium computation."""
        equilibrium = compute_equilibrium(
            params=default_params,
            theta=DEFAULT_THETA,
            ethical_drift_norm_sq=0.0,
        )
        
        # Equilibrium should be in bounds
        assert 0.0 <= equilibrium.E <= 1.0
        assert 0.0 <= equilibrium.I <= 1.0
        assert 0.0 <= equilibrium.S <= 2.0
        assert -2.0 <= equilibrium.V <= 2.0

    def test_estimate_convergence(self, default_state, default_params):
        """Test convergence estimation."""
        equilibrium = compute_equilibrium(
            params=default_params,
            theta=DEFAULT_THETA,
            ethical_drift_norm_sq=0.0,
        )
        convergence = estimate_convergence(
            current=default_state,
            equilibrium=equilibrium,
            params=default_params,
        )
        
        assert isinstance(convergence, dict)
        assert "distance" in convergence
        assert "time_to_convergence" in convergence
        assert convergence["distance"] >= 0.0

    def test_check_basin(self, default_state):
        """Test basin of attraction check."""
        basin = check_basin(default_state, threshold=0.5)
        assert isinstance(basin, str)
        assert basin in ["high", "low", "boundary"]

    def test_compute_saturation_diagnostics(self, default_state, default_theta, default_params):
        """Test saturation diagnostics."""
        diagnostics = compute_saturation_diagnostics(
            state=default_state,
            theta=default_theta,
            params=default_params,
        )
        
        assert isinstance(diagnostics, dict)
        assert "will_saturate" in diagnostics or "I_current" in diagnostics


# ============================================================================
# 2. COHERENCE.PY TESTS
# ============================================================================

class TestCoherence:
    """Tests for coherence.py - coherence functions."""

    def test_coherence_at_v_zero(self, default_theta, default_params):
        """C(V=0) should equal 0.5 * Cmax."""
        C = coherence(0.0, default_theta, default_params)
        expected = default_params.Cmax * 0.5
        assert abs(C - expected) < 1e-6

    def test_coherence_monotonic_in_v(self, default_theta, default_params):
        """C(V) should increase as V increases."""
        C_low = coherence(-1.0, default_theta, default_params)
        C_zero = coherence(0.0, default_theta, default_params)
        C_high = coherence(1.0, default_theta, default_params)
        
        assert C_low < C_zero < C_high

    def test_coherence_bounds_manual(self, default_theta, default_params):
        """C(V) should be in [0, Cmax] for any V (manual test cases)."""
        test_cases = [-10.0, -5.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 5.0, 10.0]
        for V in test_cases:
            C = coherence(V, default_theta, default_params)
            assert 0.0 <= C <= default_params.Cmax
    
    @pytest.mark.skipif(not HAS_HYPOTHESIS, reason="hypothesis not installed")
    def test_coherence_bounds_property(self, default_theta, default_params):
        """Property-based test for coherence bounds."""
        if not HAS_HYPOTHESIS:
            pytest.skip("hypothesis not installed")
        
        @given(st.floats(-10, 10))
        def _test(V):
            C = coherence(V, default_theta, default_params)
            assert 0.0 <= C <= default_params.Cmax
        
        _test()

    def test_lambda1_eta1_mapping(self, default_params):
        """eta1 in [0.1, 0.5] should map to lambda1 in [0.05, 0.20]."""
        theta_min = Theta(C1=1.0, eta1=0.1)
        theta_max = Theta(C1=1.0, eta1=0.5)
        
        lambda1_min = lambda1(theta_min, default_params)
        lambda1_max = lambda1(theta_max, default_params)
        
        assert 0.05 <= lambda1_min <= 0.20
        assert 0.05 <= lambda1_max <= 0.20
        assert lambda1_max >= lambda1_min

    def test_lambda1_clamping(self, default_params):
        """eta1 outside [0.1, 0.5] should be clamped."""
        theta_below = Theta(C1=1.0, eta1=0.05)
        theta_above = Theta(C1=1.0, eta1=0.6)
        
        lambda1_below = lambda1(theta_below, default_params)
        lambda1_above = lambda1(theta_above, default_params)
        
        # Should be clamped to valid range
        assert 0.05 <= lambda1_below <= 0.20
        assert 0.05 <= lambda1_above <= 0.20

    def test_lambda2(self, default_theta, default_params):
        """Test lambda2 computation."""
        l2 = lambda2(default_theta, default_params)
        assert l2 == default_params.lambda2_base


# ============================================================================
# 3. SCORING.PY TESTS
# ============================================================================

class TestScoring:
    """Tests for scoring.py - phi objective and verdicts."""

    def test_phi_default_healthy_state(self, default_weights):
        """DEFAULT_STATE with zero drift should have positive Φ."""
        phi = phi_objective(
            state=DEFAULT_STATE,
            delta_eta=[0.0],
            weights=default_weights,
        )
        assert phi > 0.0

    def test_phi_high_entropy_penalized(self, default_weights):
        """High S should decrease Φ."""
        state_low_S = State(E=0.7, I=0.8, S=0.2, V=0.0)
        state_high_S = State(E=0.7, I=0.8, S=1.5, V=0.0)
        
        phi_low = phi_objective(state_low_S, [0.0], default_weights)
        phi_high = phi_objective(state_high_S, [0.0], default_weights)
        
        assert phi_low > phi_high

    def test_phi_high_drift_penalized(self, default_state, default_weights):
        """High ethical drift should decrease Φ."""
        phi_low_drift = phi_objective(default_state, [0.1], default_weights)
        phi_high_drift = phi_objective(default_state, [0.8, 0.7], default_weights)
        
        assert phi_low_drift > phi_high_drift

    def test_verdict_safe(self):
        """Φ >= 0.15 should be 'safe'."""
        assert verdict_from_phi(0.15) == "safe"
        assert verdict_from_phi(0.3) == "safe"
        assert verdict_from_phi(1.0) == "safe"

    def test_verdict_caution(self):
        """0.0 <= Φ < 0.15 should be 'caution'."""
        assert verdict_from_phi(0.0) == "caution"
        assert verdict_from_phi(0.1) == "caution"
        assert verdict_from_phi(0.14) == "caution"

    def test_verdict_high_risk(self):
        """Φ < 0.0 should be 'high-risk'."""
        assert verdict_from_phi(-0.1) == "high-risk"
        assert verdict_from_phi(-1.0) == "high-risk"

    def test_verdict_thresholds(self):
        """Verify safe/caution/high-risk thresholds."""
        # Test boundary cases
        assert verdict_from_phi(0.15, safe_threshold=0.15) == "safe"
        assert verdict_from_phi(0.149, safe_threshold=0.15) == "caution"
        assert verdict_from_phi(0.0, caution_threshold=0.0) == "caution"
        assert verdict_from_phi(-0.001, caution_threshold=0.0) == "high-risk"


# ============================================================================
# 4. ETHICAL_DRIFT.PY TESTS
# ============================================================================

class TestEthicalDrift:
    """Tests for ethical_drift.py - concrete drift vector implementation."""

    def test_drift_vector_norm(self):
        """Verify L2 norm calculation."""
        drift = EthicalDriftVector(
            calibration_deviation=0.3,
            complexity_divergence=0.4,
            coherence_deviation=0.0,
            stability_deviation=0.0,
        )
        # 3-4-5 triangle
        assert abs(drift.norm - 0.5) < 1e-6

    def test_drift_vector_clipping(self):
        """Components should be clipped to [0, 1]."""
        drift = EthicalDriftVector(
            calibration_deviation=-0.5,  # Should clip to 0
            complexity_divergence=1.5,    # Should clip to 1
            coherence_deviation=0.3,
            stability_deviation=0.2,
        )
        
        assert drift.calibration_deviation == 0.0
        assert drift.complexity_divergence == 1.0
        assert 0.0 <= drift.coherence_deviation <= 1.0
        assert 0.0 <= drift.stability_deviation <= 1.0

    def test_drift_vector_to_list(self):
        """Conversion to list for dynamics compatibility."""
        drift = EthicalDriftVector(
            calibration_deviation=0.1,
            complexity_divergence=0.2,
            coherence_deviation=0.3,
            stability_deviation=0.4,
        )
        
        drift_list = drift.to_list()
        assert len(drift_list) == 4
        assert drift_list == [0.1, 0.2, 0.3, 0.4]

    def test_drift_vector_zero(self):
        """Test zero drift vector."""
        drift = EthicalDriftVector.zero(agent_id="test")
        assert drift.norm == 0.0
        assert drift.agent_id == "test"

    def test_baseline_ema_update(self):
        """EMA should smooth values correctly."""
        baseline = AgentBaseline(agent_id="test")
        
        # Update with EMA (using update method)
        baseline.update(coherence=0.5, confidence=0.5, complexity=0.5)
        assert baseline.baseline_coherence == 0.5
        
        baseline.update(coherence=0.7)
        # EMA: 0.5 * 0.9 + 0.7 * 0.1 = 0.45 + 0.07 = 0.52 (with alpha=0.1)
        assert abs(baseline.baseline_coherence - 0.52) < 0.01

    def test_baseline_decision_consistency(self):
        """Decision stability tracking."""
        baseline = AgentBaseline(agent_id="test")
        
        # Track decisions
        baseline.update(decision="proceed")
        baseline.update(decision="proceed")
        baseline.update(decision="pause")
        
        # Should have tracked decisions
        assert len(baseline.recent_decisions) >= 3
        assert baseline.decision_consistency >= 0.0

    def test_compute_ethical_drift_integration(self):
        """Full drift computation from baseline and signals."""
        # Create baseline
        baseline = AgentBaseline(agent_id="test")
        baseline.update(coherence=0.7, confidence=0.6, complexity=0.6)
        
        # Compute drift
        drift = compute_ethical_drift(
            agent_id="test",
            baseline=baseline,
            current_coherence=0.6,
            current_confidence=0.7,
            complexity_divergence=0.2,
            calibration_error=0.1,
            decision="proceed",
        )
        
        assert isinstance(drift, EthicalDriftVector)
        assert drift.agent_id == "test"
        assert 0.0 <= drift.norm <= 2.0  # Max norm when all components are 1.0

    def test_get_agent_baseline(self):
        """Test baseline retrieval."""
        baseline = get_agent_baseline("test_agent")
        assert isinstance(baseline, AgentBaseline)
        assert baseline.agent_id == "test_agent"

    def test_clear_baseline(self):
        """Test baseline clearing."""
        # Create baseline
        baseline = get_agent_baseline("test_clear")
        baseline.update(coherence=0.5, confidence=0.6, complexity=0.4)
        
        # Clear it
        clear_baseline("test_clear")
        
        # Get fresh baseline
        fresh_baseline = get_agent_baseline("test_clear")
        assert fresh_baseline.baseline_coherence == 0.5  # Default value


# ============================================================================
# 5. PHASE_AWARE.PY TESTS
# ============================================================================

class TestPhaseAware:
    """Tests for phase_aware.py - phase detection and adaptive thresholds."""

    def test_detect_phase_exploration(self):
        """I growing + S declining + high complexity = exploration."""
        E_history = [0.7] * 10
        # Need stronger growth to trigger exploration (threshold is 0.008 per step)
        I_history = [0.6 + i * 0.015 for i in range(10)]  # Growing faster
        S_history = [0.5 - i * 0.015 for i in range(10)]  # Declining faster
        complexity_history = [0.8] * 10  # High
        
        phase = detect_phase(E_history, I_history, S_history, complexity_history)
        assert phase == Phase.EXPLORATION

    def test_detect_phase_integration(self):
        """Stable state = integration."""
        E_history = [0.7] * 10
        I_history = [0.8] * 10  # Stable
        S_history = [0.2] * 10  # Stable
        complexity_history = [0.3] * 10  # Low
        
        phase = detect_phase(E_history, I_history, S_history, complexity_history)
        assert phase == Phase.INTEGRATION

    def test_detect_phase_insufficient_history(self):
        """< window+1 samples should default to integration."""
        E_history = [0.7] * 3  # Less than window+1 (default window=5)
        I_history = [0.8] * 3
        S_history = [0.2] * 3
        complexity_history = [0.5] * 3
        
        phase = detect_phase(E_history, I_history, S_history, complexity_history, window=5)
        assert phase == Phase.INTEGRATION

    def test_exploration_thresholds_more_forgiving(self):
        """Exploration phase should have lower coherence requirements."""
        thresholds_exploration = get_phase_aware_thresholds("exploration")
        thresholds_integration = get_phase_aware_thresholds("integration")
        
        # Exploration should have lower coherence threshold
        assert thresholds_exploration["coherence_critical"] <= thresholds_integration["coherence_critical"]

    def test_make_decision_void_always_pauses(self):
        """void_active=True should always return pause."""
        decision = make_decision_with_phase(
            risk=0.2,
            coherence=0.9,
            void_active=True,
            phase="integration",
        )
        assert decision["action"] == "pause"

    def test_make_decision_critical_coherence(self):
        """Below critical coherence should pause."""
        thresholds = get_phase_aware_thresholds("integration")
        critical_coherence = thresholds["coherence_critical"]
        
        decision = make_decision_with_phase(
            risk=0.2,
            coherence=critical_coherence - 0.1,  # Below critical
            void_active=False,
            phase="integration",
        )
        assert decision["action"] == "pause"

    def test_get_phase_detection_details(self):
        """Test phase detection details transparency."""
        E_history = [0.7] * 10
        I_history = [0.6 + i * 0.01 for i in range(10)]
        S_history = [0.5 - i * 0.01 for i in range(10)]
        complexity_history = [0.8] * 10
        
        details = get_phase_detection_details(
            E_history, I_history, S_history, complexity_history
        )
        
        assert isinstance(details, dict)
        assert "phase" in details
        assert "signals" in details

    def test_evaluate_health_with_phase(self):
        """Test health evaluation with phase awareness."""
        status, reason = evaluate_health_with_phase(
            coherence=0.7,
            risk=0.2,
            phase="integration",
        )
        
        assert isinstance(status, str)
        assert isinstance(reason, str)
        assert status in ["healthy", "caution", "critical"]


# ============================================================================
# 6. PARAMETERS.PY TESTS
# ============================================================================

class TestParameters:
    """Tests for parameters.py - parameter handling."""

    def test_get_i_dynamics_mode_default(self, monkeypatch):
        """Default should be 'logistic'."""
        # Remove env var if set (correct name: UNITARES_I_DYNAMICS, not _MODE)
        monkeypatch.delenv("UNITARES_I_DYNAMICS", raising=False)
        mode = get_i_dynamics_mode()
        assert mode == "logistic"

    def test_get_i_dynamics_mode_linear(self, monkeypatch):
        """Should return 'linear' when env var set."""
        monkeypatch.setenv("UNITARES_I_DYNAMICS", "linear")
        mode = get_i_dynamics_mode()
        assert mode == "linear"

    def test_get_active_params_json_override(self, monkeypatch, tmp_path):
        """UNITARES_PARAMS_JSON should override specific fields."""
        override_params = {"alpha": 0.5, "beta_E": 0.15}
        json_str = json.dumps(override_params)
        monkeypatch.setenv("UNITARES_PARAMS_JSON", json_str)
        
        params = get_active_params()
        assert params.alpha == 0.5
        assert params.beta_E == 0.15
        # Other params should remain default
        assert params.gamma_E == DEFAULT_PARAMS.gamma_E

    def test_get_active_params_invalid_json(self, monkeypatch):
        """Invalid JSON should fall back to base params."""
        monkeypatch.setenv("UNITARES_PARAMS_JSON", "invalid json {")
        
        params = get_active_params()
        # Should fall back to defaults
        assert params.alpha == DEFAULT_PARAMS.alpha

    def test_get_params_profile_name(self, monkeypatch):
        """Test profile name retrieval."""
        monkeypatch.delenv("UNITARES_PARAMS_PROFILE", raising=False)
        profile = get_params_profile_name()
        assert isinstance(profile, str)


# ============================================================================
# 7. UTILS.PY TESTS
# ============================================================================

class TestUtils:
    """Tests for utils.py - utility functions."""

    def test_clip_within_bounds(self):
        """Test clipping within bounds."""
        assert clip(0.5, 0.0, 1.0) == 0.5

    def test_clip_below_min(self):
        """Test clipping below minimum."""
        assert clip(-0.5, 0.0, 1.0) == 0.0

    def test_clip_above_max(self):
        """Test clipping above maximum."""
        assert clip(1.5, 0.0, 1.0) == 1.0

    def test_drift_norm_empty(self):
        """Test drift norm with empty list."""
        assert drift_norm([]) == 0.0

    def test_drift_norm_pythagorean(self):
        """Test drift norm with pythagorean triple."""
        # 3-4-5 triangle
        assert abs(drift_norm([0.3, 0.4]) - 0.5) < 1e-6

    def test_drift_norm_single_component(self):
        """Test drift norm with single component."""
        assert abs(drift_norm([0.5]) - 0.5) < 1e-6

    def test_drift_norm_multiple_components(self):
        """Test drift norm with multiple components."""
        # 1-1-1-1 → sqrt(4) = 2
        assert abs(drift_norm([1.0, 1.0, 1.0, 1.0]) - 2.0) < 1e-6


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests combining multiple modules."""

    def test_full_dynamics_cycle(self, default_state, default_theta, default_params):
        """Test complete dynamics cycle with drift, coherence, scoring."""
        # Compute drift
        drift = EthicalDriftVector(
            calibration_deviation=0.2,
            complexity_divergence=0.1,
            coherence_deviation=0.15,
            stability_deviation=0.05,
        )
        
        # Compute dynamics
        new_state = compute_dynamics(
            state=default_state,
            delta_eta=drift.to_list(),
            theta=default_theta,
            params=default_params,
            dt=0.1,
        )
        
        # Compute coherence
        C = coherence(new_state.V, default_theta, default_params)
        assert 0.0 <= C <= default_params.Cmax
        
        # Compute phi score
        phi = phi_objective(new_state, drift.to_list(), DEFAULT_WEIGHTS)
        verdict = verdict_from_phi(phi)
        assert verdict in ["safe", "caution", "high-risk"]

    def test_phase_aware_decision_making(self):
        """Test phase-aware decision making with full pipeline."""
        # Simulate history
        E_history = [0.7] * 10
        I_history = [0.6 + i * 0.015 for i in range(10)]  # Stronger growth
        S_history = [0.5 - i * 0.015 for i in range(10)]  # Stronger decline
        complexity_history = [0.8] * 10
        
        # Detect phase
        phase = detect_phase(E_history, I_history, S_history, complexity_history)
        
        # Get thresholds
        thresholds = get_phase_aware_thresholds(phase)
        
        # Compute coherence
        C = coherence(0.0, DEFAULT_THETA, DEFAULT_PARAMS)
        
        # Make decision
        decision = make_decision_with_phase(
            risk=0.2,
            coherence=C,
            void_active=False,
            phase=phase,
        )
        
        assert "action" in decision
        assert decision["action"] in ["proceed", "pause", "caution"]
