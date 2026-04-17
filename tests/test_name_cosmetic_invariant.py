"""Lock in the cosmetic-name invariant.

After the name-claim removal, `name` is a mutable cosmetic label. It must
NOT drive identity resolution. These tests fail loudly if anyone tries to
restore name-as-lookup behavior.

The invariants:
  1. `resolve_by_name_claim` is gone (not re-exported anywhere).
  2. `resolve_session_identity` no longer accepts `agent_name`.
  3. `UNITARES_STRICT_NAME_CLAIM` is dead code (nothing reads it).
  4. onboard(name=X) without UUID/token/signature creates a FRESH uuid,
     even if an agent with that label already exists.
"""

from __future__ import annotations

import inspect
import os
import pytest
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# Invariant 1: resolve_by_name_claim is gone
# ============================================================================

class TestResolveByNameClaimRemoved:

    def test_not_in_resolution_module(self):
        from src.mcp_handlers.identity import resolution
        assert not hasattr(resolution, "resolve_by_name_claim"), (
            "resolve_by_name_claim is gone — do not reintroduce it. "
            "Name is cosmetic; use PATH 0 (agent_uuid), PATH 2.8 "
            "(continuity_token), or force_new=true instead."
        )

    def test_not_re_exported_from_core(self):
        from src.mcp_handlers.identity import core
        assert not hasattr(core, "resolve_by_name_claim")

    def test_not_re_exported_from_package(self):
        from src.mcp_handlers import identity
        assert not hasattr(identity, "resolve_by_name_claim")

    def test_not_re_exported_from_handlers(self):
        from src.mcp_handlers.identity import handlers
        assert not hasattr(handlers, "resolve_by_name_claim")


# ============================================================================
# Invariant 2: resolve_session_identity signature no longer takes agent_name
# ============================================================================

class TestResolveSessionIdentitySignature:

    def test_no_agent_name_parameter(self):
        from src.mcp_handlers.identity.resolution import resolve_session_identity
        sig = inspect.signature(resolve_session_identity)
        assert "agent_name" not in sig.parameters, (
            "resolve_session_identity must not accept agent_name. "
            "Labels are set at the handler layer via set_agent_label."
        )


# ============================================================================
# Invariant 3: UNITARES_STRICT_NAME_CLAIM is dead
# ============================================================================

class TestStrictNameClaimEnvVarIsDead:

    def test_env_var_not_read_in_resolution(self):
        import src.mcp_handlers.identity.resolution as resolution_mod
        src = inspect.getsource(resolution_mod)
        assert "UNITARES_STRICT_NAME_CLAIM" not in src, (
            "UNITARES_STRICT_NAME_CLAIM must be fully removed, not just "
            "defaulted. The escape hatch exists only while name-claim "
            "exists; once name-claim is gone the var is meaningless."
        )

    def test_env_var_not_read_in_handlers(self):
        import src.mcp_handlers.identity.handlers as handlers_mod
        src = inspect.getsource(handlers_mod)
        assert "UNITARES_STRICT_NAME_CLAIM" not in src


# ============================================================================
# Invariant 4: onboard(name=X) without proof creates fresh uuid
# ============================================================================

@pytest.fixture
def mock_db():
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
    # Deliberately: even if a label matches, it must NOT be used for resolution.
    db.find_agent_by_label = AsyncMock(return_value="pre-existing-uuid-xxxx")
    db.update_agent_fields = AsyncMock(return_value=True)
    return db


@pytest.fixture
def mock_redis():
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.bind = AsyncMock()
    return cache


@pytest.fixture
def mock_raw_redis():
    r = AsyncMock()
    r.setex = AsyncMock()
    r.expire = AsyncMock()
    r.get = AsyncMock(return_value=None)
    return r


@pytest.fixture
def patch_deps(mock_db, mock_redis, mock_raw_redis):
    async def _get_raw():
        return mock_raw_redis
    with patch("src.mcp_handlers.identity.persistence._redis_cache", None), \
         patch("src.cache.get_session_cache", return_value=mock_redis), \
         patch("src.mcp_handlers.identity.resolution.get_db", return_value=mock_db), \
         patch("src.mcp_handlers.identity.persistence.get_db", return_value=mock_db), \
         patch("src.mcp_handlers.identity.handlers.get_db", return_value=mock_db), \
         patch("src.cache.redis_client.get_redis", new=_get_raw):
        yield


class TestNameDoesNotResolveIdentity:

    @pytest.mark.asyncio
    async def test_resolve_session_identity_ignores_label_collision(
        self, patch_deps, mock_db, mock_redis
    ):
        """Even with a label match in DB, resolve_session_identity creates a
        fresh UUID. Name-claim is gone — label is never consulted."""
        from src.mcp_handlers.identity.resolution import resolve_session_identity

        mock_redis.get.return_value = None
        mock_db.get_session.return_value = None
        # find_agent_by_label is mocked to return "pre-existing-uuid-xxxx";
        # if name-claim crept back, resolve would bind to that UUID.

        result = await resolve_session_identity(
            session_key="session-fresh-onboard",
            persist=False,
        )

        assert result["agent_uuid"] != "pre-existing-uuid-xxxx", (
            "resolve_session_identity must not resolve by label. "
            "Only UUID/token/session lookup is valid."
        )
        assert result["created"] is True
        assert result["source"] in ("created", "memory_only")
