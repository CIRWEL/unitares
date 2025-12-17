"""
SQLite Backend for Dialectic Sessions

Provides cross-process shared storage for dialectic sessions,
solving the transport isolation problem where CLI and SSE processes
couldn't see each other's active sessions.

Architecture:
- Single SQLite database shared across all processes
- WAL mode for concurrent read/write
- No in-memory caching of active sessions (always query DB)
- Backward compatible with existing DialecticSession class
"""

import sqlite3
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import asdict

from src.logging_utils import get_logger
from src.dialectic_protocol import (
    DialecticSession,
    DialecticMessage,
    DialecticPhase,
    Resolution,
)

logger = get_logger(__name__)

# Default database path - uses consolidated governance.db
DEFAULT_DB_PATH = Path(
    # Allow overriding DB path for different deployments / tests.
    __import__("os").getenv("UNITARES_DIALECTIC_DB_PATH", str(Path(__file__).parent.parent / "data" / "governance.db"))
)


class DialecticDB:
    """
    SQLite-backed storage for dialectic sessions.

    Thread-safe and process-safe via SQLite's built-in locking.
    All operations are synchronous but can be wrapped in asyncio.to_thread().
    """

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a new connection (for thread safety)."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent access
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        """Initialize database schema."""
        conn = self._get_connection()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    name TEXT PRIMARY KEY,
                    version INTEGER NOT NULL
                );

                -- Main sessions table
                CREATE TABLE IF NOT EXISTS dialectic_sessions (
                    session_id TEXT PRIMARY KEY,
                    paused_agent_id TEXT NOT NULL,
                    reviewer_agent_id TEXT,
                    phase TEXT NOT NULL DEFAULT 'thesis',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT,

                    -- Session context
                    reason TEXT,
                    discovery_id TEXT,
                    dispute_type TEXT,
                    session_type TEXT,         -- 'recovery' or 'exploration'
                    topic TEXT,                -- exploration topic
                    max_synthesis_rounds INTEGER,
                    synthesis_round INTEGER,

                    -- Paused agent state snapshot
                    paused_agent_state_json TEXT,

                    -- Resolution (when resolved)
                    resolution_json TEXT,

                    -- Indexes
                    UNIQUE(session_id)
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_paused_agent
                    ON dialectic_sessions(paused_agent_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_reviewer
                    ON dialectic_sessions(reviewer_agent_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_phase
                    ON dialectic_sessions(phase);
                CREATE INDEX IF NOT EXISTS idx_sessions_status
                    ON dialectic_sessions(status);

                -- Messages table (thesis, antithesis, synthesis)
                CREATE TABLE IF NOT EXISTS dialectic_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    message_type TEXT NOT NULL,  -- 'thesis', 'antithesis', 'synthesis'
                    timestamp TEXT NOT NULL,

                    -- Message content
                    root_cause TEXT,
                    proposed_conditions_json TEXT,  -- JSON array
                    reasoning TEXT,
                    observed_metrics_json TEXT,  -- JSON object (for antithesis)
                    concerns_json TEXT,  -- JSON array (for antithesis)
                    agrees INTEGER,  -- Boolean for synthesis
                    signature TEXT,

                    FOREIGN KEY (session_id) REFERENCES dialectic_sessions(session_id)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON dialectic_messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_messages_type
                    ON dialectic_messages(message_type);
            """)
            # Lightweight schema migration: add columns if the DB existed pre-columns.
            existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(dialectic_sessions);").fetchall()}
            for col_sql in (
                "ALTER TABLE dialectic_sessions ADD COLUMN session_type TEXT;",
                "ALTER TABLE dialectic_sessions ADD COLUMN topic TEXT;",
                "ALTER TABLE dialectic_sessions ADD COLUMN max_synthesis_rounds INTEGER;",
                "ALTER TABLE dialectic_sessions ADD COLUMN synthesis_round INTEGER;",
            ):
                col_name = col_sql.split("ADD COLUMN", 1)[1].strip().split()[0]
                if col_name not in existing_cols:
                    try:
                        conn.execute(col_sql)
                    except Exception:
                        # Best effort: don't crash on migration; continue.
                        pass

            conn.execute("INSERT OR REPLACE INTO schema_version(name, version) VALUES(?, ?);", ("dialectic_db", 2))
            conn.commit()
            logger.debug(f"Initialized dialectic database at {self.db_path}")
        finally:
            conn.close()

    # =========================================================================
    # Session Operations
    # =========================================================================

    def create_session(
        self,
        session_id: str,
        paused_agent_id: str,
        reviewer_agent_id: str = None,
        reason: str = None,
        discovery_id: str = None,
        dispute_type: str = None,
        session_type: str = None,
        topic: str = None,
        max_synthesis_rounds: int = None,
        synthesis_round: int = None,
        paused_agent_state: Dict = None,
    ) -> Dict[str, Any]:
        """Create a new dialectic session."""
        conn = self._get_connection()
        try:
            now = datetime.now().isoformat()
            conn.execute("""
                INSERT INTO dialectic_sessions (
                    session_id, paused_agent_id, reviewer_agent_id,
                    phase, status, created_at, updated_at,
                    reason, discovery_id, dispute_type,
                    session_type, topic, max_synthesis_rounds, synthesis_round,
                    paused_agent_state_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                paused_agent_id,
                reviewer_agent_id,
                DialecticPhase.THESIS.value,  # Initial phase is "thesis" (awaiting thesis submission)
                "active",
                now,
                now,
                reason,
                discovery_id,
                dispute_type,
                session_type,
                topic,
                max_synthesis_rounds,
                synthesis_round,
                json.dumps(paused_agent_state) if paused_agent_state else None,
            ))
            conn.commit()
            logger.info(f"Created dialectic session {session_id[:16]}... for agent {paused_agent_id}")
            return {"session_id": session_id, "created": True}
        except sqlite3.IntegrityError as e:
            logger.warning(f"Session {session_id} already exists: {e}")
            return {"session_id": session_id, "created": False, "error": "already_exists"}
        finally:
            conn.close()

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID with all messages."""
        conn = self._get_connection()
        try:
            # Get session
            cursor = conn.execute("""
                SELECT * FROM dialectic_sessions WHERE session_id = ?
            """, (session_id,))
            row = cursor.fetchone()
            if not row:
                return None

            session = dict(row)

            # Parse JSON fields
            if session.get("paused_agent_state_json"):
                session["paused_agent_state"] = json.loads(session["paused_agent_state_json"])
            if session.get("resolution_json"):
                session["resolution"] = json.loads(session["resolution_json"])

            # Get messages
            cursor = conn.execute("""
                SELECT * FROM dialectic_messages
                WHERE session_id = ?
                ORDER BY id ASC
            """, (session_id,))

            messages = []
            for msg_row in cursor.fetchall():
                msg = dict(msg_row)
                # Parse JSON fields
                if msg.get("proposed_conditions_json"):
                    msg["proposed_conditions"] = json.loads(msg["proposed_conditions_json"])
                if msg.get("observed_metrics_json"):
                    msg["observed_metrics"] = json.loads(msg["observed_metrics_json"])
                if msg.get("concerns_json"):
                    msg["concerns"] = json.loads(msg["concerns_json"])
                messages.append(msg)

            session["messages"] = messages
            return session
        finally:
            conn.close()

    def get_session_by_agent(self, agent_id: str, active_only: bool = True) -> Optional[Dict[str, Any]]:
        """Get session where agent is paused agent or reviewer."""
        conn = self._get_connection()
        try:
            status_filter = "AND status = 'active'" if active_only else ""
            cursor = conn.execute(f"""
                SELECT session_id FROM dialectic_sessions
                WHERE (paused_agent_id = ? OR reviewer_agent_id = ?)
                {status_filter}
                ORDER BY created_at DESC
                LIMIT 1
            """, (agent_id, agent_id))
            row = cursor.fetchone()
            if row:
                return self.get_session(row["session_id"])
            return None
        finally:
            conn.close()

    def get_all_sessions_by_agent(self, agent_id: str) -> List[Dict[str, Any]]:
        """Get all active sessions where agent is paused agent or reviewer."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT session_id FROM dialectic_sessions
                WHERE (paused_agent_id = ? OR reviewer_agent_id = ?)
                AND status = 'active'
                ORDER BY created_at DESC
            """, (agent_id, agent_id))
            rows = cursor.fetchall()
            sessions = []
            for row in rows:
                session = self.get_session(row["session_id"])
                if session:
                    sessions.append(session)
            return sessions
        finally:
            conn.close()

    def update_session_phase(self, session_id: str, phase: str) -> bool:
        """Update session phase."""
        conn = self._get_connection()
        try:
            conn.execute("""
                UPDATE dialectic_sessions
                SET phase = ?, updated_at = ?
                WHERE session_id = ?
            """, (phase, datetime.now().isoformat(), session_id))
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def update_session_reviewer(self, session_id: str, reviewer_agent_id: str) -> bool:
        """Assign reviewer to session."""
        conn = self._get_connection()
        try:
            conn.execute("""
                UPDATE dialectic_sessions
                SET reviewer_agent_id = ?, updated_at = ?
                WHERE session_id = ?
            """, (reviewer_agent_id, datetime.now().isoformat(), session_id))
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def resolve_session(
        self,
        session_id: str,
        resolution: Dict[str, Any],
        status: str = "resolved"
    ) -> bool:
        """Mark session as resolved."""
        conn = self._get_connection()
        try:
            conn.execute("""
                UPDATE dialectic_sessions
                SET status = ?, phase = ?, resolution_json = ?, updated_at = ?
                WHERE session_id = ?
            """, (
                status,
                DialecticPhase.RESOLVED.value,
                json.dumps(resolution),
                datetime.now().isoformat(),
                session_id
            ))
            conn.commit()
            logger.info(f"Resolved session {session_id[:16]}... with status {status}")
            return conn.total_changes > 0
        finally:
            conn.close()

    # =========================================================================
    # Message Operations
    # =========================================================================

    def add_message(
        self,
        session_id: str,
        agent_id: str,
        message_type: str,  # 'thesis', 'antithesis', 'synthesis'
        root_cause: str = None,
        proposed_conditions: List[str] = None,
        reasoning: str = None,
        observed_metrics: Dict = None,
        concerns: List[str] = None,
        agrees: bool = None,
        signature: str = None,
    ) -> int:
        """Add a message to a session."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO dialectic_messages (
                    session_id, agent_id, message_type, timestamp,
                    root_cause, proposed_conditions_json, reasoning,
                    observed_metrics_json, concerns_json, agrees, signature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                agent_id,
                message_type,
                datetime.now().isoformat(),
                root_cause,
                json.dumps(proposed_conditions) if proposed_conditions else None,
                reasoning,
                json.dumps(observed_metrics) if observed_metrics else None,
                json.dumps(concerns) if concerns else None,
                1 if agrees else (0 if agrees is False else None),
                signature,
            ))
            conn.commit()

            # Update session timestamp
            conn.execute("""
                UPDATE dialectic_sessions SET updated_at = ? WHERE session_id = ?
            """, (datetime.now().isoformat(), session_id))
            conn.commit()

            return cursor.lastrowid
        finally:
            conn.close()

    # =========================================================================
    # Query Operations
    # =========================================================================

    def is_agent_in_active_session(self, agent_id: str) -> bool:
        """Check if agent is in an active session (as paused or reviewer)."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT 1 FROM dialectic_sessions
                WHERE (paused_agent_id = ? OR reviewer_agent_id = ?)
                AND status = 'active'
                LIMIT 1
            """, (agent_id, agent_id))
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def has_recently_reviewed(
        self,
        reviewer_id: str,
        paused_agent_id: str,
        hours: int = 24
    ) -> bool:
        """Check if reviewer has recently reviewed this agent."""
        conn = self._get_connection()
        try:
            # Calculate cutoff time
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

            cursor = conn.execute("""
                SELECT 1 FROM dialectic_sessions
                WHERE reviewer_agent_id = ?
                AND paused_agent_id = ?
                AND status = 'resolved'
                AND created_at >= ?
                LIMIT 1
            """, (reviewer_id, paused_agent_id, cutoff))
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def get_active_sessions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all active sessions."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT * FROM dialectic_sessions
                WHERE status = 'active'
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_sessions_awaiting_reviewer(self) -> List[Dict[str, Any]]:
        """Get sessions that need a reviewer assigned."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT * FROM dialectic_sessions
                WHERE status = 'active'
                AND (reviewer_agent_id IS NULL OR reviewer_agent_id = '')
                ORDER BY created_at ASC
            """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        conn = self._get_connection()
        try:
            stats = {}

            # Session counts by status
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count
                FROM dialectic_sessions
                GROUP BY status
            """)
            stats["by_status"] = {row["status"]: row["count"] for row in cursor.fetchall()}

            # Session counts by phase
            cursor = conn.execute("""
                SELECT phase, COUNT(*) as count
                FROM dialectic_sessions
                GROUP BY phase
            """)
            stats["by_phase"] = {row["phase"]: row["count"] for row in cursor.fetchall()}

            # Total messages
            cursor = conn.execute("SELECT COUNT(*) as count FROM dialectic_messages")
            stats["total_messages"] = cursor.fetchone()["count"]

            # Total sessions
            cursor = conn.execute("SELECT COUNT(*) as count FROM dialectic_sessions")
            stats["total_sessions"] = cursor.fetchone()["count"]

            return stats
        finally:
            conn.close()

    def health_check(self) -> Dict[str, Any]:
        """Best-effort DB health check (integrity + counts)."""
        conn = self._get_connection()
        try:
            integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
            fk_issues = conn.execute("PRAGMA foreign_key_check;").fetchall()
            sess = conn.execute("SELECT COUNT(*) FROM dialectic_sessions;").fetchone()[0]
            msgs = conn.execute("SELECT COUNT(*) FROM dialectic_messages;").fetchone()[0]
            version = conn.execute("SELECT version FROM schema_version WHERE name=?;", ("dialectic_db",)).fetchone()
            return {
                "backend": "sqlite",
                "db_path": str(self.db_path),
                "schema_version": int(version[0]) if version else None,
                "integrity_check": integrity,
                "foreign_key_issues": len(fk_issues),
                "total_sessions": int(sess),
                "total_messages": int(msgs),
            }
        finally:
            conn.close()


# =========================================================================
# Async Wrapper Functions
# =========================================================================

_db_instance: Optional[DialecticDB] = None
_db_lock: Optional[asyncio.Lock] = None


async def get_dialectic_db() -> DialecticDB:
    """Get singleton dialectic database instance."""
    global _db_instance, _db_lock

    if _db_lock is None:
        _db_lock = asyncio.Lock()

    async with _db_lock:
        if _db_instance is None:
            _db_instance = DialecticDB()
        return _db_instance


async def create_session_async(**kwargs) -> Dict[str, Any]:
    """Async wrapper for create_session."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.create_session(**kwargs))


async def get_session_async(session_id: str) -> Optional[Dict[str, Any]]:
    """Async wrapper for get_session."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.get_session(session_id))


async def get_session_by_agent_async(agent_id: str, active_only: bool = True) -> Optional[Dict[str, Any]]:
    """Async wrapper for get_session_by_agent."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.get_session_by_agent(agent_id, active_only))


async def get_all_sessions_by_agent_async(agent_id: str) -> List[Dict[str, Any]]:
    """Async wrapper for get_all_sessions_by_agent."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.get_all_sessions_by_agent(agent_id))


async def is_agent_in_active_session_async(agent_id: str) -> bool:
    """Async wrapper for is_agent_in_active_session."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.is_agent_in_active_session(agent_id))


async def has_recently_reviewed_async(reviewer_id: str, paused_agent_id: str, hours: int = 24) -> bool:
    """Async wrapper for has_recently_reviewed."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.has_recently_reviewed(reviewer_id, paused_agent_id, hours))


async def add_message_async(**kwargs) -> int:
    """Async wrapper for add_message."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.add_message(**kwargs))


async def update_session_phase_async(session_id: str, phase: str) -> bool:
    """Async wrapper for update_session_phase."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.update_session_phase(session_id, phase))


async def update_session_reviewer_async(session_id: str, reviewer_agent_id: str) -> bool:
    """Async wrapper for update_session_reviewer."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.update_session_reviewer(session_id, reviewer_agent_id))


async def resolve_session_async(session_id: str, resolution: Dict[str, Any], status: str = "resolved") -> bool:
    """Async wrapper for resolve_session."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.resolve_session(session_id, resolution, status))


async def get_active_sessions_async(limit: int = 100) -> List[Dict[str, Any]]:
    """Async wrapper for get_active_sessions."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.get_active_sessions(limit))


async def get_sessions_awaiting_reviewer_async() -> List[Dict[str, Any]]:
    """Async wrapper for get_sessions_awaiting_reviewer."""
    db = await get_dialectic_db()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: db.get_sessions_awaiting_reviewer())
