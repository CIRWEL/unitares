"""
Agent Governance State Storage

Provides backend-agnostic access to agent governance state (EISV metrics).
Delegates to PostgreSQL (via get_db()) when DB_BACKEND=postgres,
falls back to SQLite for backward compatibility.

Architecture:
- PostgreSQL: Uses core.agent_state table with identity_id foreign key
- SQLite: Single database shared across all processes with WAL mode
- Core EISV values stored as columns for queryability
- Full state stored as JSON for complete persistence
"""

import asyncio
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.logging_utils import get_logger

logger = get_logger(__name__)

# Default database path - uses consolidated governance.db
# Set UNITARES_STATE_DB_PATH to override (e.g., for separate DB)
DEFAULT_DB_PATH = Path(
    os.getenv(
        "UNITARES_STATE_DB_PATH",
        str(Path(__file__).parent.parent / "data" / "governance.db")
    )
)


class AgentStateDB:
    """
    SQLite-backed storage for agent governance state.
    
    Thread-safe and process-safe via SQLite's built-in locking.
    Uses WAL mode for better concurrent access.
    """
    
    SCHEMA_VERSION = 1
    
    def __init__(self, db_path: Path = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a new connection (thread-safe pattern)."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent access
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn
    
    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    name TEXT PRIMARY KEY,
                    version INTEGER NOT NULL
                )
            """)
            
            # Main state table with queryable columns + JSON blob
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_state (
                    agent_id TEXT PRIMARY KEY,
                    
                    -- Core EISV values (queryable)
                    E REAL NOT NULL DEFAULT 0.5,
                    I REAL NOT NULL DEFAULT 1.0,
                    S REAL NOT NULL DEFAULT 0.2,
                    V REAL NOT NULL DEFAULT 0.0,
                    coherence REAL NOT NULL DEFAULT 1.0,
                    
                    -- Tracking
                    regime TEXT NOT NULL DEFAULT 'DIVERGENCE',
                    update_count INTEGER NOT NULL DEFAULT 0,
                    void_active INTEGER NOT NULL DEFAULT 0,
                    
                    -- Timestamps
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    
                    -- Full state as JSON (for complete persistence)
                    state_json TEXT NOT NULL
                )
            """)
            
            # Indexes for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_state_regime 
                ON agent_state(regime)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_state_coherence 
                ON agent_state(coherence)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_state_updated 
                ON agent_state(updated_at)
            """)
            
            # Record schema version
            conn.execute("""
                INSERT OR REPLACE INTO schema_version (name, version)
                VALUES ('agent_state', ?)
            """, (self.SCHEMA_VERSION,))
            
            conn.commit()
    
    def save_state(self, agent_id: str, state_dict: Dict[str, Any]) -> bool:
        """
        Save agent state to database.
        
        Args:
            agent_id: Agent identifier
            state_dict: Full state dictionary (from GovernanceState.to_dict_with_history())
        
        Returns:
            True if successful
        """
        now = datetime.now().isoformat()
        
        # Extract queryable fields
        E = float(state_dict.get('E', 0.5))
        I = float(state_dict.get('I', 1.0))
        S = float(state_dict.get('S', 0.2))
        V = float(state_dict.get('V', 0.0))
        coherence = float(state_dict.get('coherence', 1.0))
        regime = str(state_dict.get('regime', 'DIVERGENCE'))
        update_count = int(state_dict.get('update_count', 0))
        void_active = 1 if state_dict.get('void_active', False) else 0
        
        # Serialize full state
        state_json = json.dumps(state_dict, ensure_ascii=False)
        
        try:
            with self._get_connection() as conn:
                # Check if exists
                cursor = conn.execute(
                    "SELECT created_at FROM agent_state WHERE agent_id = ?",
                    (agent_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    # Update existing
                    conn.execute("""
                        UPDATE agent_state SET
                            E = ?, I = ?, S = ?, V = ?,
                            coherence = ?, regime = ?,
                            update_count = ?, void_active = ?,
                            updated_at = ?, state_json = ?
                        WHERE agent_id = ?
                    """, (
                        E, I, S, V, coherence, regime,
                        update_count, void_active,
                        now, state_json, agent_id
                    ))
                else:
                    # Insert new
                    conn.execute("""
                        INSERT INTO agent_state (
                            agent_id, E, I, S, V, coherence, regime,
                            update_count, void_active,
                            created_at, updated_at, state_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        agent_id, E, I, S, V, coherence, regime,
                        update_count, void_active,
                        now, now, state_json
                    ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to save state for {agent_id}: {e}", exc_info=True)
            return False
    
    def load_state(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Load agent state from database.
        
        Args:
            agent_id: Agent identifier
        
        Returns:
            State dictionary or None if not found
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT state_json FROM agent_state WHERE agent_id = ?",
                    (agent_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    return json.loads(row['state_json'])
                return None
                
        except Exception as e:
            logger.error(f"Failed to load state for {agent_id}: {e}", exc_info=True)
            return None
    
    def delete_state(self, agent_id: str) -> bool:
        """Delete agent state from database."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "DELETE FROM agent_state WHERE agent_id = ?",
                    (agent_id,)
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to delete state for {agent_id}: {e}", exc_info=True)
            return False
    
    def list_agents(self, 
                    regime: str = None,
                    min_coherence: float = None,
                    max_coherence: float = None,
                    limit: int = None) -> list[Dict[str, Any]]:
        """
        List agents with optional filters.
        
        Returns list of {agent_id, E, I, S, V, coherence, regime, update_count}
        """
        query = "SELECT agent_id, E, I, S, V, coherence, regime, update_count, updated_at FROM agent_state WHERE 1=1"
        params = []
        
        if regime:
            query += " AND regime = ?"
            params.append(regime)
        if min_coherence is not None:
            query += " AND coherence >= ?"
            params.append(min_coherence)
        if max_coherence is not None:
            query += " AND coherence <= ?"
            params.append(max_coherence)
        
        query += " ORDER BY updated_at DESC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to list agents: {e}", exc_info=True)
            return []
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics."""
        try:
            with self._get_connection() as conn:
                # Total count
                cursor = conn.execute("SELECT COUNT(*) as count FROM agent_state")
                total = cursor.fetchone()['count']
                
                # By regime
                cursor = conn.execute("""
                    SELECT regime, COUNT(*) as count 
                    FROM agent_state 
                    GROUP BY regime
                """)
                by_regime = {row['regime']: row['count'] for row in cursor.fetchall()}
                
                # Average EISV
                cursor = conn.execute("""
                    SELECT 
                        AVG(E) as avg_E,
                        AVG(I) as avg_I,
                        AVG(S) as avg_S,
                        AVG(V) as avg_V,
                        AVG(coherence) as avg_coherence
                    FROM agent_state
                """)
                row = cursor.fetchone()
                
                return {
                    "total_agents": total,
                    "by_regime": by_regime,
                    "averages": {
                        "E": row['avg_E'],
                        "I": row['avg_I'],
                        "S": row['avg_S'],
                        "V": row['avg_V'],
                        "coherence": row['avg_coherence']
                    }
                }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}", exc_info=True)
            return {"error": str(e)}
    
    def migrate_from_json(self, agents_dir: Path) -> Dict[str, Any]:
        """
        Migrate existing JSON state files to SQLite.
        
        Args:
            agents_dir: Path to data/agents/ directory
        
        Returns:
            Migration statistics
        """
        stats = {"migrated": 0, "skipped": 0, "errors": []}
        
        if not agents_dir.exists():
            return stats
        
        for json_file in agents_dir.glob("*_state.json"):
            agent_id = json_file.stem.replace("_state", "")
            
            try:
                with open(json_file, 'r') as f:
                    state_dict = json.load(f)
                
                if self.save_state(agent_id, state_dict):
                    stats["migrated"] += 1
                    logger.debug(f"Migrated state for {agent_id}")
                else:
                    stats["skipped"] += 1
                    
            except Exception as e:
                stats["errors"].append(f"{agent_id}: {e}")
                logger.warning(f"Failed to migrate {agent_id}: {e}")
        
        return stats


# Global instance (lazy initialization)
_state_db: Optional[AgentStateDB] = None
_db_lock: Optional[asyncio.Lock] = None


def get_state_db() -> AgentStateDB:
    """Get or create the global state database instance (sync API)."""
    global _state_db
    if _state_db is None:
        _state_db = AgentStateDB()
    return _state_db


# =========================================================================
# Backend-Agnostic Async Wrappers
# =========================================================================

def _use_postgres() -> bool:
    """Check if we should use PostgreSQL backend."""
    return os.getenv("DB_BACKEND", "").lower() == "postgres"


async def _get_sqlite_db() -> AgentStateDB:
    """Get or create SQLite state DB instance."""
    global _state_db, _db_lock
    if _db_lock is None:
        _db_lock = asyncio.Lock()

    async with _db_lock:
        if _state_db is None:
            _state_db = AgentStateDB()
    return _state_db


async def _get_identity_id(db, agent_id: str) -> Optional[int]:
    """Get identity_id for an agent, creating one if needed."""
    identity = await db.get_identity(agent_id)
    if identity:
        return identity.identity_id
    # Create a minimal identity for this agent
    return await db.upsert_identity(agent_id, api_key_hash="")


async def save_state_async(agent_id: str, state_dict: Dict[str, Any]) -> bool:
    """
    Save agent state to the appropriate backend.

    Uses PostgreSQL via get_db() when DB_BACKEND=postgres,
    falls back to SQLite otherwise.
    """
    if _use_postgres():
        from src.db import get_db
        db = get_db()
        if not hasattr(db, '_pool') or db._pool is None:
            await db.init()

        # Get or create identity_id
        identity_id = await _get_identity_id(db, agent_id)
        if identity_id is None:
            logger.error(f"Failed to get identity_id for {agent_id}")
            return False

        # Extract EISV values
        entropy = float(state_dict.get('E', 0.5))
        integrity = float(state_dict.get('I', 1.0))
        stability = float(state_dict.get('S', 0.2))
        volatility = float(state_dict.get('V', 0.0))
        coherence = float(state_dict.get('coherence', 1.0))
        regime = str(state_dict.get('regime', 'DIVERGENCE'))

        try:
            await db.record_agent_state(
                identity_id=identity_id,
                entropy=entropy,
                integrity=integrity,
                stability_index=stability,
                volatility=volatility,
                regime=regime,
                coherence=coherence,
                state_json=state_dict,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save state for {agent_id}: {e}")
            return False
    else:
        state_db = await _get_sqlite_db()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: state_db.save_state(agent_id, state_dict)
        )


async def load_state_async(agent_id: str) -> Optional[Dict[str, Any]]:
    """
    Load agent state from the appropriate backend.

    Uses PostgreSQL via get_db() when DB_BACKEND=postgres,
    falls back to SQLite otherwise.
    """
    if _use_postgres():
        from src.db import get_db
        db = get_db()
        if not hasattr(db, '_pool') or db._pool is None:
            await db.init()

        # Get identity_id
        identity = await db.get_identity(agent_id)
        if not identity:
            return None

        state_record = await db.get_latest_agent_state(identity.identity_id)
        if state_record:
            # Return the full state_json
            return state_record.state_json
        return None
    else:
        state_db = await _get_sqlite_db()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: state_db.load_state(agent_id)
        )


async def delete_state_async(agent_id: str) -> bool:
    """
    Delete agent state from the appropriate backend.

    Note: PostgreSQL doesn't support deletion (append-only state history),
    so this is a no-op for postgres backend.
    """
    if _use_postgres():
        # PostgreSQL state history is append-only, no deletion
        logger.debug(f"State deletion not supported in PostgreSQL (agent: {agent_id})")
        return True
    else:
        state_db = await _get_sqlite_db()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: state_db.delete_state(agent_id)
        )


async def list_agents_async(
    regime: Optional[str] = None,
    min_coherence: Optional[float] = None,
    max_coherence: Optional[float] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    List agents with optional filters.

    Returns list of {agent_id, E, I, S, V, coherence, regime, update_count}
    """
    if _use_postgres():
        from src.db import get_db
        db = get_db()
        if not hasattr(db, '_pool') or db._pool is None:
            await db.init()

        # Query identities and their latest states
        identities = await db.list_identities(limit=limit or 100)
        results = []
        for identity in identities:
            state = await db.get_latest_agent_state(identity.identity_id)
            if state:
                # Apply filters
                if regime and state.regime != regime:
                    continue
                if min_coherence is not None and state.coherence < min_coherence:
                    continue
                if max_coherence is not None and state.coherence > max_coherence:
                    continue

                results.append({
                    "agent_id": identity.agent_id,
                    "E": state.entropy,
                    "I": state.integrity,
                    "S": state.stability_index,
                    "V": state.volatility,
                    "coherence": state.coherence,
                    "regime": state.regime,
                    "update_count": state.state_json.get("update_count", 0) if state.state_json else 0,
                    "updated_at": state.recorded_at.isoformat() if state.recorded_at else None,
                })
        return results
    else:
        state_db = await _get_sqlite_db()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: state_db.list_agents(regime, min_coherence, max_coherence, limit)
        )


async def get_statistics_async() -> Dict[str, Any]:
    """Get database statistics."""
    if _use_postgres():
        from src.db import get_db
        db = get_db()
        if not hasattr(db, '_pool') or db._pool is None:
            await db.init()

        health = await db.health_check()
        return {
            "backend": "postgres",
            "total_agents": health.get("identity_count", 0),
            "status": "healthy" if health.get("status") == "healthy" else "error",
        }
    else:
        state_db = await _get_sqlite_db()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, state_db.get_statistics)


async def state_health_check_async() -> Dict[str, Any]:
    """Health check for state storage backend."""
    if _use_postgres():
        from src.db import get_db
        db = get_db()
        if not hasattr(db, '_pool') or db._pool is None:
            await db.init()
        health = await db.health_check()
        health["component"] = "agent_state"
        return health
    else:
        state_db = await _get_sqlite_db()
        loop = asyncio.get_running_loop()
        stats = await loop.run_in_executor(None, state_db.get_statistics)
        return {
            "backend": "sqlite",
            "component": "agent_state",
            **stats,
        }
