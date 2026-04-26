"""Tests for scripts/dev/_ship_watcher_fingerprints.py — the helper ship.sh
uses to derive a `Watcher-Findings:` trailer from staged files.

Locks in the contract: read findings.jsonl, intersect file paths with
staged set passed on stdin, emit unresolved fingerprints comma-separated."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / "scripts" / "dev" / "_ship_watcher_fingerprints.py"


def _run(findings_path: Path, staged: list[str]) -> tuple[str, str, int]:
    proc = subprocess.run(
        ["python3", str(HELPER), str(findings_path)],
        input="\n".join(staged),
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip(), proc.stderr.strip(), proc.returncode


def _write_findings(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_emits_fingerprint_for_unresolved_finding_on_staged_file(tmp_path):
    findings = tmp_path / "findings.jsonl"
    _write_findings(findings, [
        {"file": "/repo/agents/foo.py", "fingerprint": "abc123", "status": "surfaced"},
    ])
    out, err, rc = _run(findings, ["/repo/agents/foo.py"])
    assert rc == 0, err
    assert out == "abc123"


def test_skips_resolved_and_dismissed_findings(tmp_path):
    findings = tmp_path / "findings.jsonl"
    _write_findings(findings, [
        {"file": "/repo/a.py", "fingerprint": "kept", "status": "open"},
        {"file": "/repo/a.py", "fingerprint": "confirmed-fp", "status": "confirmed"},
        {"file": "/repo/a.py", "fingerprint": "dismissed-fp", "status": "dismissed"},
        {"file": "/repo/a.py", "fingerprint": "aged-fp", "status": "aged_out"},
    ])
    out, _, rc = _run(findings, ["/repo/a.py"])
    assert rc == 0
    assert out == "kept"


def test_only_returns_findings_for_staged_files(tmp_path):
    findings = tmp_path / "findings.jsonl"
    _write_findings(findings, [
        {"file": "/repo/staged.py", "fingerprint": "match", "status": "surfaced"},
        {"file": "/repo/elsewhere.py", "fingerprint": "noise", "status": "surfaced"},
    ])
    out, _, rc = _run(findings, ["/repo/staged.py"])
    assert rc == 0
    assert out == "match"


def test_dedupes_same_fingerprint(tmp_path):
    findings = tmp_path / "findings.jsonl"
    _write_findings(findings, [
        {"file": "/repo/a.py", "fingerprint": "dup", "status": "surfaced"},
        {"file": "/repo/a.py", "fingerprint": "dup", "status": "open"},
    ])
    out, _, rc = _run(findings, ["/repo/a.py"])
    assert rc == 0
    assert out == "dup"


def test_multiple_fingerprints_comma_separated(tmp_path):
    findings = tmp_path / "findings.jsonl"
    _write_findings(findings, [
        {"file": "/repo/a.py", "fingerprint": "first", "status": "surfaced"},
        {"file": "/repo/b.py", "fingerprint": "second", "status": "open"},
    ])
    out, _, rc = _run(findings, ["/repo/a.py", "/repo/b.py"])
    assert rc == 0
    assert set(out.split(",")) == {"first", "second"}


def test_empty_when_findings_file_missing(tmp_path):
    out, _, rc = _run(tmp_path / "absent.jsonl", ["/repo/a.py"])
    assert rc == 0
    assert out == ""


def test_empty_when_no_staged_files(tmp_path):
    findings = tmp_path / "findings.jsonl"
    _write_findings(findings, [
        {"file": "/repo/a.py", "fingerprint": "x", "status": "surfaced"},
    ])
    out, _, rc = _run(findings, [])
    assert rc == 0
    assert out == ""


def test_skips_malformed_lines(tmp_path):
    findings = tmp_path / "findings.jsonl"
    findings.write_text(
        "not json\n"
        + json.dumps({"file": "/repo/a.py", "fingerprint": "good", "status": "surfaced"})
        + "\n"
        + "{broken\n"
    )
    out, _, rc = _run(findings, ["/repo/a.py"])
    assert rc == 0
    assert out == "good"
