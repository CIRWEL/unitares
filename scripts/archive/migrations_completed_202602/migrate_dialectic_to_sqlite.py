#!/usr/bin/env python3
"""
Migrate dialectic sessions from JSON files to SQLite.

Usage:
    python scripts/migrate_dialectic_to_sqlite.py [--dry-run] [--verify]

Options:
    --dry-run   Show what would be migrated without writing to DB
    --verify    After migration, verify data integrity
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.dialectic_db import DialecticDB
from src.dialectic_protocol import DialecticPhase


def load_json_sessions(sessions_dir: Path) -> list:
    """Load all JSON session files."""
    sessions = []
    if not sessions_dir.exists():
        print(f"Sessions directory not found: {sessions_dir}")
        return sessions

    for session_file in sorted(sessions_dir.glob("*.json")):
        try:
            with open(session_file, 'r') as f:
                data = json.load(f)
                data['_source_file'] = session_file.name
                sessions.append(data)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Warning: Could not load {session_file.name}: {e}")
            continue

    return sessions


def migrate_session(db: DialecticDB, session_data: dict, dry_run: bool = False) -> bool:
    """Migrate a single session to SQLite."""
    session_id = session_data.get('session_id')
    if not session_id:
        print(f"  Skipping session without ID: {session_data.get('_source_file')}")
        return False

    # Extract session fields
    paused_agent_id = session_data.get('paused_agent_id', 'unknown')
    reviewer_agent_id = session_data.get('reviewer_agent_id')
    phase = session_data.get('phase', 'awaiting_thesis')
    status = session_data.get('status', 'active')
    created_at = session_data.get('created_at', datetime.now().isoformat())
    reason = session_data.get('reason')
    discovery_id = session_data.get('discovery_id')
    dispute_type = session_data.get('dispute_type')
    paused_agent_state = session_data.get('paused_agent_state')
    resolution = session_data.get('resolution')

    # Map status values
    if status == 'resolved' or phase == 'resolved':
        status = 'resolved'
    elif status in ('failed', 'escalated'):
        status = status
    else:
        status = 'active'

    if dry_run:
        print(f"  [DRY RUN] Would migrate: {session_id[:16]}...")
        print(f"            Paused: {paused_agent_id}, Reviewer: {reviewer_agent_id}")
        print(f"            Phase: {phase}, Status: {status}")
        messages = session_data.get('messages', [])
        print(f"            Messages: {len(messages)}")
        return True

    # Create session in DB
    conn = db._get_connection()
    try:
        # Check if session already exists
        cursor = conn.execute(
            "SELECT 1 FROM dialectic_sessions WHERE session_id = ?",
            (session_id,)
        )
        if cursor.fetchone():
            print(f"  Session {session_id[:16]}... already exists, skipping")
            return False

        # Insert session
        conn.execute("""
            INSERT INTO dialectic_sessions (
                session_id, paused_agent_id, reviewer_agent_id,
                phase, status, created_at, updated_at,
                reason, discovery_id, dispute_type,
                paused_agent_state_json, resolution_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            paused_agent_id,
            reviewer_agent_id,
            phase,
            status,
            created_at,
            session_data.get('updated_at', created_at),
            reason,
            discovery_id,
            dispute_type,
            json.dumps(paused_agent_state) if paused_agent_state else None,
            json.dumps(resolution) if resolution else None,
        ))

        # Migrate messages
        messages = session_data.get('messages', [])
        for msg in messages:
            msg_type = msg.get('type', 'unknown')
            # Map message types
            if msg_type in ('thesis', 'antithesis', 'synthesis'):
                pass
            elif 'thesis' in str(msg).lower():
                msg_type = 'thesis'
            elif 'antithesis' in str(msg).lower():
                msg_type = 'antithesis'
            elif 'synthesis' in str(msg).lower():
                msg_type = 'synthesis'
            else:
                msg_type = 'thesis'  # Default

            conn.execute("""
                INSERT INTO dialectic_messages (
                    session_id, agent_id, message_type, timestamp,
                    root_cause, proposed_conditions_json, reasoning,
                    observed_metrics_json, concerns_json, agrees, signature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                msg.get('agent_id', paused_agent_id if msg_type == 'thesis' else reviewer_agent_id),
                msg_type,
                msg.get('timestamp', created_at),
                msg.get('root_cause'),
                json.dumps(msg.get('proposed_conditions')) if msg.get('proposed_conditions') else None,
                msg.get('reasoning'),
                json.dumps(msg.get('observed_metrics')) if msg.get('observed_metrics') else None,
                json.dumps(msg.get('concerns')) if msg.get('concerns') else None,
                1 if msg.get('agrees') else (0 if msg.get('agrees') is False else None),
                msg.get('signature'),
            ))

        conn.commit()
        return True
    except Exception as e:
        print(f"  Error migrating {session_id[:16]}...: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def migrate(dry_run: bool = False, verify: bool = False):
    """Run the migration."""
    sessions_dir = project_root / "data" / "dialectic_sessions"
    db_path = project_root / "data" / "dialectic.db"

    print(f"Loading JSON sessions from: {sessions_dir}")
    sessions = load_json_sessions(sessions_dir)
    print(f"Found {len(sessions)} session files")

    if not sessions:
        print("No sessions to migrate")
        return

    if dry_run:
        print("\n=== DRY RUN - No changes will be made ===\n")

    # Backup existing DB if exists and not dry run
    if not dry_run and db_path.exists():
        backup_path = db_path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        print(f"Backing up existing DB to: {backup_path}")
        import shutil
        shutil.copy(db_path, backup_path)

    # Initialize DB
    db = DialecticDB(db_path)

    # Migrate sessions
    success = 0
    failed = 0
    skipped = 0

    for session_data in sessions:
        result = migrate_session(db, session_data, dry_run)
        if result:
            success += 1
        elif result is False:
            # Could be skipped (already exists) or failed
            if 'already exists' in str(result):
                skipped += 1
            else:
                failed += 1

    print(f"\n=== Migration {'Preview' if dry_run else 'Complete'} ===")
    print(f"Success: {success}")
    print(f"Skipped: {skipped}")
    print(f"Failed: {failed}")

    if verify and not dry_run:
        print("\n=== Verifying Migration ===")
        stats = db.get_stats()
        print(f"Total sessions in DB: {stats['total_sessions']}")
        print(f"Total messages in DB: {stats['total_messages']}")
        print(f"By status: {stats['by_status']}")
        print(f"By phase: {stats['by_phase']}")

        # Spot check
        print("\n=== Spot Check ===")
        active = db.get_active_sessions(limit=3)
        print(f"Active sessions: {len(active)}")
        for s in active:
            print(f"  {s['session_id'][:16]}... - {s['paused_agent_id']} ({s['phase']})")

    print(f"\n✓ Migration {'preview' if dry_run else 'complete'}! DB at: {db_path}")


def main():
    parser = argparse.ArgumentParser(description="Migrate dialectic sessions from JSON to SQLite")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated")
    parser.add_argument("--verify", action="store_true", help="Verify migration after completion")
    args = parser.parse_args()

    migrate(dry_run=args.dry_run, verify=args.verify)


if __name__ == "__main__":
    main()
