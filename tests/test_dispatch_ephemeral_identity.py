"""
Tests for ephemeral identity marking in dispatch middleware.

Feb 2026 fix: Identities created via dispatch (not onboard) should be marked
ephemeral=True when created=True and persisted=False. This prevents ghost
agent proliferation (96% ghost rate before the fix).

Key behavior:
- Dispatch creates new identity -> created=True, persisted=False -> ephemeral=True
- Dispatch finds existing identity -> created=False -> no ephemeral flag
- Persisted identities get TTL refresh via update_session_activity
- Ephemeral identities do NOT get TTL refresh
"""

import asyncio
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.middleware import resolve_identity, DispatchContext


@pytest.fixture
def mock_db():
    """Mock database for TTL refresh tracking."""
    db = AsyncMock()
    db.update_session_activity = AsyncMock(return_value=True)
    return db


def _identity_patches(identity_result, mock_db):
    """Stack of patches needed for resolve_identity tests.

    Mocks get_session_signals to prevent contextvar leakage from prior tests
    (the real get_session_signals reads a contextvar that may not be cleaned up).
    """
    return [
        patch("src.mcp_handlers.context.get_session_signals", return_value=None),
        patch("src.mcp_handlers.identity_v2.derive_session_key", new_callable=AsyncMock, return_value="test-session"),
        patch("src.mcp_handlers.identity_v2.resolve_session_identity", new_callable=AsyncMock, return_value=identity_result),
        patch("src.mcp_handlers.context.set_session_context", return_value=MagicMock()),
        patch("src.db.get_db", return_value=mock_db),
    ]


class TestEphemeralIdentityMarking:
    """Test that resolve_identity() correctly marks ephemeral identities."""

    @pytest.mark.asyncio
    async def test_new_identity_marked_ephemeral(self, mock_db):
        """When resolve_identity creates a new identity (created=True, persisted=False), it should be ephemeral."""
        identity_result = {
            "agent_uuid": "new-uuid-1111-2222-3333",
            "agent_name": None,
            "created": True,
            "persisted": False,
        }

        patches = _identity_patches(identity_result, mock_db)
        for p in patches:
            p.start()
        try:
            ctx = DispatchContext()
            result = await resolve_identity("status", {}, ctx)
        finally:
            for p in reversed(patches):
                p.stop()

        # identity_result should have been mutated
        assert identity_result.get("ephemeral") is True
        assert identity_result.get("created_via") == "dispatch"
        # ctx should store the result
        assert ctx.identity_result is identity_result

    @pytest.mark.asyncio
    async def test_existing_identity_not_ephemeral(self, mock_db):
        """When resolve_identity finds an existing identity (created=False), it should NOT be ephemeral."""
        identity_result = {
            "agent_uuid": "existing-uuid-4444-5555",
            "agent_name": "ExistingAgent",
            "created": False,
            "persisted": True,
        }

        patches = _identity_patches(identity_result, mock_db)
        for p in patches:
            p.start()
        try:
            ctx = DispatchContext()
            result = await resolve_identity("status", {}, ctx)
        finally:
            for p in reversed(patches):
                p.stop()

        assert "ephemeral" not in identity_result
        assert "created_via" not in identity_result

    @pytest.mark.asyncio
    async def test_persisted_identity_gets_ttl_refresh(self, mock_db):
        """Persisted identities should have their session TTL refreshed."""
        identity_result = {
            "agent_uuid": "persisted-uuid-6666-7777",
            "agent_name": "PersistedAgent",
            "created": False,
            "persisted": True,
        }

        patches = _identity_patches(identity_result, mock_db)
        for p in patches:
            p.start()
        try:
            ctx = DispatchContext()
            result = await resolve_identity("status", {}, ctx)
        finally:
            for p in reversed(patches):
                p.stop()

        # TTL refresh must be called with whatever session key was derived
        assert ctx.session_key is not None
        mock_db.update_session_activity.assert_called_once_with(ctx.session_key)

    @pytest.mark.asyncio
    async def test_ephemeral_identity_no_ttl_refresh(self, mock_db):
        """Ephemeral (not persisted) identities should NOT get TTL refresh."""
        identity_result = {
            "agent_uuid": "ephemeral-uuid-8888-9999",
            "agent_name": None,
            "created": True,
            "persisted": False,
        }

        patches = _identity_patches(identity_result, mock_db)
        for p in patches:
            p.start()
        try:
            ctx = DispatchContext()
            result = await resolve_identity("status", {}, ctx)
        finally:
            for p in reversed(patches):
                p.stop()

        # No TTL refresh for ephemeral identities
        mock_db.update_session_activity.assert_not_called()
