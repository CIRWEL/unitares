"""
Tests for pure functions in src/mcp_handlers/utils.py.

Tests _infer_error_code_and_category, _make_json_serializable,
_sanitize_error_message, and generate_actionable_feedback.
"""

import pytest
import json
import numpy as np
import sys
from pathlib import Path
from datetime import datetime, date
from enum import Enum

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.utils import (
    _infer_error_code_and_category,
    _make_json_serializable,
    _sanitize_error_message,
    generate_actionable_feedback,
    format_metrics_text,
)


# ============================================================================
# _infer_error_code_and_category
# ============================================================================

class TestInferErrorCodeAndCategory:

    def test_not_found(self):
        code, cat = _infer_error_code_and_category("Agent 'x' not found")
        assert code == "NOT_FOUND"
        assert cat == "validation_error"

    def test_does_not_exist(self):
        code, cat = _infer_error_code_and_category("Resource does not exist")
        assert code == "NOT_FOUND"

    def test_missing_required(self):
        code, cat = _infer_error_code_and_category("Missing required parameter: summary")
        assert code == "MISSING_REQUIRED"
        assert cat == "validation_error"

    def test_invalid_param(self):
        code, cat = _infer_error_code_and_category("Invalid complexity value")
        assert code == "INVALID_PARAM"

    def test_permission_denied(self):
        code, cat = _infer_error_code_and_category("Permission denied for this operation")
        assert code == "PERMISSION_DENIED"
        assert cat == "auth_error"

    def test_timeout(self):
        code, cat = _infer_error_code_and_category("Request timed out")
        assert code == "TIMEOUT"
        assert cat == "system_error"

    def test_database_error(self):
        code, cat = _infer_error_code_and_category("Database query error")
        assert code == "DATABASE_ERROR"
        assert cat == "system_error"

    def test_paused_agent(self):
        code, cat = _infer_error_code_and_category("Agent is paused")
        assert code == "AGENT_PAUSED"
        assert cat == "state_error"

    def test_no_match(self):
        code, cat = _infer_error_code_and_category("Something completely generic")
        assert code is None
        assert cat is None

    def test_case_insensitive(self):
        code, cat = _infer_error_code_and_category("PERMISSION DENIED")
        assert code == "PERMISSION_DENIED"

    def test_already_exists(self):
        code, _ = _infer_error_code_and_category("Agent already exists")
        assert code == "ALREADY_EXISTS"

    def test_too_long(self):
        code, _ = _infer_error_code_and_category("Response text too long")
        assert code == "VALUE_TOO_LARGE"

    def test_empty_value(self):
        code, _ = _infer_error_code_and_category("Field cannot be empty")
        assert code == "EMPTY_VALUE"


# ============================================================================
# _make_json_serializable
# ============================================================================

class TestMakeJsonSerializable:

    def test_none(self):
        assert _make_json_serializable(None) is None

    def test_string(self):
        assert _make_json_serializable("hello") == "hello"

    def test_int(self):
        assert _make_json_serializable(42) == 42

    def test_float(self):
        assert _make_json_serializable(3.14) == 3.14

    def test_bool(self):
        assert _make_json_serializable(True) is True

    def test_numpy_float64(self):
        val = np.float64(3.14)
        result = _make_json_serializable(val)
        assert isinstance(result, float)
        assert result == pytest.approx(3.14)

    def test_numpy_int64(self):
        val = np.int64(42)
        result = _make_json_serializable(val)
        assert isinstance(result, int)
        assert result == 42

    def test_numpy_bool(self):
        val = np.bool_(True)
        result = _make_json_serializable(val)
        assert isinstance(result, bool)
        assert result is True

    def test_numpy_array(self):
        arr = np.array([1.0, 2.0, 3.0])
        result = _make_json_serializable(arr)
        assert isinstance(result, list)
        assert len(result) == 3

    def test_datetime(self):
        dt = datetime(2026, 1, 15, 12, 30)
        result = _make_json_serializable(dt)
        assert isinstance(result, str)
        assert "2026" in result

    def test_date(self):
        d = date(2026, 1, 15)
        result = _make_json_serializable(d)
        assert isinstance(result, str)
        assert "2026" in result

    def test_enum(self):
        class Color(Enum):
            RED = "red"
        result = _make_json_serializable(Color.RED)
        assert result == "red"

    def test_dict_recursive(self):
        d = {"a": np.float64(1.0), "b": {"c": np.int64(2)}}
        result = _make_json_serializable(d)
        assert isinstance(result["a"], float)
        assert isinstance(result["b"]["c"], int)

    def test_list_recursive(self):
        lst = [np.float64(1.0), np.int64(2), "three"]
        result = _make_json_serializable(lst)
        assert isinstance(result[0], float)
        assert isinstance(result[1], int)
        assert result[2] == "three"

    def test_set(self):
        s = {1, 2, 3}
        result = _make_json_serializable(s)
        assert isinstance(result, list)
        assert len(result) == 3

    def test_large_list_truncated(self):
        lst = list(range(200))
        result = _make_json_serializable(lst)
        assert len(result) == 101  # 100 items + "... (100 more items)"
        assert "more items" in result[-1]

    def test_large_set_truncated(self):
        s = set(range(200))
        result = _make_json_serializable(s)
        assert len(result) == 101

    def test_tuple(self):
        t = (1, 2, 3)
        result = _make_json_serializable(t)
        assert isinstance(result, list)

    def test_unknown_type_to_string(self):
        class Custom:
            def __str__(self):
                return "custom_value"
        result = _make_json_serializable(Custom())
        assert result == "custom_value"

    def test_result_is_json_serializable(self):
        """Complex nested structure should be fully serializable"""
        d = {
            "arr": np.array([1.0, 2.0]),
            "nested": {"val": np.float64(3.14)},
            "dt": datetime(2026, 1, 1),
        }
        result = _make_json_serializable(d)
        # Should not raise
        json.dumps(result)


# ============================================================================
# _sanitize_error_message
# ============================================================================

class TestSanitizeErrorMessage:

    def test_simple_message_unchanged(self):
        msg = "Agent not found"
        result = _sanitize_error_message(msg)
        assert "Agent not found" in result

    def test_removes_file_paths(self):
        msg = "Error in /Users/cirwel/projects/governance-mcp-v1/src/foo.py"
        result = _sanitize_error_message(msg)
        assert "/Users/cirwel" not in result
        assert "foo.py" in result

    def test_removes_line_numbers(self):
        msg = 'File "test.py", line 42, in test_func'
        result = _sanitize_error_message(msg)
        assert "line 42" not in result

    def test_removes_internal_module_paths(self):
        msg = "Error in src.mcp_handlers.utils.some_func"
        result = _sanitize_error_message(msg)
        assert "src.mcp_handlers.utils." not in result

    def test_cleans_double_spaces(self):
        msg = "Error  occurred   here"
        result = _sanitize_error_message(msg)
        assert "  " not in result

    def test_non_string_input(self):
        result = _sanitize_error_message(12345)
        assert result == "12345"

    def test_preserves_error_codes(self):
        msg = "AGENT_NOT_FOUND: Agent 'x' not found"
        result = _sanitize_error_message(msg)
        assert "AGENT_NOT_FOUND" in result


# ============================================================================
# generate_actionable_feedback
# ============================================================================

class TestGenerateActionableFeedback:

    def test_returns_list(self):
        result = generate_actionable_feedback({'coherence': 0.5, 'risk_score': 0.3})
        assert isinstance(result, list)

    def test_first_update_skips_coherence(self):
        """First update (updates=0) should not generate coherence feedback"""
        result = generate_actionable_feedback({'coherence': 0.3, 'updates': 0})
        coherence_msgs = [f for f in result if 'coherence' in f.lower()]
        assert len(coherence_msgs) == 0

    def test_low_coherence_exploration(self):
        """Low coherence in exploration regime → feedback"""
        result = generate_actionable_feedback({
            'coherence': 0.2, 'regime': 'exploration', 'updates': 5
        })
        assert len(result) >= 1
        assert any('coherence' in f.lower() or 'exploration' in f.lower() for f in result)

    def test_coherence_drop_detected(self):
        """Coherence drop → drop-specific feedback"""
        result = generate_actionable_feedback(
            {'coherence': 0.2, 'regime': 'exploration', 'updates': 5},
            previous_coherence=0.7
        )
        assert len(result) >= 1
        assert any('drop' in f.lower() for f in result)

    def test_stable_low_coherence_feedback(self):
        """Low coherence in stable regime → drift feedback"""
        result = generate_actionable_feedback({
            'coherence': 0.5, 'regime': 'stable', 'updates': 5
        })
        assert len(result) >= 1

    def test_high_risk_feedback(self):
        """risk_score > 0.7 → feedback"""
        result = generate_actionable_feedback({'risk_score': 0.8, 'updates': 5})
        assert len(result) >= 1
        assert any('complexity' in f.lower() or 'risk' in f.lower() for f in result)

    def test_high_risk_void_basin(self):
        result = generate_actionable_feedback(
            {'risk_score': 0.8, 'updates': 5},
            interpreted_state={'health': 'moderate', 'mode': 'building', 'basin': 'void'}
        )
        assert len(result) >= 1
        assert any('void' in f.lower() or 'mismatch' in f.lower() for f in result)

    def test_void_active_high_e(self):
        result = generate_actionable_feedback({
            'void_active': True, 'E': 0.8, 'I': 0.3, 'updates': 5
        })
        assert len(result) >= 1
        assert any('void' in f.lower() for f in result)

    def test_void_active_high_i(self):
        result = generate_actionable_feedback({
            'void_active': True, 'E': 0.3, 'I': 0.8, 'updates': 5
        })
        assert any('integrity' in f.lower() or 'energy' in f.lower() or 'void' in f.lower() for f in result)

    def test_confusion_pattern_detection(self):
        result = generate_actionable_feedback(
            {'updates': 5},
            response_text="I'm not sure how to approach this"
        )
        assert len(result) >= 1
        assert any('uncertainty' in f.lower() or 'sure' in f.lower() for f in result)

    def test_stuck_pattern_detection(self):
        result = generate_actionable_feedback(
            {'updates': 5},
            response_text="I'm stuck on this problem"
        )
        assert len(result) >= 1
        assert any('stuck' in f.lower() or 'rubber duck' in f.lower() for f in result)

    def test_overconfidence_detection(self):
        result = generate_actionable_feedback(
            {'coherence': 0.3, 'updates': 5},
            response_text="This is definitely the right approach"
        )
        assert any('confidence' in f.lower() or 'assumptions' in f.lower() for f in result)

    def test_empty_metrics(self):
        """Minimal metrics → no crash"""
        result = generate_actionable_feedback({})
        assert isinstance(result, list)

    def test_convergent_task_low_coherence(self):
        result = generate_actionable_feedback(
            {'coherence': 0.3, 'regime': 'transition', 'updates': 5},
            task_type='convergent'
        )
        assert any('convergent' in f.lower() or 'focusing' in f.lower() for f in result)

    def test_divergent_task_moderate_coherence(self):
        """Moderately low coherence for divergent work → less alarming"""
        result = generate_actionable_feedback(
            {'coherence': 0.4, 'regime': 'transition', 'updates': 5},
            task_type='divergent'
        )
        # 0.4 coherence in divergent should NOT trigger feedback (only < 0.35 does)
        divergent_msgs = [f for f in result if 'divergent' in f.lower()]
        assert len(divergent_msgs) == 0

    def test_moderate_risk_degraded_health(self):
        result = generate_actionable_feedback(
            {'risk_score': 0.6, 'updates': 5},
            interpreted_state={'health': 'degraded', 'mode': 'building', 'basin': 'high'}
        )
        assert any('checkpoint' in f.lower() or 'degraded' in f.lower() or 'complexity' in f.lower() for f in result)


# ============================================================================
# format_metrics_text
# ============================================================================

class TestFormatMetricsText:

    def test_returns_string(self):
        result = format_metrics_text({'agent_id': 'test'})
        assert isinstance(result, str)

    def test_agent_id_in_output(self):
        result = format_metrics_text({'agent_id': 'my-agent'})
        assert 'my-agent' in result

    def test_default_agent_id_unknown(self):
        result = format_metrics_text({})
        assert 'unknown' in result

    def test_timestamp_included(self):
        result = format_metrics_text({'timestamp': '2026-01-15T12:00:00'})
        assert '2026-01-15' in result

    def test_health_status(self):
        result = format_metrics_text({'health_status': 'healthy'})
        assert 'healthy' in result

    def test_eisv_nested_dict(self):
        result = format_metrics_text({'eisv': {'E': 0.5, 'I': 0.6, 'S': 0.1, 'V': 0.0}})
        assert 'E=0.500' in result
        assert 'I=0.600' in result
        assert 'S=0.100' in result
        assert 'V=0.000' in result

    def test_eisv_flat_keys(self):
        result = format_metrics_text({'E': 0.5, 'I': 0.6, 'S': 0.1, 'V': 0.0})
        assert 'E=0.500' in result

    def test_eisv_nested_takes_priority(self):
        """If both nested and flat exist, nested eisv dict is used"""
        result = format_metrics_text({
            'eisv': {'E': 0.9, 'I': 0.9, 'S': 0.0, 'V': 0.0},
            'E': 0.1, 'I': 0.1
        })
        assert 'E=0.900' in result

    def test_coherence_formatted(self):
        result = format_metrics_text({'coherence': 0.75})
        assert 'coherence: 0.750' in result

    def test_risk_score_formatted(self):
        result = format_metrics_text({'risk_score': 0.3})
        assert 'risk_score: 0.300' in result

    def test_string_value_not_formatted_as_float(self):
        result = format_metrics_text({'verdict': 'proceed'})
        assert 'verdict: proceed' in result

    def test_full_metrics(self):
        result = format_metrics_text({
            'agent_id': 'test-agent',
            'timestamp': '2026-01-15',
            'health_status': 'healthy',
            'eisv': {'E': 0.5, 'I': 0.6, 'S': 0.1, 'V': 0.0},
            'coherence': 0.8,
            'risk_score': 0.2,
        })
        assert 'test-agent' in result
        assert 'healthy' in result
        assert 'E=0.500' in result
        assert 'coherence: 0.800' in result
        assert 'risk_score: 0.200' in result

    def test_empty_metrics(self):
        result = format_metrics_text({})
        assert 'unknown' in result  # default agent_id
