"""Unit tests for KnowledgeGraphPostgres timestamp coercion.

Covers the regression where lifecycle cleanup passed ISO-format strings
for timestamp-typed columns, which asyncpg rejected. The backend now
coerces strings to datetime at its boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.storage.knowledge_graph_postgres import (
    KnowledgeGraphPostgres,
    _coerce_timestamp,
)


class TestCoerceTimestamp:
    def test_passes_datetime_through(self):
        now = datetime.now(timezone.utc)
        assert _coerce_timestamp(now) is now

    def test_parses_iso_string(self):
        result = _coerce_timestamp("2026-04-18T01:23:45.678+00:00")
        assert isinstance(result, datetime)
        assert result.year == 2026 and result.minute == 23

    def test_parses_zulu_suffix(self):
        result = _coerce_timestamp("2026-04-18T01:23:45Z")
        assert isinstance(result, datetime)
        assert result.tzinfo is not None


@pytest.mark.asyncio
class TestUpdateDiscoveryTimestampCoercion:
    async def _make_backend(self, captured: list):
        """KnowledgeGraphPostgres with a mocked pool that records fetchval args."""
        backend = KnowledgeGraphPostgres()

        async def fake_fetchval(query, *args):
            captured.append((query, args))
            return "discovery-id"

        db = MagicMock()
        db._pool = MagicMock()
        db._pool.fetchval = AsyncMock(side_effect=fake_fetchval)
        backend._db = db
        backend._initialized = True

        async def _get_db():
            return db

        backend._get_db = _get_db  # type: ignore[assignment]
        return backend

    async def test_updated_at_string_coerced_to_datetime(self):
        captured: list = []
        backend = await self._make_backend(captured)

        ok = await backend.update_discovery(
            "discovery-id",
            {"status": "archived", "updated_at": "2026-04-18T01:23:45+00:00"},
        )

        assert ok is True
        assert len(captured) == 1
        _query, args = captured[0]
        # args: (discovery_id, status, updated_at)
        assert args[0] == "discovery-id"
        assert args[1] == "archived"
        assert isinstance(args[2], datetime), (
            f"updated_at must be datetime for asyncpg, got {type(args[2]).__name__}"
        )

    async def test_resolved_at_string_coerced_to_datetime(self):
        captured: list = []
        backend = await self._make_backend(captured)

        await backend.update_discovery(
            "discovery-id",
            {"resolved_at": "2026-04-18T01:23:45+00:00"},
        )

        assert len(captured) == 1
        _query, args = captured[0]
        assert isinstance(args[1], datetime)

    async def test_datetime_passes_through(self):
        captured: list = []
        backend = await self._make_backend(captured)
        now = datetime.now(timezone.utc)

        await backend.update_discovery(
            "discovery-id",
            {"updated_at": now},
        )

        _query, args = captured[0]
        assert args[1] is now
