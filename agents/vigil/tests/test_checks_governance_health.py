"""Tests for the built-in GovernanceHealth check."""

from __future__ import annotations

import asyncio

import pytest


def _reset_registry():
    from agents.vigil.checks import registry
    registry._CHECKS.clear()
    registry._LOADED = False


@pytest.fixture(autouse=True)
def clean_registry():
    _reset_registry()
    yield
    _reset_registry()


def test_governance_health_identity():
    from agents.vigil.checks.governance_health import GovernanceHealth

    check = GovernanceHealth()
    assert check.name == "governance_health"
    assert check.service_key == "governance"


def test_governance_health_ok_when_endpoint_returns_200(monkeypatch):
    """run() returns ok=True and a human-readable summary on success."""
    from agents.vigil.checks import governance_health

    monkeypatch.setattr(
        governance_health,
        "check_http_health",
        lambda url, timeout=5.0: (True, "ok (12ms)"),
    )

    result = asyncio.run(governance_health.GovernanceHealth().run())
    assert result.ok is True
    assert "Governance" in result.summary
    assert "ok (12ms)" in result.summary


def test_governance_health_failure_carries_critical_severity_and_fingerprint(monkeypatch):
    """On failure, the result must flag critical severity + a stable fingerprint_key
    so Vigil's finding-emit path can dedup pages across cycles."""
    from agents.vigil.checks import governance_health

    monkeypatch.setattr(
        governance_health,
        "check_http_health",
        lambda url, timeout=5.0: (False, "connection refused"),
    )

    result = asyncio.run(governance_health.GovernanceHealth().run())
    assert result.ok is False
    assert result.severity == "critical"
    assert result.fingerprint_key == "governance_down"
    assert "UNHEALTHY" in result.summary or "unhealthy" in result.summary.lower()


def test_governance_health_uses_configured_url(monkeypatch):
    """The check should hit the URL from GOVERNANCE_HEALTH_URL so ops can override."""
    from agents.vigil.checks import governance_health

    captured = {}

    def fake(url, timeout=5.0):
        captured["url"] = url
        return True, "ok"

    monkeypatch.setattr(governance_health, "check_http_health", fake)
    monkeypatch.setattr(governance_health, "GOVERNANCE_HEALTH_URL", "http://test.local:9999/health")

    asyncio.run(governance_health.GovernanceHealth().run())
    assert captured["url"] == "http://test.local:9999/health"


def test_load_plugins_registers_governance_health(monkeypatch):
    """Built-in governance_health is always registered via load_plugins()."""
    from agents.vigil.checks import registry

    monkeypatch.delenv("VIGIL_CHECK_PLUGINS", raising=False)
    registry.load_plugins()
    names = [c.name for c in registry.all_checks()]
    assert "governance_health" in names
