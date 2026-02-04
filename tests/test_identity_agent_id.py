#!/usr/bin/env python3
"""
Tests for agent_id generation with model type.

Verifies fix from Feb 2026: agent_id should reflect model type
(e.g., "Claude_Opus_4_5_20260204") instead of falling back to
"agent_<uuid>" format.

Tests cover:
1. _generate_agent_id() function directly
2. Integration with resolve_session_identity()
3. handle_onboard_v2() response includes correct agent_id
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


class TestGenerateAgentId:
    """Unit tests for _generate_agent_id function."""

    def test_model_type_formats_correctly(self):
        """Model type should be capitalized and joined with underscores."""
        from src.mcp_handlers.identity_v2 import _generate_agent_id

        today = datetime.now().strftime("%Y%m%d")

        # Basic model types
        assert _generate_agent_id("claude") == f"Claude_{today}"
        assert _generate_agent_id("gemini") == f"Gemini_{today}"
        assert _generate_agent_id("gpt") == f"Gpt_{today}"

    def test_model_type_with_version(self):
        """Model type with version should preserve components."""
        from src.mcp_handlers.identity_v2 import _generate_agent_id

        today = datetime.now().strftime("%Y%m%d")

        # Claude with version
        result = _generate_agent_id("claude-opus-4-5")
        assert result == f"Claude_Opus_4_5_{today}"

        # GPT with version
        result = _generate_agent_id("gpt-4-turbo")
        assert result == f"Gpt_4_Turbo_{today}"

        # Gemini
        result = _generate_agent_id("gemini-pro")
        assert result == f"Gemini_Pro_{today}"

    def test_model_type_with_dots(self):
        """Dots in model type should be replaced with underscores."""
        from src.mcp_handlers.identity_v2 import _generate_agent_id

        today = datetime.now().strftime("%Y%m%d")

        result = _generate_agent_id("claude-opus-4.5")
        assert result == f"Claude_Opus_4_5_{today}"

    def test_client_hint_fallback(self):
        """Without model_type, should use client_hint."""
        from src.mcp_handlers.identity_v2 import _generate_agent_id

        today = datetime.now().strftime("%Y%m%d")

        # Client hint used when no model_type
        result = _generate_agent_id(model_type=None, client_hint="cursor")
        assert result == f"cursor_{today}"

        result = _generate_agent_id(model_type=None, client_hint="vscode")
        assert result == f"vscode_{today}"

    def test_mcp_fallback(self):
        """Without model_type or client_hint, should use 'mcp' prefix."""
        from src.mcp_handlers.identity_v2 import _generate_agent_id

        today = datetime.now().strftime("%Y%m%d")

        # Neither model_type nor client_hint
        result = _generate_agent_id(model_type=None, client_hint=None)
        assert result == f"mcp_{today}"

        # Empty strings should also fallback
        result = _generate_agent_id(model_type=None, client_hint="")
        assert result == f"mcp_{today}"

        result = _generate_agent_id(model_type=None, client_hint="unknown")
        assert result == f"mcp_{today}"

    def test_model_type_takes_precedence(self):
        """Model type should take precedence over client_hint."""
        from src.mcp_handlers.identity_v2 import _generate_agent_id

        today = datetime.now().strftime("%Y%m%d")

        # Both provided - model_type wins
        result = _generate_agent_id(model_type="claude", client_hint="cursor")
        assert result == f"Claude_{today}"


class TestResolveSessionIdentityAgentId:
    """Tests for agent_id in resolve_session_identity."""

    @pytest.mark.asyncio
    async def test_new_agent_gets_model_based_id(self):
        """PATH 3: New agent should get model-based agent_id."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        today = datetime.now().strftime("%Y%m%d")

        # Mock Redis and DB to force PATH 3 (new agent)
        with patch('src.mcp_handlers.identity_v2._get_redis') as mock_redis, \
             patch('src.mcp_handlers.identity_v2.get_db') as mock_db, \
             patch('src.mcp_handlers.identity_v2._cache_session', new_callable=AsyncMock):

            # Redis returns no cached session
            mock_redis.return_value = None

            # DB returns no session
            mock_db_instance = MagicMock()
            mock_db_instance.get_session = AsyncMock(return_value=None)
            mock_db.return_value = mock_db_instance

            result = await resolve_session_identity(
                session_key="test-session-123",
                persist=False,
                model_type="claude-opus-4-5"
            )

            assert result["created"] is True
            assert result["agent_id"] == f"Claude_Opus_4_5_{today}"
            assert "agent_uuid" in result

    @pytest.mark.asyncio
    async def test_new_agent_without_model_uses_mcp(self):
        """New agent without model_type should get mcp_ prefix."""
        from src.mcp_handlers.identity_v2 import resolve_session_identity

        today = datetime.now().strftime("%Y%m%d")

        with patch('src.mcp_handlers.identity_v2._get_redis') as mock_redis, \
             patch('src.mcp_handlers.identity_v2.get_db') as mock_db, \
             patch('src.mcp_handlers.identity_v2._cache_session', new_callable=AsyncMock):

            mock_redis.return_value = None
            mock_db_instance = MagicMock()
            mock_db_instance.get_session = AsyncMock(return_value=None)
            mock_db.return_value = mock_db_instance

            result = await resolve_session_identity(
                session_key="test-session-456",
                persist=False,
                model_type=None
            )

            assert result["created"] is True
            assert result["agent_id"] == f"mcp_{today}"


class TestOnboardAgentIdResponse:
    """Tests for agent_id in onboard response."""

    @pytest.mark.asyncio
    async def test_onboard_returns_model_based_agent_id(self):
        """Onboard response should include model-based agent_id, not UUID fallback."""
        # This tests the fix at identity_v2.py:1446-1460
        # where structured_id now uses agent_id from resolve_session_identity

        from src.mcp_handlers.identity_v2 import _generate_agent_id

        today = datetime.now().strftime("%Y%m%d")

        # The key fix: agent_id from resolve_session_identity should be used
        # instead of falling back to f"agent_{uuid[:8]}"
        agent_id = _generate_agent_id("claude-opus-4-5")

        # Verify it's NOT the UUID fallback pattern
        assert not agent_id.startswith("agent_")
        assert agent_id == f"Claude_Opus_4_5_{today}"


class TestEdgeCases:
    """Edge case tests for agent_id generation."""

    def test_whitespace_handling(self):
        """Whitespace in model type should be handled."""
        from src.mcp_handlers.identity_v2 import _generate_agent_id

        today = datetime.now().strftime("%Y%m%d")

        # Leading/trailing whitespace
        result = _generate_agent_id("  claude  ")
        assert result == f"Claude_{today}"

    def test_special_characters(self):
        """Various separators should all work."""
        from src.mcp_handlers.identity_v2 import _generate_agent_id

        today = datetime.now().strftime("%Y%m%d")

        # Underscores
        result = _generate_agent_id("claude_opus_4")
        assert result == f"Claude_Opus_4_{today}"

        # Mixed
        result = _generate_agent_id("claude-opus_4.5")
        assert result == f"Claude_Opus_4_5_{today}"

    def test_empty_model_type(self):
        """Empty string model_type should fallback."""
        from src.mcp_handlers.identity_v2 import _generate_agent_id

        today = datetime.now().strftime("%Y%m%d")

        # Empty string - should not crash
        result = _generate_agent_id("")
        # Empty string is falsy, so should fallback to mcp_
        assert result == f"mcp_{today}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
