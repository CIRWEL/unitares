"""
Comprehensive tests for src/mcp_handlers/pi_orchestration.py

Covers:
- _extract_error_message (pure function)
- _standardize_error (pure function)
- map_anima_to_eisv (pure function)
- call_pi_tool (async, mocked HTTP/MCP transport)
- handle_pi_list_tools
- handle_pi_get_context
- handle_pi_health
- handle_pi_sync_eisv
- handle_pi_display
- handle_pi_say
- handle_pi_post_message
- handle_pi_lumen_qa
- handle_pi_query
- handle_pi_workflow
- handle_pi_git_pull
- handle_pi_system_power
- handle_pi_restart_service
- sync_eisv_once
- eisv_sync_task

All external I/O (MCP transport, SSH, httpx) is mocked.
"""

import json
import pytest
import sys
import asyncio
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Any, List, Optional, Sequence
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

import httpx

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp.types import TextContent


# ============================================================================
# Helpers
# ============================================================================

def _parse(result):
    """Parse TextContent result(s) into a dict."""
    if isinstance(result, (list, tuple)):
        return json.loads(result[0].text)
    return json.loads(result.text)


# ============================================================================
# Module under test (import after path setup)
# ============================================================================

from src.mcp_handlers.pi_orchestration import (
    _extract_error_message,
    _standardize_error,
    map_anima_to_eisv,
    call_pi_tool,
    handle_pi_list_tools,
    handle_pi_get_context,
    handle_pi_health,
    handle_pi_sync_eisv,
    handle_pi_display,
    handle_pi_say,
    handle_pi_post_message,
    handle_pi_lumen_qa,
    handle_pi_query,
    handle_pi_workflow,
    handle_pi_git_pull,
    handle_pi_system_power,
    handle_pi_restart_service,
    sync_eisv_once,
    eisv_sync_task,
    PI_MCP_URLS,
    PI_RETRY_MAX_ATTEMPTS,
)


# ============================================================================
# Shared mock helpers for MCP transport
# ============================================================================

# These imports are done lazily inside call_pi_tool and handle_pi_list_tools,
# so we patch at their source modules rather than on pi_orchestration itself.
_PATCH_STREAMABLE = "mcp.client.streamable_http.streamable_http_client"
_PATCH_SESSION = "mcp.client.session.ClientSession"
_PATCH_HTTPX_CLIENT = "src.mcp_handlers.pi_orchestration.httpx.AsyncClient"


def _make_mcp_text_content(text):
    """Create a mock MCP content object with a .text attribute."""
    return SimpleNamespace(text=text)


def _make_mcp_result(content_list):
    """Create a mock MCP CallToolResult with .content list."""
    return SimpleNamespace(content=content_list)


def _build_transport_mocks(mock_session):
    """
    Return (http_side_effect, session_side_effect) callables that yield the
    given mock_session through the async context manager protocol used by
    call_pi_tool and handle_pi_list_tools.
    """
    @asynccontextmanager
    async def fake_http(*a, **kw):
        yield (AsyncMock(), AsyncMock(), None)

    @asynccontextmanager
    async def fake_session(r, w):
        yield mock_session

    return fake_http, fake_session


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def _mock_audit_logger():
    """Mock audit_logger globally so no real audit I/O happens."""
    with patch("src.mcp_handlers.pi_orchestration.audit_logger") as mock_al:
        mock_al.log_cross_device_call = MagicMock()
        mock_al.log_device_health_check = MagicMock()
        mock_al.log_eisv_sync = MagicMock()
        mock_al.log_orchestration_request = MagicMock()
        mock_al.log_orchestration_complete = MagicMock()
        yield mock_al


@pytest.fixture
def mock_call_pi_tool():
    """Patch call_pi_tool for handler-level tests."""
    with patch("src.mcp_handlers.pi_orchestration.call_pi_tool", new_callable=AsyncMock) as m:
        yield m


# ============================================================================
# 1. Pure function tests
# ============================================================================

class TestExtractErrorMessage:
    """Tests for _extract_error_message (lines 122-124)."""

    def test_no_error_key_returns_none(self):
        assert _extract_error_message({"status": "ok"}) is None

    def test_error_key_present_returns_message(self):
        assert _extract_error_message({"error": "something broke"}) == "something broke"

    def test_error_key_empty_string(self):
        assert _extract_error_message({"error": ""}) == ""

    def test_error_with_other_keys(self):
        result = {"error": "timeout", "error_type": "connection", "extra": 42}
        assert _extract_error_message(result) == "timeout"


class TestStandardizeError:
    """Tests for _standardize_error (lines 138-168)."""

    def test_dict_input_preserves_structure(self):
        err_dict = {"error": "fail", "error_type": "tool_error", "error_details": {"x": 1}}
        result = _standardize_error(err_dict)
        assert result["error"] == "fail"
        assert result["error_type"] == "tool_error"
        assert result["error_details"] == {"x": 1}

    def test_dict_input_defaults_error_type(self):
        result = _standardize_error({"error": "bad"})
        assert result["error_type"] == "tool_error"

    def test_dict_without_error_key(self):
        result = _standardize_error({"foo": "bar"})
        assert "foo" in result["error"]
        assert result["error_type"] == "tool_error"

    def test_timeout_exception(self):
        exc = httpx.TimeoutException("read timeout")
        result = _standardize_error(exc)
        assert result["error_type"] == "timeout"
        assert "read timeout" in result["error"]
        assert result["error_details"]["exception_type"] == "TimeoutException"

    def test_connect_error_exception(self):
        exc = httpx.ConnectError("connection refused")
        result = _standardize_error(exc)
        assert result["error_type"] == "connection"

    def test_network_error_exception(self):
        exc = httpx.NetworkError("network unreachable")
        result = _standardize_error(exc)
        assert result["error_type"] == "connection"

    def test_asyncio_timeout(self):
        exc = asyncio.TimeoutError()
        result = _standardize_error(exc)
        assert result["error_type"] == "timeout"

    def test_generic_exception(self):
        exc = ValueError("bad value")
        result = _standardize_error(exc)
        assert result["error_type"] == "unknown"
        assert "bad value" in result["error"]

    def test_string_input(self):
        result = _standardize_error("plain string error")
        assert result["error"] == "plain string error"
        assert result["error_type"] == "unknown"
        assert result["error_details"] is None

    def test_integer_input(self):
        result = _standardize_error(42)
        assert result["error"] == "42"
        assert result["error_type"] == "unknown"


class TestMapAnimaToEisv:
    """Tests for map_anima_to_eisv (lines 355-387)."""

    def test_uses_pre_computed_eisv_when_all_keys_present(self):
        anima = {"warmth": 0.8, "clarity": 0.7, "stability": 0.6, "presence": 0.5}
        pre = {"E": 0.1, "I": 0.2, "S": 0.3, "V": 0.4}
        result = map_anima_to_eisv(anima, pre_computed_eisv=pre)
        assert result == {"E": 0.1, "I": 0.2, "S": 0.3, "V": 0.4}
        assert result is not pre

    def test_falls_back_when_pre_computed_missing_keys(self):
        anima = {"warmth": 0.8, "clarity": 0.7, "stability": 0.6, "presence": 0.5}
        pre = {"E": 0.1, "I": 0.2}  # Missing S and V
        result = map_anima_to_eisv(anima, pre_computed_eisv=pre)
        assert result["E"] == 0.8

    def test_falls_back_when_no_pre_computed(self):
        anima = {"warmth": 0.8, "clarity": 0.7, "stability": 0.6, "presence": 0.5}
        result = map_anima_to_eisv(anima)
        assert result["E"] == 0.8
        assert result["I"] == 0.7
        assert abs(result["S"] - 0.4) < 1e-9
        assert abs(result["V"] - 0.15) < 1e-9

    def test_defaults_when_anima_keys_missing(self):
        result = map_anima_to_eisv({})
        assert result["E"] == 0.5
        assert result["I"] == 0.5
        assert abs(result["S"] - 0.5) < 1e-9
        assert abs(result["V"] - 0.15) < 1e-9

    def test_falls_back_when_pre_computed_is_none(self):
        anima = {"warmth": 1.0, "clarity": 0.0, "stability": 1.0, "presence": 1.0}
        result = map_anima_to_eisv(anima, pre_computed_eisv=None)
        assert result["E"] == 1.0
        assert result["I"] == 0.0
        assert abs(result["S"] - 0.0) < 1e-9
        assert abs(result["V"] - 0.0) < 1e-9

    def test_falls_back_when_pre_computed_is_empty(self):
        anima = {"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}
        result = map_anima_to_eisv(anima, pre_computed_eisv={})
        assert result["E"] == 0.5


# ============================================================================
# 2. call_pi_tool tests (lines 202-352)
# ============================================================================

class TestCallPiTool:
    """Tests for call_pi_tool - exercises MCP transport, retry, parsing."""

    @pytest.mark.asyncio
    async def test_success_json_response(self, _mock_audit_logger):
        """Successful JSON response from Pi is returned as dict."""
        json_data = {"anima": {"warmth": 0.8}}
        content = _make_mcp_text_content(json.dumps(json_data))
        mock_result = _make_mcp_result([content])

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        fake_http, fake_cs = _build_transport_mocks(mock_session)

        with patch(_PATCH_STREAMABLE, side_effect=fake_http), \
             patch(_PATCH_SESSION, side_effect=fake_cs), \
             patch(_PATCH_HTTPX_CLIENT):

            result = await call_pi_tool("get_lumen_context", {"include": ["anima"]})
            assert result == json_data
            _mock_audit_logger.log_cross_device_call.assert_called()

    @pytest.mark.asyncio
    async def test_error_json_response(self, _mock_audit_logger):
        """Error JSON response from Pi is standardized and returned."""
        error_data = {"error": "sensor offline", "error_type": "hardware"}
        content = _make_mcp_text_content(json.dumps(error_data))
        mock_result = _make_mcp_result([content])

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        fake_http, fake_cs = _build_transport_mocks(mock_session)

        with patch(_PATCH_STREAMABLE, side_effect=fake_http), \
             patch(_PATCH_SESSION, side_effect=fake_cs), \
             patch(_PATCH_HTTPX_CLIENT):

            result = await call_pi_tool("diagnostics", {})
            assert "error" in result
            assert result["error"] == "sensor offline"

    @pytest.mark.asyncio
    async def test_non_json_text_response(self, _mock_audit_logger):
        """Non-JSON text response is wrapped in a text dict."""
        content = _make_mcp_text_content("Hello from Lumen")
        mock_result = _make_mcp_result([content])

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        fake_http, fake_cs = _build_transport_mocks(mock_session)

        with patch(_PATCH_STREAMABLE, side_effect=fake_http), \
             patch(_PATCH_SESSION, side_effect=fake_cs), \
             patch(_PATCH_HTTPX_CLIENT):

            result = await call_pi_tool("say", {"text": "hi"})
            assert result == {"text": "Hello from Lumen"}

    @pytest.mark.asyncio
    async def test_empty_response(self, _mock_audit_logger):
        """Empty response (no content) returns standardized error."""
        mock_result = _make_mcp_result([])

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        fake_http, fake_cs = _build_transport_mocks(mock_session)

        with patch(_PATCH_STREAMABLE, side_effect=fake_http), \
             patch(_PATCH_SESSION, side_effect=fake_cs), \
             patch(_PATCH_HTTPX_CLIENT):

            result = await call_pi_tool("diagnostics", {})
            assert "error" in result
            assert "Empty response" in result["error"]

    @pytest.mark.asyncio
    async def test_content_without_text_attribute(self, _mock_audit_logger):
        """Content objects without .text are skipped, resulting in empty response."""
        content = SimpleNamespace(data="binary data")
        mock_result = _make_mcp_result([content])

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        fake_http, fake_cs = _build_transport_mocks(mock_session)

        with patch(_PATCH_STREAMABLE, side_effect=fake_http), \
             patch(_PATCH_SESSION, side_effect=fake_cs), \
             patch(_PATCH_HTTPX_CLIENT):

            result = await call_pi_tool("diagnostics", {})
            assert "error" in result
            assert "Empty response" in result["error"]

    @pytest.mark.asyncio
    async def test_connection_failure_all_urls(self, _mock_audit_logger):
        """When all URLs fail with connection errors, returns standardized error."""
        @asynccontextmanager
        async def fail_http(*a, **kw):
            raise httpx.ConnectError("connection refused")
            yield  # pragma: no cover

        with patch(_PATCH_STREAMABLE, side_effect=fail_http), \
             patch(_PATCH_HTTPX_CLIENT), \
             patch("src.mcp_handlers.pi_orchestration.PI_RETRY_MAX_ATTEMPTS", 0):

            result = await call_pi_tool("diagnostics", {})
            assert "error" in result
            assert "Cannot connect to Pi" in result["error"]

    @pytest.mark.asyncio
    async def test_timeout_failure_all_urls(self, _mock_audit_logger):
        """When all URLs timeout, returns standardized error."""
        @asynccontextmanager
        async def fail_http(*a, **kw):
            raise httpx.TimeoutException("read timeout")
            yield  # pragma: no cover

        with patch(_PATCH_STREAMABLE, side_effect=fail_http), \
             patch(_PATCH_HTTPX_CLIENT), \
             patch("src.mcp_handlers.pi_orchestration.PI_RETRY_MAX_ATTEMPTS", 0):

            result = await call_pi_tool("diagnostics", {})
            assert "error" in result
            assert "Cannot connect to Pi" in result["error"]

    @pytest.mark.asyncio
    async def test_generic_exception_continues_to_next_url(self, _mock_audit_logger):
        """Generic exceptions are caught, logged, and the next URL is tried."""
        call_count = [0]

        @asynccontextmanager
        async def fail_always(*a, **kw):
            call_count[0] += 1
            raise RuntimeError("unexpected error")
            yield  # pragma: no cover

        with patch(_PATCH_STREAMABLE, side_effect=fail_always), \
             patch(_PATCH_HTTPX_CLIENT), \
             patch("src.mcp_handlers.pi_orchestration.PI_RETRY_MAX_ATTEMPTS", 0):

            result = await call_pi_tool("diagnostics", {})
            assert call_count[0] == len(PI_MCP_URLS)
            assert "error" in result

    @pytest.mark.asyncio
    async def test_retry_with_backoff_on_connection_error(self, _mock_audit_logger):
        """Retries with exponential backoff when connection fails."""
        @asynccontextmanager
        async def always_fail(*a, **kw):
            raise httpx.ConnectError("refused")
            yield  # pragma: no cover

        with patch(_PATCH_STREAMABLE, side_effect=always_fail), \
             patch(_PATCH_HTTPX_CLIENT), \
             patch("src.mcp_handlers.pi_orchestration.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            result = await call_pi_tool("diagnostics", {}, retry_attempt=0)
            assert "error" in result
            assert mock_sleep.call_count > 0

    @pytest.mark.asyncio
    async def test_sanitizes_sensitive_arguments(self, _mock_audit_logger):
        """Sensitive keys like api_key and secret are stripped from audit logs."""
        @asynccontextmanager
        async def fail_http(*a, **kw):
            raise httpx.ConnectError("refused")
            yield  # pragma: no cover

        with patch(_PATCH_STREAMABLE, side_effect=fail_http), \
             patch(_PATCH_HTTPX_CLIENT), \
             patch("src.mcp_handlers.pi_orchestration.PI_RETRY_MAX_ATTEMPTS", 0):

            await call_pi_tool("test", {"api_key": "secret123", "secret": "s", "safe": "v"})

            first_call = _mock_audit_logger.log_cross_device_call.call_args_list[0]
            logged_args = first_call.kwargs.get("arguments", first_call[1].get("arguments", {}))
            assert "api_key" not in logged_args
            assert "secret" not in logged_args
            assert logged_args.get("safe") == "v"


# ============================================================================
# 3. Handler tests (lines 404+)
# ============================================================================

class TestHandlePiListTools:
    """Tests for handle_pi_list_tools (lines 404-459)."""

    @pytest.mark.asyncio
    async def test_success_lists_tools(self, _mock_audit_logger):
        """Successfully lists tools from Pi."""
        mock_tool = SimpleNamespace(name="say", description="Speak", inputSchema={"type": "object"})
        mock_tools_result = SimpleNamespace(tools=[mock_tool])

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_tools_result)

        fake_http, fake_cs = _build_transport_mocks(mock_session)

        with patch(_PATCH_STREAMABLE, side_effect=fake_http), \
             patch(_PATCH_SESSION, side_effect=fake_cs), \
             patch(_PATCH_HTTPX_CLIENT):

            result = await handle_pi_list_tools({})
            data = _parse(result)
            assert data["success"] is True
            assert data["count"] == 1
            assert data["tools"][0]["name"] == "say"
            assert "tool_mapping" in data

    @pytest.mark.asyncio
    async def test_all_urls_fail(self, _mock_audit_logger):
        """When all Pi URLs fail, returns error."""
        @asynccontextmanager
        async def fail_http(*a, **kw):
            raise httpx.ConnectError("refused")
            yield  # pragma: no cover

        with patch(_PATCH_STREAMABLE, side_effect=fail_http), \
             patch(_PATCH_HTTPX_CLIENT):

            result = await handle_pi_list_tools({})
            data = _parse(result)
            assert data["success"] is False
            assert "Failed to list Pi tools" in data["error"]

    @pytest.mark.asyncio
    async def test_outer_exception_caught(self, _mock_audit_logger):
        """Outer try/except catches unexpected errors."""
        # Patching the lazy import so it raises an exception in the outer try block
        with patch(_PATCH_STREAMABLE, side_effect=RuntimeError("unexpected")), \
             patch(_PATCH_HTTPX_CLIENT):

            result = await handle_pi_list_tools({})
            data = _parse(result)
            assert data["success"] is False


class TestHandlePiGetContext:
    """Tests for handle_pi_get_context (lines 465-477)."""

    @pytest.mark.asyncio
    async def test_success(self, mock_call_pi_tool):
        context_data = {"anima": {"warmth": 0.8}, "identity": {"name": "Lumen"}}
        mock_call_pi_tool.return_value = context_data

        result = await handle_pi_get_context({})
        data = _parse(result)
        assert data["success"] is True
        assert data["source"] == "pi"
        assert data["context"] == context_data

    @pytest.mark.asyncio
    async def test_error(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"error": "Pi unreachable"}

        result = await handle_pi_get_context({})
        data = _parse(result)
        assert data["success"] is False
        assert "Failed to get Pi context" in data["error"]

    @pytest.mark.asyncio
    async def test_custom_include(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"sensors": {"temp": 25.0}}

        result = await handle_pi_get_context({"include": ["sensors"]})
        data = _parse(result)
        assert data["success"] is True
        mock_call_pi_tool.assert_called_once_with(
            "get_lumen_context",
            {"include": ["sensors"]},
            agent_id="mac-orchestrator",
        )


class TestHandlePiHealth:
    """Tests for handle_pi_health (lines 483-535)."""

    @pytest.mark.asyncio
    async def test_healthy_status(self, mock_call_pi_tool, _mock_audit_logger):
        mock_call_pi_tool.return_value = {
            "led": {"initialized": True},
            "display": {"available": True},
            "update_loop": {"running": True},
        }

        result = await handle_pi_health({})
        data = _parse(result)
        assert data["success"] is True
        assert data["status"] == "healthy"
        assert data["components"]["leds"] == "ok"
        assert data["components"]["display"] == "ok"
        assert data["components"]["update_loop"] == "ok"

    @pytest.mark.asyncio
    async def test_degraded_status(self, mock_call_pi_tool, _mock_audit_logger):
        mock_call_pi_tool.return_value = {
            "led": {"initialized": False},
            "display": {"available": True},
            "update_loop": {"running": True},
        }

        result = await handle_pi_health({})
        data = _parse(result)
        assert data["success"] is True
        assert data["status"] == "degraded"
        assert data["components"]["leds"] == "unavailable"

    @pytest.mark.asyncio
    async def test_update_loop_via_task_flags(self, mock_call_pi_tool, _mock_audit_logger):
        """Test update_loop detection via task_exists/task_done/task_cancelled flags."""
        mock_call_pi_tool.return_value = {
            "update_loop": {
                "running": False,
                "task_exists": True,
                "task_done": False,
                "task_cancelled": False,
            },
        }

        result = await handle_pi_health({})
        data = _parse(result)
        assert data["components"]["update_loop"] == "ok"

    @pytest.mark.asyncio
    async def test_update_loop_stopped(self, mock_call_pi_tool, _mock_audit_logger):
        """Update loop that is done is reported as stopped."""
        mock_call_pi_tool.return_value = {
            "update_loop": {
                "running": False,
                "task_exists": True,
                "task_done": True,
                "task_cancelled": False,
            },
        }

        result = await handle_pi_health({})
        data = _parse(result)
        assert data["components"]["update_loop"] == "stopped"

    @pytest.mark.asyncio
    async def test_error_with_connect_keyword(self, mock_call_pi_tool, _mock_audit_logger):
        """Error containing 'connect' is classified as unreachable."""
        mock_call_pi_tool.return_value = {"error": "Cannot connect to Pi"}

        result = await handle_pi_health({})
        data = _parse(result)
        assert data["success"] is False

        _mock_audit_logger.log_device_health_check.assert_called_once()
        call_kwargs = _mock_audit_logger.log_device_health_check.call_args
        assert call_kwargs.kwargs.get("status", call_kwargs[1].get("status")) == "unreachable"

    @pytest.mark.asyncio
    async def test_error_without_connect_keyword(self, mock_call_pi_tool, _mock_audit_logger):
        """Error without 'connect' is classified as 'error'."""
        mock_call_pi_tool.return_value = {"error": "sensor failure"}

        result = await handle_pi_health({})
        data = _parse(result)
        assert data["success"] is False

        _mock_audit_logger.log_device_health_check.assert_called_once()
        call_kwargs = _mock_audit_logger.log_device_health_check.call_args
        assert call_kwargs.kwargs.get("status", call_kwargs[1].get("status")) == "error"

    @pytest.mark.asyncio
    async def test_no_components_still_healthy(self, mock_call_pi_tool, _mock_audit_logger):
        """When diagnostics returns data without component keys, status is healthy."""
        mock_call_pi_tool.return_value = {"uptime": "3 days"}

        result = await handle_pi_health({})
        data = _parse(result)
        assert data["success"] is True
        assert data["status"] == "healthy"
        assert data["components"] == {}


class TestHandlePiSyncEisv:
    """Tests for handle_pi_sync_eisv (lines 548-634)."""

    @pytest.mark.asyncio
    async def test_success_fallback_mapping(self, mock_call_pi_tool, _mock_audit_logger):
        mock_call_pi_tool.return_value = {
            "anima": {
                "warmth": 0.8,
                "clarity": 0.7,
                "stability": 0.6,
                "presence": 0.5,
            }
        }

        result = await handle_pi_sync_eisv({})
        data = _parse(result)
        assert data["success"] is True
        assert data["eisv_source"] == "mac (fallback)"
        assert "anima" in data
        assert "eisv" in data
        assert "mapping" in data

    @pytest.mark.asyncio
    async def test_success_pre_computed_eisv(self, mock_call_pi_tool, _mock_audit_logger):
        mock_call_pi_tool.return_value = {
            "anima": {
                "warmth": 0.8,
                "clarity": 0.7,
                "stability": 0.6,
                "presence": 0.5,
            },
            "eisv": {"E": 0.1, "I": 0.2, "S": 0.3, "V": 0.4},
        }

        result = await handle_pi_sync_eisv({})
        data = _parse(result)
        assert data["success"] is True
        assert data["eisv_source"] == "pi (neural-weighted)"
        assert data["eisv"]["E"] == 0.1

    @pytest.mark.asyncio
    async def test_error_from_pi(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"error": "Pi offline"}

        result = await handle_pi_sync_eisv({})
        data = _parse(result)
        assert data["success"] is False
        assert "Failed to get anima state" in data["error"]

    @pytest.mark.asyncio
    async def test_anima_error(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {
            "anima": {"error": "sensor calibration failed"}
        }

        result = await handle_pi_sync_eisv({})
        data = _parse(result)
        assert data["success"] is False
        assert "Anima state unavailable" in data["error"]

    @pytest.mark.asyncio
    async def test_update_governance_success(self, mock_call_pi_tool, _mock_audit_logger):
        """When update_governance=True and governance update succeeds."""
        mock_call_pi_tool.return_value = {
            "anima": {
                "warmth": 0.8,
                "clarity": 0.7,
                "stability": 0.6,
                "presence": 0.5,
            }
        }

        mock_gov_result = {
            "decision": {"action": "continue"},
            "metrics": {"risk_score": 0.1, "coherence": 0.9},
        }

        with patch("src.mcp_server.process_update_authenticated_async",
                    create=True, new_callable=AsyncMock,
                    return_value=mock_gov_result):
            result = await handle_pi_sync_eisv({"update_governance": True})
            data = _parse(result)
            assert data["success"] is True
            assert data["governance_updated"] is True
            assert data["governance_verdict"] == "continue"
            assert data["governance_risk"] == 0.1
            assert data["governance_coherence"] == 0.9

    @pytest.mark.asyncio
    async def test_update_governance_failure(self, mock_call_pi_tool, _mock_audit_logger):
        """When update_governance=True but governance update fails."""
        mock_call_pi_tool.return_value = {
            "anima": {
                "warmth": 0.8,
                "clarity": 0.7,
                "stability": 0.6,
                "presence": 0.5,
            }
        }

        with patch("src.mcp_server.process_update_authenticated_async",
                    create=True, new_callable=AsyncMock,
                    side_effect=RuntimeError("db down")):
            result = await handle_pi_sync_eisv({"update_governance": True})
            data = _parse(result)
            assert data["success"] is True
            assert data["governance_updated"] is False
            assert "db down" in data["governance_error"]


class TestHandlePiDisplay:
    """Tests for handle_pi_display (lines 640-658)."""

    @pytest.mark.asyncio
    async def test_success_default_action(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"screen": "face"}

        result = await handle_pi_display({})
        data = _parse(result)
        assert data["success"] is True
        assert data["action"] == "next"
        assert data["device"] == "pi"

    @pytest.mark.asyncio
    async def test_success_with_screen(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"screen": "sensors"}

        result = await handle_pi_display({"action": "switch", "screen": "sensors"})
        data = _parse(result)
        assert data["success"] is True
        assert data["action"] == "switch"

        call_args = mock_call_pi_tool.call_args
        tool_args = call_args[0][1]
        assert tool_args["screen"] == "sensors"

    @pytest.mark.asyncio
    async def test_error(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"error": "display not available"}

        result = await handle_pi_display({})
        data = _parse(result)
        assert data["success"] is False
        assert "Display control failed" in data["error"]


class TestHandlePiSay:
    """Tests for handle_pi_say (lines 664-681)."""

    @pytest.mark.asyncio
    async def test_success(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"status": "spoken"}

        result = await handle_pi_say({"text": "Hello world"})
        data = _parse(result)
        assert data["success"] is True
        assert data["spoken"] == "Hello world"
        assert data["device"] == "pi"

    @pytest.mark.asyncio
    async def test_empty_text_returns_error(self, mock_call_pi_tool):
        result = await handle_pi_say({"text": ""})
        data = _parse(result)
        assert data["success"] is False
        assert "text parameter required" in data["error"]

    @pytest.mark.asyncio
    async def test_missing_text_returns_error(self, mock_call_pi_tool):
        result = await handle_pi_say({})
        data = _parse(result)
        assert data["success"] is False
        assert "text parameter required" in data["error"]

    @pytest.mark.asyncio
    async def test_error_from_pi(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"error": "TTS engine down"}

        result = await handle_pi_say({"text": "test"})
        data = _parse(result)
        assert data["success"] is False
        assert "Speech failed" in data["error"]


class TestHandlePiPostMessage:
    """Tests for handle_pi_post_message (lines 687-714)."""

    @pytest.mark.asyncio
    async def test_success(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"posted": True}

        result = await handle_pi_post_message({"message": "Hello Lumen"})
        data = _parse(result)
        assert data["success"] is True
        assert data["message_posted"] is True

    @pytest.mark.asyncio
    async def test_empty_message_returns_error(self, mock_call_pi_tool):
        result = await handle_pi_post_message({"message": ""})
        data = _parse(result)
        assert data["success"] is False
        assert "message parameter required" in data["error"]

    @pytest.mark.asyncio
    async def test_missing_message_returns_error(self, mock_call_pi_tool):
        result = await handle_pi_post_message({})
        data = _parse(result)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_with_responds_to(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"posted": True}

        result = await handle_pi_post_message({
            "message": "Answer",
            "responds_to": "q123",
            "source": "agent",
            "agent_name": "TestBot",
        })
        data = _parse(result)
        assert data["success"] is True

        call_args = mock_call_pi_tool.call_args
        tool_args = call_args[0][1]
        assert tool_args["responds_to"] == "q123"
        assert tool_args["agent_name"] == "TestBot"

    @pytest.mark.asyncio
    async def test_without_responds_to(self, mock_call_pi_tool):
        """When responds_to is not provided, it should not be in tool_args."""
        mock_call_pi_tool.return_value = {"posted": True}

        result = await handle_pi_post_message({"message": "Hello"})
        data = _parse(result)
        assert data["success"] is True

        call_args = mock_call_pi_tool.call_args
        tool_args = call_args[0][1]
        assert "responds_to" not in tool_args

    @pytest.mark.asyncio
    async def test_error(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"error": "message board full"}

        result = await handle_pi_post_message({"message": "test"})
        data = _parse(result)
        assert data["success"] is False
        assert "Message post failed" in data["error"]


class TestHandlePiLumenQa:
    """Tests for handle_pi_lumen_qa (lines 729-755)."""

    @pytest.mark.asyncio
    async def test_list_questions(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"questions": [{"id": "q1", "text": "What is 1+1?"}]}

        result = await handle_pi_lumen_qa({})
        data = _parse(result)
        assert data["success"] is True
        assert data["action"] == "list"

    @pytest.mark.asyncio
    async def test_answer_question(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"answered": True}

        result = await handle_pi_lumen_qa({
            "question_id": "q1",
            "answer": "2",
        })
        data = _parse(result)
        assert data["success"] is True
        assert data["action"] == "answered"

        call_args = mock_call_pi_tool.call_args
        tool_args = call_args[0][1]
        assert tool_args["question_id"] == "q1"
        assert tool_args["answer"] == "2"

    @pytest.mark.asyncio
    async def test_error(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"error": "QA service down"}

        result = await handle_pi_lumen_qa({})
        data = _parse(result)
        assert data["success"] is False
        assert "Q&A operation failed" in data["error"]

    @pytest.mark.asyncio
    async def test_custom_agent_name_and_limit(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"questions": []}

        result = await handle_pi_lumen_qa({"limit": 3, "agent_name": "Claude"})
        data = _parse(result)
        assert data["success"] is True

        call_args = mock_call_pi_tool.call_args
        tool_args = call_args[0][1]
        assert tool_args["limit"] == 3
        assert tool_args["agent_name"] == "Claude"

    @pytest.mark.asyncio
    async def test_question_id_without_answer_is_list_mode(self, mock_call_pi_tool):
        """If question_id is provided but answer is not, stays in list mode."""
        mock_call_pi_tool.return_value = {"questions": []}

        result = await handle_pi_lumen_qa({"question_id": "q1"})
        data = _parse(result)
        assert data["action"] == "list"


class TestHandlePiQuery:
    """Tests for handle_pi_query (lines 761-783)."""

    @pytest.mark.asyncio
    async def test_success(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"results": ["fact1", "fact2"]}

        result = await handle_pi_query({"text": "What does Lumen know?"})
        data = _parse(result)
        assert data["success"] is True
        assert data["query_type"] == "cognitive"

    @pytest.mark.asyncio
    async def test_empty_text_returns_error(self, mock_call_pi_tool):
        result = await handle_pi_query({"text": ""})
        data = _parse(result)
        assert data["success"] is False
        assert "text parameter required" in data["error"]

    @pytest.mark.asyncio
    async def test_missing_text_returns_error(self, mock_call_pi_tool):
        result = await handle_pi_query({})
        data = _parse(result)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_custom_type_and_limit(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"results": []}

        result = await handle_pi_query({"text": "search", "type": "semantic", "limit": 5})
        data = _parse(result)
        assert data["success"] is True
        assert data["query_type"] == "semantic"

    @pytest.mark.asyncio
    async def test_error(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"error": "query engine down"}

        result = await handle_pi_query({"text": "test"})
        data = _parse(result)
        assert data["success"] is False
        assert "Query failed" in data["error"]


class TestHandlePiWorkflow:
    """Tests for handle_pi_workflow (lines 796-863)."""

    @pytest.mark.asyncio
    async def test_full_status_workflow(self, mock_call_pi_tool, _mock_audit_logger):
        mock_call_pi_tool.side_effect = [
            {"anima": {"warmth": 0.8}},
            {"led": {"initialized": True}},
        ]

        result = await handle_pi_workflow({"workflow": "full_status"})
        data = _parse(result)
        assert data["success"] is True
        assert data["workflow"] == "full_status"
        assert len(data["steps"]) == 2
        assert data["errors"] is None

    @pytest.mark.asyncio
    async def test_morning_check_workflow(self, mock_call_pi_tool, _mock_audit_logger):
        mock_call_pi_tool.side_effect = [
            {"sensors": {"temp": 22}},
            {"posted": True},
        ]

        result = await handle_pi_workflow({"workflow": "morning_check"})
        data = _parse(result)
        assert data["success"] is True
        assert data["workflow"] == "morning_check"

    @pytest.mark.asyncio
    async def test_custom_workflow(self, mock_call_pi_tool, _mock_audit_logger):
        mock_call_pi_tool.side_effect = [
            {"status": "ok"},
        ]

        result = await handle_pi_workflow({
            "workflow": "custom",
            "steps": [{"tool": "diagnostics", "args": {}}],
        })
        data = _parse(result)
        assert data["success"] is True
        assert data["workflow"] == "custom"

    @pytest.mark.asyncio
    async def test_unknown_workflow_returns_error(self, mock_call_pi_tool, _mock_audit_logger):
        result = await handle_pi_workflow({"workflow": "nonexistent"})
        data = _parse(result)
        assert data["success"] is False
        assert "Unknown workflow" in data["error"]

    @pytest.mark.asyncio
    async def test_workflow_with_partial_failures(self, mock_call_pi_tool, _mock_audit_logger):
        mock_call_pi_tool.side_effect = [
            {"anima": {"warmth": 0.8}},
            {"error": "diagnostics unavailable"},
        ]

        result = await handle_pi_workflow({"workflow": "full_status"})
        data = _parse(result)
        assert data["success"] is False
        assert len(data["steps"]) == 2
        assert len(data["errors"]) == 1
        assert "diagnostics" in data["errors"][0]

    @pytest.mark.asyncio
    async def test_workflow_audits_request_and_completion(self, mock_call_pi_tool, _mock_audit_logger):
        mock_call_pi_tool.side_effect = [
            {"ok": True},
            {"ok": True},
        ]

        await handle_pi_workflow({"workflow": "full_status"})

        _mock_audit_logger.log_orchestration_request.assert_called_once()
        _mock_audit_logger.log_orchestration_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_workflow_empty_steps_returns_error(self, mock_call_pi_tool, _mock_audit_logger):
        """Custom workflow with empty steps list returns error."""
        result = await handle_pi_workflow({"workflow": "custom", "steps": []})
        data = _parse(result)
        assert data["success"] is False
        assert "Unknown workflow" in data["error"]


class TestHandlePiGitPull:
    """Tests for handle_pi_git_pull (lines 872-898)."""

    @pytest.mark.asyncio
    async def test_success_no_options(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"output": "Already up to date."}

        result = await handle_pi_git_pull({})
        data = _parse(result)
        assert data["success"] is True
        assert data["operation"] == "git_pull"
        assert data["stash"] is False
        assert data["force"] is False
        assert data["restart"] is False

    @pytest.mark.asyncio
    async def test_success_with_all_options(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"output": "Updating abc..def"}

        result = await handle_pi_git_pull({
            "stash": True,
            "force": True,
            "restart": True,
        })
        data = _parse(result)
        assert data["success"] is True
        assert data["stash"] is True
        assert data["force"] is True
        assert data["restart"] is True

        call_args = mock_call_pi_tool.call_args
        tool_args = call_args[0][1]
        assert tool_args["stash"] is True
        assert tool_args["force"] is True
        assert tool_args["restart"] is True

    @pytest.mark.asyncio
    async def test_error(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"error": "git conflict"}

        result = await handle_pi_git_pull({})
        data = _parse(result)
        assert data["success"] is False
        assert "Git pull failed" in data["error"]

    @pytest.mark.asyncio
    async def test_partial_options(self, mock_call_pi_tool):
        """Only the options set to True are included in tool_args."""
        mock_call_pi_tool.return_value = {"output": "ok"}

        result = await handle_pi_git_pull({"stash": True})
        data = _parse(result)
        assert data["success"] is True

        call_args = mock_call_pi_tool.call_args
        tool_args = call_args[0][1]
        assert tool_args.get("stash") is True
        assert "force" not in tool_args
        assert "restart" not in tool_args


class TestHandlePiSystemPower:
    """Tests for handle_pi_system_power (lines 907-927)."""

    @pytest.mark.asyncio
    async def test_status_action(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"power": "on", "uptime": "3 days"}

        result = await handle_pi_system_power({})
        data = _parse(result)
        assert data["success"] is True
        assert data["action"] == "status"
        assert data["confirm"] is False

    @pytest.mark.asyncio
    async def test_reboot_with_confirm(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"rebooting": True}

        result = await handle_pi_system_power({
            "action": "reboot",
            "confirm": True,
        })
        data = _parse(result)
        assert data["success"] is True
        assert data["action"] == "reboot"
        assert data["confirm"] is True

        call_args = mock_call_pi_tool.call_args
        tool_args = call_args[0][1]
        assert tool_args["confirm"] is True

    @pytest.mark.asyncio
    async def test_error(self, mock_call_pi_tool):
        mock_call_pi_tool.return_value = {"error": "permission denied"}

        result = await handle_pi_system_power({"action": "reboot"})
        data = _parse(result)
        assert data["success"] is False
        assert "Power command failed" in data["error"]

    @pytest.mark.asyncio
    async def test_no_confirm_omits_confirm_arg(self, mock_call_pi_tool):
        """When confirm is False (default), confirm is not added to tool_args."""
        mock_call_pi_tool.return_value = {"status": "ok"}

        await handle_pi_system_power({})
        call_args = mock_call_pi_tool.call_args
        tool_args = call_args[0][1]
        assert "confirm" not in tool_args


class TestHandlePiRestartService:
    """Tests for handle_pi_restart_service (lines 951-1030)."""

    @pytest.mark.asyncio
    async def test_disallowed_service(self, _mock_audit_logger):
        result = await handle_pi_restart_service({"service": "malicious"})
        data = _parse(result)
        assert data["success"] is False
        assert "not in allowed list" in data["error"]

    @pytest.mark.asyncio
    async def test_disallowed_action(self, _mock_audit_logger):
        result = await handle_pi_restart_service({"service": "anima", "action": "destroy"})
        data = _parse(result)
        assert data["success"] is False
        assert "not in allowed list" in data["error"]

    @pytest.mark.asyncio
    async def test_success(self, _mock_audit_logger):
        mock_completed = MagicMock()
        mock_completed.returncode = 0
        mock_completed.stdout = "active"
        mock_completed.stderr = ""

        with patch("subprocess.run", return_value=mock_completed) as mock_run:
            result = await handle_pi_restart_service({})
            data = _parse(result)
            assert data["success"] is True
            assert data["service"] == "anima"
            assert data["operation"] == "ssh_systemctl_restart"
            assert data["status"] == "active"
            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_ssh_command_failure_returns_result_with_error(self, _mock_audit_logger):
        """SSH command failure (nonzero exit) still returns via success_response but with
        the inner 'success' key overwritten to False by the handler's data dict."""
        mock_completed = MagicMock()
        mock_completed.returncode = 1
        mock_completed.stdout = ""
        mock_completed.stderr = "Failed to restart anima.service"

        with patch("subprocess.run", return_value=mock_completed):
            result = await handle_pi_restart_service({})
            data = _parse(result)
            assert data["operation"] == "ssh_systemctl_restart"
            assert data["service"] == "anima"
            # success_response sets "success": True, but the handler's data dict
            # also contains "success": result.returncode == 0 (False), which
            # overwrites the default via **data spreading in success_response.
            assert data["success"] is False
            assert data["error"] == "Failed to restart anima.service"

    @pytest.mark.asyncio
    async def test_ssh_timeout(self, _mock_audit_logger):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 30)):
            result = await handle_pi_restart_service({})
            data = _parse(result)
            assert data["success"] is False
            assert "timed out" in data["error"]

    @pytest.mark.asyncio
    async def test_ssh_key_not_found(self, _mock_audit_logger):
        with patch("subprocess.run", side_effect=FileNotFoundError("ssh key")):
            result = await handle_pi_restart_service({})
            data = _parse(result)
            assert data["success"] is False
            assert "SSH key not found" in data["error"]

    @pytest.mark.asyncio
    async def test_ssh_generic_exception(self, _mock_audit_logger):
        with patch("subprocess.run", side_effect=OSError("permission denied")):
            result = await handle_pi_restart_service({})
            data = _parse(result)
            assert data["success"] is False
            assert "SSH command failed" in data["error"]

    @pytest.mark.asyncio
    async def test_allowed_services(self, _mock_audit_logger):
        """Test that all allowed services pass validation."""
        for svc in ["anima", "anima-broker", "ngrok"]:
            mock_completed = MagicMock()
            mock_completed.returncode = 0
            mock_completed.stdout = "active"
            mock_completed.stderr = ""

            with patch("subprocess.run", return_value=mock_completed):
                result = await handle_pi_restart_service({"service": svc})
                data = _parse(result)
                assert data["success"] is True, "Service '%s' should be allowed" % svc

    @pytest.mark.asyncio
    async def test_allowed_actions(self, _mock_audit_logger):
        """Test that all allowed actions pass validation."""
        for action in ["restart", "start", "stop", "status"]:
            mock_completed = MagicMock()
            mock_completed.returncode = 0
            mock_completed.stdout = "active"
            mock_completed.stderr = ""

            with patch("subprocess.run", return_value=mock_completed):
                result = await handle_pi_restart_service({"service": "anima", "action": action})
                data = _parse(result)
                assert data["success"] is True, "Action '%s' should be allowed" % action

    @pytest.mark.asyncio
    async def test_audit_logging_on_success(self, _mock_audit_logger):
        """Verify audit logging happens on both initiation and completion."""
        mock_completed = MagicMock()
        mock_completed.returncode = 0
        mock_completed.stdout = "active"
        mock_completed.stderr = ""

        with patch("subprocess.run", return_value=mock_completed):
            await handle_pi_restart_service({})

        assert _mock_audit_logger.log_cross_device_call.call_count == 2


# ============================================================================
# 4. Background task tests (lines 1047-1117)
# ============================================================================

class TestSyncEisvOnce:
    """Tests for sync_eisv_once (lines 1047-1083)."""

    @pytest.mark.asyncio
    async def test_success(self, _mock_audit_logger):
        anima_data = {
            "anima": {
                "warmth": 0.8,
                "clarity": 0.7,
                "stability": 0.6,
                "presence": 0.5,
            }
        }

        with patch("src.mcp_handlers.pi_orchestration.call_pi_tool", new_callable=AsyncMock) as mock_cpt:
            mock_cpt.return_value = anima_data

            result = await sync_eisv_once()
            assert result["success"] is True
            assert "anima" in result
            assert "eisv" in result
            assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_error_from_pi(self, _mock_audit_logger):
        with patch("src.mcp_handlers.pi_orchestration.call_pi_tool", new_callable=AsyncMock) as mock_cpt:
            mock_cpt.return_value = {"error": "Pi down"}

            result = await sync_eisv_once()
            assert result["success"] is False
            assert result["error"] == "Pi down"

    @pytest.mark.asyncio
    async def test_empty_anima(self, _mock_audit_logger):
        with patch("src.mcp_handlers.pi_orchestration.call_pi_tool", new_callable=AsyncMock) as mock_cpt:
            mock_cpt.return_value = {"anima": {}}

            result = await sync_eisv_once()
            assert result["success"] is False
            assert "No anima state" in result["error"]

    @pytest.mark.asyncio
    async def test_exception_caught(self, _mock_audit_logger):
        with patch("src.mcp_handlers.pi_orchestration.call_pi_tool", new_callable=AsyncMock) as mock_cpt:
            mock_cpt.side_effect = RuntimeError("crash")

            result = await sync_eisv_once()
            assert result["success"] is False
            assert "crash" in result["error"]

    @pytest.mark.asyncio
    async def test_with_pre_computed_eisv(self, _mock_audit_logger):
        with patch("src.mcp_handlers.pi_orchestration.call_pi_tool", new_callable=AsyncMock) as mock_cpt:
            mock_cpt.return_value = {
                "anima": {"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5},
                "eisv": {"E": 0.9, "I": 0.8, "S": 0.7, "V": 0.6},
            }

            result = await sync_eisv_once()
            assert result["success"] is True
            assert result["eisv"]["E"] == 0.9


class TestEisvSyncTask:
    """Tests for eisv_sync_task (lines 1096-1117)."""

    @pytest.mark.asyncio
    async def test_runs_and_can_be_cancelled(self, _mock_audit_logger):
        """The background task runs, syncs, and stops on CancelledError."""
        call_count = [0]

        async def mock_sync_once(update_governance=False):
            call_count[0] += 1
            return {"success": True, "eisv": {"E": 0.5, "I": 0.5, "S": 0.5, "V": 0.5}}

        with patch("src.mcp_handlers.pi_orchestration.sync_eisv_once", side_effect=mock_sync_once), \
             patch("src.mcp_handlers.pi_orchestration.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            mock_sleep.side_effect = [None, asyncio.CancelledError()]

            await eisv_sync_task(interval_minutes=0.001)
            assert call_count[0] >= 1

    @pytest.mark.asyncio
    async def test_handles_sync_failure(self, _mock_audit_logger):
        """The task continues running even when sync fails."""
        call_count = [0]

        async def mock_sync_once(update_governance=False):
            call_count[0] += 1
            return {"success": False, "error": "Pi down"}

        with patch("src.mcp_handlers.pi_orchestration.sync_eisv_once", side_effect=mock_sync_once), \
             patch("src.mcp_handlers.pi_orchestration.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            mock_sleep.side_effect = [None, asyncio.CancelledError()]

            await eisv_sync_task(interval_minutes=0.001)
            assert call_count[0] >= 1

    @pytest.mark.asyncio
    async def test_handles_unexpected_exception(self, _mock_audit_logger):
        """The task continues running even on unexpected exceptions."""
        call_count = [0]

        async def mock_sync_once(update_governance=False):
            call_count[0] += 1
            raise ValueError("unexpected error")

        with patch("src.mcp_handlers.pi_orchestration.sync_eisv_once", side_effect=mock_sync_once), \
             patch("src.mcp_handlers.pi_orchestration.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            mock_sleep.side_effect = [None, None, asyncio.CancelledError()]

            await eisv_sync_task(interval_minutes=0.001)
            assert call_count[0] >= 1
