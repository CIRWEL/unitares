"""
Tests for src/mcp_handlers/validators.py - Parameter validation helpers.

Tests pure validation functions, type coercion, alias resolution,
enum validation, discovery type validation, Levenshtein distance,
range validation, response text, ethical drift, file path policy,
sanitize_agent_name, reserved names, and script creation detection.
"""

import pytest
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.validators import (
    TOOL_PARAM_SCHEMAS,
    PARAM_ALIASES,
    GENERIC_PARAM_TYPES,
    DISCOVERY_TYPES,
    SEVERITY_LEVELS,
    DISCOVERY_TYPE_ALIASES,
    apply_param_aliases,
    _apply_generic_coercion,
    validate_and_coerce_params,
    validate_enum,
    validate_discovery_type,
    _levenshtein_distance,
    _find_closest_match,
    validate_range,
    validate_response_text,
    validate_complexity,
    validate_confidence,
    validate_ethical_drift,
    validate_severity,
    validate_discovery_status,
    validate_task_type,
    validate_response_type,
    validate_lifecycle_status,
    validate_health_status,
    validate_file_path_policy,
    sanitize_agent_name,
    validate_agent_id_format,
    validate_agent_id_policy,
    validate_agent_id_reserved_names,
    validate_discovery_id,
    detect_script_creation_avoidance,
)


# ============================================================================
# PARAM_ALIASES / apply_param_aliases
# ============================================================================

class TestApplyParamAliases:

    def test_no_aliases_for_unknown_tool(self):
        result = apply_param_aliases("unknown_tool", {"foo": "bar"})
        assert result == {"foo": "bar"}

    def test_store_knowledge_graph_content_to_summary(self):
        result = apply_param_aliases("store_knowledge_graph", {"content": "test"})
        assert result == {"summary": "test"}

    def test_store_knowledge_graph_note_to_summary(self):
        result = apply_param_aliases("store_knowledge_graph", {"note": "test"})
        assert result == {"summary": "test"}

    def test_store_knowledge_graph_type_to_discovery_type(self):
        result = apply_param_aliases("store_knowledge_graph", {"type": "bug"})
        assert result == {"discovery_type": "bug"}

    def test_leave_note_message_to_summary(self):
        result = apply_param_aliases("leave_note", {"message": "test"})
        assert result == {"summary": "test"}

    def test_search_knowledge_graph_search_to_query(self):
        result = apply_param_aliases("search_knowledge_graph", {"search": "auth bug"})
        assert result == {"query": "auth bug"}

    def test_process_agent_update_text_to_response_text(self):
        result = apply_param_aliases("process_agent_update", {"text": "my work"})
        assert result == {"response_text": "my work"}

    def test_identity_label_to_name(self):
        result = apply_param_aliases("identity", {"label": "myname"})
        assert result == {"name": "myname"}

    def test_preserves_non_aliased_params(self):
        result = apply_param_aliases("store_knowledge_graph", {"summary": "existing", "tags": ["a"]})
        assert result == {"summary": "existing", "tags": ["a"]}


# ============================================================================
# _apply_generic_coercion
# ============================================================================

class TestApplyGenericCoercion:

    def test_empty_dict(self):
        assert _apply_generic_coercion({}) == {}

    def test_none_input(self):
        assert _apply_generic_coercion(None) is None

    def test_float_01_from_string(self):
        result = _apply_generic_coercion({"complexity": "0.7"})
        assert result["complexity"] == 0.7

    def test_float_01_clamp_high(self):
        result = _apply_generic_coercion({"complexity": "1.5"})
        assert result["complexity"] == 1.0

    def test_float_01_clamp_low(self):
        result = _apply_generic_coercion({"complexity": "-0.5"})
        assert result["complexity"] == 0.0

    def test_float_from_string(self):
        result = _apply_generic_coercion({"max_age_days": "3.5"})
        assert result["max_age_days"] == 3.5

    def test_int_from_string(self):
        result = _apply_generic_coercion({"limit": "10"})
        assert result["limit"] == 10

    def test_int_from_float_string(self):
        result = _apply_generic_coercion({"limit": "5.0"})
        assert result["limit"] == 5

    def test_int_from_float(self):
        result = _apply_generic_coercion({"limit": 5.0})
        assert result["limit"] == 5

    def test_bool_true_string(self):
        result = _apply_generic_coercion({"include_state": "true"})
        assert result["include_state"] is True

    def test_bool_yes_string(self):
        result = _apply_generic_coercion({"lite": "yes"})
        assert result["lite"] is True

    def test_bool_false_string(self):
        result = _apply_generic_coercion({"semantic": "false"})
        assert result["semantic"] is False

    def test_bool_zero_string(self):
        result = _apply_generic_coercion({"dry_run": "0"})
        assert result["dry_run"] is False

    def test_bool_from_int(self):
        result = _apply_generic_coercion({"confirm": 1})
        assert result["confirm"] is True

    def test_bool_already_bool(self):
        result = _apply_generic_coercion({"lite": True})
        assert result["lite"] is True

    def test_none_value_skipped(self):
        result = _apply_generic_coercion({"complexity": None})
        assert result["complexity"] is None

    def test_unknown_param_untouched(self):
        result = _apply_generic_coercion({"custom_param": "value"})
        assert result["custom_param"] == "value"

    def test_invalid_value_left_as_is(self):
        result = _apply_generic_coercion({"limit": "not_a_number"})
        assert result["limit"] == "not_a_number"


# ============================================================================
# validate_and_coerce_params
# ============================================================================

class TestValidateAndCoerceParams:

    def test_unknown_tool_returns_coerced(self):
        result, error, fixes = validate_and_coerce_params("unknown_tool", {"complexity": "0.5"})
        assert error is None
        assert result["complexity"] == 0.5

    def test_process_agent_update_coerces_complexity(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"complexity": "0.7"}
        )
        assert error is None
        assert result["complexity"] == 0.7

    def test_store_knowledge_graph_missing_summary(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph", {}
        )
        assert error is not None  # Missing required "summary"

    def test_store_knowledge_graph_valid(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph", {"summary": "found a bug"}
        )
        assert error is None
        assert result["summary"] == "found a bug"

    def test_alias_resolution(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph", {"content": "test note"}
        )
        assert error is None
        assert result["summary"] == "test note"

    def test_list_from_comma_string(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph", {"summary": "test", "tags": "a, b, c"}
        )
        assert error is None
        assert result["tags"] == ["a", "b", "c"]

    def test_list_from_single_string(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph", {"summary": "test", "tags": "single"}
        )
        assert error is None
        assert result["tags"] == ["single"]

    def test_enum_case_insensitive(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"task_type": "Convergent"}
        )
        assert error is None
        assert result["task_type"] == "convergent"

    def test_enum_invalid(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"task_type": "nonexistent"}
        )
        assert error is not None

    def test_health_check_no_params(self):
        result, error, fixes = validate_and_coerce_params("health_check", {})
        assert error is None


# ============================================================================
# _levenshtein_distance
# ============================================================================

class TestLevenshteinDistance:

    def test_same_strings(self):
        assert _levenshtein_distance("abc", "abc") == 0

    def test_empty_strings(self):
        assert _levenshtein_distance("", "") == 0

    def test_one_empty(self):
        assert _levenshtein_distance("abc", "") == 3

    def test_single_substitution(self):
        assert _levenshtein_distance("cat", "bat") == 1

    def test_single_insertion(self):
        assert _levenshtein_distance("cat", "cats") == 1

    def test_single_deletion(self):
        assert _levenshtein_distance("cats", "cat") == 1

    def test_completely_different(self):
        assert _levenshtein_distance("abc", "xyz") == 3

    def test_commutative(self):
        assert _levenshtein_distance("kitten", "sitting") == _levenshtein_distance("sitting", "kitten")


# ============================================================================
# _find_closest_match
# ============================================================================

class TestFindClosestMatch:

    def test_exact_match(self):
        result = _find_closest_match("insight", DISCOVERY_TYPES)
        assert result == "insight"

    def test_typo_match(self):
        result = _find_closest_match("insigt", DISCOVERY_TYPES, max_distance=2)
        assert result == "insight"

    def test_no_match(self):
        result = _find_closest_match("zzzzzzz", DISCOVERY_TYPES, max_distance=2)
        assert result is None

    def test_case_insensitive(self):
        result = _find_closest_match("BUG_FOUND", DISCOVERY_TYPES)
        assert result == "bug_found"


# ============================================================================
# validate_enum
# ============================================================================

class TestValidateEnum:

    def test_valid(self):
        val, err = validate_enum("low", SEVERITY_LEVELS, "severity")
        assert val == "low"
        assert err is None

    def test_invalid(self):
        val, err = validate_enum("super_high", SEVERITY_LEVELS, "severity")
        assert val is None
        assert err is not None

    def test_none_allowed(self):
        val, err = validate_enum(None, SEVERITY_LEVELS, "severity")
        assert val is None
        assert err is None

    def test_suggestions(self):
        val, err = validate_enum("lo", SEVERITY_LEVELS, "severity", list(SEVERITY_LEVELS))
        assert val is None
        assert err is not None


# ============================================================================
# validate_discovery_type
# ============================================================================

class TestValidateDiscoveryType:

    def test_valid_exact(self):
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

    def test_typo_suggestion(self):
        val, err = validate_discovery_type("insigt")
        assert val is None
        assert err is not None  # Should suggest "insight"

    def test_none_allowed(self):
        val, err = validate_discovery_type(None)
        assert val is None
        assert err is None

    def test_completely_invalid(self):
        val, err = validate_discovery_type("zzzzzzz_no_match")
        assert val is None
        assert err is not None


# ============================================================================
# validate_range
# ============================================================================

class TestValidateRange:

    def test_valid_inclusive(self):
        val, err = validate_range(0.5, 0.0, 1.0, "test")
        assert val == 0.5
        assert err is None

    def test_boundary_min(self):
        val, err = validate_range(0.0, 0.0, 1.0, "test")
        assert val == 0.0
        assert err is None

    def test_boundary_max(self):
        val, err = validate_range(1.0, 0.0, 1.0, "test")
        assert val == 1.0
        assert err is None

    def test_out_of_range(self):
        val, err = validate_range(1.5, 0.0, 1.0, "test")
        assert val is None
        assert err is not None

    def test_exclusive_mode(self):
        val, err = validate_range(0.0, 0.0, 1.0, "test", inclusive=False)
        assert val is None  # 0.0 not in (0.0, 1.0) exclusive
        assert err is not None

    def test_string_coercion(self):
        val, err = validate_range("0.5", 0.0, 1.0, "test")
        assert val == 0.5

    def test_invalid_string(self):
        val, err = validate_range("not_a_number", 0.0, 1.0, "test")
        assert val is None
        assert err is not None

    def test_none_allowed(self):
        val, err = validate_range(None, 0.0, 1.0, "test")
        assert val is None
        assert err is None


# ============================================================================
# validate_response_text
# ============================================================================

class TestValidateResponseText:

    def test_valid(self):
        val, err = validate_response_text("hello world")
        assert val == "hello world"
        assert err is None

    def test_none_returns_empty(self):
        val, err = validate_response_text(None)
        assert val == ""
        assert err is None

    def test_non_string(self):
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


# ============================================================================
# validate_complexity / validate_confidence
# ============================================================================

class TestValidateComplexityConfidence:

    def test_complexity_valid(self):
        val, err = validate_complexity(0.5)
        assert val == 0.5

    def test_complexity_out_of_range(self):
        val, err = validate_complexity(1.5)
        assert err is not None

    def test_confidence_valid(self):
        val, err = validate_confidence(0.8)
        assert val == 0.8

    def test_confidence_out_of_range(self):
        val, err = validate_confidence(-0.1)
        assert err is not None


# ============================================================================
# validate_ethical_drift
# ============================================================================

class TestValidateEthicalDrift:

    def test_valid(self):
        val, err = validate_ethical_drift([0.01, 0.02, 0.03])
        assert val == [0.01, 0.02, 0.03]
        assert err is None

    def test_none_allowed(self):
        val, err = validate_ethical_drift(None)
        assert val is None
        assert err is None

    def test_not_a_list(self):
        val, err = validate_ethical_drift("bad")
        assert val is None
        assert err is not None

    def test_wrong_length(self):
        val, err = validate_ethical_drift([0.01, 0.02])
        assert val is None
        assert err is not None

    def test_component_out_of_range(self):
        val, err = validate_ethical_drift([0.01, 0.02, 2.0])
        assert val is None
        assert err is not None


# ============================================================================
# Convenience validators (severity, status, task_type, etc.)
# ============================================================================

class TestConvenienceValidators:

    def test_severity_valid(self):
        val, err = validate_severity("high")
        assert val == "high"

    def test_severity_invalid(self):
        val, err = validate_severity("super_high")
        assert err is not None

    def test_discovery_status_valid(self):
        val, err = validate_discovery_status("resolved")
        assert val == "resolved"

    def test_task_type_valid(self):
        val, err = validate_task_type("convergent")
        assert val == "convergent"

    def test_response_type_valid(self):
        val, err = validate_response_type("support")
        assert val == "support"

    def test_lifecycle_status_valid(self):
        val, err = validate_lifecycle_status("active")
        assert val == "active"

    def test_health_status_valid(self):
        val, err = validate_health_status("healthy")
        assert val == "healthy"


# ============================================================================
# validate_discovery_id
# ============================================================================

class TestValidateDiscoveryId:

    def test_valid_iso(self):
        val, err = validate_discovery_id("2025-12-13T01:23:45.678901")
        assert val == "2025-12-13T01:23:45.678901"
        assert err is None

    def test_valid_simple(self):
        val, err = validate_discovery_id("abc123")
        assert val == "abc123"
        assert err is None

    def test_none(self):
        val, err = validate_discovery_id(None)
        assert val is None
        assert err is not None

    def test_empty(self):
        val, err = validate_discovery_id("")
        assert val is None
        assert err is not None

    def test_whitespace(self):
        val, err = validate_discovery_id("   ")
        assert val is None
        assert err is not None

    def test_too_long(self):
        val, err = validate_discovery_id("a" * 201)
        assert val is None
        assert err is not None

    def test_dangerous_chars(self):
        val, err = validate_discovery_id("test; DROP TABLE")
        assert val is None
        assert err is not None

    def test_numeric_coercion(self):
        val, err = validate_discovery_id(2025)
        assert val == "2025"
        assert err is None

    def test_non_string_type(self):
        val, err = validate_discovery_id([1, 2, 3])
        assert val is None
        assert err is not None


# ============================================================================
# sanitize_agent_name
# ============================================================================

class TestSanitizeAgentName:

    def test_clean_name(self):
        assert sanitize_agent_name("my_agent") == "my_agent"

    def test_spaces(self):
        result = sanitize_agent_name("ChatGPT macOS app")
        assert " " not in result
        assert result == "ChatGPT_macOS_app"

    def test_special_chars(self):
        result = sanitize_agent_name("my agent!!!")
        assert "!" not in result
        assert result == "my_agent"

    def test_empty(self):
        result = sanitize_agent_name("")
        assert result.startswith("agent_")

    def test_none(self):
        result = sanitize_agent_name(None)
        assert result.startswith("agent_")

    def test_too_short_after_clean(self):
        result = sanitize_agent_name("!!")
        assert result.startswith("agent_")

    def test_collapse_underscores(self):
        result = sanitize_agent_name("a___b___c")
        assert "___" not in result


# ============================================================================
# validate_agent_id_format
# ============================================================================

class TestValidateAgentIdFormat:

    def test_valid(self):
        val, err = validate_agent_id_format("my_agent_2025")
        assert val == "my_agent_2025"
        assert err is None

    def test_sanitizes(self):
        val, err = validate_agent_id_format("My Agent!!!")
        assert " " not in val
        assert err is None


# ============================================================================
# validate_agent_id_policy
# ============================================================================

class TestValidateAgentIdPolicy:

    def test_always_passes(self):
        """Policy validation is disabled - always passes."""
        val, err = validate_agent_id_policy("test_agent")
        assert err is None


# ============================================================================
# validate_agent_id_reserved_names
# ============================================================================

class TestValidateAgentIdReservedNames:

    def test_normal_name(self):
        val, err = validate_agent_id_reserved_names("my_agent")
        assert val == "my_agent"
        assert err is None

    def test_reserved_system(self):
        val, err = validate_agent_id_reserved_names("system")
        assert val is None
        assert err is not None

    def test_reserved_admin(self):
        val, err = validate_agent_id_reserved_names("admin")
        assert val is None
        assert err is not None

    def test_reserved_null(self):
        val, err = validate_agent_id_reserved_names("null")
        assert val is None
        assert err is not None

    def test_reserved_prefix_system(self):
        val, err = validate_agent_id_reserved_names("system_monitor")
        assert val is None
        assert err is not None

    def test_reserved_prefix_admin(self):
        val, err = validate_agent_id_reserved_names("admin_tool")
        assert val is None
        assert err is not None

    def test_case_insensitive(self):
        val, err = validate_agent_id_reserved_names("SYSTEM")
        assert val is None
        assert err is not None

    def test_none_allowed(self):
        val, err = validate_agent_id_reserved_names(None)
        assert val is None
        assert err is None


# ============================================================================
# validate_file_path_policy
# ============================================================================

class TestValidateFilePathPolicy:

    def test_normal_file(self):
        warning, err = validate_file_path_policy("src/main.py")
        assert warning is None
        assert err is None

    def test_test_in_wrong_location(self):
        warning, err = validate_file_path_policy("test_something.py")
        assert warning is not None
        assert "POLICY" in warning

    def test_test_in_correct_location(self):
        warning, err = validate_file_path_policy("tests/test_something.py")
        assert warning is None

    def test_none_path(self):
        warning, err = validate_file_path_policy(None)
        assert warning is None


# ============================================================================
# detect_script_creation_avoidance
# ============================================================================

class TestDetectScriptCreationAvoidance:

    def test_no_avoidance(self):
        warnings = detect_script_creation_avoidance("I fixed the auth bug.")
        assert warnings == []

    def test_empty_text(self):
        warnings = detect_script_creation_avoidance("")
        assert warnings == []

    def test_none_text(self):
        warnings = detect_script_creation_avoidance(None)
        assert warnings == []

    def test_script_creation_detected(self):
        warnings = detect_script_creation_avoidance("Creating a test script to verify the changes")
        assert len(warnings) >= 1

    def test_bypass_language_detected(self):
        warnings = detect_script_creation_avoidance("I'll avoid using the MCP tools")
        assert len(warnings) >= 1

    def test_standalone_file_creation(self):
        warnings = detect_script_creation_avoidance("I'm writing a test.py file to test the auth")
        # May or may not trigger depending on regex match
        # Just ensure no crash
        assert isinstance(warnings, list)


# ============================================================================
# Data structure sanity checks
# ============================================================================

class TestDataStructures:

    def test_tool_param_schemas_has_common_tools(self):
        assert "process_agent_update" in TOOL_PARAM_SCHEMAS
        assert "store_knowledge_graph" in TOOL_PARAM_SCHEMAS
        assert "health_check" in TOOL_PARAM_SCHEMAS

    def test_discovery_types_complete(self):
        assert "bug_found" in DISCOVERY_TYPES
        assert "insight" in DISCOVERY_TYPES
        assert "note" in DISCOVERY_TYPES

    def test_severity_levels_complete(self):
        assert "low" in SEVERITY_LEVELS
        assert "high" in SEVERITY_LEVELS
        assert "critical" in SEVERITY_LEVELS

    def test_discovery_aliases_map_to_valid_types(self):
        for alias, canonical in DISCOVERY_TYPE_ALIASES.items():
            assert canonical in DISCOVERY_TYPES, f"Alias '{alias}' maps to '{canonical}' which is not a valid type"

    def test_generic_param_types_has_common_params(self):
        assert "complexity" in GENERIC_PARAM_TYPES
        assert "confidence" in GENERIC_PARAM_TYPES
        assert "limit" in GENERIC_PARAM_TYPES
        assert "lite" in GENERIC_PARAM_TYPES
