"""Session-scoped schema bootstrap for resident_progress integration tests."""
from __future__ import annotations

import pytest
import pytest_asyncio

from tests.test_db_utils import (
    can_connect_to_test_db,
    ensure_test_database_schema,
    TEST_DB_URL,
)


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _bootstrap_schema():
    """Bootstrap the test schema.

    If governance_test is unreachable, does nothing — tests that don't touch
    the DB will still run successfully; tests that acquire test_db will skip
    themselves when pool creation fails.
    """
    if not can_connect_to_test_db():
        # DB unavailable — skip bootstrap; DB-dependent tests will skip on
        # their own when test_db raises.
        return
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

    try:
        pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=3, timeout=5)
    except Exception:
        pytest.skip("governance_test database not available")

    yield pool
    await pool.close()
