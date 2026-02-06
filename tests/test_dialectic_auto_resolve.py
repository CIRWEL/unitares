"""
Tests for src/mcp_handlers/dialectic_auto_resolve.py

Tests auto-resolution of stuck dialectic sessions.
Uses mocked dialectic DB functions.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta, timezone

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# --- auto_resolve_stuck_sessions Tests ---


@pytest.mark.asyncio
async def test_no_active_sessions():
    """Should return 0 resolved when no active sessions."""
    with patch("src.mcp_handlers.dialectic_auto_resolve.get_active_sessions_async",
               new_callable=AsyncMock, return_value=[]):
        from src.mcp_handlers.dialectic_auto_resolve import auto_resolve_stuck_sessions
        result = await auto_resolve_stuck_sessions()

    assert result["resolved_count"] == 0
    assert "No active sessions" in result["message"]


@pytest.mark.asyncio
async def test_no_stuck_sessions():
    """Active sessions that are recent should not be resolved."""
    recent_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    sessions = [
        {"session_id": "s1", "updated_at": recent_time, "paused_agent_id": "a1", "phase": "thesis"}
    ]

    with patch("src.mcp_handlers.dialectic_auto_resolve.get_active_sessions_async",
               new_callable=AsyncMock, return_value=sessions):
        from src.mcp_handlers.dialectic_auto_resolve import auto_resolve_stuck_sessions
        result = await auto_resolve_stuck_sessions()

    assert result["resolved_count"] == 0
    assert "No stuck sessions" in result["message"]


@pytest.mark.asyncio
async def test_resolves_stuck_session():
    """Sessions inactive for >2 hours should be auto-resolved."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    sessions = [
        {"session_id": "stuck-1", "updated_at": old_time, "paused_agent_id": "a1", "phase": "thesis"}
    ]

    mock_update = AsyncMock()
    mock_add_msg = AsyncMock()
    mock_get_db = AsyncMock()

    with patch("src.mcp_handlers.dialectic_auto_resolve.get_active_sessions_async",
               new_callable=AsyncMock, return_value=sessions), \
         patch("src.mcp_handlers.dialectic_auto_resolve.update_session_status_async",
               mock_update), \
         patch("src.mcp_handlers.dialectic_auto_resolve.add_message_async",
               mock_add_msg), \
         patch("src.mcp_handlers.dialectic_auto_resolve.get_dialectic_db",
               mock_get_db):
        from src.mcp_handlers.dialectic_auto_resolve import auto_resolve_stuck_sessions
        result = await auto_resolve_stuck_sessions()

    assert result["resolved_count"] == 1
    mock_update.assert_called_once_with("stuck-1", "failed")


@pytest.mark.asyncio
async def test_resolves_multiple_stuck_sessions():
    """Should resolve all stuck sessions, not just the first one."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    sessions = [
        {"session_id": "s1", "updated_at": old_time, "paused_agent_id": "a1", "phase": "thesis"},
        {"session_id": "s2", "updated_at": old_time, "paused_agent_id": "a2", "phase": "antithesis"},
        {"session_id": "s3", "created_at": old_time, "paused_agent_id": "a3", "phase": "synthesis"},
    ]

    mock_update = AsyncMock()
    mock_add_msg = AsyncMock()
    mock_get_db = AsyncMock()

    with patch("src.mcp_handlers.dialectic_auto_resolve.get_active_sessions_async",
               new_callable=AsyncMock, return_value=sessions), \
         patch("src.mcp_handlers.dialectic_auto_resolve.update_session_status_async",
               mock_update), \
         patch("src.mcp_handlers.dialectic_auto_resolve.add_message_async",
               mock_add_msg), \
         patch("src.mcp_handlers.dialectic_auto_resolve.get_dialectic_db",
               mock_get_db):
        from src.mcp_handlers.dialectic_auto_resolve import auto_resolve_stuck_sessions
        result = await auto_resolve_stuck_sessions()

    assert result["resolved_count"] == 3
    assert mock_update.call_count == 3


@pytest.mark.asyncio
async def test_uses_created_at_fallback():
    """Should fall back to created_at when updated_at is missing."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    sessions = [
        {"session_id": "s1", "created_at": old_time, "paused_agent_id": "a1", "phase": "thesis"}
    ]

    mock_update = AsyncMock()
    mock_add_msg = AsyncMock()
    mock_get_db = AsyncMock()

    with patch("src.mcp_handlers.dialectic_auto_resolve.get_active_sessions_async",
               new_callable=AsyncMock, return_value=sessions), \
         patch("src.mcp_handlers.dialectic_auto_resolve.update_session_status_async",
               mock_update), \
         patch("src.mcp_handlers.dialectic_auto_resolve.add_message_async",
               mock_add_msg), \
         patch("src.mcp_handlers.dialectic_auto_resolve.get_dialectic_db",
               mock_get_db):
        from src.mcp_handlers.dialectic_auto_resolve import auto_resolve_stuck_sessions
        result = await auto_resolve_stuck_sessions()

    assert result["resolved_count"] == 1


@pytest.mark.asyncio
async def test_handles_z_suffix_timestamps():
    """Should handle 'Z' suffix in ISO timestamps."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sessions = [
        {"session_id": "s1", "updated_at": old_time, "paused_agent_id": "a1", "phase": "thesis"}
    ]

    mock_update = AsyncMock()
    mock_add_msg = AsyncMock()
    mock_get_db = AsyncMock()

    with patch("src.mcp_handlers.dialectic_auto_resolve.get_active_sessions_async",
               new_callable=AsyncMock, return_value=sessions), \
         patch("src.mcp_handlers.dialectic_auto_resolve.update_session_status_async",
               mock_update), \
         patch("src.mcp_handlers.dialectic_auto_resolve.add_message_async",
               mock_add_msg), \
         patch("src.mcp_handlers.dialectic_auto_resolve.get_dialectic_db",
               mock_get_db):
        from src.mcp_handlers.dialectic_auto_resolve import auto_resolve_stuck_sessions
        result = await auto_resolve_stuck_sessions()

    assert result["resolved_count"] == 1


@pytest.mark.asyncio
async def test_handles_naive_datetime_timestamps():
    """Should handle naive datetime strings (no 'T' separator)."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    sessions = [
        {"session_id": "s1", "updated_at": old_time, "paused_agent_id": "a1", "phase": "thesis"}
    ]

    mock_update = AsyncMock()
    mock_add_msg = AsyncMock()
    mock_get_db = AsyncMock()

    with patch("src.mcp_handlers.dialectic_auto_resolve.get_active_sessions_async",
               new_callable=AsyncMock, return_value=sessions), \
         patch("src.mcp_handlers.dialectic_auto_resolve.update_session_status_async",
               mock_update), \
         patch("src.mcp_handlers.dialectic_auto_resolve.add_message_async",
               mock_add_msg), \
         patch("src.mcp_handlers.dialectic_auto_resolve.get_dialectic_db",
               mock_get_db):
        from src.mcp_handlers.dialectic_auto_resolve import auto_resolve_stuck_sessions
        result = await auto_resolve_stuck_sessions()

    assert result["resolved_count"] == 1


@pytest.mark.asyncio
async def test_handles_session_without_id():
    """Sessions without session_id should be skipped."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    sessions = [
        {"updated_at": old_time, "paused_agent_id": "a1", "phase": "thesis"}  # No session_id
    ]

    mock_update = AsyncMock()
    mock_get_db = AsyncMock()

    with patch("src.mcp_handlers.dialectic_auto_resolve.get_active_sessions_async",
               new_callable=AsyncMock, return_value=sessions), \
         patch("src.mcp_handlers.dialectic_auto_resolve.update_session_status_async",
               mock_update), \
         patch("src.mcp_handlers.dialectic_auto_resolve.add_message_async",
               AsyncMock()), \
         patch("src.mcp_handlers.dialectic_auto_resolve.get_dialectic_db",
               mock_get_db):
        from src.mcp_handlers.dialectic_auto_resolve import auto_resolve_stuck_sessions
        result = await auto_resolve_stuck_sessions()

    assert result["resolved_count"] == 0
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_handles_get_sessions_error():
    """Should handle errors from get_active_sessions_async gracefully."""
    with patch("src.mcp_handlers.dialectic_auto_resolve.get_active_sessions_async",
               new_callable=AsyncMock, side_effect=Exception("DB error")):
        from src.mcp_handlers.dialectic_auto_resolve import auto_resolve_stuck_sessions
        result = await auto_resolve_stuck_sessions()

    assert result["resolved_count"] == 0
    assert "error" in result


@pytest.mark.asyncio
async def test_handles_update_error_gracefully():
    """Should continue resolving other sessions when one update fails."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    sessions = [
        {"session_id": "s1", "updated_at": old_time, "paused_agent_id": "a1", "phase": "thesis"},
        {"session_id": "s2", "updated_at": old_time, "paused_agent_id": "a2", "phase": "thesis"},
    ]

    # First update fails, second succeeds
    mock_update = AsyncMock(side_effect=[Exception("update failed"), None])
    mock_get_db = AsyncMock()

    with patch("src.mcp_handlers.dialectic_auto_resolve.get_active_sessions_async",
               new_callable=AsyncMock, return_value=sessions), \
         patch("src.mcp_handlers.dialectic_auto_resolve.update_session_status_async",
               mock_update), \
         patch("src.mcp_handlers.dialectic_auto_resolve.add_message_async",
               AsyncMock()), \
         patch("src.mcp_handlers.dialectic_auto_resolve.get_dialectic_db",
               mock_get_db):
        from src.mcp_handlers.dialectic_auto_resolve import auto_resolve_stuck_sessions
        result = await auto_resolve_stuck_sessions()

    # Only second should succeed
    assert result["resolved_count"] == 1


# --- check_and_resolve_stuck_sessions Tests ---


@pytest.mark.asyncio
async def test_check_and_resolve_delegates():
    """check_and_resolve_stuck_sessions should delegate to auto_resolve."""
    with patch("src.mcp_handlers.dialectic_auto_resolve.get_active_sessions_async",
               new_callable=AsyncMock, return_value=[]):
        from src.mcp_handlers.dialectic_auto_resolve import check_and_resolve_stuck_sessions
        result = await check_and_resolve_stuck_sessions()

    assert result["resolved_count"] == 0


@pytest.mark.asyncio
async def test_check_and_resolve_handles_error():
    """check_and_resolve should catch errors from auto_resolve."""
    with patch("src.mcp_handlers.dialectic_auto_resolve.auto_resolve_stuck_sessions",
               new_callable=AsyncMock, side_effect=Exception("unexpected")):
        from src.mcp_handlers.dialectic_auto_resolve import check_and_resolve_stuck_sessions
        result = await check_and_resolve_stuck_sessions()

    assert result["resolved_count"] == 0
    assert "error" in result


# --- STUCK_SESSION_THRESHOLD Tests ---


def test_stuck_threshold_is_2_hours():
    """Threshold should match DialecticProtocol.MAX_ANTITHESIS_WAIT."""
    from src.mcp_handlers.dialectic_auto_resolve import STUCK_SESSION_THRESHOLD
    assert STUCK_SESSION_THRESHOLD == timedelta(hours=2)
