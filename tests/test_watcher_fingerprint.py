"""Watcher fingerprint normalization + structural-verifier refinements.

Cross-worktree dedup: the fingerprint must collapse identical code at
the same line across N worktrees into ONE surfaced finding (not N).

P001 / P003 refinements: structural verifier drops false positives where
the model matched a substring but the actual construct is the BLESSED
solution to the very pattern (the project's tracked-task wrapper, or
the cache function itself).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agents.watcher.agent import (
    Finding,
    _is_inside_get_or_create_monitor,
    _verify_finding_against_source,
    hash_line_content,
    repo_relative_path,
)


def _make_finding(file_path: str, line: int, source_line: str) -> Finding:
    f = Finding(
        pattern="P001",
        file=file_path,
        line=line,
        hint="fire-and-forget task",
        severity="high",
        detected_at="2026-04-17T00:00:00Z",
        model_used="test-stub",
    )
    f.line_content_hash = hash_line_content(source_line)
    f.fingerprint = f.compute_fingerprint()
    return f


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def two_worktrees(tmp_path):
    """Real git repo with one main checkout and one extra worktree, both
    containing the same source line at the same path. We use a real repo
    (not mocks) because repo_relative_path shells out to ``git rev-parse``."""
    main = tmp_path / "repo"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "t@t.t")
    _git(main, "config", "user.name", "t")
    src = main / "src"
    src.mkdir()
    file_main = src / "x.py"
    file_main.write_text("asyncio.create_task(noop())\n")
    _git(main, "add", "src/x.py")
    _git(main, "commit", "-q", "-m", "seed")

    wt = tmp_path / "wt-feature"
    _git(main, "worktree", "add", "-q", "-b", "feature", str(wt))
    file_wt = wt / "src" / "x.py"
    assert file_wt.read_text() == file_main.read_text()
    return file_main, file_wt


def test_repo_relative_strips_worktree_prefix(two_worktrees):
    main_file, wt_file = two_worktrees
    assert repo_relative_path(str(main_file)) == "src/x.py"
    assert repo_relative_path(str(wt_file)) == "src/x.py"


def test_fingerprint_dedups_across_worktrees(two_worktrees):
    main_file, wt_file = two_worktrees
    line = "asyncio.create_task(noop())"
    f_main = _make_finding(str(main_file), 1, line)
    f_wt = _make_finding(str(wt_file), 1, line)
    assert f_main.fingerprint == f_wt.fingerprint, (
        "identical code at the same line in two worktrees must produce "
        f"one fingerprint (got main={f_main.fingerprint!r}, wt={f_wt.fingerprint!r})"
    )


def test_fingerprint_differs_on_different_line_content(two_worktrees):
    main_file, _ = two_worktrees
    f_a = _make_finding(str(main_file), 1, "asyncio.create_task(noop())")
    f_b = _make_finding(str(main_file), 1, "asyncio.create_task(other())")
    assert f_a.fingerprint != f_b.fingerprint, (
        "different code at the same line must NOT collide — content hash "
        "is what protects against silent reuse of a stale resolution"
    )


def test_fingerprint_differs_across_files(two_worktrees):
    main_file, _ = two_worktrees
    other = main_file.parent / "y.py"
    other.write_text("asyncio.create_task(noop())\n")
    f_x = _make_finding(str(main_file), 1, "asyncio.create_task(noop())")
    f_y = _make_finding(str(other), 1, "asyncio.create_task(noop())")
    assert f_x.fingerprint != f_y.fingerprint


def test_repo_relative_falls_back_when_not_in_git(tmp_path):
    """Files outside any git repo keep their absolute path — graceful
    fallback so the watcher does not crash on scratch files."""
    loose = tmp_path / "scratch.py"
    loose.write_text("x = 1\n")
    assert repo_relative_path(str(loose)) == str(loose)


def test_repo_relative_handles_empty_input():
    assert repo_relative_path("") == ""


# ---------------------------------------------------------------------------
# P001 / P003 structural verifier refinements
# ---------------------------------------------------------------------------


def _p001_finding(line: int) -> Finding:
    return Finding(
        pattern="P001",
        file="/repo/src/x.py",
        line=line,
        hint="fire-and-forget task",
        severity="high",
        detected_at="2026-04-17T00:00:00Z",
        model_used="test-stub",
    )


def _p003_finding(line: int) -> Finding:
    return Finding(
        pattern="P003",
        file="/repo/src/agent_lifecycle.py",
        line=line,
        hint="transient monitor",
        severity="high",
        detected_at="2026-04-17T00:00:00Z",
        model_used="test-stub",
    )


def test_p001_drops_create_tracked_task_call_site():
    """`create_tracked_task(...)` is the blessed wrapper that stores the
    task ref by construction. P001 must not flag call sites of it."""
    src_line = '    create_tracked_task(my_coro(), name="bg")'
    snippet = {1: src_line}
    f = _p001_finding(1)
    assert _verify_finding_against_source(f, src_line, snippet) is False


def test_p001_still_flags_bare_create_task_call():
    """Sanity guard: bare `asyncio.create_task(coro())` with no assignment
    and no tracked-task wrapper still trips the pattern."""
    src_line = "    asyncio.create_task(noop())"
    snippet = {1: src_line}
    f = _p001_finding(1)
    assert _verify_finding_against_source(f, src_line, snippet) is True


def test_p001_keeps_assigned_create_task_drop():
    """Existing _P001_TASK_ASSIGNMENT drop still applies — assignment to
    a name proves the ref is stored."""
    src_line = "    task = asyncio.create_task(noop())"
    snippet = {1: src_line}
    f = _p001_finding(1)
    assert _verify_finding_against_source(f, src_line, snippet) is False


def test_p003_drops_when_inside_get_or_create_monitor_body():
    """Flag landing inside the cache function's own body must not surface —
    it IS the cache, not a transient instantiation outside the cache."""
    snippet = {
        20: "def get_or_create_monitor(agent_id):",
        21: "    if agent_id in monitors:",
        22: "        return monitors[agent_id]",
        23: "    monitor = UNITARESMonitor(agent_id)",
        24: "    monitors[agent_id] = monitor",
        25: "    return monitor",
    }
    f = _p003_finding(23)
    assert _is_inside_get_or_create_monitor(23, snippet) is True
    assert _verify_finding_against_source(f, snippet[23], snippet) is False


def test_p003_still_flags_when_inside_other_function():
    """A transient-monitor instantiation in a different function body
    should still surface — that's the real bug shape."""
    snippet = {
        50: "def some_other_handler(event):",
        51: "    monitor = UNITARESMonitor(event.agent_id)",
        52: "    monitor.update(...)",
    }
    f = _p003_finding(51)
    assert _is_inside_get_or_create_monitor(51, snippet) is False
    assert _verify_finding_against_source(f, snippet[51], snippet) is True


def test_p003_async_def_get_or_create_monitor_also_protected():
    """Defensive: if the cache function ever becomes async, the verifier
    must still recognize its body as 'inside the cache'."""
    snippet = {
        10: "async def get_or_create_monitor(agent_id):",
        11: "    monitor = UNITARESMonitor(agent_id)",
    }
    assert _is_inside_get_or_create_monitor(11, snippet) is True
