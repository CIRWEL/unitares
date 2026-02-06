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
