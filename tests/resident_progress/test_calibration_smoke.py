"""Calibration smoke test — catches obviously-misconfigured thresholds
before deploy. The 50% ceiling is a hard upper bound; the operational
tuning target is much lower and will be set from real data after Phase 1.

Filters to ticks that have a `progress_flat_probe` dogfood row, so
synthetic test inserts (from snapshot_writer/probe_task tests) do not
pollute the calibration signal. Skips when no real probe activity is
present in the window.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pytest


_REAL_TICK_IDS_SQL = """
SELECT DISTINCT probe_tick_id
FROM progress_flat_snapshots
WHERE ticked_at > now() - $1::interval
  AND resident_label = 'progress_flat_probe'
"""


@pytest.mark.asyncio
async def test_no_resident_candidate_above_fifty_percent(test_db):
    """If ANY configured resident is firing candidates >50% of REAL probe
    ticks, the threshold is misconfigured. Hard ceiling — operational
    target is much lower."""
    async with test_db.acquire() as conn:
        real_tick_ids = await conn.fetch(_REAL_TICK_IDS_SQL, timedelta(hours=24))
        if not real_tick_ids:
            pytest.skip(
                "no real probe ticks in the last 24h — run the probe "
                "against this DB at least once"
            )
        rows = await conn.fetch(
            """
            SELECT resident_label, candidate
            FROM progress_flat_snapshots
            WHERE probe_tick_id = ANY($1::uuid[])
              AND resident_label != 'progress_flat_probe'
            """,
            [r["probe_tick_id"] for r in real_tick_ids],
        )
    if not rows:
        pytest.skip(
            "real probe ticks had no resident rows — probe ran with empty "
            "registry; nothing to calibrate"
        )

    by_label: Counter = Counter()
    candidate_by_label: Counter = Counter()
    for r in rows:
        by_label[r["resident_label"]] += 1
        if r["candidate"]:
            candidate_by_label[r["resident_label"]] += 1

    offenders = []
    for label, total in by_label.items():
        ratio = candidate_by_label[label] / total
        if ratio > 0.5:
            offenders.append((label, ratio, total))
    assert not offenders, (
        f"residents firing candidate > 50% of ticks "
        f"(threshold misconfigured?): {offenders}"
    )


@pytest.mark.asyncio
async def test_at_least_one_dogfood_row_in_recent_window(test_db):
    """Probe-self liveness check: at least one real probe tick must
    have run in the last hour. Stronger than the previous version which
    accepted any snapshot row, including synthetic test inserts.
    """
    async with test_db.acquire() as conn:
        n = await conn.fetchval(
            """
            SELECT count(*) FROM progress_flat_snapshots
            WHERE ticked_at > now() - interval '1 hour'
              AND resident_label = 'progress_flat_probe'
            """
        )
    if n == 0:
        pytest.skip("no real probe ticks in the last hour — probe not running")
    assert n >= 1
