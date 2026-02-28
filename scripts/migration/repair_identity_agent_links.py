#!/usr/bin/env python3
"""
Repair missing core.agents rows for existing core.identities.

Use when identities exist without matching agents (Postgres).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import List

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.db import get_db, close_db


async def _fetch_orphan_identities(db) -> List[str]:
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT i.agent_id
            FROM core.identities i
            LEFT JOIN core.agents a ON a.id = i.agent_id
            WHERE a.id IS NULL
            ORDER BY i.created_at DESC
            """
        )
    return [row["agent_id"] for row in rows]


async def main() -> int:
    parser = argparse.ArgumentParser(description="Repair identities missing agents in Postgres")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()

    if os.getenv("DB_BACKEND", "").lower() != "postgres":
        print("DB_BACKEND is not 'postgres'. Set DB_BACKEND=postgres and DB_POSTGRES_URL.")
        return 1

    db = get_db()
    if not hasattr(db, "_pool") or db._pool is None:
        await db.init()

    orphan_agent_ids = await _fetch_orphan_identities(db)
    if not orphan_agent_ids:
        print("No missing agent rows found.")
        await close_db()
        return 0

    print(f"Found {len(orphan_agent_ids)} identities without agents.")
    for agent_id in orphan_agent_ids:
        print(f" - {agent_id}")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to create missing agents.")
        await close_db()
        return 0

    for agent_id in orphan_agent_ids:
        await db.upsert_agent(
            agent_id=agent_id,
            api_key="",
            status="active",
        )
        print(f"Created core.agents row for {agent_id}")

    await close_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
