"""
Tests for src/mcp_handlers/error_helpers.py - Standardized error responses.

All functions are pure (input → output), only dependency is error_response().
"""

import pytest
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.error_helpers import (
    RECOVERY_PATTERNS,
    agent_not_found_error,
    agent_not_registered_error,
    authentication_error,
    authentication_required_error,
    ownership_error,
    rate_limit_error,
    timeout_error,
    invalid_parameters_error,
    validation_error,
    resource_not_found_error,
    system_error,
    not_connected_error,
    missing_client_session_id_error,
    session_mismatch_error,
    missing_parameter_error,
    invalid_parameter_type_error,
    permission_denied_error,
    tool_not_found_error,
)


# Helper to extract JSON from TextContent
def _parse_error(result):
    """Extract parsed JSON from error response list."""
    assert len(result) == 1
    tc = result[0]
    assert hasattr(tc, "text")
    return json.loads(tc.text)


# ============================================================================
# RECOVERY_PATTERNS constant
# ============================================================================

class TestRecoveryPatterns:

    def test_all_expected_keys_present(self):
        expected = {
            "agent_not_found", "agent_not_registered", "authentication_failed",
            "authentication_required", "ownership_required", "rate_limit_exceeded",
            "timeout", "invalid_parameters", "validation_error", "system_error",
            "resource_not_found", "not_connected", "missing_client_session_id",
            "session_mismatch", "missing_parameter", "invalid_parameter_type",
            "permission_denied",
        }
        assert expected.issubset(set(RECOVERY_PATTERNS.keys()))

    def test_each_pattern_has_action(self):
        for key, pattern in RECOVERY_PATTERNS.items():
            assert "action" in pattern, f"Missing 'action' in {key}"
            assert isinstance(pattern["action"], str)

    def test_each_pattern_has_workflow(self):
        for key, pattern in RECOVERY_PATTERNS.items():
            assert "workflow" in pattern, f"Missing 'workflow' in {key}"
            assert isinstance(pattern["workflow"], list)
            assert len(pattern["workflow"]) >= 1


# ============================================================================
# agent_not_found_error
# ============================================================================

class TestAgentNotFoundError:

    def test_returns_list_of_one(self):
        result = agent_not_found_error("agent-123")
        assert len(result) == 1

    def test_message_contains_agent_id(self):
        data = _parse_error(agent_not_found_error("agent-abc"))
        assert "agent-abc" in data["error"]

    def test_error_code(self):
        data = _parse_error(agent_not_found_error("x"))
        assert data["error_code"] == "AGENT_NOT_FOUND"

    def test_custom_error_code(self):
        data = _parse_error(agent_not_found_error("x", error_code="CUSTOM"))
        assert data["error_code"] == "CUSTOM"

    def test_recovery_included(self):
        data = _parse_error(agent_not_found_error("x"))
        assert "recovery" in data


# ============================================================================
# agent_not_registered_error
# ============================================================================

class TestAgentNotRegisteredError:

    def test_message_contains_agent_id(self):
        data = _parse_error(agent_not_registered_error("agent-xyz"))
        assert "agent-xyz" in data["error"]

    def test_error_code(self):
        data = _parse_error(agent_not_registered_error("x"))
        assert data["error_code"] == "AGENT_NOT_REGISTERED"


# ============================================================================
# authentication_error
# ============================================================================

class TestAuthenticationError:

    def test_default_message(self):
        data = _parse_error(authentication_error())
        assert "Authentication failed" in data["error"]

    def test_with_agent_id(self):
        data = _parse_error(authentication_error(agent_id="agent-1"))
        assert "agent-1" in data["error"]

    def test_error_code(self):
        data = _parse_error(authentication_error())
        assert data["error_code"] == "AUTHENTICATION_FAILED"


# ============================================================================
# authentication_required_error
# ============================================================================

class TestAuthenticationRequiredError:

    def test_default_operation(self):
        data = _parse_error(authentication_required_error())
        assert "this operation" in data["error"]

    def test_custom_operation(self):
        data = _parse_error(authentication_required_error(operation="deleting agents"))
        assert "deleting agents" in data["error"]

    def test_error_code(self):
        data = _parse_error(authentication_required_error())
        assert data["error_code"] == "AUTHENTICATION_REQUIRED"


# ============================================================================
# ownership_error
# ============================================================================

class TestOwnershipError:

    def test_message_contains_all_ids(self):
        data = _parse_error(ownership_error(
            resource_type="discovery",
            resource_id="disc-1",
            owner_agent_id="owner-1",
            caller_agent_id="caller-1"
        ))
        assert "caller-1" in data["error"]
        assert "owner-1" in data["error"]
        assert "disc-1" in data["error"]

    def test_error_code(self):
        data = _parse_error(ownership_error("x", "y", "o", "c"))
        assert data["error_code"] == "OWNERSHIP_VIOLATION"


# ============================================================================
# rate_limit_error
# ============================================================================

class TestRateLimitError:

    def test_message_contains_agent_id(self):
        data = _parse_error(rate_limit_error("agent-1"))
        assert "agent-1" in data["error"]

    def test_with_stats(self):
        data = _parse_error(rate_limit_error("agent-1", stats={"remaining": 0}))
        assert data["error_code"] == "RATE_LIMIT_EXCEEDED"

    def test_without_stats(self):
        data = _parse_error(rate_limit_error("agent-1"))
        assert data["error_code"] == "RATE_LIMIT_EXCEEDED"


# ============================================================================
# timeout_error
# ============================================================================

class TestTimeoutError:

    def test_message_contains_tool_and_timeout(self):
        data = _parse_error(timeout_error("my_tool", 30.0))
        assert "my_tool" in data["error"]
        assert "30" in data["error"]

    def test_error_code(self):
        data = _parse_error(timeout_error("t", 1.0))
        assert data["error_code"] == "TIMEOUT"


# ============================================================================
# invalid_parameters_error
# ============================================================================

class TestInvalidParametersError:

    def test_basic(self):
        data = _parse_error(invalid_parameters_error("my_tool"))
        assert "my_tool" in data["error"]
        assert data["error_code"] == "INVALID_PARAMETERS"

    def test_with_details(self):
        data = _parse_error(invalid_parameters_error("t", details="missing field"))
        assert "missing field" in data["error"]

    def test_with_param_name(self):
        data = _parse_error(invalid_parameters_error("t", param_name="foo"))
        assert data["error_code"] == "INVALID_PARAMETERS"


# ============================================================================
# validation_error
# ============================================================================

class TestValidationError:

    def test_message(self):
        data = _parse_error(validation_error("Value out of range"))
        assert "Value out of range" in data["error"]

    def test_with_param_name(self):
        data = _parse_error(validation_error("bad value", param_name="complexity"))
        assert data["error_code"] == "VALIDATION_ERROR"

    def test_with_provided_value(self):
        data = _parse_error(validation_error("bad", provided_value=999))
        assert data["error_code"] == "VALIDATION_ERROR"


# ============================================================================
# resource_not_found_error
# ============================================================================

class TestResourceNotFoundError:

    def test_message(self):
        data = _parse_error(resource_not_found_error("discovery", "disc-123"))
        assert "disc-123" in data["error"]
        assert "Discovery" in data["error"]  # Capitalized

    def test_error_code(self):
        data = _parse_error(resource_not_found_error("agent", "a-1"))
        assert data["error_code"] == "RESOURCE_NOT_FOUND"


# ============================================================================
# system_error
# ============================================================================

class TestSystemError:

    def test_message(self):
        data = _parse_error(system_error("my_tool", ValueError("boom")))
        assert "my_tool" in data["error"]
        assert "boom" in data["error"]

    def test_error_code(self):
        data = _parse_error(system_error("t", RuntimeError("x")))
        assert data["error_code"] == "SYSTEM_ERROR"


# ============================================================================
# not_connected_error
# ============================================================================

class TestNotConnectedError:

    def test_message(self):
        data = _parse_error(not_connected_error())
        assert "connection" in data["error"].lower()

    def test_error_code(self):
        data = _parse_error(not_connected_error())
        assert data["error_code"] == "NOT_CONNECTED"


# ============================================================================
# missing_client_session_id_error
# ============================================================================

class TestMissingClientSessionIdError:

    def test_default(self):
        data = _parse_error(missing_client_session_id_error())
        assert "client_session_id" in data["error"]

    def test_custom_operation(self):
        data = _parse_error(missing_client_session_id_error(operation="archiving"))
        assert "archiving" in data["error"]


# ============================================================================
# session_mismatch_error
# ============================================================================

class TestSessionMismatchError:

    def test_expected_only(self):
        data = _parse_error(session_mismatch_error("abcdef1234567890"))
        assert "abcdef12" in data["error"]

    def test_with_provided_id(self):
        data = _parse_error(session_mismatch_error("abcdef1234567890", "zzzzaaaa12345678"))
        assert "abcdef12" in data["error"]
        assert "zzzzaaaa" in data["error"]

    def test_error_code(self):
        data = _parse_error(session_mismatch_error("x" * 16))
        assert data["error_code"] == "SESSION_MISMATCH"


# ============================================================================
# missing_parameter_error
# ============================================================================

class TestMissingParameterError:

    def test_basic(self):
        data = _parse_error(missing_parameter_error("summary"))
        assert "summary" in data["error"]

    def test_with_tool_name(self):
        data = _parse_error(missing_parameter_error("summary", tool_name="leave_note"))
        assert "leave_note" in data["error"]

    def test_leave_note_examples(self):
        data = _parse_error(missing_parameter_error("summary", tool_name="leave_note"))
        # Should include examples for leave_note
        assert data["error_code"] == "MISSING_PARAMETER"

    def test_custom_message_in_context(self):
        data = _parse_error(missing_parameter_error(
            "query", context={"custom_message": "Try adding a search term"}
        ))
        assert "search term" in data["error"]


# ============================================================================
# invalid_parameter_type_error
# ============================================================================

class TestInvalidParameterTypeError:

    def test_basic(self):
        data = _parse_error(invalid_parameter_type_error("complexity", "float", "string"))
        assert "complexity" in data["error"]
        assert "float" in data["error"]
        assert "string" in data["error"]

    def test_with_tool_name(self):
        data = _parse_error(invalid_parameter_type_error("x", "int", "str", tool_name="my_tool"))
        assert "my_tool" in data["error"]

    def test_error_code(self):
        data = _parse_error(invalid_parameter_type_error("x", "int", "str"))
        assert data["error_code"] == "INVALID_PARAMETER_TYPE"


# ============================================================================
# permission_denied_error
# ============================================================================

class TestPermissionDeniedError:

    def test_basic(self):
        data = _parse_error(permission_denied_error("delete_agent"))
        assert "delete_agent" in data["error"]

    def test_with_role(self):
        data = _parse_error(permission_denied_error("admin_op", required_role="admin"))
        assert "admin" in data["error"]

    def test_error_code(self):
        data = _parse_error(permission_denied_error("op"))
        assert data["error_code"] == "PERMISSION_DENIED"


# ============================================================================
# tool_not_found_error
# ============================================================================

class TestToolNotFoundError:

    def test_with_similar_tools(self):
        available = ["process_agent_update", "list_agents", "health_check"]
        data = _parse_error(tool_not_found_error("process_agent", available))
        assert "process_agent" in data["error"]

    def test_no_similar_tools(self):
        available = ["foo", "bar", "baz"]
        data = _parse_error(tool_not_found_error("xyzzy_nothing", available))
        assert "xyzzy_nothing" in data["error"]

    def test_error_code(self):
        data = _parse_error(tool_not_found_error("x", []))
        assert data["error_code"] == "TOOL_NOT_FOUND"

    def test_suggestions_in_response(self):
        available = ["process_agent_update", "list_agents"]
        data = _parse_error(tool_not_found_error("process_agent", available))
        assert "similar_tools" in data
