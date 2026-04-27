"""Batched insert for progress_flat_snapshots."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class SnapshotRow:
    probe_tick_id: UUID
    ticked_at: datetime
    resident_label: str
    resident_uuid: str | None
    source: str
    metric_value: int | None
    window_seconds: int | None
    threshold: int | None
    metric_below_threshold: bool | None
    heartbeat_alive: bool | None
    candidate: bool
    suppressed_reason: str | None
    error_details: dict | None
    liveness_inputs: dict | None
    loop_detector_state: dict | None


_INSERT_SQL = """
INSERT INTO progress_flat_snapshots (
    probe_tick_id, ticked_at, resident_label, resident_uuid, source,
    metric_value, window_seconds, threshold, metric_below_threshold,
    heartbeat_alive, candidate, suppressed_reason, error_details,
    liveness_inputs, loop_detector_state
) VALUES (
    $1, $2, $3, $4::uuid, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14::jsonb, $15::jsonb
)
"""


def _row_args(r: SnapshotRow) -> tuple[Any, ...]:
    def _j(d: dict | None) -> str | None:
        return json.dumps(d) if d is not None else None

    return (
        r.probe_tick_id, r.ticked_at, r.resident_label, r.resident_uuid,
        r.source, r.metric_value, r.window_seconds, r.threshold,
        r.metric_below_threshold, r.heartbeat_alive, r.candidate,
        r.suppressed_reason, _j(r.error_details), _j(r.liveness_inputs),
        _j(r.loop_detector_state),
    )


class SnapshotWriter:
    def __init__(self, db) -> None:
        self._db = db

    async def write(self, rows: list[SnapshotRow]) -> None:
        if not rows:
            return
        async with self._db.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(_INSERT_SQL, [_row_args(r) for r in rows])
