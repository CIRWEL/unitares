#!/usr/bin/env python3
"""
Dialectic Session Consolidation Script

Ensures all dialectic sessions are properly stored in both SQLite (primary) and JSON (backup).
This script should be run periodically or after any suspected data loss.

Usage:
    python scripts/consolidate_dialectic.py [--dry-run] [--export-all]
"""

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
JSON_DIR = DATA_DIR / "dialectic_sessions"
DB_PATH = DATA_DIR / "governance.db"


def load_json_sessions() -> Dict[str, Dict]:
    """Load all sessions from JSON files."""
    sessions = {}
    if not JSON_DIR.exists():
        JSON_DIR.mkdir(parents=True, exist_ok=True)
        return sessions

    for f in JSON_DIR.glob("*.json"):
        try:
            with open(f) as fp:
                data = json.load(fp)
                sid = data.get("session_id", f.stem)
                sessions[sid] = data
        except Exception as e:
            print(f"⚠️ Error reading {f.name}: {e}")

    return sessions


def load_sqlite_sessions() -> Dict[str, Dict]:
    """Load all sessions from SQLite with their messages."""
    sessions = {}

    if not DB_PATH.exists():
        print(f"⚠️ Database not found: {DB_PATH}")
        return sessions

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get all sessions
    c.execute("""
        SELECT session_id, paused_agent_id, reviewer_agent_id, phase, status,
               created_at, updated_at, topic, session_type, resolution_json,
               paused_agent_state_json
        FROM dialectic_sessions
    """)

    for row in c.fetchall():
        sid = row["session_id"]
        sessions[sid] = {
            "session_id": sid,
            "paused_agent_id": row["paused_agent_id"],
            "reviewer_agent_id": row["reviewer_agent_id"],
            "phase": row["phase"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "topic": row["topic"],
            "session_type": row["session_type"],
            "transcript": [],
            "resolution": json.loads(row["resolution_json"]) if row["resolution_json"] else None,
            "paused_agent_state": json.loads(row["paused_agent_state_json"]) if row["paused_agent_state_json"] else {},
        }

    # Get all messages
    c.execute("""
        SELECT session_id, agent_id, message_type, timestamp, reasoning,
               root_cause, proposed_conditions_json, observed_metrics_json,
               concerns_json, agrees
        FROM dialectic_messages
        ORDER BY timestamp ASC
    """)

    for row in c.fetchall():
        sid = row["session_id"]
        if sid in sessions:
            msg = {
                "phase": row["message_type"],
                "agent_id": row["agent_id"],
                "timestamp": row["timestamp"],
                "reasoning": row["reasoning"],
                "root_cause": row["root_cause"],
                "proposed_conditions": json.loads(row["proposed_conditions_json"]) if row["proposed_conditions_json"] else [],
                "observed_metrics": json.loads(row["observed_metrics_json"]) if row["observed_metrics_json"] else None,
                "concerns": json.loads(row["concerns_json"]) if row["concerns_json"] else None,
                "agrees": bool(row["agrees"]) if row["agrees"] is not None else None,
            }
            sessions[sid]["transcript"].append(msg)

    conn.close()
    return sessions


def export_session_to_json(session: Dict, force: bool = False) -> bool:
    """Export a session to JSON file."""
    sid = session["session_id"]
    json_path = JSON_DIR / f"{sid}.json"

    if json_path.exists() and not force:
        # Check if existing has more data
        with open(json_path) as f:
            existing = json.load(f)
        existing_msgs = len(existing.get("transcript", []))
        new_msgs = len(session.get("transcript", []))

        if existing_msgs >= new_msgs:
            return False  # Existing has same or more data

    JSON_DIR.mkdir(parents=True, exist_ok=True)

    # Convert to standard JSON format
    export_data = {
        "session_id": session["session_id"],
        "paused_agent_id": session.get("paused_agent_id"),
        "reviewer_agent_id": session.get("reviewer_agent_id"),
        "phase": session.get("phase"),
        "synthesis_round": session.get("synthesis_round", 0),
        "transcript": session.get("transcript", []),
        "resolution": session.get("resolution"),
        "created_at": session.get("created_at"),
        "discovery_id": session.get("discovery_id"),
        "dispute_type": session.get("dispute_type"),
        "session_type": session.get("session_type"),
        "topic": session.get("topic"),
        "paused_agent_state": session.get("paused_agent_state", {}),
    }

    with open(json_path, 'w') as f:
        json.dump(export_data, f, indent=2)

    return True


def sync_json_to_sqlite(session: Dict, conn: sqlite3.Connection) -> int:
    """Sync JSON messages to SQLite if missing. Returns count of messages added."""
    sid = session["session_id"]
    c = conn.cursor()

    # Check if session exists
    c.execute("SELECT session_id FROM dialectic_sessions WHERE session_id = ?", (sid,))
    if not c.fetchone():
        # Create session
        c.execute("""
            INSERT INTO dialectic_sessions
            (session_id, paused_agent_id, reviewer_agent_id, phase, status,
             created_at, topic, session_type, paused_agent_state_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sid,
            session.get("paused_agent_id"),
            session.get("reviewer_agent_id"),
            session.get("phase", "thesis"),
            "active" if session.get("phase") not in ("resolved", "failed") else session.get("phase"),
            session.get("created_at"),
            session.get("topic"),
            session.get("session_type", "review"),
            json.dumps(session.get("paused_agent_state", {})),
        ))

    # Get existing message timestamps
    c.execute("SELECT timestamp FROM dialectic_messages WHERE session_id = ?", (sid,))
    existing_timestamps = {row[0] for row in c.fetchall()}

    # Add missing messages
    added = 0
    for msg in session.get("transcript", []):
        if msg.get("timestamp") not in existing_timestamps:
            c.execute("""
                INSERT INTO dialectic_messages
                (session_id, agent_id, message_type, timestamp, reasoning,
                 root_cause, proposed_conditions_json, observed_metrics_json,
                 concerns_json, agrees)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sid,
                msg.get("agent_id"),
                msg.get("phase"),
                msg.get("timestamp"),
                msg.get("reasoning"),
                msg.get("root_cause"),
                json.dumps(msg.get("proposed_conditions", [])),
                json.dumps(msg.get("observed_metrics")) if msg.get("observed_metrics") else None,
                json.dumps(msg.get("concerns")) if msg.get("concerns") else None,
                1 if msg.get("agrees") else 0 if msg.get("agrees") is False else None,
            ))
            added += 1

    return added


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Consolidate dialectic sessions")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--export-all", action="store_true", help="Export all SQLite sessions to JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    print("=" * 70)
    print("DIALECTIC SESSION CONSOLIDATION")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Load from both sources
    json_sessions = load_json_sessions()
    sqlite_sessions = load_sqlite_sessions()

    print(f"JSON sessions: {len(json_sessions)}")
    print(f"SQLite sessions: {len(sqlite_sessions)}")

    all_sids = set(json_sessions.keys()) | set(sqlite_sessions.keys())
    print(f"Total unique sessions: {len(all_sids)}")
    print()

    # Statistics
    exported_count = 0
    synced_count = 0
    messages_added = 0

    # Open DB connection for syncing
    conn = None
    if not args.dry_run:
        conn = sqlite3.connect(DB_PATH)

    # Process each session
    for sid in sorted(all_sids):
        json_data = json_sessions.get(sid)
        sqlite_data = sqlite_sessions.get(sid)

        json_msgs = len(json_data.get("transcript", [])) if json_data else 0
        sqlite_msgs = len(sqlite_data.get("transcript", [])) if sqlite_data else 0

        if args.verbose:
            print(f"  {sid}: JSON={json_msgs}, SQLite={sqlite_msgs}")

        # Export SQLite to JSON if missing or has more data
        if sqlite_data and (args.export_all or not json_data or sqlite_msgs > json_msgs):
            if args.dry_run:
                print(f"  Would export {sid} to JSON ({sqlite_msgs} messages)")
            else:
                if export_session_to_json(sqlite_data, force=args.export_all):
                    exported_count += 1
                    if args.verbose:
                        print(f"  ✓ Exported {sid} to JSON")

        # Sync JSON to SQLite if JSON has data SQLite is missing
        if json_data and json_msgs > sqlite_msgs:
            if args.dry_run:
                print(f"  Would sync {sid} to SQLite (+{json_msgs - sqlite_msgs} messages)")
            else:
                added = sync_json_to_sqlite(json_data, conn)
                if added > 0:
                    synced_count += 1
                    messages_added += added
                    if args.verbose:
                        print(f"  ✓ Synced {sid} to SQLite (+{added} messages)")

    if conn:
        conn.commit()
        conn.close()

    # Summary
    print()
    print("-" * 70)
    print("SUMMARY")
    print("-" * 70)

    if args.dry_run:
        print("(Dry run - no changes made)")
    else:
        print(f"Sessions exported to JSON: {exported_count}")
        print(f"Sessions synced to SQLite: {synced_count}")
        print(f"Messages added to SQLite: {messages_added}")

    # Verify final state
    print()
    print("Final verification:")
    json_sessions = load_json_sessions()
    sqlite_sessions = load_sqlite_sessions()

    missing_json = set(sqlite_sessions.keys()) - set(json_sessions.keys())
    missing_sqlite = set(json_sessions.keys()) - set(sqlite_sessions.keys())

    if missing_json:
        print(f"  ⚠️ Sessions missing JSON backup: {len(missing_json)}")
    if missing_sqlite:
        print(f"  ⚠️ Sessions missing from SQLite: {len(missing_sqlite)}")
    if not missing_json and not missing_sqlite:
        print(f"  ✓ All {len(sqlite_sessions)} sessions have both JSON and SQLite records")

    # Check for empty sessions
    empty = [sid for sid, s in sqlite_sessions.items() if len(s.get("transcript", [])) == 0]
    if empty:
        print(f"  ⚠️ Empty sessions (no messages): {len(empty)}")
        for sid in empty[:5]:
            s = sqlite_sessions[sid]
            print(f"      {sid}: {s.get('topic', 'no topic')}")

    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
