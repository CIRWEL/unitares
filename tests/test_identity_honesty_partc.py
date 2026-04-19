"""Identity Honesty Part C — strict-mode gate tests.

Closes the three ghost-creation paths called out in PR #35 revert:
  - PATH 0 bare agent_uuid resume (identity handler + middleware)
  - FALLBACK 2 auto_<ts>_<uuid8> handler generation
  - Onboard-triggered orphan sweep (separate test class)

Run: pytest tests/test_identity_honesty_partc.py --no-cov -q
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_strict_mode(monkeypatch):
    """Each test controls its own mode explicitly."""
    monkeypatch.delenv("UNITARES_IDENTITY_STRICT", raising=False)
    yield


class TestPath0RequiresOwnershipProof:
    """identity(agent_uuid=X, resume=True) without matching token is rejected."""

    @pytest.mark.asyncio
    async def test_strict_mode_rejects_bare_uuid_resume(self, monkeypatch):
        """In strict mode, PATH 0 with only agent_uuid (no token) is denied."""
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "strict")

        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        fake_server = MagicMock(monitors={}, agent_metadata={})
        with patch(
            "src.mcp_handlers.identity.handlers._agent_exists_in_postgres",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.mcp_handlers.identity.handlers._get_agent_status",
            new=AsyncMock(return_value="active"),
        ), patch(
            "src.mcp_handlers.shared.get_mcp_server",
            return_value=fake_server,
        ):
            result = await handle_identity_adapter({
                "agent_uuid": "11111111-2222-3333-4444-555555555555",
                "resume": True,
            })

        text = result[0].text if result else "{}"
        data = json.loads(text)
        assert data.get("success") is False, f"Expected failure, got: {data}"
        err = (data.get("error") or "").lower()
        assert "continuity_token" in err or "bare" in err or "ownership" in err, (
            f"Error should mention token/ownership. Got: {data.get('error')!r}"
        )

    @pytest.mark.asyncio
    async def test_log_mode_warns_but_does_not_reject(self, monkeypatch, caplog):
        """In log mode, bare-UUID resume proceeds but emits [IDENTITY_STRICT] warning."""
        import logging
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "log")
        caplog.set_level(logging.WARNING)

        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        fake_server = MagicMock(
            monitors={"11111111-2222-3333-4444-555555555555": MagicMock()},
            agent_metadata={},
        )
        with patch(
            "src.mcp_handlers.shared.get_mcp_server",
            return_value=fake_server,
        ):
            result = await handle_identity_adapter({
                "agent_uuid": "11111111-2222-3333-4444-555555555555",
                "resume": True,
            })

        text = result[0].text if result else "{}"
        data = json.loads(text)
        assert data.get("success") is True, f"Log mode should not reject. Got: {data}"
        strict_warnings = [
            r for r in caplog.records
            if "[IDENTITY_STRICT]" in r.getMessage()
        ]
        assert strict_warnings, "Log mode must emit [IDENTITY_STRICT] warning"

    @pytest.mark.asyncio
    async def test_off_mode_unchanged_no_warning(self, monkeypatch, caplog):
        """In off mode, bare-UUID resume proceeds without any [IDENTITY_STRICT] output."""
        import logging
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "off")
        caplog.set_level(logging.WARNING)

        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        fake_server = MagicMock(
            monitors={"22222222-3333-4444-5555-666666666666": MagicMock()},
            agent_metadata={},
        )
        with patch(
            "src.mcp_handlers.shared.get_mcp_server",
            return_value=fake_server,
        ):
            result = await handle_identity_adapter({
                "agent_uuid": "22222222-3333-4444-5555-666666666666",
                "resume": True,
            })

        text = result[0].text if result else "{}"
        data = json.loads(text)
        assert data.get("success") is True
        strict_warnings = [
            r for r in caplog.records
            if "[IDENTITY_STRICT]" in r.getMessage()
        ]
        assert not strict_warnings, "Off mode must stay silent"

    @pytest.mark.asyncio
    async def test_strict_mode_accepts_matching_token(self, monkeypatch):
        """continuity_token with aid == agent_uuid satisfies PATH 0 strict gate."""
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "strict")
        monkeypatch.setenv("UNITARES_CONTINUITY_TOKEN_SECRET", "test-secret-partc")

        from src.mcp_handlers.identity.session import create_continuity_token
        agent_uuid = "33333333-4444-5555-6666-777777777777"
        token = create_continuity_token(agent_uuid, "test-session-id")
        assert token is not None, "token creation prerequisite"

        from src.mcp_handlers.identity.handlers import handle_identity_adapter

        fake_server = MagicMock(
            monitors={agent_uuid: MagicMock()},
            agent_metadata={},
        )
        with patch(
            "src.mcp_handlers.shared.get_mcp_server",
            return_value=fake_server,
        ):
            result = await handle_identity_adapter({
                "agent_uuid": agent_uuid,
                "continuity_token": token,
                "resume": True,
            })

        data = json.loads(result[0].text)
        assert data.get("success") is True, f"Matching token must pass strict. Got: {data}"
