"""Scraper functions for Chronicler.

Each scraper maps a catalog metric name to a zero-arg callable that
returns the scalar value at call time. Scrapers are pure "measure
something" functions — Chronicler handles HTTP posting, error emission,
and cadence. That separation keeps each scraper independently testable.

A scraper may raise on failure; Chronicler catches the exception, logs
it, and emits `<name>.error = 1` so silent breakage shows up in the
dashboard instead of as a missing line.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable


def tokei_unitares_src_code(repo_root: Path) -> float:
    """Count `.py` lines under `src/` of the unitares repo.

    Uses `wc -l` rather than tokei so no extra dep is required. Counts
    total lines (code + comments + blanks together). Absolute accuracy
    doesn't matter as long as the methodology is consistent over time.
    The `find` invocation is locked to `*.py` so language drift in
    subdirectories cannot change the reported value.
    """
    src = repo_root / "src"
    if not src.is_dir():
        raise FileNotFoundError(f"src/ not found at {src}")

    # find + xargs avoids a single huge argv; `wc -l` itself totals to stdout's last line.
    find = subprocess.run(
        ["find", str(src), "-type", "f", "-name", "*.py"],
        check=True, capture_output=True, text=True,
    )
    files = [f for f in find.stdout.splitlines() if f]
    if not files:
        return 0.0

    wc = subprocess.run(
        ["wc", "-l"] + files,
        check=True, capture_output=True, text=True,
    )
    last_line = wc.stdout.strip().splitlines()[-1]
    parts = last_line.split()
    if not parts:
        raise RuntimeError(f"Unexpected wc output: {wc.stdout!r}")
    return float(parts[0])


def tests_unitares_count(repo_root: Path) -> float:
    """Count `test_*.py` files under unitares/tests/.

    Uses `find` and relies on its exit code to catch missing directories.
    Includes tests under subdirectories (e.g. agents/*/tests/ are excluded
    — only unitares/tests/ so the signal stays interpretable).
    """
    tests = repo_root / "tests"
    if not tests.is_dir():
        raise FileNotFoundError(f"tests/ not found at {tests}")
    find = subprocess.run(
        ["find", str(tests), "-type", "f", "-name", "test_*.py"],
        check=True, capture_output=True, text=True,
    )
    files = [f for f in find.stdout.splitlines() if f]
    return float(len(files))


# Registry: metric name → scrape callable. Chronicler iterates this on each run.
#
# Keep this in sync with the server-side catalog in
# src/fleet_metrics/catalog.py — the server validates writes against the
# catalog, so a name here without a matching catalog entry is a 404 at
# the POST endpoint.
SCRAPERS: dict[str, Callable[[Path], float]] = {
    "tokei.unitares.src.code": tokei_unitares_src_code,
    "tests.unitares.count": tests_unitares_count,
}
