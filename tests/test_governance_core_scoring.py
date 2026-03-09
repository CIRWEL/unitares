"""
Tests for governance_core/utils.py and governance_core/scoring.py.

Pure math functions with zero external dependencies - very low-hanging fruit.

Covers:
- clip() - boundary clamping
- drift_norm() - L2 norm of ethical drift vector
- phi_objective() - UNITARES objective function Φ
- verdict_from_phi() - Φ → verdict classification
"""

import math
import pytest

from governance_core.utils import clip, drift_norm
from governance_core.dynamics import State
from governance_core.parameters import Weights, DEFAULT_WEIGHTS
from governance_core.scoring import phi_objective, verdict_from_phi


# ============================================================================
# clip()
# ============================================================================

class TestClip:

    def test_within_range(self):
        assert clip(0.5, 0.0, 1.0) == 0.5

    def test_below_lower(self):
        assert clip(-0.5, 0.0, 1.0) == 0.0

    def test_above_upper(self):
        assert clip(1.5, 0.0, 1.0) == 1.0

    def test_at_lower_bound(self):
        assert clip(0.0, 0.0, 1.0) == 0.0

    def test_at_upper_bound(self):
        assert clip(1.0, 0.0, 1.0) == 1.0

    def test_negative_range(self):
        assert clip(0.0, -2.0, -1.0) == -1.0

    def test_equal_bounds(self):
        assert clip(5.0, 3.0, 3.0) == 3.0


# ============================================================================
# drift_norm()
# ============================================================================

class TestDriftNorm:

    def test_empty_list(self):
        assert drift_norm([]) == 0.0

    def test_single_element(self):
        assert drift_norm([3.0]) == 3.0

    def test_two_elements(self):
        result = drift_norm([3.0, 4.0])
        assert result == pytest.approx(5.0)

    def test_zeros(self):
        assert drift_norm([0.0, 0.0, 0.0]) == 0.0

    def test_unit_vector(self):
        val = 1.0 / math.sqrt(3)
        result = drift_norm([val, val, val])
        assert result == pytest.approx(1.0)

    def test_negative_values(self):
        # L2 norm squares, so sign doesn't matter
        assert drift_norm([-3.0, 4.0]) == pytest.approx(5.0)


# ============================================================================
# verdict_from_phi()
# ============================================================================

class TestVerdictFromPhi:

    def test_safe(self):
        assert verdict_from_phi(0.5) == "safe"

    def test_safe_at_threshold(self):
        assert verdict_from_phi(0.22) == "safe"

    def test_caution(self):
        assert verdict_from_phi(0.15) == "caution"

    def test_caution_at_zero(self):
        assert verdict_from_phi(0.0) == "caution"

    def test_high_risk(self):
        assert verdict_from_phi(-0.1) == "high-risk"

    def test_custom_thresholds(self):
        # With custom thresholds
        assert verdict_from_phi(0.5, safe_threshold=0.6) == "caution"
        assert verdict_from_phi(-0.5, caution_threshold=-0.3) == "high-risk"
        assert verdict_from_phi(-0.2, caution_threshold=-0.3) == "caution"


# ============================================================================
# phi_objective()
# ============================================================================

class TestPhiObjective:

    def _state(self, E=0.7, I=0.8, S=0.2, V=0.0):
        return State(E=E, I=I, S=S, V=V)

    def test_healthy_state(self):
        """Healthy state should produce positive Φ."""
        state = self._state(E=0.7, I=0.8, S=0.2, V=0.0)
        phi = phi_objective(state, delta_eta=[])
        assert phi > 0

    def test_unhealthy_state(self):
        """High S, low I state should produce low Φ."""
        state = self._state(E=0.3, I=0.2, S=1.5, V=1.0)
        phi = phi_objective(state, delta_eta=[0.5, 0.5])
        assert phi < 0

    def test_zero_state(self):
        """All zeros except I should show cost of low integrity."""
        state = self._state(E=0.0, I=0.0, S=0.0, V=0.0)
        phi = phi_objective(state, delta_eta=[])
        # Φ = 0 - 0.5*(1-0) - 0 - 0 - 0 = -0.5
        assert phi == pytest.approx(-0.5)

    def test_perfect_state(self):
        """Perfect state: E=1, I=1, S=0, V=0, no drift."""
        state = self._state(E=1.0, I=1.0, S=0.0, V=0.0)
        phi = phi_objective(state, delta_eta=[])
        # Φ = 0.5*1 - 0.5*(1-1) - 0 - 0 - 0 = 0.5
        assert phi == pytest.approx(0.5)

    def test_drift_penalty(self):
        """Ethical drift should reduce Φ."""
        state = self._state(E=0.7, I=0.8, S=0.2, V=0.0)
        phi_no_drift = phi_objective(state, delta_eta=[])
        phi_with_drift = phi_objective(state, delta_eta=[0.5, 0.5])
        assert phi_with_drift < phi_no_drift

    def test_void_penalty(self):
        """Void (V) should reduce Φ."""
        state_no_void = self._state(E=0.7, I=0.8, S=0.2, V=0.0)
        state_with_void = self._state(E=0.7, I=0.8, S=0.2, V=1.0)
        phi_no_void = phi_objective(state_no_void, delta_eta=[])
        phi_with_void = phi_objective(state_with_void, delta_eta=[])
        assert phi_with_void < phi_no_void

    def test_custom_weights(self):
        """Custom weights should change the result."""
        state = self._state(E=0.5, I=0.5, S=0.5, V=0.5)
        weights_default = DEFAULT_WEIGHTS
        weights_custom = Weights(wE=1.0, wI=0.0, wS=0.0, wV=0.0, wEta=0.0)
        phi_default = phi_objective(state, delta_eta=[], weights=weights_default)
        phi_custom = phi_objective(state, delta_eta=[], weights=weights_custom)
        # Custom: Φ = 1.0*0.5 = 0.5
        assert phi_custom == pytest.approx(0.5)
        assert phi_custom != phi_default

    def test_negative_void(self):
        """Negative V should also be penalized (abs(V))."""
        state_pos = self._state(V=0.5)
        state_neg = self._state(V=-0.5)
        phi_pos = phi_objective(state_pos, delta_eta=[])
        phi_neg = phi_objective(state_neg, delta_eta=[])
        assert phi_pos == pytest.approx(phi_neg)
