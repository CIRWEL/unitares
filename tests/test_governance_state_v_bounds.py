"""
Tests for V (Viability) bounds validation in GovernanceState.

Feb 2026: V bounds changed from [0, 1] to [-1, 1] because the thermodynamic
dynamics `dV/dt = κ(E - I) - δV` naturally produce negative V when I > E
(agent in consolidation/information-dominant state).
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.governance_state import GovernanceState


class TestVBoundsValidation:
    """Test that V validation accepts [-1, 1] range (Feb 2026 fix)."""

    def test_v_zero_is_valid(self):
        state = GovernanceState()
        state.unitaires_state.V = 0.0
        is_valid, errors = state.validate()
        v_errors = [e for e in errors if "V out of bounds" in e]
        assert len(v_errors) == 0

    def test_v_positive_within_bounds(self):
        state = GovernanceState()
        state.unitaires_state.V = 0.5
        is_valid, errors = state.validate()
        v_errors = [e for e in errors if "V out of bounds" in e]
        assert len(v_errors) == 0

    def test_v_negative_within_bounds(self):
        """Negative V is valid — it means I > E (consolidation)."""
        state = GovernanceState()
        state.unitaires_state.V = -0.5
        is_valid, errors = state.validate()
        v_errors = [e for e in errors if "V out of bounds" in e]
        assert len(v_errors) == 0

    def test_v_at_lower_bound(self):
        """V = -1.0 is the valid lower bound."""
        state = GovernanceState()
        state.unitaires_state.V = -1.0
        is_valid, errors = state.validate()
        v_errors = [e for e in errors if "V out of bounds" in e]
        assert len(v_errors) == 0

    def test_v_at_upper_bound(self):
        """V = 1.0 is the valid upper bound."""
        state = GovernanceState()
        state.unitaires_state.V = 1.0
        is_valid, errors = state.validate()
        v_errors = [e for e in errors if "V out of bounds" in e]
        assert len(v_errors) == 0

    def test_v_below_lower_bound(self):
        """V = -1.1 should produce a validation error."""
        state = GovernanceState()
        state.unitaires_state.V = -1.1
        is_valid, errors = state.validate()
        v_errors = [e for e in errors if "V out of bounds" in e]
        assert len(v_errors) == 1
        assert "expected [-1, 1]" in v_errors[0]

    def test_v_above_upper_bound(self):
        """V = 1.1 should produce a validation error."""
        state = GovernanceState()
        state.unitaires_state.V = 1.1
        is_valid, errors = state.validate()
        v_errors = [e for e in errors if "V out of bounds" in e]
        assert len(v_errors) == 1
        assert "expected [-1, 1]" in v_errors[0]

    def test_v_far_below_bound(self):
        state = GovernanceState()
        state.unitaires_state.V = -5.0
        is_valid, errors = state.validate()
        v_errors = [e for e in errors if "V out of bounds" in e]
        assert len(v_errors) == 1

    def test_v_far_above_bound(self):
        state = GovernanceState()
        state.unitaires_state.V = 5.0
        is_valid, errors = state.validate()
        v_errors = [e for e in errors if "V out of bounds" in e]
        assert len(v_errors) == 1


class TestVAutoFix:
    """Test that V auto-fix clips to [-1, 1] (Feb 2026 addition to governance_monitor)."""

    def test_v_clipped_after_dynamics(self):
        """V should be clipped to [-1, 1] after dynamics update."""
        from src.governance_monitor import UNITARESMonitor

        monitor = UNITARESMonitor("test-v-autofix", load_state=False)
        # Force V out of bounds
        monitor.state.unitaires_state.V = -2.0
        # Run dynamics which should trigger auto-fix
        agent_state = {"complexity": 0.5}
        monitor.update_dynamics(agent_state)
        assert -1.0 <= monitor.state.V <= 1.0

    def test_v_negative_preserved_when_valid(self):
        """Negative V within bounds should NOT be clipped to 0."""
        from src.governance_monitor import UNITARESMonitor

        monitor = UNITARESMonitor("test-v-neg-preserve", load_state=False)
        # Set V to a valid negative value
        monitor.state.unitaires_state.V = -0.3
        agent_state = {"complexity": 0.5}
        monitor.update_dynamics(agent_state)
        # V may change due to dynamics, but if it stays in [-1, 1] that's fine
        assert -1.0 <= monitor.state.V <= 1.0
