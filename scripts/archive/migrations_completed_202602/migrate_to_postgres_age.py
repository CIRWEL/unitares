#!/usr/bin/env python3
"""
Migration script: SQLite/JSON → PostgreSQL + AGE

Migrates existing data from SQLite and JSON files to PostgreSQL with Apache AGE.

Usage:
    python scripts/migrate_to_postgres_age.py [--dry-run] [--skip-graph]

Phases:
    1. Migrate agents to core.agents table
    2. Migrate sessions to core.agent_sessions
    3. Migrate dialectic sessions
    4. Create AGE graph
    5. Migrate discoveries to AGE graph
    6. Create edges (AUTHORED, RESPONDS_TO, RELATED_TO, TAGGED, TEMPORALLY_NEAR)
"""

import asyncio
import argparse
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

from src.logging_utils import get_logger
from src.db import get_db
from src.knowledge_graph import DiscoveryNode
from src.storage.knowledge_graph_age import KnowledgeGraphAGE

logger = get_logger(__name__)

def _row_get(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    """sqlite3.Row doesn't implement .get(); emulate it safely across schema versions."""
    try:
        keys = row.keys()
    except Exception:
        keys = []
    return row[key] if key in keys else default


def _parse_dt(value: Any) -> datetime:
    """Best-effort datetime parser for legacy SQLite string timestamps."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.now()


def _get_postgres_pool(db) -> Any:
    """
    Extract asyncpg pool from the configured DB backend.

    Supports DB_BACKEND=postgres (PostgresBackend) and DB_BACKEND=dual (DualWriteBackend).
    """
    if hasattr(db, "_pool"):
        return getattr(db, "_pool")
    if hasattr(db, "_postgres") and getattr(db, "_postgres_available", False):
        pg = getattr(db, "_postgres")
        if hasattr(pg, "_pool"):
            return getattr(pg, "_pool")
    raise RuntimeError("PostgreSQL pool not available - set DB_BACKEND=postgres (or dual with Postgres available)")


def _get_age_graph_name(db) -> str:
    """Best-effort graph name lookup (matches PostgresBackend._age_graph)."""
    if hasattr(db, "_age_graph"):
        return getattr(db, "_age_graph") or "governance_graph"
    if hasattr(db, "_postgres") and getattr(db, "_postgres_available", False):
        pg = getattr(db, "_postgres")
        if hasattr(pg, "_age_graph"):
            return getattr(pg, "_age_graph") or "governance_graph"
    return "governance_graph"


async def migrate_agents(
    db,
    sqlite_path: Path,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Migrate agents from SQLite agent_metadata to core.agents."""
    logger.info("Phase 1: Migrating agents...")
    
    if not sqlite_path.exists():
        logger.warning(f"SQLite DB not found: {sqlite_path}")
        return {"migrated": 0, "skipped": 0}
    
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    
    agents = conn.execute("SELECT * FROM agent_metadata").fetchall()
    
    migrated = 0
    skipped = 0
    
    for row in agents:
        agent_id = row["agent_id"]
        api_key = _row_get(row, "api_key", "") or ""
        status = _row_get(row, "status", "active") or "active"
        purpose = _row_get(row, "purpose", None)
        notes = _row_get(row, "notes", "") or ""
        tags_json = _row_get(row, "tags_json", "[]") or "[]"
        created_at = _row_get(row, "created_at", None)
        parent_agent_id = _row_get(row, "parent_agent_id", None)
        spawn_reason = _row_get(row, "spawn_reason", None)
        
        try:
            tags = json.loads(tags_json) if tags_json else []
        except Exception:
            tags = []
        
        if dry_run:
            logger.info(f"[DRY RUN] Would migrate agent: {agent_id}")
            migrated += 1
            continue
        
        # Insert into core.agents
        pool = _get_postgres_pool(db)
        async with pool.acquire() as pg_conn:
            try:
                await pg_conn.execute(
                    """
                    INSERT INTO core.agents (
                        id, api_key, status, purpose, notes, tags,
                        created_at, parent_agent_id, spawn_reason
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        purpose = COALESCE(EXCLUDED.purpose, core.agents.purpose),
                        notes = COALESCE(EXCLUDED.notes, core.agents.notes),
                        tags = EXCLUDED.tags,
                        updated_at = NOW()
                    """,
                    agent_id,
                    api_key,
                    status,
                    purpose,
                    notes,
                    tags,
                    _parse_dt(created_at),
                    parent_agent_id,
                    spawn_reason,
                )
                migrated += 1
            except Exception as e:
                logger.error(f"Failed to migrate agent {agent_id}: {e}")
                skipped += 1
    
    conn.close()
    logger.info(f"Migrated {migrated} agents, skipped {skipped}")
    return {"migrated": migrated, "skipped": skipped}


async def migrate_sessions(
    db,
    sqlite_path: Path,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Migrate sessions from SQLite session_identities to core.agent_sessions."""
    logger.info("Phase 2: Migrating sessions...")
    
    if not sqlite_path.exists():
        logger.warning(f"SQLite DB not found: {sqlite_path}")
        return {"migrated": 0, "skipped": 0}
    
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    
    # Get session_identities
    sessions = conn.execute("SELECT * FROM session_identities").fetchall()
    
    migrated = 0
    skipped = 0
    
    for row in sessions:
        session_key = row["session_key"]
        agent_id = row["agent_id"]
        bound_at = _row_get(row, "bound_at", None)
        
        if dry_run:
            logger.info(f"[DRY RUN] Would migrate session: {session_key} -> {agent_id}")
            migrated += 1
            continue
        
        pool = _get_postgres_pool(db)
        async with pool.acquire() as pg_conn:
            try:
                await pg_conn.execute(
                    """
                    INSERT INTO core.agent_sessions (agent_id, session_key, bound_at, last_activity)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (agent_id) DO UPDATE SET
                        session_key = EXCLUDED.session_key,
                        bound_at = EXCLUDED.bound_at,
                        last_activity = NOW()
                    """,
                    agent_id,
                    session_key,
                    _parse_dt(bound_at) if bound_at else None,
                    _parse_dt(bound_at) if bound_at else datetime.now(),
                )
                migrated += 1
            except Exception as e:
                logger.error(f"Failed to migrate session {session_key}: {e}")
                skipped += 1
    
    conn.close()
    logger.info(f"Migrated {migrated} sessions, skipped {skipped}")
    return {"migrated": migrated, "skipped": skipped}


async def migrate_discoveries(
    kg_age: KnowledgeGraphAGE,
    knowledge_json_path: Path,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Migrate discoveries from JSON to AGE graph."""
    logger.info("Phase 3: Migrating discoveries to AGE graph...")
    
    if not knowledge_json_path.exists():
        logger.warning(f"Knowledge graph JSON not found: {knowledge_json_path}")
        return {"migrated": 0, "skipped": 0}
    
    with open(knowledge_json_path) as f:
        data = json.load(f)
    
    nodes = data.get("nodes", {})
    
    migrated = 0
    skipped = 0
    
    for node_id, node_data in nodes.items():
        try:
            discovery = DiscoveryNode.from_dict(node_data)
            
            if dry_run:
                logger.info(f"[DRY RUN] Would migrate discovery: {discovery.id}")
                migrated += 1
                continue
            
            await kg_age.add_discovery(discovery, auto_link_temporal=False)
            migrated += 1
            
            if migrated % 100 == 0:
                logger.info(f"Migrated {migrated} discoveries...")
        
        except Exception as e:
            logger.error(f"Failed to migrate discovery {node_id}: {e}")
            skipped += 1
    
    logger.info(f"Migrated {migrated} discoveries, skipped {skipped}")
    return {"migrated": migrated, "skipped": skipped}


async def create_age_graph(
    db,
    dry_run: bool = False,
) -> bool:
    """Create AGE graph if it doesn't exist."""
    logger.info("Phase 4: Creating AGE graph...")
    
    if dry_run:
        logger.info("[DRY RUN] Would create AGE graph")
        return True
    
    if not await db.graph_available():
        logger.error("AGE not available. Install Apache AGE extension.")
        return False
    
    graph_name = _get_age_graph_name(db)
    pool = _get_postgres_pool(db)
    try:
        async with pool.acquire() as conn:
            await conn.execute("LOAD 'age'")
            await conn.execute("SET search_path = ag_catalog, core, audit, public")
            await conn.execute(f"SELECT * FROM ag_catalog.create_graph('{graph_name}')")
        logger.info(f"Created AGE graph '{graph_name}'")
        return True
    except Exception as e:
        logger.warning(f"Graph may already exist: {e}")
        return True


async def main():
    parser = argparse.ArgumentParser(description="Migrate to PostgreSQL + AGE")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually migrate")
    parser.add_argument("--skip-graph", action="store_true", help="Skip AGE graph migration")
    parser.add_argument("--sqlite-path", type=Path, default=Path("data/governance.db"))
    parser.add_argument("--knowledge-json", type=Path, default=Path("data/knowledge_graph.json"))
    
    args = parser.parse_args()
    
    logger.info("Starting migration to PostgreSQL + AGE...")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Skip graph: {args.skip_graph}")
    
    # Initialize database
    db = get_db()
    await db.init()
    
    # Phase 1: Migrate agents
    agent_stats = await migrate_agents(db, args.sqlite_path, args.dry_run)
    
    # Phase 2: Migrate sessions
    session_stats = await migrate_sessions(db, args.sqlite_path, args.dry_run)
    
    # Phase 3: Create AGE graph
    if not args.skip_graph:
        graph_created = await create_age_graph(db, args.dry_run)
        
        if graph_created:
            # Phase 4: Migrate discoveries
            kg_age = KnowledgeGraphAGE()
            discovery_stats = await migrate_discoveries(
                kg_age,
                args.knowledge_json,
                args.dry_run,
            )
        else:
            discovery_stats = {"migrated": 0, "skipped": 0}
    else:
        discovery_stats = {"migrated": 0, "skipped": 0}
    
    # Summary
    logger.info("=" * 60)
    logger.info("Migration Summary:")
    logger.info(f"  Agents: {agent_stats['migrated']} migrated, {agent_stats['skipped']} skipped")
    logger.info(f"  Sessions: {session_stats['migrated']} migrated, {session_stats['skipped']} skipped")
    logger.info(f"  Discoveries: {discovery_stats['migrated']} migrated, {discovery_stats['skipped']} skipped")
    logger.info("=" * 60)
    
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())

