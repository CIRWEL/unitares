"""
Tests for src/mcp_handlers/validators.py - Parameter validation and coercion.

Focuses on pure/near-pure functions. Skips _format_param_error (integration).
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.validators import (
    apply_param_aliases,
    _apply_generic_coercion,
    validate_and_coerce_params,
    _levenshtein_distance,
    _find_closest_match,
    validate_enum,
    validate_discovery_type,
    validate_severity,
    validate_discovery_status,
    validate_task_type,
    validate_response_type,
    validate_lifecycle_status,
    validate_health_status,
    validate_discovery_id,
    validate_range,
    validate_response_text,
    validate_complexity,
    validate_confidence,
    validate_ethical_drift,
    sanitize_agent_name,
    validate_agent_id_format,
    validate_agent_id_policy,
    validate_agent_id_reserved_names,
    detect_script_creation_avoidance,
    PARAM_ALIASES,
    DISCOVERY_TYPE_ALIASES,
    DISCOVERY_TYPES,
    SEVERITY_LEVELS,
)


# ============================================================================
# apply_param_aliases - PURE
# ============================================================================

class TestApplyParamAliases:

    def test_no_aliases_for_unknown_tool(self):
        result = apply_param_aliases("unknown_tool", {"foo": "bar"})
        assert result == {"foo": "bar"}

    def test_store_knowledge_graph_content_to_summary(self):
        result = apply_param_aliases("store_knowledge_graph", {"content": "hello"})
        assert result == {"summary": "hello"}

    def test_store_knowledge_graph_type_to_discovery_type(self):
        result = apply_param_aliases("store_knowledge_graph", {"type": "bug"})
        assert result == {"discovery_type": "bug"}

    def test_leave_note_text_to_summary(self):
        result = apply_param_aliases("leave_note", {"text": "my note"})
        assert result == {"summary": "my note"}

    def test_search_knowledge_graph_search_to_query(self):
        result = apply_param_aliases("search_knowledge_graph", {"search": "auth bug"})
        assert result == {"query": "auth bug"}

    def test_process_agent_update_text_to_response_text(self):
        result = apply_param_aliases("process_agent_update", {"text": "working on auth"})
        assert result == {"response_text": "working on auth"}

    def test_identity_label_to_name(self):
        result = apply_param_aliases("identity", {"label": "my_agent"})
        assert result == {"name": "my_agent"}

    def test_canonical_name_passes_through(self):
        result = apply_param_aliases("store_knowledge_graph", {"summary": "hello"})
        assert result == {"summary": "hello"}

    def test_mixed_alias_and_canonical(self):
        result = apply_param_aliases("store_knowledge_graph", {
            "content": "hello",
            "severity": "high"
        })
        assert result == {"summary": "hello", "severity": "high"}


# ============================================================================
# _apply_generic_coercion - PURE
# ============================================================================

class TestApplyGenericCoercion:

    def test_empty_args(self):
        assert _apply_generic_coercion({}) == {}

    def test_none_args(self):
        assert _apply_generic_coercion(None) is None

    def test_float_01_from_string(self):
        result = _apply_generic_coercion({"complexity": "0.7"})
        assert result["complexity"] == 0.7

    def test_float_01_clamped_high(self):
        result = _apply_generic_coercion({"complexity": "1.5"})
        assert result["complexity"] == 1.0

    def test_float_01_clamped_low(self):
        result = _apply_generic_coercion({"complexity": "-0.5"})
        assert result["complexity"] == 0.0

    def test_float_01_from_int(self):
        result = _apply_generic_coercion({"confidence": 1})
        assert result["confidence"] == 1.0

    def test_float_no_range(self):
        result = _apply_generic_coercion({"max_age_days": "7.5"})
        assert result["max_age_days"] == 7.5

    def test_int_from_string(self):
        result = _apply_generic_coercion({"limit": "10"})
        assert result["limit"] == 10

    def test_int_from_float_string(self):
        """Handles "5.0" -> 5."""
        result = _apply_generic_coercion({"limit": "5.0"})
        assert result["limit"] == 5

    def test_int_from_float(self):
        result = _apply_generic_coercion({"limit": 5.0})
        assert result["limit"] == 5

    def test_bool_true_strings(self):
        for val in ("true", "yes", "1", "True", "YES"):
            result = _apply_generic_coercion({"lite": val})
            assert result["lite"] is True, f"Failed for {val}"

    def test_bool_false_strings(self):
        for val in ("false", "no", "0", "False", "NO", ""):
            result = _apply_generic_coercion({"lite": val})
            assert result["lite"] is False, f"Failed for {val}"

    def test_bool_already_bool(self):
        result = _apply_generic_coercion({"lite": True})
        assert result["lite"] is True

    def test_bool_from_int(self):
        result = _apply_generic_coercion({"lite": 1})
        assert result["lite"] is True
        result = _apply_generic_coercion({"lite": 0})
        assert result["lite"] is False

    def test_none_value_skipped(self):
        result = _apply_generic_coercion({"complexity": None})
        assert result["complexity"] is None

    def test_unknown_param_unchanged(self):
        result = _apply_generic_coercion({"custom_param": "hello"})
        assert result["custom_param"] == "hello"

    def test_invalid_float_string_unchanged(self):
        result = _apply_generic_coercion({"complexity": "not_a_number"})
        assert result["complexity"] == "not_a_number"


# ============================================================================
# _levenshtein_distance - PURE
# ============================================================================

class TestLevenshteinDistance:

    def test_identical_strings(self):
        assert _levenshtein_distance("hello", "hello") == 0

    def test_empty_strings(self):
        assert _levenshtein_distance("", "") == 0

    def test_one_empty(self):
        assert _levenshtein_distance("abc", "") == 3
        assert _levenshtein_distance("", "abc") == 3

    def test_single_insertion(self):
        assert _levenshtein_distance("abc", "abcd") == 1

    def test_single_deletion(self):
        assert _levenshtein_distance("abcd", "abc") == 1

    def test_single_substitution(self):
        assert _levenshtein_distance("abc", "axc") == 1

    def test_transposition(self):
        # Levenshtein treats transposition as 2 operations
        assert _levenshtein_distance("ab", "ba") == 2

    def test_completely_different(self):
        assert _levenshtein_distance("abc", "xyz") == 3

    def test_symmetric(self):
        d1 = _levenshtein_distance("kitten", "sitting")
        d2 = _levenshtein_distance("sitting", "kitten")
        assert d1 == d2


# ============================================================================
# _find_closest_match - PURE
# ============================================================================

class TestFindClosestMatch:

    def test_exact_match(self):
        result = _find_closest_match("insight", {"insight", "bug_found", "note"})
        assert result == "insight"

    def test_typo_match(self):
        result = _find_closest_match("insigt", {"insight", "bug_found", "note"})
        assert result == "insight"

    def test_no_match_too_far(self):
        result = _find_closest_match("zzzzzzz", {"insight", "bug_found", "note"})
        assert result is None

    def test_case_insensitive(self):
        result = _find_closest_match("INSIGHT", {"insight", "bug_found"})
        assert result == "insight"

    def test_best_of_multiple(self):
        result = _find_closest_match("not", {"note", "notification", "nothing"})
        assert result == "note"  # Closest

    def test_custom_max_distance(self):
        result = _find_closest_match("abcdef", {"abcxyz"}, max_distance=1)
        assert result is None
        result = _find_closest_match("abcdef", {"abcxyz"}, max_distance=5)
        assert result == "abcxyz"


# ============================================================================
# validate_enum - Light mock (calls error_response)
# ============================================================================

class TestValidateEnum:

    def test_valid_value(self):
        val, err = validate_enum("high", SEVERITY_LEVELS, "severity")
        assert val == "high"
        assert err is None

    def test_none_allowed(self):
        val, err = validate_enum(None, SEVERITY_LEVELS, "severity")
        assert val is None
        assert err is None

    def test_invalid_value_returns_error(self):
        val, err = validate_enum("extreme", SEVERITY_LEVELS, "severity")
        assert val is None
        assert err is not None

    def test_invalid_with_suggestions(self):
        val, err = validate_enum("med", SEVERITY_LEVELS, "severity", ["medium"])
        assert val is None
        assert err is not None


# ============================================================================
# validate_discovery_type - Alias resolution + fuzzy matching
# ============================================================================

class TestValidateDiscoveryType:

    def test_exact_match(self):
        val, err = validate_discovery_type("insight")
        assert val == "insight"
        assert err is None

    def test_case_insensitive(self):
        val, err = validate_discovery_type("INSIGHT")
        assert val == "insight"
        assert err is None

    def test_alias_bug(self):
        val, err = validate_discovery_type("bug")
        assert val == "bug_found"
        assert err is None

    def test_alias_implementation(self):
        val, err = validate_discovery_type("implementation")
        assert val == "improvement"
        assert err is None

    def test_alias_observation(self):
        val, err = validate_discovery_type("observation")
        assert val == "insight"
        assert err is None

    def test_alias_experiment(self):
        val, err = validate_discovery_type("experiment")
        assert val == "exploration"
        assert err is None

    def test_alias_memo(self):
        val, err = validate_discovery_type("memo")
        assert val == "note"
        assert err is None

    def test_none_allowed(self):
        val, err = validate_discovery_type(None)
        assert val is None
        assert err is None

    def test_typo_suggestion(self):
        """Close typo should return error with suggestion."""
        val, err = validate_discovery_type("insigt")
        assert val is None
        assert err is not None  # Should suggest "insight"

    def test_completely_invalid(self):
        val, err = validate_discovery_type("zzzzzzz")
        assert val is None
        assert err is not None

    def test_all_discovery_type_aliases(self):
        """Every alias should resolve to a valid type."""
        for alias, canonical in DISCOVERY_TYPE_ALIASES.items():
            val, err = validate_discovery_type(alias)
            assert val == canonical, f"Alias '{alias}' should resolve to '{canonical}', got '{val}'"
            assert err is None


# ============================================================================
# Enum wrapper validators
# ============================================================================

class TestEnumWrappers:

    def test_validate_severity_valid(self):
        val, err = validate_severity("high")
        assert val == "high"

    def test_validate_severity_invalid(self):
        val, err = validate_severity("extreme")
        assert val is None
        assert err is not None

    def test_validate_discovery_status(self):
        val, err = validate_discovery_status("open")
        assert val == "open"

    def test_validate_task_type(self):
        val, err = validate_task_type("convergent")
        assert val == "convergent"

    def test_validate_response_type(self):
        val, err = validate_response_type("question")
        assert val == "question"

    def test_validate_lifecycle_status(self):
        val, err = validate_lifecycle_status("active")
        assert val == "active"

    def test_validate_health_status(self):
        val, err = validate_health_status("healthy")
        assert val == "healthy"


# ============================================================================
# validate_discovery_id
# ============================================================================

class TestValidateDiscoveryId:

    def test_valid_iso_timestamp(self):
        val, err = validate_discovery_id("2025-12-13T01:23:45.678901")
        assert val == "2025-12-13T01:23:45.678901"
        assert err is None

    def test_valid_simple_string(self):
        val, err = validate_discovery_id("my-discovery-123")
        assert val == "my-discovery-123"
        assert err is None

    def test_none_returns_error(self):
        val, err = validate_discovery_id(None)
        assert val is None
        assert err is not None

    def test_non_string_returns_error(self):
        val, err = validate_discovery_id(12345)
        assert val is None
        assert err is not None

    def test_empty_string_returns_error(self):
        val, err = validate_discovery_id("")
        assert val is None
        assert err is not None

    def test_whitespace_only_returns_error(self):
        val, err = validate_discovery_id("   ")
        assert val is None
        assert err is not None

    def test_too_long_returns_error(self):
        val, err = validate_discovery_id("x" * 201)
        assert val is None
        assert err is not None

    def test_exactly_200_chars_ok(self):
        val, err = validate_discovery_id("x" * 200)
        assert val is not None
        assert err is None

    def test_invalid_chars_returns_error(self):
        val, err = validate_discovery_id("id with spaces")
        assert val is None
        assert err is not None

    def test_injection_attempt_blocked(self):
        val, err = validate_discovery_id("'; DROP TABLE --")
        assert val is None
        assert err is not None


# ============================================================================
# validate_range
# ============================================================================

class TestValidateRange:

    def test_valid_in_range(self):
        val, err = validate_range(0.5, 0.0, 1.0, "test")
        assert val == 0.5
        assert err is None

    def test_at_min_inclusive(self):
        val, err = validate_range(0.0, 0.0, 1.0, "test")
        assert val == 0.0

    def test_at_max_inclusive(self):
        val, err = validate_range(1.0, 0.0, 1.0, "test")
        assert val == 1.0

    def test_below_min(self):
        val, err = validate_range(-0.1, 0.0, 1.0, "test")
        assert val is None
        assert err is not None

    def test_above_max(self):
        val, err = validate_range(1.1, 0.0, 1.0, "test")
        assert val is None
        assert err is not None

    def test_none_allowed(self):
        val, err = validate_range(None, 0.0, 1.0, "test")
        assert val is None
        assert err is None

    def test_string_coercion(self):
        val, err = validate_range("0.5", 0.0, 1.0, "test")
        assert val == 0.5

    def test_non_numeric_error(self):
        val, err = validate_range("abc", 0.0, 1.0, "test")
        assert val is None
        assert err is not None

    def test_exclusive_range(self):
        val, err = validate_range(0.5, 0.0, 1.0, "test", inclusive=False)
        assert val == 0.5

    def test_exclusive_at_boundary_fails(self):
        val, err = validate_range(0.0, 0.0, 1.0, "test", inclusive=False)
        assert val is None
        assert err is not None


# ============================================================================
# validate_response_text
# ============================================================================

class TestValidateResponseText:

    def test_valid_string(self):
        val, err = validate_response_text("hello world")
        assert val == "hello world"
        assert err is None

    def test_none_returns_empty(self):
        val, err = validate_response_text(None)
        assert val == ""
        assert err is None

    def test_non_string_error(self):
        val, err = validate_response_text(12345)
        assert val is None
        assert err is not None

    def test_too_long(self):
        val, err = validate_response_text("x" * 60000)
        assert val is None
        assert err is not None

    def test_custom_max_length(self):
        val, err = validate_response_text("hello", max_length=3)
        assert val is None
        assert err is not None

    def test_at_max_length_ok(self):
        val, err = validate_response_text("hello", max_length=5)
        assert val == "hello"


# ============================================================================
# validate_complexity / validate_confidence - Wrappers
# ============================================================================

class TestValidateComplexityConfidence:

    def test_valid_complexity(self):
        val, err = validate_complexity(0.5)
        assert val == 0.5

    def test_complexity_out_of_range(self):
        val, err = validate_complexity(1.5)
        assert val is None

    def test_valid_confidence(self):
        val, err = validate_confidence(0.8)
        assert val == 0.8


# ============================================================================
# validate_ethical_drift
# ============================================================================

class TestValidateEthicalDrift:

    def test_valid_drift(self):
        val, err = validate_ethical_drift([0.01, 0.02, 0.03])
        assert val == [0.01, 0.02, 0.03]
        assert err is None

    def test_none_allowed(self):
        val, err = validate_ethical_drift(None)
        assert val is None
        assert err is None

    def test_not_list_error(self):
        val, err = validate_ethical_drift("not a list")
        assert val is None
        assert err is not None

    def test_wrong_length(self):
        val, err = validate_ethical_drift([0.01, 0.02])
        assert val is None
        assert err is not None

    def test_component_out_of_range(self):
        val, err = validate_ethical_drift([0.01, 2.0, 0.03])
        assert val is None
        assert err is not None


# ============================================================================
# sanitize_agent_name - PURE
# ============================================================================

class TestSanitizeAgentName:

    def test_valid_name_unchanged(self):
        assert sanitize_agent_name("my_agent_2025") == "my_agent_2025"

    def test_spaces_to_underscores(self):
        assert sanitize_agent_name("ChatGPT macOS app") == "ChatGPT_macOS_app"

    def test_special_chars_replaced(self):
        result = sanitize_agent_name("my agent!!!")
        assert "!" not in result
        assert result == "my_agent"

    def test_collapses_underscores(self):
        result = sanitize_agent_name("a   b   c")
        assert "__" not in result

    def test_strips_leading_trailing(self):
        result = sanitize_agent_name("_agent_")
        assert not result.startswith("_")
        assert not result.endswith("_")

    def test_empty_generates_auto(self):
        result = sanitize_agent_name("")
        assert result.startswith("agent_")

    def test_none_like_empty(self):
        """None is falsy, should generate auto."""
        result = sanitize_agent_name(None)
        assert result.startswith("agent_")

    def test_too_short_after_cleaning(self):
        result = sanitize_agent_name("!!")
        assert result.startswith("agent_")

    def test_hyphens_preserved(self):
        assert sanitize_agent_name("my-agent") == "my-agent"


# ============================================================================
# validate_agent_id_format
# ============================================================================

class TestValidateAgentIdFormat:

    def test_valid_id(self):
        val, err = validate_agent_id_format("my_agent_2025")
        assert val == "my_agent_2025"
        assert err is None

    def test_sanitizes_bad_chars(self):
        val, err = validate_agent_id_format("my agent!!!")
        assert " " not in val
        assert "!" not in val
        assert err is None


# ============================================================================
# validate_agent_id_policy - No-op
# ============================================================================

class TestValidateAgentIdPolicy:

    def test_always_passes(self):
        val, err = validate_agent_id_policy("test_agent")
        assert err is None

    def test_passes_anything(self):
        val, err = validate_agent_id_policy("demo_whatever")
        assert err is None


# ============================================================================
# validate_agent_id_reserved_names
# ============================================================================

class TestValidateAgentIdReservedNames:

    def test_normal_id_passes(self):
        val, err = validate_agent_id_reserved_names("my_agent_2025")
        assert val == "my_agent_2025"
        assert err is None

    def test_none_passes(self):
        val, err = validate_agent_id_reserved_names(None)
        assert val is None
        assert err is None

    def test_reserved_system(self):
        val, err = validate_agent_id_reserved_names("system")
        assert val is None
        assert err is not None

    def test_reserved_admin(self):
        val, err = validate_agent_id_reserved_names("admin")
        assert val is None
        assert err is not None

    def test_reserved_case_insensitive(self):
        val, err = validate_agent_id_reserved_names("SYSTEM")
        assert val is None
        assert err is not None

    def test_reserved_prefix_system(self):
        val, err = validate_agent_id_reserved_names("system_override")
        assert val is None
        assert err is not None

    def test_reserved_prefix_admin(self):
        val, err = validate_agent_id_reserved_names("admin_tool")
        assert val is None
        assert err is not None

    def test_non_reserved_with_system_in_name(self):
        """'my_system_agent' should pass (system_ is prefix, not substring)."""
        val, err = validate_agent_id_reserved_names("my_system_agent")
        assert val == "my_system_agent"
        assert err is None


# ============================================================================
# detect_script_creation_avoidance - PURE
# ============================================================================

class TestDetectScriptCreationAvoidance:

    def test_normal_text_no_warnings(self):
        warnings = detect_script_creation_avoidance("I'm working on the auth module")
        assert warnings == []

    def test_empty_text_no_warnings(self):
        assert detect_script_creation_avoidance("") == []
        assert detect_script_creation_avoidance(None) == []

    def test_creating_test_script(self):
        warnings = detect_script_creation_avoidance("I'm creating a script to test the function")
        assert len(warnings) >= 1
        assert "AVOIDANCE" in warnings[0]

    def test_writing_quick_script(self):
        warnings = detect_script_creation_avoidance("Let me write a quick script to verify")
        assert len(warnings) >= 1

    def test_avoiding_mcp(self):
        warnings = detect_script_creation_avoidance("We should avoid the MCP tools")
        assert len(warnings) >= 1
        assert "AVOIDANCE LANGUAGE" in warnings[0]

    def test_bypassing_tools(self):
        warnings = detect_script_creation_avoidance("instead of calling the tools directly")
        assert len(warnings) >= 1

    def test_standalone_py_file(self):
        warnings = detect_script_creation_avoidance("I'm creating test_auth.py to test the auth flow")
        assert len(warnings) >= 1
        assert "STANDALONE" in warnings[0]

    def test_py_file_in_tests_dir_ok(self):
        """Creating .py in tests/ should NOT trigger warning."""
        warnings = detect_script_creation_avoidance("I'm creating tests/test_auth.py for testing")
        assert not any("STANDALONE" in w for w in warnings)


# ============================================================================
# validate_and_coerce_params - Integration of aliases + coercion + schema
# ============================================================================

class TestValidateAndCoerceParams:

    def test_unknown_tool_still_coerces(self):
        """Tools without schema still get generic coercion."""
        result, err, fixes = validate_and_coerce_params("unknown_tool", {"complexity": "0.5"})
        assert result["complexity"] == 0.5
        assert err is None

    def test_process_agent_update_coerces_complexity(self):
        result, err, fixes = validate_and_coerce_params("process_agent_update", {"complexity": "0.7"})
        assert err is None
        assert isinstance(result["complexity"], float)

    def test_process_agent_update_coerces_bool(self):
        result, err, fixes = validate_and_coerce_params("process_agent_update", {"lite": "true"})
        assert err is None
        assert result["lite"] is True

    def test_applies_aliases_before_validation(self):
        result, err, fixes = validate_and_coerce_params("store_knowledge_graph", {
            "content": "found a bug",
            "type": "bug"
        })
        assert err is None
        # "content" -> "summary", "type" -> "discovery_type"
        assert "summary" in result

    def test_store_knowledge_graph_missing_summary(self):
        result, err, fixes = validate_and_coerce_params("store_knowledge_graph", {})
        assert err is not None  # summary is required

    def test_enum_case_fix(self):
        result, err, fixes = validate_and_coerce_params("process_agent_update", {
            "task_type": "Convergent"
        })
        assert err is None
        assert result["task_type"] == "convergent"

    def test_list_from_comma_string(self):
        result, err, fixes = validate_and_coerce_params("store_knowledge_graph", {
            "summary": "test",
            "tags": "auth,security,bug"
        })
        assert err is None
        assert result["tags"] == ["auth", "security", "bug"]

    def test_list_from_single_string(self):
        result, err, fixes = validate_and_coerce_params("store_knowledge_graph", {
            "summary": "test",
            "tags": "auth"
        })
        assert err is None
        assert result["tags"] == ["auth"]

    def test_discovery_type_alias_in_schema(self):
        result, err, fixes = validate_and_coerce_params("store_knowledge_graph", {
            "summary": "test",
            "discovery_type": "bug"
        })
        assert err is None
        assert result["discovery_type"] == "bug_found"
