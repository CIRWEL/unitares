from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.mixins.audit import AuditMixin


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Backend(AuditMixin):
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


@pytest.mark.asyncio
async def test_agent_scoped_confidence_lookup_does_not_fallback_to_other_agents():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    backend = _Backend(conn)

    result = await backend.get_latest_confidence_before(
        before_ts=datetime(2026, 4, 12, tzinfo=timezone.utc),
        agent_id="agent-a",
    )

    assert result is None
    conn.fetchrow.assert_awaited_once()
    sql = conn.fetchrow.call_args.args[0]
    assert "agent_id = $1" in sql


@pytest.mark.asyncio
async def test_global_confidence_lookup_still_works_without_agent_id():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"confidence": 0.73})
    backend = _Backend(conn)

    result = await backend.get_latest_confidence_before(
        before_ts=datetime(2026, 4, 12, tzinfo=timezone.utc),
        agent_id=None,
    )

    assert result == 0.73
    conn.fetchrow.assert_awaited_once()
    sql = conn.fetchrow.call_args.args[0]
    assert "agent_id NOT IN ('system', 'eisv-sync-task')" in sql
