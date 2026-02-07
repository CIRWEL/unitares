"""
Tests for src/governance_monitor.py - UNITARESMonitor pure/static methods.

Tests ONLY the pure static methods and pure instance methods that don't
require file I/O, database access, or complex dependency chains.
"""

import pytest
import numpy as np
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.governance_monitor import UNITARESMonitor


# ============================================================================
# compute_update_coherence (static)
# ============================================================================

class TestComputeUpdateCoherence:

    def test_aligned_positive(self):
        """Both E and I increasing → ρ ≈ 1"""
        rho = UNITARESMonitor.compute_update_coherence(0.1, 0.1)
        assert rho > 0.9

    def test_aligned_negative(self):
        """Both E and I decreasing → ρ ≈ 1 (coherent in same direction)"""
        rho = UNITARESMonitor.compute_update_coherence(-0.1, -0.1)
        assert rho > 0.9

    def test_misaligned(self):
        """E increasing, I decreasing → ρ < 0"""
        rho = UNITARESMonitor.compute_update_coherence(0.1, -0.1)
        assert rho < 0

    def test_zero_deltas(self):
        """Both zero → ρ ≈ 0 (epsilon prevents division by zero)"""
        rho = UNITARESMonitor.compute_update_coherence(0.0, 0.0)
        assert -1.0 <= rho <= 1.0

    def test_bounded_output(self):
        """Output always in [-1, 1]"""
        for dE in [-10.0, -0.1, 0.0, 0.1, 10.0]:
            for dI in [-10.0, -0.1, 0.0, 0.1, 10.0]:
                rho = UNITARESMonitor.compute_update_coherence(dE, dI)
                assert -1.0 <= rho <= 1.0

    def test_large_deltas(self):
        """Large but aligned deltas → still high coherence"""
        rho = UNITARESMonitor.compute_update_coherence(100.0, 100.0)
        assert rho > 0.99

    def test_returns_float(self):
        rho = UNITARESMonitor.compute_update_coherence(0.05, 0.03)
        assert isinstance(rho, float)


# ============================================================================
# compute_continuity_energy (static)
# ============================================================================

class TestComputeContinuityEnergy:

    def test_empty_history(self):
        CE = UNITARESMonitor.compute_continuity_energy([])
        assert CE == 0.0

    def test_single_entry(self):
        CE = UNITARESMonitor.compute_continuity_energy([{'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0}])
        assert CE == 0.0

    def test_no_change(self):
        """Identical states → CE ≈ 0"""
        history = [{'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0}] * 5
        CE = UNITARESMonitor.compute_continuity_energy(history)
        assert CE < 0.01

    def test_high_state_change(self):
        """Large state changes → higher CE"""
        history = [
            {'E': 0.1, 'I': 0.1, 'S': 0.1, 'V': 0.0},
            {'E': 0.9, 'I': 0.9, 'S': 0.9, 'V': 0.5},
        ]
        CE = UNITARESMonitor.compute_continuity_energy(history)
        assert CE > 0.1

    def test_decision_flips_increase_CE(self):
        """Decision changes contribute to CE"""
        stable_history = [
            {'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0, 'decision': 'approve'},
            {'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0, 'decision': 'approve'},
        ]
        flipping_history = [
            {'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0, 'decision': 'approve'},
            {'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0, 'decision': 'reject'},
        ]
        CE_stable = UNITARESMonitor.compute_continuity_energy(stable_history)
        CE_flipping = UNITARESMonitor.compute_continuity_energy(flipping_history)
        assert CE_flipping > CE_stable

    def test_window_limits_history(self):
        """Window parameter caps how much history is used"""
        history = [{'E': float(i)/20, 'I': 0.5, 'S': 0.1, 'V': 0.0} for i in range(20)]
        CE_small = UNITARESMonitor.compute_continuity_energy(history, window=3)
        CE_large = UNITARESMonitor.compute_continuity_energy(history, window=20)
        # Both should be valid non-negative
        assert CE_small >= 0.0
        assert CE_large >= 0.0

    def test_returns_float(self):
        history = [
            {'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0},
            {'E': 0.6, 'I': 0.5, 'S': 0.1, 'V': 0.0},
        ]
        CE = UNITARESMonitor.compute_continuity_energy(history)
        assert isinstance(CE, float)

    def test_non_negative(self):
        history = [
            {'E': 0.9, 'I': 0.9, 'S': 0.9, 'V': 0.9},
            {'E': 0.1, 'I': 0.1, 'S': 0.1, 'V': 0.1},
        ]
        CE = UNITARESMonitor.compute_continuity_energy(history)
        assert CE >= 0.0


# ============================================================================
# modulate_gains (static)
# ============================================================================

class TestModulateGains:

    def test_high_coherence_no_reduction(self):
        """rho=1 → gains unchanged"""
        K_p, K_i = UNITARESMonitor.modulate_gains(1.0, 0.5, rho=1.0)
        assert K_p == pytest.approx(1.0)
        assert K_i == pytest.approx(0.5)

    def test_low_coherence_reduces_gains(self):
        """rho=-1 → gains reduced to min_factor"""
        K_p, K_i = UNITARESMonitor.modulate_gains(1.0, 0.5, rho=-1.0)
        assert K_p == pytest.approx(0.5)
        assert K_i == pytest.approx(0.25)

    def test_zero_coherence(self):
        """rho=0, min_factor=0.5 → factor = max(0.5, 0.5) = 0.5"""
        K_p, K_i = UNITARESMonitor.modulate_gains(1.0, 1.0, rho=0.0)
        assert K_p == pytest.approx(0.5)
        assert K_i == pytest.approx(0.5)

    def test_custom_min_factor(self):
        K_p, K_i = UNITARESMonitor.modulate_gains(1.0, 1.0, rho=-1.0, min_factor=0.3)
        assert K_p == pytest.approx(0.3)

    def test_returns_tuple(self):
        result = UNITARESMonitor.modulate_gains(1.0, 0.5, 0.5)
        assert isinstance(result, tuple)
        assert len(result) == 2


# ============================================================================
# get_eisv_labels (static)
# ============================================================================

class TestGetEisvLabels:

    def test_returns_dict(self):
        labels = UNITARESMonitor.get_eisv_labels()
        assert isinstance(labels, dict)

    def test_has_all_dimensions(self):
        labels = UNITARESMonitor.get_eisv_labels()
        for key in ['E', 'I', 'S', 'V']:
            assert key in labels

    def test_each_has_label_and_description(self):
        labels = UNITARESMonitor.get_eisv_labels()
        for key in ['E', 'I', 'S', 'V']:
            assert 'label' in labels[key]
            assert 'description' in labels[key]
            assert 'range' in labels[key]


# ============================================================================
# compute_ethical_drift (instance but pure)
# ============================================================================

class TestComputeEthicalDrift:

    @pytest.fixture
    def monitor(self):
        return UNITARESMonitor("test-agent", load_state=False)

    def test_no_previous(self, monitor):
        """No previous params → drift = 0"""
        drift = monitor.compute_ethical_drift(np.array([0.5, 0.5]), None)
        assert drift == 0.0

    def test_identical_params(self, monitor):
        """Same params → drift = 0"""
        params = np.array([0.5, 0.5, 0.5])
        drift = monitor.compute_ethical_drift(params, params.copy())
        assert drift == 0.0

    def test_different_params(self, monitor):
        """Different params → positive drift"""
        current = np.array([0.5, 0.5])
        prev = np.array([0.3, 0.3])
        drift = monitor.compute_ethical_drift(current, prev)
        assert drift > 0.0

    def test_mismatched_length(self, monitor):
        """Different lengths → drift = 0"""
        drift = monitor.compute_ethical_drift(np.array([0.5]), np.array([0.5, 0.5]))
        assert drift == 0.0

    def test_empty_params(self, monitor):
        """Empty arrays → drift = 0"""
        drift = monitor.compute_ethical_drift(np.array([]), np.array([]))
        assert drift == 0.0

    def test_nan_in_current(self, monitor):
        drift = monitor.compute_ethical_drift(np.array([float('nan'), 0.5]), np.array([0.5, 0.5]))
        assert drift == 0.0

    def test_inf_in_prev(self, monitor):
        drift = monitor.compute_ethical_drift(np.array([0.5, 0.5]), np.array([float('inf'), 0.5]))
        assert drift == 0.0

    def test_returns_float(self, monitor):
        drift = monitor.compute_ethical_drift(np.array([0.5]), np.array([0.3]))
        assert isinstance(drift, float)


# ============================================================================
# compute_parameter_coherence (instance but pure)
# ============================================================================

class TestComputeParameterCoherence:

    @pytest.fixture
    def monitor(self):
        return UNITARESMonitor("test-agent", load_state=False)

    def test_no_previous(self, monitor):
        coh = monitor.compute_parameter_coherence(np.array([0.5]), None)
        assert coh == 1.0

    def test_identical_params(self, monitor):
        params = np.array([0.5, 0.5])
        coh = monitor.compute_parameter_coherence(params, params.copy())
        assert coh == pytest.approx(1.0)

    def test_different_params(self, monitor):
        current = np.array([0.5, 0.5])
        prev = np.array([0.3, 0.3])
        coh = monitor.compute_parameter_coherence(current, prev)
        assert 0.0 < coh < 1.0

    def test_large_change_low_coherence(self, monitor):
        current = np.array([1.0, 1.0])
        prev = np.array([0.0, 0.0])
        coh = monitor.compute_parameter_coherence(current, prev)
        assert coh < 0.5

    def test_mismatched_length(self, monitor):
        coh = monitor.compute_parameter_coherence(np.array([0.5]), np.array([0.5, 0.5]))
        assert coh == 1.0

    def test_empty_params(self, monitor):
        coh = monitor.compute_parameter_coherence(np.array([]), np.array([]))
        assert coh == 1.0

    def test_nan_input(self, monitor):
        coh = monitor.compute_parameter_coherence(np.array([float('nan')]), np.array([0.5]))
        assert coh == 0.5

    def test_bounded_output(self, monitor):
        for _ in range(20):
            current = np.random.rand(5)
            prev = np.random.rand(5)
            coh = monitor.compute_parameter_coherence(current, prev)
            assert 0.0 <= coh <= 1.0

    def test_inf_in_current(self, monitor):
        coh = monitor.compute_parameter_coherence(np.array([float('inf')]), np.array([0.5]))
        assert coh == 0.5

    def test_inf_in_prev(self, monitor):
        coh = monitor.compute_parameter_coherence(np.array([0.5]), np.array([float('inf')]))
        assert coh == 0.5


# ============================================================================
# detect_regime (instance, depends on state)
# ============================================================================

class TestDetectRegime:

    @pytest.fixture
    def monitor(self):
        return UNITARESMonitor("test-regime", load_state=False)

    def test_early_updates_divergence(self, monitor):
        """No history → defaults to DIVERGENCE."""
        monitor.state.S_history = []
        monitor.state.I_history = []
        regime = monitor.detect_regime()
        assert regime == "DIVERGENCE"

    def test_stable_requires_persistence(self, monitor):
        """STABLE needs I>=0.999, S<=0.001 for 3 consecutive calls."""
        monitor.state.unitaires_state.I = 1.0
        monitor.state.unitaires_state.S = 0.0
        monitor.state.S_history = [0.0, 0.0]
        monitor.state.I_history = [1.0, 1.0]
        monitor.state.locked_persistence_count = 0

        # First two calls → not yet STABLE (persistence count < 3)
        r1 = monitor.detect_regime()
        assert r1 != "STABLE"  # count was 0, now 1
        r2 = monitor.detect_regime()
        assert r2 != "STABLE"  # count was 1, now 2
        r3 = monitor.detect_regime()
        assert r3 == "STABLE"  # count was 2, now 3

    def test_stable_resets_on_change(self, monitor):
        """Persistence counter resets when state leaves stable region."""
        monitor.state.unitaires_state.I = 1.0
        monitor.state.unitaires_state.S = 0.0
        monitor.state.S_history = [0.0, 0.0]
        monitor.state.I_history = [1.0, 1.0]
        monitor.state.locked_persistence_count = 2

        # Move out of stable region
        monitor.state.unitaires_state.I = 0.5
        monitor.state.unitaires_state.S = 0.2
        monitor.detect_regime()
        assert monitor.state.locked_persistence_count == 0

    def test_divergence_s_rising_v_elevated(self, monitor):
        """S rising + V elevated → DIVERGENCE."""
        monitor.state.unitaires_state.I = 0.5
        monitor.state.unitaires_state.S = 0.15
        monitor.state.unitaires_state.V = 0.2
        monitor.state.S_history = [0.1, 0.1]
        monitor.state.I_history = [0.5, 0.5]
        regime = monitor.detect_regime()
        assert regime == "DIVERGENCE"

    def test_transition_s_falling_i_increasing(self, monitor):
        """S peaked and falling + I increasing → TRANSITION."""
        monitor.state.unitaires_state.I = 0.6
        monitor.state.unitaires_state.S = 0.05
        monitor.state.unitaires_state.V = 0.01
        monitor.state.S_history = [0.06, 0.07]  # S was higher
        monitor.state.I_history = [0.55, 0.58]  # I was lower
        regime = monitor.detect_regime()
        assert regime == "TRANSITION"

    def test_convergence_s_low_i_high(self, monitor):
        """S low & falling + I high → CONVERGENCE."""
        monitor.state.unitaires_state.I = 0.9
        monitor.state.unitaires_state.S = 0.05
        monitor.state.unitaires_state.V = 0.01
        monitor.state.S_history = [0.06, 0.06]  # S same or higher
        monitor.state.I_history = [0.9, 0.9]
        regime = monitor.detect_regime()
        assert regime == "CONVERGENCE"

    def test_fallback_divergence(self, monitor):
        """When no specific condition matches → DIVERGENCE."""
        monitor.state.unitaires_state.I = 0.5
        monitor.state.unitaires_state.S = 0.05
        monitor.state.unitaires_state.V = 0.01
        # S barely changing, I barely changing, S low but I not high enough
        monitor.state.S_history = [0.05, 0.05]
        monitor.state.I_history = [0.5, 0.5]
        regime = monitor.detect_regime()
        assert regime == "DIVERGENCE"

    def test_index_error_fallback(self, monitor):
        """IndexError in history access → DIVERGENCE."""
        monitor.state.unitaires_state.I = 0.5
        monitor.state.unitaires_state.S = 0.1
        # Has history but sabotage the access
        monitor.state.S_history = [0.1, 0.1]
        monitor.state.I_history = [0.5]  # Length mismatch won't trigger, but 2 items needed
        # Actually need enough history for the check to pass but then fail
        # The length check at line 467 will catch < 2
        monitor.state.I_history = [0.5]
        regime = monitor.detect_regime()
        assert regime == "DIVERGENCE"


# ============================================================================
# coherence_function (instance, delegates to governance_core)
# ============================================================================

class TestCoherenceFunction:

    @pytest.fixture
    def monitor(self):
        return UNITARESMonitor("test-coherence-fn", load_state=False)

    def test_returns_float(self, monitor):
        c = monitor.coherence_function(0.0)
        assert isinstance(c, float)

    def test_bounded(self, monitor):
        for v in [0.0, 0.1, 0.5, 0.9, 1.0]:
            c = monitor.coherence_function(v)
            assert 0.0 <= c <= 1.0

    def test_low_void_high_coherence(self, monitor):
        """Low void → high coherence."""
        c = monitor.coherence_function(0.0)
        assert c >= 0.5

    def test_monotonic_in_void(self, monitor):
        """Coherence is monotonically related to V (C(V) uses sigmoid)."""
        c_0 = monitor.coherence_function(0.0)
        c_05 = monitor.coherence_function(0.5)
        c_1 = monitor.coherence_function(1.0)
        # C(V) is a sigmoid: increases with V (per governance_core)
        assert c_0 <= c_05 <= c_1


# ============================================================================
# compute_ethical_drift additional edge cases
# ============================================================================

class TestComputeEthicalDriftExtended:

    @pytest.fixture
    def monitor(self):
        return UNITARESMonitor("test-drift-ext", load_state=False)

    def test_nan_in_result(self, monitor):
        """NaN/inf in result → returns 0.0."""
        # Very large values that could overflow
        current = np.array([1e300, 1e300])
        prev = np.array([-1e300, -1e300])
        drift = monitor.compute_ethical_drift(current, prev)
        # Should either be 0.0 (inf caught) or a valid float
        assert isinstance(drift, float)
        assert not np.isnan(drift)

    def test_known_drift_value(self, monitor):
        """Known drift: [0.5, 0.5] vs [0.3, 0.3] → ||delta||²/dim = (0.04+0.04)/2 = 0.04."""
        current = np.array([0.5, 0.5])
        prev = np.array([0.3, 0.3])
        drift = monitor.compute_ethical_drift(current, prev)
        assert drift == pytest.approx(0.04)


# ============================================================================
# modulate_gains extended tests
# ============================================================================

class TestModulateGainsExtended:

    def test_positive_rho_partial(self):
        """rho=0.5, min_factor=0.5 → factor = max(0.5, 0.75) = 0.75."""
        K_p, K_i = UNITARESMonitor.modulate_gains(2.0, 1.0, rho=0.5)
        assert K_p == pytest.approx(1.5)
        assert K_i == pytest.approx(0.75)

    def test_rho_beyond_1_clamped(self):
        """rho > 1 (shouldn't happen, but test robustness) → factor capped at max."""
        K_p, K_i = UNITARESMonitor.modulate_gains(1.0, 1.0, rho=2.0)
        # (2.0 + 1) / 2 = 1.5, max(0.5, 1.5) = 1.5 → gains amplified
        assert K_p > 1.0

    def test_zero_gains(self):
        """Zero input gains → zero output regardless of rho."""
        K_p, K_i = UNITARESMonitor.modulate_gains(0.0, 0.0, rho=1.0)
        assert K_p == 0.0
        assert K_i == 0.0


# ============================================================================
# compute_continuity_energy extended tests
# ============================================================================

class TestComputeContinuityEnergyExtended:

    def test_route_field_used(self):
        """Uses 'route' key when 'decision' is absent."""
        history = [
            {'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0, 'route': 'approve'},
            {'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0, 'route': 'reject'},
        ]
        CE = UNITARESMonitor.compute_continuity_energy(history)
        assert CE > 0.0  # Decision change contributes

    def test_mixed_route_decision(self):
        """Handles mix of 'route' and 'decision' keys."""
        history = [
            {'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0, 'route': 'approve'},
            {'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0, 'decision': 'reject'},
        ]
        CE = UNITARESMonitor.compute_continuity_energy(history)
        assert CE > 0.0

    def test_no_decision_keys(self):
        """No route or decision → no decision change contribution."""
        history = [
            {'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0},
            {'E': 0.5, 'I': 0.5, 'S': 0.1, 'V': 0.0},
        ]
        CE = UNITARESMonitor.compute_continuity_energy(history)
        assert CE < 0.01

    def test_custom_alpha_weights(self):
        """Custom alpha weights change relative contributions."""
        history = [
            {'E': 0.1, 'I': 0.5, 'S': 0.1, 'V': 0.0, 'decision': 'approve'},
            {'E': 0.9, 'I': 0.5, 'S': 0.1, 'V': 0.0, 'decision': 'reject'},
        ]
        CE_state_heavy = UNITARESMonitor.compute_continuity_energy(
            history, alpha_state=0.9, alpha_decision=0.1)
        CE_decision_heavy = UNITARESMonitor.compute_continuity_energy(
            history, alpha_state=0.1, alpha_decision=0.9)
        # State change is 0.8 in E, decision flips once
        # state_heavy should weight the E change more
        assert CE_state_heavy != CE_decision_heavy
