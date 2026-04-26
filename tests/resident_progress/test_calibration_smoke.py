"""Calibration smoke test — catches obviously-misconfigured thresholds
before deploy. The 50% ceiling is a hard upper bound; the operational
tuning target is much lower and will be set from real data after Phase 1.
"""
from __future__ import annotations

from collections import Counter

import pytest


@pytest.mark.asyncio
async def test_no_resident_candidate_above_fifty_percent(test_db):
    """If ANY configured resident is firing candidates >50% of ticks,
    the threshold is misconfigured. Hard ceiling — operational target is
    much lower."""
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT resident_label, candidate
            FROM progress_flat_snapshots
            WHERE ticked_at > now() - interval '24 hours'
              AND resident_label != 'progress_flat_probe'
            """
        )
    if not rows:
        pytest.skip("no snapshots persisted yet — run probe at least once")

    by_label = Counter()
    candidate_by_label = Counter()
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
async def test_at_least_one_row_per_resident_in_recent_window(test_db):
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT resident_label, count(*) AS n
            FROM progress_flat_snapshots
            WHERE ticked_at > now() - interval '1 hour'
            GROUP BY resident_label
            """
        )
    if not rows:
        pytest.skip("no snapshots persisted yet — run probe at least once")
    seen = {r["resident_label"] for r in rows}
    expected = {
        "vigil", "watcher", "steward", "chronicler", "sentinel",
        "progress_flat_probe",
    }
    missing = expected - seen
    # In a healthy probe, every configured resident has at least one
    # snapshot row per tick. Missing labels indicate the probe stopped
    # or the registry resolution silently failed.
    assert not missing, f"no recent snapshots for: {missing}"
