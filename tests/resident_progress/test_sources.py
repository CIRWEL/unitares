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
async def test_kg_source_batches_one_query_for_many_uuids(test_db):
    seen_calls = []
    real_acquire = test_db.acquire

    class _Tracking:
        def __init__(self, c):
            self._c = c

        async def fetch(self, *args, **kwargs):
            seen_calls.append(args[0] if args else "")
            return await self._c.fetch(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._c, name)

    class _AcquireProxy:
        def __init__(self):
            pass

        async def __aenter__(self):
            self._cm = real_acquire()
            conn = await self._cm.__aenter__()
            return _Tracking(conn)

        async def __aexit__(self, *a):
            return await self._cm.__aexit__(*a)

    class _PoolProxy:
        """Thin wrapper around the real pool that intercepts acquire() calls."""

        def acquire(self):
            return _AcquireProxy()

        def __getattr__(self, name):
            return getattr(test_db, name)

    src = KnowledgeDiscoverySource(_PoolProxy())
    await src.fetch(
        [f"22222222-0000-0000-0000-{i:012d}" for i in range(5)],
        timedelta(hours=1),
    )
    assert len(seen_calls) == 1, "must issue exactly one batched query"


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
