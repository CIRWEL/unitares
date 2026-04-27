"""Regression test: _post_resolution_event must use an event_type the
governance /api/findings endpoint actually accepts. The HTTP layer rejects
any type not ending in '_finding' (src/http_api.py:1090). The original
implementation posted 'watcher_resolution' and got silently 400'd."""

from unittest.mock import patch

from agents.watcher.agent import _post_resolution_event


def test_resolution_event_type_passes_findings_suffix_gate():
    """The event_type Watcher posts must end in '_finding' so the
    /api/findings suffix gate accepts it. Without this, every confirm/dismiss
    is silently dropped."""
    finding = {
        "fingerprint": "abcd1234efgh5678",
        "pattern": "P-DUMMY",
        "file": "/tmp/x.py",
        "line": 1,
        "hint": "h",
        "severity": "medium",
        "violation_class": "BEH",
    }
    captured = {}

    def fake_post_finding(*, event_type, **kwargs):
        captured["event_type"] = event_type
        captured["kwargs"] = kwargs
        return True

    # Stub get_watcher_identity so the function actually proceeds to post_finding
    fake_identity = {
        "agent_uuid": "11111111-2222-3333-4444-555555555555",
        "client_session_id": "csid",
        "continuity_token": "tok",
    }
    with patch("agents.watcher.agent.get_watcher_identity", return_value=fake_identity):
        with patch("agents.watcher.agent.post_finding", side_effect=fake_post_finding):
            _post_resolution_event(finding, "confirmed", "agent-uuid", reason="fp")

    assert "event_type" in captured, "post_finding was not called"
    assert captured["event_type"].endswith("_finding"), (
        f"event_type {captured['event_type']!r} would be 400'd by the "
        "/api/findings suffix gate"
    )
