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
