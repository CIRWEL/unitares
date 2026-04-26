from __future__ import annotations

from datetime import timedelta

import pytest

from src.resident_progress.sources import (
    ResidentProgressSource,
    KnowledgeDiscoverySource,
    EISVSyncSource,
    MetricsSeriesSource,
    CHRONICLER_SERIES_NAMES,
)


@pytest.mark.asyncio
async def test_kg_source_returns_zero_for_unknown_uuid(test_db):
    src = KnowledgeDiscoverySource(test_db)
    out = await src.fetch(["00000000-0000-0000-0000-000000000000"], timedelta(hours=1))
    assert out == {"00000000-0000-0000-0000-000000000000": 0}


@pytest.mark.asyncio
async def test_kg_source_counts_recent_rows(test_db):
    uuid = "10000000-0000-0000-0000-000000000001"
    async with test_db.acquire() as conn:
        await conn.execute(
            "INSERT INTO knowledge.discoveries (id, agent_id, type, summary) "
            "VALUES ($1, $2, 'note', 'x') ON CONFLICT (id) DO NOTHING",
            "test-row-task4-1", uuid,
        )
    src = KnowledgeDiscoverySource(test_db)
    out = await src.fetch([uuid], timedelta(hours=1))
    assert out[uuid] >= 1


@pytest.mark.asyncio
async def test_eisv_sync_source_filters_by_event_type(test_db):
    src = EISVSyncSource(test_db)
    out = await src.fetch(["33333333-0000-0000-0000-000000000003"], timedelta(minutes=30))
    # No matching rows in test DB → returns zero, not raises
    assert out == {"33333333-0000-0000-0000-000000000003": 0}


def test_chronicler_series_names_includes_tokei():
    assert "tokei.unitares.src.code" in CHRONICLER_SERIES_NAMES


@pytest.mark.asyncio
async def test_metrics_series_source_returns_uniform_count(test_db):
    src = MetricsSeriesSource(test_db)
    uuids = [f"44444444-0000-0000-0000-{i:012d}" for i in range(3)]
    out = await src.fetch(uuids, timedelta(hours=26))
    # Chronicler source has no agent_id column; result is the same per-uuid count
    # because all uuids share the same name-filtered total.
    assert len({v for v in out.values()}) == 1
    assert set(out.keys()) == set(uuids)


@pytest.mark.asyncio
async def test_kg_source_empty_uuid_list_no_query(test_db):
    src = KnowledgeDiscoverySource(test_db)
    out = await src.fetch([], timedelta(hours=1))
    assert out == {}
