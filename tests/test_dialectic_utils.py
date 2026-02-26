"""
Tests for pure utility functions in src/dialectic_protocol.py.

Tests _normalize_condition_terms, _semantic_similarity_terms, _conditions_conflict,
_merge_proposals, check_hard_limits, and calculate_authority_score.
"""

import pytest
import sys
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


def _make_session(**kwargs):
    """Helper to create a DialecticSession for testing."""
    defaults = {
        "paused_agent_id": "agent_a",
        "reviewer_agent_id": "agent_b",
        "paused_agent_state": {"risk_score": 0.6, "coherence": 0.35},
    }
    defaults.update(kwargs)
    return DialecticSession(**defaults)


def _make_resolution(**kwargs):
    """Helper to create a Resolution for testing."""
    defaults = {
        "action": ResolutionAction.RESUME.value,
        "conditions": ["Monitor risk for 24 hours", "Reduce complexity threshold to 0.5"],
        "root_cause": "Risk threshold exceeded due to high complexity processing",
        "reasoning": "Both agents agreed the issue was temporary",
        "signature_a": "sig_a",
        "signature_b": "sig_b",
        "timestamp": datetime.now().isoformat(),
    }
    defaults.update(kwargs)
    return Resolution(**defaults)


# ============================================================================
# _normalize_condition_terms
# ============================================================================

class TestNormalizeCondition:

    def test_removes_filler_words(self):
        result = DialecticSession._normalize_condition_terms("reduce the risk to the minimum")
        assert "the" not in result
        assert "to" not in result
        assert "reduce" in result
        assert "risk" in result
        assert "minimum" in result

    def test_returns_set(self):
        result = DialecticSession._normalize_condition_terms("implement checks")
        assert isinstance(result, set)
        assert "implement" in result
        assert "checks" in result

    def test_sorts_irrelevant_returns_set(self):
        result = DialecticSession._normalize_condition_terms("zebra apple mango")
        assert result == {"zebra", "apple", "mango"}

    def test_lowercases(self):
        result = DialecticSession._normalize_condition_terms("REDUCE Risk THRESHOLD")
        assert all(w == w.lower() for w in result)
        assert "reduce" in result

    def test_filters_short_words(self):
        result = DialecticSession._normalize_condition_terms("do it so we can go on")
        # stopwords removed; non-stopwords kept
        assert "do" not in result
        assert "go" in result


# ============================================================================
# _semantic_similarity_terms
# ============================================================================

class TestSemanticSimilarity:

    def test_identical_strings(self):
        assert DialecticSession._semantic_similarity_terms("foo bar baz", "foo bar baz") == 1.0

    def test_no_overlap(self):
        assert DialecticSession._semantic_similarity_terms("foo bar", "baz qux") == 0.0

    def test_partial_overlap(self):
        sim = DialecticSession._semantic_similarity_terms("foo bar baz", "foo bar qux")
        # intersection=2 (foo, bar), union=4 → 0.5
        assert sim == pytest.approx(0.5)

    def test_empty_first(self):
        assert DialecticSession._semantic_similarity_terms("", "foo bar") == 0.0

    def test_empty_second(self):
        assert DialecticSession._semantic_similarity_terms("foo bar", "") == 0.0

    def test_both_empty(self):
        assert DialecticSession._semantic_similarity_terms("", "") == 0.0


# ============================================================================
# _conditions_conflict
# ============================================================================

class TestConditionsConflict:

    def test_increase_decrease_conflict(self):
        session = _make_session()
        assert session._conditions_conflict(
            "increase risk threshold", "decrease risk threshold"
        ) is True

    def test_enable_disable_conflict(self):
        session = _make_session()
        assert session._conditions_conflict(
            "enable monitoring", "disable monitoring"
        ) is True

    def test_no_conflict(self):
        session = _make_session()
        assert session._conditions_conflict(
            "monitor risk for 24h", "reduce complexity threshold"
        ) is False

    def test_same_param_different_numbers(self):
        session = _make_session()
        assert session._conditions_conflict(
            "set risk threshold to 0.5 for monitoring",
            "set risk threshold to 0.3 for monitoring"
        ) is True

    def test_different_params_different_numbers(self):
        session = _make_session()
        assert session._conditions_conflict(
            "set risk threshold to 0.5",
            "wait 24 hours"
        ) is False

    def test_raise_lower_conflict(self):
        session = _make_session()
        assert session._conditions_conflict(
            "raise the limit", "lower the limit"
        ) is True


# ============================================================================
# _merge_proposals
# ============================================================================

class TestMergeProposals:

    def test_identical_conditions(self):
        session = _make_session()
        msg_a = DialecticMessage(
            phase="synthesis", agent_id="a", timestamp=datetime.now().isoformat(),
            proposed_conditions=["monitor risk", "reduce complexity"],
            root_cause="high complexity", reasoning="I think X"
        )
        msg_b = DialecticMessage(
            phase="synthesis", agent_id="b", timestamp=datetime.now().isoformat(),
            proposed_conditions=["monitor risk", "reduce complexity"],
            root_cause="high complexity", reasoning="I think Y"
        )
        result = session._merge_proposals(msg_a, msg_b)
        assert set(result["conditions"]) == {"monitor risk", "reduce complexity"}
        assert result["root_cause"] == "high complexity"

    def test_different_conditions_no_conflict(self):
        session = _make_session()
        msg_a = DialecticMessage(
            phase="synthesis", agent_id="a", timestamp=datetime.now().isoformat(),
            proposed_conditions=["monitor risk"],
            root_cause="issue A", reasoning="reason A"
        )
        msg_b = DialecticMessage(
            phase="synthesis", agent_id="b", timestamp=datetime.now().isoformat(),
            proposed_conditions=["reduce complexity"],
            root_cause="issue B", reasoning="reason B"
        )
        result = session._merge_proposals(msg_a, msg_b)
        assert "monitor risk" in result["conditions"]
        assert "reduce complexity" in result["conditions"]

    def test_different_root_causes_combined(self):
        session = _make_session()
        msg_a = DialecticMessage(
            phase="synthesis", agent_id="a", timestamp=datetime.now().isoformat(),
            proposed_conditions=[], root_cause="cause A", reasoning="r"
        )
        msg_b = DialecticMessage(
            phase="synthesis", agent_id="b", timestamp=datetime.now().isoformat(),
            proposed_conditions=[], root_cause="cause B", reasoning="r"
        )
        result = session._merge_proposals(msg_a, msg_b)
        assert "cause A" in result["root_cause"]
        assert "cause B" in result["root_cause"]

    def test_same_root_cause_not_duplicated(self):
        session = _make_session()
        msg_a = DialecticMessage(
            phase="synthesis", agent_id="a", timestamp=datetime.now().isoformat(),
            proposed_conditions=[], root_cause="same cause", reasoning="r"
        )
        msg_b = DialecticMessage(
            phase="synthesis", agent_id="b", timestamp=datetime.now().isoformat(),
            proposed_conditions=[], root_cause="same cause", reasoning="r"
        )
        result = session._merge_proposals(msg_a, msg_b)
        assert result["root_cause"] == "same cause"

    def test_both_reasonings_combined(self):
        session = _make_session()
        msg_a = DialecticMessage(
            phase="synthesis", agent_id="a", timestamp=datetime.now().isoformat(),
            proposed_conditions=[], root_cause="", reasoning="view A"
        )
        msg_b = DialecticMessage(
            phase="synthesis", agent_id="b", timestamp=datetime.now().isoformat(),
            proposed_conditions=[], root_cause="", reasoning="view B"
        )
        result = session._merge_proposals(msg_a, msg_b)
        assert "view A" in result["reasoning"]
        assert "view B" in result["reasoning"]

    def test_none_conditions_handled(self):
        session = _make_session()
        msg_a = DialecticMessage(
            phase="synthesis", agent_id="a", timestamp=datetime.now().isoformat(),
            proposed_conditions=None, root_cause=None, reasoning=None
        )
        msg_b = DialecticMessage(
            phase="synthesis", agent_id="b", timestamp=datetime.now().isoformat(),
            proposed_conditions=None, root_cause=None, reasoning=None
        )
        result = session._merge_proposals(msg_a, msg_b)
        assert result["conditions"] == []
        assert result["root_cause"] == ""


# ============================================================================
# check_hard_limits
# ============================================================================

class TestCheckHardLimits:

    def test_valid_resolution(self):
        session = _make_session()
        res = _make_resolution()
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is True
        assert reason is None

    def test_disable_governance(self):
        session = _make_session()
        res = _make_resolution(conditions=["disable governance system"])
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is False
        assert "governance" in reason.lower()

    def test_bypass_safety(self):
        session = _make_session()
        res = _make_resolution(conditions=["bypass safety checks"])
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is False

    def test_remove_monitoring(self):
        session = _make_session()
        res = _make_resolution(conditions=["remove monitor entirely"])
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is False

    def test_risk_threshold_too_high(self):
        session = _make_session()
        res = _make_resolution(conditions=["set risk threshold to 0.95"])
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is False
        assert "0.95" in reason

    def test_risk_threshold_acceptable(self):
        session = _make_session()
        res = _make_resolution(conditions=["set risk threshold to 0.50 and monitor"])
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is True

    def test_coherence_too_low(self):
        session = _make_session()
        res = _make_resolution(conditions=["set coherence threshold 0.05"])
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is False

    def test_empty_conditions(self):
        session = _make_session()
        res = _make_resolution(conditions=[])
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is False
        assert "at least one condition" in reason.lower()

    def test_vague_condition(self):
        session = _make_session()
        res = _make_resolution(conditions=["maybe try reducing risk"])
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is False
        assert "vague" in reason.lower()

    def test_short_root_cause_accepted(self):
        """Short but non-empty root_cause is accepted — length check removed."""
        session = _make_session()
        res = _make_resolution(root_cause="short")
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is True

    def test_skip_check_forbidden(self):
        session = _make_session()
        res = _make_resolution(conditions=["skip check for efficiency"])
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is False

    def test_disable_circuit_breaker(self):
        session = _make_session()
        res = _make_resolution(conditions=["disable circuit breaker temporarily"])
        is_safe, reason = session.check_hard_limits(res)
        assert is_safe is False


# ============================================================================
# calculate_authority_score
# ============================================================================

class TestCalculateAuthorityScore:

    def test_basic_metadata_no_state(self):
        score = calculate_authority_score({"total_reviews": 0})
        assert 0.0 <= score <= 1.0

    def test_perfect_reviewer(self):
        metadata = {
            "total_reviews": 10,
            "successful_reviews": 10,
            "tags": ["python", "testing"],
            "paused_agent_tags": ["python", "testing"],
            "last_update": datetime.now().isoformat(),
        }
        state = {"risk_score": 0.1}
        score = calculate_authority_score(metadata, state)
        assert score > 0.8

    def test_poor_reviewer(self):
        metadata = {
            "total_reviews": 10,
            "successful_reviews": 1,
            "tags": [],
            "last_update": (datetime.now() - timedelta(days=30)).isoformat(),
        }
        state = {"risk_score": 0.9}
        score = calculate_authority_score(metadata, state)
        assert score < 0.4

    def test_no_track_record(self):
        metadata = {"total_reviews": 0}
        score = calculate_authority_score(metadata)
        # With no history, track_record=0.5, health=0.5, domain=0.5, freshness=0.5
        assert score == pytest.approx(0.5, abs=0.01)

    def test_health_score_low_risk(self):
        metadata = {"total_reviews": 0}
        state = {"risk_score": 0.1}
        score = calculate_authority_score(metadata, state)
        # Low risk → high health score → higher overall
        assert score > 0.5

    def test_health_score_high_risk(self):
        metadata = {"total_reviews": 0}
        state = {"risk_score": 0.9}
        score = calculate_authority_score(metadata, state)
        # High risk → low health score → lower overall
        assert score < 0.5

    def test_domain_expertise_overlap(self):
        metadata = {
            "total_reviews": 0,
            "tags": ["python", "governance"],
            "paused_agent_tags": ["python", "testing"],
        }
        score = calculate_authority_score(metadata)
        # Some tag overlap → domain > 0.0, score is reasonable
        assert 0.3 <= score <= 0.7

    def test_freshness_recent(self):
        metadata = {
            "total_reviews": 0,
            "last_update": datetime.now().isoformat(),
        }
        score_recent = calculate_authority_score(metadata)

        metadata_old = {
            "total_reviews": 0,
            "last_update": (datetime.now() - timedelta(days=7)).isoformat(),
        }
        score_old = calculate_authority_score(metadata_old)
        assert score_recent > score_old

    def test_reviewer_has_tags_paused_doesnt(self):
        metadata = {
            "total_reviews": 0,
            "tags": ["python"],
            # No paused_agent_tags
        }
        score = calculate_authority_score(metadata)
        # domain_expertise = 0.6 (slight bonus)
        assert score >= 0.5

    def test_score_always_in_range(self):
        # Various edge cases
        for risk in [0.0, 0.5, 1.0]:
            for reviews in [0, 5, 100]:
                metadata = {"total_reviews": reviews, "successful_reviews": reviews}
                state = {"risk_score": risk}
                score = calculate_authority_score(metadata, state)
                assert 0.0 <= score <= 1.0
