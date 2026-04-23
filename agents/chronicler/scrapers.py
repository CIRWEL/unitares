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

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Callable

# Default matches the server's DSN (see .claude/CLAUDE.md — one Postgres
# instance, one database). Overridable so a reflash or remote scrape can
# point somewhere else without code changes.
DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/governance"


def _fetchval(sql: str) -> float:
    """Run ``sql`` against the governance DB and return the scalar as float.

    Uses asyncpg under a one-shot ``asyncio.run`` because Chronicler is a
    daily cron, not a long-running process — the per-call loop is cheap at
    this cadence and keeps scrapers stateless (no shared pool to plumb).
    """
    import asyncpg  # local import: keeps test-time patching simple

    dsn = os.environ.get("CHRONICLER_DB_DSN", DEFAULT_DSN)

    async def _run() -> float:
        conn = await asyncpg.connect(dsn)
        try:
            value = await conn.fetchval(sql)
            return float(value or 0)
        finally:
            await conn.close()

    return asyncio.run(_run())


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


def agents_active_7d(_repo_root: Path) -> float:
    """Distinct agents with any tool call in the last 7 days — fleet liveness."""
    return _fetchval(
        "SELECT count(DISTINCT agent_id) FROM audit.tool_usage "
        "WHERE ts > now() - interval '7 days' AND agent_id IS NOT NULL"
    )


def kg_entries_count(_repo_root: Path) -> float:
    """Total discoveries in the knowledge graph — cumulative growth."""
    return _fetchval("SELECT count(*) FROM knowledge.discoveries")


def checkins_7d(_repo_root: Path) -> float:
    """process_agent_update calls in the last 7 days — governance traffic."""
    return _fetchval(
        "SELECT count(*) FROM audit.tool_usage "
        "WHERE ts > now() - interval '7 days' AND tool_name = 'process_agent_update'"
    )


# Registry: metric name → scrape callable. Chronicler iterates this on each run.
#
# Keep this in sync with the server-side catalog in
# src/fleet_metrics/catalog.py — the server validates writes against the
# catalog, so a name here without a matching catalog entry is a 404 at
# the POST endpoint.
SCRAPERS: dict[str, Callable[[Path], float]] = {
    "tokei.unitares.src.code": tokei_unitares_src_code,
    "tests.unitares.count": tests_unitares_count,
    "agents.active.7d": agents_active_7d,
    "kg.entries.count": kg_entries_count,
    "checkins.7d": checkins_7d,
}
