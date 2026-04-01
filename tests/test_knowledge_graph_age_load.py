from unittest.mock import AsyncMock

import pytest

from src.storage.knowledge_graph_age import KnowledgeGraphAGE


@pytest.mark.asyncio
async def test_load_rehydrates_when_age_empty_and_postgres_has_data():
    kg = KnowledgeGraphAGE()
    db = AsyncMock()
    db.graph_available.return_value = True
    kg._get_db = AsyncMock(return_value=db)
    kg._count_postgres_discoveries = AsyncMock(return_value=5)
    kg._count_age_discoveries = AsyncMock(return_value=0)
    kg._rehydrate_from_postgres = AsyncMock(
        return_value={"discoveries": 5, "related_edges": 2}
    )

    await kg.load()

    kg._rehydrate_from_postgres.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_skips_rehydrate_when_age_already_has_data():
    kg = KnowledgeGraphAGE()
    db = AsyncMock()
    db.graph_available.return_value = True
    kg._get_db = AsyncMock(return_value=db)
    kg._count_postgres_discoveries = AsyncMock(return_value=5)
    kg._count_age_discoveries = AsyncMock(return_value=3)
    kg._rehydrate_from_postgres = AsyncMock()

    await kg.load()

    kg._rehydrate_from_postgres.assert_not_called()
