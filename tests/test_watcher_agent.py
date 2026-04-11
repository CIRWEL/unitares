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
    """Load ``scripts/ops/watcher_agent.py`` as a module without executing
    its ``__main__`` block."""
    project_root = Path(__file__).resolve().parent.parent
    module_path = project_root / "scripts" / "ops" / "watcher_agent.py"
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
