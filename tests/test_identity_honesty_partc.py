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


class TestMiddlewarePath0Gate:
    """Middleware PATH 0 passthrough must enforce the same ownership proof."""

    @pytest.mark.asyncio
    async def test_middleware_strict_rejects_bare_uuid(self, monkeypatch):
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "strict")
        from src.mcp_handlers.middleware.identity_step import resolve_identity

        signals = MagicMock(
            transport="http",
            user_agent="claude-test",
            ip_ua_fingerprint="ua:deadbe",
            x_session_id=None,
            x_agent_id=None,
            mcp_session_id=None,
            oauth_client_id=None,
            x_client_id=None,
            client_hint=None,
        )
        with patch(
            "src.mcp_handlers.context.get_session_signals",
            return_value=signals,
        ):
            ctx = MagicMock()
            ctx.strict_reject = False
            ctx.identity_result = None
            name, args, ret_ctx = await resolve_identity(
                "identity",
                {
                    "agent_uuid": "44444444-5555-6666-7777-888888888888",
                    "resume": True,
                },
                ctx,
            )

        assert ret_ctx.strict_reject is True, (
            f"Middleware should set strict_reject in strict mode. ctx={ret_ctx!r}"
        )
        assert ret_ctx.identity_result.get("reason") == "bare_uuid_resume_denied"

    @pytest.mark.asyncio
    async def test_middleware_log_mode_passes_through(self, monkeypatch, caplog):
        import logging
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "log")
        caplog.set_level(logging.WARNING)
        from src.mcp_handlers.middleware.identity_step import resolve_identity

        signals = MagicMock(
            transport="http",
            user_agent="claude-test",
            ip_ua_fingerprint="ua:deadbe",
            x_session_id=None,
            x_agent_id=None,
            mcp_session_id=None,
            oauth_client_id=None,
            x_client_id=None,
            client_hint=None,
        )
        with patch(
            "src.mcp_handlers.context.get_session_signals",
            return_value=signals,
        ):
            ctx = MagicMock()
            ctx.strict_reject = False
            await resolve_identity(
                "identity",
                {
                    "agent_uuid": "55555555-6666-7777-8888-999999999999",
                    "resume": True,
                },
                ctx,
            )

        assert ctx.strict_reject is False, "Log mode must not reject"
        strict_warnings = [
            r for r in caplog.records
            if "[IDENTITY_STRICT]" in r.getMessage()
        ]
        assert strict_warnings, "Log mode must surface warning"


class TestFallback2Gate:
    """agent_auth.require_agent_id FALLBACK 2 (auto_<ts>_<uuid8>) must gate."""

    def test_strict_mode_rejects_auto_generation(self, monkeypatch):
        """In strict mode, no agent_id + no session binding → error, no ghost."""
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "strict")
        from src.mcp_handlers.support.agent_auth import require_agent_id

        args: dict = {}
        with patch(
            "src.mcp_handlers.context.get_context_agent_id",
            return_value=None,
        ):
            agent_id, error = require_agent_id(args)

        assert agent_id is None
        assert error is not None
        assert "onboard" in error.lower() or "identity" in error.lower()
        assert "agent_id" not in args or not (args.get("agent_id") or "").startswith("auto_")

    def test_log_mode_warns_but_generates(self, monkeypatch, caplog):
        """In log mode, the ghost still gets created but the warning surfaces."""
        import logging
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "log")
        caplog.set_level(logging.WARNING)
        from src.mcp_handlers.support.agent_auth import require_agent_id

        args: dict = {}
        with patch(
            "src.mcp_handlers.context.get_context_agent_id",
            return_value=None,
        ):
            agent_id, error = require_agent_id(args)

        assert error is None
        assert agent_id is not None and agent_id.startswith("auto_")
        strict_warnings = [
            r for r in caplog.records
            if "[IDENTITY_STRICT]" in r.getMessage()
        ]
        assert strict_warnings, "Log mode must surface the FALLBACK 2 ghost creation"


class TestResidentRegression:
    """Resident agents pass continuity_token alongside agent_uuid when saved."""

    def test_sdk_base_agent_copies_token_to_client(self):
        """_ensure_identity must set client.continuity_token before identity() call."""
        import sys
        import pathlib
        sdk_path = pathlib.Path(
            "/Users/cirwel/projects/unitares/.worktrees/identity-honesty-partc/agents/sdk/src"
        )
        if str(sdk_path) not in sys.path:
            sys.path.insert(0, str(sdk_path))

        from unitares_sdk.agent import GovernanceAgent

        captured = {}

        stub = GovernanceAgent.__new__(GovernanceAgent)
        # Bypass __init__ to avoid session-file I/O side effects.
        stub.name = "Test"
        stub.persistent = True
        stub.agent_uuid = "55555555-6666-7777-8888-999999999999"
        stub.client_session_id = None
        stub.continuity_token = "v1.aGVsbG8.d29ybGQ"  # plumbing-only; not verified
        stub.parent_agent_id = None
        stub.spawn_reason = None
        stub.session_file = pathlib.Path("/tmp/nonexistent-partc-regression.json")
        stub.legacy_session_file = None

        client = MagicMock()
        client.continuity_token = None
        client.client_session_id = None
        client.agent_uuid = stub.agent_uuid

        async def _capture_identity(*args, **kwargs):
            captured["client_token_at_call"] = client.continuity_token
            return {"agent_uuid": stub.agent_uuid}

        client.identity = AsyncMock(side_effect=_capture_identity)

        import asyncio
        asyncio.run(stub._ensure_identity(client))

        assert captured.get("client_token_at_call") == "v1.aGVsbG8.d29ybGQ", (
            "BaseAgent must copy self.continuity_token to client BEFORE the "
            "identity() call so call_tool auto-injects it. "
            f"Got client.continuity_token at call time: {captured.get('client_token_at_call')!r}"
        )
