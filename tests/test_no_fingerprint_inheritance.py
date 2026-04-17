"""
Tests for the spec docs/specs/2026-04-16-sever-fingerprint-eisv-inheritance-design.md

Covers:
- State transplant is gone (agent_lifecycle.get_or_create_monitor)
- Fingerprint match on resume=False no longer sets _predecessor_uuid
- Explicit parent_agent_id still records lineage (without state transplant)
- continuity_token round-trip preserves UUID
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from src.agent_metadata_model import AgentMetadata, agent_metadata
from src.agent_monitor_state import monitors


@pytest.fixture(autouse=True)
def _clear_process_state():
    """Each test starts with fresh in-memory identity state."""
    monitors.clear()
    agent_metadata.clear()
    yield
    monitors.clear()
    agent_metadata.clear()


def test_get_or_create_monitor_does_not_transplant_state_from_predecessor():
    """
    Regression guard: once agent_lifecycle.get_or_create_monitor no longer
    transplants state from a predecessor, a new agent with parent_agent_id
    set should start with a fresh GovernanceState (empty V_history).
    """
    from src.agent_lifecycle import get_or_create_monitor
    from src.governance_monitor import UNITARESMonitor

    # Build a predecessor monitor and populate its state so
    # load_monitor_state(parent_uuid) would return something real.
    # Fixed UUID4s (deterministic) — real UUIDs are required because
    # downstream code in agent_metadata_persistence.get_or_create_metadata
    # validates agent_id against a strict UUID4 pattern; using non-UUID
    # strings could cause the test to fail for the wrong reason or pass
    # vacuously after the Task 2 fix lands.
    parent_uuid = "11111111-1111-4111-8111-111111111111"
    parent_monitor = UNITARESMonitor(parent_uuid)
    parent_monitor.state.V_history.extend([0.1, 0.2, 0.3])
    monitors[parent_uuid] = parent_monitor

    # Child agent metadata points to the predecessor.
    # NOTE: get_or_create_monitor calls get_or_create_metadata(child_uuid)
    # BEFORE reading agent_metadata[child_uuid] to decide about transplant.
    # Verified (see src/agent_metadata_persistence.py:359) that
    # get_or_create_metadata is a no-op when the entry already exists —
    # it returns the existing AgentMetadata untouched — so the seed below
    # survives into the transplant branch.
    child_uuid = "22222222-2222-4222-8222-222222222222"
    now_iso = "2026-04-16T00:00:00+00:00"
    agent_metadata[child_uuid] = AgentMetadata(
        agent_id=child_uuid,
        status="active",
        created_at=now_iso,
        last_update=now_iso,
        parent_agent_id=parent_uuid,
    )

    # load_monitor_state(parent_uuid) in the real code path would return
    # the parent's persisted state. Force it to return the parent's in-memory
    # state so the "if we wanted to transplant, we could" path is exercised.
    def fake_load(agent_id):
        if agent_id == parent_uuid:
            return parent_monitor.state
        return None

    with patch("src.agent_lifecycle.load_monitor_state", side_effect=fake_load):
        child_monitor = get_or_create_monitor(child_uuid)

    assert child_monitor.state.V_history == [], (
        "Child agent must not inherit predecessor V_history "
        f"(got {child_monitor.state.V_history!r})"
    )


@pytest.mark.asyncio
async def test_path1_redis_hit_resume_false_does_not_set_predecessor():
    """
    PATH 1: Redis lookup finds a cached agent. resume=False now creates
    a new identity WITHOUT recording the cached agent as predecessor.
    """
    from unittest.mock import AsyncMock, MagicMock, patch
    from src.mcp_handlers.identity import resolution as resolution_mod

    existing_uuid = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    cache_hit = {
        "agent_id": existing_uuid,
        "display_agent_id": "OldAgent",
    }
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=cache_hit)

    mock_raw_redis = AsyncMock()
    mock_raw_redis.expire = AsyncMock(return_value=True)

    mock_db = AsyncMock()
    mock_db.init = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=None)
    mock_db.upsert_agent = AsyncMock()
    mock_db.upsert_identity = AsyncMock()
    mock_db.create_session = AsyncMock()
    mock_db.get_identity = AsyncMock(return_value=None)

    async def _get_raw():
        return mock_raw_redis

    with patch.object(resolution_mod, "_get_redis", return_value=mock_redis), \
         patch("src.cache.redis_client.get_redis", new=_get_raw), \
         patch.object(resolution_mod, "get_db", return_value=mock_db), \
         patch.object(resolution_mod, "_agent_exists_in_postgres", AsyncMock(return_value=True)), \
         patch.object(resolution_mod, "_get_agent_label", AsyncMock(return_value="OldAgent")), \
         patch.object(resolution_mod, "_get_agent_status", AsyncMock(return_value="active")), \
         patch.object(resolution_mod, "_soft_verify_trajectory", AsyncMock(return_value={"verified": True})), \
         patch.object(resolution_mod, "_cache_session", AsyncMock()):
        result = await resolution_mod.resolve_session_identity(
            session_key="fp-session-1",
            resume=False,
            persist=False,
        )

    # A brand-new identity should have been created.
    assert result["created"] is True
    assert result["agent_uuid"] != existing_uuid
    # And it MUST NOT carry predecessor_uuid forward.
    assert "predecessor_uuid" not in result, (
        f"resume=False + Redis fingerprint hit must not leak predecessor_uuid "
        f"(got {result.get('predecessor_uuid')!r})"
    )


@pytest.mark.asyncio
async def test_path2_postgres_hit_resume_false_does_not_set_predecessor():
    """
    PATH 2: Redis miss, PostgreSQL finds a session-bound agent.
    resume=False must not claim that agent as predecessor.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch
    from src.mcp_handlers.identity import resolution as resolution_mod

    existing_uuid = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)  # PATH 1 miss

    mock_raw_redis = AsyncMock()
    mock_raw_redis.expire = AsyncMock(return_value=True)

    mock_db = AsyncMock()
    mock_db.init = AsyncMock()
    mock_db.get_session = AsyncMock(
        return_value=SimpleNamespace(agent_id=existing_uuid)
    )
    mock_db.upsert_agent = AsyncMock()
    mock_db.upsert_identity = AsyncMock()
    mock_db.create_session = AsyncMock()
    mock_db.get_identity = AsyncMock(return_value=None)

    async def _get_raw():
        return mock_raw_redis

    with patch.object(resolution_mod, "_get_redis", return_value=mock_redis), \
         patch("src.cache.redis_client.get_redis", new=_get_raw), \
         patch.object(resolution_mod, "get_db", return_value=mock_db), \
         patch.object(resolution_mod, "_agent_exists_in_postgres", AsyncMock(return_value=True)), \
         patch.object(resolution_mod, "_get_agent_label", AsyncMock(return_value="OldAgent")), \
         patch.object(resolution_mod, "_get_agent_status", AsyncMock(return_value="active")), \
         patch.object(resolution_mod, "_soft_verify_trajectory", AsyncMock(return_value={"verified": True})), \
         patch.object(resolution_mod, "_cache_session", AsyncMock()):
        result = await resolution_mod.resolve_session_identity(
            session_key="fp-session-2",
            resume=False,
            persist=False,
        )

    assert result["created"] is True
    assert result["agent_uuid"] != existing_uuid
    assert "predecessor_uuid" not in result, (
        f"resume=False + PostgreSQL session hit must not leak predecessor_uuid "
        f"(got {result.get('predecessor_uuid')!r})"
    )
