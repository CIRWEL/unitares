"""Unit tests for monitor_phi.compute_phi_and_risk task-type adjustment branches.

Scope: the pure-arithmetic risk adjustments in compute_phi_and_risk (src/monitor_phi.py
lines 33-68). Uses a stub monitor so phi_objective/verdict_from_phi run with real
governance_core values; only estimate_risk is controlled.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.monitor_phi import compute_phi_and_risk


def _make_monitor(s_value: float, estimate_risk_return: float) -> MagicMock:
    monitor = MagicMock()
    monitor.state.S = s_value
    monitor.state.unitaires_state = SimpleNamespace(E=0.5, I=0.5, S=s_value, V=0.0)
    monitor.estimate_risk = MagicMock(return_value=estimate_risk_return)
    return monitor


class TestEmptyDeltaEta:
    def test_missing_ethical_drift_defaults_to_zeros(self):
        monitor = _make_monitor(s_value=0.5, estimate_risk_return=0.2)
        phi, verdict, risk, adj, orig = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type="mixed"
        )
        assert risk == 0.2
        assert adj is None

    def test_empty_list_ethical_drift_defaults_to_zeros(self):
        monitor = _make_monitor(s_value=0.5, estimate_risk_return=0.2)
        phi, verdict, risk, adj, orig = compute_phi_and_risk(
            monitor,
            grounded_agent_state={"ethical_drift": []},
            agent_state={},
            task_type="mixed",
        )
        assert adj is None


class TestConvergentTask:
    def test_convergent_s_zero_high_risk_is_reduced(self):
        monitor = _make_monitor(s_value=0.0, estimate_risk_return=0.6)
        phi, verdict, risk, adj, orig = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type="convergent"
        )
        assert orig == 0.6
        assert risk == pytest.approx(0.48)  # max(0.2, 0.6 * 0.8)
        assert adj["applied"] is True
        assert adj["adjustment"] == "reduced"

    def test_convergent_s_zero_low_risk_hits_floor(self):
        monitor = _make_monitor(s_value=0.0, estimate_risk_return=0.31)
        _, _, risk, adj, orig = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type="convergent"
        )
        assert risk == pytest.approx(0.248)  # 0.31 * 0.8 > 0.2
        assert adj is not None

    def test_convergent_s_zero_below_threshold_no_adjustment(self):
        monitor = _make_monitor(s_value=0.0, estimate_risk_return=0.25)
        _, _, risk, adj, _ = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type="convergent"
        )
        assert risk == 0.25
        assert adj is None

    def test_convergent_s_nonzero_no_adjustment(self):
        monitor = _make_monitor(s_value=0.1, estimate_risk_return=0.6)
        _, _, risk, adj, _ = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type="convergent"
        )
        assert risk == 0.6
        assert adj is None


class TestDivergentTask:
    def test_divergent_s_zero_low_risk_is_increased(self):
        monitor = _make_monitor(s_value=0.0, estimate_risk_return=0.3)
        _, _, risk, adj, orig = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type="divergent"
        )
        assert orig == 0.3
        assert risk == pytest.approx(0.345)  # min(0.5, 0.3 * 1.15)
        assert adj["adjustment"] == "increased"

    def test_divergent_s_zero_risk_ceiling_capped(self):
        monitor = _make_monitor(s_value=0.0, estimate_risk_return=0.39)
        _, _, risk, adj, _ = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type="divergent"
        )
        # 0.39 * 1.15 = 0.4485, under 0.5 cap
        assert risk == pytest.approx(0.4485)
        assert adj is not None

    def test_divergent_s_zero_high_risk_no_adjustment(self):
        monitor = _make_monitor(s_value=0.0, estimate_risk_return=0.45)
        _, _, risk, adj, _ = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type="divergent"
        )
        assert risk == 0.45
        assert adj is None


class TestExplorationIntrospection:
    @pytest.mark.parametrize("task_type", ["exploration", "introspection"])
    def test_high_risk_reduced_by_0_08_with_floor_0_45(self, task_type):
        monitor = _make_monitor(s_value=0.3, estimate_risk_return=0.7)
        _, _, risk, adj, orig = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type=task_type
        )
        assert orig == 0.7
        assert risk == pytest.approx(0.62)  # max(0.45, 0.7 - 0.08)
        assert adj["risk_adjusted_by"] == -0.08

    @pytest.mark.parametrize("task_type", ["exploration", "introspection"])
    def test_risk_reduction_respects_floor(self, task_type):
        monitor = _make_monitor(s_value=0.3, estimate_risk_return=0.51)
        _, _, risk, adj, _ = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type=task_type
        )
        assert risk == pytest.approx(0.45)  # 0.51 - 0.08 = 0.43, clamped up to 0.45
        assert adj is not None

    def test_exploration_low_risk_no_adjustment(self):
        monitor = _make_monitor(s_value=0.3, estimate_risk_return=0.4)
        _, _, risk, adj, _ = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type="exploration"
        )
        assert risk == 0.4
        assert adj is None


class TestMixedTaskType:
    def test_mixed_reads_task_type_from_agent_state(self):
        monitor = _make_monitor(s_value=0.0, estimate_risk_return=0.6)
        _, _, risk, adj, _ = compute_phi_and_risk(
            monitor,
            grounded_agent_state={},
            agent_state={"task_type": "convergent"},
            task_type="mixed",
        )
        assert risk == pytest.approx(0.48)
        assert adj is not None

    def test_mixed_defaults_to_mixed_when_agent_state_omits(self):
        monitor = _make_monitor(s_value=0.0, estimate_risk_return=0.6)
        _, _, risk, adj, _ = compute_phi_and_risk(
            monitor, grounded_agent_state={}, agent_state={}, task_type="mixed"
        )
        # "mixed" doesn't match any branch → no adjustment
        assert risk == 0.6
        assert adj is None
