"""Hygiene guard: alert when a channel's bad_rate pins to zero with non-trivial samples."""

import pytest
from src.sequential_calibration import SequentialCalibrationTracker


@pytest.fixture
def tracker(tmp_path):
    return SequentialCalibrationTracker(state_file=tmp_path / "seq_state.json")


class TestPerChannelHealthGuard:
    def test_pinned_when_100_samples_all_correct(self, tracker):
        for _ in range(100):
            tracker.record_exogenous_tactical_outcome(
                confidence=0.6, outcome_correct=True, signal_source="tests",
                persist=False,
            )
        health = tracker.compute_per_channel_health()
        assert health["tests"]["bad_rate_pinned_to_zero"] is True

    def test_not_pinned_when_under_100_samples(self, tracker):
        for _ in range(50):
            tracker.record_exogenous_tactical_outcome(
                confidence=0.6, outcome_correct=True, signal_source="tests",
                persist=False,
            )
        health = tracker.compute_per_channel_health()
        # Below 100 samples threshold — pinned flag must be False even if bad_rate is 0.
        assert health["tests"]["bad_rate_pinned_to_zero"] is False

    def test_not_pinned_when_any_failure(self, tracker):
        for _ in range(99):
            tracker.record_exogenous_tactical_outcome(
                confidence=0.6, outcome_correct=True, signal_source="tasks",
                persist=False,
            )
        tracker.record_exogenous_tactical_outcome(
            confidence=0.6, outcome_correct=False, signal_source="tasks",
            persist=False,
        )
        health = tracker.compute_per_channel_health()
        assert health["tasks"]["bad_rate_pinned_to_zero"] is False
        assert 0.0 < health["tasks"]["bad_rate"] < 0.05
