"""Tests that execute_http_tool records tool_usage telemetry at every exit."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _consume_coro(coro, name=None):
    if hasattr(coro, "close"):
        coro.close()
    return MagicMock()


@pytest.mark.asyncio
async def test_direct_handler_records_success():
    from src.services.http_tool_service import execute_http_tool

    mock_tracker = MagicMock()
    direct_handler = AsyncMock(return_value={"status": "healthy"})

    with patch("src.services.http_tool_service.get_direct_http_tool_handler",
               return_value=direct_handler), \
         patch("src.tool_usage_tracker.get_tool_usage_tracker", return_value=mock_tracker), \
         patch("src.background_tasks.create_tracked_task", side_effect=_consume_coro) as mock_track:
        result = await execute_http_tool("health_check", {"agent_id": "a1"})

    assert result == {"status": "healthy"}
    mock_tracker.log_tool_call.assert_called_once()
    assert mock_tracker.log_tool_call.call_args.kwargs["success"] is True
    assert mock_tracker.log_tool_call.call_args.kwargs["tool_name"] == "health_check"
    assert mock_track.call_count == 1


@pytest.mark.asyncio
async def test_dispatch_fallback_records_success():
    from src.services.http_tool_service import execute_http_tool

    mock_tracker = MagicMock()

    with patch("src.services.http_tool_service.get_direct_http_tool_handler",
               return_value=None), \
         patch("src.services.http_tool_service.execute_http_dispatch_fallback",
               new_callable=AsyncMock, return_value=[MagicMock()]), \
         patch("src.tool_usage_tracker.get_tool_usage_tracker", return_value=mock_tracker), \
         patch("src.background_tasks.create_tracked_task", side_effect=_consume_coro) as mock_track:
        await execute_http_tool("custom_tool", {"agent_id": "a1"})

    mock_tracker.log_tool_call.assert_called_once()
    assert mock_tracker.log_tool_call.call_args.kwargs["success"] is True
    assert mock_track.call_count == 1


@pytest.mark.asyncio
async def test_exception_records_failure_and_reraises():
    from src.services.http_tool_service import execute_http_tool

    mock_tracker = MagicMock()
    failing = AsyncMock(side_effect=ValueError("bad input"))

    with patch("src.services.http_tool_service.get_direct_http_tool_handler",
               return_value=failing), \
         patch("src.tool_usage_tracker.get_tool_usage_tracker", return_value=mock_tracker), \
         patch("src.background_tasks.create_tracked_task", side_effect=_consume_coro) as mock_track:
        with pytest.raises(ValueError, match="bad input"):
            await execute_http_tool("bad_tool", {"agent_id": "a1"})

    mock_tracker.log_tool_call.assert_called_once()
    kwargs = mock_tracker.log_tool_call.call_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["error_type"] == "ValueError"
    assert mock_track.call_count == 1


@pytest.mark.asyncio
async def test_non_dict_arguments_do_not_raise():
    """If arguments isn't a dict (edge case), recorder still gets called with agent_id=None."""
    from src.services.http_tool_service import execute_http_tool

    mock_tracker = MagicMock()
    direct_handler = AsyncMock(return_value={"ok": True})

    with patch("src.services.http_tool_service.get_direct_http_tool_handler",
               return_value=direct_handler), \
         patch("src.tool_usage_tracker.get_tool_usage_tracker", return_value=mock_tracker), \
         patch("src.background_tasks.create_tracked_task", side_effect=_consume_coro):
        await execute_http_tool("t", None)

    assert mock_tracker.log_tool_call.call_args.kwargs["agent_id"] is None
