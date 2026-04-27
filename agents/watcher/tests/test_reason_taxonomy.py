"""--reason enum: only certain reasons mean 'false positive'. Others
(wont_fix, out_of_scope, dup, unclear, stale) document operator intent
without claiming the finding was wrong, and are excluded from the
precision math."""

import json

import pytest

from agents.watcher.findings import (
    DISMISSAL_REASONS,
    update_finding_status,
)


@pytest.fixture
def findings_file_with_one_open(tmp_path, monkeypatch):
    """Plant a single open finding and point the watcher state-dir at
    tmp_path so the lifecycle helpers operate against it."""
    state_dir = tmp_path / "watcher"
    state_dir.mkdir()
    findings_file = state_dir / "findings.jsonl"
    row = {
        "pattern": "P1",
        "file": "/repo/src/x.py",
        "line": 1,
        "hint": "h",
        "severity": "medium",
        "status": "open",
        "detected_at": "2026-04-27T00:00:00Z",
        "fingerprint": "abcd1234efgh5678",
        "violation_class": "BEH",
    }
    findings_file.write_text(json.dumps(row) + "\n")

    monkeypatch.setattr("agents.watcher.findings.STATE_DIR", state_dir)
    monkeypatch.setattr("agents.watcher.findings.FINDINGS_FILE", findings_file)
    monkeypatch.setattr("agents.watcher.findings.DEDUP_FILE", state_dir / "dedup.json")
    return findings_file


def test_valid_reasons_constant_shape():
    assert "fp" in DISMISSAL_REASONS
    assert "wont_fix" in DISMISSAL_REASONS
    assert "out_of_scope" in DISMISSAL_REASONS
    assert "dup" in DISMISSAL_REASONS
    assert "unclear" in DISMISSAL_REASONS
    assert "stale" in DISMISSAL_REASONS


def test_dismiss_with_valid_reason_persists_it(findings_file_with_one_open, monkeypatch):
    monkeypatch.setattr(
        "agents.watcher.agent._post_resolution_event", lambda *a, **kw: None
    )
    rc = update_finding_status("abcd1234", "dismissed", reason="fp")
    assert rc == 0
    persisted = json.loads(findings_file_with_one_open.read_text().strip())
    assert persisted["status"] == "dismissed"
    assert persisted["resolution_reason"] == "fp"


def test_dismiss_with_nonenum_reason_persists_with_warning(
    findings_file_with_one_open, monkeypatch
):
    """Soft taxonomy: a non-enum reason is accepted (operators often pass
    free-text rationale, and pre-2026-04-27 rows already do). The
    precision math in calibration.py excludes non-enum reasons from the
    TN count regardless, so accepting them here is safe."""
    monkeypatch.setattr(
        "agents.watcher.agent._post_resolution_event", lambda *a, **kw: None
    )
    rc = update_finding_status("abcd1234", "dismissed", reason="just because")
    assert rc == 0
    persisted = json.loads(findings_file_with_one_open.read_text().strip())
    assert persisted["status"] == "dismissed"
    assert persisted["resolution_reason"] == "just because"


def test_dismiss_without_reason_still_works(findings_file_with_one_open, monkeypatch):
    """Backward compat: existing scripts don't pass a reason. Status
    transitions, but resolution_reason is unset (treated as 'unknown'
    by precision math, i.e. excluded from TN counts)."""
    monkeypatch.setattr(
        "agents.watcher.agent._post_resolution_event", lambda *a, **kw: None
    )
    rc = update_finding_status("abcd1234", "dismissed", reason=None)
    assert rc == 0
    persisted = json.loads(findings_file_with_one_open.read_text().strip())
    assert persisted["status"] == "dismissed"
    assert "resolution_reason" not in persisted
