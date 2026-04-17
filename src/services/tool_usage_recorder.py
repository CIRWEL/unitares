"""Records tool call telemetry to JSONL + audit.tool_usage.

Shared between STDIO transport (src/mcp_server_std.py) and HTTP transport
(src/services/http_tool_service.py). JSONL write is synchronous; DB write is
fire-and-forget via create_tracked_task so request handlers never await
asyncpg (anyio-asyncio deadlock rule).
"""

from __future__ import annotations

from typing import Optional

from src.logging_utils import get_logger

logger = get_logger(__name__)


def record_tool_usage(
    tool_name: str,
    agent_id: Optional[str],
    success: bool,
    error_type: Optional[str] = None,
    latency_ms: Optional[int] = None,
) -> None:
    """Record a tool call. Never raises — telemetry failure must not break the call."""
    try:
        from src.tool_usage_tracker import get_tool_usage_tracker
        get_tool_usage_tracker().log_tool_call(
            tool_name=tool_name, agent_id=agent_id, success=success, error_type=error_type,
        )
    except Exception as e:
        logger.debug(f"JSONL tool_usage log failed (non-fatal): {e}")

    try:
        from src.background_tasks import create_tracked_task
        from src.audit_db import append_tool_usage_async
        create_tracked_task(
            append_tool_usage_async(
                agent_id=agent_id,
                tool_name=tool_name,
                latency_ms=latency_ms,
                success=success,
                error_type=error_type,
            ),
            name="persist_tool_usage",
        )
    except RuntimeError:
        pass  # no running event loop (CLI / tests)
    except Exception as e:
        logger.debug(f"DB tool_usage persist failed (non-fatal): {e}")
