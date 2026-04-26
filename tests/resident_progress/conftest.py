"""Session-scoped schema bootstrap for resident_progress integration tests."""
from __future__ import annotations

import pytest
import pytest_asyncio

from tests.test_db_utils import ensure_test_database_schema, TEST_DB_URL


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _bootstrap_schema():
    await ensure_test_database_schema()


@pytest_asyncio.fixture(loop_scope="function")
async def test_db():
    """Function-scoped asyncpg pool connected to governance_test.

    Creates a new pool per test so the pool lives in the same event loop
    as the test function (pytest-asyncio STRICT mode uses per-test loops).
    Skips if governance_test is unavailable. Relies on _bootstrap_schema
    (autouse=True above) having run before this fixture is used.
    """
    try:
        import asyncpg
    except ImportError:
        pytest.skip("asyncpg not installed")

    pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=3)
    yield pool
    await pool.close()
