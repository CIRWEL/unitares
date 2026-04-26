"""Session-scoped schema bootstrap for resident_progress integration tests."""
from __future__ import annotations

import pytest_asyncio

from tests.test_db_utils import ensure_test_database_schema


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _bootstrap_schema():
    await ensure_test_database_schema()
