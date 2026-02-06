"""
Tests for src/cache/session_cache.py - SessionCache with fakeredis.

Tests bind/get/unbind/exists/get_by_agent_id/health_check using
real Redis protocol via fakeredis (no mocks).
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

fakeredis = pytest.importorskip("fakeredis")
import fakeredis.aioredis

from src.cache.session_cache import SessionCache, SESSION_PREFIX, _fallback_cache


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fake_redis():
    """Create a fakeredis async client."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def cache(fake_redis):
    """SessionCache with fakeredis injected via get_redis patch."""
    _fallback_cache.clear()

    async def _get_fake_redis():
        return fake_redis

    with patch("src.cache.session_cache.get_redis", new=_get_fake_redis):
        yield SessionCache()

    _fallback_cache.clear()


@pytest.fixture
def cache_no_redis():
    """SessionCache with Redis unavailable (memory-only fallback)."""
    _fallback_cache.clear()

    async def _get_none():
        return None

    with patch("src.cache.session_cache.get_redis", new=_get_none):
        yield SessionCache()

    _fallback_cache.clear()


# ============================================================================
# bind
# ============================================================================

class TestBind:

    @pytest.mark.asyncio
    async def test_bind_stores_in_redis(self, cache, fake_redis):
        result = await cache.bind("sess-1", "agent-uuid-1234")
        assert result is True

        # Verify Redis has the data
        raw = await fake_redis.get(f"{SESSION_PREFIX}sess-1")
        assert raw is not None
        data = json.loads(raw)
        assert data["agent_id"] == "agent-uuid-1234"
        assert data["bind_count"] == 1
        assert "bound_at" in data

    @pytest.mark.asyncio
    async def test_bind_increments_bind_count(self, cache, fake_redis):
        await cache.bind("sess-1", "agent-1")
        await cache.bind("sess-1", "agent-1")

        raw = await fake_redis.get(f"{SESSION_PREFIX}sess-1")
        data = json.loads(raw)
        assert data["bind_count"] == 2

    @pytest.mark.asyncio
    async def test_bind_with_api_key_hash(self, cache, fake_redis):
        await cache.bind("sess-1", "agent-1", api_key_hash="hash123")

        raw = await fake_redis.get(f"{SESSION_PREFIX}sess-1")
        data = json.loads(raw)
        assert data["api_key_hash"] == "hash123"

    @pytest.mark.asyncio
    async def test_bind_also_populates_fallback(self, cache):
        await cache.bind("sess-1", "agent-1")
        assert "sess-1" in _fallback_cache
        assert _fallback_cache["sess-1"]["agent_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_bind_memory_fallback_when_no_redis(self, cache_no_redis):
        result = await cache_no_redis.bind("sess-1", "agent-1")
        assert result is True
        assert _fallback_cache["sess-1"]["agent_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_bind_memory_fallback_increments(self, cache_no_redis):
        await cache_no_redis.bind("sess-1", "agent-1")
        await cache_no_redis.bind("sess-1", "agent-1")
        assert _fallback_cache["sess-1"]["bind_count"] == 2


# ============================================================================
# get
# ============================================================================

class TestGet:

    @pytest.mark.asyncio
    async def test_get_returns_binding(self, cache):
        await cache.bind("sess-1", "agent-1")
        result = await cache.get("sess-1")
        assert result is not None
        assert result["agent_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self, cache):
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_populates_fallback(self, cache, fake_redis):
        # Write directly to Redis (bypassing cache.bind)
        data = json.dumps({"agent_id": "direct-agent", "bound_at": "t", "bind_count": 1})
        await fake_redis.set(f"{SESSION_PREFIX}sess-direct", data)

        result = await cache.get("sess-direct")
        assert result["agent_id"] == "direct-agent"
        # Should have populated fallback
        assert _fallback_cache.get("sess-direct", {}).get("agent_id") == "direct-agent"

    @pytest.mark.asyncio
    async def test_get_falls_back_to_memory(self, cache_no_redis):
        await cache_no_redis.bind("sess-1", "agent-1")
        result = await cache_no_redis.get("sess-1")
        assert result["agent_id"] == "agent-1"


# ============================================================================
# get_agent_id
# ============================================================================

class TestGetAgentId:

    @pytest.mark.asyncio
    async def test_returns_agent_id(self, cache):
        await cache.bind("sess-1", "agent-uuid")
        result = await cache.get_agent_id("sess-1")
        assert result == "agent-uuid"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self, cache):
        result = await cache.get_agent_id("missing")
        assert result is None


# ============================================================================
# unbind
# ============================================================================

class TestUnbind:

    @pytest.mark.asyncio
    async def test_unbind_removes_from_redis(self, cache, fake_redis):
        await cache.bind("sess-1", "agent-1")
        result = await cache.unbind("sess-1")
        assert result is True

        raw = await fake_redis.get(f"{SESSION_PREFIX}sess-1")
        assert raw is None

    @pytest.mark.asyncio
    async def test_unbind_removes_from_fallback(self, cache):
        await cache.bind("sess-1", "agent-1")
        await cache.unbind("sess-1")
        assert "sess-1" not in _fallback_cache

    @pytest.mark.asyncio
    async def test_unbind_nonexistent_returns_false(self, cache):
        result = await cache.unbind("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_unbind_memory_only(self, cache_no_redis):
        await cache_no_redis.bind("sess-1", "agent-1")
        result = await cache_no_redis.unbind("sess-1")
        assert result is True
        assert "sess-1" not in _fallback_cache


# ============================================================================
# exists
# ============================================================================

class TestExists:

    @pytest.mark.asyncio
    async def test_exists_true(self, cache):
        await cache.bind("sess-1", "agent-1")
        assert await cache.exists("sess-1") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, cache):
        assert await cache.exists("nonexistent") is False


# ============================================================================
# get_by_agent_id (reverse lookup)
# ============================================================================

class TestGetByAgentId:

    @pytest.mark.asyncio
    async def test_reverse_lookup_redis(self, cache):
        await cache.bind("sess-A", "agent-1")
        await cache.bind("sess-B", "agent-2")

        result = await cache.get_by_agent_id("agent-1")
        assert result == "sess-A"

    @pytest.mark.asyncio
    async def test_reverse_lookup_not_found(self, cache):
        result = await cache.get_by_agent_id("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_reverse_lookup_memory_fallback(self, cache_no_redis):
        await cache_no_redis.bind("sess-A", "agent-1")
        result = await cache_no_redis.get_by_agent_id("agent-1")
        assert result == "sess-A"


# ============================================================================
# health_check
# ============================================================================

class TestHealthCheck:

    @pytest.mark.asyncio
    async def test_healthy_with_redis(self, cache):
        await cache.bind("sess-1", "agent-1")
        result = await cache.health_check()
        assert result["backend"] == "redis"
        assert result["status"] == "healthy"
        assert result["session_count"] >= 1

    @pytest.mark.asyncio
    async def test_healthy_memory_fallback(self, cache_no_redis):
        await cache_no_redis.bind("sess-1", "agent-1")
        result = await cache_no_redis.health_check()
        assert result["backend"] == "memory"
        assert result["status"] == "healthy"
        assert result["session_count"] == 1

    @pytest.mark.asyncio
    async def test_health_includes_fallback_count(self, cache):
        await cache.bind("sess-1", "agent-1")
        result = await cache.health_check()
        assert "fallback_count" in result
