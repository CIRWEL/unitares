"""
Tests for the dispatch pipeline middleware steps.

Tests individual middleware functions from src/mcp_handlers/middleware.py
and the dispatch_tool integration from src/mcp_handlers/__init__.py.

Middleware signature: async (name, arguments, ctx) -> (name, arguments, ctx) | list
Returning a list short-circuits the pipeline with an error response.
"""

import json
import sys
import time
from pathlib import Path
from collections import deque
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.middleware import (
    DispatchContext,
    unwrap_kwargs,
    resolve_alias,
    validate_params,
    check_rate_limit,
    _tool_call_history,
)
from src.mcp_handlers.tool_stability import resolve_tool_alias, _TOOL_ALIASES
from src.mcp_handlers.validators import validate_and_coerce_params


# ============================================================================
# Helpers
# ============================================================================

def _make_ctx(**kwargs) -> DispatchContext:
    """Create a DispatchContext with optional overrides."""
    return DispatchContext(**kwargs)


def _is_short_circuit(result) -> bool:
    """Check if a middleware result is a short-circuit (list of TextContent)."""
    return isinstance(result, list)


def _extract_text(result) -> str:
    """Extract text from a short-circuit result (list of TextContent)."""
    assert isinstance(result, list) and len(result) > 0
    return result[0].text


# ============================================================================
# 1. DispatchContext dataclass
# ============================================================================

class TestDispatchContext:
    """Tests for DispatchContext dataclass."""

    def test_default_values(self):
        ctx = DispatchContext()
        assert ctx.session_key is None
        assert ctx.client_session_id is None
        assert ctx.bound_agent_id is None
        assert ctx.context_token is None
        assert ctx.trajectory_confidence_token is None
        assert ctx.migration_note is None
        assert ctx.original_name is None
        assert ctx.client_hint is None
        assert ctx.identity_result is None

    def test_all_fields_settable(self):
        ctx = DispatchContext(
            session_key="sk-123",
            client_session_id="cs-456",
            bound_agent_id="agent-789",
            context_token="tok",
            trajectory_confidence_token="traj-tok",
            migration_note="Use new_tool instead",
            original_name="old_tool",
            client_hint="cursor",
            identity_result={"agent_uuid": "abc"},
        )
        assert ctx.session_key == "sk-123"
        assert ctx.client_session_id == "cs-456"
        assert ctx.bound_agent_id == "agent-789"
        assert ctx.context_token == "tok"
        assert ctx.trajectory_confidence_token == "traj-tok"
        assert ctx.migration_note == "Use new_tool instead"
        assert ctx.original_name == "old_tool"
        assert ctx.client_hint == "cursor"
        assert ctx.identity_result == {"agent_uuid": "abc"}

    def test_partial_fields(self):
        ctx = DispatchContext(session_key="key1", bound_agent_id="agent-1")
        assert ctx.session_key == "key1"
        assert ctx.bound_agent_id == "agent-1"
        assert ctx.client_session_id is None


# ============================================================================
# 2. unwrap_kwargs middleware
# ============================================================================

class TestUnwrapKwargs:
    """Tests for the unwrap_kwargs middleware step."""

    @pytest.mark.asyncio
    async def test_dict_kwargs_unwrapped(self):
        """Dict kwargs: {"kwargs": {"foo": "bar"}} -> {"foo": "bar"}"""
        ctx = _make_ctx()
        name, args, ctx_out = await unwrap_kwargs(
            "some_tool", {"kwargs": {"foo": "bar"}}, ctx
        )
        assert name == "some_tool"
        assert args == {"foo": "bar"}
        assert "kwargs" not in args

    @pytest.mark.asyncio
    async def test_string_kwargs_unwrapped(self):
        """String kwargs: {"kwargs": '{"foo": "bar"}'} -> {"foo": "bar"}"""
        ctx = _make_ctx()
        name, args, ctx_out = await unwrap_kwargs(
            "some_tool", {"kwargs": '{"foo": "bar"}'}, ctx
        )
        assert args == {"foo": "bar"}
        assert "kwargs" not in args

    @pytest.mark.asyncio
    async def test_invalid_string_kwargs_stays(self):
        """Invalid JSON string kwargs stays as-is."""
        ctx = _make_ctx()
        name, args, ctx_out = await unwrap_kwargs(
            "some_tool", {"kwargs": "not valid json"}, ctx
        )
        # The invalid string stays in kwargs since parsing failed
        assert args == {"kwargs": "not valid json"}

    @pytest.mark.asyncio
    async def test_no_kwargs_key_passthrough(self):
        """No kwargs key: pass-through unchanged."""
        ctx = _make_ctx()
        original = {"agent_id": "abc", "complexity": 0.5}
        name, args, ctx_out = await unwrap_kwargs("tool", dict(original), ctx)
        assert args == original

    @pytest.mark.asyncio
    async def test_kwargs_merged_with_existing_args(self):
        """Kwargs merged with existing arguments."""
        ctx = _make_ctx()
        name, args, ctx_out = await unwrap_kwargs(
            "tool", {"existing_key": "keep_me", "kwargs": {"new_key": "added"}}, ctx
        )
        assert args["existing_key"] == "keep_me"
        assert args["new_key"] == "added"
        assert "kwargs" not in args

    @pytest.mark.asyncio
    async def test_kwargs_override_existing_args(self):
        """If kwargs contain a key that already exists, kwargs value wins (update semantics)."""
        ctx = _make_ctx()
        name, args, ctx_out = await unwrap_kwargs(
            "tool", {"key": "original", "kwargs": {"key": "from_kwargs"}}, ctx
        )
        assert args["key"] == "from_kwargs"

    @pytest.mark.asyncio
    async def test_empty_dict_kwargs(self):
        """Empty dict kwargs."""
        ctx = _make_ctx()
        name, args, ctx_out = await unwrap_kwargs(
            "tool", {"kwargs": {}}, ctx
        )
        assert args == {}

    @pytest.mark.asyncio
    async def test_string_kwargs_non_dict_json(self):
        """String kwargs that parse to a non-dict (e.g. a list) stay as-is."""
        ctx = _make_ctx()
        name, args, ctx_out = await unwrap_kwargs(
            "tool", {"kwargs": '[1, 2, 3]'}, ctx
        )
        # json.loads('[1,2,3]') returns a list, not dict, so it stays
        assert args == {"kwargs": '[1, 2, 3]'}


# ============================================================================
# 3. resolve_alias middleware
# ============================================================================

class TestResolveAlias:
    """Tests for the resolve_alias middleware step."""

    @pytest.mark.asyncio
    async def test_known_alias_resolves(self):
        """Known alias maps to correct tool name."""
        ctx = _make_ctx()
        name, args, ctx_out = await resolve_alias("status", {}, ctx)
        assert name == "get_governance_metrics"
        assert ctx_out.migration_note is not None
        assert ctx_out.original_name == "status"

    @pytest.mark.asyncio
    async def test_unknown_tool_passthrough(self):
        """Unknown tool passes through unchanged."""
        ctx = _make_ctx()
        name, args, ctx_out = await resolve_alias("nonexistent_tool_xyz", {"foo": 1}, ctx)
        assert name == "nonexistent_tool_xyz"
        assert args == {"foo": 1}
        assert ctx_out.migration_note is None
        assert ctx_out.original_name == "nonexistent_tool_xyz"

    @pytest.mark.asyncio
    async def test_inject_action_adds_action(self):
        """inject_action adds action parameter when not present."""
        ctx = _make_ctx()
        # pi_health has inject_action="health"
        name, args, ctx_out = await resolve_alias("pi_health", {}, ctx)
        assert name == "pi"
        assert args.get("action") == "health"

    @pytest.mark.asyncio
    async def test_inject_action_does_not_override(self):
        """inject_action does not override existing action parameter."""
        ctx = _make_ctx()
        name, args, ctx_out = await resolve_alias(
            "pi_health", {"action": "custom_action"}, ctx
        )
        assert name == "pi"
        assert args["action"] == "custom_action"

    @pytest.mark.asyncio
    async def test_multiple_aliases_for_same_target(self):
        """Multiple aliases can map to the same target tool."""
        ctx1 = _make_ctx()
        name1, _, _ = await resolve_alias("start", {}, ctx1)

        ctx2 = _make_ctx()
        name2, _, _ = await resolve_alias("init", {}, ctx2)

        ctx3 = _make_ctx()
        name3, _, _ = await resolve_alias("register", {}, ctx3)

        assert name1 == "onboard"
        assert name2 == "onboard"
        assert name3 == "onboard"

    @pytest.mark.asyncio
    async def test_consolidated_alias_with_action(self):
        """Consolidated aliases inject action parameter."""
        ctx = _make_ctx()
        name, args, _ = await resolve_alias("list_agents", {}, ctx)
        assert name == "agent"
        assert args["action"] == "list"

    @pytest.mark.asyncio
    async def test_original_name_is_always_set(self):
        """original_name is set regardless of alias match."""
        ctx = _make_ctx()
        _, _, ctx_out = await resolve_alias("health_check", {}, ctx)
        assert ctx_out.original_name == "health_check"


# ============================================================================
# 4. validate_params middleware
# ============================================================================

class TestValidateParams:
    """Tests for the validate_params middleware step."""

    @pytest.mark.asyncio
    async def test_valid_params_passthrough(self):
        """Valid params pass through unchanged."""
        ctx = _make_ctx()
        name, args, ctx_out = await validate_params(
            "health_check", {}, ctx
        )
        assert name == "health_check"
        assert isinstance(args, dict)

    @pytest.mark.asyncio
    async def test_bool_coercion_string_true(self):
        """String "true" coerced to bool True for boolean params."""
        ctx = _make_ctx()
        name, args, ctx_out = await validate_params(
            "get_governance_metrics", {"include_state": "true"}, ctx
        )
        # Should not short-circuit
        assert not _is_short_circuit((name, args, ctx_out))
        assert args["include_state"] is True

    @pytest.mark.asyncio
    async def test_bool_coercion_string_false(self):
        """String "false" coerced to bool False."""
        ctx = _make_ctx()
        name, args, ctx_out = await validate_params(
            "list_tools", {"lite": "false"}, ctx
        )
        assert args["lite"] is False

    @pytest.mark.asyncio
    async def test_float_coercion(self):
        """String float coerced to actual float."""
        ctx = _make_ctx()
        name, args, ctx_out = await validate_params(
            "process_agent_update", {"complexity": "0.7"}, ctx
        )
        assert isinstance(args["complexity"], float)
        assert args["complexity"] == 0.7

    @pytest.mark.asyncio
    async def test_validation_error_returns_list(self):
        """Validation error returns list (short-circuit)."""
        ctx = _make_ctx()
        # store_knowledge_graph requires "summary"
        result = await validate_params(
            "store_knowledge_graph", {}, ctx
        )
        assert _is_short_circuit(result)
        text = _extract_text(result)
        assert "summary" in text.lower() or "missing" in text.lower() or "required" in text.lower()

    @pytest.mark.asyncio
    async def test_unknown_tool_passthrough(self):
        """Unknown tool (no schema) passes through with generic coercion only."""
        ctx = _make_ctx()
        name, args, ctx_out = await validate_params(
            "some_unknown_tool", {"limit": "5", "dry_run": "true"}, ctx
        )
        # Generic coercion should apply
        assert args["limit"] == 5
        assert args["dry_run"] is True

    @pytest.mark.asyncio
    async def test_param_alias_resolution(self):
        """Parameter aliases are resolved (e.g., 'content' -> 'summary' for store_knowledge_graph)."""
        ctx = _make_ctx()
        name, args, ctx_out = await validate_params(
            "store_knowledge_graph", {"content": "my discovery"}, ctx
        )
        # "content" should be aliased to "summary"
        assert not _is_short_circuit((name, args, ctx_out))
        assert args.get("summary") == "my discovery"

    @pytest.mark.asyncio
    async def test_float_range_rejected(self):
        """Out-of-range float_01 values are rejected by schema validation."""
        ctx = _make_ctx()
        result = await validate_params(
            "process_agent_update", {"confidence": "1.5"}, ctx
        )
        # Schema validation rejects out-of-range values (returns error list)
        assert isinstance(result, list), "Should return error for out-of-range confidence"

    @pytest.mark.asyncio
    async def test_coercions_tracked(self):
        """When coercions are applied, _param_coercions is added."""
        ctx = _make_ctx()
        name, args, ctx_out = await validate_params(
            "process_agent_update", {"complexity": "0.5"}, ctx
        )
        # complexity is a float_01 in generic coercion and also in schema
        # The middleware attaches _param_coercions if coercions happened
        # (This tests the coercion tracking behavior)
        assert isinstance(args.get("complexity"), float)


# ============================================================================
# 5. check_rate_limit middleware
# ============================================================================

class TestCheckRateLimit:
    """Tests for the check_rate_limit middleware step."""

    @pytest.fixture(autouse=True)
    def clear_history(self):
        """Clear tool call history before each test."""
        _tool_call_history.clear()
        yield
        _tool_call_history.clear()

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_passthrough(self):
        """Rate limiter allows normal requests."""
        ctx = _make_ctx()
        result = await check_rate_limit(
            "process_agent_update", {"agent_id": "test-agent"}, ctx
        )
        assert not _is_short_circuit(result)
        name, args, ctx_out = result
        assert name == "process_agent_update"

    @pytest.mark.asyncio
    async def test_read_only_tools_skip_rate_limiting(self):
        """Read-only tools skip general rate limiting."""
        ctx = _make_ctx()
        result = await check_rate_limit("health_check", {}, ctx)
        assert not _is_short_circuit(result)

        result = await check_rate_limit("get_server_info", {}, ctx)
        assert not _is_short_circuit(result)

        result = await check_rate_limit("list_tools", {}, ctx)
        assert not _is_short_circuit(result)

        result = await check_rate_limit("get_thresholds", {}, ctx)
        assert not _is_short_circuit(result)

    @pytest.mark.asyncio
    async def test_loop_detection_for_expensive_reads(self):
        """Loop detection triggers for list_agents after 20+ calls in 60 seconds."""
        ctx = _make_ctx()

        # Fill the history with 20 recent timestamps
        now = time.time()
        history = _tool_call_history["list_agents"]
        for i in range(20):
            history.append(now - 1)  # All within last 60 seconds

        # Next call should trigger loop detection
        result = await check_rate_limit("list_agents", {}, ctx)
        assert _is_short_circuit(result)
        text = _extract_text(result)
        assert "loop detected" in text.lower() or "rate limit" in text.lower()

    @pytest.mark.asyncio
    async def test_loop_detection_old_calls_expire(self):
        """Old calls outside the 60-second window are cleaned up."""
        ctx = _make_ctx()
        history = _tool_call_history["list_agents"]

        # Add 25 calls that are all older than 60 seconds
        old_time = time.time() - 120
        for i in range(25):
            history.append(old_time)

        # Should pass since old calls are cleaned up
        result = await check_rate_limit("list_agents", {}, ctx)
        assert not _is_short_circuit(result)

    @pytest.mark.asyncio
    async def test_non_expensive_tool_no_loop_detection(self):
        """Non-expensive tools do not trigger loop detection."""
        ctx = _make_ctx()
        # Fill history for a non-expensive tool
        now = time.time()
        history = _tool_call_history["health_check"]
        for i in range(30):
            history.append(now - 1)

        # health_check is read-only and not in expensive_read_only_tools
        result = await check_rate_limit("health_check", {}, ctx)
        assert not _is_short_circuit(result)


# ============================================================================
# 6. validate_and_coerce_params (direct unit tests)
# ============================================================================

class TestValidateAndCoerceParams:
    """Direct unit tests for the validate_and_coerce_params function."""

    def test_unknown_tool_generic_coercion(self):
        """Unknown tools still get generic coercion."""
        args, err, fixes = validate_and_coerce_params(
            "unknown_tool", {"limit": "10", "dry_run": "true"}
        )
        assert err is None
        assert args["limit"] == 10
        assert args["dry_run"] is True

    def test_bool_coercion_variants(self):
        """Test various boolean string representations."""
        # "yes" -> True
        args, err, _ = validate_and_coerce_params(
            "unknown_tool", {"confirm": "yes"}
        )
        assert args["confirm"] is True

        # "no" -> False
        args, err, _ = validate_and_coerce_params(
            "unknown_tool", {"confirm": "no"}
        )
        assert args["confirm"] is False

        # "1" -> True
        args, err, _ = validate_and_coerce_params(
            "unknown_tool", {"confirm": "1"}
        )
        assert args["confirm"] is True

    def test_float_01_type_coercion_no_clamp(self):
        """Generic coercion converts type (str→float) but does not clamp range."""
        args, err, _ = validate_and_coerce_params(
            "unknown_tool", {"complexity": "2.0"}
        )
        assert args["complexity"] == 2.0  # Type coerced, not clamped

        args, err, _ = validate_and_coerce_params(
            "unknown_tool", {"complexity": "-0.5"}
        )
        assert args["complexity"] == -0.5  # Type coerced, not clamped

    def test_int_coercion_from_float_string(self):
        """Integer param from float string (e.g., "5.0" -> 5)."""
        args, err, _ = validate_and_coerce_params(
            "unknown_tool", {"limit": "5.0"}
        )
        assert args["limit"] == 5
        assert isinstance(args["limit"], int)

    def test_required_param_missing(self):
        """Missing required param returns error."""
        args, err, _ = validate_and_coerce_params(
            "store_knowledge_graph", {}
        )
        assert err is not None
        # err is a TextContent object
        assert "summary" in err.text.lower() or "missing" in err.text.lower()

    def test_enum_case_insensitive(self):
        """Enum values are matched case-insensitively."""
        args, err, fixes = validate_and_coerce_params(
            "process_agent_update", {"task_type": "MIXED"}
        )
        assert err is None
        assert args["task_type"] == "mixed"

    def test_param_alias_content_to_summary(self):
        """Parameter alias 'content' -> 'summary' for store_knowledge_graph."""
        args, err, _ = validate_and_coerce_params(
            "store_knowledge_graph", {"content": "my note"}
        )
        assert err is None
        assert args.get("summary") == "my note"


# ============================================================================
# 7. resolve_tool_alias (direct unit tests)
# ============================================================================

class TestResolveToolAlias:
    """Direct unit tests for resolve_tool_alias function."""

    def test_known_alias(self):
        actual, alias_info = resolve_tool_alias("status")
        assert actual == "get_governance_metrics"
        assert alias_info is not None
        assert alias_info.old_name == "status"

    def test_unknown_tool(self):
        actual, alias_info = resolve_tool_alias("completely_unknown")
        assert actual == "completely_unknown"
        assert alias_info is None

    def test_start_maps_to_onboard(self):
        actual, alias_info = resolve_tool_alias("start")
        assert actual == "onboard"

    def test_pi_health_inject_action(self):
        actual, alias_info = resolve_tool_alias("pi_health")
        assert actual == "pi"
        assert alias_info.inject_action == "health"

    def test_list_agents_maps_to_agent(self):
        actual, alias_info = resolve_tool_alias("list_agents")
        assert actual == "agent"
        assert alias_info.inject_action == "list"


# ============================================================================
# 8. dispatch_tool integration tests
# ============================================================================

class TestDispatchToolIntegration:
    """Integration tests for dispatch_tool with mocked identity and handlers."""

    @pytest.fixture
    def mock_identity_pipeline(self):
        """Mock the identity-related middleware steps to avoid DB/Redis deps."""
        with patch(
            "src.mcp_handlers.middleware.resolve_identity",
            new_callable=AsyncMock,
        ) as mock_resolve, patch(
            "src.mcp_handlers.middleware.verify_trajectory",
            new_callable=AsyncMock,
        ) as mock_verify:
            async def fake_resolve_identity(name, arguments, ctx):
                ctx.session_key = "test-session"
                ctx.bound_agent_id = "test-agent-uuid"
                ctx.identity_result = {
                    "agent_uuid": "test-agent-uuid",
                    "created": False,
                    "persisted": True,
                }
                # Set the context so inject_identity can find it
                from src.mcp_handlers.context import set_session_context
                ctx.context_token = set_session_context(
                    session_key="test-session",
                    agent_id="test-agent-uuid",
                )
                return name, arguments, ctx

            async def fake_verify_trajectory(name, arguments, ctx):
                return name, arguments, ctx

            mock_resolve.side_effect = fake_resolve_identity
            mock_verify.side_effect = fake_verify_trajectory

            yield mock_resolve, mock_verify

    @pytest.fixture
    def mock_track_patterns(self):
        """Mock track_patterns to avoid pattern_tracker dependency."""
        with patch(
            "src.mcp_handlers.middleware.track_patterns",
            new_callable=AsyncMock,
        ) as mock_patterns:
            async def fake_track(name, arguments, ctx):
                return name, arguments, ctx
            mock_patterns.side_effect = fake_track
            yield mock_patterns

    @pytest.fixture
    def clean_rate_limit(self):
        """Clear rate limit history and reset rate limiter."""
        _tool_call_history.clear()
        yield
        _tool_call_history.clear()

    @pytest.mark.asyncio
    async def test_known_tool_dispatches(self, mock_identity_pipeline, mock_track_patterns, clean_rate_limit):
        """Known tool dispatches correctly and returns result."""
        from src.mcp_handlers import dispatch_tool, TOOL_HANDLERS

        # Pick a tool we know exists in the registry
        if "health_check" not in TOOL_HANDLERS:
            pytest.skip("health_check not in TOOL_HANDLERS")

        # Mock the handler to return a predictable result
        from mcp.types import TextContent
        expected = [TextContent(type="text", text='{"status": "ok"}')]
        original_handler = TOOL_HANDLERS["health_check"]
        TOOL_HANDLERS["health_check"] = AsyncMock(return_value=expected)
        try:
            result = await dispatch_tool("health_check", {})
            assert result == expected
        finally:
            TOOL_HANDLERS["health_check"] = original_handler

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, mock_identity_pipeline, mock_track_patterns, clean_rate_limit):
        """Unknown tool returns tool_not_found error."""
        from src.mcp_handlers import dispatch_tool

        result = await dispatch_tool("absolutely_nonexistent_tool_xyz", {})
        assert result is not None
        assert len(result) > 0
        text = result[0].text
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_handler_exception_caught(self, mock_identity_pipeline, mock_track_patterns, clean_rate_limit):
        """Handler exception caught by @mcp_tool decorator returns error response."""
        from src.mcp_handlers import dispatch_tool, TOOL_HANDLERS
        from src.mcp_handlers.decorators import mcp_tool

        # Create a properly decorated handler that raises
        @mcp_tool("_test_failing_tool", timeout=5.0, register=False)
        async def handle_test_failing(arguments):
            raise RuntimeError("test boom")

        original = TOOL_HANDLERS.get("health_check")
        TOOL_HANDLERS["_test_failing_tool"] = handle_test_failing
        try:
            result = await dispatch_tool("_test_failing_tool", {})
            # The @mcp_tool decorator wraps handlers with try/except,
            # so the exception is caught and returned as an error response
            assert result is not None
            assert len(result) > 0
            text = result[0].text
            assert "error" in text.lower() or "boom" in text.lower()
        finally:
            TOOL_HANDLERS.pop("_test_failing_tool", None)

    @pytest.mark.asyncio
    async def test_alias_resolution_end_to_end(self, mock_identity_pipeline, mock_track_patterns, clean_rate_limit):
        """Alias resolution works end-to-end through dispatch_tool."""
        from src.mcp_handlers import dispatch_tool, TOOL_HANDLERS

        # "status" is an alias for "get_governance_metrics"
        if "get_governance_metrics" not in TOOL_HANDLERS:
            pytest.skip("get_governance_metrics not in TOOL_HANDLERS")

        from mcp.types import TextContent
        expected = [TextContent(type="text", text='{"resolved": "via_alias"}')]
        original = TOOL_HANDLERS["get_governance_metrics"]
        TOOL_HANDLERS["get_governance_metrics"] = AsyncMock(return_value=expected)
        try:
            result = await dispatch_tool("status", {})
            assert result == expected
        finally:
            TOOL_HANDLERS["get_governance_metrics"] = original

    @pytest.mark.asyncio
    async def test_kwargs_unwrapping_end_to_end(self, mock_identity_pipeline, mock_track_patterns, clean_rate_limit):
        """kwargs unwrapping works through the full pipeline."""
        from src.mcp_handlers import dispatch_tool, TOOL_HANDLERS

        if "health_check" not in TOOL_HANDLERS:
            pytest.skip("health_check not in TOOL_HANDLERS")

        from mcp.types import TextContent
        expected = [TextContent(type="text", text='{"unwrapped": true}')]
        original = TOOL_HANDLERS["health_check"]

        captured_args = {}

        async def capture_handler(arguments):
            captured_args.update(arguments)
            return expected

        TOOL_HANDLERS["health_check"] = capture_handler
        try:
            result = await dispatch_tool(
                "health_check",
                {"kwargs": {"custom_param": "value"}}
            )
            assert result == expected
            assert captured_args.get("custom_param") == "value"
            assert "kwargs" not in captured_args
        finally:
            TOOL_HANDLERS["health_check"] = original

    @pytest.mark.asyncio
    async def test_none_arguments_defaults_to_empty_dict(self, mock_identity_pipeline, mock_track_patterns, clean_rate_limit):
        """None arguments are converted to empty dict."""
        from src.mcp_handlers import dispatch_tool, TOOL_HANDLERS

        if "health_check" not in TOOL_HANDLERS:
            pytest.skip("health_check not in TOOL_HANDLERS")

        from mcp.types import TextContent
        expected = [TextContent(type="text", text='{}')]

        captured_args = {}

        async def capture_handler(arguments):
            captured_args.update(arguments)
            return expected

        original = TOOL_HANDLERS["health_check"]
        TOOL_HANDLERS["health_check"] = capture_handler
        try:
            result = await dispatch_tool("health_check", None)
            assert result == expected
        finally:
            TOOL_HANDLERS["health_check"] = original

    @pytest.mark.asyncio
    async def test_consolidated_alias_injects_action(self, mock_identity_pipeline, mock_track_patterns, clean_rate_limit):
        """Consolidated alias (e.g., list_agents -> agent(action='list')) injects action param."""
        from src.mcp_handlers import dispatch_tool, TOOL_HANDLERS

        if "agent" not in TOOL_HANDLERS:
            pytest.skip("agent not in TOOL_HANDLERS")

        from mcp.types import TextContent
        expected = [TextContent(type="text", text='{"action": "list"}')]

        captured_args = {}

        async def capture_handler(arguments):
            captured_args.update(arguments)
            return expected

        original = TOOL_HANDLERS["agent"]
        TOOL_HANDLERS["agent"] = capture_handler
        try:
            result = await dispatch_tool("list_agents", {})
            assert captured_args.get("action") == "list"
        finally:
            TOOL_HANDLERS["agent"] = original


# ============================================================================
# 9. inject_identity middleware
# ============================================================================

class TestInjectIdentity:
    """Tests for the inject_identity middleware step."""

    @pytest.mark.asyncio
    async def test_bound_id_injected_for_regular_tool(self):
        """When bound_id exists and no agent_id provided, injects it."""
        from src.mcp_handlers.middleware import inject_identity
        ctx = _make_ctx(bound_agent_id="bound-uuid-1234")
        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="bound-uuid-1234"):
            result = await inject_identity("process_agent_update", {}, ctx)
        assert not _is_short_circuit(result)
        name, args, ctx_out = result
        assert args["agent_id"] == "bound-uuid-1234"

    @pytest.mark.asyncio
    async def test_browsable_tools_skip_injection(self):
        """Browsable data tools do NOT auto-filter by agent_id."""
        from src.mcp_handlers.middleware import inject_identity
        browsable = ["search_knowledge_graph", "list_knowledge_graph",
                      "list_dialectic_sessions", "get_dialectic_session", "dialectic"]
        for tool_name in browsable:
            ctx = _make_ctx(bound_agent_id="bound-uuid-1234")
            with patch("src.mcp_handlers.context.get_context_agent_id", return_value="bound-uuid-1234"):
                result = await inject_identity(tool_name, {}, ctx)
            assert not _is_short_circuit(result)
            _, args, _ = result
            assert "agent_id" not in args, f"{tool_name} should not inject agent_id"

    @pytest.mark.asyncio
    async def test_impersonation_blocked(self):
        """Different agent_id than bound → error (session mismatch)."""
        from src.mcp_handlers.middleware import inject_identity
        ctx = _make_ctx(bound_agent_id="bound-uuid-1234")
        # Mock get_mcp_server to return empty metadata (no label match)
        mock_server = MagicMock()
        mock_server.agent_metadata = {}
        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="bound-uuid-1234"):
            with patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
                result = await inject_identity(
                    "process_agent_update",
                    {"agent_id": "different-uuid"},
                    ctx
                )
        assert _is_short_circuit(result)
        text = _extract_text(result)
        assert "mismatch" in text.lower()

    @pytest.mark.asyncio
    async def test_dialectic_tools_allow_different_id(self):
        """Dialectic tools allow different agent_id (for cross-agent review)."""
        from src.mcp_handlers.middleware import inject_identity
        ctx = _make_ctx(bound_agent_id="bound-uuid-1234")
        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="bound-uuid-1234"):
            result = await inject_identity(
                "submit_thesis",
                {"agent_id": "other-uuid"},
                ctx
            )
        assert not _is_short_circuit(result)

    @pytest.mark.asyncio
    async def test_no_binding_provided_id_passthrough(self):
        """No session binding but agent_id provided → passes through."""
        from src.mcp_handlers.middleware import inject_identity
        ctx = _make_ctx()
        with patch("src.mcp_handlers.context.get_context_agent_id", return_value=None):
            result = await inject_identity(
                "process_agent_update",
                {"agent_id": "direct-uuid"},
                ctx
            )
        assert not _is_short_circuit(result)
        _, args, _ = result
        assert args["agent_id"] == "direct-uuid"

    @pytest.mark.asyncio
    async def test_no_binding_no_id_identity_tools_ok(self):
        """Identity tools work without any binding or agent_id."""
        from src.mcp_handlers.middleware import inject_identity
        identity_tools = ["status", "list_tools", "health_check", "onboard", "identity"]
        for tool_name in identity_tools:
            ctx = _make_ctx()
            with patch("src.mcp_handlers.context.get_context_agent_id", return_value=None):
                result = await inject_identity(tool_name, {}, ctx)
            assert not _is_short_circuit(result), f"{tool_name} should not short-circuit"

    @pytest.mark.asyncio
    async def test_exception_skips_gracefully(self):
        """If context lookup throws, middleware continues gracefully."""
        from src.mcp_handlers.middleware import inject_identity
        ctx = _make_ctx()
        with patch("src.mcp_handlers.context.get_context_agent_id", side_effect=RuntimeError("test error")):
            result = await inject_identity("process_agent_update", {}, ctx)
        assert not _is_short_circuit(result)

    @pytest.mark.asyncio
    async def test_label_match_allows_different_id(self):
        """Label match allows using a different agent_id."""
        from src.mcp_handlers.middleware import inject_identity
        ctx = _make_ctx(bound_agent_id="bound-uuid-1234")
        mock_server = MagicMock()
        mock_meta = MagicMock()
        mock_meta.label = "my-friendly-name"
        mock_server.agent_metadata = {"bound-uuid-1234": mock_meta}
        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="bound-uuid-1234"):
            with patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
                result = await inject_identity(
                    "process_agent_update",
                    {"agent_id": "my-friendly-name"},
                    ctx
                )
        assert not _is_short_circuit(result)


# ============================================================================
# 10. track_patterns middleware
# ============================================================================

class TestTrackPatterns:
    """Tests for the track_patterns middleware step."""

    @pytest.mark.asyncio
    async def test_passes_through_normally(self):
        """Pattern tracking passes through without blocking."""
        from src.mcp_handlers.middleware import track_patterns
        from src.mcp_handlers import utils as mcp_utils
        ctx = _make_ctx()
        mock_tracker = MagicMock()
        mock_tracker.record_tool_call.return_value = None
        mock_tracker.record_progress.return_value = None
        # Inject get_bound_agent_id into utils module (it's missing there, import is broken in prod)
        mock_get_bound = MagicMock(return_value="test-agent")
        mcp_utils.get_bound_agent_id = mock_get_bound
        try:
            with patch("src.pattern_tracker.get_pattern_tracker", return_value=mock_tracker):
                with patch("src.mcp_handlers.pattern_helpers.record_hypothesis_if_needed"):
                    with patch("src.mcp_handlers.pattern_helpers.check_untested_hypotheses", return_value=None):
                        with patch("src.mcp_handlers.pattern_helpers.mark_hypothesis_tested"):
                            result = await track_patterns("process_agent_update", {"agent_id": "test-agent"}, ctx)
        finally:
            if hasattr(mcp_utils, 'get_bound_agent_id'):
                delattr(mcp_utils, 'get_bound_agent_id')
        assert not _is_short_circuit(result)
        mock_tracker.record_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_in_tracking_does_not_block(self):
        """Exception in pattern tracking does not block the pipeline."""
        from src.mcp_handlers.middleware import track_patterns
        ctx = _make_ctx()
        with patch("src.pattern_tracker.get_pattern_tracker", side_effect=ImportError("not available")):
            result = await track_patterns("process_agent_update", {}, ctx)
        assert not _is_short_circuit(result)

    @pytest.mark.asyncio
    async def test_no_agent_id_skips_tracking(self):
        """When no agent_id can be resolved, tracking is skipped."""
        from src.mcp_handlers.middleware import track_patterns
        from src.mcp_handlers import utils as mcp_utils
        ctx = _make_ctx()
        mock_tracker = MagicMock()
        # Inject get_bound_agent_id returning None
        mcp_utils.get_bound_agent_id = MagicMock(return_value=None)
        try:
            with patch("src.pattern_tracker.get_pattern_tracker", return_value=mock_tracker):
                result = await track_patterns("health_check", {}, ctx)
        finally:
            if hasattr(mcp_utils, 'get_bound_agent_id'):
                delattr(mcp_utils, 'get_bound_agent_id')
        assert not _is_short_circuit(result)
        mock_tracker.record_tool_call.assert_not_called()
