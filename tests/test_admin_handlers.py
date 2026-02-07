"""
Tests for src/mcp_handlers/admin.py - comprehensive admin handler coverage.

Tests cover:
- handle_health_check
- handle_get_server_info
- handle_get_connection_status
- handle_validate_file_path
- handle_get_workspace_health
- handle_reset_monitor
- handle_cleanup_stale_locks
- handle_get_tool_usage_stats
- handle_describe_tool
- handle_list_tools
- handle_debug_request_context
- handle_check_continuity_health
- handle_check_calibration
- handle_rebuild_calibration
- handle_update_calibration_ground_truth
- handle_get_telemetry_metrics
- handle_backfill_calibration_from_dialectic
- Workspace helper functions (get_workspace_last_agent, set_workspace_last_agent, etc.)
"""

import pytest
import json
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def parse_result(result):
    """Parse TextContent result into dict.

    Handles both Sequence[TextContent] (from success_response) and
    bare TextContent (from some error_response calls).
    """
    from mcp.types import TextContent
    if isinstance(result, TextContent):
        return json.loads(result.text)
    return json.loads(result[0].text)


# ============================================================================
# Shared fixtures
# ============================================================================

@pytest.fixture
def mock_mcp_server():
    """Mock the shared mcp_server module."""
    server = MagicMock()
    server.agent_metadata = {}
    server.monitors = {}
    server.SERVER_VERSION = "test-1.0.0"
    server.SERVER_BUILD_DATE = "2026-01-01"
    server.PSUTIL_AVAILABLE = False
    server.MAX_KEEP_PROCESSES = 5
    server.project_root = str(project_root)
    return server


@pytest.fixture
def patch_mcp_server(mock_mcp_server):
    """Patch both mcp_server and get_mcp_server references."""
    with patch("src.mcp_handlers.admin.mcp_server", mock_mcp_server), \
         patch("src.mcp_handlers.admin.get_mcp_server", return_value=mock_mcp_server):
        yield mock_mcp_server


@pytest.fixture
def patch_context_agent_id():
    """Patch context agent_id to return None (no bound identity).

    Since get_context_agent_id is imported locally inside functions from
    src.mcp_handlers.context, we patch it at the source module.
    """
    with patch("src.mcp_handlers.context.get_context_agent_id", return_value=None):
        yield


# ============================================================================
# handle_get_server_info
# ============================================================================

class TestGetServerInfo:

    @pytest.mark.asyncio
    async def test_server_info_without_psutil(self, mock_mcp_server, patch_context_agent_id):
        mock_mcp_server.PSUTIL_AVAILABLE = False
        with patch("src.mcp_handlers.admin.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.TOOL_HANDLERS", {"a": None, "b": None, "c": None}):
            from src.mcp_handlers.admin import handle_get_server_info
            result = await handle_get_server_info({})

            data = parse_result(result)
            assert data["success"] is True
            assert data["server_version"] == "test-1.0.0"
            assert data["build_date"] == "2026-01-01"
            assert data["tool_count"] == 3
            assert data["health"] == "healthy"
            # Without psutil, server_processes should contain error message
            assert len(data["server_processes"]) == 1
            assert "error" in data["server_processes"][0]

    @pytest.mark.asyncio
    async def test_server_info_with_psutil(self, mock_mcp_server, patch_context_agent_id):
        mock_mcp_server.PSUTIL_AVAILABLE = True

        mock_proc = MagicMock()
        mock_proc.info = {
            "pid": 12345,
            "name": "python",
            "cmdline": ["python", "mcp_server_std.py"],
            "create_time": 0,
            "status": "running"
        }

        mock_current = MagicMock()
        mock_current.create_time.return_value = 100.0
        mock_current.status.return_value = "running"

        with patch("src.mcp_handlers.admin.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.TOOL_HANDLERS", {"a": None}), \
             patch("psutil.process_iter", return_value=[mock_proc]), \
             patch("psutil.Process", return_value=mock_current), \
             patch("time.time", return_value=200.0):
            from src.mcp_handlers.admin import handle_get_server_info
            result = await handle_get_server_info({})

            data = parse_result(result)
            assert data["success"] is True
            assert data["current_pid"] == os.getpid()

    @pytest.mark.asyncio
    async def test_server_info_transport_detection(self, mock_mcp_server, patch_context_agent_id):
        """Test that transport is detected from sys.argv."""
        mock_mcp_server.PSUTIL_AVAILABLE = False
        with patch("src.mcp_handlers.admin.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.TOOL_HANDLERS", {}), \
             patch.object(sys, "argv", ["python", "mcp_server.py"]):
            from src.mcp_handlers.admin import handle_get_server_info
            result = await handle_get_server_info({})
            data = parse_result(result)
            assert data["transport"] == "HTTP"


# ============================================================================
# handle_get_connection_status
# ============================================================================

class TestGetConnectionStatus:

    @pytest.mark.asyncio
    async def test_connection_status_connected(self, patch_context_agent_id):
        mock_server = MagicMock()
        mock_server.agent_metadata = {}

        with patch("src.mcp_handlers.admin.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.admin.mcp_server", mock_server), \
             patch("src.mcp_handlers.TOOL_HANDLERS", {"tool1": None}):
            from src.mcp_handlers.admin import handle_get_connection_status
            result = await handle_get_connection_status({})

            data = parse_result(result)
            assert data["success"] is True
            assert data["status"] == "connected"
            assert data["server_available"] is True
            assert data["tools_available"] is True

    @pytest.mark.asyncio
    async def test_connection_status_with_bound_identity(self):
        mock_server = MagicMock()
        meta = MagicMock()
        meta.structured_id = "Claude_Opus_20260101"
        meta.label = "TestAgent"
        mock_server.agent_metadata = {"uuid-123": meta}

        with patch("src.mcp_handlers.admin.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.admin.mcp_server", mock_server), \
             patch("src.mcp_handlers.TOOL_HANDLERS", {"tool1": None}), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-123"):
            from src.mcp_handlers.admin import handle_get_connection_status
            result = await handle_get_connection_status({})

            data = parse_result(result)
            assert data["session_bound"] is True
            # Note: success_response overwrites resolved_agent_id with the raw UUID
            # The structured_id is in the handler's local variable but gets overwritten
            assert data["resolved_agent_id"] == "uuid-123"
            assert data["resolved_uuid"] == "uuid-123..."

    @pytest.mark.asyncio
    async def test_connection_status_no_tools(self, patch_context_agent_id):
        mock_server = MagicMock()
        mock_server.agent_metadata = {}

        with patch("src.mcp_handlers.admin.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.admin.mcp_server", mock_server), \
             patch("src.mcp_handlers.TOOL_HANDLERS", {}):
            from src.mcp_handlers.admin import handle_get_connection_status
            result = await handle_get_connection_status({})

            data = parse_result(result)
            assert data["status"] == "disconnected"
            assert data["tools_available"] is False


# ============================================================================
# handle_validate_file_path
# ============================================================================

class TestValidateFilePath:

    @pytest.mark.asyncio
    async def test_valid_path(self, patch_context_agent_id):
        with patch("src.mcp_handlers.admin.validate_file_path_policy", return_value=(None, None)):
            from src.mcp_handlers.admin import handle_validate_file_path
            result = await handle_validate_file_path({"file_path": "src/main.py"})

            data = parse_result(result)
            assert data["success"] is True
            assert data["valid"] is True
            assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_warning_path(self, patch_context_agent_id):
        warning_msg = "Test script should be in tests/"
        with patch("src.mcp_handlers.admin.validate_file_path_policy",
                    return_value=(warning_msg, None)):
            from src.mcp_handlers.admin import handle_validate_file_path
            result = await handle_validate_file_path({"file_path": "test_foo.py"})

            data = parse_result(result)
            assert data["success"] is True
            assert data["valid"] is False
            assert data["status"] == "warning"
            assert "guidance" in data

    @pytest.mark.asyncio
    async def test_error_path(self, patch_context_agent_id):
        from mcp.types import TextContent
        error_tc = TextContent(type="text", text='{"success":false,"error":"blocked"}')
        with patch("src.mcp_handlers.admin.validate_file_path_policy",
                    return_value=(None, error_tc)):
            from src.mcp_handlers.admin import handle_validate_file_path
            result = await handle_validate_file_path({"file_path": "/etc/passwd"})

            data = json.loads(result[0].text)
            assert data["success"] is False

    @pytest.mark.asyncio
    async def test_missing_file_path(self, patch_context_agent_id):
        from src.mcp_handlers.admin import handle_validate_file_path
        result = await handle_validate_file_path({})

        data = parse_result(result)
        assert data["success"] is False
        assert "file_path" in data["error"].lower() or "required" in data["error"].lower()


# ============================================================================
# handle_reset_monitor
# ============================================================================

class TestResetMonitor:

    @pytest.mark.asyncio
    async def test_reset_existing_monitor(self, mock_mcp_server, patch_context_agent_id):
        mock_mcp_server.monitors = {"agent-1": MagicMock()}
        mock_mcp_server.agent_metadata = {"agent-1": MagicMock(status="active")}

        with patch("src.mcp_handlers.admin.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.admin.require_registered_agent",
                   return_value=("agent-1", None)):
            from src.mcp_handlers.admin import handle_reset_monitor
            result = await handle_reset_monitor({"agent_id": "agent-1"})

            data = parse_result(result)
            assert data["success"] is True
            assert "reset" in data["message"].lower()
            assert "agent-1" not in mock_mcp_server.monitors

    @pytest.mark.asyncio
    async def test_reset_nonexistent_monitor(self, mock_mcp_server, patch_context_agent_id):
        mock_mcp_server.monitors = {}

        with patch("src.mcp_handlers.admin.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.admin.require_registered_agent",
                   return_value=("agent-1", None)):
            from src.mcp_handlers.admin import handle_reset_monitor
            result = await handle_reset_monitor({"agent_id": "agent-1"})

            data = parse_result(result)
            assert data["success"] is True
            assert "not found" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_reset_requires_registration(self, mock_mcp_server, patch_context_agent_id):
        from mcp.types import TextContent
        error = TextContent(type="text", text='{"success":false,"error":"not registered"}')

        with patch("src.mcp_handlers.admin.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.admin.require_registered_agent",
                   return_value=(None, error)):
            from src.mcp_handlers.admin import handle_reset_monitor
            result = await handle_reset_monitor({})

            data = json.loads(result[0].text)
            assert data["success"] is False


# ============================================================================
# handle_cleanup_stale_locks
# ============================================================================

class TestCleanupStaleLocks:

    @pytest.mark.asyncio
    async def test_cleanup_success(self, patch_context_agent_id):
        mock_result = {
            "cleaned": 2, "kept": 1, "errors": 0,
            "cleaned_locks": ["lock1", "lock2"], "kept_locks": ["lock3"],
        }
        with patch("src.lock_cleanup.cleanup_stale_state_locks",
                    return_value=mock_result):
            from src.mcp_handlers.admin import handle_cleanup_stale_locks
            result = await handle_cleanup_stale_locks({})

            data = parse_result(result)
            assert data["success"] is True
            assert data["cleaned"] == 2
            assert data["kept"] == 1
            assert "Cleaned 2" in data["message"]

    @pytest.mark.asyncio
    async def test_cleanup_dry_run(self, patch_context_agent_id):
        mock_result = {
            "cleaned": 0, "kept": 3, "errors": 0,
            "cleaned_locks": [], "kept_locks": ["a", "b", "c"],
        }
        with patch("src.lock_cleanup.cleanup_stale_state_locks",
                    return_value=mock_result):
            from src.mcp_handlers.admin import handle_cleanup_stale_locks
            result = await handle_cleanup_stale_locks({"dry_run": True})

            data = parse_result(result)
            assert data["dry_run"] is True

    @pytest.mark.asyncio
    async def test_cleanup_custom_max_age(self, patch_context_agent_id):
        mock_result = {
            "cleaned": 0, "kept": 0, "errors": 0,
            "cleaned_locks": [], "kept_locks": [],
        }
        with patch("src.lock_cleanup.cleanup_stale_state_locks",
                    return_value=mock_result) as mock_fn:
            from src.mcp_handlers.admin import handle_cleanup_stale_locks
            result = await handle_cleanup_stale_locks({"max_age_seconds": 600.0})

            data = parse_result(result)
            assert data["max_age_seconds"] == 600.0

    @pytest.mark.asyncio
    async def test_cleanup_error_handling(self, patch_context_agent_id):
        with patch("src.lock_cleanup.cleanup_stale_state_locks",
                    side_effect=RuntimeError("lock dir missing")):
            from src.mcp_handlers.admin import handle_cleanup_stale_locks
            result = await handle_cleanup_stale_locks({})

            data = parse_result(result)
            assert data["success"] is False
            assert "lock dir missing" in data["error"]


# ============================================================================
# handle_get_tool_usage_stats
# ============================================================================

class TestGetToolUsageStats:

    @pytest.mark.asyncio
    async def test_usage_stats_default(self, patch_context_agent_id):
        mock_tracker = MagicMock()
        mock_tracker.get_usage_stats.return_value = {
            "total_calls": 100,
            "unique_tools": 15,
        }
        with patch("src.tool_usage_tracker.get_tool_usage_tracker",
                    return_value=mock_tracker):
            from src.mcp_handlers.admin import handle_get_tool_usage_stats
            result = await handle_get_tool_usage_stats({})

            data = parse_result(result)
            assert data["success"] is True
            assert data["total_calls"] == 100

    @pytest.mark.asyncio
    async def test_usage_stats_with_filters(self, patch_context_agent_id):
        mock_tracker = MagicMock()
        mock_tracker.get_usage_stats.return_value = {"total_calls": 5}

        with patch("src.tool_usage_tracker.get_tool_usage_tracker",
                    return_value=mock_tracker):
            from src.mcp_handlers.admin import handle_get_tool_usage_stats
            result = await handle_get_tool_usage_stats({
                "tool_name": "health_check",
                "agent_id": "agent-1",
                "window_hours": 48,
            })

            # Verify filters were passed through
            call_kwargs = mock_tracker.get_usage_stats.call_args
            assert call_kwargs.kwargs.get("tool_name") == "health_check" or \
                   call_kwargs[1].get("tool_name") == "health_check"


# ============================================================================
# handle_get_workspace_health
# ============================================================================

class TestGetWorkspaceHealth:

    @pytest.mark.asyncio
    async def test_workspace_health_success(self, patch_context_agent_id):
        mock_data = {
            "workspace": "governance-mcp-v1",
            "overall_status": "healthy",
            "checks": {}
        }
        with patch("src.workspace_health.get_workspace_health",
                    return_value=mock_data):
            from src.mcp_handlers.admin import handle_get_workspace_health
            result = await handle_get_workspace_health({})

            data = parse_result(result)
            assert data["success"] is True
            assert data["overall_status"] == "healthy"

    @pytest.mark.asyncio
    async def test_workspace_health_error(self, patch_context_agent_id):
        with patch("src.workspace_health.get_workspace_health",
                    side_effect=RuntimeError("disk full")):
            from src.mcp_handlers.admin import handle_get_workspace_health
            result = await handle_get_workspace_health({})

            data = parse_result(result)
            assert data["success"] is False
            assert "disk full" in data["error"]


# ============================================================================
# handle_describe_tool
# ============================================================================

class TestDescribeTool:

    @pytest.mark.asyncio
    async def test_describe_existing_tool(self, patch_context_agent_id):
        mock_tool = MagicMock()
        mock_tool.name = "health_check"
        mock_tool.description = "Quick health check of system"
        mock_tool.inputSchema = {"type": "object", "properties": {}}

        with patch("src.tool_schemas.get_tool_definitions", return_value=[mock_tool]):
            from src.mcp_handlers.admin import handle_describe_tool
            result = await handle_describe_tool({
                "tool_name": "health_check",
                "lite": False
            })

            data = parse_result(result)
            assert data["success"] is True
            assert data["tool"]["name"] == "health_check"

    @pytest.mark.asyncio
    async def test_describe_missing_tool_name(self, patch_context_agent_id):
        from src.mcp_handlers.admin import handle_describe_tool
        result = await handle_describe_tool({})

        data = parse_result(result)
        assert data["success"] is False
        assert "required" in data["error"].lower() or "tool_name" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_describe_unknown_tool(self, patch_context_agent_id):
        with patch("src.tool_schemas.get_tool_definitions", return_value=[]):
            from src.mcp_handlers.admin import handle_describe_tool
            result = await handle_describe_tool({"tool_name": "nonexistent_tool"})

            data = parse_result(result)
            assert data["success"] is False
            assert "unknown" in data["error"].lower() or "nonexistent" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_describe_tool_lite_mode_with_schema(self, patch_context_agent_id):
        """Test lite mode falls back to inputSchema when no TOOL_PARAM_SCHEMAS entry."""
        mock_tool = MagicMock()
        mock_tool.name = "some_tool"
        mock_tool.description = "Some tool description"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {
                "param1": {"type": "string"},
                "param2": {"type": "integer"}
            },
            "required": ["param1"]
        }

        with patch("src.tool_schemas.get_tool_definitions", return_value=[mock_tool]), \
             patch("src.mcp_handlers.validators.TOOL_PARAM_SCHEMAS", {}), \
             patch("src.mcp_handlers.validators.PARAM_ALIASES", {}):
            from src.mcp_handlers.admin import handle_describe_tool
            result = await handle_describe_tool({
                "tool_name": "some_tool",
                "lite": True
            })

            data = parse_result(result)
            assert data["success"] is True
            assert data["tool"] == "some_tool"
            assert len(data["parameters"]) > 0

    @pytest.mark.asyncio
    async def test_describe_tool_error_handling(self, patch_context_agent_id):
        with patch("src.tool_schemas.get_tool_definitions",
                    side_effect=ImportError("module not found")):
            from src.mcp_handlers.admin import handle_describe_tool
            result = await handle_describe_tool({"tool_name": "health_check"})

            data = parse_result(result)
            assert data["success"] is False


# ============================================================================
# handle_health_check
# ============================================================================

class TestHealthCheck:

    @pytest.mark.asyncio
    async def test_health_check_calibration_error(self, mock_mcp_server, patch_context_agent_id):
        """Test that calibration errors are caught and reported."""
        mock_audit = MagicMock()
        mock_audit.log_file = MagicMock()
        mock_audit.log_file.exists.return_value = True

        mock_db = AsyncMock()
        mock_db.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_db.init = AsyncMock()

        with patch("src.mcp_handlers.admin.mcp_server", mock_mcp_server), \
             patch("src.calibration.calibration_checker") as mock_cal, \
             patch("src.telemetry.telemetry_collector", MagicMock()), \
             patch("src.audit_log.audit_logger", mock_audit), \
             patch("src.db.get_db", return_value=mock_db), \
             patch("src.calibration_db.calibration_health_check_async",
                   new_callable=AsyncMock,
                   return_value={"status": "healthy", "backend": "postgres"}), \
             patch("src.audit_db.audit_health_check_async",
                   new_callable=AsyncMock,
                   return_value={"status": "healthy", "backend": "postgres"}), \
             patch("src.cache.is_redis_available", return_value=False), \
             patch("src.knowledge_graph.get_knowledge_graph",
                   new_callable=AsyncMock) as mock_kg:

            mock_cal.get_pending_updates.side_effect = RuntimeError("calibration broken")
            mock_kg_instance = AsyncMock()
            mock_kg_instance.health_check = AsyncMock(return_value={"status": "healthy"})
            mock_kg.return_value = mock_kg_instance

            from src.mcp_handlers.admin import handle_health_check
            result = await handle_health_check({})

            data = parse_result(result)
            assert data["success"] is True
            assert "checks" in data
            assert data["checks"]["calibration"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_health_check_overall_status_logic(self, mock_mcp_server, patch_context_agent_id):
        """Test the three-tier status logic: healthy, moderate, critical."""
        mock_audit = MagicMock()
        mock_audit.log_file = MagicMock()
        mock_audit.log_file.exists.return_value = True

        mock_db = AsyncMock()
        mock_db.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_db.init = AsyncMock()

        mock_cal = MagicMock()
        mock_cal.get_pending_updates.return_value = 0

        with patch("src.mcp_handlers.admin.mcp_server", mock_mcp_server), \
             patch("src.calibration.calibration_checker", mock_cal), \
             patch("src.telemetry.telemetry_collector", MagicMock()), \
             patch("src.audit_log.audit_logger", mock_audit), \
             patch("src.db.get_db", return_value=mock_db), \
             patch("src.calibration_db.calibration_health_check_async",
                   new_callable=AsyncMock,
                   return_value={"status": "healthy", "backend": "postgres"}), \
             patch("src.audit_db.audit_health_check_async",
                   new_callable=AsyncMock,
                   return_value={"status": "healthy", "backend": "postgres"}), \
             patch("src.cache.is_redis_available", return_value=False), \
             patch("src.knowledge_graph.get_knowledge_graph",
                   new_callable=AsyncMock) as mock_kg:

            mock_kg_instance = AsyncMock()
            mock_kg_instance.health_check = AsyncMock(return_value={"status": "healthy"})
            mock_kg.return_value = mock_kg_instance

            from src.mcp_handlers.admin import handle_health_check
            result = await handle_health_check({})

            data = parse_result(result)
            assert "status" in data
            assert "status_breakdown" in data
            assert data["version"] == "test-1.0.0"


# ============================================================================
# handle_debug_request_context
# ============================================================================

class TestDebugRequestContext:

    @pytest.mark.asyncio
    async def test_debug_context_basic(self, mock_mcp_server):
        with patch("src.mcp_handlers.admin.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="test-session"), \
             patch("src.mcp_handlers.TOOL_HANDLERS", {"tool1": None, "tool2": None}), \
             patch("src.mcp_handlers.identity_v2._derive_session_key", return_value="derived-key"), \
             patch("src.mcp_handlers.identity_shared._session_identities", {}), \
             patch("src.mcp_handlers.identity_shared._uuid_prefix_index", {}):
            from src.mcp_handlers.admin import handle_debug_request_context
            result = await handle_debug_request_context({})

            data = parse_result(result)
            assert data["success"] is True
            assert "session" in data
            assert "tool_registry" in data
            assert data["tool_registry"]["count"] == 2


# ============================================================================
# handle_check_calibration
# ============================================================================

class TestCheckCalibration:

    @pytest.mark.asyncio
    async def test_check_calibration_basic(self, patch_context_agent_id):
        mock_checker = MagicMock()
        mock_checker.check_calibration.return_value = (
            True,  # is_calibrated
            {
                "bins": {
                    "low": {"count": 10, "accuracy": 0.8, "expected_accuracy": 0.3},
                    "high": {"count": 5, "accuracy": 0.9, "expected_accuracy": 0.8},
                },
                "issues": [],
            }
        )
        mock_checker.get_pending_updates.return_value = 0

        with patch("src.calibration.calibration_checker", mock_checker):
            from src.mcp_handlers.admin import handle_check_calibration
            result = await handle_check_calibration({})

            data = parse_result(result)
            assert data["success"] is True
            assert data["calibrated"] is True
            assert data["total_samples"] == 15
            assert "confidence_distribution" in data

    @pytest.mark.asyncio
    async def test_check_calibration_with_complexity(self, patch_context_agent_id):
        mock_checker = MagicMock()
        mock_checker.check_calibration.return_value = (
            False,
            {
                "bins": {
                    "low": {"count": 5, "accuracy": 0.5, "expected_accuracy": 0.2},
                },
                "issues": ["Overconfident in low bin"],
                "complexity_calibration": {
                    "simple": {"count": 3, "high_discrepancy_rate": 0.1},
                    "complex": {"count": 2, "high_discrepancy_rate": 0.8},
                }
            }
        )
        mock_checker.get_pending_updates.return_value = 2

        with patch("src.calibration.calibration_checker", mock_checker):
            from src.mcp_handlers.admin import handle_check_calibration
            result = await handle_check_calibration({})

            data = parse_result(result)
            assert data["calibrated"] is False
            assert data["pending_updates"] == 2
            assert "complexity_calibration" in data

    @pytest.mark.asyncio
    async def test_check_calibration_empty_bins(self, patch_context_agent_id):
        mock_checker = MagicMock()
        mock_checker.check_calibration.return_value = (True, {"bins": {}, "issues": []})
        mock_checker.get_pending_updates.return_value = 0

        with patch("src.calibration.calibration_checker", mock_checker):
            from src.mcp_handlers.admin import handle_check_calibration
            result = await handle_check_calibration({})

            data = parse_result(result)
            assert data["total_samples"] == 0
            assert data["trajectory_health"] == 0.0
            assert data["confidence_distribution"]["mean"] == 0.0


# ============================================================================
# handle_rebuild_calibration
# ============================================================================

class TestRebuildCalibration:

    @pytest.mark.asyncio
    async def test_rebuild_calibration_success(self, patch_context_agent_id):
        mock_result = {"processed": 10, "updated": 8, "skipped": 2, "errors": 0}
        with patch("src.auto_ground_truth.collect_ground_truth_automatically",
                    new_callable=AsyncMock, return_value=mock_result):
            from src.mcp_handlers.admin import handle_rebuild_calibration
            result = await handle_rebuild_calibration({})

            data = parse_result(result)
            assert data["success"] is True
            assert data["processed"] == 10
            assert data["updated"] == 8
            assert data["action"] == "rebuild"

    @pytest.mark.asyncio
    async def test_rebuild_calibration_dry_run(self, patch_context_agent_id):
        mock_result = {"processed": 5, "updated": 5, "skipped": 0, "errors": 0}
        with patch("src.auto_ground_truth.collect_ground_truth_automatically",
                    new_callable=AsyncMock, return_value=mock_result):
            from src.mcp_handlers.admin import handle_rebuild_calibration
            result = await handle_rebuild_calibration({"dry_run": True})

            data = parse_result(result)
            assert data["action"] == "dry_run"

    @pytest.mark.asyncio
    async def test_rebuild_calibration_string_dry_run(self, patch_context_agent_id):
        """Test that string 'true' is parsed as bool for dry_run."""
        mock_result = {"processed": 1, "updated": 1, "skipped": 0, "errors": 0}
        with patch("src.auto_ground_truth.collect_ground_truth_automatically",
                    new_callable=AsyncMock, return_value=mock_result):
            from src.mcp_handlers.admin import handle_rebuild_calibration
            result = await handle_rebuild_calibration({"dry_run": "true"})

            data = parse_result(result)
            assert data["action"] == "dry_run"

    @pytest.mark.asyncio
    async def test_rebuild_calibration_error(self, patch_context_agent_id):
        with patch("src.auto_ground_truth.collect_ground_truth_automatically",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("no data")):
            from src.mcp_handlers.admin import handle_rebuild_calibration
            result = await handle_rebuild_calibration({})

            data = parse_result(result)
            assert data["success"] is False
            assert "no data" in data["error"]

    @pytest.mark.asyncio
    async def test_rebuild_calibration_custom_params(self, patch_context_agent_id):
        mock_result = {"processed": 3, "updated": 3, "skipped": 0, "errors": 0}
        with patch("src.auto_ground_truth.collect_ground_truth_automatically",
                    new_callable=AsyncMock, return_value=mock_result) as mock_fn:
            from src.mcp_handlers.admin import handle_rebuild_calibration
            result = await handle_rebuild_calibration({
                "min_age_hours": 2.0,
                "max_decisions": 50,
            })

            # Verify parameters were passed through
            call_kwargs = mock_fn.call_args
            assert call_kwargs.kwargs["min_age_hours"] == 2.0
            assert call_kwargs.kwargs["max_decisions"] == 50
            assert call_kwargs.kwargs["rebuild"] is True


# ============================================================================
# handle_update_calibration_ground_truth
# ============================================================================

class TestUpdateCalibrationGroundTruth:

    @pytest.mark.asyncio
    async def test_direct_mode_success(self, patch_context_agent_id):
        mock_checker = MagicMock()
        mock_checker.get_pending_updates.return_value = 1

        with patch("src.calibration.calibration_checker", mock_checker):
            from src.mcp_handlers.admin import handle_update_calibration_ground_truth
            result = await handle_update_calibration_ground_truth({
                "confidence": 0.8,
                "predicted_correct": True,
                "actual_correct": True,
            })

            data = parse_result(result)
            assert data["success"] is True
            assert "direct mode" in data["message"].lower()
            mock_checker.update_ground_truth.assert_called_once()
            mock_checker.save_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_mode_missing_params(self, patch_context_agent_id):
        from src.mcp_handlers.admin import handle_update_calibration_ground_truth
        result = await handle_update_calibration_ground_truth({
            "confidence": 0.8,
            # missing predicted_correct and actual_correct
        })

        data = parse_result(result)
        assert data["success"] is False
        assert "missing" in data["error"].lower() or "required" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_timestamp_mode_missing_actual_correct(self, patch_context_agent_id):
        from src.mcp_handlers.admin import handle_update_calibration_ground_truth
        result = await handle_update_calibration_ground_truth({
            "timestamp": "2026-01-01T00:00:00",
            # missing actual_correct
        })

        data = parse_result(result)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_timestamp_mode_no_entries_found(self, patch_context_agent_id):
        mock_audit = MagicMock()
        mock_audit.query_audit_log.return_value = []

        with patch("src.calibration.calibration_checker", MagicMock()), \
             patch("src.audit_log.AuditLogger", return_value=mock_audit):
            from src.mcp_handlers.admin import handle_update_calibration_ground_truth
            result = await handle_update_calibration_ground_truth({
                "timestamp": "2026-01-01T00:00:00",
                "actual_correct": True,
            })

            data = parse_result(result)
            assert data["success"] is False
            assert "no decision found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_timestamp_mode_success(self, patch_context_agent_id):
        mock_audit = MagicMock()
        mock_audit.query_audit_log.return_value = [
            {"confidence": 0.85, "details": {"decision": "attest"}}
        ]
        mock_checker = MagicMock()
        mock_checker.get_pending_updates.return_value = 1

        with patch("src.calibration.calibration_checker", mock_checker), \
             patch("src.audit_log.AuditLogger", return_value=mock_audit):
            from src.mcp_handlers.admin import handle_update_calibration_ground_truth
            result = await handle_update_calibration_ground_truth({
                "timestamp": "2026-01-01T00:00:00",
                "actual_correct": True,
            })

            data = parse_result(result)
            assert data["success"] is True
            assert "timestamp mode" in data["message"].lower()
            assert data["looked_up"]["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_timestamp_mode_invalid_format(self, patch_context_agent_id):
        from src.mcp_handlers.admin import handle_update_calibration_ground_truth
        result = await handle_update_calibration_ground_truth({
            "timestamp": 12345,  # not a string
            "actual_correct": True,
        })

        data = parse_result(result)
        assert data["success"] is False


# ============================================================================
# handle_get_telemetry_metrics
# ============================================================================

class TestGetTelemetryMetrics:

    @pytest.mark.asyncio
    async def test_telemetry_basic(self, patch_context_agent_id):
        mock_telemetry = MagicMock()
        mock_telemetry.get_skip_rate_metrics.return_value = {"skip_rate": 0.1}
        mock_telemetry.get_confidence_distribution.return_value = {"mean": 0.7}
        mock_telemetry.detect_suspicious_patterns.return_value = []

        with patch("src.telemetry.TelemetryCollector", return_value=mock_telemetry), \
             patch("src.perf_monitor.snapshot", return_value={"avg_ms": 5}):
            from src.mcp_handlers.admin import handle_get_telemetry_metrics
            result = await handle_get_telemetry_metrics({})

            data = parse_result(result)
            assert data["success"] is True
            assert data["agent_id"] == "all_agents"
            assert data["window_hours"] == 24
            assert "calibration" in data  # should have note about excluded

    @pytest.mark.asyncio
    async def test_telemetry_with_calibration(self, patch_context_agent_id):
        mock_telemetry = MagicMock()
        mock_telemetry.get_skip_rate_metrics.return_value = {}
        mock_telemetry.get_confidence_distribution.return_value = {}
        mock_telemetry.detect_suspicious_patterns.return_value = []
        mock_telemetry.get_calibration_metrics.return_value = {"calibrated": True}

        with patch("src.telemetry.TelemetryCollector", return_value=mock_telemetry), \
             patch("src.perf_monitor.snapshot", return_value={}):
            from src.mcp_handlers.admin import handle_get_telemetry_metrics
            result = await handle_get_telemetry_metrics({
                "include_calibration": True,
                "agent_id": "agent-1",
                "window_hours": 48,
            })

            data = parse_result(result)
            assert data["agent_id"] == "agent-1"
            assert data["window_hours"] == 48
            assert data["calibration"]["calibrated"] is True

    @pytest.mark.asyncio
    async def test_telemetry_error(self, patch_context_agent_id):
        mock_telemetry = MagicMock()
        mock_telemetry.get_skip_rate_metrics.side_effect = RuntimeError("telemetry broken")

        with patch("src.telemetry.TelemetryCollector", return_value=mock_telemetry):
            from src.mcp_handlers.admin import handle_get_telemetry_metrics
            result = await handle_get_telemetry_metrics({})

            data = parse_result(result)
            assert data["success"] is False


# ============================================================================
# handle_backfill_calibration_from_dialectic
# ============================================================================

class TestBackfillCalibration:

    @pytest.mark.asyncio
    async def test_backfill_success(self, patch_context_agent_id):
        mock_result = {"processed": 5, "updated": 3, "errors": 0, "sessions": []}
        with patch(
            "src.mcp_handlers.dialectic.backfill_calibration_from_historical_sessions",
            new_callable=AsyncMock,
            return_value=mock_result
        ):
            from src.mcp_handlers.admin import handle_backfill_calibration_from_dialectic
            result = await handle_backfill_calibration_from_dialectic({})

            data = parse_result(result)
            assert data["success"] is True
            assert data["processed"] == 5
            assert data["updated"] == 3

    @pytest.mark.asyncio
    async def test_backfill_error(self, patch_context_agent_id):
        with patch(
            "src.mcp_handlers.dialectic.backfill_calibration_from_historical_sessions",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB down")
        ):
            from src.mcp_handlers.admin import handle_backfill_calibration_from_dialectic
            result = await handle_backfill_calibration_from_dialectic({})

            data = parse_result(result)
            assert data["success"] is False
            assert "DB down" in data["error"]


# ============================================================================
# handle_check_continuity_health
# ============================================================================

class TestCheckContinuityHealth:

    @pytest.mark.asyncio
    async def test_continuity_health_basic(self, mock_mcp_server, patch_context_agent_id):
        mock_mcp_server.agent_metadata = {
            "agent-1": MagicMock(status="active"),
            "agent-2": MagicMock(status="archived"),
        }
        mock_graph = AsyncMock()
        mock_graph.get_stats = AsyncMock(return_value={
            "total_discoveries": 10,
            "total_agents": 2,
        })
        mock_graph.query = AsyncMock(return_value=[])

        # Patch both the module-level and the shared.get_mcp_server (re-imported inside handler)
        with patch("src.mcp_handlers.admin.get_mcp_server", return_value=mock_mcp_server), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_mcp_server), \
             patch("src.mcp_handlers.knowledge_graph.get_knowledge_graph",
                   new_callable=AsyncMock, return_value=mock_graph):
            from src.mcp_handlers.admin import handle_check_continuity_health
            result = await handle_check_continuity_health({})

            data = parse_result(result)
            assert data["success"] is True
            assert "checks" in data
            assert data["checks"]["agent_metadata"]["count"] == 2
            assert data["checks"]["agent_metadata"]["active_agents"] == 1

    @pytest.mark.asyncio
    async def test_continuity_health_deep_check(self, mock_mcp_server, patch_context_agent_id):
        mock_mcp_server.agent_metadata = {}
        mock_discovery = MagicMock()
        mock_discovery.provenance = {"created_by": "agent-1"}

        mock_graph = AsyncMock()
        mock_graph.get_stats = AsyncMock(return_value={
            "total_discoveries": 1, "total_agents": 1
        })
        mock_graph.query = AsyncMock(return_value=[mock_discovery])

        with patch("src.mcp_handlers.admin.get_mcp_server", return_value=mock_mcp_server), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_mcp_server), \
             patch("src.mcp_handlers.knowledge_graph.get_knowledge_graph",
                   new_callable=AsyncMock, return_value=mock_graph):
            from src.mcp_handlers.admin import handle_check_continuity_health
            result = await handle_check_continuity_health({"deep_check": True})

            data = parse_result(result)
            assert data["checks"]["provenance_tracking"]["sample_provenance_count"] == 1

    @pytest.mark.asyncio
    async def test_continuity_health_with_agent_id(self, mock_mcp_server, patch_context_agent_id):
        meta = MagicMock()
        meta.parent_agent_id = None
        meta.spawn_reason = "user"
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        mock_graph = AsyncMock()
        mock_graph.get_stats = AsyncMock(return_value={
            "total_discoveries": 1, "total_agents": 1
        })
        mock_graph.query = AsyncMock(return_value=[])

        with patch("src.mcp_handlers.admin.get_mcp_server", return_value=mock_mcp_server), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_mcp_server), \
             patch("src.mcp_handlers.knowledge_graph.get_knowledge_graph",
                   new_callable=AsyncMock, return_value=mock_graph), \
             patch("src.mcp_handlers.identity_shared._get_lineage", return_value=["agent-1"]):
            from src.mcp_handlers.admin import handle_check_continuity_health
            result = await handle_check_continuity_health({"agent_id": "agent-1"})

            data = parse_result(result)
            assert "agent_lineage" in data["checks"]
            assert data["checks"]["agent_lineage"]["agent_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_continuity_health_error(self, mock_mcp_server, patch_context_agent_id):
        # Patch shared.get_mcp_server too since it's re-imported inside the handler
        with patch("src.mcp_handlers.admin.get_mcp_server",
                    side_effect=RuntimeError("server down")), \
             patch("src.mcp_handlers.shared.get_mcp_server",
                    side_effect=RuntimeError("server down")):
            from src.mcp_handlers.admin import handle_check_continuity_health
            result = await handle_check_continuity_health({})

            data = parse_result(result)
            assert data["success"] is False

    @pytest.mark.asyncio
    async def test_continuity_health_recommendations(self, mock_mcp_server, patch_context_agent_id):
        """Test recommendations are generated when metadata is empty."""
        mock_mcp_server.agent_metadata = {}
        mock_graph = AsyncMock()
        mock_graph.get_stats = AsyncMock(return_value={
            "total_discoveries": 0, "total_agents": 0
        })
        mock_graph.query = AsyncMock(return_value=[])

        with patch("src.mcp_handlers.admin.get_mcp_server", return_value=mock_mcp_server), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_mcp_server), \
             patch("src.mcp_handlers.knowledge_graph.get_knowledge_graph",
                   new_callable=AsyncMock, return_value=mock_graph):
            from src.mcp_handlers.admin import handle_check_continuity_health
            result = await handle_check_continuity_health({})

            data = parse_result(result)
            assert len(data["recommendations"]) >= 2


# ============================================================================
# Workspace helper functions (sync)
# ============================================================================

class TestWorkspaceHelpers:

    def test_get_workspace_last_agent_file(self):
        from src.mcp_handlers.admin import get_workspace_last_agent_file
        server = MagicMock()
        server.project_root = "/tmp/test_project"

        result = get_workspace_last_agent_file(server)
        assert result == Path("/tmp/test_project/data/.last_active_agent")

    def test_get_workspace_last_agent_found(self, tmp_path):
        from src.mcp_handlers.admin import get_workspace_last_agent

        server = MagicMock()
        server.project_root = str(tmp_path)
        server.agent_metadata = {"agent-123": MagicMock()}

        # Create the file
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / ".last_active_agent").write_text("agent-123")

        result = get_workspace_last_agent(server)
        assert result == "agent-123"

    def test_get_workspace_last_agent_not_found(self, tmp_path):
        from src.mcp_handlers.admin import get_workspace_last_agent

        server = MagicMock()
        server.project_root = str(tmp_path)
        server.agent_metadata = {}

        result = get_workspace_last_agent(server)
        assert result is None

    def test_get_workspace_last_agent_file_missing(self, tmp_path):
        from src.mcp_handlers.admin import get_workspace_last_agent

        server = MagicMock()
        server.project_root = str(tmp_path)
        server.agent_metadata = {"agent-1": MagicMock()}

        result = get_workspace_last_agent(server)
        assert result is None

    def test_get_workspace_last_agent_stale(self, tmp_path):
        """Agent ID in file no longer exists in metadata."""
        from src.mcp_handlers.admin import get_workspace_last_agent

        server = MagicMock()
        server.project_root = str(tmp_path)
        server.agent_metadata = {"other-agent": MagicMock()}

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / ".last_active_agent").write_text("old-agent")

        result = get_workspace_last_agent(server)
        assert result is None

    def test_set_workspace_last_agent(self, tmp_path):
        from src.mcp_handlers.admin import set_workspace_last_agent

        server = MagicMock()
        server.project_root = str(tmp_path)

        set_workspace_last_agent(server, "agent-abc")

        written = (tmp_path / "data" / ".last_active_agent").read_text()
        assert written == "agent-abc"

    def test_set_workspace_last_agent_creates_dir(self, tmp_path):
        from src.mcp_handlers.admin import set_workspace_last_agent

        server = MagicMock()
        server.project_root = str(tmp_path)

        # data dir does not exist yet
        set_workspace_last_agent(server, "agent-xyz")

        assert (tmp_path / "data" / ".last_active_agent").exists()

    def test_set_workspace_last_agent_error_suppressed(self):
        """set_workspace_last_agent suppresses errors."""
        from src.mcp_handlers.admin import set_workspace_last_agent

        server = MagicMock()
        server.project_root = "/nonexistent/path/that/will/fail"

        # Should not raise
        set_workspace_last_agent(server, "agent-err")


# ============================================================================
# handle_list_tools - basic tests
# ============================================================================

class TestListTools:

    @pytest.mark.asyncio
    async def test_list_tools_lite_mode(self, mock_mcp_server, patch_context_agent_id):
        """Test list_tools in lite mode (default)."""
        mock_mcp_server.SERVER_VERSION = "test-1.0.0"

        with patch("src.mcp_handlers.admin.get_mcp_server", return_value=mock_mcp_server), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_mcp_server), \
             patch("src.mcp_handlers.admin.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.TOOL_HANDLERS", {
                 "onboard": None,
                 "process_agent_update": None,
                 "health_check": None,
                 "list_tools": None,
             }), \
             patch("src.tool_modes.TOOL_TIERS", {
                 "essential": {"onboard", "process_agent_update", "list_tools"},
                 "common": {"health_check"},
                 "advanced": set(),
             }), \
             patch("src.tool_modes.TOOL_OPERATIONS", {
                 "onboard": "write",
                 "process_agent_update": "write",
                 "health_check": "read",
                 "list_tools": "read",
             }), \
             patch("src.tool_modes.LITE_MODE_TOOLS", {
                 "onboard", "process_agent_update", "list_tools", "health_check"
             }), \
             patch("src.mcp_handlers.tool_stability.list_all_aliases", return_value={}), \
             patch("src.mcp_handlers.decorators.get_tool_timeout", return_value=10.0), \
             patch("src.mcp_handlers.decorators.get_tool_description", return_value=""), \
             patch("src.tool_schemas.get_tool_definitions", return_value=[]):

            from src.mcp_handlers.admin import handle_list_tools
            result = await handle_list_tools({"lite": True})

            data = parse_result(result)
            assert data["success"] is True
            assert "tools" in data
            assert data["shown"] > 0
