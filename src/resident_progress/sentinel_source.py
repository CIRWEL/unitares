"""SentinelPulseSource — pull-side of the push-based progress telemetry.

Sentinel calls the ``record_progress_pulse`` MCP tool (defined in
``src/mcp_handlers/resident_progress.py``) to post a progress pulse into
``resident_progress_pulse``. This class reads those rows back in a single
batched DISTINCT ON query for the probe orchestrator.
"""
from __future__ import annotations

from datetime import timedelta


class SentinelPulseSource:
    """Returns the latest recorded pulse value per resident UUID in a window.

    Uses a single DISTINCT ON query — no per-UUID fanout.
    """

    name = "sentinel_pulse"

    def __init__(self, db) -> None:
        self._db = db

    async def fetch(
        self, resident_uuids: list[str], window: timedelta
    ) -> dict[str, int]:
        """Return the latest ``value`` per resident_uuid in the window.

        Missing UUIDs (no row in window) are returned as 0.
        Empty input returns {} without issuing a query.
        """
        if not resident_uuids:
            return {}

        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (resident_uuid)
                    resident_uuid::text AS uuid,
                    value
                FROM resident_progress_pulse
                WHERE resident_uuid = ANY($1::uuid[])
                  AND recorded_at > now() - $2::interval
                ORDER BY resident_uuid, recorded_at DESC
                """,
                resident_uuids,
                window,
            )

        latest = {r["uuid"]: int(r["value"]) for r in rows}
        return {u: latest.get(u, 0) for u in resident_uuids}
