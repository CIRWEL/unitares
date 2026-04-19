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
