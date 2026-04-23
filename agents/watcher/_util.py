"""Leaf utilities shared by agent.py and findings.py.

Split out so findings.py can depend on log/path helpers without pulling
agent.py (which would create a circular import, since agent.py imports
from findings.py).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

LOG_FILE = Path.home() / "Library" / "Logs" / "unitares-watcher.log"

# Cap for ~/Library/Logs/unitares-watcher.log rotation. Watcher logs a few
# lines per scan; 5000 lines ≈ 500 scans of operational history, which is
# plenty for debugging. Without this, the log file was a direct P002 match
# against the Watcher's own pattern library — unbounded append forever.
MAX_LOG_LINES = 5000


def log(msg: str, level: str = "info") -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} [{level}] {msg}\n"
    try:
        with LOG_FILE.open("a") as f:
            f.write(line)
    except OSError:
        pass  # never let logging errors take down the watcher
    if os.environ.get("WATCHER_DEBUG") == "1":
        sys.stderr.write(line)


_REPO_ROOT_CACHE: dict[str, str] = {}


def repo_relative_path(file_path: str) -> str:
    """Return ``file_path`` relative to its containing git worktree root.

    Falls back to the absolute string if the path is not inside a git
    repository or git invocation fails. Result is normalized to forward
    slashes so the fingerprint is platform-stable.

    Cached per-directory because hook-driven scans hit the same worktree
    over and over and ``git rev-parse`` is otherwise tens of ms each call.
    """
    if not file_path:
        return file_path
    p = Path(file_path)
    parent_key = str(p.parent if p.is_absolute() else p.resolve().parent)
    toplevel = _REPO_ROOT_CACHE.get(parent_key)
    if toplevel is None:
        try:
            result = subprocess.run(
                ["git", "-C", parent_key, "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            toplevel = result.stdout.strip() if result.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            toplevel = ""
        _REPO_ROOT_CACHE[parent_key] = toplevel
    if not toplevel:
        return file_path
    try:
        rel = Path(file_path).resolve().relative_to(Path(toplevel).resolve())
    except ValueError:
        return file_path
    return rel.as_posix()


def hash_line_content(source_line: str | None) -> str:
    """Stable hash of a source line for content-aware fingerprinting.

    Whitespace is stripped from both ends so indent-only reformats do not
    trigger spurious re-flags. Internal whitespace is preserved because it
    can be semantically meaningful (e.g. dict literal formatting).
    """
    normalized = (source_line or "").strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:12]
