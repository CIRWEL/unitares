"""Async read/write helpers for the `metrics.series` time-series table.

These are called from HTTP handlers (outside the MCP anyio task group,
so direct asyncpg `await` is safe) and from background tasks. MCP tool
handlers must not call these directly without the usual deadlock
mitigations (see project CLAUDE.md → Known Issue: anyio-asyncio Conflict).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.fleet_metrics.catalog import require


@dataclass(frozen=True)
class MetricPoint:
    ts: datetime
    value: float


async def record(name: str, value: float, ts: Optional[datetime] = None) -> None:
    """Insert one `(ts, name, value)` row after validating against the catalog.

    If `ts` is omitted the DB default (`now()`) is used, which is the path
    used by the daily Chronicler scraper. Callers backfilling historical
    values pass an explicit `ts`.
    """
    require(name)
    from src import agent_storage
    db = agent_storage.get_db()
    async with db.acquire() as conn:
        if ts is None:
            await conn.execute(
                "INSERT INTO metrics.series (name, value) VALUES ($1, $2)",
                name, float(value),
            )
        else:
            await conn.execute(
                "INSERT INTO metrics.series (ts, name, value) VALUES ($1, $2, $3)",
                ts, name, float(value),
            )


async def query(
    name: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 10_000,
) -> list[MetricPoint]:
    """Return `(ts, value)` pairs for `name`, oldest first, capped at `limit`.

    Intended shape: the dashboard requests a named series with a time range
    and renders the result as a line chart. `name` is required so we never
    scan the whole table; the `(name, ts DESC)` index handles this cheaply.

    Unknown `name` returns an empty list (no catalog check on read — you
    should be able to query a series after its catalog entry was removed,
    for forensic reasons).
    """
    if limit <= 0:
        return []
    limit = min(int(limit), 10_000)

    from src import agent_storage
    db = agent_storage.get_db()
    async with db.acquire() as conn:
        if since is None and until is None:
            rows = await conn.fetch(
                "SELECT ts, value FROM metrics.series "
                "WHERE name = $1 "
                "ORDER BY ts ASC LIMIT $2",
                name, limit,
            )
        elif until is None:
            rows = await conn.fetch(
                "SELECT ts, value FROM metrics.series "
                "WHERE name = $1 AND ts >= $2 "
                "ORDER BY ts ASC LIMIT $3",
                name, since, limit,
            )
        elif since is None:
            rows = await conn.fetch(
                "SELECT ts, value FROM metrics.series "
                "WHERE name = $1 AND ts <= $2 "
                "ORDER BY ts ASC LIMIT $3",
                name, until, limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT ts, value FROM metrics.series "
                "WHERE name = $1 AND ts >= $2 AND ts <= $3 "
                "ORDER BY ts ASC LIMIT $4",
                name, since, until, limit,
            )
    return [MetricPoint(ts=r["ts"], value=float(r["value"])) for r in rows]
