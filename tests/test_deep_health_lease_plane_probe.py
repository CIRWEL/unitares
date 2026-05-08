"""Wave 2 Phase C.5 (#417 follow-on) — deep-health probe of the BEAM lease-plane.

Pins the helper that surfaces the Python↔BEAM boundary in
governance-mcp's deep-health snapshot:
- HealthOk → status="healthy"
- HealthUnavailable → status="warning" with reason preserved
- Exception (import failure, misconfig, runtime bug) → status="error",
  isolated from the rest of the snapshot
- The probe NEVER raises (fail-safe by composition with LeasePlaneClient
  which itself never raises)

Phase C ships the probe; the deep-health probe task in
`src/background_tasks.py:deep_health_probe_task` calls
`get_health_check_data` every PROBE_INTERVAL_SECONDS (30s) and the
result lands at `/health/deep` for operators and the dashboard panel.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from src.lease_plane import HealthOk, HealthUnavailable


def _probe():
    """Lazy import to avoid the circular-import chain that fires when
    runtime_queries is imported top-level by a test (mcp_handlers/__init__
    imports outcome_events which imports back into runtime_queries during
    module init). Pre-importing mcp_handlers fully first lets the cycle
    settle: the second-level imports inside outcome_events resolve once
    runtime_queries is fully loaded."""
    import src.mcp_handlers  # noqa: F401 — warm the module cycle first
    from src.services.runtime_queries import _probe_lease_plane_boundary
    return _probe_lease_plane_boundary


@pytest.mark.asyncio
async def test_probe_returns_healthy_on_health_ok():
    """Happy path: BEAM responds with HealthOk → snapshot entry is healthy."""
    fake_client = type("FakeClient", (), {
        "health_check": lambda self, *, timeout_s=None: HealthOk(ok=True, status="ok"),
    })()

    with patch.dict("os.environ", {"LEASE_PLANE_BEARER_TOKEN": "test-token"}, clear=False), \
         patch("src.lease_plane.LeasePlaneClient", return_value=fake_client):
        loop = asyncio.get_running_loop()
        result = await _probe()(loop)

    assert result["status"] == "healthy"
    assert result["ok"] is True
    assert "url" in result


@pytest.mark.asyncio
async def test_probe_returns_unavailable_when_bearer_unset():
    """No LEASE_PLANE_BEARER_TOKEN → return "unavailable" without making the
    HTTP call. Mirrors the redis_cache pattern: an opt-in component not
    configured for this deploy shouldn't degrade the overall snapshot.
    The line-705 special-case in get_health_check_data pops "unavailable"
    lease_plane entries from effective_checks so overall stays healthy."""
    import os as _os
    saved = _os.environ.pop("LEASE_PLANE_BEARER_TOKEN", None)
    try:
        loop = asyncio.get_running_loop()
        result = await _probe()(loop)
    finally:
        if saved is not None:
            _os.environ["LEASE_PLANE_BEARER_TOKEN"] = saved

    assert result["status"] == "unavailable"
    assert result["ok"] is False
    assert "not configured" in result["reason"].lower()


@pytest.mark.asyncio
async def test_probe_returns_warning_with_reason_on_health_unavailable():
    """Bearer IS configured but boundary doesn't confirm → snapshot entry
    is `warning`. The server's reason is preserved. Distinct from the
    "no bearer configured" path which returns "unavailable" so the
    overall-status logic can pop it (operator-actionable signal vs
    config-not-set signal)."""
    unhealthy = HealthUnavailable(
        ok=False,
        error="service_unavailable",
        reason="transport failure: ConnectionRefusedError",
    )
    fake_client = type("FakeClient", (), {
        "health_check": lambda self, *, timeout_s=None: unhealthy,
    })()

    with patch.dict("os.environ", {"LEASE_PLANE_BEARER_TOKEN": "test-token"}, clear=False), \
         patch("src.lease_plane.LeasePlaneClient", return_value=fake_client):
        loop = asyncio.get_running_loop()
        result = await _probe()(loop)

    assert result["status"] == "warning"
    assert result["ok"] is False
    assert result["reason"] == "transport failure: ConnectionRefusedError"
    assert "url" in result


@pytest.mark.asyncio
async def test_probe_isolates_import_failure():
    """If the lease_plane module is somehow unimportable (broken install,
    test env, partial deploy), the probe must NOT crash get_health_check_data.
    The deep-health snapshot's whole purpose is operator visibility — we
    shouldn't lose it because of a bad-state probe."""
    import sys
    with patch.dict(sys.modules, {"src.lease_plane": None}):
        loop = asyncio.get_running_loop()
        result = await _probe()(loop)

    assert result["status"] == "error"
    assert "error" in result


@pytest.mark.asyncio
async def test_probe_isolates_runtime_exception_in_client():
    """A runtime bug in the client (e.g., a future refactor accidentally
    raises before the failure-safe wrapper kicks in) must not propagate."""
    fake_client = type("FakeClient", (), {
        "health_check": lambda self, *, timeout_s=None: (_ for _ in ()).throw(
            RuntimeError("client bug")
        ),
    })()

    with patch.dict("os.environ", {"LEASE_PLANE_BEARER_TOKEN": "test-token"}, clear=False), \
         patch("src.lease_plane.LeasePlaneClient", return_value=fake_client):
        loop = asyncio.get_running_loop()
        result = await _probe()(loop)

    assert result["status"] == "error"
    assert "client bug" in result["error"]


@pytest.mark.asyncio
async def test_probe_uses_env_for_base_url_and_token():
    """The probe reads `LEASE_PLANE_BASE_URL` + `LEASE_PLANE_BEARER_TOKEN`
    from env so operators can repoint without code changes — same env vars
    the lease-plane plist sets."""
    seen_configs = []

    def capture_config(config):
        seen_configs.append((config.base_url, config.bearer_token))
        return type("FakeClient", (), {
            "health_check": lambda self, *, timeout_s=None: HealthOk(
                ok=True, status="ok"
            ),
        })()

    env = {
        "LEASE_PLANE_BASE_URL": "http://probe-test:8788",
        "LEASE_PLANE_BEARER_TOKEN": "probe-token-xyz",
    }
    with patch.dict("os.environ", env, clear=False), \
         patch("src.lease_plane.LeasePlaneClient", side_effect=capture_config):
        loop = asyncio.get_running_loop()
        result = await _probe()(loop)

    assert result["status"] == "healthy"
    assert result["url"] == "http://probe-test:8788"
    assert seen_configs == [("http://probe-test:8788", "probe-token-xyz")]


@pytest.mark.asyncio
async def test_probe_falls_back_to_default_url_without_env():
    """No LEASE_PLANE_BASE_URL → defaults to http://127.0.0.1:8788 (the
    plist's default). Pin the literal so a future code change to the
    default goes through review. Bearer must be set so the probe
    actually instantiates the client (the no-bearer path short-circuits
    before client creation, per `test_probe_returns_unavailable_when_bearer_unset`)."""
    seen_urls = []

    def capture(config):
        seen_urls.append(config.base_url)
        return type("FakeClient", (), {
            "health_check": lambda self, *, timeout_s=None: HealthOk(
                ok=True, status="ok"
            ),
        })()

    import os as _os
    saved_url = _os.environ.pop("LEASE_PLANE_BASE_URL", None)
    try:
        with patch.dict("os.environ", {"LEASE_PLANE_BEARER_TOKEN": "test-token"}, clear=False), \
             patch("src.lease_plane.LeasePlaneClient", side_effect=capture):
            loop = asyncio.get_running_loop()
            await _probe()(loop)
    finally:
        if saved_url is not None:
            _os.environ["LEASE_PLANE_BASE_URL"] = saved_url

    assert seen_urls == ["http://127.0.0.1:8788"]
