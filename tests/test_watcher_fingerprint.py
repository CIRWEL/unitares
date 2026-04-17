"""Watcher fingerprint normalization.

The fingerprint must dedup the same finding across multiple git worktrees
of the same repo, so a P001 in `/repo/.worktrees/A/src/x.py:47` and the
identical-code P001 in `/repo/.worktrees/B/src/x.py:47` collapse to ONE
surfaced finding instead of N copies that multiply with worktree count.

The displayed ``file`` field stays absolute so the user can still navigate
to the right copy; only the fingerprint hash uses repo-relative form.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agents.watcher.agent import Finding, hash_line_content, repo_relative_path


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
