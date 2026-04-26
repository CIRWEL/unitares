"""Smoke test: migration 018 creates both telemetry tables with required columns."""
from __future__ import annotations

import pytest
import asyncpg

GOVERNANCE_DB_URL = "postgresql://postgres:postgres@localhost:5432/governance"


@pytest.mark.asyncio
async def test_progress_flat_snapshots_table_exists():
    conn = await asyncpg.connect(GOVERNANCE_DB_URL)
    try:
        cols = await conn.fetch("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='progress_flat_snapshots'
            ORDER BY ordinal_position
        """)
    finally:
        await conn.close()

    names = {r["column_name"] for r in cols}
    required = {
        "id", "probe_tick_id", "ticked_at", "resident_label", "resident_uuid",
        "source", "metric_value", "window_seconds", "threshold",
        "metric_below_threshold", "heartbeat_alive", "candidate",
        "suppressed_reason", "error_details", "liveness_inputs",
        "loop_detector_state",
    }
    missing = required - names
    assert not missing, f"missing columns: {missing}"


@pytest.mark.asyncio
async def test_resident_progress_pulse_table_exists():
    conn = await asyncpg.connect(GOVERNANCE_DB_URL)
    try:
        cols = await conn.fetch("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='resident_progress_pulse'
        """)
    finally:
        await conn.close()

    names = {r["column_name"] for r in cols}
    assert {"id", "resident_uuid", "metric_name", "value", "recorded_at"} <= names
