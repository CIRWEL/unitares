#!/usr/bin/env python3
"""
Migrate agent_metadata SQLite schema to match sqlite_backend.py expectations.

Adds missing columns:
- updated_at (copy from last_update)
- disabled_at (null)
- metadata_json (build from existing fields)

Run from project root:
    python scripts/migrate_agent_metadata_schema.py
"""

import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "governance.db"


def migrate():
    print(f"Migrating: {DB_PATH}")

    if not DB_PATH.exists():
        print("Database does not exist, nothing to migrate")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Check current columns
    columns = {row['name'] for row in conn.execute("PRAGMA table_info(agent_metadata)")}
    print(f"Current columns: {len(columns)}")

    # Track what we add
    added = []

    # 1. Add updated_at if missing (copy from last_update)
    if 'updated_at' not in columns:
        print("Adding 'updated_at' column...")
        conn.execute("ALTER TABLE agent_metadata ADD COLUMN updated_at TEXT")
        conn.execute("UPDATE agent_metadata SET updated_at = last_update WHERE updated_at IS NULL")
        added.append('updated_at')

    # 2. Add disabled_at if missing
    if 'disabled_at' not in columns:
        print("Adding 'disabled_at' column...")
        conn.execute("ALTER TABLE agent_metadata ADD COLUMN disabled_at TEXT")
        # Set disabled_at for archived agents
        conn.execute("""
            UPDATE agent_metadata
            SET disabled_at = archived_at
            WHERE status = 'archived' AND archived_at IS NOT NULL AND disabled_at IS NULL
        """)
        added.append('disabled_at')

    # 3. Add metadata_json if missing (build from tags_json, notes, purpose)
    if 'metadata_json' not in columns:
        print("Adding 'metadata_json' column...")
        conn.execute("ALTER TABLE agent_metadata ADD COLUMN metadata_json TEXT DEFAULT '{}'")

        # Populate metadata_json from existing fields
        rows = conn.execute("""
            SELECT agent_id, tags_json, notes, purpose, health_status, label
            FROM agent_metadata
        """).fetchall()

        for row in rows:
            metadata = {}

            # Parse tags
            if row['tags_json']:
                try:
                    metadata['tags'] = json.loads(row['tags_json'])
                except:
                    metadata['tags'] = []
            else:
                metadata['tags'] = []

            # Add other fields
            if row['notes']:
                metadata['notes'] = row['notes']
            if row['purpose']:
                metadata['purpose'] = row['purpose']
            if row['health_status']:
                metadata['health_status'] = row['health_status']
            if row['label']:
                metadata['label'] = row['label']

            conn.execute(
                "UPDATE agent_metadata SET metadata_json = ? WHERE agent_id = ?",
                (json.dumps(metadata), row['agent_id'])
            )

        added.append('metadata_json')

    # 4. Ensure api_key column has NOT NULL default (fix existing nulls)
    null_count = conn.execute("SELECT COUNT(*) FROM agent_metadata WHERE api_key IS NULL").fetchone()[0]
    if null_count > 0:
        print(f"Fixing {null_count} rows with NULL api_key...")
        conn.execute("UPDATE agent_metadata SET api_key = '' WHERE api_key IS NULL")
        added.append('api_key_nulls_fixed')

    conn.commit()

    # Verify
    new_columns = {row['name'] for row in conn.execute("PRAGMA table_info(agent_metadata)")}
    print(f"\nNew columns: {len(new_columns)}")

    if added:
        print(f"\nAdded: {', '.join(added)}")
    else:
        print("\nNo changes needed - schema is up to date")

    # Show sample
    sample = conn.execute("""
        SELECT agent_id, status, updated_at, disabled_at,
               substr(metadata_json, 1, 100) as metadata_preview
        FROM agent_metadata
        LIMIT 3
    """).fetchall()

    print("\nSample data:")
    for row in sample:
        print(f"  {row['agent_id'][:30]}... | {row['status']} | {row['updated_at']} | {row['metadata_preview']}")

    conn.close()
    print("\nMigration complete!")


if __name__ == "__main__":
    migrate()
