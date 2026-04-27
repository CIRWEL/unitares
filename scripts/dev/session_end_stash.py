"""Session-end auto-stash: capture uncommitted work with a branch label.

Motivation: Claude/Codex sessions regularly leave uncommitted work in the
main worktree even when the edits logically belong to a different branch
or worktree. A later session sees the stale edits, intermingles them
with new work, or silently loses track when branches switch. This hook
runs on ``SessionEnd``, detects any dirty state, and stashes it with a
branch-labeled message so intent survives the session boundary.

Design choices:
- Include untracked files (``-u``) — new files are the easiest to lose
  sight of (no ``git log`` to reconstruct them from).
- Always stash on any dirtiness, no size threshold — stash is cheap to
  pop and cheap to drop; letting work bit-rot is not.
- Never fail the hook — session end must remain instant even if git
  hangs or the cwd isn't a repo.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


_GIT_TIMEOUT_SEC = 5


def _run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Invoke git with a bounded timeout; return (rc, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SEC,
            cwd=cwd,
        )
        return result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired):
        return 1, "", ""


def detect_dirty_state(cwd: str) -> dict:
    """Return ``{is_dirty, file_count, branch}`` for the tree at ``cwd``.

    ``git status --porcelain -uall`` gives one line per changed file,
    deduped across staged/unstaged (a file with both produces a single
    line like ``MM path``), so a simple non-empty line count is the
    file_count we want. Untracked files are included because those are
    the easiest to lose and the hardest to reconstruct.
    """
    rc, stdout, _ = _run_git(["status", "--porcelain", "-uall"], cwd)
    if rc != 0:
        return {"is_dirty": False, "file_count": 0, "branch": ""}

    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    is_dirty = bool(lines)
    file_count = len(lines)

    rc_branch, branch_stdout, _ = _run_git(["branch", "--show-current"], cwd)
    branch = branch_stdout.strip() if rc_branch == 0 else ""

    return {"is_dirty": is_dirty, "file_count": file_count, "branch": branch}


def build_stash_message(branch: str, file_count: int, timestamp: str) -> str:
    """Format a ``git stash push -m`` message that identifies the work.

    The format is scannable in ``git stash list`` and tells the user at a
    glance which branch the work came from, roughly when, and how much
    of it there is — enough to decide whether to pop, inspect, or drop.
    """
    branch_label = branch or "(detached)"
    return f"session-end auto-stash [{branch_label}] {timestamp} — {file_count} files"


def auto_stash(cwd: str) -> dict:
    """Detect dirty state, stash it with a labeled message, return a result dict.

    Return shape:
        {"stashed": bool, "file_count": int, "branch": str, "message": str}

    Never raises. Hook must not disrupt session end even if git is
    misbehaving.
    """
    state = detect_dirty_state(cwd)
    if not state["is_dirty"]:
        return {
            "stashed": False,
            "file_count": 0,
            "branch": state["branch"],
            "message": "",
        }

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    message = build_stash_message(
        branch=state["branch"],
        file_count=state["file_count"],
        timestamp=timestamp,
    )

    # -u: include untracked. -m: label the stash.
    rc, _, _ = _run_git(["stash", "push", "-u", "-m", message], cwd)
    if rc != 0:
        return {
            "stashed": False,
            "file_count": state["file_count"],
            "branch": state["branch"],
            "message": message,
        }

    return {
        "stashed": True,
        "file_count": state["file_count"],
        "branch": state["branch"],
        "message": message,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Session-end auto-stash")
    parser.add_argument(
        "--cwd", default=".", help="working directory to check (default: cwd)"
    )
    args = parser.parse_args(argv)

    cwd = str(Path(args.cwd).resolve())
    result = auto_stash(cwd)

    if result["stashed"]:
        print(f"session-end: stashed {result['file_count']} file(s) — {result['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
