"""Regression tests for the Watcher agent's dedup and fingerprinting.

Background: on 2026-04-11, immediately after shipping the Watcher agent
(commit 98a7ae2), Ogler flagged two latent bugs in the watcher itself:

1. ``FINDINGS_TTL_DAYS = 14`` was defined at watcher_agent.py:78 but never
   enforced by ``persist_findings`` at :496 — the dedup dict would grow
   unboundedly over months. This is the exact P002 pattern the watcher's
   own library warns about.

2. ``_compute_fingerprint`` at :127 hashed only ``pattern|file|line`` with
   no content component. If a bug at line 47 was fixed and a DIFFERENT bug
   arrived at the same line 47 later, the watcher would silently dedup it
   as a rerun and never surface it — a false negative.

Both fixes shipped in the same commit as these tests, per the project
standing rule "every behavioral change ships with tests covering the new
behavior" (see ~/.claude memory feedback_tests-with-fixes.md).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loading — mirrors tests/test_sentinel_cycle_timeout.py
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def watcher_module():
    """Load ``agents/watcher/agent.py`` as a module without executing
    its ``__main__`` block."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    module_path = project_root / "agents" / "watcher" / "agent.py"
    spec = importlib.util.spec_from_file_location("watcher_agent", module_path)
    assert spec and spec.loader, "could not load watcher_agent module"
    module = importlib.util.module_from_spec(spec)
    sys.modules["watcher_agent"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _isolate_watcher_state(tmp_path, monkeypatch, watcher_module):
    """Redirect all Watcher state paths into a tmp dir so tests never touch
    the production findings.jsonl / dedup.json / log file."""
    tmp_state = tmp_path / "watcher-state"
    tmp_state.mkdir()
    tmp_log = tmp_path / "watcher.log"
    monkeypatch.setattr(watcher_module, "STATE_DIR", tmp_state)
    monkeypatch.setattr(watcher_module, "FINDINGS_FILE", tmp_state / "findings.jsonl")
    monkeypatch.setattr(watcher_module, "DEDUP_FILE", tmp_state / "dedup.json")
    monkeypatch.setattr(watcher_module, "LOG_FILE", tmp_log)
    yield


# ---------------------------------------------------------------------------
# hash_line_content
# ---------------------------------------------------------------------------


def test_hash_line_content_is_stable_across_leading_whitespace(watcher_module):
    """Indent-only differences must not change the content hash, so
    reformatting (e.g. a linter adjusting indentation) doesn't re-fire
    every finding in the touched region."""
    h_indented = watcher_module.hash_line_content("    asyncio.create_task(x.run())")
    h_tight = watcher_module.hash_line_content("asyncio.create_task(x.run())")
    h_trailing = watcher_module.hash_line_content("asyncio.create_task(x.run())   ")
    assert h_indented == h_tight == h_trailing


def test_hash_line_content_differs_for_different_code(watcher_module):
    """Different code at the same line must hash differently."""
    h_a = watcher_module.hash_line_content("asyncio.create_task(x.run())")
    h_b = watcher_module.hash_line_content("task = asyncio.create_task(x.run())")
    assert h_a != h_b


def test_hash_line_content_handles_empty(watcher_module):
    """Empty / missing source lines must produce a stable, non-crashing
    hash (callers rely on it as a fingerprint component)."""
    assert watcher_module.hash_line_content("") == watcher_module.hash_line_content(
        "   "
    )
    assert watcher_module.hash_line_content(None) == watcher_module.hash_line_content(
        ""
    )


# ---------------------------------------------------------------------------
# Finding.compute_fingerprint
# ---------------------------------------------------------------------------


def _finding(watcher_module, **overrides):
    """Build a Finding with sensible defaults for fingerprint tests."""
    defaults = dict(
        pattern="P001",
        file="/tmp/foo.py",
        line=47,
        hint="fire-and-forget",
        severity="high",
        detected_at="2026-04-11T00:00:00Z",
        model_used="gemma4:latest",
    )
    defaults.update(overrides)
    return watcher_module.Finding(**defaults)


def test_fingerprint_differs_when_content_hash_changes(watcher_module):
    """The critical regression: same pattern at the same line, but the code
    on that line changed — must produce a different fingerprint so the new
    bug is not silently dedup'd as a rerun of the old one."""
    f_old = _finding(watcher_module, line_content_hash="aaaaaaaaaaaa")
    f_new = _finding(watcher_module, line_content_hash="bbbbbbbbbbbb")
    assert f_old.fingerprint != f_new.fingerprint


def test_fingerprint_stable_for_identical_content(watcher_module):
    """Same pattern, same line, same content → same fingerprint. The
    dedup layer must recognize an identical re-detection and skip it."""
    f_a = _finding(watcher_module, line_content_hash="cafebabe1234")
    f_b = _finding(watcher_module, line_content_hash="cafebabe1234")
    assert f_a.fingerprint == f_b.fingerprint


def test_fingerprint_ignores_non_identifying_fields(watcher_module):
    """detected_at, hint, severity, model_used should not affect
    fingerprint identity — only pattern/file/line/content_hash do."""
    f_a = _finding(
        watcher_module,
        line_content_hash="deadbeefcafe",
        detected_at="2026-04-11T00:00:00Z",
        hint="first hint",
        model_used="gemma4:latest",
    )
    f_b = _finding(
        watcher_module,
        line_content_hash="deadbeefcafe",
        detected_at="2026-04-11T99:99:99Z",
        hint="a different hint entirely",
        model_used="gemma4:26b",
    )
    assert f_a.fingerprint == f_b.fingerprint


# ---------------------------------------------------------------------------
# sweep_stale_dedup — the TTL enforcer
# ---------------------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_sweep_drops_entries_older_than_ttl(watcher_module):
    now = datetime(2026, 4, 11, tzinfo=timezone.utc)
    ttl_days = watcher_module.FINDINGS_TTL_DAYS  # 14
    dedup = {
        "fresh1": _iso(now - timedelta(days=1)),
        "fresh2": _iso(now - timedelta(days=ttl_days - 1)),
        "stale1": _iso(now - timedelta(days=ttl_days + 1)),
        "stale2": _iso(now - timedelta(days=90)),
    }
    pruned = watcher_module.sweep_stale_dedup(dedup, ttl_days=ttl_days, now=now)
    assert "fresh1" in pruned
    assert "fresh2" in pruned
    assert "stale1" not in pruned
    assert "stale2" not in pruned
    assert len(pruned) == 2


def test_sweep_empty_dedup_is_a_noop(watcher_module):
    assert watcher_module.sweep_stale_dedup({}) == {}


def test_sweep_preserves_unparseable_timestamps(watcher_module):
    """Fail-open: a corrupted timestamp string should not cause the sweep
    to silently empty the dedup. We'd rather leak a few entries than lose
    real findings."""
    dedup = {
        "fresh": _iso(datetime.now(timezone.utc)),
        "garbage1": "not a timestamp",
        "garbage2": "",
    }
    pruned = watcher_module.sweep_stale_dedup(dedup)
    assert "fresh" in pruned
    assert "garbage1" in pruned
    assert "garbage2" in pruned


def test_sweep_boundary_exactly_at_ttl_is_kept(watcher_module):
    """An entry exactly at the TTL boundary is kept, not dropped. We use
    ``>= cutoff`` in the implementation, so the boundary is inclusive."""
    now = datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc)
    ttl_days = 14
    boundary = now - timedelta(days=ttl_days)
    dedup = {"boundary": _iso(boundary)}
    pruned = watcher_module.sweep_stale_dedup(dedup, ttl_days=ttl_days, now=now)
    assert "boundary" in pruned


# ---------------------------------------------------------------------------
# persist_findings — end-to-end dedup with TTL enforcement
# ---------------------------------------------------------------------------


def test_persist_findings_invokes_ttl_sweep(watcher_module):
    """persist_findings must sweep the dedup dict on every call so stale
    entries are pruned continuously — not just when the user remembers to
    run a cleanup. The unbounded-growth bug was that this function never
    invoked any sweep at all."""
    now = datetime.now(timezone.utc)
    stale_ts = _iso(now - timedelta(days=watcher_module.FINDINGS_TTL_DAYS + 5))

    # Seed dedup with a stale entry
    watcher_module.save_dedup({"ancient_fingerprint": stale_ts})
    assert "ancient_fingerprint" in watcher_module.load_dedup()

    new_finding = watcher_module.Finding(
        pattern="P001",
        file="/tmp/foo.py",
        line=10,
        hint="fire-and-forget",
        severity="high",
        detected_at=_iso(now),
        model_used="gemma4:latest",
        line_content_hash="1234567890ab",
    )

    fresh = watcher_module.persist_findings([new_finding])
    assert len(fresh) == 1

    dedup_after = watcher_module.load_dedup()
    assert "ancient_fingerprint" not in dedup_after, "TTL sweep did not run"
    assert new_finding.fingerprint in dedup_after, "new finding was not recorded"


def test_persist_findings_dedup_hides_repeat_but_not_content_change(watcher_module):
    """The core regression: two findings at the same (pattern, file, line)
    but DIFFERENT line_content_hash must both get persisted. A third
    finding identical to the first must be dedup'd."""
    base = dict(
        pattern="P001",
        file="/tmp/foo.py",
        line=47,
        hint="fire-and-forget",
        severity="high",
        detected_at="2026-04-11T00:00:00Z",
        model_used="gemma4:latest",
    )
    f_first = watcher_module.Finding(**base, line_content_hash="aaaaaaaaaaaa")
    f_content_change = watcher_module.Finding(
        **base, line_content_hash="bbbbbbbbbbbb"
    )
    f_duplicate = watcher_module.Finding(**base, line_content_hash="aaaaaaaaaaaa")

    # First flight: both distinct findings land; the duplicate is dropped
    fresh = watcher_module.persist_findings([f_first, f_content_change, f_duplicate])
    assert len(fresh) == 2
    fingerprints = {f.fingerprint for f in fresh}
    assert f_first.fingerprint in fingerprints
    assert f_content_change.fingerprint in fingerprints
    assert f_first.fingerprint != f_content_change.fingerprint

    # Second flight: re-submitting all three produces nothing new
    second = watcher_module.persist_findings(
        [f_first, f_content_change, f_duplicate]
    )
    assert second == []


def test_persist_empty_batch_still_lets_sweep_reach_disk(watcher_module):
    """Even when no new findings land, the TTL sweep must write the pruned
    dedup back to disk — otherwise stale entries would resurrect on the
    next scan that DID have findings."""
    now = datetime.now(timezone.utc)
    stale_ts = _iso(now - timedelta(days=watcher_module.FINDINGS_TTL_DAYS + 5))
    watcher_module.save_dedup({"stale": stale_ts})

    fresh = watcher_module.persist_findings([])
    assert fresh == []

    dedup_after = watcher_module.load_dedup()
    assert "stale" not in dedup_after, "sweep result was not persisted to disk"


# ---------------------------------------------------------------------------
# scan_file(persist=...) — self-test isolation
#
# Background: repeatedly running ``watcher_agent.py --self-test`` poured
# synthetic P001 "selftest.py" findings into the real findings.jsonl, which
# the SessionStart hook then surfaced at the top of every new Claude Code
# session. The fix was a ``persist=False`` path through scan_file(), used
# exclusively by the self-test harness so synthetic bug samples never pollute
# the live findings feed.
# ---------------------------------------------------------------------------


def _install_scan_stubs(watcher_module, monkeypatch, findings_to_return):
    """Bypass parse_findings entirely and short-circuit scan_file's model
    pipeline so the test deterministically reaches the persist gate with the
    exact findings list it wants to exercise.

    We patch the internals scan_file calls BEFORE the persist branch:
      - should_skip → never skip
      - read_file_region → canned snippet
      - load_patterns / build_prompt → stubbed
      - call_model → stub response (parse_findings output is discarded)
      - parse_findings → returns our exact fixture list, skipping verification
      - _verify_finding_against_source → always accept

    This eliminates the previous conditional-assertion weakness where a real
    parse failure would silently make the test pass without asserting
    anything.
    """
    monkeypatch.setattr(watcher_module, "should_skip", lambda _p: (False, ""))
    monkeypatch.setattr(
        watcher_module,
        "read_file_region",
        lambda _p, _r=None: ("6:    asyncio.create_task(x.run())", 1, 10),
    )
    monkeypatch.setattr(watcher_module, "load_patterns", lambda: "P001")
    monkeypatch.setattr(watcher_module, "build_prompt", lambda *a, **k: "stub")
    monkeypatch.setattr(
        watcher_module,
        "call_model",
        lambda _p: {"text": "stub", "tokens_used": 0, "model_used": "stub"},
    )
    monkeypatch.setattr(
        watcher_module,
        "parse_findings",
        lambda _text, _fp, _model, _rs: [(f, "stub-evidence") for f in findings_to_return],
    )
    monkeypatch.setattr(
        watcher_module,
        "_verify_finding_against_source",
        lambda _f, _ev, _lines: True,
    )


def _make_fake_finding(watcher_module, pattern="P001", line=6):
    return watcher_module.Finding(
        pattern=pattern,
        file="/tmp/fake.py",
        line=line,
        hint="synthetic fixture",
        severity="high",
        detected_at="2026-04-10T00:00:00Z",
        model_used="stub",
    )


def test_scan_file_persist_false_leaves_findings_file_alone(
    watcher_module, tmp_path, monkeypatch
):
    """persist=False must neither create findings.jsonl nor call persist_findings."""
    fake = _make_fake_finding(watcher_module)
    _install_scan_stubs(watcher_module, monkeypatch, [fake])

    # Spy on persist_findings so we can assert it was NOT invoked.
    persist_calls: list = []
    orig_persist = watcher_module.persist_findings

    def _spy(batch):
        persist_calls.append(list(batch))
        return orig_persist(batch)

    monkeypatch.setattr(watcher_module, "persist_findings", _spy)

    assert not watcher_module.FINDINGS_FILE.exists()

    findings = watcher_module.scan_file("/tmp/does-not-exist.py", persist=False)

    # Hard assertions — no conditional guards.
    assert findings, "stubbed scan_file should have returned the fixture finding"
    assert findings[0].pattern == "P001"
    assert persist_calls == [], "persist=False must not call persist_findings"
    assert not watcher_module.FINDINGS_FILE.exists(), (
        "persist=False must NOT create findings.jsonl"
    )


def test_scan_file_persist_true_still_writes_findings(
    watcher_module, tmp_path, monkeypatch
):
    """persist=True (default) must call persist_findings and append to disk."""
    fake = _make_fake_finding(watcher_module)
    _install_scan_stubs(watcher_module, monkeypatch, [fake])

    assert not watcher_module.FINDINGS_FILE.exists()

    findings = watcher_module.scan_file("/tmp/fake.py", persist=True)

    # Hard assertions — no `if findings:` escape hatch.
    assert findings, "stubbed scan_file should have returned the fixture finding"
    assert watcher_module.FINDINGS_FILE.exists(), (
        "persist=True must create findings.jsonl when findings exist"
    )
    lines = watcher_module.FINDINGS_FILE.read_text().splitlines()
    assert lines, "findings.jsonl should contain at least one entry"
    decoded = [json.loads(l) for l in lines]
    assert all(e["pattern"] == "P001" for e in decoded)
    assert all(e["file"] == "/tmp/fake.py" for e in decoded)


def test_scan_file_persist_default_is_true(watcher_module, tmp_path, monkeypatch):
    """Regression guard: the default must remain persist=True so existing
    callers (the live watcher loop) don't silently lose their feed if someone
    later flips the default."""
    fake = _make_fake_finding(watcher_module)
    _install_scan_stubs(watcher_module, monkeypatch, [fake])

    # Call without the kwarg at all.
    findings = watcher_module.scan_file("/tmp/fake.py")
    assert findings
    assert watcher_module.FINDINGS_FILE.exists()


# ---------------------------------------------------------------------------
# Severity routing — critical escalation
# ---------------------------------------------------------------------------


def test_escalate_high_does_not_call_external_targets(watcher_module, monkeypatch):
    finding = _finding(watcher_module, severity="high")
    kg_calls = []

    monkeypatch.setattr(
        watcher_module, "_escalate_to_kg", lambda f: kg_calls.append(f)
    )

    watcher_module.escalate(finding)

    assert kg_calls == []


def test_escalate_critical_calls_kg(watcher_module, monkeypatch):
    finding = _finding(watcher_module, severity="critical")
    calls = []

    monkeypatch.setattr(
        watcher_module, "_escalate_to_kg", lambda f: calls.append(f)
    )

    watcher_module.escalate(finding)

    assert calls == [finding]


def test_escalate_to_kg_writes_critical_discovery(watcher_module, monkeypatch):
    finding = _finding(watcher_module, severity="critical")
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr(watcher_module.urllib.request, "urlopen", fake_urlopen)

    watcher_module._escalate_to_kg(finding)

    assert captured["url"] == watcher_module.GOV_REST_URL
    assert captured["timeout"] == 5
    assert captured["payload"]["name"] == "knowledge"
    args = captured["payload"]["arguments"]
    assert args["action"] == "store"
    assert args["discovery_type"] == "bug_found"
    assert args["severity"] == "critical"
    assert "watcher" in args["tags"]
    assert finding.fingerprint in args["details"]


# ---------------------------------------------------------------------------
# Lifecycle commands — Stage 1
#
# These cover the three operations that make findings.jsonl more than an
# append-only log: marking a finding as confirmed/dismissed, sweeping
# findings whose target file vanished, and compacting resolved entries that
# have aged out. Without these, Watcher has no differential signal to report
# to governance and findings.jsonl grows unboundedly (Ogler's P002
# round two).
# ---------------------------------------------------------------------------


def _seed_findings(watcher_module, entries: list[dict]) -> None:
    """Write a raw findings.jsonl directly for tests that want explicit
    control over what's in the file (status, timestamp, file path)."""
    watcher_module.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with watcher_module.FINDINGS_FILE.open("w") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def _make_raw_entry(
    fingerprint: str,
    *,
    pattern: str = "P001",
    file: str = "/tmp/seeded.py",
    line: int = 10,
    status: str = "open",
    detected_at: str = "2026-04-11T00:00:00Z",
    severity: str = "high",
    hint: str = "fire-and-forget task",
) -> dict:
    return {
        "pattern": pattern,
        "file": file,
        "line": line,
        "hint": hint,
        "severity": severity,
        "detected_at": detected_at,
        "model_used": "gemma4:latest",
        "line_content_hash": "0123456789ab",
        "fingerprint": fingerprint,
        "status": status,
    }


# --- match_fingerprint ------------------------------------------------------


def test_match_fingerprint_rejects_empty_and_too_short(watcher_module):
    findings = [_make_raw_entry("aaaaaaaaaaaaaaaa")]
    for bad in ("", "a", "ab", "abc"):
        matches, err = watcher_module.match_fingerprint(bad, findings)
        assert matches == []
        assert err is not None


def test_match_fingerprint_exact_match(watcher_module):
    findings = [
        _make_raw_entry("aaaaaaaaaaaaaaaa"),
        _make_raw_entry("bbbbbbbbbbbbbbbb"),
    ]
    matches, err = watcher_module.match_fingerprint("aaaaaaaaaaaaaaaa", findings)
    assert err is None
    assert len(matches) == 1
    assert matches[0]["fingerprint"] == "aaaaaaaaaaaaaaaa"


def test_match_fingerprint_unique_prefix(watcher_module):
    findings = [
        _make_raw_entry("aaaaaaaaaaaaaaaa"),
        _make_raw_entry("bbbbbbbbbbbbbbbb"),
    ]
    matches, err = watcher_module.match_fingerprint("aaaa", findings)
    assert err is None
    assert len(matches) == 1
    assert matches[0]["fingerprint"] == "aaaaaaaaaaaaaaaa"


def test_match_fingerprint_ambiguous_prefix(watcher_module):
    findings = [
        _make_raw_entry("aaaa11111111"),
        _make_raw_entry("aaaa22222222"),
    ]
    matches, err = watcher_module.match_fingerprint("aaaa", findings)
    assert err is None
    assert len(matches) == 2


def test_match_fingerprint_no_match(watcher_module):
    findings = [_make_raw_entry("aaaaaaaaaaaaaaaa")]
    matches, err = watcher_module.match_fingerprint("zzzz", findings)
    assert err is None
    assert matches == []


# --- update_finding_status --------------------------------------------------


def test_update_finding_status_marks_by_exact_fingerprint(watcher_module):
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry("aaaaaaaaaaaaaaaa", line=10),
            _make_raw_entry("bbbbbbbbbbbbbbbb", line=20),
        ],
    )
    rc = watcher_module.update_finding_status("aaaaaaaaaaaaaaaa", "confirmed")
    assert rc == 0

    after = watcher_module._iter_findings_raw()
    by_fp = {f["fingerprint"]: f for f in after}
    assert by_fp["aaaaaaaaaaaaaaaa"]["status"] == "confirmed"
    # Untouched finding must keep its status
    assert by_fp["bbbbbbbbbbbbbbbb"]["status"] == "open"


def test_update_finding_status_accepts_unique_prefix(watcher_module):
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry("deadbeef11112222"),
            _make_raw_entry("cafebabe33334444"),
        ],
    )
    rc = watcher_module.update_finding_status("deadbeef", "dismissed")
    assert rc == 0

    after = watcher_module._iter_findings_raw()
    by_fp = {f["fingerprint"]: f for f in after}
    assert by_fp["deadbeef11112222"]["status"] == "dismissed"
    assert by_fp["cafebabe33334444"]["status"] == "open"


def test_update_finding_status_rejects_ambiguous_prefix(watcher_module, capsys):
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry("aaaa11111111"),
            _make_raw_entry("aaaa22222222"),
        ],
    )
    rc = watcher_module.update_finding_status("aaaa", "confirmed")
    assert rc == 1

    # Neither finding mutated
    after = watcher_module._iter_findings_raw()
    assert all(f["status"] == "open" for f in after)
    captured = capsys.readouterr()
    assert "ambiguous" in captured.out


def test_update_finding_status_rejects_unknown_fingerprint(watcher_module, capsys):
    _seed_findings(watcher_module, [_make_raw_entry("aaaaaaaaaaaaaaaa")])
    rc = watcher_module.update_finding_status("zzzzzzzz", "dismissed")
    assert rc == 1
    captured = capsys.readouterr()
    assert "no finding matches" in captured.out


def test_update_finding_status_rejects_too_short_prefix(watcher_module, capsys):
    _seed_findings(watcher_module, [_make_raw_entry("aaaaaaaaaaaaaaaa")])
    rc = watcher_module.update_finding_status("a", "dismissed")
    assert rc == 1
    captured = capsys.readouterr()
    assert "too short" in captured.out
    # Finding untouched
    after = watcher_module._iter_findings_raw()
    assert after[0]["status"] == "open"


def test_update_finding_status_rejects_invalid_status(watcher_module, capsys):
    _seed_findings(watcher_module, [_make_raw_entry("aaaaaaaaaaaaaaaa")])
    rc = watcher_module.update_finding_status("aaaaaaaaaaaaaaaa", "bogus")
    assert rc == 2
    captured = capsys.readouterr()
    assert "invalid status" in captured.out


def test_update_finding_status_handles_missing_file(watcher_module, capsys):
    # No findings.jsonl at all
    assert not watcher_module.FINDINGS_FILE.exists()
    rc = watcher_module.update_finding_status("aaaaaaaaaaaaaaaa", "confirmed")
    assert rc == 1
    captured = capsys.readouterr()
    assert "empty" in captured.out or "absent" in captured.out


# --- sweep_stale_findings ---------------------------------------------------


def test_sweep_stale_drops_findings_for_missing_files(
    watcher_module, tmp_path, capsys
):
    real = tmp_path / "real.py"
    real.write_text("print('hi')\n")
    missing = tmp_path / "missing.py"  # never created

    _seed_findings(
        watcher_module,
        [
            _make_raw_entry("aaaaaaaa11111111", file=str(real)),
            _make_raw_entry("bbbbbbbb22222222", file=str(missing)),
        ],
    )
    rc = watcher_module.sweep_stale_findings()
    assert rc == 0

    after = watcher_module._iter_findings_raw()
    assert len(after) == 1
    assert after[0]["fingerprint"] == "aaaaaaaa11111111"
    captured = capsys.readouterr()
    assert "dropped 1" in captured.out


def test_sweep_stale_keeps_all_when_all_files_exist(
    watcher_module, tmp_path, capsys
):
    real_a = tmp_path / "a.py"
    real_b = tmp_path / "b.py"
    real_a.write_text("")
    real_b.write_text("")
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry("aaaa11111111aaaa", file=str(real_a)),
            _make_raw_entry("bbbb22222222bbbb", file=str(real_b)),
        ],
    )
    rc = watcher_module.sweep_stale_findings()
    assert rc == 0

    after = watcher_module._iter_findings_raw()
    assert len(after) == 2
    captured = capsys.readouterr()
    assert "nothing to sweep" in captured.out


def test_sweep_stale_handles_empty_findings(watcher_module, capsys):
    rc = watcher_module.sweep_stale_findings()
    assert rc == 0
    captured = capsys.readouterr()
    assert "no findings to sweep" in captured.out


# --- compact_findings -------------------------------------------------------


def test_compact_drops_old_resolved_entries(watcher_module):
    now = datetime(2026, 4, 11, tzinfo=timezone.utc)
    old = _iso(now - timedelta(days=30))
    recent = _iso(now - timedelta(days=1))
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry(
                "old_confirmed__", status="confirmed", detected_at=old
            ),
            _make_raw_entry(
                "old_dismissed__", status="dismissed", detected_at=old
            ),
            _make_raw_entry(
                "old_aged_out___", status="aged_out", detected_at=old
            ),
            _make_raw_entry(
                "recent_confirm_", status="confirmed", detected_at=recent
            ),
        ],
    )
    rc = watcher_module.compact_findings(max_age_days=7, now=now)
    assert rc == 0

    after = watcher_module._iter_findings_raw()
    fps = {f["fingerprint"] for f in after}
    assert "recent_confirm_" in fps
    assert "old_confirmed__" not in fps
    assert "old_dismissed__" not in fps
    assert "old_aged_out___" not in fps


def test_compact_keeps_open_and_surfaced_regardless_of_age(watcher_module):
    now = datetime(2026, 4, 11, tzinfo=timezone.utc)
    ancient = _iso(now - timedelta(days=365))
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry("open_ancient___", status="open", detected_at=ancient),
            _make_raw_entry(
                "surface_ancient", status="surfaced", detected_at=ancient
            ),
        ],
    )
    rc = watcher_module.compact_findings(max_age_days=7, now=now)
    assert rc == 0

    after = watcher_module._iter_findings_raw()
    assert len(after) == 2
    fps = {f["fingerprint"] for f in after}
    assert "open_ancient___" in fps
    assert "surface_ancient" in fps


def test_compact_preserves_entries_with_unparseable_timestamp(watcher_module):
    """Fail-open: garbage timestamps are kept rather than silently dropped."""
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry(
                "bad_timestamp__",
                status="confirmed",
                detected_at="not a date",
            ),
        ],
    )
    rc = watcher_module.compact_findings(max_age_days=1)
    assert rc == 0
    after = watcher_module._iter_findings_raw()
    assert len(after) == 1


def test_compact_noop_on_empty(watcher_module, capsys):
    rc = watcher_module.compact_findings()
    assert rc == 0
    captured = capsys.readouterr()
    assert "no findings" in captured.out


# --- atomic write -----------------------------------------------------------


def test_write_findings_atomic_round_trip(watcher_module):
    entries = [
        _make_raw_entry("aaaa1111aaaa1111", line=1),
        _make_raw_entry("bbbb2222bbbb2222", line=2),
        _make_raw_entry("cccc3333cccc3333", line=3),
    ]
    watcher_module._write_findings_atomic(entries)
    round_trip = watcher_module._iter_findings_raw()
    assert len(round_trip) == 3
    assert [e["fingerprint"] for e in round_trip] == [
        "aaaa1111aaaa1111",
        "bbbb2222bbbb2222",
        "cccc3333cccc3333",
    ]


def test_write_findings_atomic_leaves_no_temp_file(watcher_module):
    watcher_module._write_findings_atomic([_make_raw_entry("aaaa1111aaaa1111")])
    tmp = watcher_module.FINDINGS_FILE.with_suffix(
        watcher_module.FINDINGS_FILE.suffix + ".tmp"
    )
    assert not tmp.exists(), "atomic write must rename, not leave a .tmp sibling"


# ---------------------------------------------------------------------------
# Surfacing — the chime-in path
#
# Two commands back the two hooks that inject findings into the main Claude
# session: --print-unresolved (SessionStart, read-only, shows open+surfaced)
# and --surface-pending (UserPromptSubmit, chime mode, shows only open and
# transitions them to surfaced so the next prompt doesn't repeat them).
# ---------------------------------------------------------------------------


def test_format_findings_block_returns_none_on_empty(watcher_module):
    block, shown = watcher_module._format_findings_block([], header="x")
    assert block is None
    assert shown == []


def test_format_findings_block_suppresses_low_severity(watcher_module):
    """Low-severity findings are file-only signal; they must never show up
    in an injected block because the display cap is already tight and
    session context is precious."""
    findings = [
        _make_raw_entry("low_____00000000", severity="low"),
        _make_raw_entry("low_____11111111", severity="low"),
    ]
    block, shown = watcher_module._format_findings_block(findings, header="x")
    assert block is None
    assert shown == []


def test_format_findings_block_never_hides_critical_or_high(watcher_module):
    """Critical and high findings are never capped — hiding them to save
    context would be more dangerous than a long chime. The display cap
    (10 items) only applies to medium-severity, which is rationed
    against the room left after all critical+high are shown."""
    findings = [
        _make_raw_entry(f"fp_{i:013d}", severity="high")
        for i in range(15)
    ]
    block, shown = watcher_module._format_findings_block(findings, header="x")
    assert block is not None
    shown_count = sum(1 for line in block.splitlines() if line.startswith("  ["))
    assert shown_count == 15, f"all 15 high findings must show; got {shown_count}"
    assert "Total unresolved: 15" in block
    assert len(shown) == 15


def test_format_findings_block_caps_medium_when_criticals_leave_no_room(
    watcher_module,
):
    """With 10+ critical/high findings, medium-severity is fully suppressed
    (no slots left under the 10-item budget reserved for critical+high)."""
    findings = [
        _make_raw_entry(f"hi_{i:013d}", severity="high") for i in range(10)
    ] + [
        _make_raw_entry(f"md_{i:013d}", severity="medium") for i in range(5)
    ]
    block, shown = watcher_module._format_findings_block(findings, header="x")
    assert block is not None
    assert "[HIGH]" in block
    assert "[MEDIUM]" not in block  # no budget left after 10 highs
    # Exactly the 10 highs were shown; none of the 5 mediums
    assert len(shown) == 10
    assert all(f.get("severity") == "high" for f in shown)


def test_format_findings_block_rations_medium_alongside_criticals(
    watcher_module,
):
    """With 3 critical findings, 7 medium slots remain under the 10-item
    budget. A 15-medium queue must be capped to exactly 7."""
    findings = [
        _make_raw_entry(f"crit_{i:011d}", severity="critical") for i in range(3)
    ] + [
        _make_raw_entry(f"med__{i:011d}", severity="medium") for i in range(15)
    ]
    block, shown = watcher_module._format_findings_block(findings, header="x")
    assert block is not None
    med_lines = [l for l in block.splitlines() if "[MEDIUM]" in l]
    crit_lines = [l for l in block.splitlines() if "[CRITICAL]" in l]
    assert len(crit_lines) == 3
    assert len(med_lines) == 7
    assert len(shown) == 10  # 3 criticals + 7 mediums


def test_format_findings_block_prioritizes_critical_over_medium(watcher_module):
    findings = [
        _make_raw_entry("med_____00000000", severity="medium"),
        _make_raw_entry("crit____00000000", severity="critical"),
        _make_raw_entry("high____00000000", severity="high"),
    ]
    block, shown = watcher_module._format_findings_block(findings, header="x")
    assert block is not None
    # Critical should appear before high, which should appear before medium
    crit_pos = block.find("[CRITICAL]")
    high_pos = block.find("[HIGH]")
    med_pos = block.find("[MEDIUM]")
    assert 0 <= crit_pos < high_pos < med_pos


# --- print_unresolved (SessionStart hook, read-only) -----------------------


def test_print_unresolved_shows_both_open_and_surfaced(
    watcher_module, capsys
):
    """Regression: session-start must include findings that were already
    surfaced in a prior session. If it only showed status=='open', the
    chime-transitioned findings would disappear across restarts and the
    new session would start with stale context."""
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry("open____00000000", status="open"),
            _make_raw_entry("surfac__00000000", status="surfaced"),
            _make_raw_entry("confir__00000000", status="confirmed"),
            _make_raw_entry("dismis__00000000", status="dismissed"),
            _make_raw_entry("aged____00000000", status="aged_out"),
        ],
    )
    rc = watcher_module.print_unresolved()
    assert rc == 0
    captured = capsys.readouterr()
    assert "open____" in captured.out
    assert "surfac__" in captured.out
    assert "confir__" not in captured.out
    assert "dismis__" not in captured.out
    assert "aged____" not in captured.out


def test_print_unresolved_does_not_mutate_status(watcher_module):
    _seed_findings(
        watcher_module,
        [_make_raw_entry("open____00000000", status="open")],
    )
    watcher_module.print_unresolved()
    after = watcher_module._iter_findings_raw()
    # Critical: calling --print-unresolved at SessionStart must NEVER change
    # state, otherwise the chime-mode would never have anything new to show.
    assert after[0]["status"] == "open"


def test_print_unresolved_silent_on_empty(watcher_module, capsys):
    rc = watcher_module.print_unresolved()
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == ""


def test_print_unresolved_silent_when_only_resolved(watcher_module, capsys):
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry("confir__00000000", status="confirmed"),
            _make_raw_entry("dismis__00000000", status="dismissed"),
        ],
    )
    rc = watcher_module.print_unresolved()
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == ""


# --- surface_pending (UserPromptSubmit hook, chime mode) -------------------


def test_surface_pending_transitions_open_to_surfaced(watcher_module):
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry("open____00000000", status="open"),
            _make_raw_entry("surfac__00000000", status="surfaced"),
        ],
    )
    watcher_module.surface_pending()
    after = {f["fingerprint"]: f["status"] for f in watcher_module._iter_findings_raw()}
    assert after["open____00000000"] == "surfaced"
    # Already-surfaced findings stay surfaced (no-op on them)
    assert after["surfac__00000000"] == "surfaced"


def test_surface_pending_only_prints_when_there_are_new_open_findings(
    watcher_module, capsys
):
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry("surfac__00000000", status="surfaced"),
            _make_raw_entry("confir__00000000", status="confirmed"),
        ],
    )
    rc = watcher_module.surface_pending()
    assert rc == 0
    captured = capsys.readouterr()
    # No 'open' findings → nothing to chime → empty stdout. The
    # UserPromptSubmit hook must stay silent when there's nothing new.
    assert captured.out == ""


def test_surface_pending_leaves_confirmed_dismissed_untouched(watcher_module):
    _seed_findings(
        watcher_module,
        [
            _make_raw_entry("open____00000000", status="open"),
            _make_raw_entry("confir__00000000", status="confirmed"),
            _make_raw_entry("dismis__00000000", status="dismissed"),
        ],
    )
    watcher_module.surface_pending()
    after = {f["fingerprint"]: f["status"] for f in watcher_module._iter_findings_raw()}
    assert after["open____00000000"] == "surfaced"
    assert after["confir__00000000"] == "confirmed"
    assert after["dismis__00000000"] == "dismissed"


def test_surface_pending_chimes_then_goes_silent_on_second_call(
    watcher_module, capsys
):
    """This is the core chime contract: a fresh open finding chimes once,
    then the next call produces nothing until new open findings arrive.
    Without this, every prompt would re-chime the same findings until the
    user resolved them manually."""
    _seed_findings(
        watcher_module,
        [_make_raw_entry("open____00000000", status="open")],
    )

    # First call — chime fires
    watcher_module.surface_pending()
    first = capsys.readouterr().out
    assert "open____" in first
    assert "unitares-watcher-findings" in first

    # Second call — nothing to chime
    watcher_module.surface_pending()
    second = capsys.readouterr().out
    assert second == ""


def test_surface_pending_new_finding_after_chime_still_fires(
    watcher_module, capsys
):
    _seed_findings(
        watcher_module,
        [_make_raw_entry("first___00000000", status="open")],
    )
    watcher_module.surface_pending()
    capsys.readouterr()  # discard

    # Simulate a background scan adding a new open finding
    existing = watcher_module._iter_findings_raw()
    existing.append(_make_raw_entry("second__00000000", status="open"))
    watcher_module._write_findings_atomic(existing)

    watcher_module.surface_pending()
    captured = capsys.readouterr().out
    assert "second__" in captured
    # First finding was already surfaced and must NOT re-chime
    assert "first___" not in captured


# ---------------------------------------------------------------------------
# Ogler round-3 self-review fixes — 2026-04-11
#
# After shipping the Qwen3-Coder-Next model upgrade, Ogler flagged five
# latent issues in the Watcher code itself:
#
#   1. DEFAULT_CONTEXT_LINES=200 was a gemma4-era truncation that hid
#      anything past line 200 of the file from the scan. Qwen3 has a
#      256K context window — scanning whole files is cheap.
#
#   3. ~/Library/Logs/unitares-watcher.log was unbounded append — same
#      P002 pattern (round three) the Watcher's own library warns about.
#
#   4. surface_pending marked ALL open findings as surfaced, including
#      medium-severity findings the display cap had hidden. Combined with
#      content-hash dedup, those findings became silent drops — the user
#      never saw them but they'd never re-chime either.
#
# Fixes #2 (temperature 0.1 → 0.0) and #5 (max_tokens 2048 → 1024) are
# config constants and aren't exercised by unit tests directly; they're
# asserted by inspection below as a regression guard against drift.
# ---------------------------------------------------------------------------


def test_read_file_region_scans_whole_file_by_default(
    watcher_module, tmp_path
):
    """Regression for #1: DEFAULT_CONTEXT_LINES must be large enough that
    a typical source file is scanned end-to-end, not truncated at 200
    lines. A file that passes should_skip's 256KB cap should be scanned
    in full."""
    f = tmp_path / "longfile.py"
    f.write_text("\n".join(f"line_{i}" for i in range(500)))
    text, start, end = watcher_module.read_file_region(str(f))
    assert start == 1
    assert end == 500, (
        f"whole file should be scanned (500 lines); got end={end} — "
        "is DEFAULT_CONTEXT_LINES still at 200?"
    )
    assert "line_0" in text
    assert "line_499" in text


def test_default_context_lines_is_large_enough_for_typical_files(
    watcher_module,
):
    """Guard against re-regression to the gemma4-era 200-line cap. Must
    be at least 2000 to cover typical source files end-to-end; 10000 is
    the current target."""
    assert watcher_module.DEFAULT_CONTEXT_LINES >= 2000, (
        "DEFAULT_CONTEXT_LINES regressed to a small value — Qwen3 has "
        "a 256K context window and should_skip caps at 256KB; scanning "
        "whole files is the point."
    )


def test_model_call_uses_deterministic_temperature(watcher_module):
    """Regression for #2: detector workload wants temperature=0.0, not
    0.1. Asserts the constant hasn't drifted back to the creative-writing
    value. We inspect the call_model_via_governance function body
    textually rather than via a runtime probe because the temperature is
    a literal in the payload dict."""
    import inspect

    src_gov = inspect.getsource(watcher_module.call_model_via_governance)
    src_direct = inspect.getsource(watcher_module.call_ollama_direct)
    # Gov path uses SDK kwargs (temperature=0.0), direct path uses JSON literal
    assert "temperature=0.0" in src_gov or '"temperature": 0.0' in src_gov, (
        "gov path lost temperature=0.0 — detector must be deterministic"
    )
    assert '"temperature": 0.0' in src_direct, (
        "direct path lost temperature=0.0 — detector must be deterministic"
    )
    for label, src in (("gov", src_gov), ("direct", src_direct)):
        assert "temperature=0.1" not in src and '"temperature": 0.1' not in src, (
            f"{label} path regressed to temperature=0.1 — "
            "Ogler caught this once, do not re-ship"
        )


def test_model_call_max_tokens_is_not_wasteful(watcher_module):
    """Regression for #5: max_tokens should be right-sized for Qwen3's
    ~40-tokens-per-finding economy, not gemma4's 2048-era budget."""
    import inspect

    src_gov = inspect.getsource(watcher_module.call_model_via_governance)
    src_direct = inspect.getsource(watcher_module.call_ollama_direct)
    for label, src in (("gov", src_gov), ("direct", src_direct)):
        assert '"max_tokens": 2048' not in src, (
            f"{label} path still has 2048 — trim to the Qwen3 economy"
        )


# --- Log rotation (#3) ------------------------------------------------------


def test_rotate_log_trims_to_max_lines(
    watcher_module, tmp_path, monkeypatch
):
    """The log file must be trimmed to the last MAX_LOG_LINES entries
    when it exceeds the cap. Without this, the Watcher's own log file
    was an unbounded P002 self-match — round three of the same pattern
    Ogler has caught in this codebase."""
    log = tmp_path / "rot.log"
    log.write_text("\n".join(f"line_{i}" for i in range(50)) + "\n")

    watcher_module._common_trim_log(log, 10)

    remaining = log.read_text().splitlines()
    assert len(remaining) == 10, f"expected 10 lines after rotation, got {len(remaining)}"
    # Must keep the TAIL (most recent entries), not the head
    assert remaining[0] == "line_40"
    assert remaining[-1] == "line_49"


def test_rotate_log_noop_when_under_limit(
    watcher_module, tmp_path, monkeypatch
):
    """A log file smaller than MAX_LOG_LINES should not be rewritten."""
    log = tmp_path / "small.log"
    content = "line_0\nline_1\nline_2\n"
    log.write_text(content)
    mtime_before = log.stat().st_mtime_ns

    watcher_module._common_trim_log(log, 100)

    assert log.read_text() == content
    # Additionally assert the file wasn't rewritten (mtime unchanged).
    # On some filesystems this may not be reliable, but it's a useful guard.
    assert log.stat().st_mtime_ns == mtime_before


def test_rotate_log_missing_file_is_safe(
    watcher_module, tmp_path, monkeypatch
):
    """A missing log file must not raise — this runs on every scan_file
    entry and fire-and-forget hooks shouldn't crash on a fresh install."""
    log = tmp_path / "nonexistent.log"
    # Must not raise
    watcher_module._common_trim_log(log, 5000)
    assert not log.exists()


def test_max_log_lines_has_a_sane_upper_bound(watcher_module):
    """Guard against MAX_LOG_LINES being removed or set to an absurd
    value that defeats the rotation."""
    assert 100 <= watcher_module.MAX_LOG_LINES <= 100000, (
        f"MAX_LOG_LINES={watcher_module.MAX_LOG_LINES} is outside "
        "the sane operational range"
    )


# --- surface_pending silent-drop fix (#4) ----------------------------------


def test_surface_pending_does_not_silently_drop_hidden_mediums(
    watcher_module,
):
    """Regression for the silent-drop bug: when the display cap (10
    items, reserved first for critical/high) hides medium-severity
    findings, those mediums must stay `open` so they appear on a later
    chime once the queue drains.

    The old behavior was to mark ALL open findings as surfaced regardless
    of whether the display cap had shown them. Combined with the content-
    hash dedup, that silently dropped real findings — the user never saw
    them AND they'd never re-appear.
    """
    # Fill the 10-slot display cap with highs, plus 5 extra mediums
    # that should NOT be shown
    entries = [
        _make_raw_entry(f"hi_{i:013d}", severity="high", status="open")
        for i in range(10)
    ]
    entries += [
        _make_raw_entry(f"md_{i:013d}", severity="medium", status="open")
        for i in range(5)
    ]
    _seed_findings(watcher_module, entries)

    watcher_module.surface_pending()

    by_fp = {f["fingerprint"]: f for f in watcher_module._iter_findings_raw()}

    # All 10 highs were displayed → transitioned to surfaced
    for i in range(10):
        assert by_fp[f"hi_{i:013d}"]["status"] == "surfaced", (
            f"high finding {i} should have been surfaced (displayed)"
        )

    # None of the 5 mediums were displayed → must remain open
    for i in range(5):
        assert by_fp[f"md_{i:013d}"]["status"] == "open", (
            f"medium finding {i} was silently dropped — it wasn't "
            "displayed but got marked surfaced anyway"
        )


# --- P016 self-catch: nested-success-false in call_model_via_governance ---


def test_call_model_via_governance_raises_on_failure(
    watcher_module, monkeypatch
):
    """Regression for P016: when the SDK reports failure (either envelope
    level), call_model_via_governance must raise so the fallback to
    direct Ollama triggers."""
    import unitares_sdk.sync_client as _sc
    from unittest.mock import MagicMock

    fake_payload = {
        "success": False,
        "error": "simulated ollama failure",
    }

    class _FakeResp:
        def __init__(self, payload):
            self._body = json.dumps(payload).encode()

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=None):
        return _FakeResp(fake_payload)

    monkeypatch.setattr(_sc.urllib.request, "urlopen", _fake_urlopen)

    with pytest.raises(RuntimeError, match="call_model failed"):
        watcher_module.call_model_via_governance(
            "test prompt", "test-model", timeout=5
        )


def test_call_model_via_governance_accepts_nested_success_true(
    watcher_module, monkeypatch
):
    """Sanity: the happy path must still succeed."""
    import unitares_sdk.sync_client as _sc

    fake_payload = {
        "success": True,
        "result": {
            "success": True,
            "response": "all good",
            "model_used": "test-model",
        },
    }

    class _FakeResp:
        def __init__(self, payload):
            self._body = json.dumps(payload).encode()

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=None):
        return _FakeResp(fake_payload)

    monkeypatch.setattr(_sc.urllib.request, "urlopen", _fake_urlopen)

    result = watcher_module.call_model_via_governance(
        "test prompt", "test-model", timeout=5
    )
    assert result["text"] == "all good"


def test_call_model_via_governance_accepts_result_without_success_field(
    watcher_module, monkeypatch
):
    """Backwards-compat: older governance responses may not include a
    nested success field at all. The SDK should handle this gracefully."""
    import unitares_sdk.sync_client as _sc

    fake_payload = {
        "success": True,
        "result": {
            "success": True,
            "response": "legacy shape",
            "model_used": "test-model",
        },
    }

    class _FakeResp:
        def __init__(self, payload):
            self._body = json.dumps(payload).encode()

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=None):
        return _FakeResp(fake_payload)

    monkeypatch.setattr(_sc.urllib.request, "urlopen", _fake_urlopen)

    result = watcher_module.call_model_via_governance(
        "test prompt", "test-model", timeout=5
    )
    assert result["text"] == "legacy shape"


def test_call_model_falls_back_to_ollama_when_sdk_import_fails(
    watcher_module, monkeypatch
):
    """Regression: when the Python launching the hook lacks unitares_sdk
    (e.g. Homebrew python3 vs system framework python), the governance
    route raises ImportError. call_model must catch it and fall back to
    Ollama direct instead of returning [] silently."""

    def _raise_import_error(*args, **kwargs):
        raise ImportError("No module named 'unitares_sdk'")

    def _fake_ollama(prompt, model, timeout):
        return {"text": "ok", "model_used": model, "tokens_used": 42}

    monkeypatch.setattr(
        watcher_module, "call_model_via_governance", _raise_import_error
    )
    monkeypatch.setattr(watcher_module, "call_ollama_direct", _fake_ollama)

    result = watcher_module.call_model("test prompt", "test-model", timeout=5)

    assert result["text"] == "ok"
    assert result["tokens_used"] == 42


def test_surface_pending_second_chime_picks_up_previously_hidden_mediums(
    watcher_module, capsys
):
    """With the silent-drop fix: if a first chime hides mediums behind a
    wall of highs, and those highs later get resolved/dismissed, the
    mediums should re-surface on the next chime."""
    # First chime: 10 highs + 3 mediums (mediums hidden)
    entries = [
        _make_raw_entry(f"hi_{i:013d}", severity="high", status="open")
        for i in range(10)
    ]
    entries += [
        _make_raw_entry(f"md_{i:013d}", severity="medium", status="open")
        for i in range(3)
    ]
    _seed_findings(watcher_module, entries)

    watcher_module.surface_pending()
    first = capsys.readouterr().out
    assert "[HIGH]" in first
    assert "[MEDIUM]" not in first

    # Resolve all 10 highs (user acted on them)
    for i in range(10):
        watcher_module.update_finding_status(f"hi_{i:013d}", "confirmed")
    capsys.readouterr()  # discard resolve output

    # Second chime: highs are resolved, mediums should now appear
    watcher_module.surface_pending()
    second = capsys.readouterr().out
    assert "[MEDIUM]" in second, (
        "previously-hidden mediums should resurface once the "
        "critical/high queue drains"
    )
    assert "[HIGH]" not in second  # all resolved


# ---------------------------------------------------------------------------
# Escalation: critical findings → KG discovery
# ---------------------------------------------------------------------------


class TestEscalation:
    """Verify that escalate() stores KG discoveries for critical findings
    and is a no-op for non-critical severities."""

    def _make_finding(self, watcher_module, severity="critical"):
        return watcher_module.Finding(
            pattern="P099",
            file="/tmp/test.py",
            line=42,
            hint="test finding",
            severity=severity,
            detected_at="2026-04-11T12:00:00",
            model_used="test",
        )

    def test_escalate_critical_stores_kg_discovery(self, watcher_module, monkeypatch):
        """Critical findings are stored as KG discoveries."""
        kg_calls = []

        def fake_urlopen(req, timeout=None):
            body = json.loads(req.data.decode())

            class FakeResp:
                def read(self):
                    return b'{"success": true}'
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    pass

            kg_calls.append(body)
            return FakeResp()

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        finding = self._make_finding(watcher_module, severity="critical")
        watcher_module.escalate(finding)

        assert len(kg_calls) == 1, "should store one KG discovery"
        kg_args = kg_calls[0]["arguments"]
        assert kg_args["action"] == "store"
        assert kg_args["severity"] == "critical"
        assert "P099" in kg_args["summary"]

    def test_escalate_high_skips_kg(self, watcher_module, monkeypatch):
        """Non-critical findings should NOT call KG."""
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req)
            raise AssertionError("should not be called for high severity")

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        finding = self._make_finding(watcher_module, severity="high")
        watcher_module.escalate(finding)  # should return early
        assert len(calls) == 0

    def test_escalate_kg_failure_is_graceful(self, watcher_module, monkeypatch):
        """KG write failure should not crash the watcher."""
        def fake_urlopen(req, timeout=None):
            raise ConnectionError("governance down")

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        finding = self._make_finding(watcher_module, severity="critical")
        watcher_module.escalate(finding)  # should not raise
