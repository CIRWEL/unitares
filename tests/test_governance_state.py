"""
Tests for src/governance_state.py - GovernanceState dataclass + interpretation.

Tests pure methods: properties, to_dict, to_dict_with_history, validate,
interpret_state private helpers, and module-level interpret_eisv_quick.

from_dict is tested with mocked governance_core imports.
lambda1 property requires config mock.
"""

import pytest
import numpy as np
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.governance_state import GovernanceState, interpret_eisv_quick


# ============================================================================
# Properties (E, I, S, V)
# ============================================================================

class TestProperties:

    def test_E_property(self):
        gs = GovernanceState()
        assert isinstance(gs.E, float)

    def test_I_property(self):
        gs = GovernanceState()
        assert isinstance(gs.I, float)

    def test_S_property(self):
        gs = GovernanceState()
        assert isinstance(gs.S, float)

    def test_V_property(self):
        gs = GovernanceState()
        assert isinstance(gs.V, float)

    def test_properties_reflect_unitaires_state(self):
        gs = GovernanceState()
        gs.unitaires_state.E = 0.42
        assert gs.E == 0.42


# ============================================================================
# to_dict
# ============================================================================

class TestToDict:

    def test_returns_dict(self):
        gs = GovernanceState()
        d = gs.to_dict()
        assert isinstance(d, dict)

    def test_contains_eisv(self):
        gs = GovernanceState()
        d = gs.to_dict()
        for key in ['E', 'I', 'S', 'V']:
            assert key in d

    def test_contains_metadata(self):
        gs = GovernanceState()
        d = gs.to_dict()
        assert 'coherence' in d
        assert 'time' in d
        assert 'update_count' in d

    def test_values_are_native_types(self):
        gs = GovernanceState()
        d = gs.to_dict()
        assert isinstance(d['E'], float)
        assert isinstance(d['void_active'], bool)
        assert isinstance(d['update_count'], int)

    def test_lambda1_in_dict(self):
        gs = GovernanceState()
        d = gs.to_dict()
        assert 'lambda1' in d
        assert isinstance(d['lambda1'], float)


# ============================================================================
# to_dict_with_history
# ============================================================================

class TestToDictWithHistory:

    def test_returns_dict(self):
        gs = GovernanceState()
        d = gs.to_dict_with_history()
        assert isinstance(d, dict)

    def test_contains_history_arrays(self):
        gs = GovernanceState()
        d = gs.to_dict_with_history()
        for key in ['E_history', 'I_history', 'S_history', 'V_history',
                     'coherence_history', 'risk_history']:
            assert key in d
            assert isinstance(d[key], list)

    def test_contains_internal_state(self):
        gs = GovernanceState()
        d = gs.to_dict_with_history()
        assert 'unitaires_state' in d
        assert 'unitaires_theta' in d
        assert 'E' in d['unitaires_state']

    def test_history_capping(self):
        gs = GovernanceState()
        gs.E_history = list(range(200))
        d = gs.to_dict_with_history(max_history=50)
        assert len(d['E_history']) == 50
        assert d['E_history'][0] == 150  # last 50

    def test_short_history_not_capped(self):
        gs = GovernanceState()
        gs.E_history = [0.1, 0.2, 0.3]
        d = gs.to_dict_with_history(max_history=100)
        assert len(d['E_history']) == 3

    def test_hck_metrics_included(self):
        gs = GovernanceState()
        gs.rho_history = [0.5, 0.6]
        gs.CE_history = [0.1, 0.2]
        gs.current_rho = 0.7
        d = gs.to_dict_with_history()
        assert d['rho_history'] == [0.5, 0.6]
        assert d['current_rho'] == 0.7

    def test_cirs_metrics_included(self):
        gs = GovernanceState()
        gs.resonance_events = 3
        gs.damping_applied_count = 1
        d = gs.to_dict_with_history()
        assert d['resonance_events'] == 3
        assert d['damping_applied_count'] == 1


# ============================================================================
# from_dict round-trip
# ============================================================================

class TestFromDict:

    def test_round_trip_basic(self):
        """to_dict_with_history -> from_dict should preserve core fields."""
        gs = GovernanceState()
        gs.unitaires_state.E = 0.8
        gs.unitaires_state.I = 0.7
        gs.unitaires_state.S = 0.1
        gs.unitaires_state.V = 0.05
        gs.coherence = 0.9
        gs.time = 42.0
        gs.update_count = 10
        gs.regime = "CONVERGENCE"
        gs.pi_integral = 0.25
        gs.current_rho = 0.6
        gs.resonance_events = 2

        d = gs.to_dict_with_history()
        restored = GovernanceState.from_dict(d)

        assert abs(restored.E - 0.8) < 0.01
        assert abs(restored.I - 0.7) < 0.01
        assert abs(restored.S - 0.1) < 0.01
        assert abs(restored.V - 0.05) < 0.01
        assert restored.time == 42.0
        assert restored.update_count == 10
        assert restored.regime == "CONVERGENCE"
        assert restored.pi_integral == 0.25
        assert restored.current_rho == 0.6
        assert restored.resonance_events == 2

    def test_from_dict_empty(self):
        """from_dict with minimal data should not crash."""
        restored = GovernanceState.from_dict({})
        assert isinstance(restored, GovernanceState)

    def test_from_dict_fallback_eisv(self):
        """Without unitaires_state key, should use top-level E,I,S,V."""
        d = {'E': 0.5, 'I': 0.6, 'S': 0.2, 'V': 0.1}
        restored = GovernanceState.from_dict(d)
        assert abs(restored.E - 0.5) < 0.01
        assert abs(restored.I - 0.6) < 0.01

    def test_from_dict_history_arrays(self):
        d = {
            'E_history': [0.1, 0.2],
            'I_history': [0.3, 0.4],
            'S_history': [0.01, 0.02],
            'V_history': [0.0, 0.05],
            'coherence_history': [0.9, 0.8],
            'risk_history': [0.1, 0.2],
            'decision_history': ['approve', 'approve'],
        }
        restored = GovernanceState.from_dict(d)
        assert restored.E_history == [0.1, 0.2]
        assert restored.decision_history == ['approve', 'approve']


# ============================================================================
# validate
# ============================================================================

class TestValidate:

    def test_default_state_valid(self):
        gs = GovernanceState()
        is_valid, errors = gs.validate()
        assert is_valid is True
        assert errors == []

    def test_E_out_of_bounds(self):
        gs = GovernanceState()
        gs.unitaires_state.E = 1.5
        is_valid, errors = gs.validate()
        assert is_valid is False
        assert any("E out of bounds" in e for e in errors)

    def test_I_out_of_bounds_negative(self):
        gs = GovernanceState()
        gs.unitaires_state.I = -0.1
        is_valid, errors = gs.validate()
        assert is_valid is False
        assert any("I out of bounds" in e for e in errors)

    def test_coherence_out_of_bounds(self):
        gs = GovernanceState()
        gs.coherence = 1.5
        is_valid, errors = gs.validate()
        assert is_valid is False
        assert any("Coherence out of bounds" in e for e in errors)

    def test_nan_detection(self):
        gs = GovernanceState()
        gs.unitaires_state.E = float('nan')
        is_valid, errors = gs.validate()
        assert is_valid is False
        assert any("NaN" in e for e in errors)

    def test_inf_detection(self):
        gs = GovernanceState()
        gs.unitaires_state.S = float('inf')
        is_valid, errors = gs.validate()
        assert is_valid is False
        assert any("Inf" in e for e in errors)

    def test_history_length_mismatch(self):
        gs = GovernanceState()
        gs.E_history = [0.1] * 10
        gs.I_history = [0.2] * 10
        gs.S_history = [0.3] * 10
        gs.V_history = [0.4] * 10
        gs.coherence_history = [0.5] * 10
        gs.risk_history = [0.6] * 5  # Mismatch > 1
        is_valid, errors = gs.validate()
        assert is_valid is False
        assert any("History length mismatch" in e for e in errors)

    def test_history_minor_mismatch_ok(self):
        """1 entry difference is tolerated."""
        gs = GovernanceState()
        gs.E_history = [0.1] * 10
        gs.I_history = [0.2] * 10
        gs.S_history = [0.3] * 10
        gs.V_history = [0.4] * 10
        gs.coherence_history = [0.5] * 10
        gs.risk_history = [0.6] * 9  # Only 1 off
        is_valid, errors = gs.validate()
        assert is_valid is True


# ============================================================================
# _interpret_health
# ============================================================================

class TestInterpretHealth:

    def test_critical(self):
        gs = GovernanceState()
        assert gs._interpret_health(0.5, 0.8) == "critical"

    def test_at_risk(self):
        gs = GovernanceState()
        assert gs._interpret_health(0.5, 0.6) == "at_risk"

    def test_unstable(self):
        gs = GovernanceState()
        assert gs._interpret_health(0.2, 0.2) == "unstable"

    def test_healthy(self):
        gs = GovernanceState()
        assert gs._interpret_health(0.8, 0.1) == "healthy"

    def test_moderate(self):
        gs = GovernanceState()
        assert gs._interpret_health(0.5, 0.4) == "moderate"


# ============================================================================
# _interpret_basin
# ============================================================================

class TestInterpretBasin:

    def test_high_basin(self):
        gs = GovernanceState()
        assert gs._interpret_basin(0.5, 0.7) == "high"

    def test_low_basin(self):
        gs = GovernanceState()
        assert gs._interpret_basin(0.5, 0.3) == "low"

    def test_transitional(self):
        gs = GovernanceState()
        assert gs._interpret_basin(0.5, 0.5) == "transitional"


# ============================================================================
# _interpret_mode
# ============================================================================

class TestInterpretMode:

    def test_collaborating(self):
        gs = GovernanceState()
        mode, _ = gs._interpret_mode(0.8, 0.8, 0.5)
        assert mode == "collaborating"

    def test_building_alone(self):
        gs = GovernanceState()
        mode, _ = gs._interpret_mode(0.8, 0.8, 0.1)
        assert mode == "building_alone"

    def test_stalled(self):
        gs = GovernanceState()
        mode, _ = gs._interpret_mode(0.1, 0.1, 0.1)
        assert mode == "stalled"

    def test_exploring_alone(self):
        gs = GovernanceState()
        mode, _ = gs._interpret_mode(0.8, 0.1, 0.1)
        assert mode == "exploring_alone"

    def test_borderline_detection(self):
        gs = GovernanceState()
        mode, borderline = gs._interpret_mode(0.5, 0.5, 0.3)  # All near thresholds
        assert len(borderline) > 0

    def test_hysteresis_with_prev_mode(self):
        gs = GovernanceState()
        # When prev_mode was "building_alone", I threshold shifts
        mode1, _ = gs._interpret_mode(0.6, 0.48, 0.1, prev_mode="building_alone")
        mode2, _ = gs._interpret_mode(0.6, 0.48, 0.1, prev_mode=None)
        # With hysteresis, I=0.48 might stay "high" if previously building
        assert isinstance(mode1, str)
        assert isinstance(mode2, str)


# ============================================================================
# _interpret_trajectory
# ============================================================================

class TestInterpretTrajectory:

    def test_improving(self):
        gs = GovernanceState()
        gs.unitaires_state.V = 0.2
        assert gs._interpret_trajectory() == "improving"

    def test_declining(self):
        gs = GovernanceState()
        gs.unitaires_state.V = -0.2
        assert gs._interpret_trajectory() == "declining"

    def test_stable(self):
        gs = GovernanceState()
        gs.unitaires_state.V = 0.05
        assert gs._interpret_trajectory() == "stable"

    def test_stuck(self):
        gs = GovernanceState()
        gs.unitaires_state.V = 0.0
        gs.decision_history = ["pause", "reflect", "pause", "reflect", "pause"]
        assert gs._interpret_trajectory() == "stuck"


# ============================================================================
# _estimate_risk_simple
# ============================================================================

class TestEstimateRiskSimple:

    def test_returns_float(self):
        gs = GovernanceState()
        risk = gs._estimate_risk_simple()
        assert isinstance(risk, float)

    def test_bounded(self):
        gs = GovernanceState()
        risk = gs._estimate_risk_simple()
        assert 0.0 <= risk <= 1.0

    def test_low_risk_state(self):
        gs = GovernanceState()
        gs.unitaires_state.S = 0.0
        gs.unitaires_state.V = 0.0
        gs.coherence = 1.0
        risk = gs._estimate_risk_simple()
        assert risk < 0.1

    def test_high_risk_state(self):
        gs = GovernanceState()
        gs.unitaires_state.S = 1.0
        gs.unitaires_state.V = 1.0
        gs.coherence = 0.0
        risk = gs._estimate_risk_simple()
        assert risk > 0.5


# ============================================================================
# _generate_guidance
# ============================================================================

class TestGenerateGuidance:

    def test_critical_health(self):
        gs = GovernanceState()
        g = gs._generate_guidance("critical", "high", "collaborating", "stable", "mixed", {})
        assert g is not None
        assert "circuit breaker" in g.lower() or "pause" in g.lower()

    def test_declining_trajectory(self):
        gs = GovernanceState()
        g = gs._generate_guidance("moderate", "high", "building_alone", "declining", "mixed", {})
        assert g is not None
        assert "negative" in g.lower() or "simplify" in g.lower()

    def test_stuck_trajectory(self):
        gs = GovernanceState()
        g = gs._generate_guidance("moderate", "high", "building_alone", "stuck", "mixed", {})
        assert g is not None
        assert "pauses" in g.lower() or "different" in g.lower()

    def test_stalled_mode(self):
        gs = GovernanceState()
        g = gs._generate_guidance("moderate", "low", "stalled", "stable", "mixed", {})
        assert g is not None

    def test_healthy_productive_no_guidance(self):
        gs = GovernanceState()
        g = gs._generate_guidance("healthy", "high", "building_alone", "stable", "mixed", {})
        assert g is None

    def test_borderline_guidance(self):
        gs = GovernanceState()
        borderline = {"E": {"value": 0.51, "threshold": 0.5, "status": "high",
                            "note": "Near threshold"}}
        g = gs._generate_guidance("moderate", "high", "collaborating", "stable", "mixed", borderline)
        assert g is not None
        assert "borderline" in g.lower()


# ============================================================================
# interpret_state (integration of private methods)
# ============================================================================

class TestInterpretState:

    def test_returns_dict(self):
        gs = GovernanceState()
        result = gs.interpret_state(risk_score=0.2)
        assert isinstance(result, dict)

    def test_contains_expected_keys(self):
        gs = GovernanceState()
        result = gs.interpret_state(risk_score=0.1)
        for key in ['health', 'basin', 'mode', 'trajectory', 'guidance', 'borderline']:
            assert key in result

    def test_auto_risk_estimation(self):
        """Without risk_score, should compute internally."""
        gs = GovernanceState()
        result = gs.interpret_state()
        assert 'health' in result


# ============================================================================
# interpret_eisv_quick (module-level)
# ============================================================================

class TestInterpretEisvQuick:

    def test_returns_dict(self):
        result = interpret_eisv_quick(0.5, 0.5, 0.2, 0.1)
        assert isinstance(result, dict)

    def test_contains_expected_keys(self):
        result = interpret_eisv_quick(0.5, 0.5, 0.2, 0.1)
        for key in ['health', 'basin', 'mode', 'summary']:
            assert key in result

    def test_high_basin(self):
        result = interpret_eisv_quick(0.5, 0.8, 0.1, 0.0)
        assert result['basin'] == "high"

    def test_low_basin(self):
        result = interpret_eisv_quick(0.5, 0.2, 0.1, 0.0)
        assert result['basin'] == "low"

    def test_transitional_basin(self):
        result = interpret_eisv_quick(0.5, 0.5, 0.1, 0.0)
        assert result['basin'] == "transitional"

    def test_productive_mode(self):
        result = interpret_eisv_quick(0.8, 0.8, 0.1, 0.0)
        assert result['mode'] == "productive"

    def test_productive_social_mode(self):
        result = interpret_eisv_quick(0.8, 0.8, 0.5, 0.0)
        assert result['mode'] == "productive_social"

    def test_exploring_mode(self):
        result = interpret_eisv_quick(0.8, 0.2, 0.1, 0.0)
        assert result['mode'] == "exploring"

    def test_executing_mode(self):
        result = interpret_eisv_quick(0.2, 0.8, 0.1, 0.0)
        assert result['mode'] == "executing"

    def test_stalled_mode(self):
        result = interpret_eisv_quick(0.2, 0.2, 0.1, 0.0)
        assert result['mode'] == "stalled"

    def test_health_from_risk(self):
        result = interpret_eisv_quick(0.5, 0.5, 0.1, 0.0, risk_score=0.8)
        assert result['health'] == "at_risk"

    def test_health_from_coherence(self):
        result = interpret_eisv_quick(0.5, 0.5, 0.1, 0.0, coherence=0.9)
        assert result['health'] == "healthy"

    def test_health_unknown_no_info(self):
        result = interpret_eisv_quick(0.5, 0.5, 0.1, 0.0)
        assert result['health'] == "unknown"

    def test_summary_format(self):
        result = interpret_eisv_quick(0.8, 0.8, 0.1, 0.0, risk_score=0.1)
        assert "|" in result['summary']
        assert "healthy" in result['summary']
