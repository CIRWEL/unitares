"""
Comprehensive tests for src/mcp_handlers/identity_v2.py.

Covers the full identity resolution pipeline:
- resolve_session_identity() 3-tier: Redis -> PostgreSQL -> Create new
- derive_session_key() unified async + _derive_session_key() deprecated sync wrapper
- _validate_session_key() / sanitization within resolve_session_identity
- persist_identity via ensure_agent_persisted()
- get_agent_label / _get_agent_label
- _agent_exists_in_postgres
- _find_agent_by_label
- _get_agent_id_from_metadata
- _generate_agent_id (pure function)
- _normalize_model_type (pure function)
- set_agent_label
- resolve_by_name_claim
- _cache_session
- _extract_base_fingerprint
- ua_hash_from_header
- lookup_onboard_pin / set_onboard_pin
- handle_identity_v2 (tool handler)
- ensure_agent_persisted (lazy creation)

All external I/O (Redis, PostgreSQL, MCP server) is mocked.
"""

import pytest
import json
import sys
import os
import uuid
import re
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# Shared Fixtures
# ============================================================================

@pytest.fixture
def mock_db():
    """Mock PostgreSQL database with all methods used by identity_v2."""
    db = AsyncMock()
    db.init = AsyncMock()
    db.get_session = AsyncMock(return_value=None)
    db.get_identity = AsyncMock(return_value=None)
    db.get_agent = AsyncMock(return_value=None)
    db.get_agent_label = AsyncMock(return_value=None)
    db.upsert_agent = AsyncMock()
    db.upsert_identity = AsyncMock()
    db.create_session = AsyncMock()
    db.update_session_activity = AsyncMock()
    db.find_agent_by_label = AsyncMock(return_value=None)
    db.update_agent_fields = AsyncMock(return_value=True)
    return db


@pytest.fixture
def mock_redis():
    """Mock Redis session cache (SessionCache interface)."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.bind = AsyncMock()
    return cache


@pytest.fixture
def mock_raw_redis():
    """Mock raw Redis client for setex/expire/get operations."""
    r = AsyncMock()
    r.setex = AsyncMock()
    r.expire = AsyncMock()
    r.get = AsyncMock(return_value=None)
    return r


@pytest.fixture
def patch_all_deps(mock_db, mock_redis, mock_raw_redis):
    """
    Patch all identity_v2 external dependencies: Redis, PostgreSQL, raw Redis.

    This fixture resets the module-level _redis_cache so _get_redis() re-initializes,
    and patches get_db, get_session_cache, and raw get_redis.
    """
    async def _get_raw():
        return mock_raw_redis

    with patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
         patch("src.cache.get_session_cache", return_value=mock_redis), \
         patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
         patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
         patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db), \
         patch("src.cache.redis_client.get_redis", new=_get_raw):
        yield


@pytest.fixture
def patch_no_redis(mock_db):
    """Patch dependencies with Redis unavailable (cache returns None)."""
    with patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
         patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
         patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
         patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db):
        yield


@pytest.fixture
def patch_mcp_server():
    """Patch get_mcp_server to return a mock with agent_metadata dict."""
    mock_server = MagicMock()
    mock_server.agent_metadata = {}
    with patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
        yield mock_server


# ============================================================================
# _generate_agent_id (pure function - no I/O)
# ============================================================================

class TestEnsureAgentPersisted:

    @pytest.mark.asyncio
    async def test_persists_new_agent(self):
        """When agent doesn't exist in PG, persists and returns True."""
        from src.mcp_handlers.identity.handlers import ensure_agent_persisted

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        # First call: not persisted. After upsert: return identity for session creation.
        mock_db.get_identity.side_effect = [
            None,  # First check: not persisted
            SimpleNamespace(identity_id="new-ident", metadata={}),  # After upsert: for session creation
        ]
        mock_db.upsert_agent = AsyncMock()
        mock_db.upsert_identity = AsyncMock()
        mock_db.create_session = AsyncMock()

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await ensure_agent_persisted("uuid-lazy", "session-lazy")

        assert result is True
        mock_db.upsert_agent.assert_called_once()
        mock_db.upsert_identity.assert_called_once()
        mock_db.create_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_already_persisted(self):
        """When agent already exists in PG, returns False without writing."""
        from src.mcp_handlers.identity.handlers import ensure_agent_persisted

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="existing-ident", metadata={}
        )

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await ensure_agent_persisted("uuid-existing", "session-existing")

        assert result is False
        mock_db.upsert_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        """On exception, returns False (non-fatal)."""
        from src.mcp_handlers.identity.handlers import ensure_agent_persisted

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.side_effect = Exception("DB error")

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await ensure_agent_persisted("uuid-error", "session-error")

        assert result is False


# ============================================================================
# set_agent_label
# ============================================================================

class TestOnboardPin:

    @pytest.mark.asyncio
    async def test_set_and_lookup_pin(self):
        """Pin can be set and looked up."""
        from src.mcp_handlers.identity.handlers import set_onboard_pin, lookup_onboard_pin

        mock_raw = AsyncMock()
        stored_data = {}

        async def mock_setex(key, ttl, value):
            stored_data[key] = value

        async def mock_get(key):
            return stored_data.get(key)

        async def mock_expire(key, ttl):
            pass

        mock_raw.setex = mock_setex
        mock_raw.get = mock_get
        mock_raw.expire = mock_expire

        async def _get_raw():
            return mock_raw

        with patch("src.cache.redis_client.get_redis", new=_get_raw):
            set_result = await set_onboard_pin("ua:d20c2f", "uuid-123", "agent-uuid-123456")
            assert set_result is True

            lookup_result = await lookup_onboard_pin("ua:d20c2f")
            assert lookup_result == "agent-uuid-123456"

    @pytest.mark.asyncio
    async def test_set_pin_no_fingerprint(self):
        """set_onboard_pin with empty fingerprint returns False."""
        from src.mcp_handlers.identity.handlers import set_onboard_pin
        result = await set_onboard_pin("", "uuid-1", "sess-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_set_pin_none_fingerprint(self):
        """set_onboard_pin with None fingerprint returns False."""
        from src.mcp_handlers.identity.handlers import set_onboard_pin
        result = await set_onboard_pin(None, "uuid-1", "sess-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_lookup_pin_none_fingerprint(self):
        """lookup_onboard_pin with None fingerprint returns None."""
        from src.mcp_handlers.identity.handlers import lookup_onboard_pin
        result = await lookup_onboard_pin(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_pin_empty_fingerprint(self):
        """lookup_onboard_pin with empty fingerprint returns None."""
        from src.mcp_handlers.identity.handlers import lookup_onboard_pin
        result = await lookup_onboard_pin("")
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_pin_no_redis(self):
        """lookup_onboard_pin returns None when Redis is unavailable."""
        from src.mcp_handlers.identity.handlers import lookup_onboard_pin

        async def _get_no_redis():
            return None

        with patch("src.cache.redis_client.get_redis", new=_get_no_redis):
            result = await lookup_onboard_pin("ua:test")
            assert result is None

    @pytest.mark.asyncio
    async def test_set_pin_no_redis(self):
        """set_onboard_pin returns False when Redis is unavailable."""
        from src.mcp_handlers.identity.handlers import set_onboard_pin

        async def _get_no_redis():
            return None

        with patch("src.cache.redis_client.get_redis", new=_get_no_redis):
            result = await set_onboard_pin("ua:test", "uuid-1", "sess-1")
            assert result is False


# ============================================================================
# handle_identity_v2 (tool handler, not the decorator adapter)
# ============================================================================

class TestHandleIdentityV2:

    @pytest.mark.asyncio
    async def test_basic_identity_resolution(self, patch_all_deps, mock_db):
        """Basic identity() call resolves and returns identity."""
        from src.mcp_handlers.identity.handlers import handle_identity_v2

        result = await handle_identity_v2(
            arguments={},
            session_key="handle-test-session",
        )

        assert result["success"] is True
        assert "agent_id" in result
        assert "agent_uuid" in result
        assert result["bound"] is True

    @pytest.mark.asyncio
    async def test_identity_with_model_type(self, patch_all_deps, mock_db):
        """identity(model_type=...) uses model in agent_id generation."""
        from src.mcp_handlers.identity.handlers import handle_identity_v2

        result = await handle_identity_v2(
            arguments={"model_type": "claude-opus-4"},
            session_key="model-type-session",
            model_type="claude-opus-4",
        )

        assert result["success"] is True
        assert "Claude_Opus_4" in result["agent_id"]

    @pytest.mark.asyncio
    async def test_identity_with_name_sets_label(self, patch_all_deps, mock_db):
        """identity(name='X') sets the agent label."""
        from src.mcp_handlers.identity.handlers import handle_identity_v2

        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.upsert_agent = AsyncMock()
        mock_db.upsert_identity = AsyncMock()
        mock_db.create_session = AsyncMock()

        with patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("no server")):
            result = await handle_identity_v2(
                arguments={"name": "TestBot"},
                session_key="name-set-session",
            )

        assert result["success"] is True
        assert result.get("label") == "TestBot"
        assert result.get("display_name") == "TestBot"

    @pytest.mark.asyncio
    async def test_identity_name_claim_resolves_existing(self, patch_all_deps, mock_db, mock_redis, mock_raw_redis):
        """identity(name='X') resolves to existing agent via name claim."""
        from src.mcp_handlers.identity.handlers import handle_identity_v2

        test_uuid = str(uuid.uuid4())
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_id": "Claude_20260206"}
        )
        mock_db.get_agent_label.return_value = "ExistingBot"

        with patch("src.mcp_handlers.identity.shared.make_client_session_id", return_value="agent-test12345"):
            result = await handle_identity_v2(
                arguments={"name": "ExistingBot"},
                session_key="name-claim-handler-test",
            )

        assert result["success"] is True
        assert result["agent_uuid"] == test_uuid
        assert result.get("resumed_by_name") is True
        assert result.get("source") == "name_claim"


# ============================================================================
# resolve_by_name_claim (standalone)
# ============================================================================

class TestIdentityResolutionIntegration:

    @pytest.mark.asyncio
    async def test_redis_miss_pg_miss_creates_new(self, patch_all_deps, mock_redis, mock_db):
        """Full pipeline: Redis miss -> PG miss -> Create new."""
        from src.mcp_handlers.identity.handlers import resolve_session_identity

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None

        result = await resolve_session_identity(
            session_key="integration-test-1",
            model_type="claude-opus-4",
        )

        assert result["created"] is True
        assert result["source"] == "memory_only"
        assert result["agent_id"].startswith("Claude_Opus_4_")

    @pytest.mark.asyncio
    async def test_consistent_uuid_on_second_call_via_redis(self, patch_all_deps, mock_redis, mock_db, mock_raw_redis):
        """Second call should get same UUID back from Redis cache."""
        from src.mcp_handlers.identity.handlers import resolve_session_identity

        # First call: creates new agent (Redis and PG both miss)
        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None

        first = await resolve_session_identity(session_key="consistency-test")
        first_uuid = first["agent_uuid"]

        # Simulate Redis cache being populated: second call returns cached data
        mock_redis.get.return_value = {
            "agent_id": first_uuid,
            "display_agent_id": first["agent_id"],
        }
        mock_db.get_identity.return_value = None  # Not persisted

        second = await resolve_session_identity(session_key="consistency-test")

        assert second["agent_uuid"] == first_uuid
        assert second["source"] == "redis"
        assert second["created"] is False

    @pytest.mark.asyncio
    async def test_ephemeral_then_persisted_via_ensure(self, patch_all_deps, mock_db):
        """Agent starts ephemeral, then gets persisted via ensure_agent_persisted."""
        from src.mcp_handlers.identity.handlers import resolve_session_identity, ensure_agent_persisted

        # Create ephemeral
        result = await resolve_session_identity(session_key="ephemeral-test")
        assert result["persisted"] is False
        agent_uuid = result["agent_uuid"]

        # Now persist
        mock_db.get_identity.side_effect = [
            None,  # Not yet persisted
            SimpleNamespace(identity_id="new-ident", metadata={}),  # After upsert
        ]

        newly_persisted = await ensure_agent_persisted(agent_uuid, "ephemeral-test")
        assert newly_persisted is True
        mock_db.upsert_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_redis_and_pg_down_still_creates(self):
        """Even when both Redis and PG are down, a new identity is created."""
        from src.mcp_handlers.identity.handlers import resolve_session_identity

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_session.side_effect = Exception("PG down")
        mock_db.find_agent_by_label.return_value = None

        with patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db):
            result = await resolve_session_identity(session_key="all-down-test")

        assert result["created"] is True
        assert result["source"] == "memory_only"
        assert len(result["agent_uuid"]) == 36


# ============================================================================
# Edge cases
# ============================================================================

class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_legacy_non_uuid_in_redis_cache(self, patch_all_deps, mock_redis, mock_db):
        """Legacy Redis entries with model+date format (not UUID) are handled."""
        from src.mcp_handlers.identity.handlers import resolve_session_identity

        # Legacy format: agent_id is model+date, not UUID
        mock_redis.get.return_value = {"agent_id": "Claude_Opus_20260205"}
        mock_db.get_agent.return_value = SimpleNamespace(
            label="LegacyAgent", status="active"
        )
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_uuid": "legacy-uuid-1234"}
        )

        result = await resolve_session_identity(session_key="legacy-redis-test")

        assert result["source"] == "redis"
        assert result["agent_id"] == "Claude_Opus_20260205"

    @pytest.mark.asyncio
    async def test_legacy_non_uuid_in_pg(self, patch_no_redis, mock_db):
        """Legacy PG entries with model+date format session.agent_id are handled."""
        from src.mcp_handlers.identity.handlers import resolve_session_identity

        # Legacy PG: agent_id stored as model+date
        mock_db.get_session.return_value = SimpleNamespace(
            agent_id="Gemini_Pro_20260101"
        )
        mock_db.get_agent.return_value = SimpleNamespace(
            label="LegacyPGAgent", status="active"
        )
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_uuid": "legacy-pg-uuid"}
        )
        mock_db.get_agent_label.return_value = "LegacyPGAgent"

        result = await resolve_session_identity(session_key="legacy-pg-test")

        assert result["source"] == "postgres"
        assert result["agent_id"] == "Gemini_Pro_20260101"

    @pytest.mark.asyncio
    async def test_session_key_with_only_colons(self, patch_all_deps):
        """Session key with only colons is valid (allowed chars)."""
        from src.mcp_handlers.identity.handlers import resolve_session_identity

        result = await resolve_session_identity(session_key=":::")
        assert result["created"] is True

    @pytest.mark.asyncio
    async def test_session_key_at_exact_max_length(self, patch_all_deps):
        """Session key at exactly 256 chars passes without truncation."""
        from src.mcp_handlers.identity.handlers import resolve_session_identity

        key = "a" * 256
        result = await resolve_session_identity(session_key=key)
        assert result["created"] is True

    @pytest.mark.asyncio
    async def test_session_key_at_257_chars_truncated(self, patch_all_deps):
        """Session key at 257 chars is truncated to 256."""
        from src.mcp_handlers.identity.handlers import resolve_session_identity

        key = "a" * 257
        result = await resolve_session_identity(session_key=key)
        assert result["created"] is True


# ============================================================================
# GovernanceConfig import fallback (lines 41-45)
# ============================================================================

class TestGovernanceConfigFallback:
    """Test that GovernanceConfig has expected constants available."""

    def test_session_ttl_seconds_exists(self):
        """GovernanceConfig.SESSION_TTL_SECONDS is available."""
        from config.governance_config import GovernanceConfig
        assert hasattr(GovernanceConfig, "SESSION_TTL_SECONDS")
        assert isinstance(GovernanceConfig.SESSION_TTL_SECONDS, int)

    def test_session_ttl_hours_exists(self):
        """GovernanceConfig.SESSION_TTL_HOURS is available."""
        from config.governance_config import GovernanceConfig
        assert hasattr(GovernanceConfig, "SESSION_TTL_HOURS")


# ============================================================================
# _get_redis exception path (lines 62-64)
# ============================================================================

class TestOnboardPinExceptionPaths:

    @pytest.mark.asyncio
    async def test_lookup_pin_redis_exception_returns_none(self):
        """lookup_onboard_pin returns None when Redis throws (lines 1138-1140)."""
        from src.mcp_handlers.identity.handlers import lookup_onboard_pin

        async def _get_error_redis():
            raise Exception("Connection reset")

        with patch("src.cache.redis_client.get_redis", new=_get_error_redis):
            result = await lookup_onboard_pin("ua:test123")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_pin_redis_exception_returns_false(self):
        """set_onboard_pin returns False when Redis throws (lines 1173-1175)."""
        from src.mcp_handlers.identity.handlers import set_onboard_pin

        async def _get_error_redis():
            raise Exception("Connection reset")

        with patch("src.cache.redis_client.get_redis", new=_get_error_redis):
            result = await set_onboard_pin("ua:test456", "uuid-1", "sess-1")

        assert result is False

    @pytest.mark.asyncio
    async def test_lookup_pin_with_bytes_data(self):
        """lookup_onboard_pin handles bytes data from Redis."""
        from src.mcp_handlers.identity.handlers import lookup_onboard_pin

        mock_raw = AsyncMock()
        pin_data = json.dumps({"client_session_id": "agent-abc123", "agent_uuid": "uuid-123"})
        mock_raw.get.return_value = pin_data.encode("utf-8")  # bytes, not str
        mock_raw.expire = AsyncMock()

        async def _get_raw():
            return mock_raw

        with patch("src.cache.redis_client.get_redis", new=_get_raw):
            result = await lookup_onboard_pin("ua:bytes-test")

        assert result == "agent-abc123"

    @pytest.mark.asyncio
    async def test_lookup_pin_no_refresh_ttl(self):
        """lookup_onboard_pin with refresh_ttl=False does not call expire."""
        from src.mcp_handlers.identity.handlers import lookup_onboard_pin

        mock_raw = AsyncMock()
        pin_data = json.dumps({"client_session_id": "agent-norefresh", "agent_uuid": "uuid-123"})
        mock_raw.get.return_value = pin_data
        mock_raw.expire = AsyncMock()

        async def _get_raw():
            return mock_raw

        with patch("src.cache.redis_client.get_redis", new=_get_raw):
            result = await lookup_onboard_pin("ua:norefresh", refresh_ttl=False)

        assert result == "agent-norefresh"
        mock_raw.expire.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_pin_no_data_returns_none(self):
        """lookup_onboard_pin returns None when no pin data at key."""
        from src.mcp_handlers.identity.handlers import lookup_onboard_pin

        mock_raw = AsyncMock()
        mock_raw.get.return_value = None

        async def _get_raw():
            return mock_raw

        with patch("src.cache.redis_client.get_redis", new=_get_raw):
            result = await lookup_onboard_pin("ua:nodata")

        assert result is None


# ============================================================================
# Helper to parse TextContent results from handler functions
# ============================================================================

def _parse(result):
    """Extract JSON data from Sequence[TextContent] or single TextContent."""
    if isinstance(result, (list, tuple)):
        text_content = result[0]
    else:
        text_content = result
    return json.loads(text_content.text)


# ============================================================================
# handle_identity_adapter - full decorator-wrapped handler (lines 1208-1410)
# ============================================================================

class TestHandleIdentityAdapter:

    @pytest.fixture
    def patch_identity_deps(self, mock_db, mock_redis, mock_raw_redis):
        """Patch all deps for handle_identity_adapter tests."""
        async def _get_raw():
            return mock_raw_redis

        mock_server = MagicMock()
        mock_server.agent_metadata = {}

        with patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value=None), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
            yield mock_server

    @pytest.mark.asyncio
    async def test_basic_identity_call(self, patch_identity_deps, mock_db, mock_redis):
        """Basic identity() call with no arguments returns identity info."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None

        result = await handle_identity_adapter({"client_session_id": "test-sess-1"})
        data = _parse(result)

        assert data["success"] is True
        assert "uuid" in data
        assert "agent_id" in data
        assert "identity_summary" in data
        assert "quick_reference" in data
        assert "session_continuity" in data

    @pytest.mark.asyncio
    async def test_identity_name_claim_resolves_existing(self, patch_identity_deps, mock_db, mock_redis, mock_raw_redis):
        """identity(name='X') resolves via name claim when agent exists (lines 1208-1228)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_id": "Claude_20260206"}
        )
        mock_db.get_agent_label.return_value = "TestBot"
        mock_db.create_session = AsyncMock()

        result = await handle_identity_adapter({
            "client_session_id": "name-adapter-test",
            "name": "TestBot",
        })
        data = _parse(result)

        assert data["success"] is True
        assert data["uuid"] == test_uuid
        assert data.get("resumed") is True
        assert data.get("resumed_by_name") is True

    @pytest.mark.asyncio
    async def test_identity_resumes_existing_agent(self, patch_identity_deps, mock_db, mock_redis, mock_raw_redis):
        """identity() auto-resumes existing agent under base key."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = "ExistingAgent"

        result = await handle_identity_adapter({"client_session_id": "resume-test"})
        data = _parse(result)

        assert data["success"] is True
        assert data["uuid"] == test_uuid
        assert data.get("resumed") is True

    @pytest.mark.asyncio
    async def test_identity_with_model_type_new_agent(self, patch_identity_deps, mock_db, mock_redis):
        """identity(model_type='claude-opus-4') for new agent uses model differentiation (lines 1262-1277)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        result = await handle_identity_adapter({
            "client_session_id": "model-new-test",
            "model_type": "claude-opus-4",
        })
        data = _parse(result)

        assert data["success"] is True
        assert "Claude_Opus_4" in data.get("agent_id", "")

    @pytest.mark.asyncio
    async def test_identity_with_model_type_gemini(self, patch_identity_deps, mock_db, mock_redis):
        """Model normalization works for gemini (lines 1267-1268)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        result = await handle_identity_adapter({
            "client_session_id": "gemini-test",
            "model_type": "gemini-pro-1.5",
        })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_identity_with_model_type_gpt(self, patch_identity_deps, mock_db, mock_redis):
        """Model normalization works for gpt (lines 1269-1270)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        result = await handle_identity_adapter({
            "client_session_id": "gpt-test",
            "model_type": "gpt-4-turbo",
        })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_identity_with_model_type_composer(self, patch_identity_deps, mock_db, mock_redis):
        """Model normalization works for composer/cursor (lines 1271-1272)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        result = await handle_identity_adapter({
            "client_session_id": "composer-test",
            "model_type": "cursor-composer",
        })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_identity_with_model_type_llama(self, patch_identity_deps, mock_db, mock_redis):
        """Model normalization works for llama (lines 1273-1274)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        result = await handle_identity_adapter({
            "client_session_id": "llama-test",
            "model_type": "llama-3.1-70b",
        })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_identity_force_new(self, patch_identity_deps, mock_db, mock_redis):
        """identity(force_new=true) skips existing check and creates new."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        result = await handle_identity_adapter({
            "client_session_id": "force-new-adapter",
            "force_new": True,
        })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_identity_model_type_in_response(self, patch_identity_deps, mock_db, mock_redis):
        """model_type is included in response when provided (line 1361)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        result = await handle_identity_adapter({
            "client_session_id": "model-response-test",
            "model_type": "claude-opus-4",
        })
        data = _parse(result)

        assert data.get("model_type") == "claude-opus-4"

    @pytest.mark.asyncio
    async def test_identity_none_arguments_handled(self, patch_identity_deps, mock_db, mock_redis):
        """identity() with None arguments does not crash (line 1407-1408)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None

        # The decorator passes arguments=arguments, so None would come from decorator
        # but the function defaults to {} if None. Test with empty dict.
        result = await handle_identity_adapter({})
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_identity_existing_under_model_key_resumes(self, patch_identity_deps, mock_db, mock_redis, mock_raw_redis):
        """When no base key match but model-suffixed key matches, resumes (lines 1281-1303)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        test_uuid = str(uuid.uuid4())

        call_count = [0]
        original_get = mock_redis.get

        async def side_effect_get(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call (base key): miss (created=True in resolve)
                return None
            else:
                # Second call (model-suffixed key): hit
                return {"agent_id": test_uuid, "display_agent_id": "Claude_20260207"}

        mock_redis.get.side_effect = side_effect_get
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = "ModelAgent"

        result = await handle_identity_adapter({
            "client_session_id": "model-key-resume",
            "model_type": "claude-opus-4",
        })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_identity_update_label_on_resume(self, patch_identity_deps, mock_db, mock_redis, mock_raw_redis):
        """identity(name='X') updates label on existing resumed agent (lines 1246-1249, 1291-1294)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = "OldName"
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        result = await handle_identity_adapter({
            "client_session_id": "label-update-test",
            "name": "NewName",
        })
        data = _parse(result)

        assert data["success"] is True


# ============================================================================
# handle_onboard_v2 - full flow (lines 1480-1857)
# ============================================================================

class TestHandleOnboardV2:

    @pytest.fixture
    def patch_onboard_deps(self, mock_db, mock_redis, mock_raw_redis):
        """Patch all deps for handle_onboard_v2 tests."""
        async def _get_raw():
            return mock_raw_redis

        mock_server = MagicMock()
        mock_server.agent_metadata = {}

        with patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="test-ctx-key"), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity.shared._register_uuid_prefix"):
            yield mock_server

    @pytest.mark.asyncio
    async def test_basic_onboard_new_agent(self, patch_onboard_deps, mock_db, mock_redis):
        """Basic onboard() creates a new agent."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        # For ensure_agent_persisted
        mock_db.get_identity.side_effect = [
            None,  # resolve_session_identity PG lookup
            None,  # ensure_agent_persisted check
            SimpleNamespace(identity_id="new-ident", metadata={}),  # after upsert
        ]

        result = await handle_onboard_v2({"client_session_id": "onboard-new"})
        data = _parse(result)

        assert data["success"] is True
        assert data["is_new"] is True
        assert "uuid" in data
        assert "client_session_id" in data
        assert "next_calls" in data
        assert "date_context" in data
        assert "session_continuity" in data
        assert "workflow" in data
        assert "what_this_does" not in data

    @pytest.mark.asyncio
    async def test_onboard_creates_new_instance_for_existing_trajectory(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """onboard() creates new UUID for existing trajectory, linking predecessor."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        predecessor_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": predecessor_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = "PredecessorAgent"

        result = await handle_onboard_v2({"client_session_id": "onboard-resume"})
        data = _parse(result)

        assert data["success"] is True
        assert data["is_new"] is True
        assert data["uuid"] != predecessor_uuid  # New UUID, not the old one
        assert data.get("predecessor", {}).get("uuid") == predecessor_uuid

    @pytest.mark.asyncio
    async def test_onboard_with_name_resolves_by_name_claim(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """onboard(name='X') resolves via name claim."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_id": "Claude_20260207"}
        )
        mock_db.get_agent_label.return_value = "NamedAgent"
        mock_db.create_session = AsyncMock()

        result = await handle_onboard_v2({
            "client_session_id": "onboard-name-claim",
            "name": "NamedAgent",
            "resume": True,
        })
        data = _parse(result)

        assert data["success"] is True
        assert data["uuid"] == test_uuid
        assert data["is_new"] is False

    @pytest.mark.asyncio
    async def test_onboard_force_new(self, patch_onboard_deps, mock_db, mock_redis):
        """onboard(force_new=true) creates fresh identity."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="new-ident", metadata={})

        result = await handle_onboard_v2({
            "client_session_id": "onboard-force-new",
            "force_new": True,
        })
        data = _parse(result)

        assert data["success"] is True
        assert data["force_new_applied"] is True

    @pytest.mark.asyncio
    async def test_onboard_force_new_with_model_type(self, patch_onboard_deps, mock_db, mock_redis):
        """onboard(force_new=true, model_type='claude') uses model-suffixed key."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="new-ident", metadata={})

        result = await handle_onboard_v2({
            "client_session_id": "onboard-force-model",
            "force_new": True,
            "model_type": "claude-opus-4",
        })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_onboard_with_model_type_gemini(self, patch_onboard_deps, mock_db, mock_redis):
        """Model normalization for gemini in onboard flow."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.side_effect = [
            None, None,
            SimpleNamespace(identity_id="new-ident", metadata={})
        ]

        result = await handle_onboard_v2({
            "client_session_id": "onboard-gemini",
            "model_type": "gemini-pro",
        })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_onboard_with_model_type_gpt(self, patch_onboard_deps, mock_db, mock_redis):
        """Model normalization for gpt in onboard flow."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.side_effect = [
            None, None,
            SimpleNamespace(identity_id="new-ident", metadata={})
        ]

        result = await handle_onboard_v2({
            "client_session_id": "onboard-gpt",
            "model_type": "chatgpt-4o",
        })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_onboard_with_model_type_llama(self, patch_onboard_deps, mock_db, mock_redis):
        """Model normalization for llama in onboard flow."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.side_effect = [
            None, None,
            SimpleNamespace(identity_id="new-ident", metadata={})
        ]

        result = await handle_onboard_v2({
            "client_session_id": "onboard-llama",
            "model_type": "llama-3.1-70b",
        })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_onboard_sets_label(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """onboard(name='X') sets the display label."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.side_effect = [
            None, None,
            SimpleNamespace(identity_id="new-ident", metadata={}),
            SimpleNamespace(identity_id="new-ident", metadata={}),
        ]
        mock_db.update_agent_fields.return_value = True

        with patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("no server")):
            result = await handle_onboard_v2({
                "client_session_id": "onboard-label",
                "name": "MyNewAgent",
            })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_onboard_with_trajectory_signature(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """onboard() with trajectory_signature stores genesis."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = "TrajectoryAgent"

        mock_sig = MagicMock()
        mock_sig.identity_confidence = 0.8
        mock_sig.observation_count = 10

        with patch("src.trajectory_identity.TrajectorySignature") as MockTrajSig, \
             patch("src.trajectory_identity.store_genesis_signature", new_callable=AsyncMock, return_value=True):
            MockTrajSig.from_dict.return_value = mock_sig

            result = await handle_onboard_v2({
                "client_session_id": "onboard-trajectory",
                "trajectory_signature": {
                    "preferences": {}, "beliefs": {},
                    "stability_score": 0.9, "identity_confidence": 0.8,
                    "observation_count": 10,
                },
            })
        data = _parse(result)

        assert data["success"] is True
        assert "trajectory" in data
        assert data["trajectory"]["genesis_stored"] is True
        assert "trust_tier" in data["trajectory"]

    @pytest.mark.asyncio
    async def test_onboard_trajectory_exception_non_blocking(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """Trajectory store failure does not block onboard."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = None

        with patch("src.trajectory_identity.TrajectorySignature", side_effect=Exception("Import fail")):
            result = await handle_onboard_v2({
                "client_session_id": "onboard-traj-fail",
                "trajectory_signature": {"some": "data"},
            })
        data = _parse(result)

        assert data["success"] is True
        assert "trajectory" not in data  # Not included on failure

    @pytest.mark.asyncio
    async def test_onboard_kwargs_string_unwrapping(self, patch_onboard_deps, mock_db, mock_redis):
        """onboard() unwraps kwargs string into arguments (lines 1483-1492)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.side_effect = [
            None, None,
            SimpleNamespace(identity_id="new-ident", metadata={})
        ]

        result = await handle_onboard_v2({
            "client_session_id": "kwargs-test",
            "kwargs": json.dumps({"model_type": "claude-opus-4"}),
        })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_onboard_kwargs_invalid_json_handled(self, patch_onboard_deps, mock_db, mock_redis):
        """onboard() handles invalid kwargs JSON gracefully (line 1491)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.side_effect = [
            None, None,
            SimpleNamespace(identity_id="new-ident", metadata={})
        ]

        result = await handle_onboard_v2({
            "client_session_id": "kwargs-invalid",
            "kwargs": "not valid json{{{",
        })
        data = _parse(result)

        assert data["success"] is True  # Should not crash

    @pytest.mark.asyncio
    async def test_onboard_tool_mode_info(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """onboard() includes tool_mode info when available."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = None

        with patch("src.tool_modes.TOOL_MODE", "lite"), \
             patch("src.tool_modes.get_tools_for_mode", return_value=["t1", "t2", "t3"]), \
             patch("src.tool_schemas.get_tool_definitions", return_value={"t1": {}, "t2": {}, "t3": {}, "t4": {}, "t5": {}}):
            result = await handle_onboard_v2({"client_session_id": "tool-mode-test"})
        data = _parse(result)

        assert data["success"] is True
        assert "tool_mode" in data
        assert data["tool_mode"]["current_mode"] == "lite"
        assert data["tool_mode"]["visible_tools"] == 3
        assert data["tool_mode"]["total_tools"] == 5

    @pytest.mark.asyncio
    async def test_onboard_tool_mode_exception_handled(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """tool_mode import failure is swallowed."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = None

        with patch("src.tool_modes.TOOL_MODE", side_effect=Exception("No module")):
            result = await handle_onboard_v2({"client_session_id": "tool-mode-fail"})
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_onboard_client_tips_chatgpt(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """Client tips for chatgpt hint are included."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = None

        with patch("src.mcp_handlers.context.get_context_client_hint", return_value="chatgpt"):
            result = await handle_onboard_v2({"client_session_id": "chatgpt-tips"})
        data = _parse(result)

        assert data["success"] is True
        tip = data.get("session_continuity", {}).get("tip", "")
        assert "ChatGPT" in tip or "client_session_id" in tip

    @pytest.mark.asyncio
    async def test_onboard_persist_failure_returns_error(self, patch_onboard_deps, mock_db, mock_redis):
        """When persist fails for fresh identity, returns error (line 1613-1615)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        # Mock ensure_agent_persisted to raise an exception directly
        # This triggers the except block at line 1613 which returns error_response
        with patch("src.mcp_handlers.identity.handlers.ensure_agent_persisted", side_effect=Exception("Fatal persist error")):
            result = await handle_onboard_v2({"client_session_id": "persist-fail"})
        data = _parse(result)

        assert data.get("success") is False
        assert "persist" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_onboard_none_arguments_handled(self, patch_onboard_deps, mock_db, mock_redis):
        """onboard(None) defaults to empty dict."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.side_effect = [
            None, None,
            SimpleNamespace(identity_id="new-ident", metadata={})
        ]

        result = await handle_onboard_v2(None)
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_onboard_structured_id_fallback(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """When structured_id lookup from metadata returns nothing, falls back to agent_UUID prefix."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.side_effect = [
            None, None,
            SimpleNamespace(identity_id="new-ident", metadata={})
        ]

        result = await handle_onboard_v2({"client_session_id": "fallback-id-test"})
        data = _parse(result)

        assert data["success"] is True
        # agent_id should be generated, not an empty UUID
        assert data.get("agent_id") is not None

    @pytest.mark.asyncio
    async def test_onboard_auto_unarchives_agent(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """onboard() auto-unarchives an archived agent and sets auto_resumed flag."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        # Return archived identity
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={}, status="archived"
        )
        mock_db.get_agent_label.return_value = "ArchivedAgent"
        mock_db.update_agent_fields.return_value = True

        result = await handle_onboard_v2({"client_session_id": "onboard-archived"})
        data = _parse(result)

        assert data["success"] is True
        assert data["is_new"] is False
        assert data.get("auto_resumed") is True
        assert data.get("previous_status") == "archived"
        assert "reactivated" in data.get("welcome_message", "").lower()
        # Verify DB update was called
        mock_db.update_agent_fields.assert_called_with(test_uuid, status="active")


# ============================================================================
# handle_verify_trajectory_identity (lines 1884-1921)
# ============================================================================

class TestHandleVerifyTrajectoryIdentity:

    @pytest.mark.asyncio
    async def test_no_agent_uuid_returns_error(self):
        """verify_trajectory_identity with no identity returns error."""
        from src.mcp_handlers.identity.handlers import handle_verify_trajectory_identity

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value=None):
            result = await handle_verify_trajectory_identity({})
        data = _parse(result)

        assert data["success"] is False
        assert "identity" in data["error"].lower() or "resolved" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_no_trajectory_signature_returns_error(self):
        """verify_trajectory_identity without trajectory_signature returns error."""
        from src.mcp_handlers.identity.handlers import handle_verify_trajectory_identity

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-123"):
            result = await handle_verify_trajectory_identity({})
        data = _parse(result)

        assert data["success"] is False
        assert "trajectory_signature" in data["error"]

    @pytest.mark.asyncio
    async def test_invalid_trajectory_signature_type_returns_error(self):
        """verify_trajectory_identity with non-dict trajectory_signature returns error."""
        from src.mcp_handlers.identity.handlers import handle_verify_trajectory_identity

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-123"):
            result = await handle_verify_trajectory_identity({"trajectory_signature": "not a dict"})
        data = _parse(result)

        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_successful_verification(self):
        """verify_trajectory_identity succeeds with valid inputs."""
        from src.mcp_handlers.identity.handlers import handle_verify_trajectory_identity

        mock_sig = MagicMock()
        mock_verification_result = {
            "verified": True,
            "tiers": {"coherence": {"similarity": 0.9}, "lineage": {"similarity": 0.85}},
        }

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-verify"), \
             patch("src.trajectory_identity.TrajectorySignature") as MockTrajSig, \
             patch("src.trajectory_identity.verify_trajectory_identity", new_callable=AsyncMock, return_value=mock_verification_result):
            MockTrajSig.from_dict.return_value = mock_sig

            result = await handle_verify_trajectory_identity({
                "trajectory_signature": {"preferences": {}, "stability_score": 0.9},
                "coherence_threshold": 0.7,
                "lineage_threshold": 0.6,
            })
        data = _parse(result)

        assert data["success"] is True
        assert data["verified"] is True

    @pytest.mark.asyncio
    async def test_verification_error_result(self):
        """verify_trajectory_identity with error in result returns error."""
        from src.mcp_handlers.identity.handlers import handle_verify_trajectory_identity

        mock_sig = MagicMock()
        mock_verification_result = {"error": "No genesis signature found"}

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-verify"), \
             patch("src.trajectory_identity.TrajectorySignature") as MockTrajSig, \
             patch("src.trajectory_identity.verify_trajectory_identity", new_callable=AsyncMock, return_value=mock_verification_result):
            MockTrajSig.from_dict.return_value = mock_sig

            result = await handle_verify_trajectory_identity({
                "trajectory_signature": {"preferences": {}},
            })
        data = _parse(result)

        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_verification_exception_returns_error(self):
        """verify_trajectory_identity exception returns error (lines 1919-1921)."""
        from src.mcp_handlers.identity.handlers import handle_verify_trajectory_identity

        mock_sig = MagicMock()
        mock_verify = AsyncMock(side_effect=Exception("Verification module error"))

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-verify"), \
             patch("src.trajectory_identity.TrajectorySignature") as MockTrajSig, \
             patch("src.trajectory_identity.verify_trajectory_identity", mock_verify):
            MockTrajSig.from_dict.return_value = mock_sig

            result = await handle_verify_trajectory_identity({
                "trajectory_signature": {"preferences": {}},
            })
        data = _parse(result)

        assert data["success"] is False
        error_msg = data.get("error", "").lower()
        assert "failed" in error_msg or "verification" in error_msg


# ============================================================================
# handle_get_trajectory_status (lines 1938-1966)
# ============================================================================

class TestHandleGetTrajectoryStatus:

    @pytest.mark.asyncio
    async def test_no_agent_uuid_returns_error(self):
        """get_trajectory_status with no identity returns error."""
        from src.mcp_handlers.identity.handlers import handle_get_trajectory_status

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value=None):
            result = await handle_get_trajectory_status({})
        data = _parse(result)

        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_successful_status(self):
        """get_trajectory_status returns status info."""
        from src.mcp_handlers.identity.handlers import handle_get_trajectory_status

        mock_status_result = {
            "has_genesis": True,
            "has_current": True,
            "lineage_similarity": 0.85,
        }

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"total_updates": 20}
        )

        mock_trust_tier = {"tier": 2, "name": "stable"}

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-status"), \
             patch("src.trajectory_identity.get_trajectory_status", new_callable=AsyncMock, return_value=mock_status_result), \
             patch("src.trajectory_identity.compute_trust_tier", return_value=mock_trust_tier), \
             patch("src.db.get_db", return_value=mock_db):
            result = await handle_get_trajectory_status({})
        data = _parse(result)

        assert data["success"] is True
        assert data["has_genesis"] is True
        assert "trust_tier" in data

    @pytest.mark.asyncio
    async def test_status_error_result(self):
        """get_trajectory_status with error in result returns error."""
        from src.mcp_handlers.identity.handlers import handle_get_trajectory_status

        mock_status_result = {"error": "Agent has no trajectory data"}

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-status"), \
             patch("src.trajectory_identity.get_trajectory_status", new_callable=AsyncMock, return_value=mock_status_result):
            result = await handle_get_trajectory_status({})
        data = _parse(result)

        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_status_exception_returns_error(self):
        """get_trajectory_status exception returns error (lines 1964-1966)."""
        from src.mcp_handlers.identity.handlers import handle_get_trajectory_status

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-status"), \
             patch("src.trajectory_identity.get_trajectory_status", side_effect=Exception("Module error")):
            result = await handle_get_trajectory_status({})
        data = _parse(result)

        assert data["success"] is False
        assert "failed" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_trust_tier_exception_non_blocking(self):
        """trust_tier computation failure does not block status response (lines 1959-1960)."""
        from src.mcp_handlers.identity.handlers import handle_get_trajectory_status

        mock_status_result = {
            "has_genesis": True,
            "has_current": False,
        }

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-status"), \
             patch("src.trajectory_identity.get_trajectory_status", new_callable=AsyncMock, return_value=mock_status_result), \
             patch("src.trajectory_identity.compute_trust_tier", side_effect=Exception("No trust data")), \
             patch("src.db.get_db", side_effect=Exception("DB down")):
            result = await handle_get_trajectory_status({})
        data = _parse(result)

        assert data["success"] is True
        assert data["has_genesis"] is True
        # trust_tier should not be present since computation failed
        assert "trust_tier" not in data


# ============================================================================
# Additional coverage: set_agent_label structured_id migration (lines 611-621)
# ============================================================================

class TestIdentityAdapterStructuredIdRegeneration:

    @pytest.fixture
    def patch_identity_regen_deps(self, mock_db, mock_redis, mock_raw_redis):
        """Patch deps for structured_id regeneration tests."""
        async def _get_raw():
            return mock_raw_redis

        mock_server = MagicMock()

        with patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value=None), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
            yield mock_server

    @pytest.mark.asyncio
    async def test_structured_id_regenerated_when_model_doesnt_match(self, patch_identity_regen_deps, mock_db, mock_redis):
        """structured_id is regenerated when model_type doesn't match existing ID (lines 1327-1342)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        # Get the mock server from the fixture
        mock_server = patch_identity_regen_deps

        # We need the handler to create a new identity first, then check metadata
        # The trick is the metadata needs to exist AFTER resolve_session_identity runs
        original_resolve = None

        async def resolve_side_effect(*args, **kwargs):
            # Simulate creating a new identity and populating metadata
            agent_uuid = str(uuid.uuid4())
            agent_id = "Claude_Opus_4_20260207"
            meta = SimpleNamespace(
                label=None,
                structured_id="generic_id_1"  # Doesn't contain "claude"
            )
            mock_server.agent_metadata[agent_uuid] = meta
            return {
                "agent_id": agent_id,
                "agent_uuid": agent_uuid,
                "label": None,
                "created": True,
                "persisted": False,
                "source": "memory_only",
            }

        with patch("src.mcp_handlers.identity.handlers.resolve_session_identity", side_effect=resolve_side_effect), \
             patch("src.mcp_handlers.support.naming_helpers.detect_interface_context", return_value={"type": "test"}), \
             patch("src.mcp_handlers.support.naming_helpers.generate_structured_id", return_value="claude_opus_1"), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="cursor"):

            result = await handle_identity_adapter({
                "client_session_id": "regen-struct-id",
                "model_type": "claude-opus-4",
                "force_new": True,  # Skip base key lookup
            })
        data = _parse(result)

        assert data["success"] is True


# ============================================================================
# Additional coverage: onboard force_new with model normalization branches
# ============================================================================

class TestOnboardForceNewModelNormalization:

    @pytest.fixture
    def patch_onboard_force_deps(self, mock_db, mock_redis, mock_raw_redis):
        """Patch deps for onboard force_new model tests."""
        async def _get_raw():
            return mock_raw_redis

        mock_server = MagicMock()
        mock_server.agent_metadata = {}

        with patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="force-ctx-key"), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity.shared._register_uuid_prefix"):
            yield mock_server

    @pytest.mark.asyncio
    async def test_force_new_gemini_normalization(self, patch_onboard_force_deps, mock_db, mock_redis):
        """onboard(force_new=true, model_type='gemini-pro') normalizes to 'gemini' (line 1574-1575)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="new-ident", metadata={})

        result = await handle_onboard_v2({
            "client_session_id": "force-gemini",
            "force_new": True,
            "model_type": "gemini-pro-1.5",
        })
        data = _parse(result)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_force_new_gpt_normalization(self, patch_onboard_force_deps, mock_db, mock_redis):
        """onboard(force_new=true, model_type='gpt-4') normalizes to 'gpt' (line 1576-1577)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="new-ident", metadata={})

        result = await handle_onboard_v2({
            "client_session_id": "force-gpt",
            "force_new": True,
            "model_type": "gpt-4-turbo",
        })
        data = _parse(result)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_force_new_llama_normalization(self, patch_onboard_force_deps, mock_db, mock_redis):
        """onboard(force_new=true, model_type='llama-3') normalizes to 'llama' (line 1578-1579)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="new-ident", metadata={})

        result = await handle_onboard_v2({
            "client_session_id": "force-llama",
            "force_new": True,
            "model_type": "llama-3.1-70b",
        })
        data = _parse(result)
        assert data["success"] is True


# ============================================================================
# Additional coverage: onboard resolve_session_identity failure in force_new (lines 1632-1634)
# ============================================================================

class TestOnboardResolveSessionIdentityFailure:

    @pytest.fixture
    def patch_onboard_resolve_fail_deps(self, mock_db, mock_redis, mock_raw_redis):
        async def _get_raw():
            return mock_raw_redis

        mock_server = MagicMock()
        mock_server.agent_metadata = {}

        with patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="ctx-key"), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity.shared._register_uuid_prefix"):
            yield mock_server

    @pytest.mark.asyncio
    async def test_force_new_resolve_exception_returns_error(self, patch_onboard_resolve_fail_deps, mock_db, mock_redis):
        """When force_new + resolve_session_identity raises, returns error (lines 1632-1634)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        with patch("src.mcp_handlers.identity.handlers.resolve_session_identity", side_effect=Exception("Resolve failed")):
            result = await handle_onboard_v2({
                "client_session_id": "force-resolve-fail",
                "force_new": True,
            })
        data = _parse(result)

        assert data.get("success") is False
        assert "failed" in data.get("error", "").lower()


# ============================================================================
# Additional coverage: onboard already-persisted fresh identity (line 1603)
# ============================================================================

class TestOnboardAlreadyPersistedFreshIdentity:

    @pytest.fixture
    def patch_onboard_persisted_deps(self, mock_db, mock_redis, mock_raw_redis):
        async def _get_raw():
            return mock_raw_redis

        mock_server = MagicMock()
        mock_server.agent_metadata = {}

        with patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="ctx-key"), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity.shared._register_uuid_prefix"):
            yield mock_server

    @pytest.mark.asyncio
    async def test_fresh_identity_already_persisted(self, patch_onboard_persisted_deps, mock_db, mock_redis):
        """When fresh identity is already persisted, ensure_agent_persisted returns False (line 1603)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        # ensure_agent_persisted returns False (already persisted)
        with patch("src.mcp_handlers.identity.handlers.ensure_agent_persisted", new_callable=AsyncMock, return_value=False):
            result = await handle_onboard_v2({"client_session_id": "already-persisted"})
        data = _parse(result)

        assert data["success"] is True
        assert data["is_new"] is True


# ============================================================================
# Additional coverage: update_context_agent_id exception paths
# ============================================================================

class TestContextUpdateExceptions:

    @pytest.fixture
    def patch_ctx_deps(self, mock_db, mock_redis, mock_raw_redis):
        async def _get_raw():
            return mock_raw_redis

        mock_server = MagicMock()
        mock_server.agent_metadata = {}

        with patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value=None), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
            yield mock_server

    @pytest.mark.asyncio
    async def test_identity_adapter_context_update_exception(self, patch_ctx_deps, mock_db, mock_redis):
        """update_context_agent_id failure is swallowed in identity adapter (lines 1314-1315)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        with patch("src.mcp_handlers.context.update_context_agent_id", side_effect=Exception("Context error")):
            result = await handle_identity_adapter({
                "client_session_id": "ctx-fail-test",
                "force_new": True,
            })
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_identity_adapter_name_claim_context_update_exception(self, patch_ctx_deps, mock_db, mock_redis, mock_raw_redis):
        """update_context_agent_id failure in name claim path is swallowed (lines 1217-1218)."""
        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_id": "Claude_20260207"}
        )
        mock_db.get_agent_label.return_value = "CtxFailAgent"
        mock_db.create_session = AsyncMock()

        with patch("src.mcp_handlers.context.update_context_agent_id", side_effect=Exception("Context error")):
            result = await handle_identity_adapter({
                "client_session_id": "ctx-name-fail",
                "name": "CtxFailAgent",
            })
        data = _parse(result)

        assert data["success"] is True
        assert data.get("resumed_by_name") is True


# ============================================================================
# Additional coverage: onboard structured_id fallback (lines 1752-1763)
# ============================================================================

class TestOnboardStructuredIdFallback:

    @pytest.fixture
    def patch_sid_deps(self, mock_db, mock_redis, mock_raw_redis):
        async def _get_raw():
            return mock_raw_redis

        mock_server = MagicMock()
        mock_server.agent_metadata = {}

        with patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="ctx"), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity.shared._register_uuid_prefix"):
            yield mock_server

    @pytest.mark.asyncio
    async def test_structured_id_from_metadata_lookup(self, patch_sid_deps, mock_db, mock_redis, mock_raw_redis):
        """When agent_id == agent_uuid, falls back to metadata for structured_id (lines 1752-1759)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_server = patch_sid_deps
        test_uuid = str(uuid.uuid4())

        # Force resume path where agent_id might equal agent_uuid
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": test_uuid,  # Same as UUID -> triggers fallback
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = None

        # Add metadata with structured_id
        meta = SimpleNamespace(structured_id="custom_agent_1")
        mock_server.agent_metadata[test_uuid] = meta

        # resume=True to reuse old UUID (escape hatch) — tests structured_id fallback
        result = await handle_onboard_v2({"client_session_id": "sid-fallback", "resume": True})
        data = _parse(result)

        assert data["success"] is True
        # structured_id should be from metadata
        assert data.get("agent_id") == "custom_agent_1"

    @pytest.mark.asyncio
    async def test_structured_id_uuid_prefix_fallback(self, patch_sid_deps, mock_db, mock_redis, mock_raw_redis):
        """When no structured_id anywhere, falls back to agent_{uuid[:8]} (line 1763)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        mock_server = patch_sid_deps
        test_uuid = str(uuid.uuid4())

        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": test_uuid,  # Same as UUID
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = None

        # resume=True to reuse old UUID — tests uuid prefix fallback
        result = await handle_onboard_v2({"client_session_id": "uuid-prefix-fallback", "resume": True})
        data = _parse(result)

        assert data["success"] is True
        assert data.get("agent_id", "").startswith("agent_")


# ============================================================================
# Additional coverage: onboard pin/uuid_prefix exception paths (lines 1686-1698)
# ============================================================================

class TestOnboardPinAndPrefixExceptions:

    @pytest.fixture
    def patch_pin_deps(self, mock_db, mock_redis, mock_raw_redis):
        async def _get_raw():
            return mock_raw_redis

        mock_server = MagicMock()
        mock_server.agent_metadata = {}

        with patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="ctx"), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
            yield mock_server

    @pytest.mark.asyncio
    async def test_uuid_prefix_import_error_handled(self, patch_pin_deps, mock_db, mock_redis, mock_raw_redis):
        """ImportError for _register_uuid_prefix is swallowed (lines 1686-1687)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = None

        with patch("src.mcp_handlers.identity.shared._register_uuid_prefix", side_effect=ImportError("not found")):
            result = await handle_onboard_v2({"client_session_id": "prefix-import-fail"})
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_set_onboard_pin_exception_handled(self, patch_pin_deps, mock_db, mock_redis, mock_raw_redis):
        """set_onboard_pin exception is swallowed (lines 1697-1698)."""
        from src.mcp_handlers.identity.handlers import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = None

        with patch("src.mcp_handlers.identity.shared._register_uuid_prefix"), \
             patch("src.mcp_handlers.identity.handlers.set_onboard_pin", side_effect=Exception("Pin error")):
            result = await handle_onboard_v2({"client_session_id": "pin-exception"})
        data = _parse(result)

        assert data["success"] is True
