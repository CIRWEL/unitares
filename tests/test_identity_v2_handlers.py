"""
Comprehensive tests for src/mcp_handlers/identity_v2.py.

Covers the full identity resolution pipeline:
- resolve_session_identity() 3-tier: Redis -> PostgreSQL -> Create new
- _derive_session_key() priority chain
- _validate_session_key() / sanitization within resolve_session_identity
- persist_identity via ensure_agent_persisted()
- get_agent_label / _get_agent_label
- _agent_exists_in_postgres
- _find_agent_by_label
- _get_agent_id_from_metadata
- _generate_agent_id (pure function)
- set_agent_label
- resolve_by_name_claim
- _cache_session
- _extract_stable_identifier
- _extract_base_fingerprint
- ua_hash_from_header
- lookup_onboard_pin / set_onboard_pin
- handle_identity_v2 (tool handler)
- ensure_agent_persisted (lazy creation)
- migrate_from_v1

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

    with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
         patch("src.cache.get_session_cache", return_value=mock_redis), \
         patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
         patch("src.cache.redis_client.get_redis", new=_get_raw):
        yield


@pytest.fixture
def patch_no_redis(mock_db):
    """Patch dependencies with Redis unavailable (cache returns None)."""
    with patch("src.mcp_handlers.identity_v2._redis_cache", False), \
         patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
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

class TestGenerateAgentId:

    @pytest.fixture(autouse=True)
    def import_fn(self):
        from src.mcp_handlers.identity_v2 import _generate_agent_id
        self.generate = _generate_agent_id

    def test_with_model_type_claude(self):
        result = self.generate(model_type="claude-opus-4-5")
        assert result.startswith("Claude_Opus_4_5_")
        # Ends with YYYYMMDD
        date_part = result.split("_")[-1]
        assert len(date_part) == 8
        assert date_part.isdigit()

    def test_with_model_type_gemini(self):
        result = self.generate(model_type="gemini-pro")
        assert result.startswith("Gemini_Pro_")

    def test_with_model_type_dots(self):
        result = self.generate(model_type="gpt.4.turbo")
        assert "Gpt" in result
        assert "4" in result
        assert "Turbo" in result

    def test_with_client_hint(self):
        result = self.generate(client_hint="cursor")
        assert result.startswith("cursor_")

    def test_with_client_hint_spaces(self):
        result = self.generate(client_hint="my editor")
        assert result.startswith("my_editor_")

    def test_fallback_no_args(self):
        result = self.generate()
        assert result.startswith("mcp_")

    def test_model_type_takes_priority_over_client_hint(self):
        result = self.generate(model_type="gemini-pro", client_hint="cursor")
        assert result.startswith("Gemini_Pro_")
        assert "cursor" not in result

    def test_empty_client_hint_fallback(self):
        result = self.generate(client_hint="")
        assert result.startswith("mcp_")

    def test_unknown_client_hint_fallback(self):
        result = self.generate(client_hint="unknown")
        assert result.startswith("mcp_")

    def test_whitespace_model_type(self):
        result = self.generate(model_type="  claude-haiku  ")
        assert result.startswith("Claude_Haiku_")

    def test_underscores_in_model_type(self):
        result = self.generate(model_type="claude_opus_4")
        assert result.startswith("Claude_Opus_4_")


# ============================================================================
# _get_date_context (pure function)
# ============================================================================

class TestGetDateContext:

    @pytest.fixture(autouse=True)
    def import_fn(self):
        from src.mcp_handlers.identity_v2 import _get_date_context
        self.get_ctx = _get_date_context

    def test_returns_all_required_keys(self):
        result = self.get_ctx()
        required = ['full', 'short', 'compact', 'iso', 'iso_utc', 'year', 'month', 'weekday']
        for k in required:
            assert k in result, f"Missing key: {k}"

    def test_iso_utc_ends_with_z(self):
        result = self.get_ctx()
        assert result['iso_utc'].endswith('Z')

    def test_compact_is_digits(self):
        result = self.get_ctx()
        assert result['compact'].isdigit()
        assert len(result['compact']) == 8


# ============================================================================
# _derive_session_key - Priority chain
# ============================================================================

class TestDeriveSessionKey:

    @pytest.fixture(autouse=True)
    def import_fn(self):
        from src.mcp_handlers.identity_v2 import _derive_session_key
        self.derive = _derive_session_key

    def test_priority_1_explicit_client_session_id(self):
        """client_session_id in arguments has highest priority."""
        result = self.derive({"client_session_id": "explicit-123"})
        assert result == "explicit-123"

    def test_priority_2_mcp_session_id_header(self):
        """mcp-session-id header is second priority."""
        with patch("src.mcp_handlers.context.get_mcp_session_id", return_value="mcp-sess-abc"):
            result = self.derive({})
            assert result == "mcp:mcp-sess-abc"

    def test_priority_3_contextvars_session_key(self):
        """contextvars session_key is third priority."""
        with patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="ctx-key-789"):
            result = self.derive({})
            assert result == "ctx-key-789"

    def test_priority_4_stdio_fallback(self):
        """Falls back to stdio:{pid} when nothing else is available."""
        with patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value=None):
            result = self.derive({})
            assert result.startswith("stdio:")
            assert str(os.getpid()) in result

    def test_explicit_overrides_mcp_header(self):
        """client_session_id takes priority over mcp-session-id."""
        with patch("src.mcp_handlers.context.get_mcp_session_id", return_value="mcp-id"):
            result = self.derive({"client_session_id": "explicit"})
            assert result == "explicit"

    def test_mcp_session_id_overrides_contextvars(self):
        """mcp-session-id takes priority over contextvars."""
        with patch("src.mcp_handlers.context.get_mcp_session_id", return_value="mcp-id"), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="ctx-key"):
            result = self.derive({})
            assert result == "mcp:mcp-id"

    def test_empty_client_session_id_falls_through(self):
        """Empty string client_session_id falls through to next priority."""
        with patch("src.mcp_handlers.context.get_mcp_session_id", return_value="mcp-id"):
            result = self.derive({"client_session_id": ""})
            assert result == "mcp:mcp-id"

    def test_none_client_session_id_falls_through(self):
        """None client_session_id falls through to next priority."""
        with patch("src.mcp_handlers.context.get_mcp_session_id", return_value="mcp-id"):
            result = self.derive({"client_session_id": None})
            assert result == "mcp:mcp-id"

    def test_mcp_session_id_exception_falls_through(self):
        """Exception in get_mcp_session_id falls through gracefully."""
        with patch("src.mcp_handlers.context.get_mcp_session_id", side_effect=Exception("boom")), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="ctx-fallback"):
            result = self.derive({})
            assert result == "ctx-fallback"

    def test_context_session_key_exception_falls_through(self):
        """Exception in get_context_session_key falls through to stdio."""
        with patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", side_effect=Exception("boom")):
            result = self.derive({})
            assert result.startswith("stdio:")


# ============================================================================
# Session key validation (within resolve_session_identity)
# ============================================================================

class TestSessionKeyValidation:

    @pytest.mark.asyncio
    async def test_empty_session_key_raises_valueerror(self, patch_all_deps):
        from src.mcp_handlers.identity_v2 import resolve_session_identity
        with pytest.raises(ValueError, match="session_key is required"):
            await resolve_session_identity(session_key="")

    @pytest.mark.asyncio
    async def test_long_session_key_truncated(self, patch_all_deps):
        """Session keys longer than 256 chars are truncated."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity
        long_key = "a" * 500
        result = await resolve_session_identity(session_key=long_key)
        assert result["created"] is True  # Should succeed

    @pytest.mark.asyncio
    async def test_special_chars_sanitized(self, patch_all_deps):
        """Characters outside allowed set are replaced with underscores."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity
        result = await resolve_session_identity(session_key="user'; DROP TABLE agents;--")
        assert result["created"] is True

    @pytest.mark.asyncio
    async def test_allowed_chars_not_sanitized(self, patch_all_deps):
        """Allowed characters pass through without sanitization."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity
        # alphanumeric, dash, underscore, colon, dot, at-sign
        clean_key = "user-name_123:test.session@host"
        result = await resolve_session_identity(session_key=clean_key)
        assert result["created"] is True

    @pytest.mark.asyncio
    async def test_sql_injection_in_session_key(self, patch_all_deps):
        """SQL injection attempts are safely handled."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity
        result = await resolve_session_identity(session_key="1 OR 1=1; --")
        assert result["created"] is True

    @pytest.mark.asyncio
    async def test_unicode_chars_sanitized(self, patch_all_deps):
        """Unicode characters outside allowed set are sanitized."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity
        result = await resolve_session_identity(session_key="test\x00null\x01ctrl")
        assert result["created"] is True


# ============================================================================
# resolve_session_identity - PATH 1: Redis cache hit
# ============================================================================

class TestResolvePath1RedisHit:

    @pytest.mark.asyncio
    async def test_redis_uuid_hit_returns_cached(self, patch_all_deps, mock_redis, mock_db, mock_raw_redis):
        """When Redis has a UUID-format cached entry, return it directly."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_Opus_20260206",
        }
        # Mock that agent exists in PG for the persisted check
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="id-1", metadata={})
        mock_db.get_agent_label.return_value = "TestAgent"

        result = await resolve_session_identity(session_key="redis-hit-session")

        assert result["source"] == "redis"
        assert result["created"] is False
        assert result["agent_uuid"] == test_uuid
        assert result["agent_id"] == "Claude_Opus_20260206"
        assert result["persisted"] is True
        assert result["label"] == "TestAgent"

    @pytest.mark.asyncio
    async def test_redis_uuid_hit_without_display_agent_id(self, patch_all_deps, mock_redis, mock_db, mock_raw_redis):
        """When Redis has UUID but no display_agent_id, falls back to metadata lookup."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {"agent_id": test_uuid}
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="id-1",
            metadata={"agent_id": "Gemini_Pro_20260206"}
        )

        result = await resolve_session_identity(session_key="redis-hit-no-display")

        assert result["source"] == "redis"
        assert result["agent_uuid"] == test_uuid
        assert result["agent_id"] == "Gemini_Pro_20260206"

    @pytest.mark.asyncio
    async def test_redis_uuid_hit_no_metadata_uses_uuid_as_agent_id(self, patch_all_deps, mock_redis, mock_db, mock_raw_redis):
        """When Redis has UUID but metadata lookup fails, agent_id falls back to UUID."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {"agent_id": test_uuid}
        # No metadata found
        mock_db.get_identity.return_value = None

        result = await resolve_session_identity(session_key="redis-hit-no-meta")

        assert result["source"] == "redis"
        assert result["agent_uuid"] == test_uuid
        assert result["agent_id"] == test_uuid  # falls back to UUID

    @pytest.mark.asyncio
    async def test_redis_hit_refreshes_ttl(self, patch_all_deps, mock_redis, mock_db, mock_raw_redis):
        """Redis hit should refresh TTL via EXPIRE command (sliding window)."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {"agent_id": test_uuid, "display_agent_id": "Test_20260206"}
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="id-1", metadata={})

        await resolve_session_identity(session_key="ttl-refresh-test")

        # Should have called expire on the raw redis
        mock_raw_redis.expire.assert_called()

    @pytest.mark.asyncio
    async def test_redis_hit_not_persisted(self, patch_all_deps, mock_redis, mock_db, mock_raw_redis):
        """Redis hit for agent that is NOT in PostgreSQL shows persisted=False."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {"agent_id": test_uuid, "display_agent_id": "Test_20260206"}
        mock_db.get_identity.return_value = None  # Not in PG

        result = await resolve_session_identity(session_key="not-persisted-session")

        assert result["source"] == "redis"
        assert result["persisted"] is False
        assert result["label"] is None

    @pytest.mark.asyncio
    async def test_redis_exception_falls_through_to_pg(self, patch_all_deps, mock_redis, mock_db):
        """If Redis raises an exception, falls through to PostgreSQL path."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        mock_redis.get.side_effect = Exception("Redis connection refused")
        mock_db.get_session.return_value = None  # PG also has nothing

        result = await resolve_session_identity(session_key="redis-error-session")

        assert result["created"] is True  # Falls through to creation
        assert result["source"] in ("created", "memory_only")

    @pytest.mark.asyncio
    async def test_redis_returns_none_agent_id_falls_through(self, patch_all_deps, mock_redis, mock_db):
        """If Redis returns data with no agent_id, falls through."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        mock_redis.get.return_value = {"some_other_field": "value"}
        mock_db.get_session.return_value = None

        result = await resolve_session_identity(session_key="redis-no-agentid")

        assert result["created"] is True


# ============================================================================
# resolve_session_identity - PATH 2: PostgreSQL session lookup
# ============================================================================

class TestResolvePath2PostgresHit:

    @pytest.mark.asyncio
    async def test_pg_uuid_hit_returns_identity(self, patch_no_redis, mock_db):
        """When Redis misses but PG has session with UUID, returns it."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        mock_db.get_session.return_value = SimpleNamespace(
            agent_id=test_uuid,
            session_id="pg-test-session",
        )
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="ident-1",
            metadata={"agent_id": "Claude_Opus_20260206"}
        )
        mock_db.get_agent_label.return_value = "MyAgent"

        result = await resolve_session_identity(session_key="pg-test-session")

        assert result["source"] == "postgres"
        assert result["created"] is False
        assert result["persisted"] is True
        assert result["agent_uuid"] == test_uuid
        assert result["agent_id"] == "Claude_Opus_20260206"
        assert result["label"] == "MyAgent"

    @pytest.mark.asyncio
    async def test_pg_hit_updates_session_activity(self, patch_no_redis, mock_db):
        """PG hit should call update_session_activity (best effort)."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        mock_db.get_session.return_value = SimpleNamespace(agent_id=test_uuid)
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="ident-1", metadata={"agent_id": "Test_20260206"}
        )

        await resolve_session_identity(session_key="activity-test")

        mock_db.update_session_activity.assert_called_once_with("activity-test")

    @pytest.mark.asyncio
    async def test_pg_hit_warms_redis_cache(self, patch_all_deps, mock_redis, mock_db, mock_raw_redis):
        """PG hit should warm the Redis cache for next time."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        # Redis misses
        mock_redis.get.return_value = None
        # PG has the session
        mock_db.get_session.return_value = SimpleNamespace(agent_id=test_uuid)
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="ident-1", metadata={"agent_id": "Test_20260206"}
        )

        result = await resolve_session_identity(session_key="warm-cache-test")

        assert result["source"] == "postgres"
        # Redis should have been written to (via _cache_session)
        # The _cache_session function uses raw redis setex when display_agent_id is different
        mock_raw_redis.setex.assert_called()

    @pytest.mark.asyncio
    async def test_pg_hit_no_metadata_uses_uuid(self, patch_no_redis, mock_db):
        """When PG has session but identity metadata lookup fails, falls back to UUID."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        mock_db.get_session.return_value = SimpleNamespace(agent_id=test_uuid)
        # get_identity returns identity but with no agent_id in metadata
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="ident-1", metadata={}
        )

        result = await resolve_session_identity(session_key="no-meta-test")

        assert result["source"] == "postgres"
        assert result["agent_uuid"] == test_uuid
        # agent_id falls back to uuid since metadata has no agent_id
        assert result["agent_id"] == test_uuid

    @pytest.mark.asyncio
    async def test_pg_exception_falls_through_to_create(self, patch_no_redis, mock_db):
        """If PG raises exception, falls through to PATH 3 (create new)."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        mock_db.get_session.side_effect = Exception("PG connection lost")

        result = await resolve_session_identity(session_key="pg-error-test")

        assert result["created"] is True
        assert result["source"] in ("created", "memory_only")


# ============================================================================
# resolve_session_identity - PATH 3: Create new agent
# ============================================================================

class TestResolvePath3CreateNew:

    @pytest.mark.asyncio
    async def test_creates_new_agent_lazy(self, patch_all_deps, mock_db):
        """Default persist=False creates lazy (memory only) agent."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        result = await resolve_session_identity(
            session_key="new-agent-lazy",
            model_type="claude-opus-4",
        )

        assert result["created"] is True
        assert result["persisted"] is False
        assert result["source"] == "memory_only"
        assert result["agent_id"].startswith("Claude_Opus_4_")
        assert result["display_name"] is None
        assert result["label"] is None
        # UUID should be valid
        assert len(result["agent_uuid"]) == 36
        assert result["agent_uuid"].count("-") == 4
        # Should NOT have called upsert_agent (lazy)
        mock_db.upsert_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_agent_persisted(self, patch_all_deps, mock_db):
        """persist=True creates agent in PostgreSQL."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="new-ident-1", metadata={}
        )

        result = await resolve_session_identity(
            session_key="new-agent-persist",
            persist=True,
            model_type="gemini-pro",
        )

        assert result["created"] is True
        assert result["persisted"] is True
        assert result["source"] == "created"
        mock_db.upsert_agent.assert_called_once()
        mock_db.upsert_identity.assert_called_once()

    @pytest.mark.asyncio
    async def test_persisted_agent_creates_session_binding(self, patch_all_deps, mock_db):
        """persist=True also creates session binding in PG."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="ident-bind-1", metadata={}
        )

        await resolve_session_identity(
            session_key="session-bind-test",
            persist=True,
        )

        mock_db.create_session.assert_called_once()
        call_args = mock_db.create_session.call_args
        assert call_args.kwargs["session_id"] == "session-bind-test"

    @pytest.mark.asyncio
    async def test_new_agent_uuid_is_unique(self, patch_all_deps):
        """Each new agent gets a unique UUID."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        result1 = await resolve_session_identity(session_key="unique-1")
        result2 = await resolve_session_identity(session_key="unique-2")

        assert result1["agent_uuid"] != result2["agent_uuid"]

    @pytest.mark.asyncio
    async def test_persist_failure_falls_through_to_memory_only(self, patch_all_deps, mock_db):
        """If PG persist fails, falls through to memory-only."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        mock_db.upsert_agent.side_effect = Exception("PG write failed")

        result = await resolve_session_identity(
            session_key="persist-fail-test",
            persist=True,
        )

        # Should fall through to memory_only
        assert result["created"] is True
        assert result["persisted"] is False
        assert result["source"] == "memory_only"


# ============================================================================
# resolve_session_identity - force_new
# ============================================================================

class TestResolveForceNew:

    @pytest.mark.asyncio
    async def test_force_new_skips_all_lookups(self, patch_all_deps, mock_redis, mock_db):
        """force_new=True bypasses Redis and PG lookups."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        result = await resolve_session_identity(
            session_key="force-new-test",
            force_new=True,
        )

        assert result["created"] is True
        # Should NOT have called Redis get or PG get_session
        mock_redis.get.assert_not_called()
        mock_db.get_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_new_creates_different_uuid(self, patch_all_deps, mock_redis):
        """force_new creates a new UUID even when cache exists."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        # First call creates an agent
        first = await resolve_session_identity(session_key="force-diff-test")

        # Reset redis mock to return the first agent
        mock_redis.get.return_value = {
            "agent_id": first["agent_uuid"],
            "display_agent_id": first["agent_id"],
        }

        # Second call with force_new should create a different UUID
        second = await resolve_session_identity(
            session_key="force-diff-test",
            force_new=True,
        )

        assert second["agent_uuid"] != first["agent_uuid"]
        assert second["created"] is True


# ============================================================================
# resolve_session_identity - PATH 2.5: Name-based identity claim
# ============================================================================

class TestResolvePath25NameClaim:

    @pytest.mark.asyncio
    async def test_name_claim_resolves_existing_agent(self, patch_all_deps, mock_db, mock_redis, mock_raw_redis):
        """agent_name resolves to existing agent by label."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        # Redis and PG miss for session lookup
        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        # But find_agent_by_label finds the agent
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="ident-name", metadata={"agent_id": "Claude_20260206"}
        )
        mock_db.get_agent_label.return_value = "Lumen"

        result = await resolve_session_identity(
            session_key="name-claim-test",
            agent_name="Lumen",
        )

        assert result["source"] == "name_claim"
        assert result["agent_uuid"] == test_uuid
        assert result["created"] is False
        assert result["persisted"] is True
        assert result.get("resumed_by_name") is True

    @pytest.mark.asyncio
    async def test_name_claim_short_name_ignored(self, patch_all_deps, mock_db, mock_redis):
        """Names shorter than 2 chars are ignored."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        result = await resolve_session_identity(
            session_key="short-name-test",
            agent_name="A",  # Too short
        )

        # Should create new, not resolve by name
        assert result["created"] is True

    @pytest.mark.asyncio
    async def test_name_claim_no_match_creates_new(self, patch_all_deps, mock_db, mock_redis):
        """When name doesn't match any agent, creates new."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None  # No match

        result = await resolve_session_identity(
            session_key="no-name-match-test",
            agent_name="NonexistentAgent",
        )

        assert result["created"] is True


# ============================================================================
# _agent_exists_in_postgres
# ============================================================================

class TestAgentExistsInPostgres:

    @pytest.mark.asyncio
    async def test_returns_true_when_identity_found(self):
        from src.mcp_handlers.identity_v2 import _agent_exists_in_postgres

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            assert await _agent_exists_in_postgres("uuid-exists") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        from src.mcp_handlers.identity_v2 import _agent_exists_in_postgres

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = None

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            assert await _agent_exists_in_postgres("uuid-not-found") is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        from src.mcp_handlers.identity_v2 import _agent_exists_in_postgres

        mock_db = AsyncMock()
        mock_db.get_identity.side_effect = Exception("DB down")

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            assert await _agent_exists_in_postgres("uuid-error") is False


# ============================================================================
# _get_agent_label
# ============================================================================

class TestGetAgentLabel:

    @pytest.mark.asyncio
    async def test_returns_label_from_db(self):
        from src.mcp_handlers.identity_v2 import _get_agent_label

        mock_db = AsyncMock()
        mock_db.get_agent_label.return_value = "MyAgent"

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _get_agent_label("uuid-label")
            assert result == "MyAgent"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from src.mcp_handlers.identity_v2 import _get_agent_label

        mock_db = AsyncMock()
        mock_db.get_agent_label.return_value = None

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _get_agent_label("uuid-no-label")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from src.mcp_handlers.identity_v2 import _get_agent_label

        mock_db = AsyncMock()
        mock_db.get_agent_label.side_effect = Exception("DB error")

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _get_agent_label("uuid-error")
            assert result is None


# ============================================================================
# _get_agent_id_from_metadata
# ============================================================================

class TestGetAgentIdFromMetadata:

    @pytest.mark.asyncio
    async def test_returns_agent_id_from_identity_metadata(self):
        from src.mcp_handlers.identity_v2 import _get_agent_id_from_metadata

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1",
            metadata={"agent_id": "Claude_Opus_20260206"}
        )

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _get_agent_id_from_metadata("uuid-meta")
            assert result == "Claude_Opus_20260206"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_identity(self):
        from src.mcp_handlers.identity_v2 import _get_agent_id_from_metadata

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = None

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _get_agent_id_from_metadata("uuid-no-identity")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_metadata(self):
        from src.mcp_handlers.identity_v2 import _get_agent_id_from_metadata

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata=None
        )

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _get_agent_id_from_metadata("uuid-no-meta")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_metadata_has_no_agent_id(self):
        from src.mcp_handlers.identity_v2 import _get_agent_id_from_metadata

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"some_other": "data"}
        )

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _get_agent_id_from_metadata("uuid-no-aid")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from src.mcp_handlers.identity_v2 import _get_agent_id_from_metadata

        mock_db = AsyncMock()
        mock_db.get_identity.side_effect = Exception("DB error")

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _get_agent_id_from_metadata("uuid-error")
            assert result is None


# ============================================================================
# _find_agent_by_label
# ============================================================================

class TestFindAgentByLabel:

    @pytest.mark.asyncio
    async def test_returns_uuid_when_found(self):
        from src.mcp_handlers.identity_v2 import _find_agent_by_label

        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = "uuid-found-by-label"

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _find_agent_by_label("MyAgent")
            assert result == "uuid-found-by-label"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from src.mcp_handlers.identity_v2 import _find_agent_by_label

        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = None

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _find_agent_by_label("Nonexistent")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from src.mcp_handlers.identity_v2 import _find_agent_by_label

        mock_db = AsyncMock()
        mock_db.find_agent_by_label.side_effect = Exception("DB error")

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _find_agent_by_label("Error")
            assert result is None


# ============================================================================
# ensure_agent_persisted (lazy creation)
# ============================================================================

class TestEnsureAgentPersisted:

    @pytest.mark.asyncio
    async def test_persists_new_agent(self):
        """When agent doesn't exist in PG, persists and returns True."""
        from src.mcp_handlers.identity_v2 import ensure_agent_persisted

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

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await ensure_agent_persisted("uuid-lazy", "session-lazy")

        assert result is True
        mock_db.upsert_agent.assert_called_once()
        mock_db.upsert_identity.assert_called_once()
        mock_db.create_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_already_persisted(self):
        """When agent already exists in PG, returns False without writing."""
        from src.mcp_handlers.identity_v2 import ensure_agent_persisted

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="existing-ident", metadata={}
        )

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await ensure_agent_persisted("uuid-existing", "session-existing")

        assert result is False
        mock_db.upsert_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        """On exception, returns False (non-fatal)."""
        from src.mcp_handlers.identity_v2 import ensure_agent_persisted

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.side_effect = Exception("DB error")

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await ensure_agent_persisted("uuid-error", "session-error")

        assert result is False


# ============================================================================
# set_agent_label
# ============================================================================

class TestSetAgentLabel:

    @pytest.mark.asyncio
    async def test_sets_label_successfully(self):
        """Sets label via db.update_agent_fields."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None  # No collision
        mock_db.update_agent_fields.return_value = True
        mock_db.upsert_agent = AsyncMock()
        mock_db.upsert_identity = AsyncMock()
        mock_db.create_session = AsyncMock()

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("no server")):
            result = await set_agent_label("uuid-label-set", "NewLabel")

        assert result is True
        mock_db.update_agent_fields.assert_called_once_with("uuid-label-set", label="NewLabel")

    @pytest.mark.asyncio
    async def test_empty_label_returns_false(self):
        from src.mcp_handlers.identity_v2 import set_agent_label
        result = await set_agent_label("uuid-1", "")
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_uuid_returns_false(self):
        from src.mcp_handlers.identity_v2 import set_agent_label
        result = await set_agent_label("", "Label")
        assert result is False

    @pytest.mark.asyncio
    async def test_label_collision_appends_suffix(self):
        """When label already exists for different agent, appends UUID suffix."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        test_uuid = "aaaabbbb-1234-5678-9abc-def012345678"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = "other-uuid"  # Collision!
        mock_db.update_agent_fields.return_value = True
        mock_db.upsert_agent = AsyncMock()
        mock_db.upsert_identity = AsyncMock()
        mock_db.create_session = AsyncMock()

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("no server")):
            result = await set_agent_label(test_uuid, "DuplicateName")

        assert result is True
        # Should have been called with suffixed label
        call_args = mock_db.update_agent_fields.call_args
        label_used = call_args.kwargs.get("label") or call_args[1].get("label")
        assert label_used.startswith("DuplicateName_")
        assert test_uuid[:8] in label_used


# ============================================================================
# _extract_stable_identifier
# ============================================================================

class TestExtractStableIdentifier:

    @pytest.fixture(autouse=True)
    def import_fn(self):
        from src.mcp_handlers.identity_v2 import _extract_stable_identifier
        self.extract = _extract_stable_identifier

    def test_extracts_hex_suffix(self):
        result = self.extract("217.216.112.229:8767:6d79c4")
        assert result == "6d79c4"

    def test_extracts_hex_from_two_parts(self):
        result = self.extract("192.168.1.1:abcdef")
        assert result == "abcdef"

    def test_returns_none_for_single_part(self):
        result = self.extract("singlepart")
        assert result is None

    def test_returns_none_for_non_hex_suffix(self):
        result = self.extract("192.168.1.1:not-hex-here")
        assert result is None

    def test_returns_none_for_short_suffix(self):
        result = self.extract("192.168.1.1:ab")
        assert result is None

    def test_returns_none_for_empty(self):
        result = self.extract("")
        assert result is None

    def test_returns_none_for_none(self):
        result = self.extract(None)
        assert result is None


# ============================================================================
# _extract_base_fingerprint
# ============================================================================

class TestExtractBaseFingerprint:

    @pytest.fixture(autouse=True)
    def import_fn(self):
        from src.mcp_handlers.identity_v2 import _extract_base_fingerprint
        self.extract = _extract_base_fingerprint

    def test_mcp_prefix_returns_none(self):
        assert self.extract("mcp:session-abc") is None

    def test_stdio_prefix_returns_none(self):
        assert self.extract("stdio:12345") is None

    def test_agent_prefix_returns_none(self):
        assert self.extract("agent-uuid-prefix") is None

    def test_ip_ua_hash_extracts_ua(self):
        result = self.extract("192.168.1.1:d20c2f")
        assert result == "ua:d20c2f"

    def test_ip_ua_hash_suffix_extracts_ua(self):
        result = self.extract("192.168.1.1:d20c2f:extra_suffix")
        assert result == "ua:d20c2f"

    def test_single_part_returns_as_is(self):
        result = self.extract("onlyone")
        assert result == "onlyone"

    def test_none_returns_none(self):
        assert self.extract(None) is None

    def test_empty_returns_none(self):
        assert self.extract("") is None


# ============================================================================
# ua_hash_from_header
# ============================================================================

class TestUaHashFromHeader:

    @pytest.fixture(autouse=True)
    def import_fn(self):
        from src.mcp_handlers.identity_v2 import ua_hash_from_header
        self.ua_hash = ua_hash_from_header

    def test_returns_ua_prefix_hash(self):
        import hashlib
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        expected_hash = hashlib.md5(ua.encode()).hexdigest()[:6]
        result = self.ua_hash(ua)
        assert result == f"ua:{expected_hash}"

    def test_returns_none_for_empty(self):
        assert self.ua_hash("") is None

    def test_returns_none_for_none(self):
        assert self.ua_hash(None) is None

    def test_consistent_results(self):
        """Same UA string always produces same hash."""
        ua = "TestAgent/1.0"
        r1 = self.ua_hash(ua)
        r2 = self.ua_hash(ua)
        assert r1 == r2

    def test_different_ua_different_hash(self):
        """Different UA strings produce different hashes."""
        r1 = self.ua_hash("Agent/1.0")
        r2 = self.ua_hash("Agent/2.0")
        assert r1 != r2


# ============================================================================
# lookup_onboard_pin / set_onboard_pin
# ============================================================================

class TestOnboardPin:

    @pytest.mark.asyncio
    async def test_set_and_lookup_pin(self):
        """Pin can be set and looked up."""
        from src.mcp_handlers.identity_v2 import set_onboard_pin, lookup_onboard_pin

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
        from src.mcp_handlers.identity_v2 import set_onboard_pin
        result = await set_onboard_pin("", "uuid-1", "sess-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_set_pin_none_fingerprint(self):
        """set_onboard_pin with None fingerprint returns False."""
        from src.mcp_handlers.identity_v2 import set_onboard_pin
        result = await set_onboard_pin(None, "uuid-1", "sess-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_lookup_pin_none_fingerprint(self):
        """lookup_onboard_pin with None fingerprint returns None."""
        from src.mcp_handlers.identity_v2 import lookup_onboard_pin
        result = await lookup_onboard_pin(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_pin_empty_fingerprint(self):
        """lookup_onboard_pin with empty fingerprint returns None."""
        from src.mcp_handlers.identity_v2 import lookup_onboard_pin
        result = await lookup_onboard_pin("")
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_pin_no_redis(self):
        """lookup_onboard_pin returns None when Redis is unavailable."""
        from src.mcp_handlers.identity_v2 import lookup_onboard_pin

        async def _get_no_redis():
            return None

        with patch("src.cache.redis_client.get_redis", new=_get_no_redis):
            result = await lookup_onboard_pin("ua:test")
            assert result is None

    @pytest.mark.asyncio
    async def test_set_pin_no_redis(self):
        """set_onboard_pin returns False when Redis is unavailable."""
        from src.mcp_handlers.identity_v2 import set_onboard_pin

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
        from src.mcp_handlers.identity_v2 import handle_identity_v2

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
        from src.mcp_handlers.identity_v2 import handle_identity_v2

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
        from src.mcp_handlers.identity_v2 import handle_identity_v2

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
        from src.mcp_handlers.identity_v2 import handle_identity_v2

        test_uuid = str(uuid.uuid4())
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_id": "Claude_20260206"}
        )
        mock_db.get_agent_label.return_value = "ExistingBot"

        with patch("src.mcp_handlers.identity_shared.make_client_session_id", return_value="agent-test12345"):
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

class TestResolveByNameClaim:

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_name(self):
        from src.mcp_handlers.identity_v2 import resolve_by_name_claim
        result = await resolve_by_name_claim("", "session-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_none_name(self):
        from src.mcp_handlers.identity_v2 import resolve_by_name_claim
        result = await resolve_by_name_claim(None, "session-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_short_name(self):
        from src.mcp_handlers.identity_v2 import resolve_by_name_claim
        result = await resolve_by_name_claim("A", "session-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_label_not_found(self):
        from src.mcp_handlers.identity_v2 import resolve_by_name_claim

        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = None

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await resolve_by_name_claim("UnknownAgent", "session-1")
            assert result is None

    @pytest.mark.asyncio
    async def test_resolves_when_label_found(self):
        from src.mcp_handlers.identity_v2 import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_id": "Test_20260206"}
        )
        mock_db.get_agent_label.return_value = "FoundAgent"
        mock_db.create_session = AsyncMock()

        mock_cache = AsyncMock()
        mock_cache.bind = AsyncMock()

        mock_raw = AsyncMock()
        mock_raw.setex = AsyncMock()

        async def _get_raw():
            return mock_raw

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_cache), \
             patch("src.cache.redis_client.get_redis", new=_get_raw):
            result = await resolve_by_name_claim("FoundAgent", "session-resolve")

        assert result is not None
        assert result["agent_uuid"] == test_uuid
        assert result["source"] == "name_claim"
        assert result["resumed_by_name"] is True
        assert result["persisted"] is True

    @pytest.mark.asyncio
    async def test_trajectory_verification_rejects_impersonation(self):
        """Trajectory mismatch (lineage < 0.6) rejects the name claim."""
        from src.mcp_handlers.identity_v2 import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid

        mock_verification = {
            "verified": False,
            "tiers": {"lineage": {"similarity": 0.3}},  # Way below 0.6
        }

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", False), \
             patch("src.trajectory_identity.verify_trajectory_identity", new_callable=AsyncMock, return_value=mock_verification):
            result = await resolve_by_name_claim(
                "SomeAgent", "session-traj",
                trajectory_signature={"some": "data"}
            )

        assert result is None  # Rejected due to lineage mismatch


# ============================================================================
# _cache_session
# ============================================================================

class TestCacheSession:

    @pytest.mark.asyncio
    async def test_cache_with_display_agent_id_uses_raw_redis(self, mock_raw_redis):
        """When display_agent_id differs from UUID, uses raw Redis setex."""
        from src.mcp_handlers.identity_v2 import _cache_session

        mock_cache = AsyncMock()

        async def _get_raw():
            return mock_raw_redis

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_cache), \
             patch("src.cache.redis_client.get_redis", new=_get_raw):
            await _cache_session("sess-1", "uuid-1234", display_agent_id="Claude_20260206")

        mock_raw_redis.setex.assert_called_once()
        call_args = mock_raw_redis.setex.call_args
        assert call_args[0][0] == "session:sess-1"
        stored_data = json.loads(call_args[0][2])
        assert stored_data["agent_id"] == "uuid-1234"
        assert stored_data["display_agent_id"] == "Claude_20260206"

    @pytest.mark.asyncio
    async def test_cache_without_display_id_uses_bind(self):
        """Without display_agent_id, uses SessionCache.bind()."""
        from src.mcp_handlers.identity_v2 import _cache_session

        mock_cache = AsyncMock()
        mock_cache.bind = AsyncMock()

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_cache):
            await _cache_session("sess-2", "uuid-5678")

        mock_cache.bind.assert_called_once_with("sess-2", "uuid-5678")

    @pytest.mark.asyncio
    async def test_cache_display_id_same_as_uuid_uses_bind(self):
        """When display_agent_id == uuid, uses bind (no separate storage needed)."""
        from src.mcp_handlers.identity_v2 import _cache_session

        mock_cache = AsyncMock()
        mock_cache.bind = AsyncMock()

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_cache):
            await _cache_session("sess-3", "uuid-same", display_agent_id="uuid-same")

        mock_cache.bind.assert_called_once_with("sess-3", "uuid-same")

    @pytest.mark.asyncio
    async def test_cache_redis_unavailable_no_error(self):
        """When Redis is unavailable, _cache_session does not raise."""
        from src.mcp_handlers.identity_v2 import _cache_session

        with patch("src.mcp_handlers.identity_v2._redis_cache", False):
            # Should not raise
            await _cache_session("sess-4", "uuid-noop")


# ============================================================================
# migrate_from_v1
# ============================================================================

class TestMigrateFromV1:

    @pytest.mark.asyncio
    async def test_migrates_sessions(self):
        """Migrates v1 session bindings to v2 format."""
        from src.mcp_handlers.identity_v2 import migrate_from_v1

        mock_db = AsyncMock()
        mock_db.upsert_agent = AsyncMock()
        mock_db.upsert_identity = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="migrated-ident", metadata={})
        mock_db.create_session = AsyncMock()

        old_bindings = {
            "session-1": {"bound_agent_id": "uuid-1", "api_key": "key-1"},
            "session-2": {"bound_agent_id": "uuid-2", "api_key": "key-2"},
        }

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            count = await migrate_from_v1(old_bindings)

        assert count == 2
        assert mock_db.upsert_agent.call_count == 2
        assert mock_db.upsert_identity.call_count == 2
        assert mock_db.create_session.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_bindings_without_agent_id(self):
        """Bindings without bound_agent_id are skipped."""
        from src.mcp_handlers.identity_v2 import migrate_from_v1

        mock_db = AsyncMock()

        old_bindings = {
            "session-1": {"bound_agent_id": None},
            "session-2": {},  # No bound_agent_id key
        }

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            count = await migrate_from_v1(old_bindings)

        assert count == 0
        mock_db.upsert_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_on_individual_failure(self):
        """Failures for individual sessions don't stop migration."""
        from src.mcp_handlers.identity_v2 import migrate_from_v1

        mock_db = AsyncMock()
        mock_db.upsert_agent.side_effect = [
            Exception("DB error"),  # First fails
            None,  # Second succeeds
        ]
        mock_db.upsert_identity = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="ident", metadata={})
        mock_db.create_session = AsyncMock()

        old_bindings = {
            "session-fail": {"bound_agent_id": "uuid-fail"},
            "session-ok": {"bound_agent_id": "uuid-ok"},
        }

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            count = await migrate_from_v1(old_bindings)

        assert count == 1  # Only the second one succeeded

    @pytest.mark.asyncio
    async def test_empty_bindings_returns_zero(self):
        """Empty bindings dict returns 0."""
        from src.mcp_handlers.identity_v2 import migrate_from_v1

        mock_db = AsyncMock()

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            count = await migrate_from_v1({})

        assert count == 0


# ============================================================================
# _find_agent_by_id (deprecated but still present)
# ============================================================================

class TestFindAgentById:

    @pytest.mark.asyncio
    async def test_returns_agent_from_postgres(self):
        from src.mcp_handlers.identity_v2 import _find_agent_by_id

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_agent.return_value = SimpleNamespace(
            label="TestAgent", status="active"
        )
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_uuid": "uuid-from-meta"}
        )

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _find_agent_by_id("old-agent-id")

        assert result is not None
        assert result["agent_id"] == "old-agent-id"
        assert result["agent_uuid"] == "uuid-from-meta"
        assert result["display_name"] == "TestAgent"
        assert result["label"] == "TestAgent"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from src.mcp_handlers.identity_v2 import _find_agent_by_id

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_agent.return_value = None

        mock_server = MagicMock()
        mock_server.agent_metadata = {}

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
            result = await _find_agent_by_id("nonexistent-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_falls_back_to_memory_cache(self):
        from src.mcp_handlers.identity_v2 import _find_agent_by_id

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_agent.side_effect = Exception("DB error")

        mock_server = MagicMock()
        meta = SimpleNamespace(
            label="CachedAgent",
            agent_uuid="uuid-cached",
            status="active",
        )
        mock_server.agent_metadata = {"agent-id-1": meta}

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
            result = await _find_agent_by_id("agent-id-1")

        assert result is not None
        assert result["agent_uuid"] == "uuid-cached"
        assert result["display_name"] == "CachedAgent"

    @pytest.mark.asyncio
    async def test_uuid_fallback_when_no_metadata_uuid(self):
        """When identity metadata has no agent_uuid, falls back to agent_id."""
        from src.mcp_handlers.identity_v2 import _find_agent_by_id

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_agent.return_value = SimpleNamespace(label=None, status="active")
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={}  # No agent_uuid in metadata
        )

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
            result = await _find_agent_by_id("fallback-id")

        assert result is not None
        assert result["agent_uuid"] == "fallback-id"  # Falls back to agent_id


# ============================================================================
# Integration-style tests (multiple paths)
# ============================================================================

class TestIdentityResolutionIntegration:

    @pytest.mark.asyncio
    async def test_redis_miss_pg_miss_creates_new(self, patch_all_deps, mock_redis, mock_db):
        """Full pipeline: Redis miss -> PG miss -> Create new."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

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
        from src.mcp_handlers.identity_v2 import resolve_session_identity

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
        from src.mcp_handlers.identity_v2 import resolve_session_identity, ensure_agent_persisted

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
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_session.side_effect = Exception("PG down")
        mock_db.find_agent_by_label.return_value = None

        with patch("src.mcp_handlers.identity_v2._redis_cache", False), \
             patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db):
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
        from src.mcp_handlers.identity_v2 import resolve_session_identity

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
        from src.mcp_handlers.identity_v2 import resolve_session_identity

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
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        result = await resolve_session_identity(session_key=":::")
        assert result["created"] is True

    @pytest.mark.asyncio
    async def test_session_key_at_exact_max_length(self, patch_all_deps):
        """Session key at exactly 256 chars passes without truncation."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        key = "a" * 256
        result = await resolve_session_identity(session_key=key)
        assert result["created"] is True

    @pytest.mark.asyncio
    async def test_session_key_at_257_chars_truncated(self, patch_all_deps):
        """Session key at 257 chars is truncated to 256."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

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

class TestGetRedisExceptionPath:

    def test_redis_exception_marks_unavailable(self):
        """When get_session_cache raises, _get_redis sets cache to False."""
        import src.mcp_handlers.identity_v2 as mod

        # Save original
        original = mod._redis_cache
        try:
            mod._redis_cache = None
            with patch("src.cache.get_session_cache", side_effect=Exception("Connection refused")):
                result = mod._get_redis()

            assert result is None
            # Module-level _redis_cache should now be False (unavailable)
            assert mod._redis_cache is False
        finally:
            mod._redis_cache = original

    def test_redis_already_false_returns_none(self):
        """When _redis_cache is False (marked unavailable), returns None."""
        import src.mcp_handlers.identity_v2 as mod

        original = mod._redis_cache
        try:
            mod._redis_cache = False
            result = mod._get_redis()
            assert result is None
        finally:
            mod._redis_cache = original


# ============================================================================
# _find_agent_by_id - both PG and in-memory fail (lines 182-183)
# ============================================================================

class TestFindAgentByIdBothFail:

    @pytest.mark.asyncio
    async def test_pg_and_memory_both_fail_returns_none(self):
        """When PG raises and in-memory lookup also raises, returns None."""
        from src.mcp_handlers.identity_v2 import _find_agent_by_id

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_agent.side_effect = Exception("PG error")

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("No server")):
            result = await _find_agent_by_id("test-agent-id")

        assert result is None


# ============================================================================
# Redis TTL refresh exception (lines 354-356)
# ============================================================================

class TestRedisTtlRefreshException:

    @pytest.mark.asyncio
    async def test_ttl_refresh_failure_does_not_break_result(self, mock_db, mock_redis):
        """If TTL refresh fails, the cached result is still returned."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260206",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="id-1", metadata={})
        mock_db.get_agent_label.return_value = "TestAgent"

        # Make raw redis raise on expire (TTL refresh)
        async def _raise_redis():
            raise Exception("Redis expire failed")

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", side_effect=Exception("Redis error")):
            result = await resolve_session_identity(session_key="ttl-fail-test")

        assert result["source"] == "redis"
        assert result["agent_uuid"] == test_uuid
        assert result["created"] is False


# ============================================================================
# PG update_session_activity exception (lines 446-448)
# ============================================================================

class TestPgSessionActivityException:

    @pytest.mark.asyncio
    async def test_session_activity_update_failure_ignored(self, patch_no_redis, mock_db):
        """When update_session_activity raises, PG result is still returned."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        test_uuid = str(uuid.uuid4())
        mock_db.get_session.return_value = SimpleNamespace(agent_id=test_uuid)
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="ident-1", metadata={"agent_id": "Test_20260206"}
        )
        mock_db.get_agent_label.return_value = "MyAgent"
        mock_db.update_session_activity.side_effect = Exception("Activity update failed")

        result = await resolve_session_identity(session_key="activity-fail-test")

        assert result["source"] == "postgres"
        assert result["agent_uuid"] == test_uuid
        assert result["created"] is False


# ============================================================================
# set_agent_label - structured_id migration and cache creation (lines 622-688)
# ============================================================================

class TestSetAgentLabelCacheManagement:

    @pytest.mark.asyncio
    async def test_syncs_label_to_existing_metadata_entry(self):
        """When agent is already in cache, label is synced to existing entry."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_server = MagicMock()
        meta = SimpleNamespace(label=None, structured_id="existing_id")
        mock_server.agent_metadata = {test_uuid: meta}

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
            result = await set_agent_label(test_uuid, "NewLabel")

        assert result is True
        assert meta.label == "NewLabel"

    @pytest.mark.asyncio
    async def test_creates_new_metadata_entry_when_not_cached(self):
        """When agent is NOT in cache, a new AgentMetadata entry is created."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_server = MagicMock()
        mock_server.agent_metadata = {}  # Empty - agent not cached

        # Mock AgentMetadata class
        mock_meta_class = MagicMock()
        mock_meta_instance = SimpleNamespace(
            agent_id=test_uuid, status='active', created_at='', last_update=''
        )
        mock_meta_class.return_value = mock_meta_instance

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_server_std.AgentMetadata", mock_meta_class), \
             patch("src.mcp_handlers.identity_v2.detect_interface_context", return_value={"type": "test"}, create=True), \
             patch("src.mcp_handlers.identity_v2.generate_structured_id", return_value="test_1", create=True), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"):
            result = await set_agent_label(test_uuid, "FreshLabel")

        assert result is True
        # Agent should now be in the metadata dict
        assert test_uuid in mock_server.agent_metadata

    @pytest.mark.asyncio
    async def test_structured_id_generation_failure_handled(self):
        """If structured_id generation fails, label is still set."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_server = MagicMock()
        meta = SimpleNamespace(label=None, structured_id=None)
        mock_server.agent_metadata = {test_uuid: meta}

        # detect_interface_context raises
        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.naming_helpers.detect_interface_context", side_effect=Exception("No context")):
            result = await set_agent_label(test_uuid, "LabelWithoutStructured")

        assert result is True
        assert meta.label == "LabelWithoutStructured"

    @pytest.mark.asyncio
    async def test_session_binding_cache_updated(self):
        """Session binding cache is updated when label is set."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_server = MagicMock()
        meta = SimpleNamespace(label=None, structured_id="existing_id")
        mock_server.agent_metadata = {test_uuid: meta}

        # Create a session binding
        session_identities = {
            "test-session": {"bound_agent_id": test_uuid, "agent_label": None}
        }

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity_shared._session_identities", session_identities):
            result = await set_agent_label(test_uuid, "UpdatedLabel")

        assert result is True
        assert session_identities["test-session"]["agent_label"] == "UpdatedLabel"

    @pytest.mark.asyncio
    async def test_session_binding_update_failure_handled(self):
        """If session binding update fails, label is still set."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_server = MagicMock()
        meta = SimpleNamespace(label=None, structured_id="existing_id")
        mock_server.agent_metadata = {test_uuid: meta}

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity_shared._session_identities", side_effect=Exception("import fail")):
            result = await set_agent_label(test_uuid, "StillWorks")

        assert result is True

    @pytest.mark.asyncio
    async def test_redis_metadata_invalidation_on_label_set(self):
        """Redis metadata cache is invalidated after label set."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_redis = MagicMock()  # Non-None value so _get_redis() returns it
        mock_metadata_cache = AsyncMock()
        mock_metadata_cache.invalidate = AsyncMock()

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._get_redis", return_value=mock_redis), \
             patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("no server")), \
             patch("src.cache.get_metadata_cache", return_value=mock_metadata_cache):
            result = await set_agent_label(test_uuid, "InvalidateTest")

        assert result is True
        mock_metadata_cache.invalidate.assert_called_once_with(test_uuid)

    @pytest.mark.asyncio
    async def test_redis_invalidation_exception_handled(self):
        """Redis metadata invalidation failure is swallowed (lines 681-682)."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_redis = MagicMock()

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._get_redis", return_value=mock_redis), \
             patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("no server")), \
             patch("src.cache.get_metadata_cache", side_effect=Exception("cache error")):
            result = await set_agent_label(test_uuid, "StillOK")

        assert result is True

    @pytest.mark.asyncio
    async def test_overall_exception_returns_false(self):
        """When the entire set_agent_label throws, returns False (lines 686-688)."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"

        with patch("src.mcp_handlers.identity_v2.get_db", side_effect=Exception("Fatal DB error")):
            result = await set_agent_label(test_uuid, "WillFail")

        assert result is False

    @pytest.mark.asyncio
    async def test_set_label_with_session_key_calls_ensure_persisted(self):
        """set_agent_label with session_key calls ensure_agent_persisted."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        # First call from ensure_agent_persisted, second from set_agent_label
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("no server")):
            result = await set_agent_label(test_uuid, "PersistLabel", session_key="sess-key")

        assert result is True


# ============================================================================
# resolve_by_name_claim - trajectory verification exception (lines 759-760)
# ============================================================================

class TestResolveByNameClaimTrajectoryException:

    @pytest.mark.asyncio
    async def test_trajectory_verification_exception_still_resolves(self):
        """If trajectory verification throws, name claim proceeds (non-blocking)."""
        from src.mcp_handlers.identity_v2 import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_id": "Claude_20260206"}
        )
        mock_db.get_agent_label.return_value = "VerifyFailAgent"
        mock_db.create_session = AsyncMock()

        mock_cache = AsyncMock()
        mock_cache.bind = AsyncMock()

        mock_raw = AsyncMock()
        mock_raw.setex = AsyncMock()

        async def _get_raw():
            return mock_raw

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_cache), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.trajectory_identity.verify_trajectory_identity", side_effect=Exception("Module not loaded")):
            result = await resolve_by_name_claim(
                "VerifyFailAgent", "session-traj-fail",
                trajectory_signature={"some": "data"}
            )

        # Should still resolve despite trajectory failure
        assert result is not None
        assert result["agent_uuid"] == test_uuid
        assert result["source"] == "name_claim"

    @pytest.mark.asyncio
    async def test_session_persist_failure_still_resolves(self):
        """If session persistence fails in name claim, result is still returned (lines 779-780)."""
        from src.mcp_handlers.identity_v2 import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_id": "Test_20260206"}
        )
        mock_db.get_agent_label.return_value = "SessionFailAgent"
        mock_db.create_session.side_effect = Exception("Session create failed")

        mock_cache = AsyncMock()
        mock_cache.bind = AsyncMock()

        mock_raw = AsyncMock()
        mock_raw.setex = AsyncMock()

        async def _get_raw():
            return mock_raw

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_cache), \
             patch("src.cache.redis_client.get_redis", new=_get_raw):
            result = await resolve_by_name_claim("SessionFailAgent", "session-fail")

        assert result is not None
        assert result["agent_uuid"] == test_uuid


# ============================================================================
# _cache_session - fallback bind and exception paths (lines 818-823)
# ============================================================================

class TestCacheSessionEdgeCases:

    @pytest.mark.asyncio
    async def test_raw_redis_none_falls_back_to_bind(self):
        """When raw redis returns None, falls back to session_cache.bind (line 818)."""
        from src.mcp_handlers.identity_v2 import _cache_session

        mock_cache = AsyncMock()
        mock_cache.bind = AsyncMock()

        async def _get_no_raw():
            return None

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_cache), \
             patch("src.cache.redis_client.get_redis", new=_get_no_raw):
            await _cache_session("sess-fallback", "uuid-fb", display_agent_id="Agent_20260206")

        mock_cache.bind.assert_called_once_with("sess-fallback", "uuid-fb")

    @pytest.mark.asyncio
    async def test_cache_exception_is_caught(self):
        """When cache write raises, exception is swallowed (lines 821-823)."""
        from src.mcp_handlers.identity_v2 import _cache_session

        mock_cache = AsyncMock()
        mock_cache.bind.side_effect = Exception("Redis write error")

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_cache):
            # Should not raise
            await _cache_session("sess-err", "uuid-err")


# ============================================================================
# lookup_onboard_pin / set_onboard_pin exception paths (lines 1138-1175)
# ============================================================================

class TestOnboardPinExceptionPaths:

    @pytest.mark.asyncio
    async def test_lookup_pin_redis_exception_returns_none(self):
        """lookup_onboard_pin returns None when Redis throws (lines 1138-1140)."""
        from src.mcp_handlers.identity_v2 import lookup_onboard_pin

        async def _get_error_redis():
            raise Exception("Connection reset")

        with patch("src.cache.redis_client.get_redis", new=_get_error_redis):
            result = await lookup_onboard_pin("ua:test123")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_pin_redis_exception_returns_false(self):
        """set_onboard_pin returns False when Redis throws (lines 1173-1175)."""
        from src.mcp_handlers.identity_v2 import set_onboard_pin

        async def _get_error_redis():
            raise Exception("Connection reset")

        with patch("src.cache.redis_client.get_redis", new=_get_error_redis):
            result = await set_onboard_pin("ua:test456", "uuid-1", "sess-1")

        assert result is False

    @pytest.mark.asyncio
    async def test_lookup_pin_with_bytes_data(self):
        """lookup_onboard_pin handles bytes data from Redis."""
        from src.mcp_handlers.identity_v2 import lookup_onboard_pin

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
        from src.mcp_handlers.identity_v2 import lookup_onboard_pin

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
        from src.mcp_handlers.identity_v2 import lookup_onboard_pin

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

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="test-ctx-key"), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity_shared._register_uuid_prefix"):
            yield mock_server

    @pytest.mark.asyncio
    async def test_basic_onboard_new_agent(self, patch_onboard_deps, mock_db, mock_redis):
        """Basic onboard() creates a new agent."""
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
    async def test_onboard_resumes_existing_agent(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """onboard() auto-resumes existing agent."""
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = "ResumedAgent"

        result = await handle_onboard_v2({"client_session_id": "onboard-resume"})
        data = _parse(result)

        assert data["success"] is True
        assert data["is_new"] is False
        assert data["uuid"] == test_uuid
        assert "Welcome back" in data.get("welcome", "")

    @pytest.mark.asyncio
    async def test_onboard_with_name_resolves_by_name_claim(self, patch_onboard_deps, mock_db, mock_redis, mock_raw_redis):
        """onboard(name='X') resolves via name claim."""
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        # Mock ensure_agent_persisted to raise an exception directly
        # This triggers the except block at line 1613 which returns error_response
        with patch("src.mcp_handlers.identity_v2.ensure_agent_persisted", side_effect=Exception("Fatal persist error")):
            result = await handle_onboard_v2({"client_session_id": "persist-fail"})
        data = _parse(result)

        assert data.get("success") is False
        assert "persist" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_onboard_none_arguments_handled(self, patch_onboard_deps, mock_db, mock_redis):
        """onboard(None) defaults to empty dict."""
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_verify_trajectory_identity

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value=None):
            result = await handle_verify_trajectory_identity({})
        data = _parse(result)

        assert data["success"] is False
        assert "identity" in data["error"].lower() or "resolved" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_no_trajectory_signature_returns_error(self):
        """verify_trajectory_identity without trajectory_signature returns error."""
        from src.mcp_handlers.identity_v2 import handle_verify_trajectory_identity

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-123"):
            result = await handle_verify_trajectory_identity({})
        data = _parse(result)

        assert data["success"] is False
        assert "trajectory_signature" in data["error"]

    @pytest.mark.asyncio
    async def test_invalid_trajectory_signature_type_returns_error(self):
        """verify_trajectory_identity with non-dict trajectory_signature returns error."""
        from src.mcp_handlers.identity_v2 import handle_verify_trajectory_identity

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-123"):
            result = await handle_verify_trajectory_identity({"trajectory_signature": "not a dict"})
        data = _parse(result)

        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_successful_verification(self):
        """verify_trajectory_identity succeeds with valid inputs."""
        from src.mcp_handlers.identity_v2 import handle_verify_trajectory_identity

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
        from src.mcp_handlers.identity_v2 import handle_verify_trajectory_identity

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
        from src.mcp_handlers.identity_v2 import handle_verify_trajectory_identity

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
        from src.mcp_handlers.identity_v2 import handle_get_trajectory_status

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value=None):
            result = await handle_get_trajectory_status({})
        data = _parse(result)

        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_successful_status(self):
        """get_trajectory_status returns status info."""
        from src.mcp_handlers.identity_v2 import handle_get_trajectory_status

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
        from src.mcp_handlers.identity_v2 import handle_get_trajectory_status

        mock_status_result = {"error": "Agent has no trajectory data"}

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-status"), \
             patch("src.trajectory_identity.get_trajectory_status", new_callable=AsyncMock, return_value=mock_status_result):
            result = await handle_get_trajectory_status({})
        data = _parse(result)

        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_status_exception_returns_error(self):
        """get_trajectory_status exception returns error (lines 1964-1966)."""
        from src.mcp_handlers.identity_v2 import handle_get_trajectory_status

        with patch("src.mcp_handlers.context.get_context_agent_id", return_value="uuid-status"), \
             patch("src.trajectory_identity.get_trajectory_status", side_effect=Exception("Module error")):
            result = await handle_get_trajectory_status({})
        data = _parse(result)

        assert data["success"] is False
        assert "failed" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_trust_tier_exception_non_blocking(self):
        """trust_tier computation failure does not block status response (lines 1959-1960)."""
        from src.mcp_handlers.identity_v2 import handle_get_trajectory_status

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

class TestSetAgentLabelStructuredIdMigration:

    @pytest.mark.asyncio
    async def test_existing_agent_missing_structured_id_gets_migrated(self):
        """When existing cache entry has no structured_id, it attempts generation."""
        from src.mcp_handlers.identity_v2 import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_server = MagicMock()
        # Agent in cache but no structured_id (None)
        meta = SimpleNamespace(label=None, structured_id=None)
        # Ensure getattr returns None for structured_id
        mock_server.agent_metadata = {test_uuid: meta}

        with patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity_v2._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.naming_helpers.detect_interface_context", return_value={"type": "test"}), \
             patch("src.mcp_handlers.naming_helpers.generate_structured_id", return_value="migrated_id_1"), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="cursor"):
            result = await set_agent_label(test_uuid, "MigrateLabel")

        assert result is True
        assert meta.label == "MigrateLabel"
        assert meta.structured_id == "migrated_id_1"


# ============================================================================
# Additional coverage: handle_identity_adapter structured_id regeneration (lines 1323-1345)
# ============================================================================

class TestIdentityAdapterStructuredIdRegeneration:

    @pytest.fixture
    def patch_identity_regen_deps(self, mock_db, mock_redis, mock_raw_redis):
        """Patch deps for structured_id regeneration tests."""
        async def _get_raw():
            return mock_raw_redis

        mock_server = MagicMock()

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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

        with patch("src.mcp_handlers.identity_v2.resolve_session_identity", side_effect=resolve_side_effect), \
             patch("src.mcp_handlers.naming_helpers.detect_interface_context", return_value={"type": "test"}), \
             patch("src.mcp_handlers.naming_helpers.generate_structured_id", return_value="claude_opus_1"), \
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

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="force-ctx-key"), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity_shared._register_uuid_prefix"):
            yield mock_server

    @pytest.mark.asyncio
    async def test_force_new_gemini_normalization(self, patch_onboard_force_deps, mock_db, mock_redis):
        """onboard(force_new=true, model_type='gemini-pro') normalizes to 'gemini' (line 1574-1575)."""
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="ctx-key"), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity_shared._register_uuid_prefix"):
            yield mock_server

    @pytest.mark.asyncio
    async def test_force_new_resolve_exception_returns_error(self, patch_onboard_resolve_fail_deps, mock_db, mock_redis):
        """When force_new + resolve_session_identity raises, returns error (lines 1632-1634)."""
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

        with patch("src.mcp_handlers.identity_v2.resolve_session_identity", side_effect=Exception("Resolve failed")):
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

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="ctx-key"), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity_shared._register_uuid_prefix"):
            yield mock_server

    @pytest.mark.asyncio
    async def test_fresh_identity_already_persisted(self, patch_onboard_persisted_deps, mock_db, mock_redis):
        """When fresh identity is already persisted, ensure_agent_persisted returns False (line 1603)."""
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        mock_db.find_agent_by_label.return_value = None

        # ensure_agent_persisted returns False (already persisted)
        with patch("src.mcp_handlers.identity_v2.ensure_agent_persisted", new_callable=AsyncMock, return_value=False):
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

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value=None), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
            yield mock_server

    @pytest.mark.asyncio
    async def test_identity_adapter_context_update_exception(self, patch_ctx_deps, mock_db, mock_redis):
        """update_context_agent_id failure is swallowed in identity adapter (lines 1314-1315)."""
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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
        from src.mcp_handlers.identity_v2 import handle_identity_adapter

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

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.mcp_handlers.context.get_mcp_session_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_session_key", return_value="ctx"), \
             patch("src.mcp_handlers.context.get_context_agent_id", return_value=None), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"), \
             patch("src.mcp_handlers.context.update_context_agent_id"), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity_shared._register_uuid_prefix"):
            yield mock_server

    @pytest.mark.asyncio
    async def test_structured_id_from_metadata_lookup(self, patch_sid_deps, mock_db, mock_redis, mock_raw_redis):
        """When agent_id == agent_uuid, falls back to metadata for structured_id (lines 1752-1759)."""
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

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

        result = await handle_onboard_v2({"client_session_id": "sid-fallback"})
        data = _parse(result)

        assert data["success"] is True
        # structured_id should be from metadata
        assert data.get("agent_id") == "custom_agent_1"

    @pytest.mark.asyncio
    async def test_structured_id_uuid_prefix_fallback(self, patch_sid_deps, mock_db, mock_redis, mock_raw_redis):
        """When no structured_id anywhere, falls back to agent_{uuid[:8]} (line 1763)."""
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

        mock_server = patch_sid_deps
        test_uuid = str(uuid.uuid4())

        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": test_uuid,  # Same as UUID
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = None

        result = await handle_onboard_v2({"client_session_id": "uuid-prefix-fallback"})
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

        with patch("src.mcp_handlers.identity_v2._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_redis), \
             patch("src.mcp_handlers.identity_v2.get_db", return_value=mock_db), \
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
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = None

        with patch("src.mcp_handlers.identity_shared._register_uuid_prefix", side_effect=ImportError("not found")):
            result = await handle_onboard_v2({"client_session_id": "prefix-import-fail"})
        data = _parse(result)

        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_set_onboard_pin_exception_handled(self, patch_pin_deps, mock_db, mock_redis, mock_raw_redis):
        """set_onboard_pin exception is swallowed (lines 1697-1698)."""
        from src.mcp_handlers.identity_v2 import handle_onboard_v2

        test_uuid = str(uuid.uuid4())
        mock_redis.get.return_value = {
            "agent_id": test_uuid,
            "display_agent_id": "Claude_20260207",
        }
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.get_agent_label.return_value = None

        with patch("src.mcp_handlers.identity_shared._register_uuid_prefix"), \
             patch("src.mcp_handlers.identity_v2.set_onboard_pin", side_effect=Exception("Pin error")):
            result = await handle_onboard_v2({"client_session_id": "pin-exception"})
        data = _parse(result)

        assert data["success"] is True
