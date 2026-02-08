"""
Tests for ephemeral identity marking in dispatch middleware.

Feb 2026 fix: Identities created via dispatch (not onboard) should be marked
ephemeral=True when created=True and persisted=False. This prevents ghost
agent proliferation (96% ghost rate before the fix).

Key behavior:
- Dispatch creates new identity → created=True, persisted=False → ephemeral=True
- Dispatch finds existing identity → created=False → no ephemeral flag
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

        with patch("src.mcp_handlers.identity_v2.resolve_session_identity", new_callable=AsyncMock, return_value=identity_result):
            with patch("src.mcp_handlers.identity_v2._derive_session_key", return_value="test-session"):
                with patch("src.mcp_handlers.identity_v2._extract_base_fingerprint", return_value="fp"):
                    with patch("src.mcp_handlers.identity_v2.lookup_onboard_pin", new_callable=AsyncMock, return_value=None):
                        with patch("src.mcp_handlers.context.set_session_context", return_value=MagicMock()):
                            with patch("src.db.get_db", return_value=mock_db):
                                ctx = DispatchContext()
                                result = await resolve_identity("status", {}, ctx)

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

        with patch("src.mcp_handlers.identity_v2.resolve_session_identity", new_callable=AsyncMock, return_value=identity_result):
            with patch("src.mcp_handlers.identity_v2._derive_session_key", return_value="test-session"):
                with patch("src.mcp_handlers.identity_v2._extract_base_fingerprint", return_value="fp"):
                    with patch("src.mcp_handlers.identity_v2.lookup_onboard_pin", new_callable=AsyncMock, return_value=None):
                        with patch("src.mcp_handlers.context.set_session_context", return_value=MagicMock()):
                            with patch("src.db.get_db", return_value=mock_db):
                                ctx = DispatchContext()
                                result = await resolve_identity("status", {}, ctx)

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

        with patch("src.mcp_handlers.identity_v2.resolve_session_identity", new_callable=AsyncMock, return_value=identity_result):
            with patch("src.mcp_handlers.identity_v2._derive_session_key", return_value="test-session"):
                with patch("src.mcp_handlers.identity_v2._extract_base_fingerprint", return_value="fp"):
                    with patch("src.mcp_handlers.identity_v2.lookup_onboard_pin", new_callable=AsyncMock, return_value=None):
                        with patch("src.mcp_handlers.context.set_session_context", return_value=MagicMock()):
                            with patch("src.db.get_db", return_value=mock_db):
                                ctx = DispatchContext()
                                result = await resolve_identity("status", {}, ctx)

        mock_db.update_session_activity.assert_called_once_with("test-session")

    @pytest.mark.asyncio
    async def test_ephemeral_identity_no_ttl_refresh(self, mock_db):
        """Ephemeral (not persisted) identities should NOT get TTL refresh."""
        identity_result = {
            "agent_uuid": "ephemeral-uuid-8888-9999",
            "agent_name": None,
            "created": True,
            "persisted": False,
        }

        with patch("src.mcp_handlers.identity_v2.resolve_session_identity", new_callable=AsyncMock, return_value=identity_result):
            with patch("src.mcp_handlers.identity_v2._derive_session_key", return_value="test-session"):
                with patch("src.mcp_handlers.identity_v2._extract_base_fingerprint", return_value="fp"):
                    with patch("src.mcp_handlers.identity_v2.lookup_onboard_pin", new_callable=AsyncMock, return_value=None):
                        with patch("src.mcp_handlers.context.set_session_context", return_value=MagicMock()):
                            with patch("src.db.get_db", return_value=mock_db):
                                ctx = DispatchContext()
                                result = await resolve_identity("status", {}, ctx)

        # No TTL refresh for ephemeral identities
        mock_db.update_session_activity.assert_not_called()
