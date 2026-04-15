"""
Tests for src/mcp_handlers/response_formatter.py — Response mode filtering.

Tests _format_minimal, _format_compact, _strip_context (pure dict operations),
and format_response routing (mocked for standard mode which needs GovernanceState).
"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.response_formatter import (
    format_response,
    _format_minimal,
    _format_compact,
    _format_mirror,
    _strip_context,
)


# ============================================================================
# Sample response data for testing
# ============================================================================

def _sample_response():
    return {
        "agent_id": "test-agent-123",
        "status": "approved",
        "health_status": "healthy",
        "health_message": "All systems nominal",
        "decision": {
            "action": "continue",
            "reason": "Low risk, high coherence",
            "require_human": False,
            "margin": 0.15,
            "nearest_edge": "risk_threshold",
        },
        "metrics": {
            "E": 0.7,
            "I": 0.85,
            "S": 0.1,
            "V": -0.02,
            "coherence": 0.92,
            "risk_score": 0.08,
            "latest_risk_score": 0.08,
            "phi": 1.23,
            "verdict": "approve",
            "lambda1": 0.9,
            "health_status": "healthy",
            "health_message": "All good",
        },
        "trajectory_identity": {
            "trust_tier": {"name": "established"}
        },
        "history": {"decision_history": []},
        # Context fields that may be stripped
        "eisv_labels": {"E": "energy"},
        "learning_context": {"key": "value"},
        "relevant_discoveries": [{"id": "d1"}],
        "onboarding": {"step": 1},
        "welcome": "Hello!",
        "api_key_hint": "sk-***",
        "_onboarding": True,
        # Enrichment bloat (stripped for established agents)
        "convergence_guidance": {"lines": 20},
        "calibration_feedback": {"nested": "dict"},
        "drift_forecast": {"heavy": True},
        "saturation_diagnostics": {"medium": True},
        "perturbation": {"medium": True},
        "actionable_feedback": {"medium": True},
        "state": {"interpretation": "duplicate"},
        "cirs_void_alert": {"internal": True},
        "cirs_state_announce": {"internal": True},
        "outcome_event": {"internal": True},
        "temporal_context": {"low_value": True},
        "identity_reminder": "first 3 only",
        "unitares_v41": {"passthrough": True},
        "pending_dialectic": {"conditional": True},
        "llm_coaching": {"heavy": True},
        "recovery_coaching": {"heavy": True},
        # Internal signals (stripped unconditionally by _strip_context)
        "_mirror_signals": [],
        "_mirror_kg_results": [],
        "_mirror_question": None,
        "_mirror_reflection": None,
        "_has_sensor_data": False,
        "_eisv_validation_warning": "warning",
        "advisories": [],
    }


# ============================================================================
# _format_minimal
# ============================================================================

class TestFormatMinimal:

    def test_basic_fields(self):
        data = _sample_response()
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier=None)
        assert result["action"] == "continue"
        assert result["_mode"] == "minimal"
        assert result["E"] == 0.7
        assert result["I"] == 0.85
        assert result["S"] == 0.1
        assert result["V"] == -0.02
        assert result["coherence"] == 0.92

    def test_includes_margin(self):
        data = _sample_response()
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier=None)
        assert result["margin"] == 0.15

    def test_includes_nearest_edge(self):
        data = _sample_response()
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier=None)
        assert result["nearest_edge"] == "risk_threshold"

    def test_no_margin_when_absent(self):
        data = _sample_response()
        data["decision"]["margin"] = None
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier=None)
        assert "margin" not in result

    def test_tip_when_default_mode(self):
        data = _sample_response()
        result = _format_minimal(data, using_default_mode=True, saved_trust_tier=None)
        assert "_tip" in result

    def test_no_tip_when_explicit_mode(self):
        data = _sample_response()
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier=None)
        assert "_tip" not in result

    def test_trust_tier_included(self):
        data = _sample_response()
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier="established")
        assert result["trust_tier"] == "established"

    def test_no_trust_tier_when_none(self):
        data = _sample_response()
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier=None)
        assert "trust_tier" not in result

    def test_risk_score_from_latest(self):
        data = _sample_response()
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier=None)
        assert result["risk_score"] == 0.08

    def test_risk_score_fallback(self):
        data = _sample_response()
        data["metrics"].pop("latest_risk_score")
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier=None)
        assert result["risk_score"] == 0.08  # falls back to risk_score

    def test_empty_decision(self):
        data = _sample_response()
        data["decision"] = {}
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier=None)
        assert result["action"] == "continue"  # default

    def test_non_dict_decision(self):
        data = _sample_response()
        data["decision"] = "not_a_dict"
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier=None)
        assert result["action"] == "continue"

    def test_non_dict_metrics(self):
        data = _sample_response()
        data["metrics"] = "not_a_dict"
        result = _format_minimal(data, using_default_mode=False, saved_trust_tier=None)
        assert result["E"] is None
        assert result["I"] is None


# ============================================================================
# _format_compact
# ============================================================================

class TestFormatCompact:

    def test_basic_structure(self):
        data = _sample_response()
        result = _format_compact(data, using_default_mode=False, saved_trust_tier=None)
        assert result["success"] is True
        assert result["_mode"] == "compact"
        assert result["agent_id"] == "test-agent-123"
        assert "summary" in result

    def test_metrics_included(self):
        data = _sample_response()
        result = _format_compact(data, using_default_mode=False, saved_trust_tier=None)
        m = result["metrics"]
        assert m["E"] == 0.7
        assert m["coherence"] == 0.92
        assert m["phi"] == 1.23

    def test_decision_included(self):
        data = _sample_response()
        result = _format_compact(data, using_default_mode=False, saved_trust_tier=None)
        d = result["decision"]
        assert d["action"] == "continue"
        assert d["reason"] == "Low risk, high coherence"
        assert d["margin"] == 0.15

    def test_summary_format(self):
        data = _sample_response()
        result = _format_compact(data, using_default_mode=False, saved_trust_tier=None)
        assert "continue" in result["summary"]
        assert "healthy" in result["summary"]
        assert "0.92" in result["summary"]

    def test_trust_tier_included(self):
        data = _sample_response()
        result = _format_compact(data, using_default_mode=False, saved_trust_tier="established")
        assert result["trust_tier"] == "established"

    def test_tip_when_default_mode(self):
        data = _sample_response()
        result = _format_compact(data, using_default_mode=True, saved_trust_tier=None)
        assert "_tip" in result

    def test_no_tip_when_explicit(self):
        data = _sample_response()
        result = _format_compact(data, using_default_mode=False, saved_trust_tier=None)
        assert "_tip" not in result

    def test_risk_score_fallback(self):
        data = _sample_response()
        data["metrics"]["latest_risk_score"] = None
        result = _format_compact(data, using_default_mode=False, saved_trust_tier=None)
        assert result["metrics"]["risk_score"] == 0.08

    def test_empty_metrics(self):
        data = _sample_response()
        data["metrics"] = {}
        result = _format_compact(data, using_default_mode=False, saved_trust_tier=None)
        assert result["metrics"]["E"] is None

    def test_non_dict_metrics(self):
        data = _sample_response()
        data["metrics"] = "nope"
        result = _format_compact(data, using_default_mode=False, saved_trust_tier=None)
        assert result["metrics"]["E"] is None


# ============================================================================
# _strip_context
# ============================================================================

class TestStripContext:

    def test_strips_eisv_labels(self):
        data = _sample_response()
        _strip_context(data, is_new_agent=False, key_was_generated=False, api_key_auto_retrieved=False)
        assert "eisv_labels" not in data

    def test_strips_learning_context_for_established(self):
        data = _sample_response()
        _strip_context(data, is_new_agent=False, key_was_generated=False, api_key_auto_retrieved=False)
        assert "learning_context" not in data
        assert "relevant_discoveries" not in data
        assert "onboarding" not in data
        assert "welcome" not in data

    def test_strips_enrichment_bloat_for_established(self):
        data = _sample_response()
        _strip_context(data, is_new_agent=False, key_was_generated=False, api_key_auto_retrieved=False)
        for key in [
            "convergence_guidance", "calibration_feedback", "trajectory_identity",
            "drift_forecast", "saturation_diagnostics", "perturbation",
            "actionable_feedback", "state", "cirs_void_alert",
            "cirs_state_announce", "outcome_event", "temporal_context",
            "identity_reminder", "unitares_v41", "pending_dialectic",
            "llm_coaching", "recovery_coaching",
        ]:
            assert key not in data, f"{key} should be stripped for established agents"

    def test_preserves_enrichment_for_new_agent(self):
        data = _sample_response()
        _strip_context(data, is_new_agent=True, key_was_generated=False, api_key_auto_retrieved=False)
        assert "learning_context" in data
        assert "onboarding" in data
        assert "convergence_guidance" in data
        assert "calibration_feedback" in data

    def test_strips_internal_signals_unconditionally(self):
        data = _sample_response()
        # Set non-empty values to verify they get stripped
        data["_mirror_signals"] = ["signal"]
        data["_mirror_kg_results"] = [{"summary": "result"}]
        data["_mirror_question"] = "question"
        data["_mirror_reflection"] = "reflect"
        _strip_context(data, is_new_agent=True, key_was_generated=False, api_key_auto_retrieved=False)
        assert "_mirror_signals" not in data
        assert "_mirror_kg_results" not in data
        assert "_mirror_question" not in data
        assert "_mirror_reflection" not in data
        assert "_has_sensor_data" not in data
        assert "_eisv_validation_warning" not in data

    def test_strips_empty_advisories(self):
        data = _sample_response()
        _strip_context(data, is_new_agent=True, key_was_generated=False, api_key_auto_retrieved=False)
        assert "advisories" not in data

    def test_preserves_nonempty_advisories(self):
        data = _sample_response()
        data["advisories"] = [{"msg": "important"}]
        _strip_context(data, is_new_agent=True, key_was_generated=False, api_key_auto_retrieved=False)
        assert "advisories" in data

    def test_strips_api_key_hint_for_established(self):
        data = _sample_response()
        _strip_context(data, is_new_agent=False, key_was_generated=False, api_key_auto_retrieved=False)
        assert "api_key_hint" not in data
        assert "_onboarding" not in data

    def test_preserves_api_key_hint_when_generated(self):
        data = _sample_response()
        _strip_context(data, is_new_agent=False, key_was_generated=True, api_key_auto_retrieved=False)
        assert "api_key_hint" in data

    def test_preserves_api_key_hint_when_auto_retrieved(self):
        data = _sample_response()
        _strip_context(data, is_new_agent=False, key_was_generated=False, api_key_auto_retrieved=True)
        assert "api_key_hint" in data

    def test_modifies_in_place(self):
        data = {"eisv_labels": True}
        _strip_context(data, is_new_agent=True, key_was_generated=False, api_key_auto_retrieved=False)
        assert "eisv_labels" not in data

    def test_handles_missing_keys_gracefully(self):
        data = {}
        _strip_context(data, is_new_agent=False, key_was_generated=False, api_key_auto_retrieved=False)
        # Should not raise


# ============================================================================
# format_response routing
# ============================================================================

class TestFormatResponse:

    def test_full_mode_returns_as_is(self):
        data = _sample_response()
        original_keys = set(data.keys())
        result = format_response(data, {"response_mode": "full"})
        assert set(result.keys()) == original_keys

    def test_minimal_mode(self):
        data = _sample_response()
        result = format_response(data, {"response_mode": "minimal"})
        assert result["_mode"] == "minimal"
        assert result["action"] == "continue"

    def test_compact_mode(self):
        data = _sample_response()
        result = format_response(data, {"response_mode": "compact"})
        assert result["_mode"] == "compact"
        assert "summary" in result

    def test_lite_alias_for_compact(self):
        data = _sample_response()
        result = format_response(data, {"response_mode": "lite"})
        assert result["_mode"] == "compact"

    def test_auto_mode_healthy_becomes_mirror_for_disembodied(self):
        data = _sample_response()
        data["health_status"] = "healthy"
        result = format_response(data, {"response_mode": "auto"})
        assert result["_mode"] == "mirror"  # Disembodied (no sensor_data) -> mirror

    def test_auto_mode_healthy_becomes_minimal_for_embodied(self):
        data = _sample_response()
        data["health_status"] = "healthy"
        data["_has_sensor_data"] = True
        result = format_response(data, {"response_mode": "auto"})
        assert result["_mode"] == "minimal"  # Embodied (has sensor_data) -> minimal

    def test_auto_mode_at_risk_becomes_standard(self):
        """auto mode with at_risk health should become standard (needs GovernanceState)."""
        data = _sample_response()
        data["health_status"] = "at_risk"
        # Standard mode needs GovernanceState imports — mock them
        mock_state = MagicMock()
        mock_state.interpret_state.return_value = {"summary": "At risk"}
        with patch("src.mcp_handlers.response_formatter.GovernanceState", return_value=mock_state, create=True):
            with patch("src.mcp_handlers.response_formatter._format_standard") as mock_std:
                mock_std.return_value = {"_mode": "standard", "state": "at risk"}
                result = format_response(data, {"response_mode": "auto"})
                mock_std.assert_called_once()

    def test_auto_mode_unknown_becomes_compact(self):
        data = _sample_response()
        data["health_status"] = "unknown"
        data["metrics"]["health_status"] = "unknown"
        result = format_response(data, {"response_mode": "auto"})
        assert result["_mode"] == "compact"

    def test_env_var_override(self):
        data = _sample_response()
        with patch.dict(os.environ, {"UNITARES_PROCESS_UPDATE_RESPONSE_MODE": "compact"}):
            result = format_response(data, {})  # No per-call mode
            assert result["_mode"] == "compact"

    def test_per_call_overrides_env_var(self):
        data = _sample_response()
        with patch.dict(os.environ, {"UNITARES_PROCESS_UPDATE_RESPONSE_MODE": "compact"}):
            result = format_response(data, {"response_mode": "minimal"})
            assert result["_mode"] == "minimal"

    def test_agent_preference_override(self):
        data = _sample_response()
        meta = MagicMock()
        meta.preferences = {"verbosity": "compact"}
        result = format_response(data, {}, meta=meta)
        assert result["_mode"] == "compact"

    def test_per_call_overrides_agent_pref(self):
        data = _sample_response()
        meta = MagicMock()
        meta.preferences = {"verbosity": "compact"}
        result = format_response(data, {"response_mode": "minimal"}, meta=meta)
        assert result["_mode"] == "minimal"

    def test_strip_context_applied_for_minimal(self):
        data = _sample_response()
        result = format_response(data, {"response_mode": "minimal"}, is_new_agent=False)
        # eisv_labels stripped
        assert "eisv_labels" not in result

    def test_strip_context_applied_for_compact(self):
        data = _sample_response()
        result = format_response(data, {"response_mode": "compact"}, is_new_agent=False)
        assert "eisv_labels" not in result

    def test_trust_tier_preserved(self):
        data = _sample_response()
        result = format_response(data, {"response_mode": "minimal"})
        assert result.get("trust_tier") == "established"

    def test_trust_tier_none_when_no_trajectory(self):
        data = _sample_response()
        data.pop("trajectory_identity")
        result = format_response(data, {"response_mode": "minimal"})
        assert "trust_tier" not in result

    def test_meta_without_preferences(self):
        data = _sample_response()
        meta = MagicMock()
        meta.preferences = None
        result = format_response(data, {"response_mode": "minimal"}, meta=meta)
        assert result["_mode"] == "minimal"

    def test_meta_without_preferences_attr(self):
        data = _sample_response()
        meta = object()  # No preferences attribute
        result = format_response(data, {"response_mode": "minimal"}, meta=meta)
        assert result["_mode"] == "minimal"


# ============================================================================
# _format_mirror
# ============================================================================

class TestFormatMirror:

    def test_basic_output_shape(self):
        data = _sample_response()
        result = _format_mirror(data, saved_trust_tier=None)
        assert result["_mode"] == "mirror"
        assert result["success"] is True
        assert "verdict" in result
        assert "mirror" in result
        assert isinstance(result["mirror"], list)

    def test_verdict_from_decision(self):
        data = _sample_response()
        data["decision"]["action"] = "pause"
        result = _format_mirror(data, saved_trust_tier=None)
        assert result["verdict"] == "pause"

    def test_calibration_insight_inverted(self):
        data = _sample_response()
        data["learning_context"] = {
            "calibration": {
                "insight": "INVERTED CALIBRATION: High confidence correlates with LOWER accuracy.",
                "total_decisions": 15,
                "overall_accuracy": 0.65,
            }
        }
        result = _format_mirror(data, saved_trust_tier=None)
        assert any("inverted" in s.lower() for s in result["mirror"])
        # Must be labeled as a fleet-wide trend, not the caller's personal
        # confidence — the underlying data is from a module-level singleton
        # aggregated across all agents. Previously the string was "Your
        # confidence tends to be inverted ..." which misled fresh agents
        # into thinking they had accumulated history.
        assert any("fleet" in s.lower() for s in result["mirror"]), \
            "INVERTED calibration signal must be labeled fleet-wide"

    def test_calibration_insight_normal(self):
        data = _sample_response()
        data["learning_context"] = {
            "calibration": {
                "insight": "Well calibrated",
                "total_decisions": 20,
                "overall_accuracy": 0.82,
            }
        }
        result = _format_mirror(data, saved_trust_tier=None)
        assert any("82%" in s for s in result["mirror"])
        # Same scope concern as the inverted case — the 20 decisions are
        # fleet-wide, not per-agent. Label must match the dashboard, which
        # renders the same singleton under a "Fleet-wide" header.
        assert any("fleet" in s.lower() for s in result["mirror"]), \
            "Calibration accuracy signal must be labeled fleet-wide"

    def test_complexity_divergence_question(self):
        data = _sample_response()
        data["calibration_feedback"] = {
            "complexity": {
                "reported": 0.8,
                "derived": 0.28,
                "discrepancy": 0.52,
            }
        }
        result = _format_mirror(data, saved_trust_tier=None)
        assert any("complexity=0.80" in s for s in result["mirror"])
        assert any("what's driving" in s.lower() for s in result["mirror"])

    def test_mirror_signals_from_enrichment(self):
        data = _sample_response()
        data["_mirror_signals"] = ["Your reports show low variance"]
        result = _format_mirror(data, saved_trust_tier=None)
        assert "Your reports show low variance" in result["mirror"]

    def test_kg_results_surfaced(self):
        data = _sample_response()
        data["_mirror_kg_results"] = [
            {"summary": "Coherence issue found", "agent_id": "AlvaNoto", "relevance": 0.42}
        ]
        result = _format_mirror(data, saved_trust_tier=None)
        assert "relevant_prior_work" in result
        assert result["relevant_prior_work"][0]["by"] == "AlvaNoto"

    def test_question_prompt(self):
        data = _sample_response()
        data["_mirror_question"] = "What changed in your understanding?"
        result = _format_mirror(data, saved_trust_tier=None)
        assert result["question"] == "What changed in your understanding?"

    def test_legacy_reflection_prompt_supported(self):
        data = _sample_response()
        data["_mirror_reflection"] = "What changed in your understanding?"
        result = _format_mirror(data, saved_trust_tier=None)
        assert result["question"] == "What changed in your understanding?"

    def test_trust_tier_included(self):
        data = _sample_response()
        result = _format_mirror(data, saved_trust_tier="established")
        assert result["trust_tier"] == "established"

    def test_thread_context_preserved(self):
        data = _sample_response()
        data["thread_context"] = {"thread_id": "t123", "position": 2}
        result = _format_mirror(data, saved_trust_tier=None)
        assert result["thread_context"]["thread_id"] == "t123"

    def test_no_signals_gives_steady_state(self):
        data = _sample_response()
        # No enrichment data, no calibration, no divergence, no capping, no restorative
        data.pop("learning_context", None)
        data.pop("calibration_feedback", None)
        data.pop("confidence_reliability", None)
        data.pop("continuity", None)
        data.pop("restorative", None)
        data.pop("relevant_discoveries", None)
        data.pop("_mirror_question", None)
        data.pop("_mirror_reflection", None)
        result = _format_mirror(data, saved_trust_tier=None)
        assert "steady state" in result["mirror"][0].lower()
        assert "question" not in result

    def test_margin_included_when_tight(self):
        data = _sample_response()
        data["decision"]["margin"] = 0.05
        result = _format_mirror(data, saved_trust_tier=None)
        assert result["margin"] == 0.05

    def test_margin_excluded_when_comfortable(self):
        data = _sample_response()
        data["decision"]["margin"] = 0.2
        result = _format_mirror(data, saved_trust_tier=None)
        assert "margin" not in result

    def test_identity_notifications_surfaced(self):
        data = _sample_response()
        data["_identity_notifications"] = [{"message": "Identity accessed from new session"}]
        result = _format_mirror(data, saved_trust_tier=None)
        assert "identity_notifications" in result

    def test_observed_confidence_surfaced(self):
        data = _sample_response()
        data["confidence_reliability"] = {
            "source": "observed",
        }
        result = _format_mirror(data, saved_trust_tier=None)
        assert any("derived" in s.lower() for s in result["mirror"])

    def test_continuity_divergence_surfaced(self):
        data = _sample_response()
        data["continuity"] = {
            "self_reported_complexity": 0.7,
            "derived_complexity": 0.22,
            "complexity_divergence": 0.48,
        }
        result = _format_mirror(data, saved_trust_tier=None)
        assert any("complexity=0.70" in s for s in result["mirror"])
        assert any("0.22" in s for s in result["mirror"])

    def test_continuity_takes_precedence_over_calibration_feedback(self):
        data = _sample_response()
        data["continuity"] = {
            "self_reported_complexity": 0.7,
            "derived_complexity": 0.22,
            "complexity_divergence": 0.48,
        }
        data["calibration_feedback"] = {
            "complexity": {"reported": 0.8, "derived": 0.28, "discrepancy": 0.52}
        }
        result = _format_mirror(data, saved_trust_tier=None)
        # Should use continuity (0.7/0.22), not calibration_feedback (0.8/0.28)
        assert any("complexity=0.70" in s for s in result["mirror"])

    def test_restorative_action_surfaced(self):
        data = _sample_response()
        data["restorative"] = {
            "needs_restoration": True,
            "reason": "complexity divergence pattern (0.48 cumulative)",
        }
        result = _format_mirror(data, saved_trust_tier=None)
        assert any("restorative" in s.lower() for s in result["mirror"])

    def test_existing_discoveries_merged_into_prior_work(self):
        data = _sample_response()
        data["relevant_discoveries"] = [
            {"summary": "Inverted U curve in calibration", "agent_id": "Alva_Noto", "score": 0.85}
        ]
        result = _format_mirror(data, saved_trust_tier=None)
        assert "relevant_prior_work" in result
        assert result["relevant_prior_work"][0]["summary"] == "Inverted U curve in calibration"

    def test_calibration_feedback_fallback_when_no_continuity(self):
        """calibration_feedback is used when continuity data is absent."""
        data = _sample_response()
        data["calibration_feedback"] = {
            "complexity": {"reported": 0.8, "derived": 0.28, "discrepancy": 0.52}
        }
        result = _format_mirror(data, saved_trust_tier=None)
        assert any("complexity=0.80" in s for s in result["mirror"])

    def test_complexity_divergence_suppressed_early(self):
        """With meta.total_updates <= 3, complexity divergence is suppressed."""
        data = _sample_response()
        data["continuity"] = {
            "self_reported_complexity": 0.7,
            "derived_complexity": 0.22,
            "complexity_divergence": 0.48,
        }
        data["calibration_feedback"] = {
            "complexity": {"reported": 0.8, "derived": 0.28, "discrepancy": 0.52}
        }
        meta = MagicMock()
        meta.total_updates = 1
        result = _format_mirror(data, saved_trust_tier=None, meta=meta)
        # No complexity divergence signals should appear
        for s in result["mirror"]:
            assert "complexity=" not in s, f"Unexpected complexity signal on early check-in: {s}"

    def test_complexity_divergence_shown_after_baseline(self):
        """With meta.total_updates > 3, complexity divergence appears normally."""
        data = _sample_response()
        data["continuity"] = {
            "self_reported_complexity": 0.7,
            "derived_complexity": 0.22,
            "complexity_divergence": 0.48,
        }
        meta = MagicMock()
        meta.total_updates = 10
        result = _format_mirror(data, saved_trust_tier=None, meta=meta)
        assert any("complexity=0.70" in s for s in result["mirror"])


class TestFormatResponseMirror:

    def test_explicit_mirror_mode(self):
        data = _sample_response()
        result = format_response(data, {"response_mode": "mirror"})
        assert result["_mode"] == "mirror"

    def test_auto_selects_mirror_for_disembodied(self):
        data = _sample_response()
        data["health_status"] = "healthy"
        data["_has_sensor_data"] = False
        result = format_response(data, {"response_mode": "auto"})
        assert result["_mode"] == "mirror"

    def test_auto_selects_minimal_for_embodied(self):
        data = _sample_response()
        data["health_status"] = "healthy"
        data["_has_sensor_data"] = True
        result = format_response(data, {"response_mode": "auto"})
        assert result["_mode"] == "minimal"

    def test_strip_context_applied_for_mirror(self):
        data = _sample_response()
        result = format_response(data, {"response_mode": "mirror"}, is_new_agent=False)
        assert "eisv_labels" not in result
