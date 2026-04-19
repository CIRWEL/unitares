"""Region-aware input helper for the watcher PostToolUse hook.

The hook used to pass only ``--file`` to the watcher, which then scanned the
whole file. For a 1951-line module the default 90s model timeout was not
enough. This helper runs ``git diff --unified=<context>`` on the edited file,
parses the hunk headers, and returns the changed regions so the watcher can
scan ~60-150 lines instead of the full file.

``git diff --unified=5`` is the same primitive pre-commit, reviewdog,
CodeRabbit and Sourcery use; the 5-line surrounding context is what LLM
review needs to reason about semantic changes (bare changed lines alone are
too local).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


# ``@@ -a[,b] +c[,d] @@`` — we only care about the new side (+c, +d).
# d defaults to 1 when the comma+count is absent (git convention).
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

_GIT_DIFF_TIMEOUT_SEC = 5


def extract_regions(file_path: str, context: int = 5) -> list[tuple[int, int]]:
    """Return the changed line ranges (1-indexed, inclusive) of ``file_path``.

    Uses ``git diff --unified=<context>`` against the working tree vs HEAD.
    ``context`` defaults to 5 because that is the empirically-grounded window
    LLM reviewers need (Sourcery documents the same value).

    Returns ``[]`` on any failure — git unavailable, file untracked, no diff,
    timeout. The hook is best-effort and must fall back gracefully to a
    full-file scan rather than propagating exceptions into the edit path.
    """
    # Pass the absolute path so git does not depend on the caller's cwd;
    # run from the file's parent so git finds the enclosing repo.
    abs_path = str(Path(file_path).resolve())
    try:
        result = subprocess.run(
            ["git", "diff", f"--unified={context}", "--", abs_path],
            capture_output=True,
            text=True,
            timeout=_GIT_DIFF_TIMEOUT_SEC,
            cwd=str(Path(abs_path).parent),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    regions: list[tuple[int, int]] = []
    for line in result.stdout.splitlines():
        match = _HUNK_HEADER_RE.match(line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        if count <= 0:
            continue
        regions.append((start, start + count - 1))
    return regions


def merge_adjacent(
    regions: list[tuple[int, int]], gap: int = 50
) -> list[tuple[int, int]]:
    """Merge regions whose separation is at most ``gap`` lines.

    Prevents both extremes:
    - Naive bounding box: lines 10 and 900 would become one 900-line region,
      no better than scanning the whole file.
    - One scan per hunk: back-to-back small edits would fan out into many
      processes and saturate the Ollama queue.

    Clusters with small gaps fuse into one prompt; disjoint clusters stay
    separate so the caller can fire one scan per cluster in sequence.
    """
    if not regions:
        return []
    ordered = sorted(regions)
    merged: list[tuple[int, int]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end - 1 <= gap:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def format_region(region: tuple[int, int]) -> str:
    """Render ``(start, end)`` as the exact ``--region`` syntax ``agent.py`` expects.

    agent.py's ``read_file_region`` parses ``L<start>-L<end>``; anything else
    is silently ignored and the watcher falls back to scanning head, which
    defeats the entire point of this module.
    """
    return f"L{region[0]}-L{region[1]}"


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the bash hook.

    Prints one region per line (e.g. ``L10-L30``). Empty output means the
    hook should scan the whole file. Multiple regions mean the hook should
    fire one watcher per region, sequentially.
    """
    parser = argparse.ArgumentParser(description="Extract changed regions for the watcher hook")
    parser.add_argument("--file", required=True, help="path of the edited file")
    parser.add_argument("--context", type=int, default=5, help="unified diff context lines")
    parser.add_argument("--gap", type=int, default=50, help="merge regions with gap <= this")
    args = parser.parse_args(argv)

    regions = extract_regions(args.file, context=args.context)
    merged = merge_adjacent(regions, gap=args.gap)
    for r in merged:
        print(format_region(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
