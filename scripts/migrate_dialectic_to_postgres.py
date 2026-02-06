#!/usr/bin/env python3
"""
Migrate Dialectic Sessions from SQLite to PostgreSQL

Handles:
- Session deduplication (skips if session_id already exists)
- JSON field conversion (SQLite strings to PostgreSQL jsonb)
- Column name mapping (proposed_conditions_json -> proposed_conditions)
"""

import sqlite3
import asyncio
import asyncpg
import json
from datetime import datetime
from pathlib import Path


def parse_timestamp(ts_str):
    """Parse ISO timestamp string to datetime object."""
    if not ts_str:
        return datetime.now()
    try:
        # Handle various ISO formats
        if 'T' in ts_str:
            return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return datetime.now()


SQLITE_PATH = Path(__file__).parent.parent / "data" / "governance.db"
POSTGRES_URL = "postgresql://postgres:postgres@localhost:5432/governance"


async def migrate():
    # Connect to both databases
    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    sqlite_conn.row_factory = sqlite3.Row

    pg_conn = await asyncpg.connect(POSTGRES_URL)

    try:
        # Get existing PostgreSQL session IDs
        pg_sessions = await pg_conn.fetch("SELECT session_id FROM core.dialectic_sessions")
        existing_session_ids = {r["session_id"] for r in pg_sessions}
        print(f"PostgreSQL has {len(existing_session_ids)} existing sessions")

        # Get all SQLite sessions
        sqlite_sessions = sqlite_conn.execute("""
            SELECT * FROM dialectic_sessions ORDER BY created_at ASC
        """).fetchall()
        print(f"SQLite has {len(sqlite_sessions)} sessions")

        # Migrate sessions
        sessions_migrated = 0
        sessions_skipped = 0

        for row in sqlite_sessions:
            session = dict(row)
            session_id = session["session_id"]

            if session_id in existing_session_ids:
                sessions_skipped += 1
                continue

            # Parse JSON fields
            paused_agent_state = None
            if session.get("paused_agent_state_json"):
                try:
                    paused_agent_state = json.loads(session["paused_agent_state_json"])
                except json.JSONDecodeError:
                    paused_agent_state = None

            resolution = None
            if session.get("resolution_json"):
                try:
                    resolution = json.loads(session["resolution_json"])
                except json.JSONDecodeError:
                    resolution = None

            # Convert timestamp strings to datetime objects
            created_at = parse_timestamp(session["created_at"])
            updated_at = parse_timestamp(session.get("updated_at") or session["created_at"])

            try:
                await pg_conn.execute("""
                    INSERT INTO core.dialectic_sessions (
                        session_id, paused_agent_id, reviewer_agent_id,
                        phase, status, created_at, updated_at,
                        reason, discovery_id, dispute_type,
                        session_type, topic, max_synthesis_rounds, synthesis_round,
                        paused_agent_state_json, resolution_json
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """,
                    session_id,
                    session["paused_agent_id"],
                    session.get("reviewer_agent_id"),
                    session["phase"],
                    session["status"],
                    created_at,
                    updated_at,
                    session.get("reason"),
                    session.get("discovery_id"),
                    session.get("dispute_type"),
                    session.get("session_type"),
                    session.get("topic"),
                    session.get("max_synthesis_rounds"),
                    session.get("synthesis_round"),
                    json.dumps(paused_agent_state) if paused_agent_state else None,
                    json.dumps(resolution) if resolution else None,
                )
                sessions_migrated += 1
                existing_session_ids.add(session_id)  # Track for message migration
            except Exception as e:
                print(f"Error migrating session {session_id}: {e}")

        print(f"Sessions: migrated {sessions_migrated}, skipped {sessions_skipped}")

        # Get existing PostgreSQL message session_ids to know which messages to migrate
        # Get all messages for sessions that now exist in PostgreSQL
        pg_messages = await pg_conn.fetch("""
            SELECT session_id, agent_id, message_type FROM core.dialectic_messages
        """)
        existing_messages = {
            (r["session_id"], r["agent_id"], r["message_type"])
            for r in pg_messages
        }
        print(f"PostgreSQL has {len(existing_messages)} existing messages")

        # Get all SQLite messages
        sqlite_messages = sqlite_conn.execute("""
            SELECT * FROM dialectic_messages ORDER BY id ASC
        """).fetchall()
        print(f"SQLite has {len(sqlite_messages)} messages")

        # Migrate messages
        messages_migrated = 0
        messages_skipped = 0

        for row in sqlite_messages:
            msg = dict(row)
            session_id = msg["session_id"]

            # Only migrate messages for sessions that exist in PostgreSQL
            if session_id not in existing_session_ids:
                messages_skipped += 1
                continue

            # Check for duplicate
            msg_key = (session_id, msg["agent_id"], msg["message_type"])
            if msg_key in existing_messages:
                messages_skipped += 1
                continue

            # Parse JSON fields
            proposed_conditions = None
            if msg.get("proposed_conditions_json"):
                try:
                    proposed_conditions = json.loads(msg["proposed_conditions_json"])
                except json.JSONDecodeError:
                    proposed_conditions = None

            observed_metrics = None
            if msg.get("observed_metrics_json"):
                try:
                    observed_metrics = json.loads(msg["observed_metrics_json"])
                except json.JSONDecodeError:
                    observed_metrics = None

            concerns = None
            if msg.get("concerns_json"):
                try:
                    concerns = json.loads(msg["concerns_json"])
                except json.JSONDecodeError:
                    concerns = None

            # Convert agrees (0/1/NULL) to boolean
            agrees = None
            if msg.get("agrees") is not None:
                agrees = bool(msg["agrees"])

            try:
                await pg_conn.execute("""
                    INSERT INTO core.dialectic_messages (
                        session_id, agent_id, message_type, timestamp,
                        root_cause, proposed_conditions, reasoning,
                        observed_metrics, concerns, agrees, signature
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                    session_id,
                    msg["agent_id"],
                    msg["message_type"],
                    parse_timestamp(msg["timestamp"]),
                    msg.get("root_cause"),
                    json.dumps(proposed_conditions) if proposed_conditions else None,
                    msg.get("reasoning"),
                    json.dumps(observed_metrics) if observed_metrics else None,
                    json.dumps(concerns) if concerns else None,
                    agrees,
                    msg.get("signature"),
                )
                messages_migrated += 1
                existing_messages.add(msg_key)
            except Exception as e:
                print(f"Error migrating message for session {session_id}: {e}")

        print(f"Messages: migrated {messages_migrated}, skipped {messages_skipped}")

        # Final counts
        final_sess = await pg_conn.fetchval("SELECT COUNT(*) FROM core.dialectic_sessions")
        final_msgs = await pg_conn.fetchval("SELECT COUNT(*) FROM core.dialectic_messages")
        print(f"\nFinal PostgreSQL counts:")
        print(f"  Sessions: {final_sess}")
        print(f"  Messages: {final_msgs}")

    finally:
        sqlite_conn.close()
        await pg_conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
