"""
SQLite-backed Agent Metadata Store

Motivation:
- `data/agent_metadata.json` works for single-process stdio but becomes fragile under
  multi-client SSE / concurrent writers.
- SQLite provides atomicity, WAL concurrency, and fast indexed queries.

Design:
- Store the same logical fields as `AgentMetadata` (from `mcp_server_std.py`).
- Complex nested fields are stored as JSON strings (tags, lifecycle_events, etc.).
- Optional JSON snapshot can still be written for backward compatibility / transparency.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Optional[str], default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except Exception:
        # Corrupt row data should not crash server; fall back.
        return default


class AgentMetadataDB:
    """
    Lightweight SQLite store for agent metadata.

    This class opens a new connection per operation (simple + safe) and uses WAL mode
    for better concurrency.
    """

    SCHEMA_VERSION = 2  # Added active_session_key, session_bound_at

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        # Concurrency + durability tuning
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                  name TEXT PRIMARY KEY,
                  version INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_metadata (
                  agent_id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  last_update TEXT NOT NULL,
                  version TEXT,
                  total_updates INTEGER NOT NULL DEFAULT 0,
                  tags_json TEXT,
                  notes TEXT,
                  lifecycle_events_json TEXT,
                  paused_at TEXT,
                  archived_at TEXT,
                  parent_agent_id TEXT,
                  spawn_reason TEXT,
                  api_key TEXT,
                  recent_update_timestamps_json TEXT,
                  recent_decisions_json TEXT,
                  loop_detected_at TEXT,
                  loop_cooldown_until TEXT,
                  last_response_at TEXT,
                  response_completed INTEGER NOT NULL DEFAULT 0,
                  health_status TEXT,
                  dialectic_conditions_json TEXT,
                  active_session_key TEXT,
                  session_bound_at TEXT
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_metadata_status ON agent_metadata(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_metadata_last_update ON agent_metadata(last_update);")

            # Migration: Add new columns if they don't exist (for existing DBs)
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(agent_metadata);").fetchall()}
            if "active_session_key" not in existing_cols:
                conn.execute("ALTER TABLE agent_metadata ADD COLUMN active_session_key TEXT;")
            if "session_bound_at" not in existing_cols:
                conn.execute("ALTER TABLE agent_metadata ADD COLUMN session_bound_at TEXT;")
            if "purpose" not in existing_cols:
                conn.execute("ALTER TABLE agent_metadata ADD COLUMN purpose TEXT;")
            if "agent_uuid" not in existing_cols:
                conn.execute("ALTER TABLE agent_metadata ADD COLUMN agent_uuid TEXT;")
            if "label" not in existing_cols:
                conn.execute("ALTER TABLE agent_metadata ADD COLUMN label TEXT;")

            # Record schema version
            conn.execute(
                "INSERT OR REPLACE INTO schema_version(name, version) VALUES(?, ?);",
                ("agent_metadata", self.SCHEMA_VERSION),
            )

    def upsert_many(self, metadata_by_id: Dict[str, Any]) -> None:
        """
        Upsert all agent metadata rows in a single transaction.

        metadata_by_id values may be dataclasses or dicts matching AgentMetadata fields.
        """
        rows = []
        for agent_id, meta in metadata_by_id.items():
            if is_dataclass(meta):
                d = asdict(meta)
            elif isinstance(meta, dict):
                d = dict(meta)
            else:
                # Skip unexpected types
                continue

            rows.append(
                (
                    agent_id,
                    d.get("status"),
                    d.get("created_at"),
                    d.get("last_update"),
                    d.get("version"),
                    int(d.get("total_updates") or 0),
                    _json_dumps(d.get("tags") or []),
                    d.get("notes") or "",
                    _json_dumps(d.get("lifecycle_events") or []),
                    d.get("paused_at"),
                    d.get("archived_at"),
                    d.get("parent_agent_id"),
                    d.get("spawn_reason"),
                    d.get("api_key"),
                    _json_dumps(d.get("recent_update_timestamps") or []),
                    _json_dumps(d.get("recent_decisions") or []),
                    d.get("loop_detected_at"),
                    d.get("loop_cooldown_until"),
                    d.get("last_response_at"),
                    1 if d.get("response_completed") else 0,
                    d.get("health_status") or "unknown",
                    _json_dumps(d.get("dialectic_conditions") or []),
                    d.get("active_session_key"),
                    d.get("session_bound_at"),
                    d.get("purpose"),
                    d.get("agent_uuid"),
                    d.get("label"),
                )
            )

        with self._connect() as conn:
            conn.execute("BEGIN;")
            conn.executemany(
                """
                INSERT INTO agent_metadata (
                  agent_id, status, created_at, last_update, version, total_updates,
                  tags_json, notes, lifecycle_events_json,
                  paused_at, archived_at, parent_agent_id, spawn_reason, api_key,
                  recent_update_timestamps_json, recent_decisions_json,
                  loop_detected_at, loop_cooldown_until,
                  last_response_at, response_completed,
                  health_status, dialectic_conditions_json,
                  active_session_key, session_bound_at, purpose, agent_uuid, label
                ) VALUES (
                  ?, ?, ?, ?, ?, ?,
                  ?, ?, ?,
                  ?, ?, ?, ?, ?,
                  ?, ?,
                  ?, ?,
                  ?, ?,
                  ?, ?,
                  ?, ?, ?, ?, ?
                )
                ON CONFLICT(agent_id) DO UPDATE SET
                  status=excluded.status,
                  created_at=excluded.created_at,
                  last_update=excluded.last_update,
                  version=excluded.version,
                  total_updates=excluded.total_updates,
                  tags_json=excluded.tags_json,
                  notes=excluded.notes,
                  lifecycle_events_json=excluded.lifecycle_events_json,
                  paused_at=excluded.paused_at,
                  archived_at=excluded.archived_at,
                  parent_agent_id=excluded.parent_agent_id,
                  spawn_reason=excluded.spawn_reason,
                  api_key=excluded.api_key,
                  recent_update_timestamps_json=excluded.recent_update_timestamps_json,
                  recent_decisions_json=excluded.recent_decisions_json,
                  loop_detected_at=excluded.loop_detected_at,
                  loop_cooldown_until=excluded.loop_cooldown_until,
                  last_response_at=excluded.last_response_at,
                  response_completed=excluded.response_completed,
                  health_status=excluded.health_status,
                  dialectic_conditions_json=excluded.dialectic_conditions_json,
                  active_session_key=excluded.active_session_key,
                  session_bound_at=excluded.session_bound_at,
                  purpose=excluded.purpose,
                  agent_uuid=excluded.agent_uuid,
                  label=excluded.label;
                """,
                rows,
            )
            conn.execute("COMMIT;")

    def load_all(self) -> Dict[str, Dict[str, Any]]:
        """Load all metadata rows as plain dicts matching AgentMetadata fields."""
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM agent_metadata;")
            out: Dict[str, Dict[str, Any]] = {}
            for row in cur.fetchall():
                agent_id = row["agent_id"]
                out[agent_id] = {
                    "agent_id": agent_id,
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "last_update": row["last_update"],
                    "version": row["version"] or "v1.0",
                    "total_updates": int(row["total_updates"] or 0),
                    "tags": _json_loads(row["tags_json"], []),
                    "notes": row["notes"] or "",
                    "lifecycle_events": _json_loads(row["lifecycle_events_json"], []),
                    "paused_at": row["paused_at"],
                    "archived_at": row["archived_at"],
                    "parent_agent_id": row["parent_agent_id"],
                    "spawn_reason": row["spawn_reason"],
                    "api_key": row["api_key"],
                    "recent_update_timestamps": _json_loads(row["recent_update_timestamps_json"], []),
                    "recent_decisions": _json_loads(row["recent_decisions_json"], []),
                    "loop_detected_at": row["loop_detected_at"],
                    "loop_cooldown_until": row["loop_cooldown_until"],
                    "last_response_at": row["last_response_at"],
                    "response_completed": bool(row["response_completed"]),
                    "health_status": row["health_status"] or "unknown",
                    "dialectic_conditions": _json_loads(row["dialectic_conditions_json"], []),
                    "active_session_key": row["active_session_key"] if "active_session_key" in row.keys() else None,
                    "session_bound_at": row["session_bound_at"] if "session_bound_at" in row.keys() else None,
                    "purpose": row["purpose"] if "purpose" in row.keys() else None,
                    "agent_uuid": row["agent_uuid"] if "agent_uuid" in row.keys() else None,
                    "label": row["label"] if "label" in row.keys() else None,
                }
            return out

    def health_check(self) -> Dict[str, Any]:
        """Best-effort DB health check (integrity + basic counts)."""
        with self._connect() as conn:
            integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
            fk_issues = conn.execute("PRAGMA foreign_key_check;").fetchall()
            count = conn.execute("SELECT COUNT(*) FROM agent_metadata;").fetchone()[0]
            version = conn.execute(
                "SELECT version FROM schema_version WHERE name = ?;", ("agent_metadata",)
            ).fetchone()
            return {
                "backend": "sqlite",
                "db_path": str(self.db_path),
                "schema_version": int(version[0]) if version else None,
                "integrity_check": integrity,
                "foreign_key_issues": len(fk_issues),
                "agent_count": int(count),
            }


