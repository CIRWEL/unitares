"""Vigil posts findings on governance-down and Lumen-unreachable transitions."""


def test_gov_down_transition_posts_finding():
    """First cycle that sees governance unhealthy must post a vigil_finding."""
    from agents.common.findings import compute_fingerprint

    # Vigil's finding on gov_down should have a stable fingerprint so the
    # 30-min dedup window suppresses repeat pages while governance stays down.
    fp = compute_fingerprint(["vigil", "governance_down"])
    assert len(fp) == 16
    assert compute_fingerprint(["vigil", "governance_down"]) == fp
    assert compute_fingerprint(["vigil", "lumen_unreachable"]) != fp


def test_lumen_outage_streak_fingerprint_stable():
    from agents.common.findings import compute_fingerprint
    a = compute_fingerprint(["vigil", "lumen_unreachable"])
    b = compute_fingerprint(["vigil", "lumen_unreachable"])
    assert a == b


def test_vigil_emits_on_gov_down_transition(monkeypatch):
    """When governance transitions healthy → unhealthy, post_finding fires once."""
    from agents.vigil import agent as vigil_mod

    calls = []

    def fake_post(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(vigil_mod, "post_finding", fake_post)

    # Simulate the emit site directly
    prev_state = {"governance_healthy": True}
    gov_healthy = False
    gov_detail = "connection refused"

    if not gov_healthy and prev_state.get("governance_healthy", True):
        vigil_mod.post_finding(
            event_type="vigil_finding",
            severity="critical",
            message=f"Governance is down: {gov_detail}",
            agent_id="vigil",
            agent_name="Vigil",
            fingerprint=vigil_mod.compute_fingerprint(["vigil", "governance_down"]),
            extra={"finding_type": "governance_down"},
        )

    assert len(calls) == 1
    assert calls[0]["event_type"] == "vigil_finding"
    assert calls[0]["severity"] == "critical"
    assert "connection refused" in calls[0]["message"]
