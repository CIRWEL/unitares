"""
Comprehensive tests for src/mcp_handlers/validators.py - extended coverage.

Covers edge cases, boundary conditions, error message formatting,
and paths not covered by the base test_validators.py.

Target: boost from ~16% to 50%+ coverage.
"""

import pytest
import json
import sys
import re
import os
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.validators import (
    # Constants
    TOOL_PARAM_SCHEMAS,
    PARAM_ALIASES,
    GENERIC_PARAM_TYPES,
    DISCOVERY_TYPES,
    SEVERITY_LEVELS,
    DISCOVERY_STATUSES,
    TASK_TYPES,
    RESPONSE_TYPES,
    LIFECYCLE_STATUSES,
    HEALTH_STATUSES,
    DISCOVERY_TYPE_ALIASES,
    # Functions
    apply_param_aliases,
    _apply_generic_coercion,
    validate_and_coerce_params,
    _format_param_error,
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
# PARAM_ALIASES: deep edge cases
# ============================================================================

class TestParamAliasesDeepCoverage:
    """Extended alias tests covering all alias mappings and edge interactions."""

    def test_store_knowledge_graph_discovery_alias(self):
        result = apply_param_aliases("store_knowledge_graph", {"discovery": "found it"})
        assert result == {"summary": "found it"}

    def test_store_knowledge_graph_insight_alias(self):
        result = apply_param_aliases("store_knowledge_graph", {"insight": "interesting"})
        assert result == {"summary": "interesting"}

    def test_store_knowledge_graph_finding_alias(self):
        result = apply_param_aliases("store_knowledge_graph", {"finding": "data"})
        assert result == {"summary": "data"}

    def test_store_knowledge_graph_text_alias(self):
        result = apply_param_aliases("store_knowledge_graph", {"text": "my text"})
        assert result == {"summary": "my text"}

    def test_store_knowledge_graph_message_alias(self):
        result = apply_param_aliases("store_knowledge_graph", {"message": "msg"})
        assert result == {"summary": "msg"}

    def test_store_knowledge_graph_learning_alias(self):
        result = apply_param_aliases("store_knowledge_graph", {"learning": "I learned"})
        assert result == {"summary": "I learned"}

    def test_store_knowledge_graph_observation_alias(self):
        result = apply_param_aliases("store_knowledge_graph", {"observation": "I saw"})
        assert result == {"summary": "I saw"}

    def test_store_knowledge_graph_kind_alias(self):
        result = apply_param_aliases("store_knowledge_graph", {"kind": "insight"})
        assert result == {"discovery_type": "insight"}

    def test_store_knowledge_graph_category_alias(self):
        result = apply_param_aliases("store_knowledge_graph", {"category": "note"})
        assert result == {"discovery_type": "note"}

    def test_leave_note_all_aliases(self):
        """Test all leave_note aliases resolve to summary."""
        aliases_to_test = ["discovery", "insight", "finding", "text", "note", "content", "message", "learning"]
        for alias in aliases_to_test:
            result = apply_param_aliases("leave_note", {alias: "test_val"})
            assert result == {"summary": "test_val"}, f"Alias '{alias}' failed"

    def test_search_knowledge_graph_term_alias(self):
        result = apply_param_aliases("search_knowledge_graph", {"term": "auth"})
        assert result == {"query": "auth"}

    def test_search_knowledge_graph_text_alias(self):
        result = apply_param_aliases("search_knowledge_graph", {"text": "auth"})
        assert result == {"query": "auth"}

    def test_search_knowledge_graph_find_alias(self):
        result = apply_param_aliases("search_knowledge_graph", {"find": "auth"})
        assert result == {"query": "auth"}

    def test_process_agent_update_message_alias(self):
        result = apply_param_aliases("process_agent_update", {"message": "hi"})
        assert result == {"response_text": "hi"}

    def test_process_agent_update_update_alias(self):
        result = apply_param_aliases("process_agent_update", {"update": "work done"})
        assert result == {"response_text": "work done"}

    def test_process_agent_update_content_alias(self):
        result = apply_param_aliases("process_agent_update", {"content": "content"})
        assert result == {"response_text": "content"}

    def test_process_agent_update_work_alias(self):
        result = apply_param_aliases("process_agent_update", {"work": "progress"})
        assert result == {"response_text": "progress"}

    def test_process_agent_update_summary_alias(self):
        result = apply_param_aliases("process_agent_update", {"summary": "sum"})
        assert result == {"response_text": "sum"}

    def test_identity_display_name_alias(self):
        result = apply_param_aliases("identity", {"display_name": "Bob"})
        assert result == {"name": "Bob"}

    def test_identity_nickname_alias(self):
        result = apply_param_aliases("identity", {"nickname": "Bobby"})
        assert result == {"name": "Bobby"}

    def test_mixed_alias_and_canonical(self):
        """When both alias and canonical are provided, alias overwrites."""
        result = apply_param_aliases("store_knowledge_graph", {
            "content": "alias_val",
            "tags": ["tag1"]
        })
        assert result["summary"] == "alias_val"
        assert result["tags"] == ["tag1"]

    def test_empty_arguments(self):
        result = apply_param_aliases("store_knowledge_graph", {})
        assert result == {}

    def test_none_value_in_alias(self):
        result = apply_param_aliases("store_knowledge_graph", {"content": None})
        assert result == {"summary": None}


# ============================================================================
# _apply_generic_coercion: extended edge cases
# ============================================================================

class TestGenericCoercionEdgeCases:
    """Deep edge cases for generic type coercion."""

    def test_float_01_from_int(self):
        result = _apply_generic_coercion({"complexity": 1})
        assert result["complexity"] == 1.0

    def test_float_01_from_float(self):
        result = _apply_generic_coercion({"confidence": 0.75})
        assert result["confidence"] == 0.75

    def test_float_01_clamp_negative_int(self):
        result = _apply_generic_coercion({"complexity": -2})
        assert result["complexity"] == 0.0

    def test_float_01_clamp_large_int(self):
        result = _apply_generic_coercion({"complexity": 5})
        assert result["complexity"] == 1.0

    def test_float_from_int(self):
        result = _apply_generic_coercion({"max_age_days": 7})
        assert result["max_age_days"] == 7.0
        assert isinstance(result["max_age_days"], float)

    def test_float_from_float(self):
        result = _apply_generic_coercion({"max_age_hours": 2.5})
        assert result["max_age_hours"] == 2.5

    def test_int_already_int(self):
        result = _apply_generic_coercion({"limit": 50})
        assert result["limit"] == 50

    def test_bool_one_string(self):
        result = _apply_generic_coercion({"include_state": "1"})
        assert result["include_state"] is True

    def test_bool_no_string(self):
        result = _apply_generic_coercion({"grouped": "no"})
        assert result["grouped"] is False

    def test_bool_empty_string_is_false(self):
        result = _apply_generic_coercion({"lite": ""})
        assert result["lite"] is False

    def test_bool_int_zero_is_false(self):
        result = _apply_generic_coercion({"confirm": 0})
        assert result["confirm"] is False

    def test_multiple_params_at_once(self):
        result = _apply_generic_coercion({
            "complexity": "0.5",
            "limit": "10",
            "lite": "true",
            "max_age_days": "3",
        })
        assert result["complexity"] == 0.5
        assert result["limit"] == 10
        assert result["lite"] is True
        assert result["max_age_days"] == 3.0

    def test_invalid_float_string_leaves_original(self):
        result = _apply_generic_coercion({"complexity": "abc"})
        assert result["complexity"] == "abc"

    def test_invalid_int_string_leaves_original(self):
        result = _apply_generic_coercion({"limit": "xyz"})
        assert result["limit"] == "xyz"

    def test_bool_unrecognized_string_leaves_original(self):
        """Unrecognized bool string (not true/false/yes/no/0/1) stays as-is."""
        result = _apply_generic_coercion({"lite": "maybe"})
        assert result["lite"] == "maybe"

    def test_min_similarity_float_01(self):
        result = _apply_generic_coercion({"min_similarity": "0.8"})
        assert result["min_similarity"] == 0.8

    def test_connectivity_weight_clamp(self):
        result = _apply_generic_coercion({"connectivity_weight": "2.0"})
        assert result["connectivity_weight"] == 1.0

    def test_similarity_threshold_float_01(self):
        result = _apply_generic_coercion({"similarity_threshold": "0.3"})
        assert result["similarity_threshold"] == 0.3

    def test_offset_int(self):
        result = _apply_generic_coercion({"offset": "20"})
        assert result["offset"] == 20

    def test_window_hours_int(self):
        result = _apply_generic_coercion({"window_hours": "24"})
        assert result["window_hours"] == 24

    def test_dry_run_bool(self):
        result = _apply_generic_coercion({"dry_run": "true"})
        assert result["dry_run"] is True

    def test_auto_export_bool(self):
        result = _apply_generic_coercion({"auto_export_on_significance": "false"})
        assert result["auto_export_on_significance"] is False


# ============================================================================
# validate_and_coerce_params: comprehensive schema-based tests
# ============================================================================

class TestValidateAndCoerceParamsExtended:
    """Extended tests for the main validation entry point."""

    # --- process_agent_update ---

    def test_process_agent_update_all_valid_params(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update",
            {
                "complexity": 0.5,
                "confidence": 0.8,
                "task_type": "convergent",
                "response_text": "hello",
                "response_mode": "compact",
            }
        )
        assert error is None
        assert result["complexity"] == 0.5
        assert result["confidence"] == 0.8
        assert result["task_type"] == "convergent"
        assert result["response_text"] == "hello"
        assert result["response_mode"] == "compact"

    def test_process_agent_update_lite_bool_coercion(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"lite": "true"}
        )
        assert error is None
        assert result["lite"] is True

    def test_process_agent_update_response_mode_case_fix(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"response_mode": "Compact"}
        )
        assert error is None
        assert result["response_mode"] == "compact"
        assert any("case" in f.lower() for f in fixes)

    def test_process_agent_update_invalid_response_mode(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"response_mode": "verbose"}
        )
        assert error is not None

    def test_process_agent_update_confidence_string(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"confidence": "0.9"}
        )
        assert error is None
        assert result["confidence"] == 0.9

    def test_process_agent_update_confidence_out_of_range_clamped(self):
        """Generic coercion clamps float_01 before schema validation."""
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"confidence": 1.5}
        )
        # Generic coercion clamps 1.5 -> 1.0, so no error
        assert error is None
        assert result["confidence"] == 1.0

    def test_process_agent_update_complexity_out_of_range_clamped(self):
        """Generic coercion clamps float_01 before schema validation."""
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"complexity": -0.1}
        )
        # Generic coercion clamps -0.1 -> 0.0, so no error
        assert error is None
        assert result["complexity"] == 0.0

    def test_process_agent_update_complexity_boundary_zero(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"complexity": 0.0}
        )
        assert error is None
        assert result["complexity"] == 0.0

    def test_process_agent_update_complexity_boundary_one(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"complexity": 1.0}
        )
        assert error is None
        assert result["complexity"] == 1.0

    def test_process_agent_update_alias_then_validate(self):
        """Aliases are applied before validation."""
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"text": "my update"}
        )
        assert error is None
        assert result["response_text"] == "my update"

    def test_process_agent_update_empty_dict(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {}
        )
        assert error is None  # No required params

    # --- store_knowledge_graph ---

    def test_store_knowledge_graph_with_discovery_type(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "found issue", "discovery_type": "bug_found"}
        )
        assert error is None
        assert result["discovery_type"] == "bug_found"

    def test_store_knowledge_graph_discovery_type_alias(self):
        """Discovery type aliases resolve during enum validation."""
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "found issue", "discovery_type": "bug"}
        )
        assert error is None
        assert result["discovery_type"] == "bug_found"

    def test_store_knowledge_graph_severity_valid(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "found issue", "severity": "high"}
        )
        assert error is None
        assert result["severity"] == "high"

    def test_store_knowledge_graph_severity_invalid(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "found issue", "severity": "extreme"}
        )
        assert error is not None

    def test_store_knowledge_graph_tags_as_list(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "test", "tags": ["a", "b"]}
        )
        assert error is None
        assert result["tags"] == ["a", "b"]

    def test_store_knowledge_graph_tags_invalid_type(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "test", "tags": 123}
        )
        assert error is not None

    def test_store_knowledge_graph_details_string(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "test", "details": "detailed info"}
        )
        assert error is None
        assert result["details"] == "detailed info"

    def test_store_knowledge_graph_details_non_string_coerced(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "test", "details": 42}
        )
        assert error is None
        assert result["details"] == "42"
        assert any("Converted" in f for f in fixes)

    def test_store_knowledge_graph_summary_none_is_missing(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph", {"summary": None}
        )
        assert error is not None

    def test_store_knowledge_graph_alias_content_fills_summary(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph", {"content": "via alias"}
        )
        assert error is None
        assert result["summary"] == "via alias"

    # --- search_knowledge_graph ---

    def test_search_knowledge_graph_valid(self):
        result, error, fixes = validate_and_coerce_params(
            "search_knowledge_graph", {"query": "auth bug"}
        )
        assert error is None
        assert result["query"] == "auth bug"

    def test_search_knowledge_graph_semantic_coercion(self):
        result, error, fixes = validate_and_coerce_params(
            "search_knowledge_graph", {"query": "test", "semantic": "true"}
        )
        assert error is None
        assert result["semantic"] is True

    def test_search_knowledge_graph_limit_coercion(self):
        result, error, fixes = validate_and_coerce_params(
            "search_knowledge_graph", {"limit": "50"}
        )
        assert error is None
        assert result["limit"] == 50

    def test_search_knowledge_graph_alias_search(self):
        result, error, fixes = validate_and_coerce_params(
            "search_knowledge_graph", {"search": "find this"}
        )
        assert error is None
        assert result["query"] == "find this"

    def test_search_knowledge_graph_empty(self):
        result, error, fixes = validate_and_coerce_params(
            "search_knowledge_graph", {}
        )
        assert error is None

    # --- leave_note ---

    def test_leave_note_valid(self):
        result, error, fixes = validate_and_coerce_params(
            "leave_note", {"summary": "my note"}
        )
        assert error is None

    def test_leave_note_missing_summary(self):
        result, error, fixes = validate_and_coerce_params(
            "leave_note", {}
        )
        assert error is not None

    def test_leave_note_alias_note(self):
        result, error, fixes = validate_and_coerce_params(
            "leave_note", {"note": "quick note"}
        )
        assert error is None
        assert result["summary"] == "quick note"

    def test_leave_note_with_tags(self):
        result, error, fixes = validate_and_coerce_params(
            "leave_note", {"summary": "note", "tags": "a, b"}
        )
        assert error is None
        assert result["tags"] == ["a", "b"]

    # --- get_governance_metrics ---

    def test_get_governance_metrics_empty(self):
        result, error, fixes = validate_and_coerce_params(
            "get_governance_metrics", {}
        )
        assert error is None

    def test_get_governance_metrics_include_state(self):
        result, error, fixes = validate_and_coerce_params(
            "get_governance_metrics", {"include_state": "true"}
        )
        assert error is None
        assert result["include_state"] is True

    # --- list_agents ---

    def test_list_agents_empty(self):
        result, error, fixes = validate_and_coerce_params(
            "list_agents", {}
        )
        assert error is None

    def test_list_agents_status_filter_valid(self):
        result, error, fixes = validate_and_coerce_params(
            "list_agents", {"status_filter": "active"}
        )
        assert error is None
        assert result["status_filter"] == "active"

    def test_list_agents_status_filter_invalid(self):
        result, error, fixes = validate_and_coerce_params(
            "list_agents", {"status_filter": "sleeping"}
        )
        assert error is not None

    def test_list_agents_grouped_coercion(self):
        result, error, fixes = validate_and_coerce_params(
            "list_agents", {"grouped": "false"}
        )
        assert error is None
        assert result["grouped"] is False

    def test_list_agents_summary_only_coercion(self):
        result, error, fixes = validate_and_coerce_params(
            "list_agents", {"summary_only": "yes"}
        )
        assert error is None
        assert result["summary_only"] is True

    # --- identity ---

    def test_identity_empty(self):
        result, error, fixes = validate_and_coerce_params(
            "identity", {}
        )
        assert error is None

    def test_identity_with_name(self):
        result, error, fixes = validate_and_coerce_params(
            "identity", {"name": "my_agent"}
        )
        assert error is None

    def test_identity_alias_label(self):
        result, error, fixes = validate_and_coerce_params(
            "identity", {"label": "my_agent"}
        )
        assert error is None
        assert result["name"] == "my_agent"

    # --- list_tools ---

    def test_list_tools_empty(self):
        result, error, fixes = validate_and_coerce_params(
            "list_tools", {}
        )
        assert error is None

    def test_list_tools_tier_valid(self):
        result, error, fixes = validate_and_coerce_params(
            "list_tools", {"tier": "essential"}
        )
        assert error is None

    def test_list_tools_tier_invalid(self):
        result, error, fixes = validate_and_coerce_params(
            "list_tools", {"tier": "super"}
        )
        assert error is not None

    def test_list_tools_lite_coercion(self):
        result, error, fixes = validate_and_coerce_params(
            "list_tools", {"lite": "1"}
        )
        assert error is None
        assert result["lite"] is True

    def test_list_tools_essential_only(self):
        result, error, fixes = validate_and_coerce_params(
            "list_tools", {"essential_only": "true"}
        )
        assert error is None
        assert result["essential_only"] is True

    # --- Generic coercion for unschemaed params ---

    def test_unknown_tool_generic_coercion_applied(self):
        """Unknown tools still get generic coercion."""
        result, error, fixes = validate_and_coerce_params(
            "nonexistent_tool", {"limit": "5", "lite": "true"}
        )
        assert error is None
        assert result["limit"] == 5
        assert result["lite"] is True

    def test_schemaed_tool_non_schema_params_still_coerced(self):
        """Params not in the tool schema but in GENERIC_PARAM_TYPES still get coerced."""
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update",
            {"complexity": 0.5, "include_history": "true"}
        )
        assert error is None
        assert result["include_history"] is True

    # --- Type coercion failure cases ---

    def test_float_param_bad_string_errors(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"complexity": "not_a_float"}
        )
        # Generic coercion happens first and fails silently,
        # then schema validation tries and fails
        assert error is not None

    def test_int_param_bad_string_errors(self):
        result, error, fixes = validate_and_coerce_params(
            "search_knowledge_graph", {"limit": "not_an_int"}
        )
        assert error is not None

    def test_bool_param_bad_string_errors(self):
        result, error, fixes = validate_and_coerce_params(
            "search_knowledge_graph", {"semantic": "maybe"}
        )
        assert error is not None


# ============================================================================
# validate_and_coerce_params: discovery_type alias resolution in schema
# ============================================================================

class TestDiscoveryTypeAliasInSchema:
    """Test discovery type alias resolution during schema-level validation."""

    def test_alias_implementation_resolves(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "test", "discovery_type": "implementation"}
        )
        assert error is None
        assert result["discovery_type"] == "improvement"

    def test_alias_enhancement_resolves(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "test", "discovery_type": "enhancement"}
        )
        assert error is None
        assert result["discovery_type"] == "improvement"

    def test_alias_observation_resolves(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "test", "discovery_type": "observation"}
        )
        assert error is None
        assert result["discovery_type"] == "insight"

    def test_alias_memo_resolves(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "test", "discovery_type": "memo"}
        )
        assert error is None
        assert result["discovery_type"] == "note"

    def test_alias_experiment_resolves(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"summary": "test", "discovery_type": "experiment"}
        )
        assert error is None
        assert result["discovery_type"] == "exploration"


# ============================================================================
# _format_param_error: error message formatting
# ============================================================================

class TestFormatParamError:
    """Tests for error message formatting in _format_param_error."""

    def test_missing_param_error_format(self):
        """Missing parameter produces a TextContent error."""
        schema = TOOL_PARAM_SCHEMAS["store_knowledge_graph"]
        error = _format_param_error(
            "store_knowledge_graph",
            schema,
            ["Missing required parameter: 'summary'"],
            []
        )
        assert error is not None
        # It returns a TextContent object
        assert hasattr(error, "text")
        parsed = json.loads(error.text)
        assert parsed["success"] is False

    def test_type_error_format(self):
        """Type errors produce structured error with expected/provided types."""
        schema = TOOL_PARAM_SCHEMAS["process_agent_update"]
        error = _format_param_error(
            "process_agent_update",
            schema,
            ["'complexity' must be number, got str"],
            []
        )
        assert error is not None
        assert hasattr(error, "text")

    def test_fallback_error_with_fixes(self):
        """Complex errors fall back to detailed message."""
        schema = TOOL_PARAM_SCHEMAS["process_agent_update"]
        error = _format_param_error(
            "process_agent_update",
            schema,
            ["Some complex error that does not match standard patterns"],
            ["Converted complexity from string to float"]
        )
        assert error is not None
        assert hasattr(error, "text")
        parsed = json.loads(error.text)
        assert parsed["success"] is False

    def test_fallback_error_shows_example(self):
        """Fallback includes example when available."""
        schema = TOOL_PARAM_SCHEMAS["store_knowledge_graph"]
        error = _format_param_error(
            "store_knowledge_graph",
            schema,
            ["Some non-standard error"],
            []
        )
        parsed = json.loads(error.text)
        # The error message should contain info about the tool
        assert "store_knowledge_graph" in parsed.get("error", "")

    def test_empty_optional_params(self):
        """Schema with empty optional params still formats correctly."""
        schema = TOOL_PARAM_SCHEMAS["health_check"]
        error = _format_param_error(
            "health_check",
            schema,
            ["Some error"],
            []
        )
        assert error is not None

    def test_many_optional_params_truncated(self):
        """Only first 5 optional params shown in fallback message."""
        # Use a tool with many optional params
        schema = TOOL_PARAM_SCHEMAS["search_knowledge_graph"]
        error = _format_param_error(
            "search_knowledge_graph",
            schema,
            ["Some non-standard complex error"],
            []
        )
        assert error is not None
        parsed = json.loads(error.text)
        error_text = parsed.get("error", "")
        # Should mention the tool
        assert "search_knowledge_graph" in error_text


# ============================================================================
# validate_enum: extended tests
# ============================================================================

class TestValidateEnumExtended:
    """Extended validate_enum coverage."""

    def test_integer_value_invalid(self):
        val, err = validate_enum(42, SEVERITY_LEVELS, "severity")
        assert val is None
        assert err is not None

    def test_empty_string_invalid(self):
        val, err = validate_enum("", SEVERITY_LEVELS, "severity")
        assert val is None
        assert err is not None

    def test_suggestion_partial_match(self):
        """Suggestions work via substring matching."""
        val, err = validate_enum("med", SEVERITY_LEVELS, "severity", list(SEVERITY_LEVELS))
        assert val is None
        assert err is not None
        parsed = json.loads(err.text)
        # Should have "recovery" with valid values
        assert "recovery" in parsed

    def test_all_severity_values(self):
        for sev in SEVERITY_LEVELS:
            val, err = validate_enum(sev, SEVERITY_LEVELS, "severity")
            assert val == sev
            assert err is None

    def test_all_task_types(self):
        for tt in TASK_TYPES:
            val, err = validate_enum(tt, TASK_TYPES, "task_type")
            assert val == tt
            assert err is None

    def test_error_message_contains_valid_values(self):
        val, err = validate_enum("xyz", {"a", "b", "c"}, "test_param")
        parsed = json.loads(err.text)
        assert "a" in parsed["error"]
        assert "b" in parsed["error"]
        assert "c" in parsed["error"]

    def test_no_suggestions_param(self):
        """When suggestions is None, no 'Did you mean' in error."""
        val, err = validate_enum("lo", SEVERITY_LEVELS, "severity", None)
        assert err is not None
        parsed = json.loads(err.text)
        assert "Did you mean" not in parsed["error"]


# ============================================================================
# validate_discovery_type: comprehensive alias and fuzzy coverage
# ============================================================================

class TestValidateDiscoveryTypeExtended:
    """Extended discovery type validation covering all aliases and edge cases."""

    def test_all_canonical_types_exact(self):
        """Every canonical type validates correctly."""
        for dtype in DISCOVERY_TYPES:
            val, err = validate_discovery_type(dtype)
            assert val == dtype, f"Failed for {dtype}"
            assert err is None

    def test_all_canonical_types_case_insensitive(self):
        """Every canonical type works case-insensitively."""
        for dtype in DISCOVERY_TYPES:
            val, err = validate_discovery_type(dtype.upper())
            assert val == dtype, f"Failed for {dtype.upper()}"
            assert err is None

    def test_all_aliases_resolve(self):
        """Every defined alias resolves correctly."""
        for alias, canonical in DISCOVERY_TYPE_ALIASES.items():
            val, err = validate_discovery_type(alias)
            assert val == canonical, f"Alias '{alias}' should resolve to '{canonical}', got '{val}'"
            assert err is None

    def test_alias_with_whitespace(self):
        val, err = validate_discovery_type("  bug  ")
        assert val == "bug_found"
        assert err is None

    def test_alias_mixed_case(self):
        val, err = validate_discovery_type("BUG")
        assert val == "bug_found"
        assert err is None

    def test_bugfix_alias(self):
        val, err = validate_discovery_type("bugfix")
        assert val == "bug_found"

    def test_defect_alias(self):
        val, err = validate_discovery_type("defect")
        assert val == "bug_found"

    def test_feature_alias(self):
        val, err = validate_discovery_type("feature")
        assert val == "improvement"

    def test_refactor_alias(self):
        val, err = validate_discovery_type("refactor")
        assert val == "improvement"

    def test_ticket_alias(self):
        val, err = validate_discovery_type("ticket")
        assert val == "improvement"

    def test_story_alias(self):
        val, err = validate_discovery_type("story")
        assert val == "improvement"

    def test_trend_alias(self):
        val, err = validate_discovery_type("trend")
        assert val == "pattern"

    def test_query_alias(self):
        val, err = validate_discovery_type("query")
        assert val == "question"

    def test_solution_alias(self):
        val, err = validate_discovery_type("solution")
        assert val == "answer"

    def test_research_alias(self):
        val, err = validate_discovery_type("research")
        assert val == "exploration"

    def test_ux_feedback_alias(self):
        val, err = validate_discovery_type("ux_feedback")
        assert val == "improvement"

    def test_typo_insigh_suggests(self):
        """Close typo returns error with suggestion."""
        val, err = validate_discovery_type("insigh")
        assert val is None
        assert err is not None
        parsed = json.loads(err.text)
        assert "insight" in parsed["error"]

    def test_typo_patter_suggests(self):
        val, err = validate_discovery_type("patter")
        assert val is None
        assert err is not None
        parsed = json.loads(err.text)
        assert "pattern" in parsed["error"]

    def test_no_match_at_all(self):
        """Completely invalid returns full error with aliases."""
        val, err = validate_discovery_type("xxxxxxxxxx_not_a_thing")
        assert val is None
        assert err is not None
        parsed = json.loads(err.text)
        assert "recovery" in parsed

    def test_integer_input(self):
        """Integer input gets stringified."""
        val, err = validate_discovery_type(42)
        assert val is None
        assert err is not None

    def test_empty_string(self):
        """Empty string after strip doesn't match."""
        val, err = validate_discovery_type("   ")
        assert val is None
        assert err is not None


# ============================================================================
# _levenshtein_distance: more thorough coverage
# ============================================================================

class TestLevenshteinExtended:

    def test_reversed_argument_order(self):
        """Distance is symmetric via the swap in the function."""
        assert _levenshtein_distance("abc", "abcdef") == _levenshtein_distance("abcdef", "abc")

    def test_identical_long_strings(self):
        assert _levenshtein_distance("abcdefghij", "abcdefghij") == 0

    def test_one_char_difference(self):
        assert _levenshtein_distance("test", "best") == 1

    def test_all_different_chars(self):
        assert _levenshtein_distance("abc", "def") == 3

    def test_prefix(self):
        assert _levenshtein_distance("abc", "abcdef") == 3

    def test_suffix(self):
        assert _levenshtein_distance("def", "abcdef") == 3


# ============================================================================
# _find_closest_match: extended
# ============================================================================

class TestFindClosestMatchExtended:

    def test_max_distance_zero(self):
        """Only exact matches with distance 0."""
        result = _find_closest_match("insight", DISCOVERY_TYPES, max_distance=0)
        assert result == "insight"

    def test_max_distance_zero_no_match(self):
        result = _find_closest_match("insigt", DISCOVERY_TYPES, max_distance=0)
        assert result is None

    def test_max_distance_1(self):
        result = _find_closest_match("insigh", DISCOVERY_TYPES, max_distance=1)
        # "insigh" is distance 1 from "insight"
        assert result == "insight"

    def test_returns_best_match(self):
        """When multiple matches exist, returns the closest."""
        result = _find_closest_match("note", {"note", "notes", "nope"}, max_distance=2)
        assert result == "note"  # exact match distance 0

    def test_empty_valid_values(self):
        result = _find_closest_match("anything", set(), max_distance=5)
        assert result is None


# ============================================================================
# validate_range: extended boundary and type tests
# ============================================================================

class TestValidateRangeExtended:

    def test_int_value_in_float_range(self):
        val, err = validate_range(1, 0.0, 2.0, "param")
        assert val == 1.0
        assert err is None

    def test_string_float(self):
        val, err = validate_range("0.75", 0.0, 1.0, "param")
        assert val == 0.75

    def test_string_int(self):
        val, err = validate_range("5", 0, 10, "param")
        assert val == 5.0

    def test_negative_range(self):
        val, err = validate_range(-0.5, -1.0, 0.0, "param")
        assert val == -0.5
        assert err is None

    def test_out_of_range_low(self):
        val, err = validate_range(-2.0, -1.0, 1.0, "param")
        assert val is None
        assert err is not None

    def test_out_of_range_high(self):
        val, err = validate_range(2.0, -1.0, 1.0, "param")
        assert val is None
        assert err is not None

    def test_exclusive_boundary_low(self):
        val, err = validate_range(0.0, 0.0, 1.0, "param", inclusive=False)
        assert val is None

    def test_exclusive_boundary_high(self):
        val, err = validate_range(1.0, 0.0, 1.0, "param", inclusive=False)
        assert val is None

    def test_exclusive_inside(self):
        val, err = validate_range(0.5, 0.0, 1.0, "param", inclusive=False)
        assert val == 0.5
        assert err is None

    def test_non_numeric_list_fails(self):
        val, err = validate_range([1, 2], 0.0, 1.0, "param")
        assert val is None
        assert err is not None

    def test_non_numeric_dict_fails(self):
        val, err = validate_range({"a": 1}, 0.0, 1.0, "param")
        assert val is None
        assert err is not None

    def test_bool_coerces_to_float(self):
        """bool is a subclass of int, so True = 1.0."""
        val, err = validate_range(True, 0.0, 2.0, "param")
        assert val == 1.0
        assert err is None


# ============================================================================
# validate_response_text: extended
# ============================================================================

class TestValidateResponseTextExtended:

    def test_empty_string_valid(self):
        val, err = validate_response_text("")
        assert val == ""
        assert err is None

    def test_exact_max_length(self):
        val, err = validate_response_text("x" * 50000)
        assert val == "x" * 50000
        assert err is None

    def test_one_over_max_length(self):
        val, err = validate_response_text("x" * 50001)
        assert val is None
        assert err is not None

    def test_list_input(self):
        val, err = validate_response_text(["a", "b"])
        assert val is None
        assert err is not None

    def test_dict_input(self):
        val, err = validate_response_text({"text": "hello"})
        assert val is None
        assert err is not None

    def test_bool_input(self):
        val, err = validate_response_text(True)
        assert val is None
        assert err is not None

    def test_custom_max_length_exactly_at_limit(self):
        val, err = validate_response_text("abc", max_length=3)
        assert val == "abc"
        assert err is None

    def test_unicode_string(self):
        val, err = validate_response_text("Hello world! Special chars: <>&\"'")
        assert val is not None
        assert err is None


# ============================================================================
# validate_ethical_drift: extended
# ============================================================================

class TestValidateEthicalDriftExtended:

    def test_boundary_values(self):
        val, err = validate_ethical_drift([-1.0, 0.0, 1.0])
        assert val == [-1.0, 0.0, 1.0]
        assert err is None

    def test_four_elements_accepted(self):
        """4-element drift is valid (governance-computed EthicalDriftVector)."""
        val, err = validate_ethical_drift([0.1, 0.2, 0.3, 0.4])
        assert val == [0.1, 0.2, 0.3, 0.4]
        assert err is None

    def test_too_many_elements(self):
        val, err = validate_ethical_drift([0.1, 0.2, 0.3, 0.4, 0.5])
        assert val is None
        assert err is not None

    def test_single_element(self):
        val, err = validate_ethical_drift([0.1])
        assert val is None
        assert err is not None

    def test_empty_list(self):
        val, err = validate_ethical_drift([])
        assert val is None
        assert err is not None

    def test_string_components(self):
        """String components should be coerced by validate_range."""
        val, err = validate_ethical_drift(["0.1", "0.2", "0.3"])
        assert val == [0.1, 0.2, 0.3]
        assert err is None

    def test_component_out_of_range_negative(self):
        val, err = validate_ethical_drift([-1.5, 0.0, 0.0])
        assert val is None
        assert err is not None

    def test_tuple_not_list(self):
        """Tuple is not a list."""
        val, err = validate_ethical_drift((0.1, 0.2, 0.3))
        assert val is None
        assert err is not None

    def test_dict_not_list(self):
        val, err = validate_ethical_drift({"a": 0.1})
        assert val is None
        assert err is not None


# ============================================================================
# Convenience validators: extended
# ============================================================================

class TestConvenienceValidatorsExtended:

    def test_all_severity_values(self):
        for sev in SEVERITY_LEVELS:
            val, err = validate_severity(sev)
            assert val == sev
            assert err is None

    def test_severity_none(self):
        val, err = validate_severity(None)
        assert val is None
        assert err is None

    def test_all_discovery_statuses(self):
        for status in DISCOVERY_STATUSES:
            val, err = validate_discovery_status(status)
            assert val == status
            assert err is None

    def test_discovery_status_invalid(self):
        val, err = validate_discovery_status("deleted")
        assert err is not None

    def test_all_task_types(self):
        for tt in TASK_TYPES:
            val, err = validate_task_type(tt)
            assert val == tt
            assert err is None

    def test_task_type_invalid(self):
        val, err = validate_task_type("parallel")
        assert err is not None

    def test_all_response_types(self):
        for rt in RESPONSE_TYPES:
            val, err = validate_response_type(rt)
            assert val == rt
            assert err is None

    def test_response_type_invalid(self):
        val, err = validate_response_type("approve")
        assert err is not None

    def test_all_lifecycle_statuses(self):
        for ls in LIFECYCLE_STATUSES:
            val, err = validate_lifecycle_status(ls)
            assert val == ls
            assert err is None

    def test_lifecycle_status_invalid(self):
        val, err = validate_lifecycle_status("sleeping")
        assert err is not None

    def test_all_health_statuses(self):
        for hs in HEALTH_STATUSES:
            val, err = validate_health_status(hs)
            assert val == hs
            assert err is None

    def test_health_status_invalid(self):
        val, err = validate_health_status("dead")
        assert err is not None


# ============================================================================
# validate_discovery_id: extended
# ============================================================================

class TestValidateDiscoveryIdExtended:

    def test_valid_with_dashes_and_dots(self):
        val, err = validate_discovery_id("abc-def.123")
        assert val == "abc-def.123"
        assert err is None

    def test_valid_with_underscores(self):
        val, err = validate_discovery_id("test_id_123")
        assert val == "test_id_123"
        assert err is None

    def test_valid_with_colons(self):
        val, err = validate_discovery_id("12:34:56")
        assert val == "12:34:56"
        assert err is None

    def test_valid_with_T(self):
        val, err = validate_discovery_id("2025-12-13T01:23:45")
        assert val == "2025-12-13T01:23:45"
        assert err is None

    def test_float_coercion(self):
        val, err = validate_discovery_id(3.14)
        assert val == "3.14"
        assert err is None

    def test_exactly_200_chars(self):
        val, err = validate_discovery_id("a" * 200)
        assert val == "a" * 200
        assert err is None

    def test_201_chars_too_long(self):
        val, err = validate_discovery_id("a" * 201)
        assert val is None
        assert err is not None

    def test_space_in_id(self):
        val, err = validate_discovery_id("test id")
        assert val is None
        assert err is not None

    def test_semicolon(self):
        val, err = validate_discovery_id("test;drop")
        assert val is None
        assert err is not None

    def test_single_quote(self):
        val, err = validate_discovery_id("test'injection")
        assert val is None
        assert err is not None

    def test_angle_brackets(self):
        val, err = validate_discovery_id("<script>")
        assert val is None
        assert err is not None

    def test_dict_input(self):
        val, err = validate_discovery_id({"id": "test"})
        assert val is None
        assert err is not None

    def test_bool_input_coerced_to_string(self):
        """bool is subclass of int, so True gets coerced to str "True"."""
        val, err = validate_discovery_id(True)
        assert val == "True"
        assert err is None


# ============================================================================
# sanitize_agent_name: extended
# ============================================================================

class TestSanitizeAgentNameExtended:

    def test_hyphens_preserved(self):
        assert sanitize_agent_name("my-agent") == "my-agent"

    def test_underscores_preserved(self):
        assert sanitize_agent_name("my_agent") == "my_agent"

    def test_numbers_preserved(self):
        assert sanitize_agent_name("agent123") == "agent123"

    def test_mixed_case_preserved(self):
        assert sanitize_agent_name("MyAgent") == "MyAgent"

    def test_leading_special_chars_stripped(self):
        result = sanitize_agent_name("___myagent")
        assert not result.startswith("_")

    def test_trailing_special_chars_stripped(self):
        result = sanitize_agent_name("myagent---")
        assert not result.endswith("-")

    def test_all_special_chars_auto_generates(self):
        result = sanitize_agent_name("@#$")
        assert result.startswith("agent_")

    def test_two_char_after_clean_auto_generates(self):
        result = sanitize_agent_name("ab")
        # "ab" is only 2 chars, below the 3-char minimum
        assert result.startswith("agent_")

    def test_three_char_valid(self):
        result = sanitize_agent_name("abc")
        assert result == "abc"

    def test_unicode_replaced(self):
        result = sanitize_agent_name("agent_test")
        # Emoji gets replaced with underscore, then collapsed
        assert "_" not in result or result.count("_") <= result.count("_")

    def test_tabs_replaced(self):
        result = sanitize_agent_name("my\tagent")
        assert "\t" not in result

    def test_newlines_replaced(self):
        result = sanitize_agent_name("my\nagent")
        assert "\n" not in result

    def test_long_name_preserved(self):
        long_name = "a" * 200
        result = sanitize_agent_name(long_name)
        assert result == long_name


# ============================================================================
# validate_agent_id_format: extended
# ============================================================================

class TestValidateAgentIdFormatExtended:

    def test_returns_sanitized_and_no_error(self):
        val, err = validate_agent_id_format("good_name")
        assert val == "good_name"
        assert err is None

    def test_special_chars_sanitized(self):
        val, err = validate_agent_id_format("test@agent#1")
        assert err is None
        assert "@" not in val
        assert "#" not in val

    def test_empty_string_auto_generates(self):
        val, err = validate_agent_id_format("")
        assert err is None
        assert val.startswith("agent_")

    def test_none_auto_generates(self):
        val, err = validate_agent_id_format(None)
        assert err is None
        assert val.startswith("agent_")


# ============================================================================
# validate_agent_id_policy: always passes (disabled)
# ============================================================================

class TestValidateAgentIdPolicyExtended:

    def test_test_prefix_allowed(self):
        val, err = validate_agent_id_policy("test_agent")
        assert err is None

    def test_demo_prefix_allowed(self):
        val, err = validate_agent_id_policy("demo_agent")
        assert err is None

    def test_any_name_allowed(self):
        val, err = validate_agent_id_policy("literally_anything_goes")
        assert err is None


# ============================================================================
# validate_agent_id_reserved_names: extended
# ============================================================================

class TestReservedNamesExtended:

    def test_all_reserved_exact_names(self):
        """All exact reserved names are blocked."""
        reserved = [
            "system", "admin", "root", "superuser", "administrator", "sudo",
            "null", "undefined", "none", "anonymous", "guest", "default",
            "mcp", "server", "client", "handler", "transport",
            "governance", "monitor", "arbiter", "validator", "auditor",
            "security", "auth", "identity", "certificate",
        ]
        for name in reserved:
            val, err = validate_agent_id_reserved_names(name)
            assert val is None, f"Reserved name '{name}' was not blocked"
            assert err is not None

    def test_reserved_names_case_insensitive(self):
        for name in ["SYSTEM", "Admin", "ROOT", "Null", "MCP"]:
            val, err = validate_agent_id_reserved_names(name)
            assert val is None, f"Reserved name '{name}' (case variant) was not blocked"

    def test_all_reserved_prefixes(self):
        prefixes = ["system_", "admin_", "root_", "mcp_", "governance_", "auth_"]
        for prefix in prefixes:
            val, err = validate_agent_id_reserved_names(prefix + "something")
            assert val is None, f"Reserved prefix '{prefix}' was not blocked"
            assert err is not None

    def test_reserved_prefix_case_insensitive(self):
        val, err = validate_agent_id_reserved_names("SYSTEM_monitor")
        assert val is None
        assert err is not None

    def test_non_reserved_with_reserved_substring(self):
        """Contains 'admin' but doesn't start with admin_ or equal 'admin'."""
        val, err = validate_agent_id_reserved_names("my_admin_helper")
        assert val == "my_admin_helper"
        assert err is None

    def test_error_contains_security_message(self):
        val, err = validate_agent_id_reserved_names("root")
        parsed = json.loads(err.text)
        assert "SECURITY" in parsed["error"]

    def test_prefix_error_contains_security_message(self):
        val, err = validate_agent_id_reserved_names("admin_tool")
        parsed = json.loads(err.text)
        assert "SECURITY" in parsed["error"]


# ============================================================================
# validate_file_path_policy: extended
# ============================================================================

class TestFilePathPolicyExtended:

    def test_demo_script_in_wrong_location(self):
        warning, err = validate_file_path_policy("demo_test.py")
        assert warning is not None
        assert "POLICY" in warning

    def test_test_in_nested_tests_dir(self):
        warning, err = validate_file_path_policy("src/tests/test_something.py")
        assert warning is None

    def test_non_python_test_prefix(self):
        """test_file.txt is not a .py file, no warning."""
        warning, err = validate_file_path_policy("test_file.txt")
        assert warning is None

    def test_readme_in_root(self):
        """README.md should not trigger warning - it's approved."""
        warning, err = validate_file_path_policy("README.md")
        assert warning is None

    def test_md_in_docs_guides(self):
        """Files in docs/guides/ are allowed."""
        warning, err = validate_file_path_policy("docs/guides/ONBOARDING.md")
        assert warning is None

    def test_md_in_docs_reference(self):
        """Files in docs/reference/ are allowed."""
        warning, err = validate_file_path_policy("docs/reference/SOME_NEW_DOC.md")
        assert warning is None

    def test_md_in_docs_archive(self):
        """Files in docs/archive/ are allowed."""
        warning, err = validate_file_path_policy("docs/archive/old_doc.md")
        assert warning is None

    def test_md_in_docs_analysis_migration_target(self):
        """Files in docs/analysis/ should warn - migration target."""
        warning, err = validate_file_path_policy("docs/analysis/my_analysis.md")
        assert warning is not None
        assert "POLICY" in warning

    def test_md_in_docs_fixes_migration_target(self):
        warning, err = validate_file_path_policy("docs/fixes/my_fix.md")
        assert warning is not None
        assert "POLICY" in warning

    def test_md_in_docs_reflection_migration_target(self):
        warning, err = validate_file_path_policy("docs/reflection/my_reflection.md")
        assert warning is not None
        assert "POLICY" in warning

    def test_md_in_docs_proposals_migration_target(self):
        warning, err = validate_file_path_policy("docs/proposals/my_proposal.md")
        assert warning is not None
        assert "POLICY" in warning

    def test_non_md_file_in_docs(self):
        """Non-markdown files in docs don't trigger warning."""
        warning, err = validate_file_path_policy("docs/analysis/script.py")
        assert warning is None

    def test_regular_python_file(self):
        warning, err = validate_file_path_policy("src/main.py")
        assert warning is None

    def test_regular_json_file(self):
        warning, err = validate_file_path_policy("config.json")
        assert warning is None


# ============================================================================
# detect_script_creation_avoidance: extended
# ============================================================================

class TestDetectScriptCreationAvoidanceExtended:

    def test_creating_script_to_test(self):
        warnings = detect_script_creation_avoidance("I'm creating a test script to test the auth flow")
        assert len(warnings) >= 1
        assert "AVOIDANCE" in warnings[0]

    def test_writing_quick_script(self):
        warnings = detect_script_creation_avoidance("Writing a quick test script to check")
        assert len(warnings) >= 1

    def test_make_script_to_verify(self):
        warnings = detect_script_creation_avoidance("Let me make a simple script to verify it works")
        assert len(warnings) >= 1

    def test_avoiding_mcp(self):
        warnings = detect_script_creation_avoidance("Let's avoid the MCP and do it directly")
        assert len(warnings) >= 1
        assert "AVOIDANCE LANGUAGE" in warnings[0]

    def test_bypass_tools(self):
        warnings = detect_script_creation_avoidance("I'll bypass the tools for now")
        assert len(warnings) >= 1

    def test_without_using_governance(self):
        warnings = detect_script_creation_avoidance("We can do this without using governance")
        assert len(warnings) >= 1

    def test_instead_of_mcp(self):
        warnings = detect_script_creation_avoidance("Let's do it instead of calling MCP")
        assert len(warnings) >= 1

    def test_creating_py_for_testing_outside_tests(self):
        """Creating .py file for testing outside tests/ dir."""
        warnings = detect_script_creation_avoidance("I'm creating verify.py to test the auth")
        assert isinstance(warnings, list)

    def test_creating_py_in_tests_dir_ok(self):
        """Mentioning tests/ directory should not trigger standalone file warning."""
        warnings = detect_script_creation_avoidance("I'm writing tests/test_auth.py to test the auth")
        # The standalone file pattern checks for absence of "tests/"
        # so this should NOT trigger that specific warning
        standalone_warnings = [w for w in warnings if "STANDALONE" in w]
        assert len(standalone_warnings) == 0

    def test_normal_work_description(self):
        warnings = detect_script_creation_avoidance(
            "I fixed the authentication bug by updating the validation logic."
        )
        assert warnings == []

    def test_code_review_description(self):
        warnings = detect_script_creation_avoidance(
            "I reviewed the code and found a pattern in the error handling."
        )
        assert warnings == []

    def test_only_one_script_warning(self):
        """Script creation detection should only warn once (break after first match)."""
        text = "Creating a test script to test. Also writing a quick script."
        warnings = detect_script_creation_avoidance(text)
        script_warnings = [w for w in warnings if "Creating scripts" in w or "Writing quick" in w]
        assert len(script_warnings) <= 1


# ============================================================================
# Data structures: extended validation
# ============================================================================

class TestDataStructuresExtended:

    def test_all_tools_have_required_and_optional(self):
        """Every tool schema has 'required' and 'optional' keys."""
        for tool_name, schema in TOOL_PARAM_SCHEMAS.items():
            assert "required" in schema, f"Tool '{tool_name}' missing 'required'"
            assert "optional" in schema, f"Tool '{tool_name}' missing 'optional'"

    def test_all_tools_have_example(self):
        """Every tool schema has an 'example' key."""
        for tool_name, schema in TOOL_PARAM_SCHEMAS.items():
            assert "example" in schema, f"Tool '{tool_name}' missing 'example'"

    def test_all_optional_params_have_type(self):
        """Every optional param spec has a 'type' key."""
        for tool_name, schema in TOOL_PARAM_SCHEMAS.items():
            for param_name, spec in schema.get("optional", {}).items():
                assert "type" in spec, f"Tool '{tool_name}' param '{param_name}' missing 'type'"

    def test_enum_params_have_values(self):
        """Every enum param has 'values' list."""
        for tool_name, schema in TOOL_PARAM_SCHEMAS.items():
            for param_name, spec in schema.get("optional", {}).items():
                if spec.get("type") == "enum":
                    assert "values" in spec, f"Tool '{tool_name}' param '{param_name}' enum missing 'values'"
                    assert len(spec["values"]) > 0

    def test_float_range_params_have_range(self):
        """Float params with range constraints have valid range tuples."""
        for tool_name, schema in TOOL_PARAM_SCHEMAS.items():
            for param_name, spec in schema.get("optional", {}).items():
                if "range" in spec:
                    r = spec["range"]
                    assert len(r) == 2
                    assert r[0] <= r[1]

    def test_generic_param_types_values_valid(self):
        """All GENERIC_PARAM_TYPES values are known type strings."""
        valid_types = {"float", "float_01", "int", "bool"}
        for param, ptype in GENERIC_PARAM_TYPES.items():
            assert ptype in valid_types, f"Param '{param}' has unknown type '{ptype}'"

    def test_param_aliases_tools_exist_in_schemas_or_are_valid(self):
        """Alias mappings reference tools that exist or are at least valid."""
        for tool_name in PARAM_ALIASES:
            # The tool doesn't need to be in TOOL_PARAM_SCHEMAS, but it should be a real tool
            assert isinstance(PARAM_ALIASES[tool_name], dict)

    def test_discovery_type_aliases_values_all_valid(self):
        """Every alias maps to a canonical discovery type."""
        for alias, canonical in DISCOVERY_TYPE_ALIASES.items():
            assert canonical in DISCOVERY_TYPES, f"Alias '{alias}' -> '{canonical}' not in DISCOVERY_TYPES"

    def test_no_duplicate_alias_keys(self):
        """Aliases dict has unique keys (Python enforces this, but test intent)."""
        for tool_name, aliases in PARAM_ALIASES.items():
            keys = list(aliases.keys())
            assert len(keys) == len(set(keys)), f"Duplicate alias keys in {tool_name}"


# ============================================================================
# Integration-style: combined alias + coercion + validation
# ============================================================================

class TestIntegrationScenarios:
    """End-to-end scenarios combining aliases, coercion, and validation."""

    def test_lite_agent_store_note_minimal(self):
        """Minimal call: alias 'note' to summary, no other params."""
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph", {"note": "Quick observation"}
        )
        assert error is None
        assert result["summary"] == "Quick observation"

    def test_lite_agent_store_with_type_alias_and_string_tags(self):
        """Alias type + discovery type alias, comma-separated tags."""
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph",
            {"content": "Found a bug", "type": "bug", "tags": "auth, security"}
        )
        assert error is None
        assert result["summary"] == "Found a bug"
        # "type" aliased to "discovery_type" by param alias,
        # then "bug" resolved to "bug_found" by discovery type alias
        assert result["discovery_type"] == "bug_found"
        assert result["tags"] == ["auth", "security"]

    def test_chatgpt_style_all_strings(self):
        """ChatGPT-style: everything as strings."""
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update",
            {
                "complexity": "0.5",
                "confidence": "0.8",
                "task_type": "mixed",
                "lite": "true",
            }
        )
        assert error is None
        assert result["complexity"] == 0.5
        assert result["confidence"] == 0.8
        assert result["lite"] is True

    def test_search_with_alias_and_coercion(self):
        result, error, fixes = validate_and_coerce_params(
            "search_knowledge_graph",
            {"find": "auth bug", "limit": "5", "semantic": "true"}
        )
        assert error is None
        assert result["query"] == "auth bug"
        assert result["limit"] == 5
        assert result["semantic"] is True

    def test_multiple_errors_in_one_call(self):
        """Multiple invalid params produce error."""
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update",
            {"task_type": "invalid_type"}
        )
        assert error is not None

    def test_identity_with_alias_display_name(self):
        result, error, fixes = validate_and_coerce_params(
            "identity", {"display_name": "My Agent"}
        )
        assert error is None
        assert result["name"] == "My Agent"


# ============================================================================
# validate_complexity / validate_confidence: focused edge cases
# ============================================================================

class TestComplexityConfidenceEdgeCases:

    def test_complexity_string_coercion(self):
        val, err = validate_complexity("0.5")
        assert val == 0.5
        assert err is None

    def test_complexity_zero(self):
        val, err = validate_complexity(0.0)
        assert val == 0.0
        assert err is None

    def test_complexity_one(self):
        val, err = validate_complexity(1.0)
        assert val == 1.0
        assert err is None

    def test_complexity_negative(self):
        val, err = validate_complexity(-0.01)
        assert err is not None

    def test_complexity_above_one(self):
        val, err = validate_complexity(1.01)
        assert err is not None

    def test_complexity_none(self):
        val, err = validate_complexity(None)
        assert val is None
        assert err is None

    def test_confidence_string_coercion(self):
        val, err = validate_confidence("0.9")
        assert val == 0.9
        assert err is None

    def test_confidence_none(self):
        val, err = validate_confidence(None)
        assert val is None
        assert err is None

    def test_confidence_int_one(self):
        val, err = validate_confidence(1)
        assert val == 1.0
        assert err is None

    def test_confidence_int_zero(self):
        val, err = validate_confidence(0)
        assert val == 0.0
        assert err is None


# ============================================================================
# Edge case: validate_and_coerce_params with None arguments for optional params
# ============================================================================

class TestNoneArgumentHandling:
    """Test that None values in optional params are correctly skipped."""

    def test_none_complexity_skipped(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"complexity": None}
        )
        assert error is None
        assert result["complexity"] is None

    def test_none_task_type_skipped(self):
        result, error, fixes = validate_and_coerce_params(
            "process_agent_update", {"task_type": None}
        )
        assert error is None

    def test_none_tags_skipped(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph", {"summary": "test", "tags": None}
        )
        assert error is None

    def test_none_discovery_type_skipped(self):
        result, error, fixes = validate_and_coerce_params(
            "store_knowledge_graph", {"summary": "test", "discovery_type": None}
        )
        assert error is None

    def test_none_limit_skipped(self):
        result, error, fixes = validate_and_coerce_params(
            "search_knowledge_graph", {"limit": None}
        )
        assert error is None
