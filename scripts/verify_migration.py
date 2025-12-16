#!/usr/bin/env python3
"""
Migration Verification Script

Compares data between SQLite and PostgreSQL to verify migration integrity.

Usage:
    python3 scripts/verify_migration.py --sqlite data/governance.db --postgres postgresql://...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import asyncpg
except ImportError:
    print("ERROR: asyncpg required. pip install asyncpg")
    sys.exit(1)


class Verifier:
    """Compare SQLite and PostgreSQL data."""

    def __init__(self, sqlite_path: Path, postgres_url: str):
        self.sqlite_path = sqlite_path
        self.postgres_url = postgres_url
        self._sqlite_conn = None
        self._pg_pool = None

    def _get_sqlite(self) -> sqlite3.Connection:
        if self._sqlite_conn is None:
            self._sqlite_conn = sqlite3.connect(str(self.sqlite_path))
            self._sqlite_conn.row_factory = sqlite3.Row
        return self._sqlite_conn

    async def _get_pg(self) -> asyncpg.Pool:
        if self._pg_pool is None:
            self._pg_pool = await asyncpg.create_pool(self.postgres_url, min_size=1, max_size=5)
        return self._pg_pool

    async def verify_all(self) -> Dict[str, Dict[str, Any]]:
        """Run all verifications."""
        results = {}

        try:
        results["identities"] = await self._verify_identities()
        results["sessions"] = await self._verify_sessions()
        results["calibration"] = await self._verify_calibration()
        results["audit_events"] = await self._verify_audit_events()
        results["tool_usage"] = await self._verify_tool_usage()
        finally:
            # Cleanup - ensure connections are closed even if verification fails
        if self._sqlite_conn:
                try:
            self._sqlite_conn.close()
                except Exception as e:
                    print(f"Warning: Error closing SQLite connection: {e}")
        if self._pg_pool:
                try:
            await self._pg_pool.close()
                except Exception as e:
                    print(f"Warning: Error closing PostgreSQL pool: {e}")

        return results

    async def _verify_identities(self) -> Dict[str, Any]:
        """Verify identities match."""
        sqlite_conn = self._get_sqlite()
        pg_pool = await self._get_pg()

        # Get counts
        sqlite_count = sqlite_conn.execute("SELECT COUNT(*) FROM agent_metadata").fetchone()[0]

        async with pg_pool.acquire() as conn:
            pg_count = await conn.fetchval("SELECT COUNT(*) FROM core.identities")

        # Sample comparison
        sqlite_sample = sqlite_conn.execute(
            "SELECT agent_id, status FROM agent_metadata ORDER BY agent_id LIMIT 10"
        ).fetchall()

        mismatches = []
        async with pg_pool.acquire() as conn:
            for row in sqlite_sample:
                pg_row = await conn.fetchrow(
                    "SELECT agent_id, status FROM core.identities WHERE agent_id = $1",
                    row["agent_id"]
                )
                if not pg_row:
                    mismatches.append(f"Missing in PG: {row['agent_id']}")
                elif pg_row["status"] != (row["status"] or "active"):
                    mismatches.append(f"Status mismatch for {row['agent_id']}: sqlite={row['status']}, pg={pg_row['status']}")

        return {
            "sqlite_count": sqlite_count,
            "postgres_count": pg_count,
            "count_match": sqlite_count == pg_count,
            "sample_mismatches": mismatches,
            "status": "OK" if sqlite_count == pg_count and not mismatches else "MISMATCH",
        }

    async def _verify_sessions(self) -> Dict[str, Any]:
        """Verify sessions match."""
        sqlite_conn = self._get_sqlite()
        pg_pool = await self._get_pg()

        # Check if table exists
        table_exists = sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_identities'"
        ).fetchone()

        if not table_exists:
            return {"status": "SKIPPED", "reason": "Table not found in SQLite"}

        sqlite_count = sqlite_conn.execute("SELECT COUNT(*) FROM session_identities").fetchone()[0]

        async with pg_pool.acquire() as conn:
            pg_count = await conn.fetchval("SELECT COUNT(*) FROM core.sessions")

        return {
            "sqlite_count": sqlite_count,
            "postgres_count": pg_count,
            "count_match": sqlite_count == pg_count,
            "status": "OK" if sqlite_count == pg_count else "MISMATCH",
        }

    async def _verify_calibration(self) -> Dict[str, Any]:
        """Verify calibration state matches."""
        sqlite_conn = self._get_sqlite()
        pg_pool = await self._get_pg()

        table_exists = sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='calibration_state'"
        ).fetchone()

        if not table_exists:
            return {"status": "SKIPPED", "reason": "Table not found in SQLite"}

        sqlite_row = sqlite_conn.execute(
            "SELECT state_json FROM calibration_state WHERE id = 1"
        ).fetchone()

        async with pg_pool.acquire() as conn:
            pg_row = await conn.fetchrow("SELECT data FROM core.calibration WHERE id = TRUE")

        sqlite_data = json.loads(sqlite_row["state_json"]) if sqlite_row else {}
        pg_data = json.loads(pg_row["data"]) if pg_row else {}

        # Compare key fields
        keys_to_check = ["lambda1_threshold", "lambda2_threshold"]
        mismatches = []
        for key in keys_to_check:
            if sqlite_data.get(key) != pg_data.get(key):
                mismatches.append(f"{key}: sqlite={sqlite_data.get(key)}, pg={pg_data.get(key)}")

        return {
            "sqlite_keys": list(sqlite_data.keys()),
            "postgres_keys": list(pg_data.keys()),
            "mismatches": mismatches,
            "status": "OK" if not mismatches else "MISMATCH",
        }

    async def _verify_audit_events(self) -> Dict[str, Any]:
        """Verify audit events count (exact match may differ due to partitions)."""
        sqlite_conn = self._get_sqlite()
        pg_pool = await self._get_pg()

        table_exists = sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'"
        ).fetchone()

        if not table_exists:
            return {"status": "SKIPPED", "reason": "Table not found in SQLite"}

        sqlite_count = sqlite_conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]

        async with pg_pool.acquire() as conn:
            pg_count = await conn.fetchval("SELECT COUNT(*) FROM audit.events")

        # Allow some skipped events (due to missing partitions for old dates)
        diff = abs(sqlite_count - pg_count)
        diff_pct = (diff / sqlite_count * 100) if sqlite_count > 0 else 0

        return {
            "sqlite_count": sqlite_count,
            "postgres_count": pg_count,
            "difference": diff,
            "difference_pct": f"{diff_pct:.2f}%",
            "status": "OK" if diff_pct < 5 else "WARNING" if diff_pct < 20 else "MISMATCH",
        }

    async def _verify_tool_usage(self) -> Dict[str, Any]:
        """Verify tool usage count."""
        sqlite_conn = self._get_sqlite()
        pg_pool = await self._get_pg()

        table_exists = sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_usage'"
        ).fetchone()

        if not table_exists:
            return {"status": "SKIPPED", "reason": "Table not found in SQLite"}

        sqlite_count = sqlite_conn.execute("SELECT COUNT(*) FROM tool_usage").fetchone()[0]

        async with pg_pool.acquire() as conn:
            pg_count = await conn.fetchval("SELECT COUNT(*) FROM audit.tool_usage")

        diff = abs(sqlite_count - pg_count)
        diff_pct = (diff / sqlite_count * 100) if sqlite_count > 0 else 0

        return {
            "sqlite_count": sqlite_count,
            "postgres_count": pg_count,
            "difference": diff,
            "difference_pct": f"{diff_pct:.2f}%",
            "status": "OK" if diff_pct < 5 else "WARNING" if diff_pct < 20 else "MISMATCH",
        }


def main():
    parser = argparse.ArgumentParser(description="Verify SQLite to PostgreSQL migration")
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=Path("data/governance.db"),
        help="SQLite database path",
    )
    parser.add_argument(
        "--postgres",
        type=str,
        default="postgresql://postgres:postgres@localhost:5432/governance",
        help="PostgreSQL connection URL",
    )

    args = parser.parse_args()

    verifier = Verifier(args.sqlite, args.postgres)
    results = asyncio.run(verifier.verify_all())

    # Print results
    print("\n" + "=" * 60)
    print("MIGRATION VERIFICATION")
    print("=" * 60)

    all_ok = True
    for table, result in results.items():
        status = result.get("status", "UNKNOWN")
        if status not in ["OK", "SKIPPED"]:
            all_ok = False

        print(f"\n{table.upper()}: {status}")
        for key, value in result.items():
            if key != "status":
                print(f"  {key}: {value}")

    print("\n" + "=" * 60)
    if all_ok:
        print("OVERALL: PASS")
    else:
        print("OVERALL: ISSUES DETECTED")
        sys.exit(1)


if __name__ == "__main__":
    main()
