#!/usr/bin/env python3
"""
Sync discoveries from SQLite (governance.db) to AGE graph.
Only syncs discoveries not already in AGE.
"""

import sys
import os
import asyncio
import sqlite3
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set environment for PostgreSQL+AGE backend
os.environ["DB_BACKEND"] = "postgres"
os.environ["DB_POSTGRES_URL"] = "postgresql://postgres:postgres@localhost:5432/governance"
os.environ["DB_AGE_GRAPH"] = "governance_graph"

from src.knowledge_graph import DiscoveryNode


async def get_age_discovery_ids() -> set:
    """Get IDs of discoveries already in AGE."""
    import asyncpg
    conn = await asyncpg.connect("postgresql://postgres:postgres@localhost:5432/governance")
    try:
        # Load AGE extension and set search path
        await conn.execute("LOAD 'age';")
        await conn.execute("SET search_path = ag_catalog, public;")

        rows = await conn.fetch("""
            SELECT * FROM cypher('governance_graph', $$
                MATCH (d:Discovery) RETURN d.id as id
            $$) as (id agtype);
        """)
        return {str(r['id']).strip('"') for r in rows}
    finally:
        await conn.close()


async def sync_discoveries():
    """Sync missing discoveries from SQLite to AGE."""
    # Get AGE discovery IDs
    print("Fetching existing AGE discoveries...")
    age_ids = await get_age_discovery_ids()
    print(f"  Found {len(age_ids)} discoveries in AGE")

    # Get SQLite discoveries
    sqlite_path = project_root / "data" / "governance.db"
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM discoveries ORDER BY created_at")
    rows = cursor.fetchall()
    print(f"  Found {len(rows)} discoveries in SQLite")

    # Get tags for each discovery
    cursor.execute("SELECT discovery_id, tag FROM discovery_tags")
    tag_rows = cursor.fetchall()
    tags_by_id = {}
    for row in tag_rows:
        did = row['discovery_id']
        if did not in tags_by_id:
            tags_by_id[did] = []
        tags_by_id[did].append(row['tag'])

    # Find missing
    missing = []
    for row in rows:
        if row['id'] not in age_ids:
            missing.append((row, tags_by_id.get(row['id'], [])))

    print(f"  {len(missing)} discoveries need syncing")

    if not missing:
        print("All discoveries already synced!")
        return

    # Import AGE backend
    from src.storage.knowledge_graph_age import KnowledgeGraphAGE

    print("Connecting to AGE...")
    age = KnowledgeGraphAGE()
    await age.load()  # Initialize connection

    # Sync missing discoveries
    synced = 0
    errors = 0
    for row, tags in missing:
        try:
            discovery = DiscoveryNode(
                id=row['id'],
                agent_id=row['agent_id'],
                type=row['type'],
                summary=row['summary'] or '',
                details=row['details'] or '',
                tags=tags[:20],
                severity=row['severity'],
                timestamp=row['created_at'],
                status=row['status'] or 'open',
                related_to=[],
                references_files=[],
            )

            await age.add_discovery(discovery)
            synced += 1

            if synced % 50 == 0:
                print(f"  Progress: {synced}/{len(missing)}")

        except Exception as e:
            errors += 1
            if errors <= 3:  # Only show traceback for first 3 errors
                import traceback
                traceback.print_exc()
            print(f"  Error syncing {row['id']}: {e}")

    print(f"\nSync complete: {synced} synced, {errors} errors")

    # Verify
    new_count = len(await get_age_discovery_ids())
    print(f"AGE now has {new_count} discoveries")


if __name__ == "__main__":
    asyncio.run(sync_discoveries())
