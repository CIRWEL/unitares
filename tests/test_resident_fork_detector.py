"""Resident-fork detector: label collision on persistent-tagged agent emits event.

See docs/superpowers/plans/2026-04-19-anchor-resilience-series.md (Phase 1).
"""
from unittest.mock import AsyncMock, patch

import pytest

from src.mcp_handlers.identity import persistence


@pytest.mark.asyncio
async def test_label_collision_on_persistent_agent_emits_event():
    """When fresh onboard collides with a persistent-tagged existing agent,
    broadcaster should receive resident_fork_detected with both UUIDs."""
    existing_uuid = "907e3195-c649-49db-b753-1edc1a105f33"
    new_uuid = "7bf970d4-5713-4184-a6f8-58e798275f3f"
    label = "Watcher"

    mock_broadcaster = AsyncMock()

    mock_db = AsyncMock()
    mock_db.find_agent_by_label = AsyncMock(return_value=existing_uuid)
    mock_db.agent_has_tag = AsyncMock(return_value=True)
    mock_db.update_agent_fields = AsyncMock(return_value=True)
    mock_db.get_identity = AsyncMock(return_value=None)

    # Avoid touching mcp_server state + structured-id generation
    with patch.object(persistence, "get_db", return_value=mock_db), \
         patch.object(persistence, "_broadcaster", return_value=mock_broadcaster), \
         patch.object(persistence, "mcp_server") as mock_mcp:
        mock_mcp.agent_metadata = {}
        await persistence.set_agent_label(new_uuid, label, session_key="sk")

    mock_broadcaster.broadcast_event.assert_called_once()
    call = mock_broadcaster.broadcast_event.call_args
    assert call.kwargs["event_type"] == "resident_fork_detected"
    assert call.kwargs["agent_id"] == new_uuid
    payload = call.kwargs["payload"]
    assert payload["existing_agent_id"] == existing_uuid
    assert payload["label"] == label
    assert payload["new_label"] == f"Watcher_{new_uuid[:8]}"


@pytest.mark.asyncio
async def test_label_collision_on_non_persistent_agent_no_event():
    """Collision with a non-persistent existing agent is silently renamed
    (current behavior for ephemerals, preserved)."""
    mock_broadcaster = AsyncMock()

    mock_db = AsyncMock()
    mock_db.find_agent_by_label = AsyncMock(return_value="some-other-uuid")
    mock_db.agent_has_tag = AsyncMock(return_value=False)
    mock_db.update_agent_fields = AsyncMock(return_value=True)
    mock_db.get_identity = AsyncMock(return_value=None)

    with patch.object(persistence, "get_db", return_value=mock_db), \
         patch.object(persistence, "_broadcaster", return_value=mock_broadcaster), \
         patch.object(persistence, "mcp_server") as mock_mcp:
        mock_mcp.agent_metadata = {}
        await persistence.set_agent_label(
            "new-uuid-here", "temp-ephemeral", session_key="sk",
        )

    mock_broadcaster.broadcast_event.assert_not_called()


@pytest.mark.asyncio
async def test_no_collision_no_event_no_rename():
    """No existing agent with that label => no rename, no event."""
    mock_broadcaster = AsyncMock()

    mock_db = AsyncMock()
    mock_db.find_agent_by_label = AsyncMock(return_value=None)
    mock_db.agent_has_tag = AsyncMock(return_value=False)
    mock_db.update_agent_fields = AsyncMock(return_value=True)
    mock_db.get_identity = AsyncMock(return_value=None)

    with patch.object(persistence, "get_db", return_value=mock_db), \
         patch.object(persistence, "_broadcaster", return_value=mock_broadcaster), \
         patch.object(persistence, "mcp_server") as mock_mcp:
        mock_mcp.agent_metadata = {}
        result = await persistence.set_agent_label(
            "new-uuid", "UniqueLabel", session_key="sk",
        )

    assert result is True
    mock_broadcaster.broadcast_event.assert_not_called()
    # agent_has_tag should not have been called (short-circuits on no existing)
    mock_db.agent_has_tag.assert_not_called()


@pytest.mark.asyncio
async def test_agent_has_tag_sql_roundtrip(live_postgres_backend):
    """Integration test against live Postgres: verify agent_has_tag SQL is
    correct. Skipped by the fixture if governance_test DB unavailable."""
    be = live_postgres_backend
    seed_uuid = "00000000-0000-0000-0000-000000000fkd"
    async with be.acquire() as conn:
        await conn.execute(
            "INSERT INTO core.agents (id, api_key, status, label, tags) "
            "VALUES ($1, 'test-key', 'active', 'test-fork-detector', "
            "ARRAY['persistent']) "
            "ON CONFLICT (id) DO UPDATE SET tags = ARRAY['persistent'], "
            "status = 'active'",
            seed_uuid,
        )
    try:
        assert await be.agent_has_tag(seed_uuid, "persistent") is True
        assert await be.agent_has_tag(seed_uuid, "nonexistent-tag") is False
        assert await be.agent_has_tag(
            "00000000-0000-0000-0000-deadbeef0000", "persistent"
        ) is False
    finally:
        async with be.acquire() as conn:
            await conn.execute(
                "DELETE FROM core.agents WHERE id = $1", seed_uuid
            )
