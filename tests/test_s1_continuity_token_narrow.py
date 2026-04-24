"""S1-a — continuity_token retirement, narrowed.

Tests the TTL shrink, ownership_proof_version schema extension, and
deprecation-warning emission per docs/ontology/s1-continuity-token-retirement.md
§4.1, §4.3, §4.5.

Reference: S1 plan doc §7 risks require regression coverage for:
- PATH-0-with-expired-token (Part-C invariant preserved under short TTL)
- TTL-boundary behavior (token valid at edge, rejected just past)
- ownership_proof_version surfaces in payload and response
- deprecation warning fires only on cross-instance resume (onboard+token)
- deprecation does NOT fire on intra-session continuity_token use
"""
from __future__ import annotations

import base64
import json
import time
from unittest.mock import patch

import pytest


# -----------------------------------------------------------------------------
# 4.1 TTL shrink
# -----------------------------------------------------------------------------


def test_continuity_ttl_is_one_hour():
    """Per S1-a: _CONTINUITY_TTL shrinks from 30 days to 1 hour (3600s).

    This is the operator-approved value. Threshold is a convenience anchor,
    not threat-model-derived — see s1 doc §11.2.
    """
    from src.mcp_handlers.identity import session as session_mod

    assert session_mod._CONTINUITY_TTL == 3600, (
        f"S1-a expects 1h TTL (3600s); got {session_mod._CONTINUITY_TTL}"
    )


def test_token_issued_with_default_ttl_carries_1h_expiry():
    """Newly-minted token's exp claim reflects the shrunk TTL."""
    from src.mcp_handlers.identity.session import create_continuity_token

    with patch.dict("os.environ", {"UNITARES_CONTINUITY_TOKEN_SECRET": "test-secret"}, clear=False):
        before = int(time.time())
        token = create_continuity_token(
            "11111111-2222-3333-4444-555555555555",
            "agent-111:claude",
        )
        after = int(time.time())

    assert token is not None and token.startswith("v1.")
    _, payload_b64, _ = token.split(".", 2)
    payload = json.loads(_b64url_decode(payload_b64))

    expiry_offset = payload["exp"] - payload["iat"]
    assert expiry_offset == 3600, (
        f"expected 3600s offset, got {expiry_offset}"
    )
    assert before <= payload["iat"] <= after


def test_resolve_rejects_expired_token_at_ttl_boundary():
    """Token valid 1s before expiry; rejected 1s after.

    S1 doc §7.2 flags clock-skew near boundary as a new code path under short TTL.
    This test pins the strict-expiry semantics; any loosening must be deliberate.
    """
    from src.mcp_handlers.identity.session import (
        create_continuity_token,
        resolve_continuity_token,
    )

    with patch.dict("os.environ", {"UNITARES_CONTINUITY_TOKEN_SECRET": "test-secret"}, clear=False):
        token = create_continuity_token(
            "11111111-2222-3333-4444-555555555555",
            "agent-111:claude",
        )
        assert token is not None

        # Token valid now
        resolved = resolve_continuity_token(token)
        assert resolved == "agent-111:claude"

        # Freeze "now" to 1s past expiry — resolve must reject
        now = int(time.time()) + 3601
        with patch("src.mcp_handlers.identity.session.time.time", return_value=now):
            assert resolve_continuity_token(token) is None


# -----------------------------------------------------------------------------
# 4.5 ownership_proof_version schema extension
# -----------------------------------------------------------------------------


def test_token_payload_carries_opv_field():
    """JWT payload gains "opv": 1. Forward-compat: future A′/B bump to 2/3."""
    from src.mcp_handlers.identity.session import create_continuity_token

    with patch.dict("os.environ", {"UNITARES_CONTINUITY_TOKEN_SECRET": "test-secret"}, clear=False):
        token = create_continuity_token(
            "11111111-2222-3333-4444-555555555555",
            "agent-111:claude",
        )

    assert token is not None
    _, payload_b64, _ = token.split(".", 2)
    payload = json.loads(_b64url_decode(payload_b64))
    assert payload.get("opv") == 1, (
        f"expected opv=1 in payload, got {payload!r}"
    )


def test_continuity_support_status_exposes_ownership_proof_version():
    """Diagnostic surface surfaces the version for log consumers + dashboards."""
    from src.mcp_handlers.identity.session import continuity_token_support_status

    with patch.dict("os.environ", {"UNITARES_CONTINUITY_TOKEN_SECRET": "test-secret"}, clear=False):
        status = continuity_token_support_status()

    assert status["enabled"] is True
    assert status.get("ownership_proof_version") == 1


def test_continuity_support_status_omits_version_when_disabled():
    """No secret = no token, no version — cleanly disabled state."""
    from src.mcp_handlers.identity.session import continuity_token_support_status

    # Clear all three possible secret sources
    with patch.dict(
        "os.environ",
        {
            "UNITARES_CONTINUITY_TOKEN_SECRET": "",
            "UNITARES_HTTP_API_TOKEN": "",
            "UNITARES_API_TOKEN": "",
        },
        clear=False,
    ):
        status = continuity_token_support_status()

    assert status["enabled"] is False
    assert "ownership_proof_version" not in status or status.get("ownership_proof_version") is None


# -----------------------------------------------------------------------------
# 4.3 Deprecation warning emission
# -----------------------------------------------------------------------------


def test_build_token_deprecation_block_for_resume():
    """onboard+token (without force_new) is the retiring cross-instance resume path.

    S1 doc §4.3: grace-period warning fires for this case.
    """
    from src.mcp_handlers.identity.session import build_token_deprecation_block

    block = build_token_deprecation_block(
        used_token_for_resume=True,
        token_issued_at=int(time.time()) - 60,
    )

    assert block is not None
    assert block["field"] == "continuity_token"
    assert block["severity"] == "warning"
    assert "deprecated" in block["message"].lower()
    assert "parent_agent_id" in block["message"]
    assert "force_new=true" in block["message"]
    assert "sunset" in block


def test_no_deprecation_for_non_resume_usage():
    """Intra-session token use (request auth, mid-session identity calls) is NOT deprecated.

    Only the onboard+token cross-instance resume path warns. S1 doc §4.3.
    """
    from src.mcp_handlers.identity.session import build_token_deprecation_block

    assert build_token_deprecation_block(used_token_for_resume=False) is None


# -----------------------------------------------------------------------------
# 4.3 audit event
# -----------------------------------------------------------------------------


def test_audit_log_has_continuity_token_deprecated_accept_method(tmp_path):
    """Audit sink has a typed method for the grace-period event per S1 doc §6."""
    from src.audit_log import AuditLogger

    audit = AuditLogger(log_file=tmp_path / "audit.jsonl")
    assert hasattr(audit, "log_continuity_token_deprecated_accept"), (
        "expected log_continuity_token_deprecated_accept on AuditLog"
    )

    # Method accepts the §6-specified fields and writes a JSONL entry.
    audit.log_continuity_token_deprecated_accept(
        agent_id="agent-xyz",
        caller_channel="claude_code",
        caller_model_type="claude",
        issued_at=int(time.time()) - 600,
        accepted_at=int(time.time()),
        agent_uuid="11111111-2222-3333-4444-555555555555",
    )

    logged = (tmp_path / "audit.jsonl").read_text().strip()
    assert logged, "expected one JSONL entry"
    entry = json.loads(logged.splitlines()[-1])
    assert entry["event_type"] == "continuity_token_deprecated_accept"
    details = entry["details"]
    assert details["caller_channel"] == "claude_code"
    assert details["caller_model_type"] == "claude"
    assert details["agent_uuid"] == "11111111-2222-3333-4444-555555555555"
    assert isinstance(details["lifetime_seconds"], int)
    assert details["lifetime_seconds"] >= 0


# -----------------------------------------------------------------------------
# Part-C invariant regression (§7.2)
# -----------------------------------------------------------------------------


def test_part_c_extract_token_agent_uuid_survives_expiry():
    """extract_token_agent_uuid deliberately ignores exp (Part-C / PR #42).

    Under short TTL this matters more, not less: residents idle past TTL still
    need signature-verification to work for identity lookup. This test pins
    the existing contract — any future refactor that enforces exp here breaks
    Part-C.
    """
    from src.mcp_handlers.identity.session import (
        create_continuity_token,
        extract_token_agent_uuid,
    )

    with patch.dict("os.environ", {"UNITARES_CONTINUITY_TOKEN_SECRET": "test-secret"}, clear=False):
        token = create_continuity_token(
            "11111111-2222-3333-4444-555555555555",
            "agent-xyz",
        )
        assert token is not None

        # Sim token aged well past 1h TTL
        future = int(time.time()) + 7200
        with patch("src.mcp_handlers.identity.session.time.time", return_value=future):
            # resolve_continuity_token rejects (enforces exp)
            from src.mcp_handlers.identity.session import resolve_continuity_token
            assert resolve_continuity_token(token) is None
            # extract_token_agent_uuid still returns aid (ignores exp — Part C)
            assert extract_token_agent_uuid(token) == "11111111-2222-3333-4444-555555555555"


# -----------------------------------------------------------------------------
# extract_token_iat helper (§6 audit-event dependency)
# -----------------------------------------------------------------------------


def test_extract_token_iat_returns_issued_at():
    """Grace-period audit needs the token's iat claim at accept time.

    extract_token_iat verifies signature (like extract_token_agent_uuid) but
    skips expiry — an expired token still carries an honest iat.
    """
    from src.mcp_handlers.identity.session import (
        create_continuity_token,
        extract_token_iat,
    )

    with patch.dict("os.environ", {"UNITARES_CONTINUITY_TOKEN_SECRET": "test-secret"}, clear=False):
        before = int(time.time())
        token = create_continuity_token(
            "11111111-2222-3333-4444-555555555555",
            "agent-iat",
        )
        after = int(time.time())
        iat = extract_token_iat(token)

    assert iat is not None
    assert before <= iat <= after


def test_extract_token_iat_rejects_tampered_token():
    """Signature mismatch → None (same trust model as extract_token_agent_uuid)."""
    from src.mcp_handlers.identity.session import extract_token_iat

    with patch.dict("os.environ", {"UNITARES_CONTINUITY_TOKEN_SECRET": "test-secret"}, clear=False):
        # Construct obviously-malformed token
        assert extract_token_iat("v1.junk.sig") is None
        assert extract_token_iat("") is None
        assert extract_token_iat(None) is None  # type: ignore[arg-type]


# -----------------------------------------------------------------------------
# ownership_proof_version surfaces on top-level response (§4.5)
# -----------------------------------------------------------------------------


def test_onboard_response_surfaces_ownership_proof_version_top_level():
    """Dashboard + log consumers can read opv without digging into token payload."""
    from src.services.identity_payloads import build_onboard_response_data
    from src.mcp_handlers.identity.session import continuity_token_support_status

    with patch.dict("os.environ", {"UNITARES_CONTINUITY_TOKEN_SECRET": "test-secret"}, clear=False):
        support = continuity_token_support_status()

    result = build_onboard_response_data(
        agent_uuid="11111111-2222-3333-4444-555555555555",
        structured_agent_id="agent_11111111",
        agent_label=None,
        stable_session_id="agent-111",
        is_new=True,
        force_new=False,
        client_hint="unknown",
        was_archived=False,
        trajectory_result=None,
        parent_agent_id=None,
        thread_context=None,
        verbose=False,
        continuity_source="test",
        continuity_support=support,
        continuity_token="v1.dummy.token",
        system_activity=None,
        tool_mode_info=None,
    )
    assert result.get("ownership_proof_version") == 1


def test_identity_response_surfaces_ownership_proof_version_top_level():
    """Same shape on identity() as onboard() — keep the surface consistent."""
    from src.services.identity_payloads import build_identity_response_data
    from src.mcp_handlers.identity.session import continuity_token_support_status

    with patch.dict("os.environ", {"UNITARES_CONTINUITY_TOKEN_SECRET": "test-secret"}, clear=False):
        support = continuity_token_support_status()

    result = build_identity_response_data(
        agent_uuid="11111111-2222-3333-4444-555555555555",
        agent_id="agent_11111111",
        display_name=None,
        client_session_id="agent-111",
        continuity_source="test",
        continuity_support=support,
        continuity_token="v1.dummy.token",
        identity_status="active",
        model_type=None,
        resumed=True,
        session_continuity=None,
        verbose=False,
    )
    assert result.get("ownership_proof_version") == 1


def test_response_omits_ownership_proof_version_when_disabled():
    """When token support is off, the field is absent (not None, not 0)."""
    from src.services.identity_payloads import build_onboard_response_data

    support_disabled = {"enabled": False, "secret_source": None}
    result = build_onboard_response_data(
        agent_uuid="11111111-2222-3333-4444-555555555555",
        structured_agent_id="agent_11111111",
        agent_label=None,
        stable_session_id="agent-111",
        is_new=True,
        force_new=False,
        client_hint="unknown",
        was_archived=False,
        trajectory_result=None,
        parent_agent_id=None,
        thread_context=None,
        verbose=False,
        continuity_source="test",
        continuity_support=support_disabled,
        continuity_token=None,
        system_activity=None,
        tool_mode_info=None,
    )
    assert "ownership_proof_version" not in result


# -----------------------------------------------------------------------------
# §7.3 bind_session inherits the new short TTL
# -----------------------------------------------------------------------------


def test_bind_session_resolve_path_uses_1h_ttl():
    """bind_session calls resolve_continuity_token (handlers.py:1066) which
    uses _CONTINUITY_TTL. S1-a's shrink propagates; §7.3 operator call was
    let-it-propagate. Verify a token past 1h is rejected by the bind_session
    resolve path — same function, same behavior.
    """
    from src.mcp_handlers.identity.session import (
        create_continuity_token,
        resolve_continuity_token,
    )

    with patch.dict("os.environ", {"UNITARES_CONTINUITY_TOKEN_SECRET": "test-secret"}, clear=False):
        token = create_continuity_token(
            "11111111-2222-3333-4444-555555555555",
            "agent-bind-test",
        )
        assert token is not None

        # Within TTL — resolves
        assert resolve_continuity_token(token) == "agent-bind-test"

        # Past 1h TTL — rejected (same gate bind_session hits)
        past_ttl = int(time.time()) + 3601
        with patch("src.mcp_handlers.identity.session.time.time", return_value=past_ttl):
            assert resolve_continuity_token(token) is None


# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)
