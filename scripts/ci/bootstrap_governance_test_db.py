#!/usr/bin/env python3
"""
Create `governance_test` and apply schema for integration tests.

Used by `.github/workflows/integration-live.yml`. Expects Postgres reachable at
`DB_POSTGRES_ADMIN_URL` or default postgresql://postgres:postgres@localhost:5432/postgres.

Set `DB_POSTGRES_URL` before running (same URL used by tests), e.g.:
  postgresql://postgres:postgres@127.0.0.1:5432/governance_test
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

DEFAULT_ADMIN = "postgresql://postgres:postgres@localhost:5432/postgres"
TEST_DB = "governance_test"


async def _main() -> int:
    try:
        import asyncpg
    except ImportError:
        print("asyncpg required: pip install asyncpg", file=sys.stderr)
        return 1

    admin_url = os.environ.get("DB_POSTGRES_ADMIN_URL", DEFAULT_ADMIN)
    test_url = os.environ.get(
        "DB_POSTGRES_URL",
        f"postgresql://postgres:postgres@localhost:5432/{TEST_DB}",
    )
    os.environ["DB_POSTGRES_URL"] = test_url

    conn = await asyncpg.connect(admin_url, timeout=30)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
            print(f"Created database {TEST_DB}")
        else:
            print(f"Database {TEST_DB} already exists")
    finally:
        await conn.close()

    # Import after DB_POSTGRES_URL is set (tests.test_db_utils reads it at import time)
    sys.path.insert(0, str(_REPO))
    from tests.test_db_utils import ensure_test_database_schema

    await ensure_test_database_schema()
    print("Schema ready for integration tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
