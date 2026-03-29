"""
Tests for the sticky transport binding cache in identity_step.py.

The sticky cache prevents identity fragmentation for IP:UA fingerprint sessions
by reusing the first-resolved identity for all subsequent tool calls.
"""

import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.middleware import DispatchContext
from src.mcp_handlers.middleware.identity_step import (
    _transport_cache_key,
    _transport_identity_cache,
    TransportBinding,
    update_transport_binding,
    invalidate_transport_binding,
    _evict_stale_entries,
    _TRANSPORT_CACHE_TTL,
    _TRANSPORT_CACHE_MAX,
    resolve_identity,
)


# ============================================================================
# Helpers
# ============================================================================

@dataclass
class FakeSignals:
    """Minimal SessionSignals stand-in for testing."""
    mcp_session_id: Optional[str] = None
    x_session_id: Optional[str] = None
    x_client_id: Optional[str] = None
    oauth_client_id: Optional[str] = None
    ip_ua_fingerprint: Optional[str] = None
    user_agent: Optional[str] = None
    client_hint: Optional[str] = None
    x_agent_name: Optional[str] = None
    x_agent_id: Optional[str] = None
    transport: str = "mcp"


def _clear_cache():
    """Clear the module-level transport cache for test isolation."""
    _transport_identity_cache.clear()


@pytest.fixture(autouse=True)
def clean_cache():
    """Ensure each test starts with a clean cache."""
    _clear_cache()
    yield
    _clear_cache()


# ============================================================================
# 1. _transport_cache_key() unit tests
# ============================================================================

class TestTransportCacheKey:
    """Tests for _transport_cache_key()."""

    def test_returns_none_for_no_signals(self):
        assert _transport_cache_key(None) is None

    def test_returns_none_for_mcp_session_id(self):
        signals = FakeSignals(mcp_session_id="mcp-123")
        assert _transport_cache_key(signals) is None

    def test_returns_none_for_x_session_id(self):
        signals = FakeSignals(x_session_id="x-sess-456")
        assert _transport_cache_key(signals) is None

    def test_returns_none_for_x_client_id(self):
        signals = FakeSignals(x_client_id="client-789")
        assert _transport_cache_key(signals) is None

    def test_returns_none_for_oauth_client_id(self):
        signals = FakeSignals(oauth_client_id="oauth:abc")
        assert _transport_cache_key(signals) is None

    def test_returns_key_for_fingerprint_path(self):
        signals = FakeSignals(ip_ua_fingerprint="192.168.1.1:abc123")
        result = _transport_cache_key(signals)
        assert result == "sticky:192.168.1.1:abc123"

    def test_returns_none_for_no_fingerprint(self):
        signals = FakeSignals()
        assert _transport_cache_key(signals) is None

    def test_stable_path_takes_priority_over_fingerprint(self):
        """If both mcp_session_id and fingerprint exist, returns None (stable path)."""
        signals = FakeSignals(mcp_session_id="mcp-123", ip_ua_fingerprint="192.168.1.1:abc")
        assert _transport_cache_key(signals) is None


# ============================================================================
# 2. Cache management unit tests
# ============================================================================

class TestCacheManagement:
    """Tests for update_transport_binding, invalidate, and eviction."""

    def test_update_creates_binding(self):
        update_transport_binding("sticky:fp1", "uuid-111", "sk-111", "redis")
        assert "sticky:fp1" in _transport_identity_cache
        binding = _transport_identity_cache["sticky:fp1"]
        assert binding.agent_uuid == "uuid-111"
        assert binding.session_key == "sk-111"
        assert binding.source == "redis"

    def test_update_overwrites_existing(self):
        update_transport_binding("sticky:fp1", "uuid-111", "sk-111", "redis")
        update_transport_binding("sticky:fp1", "uuid-222", "sk-222", "bind_session")
        binding = _transport_identity_cache["sticky:fp1"]
        assert binding.agent_uuid == "uuid-222"
        assert binding.source == "bind_session"

    def test_invalidate_removes_binding(self):
        update_transport_binding("sticky:fp1", "uuid-111", "sk-111", "redis")
        invalidate_transport_binding("sticky:fp1")
        assert "sticky:fp1" not in _transport_identity_cache

    def test_invalidate_nonexistent_key_is_noop(self):
        invalidate_transport_binding("sticky:nonexistent")  # Should not raise

    def test_evict_stale_entries_by_ttl(self):
        """Entries older than TTL are evicted."""
        _transport_identity_cache["sticky:old"] = TransportBinding(
            agent_uuid="uuid-old",
            session_key="sk-old",
            bound_at=time.monotonic() - _TRANSPORT_CACHE_TTL - 100,
            source="test",
        )
        update_transport_binding("sticky:new", "uuid-new", "sk-new", "test")
        # Eviction happens inside update_transport_binding
        assert "sticky:old" not in _transport_identity_cache
        assert "sticky:new" in _transport_identity_cache

    def test_evict_max_size(self):
        """When cache exceeds max size, oldest entries are evicted."""
        base_time = time.monotonic()
        # Fill beyond max
        for i in range(_TRANSPORT_CACHE_MAX + 5):
            _transport_identity_cache[f"sticky:fp{i}"] = TransportBinding(
                agent_uuid=f"uuid-{i}",
                session_key=f"sk-{i}",
                bound_at=base_time + i * 0.001,  # Slightly increasing timestamps
                source="test",
            )
        _evict_stale_entries()
        assert len(_transport_identity_cache) <= _TRANSPORT_CACHE_MAX


# ============================================================================
# 3. resolve_identity() integration with sticky cache
# ============================================================================

class TestStickyResolveIdentity:
    """Integration tests for sticky cache in resolve_identity()."""

    @pytest.mark.asyncio
    async def test_cache_hit_reuses_identity(self):
        """When cache has a fresh binding, resolve_identity returns it without calling derive_session_key."""
        # Pre-populate cache
        update_transport_binding("sticky:192.168.1.1:abc", "uuid-cached", "sk-cached", "redis")

        signals = FakeSignals(ip_ua_fingerprint="192.168.1.1:abc")
        ctx = DispatchContext()

        with patch("src.mcp_handlers.context.get_session_signals", return_value=signals):
            with patch("src.mcp_handlers.context.set_session_context", return_value="tok") as mock_set:
                # derive_session_key should NOT be called
                with patch("src.mcp_handlers.identity.handlers.derive_session_key") as mock_derive:
                    result = await resolve_identity("some_tool", {}, ctx)

                    name, args, out_ctx = result
                    assert out_ctx.bound_agent_id == "uuid-cached"
                    assert out_ctx.session_key == "sk-cached"
                    assert out_ctx.identity_result["source"] == "sticky_cache"
                    # derive_session_key was never called
                    mock_derive.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_bypass_on_force_new(self):
        """force_new=True bypasses and invalidates the cache."""
        update_transport_binding("sticky:192.168.1.1:abc", "uuid-old", "sk-old", "redis")

        signals = FakeSignals(ip_ua_fingerprint="192.168.1.1:abc")
        ctx = DispatchContext()

        mock_identity = {
            "agent_uuid": "uuid-new",
            "created": True,
            "persisted": False,
            "source": "created",
        }

        with patch("src.mcp_handlers.context.get_session_signals", return_value=signals):
            with patch("src.mcp_handlers.identity.handlers.derive_session_key", new_callable=AsyncMock, return_value="sk-derived"):
                with patch("src.mcp_handlers.identity.handlers.resolve_session_identity", new_callable=AsyncMock, return_value=mock_identity):
                    with patch("src.mcp_handlers.context.set_session_context", return_value="tok"):
                        result = await resolve_identity("identity", {"force_new": True}, ctx)

                        _, _, out_ctx = result
                        assert out_ctx.bound_agent_id == "uuid-new"
                        # Old cache entry should be invalidated
                        assert "sticky:192.168.1.1:abc" not in _transport_identity_cache or \
                               _transport_identity_cache["sticky:192.168.1.1:abc"].agent_uuid == "uuid-new"

    @pytest.mark.asyncio
    async def test_cache_bypass_on_client_session_id(self):
        """Explicit client_session_id bypasses the cache."""
        update_transport_binding("sticky:192.168.1.1:abc", "uuid-cached", "sk-cached", "redis")

        signals = FakeSignals(ip_ua_fingerprint="192.168.1.1:abc")
        ctx = DispatchContext()

        mock_identity = {
            "agent_uuid": "uuid-explicit",
            "source": "redis",
        }

        with patch("src.mcp_handlers.context.get_session_signals", return_value=signals):
            with patch("src.mcp_handlers.identity.handlers.derive_session_key", new_callable=AsyncMock, return_value="sk-explicit"):
                with patch("src.mcp_handlers.identity.handlers.resolve_session_identity", new_callable=AsyncMock, return_value=mock_identity):
                    with patch("src.mcp_handlers.context.set_session_context", return_value="tok"):
                        result = await resolve_identity(
                            "process_agent_update",
                            {"client_session_id": "my-explicit-session"},
                            ctx,
                        )
                        _, _, out_ctx = result
                        # Should use the explicitly resolved identity, not the cached one
                        assert out_ctx.bound_agent_id == "uuid-explicit"

    @pytest.mark.asyncio
    async def test_cache_bypass_on_continuity_token(self):
        """Explicit continuity_token bypasses the cache."""
        update_transport_binding("sticky:192.168.1.1:abc", "uuid-cached", "sk-cached", "redis")

        signals = FakeSignals(ip_ua_fingerprint="192.168.1.1:abc")
        ctx = DispatchContext()

        mock_identity = {
            "agent_uuid": "uuid-token",
            "source": "continuity",
        }

        with patch("src.mcp_handlers.context.get_session_signals", return_value=signals):
            with patch("src.mcp_handlers.identity.handlers.derive_session_key", new_callable=AsyncMock, return_value="sk-token"):
                with patch("src.mcp_handlers.identity.handlers.resolve_session_identity", new_callable=AsyncMock, return_value=mock_identity):
                    with patch("src.mcp_handlers.context.set_session_context", return_value="tok"):
                        result = await resolve_identity(
                            "some_tool",
                            {"continuity_token": "ct-abc123"},
                            ctx,
                        )
                        _, _, out_ctx = result
                        assert out_ctx.bound_agent_id == "uuid-token"

    @pytest.mark.asyncio
    async def test_not_used_for_mcp_session_path(self):
        """mcp_session_id path is already stable — cache not used."""
        signals = FakeSignals(mcp_session_id="mcp-stable-123", ip_ua_fingerprint="192.168.1.1:abc")
        ctx = DispatchContext()

        mock_identity = {
            "agent_uuid": "uuid-mcp",
            "source": "redis",
        }

        with patch("src.mcp_handlers.context.get_session_signals", return_value=signals):
            with patch("src.mcp_handlers.identity.handlers.derive_session_key", new_callable=AsyncMock, return_value="sk-mcp"):
                with patch("src.mcp_handlers.identity.handlers.resolve_session_identity", new_callable=AsyncMock, return_value=mock_identity):
                    with patch("src.mcp_handlers.context.set_session_context", return_value="tok"):
                        result = await resolve_identity("some_tool", {}, ctx)
                        _, _, out_ctx = result
                        # Should NOT populate the cache (transport key is None for stable paths)
                        assert out_ctx._transport_key is None
                        assert len(_transport_identity_cache) == 0

    @pytest.mark.asyncio
    async def test_ttl_expiry_falls_back_to_normal(self):
        """Expired cache entries are not used; normal resolution proceeds."""
        # Insert expired entry
        _transport_identity_cache["sticky:192.168.1.1:abc"] = TransportBinding(
            agent_uuid="uuid-expired",
            session_key="sk-expired",
            bound_at=time.monotonic() - _TRANSPORT_CACHE_TTL - 100,
            source="test",
        )

        signals = FakeSignals(ip_ua_fingerprint="192.168.1.1:abc")
        ctx = DispatchContext()

        mock_identity = {
            "agent_uuid": "uuid-fresh",
            "source": "postgres",
        }

        with patch("src.mcp_handlers.context.get_session_signals", return_value=signals):
            with patch("src.mcp_handlers.identity.handlers.derive_session_key", new_callable=AsyncMock, return_value="sk-fresh"):
                with patch("src.mcp_handlers.identity.handlers.resolve_session_identity", new_callable=AsyncMock, return_value=mock_identity):
                    with patch("src.mcp_handlers.context.set_session_context", return_value="tok"):
                        result = await resolve_identity("some_tool", {}, ctx)
                        _, _, out_ctx = result
                        assert out_ctx.bound_agent_id == "uuid-fresh"
                        # Cache should be refreshed with the new identity
                        binding = _transport_identity_cache.get("sticky:192.168.1.1:abc")
                        assert binding is not None
                        assert binding.agent_uuid == "uuid-fresh"

    @pytest.mark.asyncio
    async def test_normal_resolution_populates_cache(self):
        """After normal resolution (no cache hit), the cache is populated for next time."""
        signals = FakeSignals(ip_ua_fingerprint="192.168.1.1:new")
        ctx = DispatchContext()

        mock_identity = {
            "agent_uuid": "uuid-resolved",
            "source": "redis",
        }

        with patch("src.mcp_handlers.context.get_session_signals", return_value=signals):
            with patch("src.mcp_handlers.identity.handlers.derive_session_key", new_callable=AsyncMock, return_value="sk-resolved"):
                with patch("src.mcp_handlers.identity.handlers.resolve_session_identity", new_callable=AsyncMock, return_value=mock_identity):
                    with patch("src.mcp_handlers.context.set_session_context", return_value="tok"):
                        result = await resolve_identity("some_tool", {}, ctx)
                        _, _, out_ctx = result
                        assert out_ctx.bound_agent_id == "uuid-resolved"
                        # Cache should now contain the binding
                        binding = _transport_identity_cache.get("sticky:192.168.1.1:new")
                        assert binding is not None
                        assert binding.agent_uuid == "uuid-resolved"
                        assert binding.session_key == "sk-resolved"


# ============================================================================
# 4. DispatchContext._transport_key field
# ============================================================================

class TestDispatchContextTransportKey:
    """Verify _transport_key field on DispatchContext."""

    def test_default_is_none(self):
        ctx = DispatchContext()
        assert ctx._transport_key is None

    def test_settable(self):
        ctx = DispatchContext(_transport_key="sticky:fp1")
        assert ctx._transport_key == "sticky:fp1"
