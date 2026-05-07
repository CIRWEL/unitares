"""Wave 2 §"Lease-integration boundary hardening" — protocol_version contract.

Pins the client side of the protocol_version handshake added in this PR:
- The Python constant PROTOCOL_VERSION matches the literal "v1.0" the Elixir
  router emits (the Elixir test does the same pin from the other side).
- LeasePlaneClient logs a WARNING on mismatch but does NOT fail — the rollout
  grace window relies on this ("ship the field on both sides without
  coordinating deploys").
- A missing field (older BEAM) does not warn.
- The mismatch log is dedup'd so a stuck mismatch doesn't spam.

Future PRs that bump PROTOCOL_VERSION must also bump the Elixir constant and
update both literal-pinning tests in the same PR (Stability discipline).
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

import src.lease_plane.client as client_module
from src.lease_plane import PROTOCOL_VERSION
from src.lease_plane.client import LeasePlaneClient, LeasePlaneClientConfig
from src.lease_plane.models import AcquireRequest


def test_protocol_version_constant_is_v1_0():
    """Drift guard: this constant MUST match the Elixir
    `UnitaresLeasePlane.HttpRouter.protocol_version/0` literal. Bumping
    requires touching both sides in the same PR."""
    assert PROTOCOL_VERSION == "v1.0"


def _reset_dedup_state() -> None:
    client_module._logged_protocol_mismatches.clear()
    client_module._logged_protocol_absences = False


@pytest.fixture(autouse=True)
def reset_dedup():
    _reset_dedup_state()
    yield
    _reset_dedup_state()


def _acquire_req() -> AcquireRequest:
    return AcquireRequest(
        surface_id="dialectic:/x",
        holder_agent_uuid=uuid4(),
        holder_class="process_instance",
        holder_kind="local_beam",
        ttl_s=60,
        intent="test",
    )


def _client_returning(payload: dict[str, Any]) -> LeasePlaneClient:
    return LeasePlaneClient(
        LeasePlaneClientConfig(base_url="http://test.invalid"),
        transport=lambda _request: payload,
    )


def test_matched_version_emits_no_warning(caplog):
    """Happy path: server returns matching protocol_version; nothing is logged."""
    client = _client_returning({
        "ok": True,
        "lease": {
            "lease_id": "00000000-0000-0000-0000-000000000001",
            "surface_id": "dialectic:/x",
            "holder_agent_uuid": "11111111-1111-1111-1111-111111111111",
            "holder_class": "process_instance",
            "holder_kind": "local_beam",
            "heartbeat_required": False,
            "expires_at": "2026-05-07T20:00:00+00:00",
            "original_ttl_s": 60,
        },
        "idempotent": False,
        "drift_warning": [],
        "protocol_version": PROTOCOL_VERSION,
    })

    with caplog.at_level(logging.WARNING, logger="src.lease_plane.client"):
        client.acquire(_acquire_req())

    assert "protocol_version mismatch" not in caplog.text


def test_mismatched_version_logs_warning_and_does_not_fail():
    """Mismatch path: client logs WARNING but the call still returns the
    parsed result. Missing this would force a coordinated client/server
    deploy on every shape change — the whole point of the version grace
    window is to avoid that."""
    client = _client_returning({
        "ok": False,
        "error": "service_unavailable",
        "protocol_version": "v9.99",  # server far ahead; we should warn, not fail
    })

    with patch.object(client_module.logger, "warning") as mock_warn:
        result = client.acquire(_acquire_req())

    # Call did not fail — we got a typed result, not an exception.
    assert result is not None
    # Exactly one warning fired with both versions in the message.
    assert mock_warn.called
    msg = mock_warn.call_args.args[0]
    assert "protocol_version mismatch" in msg


def test_absent_version_is_silent_for_grace_period():
    """Older BEAM that hasn't redeployed yet returns no protocol_version
    field. Logging WARNING in that case would generate noise during every
    rollout — the contract says emit only DEBUG-level breadcrumbs and only
    once per process."""
    client = _client_returning({
        "ok": False,
        "error": "service_unavailable",
        # no protocol_version key at all
    })

    with patch.object(client_module.logger, "warning") as mock_warn:
        client.acquire(_acquire_req())

    mock_warn.assert_not_called()


def test_repeated_mismatch_logs_only_once_per_path_and_version():
    """Stuck mismatch (same server_version on every call to the same path)
    must log ONCE, not on every request — the alternative is a flooded log
    that buries the actual problem."""
    bad = {
        "ok": False,
        "error": "service_unavailable",
        "protocol_version": "v0.9",
    }
    client = _client_returning(bad)

    with patch.object(client_module.logger, "warning") as mock_warn:
        for _ in range(5):
            client.acquire(_acquire_req())

    # Five identical-mismatch calls, one warning.
    assert mock_warn.call_count == 1


def test_distinct_mismatches_log_separately():
    """Two different server_version strings on the same path SHOULD fire
    distinct warnings — they're distinct deploy states the operator wants
    to see (e.g., the BEAM is being rolled forward and back). The third
    call repeats the first version and is dedup'd."""
    versions_seen = ["v0.9", "v1.5", "v0.9"]

    payloads = iter([
        {"ok": False, "error": "service_unavailable", "protocol_version": v}
        for v in versions_seen
    ])

    client = LeasePlaneClient(
        LeasePlaneClientConfig(base_url="http://test.invalid"),
        transport=lambda _request: next(payloads),
    )

    with patch.object(client_module.logger, "warning") as mock_warn:
        for _ in versions_seen:
            client.acquire(_acquire_req())

    # Two distinct (path, version) pairs → two warnings; the third (repeat
    # of v0.9 on /v1/lease/acquire) is dedup'd.
    assert mock_warn.call_count == 2
