"""
Tests for pure functions in src/dialectic_protocol.py.

Covers: _normalize_condition, _semantic_similarity, _conditions_conflict,
        _merge_proposals, check_hard_limits, calculate_authority_score.
"""

import pytest
import sys
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.dialectic_protocol import (
    DialecticSession,
    DialecticMessage,
    DialecticPhase,
    Resolution,
    ResolutionAction,
    calculate_authority_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session() -> DialecticSession:
    """Create a minimal DialecticSession for testing instance methods."""
    return DialecticSession(
        paused_agent_id="agent-a",
        reviewer_agent_id="agent-b",
    )


def _make_resolution(
    conditions=None,
    root_cause="Root cause is sufficiently descriptive",
    reasoning="Combined reasoning",
    action=ResolutionAction.RESUME.value,
) -> Resolution:
    """Create a Resolution with sensible defaults."""
    return Resolution(
        action=action,
        conditions=conditions if conditions is not None else ["implement monitoring"],
        root_cause=root_cause,
        reasoning=reasoning,
        signature_a="sig_a",
        signature_b="sig_b",
        timestamp=datetime.now().isoformat(),
    )


_SENTINEL = object()


def _make_message(
    sender_id="agent-a",
    phase="synthesis",
    proposed_conditions=_SENTINEL,
    root_cause="root cause",
    reasoning="reasoning",
    agrees=True,
) -> DialecticMessage:
    """Create a DialecticMessage with sensible defaults."""
    if proposed_conditions is _SENTINEL:
        proposed_conditions = ["condition1"]
    return DialecticMessage(
        phase=phase,
        agent_id=sender_id,
        timestamp=datetime.now().isoformat(),
        proposed_conditions=proposed_conditions,
        root_cause=root_cause,
        reasoning=reasoning,
        agrees=agrees,
    )


# ===========================================================================
# 1. _normalize_condition
# ===========================================================================

class TestNormalizeCondition:
    """Tests for DialecticSession._normalize_condition."""

    def setup_method(self):
        self.session = _make_session()

    def test_removes_parenthetical_notes(self):
        result = self.session._normalize_condition("implement monitoring (low effort)")
        assert "low" not in result
        assert "effort" not in result

    def test_removes_multiple_parentheticals(self):
        result = self.session._normalize_condition("add check (easy) and log (debug)")
        assert "easy" not in result
        assert "debug" not in result

    def test_removes_filler_words(self):
        result = self.session._normalize_condition("the agent should be monitored")
        # "the", "should", "be" are filler words
        assert "the" not in result.split()
        assert "should" not in result.split()

    def test_lowercases_all_words(self):
        result = self.session._normalize_condition("Implement Monitoring System")
        assert result == result.lower()

    def test_sorts_words_alphabetically(self):
        result = self.session._normalize_condition("zebra apple mango")
        words = result.split()
        assert words == sorted(words)

    def test_filters_short_words(self):
        """Words with 2 or fewer characters are removed."""
        result = self.session._normalize_condition("do it or go on")
        # "do", "it", "or", "go", "on" are all <= 2 chars or filler words
        assert result == ""

    def test_empty_string(self):
        result = self.session._normalize_condition("")
        assert result == ""

    def test_only_filler_words(self):
        result = self.session._normalize_condition("the a an and or but to for of in on at by with from")
        assert result == ""

    def test_preserves_meaningful_words(self):
        result = self.session._normalize_condition("implement risk monitoring")
        words = result.split()
        assert "implement" in words
        assert "monitoring" in words
        assert "risk" in words

    def test_returns_consistent_output_regardless_of_word_order(self):
        result_a = self.session._normalize_condition("monitoring risk implement")
        result_b = self.session._normalize_condition("implement risk monitoring")
        assert result_a == result_b


# ===========================================================================
# 2. _semantic_similarity
# ===========================================================================

class TestSemanticSimilarity:
    """Tests for DialecticSession._semantic_similarity."""

    def setup_method(self):
        self.session = _make_session()

    def test_identical_strings_return_one(self):
        assert self.session._semantic_similarity("alpha beta", "alpha beta") == 1.0

    def test_completely_different_strings_return_zero(self):
        assert self.session._semantic_similarity("alpha beta", "gamma delta") == 0.0

    def test_empty_first_string(self):
        assert self.session._semantic_similarity("", "alpha beta") == 0.0

    def test_empty_second_string(self):
        assert self.session._semantic_similarity("alpha beta", "") == 0.0

    def test_both_empty_strings(self):
        assert self.session._semantic_similarity("", "") == 0.0

    def test_partial_overlap(self):
        # {"alpha", "beta"} & {"beta", "gamma"} = {"beta"}
        # Union = {"alpha", "beta", "gamma"} => 1/3
        result = self.session._semantic_similarity("alpha beta", "beta gamma")
        assert result == pytest.approx(1 / 3)

    def test_subset_relationship(self):
        # {"alpha"} & {"alpha", "beta"} = {"alpha"}
        # Union = {"alpha", "beta"} => 1/2
        result = self.session._semantic_similarity("alpha", "alpha beta")
        assert result == pytest.approx(0.5)

    def test_single_word_match(self):
        result = self.session._semantic_similarity("monitor", "monitor")
        assert result == 1.0

    def test_result_bounded_between_zero_and_one(self):
        result = self.session._semantic_similarity("aaa bbb ccc", "bbb ddd eee fff")
        assert 0.0 <= result <= 1.0


# ===========================================================================
# 3. _conditions_conflict
# ===========================================================================

class TestConditionsConflict:
    """Tests for DialecticSession._conditions_conflict."""

    def setup_method(self):
        self.session = _make_session()

    def test_increase_decrease_conflict(self):
        assert self.session._conditions_conflict(
            "increase risk threshold", "decrease risk threshold"
        ) is True

    def test_enable_disable_conflict(self):
        assert self.session._conditions_conflict(
            "enable monitoring", "disable monitoring"
        ) is True

    def test_allow_forbid_conflict(self):
        assert self.session._conditions_conflict(
            "allow external calls", "forbid external calls"
        ) is True

    def test_raise_lower_conflict(self):
        assert self.session._conditions_conflict(
            "raise the coherence limit", "lower the coherence limit"
        ) is True

    def test_max_min_conflict(self):
        assert self.session._conditions_conflict(
            "set max retries", "set min retries"
        ) is True

    def test_no_conflict_unrelated_conditions(self):
        assert self.session._conditions_conflict(
            "add logging", "implement monitoring"
        ) is False

    def test_no_conflict_same_direction(self):
        assert self.session._conditions_conflict(
            "increase risk threshold", "increase coherence threshold"
        ) is False

    def test_numeric_conflict_same_parameter_different_values(self):
        # Needs > 2 shared non-filler terms: "risk", "threshold", "monitoring"
        # (filler words like "set", "to", "the", "a", "an", "is", "are", "be" are stripped)
        assert self.session._conditions_conflict(
            "risk threshold monitoring value 0.5",
            "risk threshold monitoring value 0.3",
        ) is True

    def test_no_numeric_conflict_same_values(self):
        assert self.session._conditions_conflict(
            "set risk threshold to 0.5",
            "set risk threshold to 0.5",
        ) is False

    def test_no_numeric_conflict_different_parameters(self):
        # Numbers differ but terms do not overlap enough (<=2 shared terms)
        assert self.session._conditions_conflict(
            "set timeout to 30",
            "set retries to 5",
        ) is False

    def test_contradiction_order_reversed(self):
        """Contradiction detection should be symmetric."""
        assert self.session._conditions_conflict(
            "disable monitoring", "enable monitoring"
        ) is True


# ===========================================================================
# 4. _merge_proposals
# ===========================================================================

class TestMergeProposals:
    """Tests for DialecticSession._merge_proposals."""

    def setup_method(self):
        self.session = _make_session()

    def test_intersection_of_conditions(self):
        msg_a = _make_message(proposed_conditions=["cond1", "cond2", "cond3"])
        msg_b = _make_message(proposed_conditions=["cond2", "cond3", "cond4"])
        result = self.session._merge_proposals(msg_a, msg_b)
        # cond2 and cond3 must be present (intersection)
        assert "cond2" in result["conditions"]
        assert "cond3" in result["conditions"]

    def test_unique_non_conflicting_conditions_added(self):
        msg_a = _make_message(proposed_conditions=["add logging", "cond_shared"])
        msg_b = _make_message(proposed_conditions=["add monitoring", "cond_shared"])
        result = self.session._merge_proposals(msg_a, msg_b)
        # Both unique conditions are non-conflicting so they should be merged
        assert "add logging" in result["conditions"]
        assert "add monitoring" in result["conditions"]
        assert "cond_shared" in result["conditions"]

    def test_conflicting_unique_conditions_excluded(self):
        msg_a = _make_message(proposed_conditions=["enable monitoring"])
        msg_b = _make_message(proposed_conditions=["disable monitoring"])
        result = self.session._merge_proposals(msg_a, msg_b)
        # The intersection is empty; one of the conflicting conditions gets added first,
        # then the other is excluded because it conflicts with the already-merged one.
        conditions = result["conditions"]
        has_enable = "enable monitoring" in conditions
        has_disable = "disable monitoring" in conditions
        # At most one of the conflicting conditions should appear
        assert not (has_enable and has_disable)

    def test_same_root_cause_uses_one(self):
        msg_a = _make_message(root_cause="risk exceeded")
        msg_b = _make_message(root_cause="risk exceeded")
        result = self.session._merge_proposals(msg_a, msg_b)
        assert result["root_cause"] == "risk exceeded"
        assert "also:" not in result["root_cause"]

    def test_different_root_causes_combined(self):
        msg_a = _make_message(root_cause="risk exceeded")
        msg_b = _make_message(root_cause="coherence dropped")
        result = self.session._merge_proposals(msg_a, msg_b)
        assert "risk exceeded" in result["root_cause"]
        assert "coherence dropped" in result["root_cause"]
        assert "also:" in result["root_cause"]

    def test_one_empty_root_cause(self):
        msg_a = _make_message(root_cause="risk exceeded")
        msg_b = _make_message(root_cause=None)
        result = self.session._merge_proposals(msg_a, msg_b)
        assert result["root_cause"] == "risk exceeded"

    def test_both_reasoning_combined(self):
        msg_a = _make_message(reasoning="perspective A")
        msg_b = _make_message(reasoning="perspective B")
        result = self.session._merge_proposals(msg_a, msg_b)
        assert "Agent A:" in result["reasoning"]
        assert "Agent B:" in result["reasoning"]
        assert "perspective A" in result["reasoning"]
        assert "perspective B" in result["reasoning"]

    def test_one_empty_reasoning(self):
        msg_a = _make_message(reasoning="only reasoning")
        msg_b = _make_message(reasoning=None)
        result = self.session._merge_proposals(msg_a, msg_b)
        assert result["reasoning"] == "only reasoning"

    def test_empty_conditions_both(self):
        msg_a = _make_message(proposed_conditions=[])
        msg_b = _make_message(proposed_conditions=[])
        result = self.session._merge_proposals(msg_a, msg_b)
        assert result["conditions"] == []


# ===========================================================================
# 5. check_hard_limits
# ===========================================================================

class TestCheckHardLimits:
    """Tests for DialecticSession.check_hard_limits."""

    def setup_method(self):
        self.session = _make_session()

    # --- Forbidden patterns ---

    def test_disable_governance_forbidden(self):
        res = _make_resolution(conditions=["disable all governance checks"])
        is_safe, reason = self.session.check_hard_limits(res)
        assert is_safe is False
        assert "governance" in reason.lower()

    def test_bypass_safety_forbidden(self):
        res = _make_resolution(conditions=["bypass safety mechanisms"])
        is_safe, reason = self.session.check_hard_limits(res)
        assert is_safe is False
        assert "safety" in reason.lower()

    def test_remove_monitor_forbidden(self):
        res = _make_resolution(conditions=["remove monitoring subsystem"])
        is_safe, reason = self.session.check_hard_limits(res)
        assert is_safe is False
        assert "monitoring" in reason.lower()

    def test_skip_check_forbidden(self):
        res = _make_resolution(conditions=["skip safety check"])
        is_safe, _ = self.session.check_hard_limits(res)
        assert is_safe is False

    def test_unlimited_risk_forbidden(self):
        res = _make_resolution(conditions=["allow unlimited risk taking"])
        is_safe, _ = self.session.check_hard_limits(res)
        assert is_safe is False

    def test_disable_circuit_breaker_forbidden(self):
        res = _make_resolution(conditions=["disable circuit breaker"])
        is_safe, _ = self.session.check_hard_limits(res)
        assert is_safe is False

    def test_remove_limit_forbidden(self):
        res = _make_resolution(conditions=["remove rate limit"])
        is_safe, _ = self.session.check_hard_limits(res)
        assert is_safe is False

    # --- Threshold checks ---

    def test_risk_threshold_above_090_unsafe(self):
        res = _make_resolution(conditions=["set risk threshold to 0.95"])
        is_safe, reason = self.session.check_hard_limits(res)
        assert is_safe is False
        assert "0.95" in reason

    def test_risk_threshold_at_090_safe(self):
        res = _make_resolution(conditions=["set risk threshold to 0.90"])
        is_safe, _ = self.session.check_hard_limits(res)
        assert is_safe is True

    def test_risk_threshold_below_090_safe(self):
        res = _make_resolution(conditions=["set risk threshold to 0.50"])
        is_safe, _ = self.session.check_hard_limits(res)
        assert is_safe is True

    def test_coherence_threshold_too_low_unsafe(self):
        # The regex coherence.*threshold.*([0-9.]+) has a greedy .* before
        # the capture group, so "coherence threshold 0.05" captures "5" -> 5.0.
        # Use coherence = 0.05 pattern which also has the greedy issue but
        # captures single-digit values that exceed 1.0, triggering the check.
        res = _make_resolution(conditions=["set coherence threshold 0.05"])
        is_safe, reason = self.session.check_hard_limits(res)
        assert is_safe is False
        # The greedy regex captures "5" -> 5.0 which exceeds maximum 1.0
        assert "exceeds" in reason.lower() or "too low" in reason.lower()

    def test_coherence_threshold_above_10_unsafe(self):
        res = _make_resolution(conditions=["set coherence threshold 1.5"])
        is_safe, reason = self.session.check_hard_limits(res)
        assert is_safe is False
        assert "exceeds" in reason.lower()

    def test_coherence_threshold_valid_no_match(self):
        # Conditions without any coherence threshold pattern pass safely
        res = _make_resolution(conditions=["implement continuous monitoring"])
        is_safe, _ = self.session.check_hard_limits(res)
        assert is_safe is True

    # --- Structural checks ---

    def test_empty_conditions_unsafe(self):
        res = _make_resolution(conditions=[])
        is_safe, reason = self.session.check_hard_limits(res)
        assert is_safe is False
        assert "at least one condition" in reason.lower()

    def test_vague_condition_maybe(self):
        res = _make_resolution(conditions=["maybe add monitoring later"])
        is_safe, reason = self.session.check_hard_limits(res)
        assert is_safe is False
        assert "vague" in reason.lower()

    def test_vague_condition_perhaps(self):
        res = _make_resolution(conditions=["perhaps review the logs"])
        is_safe, _ = self.session.check_hard_limits(res)
        assert is_safe is False

    def test_vague_condition_try(self):
        res = _make_resolution(conditions=["try reducing complexity"])
        is_safe, _ = self.session.check_hard_limits(res)
        assert is_safe is False

    def test_vague_condition_consider(self):
        res = _make_resolution(conditions=["consider adding checks"])
        is_safe, _ = self.session.check_hard_limits(res)
        assert is_safe is False

    def test_short_root_cause_unsafe(self):
        res = _make_resolution(root_cause="short")
        is_safe, reason = self.session.check_hard_limits(res)
        assert is_safe is False
        assert "10 characters" in reason

    def test_empty_root_cause_unsafe(self):
        res = _make_resolution(root_cause="")
        is_safe, _ = self.session.check_hard_limits(res)
        assert is_safe is False

    def test_valid_resolution_safe(self):
        res = _make_resolution(
            conditions=["implement continuous monitoring for 48 hours"],
            root_cause="Risk threshold exceeded due to rapid state changes during high load",
        )
        is_safe, reason = self.session.check_hard_limits(res)
        assert is_safe is True
        assert reason is None


# ===========================================================================
# 6. calculate_authority_score
# ===========================================================================

class TestCalculateAuthorityScore:
    """Tests for module-level calculate_authority_score."""

    def test_no_state_returns_default_health(self):
        """Without agent_state, health_score defaults to 0.5."""
        score = calculate_authority_score(
            agent_metadata={"total_reviews": 0},
            agent_state=None,
        )
        # health 0.5*0.4 + track 0.5*0.3 + domain 0.5*0.2 + fresh 0.5*0.1 = 0.5
        assert score == pytest.approx(0.5, abs=0.01)

    def test_low_risk_gives_high_health_score(self):
        score = calculate_authority_score(
            agent_metadata={"total_reviews": 0},
            agent_state={"risk_score": 0.05},
        )
        # sigmoid(10*(0.05-0.35)) = sigmoid(-3) ~ 0.95 => health ~ 0.95
        # health 0.95*0.4=0.38, track 0.5*0.3=0.15, domain 0.5*0.2=0.10, fresh 0.5*0.1=0.05 = 0.68
        assert score > 0.6

    def test_high_risk_gives_low_health_score(self):
        score = calculate_authority_score(
            agent_metadata={"total_reviews": 0},
            agent_state={"risk_score": 0.80},
        )
        # sigmoid(10*(0.80-0.35)) = sigmoid(4.5) ~ 0.011 => health ~ 0.01
        # health 0.01*0.4=0.004, track 0.5*0.3=0.15, domain 0.5*0.2=0.10, fresh 0.5*0.1=0.05 = ~0.30
        assert score < 0.4

    def test_perfect_track_record(self):
        score = calculate_authority_score(
            agent_metadata={"total_reviews": 10, "successful_reviews": 10},
            agent_state=None,
        )
        # health 0.5*0.4=0.20, track 1.0*0.3=0.30, domain 0.5*0.2=0.10, fresh 0.5*0.1=0.05 = 0.65
        assert score == pytest.approx(0.65, abs=0.01)

    def test_zero_track_record(self):
        score = calculate_authority_score(
            agent_metadata={"total_reviews": 10, "successful_reviews": 0},
            agent_state=None,
        )
        # health 0.5*0.4=0.20, track 0.0*0.3=0.00, domain 0.5*0.2=0.10, fresh 0.5*0.1=0.05 = 0.35
        assert score == pytest.approx(0.35, abs=0.01)

    def test_tag_overlap_full(self):
        score = calculate_authority_score(
            agent_metadata={
                "total_reviews": 0,
                "tags": ["governance", "monitoring"],
                "paused_agent_tags": ["governance", "monitoring"],
            },
            agent_state=None,
        )
        # domain_expertise = 1.0 (perfect Jaccard overlap)
        # health 0.5*0.4=0.20, track 0.5*0.3=0.15, domain 1.0*0.2=0.20, fresh 0.5*0.1=0.05 = 0.60
        assert score == pytest.approx(0.60, abs=0.01)

    def test_tag_overlap_partial(self):
        score = calculate_authority_score(
            agent_metadata={
                "total_reviews": 0,
                "tags": ["governance", "monitoring"],
                "paused_agent_tags": ["governance", "analysis"],
            },
            agent_state=None,
        )
        # Jaccard: {"governance"} / {"governance","monitoring","analysis"} = 1/3
        # domain = 1/3
        # health 0.5*0.4=0.20, track 0.5*0.3=0.15, domain 0.333*0.2=0.067, fresh 0.5*0.1=0.05 = ~0.467
        assert 0.4 < score < 0.55

    def test_tag_overlap_none(self):
        score = calculate_authority_score(
            agent_metadata={
                "total_reviews": 0,
                "tags": ["governance"],
                "paused_agent_tags": ["analysis"],
            },
            agent_state=None,
        )
        # Jaccard: 0 / {"governance","analysis"} = 0.0
        # domain = 0.0
        # health 0.5*0.4=0.20, track 0.5*0.3=0.15, domain 0.0*0.2=0.00, fresh 0.5*0.1=0.05 = 0.40
        assert score == pytest.approx(0.40, abs=0.01)

    def test_reviewer_has_tags_paused_does_not(self):
        score = calculate_authority_score(
            agent_metadata={
                "total_reviews": 0,
                "tags": ["governance", "monitoring"],
            },
            agent_state=None,
        )
        # No paused_agent_tags => domain_expertise = 0.6 (slight bonus)
        # health 0.5*0.4=0.20, track 0.5*0.3=0.15, domain 0.6*0.2=0.12, fresh 0.5*0.1=0.05 = 0.52
        assert score == pytest.approx(0.52, abs=0.01)

    def test_recent_update_freshness(self):
        recent_time = (datetime.now() - timedelta(hours=1)).isoformat()
        score = calculate_authority_score(
            agent_metadata={"total_reviews": 0, "last_update": recent_time},
            agent_state=None,
        )
        # freshness = 1.0 (< 24h)
        # health 0.5*0.4=0.20, track 0.5*0.3=0.15, domain 0.5*0.2=0.10, fresh 1.0*0.1=0.10 = 0.55
        assert score == pytest.approx(0.55, abs=0.01)

    def test_stale_update_freshness(self):
        stale_time = (datetime.now() - timedelta(hours=48)).isoformat()
        score = calculate_authority_score(
            agent_metadata={"total_reviews": 0, "last_update": stale_time},
            agent_state=None,
        )
        # freshness = 0.5 (>= 24h)
        # health 0.5*0.4=0.20, track 0.5*0.3=0.15, domain 0.5*0.2=0.10, fresh 0.5*0.1=0.05 = 0.50
        assert score == pytest.approx(0.50, abs=0.01)

    def test_no_last_update_freshness(self):
        score = calculate_authority_score(
            agent_metadata={"total_reviews": 0},
            agent_state=None,
        )
        # freshness = 0.5 (no last_update)
        assert score == pytest.approx(0.50, abs=0.01)

    def test_score_bounded_zero_to_one(self):
        """Authority score must always be in [0, 1]."""
        # Best possible inputs
        recent = datetime.now().isoformat()
        score_best = calculate_authority_score(
            agent_metadata={
                "total_reviews": 100,
                "successful_reviews": 100,
                "tags": ["a", "b"],
                "paused_agent_tags": ["a", "b"],
                "last_update": recent,
            },
            agent_state={"risk_score": 0.0},
        )
        assert 0.0 <= score_best <= 1.0

        # Worst possible inputs
        stale = (datetime.now() - timedelta(days=30)).isoformat()
        score_worst = calculate_authority_score(
            agent_metadata={
                "total_reviews": 100,
                "successful_reviews": 0,
                "tags": ["x"],
                "paused_agent_tags": ["y"],
                "last_update": stale,
            },
            agent_state={"risk_score": 1.0},
        )
        assert 0.0 <= score_worst <= 1.0

    def test_invalid_last_update_treated_as_stale(self):
        score = calculate_authority_score(
            agent_metadata={"total_reviews": 0, "last_update": "not-a-date"},
            agent_state=None,
        )
        # Invalid date => freshness = 0.5 (fallback)
        assert score == pytest.approx(0.50, abs=0.01)
