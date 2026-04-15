"""Tests for POST /api/findings — external finding ingestion."""

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from src.event_detector import event_detector
from src.http_api import http_record_finding


@pytest.fixture(autouse=True)
def clear_events():
    event_detector.clear_events()
    event_detector._recent_fingerprints.clear()
    event_detector._event_counter = 0
    yield
    event_detector.clear_events()
    event_detector._recent_fingerprints.clear()
    event_detector._event_counter = 0


@pytest.fixture
def client():
    app = Starlette(routes=[Route("/api/findings", http_record_finding, methods=["POST"])])
    return TestClient(app)


def test_accepts_valid_finding(client):
    payload = {
        "type": "sentinel_finding",
        "severity": "high",
        "message": "fleet coherence dipped",
        "agent_id": "sentinel-01",
        "agent_name": "Sentinel",
        "fingerprint": "abcd1234",
    }
    r = client.post("/api/findings", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["event"]["event_id"] == 1
    assert body["event"]["type"] == "sentinel_finding"
    assert body["deduped"] is False


def test_deduped_finding_returns_success_but_marked(client):
    payload = {
        "type": "sentinel_finding", "severity": "high", "message": "m",
        "agent_id": "a", "agent_name": "n", "fingerprint": "dedup-me",
    }
    r1 = client.post("/api/findings", json=payload)
    r2 = client.post("/api/findings", json=payload)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["deduped"] is False
    assert r2.json()["deduped"] is True
    assert r2.json()["event"] is None


def test_rejects_missing_required_fields(client):
    r = client.post("/api/findings", json={"type": "x"})
    assert r.status_code == 400
    assert r.json()["success"] is False


def test_rejects_invalid_severity(client):
    r = client.post("/api/findings", json={
        "type": "x", "severity": "BOGUS", "message": "m",
        "agent_id": "a", "agent_name": "n", "fingerprint": "fp",
    })
    assert r.status_code == 400


def test_rejects_invalid_type_prefix(client):
    r = client.post("/api/findings", json={
        "type": "verdict_change", "severity": "info", "message": "m",
        "agent_id": "a", "agent_name": "n", "fingerprint": "fp",
    })
    assert r.status_code == 400
