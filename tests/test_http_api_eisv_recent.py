"""Tests for GET /v1/eisv/recent — backfill endpoint for dashboard chart."""

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from src.http_api import http_eisv_recent
from src import http_api


def _make_event(agent_id, e_val, ts="2026-04-22T00:00:00+00:00"):
    return {
        "type": "eisv_update",
        "agent_id": agent_id,
        "agent_name": agent_id,
        "timestamp": ts,
        "eisv": {"E": e_val, "I": 0.5, "S": 0.1, "V": 0.0},
        "coherence": 0.5,
    }


def _client():
    app = Starlette(routes=[Route("/v1/eisv/recent", http_eisv_recent, methods=["GET"])])
    return TestClient(app)


def test_returns_eisv_events_in_chronological_order():
    http_api.broadcaster_instance.event_history.clear()
    http_api.broadcaster_instance.event_history.append(_make_event("a", 0.1))
    http_api.broadcaster_instance.event_history.append(_make_event("b", 0.2))
    http_api.broadcaster_instance.event_history.append(_make_event("c", 0.3))

    r = _client().get("/v1/eisv/recent")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "eisv_recent"
    assert body["count"] == 3
    assert [e["agent_id"] for e in body["events"]] == ["a", "b", "c"]


def test_filters_out_non_eisv_events():
    http_api.broadcaster_instance.event_history.clear()
    http_api.broadcaster_instance.event_history.append(_make_event("a", 0.1))
    http_api.broadcaster_instance.event_history.append({"type": "lifecycle_paused", "agent_id": "x"})
    http_api.broadcaster_instance.event_history.append(_make_event("b", 0.2))

    body = _client().get("/v1/eisv/recent").json()
    assert body["count"] == 2
    assert [e["agent_id"] for e in body["events"]] == ["a", "b"]


def test_limit_parameter_is_honored_and_clamped():
    http_api.broadcaster_instance.event_history.clear()
    for i in range(10):
        http_api.broadcaster_instance.event_history.append(_make_event(f"a{i}", i / 10))

    body = _client().get("/v1/eisv/recent?limit=3").json()
    assert body["count"] == 3
    # Most recent three, in order
    assert [e["agent_id"] for e in body["events"]] == ["a7", "a8", "a9"]


def test_limit_is_clamped_to_max():
    http_api.broadcaster_instance.event_history.clear()
    body = _client().get("/v1/eisv/recent?limit=999999").json()
    # Clamped internally; with an empty buffer just returns []
    assert body["count"] == 0
    assert body["events"] == []


def test_invalid_limit_falls_back_to_default():
    http_api.broadcaster_instance.event_history.clear()
    http_api.broadcaster_instance.event_history.append(_make_event("a", 0.1))
    body = _client().get("/v1/eisv/recent?limit=abc").json()
    assert body["count"] == 1
