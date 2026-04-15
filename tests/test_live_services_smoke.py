"""
Optional live-service smoke tests (Postgres + AGE + Redis).

Runs only when `CI_LIVE_SERVICES=1` (set by `.github/workflows/integration-live.yml`).
Same opt-in as `test_postgres_backend_integration.py`. PR workflows do not set this.
"""

from __future__ import annotations

import os

import pytest

from tests.test_db_utils import live_integration_enabled

if not live_integration_enabled():
    pytest.skip(
        "Set CI_LIVE_SERVICES=1 for live Postgres/AGE/Redis checks",
        allow_module_level=True,
    )

pytestmark = pytest.mark.integration_live


@pytest.mark.asyncio
async def test_postgres_connects():
    try:
        import asyncpg
    except ImportError:
        pytest.fail("asyncpg required")

    from tests.test_db_utils import TEST_DB_URL

    conn = await asyncpg.connect(TEST_DB_URL, timeout=10)
    try:
        v = await conn.fetchval("SELECT 1")
        assert v == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_age_extension_loaded():
    """Verify Apache AGE is available (LOAD 'age' may be needed per session)."""
    try:
        import asyncpg
    except ImportError:
        pytest.fail("asyncpg required")

    from tests.test_db_utils import TEST_DB_URL

    conn = await asyncpg.connect(TEST_DB_URL, timeout=10)
    try:
        await conn.execute("LOAD 'age'")
        await conn.execute("SET search_path = ag_catalog, public")
        n = await conn.fetchval(
            "SELECT COUNT(*)::int FROM pg_extension WHERE extname = 'age'"
        )
        assert n == 1, "AGE extension should be installed"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_redis_ping():
    try:
        from redis import asyncio as redis_async
    except ImportError:
        pytest.skip("redis package not installed")

    url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    client = redis_async.from_url(url)
    try:
        pong = await client.ping()
        assert pong is True
    finally:
        await client.aclose()
