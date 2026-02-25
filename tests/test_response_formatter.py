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
        "sampling_params": {"temperature": 0.7},
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

    def test_preserves_learning_context_for_new_agent(self):
        data = _sample_response()
        _strip_context(data, is_new_agent=True, key_was_generated=False, api_key_auto_retrieved=False)
        assert "learning_context" in data
        assert "onboarding" in data

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

    def test_auto_mode_healthy_becomes_minimal(self):
        data = _sample_response()
        data["health_status"] = "healthy"
        result = format_response(data, {"response_mode": "auto"})
        assert result["_mode"] == "minimal"

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
