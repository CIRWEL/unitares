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

class TestGenerateAgentId:

    @pytest.fixture(autouse=True)
    def import_fn(self):
        from src.mcp_handlers.identity.handlers import _generate_agent_id
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

    def test_third_party_client_prefixed_with_model(self):
        result = self.generate(model_type="gemini-pro", client_hint="cursor")
        assert result.startswith("Cursor_Gemini_Pro_")

    def test_native_client_not_prefixed_with_model(self):
        result = self.generate(model_type="claude-opus-4-5", client_hint="claude_desktop")
        assert result.startswith("Claude_Opus_4_5_")
        assert "Desktop" not in result

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
        from src.mcp_handlers.identity.handlers import _get_date_context
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
# derive_session_key - Priority chain (signals=None uses context/stdio)
# ============================================================================

class TestNormalizeModelType:
    """Tests for model type normalization helper."""

    def test_claude_variants(self):
        from src.mcp_handlers.identity.handlers import _normalize_model_type
        assert _normalize_model_type("claude-opus-4-5") == "claude"
        assert _normalize_model_type("Claude-Sonnet-4") == "claude"
        assert _normalize_model_type("claude") == "claude"

    def test_gemini(self):
        from src.mcp_handlers.identity.handlers import _normalize_model_type
        assert _normalize_model_type("gemini-pro") == "gemini"

    def test_gpt(self):
        from src.mcp_handlers.identity.handlers import _normalize_model_type
        assert _normalize_model_type("gpt-4o") == "gpt"
        assert _normalize_model_type("chatgpt") == "gpt"

    def test_cursor(self):
        from src.mcp_handlers.identity.handlers import _normalize_model_type
        assert _normalize_model_type("cursor") == "composer"
        assert _normalize_model_type("composer") == "composer"

    def test_llama(self):
        from src.mcp_handlers.identity.handlers import _normalize_model_type
        assert _normalize_model_type("llama-3.1") == "llama"

    def test_unknown_passthrough(self):
        from src.mcp_handlers.identity.handlers import _normalize_model_type
        result = _normalize_model_type("mistral-7b")
        assert result == "mistral_7b"


# ============================================================================
# Session key validation (within resolve_session_identity)
# ============================================================================

class TestResolvePath25NameClaim:

    @pytest.mark.asyncio
    async def test_name_claim_resolves_existing_agent(self, patch_all_deps, mock_db, mock_redis, mock_raw_redis, monkeypatch):
        """agent_name resolves to existing agent by label (legacy mode).

        Under strict name-claim (v2.7.0 default) this path requires proof;
        this test covers the legacy escape-hatch behavior that remains
        available via UNITARES_STRICT_NAME_CLAIM=0 during the caller
        migration window."""
        monkeypatch.setenv("UNITARES_STRICT_NAME_CLAIM", "0")
        from src.mcp_handlers.identity.handlers import resolve_session_identity

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
        from src.mcp_handlers.identity.handlers import resolve_session_identity

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
        from src.mcp_handlers.identity.handlers import resolve_session_identity

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
        from src.mcp_handlers.identity.handlers import _agent_exists_in_postgres

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            assert await _agent_exists_in_postgres("uuid-exists") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        from src.mcp_handlers.identity.handlers import _agent_exists_in_postgres

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = None

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            assert await _agent_exists_in_postgres("uuid-not-found") is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        from src.mcp_handlers.identity.handlers import _agent_exists_in_postgres

        mock_db = AsyncMock()
        mock_db.get_identity.side_effect = Exception("DB down")

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            assert await _agent_exists_in_postgres("uuid-error") is False


# ============================================================================
# _get_agent_label
# ============================================================================

class TestGetAgentLabel:

    @pytest.mark.asyncio
    async def test_returns_label_from_db(self):
        from src.mcp_handlers.identity.handlers import _get_agent_label

        mock_db = AsyncMock()
        mock_db.get_agent_label.return_value = "MyAgent"

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await _get_agent_label("uuid-label")
            assert result == "MyAgent"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from src.mcp_handlers.identity.handlers import _get_agent_label

        mock_db = AsyncMock()
        mock_db.get_agent_label.return_value = None

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await _get_agent_label("uuid-no-label")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from src.mcp_handlers.identity.handlers import _get_agent_label

        mock_db = AsyncMock()
        mock_db.get_agent_label.side_effect = Exception("DB error")

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await _get_agent_label("uuid-error")
            assert result is None


# ============================================================================
# _get_agent_id_from_metadata
# ============================================================================

class TestGetAgentIdFromMetadata:

    @pytest.mark.asyncio
    async def test_returns_agent_id_from_identity_metadata(self):
        from src.mcp_handlers.identity.handlers import _get_agent_id_from_metadata

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1",
            metadata={"agent_id": "Claude_Opus_20260206"}
        )

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await _get_agent_id_from_metadata("uuid-meta")
            assert result == "Claude_Opus_20260206"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_identity(self):
        from src.mcp_handlers.identity.handlers import _get_agent_id_from_metadata

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = None

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await _get_agent_id_from_metadata("uuid-no-identity")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_metadata(self):
        from src.mcp_handlers.identity.handlers import _get_agent_id_from_metadata

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata=None
        )

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await _get_agent_id_from_metadata("uuid-no-meta")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_metadata_has_no_agent_id(self):
        from src.mcp_handlers.identity.handlers import _get_agent_id_from_metadata

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"some_other": "data"}
        )

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await _get_agent_id_from_metadata("uuid-no-aid")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from src.mcp_handlers.identity.handlers import _get_agent_id_from_metadata

        mock_db = AsyncMock()
        mock_db.get_identity.side_effect = Exception("DB error")

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await _get_agent_id_from_metadata("uuid-error")
            assert result is None


# ============================================================================
# _find_agent_by_label
# ============================================================================

class TestFindAgentByLabel:

    @pytest.mark.asyncio
    async def test_returns_uuid_when_found(self):
        from src.mcp_handlers.identity.handlers import _find_agent_by_label

        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = "uuid-found-by-label"

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await _find_agent_by_label("MyAgent")
            assert result == "uuid-found-by-label"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from src.mcp_handlers.identity.handlers import _find_agent_by_label

        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = None

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await _find_agent_by_label("Nonexistent")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from src.mcp_handlers.identity.handlers import _find_agent_by_label

        mock_db = AsyncMock()
        mock_db.find_agent_by_label.side_effect = Exception("DB error")

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await _find_agent_by_label("Error")
            assert result is None


# ============================================================================
# ensure_agent_persisted (lazy creation)
# ============================================================================

class TestSetAgentLabel:

    @pytest.mark.asyncio
    async def test_sets_label_successfully(self):
        """Sets label via db.update_agent_fields."""
        from src.mcp_handlers.identity.handlers import set_agent_label

        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None  # No collision
        mock_db.update_agent_fields.return_value = True
        mock_db.upsert_agent = AsyncMock()
        mock_db.upsert_identity = AsyncMock()
        mock_db.create_session = AsyncMock()

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("no server")):
            result = await set_agent_label("uuid-label-set", "NewLabel")

        assert result is True
        mock_db.update_agent_fields.assert_called_once_with("uuid-label-set", label="NewLabel")

    @pytest.mark.asyncio
    async def test_empty_label_returns_false(self):
        from src.mcp_handlers.identity.handlers import set_agent_label
        result = await set_agent_label("uuid-1", "")
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_uuid_returns_false(self):
        from src.mcp_handlers.identity.handlers import set_agent_label
        result = await set_agent_label("", "Label")
        assert result is False

    @pytest.mark.asyncio
    async def test_label_collision_appends_suffix(self):
        """When label already exists for different agent, appends UUID suffix."""
        from src.mcp_handlers.identity.handlers import set_agent_label

        test_uuid = "aaaabbbb-1234-5678-9abc-def012345678"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = "other-uuid"  # Collision!
        mock_db.update_agent_fields.return_value = True
        mock_db.upsert_agent = AsyncMock()
        mock_db.upsert_identity = AsyncMock()
        mock_db.create_session = AsyncMock()

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("no server")):
            result = await set_agent_label(test_uuid, "DuplicateName")

        assert result is True
        # Should have been called with suffixed label
        call_args = mock_db.update_agent_fields.call_args
        label_used = call_args.kwargs.get("label") or call_args[1].get("label")
        assert label_used.startswith("DuplicateName_")
        assert test_uuid[:8] in label_used


# ============================================================================
# _extract_base_fingerprint
# ============================================================================

class TestExtractBaseFingerprint:

    @pytest.fixture(autouse=True)
    def import_fn(self):
        from src.mcp_handlers.identity.handlers import _extract_base_fingerprint
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
        from src.mcp_handlers.identity.handlers import ua_hash_from_header
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

class TestResolveByNameClaim:

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_name(self):
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim
        result = await resolve_by_name_claim("", "session-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_none_name(self):
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim
        result = await resolve_by_name_claim(None, "session-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_short_name(self):
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim
        result = await resolve_by_name_claim("A", "session-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_label_not_found(self):
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = None

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db):
            result = await resolve_by_name_claim("UnknownAgent", "session-1")
            assert result is None

    @pytest.mark.asyncio
    async def test_resolves_when_label_found(self):
        """Canonical success path: label match + valid trajectory_signature.

        Under strict name-claim (v2.7.0 default) callers must prove
        identity to resume by label — a signature that verifies cleanly
        is one of the three accepted proofs alongside continuity_token
        and agent_uuid."""
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

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

        mock_verification = {
            "verified": True,
            "tiers": {"lineage": {"similarity": 0.95}},
        }

        with patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.trajectory_identity.get_trajectory_status", new_callable=AsyncMock, return_value={"has_genesis": True}), \
             patch("src.trajectory_identity.verify_trajectory_identity", new_callable=AsyncMock, return_value=mock_verification), \
             patch("src.cache.get_session_cache", return_value=mock_cache), \
             patch("src.cache.redis_client.get_redis", new=_get_raw):
            result = await resolve_by_name_claim(
                "FoundAgent", "session-resolve",
                trajectory_signature={"preferences": {}, "beliefs": {}},
            )

        assert result is not None
        assert result["agent_uuid"] == test_uuid
        assert result["source"] == "name_claim"
        assert result["resumed_by_name"] is True
        assert result["persisted"] is True

    @pytest.mark.asyncio
    async def test_trajectory_verification_rejects_impersonation(self):
        """Trajectory mismatch (lineage < 0.6) rejects the name claim."""
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid

        mock_verification = {
            "verified": False,
            "tiers": {"lineage": {"similarity": 0.3}},  # Way below 0.6
        }

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.trajectory_identity.verify_trajectory_identity", new_callable=AsyncMock, return_value=mock_verification):
            result = await resolve_by_name_claim(
                "SomeAgent", "session-traj",
                trajectory_signature={"some": "data"}
            )

        assert result is None  # Rejected due to lineage mismatch

    # ----------------------------------------------------------------
    # Strict name-claim guard (v2.7.0) — a label collision requires proof
    # even when the target has no stored trajectory yet. Regression bar:
    # the "name-claim identity ghost" kept reappearing because every new
    # client defaulted to onboard(name=X) and silently hijacked whoever
    # owned that label. These tests pin the strict behavior so the bug
    # can't slide back in as a permissive default.
    # ----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_strict_rejects_label_collision_without_proof(self, monkeypatch):
        """No trajectory + no signature must be rejected, not silently bound."""
        monkeypatch.setenv("UNITARES_STRICT_NAME_CLAIM", "1")
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid

        # Target has no stored trajectory — the path that used to silently bind.
        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.trajectory_identity.get_trajectory_status", new_callable=AsyncMock, return_value={"has_genesis": False}):
            result = await resolve_by_name_claim("GhostlyAgent", "session-strict-no-proof")

        assert result is not None
        assert result.get("rejected") is True
        assert result.get("reason") == "identity_proof_required"
        # Recovery hint must name all three valid proofs so callers can fix
        # themselves without reading source.
        msg = result.get("message", "")
        assert "continuity_token" in msg
        assert "trajectory_signature" in msg
        assert "force_new" in msg

    @pytest.mark.asyncio
    async def test_strict_preserves_trajectory_required_reason(self, monkeypatch):
        """Existing 'trajectory_required' semantics for established agents
        must survive the strict-mode refactor — they're a distinct signal
        to operators that the target has history worth protecting."""
        monkeypatch.setenv("UNITARES_STRICT_NAME_CLAIM", "1")
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.trajectory_identity.get_trajectory_status", new_callable=AsyncMock, return_value={"has_genesis": True}):
            result = await resolve_by_name_claim("EstablishedAgent", "session-strict-established")

        assert result.get("rejected") is True
        assert result.get("reason") == "trajectory_required"

    @pytest.mark.asyncio
    async def test_legacy_mode_silently_binds_as_escape_hatch(self, monkeypatch):
        """UNITARES_STRICT_NAME_CLAIM=0 preserves the v2.6 permissive path
        so operators have a one-env-var rollback if an unforeseen caller
        breaks under strict mode. The feature flag is the migration window."""
        monkeypatch.setenv("UNITARES_STRICT_NAME_CLAIM", "0")
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_id": "Legacy_20260417"}
        )
        mock_db.get_agent_label.return_value = "LegacyAgent"
        mock_db.create_session = AsyncMock()

        mock_cache = AsyncMock()
        mock_cache.bind = AsyncMock()
        mock_raw = AsyncMock()
        mock_raw.setex = AsyncMock()

        async def _get_raw():
            return mock_raw

        with patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.trajectory_identity.get_trajectory_status", new_callable=AsyncMock, return_value={"has_genesis": False}), \
             patch("src.cache.get_session_cache", return_value=mock_cache), \
             patch("src.cache.redis_client.get_redis", new=_get_raw):
            result = await resolve_by_name_claim("LegacyAgent", "session-legacy")

        # Legacy behavior: bind succeeds without proof.
        assert result is not None
        assert result.get("rejected") is not True
        assert result.get("agent_uuid") == test_uuid
        assert result.get("source") == "name_claim"

    @pytest.mark.asyncio
    async def test_strict_with_valid_signature_still_binds(self, monkeypatch):
        """A caller that provides a valid trajectory_signature must still
        succeed under strict mode — otherwise we've broken established
        resume flows too."""
        monkeypatch.setenv("UNITARES_STRICT_NAME_CLAIM", "1")
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_id": "Real_20260417"}
        )
        mock_db.get_agent_label.return_value = "RealAgent"
        mock_db.create_session = AsyncMock()

        mock_cache = AsyncMock()
        mock_cache.bind = AsyncMock()
        mock_raw = AsyncMock()
        mock_raw.setex = AsyncMock()

        async def _get_raw():
            return mock_raw

        # Signature verifies cleanly (lineage similarity above threshold).
        mock_verification = {
            "verified": True,
            "tiers": {"lineage": {"similarity": 0.95}},
        }

        with patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.trajectory_identity.get_trajectory_status", new_callable=AsyncMock, return_value={"has_genesis": True}), \
             patch("src.trajectory_identity.verify_trajectory_identity", new_callable=AsyncMock, return_value=mock_verification), \
             patch("src.cache.get_session_cache", return_value=mock_cache), \
             patch("src.cache.redis_client.get_redis", new=_get_raw):
            result = await resolve_by_name_claim(
                "RealAgent", "session-strict-sig-valid",
                trajectory_signature={"preferences": {}, "beliefs": {}},
            )

        assert result is not None
        assert result.get("rejected") is not True
        assert result.get("agent_uuid") == test_uuid
        assert result.get("source") == "name_claim"


# ============================================================================
# _cache_session
# ============================================================================

class TestSetAgentLabelCacheManagement:

    @pytest.mark.asyncio
    async def test_syncs_label_to_existing_metadata_entry(self):
        """When agent is already in cache, label is synced to existing entry."""
        from src.mcp_handlers.identity.handlers import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_server = MagicMock()
        meta = SimpleNamespace(label=None, structured_id="existing_id")
        mock_server.agent_metadata = {test_uuid: meta}

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server):
            result = await set_agent_label(test_uuid, "NewLabel")

        assert result is True
        assert meta.label == "NewLabel"

    @pytest.mark.asyncio
    async def test_creates_new_metadata_entry_when_not_cached(self):
        """When agent is NOT in cache, a new AgentMetadata entry is created."""
        from src.mcp_handlers.identity.handlers import set_agent_label

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

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.agent_state.AgentMetadata", mock_meta_class), \
             patch("src.mcp_handlers.identity.handlers.detect_interface_context", return_value={"type": "test"}, create=True), \
             patch("src.mcp_handlers.identity.handlers.generate_structured_id", return_value="test_1", create=True), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="test"):
            result = await set_agent_label(test_uuid, "FreshLabel")

        assert result is True
        # Agent should now be in the metadata dict
        assert test_uuid in mock_server.agent_metadata

    @pytest.mark.asyncio
    async def test_structured_id_generation_failure_handled(self):
        """If structured_id generation fails, label is still set."""
        from src.mcp_handlers.identity.handlers import set_agent_label

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
        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.support.naming_helpers.detect_interface_context", side_effect=Exception("No context")):
            result = await set_agent_label(test_uuid, "LabelWithoutStructured")

        assert result is True
        assert meta.label == "LabelWithoutStructured"

    @pytest.mark.asyncio
    async def test_session_binding_cache_updated(self):
        """Session binding cache is updated when label is set."""
        from src.mcp_handlers.identity.handlers import set_agent_label

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

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity.shared._session_identities", session_identities):
            result = await set_agent_label(test_uuid, "UpdatedLabel")

        assert result is True
        assert session_identities["test-session"]["agent_label"] == "UpdatedLabel"

    @pytest.mark.asyncio
    async def test_session_binding_update_failure_handled(self):
        """If session binding update fails, label is still set."""
        from src.mcp_handlers.identity.handlers import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_server = MagicMock()
        meta = SimpleNamespace(label=None, structured_id="existing_id")
        mock_server.agent_metadata = {test_uuid: meta}

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.identity.shared._session_identities", side_effect=Exception("import fail")):
            result = await set_agent_label(test_uuid, "StillWorks")

        assert result is True

    @pytest.mark.asyncio
    async def test_redis_metadata_invalidation_on_label_set(self):
        """Redis metadata cache is invalidated after label set."""
        from src.mcp_handlers.identity.handlers import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_redis = MagicMock()  # Non-None value so _get_redis() returns it
        mock_metadata_cache = AsyncMock()
        mock_metadata_cache.invalidate = AsyncMock()

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._get_redis", return_value=mock_redis), \
             patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("no server")), \
             patch("src.cache.get_metadata_cache", return_value=mock_metadata_cache):
            result = await set_agent_label(test_uuid, "InvalidateTest")

        assert result is True
        mock_metadata_cache.invalidate.assert_called_once_with(test_uuid)

    @pytest.mark.asyncio
    async def test_redis_invalidation_exception_handled(self):
        """Redis metadata invalidation failure is swallowed (lines 681-682)."""
        from src.mcp_handlers.identity.handlers import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        mock_redis = MagicMock()

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._get_redis", return_value=mock_redis), \
             patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("no server")), \
             patch("src.cache.get_metadata_cache", side_effect=Exception("cache error")):
            result = await set_agent_label(test_uuid, "StillOK")

        assert result is True

    @pytest.mark.asyncio
    async def test_overall_exception_returns_false(self):
        """When the entire set_agent_label throws, returns False (lines 686-688)."""
        from src.mcp_handlers.identity.handlers import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"

        with patch("src.mcp_handlers.identity.persistence.get_db", side_effect=Exception("Fatal DB error")):
            result = await set_agent_label(test_uuid, "WillFail")

        assert result is False

    @pytest.mark.asyncio
    async def test_set_label_with_session_key_calls_ensure_persisted(self):
        """set_agent_label with session_key calls ensure_agent_persisted."""
        from src.mcp_handlers.identity.handlers import set_agent_label

        test_uuid = "aaaabbbb-1111-2222-3333-444455556666"
        mock_db = AsyncMock()
        mock_db.init = AsyncMock()
        # First call from ensure_agent_persisted, second from set_agent_label
        mock_db.get_identity.return_value = SimpleNamespace(identity_id="i1", metadata={})
        mock_db.find_agent_by_label.return_value = None
        mock_db.update_agent_fields.return_value = True

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
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
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

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

        with patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
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
    async def test_session_persist_failure_still_resolves(self, monkeypatch):
        """If session persistence fails in name claim, result is still returned (lines 779-780).

        Pinned to legacy mode — the concern here is the session-persist
        exception path, not the strict-gate behavior. Strict mode has
        its own dedicated coverage in TestResolveByNameClaim."""
        monkeypatch.setenv("UNITARES_STRICT_NAME_CLAIM", "0")
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

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

        with patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_cache), \
             patch("src.cache.redis_client.get_redis", new=_get_raw):
            result = await resolve_by_name_claim("SessionFailAgent", "session-fail")

        assert result is not None
        assert result["agent_uuid"] == test_uuid


# ============================================================================
# _cache_session - fallback bind and exception paths (lines 818-823)
# ============================================================================

class TestSetAgentLabelStructuredIdMigration:

    @pytest.mark.asyncio
    async def test_existing_agent_missing_structured_id_gets_migrated(self):
        """When existing cache entry has no structured_id, it attempts generation."""
        from src.mcp_handlers.identity.handlers import set_agent_label

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

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_server), \
             patch("src.mcp_handlers.support.naming_helpers.detect_interface_context", return_value={"type": "test"}), \
             patch("src.mcp_handlers.support.naming_helpers.generate_structured_id", return_value="migrated_id_1"), \
             patch("src.mcp_handlers.context.get_context_client_hint", return_value="cursor"):
            result = await set_agent_label(test_uuid, "MigrateLabel")

        assert result is True
        assert meta.label == "MigrateLabel"
        assert meta.structured_id == "migrated_id_1"


# ============================================================================
# Identity Hardening: Name-claim trajectory requirement (v2.6.0)
# ============================================================================

class TestNameClaimTrajectoryRequired:
    """Test that name claims require trajectory_signature when target has stored trajectory."""

    @pytest.mark.asyncio
    async def test_name_claim_requires_trajectory_when_stored(self):
        """Reject name claim without signature when target has stored trajectory."""
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid

        mock_traj_status = {
            "has_genesis": True,
            "has_current": True,
        }

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.trajectory_identity.get_trajectory_status",
                   new_callable=AsyncMock, return_value=mock_traj_status):
            result = await resolve_by_name_claim("EstablishedAgent", "session-no-sig")

        assert result is not None
        assert result.get("rejected") is True
        assert result["reason"] == "trajectory_required"

    @pytest.mark.asyncio
    async def test_name_claim_succeeds_with_valid_trajectory(self):
        """Accept name claim when valid trajectory_signature is provided."""
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid
        mock_db.get_identity.return_value = SimpleNamespace(
            identity_id="i1", metadata={"agent_id": "Agent_20260311"}
        )
        mock_db.get_agent_label.return_value = "EstablishedAgent"
        mock_db.create_session = AsyncMock()

        mock_traj_status = {"has_genesis": True, "has_current": True}
        mock_verification = {"verified": True}

        mock_cache = AsyncMock()
        mock_cache.bind = AsyncMock()
        mock_raw = AsyncMock()
        mock_raw.setex = AsyncMock()
        mock_raw.rpush = AsyncMock()
        mock_raw.expire = AsyncMock()
        async def _get_raw():
            return mock_raw

        with patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
             patch("src.cache.get_session_cache", return_value=mock_cache), \
             patch("src.cache.redis_client.get_redis", new=_get_raw), \
             patch("src.trajectory_identity.get_trajectory_status",
                   new_callable=AsyncMock, return_value=mock_traj_status), \
             patch("src.trajectory_identity.verify_trajectory_identity",
                   new_callable=AsyncMock, return_value=mock_verification):
            result = await resolve_by_name_claim(
                "EstablishedAgent", "session-with-sig",
                trajectory_signature={"preferences": [0.1, 0.2]}
            )

        assert result is not None
        assert result.get("rejected") is not True
        assert result["agent_uuid"] == test_uuid
        assert result["source"] == "name_claim"

    @pytest.mark.asyncio
    async def test_name_claim_rejects_without_signature_even_when_no_stored_trajectory(self):
        """Strict mode: a label collision requires proof even when the
        target has no stored trajectory yet. This used to be the
        permissive 'backward compat' branch — it was the exact path the
        name-claim identity ghost used to silently hijack identities
        across parallel Claude processes. v2.7.0 closes it; rollback
        remains available via UNITARES_STRICT_NAME_CLAIM=0."""
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid

        mock_traj_status = {"has_genesis": False}

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.trajectory_identity.get_trajectory_status",
                   new_callable=AsyncMock, return_value=mock_traj_status):
            result = await resolve_by_name_claim("NewAgent", "session-no-traj")

        assert result is not None
        assert result.get("rejected") is True
        assert result["reason"] == "identity_proof_required"

    @pytest.mark.asyncio
    async def test_name_claim_trajectory_mismatch_rejected(self):
        """Reject name claim when trajectory signature doesn't match stored trajectory."""
        from src.mcp_handlers.identity.handlers import resolve_by_name_claim

        test_uuid = str(uuid.uuid4())
        mock_db = AsyncMock()
        mock_db.find_agent_by_label.return_value = test_uuid

        mock_traj_status = {"has_genesis": True, "has_current": True}
        mock_verification = {
            "verified": False,
            "tiers": {"lineage": {"similarity": 0.3}},
        }

        with patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
             patch("src.mcp_handlers.identity.persistence._redis_cache", False), \
             patch("src.trajectory_identity.get_trajectory_status",
                   new_callable=AsyncMock, return_value=mock_traj_status), \
             patch("src.trajectory_identity.verify_trajectory_identity",
                   new_callable=AsyncMock, return_value=mock_verification):
            result = await resolve_by_name_claim(
                "EstablishedAgent", "session-bad-sig",
                trajectory_signature={"preferences": [0.9, 0.1]}
            )

        assert result is not None
        assert result.get("rejected") is True
        assert result["reason"] == "trajectory_mismatch"
        assert result["lineage_similarity"] == 0.3


class TestIdentityAuditLogging:

    @pytest.mark.asyncio
    async def test_identity_audit_logs_session_change(self):
        """Verify audit logging is called on successful name claim."""
        from src.mcp_handlers.identity.resolution import _audit_identity_claim

        mock_audit = MagicMock()
        mock_raw = AsyncMock()
        mock_raw.rpush = AsyncMock()
        mock_raw.expire = AsyncMock()
        async def _get_raw():
            return mock_raw

        with patch("src.audit_log.AuditLogger", return_value=mock_audit), \
             patch("src.cache.redis_client.get_redis", new=_get_raw):
            await _audit_identity_claim("test-uuid", "session-key-123", "TestAgent")

        mock_audit.log_identity_claim.assert_called_once()
        call_kwargs = mock_audit.log_identity_claim.call_args
        assert call_kwargs[1]["claimed_name"] == "TestAgent" or call_kwargs[0][1] == "TestAgent"

    @pytest.mark.asyncio
    async def test_identity_notification_queued_in_redis(self):
        """Verify identity notification is pushed to Redis."""
        from src.mcp_handlers.identity.resolution import _audit_identity_claim

        mock_audit = MagicMock()
        mock_raw = AsyncMock()
        mock_raw.rpush = AsyncMock()
        mock_raw.expire = AsyncMock()
        async def _get_raw():
            return mock_raw

        with patch("src.audit_log.AuditLogger", return_value=mock_audit), \
             patch("src.cache.redis_client.get_redis", new=_get_raw):
            await _audit_identity_claim("test-uuid", "session-key-123", "TestAgent")

        mock_raw.rpush.assert_called_once()
        key_arg = mock_raw.rpush.call_args[0][0]
        assert key_arg == "identity_notifications:test-uuid"


# ============================================================================
# Additional coverage: handle_identity_adapter structured_id regeneration (lines 1323-1345)
# ============================================================================

