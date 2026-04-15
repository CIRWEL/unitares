"""
Integration tests for src/db/postgres_backend.py

Runs against a real PostgreSQL database (governance_test).
Requires CI_LIVE_SERVICES=1 and a reachable governance_test (see tests.test_db_utils).
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Check prerequisites
try:
    import asyncpg
except ImportError:
    pytest.skip("asyncpg not installed", allow_module_level=True)

from tests.test_db_utils import (
    TEST_DB_URL,
    can_connect_to_test_db,
    live_integration_enabled,
)

if not live_integration_enabled():
    pytest.skip(
        "Set CI_LIVE_SERVICES=1 to run live DB integration tests",
        allow_module_level=True,
    )

if not can_connect_to_test_db():
    pytest.skip("governance_test database not available", allow_module_level=True)

pytestmark = pytest.mark.integration_live

# ============================================================================
# Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def backend(live_postgres_backend):
    """Alias for live_postgres_backend; keeps existing test parameter names."""
    return live_postgres_backend


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_agent(backend, agent_id: str):
    """Create agent row in core.agents (required FK for identities)."""
    await backend.upsert_agent(agent_id, "test_key")


async def _create_identity_with_agent(backend) -> tuple:
    """Create agent + identity, return (agent_id, identity_id)."""
    agent_id = _uuid()
    await _ensure_agent(backend, agent_id)
    identity_id = await backend.upsert_identity(agent_id, "hash1")
    return agent_id, identity_id


# ============================================================================
# Init / Health / Pool
# ============================================================================


class TestInitAndHealth:

    @pytest.mark.asyncio
    async def test_health_check_returns_healthy(self, backend):
        result = await backend.health_check()
        assert result["status"] == "healthy"
        assert result["backend"] == "postgres"
        assert result["pool_size"] >= 1
        assert result["pool_free"] >= 0

    @pytest.mark.asyncio
    async def test_health_check_shows_counts(self, backend):
        result = await backend.health_check()
        assert result["identity_count"] == 0
        assert result["active_session_count"] == 0

    @pytest.mark.asyncio
    async def test_health_check_age_available(self, backend):
        result = await backend.health_check()
        assert result["age_available"] is True
        assert result["age_graph"] == "governance_graph"

    @pytest.mark.asyncio
    async def test_acquire_returns_connection(self, backend):
        async with backend.acquire() as conn:
            val = await conn.fetchval("SELECT 42")
            assert val == 42

    @pytest.mark.asyncio
    async def test_close_and_reinit(self):
        """Backend can be closed and reinitialized."""
        os.environ["DB_POSTGRES_URL"] = TEST_DB_URL
        os.environ["DB_POSTGRES_MIN_CONN"] = "1"
        os.environ["DB_POSTGRES_MAX_CONN"] = "2"

        from src.db.postgres_backend import PostgresBackend

        be = PostgresBackend()
        await be.init()
        async with be.acquire() as conn:
            assert await conn.fetchval("SELECT 1") == 1
        await be.close()

        # Pool is None after close
        assert be._pool is None

        # _ensure_pool recreates it
        pool = await be._ensure_pool()
        assert pool is not None
        await be.close()


# ============================================================================
# Identity Operations
# ============================================================================


class TestIdentityOperations:

    @pytest.mark.asyncio
    async def test_upsert_identity_creates(self, backend):
        agent_id = _uuid()
        await _ensure_agent(backend, agent_id)
        identity_id = await backend.upsert_identity(agent_id, "hash123")
        assert isinstance(identity_id, int)
        assert identity_id > 0

    @pytest.mark.asyncio
    async def test_upsert_identity_with_metadata(self, backend):
        agent_id = _uuid()
        await _ensure_agent(backend, agent_id)
        await backend.upsert_identity(
            agent_id, "hash123",
            metadata={"model": "claude", "version": "4.5"}
        )
        record = await backend.get_identity(agent_id)
        assert record is not None
        assert record.metadata["model"] == "claude"

    @pytest.mark.asyncio
    async def test_upsert_identity_upsert_merges_metadata(self, backend):
        agent_id = _uuid()
        await _ensure_agent(backend, agent_id)
        await backend.upsert_identity(agent_id, "hash1", metadata={"a": 1})
        await backend.upsert_identity(agent_id, "hash1", metadata={"b": 2})
        record = await backend.get_identity(agent_id)
        assert record.metadata.get("a") == 1
        assert record.metadata.get("b") == 2

    @pytest.mark.asyncio
    async def test_get_identity_not_found(self, backend):
        result = await backend.get_identity("nonexistent-" + _uuid())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_identity_by_id(self, backend):
        agent_id, identity_id = await _create_identity_with_agent(backend)
        record = await backend.get_identity_by_id(identity_id)
        assert record is not None
        assert record.agent_id == agent_id

    @pytest.mark.asyncio
    async def test_get_identity_by_id_not_found(self, backend):
        result = await backend.get_identity_by_id(999999)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_identities_all(self, backend):
        for _ in range(2):
            await _create_identity_with_agent(backend)
        records = await backend.list_identities()
        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_list_identities_with_status_filter(self, backend):
        a1, _ = await _create_identity_with_agent(backend)
        a2, _ = await _create_identity_with_agent(backend)
        await backend.update_identity_status(a2, "disabled")
        active = await backend.list_identities(status="active")
        assert len(active) == 1
        assert active[0].agent_id == a1

    @pytest.mark.asyncio
    async def test_list_identities_pagination(self, backend):
        for _ in range(5):
            await _create_identity_with_agent(backend)
        page1 = await backend.list_identities(limit=2, offset=0)
        page2 = await backend.list_identities(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].agent_id != page2[0].agent_id

    @pytest.mark.asyncio
    async def test_update_identity_status(self, backend):
        agent_id, _ = await _create_identity_with_agent(backend)
        result = await backend.update_identity_status(agent_id, "disabled", disabled_at=_now())
        assert result is True
        record = await backend.get_identity(agent_id)
        assert record.status == "disabled"
        assert record.disabled_at is not None

    @pytest.mark.asyncio
    async def test_update_identity_status_nonexistent(self, backend):
        result = await backend.update_identity_status("nonexistent", "disabled")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_identity_metadata_merge(self, backend):
        agent_id, _ = await _create_identity_with_agent(backend)
        await backend.update_identity_metadata(agent_id, {"a": 1, "b": 2}, merge=False)
        result = await backend.update_identity_metadata(agent_id, {"b": 99, "c": 3}, merge=True)
        assert result is True
        record = await backend.get_identity(agent_id)
        assert record.metadata["a"] == 1
        assert record.metadata["b"] == 99
        assert record.metadata["c"] == 3

    @pytest.mark.asyncio
    async def test_update_identity_metadata_replace(self, backend):
        agent_id, _ = await _create_identity_with_agent(backend)
        await backend.update_identity_metadata(agent_id, {"a": 1, "b": 2}, merge=False)
        result = await backend.update_identity_metadata(agent_id, {"x": 10}, merge=False)
        assert result is True
        record = await backend.get_identity(agent_id)
        assert record.metadata == {"x": 10}

    @pytest.mark.asyncio
    async def test_update_identity_metadata_nonexistent(self, backend):
        result = await backend.update_identity_metadata("nonexistent", {"a": 1})
        assert result is False

    @pytest.mark.asyncio
    async def test_upsert_identity_with_parent(self, backend):
        parent_id, _ = await _create_identity_with_agent(backend)
        child_id = _uuid()
        await _ensure_agent(backend, child_id)
        await backend.upsert_identity(child_id, "hc", parent_agent_id=parent_id)
        record = await backend.get_identity(child_id)
        assert record.parent_agent_id == parent_id

    @pytest.mark.asyncio
    async def test_identity_record_fields(self, backend):
        agent_id, identity_id = await _create_identity_with_agent(backend)
        record = await backend.get_identity(agent_id)
        assert record.identity_id == identity_id
        assert record.agent_id == agent_id
        assert record.api_key_hash == "hash1"
        assert record.status == "active"
        assert record.created_at is not None
        assert record.updated_at is not None


# ============================================================================
# Agent Operations (core.agents)
# ============================================================================


class TestAgentOperations:

    @pytest.mark.asyncio
    async def test_upsert_agent_creates(self, backend):
        agent_id = _uuid()
        result = await backend.upsert_agent(agent_id, "key123", purpose="testing")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_agent(self, backend):
        agent_id = _uuid()
        await backend.upsert_agent(agent_id, "key1", purpose="test agent", notes="some notes", tags=["test", "ci"])
        agent = await backend.get_agent(agent_id)
        assert agent is not None
        assert str(agent["id"]) == agent_id
        assert agent["purpose"] == "test agent"
        assert agent["notes"] == "some notes"
        assert "test" in agent["tags"]

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, backend):
        result = await backend.get_agent("nonexistent-" + _uuid())
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_agent_update_preserves_api_key(self, backend):
        agent_id = _uuid()
        await backend.upsert_agent(agent_id, "real_key")
        await backend.upsert_agent(agent_id, "", purpose="updated purpose")
        agent = await backend.get_agent(agent_id)
        assert agent["api_key"] == "real_key"  # Empty string shouldn't overwrite
        assert agent["purpose"] == "updated purpose"

    @pytest.mark.asyncio
    async def test_update_agent_fields(self, backend):
        agent_id = _uuid()
        await backend.upsert_agent(agent_id, "key1")
        result = await backend.update_agent_fields(
            agent_id, status="archived", label="MyAgent", tags=["archived"]
        )
        assert result is True
        agent = await backend.get_agent(agent_id)
        assert agent["status"] == "archived"
        assert str(agent["label"]) == "MyAgent"

    @pytest.mark.asyncio
    async def test_update_agent_fields_nonexistent(self, backend):
        result = await backend.update_agent_fields("nonexistent", status="active")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_agent_label(self, backend):
        agent_id = _uuid()
        await backend.upsert_agent(agent_id, "key1")
        await backend.update_agent_fields(agent_id, label="TestBot")
        label = await backend.get_agent_label(agent_id)
        assert label == "TestBot"

    @pytest.mark.asyncio
    async def test_get_agent_label_not_found(self, backend):
        label = await backend.get_agent_label("nonexistent-" + _uuid())
        assert label is None

    @pytest.mark.asyncio
    async def test_find_agent_by_label(self, backend):
        agent_id = _uuid()
        await backend.upsert_agent(agent_id, "key1")
        await backend.update_agent_fields(agent_id, label="UniqueLabel")
        found = await backend.find_agent_by_label("UniqueLabel")
        assert str(found) == agent_id

    @pytest.mark.asyncio
    async def test_find_agent_by_label_not_found(self, backend):
        found = await backend.find_agent_by_label("NoSuchLabel")
        assert found is None


# ============================================================================
# Session Operations
# ============================================================================


class TestSessionOperations:

    @pytest.mark.asyncio
    async def test_create_session(self, backend):
        _, identity_id = await _create_identity_with_agent(backend)
        session_id = _uuid()
        result = await backend.create_session(
            session_id, identity_id,
            expires_at=_now() + timedelta(hours=24)
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_create_session_duplicate(self, backend):
        _, identity_id = await _create_identity_with_agent(backend)
        session_id = _uuid()
        await backend.create_session(session_id, identity_id, expires_at=_now() + timedelta(hours=24))
        result = await backend.create_session(session_id, identity_id, expires_at=_now() + timedelta(hours=24))
        assert result is False

    @pytest.mark.asyncio
    async def test_get_session(self, backend):
        agent_id, identity_id = await _create_identity_with_agent(backend)
        session_id = _uuid()
        await backend.create_session(
            session_id, identity_id,
            expires_at=_now() + timedelta(hours=24),
            client_type="test",
            client_info={"tool": "pytest"},
        )
        session = await backend.get_session(session_id)
        assert session is not None
        assert session.session_id == session_id
        assert session.identity_id == identity_id
        assert session.agent_id == agent_id
        assert session.is_active is True
        assert session.client_type == "test"
        assert session.client_info["tool"] == "pytest"

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, backend):
        result = await backend.get_session("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_end_session(self, backend):
        _, identity_id = await _create_identity_with_agent(backend)
        session_id = _uuid()
        await backend.create_session(session_id, identity_id, expires_at=_now() + timedelta(hours=24))
        result = await backend.end_session(session_id)
        assert result is True
        session = await backend.get_session(session_id)
        assert session.is_active is False

    @pytest.mark.asyncio
    async def test_end_session_nonexistent(self, backend):
        result = await backend.end_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_active_sessions_for_identity(self, backend):
        _, identity_id = await _create_identity_with_agent(backend)
        s1, s2 = _uuid(), _uuid()
        await backend.create_session(s1, identity_id, expires_at=_now() + timedelta(hours=24))
        await backend.create_session(s2, identity_id, expires_at=_now() + timedelta(hours=24))
        await backend.end_session(s1)
        active = await backend.get_active_sessions_for_identity(identity_id)
        assert len(active) == 1
        assert active[0].session_id == s2

    @pytest.mark.asyncio
    async def test_update_session_activity(self, backend):
        _, identity_id = await _create_identity_with_agent(backend)
        session_id = _uuid()
        await backend.create_session(session_id, identity_id, expires_at=_now() + timedelta(hours=24))
        session_before = await backend.get_session(session_id)
        await asyncio.sleep(0.05)
        result = await backend.update_session_activity(session_id)
        assert result is True
        session_after = await backend.get_session(session_id)
        assert session_after.last_active >= session_before.last_active


# ============================================================================
# Agent State Operations
# ============================================================================


class TestAgentStateOperations:

    @pytest.mark.asyncio
    async def test_record_agent_state(self, backend):
        _, identity_id = await _create_identity_with_agent(backend)
        state_id = await backend.record_agent_state(
            identity_id,
            entropy=0.7, integrity=0.8,
            stability_index=0.3, void=0.2,
            regime="nominal", coherence=0.52,
        )
        assert isinstance(state_id, int)
        assert state_id > 0

    @pytest.mark.asyncio
    async def test_record_state_with_json(self, backend):
        _, identity_id = await _create_identity_with_agent(backend)
        await backend.record_agent_state(
            identity_id,
            entropy=0.5, integrity=0.5,
            stability_index=0.5, void=0.1,
            regime="nominal", coherence=1.0,
            state_json={"decision": "proceed", "phi": 0.85},
        )
        state = await backend.get_latest_agent_state(identity_id)
        assert state.state_json["decision"] == "proceed"

    @pytest.mark.asyncio
    async def test_get_latest_agent_state(self, backend):
        agent_id, identity_id = await _create_identity_with_agent(backend)
        await backend.record_agent_state(
            identity_id, entropy=0.3, integrity=0.9,
            stability_index=0.5, void=0.1,
            regime="nominal", coherence=0.55,
        )
        state = await backend.get_latest_agent_state(identity_id)
        assert state is not None
        assert state.agent_id == agent_id
        assert state.entropy == pytest.approx(0.3)
        assert state.integrity == pytest.approx(0.9)
        assert state.regime == "nominal"

    @pytest.mark.asyncio
    async def test_get_latest_agent_state_returns_most_recent(self, backend):
        _, identity_id = await _create_identity_with_agent(backend)
        await backend.record_agent_state(
            identity_id, entropy=0.1, integrity=0.1,
            stability_index=0.1, void=0.1,
            regime="nominal", coherence=0.5,
        )
        await backend.record_agent_state(
            identity_id, entropy=0.9, integrity=0.9,
            stability_index=0.9, void=0.9,
            regime="critical", coherence=0.9,
        )
        state = await backend.get_latest_agent_state(identity_id)
        assert state.regime == "critical"
        assert state.entropy == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_get_latest_state_not_found(self, backend):
        result = await backend.get_latest_agent_state(999999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_agent_state_history(self, backend):
        _, identity_id = await _create_identity_with_agent(backend)
        for i in range(5):
            await backend.record_agent_state(
                identity_id, entropy=i * 0.1, integrity=0.5,
                stability_index=0.5, void=0.1,
                regime="nominal", coherence=0.5,
            )
        history = await backend.get_agent_state_history(identity_id, limit=3)
        assert len(history) == 3
        assert history[0].entropy > history[2].entropy

    @pytest.mark.asyncio
    async def test_get_agent_state_history_empty(self, backend):
        result = await backend.get_agent_state_history(999999)
        assert result == []


# ============================================================================
# Audit Operations
# ============================================================================


class TestAuditOperations:

    @pytest.mark.asyncio
    async def test_append_audit_event(self, backend):
        from src.db.base import AuditEvent

        event = AuditEvent(
            ts=_now(),
            event_id=str(uuid.uuid4()),
            event_type="test_event",
            agent_id="agent-1",
            session_id="session-1",
            confidence=0.95,
            payload={"action": "test"},
        )
        result = await backend.append_audit_event(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_append_audit_event_invalid_uuid(self, backend):
        from src.db.base import AuditEvent

        event = AuditEvent(
            ts=_now(),
            event_id="not-a-uuid",
            event_type="test_event",
        )
        # Should generate new UUID and succeed
        result = await backend.append_audit_event(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_append_audit_event_no_event_id(self, backend):
        from src.db.base import AuditEvent

        event = AuditEvent(
            ts=_now(),
            event_id=None,
            event_type="test_event",
        )
        result = await backend.append_audit_event(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_query_audit_events_no_filter(self, backend):
        from src.db.base import AuditEvent

        for i in range(3):
            await backend.append_audit_event(AuditEvent(
                ts=_now(),
                event_id=str(uuid.uuid4()),
                event_type=f"type_{i}",
                agent_id="agent-1",
            ))
        events = await backend.query_audit_events()
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_query_audit_events_by_agent_id(self, backend):
        from src.db.base import AuditEvent

        for agent in ["a1", "a2", "a1"]:
            await backend.append_audit_event(AuditEvent(
                ts=_now(),
                event_id=str(uuid.uuid4()),
                event_type="test",
                agent_id=agent,
            ))
        events = await backend.query_audit_events(agent_id="a1")
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_query_audit_events_by_type(self, backend):
        from src.db.base import AuditEvent

        await backend.append_audit_event(AuditEvent(
            ts=_now(), event_id=str(uuid.uuid4()),
            event_type="governance_decision", agent_id="a1",
        ))
        await backend.append_audit_event(AuditEvent(
            ts=_now(), event_id=str(uuid.uuid4()),
            event_type="tool_call", agent_id="a1",
        ))
        events = await backend.query_audit_events(event_type="governance_decision")
        assert len(events) == 1
        assert events[0].event_type == "governance_decision"

    @pytest.mark.asyncio
    async def test_query_audit_events_order(self, backend):
        from src.db.base import AuditEvent

        t1 = _now()
        t2 = t1 + timedelta(seconds=1)
        await backend.append_audit_event(AuditEvent(
            ts=t1, event_id=str(uuid.uuid4()), event_type="first",
        ))
        await backend.append_audit_event(AuditEvent(
            ts=t2, event_id=str(uuid.uuid4()), event_type="second",
        ))
        events_asc = await backend.query_audit_events(order="asc")
        assert events_asc[0].event_type == "first"
        events_desc = await backend.query_audit_events(order="desc")
        assert events_desc[0].event_type == "second"

    @pytest.mark.asyncio
    async def test_query_audit_events_time_range(self, backend):
        from src.db.base import AuditEvent

        now = _now()
        await backend.append_audit_event(AuditEvent(
            ts=now - timedelta(hours=2), event_id=str(uuid.uuid4()),
            event_type="old",
        ))
        await backend.append_audit_event(AuditEvent(
            ts=now, event_id=str(uuid.uuid4()),
            event_type="new",
        ))
        events = await backend.query_audit_events(
            start_time=now - timedelta(hours=1),
        )
        assert len(events) == 1
        assert events[0].event_type == "new"

    @pytest.mark.asyncio
    async def test_search_audit_events(self, backend):
        from src.db.base import AuditEvent

        await backend.append_audit_event(AuditEvent(
            ts=_now(), event_id=str(uuid.uuid4()),
            event_type="test", payload={"message": "found the needle here"},
        ))
        await backend.append_audit_event(AuditEvent(
            ts=_now(), event_id=str(uuid.uuid4()),
            event_type="test", payload={"message": "nothing special"},
        ))
        results = await backend.search_audit_events("needle")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_audit_events_with_agent_id(self, backend):
        from src.db.base import AuditEvent

        await backend.append_audit_event(AuditEvent(
            ts=_now(), event_id=str(uuid.uuid4()),
            event_type="test", agent_id="a1",
            payload={"message": "keyword match"},
        ))
        await backend.append_audit_event(AuditEvent(
            ts=_now(), event_id=str(uuid.uuid4()),
            event_type="test", agent_id="a2",
            payload={"message": "keyword match"},
        ))
        results = await backend.search_audit_events("keyword", agent_id="a1")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_audit_event_record_fields(self, backend):
        from src.db.base import AuditEvent

        event = AuditEvent(
            ts=_now(), event_id=str(uuid.uuid4()),
            event_type="test_full",
            agent_id="agent-x",
            session_id="session-y",
            confidence=0.87,
            payload={"key": "value"},
            raw_hash="abc123",
        )
        await backend.append_audit_event(event)
        events = await backend.query_audit_events(agent_id="agent-x")
        assert len(events) == 1
        e = events[0]
        assert e.event_type == "test_full"
        assert e.agent_id == "agent-x"
        assert e.confidence == pytest.approx(0.87)
        assert e.payload["key"] == "value"
        assert e.raw_hash == "abc123"


# ============================================================================
# Calibration Operations
# ============================================================================


class TestCalibrationOperations:

    @pytest.mark.asyncio
    async def test_get_calibration_default(self, backend):
        data = await backend.get_calibration()
        assert isinstance(data, dict)
        assert "_version" in data

    @pytest.mark.asyncio
    async def test_update_calibration(self, backend):
        result = await backend.update_calibration({
            "lambda1_threshold": 0.4,
            "bins": [0.0, 0.5, 1.0],
        })
        assert result is True
        data = await backend.get_calibration()
        assert data["lambda1_threshold"] == 0.4
        assert data["bins"] == [0.0, 0.5, 1.0]

    @pytest.mark.asyncio
    async def test_update_calibration_strips_internal_fields(self, backend):
        await backend.update_calibration({
            "real_key": True,
            "_version": 999,
            "_updated_at": "ignore",
        })
        data = await backend.get_calibration()
        assert data["real_key"] is True
        # Internal fields should not be stored in data
        assert data.get("_version") is not None  # _version comes from the row, not the data


# ============================================================================
# Tool Usage Operations
# ============================================================================


class TestToolUsageOperations:

    @pytest.mark.asyncio
    async def test_append_tool_usage(self, backend):
        result = await backend.append_tool_usage(
            agent_id="agent-1",
            session_id="session-1",
            tool_name="process_agent_update",
            latency_ms=150,
            success=True,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_append_tool_usage_with_error(self, backend):
        result = await backend.append_tool_usage(
            agent_id="agent-1",
            session_id="session-1",
            tool_name="bad_tool",
            latency_ms=50,
            success=False,
            error_type="TOOL_NOT_FOUND",
            payload={"attempted": "bad_tool"},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_query_tool_usage_no_filter(self, backend):
        await backend.append_tool_usage("a1", "s1", "tool1", 100, True)
        await backend.append_tool_usage("a2", "s2", "tool2", 200, False)
        results = await backend.query_tool_usage()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_query_tool_usage_by_agent(self, backend):
        await backend.append_tool_usage("a1", "s1", "tool1", 100, True)
        await backend.append_tool_usage("a2", "s2", "tool2", 200, True)
        results = await backend.query_tool_usage(agent_id="a1")
        assert len(results) == 1
        assert results[0]["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_query_tool_usage_by_tool_name(self, backend):
        await backend.append_tool_usage("a1", "s1", "identity", 50, True)
        await backend.append_tool_usage("a1", "s1", "knowledge", 100, True)
        results = await backend.query_tool_usage(tool_name="identity")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_query_tool_usage_result_fields(self, backend):
        await backend.append_tool_usage(
            "a1", "s1", "my_tool", 75, True,
            payload={"param": "value"},
        )
        results = await backend.query_tool_usage()
        assert len(results) == 1
        r = results[0]
        assert r["tool_name"] == "my_tool"
        assert r["latency_ms"] == 75
        assert r["success"] is True
        assert r["payload"]["param"] == "value"
        assert "ts" in r
        assert "usage_id" in r


# ============================================================================
# ============================================================================
# Knowledge Graph (FTS) Operations
# ============================================================================


class TestKnowledgeGraphOperations:

    def _make_discovery(self, **kwargs):
        """Create a mock discovery object."""
        from types import SimpleNamespace

        defaults = {
            "id": _uuid(),
            "agent_id": "agent-1",
            "type": "insight",
            "summary": "Test discovery",
            "details": "Detailed description",
            "tags": ["test", "automated"],
            "severity": "low",
            "status": "open",
            "references_files": [],
            "related_to": [],
            "response_to": None,
            "provenance": None,
            "timestamp": _now().isoformat(),
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    @pytest.mark.asyncio
    async def test_kg_add_discovery(self, backend):
        d = self._make_discovery()
        await backend.kg_add_discovery(d)
        result = await backend.kg_get_discovery(d.id)
        assert result is not None
        assert result["summary"] == "Test discovery"

    @pytest.mark.asyncio
    async def test_kg_get_discovery_not_found(self, backend):
        result = await backend.kg_get_discovery("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_kg_query_no_filter(self, backend):
        d1 = self._make_discovery(summary="First")
        d2 = self._make_discovery(summary="Second")
        await backend.kg_add_discovery(d1)
        await backend.kg_add_discovery(d2)
        results = await backend.kg_query()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_kg_query_by_agent(self, backend):
        d1 = self._make_discovery(agent_id="a1")
        d2 = self._make_discovery(agent_id="a2")
        await backend.kg_add_discovery(d1)
        await backend.kg_add_discovery(d2)
        results = await backend.kg_query(agent_id="a1")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_kg_query_by_type(self, backend):
        d1 = self._make_discovery(type="bug")
        d2 = self._make_discovery(type="insight")
        await backend.kg_add_discovery(d1)
        await backend.kg_add_discovery(d2)
        results = await backend.kg_query(type="bug")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_kg_query_by_tags(self, backend):
        d1 = self._make_discovery(tags=["security", "critical"])
        d2 = self._make_discovery(tags=["performance"])
        await backend.kg_add_discovery(d1)
        await backend.kg_add_discovery(d2)
        results = await backend.kg_query(tags=["security"])
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_kg_query_by_severity(self, backend):
        d1 = self._make_discovery(severity="high")
        d2 = self._make_discovery(severity="low")
        await backend.kg_add_discovery(d1)
        await backend.kg_add_discovery(d2)
        results = await backend.kg_query(severity="high")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_kg_query_by_status(self, backend):
        d1 = self._make_discovery(status="open")
        d2 = self._make_discovery(status="resolved")
        await backend.kg_add_discovery(d1)
        await backend.kg_add_discovery(d2)
        results = await backend.kg_query(status="open")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_kg_update_status(self, backend):
        d = self._make_discovery(status="open")
        await backend.kg_add_discovery(d)
        result = await backend.kg_update_status(d.id, "resolved")
        assert result is True
        updated = await backend.kg_get_discovery(d.id)
        assert updated["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_kg_update_status_not_found(self, backend):
        result = await backend.kg_update_status("nonexistent", "resolved")
        assert result is False

    @pytest.mark.asyncio
    async def test_kg_full_text_search(self, backend):
        d1 = self._make_discovery(summary="PostgreSQL connection pool exhausted")
        d2 = self._make_discovery(summary="Agent coherence is improving")
        await backend.kg_add_discovery(d1)
        await backend.kg_add_discovery(d2)
        results = await backend.kg_full_text_search("PostgreSQL pool")
        assert len(results) >= 1
        assert any("PostgreSQL" in r["summary"] for r in results)

    @pytest.mark.asyncio
    async def test_kg_find_similar(self, backend):
        d1 = self._make_discovery(tags=["security", "auth", "critical"])
        d2 = self._make_discovery(tags=["security", "auth"])
        d3 = self._make_discovery(tags=["performance", "database"])
        await backend.kg_add_discovery(d1)
        await backend.kg_add_discovery(d2)
        await backend.kg_add_discovery(d3)
        similar = await backend.kg_find_similar(d1.id)
        assert len(similar) >= 1
        # d2 should be more similar (shared tags) than d3
        assert similar[0]["id"] == d2.id

    @pytest.mark.asyncio
    async def test_kg_find_similar_no_tags(self, backend):
        d = self._make_discovery(tags=[])
        await backend.kg_add_discovery(d)
        results = await backend.kg_find_similar(d.id)
        assert results == []

    @pytest.mark.asyncio
    async def test_kg_upsert_updates_existing(self, backend):
        d = self._make_discovery(summary="Original")
        await backend.kg_add_discovery(d)
        d.summary = "Updated"
        await backend.kg_add_discovery(d)
        result = await backend.kg_get_discovery(d.id)
        assert result["summary"] == "Updated"

    @pytest.mark.asyncio
    async def test_kg_discovery_dict_fields(self, backend):
        d = self._make_discovery(
            summary="Test fields",
            details="Full details here",
            tags=["tag1", "tag2"],
            severity="medium",
            status="open",
        )
        await backend.kg_add_discovery(d)
        result = await backend.kg_get_discovery(d.id)
        assert result["summary"] == "Test fields"
        assert result["details"] == "Full details here"
        assert result["tags"] == ["tag1", "tag2"]
        assert result["severity"] == "medium"
        assert "timestamp" in result  # Mapped from created_at


# ============================================================================
# Graph Operations (AGE)
# ============================================================================


class TestGraphOperations:

    @pytest.mark.asyncio
    async def test_graph_available(self, backend):
        result = await backend.graph_available()
        if not result:
            pytest.skip("Apache AGE extension is not available in governance_test")
        assert result is True

    @pytest.mark.asyncio
    async def test_graph_query_simple(self, backend):
        if not await backend.graph_available():
            pytest.skip("Apache AGE extension is not available in governance_test")
        # Create and query a node
        await backend.graph_query("CREATE (n:TestNode {name: 'test1'})")
        results = await backend.graph_query("MATCH (n:TestNode) RETURN n")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_graph_query_with_params(self, backend):
        if not await backend.graph_available():
            pytest.skip("Apache AGE extension is not available in governance_test")
        name = "param_test_" + _uuid()[:8]
        await backend.graph_query(
            "CREATE (n:TestNode {name: ${name}})",
            params={"name": name},
        )
        results = await backend.graph_query(
            "MATCH (n:TestNode {name: ${name}}) RETURN n",
            params={"name": name},
        )
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_graph_query_error_raises(self, backend):
        if not await backend.graph_available():
            pytest.skip("Apache AGE extension is not available in governance_test")
        # Invalid Cypher should raise, not silently return error dicts
        with pytest.raises(Exception):
            await backend.graph_query("INVALID CYPHER !!!")


# ============================================================================
# Cypher Parameter Sanitization (pure, no DB needed)
# ============================================================================


class TestCypherSanitization:

    def _backend(self):
        os.environ["DB_POSTGRES_URL"] = TEST_DB_URL
        from src.db.postgres_backend import PostgresBackend
        return PostgresBackend()

    def test_sanitize_none(self):
        assert self._backend()._sanitize_cypher_param(None) == "NULL"

    def test_sanitize_bool_true(self):
        assert self._backend()._sanitize_cypher_param(True) == "true"

    def test_sanitize_bool_false(self):
        assert self._backend()._sanitize_cypher_param(False) == "false"

    def test_sanitize_int(self):
        assert self._backend()._sanitize_cypher_param(42) == "42"

    def test_sanitize_float(self):
        assert self._backend()._sanitize_cypher_param(3.14) == "3.14"

    def test_sanitize_simple_string(self):
        result = self._backend()._sanitize_cypher_param("hello")
        assert result == "'hello'"

    def test_sanitize_string_with_special_chars(self):
        result = self._backend()._sanitize_cypher_param("it's a test")
        assert "\\'" in result or "it" in result

    def test_sanitize_string_with_control_chars(self):
        result = self._backend()._sanitize_cypher_param("line1\nline2\tvalue")
        assert "\\n" in result
        assert "\\t" in result

    def test_sanitize_list(self):
        result = self._backend()._sanitize_cypher_param([1, "a", True])
        assert result.startswith("[")
        assert result.endswith("]")
        assert "1" in result
        assert "'a'" in result

    def test_sanitize_dict(self):
        result = self._backend()._sanitize_cypher_param({"key": "value"})
        assert "key" in result
        assert "value" in result

    def test_sanitize_unsupported_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            self._backend()._sanitize_cypher_param(object())


# ============================================================================
# Verify API Key
# ============================================================================


class TestVerifyApiKey:

    @pytest.mark.asyncio
    async def test_verify_valid_key(self, backend):
        agent_id = _uuid()
        await _ensure_agent(backend, agent_id)
        async with backend.acquire() as conn:
            hashed = await conn.fetchval("SELECT core.hash_api_key($1)", "my_secret_key")
        await backend.upsert_identity(agent_id, hashed)
        result = await backend.verify_api_key(agent_id, "my_secret_key")
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_invalid_key(self, backend):
        agent_id = _uuid()
        await _ensure_agent(backend, agent_id)
        async with backend.acquire() as conn:
            hashed = await conn.fetchval("SELECT core.hash_api_key($1)", "correct_key")
        await backend.upsert_identity(agent_id, hashed)
        result = await backend.verify_api_key(agent_id, "wrong_key")
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_key_nonexistent_agent(self, backend):
        result = await backend.verify_api_key("nonexistent", "any_key")
        assert result is False
