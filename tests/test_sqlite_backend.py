"""
Comprehensive tests for SQLiteBackend.

Tests the SQLite storage backend implementing the DatabaseBackend interface.
Uses tmp_path for database files (real SQLite, no mocking needed).
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio

from src.db.base import (
    AgentStateRecord,
    AuditEvent,
    IdentityRecord,
    SessionRecord,
)
from src.db.sqlite_backend import SQLiteBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def backend(tmp_path):
    """Create a fresh SQLiteBackend pointing at a temporary database."""
    db_path = tmp_path / "test_governance.db"
    os.environ["DB_SQLITE_PATH"] = str(db_path)
    b = SQLiteBackend()
    await b.init()
    yield b
    await b.close()
    os.environ.pop("DB_SQLITE_PATH", None)


@pytest_asyncio.fixture
async def backend_async_wrap(tmp_path):
    """Create a backend with async wrapping enabled."""
    db_path = tmp_path / "test_async.db"
    os.environ["DB_SQLITE_PATH"] = str(db_path)
    os.environ["DB_SQLITE_ASYNC_WRAP"] = "true"
    b = SQLiteBackend()
    await b.init()
    yield b
    await b.close()
    os.environ.pop("DB_SQLITE_PATH", None)
    os.environ.pop("DB_SQLITE_ASYNC_WRAP", None)


def _make_agent_id():
    """Generate a random agent UUID string."""
    return str(uuid.uuid4())


def _make_api_key():
    """Generate a random API key."""
    return f"key-{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# LIFECYCLE / INIT
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Tests for init, close, and health_check."""

    @pytest.mark.asyncio
    async def test_init_creates_tables(self, backend):
        """init() should create all required tables without errors."""
        conn = backend._get_conn()
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "agent_metadata" in tables
        assert "session_identities" in tables
        assert "agent_state" in tables
        assert "audit_events" in tables
        assert "tool_usage" in tables
        assert "calibration_state" in tables

    @pytest.mark.asyncio
    async def test_init_is_idempotent(self, backend):
        """Calling init() twice should not raise."""
        await backend.init()

    @pytest.mark.asyncio
    async def test_close_sets_conn_to_none(self, tmp_path):
        """close() should clear the internal connection."""
        db_path = tmp_path / "close_test.db"
        os.environ["DB_SQLITE_PATH"] = str(db_path)
        b = SQLiteBackend()
        await b.init()
        assert b._conn is not None
        await b.close()
        assert b._conn is None
        os.environ.pop("DB_SQLITE_PATH", None)

    @pytest.mark.asyncio
    async def test_close_when_already_closed(self, tmp_path):
        """close() on an already-closed backend should not raise."""
        db_path = tmp_path / "close_double.db"
        os.environ["DB_SQLITE_PATH"] = str(db_path)
        b = SQLiteBackend()
        await b.init()
        await b.close()
        await b.close()  # Should not raise
        os.environ.pop("DB_SQLITE_PATH", None)

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, backend):
        """health_check() returns healthy status on a fresh database."""
        result = await backend.health_check()
        assert result["status"] == "healthy"
        assert result["backend"] == "sqlite"
        assert result["integrity"] == "ok"
        assert result["identity_count"] == 0
        assert result["active_session_count"] == 0
        assert result["audit_event_count"] == 0

    @pytest.mark.asyncio
    async def test_health_check_reflects_data(self, backend):
        """health_check() counts should reflect inserted data."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key123")
        result = await backend.health_check()
        assert result["identity_count"] == 1

    @pytest.mark.asyncio
    async def test_default_calibration_inserted(self, backend):
        """init() should insert default calibration data."""
        cal = await backend.get_calibration()
        assert "lambda1_threshold" in cal
        assert cal["lambda1_threshold"] == 0.3
        assert cal["lambda2_threshold"] == 0.7

    @pytest.mark.asyncio
    async def test_db_path_parent_created(self, tmp_path):
        """If the parent directory of the DB path doesn't exist, init should create it."""
        db_path = tmp_path / "nested" / "dir" / "test.db"
        os.environ["DB_SQLITE_PATH"] = str(db_path)
        b = SQLiteBackend()
        await b.init()
        assert db_path.exists()
        await b.close()
        os.environ.pop("DB_SQLITE_PATH", None)

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, backend):
        """Connection should use WAL journal mode."""
        conn = backend._get_conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


# ---------------------------------------------------------------------------
# IDENTITY OPERATIONS
# ---------------------------------------------------------------------------


class TestIdentityOperations:
    """Tests for upsert_identity, get_identity, list, update, verify."""

    @pytest.mark.asyncio
    async def test_upsert_identity_creates_new(self, backend):
        """upsert_identity should create a new agent and return a positive rowid."""
        agent_id = _make_agent_id()
        identity_id = await backend.upsert_identity(agent_id, "key_hash_1")
        assert identity_id > 0

    @pytest.mark.asyncio
    async def test_upsert_identity_returns_same_id_on_update(self, backend):
        """Upserting the same agent_id twice should return the same rowid."""
        agent_id = _make_agent_id()
        id1 = await backend.upsert_identity(agent_id, "key_hash_1")
        id2 = await backend.upsert_identity(agent_id, "key_hash_2")
        assert id1 == id2

    @pytest.mark.asyncio
    async def test_upsert_identity_with_metadata(self, backend):
        """upsert_identity should store metadata."""
        agent_id = _make_agent_id()
        meta = {"name": "test-agent", "version": 1}
        await backend.upsert_identity(agent_id, "key1", metadata=meta)
        identity = await backend.get_identity(agent_id)
        assert identity is not None
        assert identity.metadata["name"] == "test-agent"
        assert identity.metadata["version"] == 1

    @pytest.mark.asyncio
    async def test_upsert_identity_merges_metadata(self, backend):
        """Upserting with new metadata should merge with existing via json_patch."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1", metadata={"a": 1})
        await backend.upsert_identity(agent_id, "key1", metadata={"b": 2})
        identity = await backend.get_identity(agent_id)
        # json_patch should merge: {"a":1} patched with {"b":2} = {"a":1,"b":2}
        assert identity.metadata.get("a") == 1
        assert identity.metadata.get("b") == 2

    @pytest.mark.asyncio
    async def test_upsert_identity_with_parent(self, backend):
        """upsert_identity should store parent_agent_id."""
        parent_id = _make_agent_id()
        child_id = _make_agent_id()
        await backend.upsert_identity(parent_id, "key_parent")
        await backend.upsert_identity(child_id, "key_child", parent_agent_id=parent_id)
        identity = await backend.get_identity(child_id)
        assert identity.parent_agent_id == parent_id

    @pytest.mark.asyncio
    async def test_upsert_identity_with_created_at(self, backend):
        """upsert_identity should respect custom created_at."""
        agent_id = _make_agent_id()
        custom_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        await backend.upsert_identity(agent_id, "key1", created_at=custom_time)
        identity = await backend.get_identity(agent_id)
        assert identity.created_at.year == 2024
        assert identity.created_at.month == 1

    @pytest.mark.asyncio
    async def test_get_identity_returns_none_for_missing(self, backend):
        """get_identity should return None for nonexistent agent_id."""
        result = await backend.get_identity("nonexistent-agent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_identity_returns_correct_record(self, backend):
        """get_identity should return a properly populated IdentityRecord."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "my_api_key")
        identity = await backend.get_identity(agent_id)
        assert isinstance(identity, IdentityRecord)
        assert identity.agent_id == agent_id
        assert identity.api_key_hash == "my_api_key"
        assert identity.status == "active"
        assert isinstance(identity.created_at, datetime)
        assert isinstance(identity.updated_at, datetime)

    @pytest.mark.asyncio
    async def test_get_identity_by_id(self, backend):
        """get_identity_by_id should find identity by numeric rowid."""
        agent_id = _make_agent_id()
        identity_id = await backend.upsert_identity(agent_id, "key123")
        identity = await backend.get_identity_by_id(identity_id)
        assert identity is not None
        assert identity.agent_id == agent_id
        assert identity.identity_id == identity_id

    @pytest.mark.asyncio
    async def test_get_identity_by_id_returns_none_for_missing(self, backend):
        """get_identity_by_id should return None for nonexistent rowid."""
        result = await backend.get_identity_by_id(999999)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_identities_empty(self, backend):
        """list_identities should return empty list on fresh database."""
        result = await backend.list_identities()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_identities_returns_all(self, backend):
        """list_identities should return all identities."""
        ids = [_make_agent_id() for _ in range(3)]
        for aid in ids:
            await backend.upsert_identity(aid, f"key-{aid}")
        result = await backend.list_identities()
        assert len(result) == 3
        returned_ids = {r.agent_id for r in result}
        assert returned_ids == set(ids)

    @pytest.mark.asyncio
    async def test_list_identities_filter_by_status(self, backend):
        """list_identities should filter by status."""
        active_id = _make_agent_id()
        disabled_id = _make_agent_id()
        await backend.upsert_identity(active_id, "key1")
        await backend.upsert_identity(disabled_id, "key2")
        await backend.update_identity_status(disabled_id, "disabled")

        active_only = await backend.list_identities(status="active")
        assert len(active_only) == 1
        assert active_only[0].agent_id == active_id

        disabled_only = await backend.list_identities(status="disabled")
        assert len(disabled_only) == 1
        assert disabled_only[0].agent_id == disabled_id

    @pytest.mark.asyncio
    async def test_list_identities_limit_and_offset(self, backend):
        """list_identities should respect limit and offset."""
        ids = [_make_agent_id() for _ in range(5)]
        for aid in ids:
            await backend.upsert_identity(aid, f"key-{aid}")

        page1 = await backend.list_identities(limit=2, offset=0)
        assert len(page1) == 2

        page2 = await backend.list_identities(limit=2, offset=2)
        assert len(page2) == 2

        page3 = await backend.list_identities(limit=2, offset=4)
        assert len(page3) == 1

    @pytest.mark.asyncio
    async def test_update_identity_status(self, backend):
        """update_identity_status should change the status field."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1")
        result = await backend.update_identity_status(agent_id, "disabled")
        assert result is True

        identity = await backend.get_identity(agent_id)
        assert identity.status == "disabled"

    @pytest.mark.asyncio
    async def test_update_identity_status_with_disabled_at(self, backend):
        """update_identity_status should set disabled_at datetime."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1")
        disabled_time = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        await backend.update_identity_status(agent_id, "disabled", disabled_at=disabled_time)

        identity = await backend.get_identity(agent_id)
        assert identity.disabled_at is not None
        assert identity.disabled_at.year == 2025

    @pytest.mark.asyncio
    async def test_update_identity_status_nonexistent(self, backend):
        """update_identity_status should return False for nonexistent agent."""
        result = await backend.update_identity_status("nonexistent", "disabled")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_identity_metadata_merge(self, backend):
        """update_identity_metadata with merge=True should merge with existing."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1", metadata={"a": 1, "b": 2})
        result = await backend.update_identity_metadata(agent_id, {"b": 3, "c": 4}, merge=True)
        assert result is True

        identity = await backend.get_identity(agent_id)
        assert identity.metadata["a"] == 1
        assert identity.metadata["b"] == 3  # Updated
        assert identity.metadata["c"] == 4  # Added

    @pytest.mark.asyncio
    async def test_update_identity_metadata_replace(self, backend):
        """update_identity_metadata with merge=False should replace entirely."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1", metadata={"a": 1, "b": 2})
        result = await backend.update_identity_metadata(agent_id, {"x": 99}, merge=False)
        assert result is True

        identity = await backend.get_identity(agent_id)
        assert identity.metadata == {"x": 99}

    @pytest.mark.asyncio
    async def test_update_identity_metadata_nonexistent(self, backend):
        """update_identity_metadata should return False for nonexistent agent."""
        result = await backend.update_identity_metadata("nonexistent", {"a": 1})
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_api_key_raw_match(self, backend):
        """verify_api_key should match raw key when stored as plain text."""
        agent_id = _make_agent_id()
        api_key = "my-secret-key"
        await backend.upsert_identity(agent_id, api_key)
        assert await backend.verify_api_key(agent_id, api_key) is True

    @pytest.mark.asyncio
    async def test_verify_api_key_hash_match(self, backend):
        """verify_api_key should match when stored key is sha256 hash of provided key."""
        agent_id = _make_agent_id()
        api_key = "my-secret-key"
        hashed = hashlib.sha256(api_key.encode()).hexdigest()
        await backend.upsert_identity(agent_id, hashed)
        assert await backend.verify_api_key(agent_id, api_key) is True

    @pytest.mark.asyncio
    async def test_verify_api_key_wrong_key(self, backend):
        """verify_api_key should return False for wrong key."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "correct-key")
        assert await backend.verify_api_key(agent_id, "wrong-key") is False

    @pytest.mark.asyncio
    async def test_verify_api_key_nonexistent_agent(self, backend):
        """verify_api_key should return False for nonexistent agent."""
        assert await backend.verify_api_key("nonexistent", "any-key") is False


# ---------------------------------------------------------------------------
# AGENT OPERATIONS (upsert_agent, update_agent_fields, labels)
# ---------------------------------------------------------------------------


class TestAgentOperations:
    """Tests for upsert_agent, update_agent_fields, get_agent_label, find_agent_by_label."""

    @pytest.mark.asyncio
    async def test_upsert_agent_is_noop(self, backend):
        """upsert_agent should be a no-op returning True (SQLite-only behavior)."""
        result = await backend.upsert_agent(_make_agent_id(), "key")
        assert result is True

    @pytest.mark.asyncio
    async def test_update_agent_fields_status(self, backend):
        """update_agent_fields should update the status column."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1")
        result = await backend.update_agent_fields(agent_id, status="archived")
        assert result is True

        identity = await backend.get_identity(agent_id)
        assert identity.status == "archived"

    @pytest.mark.asyncio
    async def test_update_agent_fields_tags(self, backend):
        """update_agent_fields should update tags_json."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1")
        await backend.update_agent_fields(agent_id, tags=["tag1", "tag2"])

        conn = backend._get_conn()
        row = conn.execute(
            "SELECT tags_json FROM agent_metadata WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        tags = json.loads(row["tags_json"])
        assert tags == ["tag1", "tag2"]

    @pytest.mark.asyncio
    async def test_update_agent_fields_metadata_fields(self, backend):
        """update_agent_fields should store purpose/notes/label in metadata_json."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1")
        await backend.update_agent_fields(
            agent_id,
            purpose="testing",
            notes="test notes",
            label="TestBot",
        )

        identity = await backend.get_identity(agent_id)
        assert identity.metadata["purpose"] == "testing"
        assert identity.metadata["notes"] == "test notes"
        assert identity.metadata["label"] == "TestBot"

    @pytest.mark.asyncio
    async def test_update_agent_fields_parent_and_spawn_reason(self, backend):
        """update_agent_fields should update parent_agent_id and spawn_reason."""
        agent_id = _make_agent_id()
        parent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1")
        await backend.update_agent_fields(
            agent_id,
            parent_agent_id=parent_id,
            spawn_reason="test spawn",
        )

        identity = await backend.get_identity(agent_id)
        assert identity.parent_agent_id == parent_id
        assert identity.spawn_reason == "test spawn"

    @pytest.mark.asyncio
    async def test_update_agent_fields_nonexistent(self, backend):
        """update_agent_fields should return False for nonexistent agent."""
        result = await backend.update_agent_fields("nonexistent", status="active")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_agent_label(self, backend):
        """get_agent_label should return label from metadata_json."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1", metadata={"label": "MyBot"})
        label = await backend.get_agent_label(agent_id)
        assert label == "MyBot"

    @pytest.mark.asyncio
    async def test_get_agent_label_no_label(self, backend):
        """get_agent_label should return None if no label set."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1")
        label = await backend.get_agent_label(agent_id)
        assert label is None

    @pytest.mark.asyncio
    async def test_get_agent_label_nonexistent(self, backend):
        """get_agent_label should return None for nonexistent agent."""
        label = await backend.get_agent_label("nonexistent")
        assert label is None

    @pytest.mark.asyncio
    async def test_find_agent_by_label(self, backend):
        """find_agent_by_label should find the agent UUID by label."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1", metadata={"label": "UniqueLabel"})
        found = await backend.find_agent_by_label("UniqueLabel")
        assert found == agent_id

    @pytest.mark.asyncio
    async def test_find_agent_by_label_not_found(self, backend):
        """find_agent_by_label should return None when no agent has the label."""
        result = await backend.find_agent_by_label("NonexistentLabel")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_agent_by_label_among_many(self, backend):
        """find_agent_by_label should find the correct one among multiple agents."""
        ids = [_make_agent_id() for _ in range(3)]
        labels = ["Alpha", "Beta", "Gamma"]
        for aid, lab in zip(ids, labels):
            await backend.upsert_identity(aid, f"key-{aid}", metadata={"label": lab})

        assert await backend.find_agent_by_label("Beta") == ids[1]
        assert await backend.find_agent_by_label("Gamma") == ids[2]


# ---------------------------------------------------------------------------
# SESSION OPERATIONS
# ---------------------------------------------------------------------------


class TestSessionOperations:
    """Tests for create_session, get_session, end_session, etc."""

    async def _create_agent_and_get_identity_id(self, backend):
        """Helper to create an agent and return its identity_id (rowid)."""
        agent_id = _make_agent_id()
        identity_id = await backend.upsert_identity(agent_id, "key1")
        return agent_id, identity_id

    @pytest.mark.asyncio
    async def test_create_session(self, backend):
        """create_session should return True for valid identity."""
        agent_id, identity_id = await self._create_agent_and_get_identity_id(backend)
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        result = await backend.create_session(session_id, identity_id, expires)
        assert result is True

    @pytest.mark.asyncio
    async def test_create_session_with_client_info(self, backend):
        """create_session should store client_type and client_info."""
        agent_id, identity_id = await self._create_agent_and_get_identity_id(backend)
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        client_info = {"ip": "127.0.0.1", "user_agent": "test"}
        result = await backend.create_session(
            session_id, identity_id, expires,
            client_type="cli", client_info=client_info,
        )
        assert result is True

        session = await backend.get_session(session_id)
        assert session is not None
        assert session.client_type == "cli"
        assert session.client_info["ip"] == "127.0.0.1"

    @pytest.mark.asyncio
    async def test_create_session_invalid_identity(self, backend):
        """create_session should return False for invalid identity_id."""
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        result = await backend.create_session(session_id, 999999, expires)
        assert result is False

    @pytest.mark.asyncio
    async def test_create_session_duplicate_id(self, backend):
        """create_session should return False for duplicate session_id."""
        agent_id, identity_id = await self._create_agent_and_get_identity_id(backend)
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        await backend.create_session(session_id, identity_id, expires)
        result = await backend.create_session(session_id, identity_id, expires)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_session(self, backend):
        """get_session should return a properly populated SessionRecord."""
        agent_id, identity_id = await self._create_agent_and_get_identity_id(backend)
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        await backend.create_session(session_id, identity_id, expires)

        session = await backend.get_session(session_id)
        assert isinstance(session, SessionRecord)
        assert session.session_id == session_id
        assert session.agent_id == agent_id
        assert session.identity_id == identity_id
        assert session.is_active is True
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.expires_at, datetime)

    @pytest.mark.asyncio
    async def test_get_session_nonexistent(self, backend):
        """get_session should return None for nonexistent session."""
        result = await backend.get_session("nonexistent-session")
        assert result is None

    @pytest.mark.asyncio
    async def test_end_session(self, backend):
        """end_session should mark session as inactive."""
        agent_id, identity_id = await self._create_agent_and_get_identity_id(backend)
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        await backend.create_session(session_id, identity_id, expires)

        result = await backend.end_session(session_id)
        assert result is True

        session = await backend.get_session(session_id)
        assert session.is_active is False

    @pytest.mark.asyncio
    async def test_end_session_nonexistent(self, backend):
        """end_session should return False for nonexistent session."""
        result = await backend.end_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_active_sessions_for_identity(self, backend):
        """get_active_sessions_for_identity should return only active sessions."""
        agent_id, identity_id = await self._create_agent_and_get_identity_id(backend)
        expires = datetime.now(timezone.utc) + timedelta(hours=24)

        sess1 = f"sess-{uuid.uuid4().hex[:8]}"
        sess2 = f"sess-{uuid.uuid4().hex[:8]}"
        sess3 = f"sess-{uuid.uuid4().hex[:8]}"

        await backend.create_session(sess1, identity_id, expires)
        await backend.create_session(sess2, identity_id, expires)
        await backend.create_session(sess3, identity_id, expires)
        await backend.end_session(sess2)  # Deactivate one

        active = await backend.get_active_sessions_for_identity(identity_id)
        active_ids = {s.session_id for s in active}
        assert sess1 in active_ids
        assert sess2 not in active_ids
        assert sess3 in active_ids

    @pytest.mark.asyncio
    async def test_get_active_sessions_for_invalid_identity(self, backend):
        """get_active_sessions_for_identity should return [] for invalid identity."""
        result = await backend.get_active_sessions_for_identity(999999)
        assert result == []

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, backend):
        """cleanup_expired_sessions should delete sessions with past expires_at."""
        agent_id, identity_id = await self._create_agent_and_get_identity_id(backend)

        # Insert an expired session directly using SQLite datetime format
        # (cleanup_expired_sessions compares with datetime('now') which uses
        # SQLite-native format YYYY-MM-DD HH:MM:SS, not ISO 8601 with T and tz)
        conn = backend._get_conn()
        expired_sess = f"sess-expired-{uuid.uuid4().hex[:8]}"
        conn.execute(
            """INSERT INTO session_identities
               (session_id, agent_id, created_at, last_active, expires_at, is_active)
               VALUES (?, ?, datetime('now'), datetime('now'), datetime('now', '-1 hour'), 1)""",
            (expired_sess, agent_id),
        )
        conn.commit()

        # Create one session still valid using the same native format
        valid_sess = f"sess-valid-{uuid.uuid4().hex[:8]}"
        conn.execute(
            """INSERT INTO session_identities
               (session_id, agent_id, created_at, last_active, expires_at, is_active)
               VALUES (?, ?, datetime('now'), datetime('now'), datetime('now', '+24 hours'), 1)""",
            (valid_sess, agent_id),
        )
        conn.commit()

        deleted = await backend.cleanup_expired_sessions()
        assert deleted >= 1

        # Expired session should be gone
        row = conn.execute(
            "SELECT session_id FROM session_identities WHERE session_id = ?",
            (expired_sess,),
        ).fetchone()
        assert row is None

        # Valid session should remain
        row = conn.execute(
            "SELECT session_id FROM session_identities WHERE session_id = ?",
            (valid_sess,),
        ).fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# AGENT STATE OPERATIONS
# ---------------------------------------------------------------------------


class TestAgentStateOperations:
    """Tests for record_agent_state, get_latest, get_history."""

    async def _create_agent(self, backend):
        """Helper to create an agent and return (agent_id, identity_id)."""
        agent_id = _make_agent_id()
        identity_id = await backend.upsert_identity(agent_id, "key1")
        return agent_id, identity_id

    @pytest.mark.asyncio
    async def test_record_agent_state(self, backend):
        """record_agent_state should insert a state row and return state_id > 0."""
        agent_id, identity_id = await self._create_agent(backend)
        state_id = await backend.record_agent_state(
            identity_id=identity_id,
            entropy=0.3,
            integrity=0.8,
            stability_index=0.6,
            volatility=0.15,
            regime="nominal",
            coherence=0.95,
        )
        assert state_id > 0

    @pytest.mark.asyncio
    async def test_record_agent_state_with_state_json(self, backend):
        """record_agent_state should store state_json."""
        agent_id, identity_id = await self._create_agent(backend)
        extra = {"proprioceptive_margin": 0.42, "custom_field": "hello"}
        state_id = await backend.record_agent_state(
            identity_id=identity_id,
            entropy=0.5, integrity=0.5, stability_index=0.5,
            volatility=0.1, regime="nominal", coherence=1.0,
            state_json=extra,
        )
        assert state_id > 0

        state = await backend.get_latest_agent_state(identity_id)
        assert state.state_json["proprioceptive_margin"] == 0.42
        assert state.state_json["custom_field"] == "hello"

    @pytest.mark.asyncio
    async def test_record_agent_state_invalid_identity(self, backend):
        """record_agent_state should return 0 for invalid identity_id."""
        state_id = await backend.record_agent_state(
            identity_id=999999,
            entropy=0.5, integrity=0.5, stability_index=0.5,
            volatility=0.1, regime="nominal", coherence=1.0,
        )
        assert state_id == 0

    @pytest.mark.asyncio
    async def test_get_latest_agent_state(self, backend):
        """get_latest_agent_state should return the most recent state."""
        agent_id, identity_id = await self._create_agent(backend)

        # Record two states
        await backend.record_agent_state(
            identity_id=identity_id,
            entropy=0.3, integrity=0.7, stability_index=0.5,
            volatility=0.1, regime="nominal", coherence=0.9,
        )
        await backend.record_agent_state(
            identity_id=identity_id,
            entropy=0.8, integrity=0.2, stability_index=0.3,
            volatility=0.5, regime="critical", coherence=0.4,
        )

        latest = await backend.get_latest_agent_state(identity_id)
        assert isinstance(latest, AgentStateRecord)
        assert latest.entropy == 0.8
        assert latest.integrity == 0.2
        assert latest.regime == "critical"
        assert latest.coherence == 0.4

    @pytest.mark.asyncio
    async def test_get_latest_agent_state_no_states(self, backend):
        """get_latest_agent_state should return None if no states recorded."""
        agent_id, identity_id = await self._create_agent(backend)
        result = await backend.get_latest_agent_state(identity_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_agent_state_invalid_identity(self, backend):
        """get_latest_agent_state should return None for invalid identity."""
        result = await backend.get_latest_agent_state(999999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_agent_state_history(self, backend):
        """get_agent_state_history should return states in reverse chronological order."""
        agent_id, identity_id = await self._create_agent(backend)

        for i in range(5):
            await backend.record_agent_state(
                identity_id=identity_id,
                entropy=i * 0.1, integrity=0.5, stability_index=0.5,
                volatility=0.1, regime="nominal", coherence=1.0,
            )

        history = await backend.get_agent_state_history(identity_id)
        assert len(history) == 5
        # All should have the same agent_id
        for state in history:
            assert state.agent_id == agent_id

    @pytest.mark.asyncio
    async def test_get_agent_state_history_with_limit(self, backend):
        """get_agent_state_history should respect limit parameter."""
        agent_id, identity_id = await self._create_agent(backend)

        for i in range(10):
            await backend.record_agent_state(
                identity_id=identity_id,
                entropy=i * 0.1, integrity=0.5, stability_index=0.5,
                volatility=0.1, regime="nominal", coherence=1.0,
            )

        history = await backend.get_agent_state_history(identity_id, limit=3)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_get_agent_state_history_invalid_identity(self, backend):
        """get_agent_state_history should return [] for invalid identity."""
        result = await backend.get_agent_state_history(999999)
        assert result == []

    @pytest.mark.asyncio
    async def test_agent_state_record_fields(self, backend):
        """AgentStateRecord should have all EISV fields populated correctly."""
        agent_id, identity_id = await self._create_agent(backend)
        await backend.record_agent_state(
            identity_id=identity_id,
            entropy=0.33,
            integrity=0.77,
            stability_index=0.55,
            volatility=0.22,
            regime="elevated",
            coherence=0.88,
            state_json={"test": True},
        )
        state = await backend.get_latest_agent_state(identity_id)
        assert state.entropy == 0.33
        assert state.integrity == 0.77
        assert state.stability_index == 0.55
        assert state.volatility == 0.22
        assert state.regime == "elevated"
        assert state.coherence == 0.88
        assert state.state_json == {"test": True}
        assert state.identity_id == identity_id
        assert state.agent_id == agent_id
        assert isinstance(state.recorded_at, datetime)


# ---------------------------------------------------------------------------
# AUDIT OPERATIONS
# ---------------------------------------------------------------------------


class TestAuditOperations:
    """Tests for append_audit_event, query_audit_events, search_audit_events."""

    def _make_event(
        self,
        agent_id=None,
        event_type="test_event",
        confidence=1.0,
        payload=None,
        raw_hash=None,
        event_id=None,
        session_id=None,
        ts=None,
    ):
        """Helper to construct an AuditEvent."""
        return AuditEvent(
            ts=ts or datetime.now(timezone.utc),
            event_id=event_id or str(uuid.uuid4()),
            event_type=event_type,
            agent_id=agent_id,
            session_id=session_id,
            confidence=confidence,
            payload=payload or {},
            raw_hash=raw_hash or uuid.uuid4().hex,
        )

    @pytest.mark.asyncio
    async def test_append_audit_event(self, backend):
        """append_audit_event should return True on success."""
        event = self._make_event(agent_id="agent-1")
        result = await backend.append_audit_event(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_append_audit_event_preserves_event_id_in_payload(self, backend):
        """append_audit_event should store event_id in details_json."""
        event = self._make_event(
            agent_id="agent-1",
            event_id="custom-event-id",
            session_id="custom-session-id",
        )
        await backend.append_audit_event(event)
        events = await backend.query_audit_events(agent_id="agent-1")
        assert len(events) == 1
        assert events[0].event_id == "custom-event-id"
        assert events[0].session_id == "custom-session-id"

    @pytest.mark.asyncio
    async def test_append_audit_event_duplicate_hash_ignored(self, backend):
        """append_audit_event with duplicate raw_hash should be silently ignored."""
        hash_val = "unique_hash_123"
        event1 = self._make_event(agent_id="agent-1", raw_hash=hash_val)
        event2 = self._make_event(agent_id="agent-2", raw_hash=hash_val)
        assert await backend.append_audit_event(event1) is True
        assert await backend.append_audit_event(event2) is True  # INSERT OR IGNORE

        events = await backend.query_audit_events()
        assert len(events) == 1  # Only the first was inserted

    @pytest.mark.asyncio
    async def test_query_audit_events_no_filter(self, backend):
        """query_audit_events with no filters should return all events."""
        for i in range(3):
            await backend.append_audit_event(self._make_event(
                agent_id=f"agent-{i}",
                event_type=f"type_{i}",
            ))
        events = await backend.query_audit_events()
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_query_audit_events_by_agent_id(self, backend):
        """query_audit_events should filter by agent_id."""
        await backend.append_audit_event(self._make_event(agent_id="agent-A"))
        await backend.append_audit_event(self._make_event(agent_id="agent-B"))
        await backend.append_audit_event(self._make_event(agent_id="agent-A"))

        events = await backend.query_audit_events(agent_id="agent-A")
        assert len(events) == 2
        assert all(e.agent_id == "agent-A" for e in events)

    @pytest.mark.asyncio
    async def test_query_audit_events_by_event_type(self, backend):
        """query_audit_events should filter by event_type."""
        await backend.append_audit_event(self._make_event(event_type="login"))
        await backend.append_audit_event(self._make_event(event_type="logout"))
        await backend.append_audit_event(self._make_event(event_type="login"))

        events = await backend.query_audit_events(event_type="login")
        assert len(events) == 2
        assert all(e.event_type == "login" for e in events)

    @pytest.mark.asyncio
    async def test_query_audit_events_by_time_range(self, backend):
        """query_audit_events should filter by start_time and end_time."""
        t1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2025, 6, 1, tzinfo=timezone.utc)
        t3 = datetime(2025, 12, 1, tzinfo=timezone.utc)

        await backend.append_audit_event(self._make_event(ts=t1))
        await backend.append_audit_event(self._make_event(ts=t2))
        await backend.append_audit_event(self._make_event(ts=t3))

        start = datetime(2025, 3, 1, tzinfo=timezone.utc)
        end = datetime(2025, 9, 1, tzinfo=timezone.utc)
        events = await backend.query_audit_events(start_time=start, end_time=end)
        assert len(events) == 1
        assert events[0].ts.month == 6

    @pytest.mark.asyncio
    async def test_query_audit_events_order_asc(self, backend):
        """query_audit_events with order='asc' should return oldest first."""
        t1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2025, 6, 1, tzinfo=timezone.utc)
        await backend.append_audit_event(self._make_event(ts=t2))
        await backend.append_audit_event(self._make_event(ts=t1))

        events = await backend.query_audit_events(order="asc")
        assert events[0].ts < events[1].ts

    @pytest.mark.asyncio
    async def test_query_audit_events_order_desc(self, backend):
        """query_audit_events with order='desc' should return newest first."""
        t1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2025, 6, 1, tzinfo=timezone.utc)
        await backend.append_audit_event(self._make_event(ts=t1))
        await backend.append_audit_event(self._make_event(ts=t2))

        events = await backend.query_audit_events(order="desc")
        assert events[0].ts > events[1].ts

    @pytest.mark.asyncio
    async def test_query_audit_events_limit(self, backend):
        """query_audit_events should respect limit parameter."""
        for i in range(10):
            await backend.append_audit_event(self._make_event())
        events = await backend.query_audit_events(limit=3)
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_query_audit_event_payload_preserved(self, backend):
        """Payload data (excluding _event_id/_session_id) should be preserved."""
        payload = {"action": "login", "details": {"ip": "1.2.3.4"}}
        event = self._make_event(agent_id="agent-1", payload=payload)
        await backend.append_audit_event(event)

        events = await backend.query_audit_events(agent_id="agent-1")
        assert events[0].payload["action"] == "login"
        assert events[0].payload["details"]["ip"] == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_search_audit_events(self, backend):
        """search_audit_events should find events by text in details_json."""
        await backend.append_audit_event(self._make_event(
            agent_id="agent-1",
            payload={"message": "user logged in from mobile"},
        ))
        await backend.append_audit_event(self._make_event(
            agent_id="agent-2",
            payload={"message": "config updated"},
        ))

        results = await backend.search_audit_events("mobile")
        assert len(results) == 1
        assert results[0].agent_id == "agent-1"

    @pytest.mark.asyncio
    async def test_search_audit_events_with_agent_filter(self, backend):
        """search_audit_events should combine text search with agent_id filter."""
        await backend.append_audit_event(self._make_event(
            agent_id="agent-1", payload={"msg": "hello world"},
        ))
        await backend.append_audit_event(self._make_event(
            agent_id="agent-2", payload={"msg": "hello world"},
        ))

        results = await backend.search_audit_events("hello", agent_id="agent-1")
        assert len(results) == 1
        assert results[0].agent_id == "agent-1"

    @pytest.mark.asyncio
    async def test_search_audit_events_no_match(self, backend):
        """search_audit_events should return [] when nothing matches."""
        await backend.append_audit_event(self._make_event(payload={"msg": "foo"}))
        results = await backend.search_audit_events("nonexistent_string")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_audit_events_limit(self, backend):
        """search_audit_events should respect limit."""
        for i in range(10):
            await backend.append_audit_event(self._make_event(
                payload={"msg": "repeated pattern"},
            ))
        results = await backend.search_audit_events("repeated", limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_audit_event_with_empty_payload(self, backend):
        """AuditEvent with empty payload should not cause errors."""
        event = AuditEvent(
            ts=datetime.now(timezone.utc),
            event_id="test-evt",
            event_type="test",
            agent_id="agent-1",
            payload={},
            raw_hash="hash_empty_payload",
        )
        assert await backend.append_audit_event(event) is True
        events = await backend.query_audit_events(agent_id="agent-1")
        assert len(events) == 1


# ---------------------------------------------------------------------------
# CALIBRATION OPERATIONS
# ---------------------------------------------------------------------------


class TestCalibrationOperations:
    """Tests for get_calibration and update_calibration."""

    @pytest.mark.asyncio
    async def test_get_calibration_default(self, backend):
        """get_calibration should return default calibration after init."""
        cal = await backend.get_calibration()
        assert cal["lambda1_threshold"] == 0.3
        assert cal["lambda2_threshold"] == 0.7
        assert "_updated_at" in cal
        assert "_version" in cal

    @pytest.mark.asyncio
    async def test_update_calibration(self, backend):
        """update_calibration should replace calibration data."""
        new_data = {"lambda1_threshold": 0.5, "lambda2_threshold": 0.9, "custom": 42}
        result = await backend.update_calibration(new_data)
        assert result is True

        cal = await backend.get_calibration()
        assert cal["lambda1_threshold"] == 0.5
        assert cal["lambda2_threshold"] == 0.9
        assert cal["custom"] == 42

    @pytest.mark.asyncio
    async def test_update_calibration_strips_internal_keys(self, backend):
        """update_calibration should strip keys starting with _ before saving."""
        new_data = {"threshold": 0.5, "_updated_at": "should-be-ignored", "_version": 999}
        await backend.update_calibration(new_data)

        cal = await backend.get_calibration()
        assert cal["threshold"] == 0.5
        # _updated_at and _version should be system-generated, not our values
        assert cal["_version"] is not None

    @pytest.mark.asyncio
    async def test_update_calibration_increments_version(self, backend):
        """Each update_calibration call should increment the version."""
        cal1 = await backend.get_calibration()
        v1 = cal1["_version"]

        await backend.update_calibration({"new_key": "value1"})
        cal2 = await backend.get_calibration()
        v2 = cal2["_version"]

        await backend.update_calibration({"new_key": "value2"})
        cal3 = await backend.get_calibration()
        v3 = cal3["_version"]

        assert v2 == v1 + 1
        assert v3 == v2 + 1

    @pytest.mark.asyncio
    async def test_update_calibration_updates_timestamp(self, backend):
        """update_calibration should update the updated_at timestamp."""
        cal_before = await backend.get_calibration()
        await backend.update_calibration({"x": 1})
        cal_after = await backend.get_calibration()
        assert cal_after["_updated_at"] >= cal_before["_updated_at"]


# ---------------------------------------------------------------------------
# TOOL USAGE OPERATIONS
# ---------------------------------------------------------------------------


class TestToolUsageOperations:
    """Tests for append_tool_usage and query_tool_usage."""

    @pytest.mark.asyncio
    async def test_append_tool_usage_success(self, backend):
        """append_tool_usage should return True on success."""
        result = await backend.append_tool_usage(
            agent_id="agent-1",
            session_id="sess-1",
            tool_name="process_agent_update",
            latency_ms=150,
            success=True,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_append_tool_usage_with_error(self, backend):
        """append_tool_usage should store error information."""
        await backend.append_tool_usage(
            agent_id="agent-1",
            session_id="sess-1",
            tool_name="broken_tool",
            latency_ms=500,
            success=False,
            error_type="TimeoutError",
            payload={"details": "connection timed out"},
        )

        results = await backend.query_tool_usage(agent_id="agent-1")
        assert len(results) == 1
        assert results[0]["success"] is False
        assert results[0]["error_type"] == "TimeoutError"
        assert results[0]["payload"]["details"] == "connection timed out"

    @pytest.mark.asyncio
    async def test_append_tool_usage_none_agent(self, backend):
        """append_tool_usage should work with None agent_id and session_id."""
        result = await backend.append_tool_usage(
            agent_id=None,
            session_id=None,
            tool_name="anonymous_tool",
            latency_ms=10,
            success=True,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_query_tool_usage_no_filters(self, backend):
        """query_tool_usage with no filters should return all usage records."""
        for i in range(3):
            await backend.append_tool_usage(
                agent_id=f"agent-{i}",
                session_id=None,
                tool_name=f"tool_{i}",
                latency_ms=i * 100,
                success=True,
            )
        results = await backend.query_tool_usage()
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_query_tool_usage_by_agent(self, backend):
        """query_tool_usage should filter by agent_id."""
        await backend.append_tool_usage("agent-A", None, "tool1", 10, True)
        await backend.append_tool_usage("agent-B", None, "tool2", 20, True)
        await backend.append_tool_usage("agent-A", None, "tool3", 30, True)

        results = await backend.query_tool_usage(agent_id="agent-A")
        assert len(results) == 2
        assert all(r["agent_id"] == "agent-A" for r in results)

    @pytest.mark.asyncio
    async def test_query_tool_usage_by_tool_name(self, backend):
        """query_tool_usage should filter by tool_name."""
        await backend.append_tool_usage("agent-1", None, "onboard", 10, True)
        await backend.append_tool_usage("agent-1", None, "status", 20, True)
        await backend.append_tool_usage("agent-2", None, "onboard", 15, True)

        results = await backend.query_tool_usage(tool_name="onboard")
        assert len(results) == 2
        assert all(r["tool_name"] == "onboard" for r in results)

    @pytest.mark.asyncio
    async def test_query_tool_usage_by_time_range(self, backend):
        """query_tool_usage should filter by start_time and end_time."""
        await backend.append_tool_usage("agent-1", None, "tool1", 10, True)

        now = datetime.now(timezone.utc)
        results = await backend.query_tool_usage(
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(minutes=1),
        )
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_query_tool_usage_limit(self, backend):
        """query_tool_usage should respect limit parameter."""
        for i in range(10):
            await backend.append_tool_usage("agent-1", None, f"tool_{i}", i, True)
        results = await backend.query_tool_usage(limit=5)
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_query_tool_usage_result_fields(self, backend):
        """query_tool_usage results should have all expected fields."""
        await backend.append_tool_usage(
            agent_id="agent-1",
            session_id="sess-1",
            tool_name="my_tool",
            latency_ms=42,
            success=True,
            payload={"key": "value"},
        )

        results = await backend.query_tool_usage()
        assert len(results) == 1
        r = results[0]
        assert isinstance(r["ts"], datetime)
        assert r["usage_id"] is not None
        assert r["agent_id"] == "agent-1"
        assert r["session_id"] == "sess-1"
        assert r["tool_name"] == "my_tool"
        assert r["latency_ms"] == 42
        assert r["success"] is True
        assert r["payload"] == {"key": "value"}


# ---------------------------------------------------------------------------
# ASYNC WRAPPING
# ---------------------------------------------------------------------------


class TestAsyncWrap:
    """Tests for _run_sync with DB_SQLITE_ASYNC_WRAP=true."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="SQLite check_same_thread=True prevents cross-thread access via asyncio.to_thread; "
               "get_identity uses _run_sync which calls to_thread when async_wrap is enabled",
        strict=True,
    )
    async def test_get_identity_with_async_wrap(self, backend_async_wrap):
        """Basic identity operations should work with async wrapping enabled.

        Note: This is expected to fail because SQLite connections cannot be
        used across threads without check_same_thread=False. The async_wrap
        feature is designed for use cases where the connection is created in
        the worker thread, not the main event loop thread.
        """
        agent_id = _make_agent_id()
        identity_id = await backend_async_wrap.upsert_identity(agent_id, "key1")
        assert identity_id > 0

        identity = await backend_async_wrap.get_identity(agent_id)
        assert identity is not None
        assert identity.agent_id == agent_id

    @pytest.mark.asyncio
    async def test_async_wrap_flag_set(self, backend_async_wrap):
        """Verify the _async_wrap flag is set to True."""
        assert backend_async_wrap._async_wrap is True

    @pytest.mark.asyncio
    async def test_async_wrap_env_var_parsing(self, tmp_path):
        """DB_SQLITE_ASYNC_WRAP should be parsed as boolean from env."""
        db_path = tmp_path / "wrap_test.db"
        os.environ["DB_SQLITE_PATH"] = str(db_path)

        # "true" => True
        os.environ["DB_SQLITE_ASYNC_WRAP"] = "true"
        b1 = SQLiteBackend()
        assert b1._async_wrap is True

        # "false" => False
        os.environ["DB_SQLITE_ASYNC_WRAP"] = "false"
        b2 = SQLiteBackend()
        assert b2._async_wrap is False

        # "True" (uppercase) => False (only "true" lowercase matches)
        os.environ["DB_SQLITE_ASYNC_WRAP"] = "True"
        b3 = SQLiteBackend()
        # Source checks .lower() == "true", so "True" lowered == "true" => True
        assert b3._async_wrap is True

        os.environ.pop("DB_SQLITE_PATH", None)
        os.environ.pop("DB_SQLITE_ASYNC_WRAP", None)


# ---------------------------------------------------------------------------
# _run_sync INTERNAL
# ---------------------------------------------------------------------------


class TestRunSync:
    """Tests for the _run_sync helper method."""

    @pytest.mark.asyncio
    async def test_run_sync_direct(self, backend):
        """Without async wrapping, _run_sync should call the function directly."""
        assert backend._async_wrap is False
        result = await backend._run_sync(lambda: 42)
        assert result == 42

    @pytest.mark.asyncio
    async def test_run_sync_with_args(self, backend):
        """_run_sync should pass positional and keyword args."""
        def add(a, b, extra=0):
            return a + b + extra
        result = await backend._run_sync(add, 1, 2, extra=10)
        assert result == 13

    @pytest.mark.asyncio
    async def test_run_sync_async_wrap(self, backend_async_wrap):
        """With async wrapping, _run_sync should use asyncio.to_thread."""
        result = await backend_async_wrap._run_sync(lambda: 99)
        assert result == 99


# ---------------------------------------------------------------------------
# DIALECTIC OPERATIONS (stub-level)
# ---------------------------------------------------------------------------


class TestDialecticStubs:
    """Test that dialectic methods exist and the SQLite-only stub returns correctly."""

    @pytest.mark.asyncio
    async def test_get_pending_dialectic_sessions_returns_empty(self, backend):
        """get_pending_dialectic_sessions should return [] (SQLite-only behavior)."""
        result = await backend.get_pending_dialectic_sessions()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_pending_dialectic_sessions_ignores_limit(self, backend):
        """get_pending_dialectic_sessions ignores limit and always returns []."""
        result = await backend.get_pending_dialectic_sessions(limit=50)
        assert result == []


# ---------------------------------------------------------------------------
# GRAPH OPERATIONS (base class defaults)
# ---------------------------------------------------------------------------


class TestGraphOperations:
    """Test graph operations inherited from base class."""

    @pytest.mark.asyncio
    async def test_graph_available_returns_false(self, backend):
        """SQLiteBackend should report graph as unavailable."""
        assert await backend.graph_available() is False

    @pytest.mark.asyncio
    async def test_graph_query_returns_empty(self, backend):
        """graph_query should return empty list for SQLite backend."""
        result = await backend.graph_query("MATCH (n) RETURN n")
        assert result == []


# ---------------------------------------------------------------------------
# EDGE CASES AND ERROR HANDLING
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases, empty values, special characters, etc."""

    @pytest.mark.asyncio
    async def test_identity_empty_metadata(self, backend):
        """Identity with no explicit metadata should have empty dict."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1")
        identity = await backend.get_identity(agent_id)
        assert identity.metadata == {}

    @pytest.mark.asyncio
    async def test_identity_unicode_metadata(self, backend):
        """Identity metadata should handle unicode characters."""
        agent_id = _make_agent_id()
        meta = {"name": "Test Agent", "description": "Handles unicode fine"}
        await backend.upsert_identity(agent_id, "key1", metadata=meta)
        identity = await backend.get_identity(agent_id)
        assert identity.metadata["name"] == "Test Agent"

    @pytest.mark.asyncio
    async def test_audit_event_with_large_payload(self, backend):
        """Audit events with large payloads should be stored correctly."""
        large_payload = {"data": "x" * 10000, "nested": {"deep": [1, 2, 3] * 100}}
        event = AuditEvent(
            ts=datetime.now(timezone.utc),
            event_id="large-evt",
            event_type="large_payload",
            agent_id="agent-1",
            payload=large_payload,
            raw_hash="hash_large",
        )
        assert await backend.append_audit_event(event) is True

        events = await backend.query_audit_events(agent_id="agent-1")
        assert len(events) == 1
        assert len(events[0].payload["data"]) == 10000

    @pytest.mark.asyncio
    async def test_multiple_agents_state_isolation(self, backend):
        """State for one agent should not leak into another agent's queries."""
        aid1 = _make_agent_id()
        aid2 = _make_agent_id()
        iid1 = await backend.upsert_identity(aid1, "key1")
        iid2 = await backend.upsert_identity(aid2, "key2")

        await backend.record_agent_state(
            iid1, entropy=0.1, integrity=0.9, stability_index=0.5,
            volatility=0.1, regime="nominal", coherence=1.0,
        )
        await backend.record_agent_state(
            iid2, entropy=0.9, integrity=0.1, stability_index=0.5,
            volatility=0.1, regime="critical", coherence=0.3,
        )

        state1 = await backend.get_latest_agent_state(iid1)
        state2 = await backend.get_latest_agent_state(iid2)
        assert state1.entropy == 0.1
        assert state1.regime == "nominal"
        assert state2.entropy == 0.9
        assert state2.regime == "critical"

    @pytest.mark.asyncio
    async def test_session_across_agents(self, backend):
        """Sessions should be correctly associated with their respective agents."""
        aid1 = _make_agent_id()
        aid2 = _make_agent_id()
        iid1 = await backend.upsert_identity(aid1, "key1")
        iid2 = await backend.upsert_identity(aid2, "key2")

        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        sess1 = f"sess-{uuid.uuid4().hex[:8]}"
        sess2 = f"sess-{uuid.uuid4().hex[:8]}"

        await backend.create_session(sess1, iid1, expires)
        await backend.create_session(sess2, iid2, expires)

        s1 = await backend.get_session(sess1)
        s2 = await backend.get_session(sess2)
        assert s1.agent_id == aid1
        assert s2.agent_id == aid2

        # Active sessions for identity1 should not include identity2's sessions
        active1 = await backend.get_active_sessions_for_identity(iid1)
        active1_ids = {s.session_id for s in active1}
        assert sess1 in active1_ids
        assert sess2 not in active1_ids

    @pytest.mark.asyncio
    async def test_update_identity_metadata_empty_dict(self, backend):
        """Updating metadata with empty dict should not cause errors."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1", metadata={"a": 1})
        result = await backend.update_identity_metadata(agent_id, {}, merge=True)
        assert result is True
        identity = await backend.get_identity(agent_id)
        # Original metadata should be preserved
        assert identity.metadata.get("a") == 1

    @pytest.mark.asyncio
    async def test_tool_usage_with_none_latency(self, backend):
        """Tool usage should accept None latency_ms."""
        result = await backend.append_tool_usage(
            agent_id="agent-1",
            session_id=None,
            tool_name="fast_tool",
            latency_ms=None,
            success=True,
        )
        assert result is True

        results = await backend.query_tool_usage(agent_id="agent-1")
        assert len(results) == 1
        assert results[0]["latency_ms"] is None

    @pytest.mark.asyncio
    async def test_connection_reuse(self, backend):
        """Multiple _get_conn() calls should return the same connection."""
        conn1 = backend._get_conn()
        conn2 = backend._get_conn()
        assert conn1 is conn2

    @pytest.mark.asyncio
    async def test_health_check_after_data_operations(self, backend):
        """health_check should return correct counts after various operations."""
        # Create 2 agents
        aid1 = _make_agent_id()
        aid2 = _make_agent_id()
        iid1 = await backend.upsert_identity(aid1, "key1")
        await backend.upsert_identity(aid2, "key2")

        # Create 1 active session
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        await backend.create_session("sess-1", iid1, expires)

        # Create 3 audit events
        for i in range(3):
            await backend.append_audit_event(AuditEvent(
                ts=datetime.now(timezone.utc),
                event_id=f"evt-{i}",
                event_type="test",
                raw_hash=f"hash-{i}",
            ))

        health = await backend.health_check()
        assert health["identity_count"] == 2
        assert health["active_session_count"] == 1
        assert health["audit_event_count"] == 3

    @pytest.mark.asyncio
    async def test_audit_event_confidence_stored(self, backend):
        """AuditEvent confidence field should be stored and retrieved."""
        event = AuditEvent(
            ts=datetime.now(timezone.utc),
            event_id="conf-evt",
            event_type="test",
            confidence=0.75,
            raw_hash="hash_conf",
        )
        await backend.append_audit_event(event)
        events = await backend.query_audit_events()
        assert events[0].confidence == 0.75

    @pytest.mark.asyncio
    async def test_identity_status_default_active(self, backend):
        """Newly created identity should have status='active'."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1")
        identity = await backend.get_identity(agent_id)
        assert identity.status == "active"

    @pytest.mark.asyncio
    async def test_multiple_updates_to_same_identity(self, backend):
        """Multiple sequential updates to the same identity should all apply."""
        agent_id = _make_agent_id()
        await backend.upsert_identity(agent_id, "key1")

        await backend.update_identity_status(agent_id, "paused")
        await backend.update_identity_metadata(agent_id, {"step": 1})
        await backend.update_identity_status(agent_id, "active")
        await backend.update_identity_metadata(agent_id, {"step": 2})

        identity = await backend.get_identity(agent_id)
        assert identity.status == "active"
        assert identity.metadata["step"] == 2

    @pytest.mark.asyncio
    async def test_query_audit_combined_filters(self, backend):
        """query_audit_events should support combining agent_id and event_type filters."""
        await backend.append_audit_event(AuditEvent(
            ts=datetime.now(timezone.utc), event_id="e1", event_type="login",
            agent_id="agent-A", raw_hash="h1",
        ))
        await backend.append_audit_event(AuditEvent(
            ts=datetime.now(timezone.utc), event_id="e2", event_type="logout",
            agent_id="agent-A", raw_hash="h2",
        ))
        await backend.append_audit_event(AuditEvent(
            ts=datetime.now(timezone.utc), event_id="e3", event_type="login",
            agent_id="agent-B", raw_hash="h3",
        ))

        events = await backend.query_audit_events(agent_id="agent-A", event_type="login")
        assert len(events) == 1
        assert events[0].agent_id == "agent-A"
        assert events[0].event_type == "login"
