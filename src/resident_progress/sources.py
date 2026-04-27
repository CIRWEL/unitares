"""ResidentProgressSource implementations.

Each source issues exactly one batched query covering all relevant
resident UUIDs in the window — never N×M fanout. The orchestrator
groups configured (source_name, window) pairs and calls each group once.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Protocol

# Names defined in agents/chronicler/scrapers.py (SCRAPERS dict). Must
# stay in sync with that file; if Chronicler adds a series, add it here.
CHRONICLER_SERIES_NAMES: tuple[str, ...] = (
    "tokei.unitares.src.code",
    "tests.unitares.count",
    "agents.active.7d",
    "kg.entries.count",
    "checkins.7d",
)


class ResidentProgressSource(Protocol):
    name: str

    async def fetch(self, resident_uuids: list[str], window: timedelta) -> dict[str, int]: ...


class KnowledgeDiscoverySource:
    """Counts rows in knowledge.discoveries per resident_uuid in the window.

    Used for both Vigil (resident_label='vigil') and Watcher
    (resident_label='watcher'); the orchestrator filters by the resolved
    UUID so the same source class serves both.
    """
    name = "kg_writes"  # Watcher's source uses name='watcher_findings' (see registry)

    def __init__(self, db) -> None:
        self._db = db

    async def fetch(self, resident_uuids: list[str], window: timedelta) -> dict[str, int]:
        if not resident_uuids:
            return {}
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT agent_id::text AS uuid, count(*) AS n
                FROM knowledge.discoveries
                WHERE agent_id = ANY($1::text[])
                  AND created_at > now() - $2::interval
                GROUP BY agent_id
                """,
                resident_uuids,
                window,
            )
        counts = {r["uuid"]: int(r["n"]) for r in rows}
        return {u: counts.get(u, 0) for u in resident_uuids}


class WatcherFindingSource(KnowledgeDiscoverySource):
    """Same as KnowledgeDiscoverySource — Watcher posts via post_finding
    which lands in knowledge.discoveries. Subclassed only so the source
    name on snapshot rows is forensically distinct from Vigil's writes.
    """
    name = "watcher_findings"


class EISVSyncSource:
    """Counts audit.events rows with event_type='eisv_sync' authored by
    the given resident in the window. Steward is the sole writer.
    """
    name = "eisv_sync_rows"

    def __init__(self, db) -> None:
        self._db = db

    async def fetch(self, resident_uuids: list[str], window: timedelta) -> dict[str, int]:
        if not resident_uuids:
            return {}
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT agent_id::text AS uuid, count(*) AS n
                FROM audit.events
                WHERE event_type = 'eisv_sync'
                  AND agent_id = ANY($1::text[])
                  AND ts > now() - $2::interval
                GROUP BY agent_id
                """,
                resident_uuids,
                window,
            )
        counts = {r["uuid"]: int(r["n"]) for r in rows}
        return {u: counts.get(u, 0) for u in resident_uuids}


class MetricsSeriesSource:
    """Counts metrics.series rows whose `name` is in the
    Chronicler-known list, in the window. metrics.series has no agent_id
    column, so all configured UUIDs receive the same count — Chronicler
    is the sole writer of these names. If another agent ever starts
    writing to these names, this assumption breaks; revisit at that time.
    """
    name = "metrics_series"

    def __init__(self, db) -> None:
        self._db = db

    async def fetch(self, resident_uuids: list[str], window: timedelta) -> dict[str, int]:
        if not resident_uuids:
            return {}
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT count(*) AS n
                FROM metrics.series
                WHERE name = ANY($1::text[])
                  AND ts > now() - $2::interval
                """,
                list(CHRONICLER_SERIES_NAMES),
                window,
            )
        n = int(row["n"]) if row else 0
        return {u: n for u in resident_uuids}
