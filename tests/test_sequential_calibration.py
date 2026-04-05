"""Tests for the exogenous-only sequential calibration tracker."""

from src.sequential_calibration import SequentialCalibrationTracker


def test_overconfident_failures_accumulate_positive_evidence(tmp_path):
    tracker = SequentialCalibrationTracker(state_file=tmp_path / "seq_state.json")

    tracker.record_exogenous_tactical_outcome(
        confidence=0.9,
        outcome_correct=False,
        agent_id="agent-a",
        signal_source="tests",
        decision_action="proceed",
        outcome_type="test_failed",
    )
    tracker.record_exogenous_tactical_outcome(
        confidence=0.9,
        outcome_correct=False,
        agent_id="agent-a",
        signal_source="tests",
        decision_action="proceed",
        outcome_type="test_failed",
    )

    metrics = tracker.compute_metrics()
    assert metrics["status"] == "tracking"
    assert metrics["eligible_samples"] == 2
    assert metrics["empirical_accuracy"] == 0.0
    assert metrics["mean_confidence"] == 0.9
    assert metrics["log_evidence"] > 0.0
    assert metrics["capped_alarm"] > 0.0
    assert metrics["signal_sources"]["tests"] == 2


def test_positive_log_is_clamped_for_alarm(tmp_path):
    tracker = SequentialCalibrationTracker(state_file=tmp_path / "seq_state.json")

    tracker.record_exogenous_tactical_outcome(
        confidence=0.9,
        outcome_correct=True,
        agent_id="agent-a",
        signal_source="tests",
        decision_action="proceed",
        outcome_type="test_passed",
    )

    metrics = tracker.compute_metrics()
    assert metrics["eligible_samples"] == 1
    assert metrics["log_evidence"] == 0.0
    assert metrics["capped_alarm"] == 0.0


def test_agent_metrics_are_isolated(tmp_path):
    tracker = SequentialCalibrationTracker(state_file=tmp_path / "seq_state.json")

    tracker.record_exogenous_tactical_outcome(
        confidence=0.9,
        outcome_correct=False,
        agent_id="agent-a",
        signal_source="tests",
        decision_action="proceed",
        outcome_type="test_failed",
    )
    tracker.record_exogenous_tactical_outcome(
        confidence=0.8,
        outcome_correct=True,
        agent_id="agent-b",
        signal_source="lint",
        decision_action="proceed",
        outcome_type="task_completed",
    )

    global_metrics = tracker.compute_metrics()
    a_metrics = tracker.compute_metrics(agent_id="agent-a")
    b_metrics = tracker.compute_metrics(agent_id="agent-b")

    assert global_metrics["eligible_samples"] == 2
    assert a_metrics["eligible_samples"] == 1
    assert b_metrics["eligible_samples"] == 1
    assert a_metrics["empirical_accuracy"] == 0.0
    assert b_metrics["empirical_accuracy"] == 1.0
    assert a_metrics["signal_sources"] == {"tests": 1}
    assert b_metrics["signal_sources"] == {"lint": 1}
