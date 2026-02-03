#!/usr/bin/env python3
"""
Migrate Knowledge Graph from SQLite to PostgreSQL

This script migrates all data from the SQLite knowledge graph (governance.db)
to the PostgreSQL knowledge schema.

Usage:
    python scripts/migrate_knowledge_to_postgres.py [--dry-run] [--batch-size N]

Options:
    --dry-run       Show what would be migrated without making changes
    --batch-size N  Number of discoveries to migrate per batch (default: 100)
"""

import sys
import os
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.logging_utils import get_logger
logger = get_logger(__name__)


async def ensure_knowledge_schema(conn) -> bool:
    """Ensure the knowledge schema exists in PostgreSQL."""
    try:
        # Check if schema exists
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'knowledge')"
        )
        if exists:
            logger.info("Knowledge schema already exists")
            return True

        # Run schema creation
        schema_file = project_root / "db" / "postgres" / "knowledge_schema.sql"
        if not schema_file.exists():
            logger.error(f"Schema file not found: {schema_file}")
            return False

        logger.info("Creating knowledge schema...")
        with open(schema_file, 'r') as f:
            schema_sql = f.read()

        # Split by semicolons and execute each statement
        # (asyncpg doesn't support multi-statement execution)
        for statement in schema_sql.split(';'):
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                try:
                    await conn.execute(statement)
                except Exception as e:
                    # Some statements may fail (IF NOT EXISTS, etc.) - that's OK
                    if 'already exists' not in str(e).lower():
                        logger.warning(f"Statement failed (may be OK): {e}")

        logger.info("Knowledge schema created")
        return True

    except Exception as e:
        logger.error(f"Failed to ensure knowledge schema: {e}")
        return False


async def migrate_discoveries(sqlite_db, pg_conn, dry_run: bool, batch_size: int) -> dict:
    """Migrate discoveries from SQLite to PostgreSQL."""
    stats = {
        "total": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": 0,
    }

    # Get all discoveries from SQLite
    cursor = sqlite_db.execute("""
        SELECT id, agent_id, type, severity, status, created_at, updated_at,
               resolved_at, summary, details, related_files, confidence,
               provenance, provenance_chain
        FROM discoveries
        ORDER BY created_at ASC
    """)
    discoveries = cursor.fetchall()
    stats["total"] = len(discoveries)

    logger.info(f"Found {stats['total']} discoveries to migrate")

    for i, row in enumerate(discoveries):
        discovery_id = row[0]

        try:
            # Check if already exists in PostgreSQL
            exists = await pg_conn.fetchval(
                "SELECT 1 FROM knowledge.discoveries WHERE id = $1",
                discovery_id
            )
            if exists:
                stats["skipped"] += 1
                continue

            if dry_run:
                logger.info(f"[DRY-RUN] Would migrate discovery {discovery_id}")
                stats["migrated"] += 1
                continue

            # Get tags for this discovery
            tag_cursor = sqlite_db.execute(
                "SELECT tag FROM discovery_tags WHERE discovery_id = ?",
                (discovery_id,)
            )
            tags = [t[0] for t in tag_cursor.fetchall()]

            # Get response_to edge
            edge_cursor = sqlite_db.execute("""
                SELECT dst_id, response_type FROM discovery_edges
                WHERE src_id = ? AND edge_type = 'response_to'
            """, (discovery_id,))
            resp_row = edge_cursor.fetchone()
            response_to_id = resp_row[0] if resp_row else None
            response_type = resp_row[1] if resp_row else None

            # Get related_to edges
            rel_cursor = sqlite_db.execute("""
                SELECT dst_id FROM discovery_edges
                WHERE src_id = ? AND edge_type = 'related_to'
            """, (discovery_id,))
            related_to = [r[0] for r in rel_cursor.fetchall()]

            # Parse related_files JSON
            related_files = []
            if row[10]:
                try:
                    related_files = json.loads(row[10])
                except json.JSONDecodeError:
                    pass

            # Parse provenance JSON
            provenance = None
            if row[12]:
                try:
                    provenance = json.loads(row[12]) if isinstance(row[12], str) else row[12]
                except (json.JSONDecodeError, TypeError):
                    pass

            provenance_chain = None
            if row[13]:
                try:
                    provenance_chain = json.loads(row[13]) if isinstance(row[13], str) else row[13]
                except (json.JSONDecodeError, TypeError):
                    pass

            # Parse timestamps
            created_at = _parse_timestamp(row[5])
            updated_at = _parse_timestamp(row[6])
            resolved_at = _parse_timestamp(row[7])

            # Insert into PostgreSQL
            await pg_conn.execute("""
                INSERT INTO knowledge.discoveries (
                    id, agent_id, type, severity, status, created_at, updated_at,
                    resolved_at, summary, details, tags, references_files, related_to,
                    response_to_id, response_type, confidence, provenance, provenance_chain
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
                ON CONFLICT (id) DO NOTHING
            """,
                discovery_id,           # id
                row[1],                 # agent_id
                row[2],                 # type
                row[3] or 'low',        # severity
                row[4] or 'open',       # status
                created_at,             # created_at
                updated_at,             # updated_at
                resolved_at,            # resolved_at
                row[8],                 # summary
                row[9] or '',           # details
                tags,                   # tags
                related_files,          # references_files
                related_to,             # related_to
                response_to_id,         # response_to_id
                response_type,          # response_type
                row[11],                # confidence
                json.dumps(provenance) if provenance else None,
                json.dumps(provenance_chain) if provenance_chain else None,
            )

            # Insert tags into normalized table
            for tag in tags:
                await pg_conn.execute("""
                    INSERT INTO knowledge.discovery_tags (discovery_id, tag)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                """, discovery_id, tag)

            stats["migrated"] += 1

            if (i + 1) % batch_size == 0:
                logger.info(f"Progress: {i + 1}/{stats['total']} discoveries processed")

        except Exception as e:
            logger.error(f"Error migrating discovery {discovery_id}: {e}")
            stats["errors"] += 1

    return stats


async def migrate_edges(sqlite_db, pg_conn, dry_run: bool) -> dict:
    """Migrate discovery edges from SQLite to PostgreSQL."""
    stats = {
        "total": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": 0,
    }

    # Get all edges from SQLite
    cursor = sqlite_db.execute("""
        SELECT src_id, dst_id, edge_type, response_type, weight,
               created_at, created_by, metadata
        FROM discovery_edges
    """)
    edges = cursor.fetchall()
    stats["total"] = len(edges)

    logger.info(f"Found {stats['total']} edges to migrate")

    for edge in edges:
        src_id, dst_id, edge_type = edge[0], edge[1], edge[2]

        try:
            # Check if already exists
            exists = await pg_conn.fetchval("""
                SELECT 1 FROM knowledge.discovery_edges
                WHERE src_id = $1 AND dst_id = $2 AND edge_type = $3
            """, src_id, dst_id, edge_type)

            if exists:
                stats["skipped"] += 1
                continue

            if dry_run:
                stats["migrated"] += 1
                continue

            # Parse metadata JSON
            metadata = None
            if edge[7]:
                try:
                    metadata = json.loads(edge[7]) if isinstance(edge[7], str) else edge[7]
                except (json.JSONDecodeError, TypeError):
                    pass

            await pg_conn.execute("""
                INSERT INTO knowledge.discovery_edges
                (src_id, dst_id, edge_type, response_type, weight, created_at, created_by, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT DO NOTHING
            """,
                src_id,
                dst_id,
                edge_type,
                edge[3],  # response_type
                edge[4] or 1.0,  # weight
                _parse_timestamp(edge[5]),  # created_at
                edge[6],  # created_by
                json.dumps(metadata) if metadata else None,
            )
            stats["migrated"] += 1

        except Exception as e:
            logger.error(f"Error migrating edge {src_id}->{dst_id}: {e}")
            stats["errors"] += 1

    return stats


def _parse_timestamp(ts):
    """Parse timestamp string to datetime."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return datetime.now()


async def main():
    parser = argparse.ArgumentParser(description="Migrate knowledge graph from SQLite to PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for progress reporting")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Knowledge Graph Migration: SQLite -> PostgreSQL")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    # Check for SQLite database
    sqlite_path = project_root / "data" / "governance.db"
    if not sqlite_path.exists():
        logger.error(f"SQLite database not found: {sqlite_path}")
        logger.info("Nothing to migrate - SQLite knowledge graph doesn't exist")
        return 0

    # Connect to SQLite
    import sqlite3
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row

    # Check if discoveries table exists
    cursor = sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='discoveries'"
    )
    if not cursor.fetchone():
        logger.info("No discoveries table in SQLite - nothing to migrate")
        sqlite_conn.close()
        return 0

    # Connect to PostgreSQL
    import asyncpg
    pg_url = os.environ.get("DB_POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/governance")

    try:
        pg_conn = await asyncpg.connect(pg_url)
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        sqlite_conn.close()
        return 1

    try:
        # Ensure schema exists
        if not args.dry_run:
            if not await ensure_knowledge_schema(pg_conn):
                logger.error("Failed to create knowledge schema")
                return 1

        # Migrate discoveries
        logger.info("\n--- Migrating Discoveries ---")
        disc_stats = await migrate_discoveries(sqlite_conn, pg_conn, args.dry_run, args.batch_size)

        # Migrate edges
        logger.info("\n--- Migrating Edges ---")
        edge_stats = await migrate_edges(sqlite_conn, pg_conn, args.dry_run)

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("Migration Summary")
        logger.info("=" * 60)
        logger.info(f"Discoveries: {disc_stats['migrated']} migrated, {disc_stats['skipped']} skipped, {disc_stats['errors']} errors")
        logger.info(f"Edges: {edge_stats['migrated']} migrated, {edge_stats['skipped']} skipped, {edge_stats['errors']} errors")

        if args.dry_run:
            logger.info("\nDRY RUN complete - no changes made")
        else:
            logger.info("\nMigration complete!")
            logger.info("To switch to PostgreSQL backend, ensure DB_BACKEND=postgres is set")

        return 0 if (disc_stats['errors'] == 0 and edge_stats['errors'] == 0) else 1

    finally:
        await pg_conn.close()
        sqlite_conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
