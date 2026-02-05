#!/usr/bin/env python3
"""
Migrate dialectic sessions from SQLite to PostgreSQL.

This script:
1. Reads all sessions and messages from SQLite (data/governance.db)
2. Inserts them into PostgreSQL (core.dialectic_sessions, core.dialectic_messages)
3. Handles conflicts gracefully (skips existing records)

Usage:
    python scripts/migrate_dialectic_to_postgres.py [--dry-run]

Environment:
    DB_POSTGRES_URL - PostgreSQL connection string
    DB_BACKEND=postgres
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def migrate_dialectic_data(dry_run: bool = True):
    """Migrate dialectic data from SQLite to PostgreSQL."""

    # SQLite source
    sqlite_path = Path(__file__).parent.parent / "data" / "governance.db"

    if not sqlite_path.exists():
        print(f"SQLite database not found: {sqlite_path}")
        print("Nothing to migrate.")
        return

    print(f"=== Dialectic Migration: SQLite → PostgreSQL ===")
    print(f"Source: {sqlite_path}")
    print(f"Dry run: {dry_run}")
    print()

    # Connect to SQLite
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row

    # Check if dialectic tables exist in SQLite
    cursor = sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dialectic_sessions'"
    )
    if not cursor.fetchone():
        print("No dialectic_sessions table in SQLite. Nothing to migrate.")
        sqlite_conn.close()
        return

    # Get all sessions from SQLite
    cursor = sqlite_conn.execute("SELECT * FROM dialectic_sessions ORDER BY created_at")
    sessions = [dict(row) for row in cursor.fetchall()]
    print(f"Found {len(sessions)} sessions in SQLite")

    # Get all messages from SQLite
    cursor = sqlite_conn.execute("SELECT * FROM dialectic_messages ORDER BY id")
    messages = [dict(row) for row in cursor.fetchall()]
    print(f"Found {len(messages)} messages in SQLite")
    print()

    if dry_run:
        print("DRY RUN - No changes will be made")
        print()
        print("Sessions to migrate:")
        for s in sessions[:10]:
            print(f"  {s['session_id'][:16]}... status={s.get('status', s.get('phase', '?'))} agent={s['paused_agent_id']}")
        if len(sessions) > 10:
            print(f"  ... and {len(sessions) - 10} more")
        print()
        print("Messages to migrate:")
        for m in messages[:10]:
            print(f"  session={m['session_id'][:16]}... type={m['message_type']} agent={m['agent_id']}")
        if len(messages) > 10:
            print(f"  ... and {len(messages) - 10} more")
        sqlite_conn.close()
        return

    # Connect to PostgreSQL
    from src.db import get_db
    db = get_db()
    await db.init()

    async with db._pool.acquire() as conn:
        # Migrate sessions
        sessions_migrated = 0
        sessions_skipped = 0

        for session in sessions:
            try:
                # Map SQLite fields to PostgreSQL schema
                session_id = session["session_id"]

                # Check if already exists (actual schema uses session_id as PK)
                existing = await conn.fetchval(
                    "SELECT 1 FROM core.dialectic_sessions WHERE session_id = $1",
                    session_id
                )

                if existing:
                    sessions_skipped += 1
                    continue

                # Parse JSON fields (keep as strings for JSONB)
                paused_state = session.get("paused_agent_state_json")
                resolution = session.get("resolution_json")

                # Handle phase/status fields
                phase = session.get("phase", "thesis")
                status = session.get("status", "active")

                # Parse timestamps
                created_at = session.get("created_at")
                updated_at = session.get("updated_at")

                # Actual schema uses session_id, phase, status, and _json suffix columns
                await conn.execute("""
                    INSERT INTO core.dialectic_sessions (
                        session_id, paused_agent_id, reviewer_agent_id,
                        phase, status, session_type, topic,
                        reason, discovery_id, dispute_type,
                        max_synthesis_rounds, synthesis_round, paused_agent_state_json,
                        resolution_json, created_at, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """,
                    session_id,
                    session.get("paused_agent_id"),
                    session.get("reviewer_agent_id"),
                    phase,
                    status,
                    session.get("session_type"),
                    session.get("topic"),
                    session.get("reason"),
                    session.get("discovery_id"),
                    session.get("dispute_type"),
                    session.get("max_synthesis_rounds"),
                    session.get("synthesis_round", 0),
                    paused_state,
                    resolution,
                    datetime.fromisoformat(created_at) if created_at else None,
                    datetime.fromisoformat(updated_at) if updated_at else None,
                )
                sessions_migrated += 1

            except Exception as e:
                print(f"Error migrating session {session.get('session_id', '?')}: {e}")

        print(f"Sessions: {sessions_migrated} migrated, {sessions_skipped} skipped (already exist)")

        # Migrate messages
        messages_migrated = 0
        messages_skipped = 0

        for msg in messages:
            try:
                session_id = msg["session_id"]

                # Check if session exists in PostgreSQL (required for FK)
                session_exists = await conn.fetchval(
                    "SELECT 1 FROM core.dialectic_sessions WHERE session_id = $1",
                    session_id
                )

                if not session_exists:
                    messages_skipped += 1
                    continue

                # Parse timestamp
                timestamp = msg.get("timestamp")

                await conn.execute("""
                    INSERT INTO core.dialectic_messages (
                        session_id, agent_id, message_type, timestamp,
                        root_cause, proposed_conditions, reasoning,
                        observed_metrics, concerns, agrees, signature
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                    session_id,
                    msg.get("agent_id"),
                    msg.get("message_type"),
                    datetime.fromisoformat(timestamp) if timestamp else datetime.now(),
                    msg.get("root_cause"),
                    msg.get("proposed_conditions_json"),
                    msg.get("reasoning"),
                    msg.get("observed_metrics_json"),
                    msg.get("concerns_json"),
                    bool(msg.get("agrees")) if msg.get("agrees") is not None else None,
                    msg.get("signature"),
                )
                messages_migrated += 1

            except Exception as e:
                if "duplicate" not in str(e).lower():
                    print(f"Error migrating message: {e}")
                messages_skipped += 1

        print(f"Messages: {messages_migrated} migrated, {messages_skipped} skipped")

    sqlite_conn.close()
    print()
    print("Migration complete!")

    # Verify
    async with db._pool.acquire() as conn:
        pg_sessions = await conn.fetchval("SELECT COUNT(*) FROM core.dialectic_sessions")
        pg_messages = await conn.fetchval("SELECT COUNT(*) FROM core.dialectic_messages")
        print(f"PostgreSQL now has: {pg_sessions} sessions, {pg_messages} messages")


async def main():
    parser = argparse.ArgumentParser(description='Migrate dialectic data from SQLite to PostgreSQL')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Show what would be migrated without making changes (default)')
    parser.add_argument('--execute', action='store_true',
                        help='Actually perform the migration')
    args = parser.parse_args()

    # Check environment
    if os.getenv('DB_BACKEND', '').lower() != 'postgres':
        print("Warning: DB_BACKEND is not 'postgres'")
        print("Set DB_BACKEND=postgres and DB_POSTGRES_URL to continue")
        if not args.dry_run and not args.execute:
            sys.exit(1)

    dry_run = not args.execute
    await migrate_dialectic_data(dry_run=dry_run)


if __name__ == '__main__':
    asyncio.run(main())
