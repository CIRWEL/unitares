from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.resident_progress.snapshot_writer import SnapshotRow, SnapshotWriter


@pytest.mark.asyncio
async def test_writer_persists_all_rows_in_one_batch(test_db):
    tick_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    rows = [
        SnapshotRow(
            probe_tick_id=tick_id, ticked_at=now, resident_label="vigil",
            resident_uuid="11111111-1111-1111-1111-111111111111",
            source="kg_writes", metric_value=3, window_seconds=3600,
            threshold=1, metric_below_threshold=False, heartbeat_alive=True,
            candidate=False, suppressed_reason=None,
            error_details=None, liveness_inputs={"alive": True},
            loop_detector_state=None,
        ),
        SnapshotRow(
            probe_tick_id=tick_id, ticked_at=now, resident_label="watcher",
            resident_uuid="22222222-2222-2222-2222-222222222222",
            source="watcher_findings", metric_value=0, window_seconds=21600,
            threshold=1, metric_below_threshold=True, heartbeat_alive=True,
            candidate=True, suppressed_reason=None, error_details=None,
            liveness_inputs={"alive": True}, loop_detector_state=None,
        ),
    ]
    writer = SnapshotWriter(test_db)
    await writer.write(rows)

    async with test_db.acquire() as conn:
        persisted = await conn.fetch(
            "SELECT resident_label, candidate FROM progress_flat_snapshots "
            "WHERE probe_tick_id = $1 ORDER BY resident_label",
            tick_id,
        )
    assert len(persisted) == 2
    assert persisted[0]["resident_label"] == "vigil"
    assert persisted[0]["candidate"] is False
    assert persisted[1]["resident_label"] == "watcher"
    assert persisted[1]["candidate"] is True


@pytest.mark.asyncio
async def test_writer_persists_jsonb_dicts(test_db):
    tick_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    rows = [SnapshotRow(
        probe_tick_id=tick_id, ticked_at=now, resident_label="vigil",
        resident_uuid="11111111-1111-1111-1111-111111111111",
        source="kg_writes", metric_value=None, window_seconds=3600,
        threshold=1, metric_below_threshold=None, heartbeat_alive=False,
        candidate=False, suppressed_reason="source_error",
        error_details={"source": "kg_writes", "error": "boom"},
        liveness_inputs={"alive": False, "in_critical_silence": True},
        loop_detector_state={"loop_detected_at": "2026-04-25T20:00:00+00:00"},
    )]
    await SnapshotWriter(test_db).write(rows)
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT error_details, liveness_inputs, loop_detector_state "
            "FROM progress_flat_snapshots WHERE probe_tick_id = $1",
            tick_id,
        )
    assert row["error_details"]["error"] == "boom"
    assert row["liveness_inputs"]["in_critical_silence"] is True
    assert row["loop_detector_state"]["loop_detected_at"].startswith("2026-04-25")


@pytest.mark.asyncio
async def test_writer_empty_input_is_noop(test_db):
    # Should not acquire a connection. We assert by counting rows before/after.
    async with test_db.acquire() as conn:
        before = await conn.fetchval("SELECT count(*) FROM progress_flat_snapshots")
    await SnapshotWriter(test_db).write([])
    async with test_db.acquire() as conn:
        after = await conn.fetchval("SELECT count(*) FROM progress_flat_snapshots")
    assert before == after
