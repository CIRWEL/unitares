"""After 10 probe ticks, the dogfood row must appear in 10 of 10 ticks.
Regression guard for the dogfood-row write path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.resident_progress.probe_task import ProgressFlatProbe
from src.resident_progress.snapshot_writer import SnapshotWriter


@pytest.mark.asyncio
async def test_dogfood_row_present_in_every_tick(test_db, monkeypatch):
    """Run 10 ticks against the real writer with an empty registry —
    only the dogfood row should be produced per tick. Verify each
    tick's probe_tick_id has at least one progress_flat_probe row.
    """
    monkeypatch.setattr(
        "src.resident_progress.probe_task.RESIDENT_PROGRESS_REGISTRY", {},
    )
    writer = SnapshotWriter(test_db)
    probe = ProgressFlatProbe(
        sources_by_name={}, heartbeat_evaluator=AsyncMock(),
        writer=writer, audit_emitter=AsyncMock(), _now_tick=10,
    )
    # Capture the time before the test so we filter to just our ticks
    started_at = datetime.now(timezone.utc)
    for _ in range(10):
        await probe.tick()

    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT probe_tick_id,
                   count(*) FILTER (
                       WHERE resident_label = 'progress_flat_probe'
                   ) AS dogfoods
            FROM progress_flat_snapshots
            WHERE ticked_at >= $1
            GROUP BY probe_tick_id
            ORDER BY probe_tick_id
            """,
            started_at,
        )
    distinct_ticks_with_dogfood = [r for r in rows if r["dogfoods"] >= 1]
    assert len(distinct_ticks_with_dogfood) >= 10, (
        f"expected at least 10 ticks with dogfood rows, got "
        f"{len(distinct_ticks_with_dogfood)} (rows: {rows})"
    )
