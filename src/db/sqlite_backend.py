"""
SQLite Backend

Wraps existing SQLite-based storage (governance.db, audit_db.py) to implement
the DatabaseBackend interface. This allows gradual migration to PostgreSQL.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from .base import (
    DatabaseBackend,
    IdentityRecord,
    SessionRecord,
    AgentStateRecord,
    AuditEvent,
)


class SQLiteBackend(DatabaseBackend):
    """
    SQLite backend using existing governance.db schema.

    Environment:
        DB_SQLITE_PATH=data/governance.db (default)
        DB_SQLITE_ASYNC_WRAP=true|false (default: false, enable for high concurrency)
    """

    def __init__(self):
        self._db_path = Path(os.environ.get("DB_SQLITE_PATH", "data/governance.db"))
        self._conn: Optional[sqlite3.Connection] = None
        # Enable async wrapping for better concurrency under load
        self._async_wrap = os.environ.get("DB_SQLITE_ASYNC_WRAP", "false").lower() == "true"

    async def _run_sync(self, func, *args, **kwargs):
        """
        Run a synchronous function, optionally in a thread pool.
        
        When DB_SQLITE_ASYNC_WRAP=true, blocking SQLite operations run in 
        asyncio.to_thread() to avoid blocking the event loop under high concurrency.
        For low-traffic scenarios, direct execution is faster.
        """
        if self._async_wrap:
            return await asyncio.to_thread(func, *args, **kwargs)
        return func(*args, **kwargs)

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create connection."""
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), timeout=10.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    async def init(self) -> None:
        """Initialize tables if they don't exist."""
        conn = self._get_conn()

        # Schema matches existing governance.db structure
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_metadata (
                agent_id TEXT PRIMARY KEY,
                api_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                status TEXT DEFAULT 'active',
                parent_agent_id TEXT,
                spawn_reason TEXT,
                disabled_at TEXT,
                tags_json TEXT DEFAULT '[]',
                lifecycle_events_json TEXT DEFAULT '[]',
                metadata_json TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS session_identities (
                session_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_active TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                client_type TEXT,
                client_info_json TEXT DEFAULT '{}',
                metadata_json TEXT DEFAULT '{}',
                FOREIGN KEY (agent_id) REFERENCES agent_metadata(agent_id)
            );

            CREATE TABLE IF NOT EXISTS agent_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                entropy REAL DEFAULT 0.5,
                integrity REAL DEFAULT 0.5,
                stability_index REAL DEFAULT 0.5,
                volatility REAL DEFAULT 0.1,
                regime TEXT DEFAULT 'nominal',
                coherence REAL DEFAULT 1.0,
                state_json TEXT DEFAULT '{}',
                FOREIGN KEY (agent_id) REFERENCES agent_metadata(agent_id)
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_id TEXT,
                agent_id TEXT,
                session_id TEXT,
                event_type TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                details_json TEXT NOT NULL,
                raw_hash TEXT UNIQUE
            );

            CREATE TABLE IF NOT EXISTS tool_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                usage_id TEXT,
                agent_id TEXT,
                session_id TEXT,
                tool_name TEXT NOT NULL,
                latency_ms INTEGER,
                success INTEGER DEFAULT 1,
                error_type TEXT,
                payload_json TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS calibration_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                updated_at TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                state_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_session_agent ON session_identities(agent_id);
            CREATE INDEX IF NOT EXISTS idx_session_active ON session_identities(is_active, last_active);
            CREATE INDEX IF NOT EXISTS idx_audit_agent_time ON audit_events(agent_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_tool_usage_time ON tool_usage(timestamp);
        """)

        # Conditional index for agent_state - schema may differ between old and new DBs
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_state_agent_time ON agent_state(agent_id, recorded_at)")
        except sqlite3.OperationalError:
            # Old schema uses updated_at instead of recorded_at
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_state_agent_time ON agent_state(agent_id, updated_at)")
            except sqlite3.OperationalError:
                pass  # Index may already exist or column names differ

        # Insert default calibration if missing
        # Note: schema may or may not have 'version' column depending on DB version
        try:
            conn.execute("""
                INSERT OR IGNORE INTO calibration_state (id, updated_at, version, state_json)
                VALUES (1, datetime('now'), 1, '{"lambda1_threshold": 0.3, "lambda2_threshold": 0.7}')
            """)
        except sqlite3.OperationalError:
            # Fallback for old schema without version column
            conn.execute("""
                INSERT OR IGNORE INTO calibration_state (id, updated_at, state_json)
                VALUES (1, datetime('now'), '{"lambda1_threshold": 0.3, "lambda2_threshold": 0.7}')
            """)
        conn.commit()

    async def close(self) -> None:
        """Close connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    async def health_check(self) -> Dict[str, Any]:
        """Return health information."""
        conn = self._get_conn()
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            identity_count = conn.execute("SELECT COUNT(*) FROM agent_metadata").fetchone()[0]
            session_count = conn.execute(
                "SELECT COUNT(*) FROM session_identities WHERE is_active = 1"
            ).fetchone()[0]
            audit_count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]

            return {
                "status": "healthy",
                "backend": "sqlite",
                "db_path": str(self._db_path),
                "integrity": integrity,
                "identity_count": identity_count,
                "active_session_count": session_count,
                "audit_event_count": audit_count,
            }
        except Exception as e:
            return {"status": "error", "backend": "sqlite", "error": str(e)}

    # =========================================================================
    # IDENTITY OPERATIONS
    # =========================================================================

    async def upsert_identity(
        self,
        agent_id: str,
        api_key_hash: str,
        parent_agent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
    ) -> int:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        created = created_at.isoformat() if created_at else now

        # SQLite doesn't have RETURNING for UPSERT, so we use INSERT OR REPLACE
        # and then get rowid
        conn.execute(
            """
            INSERT INTO agent_metadata (agent_id, api_key, created_at, updated_at, parent_agent_id, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                metadata_json = json_patch(agent_metadata.metadata_json, excluded.metadata_json)
            """,
            (agent_id, api_key_hash, created, now, parent_agent_id, json.dumps(metadata or {})),
        )
        conn.commit()

        # Return rowid as identity_id equivalent
        row = conn.execute("SELECT rowid FROM agent_metadata WHERE agent_id = ?", (agent_id,)).fetchone()
        return row[0] if row else 0

    async def get_identity(self, agent_id: str) -> Optional[IdentityRecord]:
        def _sync_get():
            conn = self._get_conn()
            return conn.execute(
                """
                SELECT rowid, agent_id, api_key, created_at, updated_at, status,
                       parent_agent_id, spawn_reason, disabled_at, metadata_json
                FROM agent_metadata WHERE agent_id = ?
                """,
                (agent_id,),
            ).fetchone()

        row = await self._run_sync(_sync_get)

        if not row:
            return None

        return self._row_to_identity(row)

    async def get_identity_by_id(self, identity_id: int) -> Optional[IdentityRecord]:
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT rowid, agent_id, api_key, created_at, updated_at, status,
                   parent_agent_id, spawn_reason, disabled_at, metadata_json
            FROM agent_metadata WHERE rowid = ?
            """,
            (identity_id,),
        ).fetchone()

        if not row:
            return None

        return self._row_to_identity(row)

    async def list_identities(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[IdentityRecord]:
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                """
                SELECT rowid, agent_id, api_key, created_at, updated_at, status,
                       parent_agent_id, spawn_reason, disabled_at, metadata_json
                FROM agent_metadata WHERE status = ?
                ORDER BY created_at DESC LIMIT ? OFFSET ?
                """,
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT rowid, agent_id, api_key, created_at, updated_at, status,
                       parent_agent_id, spawn_reason, disabled_at, metadata_json
                FROM agent_metadata
                ORDER BY created_at DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        return [self._row_to_identity(r) for r in rows]

    async def update_identity_status(
        self,
        agent_id: str,
        status: str,
        disabled_at: Optional[datetime] = None,
    ) -> bool:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        disabled = disabled_at.isoformat() if disabled_at else None

        cursor = conn.execute(
            """
            UPDATE agent_metadata SET status = ?, disabled_at = ?, updated_at = ?
            WHERE agent_id = ?
            """,
            (status, disabled, now, agent_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    async def update_identity_metadata(
        self,
        agent_id: str,
        metadata: Dict[str, Any],
        merge: bool = True,
    ) -> bool:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()

        if merge:
            cursor = conn.execute(
                """
                UPDATE agent_metadata
                SET metadata_json = json_patch(metadata_json, ?), updated_at = ?
                WHERE agent_id = ?
                """,
                (json.dumps(metadata), now, agent_id),
            )
        else:
            cursor = conn.execute(
                """
                UPDATE agent_metadata SET metadata_json = ?, updated_at = ?
                WHERE agent_id = ?
                """,
                (json.dumps(metadata), now, agent_id),
            )
        conn.commit()
        return cursor.rowcount > 0

    async def verify_api_key(self, agent_id: str, api_key: str) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT api_key FROM agent_metadata WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()

        if not row:
            return False

        # Simple comparison (SQLite stores raw or hashed depending on how it was inserted)
        stored = row[0]
        return stored == api_key or stored == hashlib.sha256(api_key.encode()).hexdigest()

    async def upsert_agent(
        self,
        agent_id: str,
        api_key: str,
        status: str = "active",
        purpose: Optional[str] = None,
        notes: Optional[str] = None,
        tags: Optional[List[str]] = None,
        parent_agent_id: Optional[str] = None,
        spawn_reason: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> bool:
        """
        SQLite backend has no core.agents table; agent fields live in agent_metadata/metadata_json.
        No-op to satisfy the unified interface used by PostgreSQL migrations.
        """
        return True

    async def update_agent_fields(
        self,
        agent_id: str,
        *,
        status: Optional[str] = None,
        purpose: Optional[str] = None,
        notes: Optional[str] = None,
        tags: Optional[List[str]] = None,
        parent_agent_id: Optional[str] = None,
        spawn_reason: Optional[str] = None,
        label: Optional[str] = None,
    ) -> bool:
        """
        Update agent metadata in SQLite.
        """
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        
        # Build update for main columns
        updates = ["updated_at = ?"]
        params = [now]
        
        if status:
            updates.append("status = ?")
            params.append(status)
        if parent_agent_id:
            updates.append("parent_agent_id = ?")
            params.append(parent_agent_id)
        if spawn_reason:
            updates.append("spawn_reason = ?")
            params.append(spawn_reason)
        if tags:
            updates.append("tags_json = ?")
            params.append(json.dumps(tags))
            
        # Update metadata_json for fields that don't have columns
        meta_updates = {}
        if purpose:
            meta_updates["purpose"] = purpose
        if notes:
            meta_updates["notes"] = notes
        if label:
            meta_updates["label"] = label
            
        if meta_updates:
            updates.append("metadata_json = json_patch(metadata_json, ?)")
            params.append(json.dumps(meta_updates))
            
        params.append(agent_id)
        query = f"UPDATE agent_metadata SET {', '.join(updates)} WHERE agent_id = ?"
        
        cursor = conn.execute(query, tuple(params))
        conn.commit()
        return cursor.rowcount > 0

    async def get_agent_label(self, agent_id: str) -> Optional[str]:
        """Get agent's display label from metadata_json."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT metadata_json FROM agent_metadata WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        
        if row and row["metadata_json"]:
            meta = json.loads(row["metadata_json"])
            return meta.get("label")
        return None

    async def find_agent_by_label(self, label: str) -> Optional[str]:
        """Find agent UUID by label in metadata_json."""
        conn = self._get_conn()
        # Note: SQLite json_extract or ->> can be used if available, 
        # but for compatibility we might need to scan if it's an old SQLite.
        # Most modern ones have it.
        try:
            row = conn.execute(
                "SELECT agent_id FROM agent_metadata WHERE json_extract(metadata_json, '$.label') = ?",
                (label,),
            ).fetchone()
            if row:
                return row["agent_id"]
        except sqlite3.OperationalError:
            # Fallback for old SQLite without JSON support: scan (expensive but rare)
            rows = conn.execute("SELECT agent_id, metadata_json FROM agent_metadata").fetchall()
            for r in rows:
                if r["metadata_json"]:
                    meta = json.loads(r["metadata_json"])
                    if meta.get("label") == label:
                        return r["agent_id"]
        return None

    def _row_to_identity(self, row) -> IdentityRecord:
        created = datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc)
        updated = datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else created
        disabled = datetime.fromisoformat(row["disabled_at"]) if row["disabled_at"] else None

        return IdentityRecord(
            identity_id=row["rowid"],
            agent_id=row["agent_id"],
            api_key_hash=row["api_key"],
            created_at=created,
            updated_at=updated,
            status=row["status"] or "active",
            parent_agent_id=row["parent_agent_id"],
            spawn_reason=row["spawn_reason"],
            disabled_at=disabled,
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        )

    # =========================================================================
    # SESSION OPERATIONS
    # =========================================================================

    async def create_session(
        self,
        session_id: str,
        identity_id: int,
        expires_at: datetime,
        client_type: Optional[str] = None,
        client_info: Optional[Dict[str, Any]] = None,
    ) -> bool:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()

        # Get agent_id from identity_id
        row = conn.execute(
            "SELECT agent_id FROM agent_metadata WHERE rowid = ?", (identity_id,)
        ).fetchone()
        if not row:
            return False

        agent_id = row[0]

        try:
            conn.execute(
                """
                INSERT INTO session_identities
                    (session_id, agent_id, created_at, last_active, expires_at, client_type, client_info_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, agent_id, now, now, expires_at.isoformat(), client_type, json.dumps(client_info or {})),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    async def get_session(self, session_id: str) -> Optional[SessionRecord]:
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT s.session_id, m.rowid as identity_id, s.agent_id, s.created_at,
                   s.last_active, s.expires_at, s.is_active, s.client_type,
                   s.client_info_json, s.metadata_json
            FROM session_identities s
            JOIN agent_metadata m ON m.agent_id = s.agent_id
            WHERE s.session_id = ?
            """,
            (session_id,),
        ).fetchone()

        if not row:
            return None

        return self._row_to_session(row)

    async def update_session_activity(self, session_id: str) -> bool:
        from config.governance_config import GovernanceConfig
        ttl_hours = GovernanceConfig.SESSION_TTL_HOURS
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        expires = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
        cursor = conn.execute(
            "UPDATE session_identities SET last_active = ?, expires_at = ? WHERE session_id = ? AND is_active = 1",
            (now, expires, session_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    async def end_session(self, session_id: str) -> bool:
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE session_identities SET is_active = 0 WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()
        return cursor.rowcount > 0

    async def get_active_sessions_for_identity(
        self,
        identity_id: int,
    ) -> List[SessionRecord]:
        conn = self._get_conn()

        # Get agent_id from identity_id
        row = conn.execute(
            "SELECT agent_id FROM agent_metadata WHERE rowid = ?", (identity_id,)
        ).fetchone()
        if not row:
            return []

        agent_id = row[0]

        rows = conn.execute(
            """
            SELECT s.session_id, ? as identity_id, s.agent_id, s.created_at,
                   s.last_active, s.expires_at, s.is_active, s.client_type,
                   s.client_info_json, s.metadata_json
            FROM session_identities s
            WHERE s.agent_id = ? AND s.is_active = 1 AND s.expires_at > datetime('now')
            ORDER BY s.last_active DESC
            """,
            (identity_id, agent_id),
        ).fetchall()

        return [self._row_to_session(r) for r in rows]

    async def cleanup_expired_sessions(self) -> int:
        conn = self._get_conn()
        cursor = conn.execute(
            """
            DELETE FROM session_identities
            WHERE expires_at < datetime('now') OR (is_active = 0 AND last_active < datetime('now', '-1 hour'))
            """
        )
        conn.commit()
        return cursor.rowcount

    def _row_to_session(self, row) -> SessionRecord:
        return SessionRecord(
            session_id=row["session_id"],
            identity_id=row["identity_id"],
            agent_id=row["agent_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_active=datetime.fromisoformat(row["last_active"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            is_active=bool(row["is_active"]),
            client_type=row["client_type"],
            client_info=json.loads(row["client_info_json"]) if row["client_info_json"] else {},
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        )

    # =========================================================================
    # AGENT STATE OPERATIONS
    # =========================================================================

    async def record_agent_state(
        self,
        identity_id: int,
        entropy: float,
        integrity: float,
        stability_index: float,
        volatility: float,
        regime: str,
        coherence: float,
        state_json: Optional[Dict[str, Any]] = None,
    ) -> int:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()

        # Get agent_id from identity_id
        row = conn.execute(
            "SELECT agent_id FROM agent_metadata WHERE rowid = ?", (identity_id,)
        ).fetchone()
        if not row:
            return 0

        agent_id = row[0]

        cursor = conn.execute(
            """
            INSERT INTO agent_state
                (agent_id, recorded_at, entropy, integrity, stability_index, volatility, regime, coherence, state_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (agent_id, now, entropy, integrity, stability_index, volatility, regime, coherence, json.dumps(state_json or {})),
        )
        conn.commit()
        return cursor.lastrowid

    async def get_latest_agent_state(
        self,
        identity_id: int,
    ) -> Optional[AgentStateRecord]:
        conn = self._get_conn()

        row = conn.execute(
            "SELECT agent_id FROM agent_metadata WHERE rowid = ?", (identity_id,)
        ).fetchone()
        if not row:
            return None

        agent_id = row[0]

        state_row = conn.execute(
            """
            SELECT id, agent_id, recorded_at, entropy, integrity, stability_index,
                   volatility, regime, coherence, state_json
            FROM agent_state
            WHERE agent_id = ?
            ORDER BY recorded_at DESC LIMIT 1
            """,
            (agent_id,),
        ).fetchone()

        if not state_row:
            return None

        return self._row_to_agent_state(state_row, identity_id)

    async def get_agent_state_history(
        self,
        identity_id: int,
        limit: int = 100,
    ) -> List[AgentStateRecord]:
        conn = self._get_conn()

        row = conn.execute(
            "SELECT agent_id FROM agent_metadata WHERE rowid = ?", (identity_id,)
        ).fetchone()
        if not row:
            return []

        agent_id = row[0]

        rows = conn.execute(
            """
            SELECT id, agent_id, recorded_at, entropy, integrity, stability_index,
                   volatility, regime, coherence, state_json
            FROM agent_state
            WHERE agent_id = ?
            ORDER BY recorded_at DESC LIMIT ?
            """,
            (agent_id, limit),
        ).fetchall()

        return [self._row_to_agent_state(r, identity_id) for r in rows]

    def _row_to_agent_state(self, row, identity_id: int) -> AgentStateRecord:
        return AgentStateRecord(
            state_id=row["id"],
            identity_id=identity_id,
            agent_id=row["agent_id"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            entropy=row["entropy"],
            integrity=row["integrity"],
            stability_index=row["stability_index"],
            volatility=row["volatility"],
            regime=row["regime"],
            coherence=row["coherence"],
            state_json=json.loads(row["state_json"]) if row["state_json"] else {},
        )

    # =========================================================================
    # AUDIT OPERATIONS
    # =========================================================================

    async def append_audit_event(self, event: AuditEvent) -> bool:
        conn = self._get_conn()
        try:
            # Note: existing schema uses 'id' (auto), no 'event_id' or 'session_id' columns
            # Store event_id and session_id in details_json if present
            payload = event.payload.copy() if event.payload else {}
            if event.event_id:
                payload["_event_id"] = event.event_id
            if event.session_id:
                payload["_session_id"] = event.session_id

            conn.execute(
                """
                INSERT OR IGNORE INTO audit_events
                    (timestamp, agent_id, event_type, confidence, details_json, raw_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (event.ts or datetime.now(timezone.utc)).isoformat(),
                    event.agent_id,
                    event.event_type,
                    event.confidence,
                    json.dumps(payload),
                    event.raw_hash,
                ),
            )
            conn.commit()
            return True
        except Exception:
            return False

    async def query_audit_events(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
        order: str = "asc",
    ) -> List[AuditEvent]:
        conn = self._get_conn()
        conditions = []
        params = []

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time.isoformat())
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time.isoformat())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_clause = "ASC" if order.lower() == "asc" else "DESC"
        params.append(limit)

        # Note: existing schema uses 'id' not 'event_id', no 'session_id' column
        rows = conn.execute(
            f"""
            SELECT timestamp, id, agent_id, event_type, confidence, details_json, raw_hash
            FROM audit_events
            {where_clause}
            ORDER BY timestamp {order_clause}
            LIMIT ?
            """,
            params,
        ).fetchall()

        return [self._row_to_audit_event(r) for r in rows]

    async def search_audit_events(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[AuditEvent]:
        conn = self._get_conn()
        # Note: existing schema uses 'id' not 'event_id', no 'session_id' column
        if agent_id:
            rows = conn.execute(
                """
                SELECT timestamp, id, agent_id, event_type, confidence, details_json, raw_hash
                FROM audit_events
                WHERE details_json LIKE ? AND agent_id = ?
                ORDER BY timestamp DESC LIMIT ?
                """,
                (f"%{query}%", agent_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT timestamp, id, agent_id, event_type, confidence, details_json, raw_hash
                FROM audit_events
                WHERE details_json LIKE ?
                ORDER BY timestamp DESC LIMIT ?
                """,
                (f"%{query}%", limit),
            ).fetchall()

        return [self._row_to_audit_event(r) for r in rows]

    def _row_to_audit_event(self, row) -> AuditEvent:
        # Parse details_json and extract event_id/session_id if stored there
        details = json.loads(row["details_json"]) if row["details_json"] else {}
        event_id = details.pop("_event_id", None) or str(row["id"])
        session_id = details.pop("_session_id", None)

        return AuditEvent(
            ts=datetime.fromisoformat(row["timestamp"]),
            event_id=event_id,
            event_type=row["event_type"],
            agent_id=row["agent_id"],
            session_id=session_id,
            confidence=row["confidence"],
            payload=details,
            raw_hash=row["raw_hash"],
        )

    # =========================================================================
    # CALIBRATION OPERATIONS
    # =========================================================================

    async def get_calibration(self) -> Dict[str, Any]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT state_json, updated_at, version FROM calibration_state WHERE id = 1"
        ).fetchone()

        if not row:
            return {}

        data = json.loads(row["state_json"]) if row["state_json"] else {}
        data["_updated_at"] = row["updated_at"]
        data["_version"] = row["version"]
        return data

    async def update_calibration(self, data: Dict[str, Any]) -> bool:
        conn = self._get_conn()
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}
        now = datetime.now(timezone.utc).isoformat()

        cursor = conn.execute(
            """
            UPDATE calibration_state
            SET state_json = ?, updated_at = ?, version = version + 1
            WHERE id = 1
            """,
            (json.dumps(clean_data), now),
        )
        conn.commit()
        return cursor.rowcount > 0

    # =========================================================================
    # TOOL USAGE OPERATIONS
    # =========================================================================

    async def append_tool_usage(
        self,
        agent_id: Optional[str],
        session_id: Optional[str],
        tool_name: str,
        latency_ms: Optional[int],
        success: bool,
        error_type: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn.execute(
                """
                INSERT INTO tool_usage
                    (timestamp, usage_id, agent_id, session_id, tool_name, latency_ms, success, error_type, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, str(uuid.uuid4()), agent_id, session_id, tool_name, latency_ms, int(success), error_type, json.dumps(payload or {})),
            )
            conn.commit()
            return True
        except Exception:
            return False

    async def query_tool_usage(
        self,
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        conditions = []
        params = []

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if tool_name:
            conditions.append("tool_name = ?")
            params.append(tool_name)
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time.isoformat())
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time.isoformat())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        rows = conn.execute(
            f"""
            SELECT timestamp, usage_id, agent_id, session_id, tool_name, latency_ms, success, error_type, payload_json
            FROM tool_usage
            {where_clause}
            ORDER BY timestamp DESC LIMIT ?
            """,
            params,
        ).fetchall()

        return [
            {
                "ts": datetime.fromisoformat(r["timestamp"]),
                "usage_id": r["usage_id"],
                "agent_id": r["agent_id"],
                "session_id": r["session_id"],
                "tool_name": r["tool_name"],
                "latency_ms": r["latency_ms"],
                "success": bool(r["success"]),
                "error_type": r["error_type"],
                "payload": json.loads(r["payload_json"]) if r["payload_json"] else {},
            }
            for r in rows
        ]

    # =========================================================================
    # DIALECTIC OPERATIONS
    # =========================================================================

    async def create_dialectic_session(
        self,
        session_id: str,
        paused_agent_id: str,
        reviewer_agent_id: Optional[str] = None,
        reason: Optional[str] = None,
        discovery_id: Optional[str] = None,
        dispute_type: Optional[str] = None,
        session_type: Optional[str] = None,
        topic: Optional[str] = None,
        max_synthesis_rounds: Optional[int] = None,
        synthesis_round: Optional[int] = None,
        paused_agent_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create dialectic session - delegates to existing dialectic_db."""
        from src.dialectic_db import create_session_async
        return await create_session_async(
            session_id=session_id,
            paused_agent_id=paused_agent_id,
            reviewer_agent_id=reviewer_agent_id,
            reason=reason,
            discovery_id=discovery_id,
            dispute_type=dispute_type,
            session_type=session_type,
            topic=topic,
            max_synthesis_rounds=max_synthesis_rounds,
            synthesis_round=synthesis_round,
            paused_agent_state=paused_agent_state,
        )

    async def get_dialectic_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get dialectic session - delegates to existing dialectic_db."""
        from src.dialectic_db import get_session_async
        return await get_session_async(session_id)

    async def get_dialectic_session_by_agent(
        self,
        agent_id: str,
        active_only: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Get dialectic session by agent - delegates to existing dialectic_db."""
        from src.dialectic_db import get_session_by_agent_async
        return await get_session_by_agent_async(agent_id, active_only)

    async def get_all_active_dialectic_sessions_for_agent(
        self,
        agent_id: str,
    ) -> List[Dict[str, Any]]:
        """Get all active sessions where agent is paused agent or reviewer."""
        from src.dialectic_db import get_all_sessions_by_agent_async
        return await get_all_sessions_by_agent_async(agent_id)

    async def update_dialectic_session_phase(
        self,
        session_id: str,
        phase: str,
    ) -> bool:
        """Update dialectic session phase - delegates to existing dialectic_db."""
        from src.dialectic_db import update_session_phase_async
        return await update_session_phase_async(session_id, phase)

    async def update_dialectic_session_reviewer(
        self,
        session_id: str,
        reviewer_agent_id: str,
    ) -> bool:
        """Update dialectic session reviewer - delegates to existing dialectic_db."""
        from src.dialectic_db import update_session_reviewer_async
        return await update_session_reviewer_async(session_id, reviewer_agent_id)

    async def add_dialectic_message(
        self,
        session_id: str,
        agent_id: str,
        message_type: str,
        root_cause: Optional[str] = None,
        proposed_conditions: Optional[List[str]] = None,
        reasoning: Optional[str] = None,
        observed_metrics: Optional[Dict[str, Any]] = None,
        concerns: Optional[List[str]] = None,
        agrees: Optional[bool] = None,
        signature: Optional[str] = None,
    ) -> int:
        """Add dialectic message - delegates to existing dialectic_db."""
        from src.dialectic_db import add_message_async
        return await add_message_async(
            session_id=session_id,
            agent_id=agent_id,
            message_type=message_type,
            root_cause=root_cause,
            proposed_conditions=proposed_conditions,
            reasoning=reasoning,
            observed_metrics=observed_metrics,
            concerns=concerns,
            agrees=agrees,
            signature=signature,
        )

    async def resolve_dialectic_session(
        self,
        session_id: str,
        resolution: Dict[str, Any],
        status: str = "resolved",
    ) -> bool:
        """Resolve dialectic session - delegates to existing dialectic_db."""
        from src.dialectic_db import resolve_session_async
        return await resolve_session_async(session_id, resolution, status)

    async def is_agent_in_active_dialectic_session(self, agent_id: str) -> bool:
        """Check if agent is in active dialectic session - delegates to existing dialectic_db."""
        from src.dialectic_db import is_agent_in_active_session_async
        return await is_agent_in_active_session_async(agent_id)

    async def get_pending_dialectic_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get dialectic sessions awaiting a reviewer (reviewer_agent_id IS NULL).

        SQLite delegates to existing dialectic_db.py which doesn't track this.
        Returns empty list - pull-based discovery is PostgreSQL-only feature.
        """
        # SQLite's dialectic support is via old dialectic_db.py which doesn't
        # have a method for this. PostgreSQL-only feature for now.
        return []
