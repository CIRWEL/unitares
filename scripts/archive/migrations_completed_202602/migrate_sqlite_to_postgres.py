#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script

Migrates data from SQLite (governance.db) to PostgreSQL.
Handles relational data only - AGE graph migration uses existing prototype.

Usage:
    python3 scripts/migrate_sqlite_to_postgres.py --help

    # Dry run (shows what would be migrated)
    python3 scripts/migrate_sqlite_to_postgres.py --dry-run

    # Full migration
    python3 scripts/migrate_sqlite_to_postgres.py \
        --sqlite data/governance.db \
        --postgres postgresql://postgres:postgres@localhost:5432/governance

    # Selective migration
    python3 scripts/migrate_sqlite_to_postgres.py --tables identities,sessions

    # Resume from checkpoint
    python3 scripts/migrate_sqlite_to_postgres.py --resume
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Namespace UUID for generating deterministic UUIDs from SQLite IDs
AUDIT_EVENT_NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")

try:
    import asyncpg
except ImportError:
    print("ERROR: asyncpg required. pip install asyncpg")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class MigrationStats:
    table: str
    total: int = 0
    migrated: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: int = 0


class Migrator:
    """SQLite to PostgreSQL migrator."""

    BATCH_SIZE = 500
    CHECKPOINT_FILE = Path("data/.migration_checkpoint.json")

    def __init__(
        self,
        sqlite_path: Path,
        postgres_url: str,
        tables: Optional[List[str]] = None,
        dry_run: bool = False,
        resume: bool = False,
    ):
        self.sqlite_path = sqlite_path
        self.postgres_url = postgres_url
        self.tables = tables or [
            "identities",
            "sessions",
            "agent_state",
            "calibration",
            "audit_events",
            "tool_usage",
        ]
        self.dry_run = dry_run
        self.resume = resume
        self.stats: Dict[str, MigrationStats] = {}
        self.checkpoint: Dict[str, Any] = {}

        self._sqlite_conn: Optional[sqlite3.Connection] = None
        self._pg_pool: Optional[asyncpg.Pool] = None

    def _load_checkpoint(self) -> None:
        """Load checkpoint from previous run."""
        if self.resume and self.CHECKPOINT_FILE.exists():
            try:
                self.checkpoint = json.loads(self.CHECKPOINT_FILE.read_text())
                logger.info(f"Loaded checkpoint: {self.checkpoint}")
            except Exception as e:
                logger.warning(f"Could not load checkpoint: {e}")
                self.checkpoint = {}

    def _save_checkpoint(self) -> None:
        """Save checkpoint for resume."""
        try:
            self.CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.CHECKPOINT_FILE.write_text(json.dumps(self.checkpoint, indent=2))
        except Exception as e:
            logger.warning(f"Could not save checkpoint: {e}")

    def _get_sqlite(self) -> sqlite3.Connection:
        """Get SQLite connection."""
        if self._sqlite_conn is None:
            if not self.sqlite_path.exists():
                raise FileNotFoundError(f"SQLite database not found: {self.sqlite_path}")
            self._sqlite_conn = sqlite3.connect(str(self.sqlite_path))
            self._sqlite_conn.row_factory = sqlite3.Row
        return self._sqlite_conn

    async def _get_pg(self) -> asyncpg.Pool:
        """Get PostgreSQL connection pool."""
        if self._pg_pool is None:
            self._pg_pool = await asyncpg.create_pool(
                self.postgres_url,
                min_size=2,
                max_size=10,
                command_timeout=60,
            )
        return self._pg_pool

    async def run(self) -> Dict[str, MigrationStats]:
        """Run the migration."""
        self._load_checkpoint()

        if self.dry_run:
            logger.info("DRY RUN - no data will be written")

        # Verify connections
        logger.info(f"SQLite: {self.sqlite_path}")
        sqlite_conn = self._get_sqlite()

        if not self.dry_run:
            logger.info(f"PostgreSQL: {self.postgres_url.split('@')[-1] if '@' in self.postgres_url else '***'}")
            pg_pool = await self._get_pg()
            async with pg_pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
                logger.info(f"PostgreSQL version: {version[:50]}...")

        try:
            # Migrate each table
            for table in self.tables:
                method = getattr(self, f"_migrate_{table}", None)
                if method:
                    try:
                        stats = await method()
                        self.stats[table] = stats
                        logger.info(
                            f"{table}: migrated={stats.migrated}, skipped={stats.skipped}, "
                            f"errors={stats.errors}, duration={stats.duration_ms}ms"
                        )
                    except Exception as e:
                        logger.error(f"Failed to migrate {table}: {e}")
                        self.stats[table] = MigrationStats(table=table, errors=1)
                else:
                    logger.warning(f"No migration method for table: {table}")

            # Remove checkpoint on success
            if not any(s.errors > 0 for s in self.stats.values()):
                if self.CHECKPOINT_FILE.exists():
                    self.CHECKPOINT_FILE.unlink()
                logger.info("Migration completed successfully!")
            else:
                self._save_checkpoint()
                logger.warning("Migration completed with errors. Checkpoint saved.")
        finally:
            # Cleanup - ensure connections are closed even if migration fails
            if self._sqlite_conn:
                try:
                    self._sqlite_conn.close()
                except Exception as e:
                    logger.warning(f"Error closing SQLite connection: {e}")
            if self._pg_pool:
                try:
                    await self._pg_pool.close()
                except Exception as e:
                    logger.warning(f"Error closing PostgreSQL pool: {e}")

        return self.stats

    # =========================================================================
    # TABLE MIGRATIONS
    # =========================================================================

    async def _migrate_identities(self) -> MigrationStats:
        """Migrate agent_metadata -> core.identities."""
        stats = MigrationStats(table="identities")
        start = datetime.now()

        sqlite_conn = self._get_sqlite()
        rows = sqlite_conn.execute("""
            SELECT rowid, agent_id, api_key, created_at, last_update, status,
                   parent_agent_id, spawn_reason, archived_at, tags_json, notes
            FROM agent_metadata
            ORDER BY rowid
        """).fetchall()

        stats.total = len(rows)

        if self.dry_run:
            logger.info(f"  Would migrate {stats.total} identities")
            stats.migrated = stats.total
            return stats

        pg_pool = await self._get_pg()
        async with pg_pool.acquire() as conn:
            for row in rows:
                try:
                    # Parse dates
                    created = self._parse_datetime(row["created_at"])
                    updated = self._parse_datetime(row["last_update"]) or created
                    disabled = self._parse_datetime(row["archived_at"])

                    # Build metadata from SQLite fields
                    metadata = {}
                    if row["tags_json"]:
                        try:
                            metadata["tags"] = json.loads(row["tags_json"])
                        except json.JSONDecodeError:
                            pass
                    if row["notes"]:
                        metadata["notes"] = row["notes"]

                    await conn.execute("""
                        INSERT INTO core.identities
                            (agent_id, api_key_hash, created_at, updated_at, status,
                             parent_agent_id, spawn_reason, disabled_at, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        ON CONFLICT (agent_id) DO UPDATE SET
                            updated_at = EXCLUDED.updated_at,
                            metadata = core.identities.metadata || EXCLUDED.metadata
                    """,
                        row["agent_id"],
                        row["api_key"],  # Already hashed or raw - keep as-is
                        created,
                        updated,
                        row["status"] or "active",
                        row["parent_agent_id"],
                        row["spawn_reason"],
                        disabled,
                        json.dumps(metadata),
                    )
                    stats.migrated += 1

                except Exception as e:
                    logger.warning(f"  Error migrating identity {row['agent_id']}: {e}")
                    stats.errors += 1

        stats.duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        return stats

    async def _migrate_sessions(self) -> MigrationStats:
        """Migrate session_identities -> core.sessions."""
        stats = MigrationStats(table="sessions")
        start = datetime.now()

        sqlite_conn = self._get_sqlite()
        rows = sqlite_conn.execute("""
            SELECT session_key, agent_id, api_key, bound_at, updated_at, bind_count
            FROM session_identities
            ORDER BY bound_at
        """).fetchall()

        stats.total = len(rows)

        if self.dry_run:
            logger.info(f"  Would migrate {stats.total} sessions")
            stats.migrated = stats.total
            return stats

        pg_pool = await self._get_pg()
        async with pg_pool.acquire() as conn:
            for row in rows:
                try:
                    # Get identity_id from agent_id
                    identity_id = await conn.fetchval(
                        "SELECT identity_id FROM core.identities WHERE agent_id = $1",
                        row["agent_id"]
                    )
                    if not identity_id:
                        stats.skipped += 1
                        continue

                    created = self._parse_datetime(row["bound_at"])
                    last_active = self._parse_datetime(row["updated_at"]) or created
                    # Default expiry to 24 hours from last activity
                    expires = last_active.replace(hour=23, minute=59, second=59) if last_active else datetime.now(timezone.utc)

                    # Build metadata from available fields
                    metadata = {"bind_count": row["bind_count"] or 1}

                    await conn.execute("""
                        INSERT INTO core.sessions
                            (session_id, identity_id, created_at, last_active, expires_at,
                             is_active, client_type, client_info, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        ON CONFLICT (session_id) DO UPDATE SET
                            last_active = EXCLUDED.last_active,
                            is_active = EXCLUDED.is_active
                    """,
                        row["session_key"],
                        identity_id,
                        created,
                        last_active,
                        expires,
                        True,  # Assume active since they're in the table
                        "unknown",  # No client_type in SQLite
                        json.dumps({}),
                        json.dumps(metadata),
                    )
                    stats.migrated += 1

                except Exception as e:
                    logger.warning(f"  Error migrating session {row['session_key']}: {e}")
                    stats.errors += 1

        stats.duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        return stats

    async def _migrate_agent_state(self) -> MigrationStats:
        """Migrate agent_state -> core.agent_state."""
        stats = MigrationStats(table="agent_state")
        start = datetime.now()

        sqlite_conn = self._get_sqlite()

        # Check if table exists
        table_exists = sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_state'"
        ).fetchone()

        if not table_exists:
            logger.info("  agent_state table not found in SQLite, skipping")
            return stats

        rows = sqlite_conn.execute("""
            SELECT agent_id, updated_at, E, I, S, V, regime, coherence, state_json
            FROM agent_state
            ORDER BY updated_at
        """).fetchall()

        stats.total = len(rows)

        if self.dry_run:
            logger.info(f"  Would migrate {stats.total} agent states")
            stats.migrated = stats.total
            return stats

        pg_pool = await self._get_pg()
        async with pg_pool.acquire() as conn:
            for row in rows:
                try:
                    identity_id = await conn.fetchval(
                        "SELECT identity_id FROM core.identities WHERE agent_id = $1",
                        row["agent_id"]
                    )
                    if not identity_id:
                        stats.skipped += 1
                        continue

                    recorded = self._parse_datetime(row["updated_at"])
                    state_json = {}
                    if row["state_json"]:
                        try:
                            state_json = json.loads(row["state_json"])
                        except json.JSONDecodeError:
                            pass

                    await conn.execute("""
                        INSERT INTO core.agent_state
                            (identity_id, recorded_at, entropy, integrity, stability_index,
                             volatility, regime, coherence, state_json)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        ON CONFLICT (identity_id, recorded_at) DO NOTHING
                    """,
                        identity_id,
                        recorded,
                        row["E"] or 0.5,  # entropy from E
                        row["I"] or 1.0,  # integrity from I
                        row["S"] or 0.2,  # stability_index from S
                        row["V"] or 0.0,  # volatility from V
                        row["regime"] or "EXPLORATION",
                        row["coherence"] or 1.0,
                        json.dumps(state_json),
                    )
                    stats.migrated += 1

                except Exception as e:
                    logger.warning(f"  Error migrating agent state: {e}")
                    stats.errors += 1

        stats.duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        return stats

    async def _migrate_calibration(self) -> MigrationStats:
        """Migrate calibration_state -> core.calibration."""
        stats = MigrationStats(table="calibration")
        start = datetime.now()

        sqlite_conn = self._get_sqlite()

        table_exists = sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='calibration_state'"
        ).fetchone()

        if not table_exists:
            logger.info("  calibration_state table not found in SQLite, skipping")
            return stats

        row = sqlite_conn.execute(
            "SELECT state_json, updated_at FROM calibration_state WHERE id = 1"
        ).fetchone()

        if not row:
            stats.total = 0
            return stats

        stats.total = 1

        if self.dry_run:
            logger.info("  Would migrate calibration state")
            stats.migrated = 1
            return stats

        pg_pool = await self._get_pg()
        async with pg_pool.acquire() as conn:
            try:
                data = {}
                if row["state_json"]:
                    try:
                        data = json.loads(row["state_json"])
                    except json.JSONDecodeError:
                        pass

                await conn.execute("""
                    UPDATE core.calibration
                    SET data = $1, updated_at = $2, version = 1
                    WHERE id = TRUE
                """,
                    json.dumps(data),
                    self._parse_datetime(row["updated_at"]) or datetime.now(timezone.utc),
                )
                stats.migrated = 1

            except Exception as e:
                logger.warning(f"  Error migrating calibration: {e}")
                stats.errors = 1

        stats.duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        return stats

    async def _migrate_audit_events(self) -> MigrationStats:
        """Migrate audit_events -> audit.events (partitioned)."""
        stats = MigrationStats(table="audit_events")
        start = datetime.now()

        sqlite_conn = self._get_sqlite()

        # Check if table exists
        table_exists = sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'"
        ).fetchone()

        if not table_exists:
            logger.info("  audit_events table not found in SQLite, skipping")
            return stats

        # Get checkpoint offset
        offset = self.checkpoint.get("audit_events_offset", 0)

        # Count total
        stats.total = sqlite_conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]

        if self.dry_run:
            logger.info(f"  Would migrate {stats.total} audit events")
            stats.migrated = stats.total
            return stats

        pg_pool = await self._get_pg()

        # Process in batches
        batch_num = 0
        while True:
            rows = sqlite_conn.execute("""
                SELECT timestamp, id, agent_id, event_type,
                       confidence, details_json, raw_hash
                FROM audit_events
                ORDER BY rowid
                LIMIT ? OFFSET ?
            """, (self.BATCH_SIZE, offset)).fetchall()

            if not rows:
                break

            async with pg_pool.acquire() as conn:
                for row in rows:
                    try:
                        ts = self._parse_datetime(row["timestamp"])
                        if not ts:
                            stats.skipped += 1
                            continue

                        payload = {}
                        if row["details_json"]:
                            try:
                                payload = json.loads(row["details_json"])
                            except json.JSONDecodeError:
                                pass

                        # Generate deterministic UUID from SQLite integer ID
                        event_uuid = uuid.uuid5(AUDIT_EVENT_NAMESPACE, str(row["id"])) if row["id"] else uuid.uuid4()

                        await conn.execute("""
                            INSERT INTO audit.events
                                (ts, event_id, agent_id, session_id, event_type, confidence, payload, raw_hash)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            ON CONFLICT DO NOTHING
                        """,
                            ts,
                            event_uuid,
                            row["agent_id"],
                            None,  # session_id not in SQLite
                            row["event_type"],
                            row["confidence"] or 1.0,
                            json.dumps(payload),
                            row["raw_hash"],
                        )
                        stats.migrated += 1

                    except Exception as e:
                        # Partition may not exist for old dates
                        if "no partition" in str(e).lower():
                            stats.skipped += 1
                        else:
                            logger.warning(f"  Error migrating audit event: {e}")
                            stats.errors += 1

            offset += len(rows)
            batch_num += 1

            # Save checkpoint periodically
            if batch_num % 10 == 0:
                self.checkpoint["audit_events_offset"] = offset
                self._save_checkpoint()
                logger.info(f"  Progress: {offset}/{stats.total} audit events")

        stats.duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        return stats

    async def _migrate_tool_usage(self) -> MigrationStats:
        """Migrate tool_usage -> audit.tool_usage (partitioned).
        
        Supports both SQLite table and JSONL file sources.
        """
        stats = MigrationStats(table="tool_usage")
        start = datetime.now()

        sqlite_conn = self._get_sqlite()

        # Check if SQLite table exists
        table_exists = sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_usage'"
        ).fetchone()

        # Also check for JSONL file
        jsonl_path = self.sqlite_path.parent / "tool_usage.jsonl"
        jsonl_exists = jsonl_path.exists()

        if not table_exists and not jsonl_exists:
            logger.info("  tool_usage not found in SQLite or JSONL, skipping")
            return stats
        
        # If JSONL exists but table doesn't, migrate from JSONL
        if not table_exists and jsonl_exists:
            return await self._migrate_tool_usage_jsonl(jsonl_path, stats, start)

        offset = self.checkpoint.get("tool_usage_offset", 0)
        stats.total = sqlite_conn.execute("SELECT COUNT(*) FROM tool_usage").fetchone()[0]

        if self.dry_run:
            logger.info(f"  Would migrate {stats.total} tool usage records")
            stats.migrated = stats.total
            return stats

        pg_pool = await self._get_pg()

        batch_num = 0
        while True:
            rows = sqlite_conn.execute("""
                SELECT timestamp, usage_id, agent_id, session_id, tool_name,
                       latency_ms, success, error_type, payload_json
                FROM tool_usage
                ORDER BY rowid
                LIMIT ? OFFSET ?
            """, (self.BATCH_SIZE, offset)).fetchall()

            if not rows:
                break

            async with pg_pool.acquire() as conn:
                for row in rows:
                    try:
                        ts = self._parse_datetime(row["timestamp"])
                        if not ts:
                            stats.skipped += 1
                            continue

                        payload = {}
                        if row["payload_json"]:
                            try:
                                payload = json.loads(row["payload_json"])
                            except json.JSONDecodeError:
                                pass

                        await conn.execute("""
                            INSERT INTO audit.tool_usage
                                (ts, usage_id, agent_id, session_id, tool_name,
                                 latency_ms, success, error_type, payload)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                            ON CONFLICT DO NOTHING
                        """,
                            ts,
                            row["usage_id"] or hashlib.sha256(str(row).encode()).hexdigest()[:32],
                            row["agent_id"],
                            row["session_id"],
                            row["tool_name"],
                            row["latency_ms"],
                            bool(row["success"]) if row["success"] is not None else True,
                            row["error_type"],
                            json.dumps(payload),
                        )
                        stats.migrated += 1

                    except Exception as e:
                        if "no partition" in str(e).lower():
                            stats.skipped += 1
                        else:
                            logger.warning(f"  Error migrating tool usage: {e}")
                            stats.errors += 1

            offset += len(rows)
            batch_num += 1

            if batch_num % 10 == 0:
                self.checkpoint["tool_usage_offset"] = offset
                self._save_checkpoint()
                logger.info(f"  Progress: {offset}/{stats.total} tool usage records")

        stats.duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        return stats

    async def _migrate_tool_usage_jsonl(
        self, jsonl_path: Path, stats: MigrationStats, start: datetime
    ) -> MigrationStats:
        """Migrate tool_usage from JSONL file."""
        logger.info(f"  Migrating from JSONL: {jsonl_path}")
        
        # Count lines
        with open(jsonl_path, 'r') as f:
            stats.total = sum(1 for _ in f)
        
        if self.dry_run:
            logger.info(f"  Would migrate {stats.total} tool usage records from JSONL")
            stats.migrated = stats.total
            return stats
        
        pg_pool = await self._get_pg()
        offset = self.checkpoint.get("tool_usage_jsonl_offset", 0)
        
        with open(jsonl_path, 'r') as f:
            # Skip to checkpoint
            for _ in range(offset):
                next(f, None)
            
            batch = []
            line_num = offset
            
            for line in f:
                line_num += 1
                try:
                    record = json.loads(line.strip())
                    batch.append(record)
                    
                    if len(batch) >= self.BATCH_SIZE:
                        await self._insert_tool_usage_batch(pg_pool, batch, stats)
                        batch = []
                        
                        # Save checkpoint
                        if line_num % (self.BATCH_SIZE * 10) == 0:
                            self.checkpoint["tool_usage_jsonl_offset"] = line_num
                            self._save_checkpoint()
                            logger.info(f"  Progress: {line_num}/{stats.total} tool usage records")
                            
                except json.JSONDecodeError:
                    stats.errors += 1
                except Exception as e:
                    logger.warning(f"  Error at line {line_num}: {e}")
                    stats.errors += 1
            
            # Final batch
            if batch:
                await self._insert_tool_usage_batch(pg_pool, batch, stats)
        
        stats.duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        return stats

    async def _insert_tool_usage_batch(
        self, pg_pool: asyncpg.Pool, batch: List[Dict], stats: MigrationStats
    ) -> None:
        """Insert a batch of tool usage records."""
        async with pg_pool.acquire() as conn:
            for record in batch:
                try:
                    # Handle various timestamp formats
                    ts = self._parse_datetime(
                        record.get("timestamp") or record.get("ts") or record.get("time")
                    )
                    if not ts:
                        stats.skipped += 1
                        continue
                    
                    await conn.execute("""
                        INSERT INTO audit.tool_usage
                            (ts, usage_id, agent_id, session_id, tool_name,
                             latency_ms, success, error_type, payload)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        ON CONFLICT DO NOTHING
                    """,
                        ts,
                        record.get("usage_id") or hashlib.sha256(json.dumps(record).encode()).hexdigest()[:32],
                        record.get("agent_id"),
                        record.get("session_id"),
                        record.get("tool_name") or record.get("tool") or "unknown",
                        record.get("latency_ms") or record.get("latency"),
                        record.get("success", True),
                        record.get("error_type") or record.get("error"),
                        json.dumps({k: v for k, v in record.items() 
                                   if k not in ("timestamp", "ts", "time", "usage_id", "agent_id", 
                                               "session_id", "tool_name", "tool", "latency_ms", 
                                               "latency", "success", "error_type", "error")}),
                    )
                    stats.migrated += 1
                except Exception as e:
                    if "no partition" in str(e).lower():
                        stats.skipped += 1
                    else:
                        stats.errors += 1

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """Parse datetime from various formats."""
        if not value:
            return None
        try:
            # Try ISO format first
            if "T" in value:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(value)
            # Ensure timezone aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None


def main():
    parser = argparse.ArgumentParser(
        description="Migrate SQLite to PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=Path("data/governance.db"),
        help="SQLite database path (default: data/governance.db)",
    )
    parser.add_argument(
        "--postgres",
        type=str,
        default="postgresql://postgres:postgres@localhost:5432/governance",
        help="PostgreSQL connection URL",
    )
    parser.add_argument(
        "--tables",
        type=str,
        default=None,
        help="Comma-separated list of tables to migrate (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint",
    )

    args = parser.parse_args()

    tables = args.tables.split(",") if args.tables else None

    migrator = Migrator(
        sqlite_path=args.sqlite,
        postgres_url=args.postgres,
        tables=tables,
        dry_run=args.dry_run,
        resume=args.resume,
    )

    stats = asyncio.run(migrator.run())

    # Print summary
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    for table, s in stats.items():
        status = "OK" if s.errors == 0 else "ERRORS"
        print(f"{table:20} {s.migrated:6} migrated, {s.skipped:6} skipped, {s.errors:3} errors [{status}]")
    print("=" * 60)

    # Exit with error if any failures
    if any(s.errors > 0 for s in stats.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
