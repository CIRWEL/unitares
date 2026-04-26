"""S19 PR3e: substrate-attestation gate in _try_resume_by_agent_uuid_direct.

Verifies that ``handle_identity_adapter`` (and therefore PATH 0 resume)
respects the substrate-attestation gate added by PR3e:

- HTTP path (peer_pid is None) → behavior unchanged from PR3d baseline.
- UDS path with no substrate-claim row → behavior unchanged (falls through
  to existing Part-C strict-mode handling).
- UDS path with substrate-claim row + verify accepts → resume proceeds
  even without continuity_token (substrate attestation = ownership proof).
- UDS path with substrate-claim row + verify rejects → explicit-rejection
  error with the verification's failure_code in recovery.

These tests mock ``verify_substrate_at_resume`` (the helper from PR3d) so
no DB / no subprocess / no ctypes calls happen; the focus is the wiring
correctness, not the verification logic itself (already tested in
``test_substrate_handler_gate.py``).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp_handlers.context import (
    SessionSignals,
    set_session_signals,
    reset_session_signals,
)
from src.substrate.verification import VerificationResult


_TEST_UUID = "ffffffff-1111-2222-3333-444444444444"


@pytest.fixture
def _strict_mode(monkeypatch):
    """Run under identity strict mode so PATH 0 actually rejects on Part-C
    failure (otherwise the substrate gate is moot — log/off modes would
    let the resume proceed regardless)."""
    monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "strict")


# =============================================================================
# HTTP path: peer_pid is None — behavior unchanged from baseline
# =============================================================================


@pytest.mark.asyncio
async def test_http_path_no_peer_pid_falls_through_to_strict_reject(_strict_mode):
    """No SessionSignals at all (HTTP test fixture): strict-mode reject as before."""
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
            "agent_uuid": _TEST_UUID,
            "resume": True,
        })

    data = json.loads(result[0].text)
    assert data.get("success") is False
    err = (data.get("error") or "").lower()
    assert "bare" in err or "continuity_token" in err
    # Substrate gate was not invoked (peer_pid is None) — error message
    # is the existing strict-mode message, not a substrate-specific one.
    assert "substrate" not in err


# =============================================================================
# UDS path: peer_pid set, no substrate-claim row → fall through unchanged
# =============================================================================


@pytest.mark.asyncio
async def test_uds_path_no_claim_falls_through_to_strict_reject(_strict_mode):
    """peer_pid is set but UUID has no substrate-claim → existing strict-mode reject."""
    from src.mcp_handlers.identity.handlers import handle_identity_adapter

    signals_token = set_session_signals(SessionSignals(peer_pid=12345))
    try:
        fake_server = MagicMock(monitors={}, agent_metadata={})
        with patch(
            "src.substrate.handler_gate.verify_substrate_at_resume",
            new=AsyncMock(return_value=None),  # None = no claim
        ), patch(
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
                "agent_uuid": _TEST_UUID,
                "resume": True,
            })
    finally:
        reset_session_signals(signals_token)

    data = json.loads(result[0].text)
    assert data.get("success") is False
    err = (data.get("error") or "").lower()
    # Falls through to existing strict-mode message (not substrate-specific)
    assert "bare" in err or "continuity_token" in err
    assert "substrate" not in err


# =============================================================================
# UDS path: substrate verification accepts → resume succeeds without token
# =============================================================================


@pytest.mark.asyncio
async def test_uds_path_substrate_accepts_allows_resume(_strict_mode):
    """peer_pid + claim + verify accepts → resume proceeds, no error."""
    from src.mcp_handlers.identity.handlers import handle_identity_adapter

    signals_token = set_session_signals(SessionSignals(peer_pid=12345))
    try:
        fake_server = MagicMock(
            monitors={_TEST_UUID: MagicMock()},  # so PATH 0 fast-path hits
            agent_metadata={},
        )
        accepted = VerificationResult(
            accepted=True,
            reason="substrate-claim verified",
        )
        with patch(
            "src.substrate.handler_gate.verify_substrate_at_resume",
            new=AsyncMock(return_value=accepted),
        ), patch(
            "src.mcp_handlers.shared.get_mcp_server",
            return_value=fake_server,
        ):
            result = await handle_identity_adapter({
                "agent_uuid": _TEST_UUID,
                "resume": True,
            })
    finally:
        reset_session_signals(signals_token)

    data = json.loads(result[0].text)
    assert data.get("success") is True, f"Expected accept, got: {data}"


# =============================================================================
# UDS path: substrate verification rejects → explicit error with failure_code
# =============================================================================


@pytest.mark.asyncio
async def test_uds_path_substrate_rejects_returns_explicit_error(_strict_mode):
    """peer_pid + claim + verify rejects → explicit-rejection naming the cause."""
    from src.mcp_handlers.identity.handlers import handle_identity_adapter

    signals_token = set_session_signals(SessionSignals(peer_pid=12345))
    try:
        fake_server = MagicMock(monitors={}, agent_metadata={})
        rejected = VerificationResult(
            accepted=False,
            reason=(
                "launchd label mismatch for PID 12345: "
                "registered 'com.unitares.sentinel', observed 'com.someone.else'"
            ),
            failure_code="label_mismatch",
        )
        with patch(
            "src.substrate.handler_gate.verify_substrate_at_resume",
            new=AsyncMock(return_value=rejected),
        ), patch(
            "src.mcp_handlers.shared.get_mcp_server",
            return_value=fake_server,
        ):
            result = await handle_identity_adapter({
                "agent_uuid": _TEST_UUID,
                "resume": True,
            })
    finally:
        reset_session_signals(signals_token)

    data = json.loads(result[0].text)
    assert data.get("success") is False
    err = data.get("error") or ""
    # Error message is the substrate-specific reason, not the generic strict-mode one.
    assert "label mismatch" in err.lower()
    recovery = data.get("recovery") or {}
    assert recovery.get("reason") == "label_mismatch", (
        f"recovery should expose failure_code; got {recovery!r}"
    )


@pytest.mark.asyncio
async def test_uds_path_pid_reuse_rejection_propagates(_strict_mode):
    """Q3(e) PID-reuse rejection surfaces with failure_code='pid_reuse'."""
    from src.mcp_handlers.identity.handlers import handle_identity_adapter

    signals_token = set_session_signals(SessionSignals(peer_pid=12345))
    try:
        fake_server = MagicMock(monitors={}, agent_metadata={})
        rejected = VerificationResult(
            accepted=False,
            reason=(
                "PID reuse detected for ffffffff-...: "
                "PID 12345 previously had start_tvsec=1777000000, "
                "now 1777000999 (different process)"
            ),
            failure_code="pid_reuse",
        )
        with patch(
            "src.substrate.handler_gate.verify_substrate_at_resume",
            new=AsyncMock(return_value=rejected),
        ), patch(
            "src.mcp_handlers.shared.get_mcp_server",
            return_value=fake_server,
        ):
            result = await handle_identity_adapter({
                "agent_uuid": _TEST_UUID,
                "resume": True,
            })
    finally:
        reset_session_signals(signals_token)

    data = json.loads(result[0].text)
    assert data.get("success") is False
    recovery = data.get("recovery") or {}
    assert recovery.get("reason") == "pid_reuse"


# =============================================================================
# Defense-in-depth: gate exception falls through to strict-mode (not accept)
# =============================================================================


@pytest.mark.asyncio
async def test_uds_path_gate_exception_falls_through_to_strict_reject(_strict_mode):
    """Truly unexpected exception in the gate falls through to existing
    strict-mode behavior — does NOT default-accept."""
    from src.mcp_handlers.identity.handlers import handle_identity_adapter

    signals_token = set_session_signals(SessionSignals(peer_pid=12345))
    try:
        fake_server = MagicMock(monitors={}, agent_metadata={})
        with patch(
            "src.substrate.handler_gate.verify_substrate_at_resume",
            new=AsyncMock(side_effect=ImportError("boom")),
        ), patch(
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
                "agent_uuid": _TEST_UUID,
                "resume": True,
            })
    finally:
        reset_session_signals(signals_token)

    data = json.loads(result[0].text)
    assert data.get("success") is False, "Must fail closed on gate exception"
    err = (data.get("error") or "").lower()
    # Falls through to existing strict-mode message
    assert "bare" in err or "continuity_token" in err
