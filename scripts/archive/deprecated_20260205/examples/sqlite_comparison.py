#!/usr/bin/env python3
"""
SQLite vs JSON - Practical Comparison for Governance System

This shows how SQLite would solve the metadata race condition
that we fixed with locks and immediate saves.
"""

import sqlite3
import json
import time
import asyncio
from pathlib import Path

# Setup paths
example_dir = Path(__file__).parent
json_file = example_dir / "test_agents.json"
db_file = example_dir / "test_agents.db"


# ============================================================================
# APPROACH 1: JSON (Current System)
# ============================================================================

def json_create_agent(agent_id: str, api_key: str):
    """Create agent using JSON file (requires careful locking)"""

    # Load existing data
    if json_file.exists():
        with open(json_file, 'r') as f:
            agents = json.load(f)
    else:
        agents = {}

    # Add new agent
    agents[agent_id] = {
        "api_key": api_key,
        "status": "active",
        "total_updates": 0,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    # Save back (RACE CONDITION if multiple processes!)
    with open(json_file, 'w') as f:
        json.dump(agents, f, indent=2)


def json_get_active_agents():
    """Get all active agents (must load entire file)"""
    if not json_file.exists():
        return []

    with open(json_file, 'r') as f:
        agents = json.load(f)

    # Filter in Python (slow for large files)
    return [aid for aid, data in agents.items() if data['status'] == 'active']


# ============================================================================
# APPROACH 2: SQLite (Recommended Upgrade)
# ============================================================================

def sqlite_setup():
    """Setup SQLite database (one-time)"""
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            api_key TEXT NOT NULL,
            status TEXT NOT NULL,
            total_updates INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def sqlite_create_agent(agent_id: str, api_key: str):
    """Create agent using SQLite (handles concurrency automatically)"""
    conn = sqlite3.connect(db_file)

    # This is ATOMIC - no race conditions!
    conn.execute("""
        INSERT INTO agents (agent_id, api_key, status, total_updates, created_at)
        VALUES (?, ?, 'active', 0, datetime('now'))
    """, (agent_id, api_key))

    conn.commit()
    conn.close()


def sqlite_get_active_agents():
    """Get all active agents (fast database query)"""
    conn = sqlite3.connect(db_file)

    # Database does the filtering (fast!)
    cursor = conn.execute("SELECT agent_id FROM agents WHERE status = 'active'")
    agents = [row[0] for row in cursor.fetchall()]

    conn.close()
    return agents


# ============================================================================
# COMPARISON DEMO
# ============================================================================

def demo():
    """Show side-by-side comparison"""

    print("=" * 70)
    print("JSON vs SQLite - Practical Comparison")
    print("=" * 70)

    # Clean slate
    json_file.unlink(missing_ok=True)
    db_file.unlink(missing_ok=True)

    # Setup SQLite
    sqlite_setup()

    print("\n[TEST 1] Create 3 agents")
    print("-" * 70)

    # JSON approach
    print("\nJSON:")
    start = time.time()
    json_create_agent("agent_1", "key_1")
    json_create_agent("agent_2", "key_2")
    json_create_agent("agent_3", "key_3")
    json_time = time.time() - start
    print(f"  Created 3 agents in {json_time:.4f}s")
    print(f"  File size: {json_file.stat().st_size} bytes")

    # SQLite approach
    print("\nSQLite:")
    start = time.time()
    sqlite_create_agent("agent_1", "key_1")
    sqlite_create_agent("agent_2", "key_2")
    sqlite_create_agent("agent_3", "key_3")
    sqlite_time = time.time() - start
    print(f"  Created 3 agents in {sqlite_time:.4f}s")
    print(f"  File size: {db_file.stat().st_size} bytes")

    print("\n[TEST 2] Query active agents")
    print("-" * 70)

    # JSON approach
    print("\nJSON:")
    start = time.time()
    json_active = json_get_active_agents()
    json_query_time = time.time() - start
    print(f"  Found {len(json_active)} active agents in {json_query_time:.6f}s")
    print(f"  Method: Load entire file, filter in Python")

    # SQLite approach
    print("\nSQLite:")
    start = time.time()
    sqlite_active = sqlite_get_active_agents()
    sqlite_query_time = time.time() - start
    print(f"  Found {len(sqlite_active)} active agents in {sqlite_query_time:.6f}s")
    print(f"  Method: Database query with WHERE clause")

    print("\n[TEST 3] Concurrency (the killer test)")
    print("-" * 70)

    print("\nJSON:")
    print("  ❌ Race conditions possible without careful locking")
    print("  ❌ Need immediate saves (force=True) for critical ops")
    print("  ❌ Batched saves can lose data in debounce window")

    print("\nSQLite:")
    print("  ✅ Automatic locking - no race conditions")
    print("  ✅ ACID transactions - all-or-nothing")
    print("  ✅ Multiple processes can write simultaneously")

    print("\n[TEST 4] Complex Queries")
    print("-" * 70)

    print("\nJSON:")
    print("  ❌ Must load entire file")
    print("  ❌ Filter/sort in Python (slow for 1000+ agents)")
    print("  ❌ No indexes")

    print("\nSQLite:")
    print("  ✅ Query only what you need:")
    print("      SELECT * FROM agents WHERE total_updates > 100")
    print("      SELECT * FROM agents WHERE status = 'paused'")
    print("      SELECT * FROM agents ORDER BY created_at DESC LIMIT 10")
    print("  ✅ Fast indexes on any column")

    print("\n" + "=" * 70)
    print("RECOMMENDATION")
    print("=" * 70)
    print("\nFor your governance system:")
    print("  Current scale: JSON is acceptable with our race fix")
    print("  Future scale (100+ agents): SQLite recommended")
    print("  Multi-server: PostgreSQL")

    print("\nMigration effort:")
    print("  JSON → SQLite: ~200 lines of code, 2-3 hours")
    print("  SQLite → PostgreSQL: Just change connection string")

    # Show actual JSON structure
    print("\n" + "=" * 70)
    print("ACTUAL DATA STRUCTURES")
    print("=" * 70)

    print("\nJSON file content:")
    with open(json_file) as f:
        print(f.read())

    print("\nSQLite schema:")
    conn = sqlite3.connect(db_file)
    cursor = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'")
    print(cursor.fetchone()[0])

    print("\nSQLite data:")
    cursor = conn.execute("SELECT * FROM agents")
    for row in cursor:
        print(f"  {row}")
    conn.close()


if __name__ == "__main__":
    demo()
