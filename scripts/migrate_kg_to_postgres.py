#!/usr/bin/env python3
"""
Migrate Knowledge Graph from SQLite to PostgreSQL

Moves discoveries, tags, and edges from governance.db to PostgreSQL knowledge.discoveries.
"""

import asyncio
import json
import sqlite3
from pathlib import Path
from datetime import datetime

try:
    import asyncpg
except ImportError:
    print("ERROR: asyncpg required. pip install asyncpg")
    exit(1)

SQLITE_PATH = Path("/Users/cirwel/projects/governance-mcp-v1/data/governance.db")
POSTGRES_URL = "postgresql://postgres:postgres@localhost:5432/governance"


async def migrate():
    print(f"Connecting to SQLite: {SQLITE_PATH}")
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row

    print(f"Connecting to PostgreSQL...")
    pg_conn = await asyncpg.connect(POSTGRES_URL)

    # Get existing Postgres count
    pg_count = await pg_conn.fetchval("SELECT COUNT(*) FROM knowledge.discoveries")
    print(f"PostgreSQL currently has {pg_count} discoveries")

    # Get SQLite discoveries
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM discoveries")
    sqlite_count = cursor.fetchone()[0]
    print(f"SQLite has {sqlite_count} discoveries to migrate")

    # Get all discoveries
    cursor.execute("""
        SELECT id, agent_id, type, severity, status, created_at, updated_at,
               resolved_at, summary, details, related_files, confidence,
               provenance, provenance_chain
        FROM discoveries
    """)
    discoveries = cursor.fetchall()

    # Get all tags
    cursor.execute("SELECT discovery_id, tag FROM discovery_tags")
    tags_raw = cursor.fetchall()
    tags_by_discovery = {}
    for row in tags_raw:
        did = row['discovery_id']
        if did not in tags_by_discovery:
            tags_by_discovery[did] = []
        tags_by_discovery[did].append(row['tag'])

    # Get all edges (related_to)
    cursor.execute("SELECT src_id, dst_id FROM discovery_edges WHERE edge_type = 'related_to'")
    edges_raw = cursor.fetchall()
    related_by_discovery = {}
    for row in edges_raw:
        sid = row['src_id']
        if sid not in related_by_discovery:
            related_by_discovery[sid] = []
        related_by_discovery[sid].append(row['dst_id'])

    migrated = 0
    skipped = 0
    errors = 0

    for disc in discoveries:
        disc_id = disc['id']
        try:
            # Check if already exists
            exists = await pg_conn.fetchval(
                "SELECT 1 FROM knowledge.discoveries WHERE id = $1", disc_id
            )
            if exists:
                skipped += 1
                continue

            # Parse timestamps
            created_at = None
            if disc['created_at']:
                try:
                    created_at = datetime.fromisoformat(disc['created_at'].replace('Z', '+00:00'))
                except:
                    created_at = datetime.now()

            updated_at = None
            if disc['updated_at']:
                try:
                    updated_at = datetime.fromisoformat(disc['updated_at'].replace('Z', '+00:00'))
                except:
                    pass

            resolved_at = None
            if disc['resolved_at']:
                try:
                    resolved_at = datetime.fromisoformat(disc['resolved_at'].replace('Z', '+00:00'))
                except:
                    pass

            # Get tags and related_to
            tags = tags_by_discovery.get(disc_id, [])
            related_to = related_by_discovery.get(disc_id, [])

            # Parse related_files
            references_files = []
            if disc['related_files']:
                try:
                    references_files = json.loads(disc['related_files'])
                except:
                    pass

            # Parse provenance
            provenance = None
            if disc['provenance']:
                try:
                    provenance = disc['provenance']  # Already JSON string
                except:
                    pass

            await pg_conn.execute("""
                INSERT INTO knowledge.discoveries (
                    id, agent_id, type, summary, details, tags, severity, status,
                    references_files, related_to, response_to_id, response_type,
                    provenance, created_at, updated_at, resolved_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            """,
                disc_id,
                disc['agent_id'],
                disc['type'],
                disc['summary'] or "",
                disc['details'] or "",
                tags,
                disc['severity'] or "low",
                disc['status'] or "open",
                references_files,
                related_to,
                None,  # response_to_id - would need separate parsing
                None,  # response_type
                provenance,
                created_at,
                updated_at,
                resolved_at,
            )
            migrated += 1

            if migrated % 50 == 0:
                print(f"  Migrated {migrated}...")

        except Exception as e:
            errors += 1
            print(f"  ERROR migrating {disc_id}: {e}")

    print(f"\nMigration complete:")
    print(f"  Migrated: {migrated}")
    print(f"  Skipped (already exists): {skipped}")
    print(f"  Errors: {errors}")

    # Verify
    new_pg_count = await pg_conn.fetchval("SELECT COUNT(*) FROM knowledge.discoveries")
    print(f"\nPostgreSQL now has {new_pg_count} discoveries")

    await pg_conn.close()
    sqlite_conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
