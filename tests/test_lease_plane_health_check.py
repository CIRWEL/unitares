"""Wave 2 §"Lease-integration boundary hardening" — Phase C (supervised health).

Pins the client side of the /v1/health probe added in this PR:
- Happy path: BEAM returns {ok: true, status: "ok"} → HealthOk
- Network failure: transport raises → HealthUnavailable with named reason
- Auth/server error: ok:false envelope → HealthUnavailable preserves reason
- Body shape mismatch: validation error → HealthUnavailable with detail
- Timeout override: caller-supplied tighter budget propagates to transport
- Health probe NEVER raises (failure-safe contract for supervisors)
- Bearer token forwarded when configured

The Elixir test (`test/lease_plane_health_test.exs`) pins the server side
of the same handshake (200 envelope shape + `protocol_version` injection).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

import src.lease_plane.client as client_module
from src.lease_plane import (
    HealthOk,
    HealthUnavailable,
    LeasePlaneClient,
    LeasePlaneClientConfig,
)


def _client_returning(payload: Any) -> LeasePlaneClient:
    return LeasePlaneClient(
        LeasePlaneClientConfig(base_url="http://test.invalid", bearer_token="t"),
        transport=lambda _request: payload,
    )


def _client_raising(exc: Exception) -> LeasePlaneClient:
    def transport(_request):
        raise exc
    return LeasePlaneClient(
        LeasePlaneClientConfig(base_url="http://test.invalid", bearer_token="t"),
        transport=transport,
    )


@pytest.fixture(autouse=True)
def reset_protocol_dedup():
    """Clear protocol-version mismatch dedup state between tests so each
    test sees a clean log surface."""
    client_module._logged_protocol_mismatches.clear()
    client_module._logged_protocol_absences = False
    yield
    client_module._logged_protocol_mismatches.clear()
    client_module._logged_protocol_absences = False


# ============================================================================
# Happy path
# ============================================================================


def test_health_check_ok_returns_typed_health_ok():
    """200 + {ok: true, status: "ok"} → HealthOk."""
    client = _client_returning({"ok": True, "status": "ok", "protocol_version": "v1.0"})
    result = client.health_check()
    assert isinstance(result, HealthOk)
    assert result.ok is True
    assert result.status == "ok"


def test_health_check_tolerates_unknown_extra_fields():
    """Phase C ships minimal payload; future phases add fields like
    `db_ready`, `inflight_lease_count`. Pydantic default extra="ignore"
    means unknown fields don't break the typed parse — pin that contract
    so older clients keep working when servers add fields."""
    client = _client_returning({
        "ok": True,
        "status": "ok",
        "protocol_version": "v1.0",
        "db_ready": True,
        "inflight_lease_count": 3,
    })
    result = client.health_check()
    assert isinstance(result, HealthOk)


# ============================================================================
# Failure paths
# ============================================================================


def test_health_check_returns_unavailable_on_transport_failure():
    """Network failure (connection refused, DNS, etc.) → HealthUnavailable
    with the exception class name in `reason`. Health probe NEVER raises."""
    client = _client_raising(ConnectionRefusedError("nope"))
    result = client.health_check()
    assert isinstance(result, HealthUnavailable)
    assert result.error == "service_unavailable"
    assert "ConnectionRefusedError" in result.reason


def test_health_check_returns_unavailable_on_non_object_response():
    """Server returned non-JSON or a non-object JSON body. The transport
    helper might surface this as a non-Mapping; health_check must coerce
    to HealthUnavailable rather than crash."""
    client = _client_returning("plain text response")
    result = client.health_check()
    assert isinstance(result, HealthUnavailable)
    assert "JSON object" in result.reason


def test_health_check_passes_through_server_reason_on_failure_envelope():
    """If the server returns ok:false (e.g., 503 with a JSON body), preserve
    the server's `reason` so the operator sees what the BEAM actually said."""
    client = _client_returning({
        "ok": False,
        "error": "service_unavailable",
        "reason": "db pool not ready",
        "protocol_version": "v1.0",
    })
    result = client.health_check()
    assert isinstance(result, HealthUnavailable)
    assert result.reason == "db pool not ready"


def test_health_check_falls_back_to_error_when_no_reason():
    """Some servers return ok:false without a reason field. Surface the
    error discriminant so the result has actionable info."""
    client = _client_returning({"ok": False, "error": "permission_denied"})
    result = client.health_check()
    assert isinstance(result, HealthUnavailable)
    assert "permission_denied" in result.reason


def test_health_check_returns_unavailable_on_validation_error():
    """A 200 with an unexpected envelope shape (e.g., status="degraded"
    when the contract says Literal["ok"]) must NOT silently parse as
    HealthOk. Pin the validation-error path."""
    client = _client_returning({
        "ok": True,
        "status": "degraded",  # Literal["ok"] doesn't accept this
        "protocol_version": "v1.0",
    })
    result = client.health_check()
    assert isinstance(result, HealthUnavailable)
    assert "validation" in result.reason.lower()


# ============================================================================
# Timeout override
# ============================================================================


def test_health_check_timeout_override_propagates_to_transport():
    """Health probes typically want a tighter budget than full lease ops.
    The `timeout_s` kwarg overrides the client's default for THIS probe
    only — neighboring acquire/status calls keep their original timeout."""
    seen_timeouts = []

    def recording_transport(request):
        seen_timeouts.append(request.timeout_s)
        return {"ok": True, "status": "ok", "protocol_version": "v1.0"}

    client = LeasePlaneClient(
        LeasePlaneClientConfig(base_url="http://test.invalid", bearer_token="t", timeout_s=10.0),
        transport=recording_transport,
    )
    client.health_check(timeout_s=1.5)
    assert seen_timeouts == [1.5]


def test_health_check_default_timeout_falls_back_to_config():
    seen_timeouts = []

    def recording_transport(request):
        seen_timeouts.append(request.timeout_s)
        return {"ok": True, "status": "ok", "protocol_version": "v1.0"}

    client = LeasePlaneClient(
        LeasePlaneClientConfig(base_url="http://test.invalid", bearer_token="t", timeout_s=7.5),
        transport=recording_transport,
    )
    client.health_check()
    assert seen_timeouts == [7.5]


# ============================================================================
# Bearer auth
# ============================================================================


def test_health_check_forwards_bearer_token():
    """Health endpoint goes through the same auth plug as every other
    route. Token must be in Authorization header."""
    seen_headers = []

    def recording_transport(request):
        seen_headers.append(dict(request.headers))
        return {"ok": True, "status": "ok", "protocol_version": "v1.0"}

    client = LeasePlaneClient(
        LeasePlaneClientConfig(base_url="http://test.invalid", bearer_token="secret-xyz"),
        transport=recording_transport,
    )
    client.health_check()
    assert seen_headers[0].get("Authorization") == "Bearer secret-xyz"


def test_health_check_omits_authorization_when_no_token_configured():
    """When no bearer is configured, the request is sent without an
    Authorization header — the server will respond 401 and the client will
    parse that as HealthUnavailable. Pin this to catch a future refactor
    that accidentally sends `Bearer ` with empty token (always 401)."""
    seen_headers = []

    def recording_transport(request):
        seen_headers.append(dict(request.headers))
        return {"ok": False, "error": "permission_denied", "reason": "missing token"}

    client = LeasePlaneClient(
        LeasePlaneClientConfig(base_url="http://test.invalid", bearer_token=""),
        transport=recording_transport,
    )
    result = client.health_check()
    assert "Authorization" not in seen_headers[0]
    assert isinstance(result, HealthUnavailable)


# ============================================================================
# Failure-safe contract
# ============================================================================


def test_health_check_does_not_propagate_arbitrary_exceptions():
    """Supervisors call health_check in tight loops; any exception leaking
    out would crash the supervisor. Verify the BroadException-Like-Anything
    contract by raising several kinds of errors and confirming each becomes
    HealthUnavailable."""
    for exc in [
        OSError("network down"),
        TimeoutError("read timeout"),
        ValueError("transport bug"),
        RuntimeError("unexpected"),
    ]:
        client = _client_raising(exc)
        result = client.health_check()
        assert isinstance(result, HealthUnavailable), (
            f"health_check leaked {type(exc).__name__}: {exc}"
        )
        assert type(exc).__name__ in result.reason
