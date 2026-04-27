"""Direct unit tests on the tactical-truth-channel gate.

Council finding (rev 2 of design doc): _classify_hard_exogenous_signal is
the *real* whitelist — the inline tuple at line 266 only governs the
CalibrationChecker call, not the SequentialCalibrationTracker call.
Both must derive from the same constant.
"""

from src.mcp_handlers.observability.outcome_events import (
    HARD_EXOGENOUS_TYPES,
    _HARD_EXOGENOUS_TYPE_TO_CHANNEL,
    _classify_hard_exogenous_signal,
)


class TestHardExogenousClassification:
    def test_test_passed_classifies_as_tests(self):
        assert _classify_hard_exogenous_signal("test_passed", {}) == "tests"

    def test_test_failed_classifies_as_tests(self):
        assert _classify_hard_exogenous_signal("test_failed", {}) == "tests"

    def test_task_completed_classifies_as_tasks(self):
        assert _classify_hard_exogenous_signal("task_completed", {}) == "tasks"

    def test_task_failed_classifies_as_tasks(self):
        assert _classify_hard_exogenous_signal("task_failed", {}) == "tasks"

    def test_cirs_resonance_returns_none(self):
        # cirs_resonance is a detector output, not a prediction outcome.
        # No stated-confidence anchor → not eligible for tactical calibration.
        assert _classify_hard_exogenous_signal("cirs_resonance", {}) is None

    def test_trajectory_validated_returns_none(self):
        # Strategic-only signal; tactical channel must reject.
        assert _classify_hard_exogenous_signal("trajectory_validated", {}) is None

    def test_detail_key_fallback_still_works(self):
        # Pre-existing behavior: if outcome_type isn't in the whitelist but
        # detail carries a known signal key, return that label.
        assert _classify_hard_exogenous_signal("custom_event", {"tests": True}) == "tests"
        assert _classify_hard_exogenous_signal("custom_event", {"commands": [1]}) == "commands"

    def test_constant_and_routing_dict_agree(self):
        # If they ever drift, that drift IS the bug.
        assert set(_HARD_EXOGENOUS_TYPE_TO_CHANNEL.keys()) == HARD_EXOGENOUS_TYPES
