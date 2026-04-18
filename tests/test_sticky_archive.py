"""Tests for sticky-archive guard: manual-intent + cooldown window.

Regression coverage for the 2026-04-18 incident where acd8a774 was
manually archived at 01:29:33 and resurrected 10 seconds later via
process_agent_update, then circuit-broke ~45 min later.
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import parse_result
from tests.test_core_update import (
    _make_metadata,
    _make_mock_mcp_server,
    _make_monitor,
)


# ----------------------------------------------------------------------
# Local helpers — duplicated from test_core_update.TestProcessAgentUpdate
# to avoid pytest re-running the parent class's tests via inheritance.
# ----------------------------------------------------------------------


def _common_patches(mock_server, agent_uuid="test-uuid-1234",
                    context_agent_id=None, context_session_key="session-1"):
    ctx_agent = context_agent_id or agent_uuid
    mock_storage = MagicMock(
        update_agent=AsyncMock(),
        get_agent=AsyncMock(return_value=None),
        get_or_create_agent=AsyncMock(
            return_value=(MagicMock(api_key="test-key"), True)
        ),
        record_agent_state=AsyncMock(),
        create_agent=AsyncMock(),
    )
    return {
        "mcp_server": mock_server,
        "ctx_agent_id": ctx_agent,
        "ctx_session_key": context_session_key,
        "storage": mock_storage,
    }


def _apply_patches(patches_dict):
    stack = ExitStack()
    stack.enter_context(patch("src.mcp_handlers.core.mcp_server", patches_dict["mcp_server"]))
    stack.enter_context(patch(
        "src.mcp_handlers.context.get_context_agent_id",
        return_value=patches_dict["ctx_agent_id"],
    ))
    stack.enter_context(patch(
        "src.mcp_handlers.context.get_context_session_key",
        return_value=patches_dict["ctx_session_key"],
    ))
    stack.enter_context(patch(
        "src.mcp_handlers.identity.handlers.ensure_agent_persisted",
        new_callable=AsyncMock, return_value=False,
    ))
    stack.enter_context(patch(
        "src.mcp_handlers.updates.phases.agent_storage",
        patches_dict["storage"],
    ))
    return stack


@pytest.fixture
def mock_server():
    return _make_mock_mcp_server()


@pytest.fixture
def mock_monitor():
    return _make_monitor()


# ----------------------------------------------------------------------
# Task 2: Cooldown guard refuses auto-resume when archive is recent.
# ----------------------------------------------------------------------


class TestCooldownGuard:
    """Archive → immediate process_agent_update must NOT auto-resume."""

    @pytest.mark.asyncio
    async def test_recent_archive_within_cooldown_is_rejected(
        self, mock_server, mock_monitor
    ):
        """Archive <300s ago blocks auto-resume even without 'user requested' marker."""
        agent_uuid = "test-uuid-cooldown"
        recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        meta = _make_metadata(status="archived", total_updates=5)
        meta.archived_at = recent
        meta.notes = ""  # No manual marker — must still be blocked by cooldown.
        mock_server.agent_metadata = {agent_uuid: meta}
        mock_server.get_or_create_monitor.return_value = mock_monitor
        mock_server.monitors = {agent_uuid: mock_monitor}

        p = _common_patches(mock_server, agent_uuid=agent_uuid)
        with _apply_patches(p):
            from src.mcp_handlers.core import handle_process_agent_update
            result = await handle_process_agent_update({
                "response_text": "Immediate resurrection attempt.",
                "response_mode": "full",
            })
            data = parse_result(result)

        assert data["success"] is False, (
            f"Expected auto-resume to be refused within cooldown. "
            f"Got: {json.dumps(data, default=str)[:400]}"
        )
        error_lower = data["error"].lower()
        assert "cooldown" in error_lower or "recent" in error_lower or "seconds" in error_lower, (
            f"Error message should cite cooldown/recent/seconds. Got: {data['error']!r}"
        )
        assert data["context"]["status"] == "archived"
