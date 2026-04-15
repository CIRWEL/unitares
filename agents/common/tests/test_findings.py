"""Tests for the shared post_finding helper used by Sentinel/Vigil/Watcher."""

from __future__ import annotations

import pytest

from agents.common.findings import compute_fingerprint, post_finding


def test_compute_fingerprint_is_stable():
    fp1 = compute_fingerprint(["sentinel", "coordinated_degradation", "BEH", "sentinel-01"])
    fp2 = compute_fingerprint(["sentinel", "coordinated_degradation", "BEH", "sentinel-01"])
    assert fp1 == fp2
    assert len(fp1) == 16


def test_compute_fingerprint_differs_on_input():
    fp1 = compute_fingerprint(["sentinel", "a"])
    fp2 = compute_fingerprint(["sentinel", "b"])
    assert fp1 != fp2


def test_post_finding_success(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout):  # noqa: A002
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})

        class FakeResp:
            status_code = 200

            def json(self):
                return {"success": True, "deduped": False, "event": {"event_id": 1}}

        return FakeResp()

    monkeypatch.setattr("agents.common.findings._httpx_post", fake_post)
    ok = post_finding(
        event_type="sentinel_finding",
        severity="high",
        message="fleet coherence dipped",
        agent_id="sentinel-01",
        agent_name="Sentinel",
        fingerprint="abcd1234",
        extra={"violation_class": "BEH"},
    )
    assert ok is True
    assert len(calls) == 1
    body = calls[0]["json"]
    assert body["type"] == "sentinel_finding"
    assert body["violation_class"] == "BEH"
    assert body["fingerprint"] == "abcd1234"
    assert calls[0]["url"].endswith("/api/findings")


def test_post_finding_swallows_network_errors(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("agents.common.findings._httpx_post", boom)
    # Must NOT raise — posting findings is best-effort, never blocks the agent
    assert post_finding(
        event_type="vigil_finding", severity="critical", message="gov down",
        agent_id="vigil", agent_name="Vigil", fingerprint="fp",
    ) is False


def test_post_finding_respects_env_token(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout):  # noqa: A002
        calls.append(headers)

        class FakeResp:
            status_code = 200

            def json(self):
                return {"success": True}

        return FakeResp()

    monkeypatch.setattr("agents.common.findings._httpx_post", fake_post)
    monkeypatch.setenv("UNITARES_HTTP_API_TOKEN", "secret-token-xyz")
    post_finding(
        event_type="watcher_finding", severity="high", message="m",
        agent_id="watcher", agent_name="Watcher", fingerprint="fp",
    )
    assert calls[0].get("Authorization") == "Bearer secret-token-xyz"
