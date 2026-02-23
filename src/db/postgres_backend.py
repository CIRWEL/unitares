"""
PostgreSQL + AGE Backend

Async PostgreSQL backend using asyncpg with Apache AGE for graph queries.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore

from .base import (
    DatabaseBackend,
    IdentityRecord,
    SessionRecord,
    AgentStateRecord,
    AuditEvent,
)
from src.logging_utils import get_logger

logger = get_logger(__name__)
from .dialectic_constants import ACTIVE_DIALECTIC_STATUSES


class PostgresBackend(DatabaseBackend):
    """
    PostgreSQL + AGE backend.

    Requires:
        pip install asyncpg

    Environment:
        DB_POSTGRES_URL=postgresql://user:pass@host:port/dbname
        DB_POSTGRES_MIN_CONN=2
        DB_POSTGRES_MAX_CONN=10
        DB_AGE_GRAPH=governance
    """

    def __init__(self):
        if asyncpg is None:
            raise ImportError("asyncpg is required for PostgreSQL backend. pip install asyncpg")

        self._pool: Optional[asyncpg.Pool] = None
        self._db_url = os.environ.get("DB_POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/governance")
        # Increased default pool size to handle concurrent requests
        # Can be overridden with DB_POSTGRES_MIN_CONN and DB_POSTGRES_MAX_CONN
        self._min_conn = int(os.environ.get("DB_POSTGRES_MIN_CONN", "5"))
        self._max_conn = int(os.environ.get("DB_POSTGRES_MAX_CONN", "25"))
        self._age_graph = os.environ.get("DB_AGE_GRAPH", "governance_graph")
        self._init_lock = None  # Will be created on first use
        self._last_pool_check = time.time()  # Avoid immediate health check on first request

    async def _ensure_pool(self) -> asyncpg.Pool:
        """
        Ensure connection pool is available, recreating if necessary.

        This provides automatic recovery from:
        - Pool becoming None after close()
        - Connection timeouts
        - PostgreSQL restarts
        """
        import asyncio
        import time

        # Fast path: pool exists and is healthy
        if self._pool is not None:
            # Periodic health check (every 60s)
            now = time.time()
            if now - self._last_pool_check > 60:
                try:
                    async with self._pool.acquire(timeout=5) as conn:
                        await conn.fetchval("SELECT 1")
                    self._last_pool_check = now
                    
                    # Check pool size and warn if getting full
                    pool_size = self._pool.get_size()
                    pool_max = self._pool.get_max_size()
                    if pool_size >= pool_max * 0.9:  # 90% full
                        logger.warning(
                            f"Connection pool nearly full: {pool_size}/{pool_max}. "
                            f"Consider increasing DB_POSTGRES_MAX_CONN or checking for connection leaks."
                        )
                except Exception as e:
                    logger.warning(f"Pool health check failed, destroying pool (backend={id(self)}): {e}")
                    try:
                        await self._pool.close()
                    except Exception:
                        pass
                    self._pool = None

        if self._pool is not None:
            return self._pool

        # Slow path: need to create pool
        # Use lock to prevent multiple concurrent pool creations
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            # Double-check after acquiring lock
            if self._pool is not None:
                return self._pool

            logger.info("Creating PostgreSQL connection pool...")
            # Wrap pool creation in timeout to prevent infinite retry loop
            # If PostgreSQL isn't running, fail fast (5 seconds) instead of retrying forever
            try:
                self._pool = await asyncio.wait_for(
                    asyncpg.create_pool(
                        self._db_url,
                        min_size=self._min_conn,
                        max_size=self._max_conn,
                        command_timeout=30,
                        max_inactive_connection_lifetime=300,  # Close idle connections after 5 minutes
                        max_queries=50000,  # Recycle connections after 50k queries
                    ),
                    timeout=5.0  # Fail fast if PostgreSQL isn't available
                )
            except asyncio.TimeoutError:
                raise ConnectionError(
                    f"PostgreSQL connection timeout after 5s. "
                    f"Is PostgreSQL running on {self._db_url}? "
                    f"Check: psql -d {self._db_url.split('/')[-1]}"
                )
            except Exception as e:
                # Re-raise with clearer error message
                raise ConnectionError(
                    f"Failed to connect to PostgreSQL at {self._db_url}: {e}. "
                    f"Is PostgreSQL running?"
                ) from e
            
            self._last_pool_check = time.time()
            logger.info("PostgreSQL connection pool created")
            return self._pool

    def acquire(self, timeout: float = None):
        """
        Get a connection from the pool with automatic recovery.

        Usage:
            async with self.acquire() as conn:
                await conn.fetchval("SELECT 1")

        This wraps pool.acquire() and ensures the pool exists.
        """
        class _AcquireContext:
            def __init__(ctx_self, backend, timeout):
                ctx_self.backend = backend
                ctx_self.timeout = timeout
                ctx_self.conn = None
                ctx_self.acquired_pool = None  # Track which pool we acquired from

            async def __aenter__(ctx_self):
                pool = await ctx_self.backend._ensure_pool()
                ctx_self.acquired_pool = pool  # Store reference to THIS pool
                try:
                    # Use timeout to prevent hanging (default 10s)
                    acquire_timeout = ctx_self.timeout or 10.0
                    ctx_self.conn = await pool.acquire(timeout=acquire_timeout)
                    return ctx_self.conn
                except asyncio.TimeoutError:
                    logger.error(f"Connection pool timeout after {acquire_timeout}s. Pool size: {pool.get_size()}, free: {pool.get_idle_size()}")
                    raise ConnectionError(
                        f"PostgreSQL connection pool exhausted. "
                        f"Current pool: {pool.get_size()}/{pool.get_max_size()}. "
                        f"Try increasing DB_POSTGRES_MAX_CONN or check for connection leaks."
                    )

            async def __aexit__(ctx_self, exc_type, exc_val, exc_tb):
                if ctx_self.conn and ctx_self.acquired_pool:
                    # Only release to the SAME pool we acquired from
                    # If pool was recreated, current_pool will differ from acquired_pool
                    current_pool = ctx_self.backend._pool
                    if current_pool is ctx_self.acquired_pool:
                        try:
                            await ctx_self.acquired_pool.release(ctx_self.conn)
                        except Exception as e:
                            logger.warning(f"Error releasing connection: {e}")
                    else:
                        # Pool was recreated - connection is orphaned, just close it
                        logger.debug("Pool was recreated during operation, closing orphan connection")
                        try:
                            await ctx_self.conn.close()
                        except Exception:
                            pass  # Connection may already be closed
                ctx_self.conn = None
                ctx_self.acquired_pool = None
                return False

        return _AcquireContext(self, timeout)

    async def init(self) -> None:
        """Initialize connection pool and verify schema."""
        import asyncio
        import time

        # Guard: don't recreate pool if it already exists and is usable
        if self._pool is not None:
            return

        # Initialize lock if not already created
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        # Wrap pool creation in timeout to prevent infinite retry loop
        # If PostgreSQL isn't running, fail fast (5 seconds) instead of retrying forever
        try:
            self._pool = await asyncio.wait_for(
                asyncpg.create_pool(
                    self._db_url,
                    min_size=self._min_conn,
                    max_size=self._max_conn,
                    command_timeout=30,
                    max_inactive_connection_lifetime=300,  # Close idle connections after 5 minutes
                    max_queries=50000,  # Recycle connections after 50k queries
                ),
                timeout=5.0  # Fail fast if PostgreSQL isn't available
            )
        except asyncio.TimeoutError:
            raise ConnectionError(
                f"PostgreSQL connection timeout after 5s. "
                f"Is PostgreSQL running on {self._db_url}? "
                f"Check: psql -d {self._db_url.split('/')[-1]}"
            )
        except Exception as e:
            # Re-raise with clearer error message
            raise ConnectionError(
                f"Failed to connect to PostgreSQL at {self._db_url}: {e}. "
                f"Is PostgreSQL running?"
            ) from e
        
        self._last_pool_check = time.time()

        # Verify schema exists
        async with self.acquire() as conn:
            # Check core schema
            result = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core')"
            )
            if not result:
                raise RuntimeError(
                    "PostgreSQL schema not initialized. Run db/postgres/schema.sql first."
                )

            # Check AGE extension
            try:
                await conn.execute("LOAD 'age'")
                await conn.execute(f"SET search_path = ag_catalog, core, audit, public")
            except Exception:
                # AGE not available, graph queries will be disabled
                pass

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def health_check(self) -> Dict[str, Any]:
        """Return health/status information."""
        if not self._pool:
            return {"status": "error", "error": "Pool not initialized"}

        async with self.acquire() as conn:
            # Basic connectivity
            result = await conn.fetchval("SELECT 1")

            # Schema version (from migrations table)
            version = await conn.fetchval("""
                SELECT MAX(version) FROM core.schema_migrations
            """)

            # Counts
            identity_count = await conn.fetchval("SELECT COUNT(*) FROM core.identities")
            session_count = await conn.fetchval("SELECT COUNT(*) FROM core.sessions WHERE is_active = TRUE")

            # AGE status
            age_available = False
            try:
                await conn.execute("LOAD 'age'")
                age_available = True
            except Exception:
                pass

            return {
                "status": "healthy",
                "backend": "postgres",
                "db_url": self._db_url.split("@")[-1] if "@" in self._db_url else "***",  # Hide credentials
                "pool_size": self._pool.get_size(),
                "pool_free": self._pool.get_idle_size(),
                "schema_version": version,
                "identity_count": identity_count,
                "active_session_count": session_count,
                "age_available": age_available,
                "age_graph": self._age_graph if age_available else None,
            }

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
        async with self.acquire() as conn:
            identity_id = await conn.fetchval(
                """
                INSERT INTO core.identities (agent_id, api_key_hash, parent_agent_id, metadata, created_at)
                VALUES ($1, $2, $3, $4, COALESCE($5, now()))
                ON CONFLICT (agent_id) DO UPDATE SET
                    metadata = core.identities.metadata || COALESCE($4, '{}'::jsonb),
                    updated_at = now()
                RETURNING identity_id
                """,
                agent_id,
                api_key_hash,
                parent_agent_id,
                json.dumps(metadata or {}),
                created_at,
            )
            return identity_id

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
        Create or update an agent in core.agents table.
        
        This is required for foreign key references in dialectic_sessions.
        Returns True if successful.
        """
        async with self.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO core.agents (
                        id, api_key, status, purpose, notes, tags,
                        created_at, parent_agent_id, spawn_reason
                    ) VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, now()), $8, $9)
                    ON CONFLICT (id) DO UPDATE SET
                        -- Only overwrite api_key if the existing value is empty and we have a non-empty one.
                        api_key = CASE
                            WHEN core.agents.api_key = '' AND EXCLUDED.api_key <> '' THEN EXCLUDED.api_key
                            ELSE core.agents.api_key
                        END,
                        status = EXCLUDED.status,
                        purpose = COALESCE(EXCLUDED.purpose, core.agents.purpose),
                        notes = COALESCE(EXCLUDED.notes, core.agents.notes),
                        tags = EXCLUDED.tags,
                        updated_at = now()
                    """,
                    agent_id,
                    api_key,
                    status,
                    purpose,
                    notes,
                    tags or [],
                    created_at,
                    parent_agent_id,
                    spawn_reason,
                )
                return True
            except Exception as e:
                logger.error(f"Failed to upsert agent {agent_id} in core.agents: {e}")
                return False

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
        Partial update of core.agents (does NOT modify api_key).
        """
        async with self.acquire() as conn:
            try:
                result = await conn.execute(
                    """
                    UPDATE core.agents
                    SET
                        status = COALESCE($2, status),
                        purpose = COALESCE($3, purpose),
                        notes = COALESCE($4, notes),
                        tags = COALESCE($5, tags),
                        parent_agent_id = COALESCE($6, parent_agent_id),
                        spawn_reason = COALESCE($7, spawn_reason),
                        label = COALESCE($8, label),
                        updated_at = now()
                    WHERE id = $1
                    """,
                    agent_id,
                    status,
                    purpose,
                    notes,
                    tags,
                    parent_agent_id,
                    spawn_reason,
                    label,
                )
                return "UPDATE 1" in result
            except Exception as e:
                logger.error(f"Failed to update agent fields for {agent_id}: {e}")
                return False

    async def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get agent record from core.agents.
        Returns dict with agent fields or None if not found.
        """
        async with self.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    SELECT id, api_key, status, purpose, notes, tags,
                           created_at, updated_at, archived_at, parent_agent_id,
                           spawn_reason, label
                    FROM core.agents
                    WHERE id = $1
                    """,
                    agent_id
                )
                if row:
                    return dict(row)
                return None
            except Exception as e:
                logger.error(f"Failed to get agent {agent_id}: {e}")
                return None

    async def get_agent_label(self, agent_id: str) -> Optional[str]:
        """Get agent's display label from core.agents."""
        async with self.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT label FROM core.agents WHERE id = $1",
                    agent_id
                )
                return row["label"] if row else None
            except Exception as e:
                logger.debug(f"Failed to get label for {agent_id}: {e}")
                return None

    async def find_agent_by_label(self, label: str) -> Optional[str]:
        """Find agent UUID by label. Prefers active agents, most recently updated."""
        async with self.acquire() as conn:
            try:
                rows = await conn.fetch(
                    "SELECT id FROM core.agents WHERE label = $1 AND status = 'active' "
                    "ORDER BY updated_at DESC",
                    label
                )
                if len(rows) > 1:
                    logger.warning(
                        f"[IDENTITY] Multiple active agents with label '{label}': "
                        f"{[str(r['id'])[:12] for r in rows]} — returning most recent"
                    )
                return str(rows[0]["id"]) if rows else None
            except Exception as e:
                logger.debug(f"Failed to find agent by label {label}: {e}")
                return None

    async def get_identity(self, agent_id: str) -> Optional[IdentityRecord]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                       status, parent_agent_id, spawn_reason, disabled_at, metadata
                FROM core.identities
                WHERE agent_id = $1
                """,
                agent_id,
            )
            if not row:
                return None
            return self._row_to_identity(row)

    async def get_identity_by_id(self, identity_id: int) -> Optional[IdentityRecord]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                       status, parent_agent_id, spawn_reason, disabled_at, metadata
                FROM core.identities
                WHERE identity_id = $1
                """,
                identity_id,
            )
            if not row:
                return None
            return self._row_to_identity(row)

    async def list_identities(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[IdentityRecord]:
        async with self.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                           status, parent_agent_id, spawn_reason, disabled_at, metadata
                    FROM core.identities
                    WHERE status = $1
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    status, limit, offset,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                           status, parent_agent_id, spawn_reason, disabled_at, metadata
                    FROM core.identities
                    ORDER BY created_at DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit, offset,
                )
            return [self._row_to_identity(r) for r in rows]

    async def update_identity_status(
        self,
        agent_id: str,
        status: str,
        disabled_at: Optional[datetime] = None,
    ) -> bool:
        async with self.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE core.identities
                SET status = $2, disabled_at = $3, updated_at = now()
                WHERE agent_id = $1
                """,
                agent_id, status, disabled_at,
            )
            return result == "UPDATE 1"

    async def update_identity_metadata(
        self,
        agent_id: str,
        metadata: Dict[str, Any],
        merge: bool = True,
    ) -> bool:
        async with self.acquire() as conn:
            if merge:
                result = await conn.execute(
                    """
                    UPDATE core.identities
                    SET metadata = metadata || $2::jsonb, updated_at = now()
                    WHERE agent_id = $1
                    """,
                    agent_id, json.dumps(metadata),
                )
            else:
                result = await conn.execute(
                    """
                    UPDATE core.identities
                    SET metadata = $2::jsonb, updated_at = now()
                    WHERE agent_id = $1
                    """,
                    agent_id, json.dumps(metadata),
                )
            return "UPDATE 1" in result

    async def increment_update_count(
        self,
        agent_id: str,
        extra_metadata: Dict[str, Any] | None = None,
    ) -> int:
        """Atomically increment total_updates in PostgreSQL and return the new value.

        This is the ONLY way total_updates should be modified. No in-memory
        counter, no batch sync, no merge logic. One atomic SQL operation.

        Args:
            agent_id: Agent identifier
            extra_metadata: Optional additional metadata to merge (e.g., recent_decisions)

        Returns:
            The new total_updates value after increment
        """
        async with self.acquire() as conn:
            # Atomic increment + merge extra metadata in a single statement
            if extra_metadata:
                new_count = await conn.fetchval(
                    """
                    UPDATE core.identities
                    SET metadata = jsonb_set(
                            metadata || $2::jsonb,
                            '{total_updates}',
                            (COALESCE((metadata->>'total_updates')::int, 0) + 1)::text::jsonb
                        ),
                        updated_at = now()
                    WHERE agent_id = $1
                    RETURNING (metadata->>'total_updates')::int
                    """,
                    agent_id, json.dumps(extra_metadata),
                )
            else:
                new_count = await conn.fetchval(
                    """
                    UPDATE core.identities
                    SET metadata = jsonb_set(
                            metadata,
                            '{total_updates}',
                            (COALESCE((metadata->>'total_updates')::int, 0) + 1)::text::jsonb
                        ),
                        updated_at = now()
                    WHERE agent_id = $1
                    RETURNING (metadata->>'total_updates')::int
                    """,
                    agent_id,
                )
            return new_count or 0

    async def verify_api_key(self, agent_id: str, api_key: str) -> bool:
        async with self.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT core.verify_api_key($2, api_key_hash)
                FROM core.identities
                WHERE agent_id = $1
                """,
                agent_id, api_key,
            )
            return bool(result)

    def _row_to_identity(self, row) -> IdentityRecord:
        return IdentityRecord(
            identity_id=row["identity_id"],
            agent_id=row["agent_id"],
            api_key_hash=row["api_key_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=row["status"],
            parent_agent_id=row["parent_agent_id"],
            spawn_reason=row["spawn_reason"],
            disabled_at=row["disabled_at"],
            metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
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
        async with self.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO core.sessions (session_id, identity_id, expires_at, client_type, client_info)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    session_id, identity_id, expires_at, client_type, json.dumps(client_info or {}),
                )
                return True
            except asyncpg.UniqueViolationError:
                return False

    async def get_session(self, session_id: str) -> Optional[SessionRecord]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.session_id, s.identity_id, i.agent_id, s.created_at, s.last_active,
                       s.expires_at, s.is_active, s.client_type, s.client_info, s.metadata
                FROM core.sessions s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.session_id = $1
                """,
                session_id,
            )
            if not row:
                return None
            return self._row_to_session(row)

    async def update_session_activity(self, session_id: str) -> bool:
        from config.governance_config import GovernanceConfig
        ttl_hours = GovernanceConfig.SESSION_TTL_HOURS
        async with self.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE core.sessions
                SET last_active = now(),
                    expires_at = now() + interval '{ttl_hours} hours'
                WHERE session_id = $1 AND is_active = TRUE
                """,
                session_id,
            )
            return "UPDATE 1" in result

    async def end_session(self, session_id: str) -> bool:
        async with self.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE core.sessions
                SET is_active = FALSE
                WHERE session_id = $1
                """,
                session_id,
            )
            return "UPDATE 1" in result

    async def get_active_sessions_for_identity(
        self,
        identity_id: int,
    ) -> List[SessionRecord]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.session_id, s.identity_id, i.agent_id, s.created_at, s.last_active,
                       s.expires_at, s.is_active, s.client_type, s.client_info, s.metadata
                FROM core.sessions s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id = $1 AND s.is_active = TRUE AND s.expires_at > now()
                ORDER BY s.last_active DESC
                """,
                identity_id,
            )
            return [self._row_to_session(r) for r in rows]

    async def cleanup_expired_sessions(self) -> int:
        async with self.acquire() as conn:
            result = await conn.fetchval("SELECT core.cleanup_expired_sessions()")
            return result or 0

    def _row_to_session(self, row) -> SessionRecord:
        return SessionRecord(
            session_id=row["session_id"],
            identity_id=row["identity_id"],
            agent_id=row["agent_id"],
            created_at=row["created_at"],
            last_active=row["last_active"],
            expires_at=row["expires_at"],
            is_active=row["is_active"],
            client_type=row["client_type"],
            client_info=json.loads(row["client_info"]) if isinstance(row["client_info"], str) else row["client_info"],
            metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
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
        void: float,
        regime: str,
        coherence: float,
        state_json: Optional[Dict[str, Any]] = None,
    ) -> int:
        async with self.acquire() as conn:
            state_id = await conn.fetchval(
                """
                INSERT INTO core.agent_state
                    (identity_id, entropy, integrity, stability_index, volatility, regime, coherence, state_json)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING state_id
                """,
                identity_id, entropy, integrity, stability_index, void,  # void maps to volatility column
                regime, coherence, json.dumps(state_json or {}),
            )
            return state_id

    async def get_latest_agent_state(
        self,
        identity_id: int,
    ) -> Optional[AgentStateRecord]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.state_id, s.identity_id, i.agent_id, s.recorded_at,
                       s.entropy, s.integrity, s.stability_index, s.volatility,
                       s.regime, s.coherence, s.state_json
                FROM core.agent_state s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id = $1
                ORDER BY s.recorded_at DESC
                LIMIT 1
                """,
                identity_id,
            )
            if not row:
                return None
            return self._row_to_agent_state(row)

    async def get_agent_state_history(
        self,
        identity_id: int,
        limit: int = 100,
    ) -> List[AgentStateRecord]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.state_id, s.identity_id, i.agent_id, s.recorded_at,
                       s.entropy, s.integrity, s.stability_index, s.volatility,
                       s.regime, s.coherence, s.state_json
                FROM core.agent_state s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id = $1
                ORDER BY s.recorded_at DESC
                LIMIT $2
                """,
                identity_id, limit,
            )
            return [self._row_to_agent_state(r) for r in rows]

    def _row_to_agent_state(self, row) -> AgentStateRecord:
        return AgentStateRecord(
            state_id=row["state_id"],
            identity_id=row["identity_id"],
            agent_id=row["agent_id"],
            recorded_at=row["recorded_at"],
            entropy=row["entropy"],
            integrity=row["integrity"],
            stability_index=row["stability_index"],
            void=row["volatility"],  # Map database column 'volatility' to 'void' field
            regime=row["regime"],
            coherence=row["coherence"],
            state_json=json.loads(row["state_json"]) if isinstance(row["state_json"], str) else row["state_json"],
        )

    # =========================================================================
    # AUDIT OPERATIONS
    # =========================================================================

    async def append_audit_event(self, event: AuditEvent) -> bool:
        async with self.acquire() as conn:
            try:
                # event_id must be passed as UUID object for asyncpg
                # Handle invalid UUID strings gracefully by generating new UUID
                event_id_uuid: uuid.UUID
                if event.event_id:
                    try:
                        event_id_uuid = uuid.UUID(event.event_id)
                    except (ValueError, AttributeError):
                        event_id_uuid = uuid.uuid4()  # Invalid format, generate new
                else:
                    event_id_uuid = uuid.uuid4()

                await conn.execute(
                    """
                    INSERT INTO audit.events (ts, event_id, agent_id, session_id, event_type, confidence, payload, raw_hash)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT DO NOTHING
                    """,
                    event.ts or datetime.now(timezone.utc),
                    event_id_uuid,
                    event.agent_id,
                    event.session_id,
                    event.event_type,
                    event.confidence,
                    json.dumps(event.payload),
                    event.raw_hash,
                )
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
        conditions = []
        params = []
        param_idx = 1

        if agent_id:
            conditions.append(f"agent_id = ${param_idx}")
            params.append(agent_id)
            param_idx += 1
        if event_type:
            conditions.append(f"event_type = ${param_idx}")
            params.append(event_type)
            param_idx += 1
        if start_time:
            conditions.append(f"ts >= ${param_idx}")
            params.append(start_time)
            param_idx += 1
        if end_time:
            conditions.append(f"ts <= ${param_idx}")
            params.append(end_time)
            param_idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_clause = "ASC" if order.lower() == "asc" else "DESC"

        params.append(limit)

        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT ts, event_id, agent_id, session_id, event_type, confidence, payload, raw_hash
                FROM audit.events
                {where_clause}
                ORDER BY ts {order_clause}
                LIMIT ${param_idx}
                """,
                *params,
            )
            return [self._row_to_audit_event(r) for r in rows]

    async def search_audit_events(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[AuditEvent]:
        # Use pg_trgm for fuzzy search on payload
        async with self.acquire() as conn:
            if agent_id:
                rows = await conn.fetch(
                    """
                    SELECT ts, event_id, agent_id, session_id, event_type, confidence, payload, raw_hash
                    FROM audit.events
                    WHERE payload::text ILIKE '%' || $1 || '%' AND agent_id = $2
                    ORDER BY ts DESC
                    LIMIT $3
                    """,
                    query, agent_id, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT ts, event_id, agent_id, session_id, event_type, confidence, payload, raw_hash
                    FROM audit.events
                    WHERE payload::text ILIKE '%' || $1 || '%'
                    ORDER BY ts DESC
                    LIMIT $2
                    """,
                    query, limit,
                )
            return [self._row_to_audit_event(r) for r in rows]

    def _row_to_audit_event(self, row) -> AuditEvent:
        return AuditEvent(
            ts=row["ts"],
            event_id=str(row["event_id"]),
            event_type=row["event_type"],
            agent_id=row["agent_id"],
            session_id=row["session_id"],
            confidence=row["confidence"],
            payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            raw_hash=row["raw_hash"],
        )

    # =========================================================================
    # CALIBRATION OPERATIONS
    # =========================================================================

    async def get_calibration(self) -> Dict[str, Any]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data, updated_at, version FROM core.calibration WHERE id = TRUE"
            )
            if not row:
                return {}
            data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
            data["_updated_at"] = row["updated_at"].isoformat() if row["updated_at"] else None
            data["_version"] = row["version"]
            return data

    async def update_calibration(self, data: Dict[str, Any]) -> bool:
        # Remove internal fields
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}
        async with self.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE core.calibration
                SET data = $1::jsonb, updated_at = now(), version = version + 1
                WHERE id = TRUE
                """,
                json.dumps(clean_data),
            )
            return "UPDATE 1" in result

    # =========================================================================
    # GRAPH OPERATIONS (AGE)
    # =========================================================================

    async def graph_available(self) -> bool:
        """Check if AGE graph queries are available."""
        async with self.acquire() as conn:
            try:
                await conn.execute("LOAD 'age'")
                return True
            except Exception:
                return False

    async def graph_query(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query against the AGE graph.
        
        Parameters are validated and safely interpolated since AGE doesn't support
        parameterized Cypher queries ($1, $2 style).
        """
        async with self.acquire() as conn:
            try:
                await conn.execute("LOAD 'age'")
                await conn.execute(f"SET search_path = ag_catalog, core, audit, public")

                # AGE requires wrapping Cypher in cypher() function
                # Parameters must be embedded in the query (AGE doesn't support $1, $2 for Cypher)
                safe_cypher = cypher
                if params:
                    for k, v in params.items():
                        safe_value = self._sanitize_cypher_param(v)
                        # Use regex to replace only parameter placeholders, not arbitrary ${...} patterns
                        safe_cypher = re.sub(rf'\$\{{{re.escape(k)}\}}', safe_value, safe_cypher)

                rows = await conn.fetch(
                    f"SELECT * FROM cypher('{self._age_graph}', $$ {safe_cypher} $$) as (result agtype)"
                )

                results = []
                for row in rows:
                    # Parse agtype JSON
                    result = row["result"]
                    if isinstance(result, str):
                        # Strip AGE type suffixes (::vertex, ::edge, ::agtype)
                        clean_result = result
                        for suffix in ("::vertex", "::edge", "::agtype"):
                            if clean_result.endswith(suffix):
                                clean_result = clean_result[:-len(suffix)]
                                break
                        try:
                            results.append(json.loads(clean_result))
                        except json.JSONDecodeError:
                            results.append(result)
                    elif isinstance(result, (dict, list)):
                        results.append(result)
                    else:
                        # Handle primitive types (int, float, bool, None)
                        results.append(result)
                return results

            except Exception as e:
                # Log error but don't crash
                return [{"error": str(e)}]

    def _sanitize_cypher_param(self, value: Any) -> str:
        """
        Sanitize a parameter value for safe inclusion in a Cypher query.
        
        AGE doesn't support parameterized queries, so we must validate values.
        """
        if value is None:
            return "NULL"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Validate string doesn't contain injection patterns
            # Allow alphanumeric, underscores, hyphens, spaces, and common punctuation
            if not re.match(r'^[\w\s\-._@/:,()#]+$', value, re.UNICODE):
                # For complex strings, escape single quotes and wrap
                escaped = value.replace("\\", "\\\\").replace("'", "\\'")
                return f"'{escaped}'"
            return f"'{value}'"
        elif isinstance(value, list):
            # Convert to Cypher list syntax: ['a', 'b', 'c']
            # Recursively sanitize each element
            sanitized_elements = [self._sanitize_cypher_param(item) for item in value]
            return f"[{', '.join(sanitized_elements)}]"
        elif isinstance(value, dict):
            # JSON-encode dicts (used for complex properties)
            json_str = json.dumps(value).replace("'", "\\'")
            return f"'{json_str}'"
        else:
            raise ValueError(f"Unsupported Cypher param type: {type(value)}")

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
        async with self.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO audit.tool_usage
                        (ts, agent_id, session_id, tool_name, latency_ms, success, error_type, payload)
                    VALUES (now(), $1, $2, $3, $4, $5, $6, $7)
                    """,
                    agent_id, session_id, tool_name, latency_ms, success, error_type,
                    json.dumps(payload or {}),
                )
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
        conditions = []
        params = []
        param_idx = 1

        if agent_id:
            conditions.append(f"agent_id = ${param_idx}")
            params.append(agent_id)
            param_idx += 1
        if tool_name:
            conditions.append(f"tool_name = ${param_idx}")
            params.append(tool_name)
            param_idx += 1
        if start_time:
            conditions.append(f"ts >= ${param_idx}")
            params.append(start_time)
            param_idx += 1
        if end_time:
            conditions.append(f"ts <= ${param_idx}")
            params.append(end_time)
            param_idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT ts, usage_id, agent_id, session_id, tool_name, latency_ms, success, error_type, payload
                FROM audit.tool_usage
                {where_clause}
                ORDER BY ts DESC
                LIMIT ${param_idx}
                """,
                *params,
            )
            return [
                {
                    "ts": r["ts"],
                    "usage_id": str(r["usage_id"]),
                    "agent_id": r["agent_id"],
                    "session_id": r["session_id"],
                    "tool_name": r["tool_name"],
                    "latency_ms": r["latency_ms"],
                    "success": r["success"],
                    "error_type": r["error_type"],
                    "payload": json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
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
        async with self.acquire() as conn:
            try:
                # Ensure FK targets exist (core.dialectic_sessions.*_agent_id -> core.agents.id).
                # We may not have access to the real api_key here; insert placeholder rows if missing.
                # Later, normal agent creation/upsert will replace empty api_key values.
                await conn.execute(
                    """
                    INSERT INTO core.agents (id, api_key)
                    VALUES ($1, '')
                    ON CONFLICT (id) DO NOTHING
                    """,
                    paused_agent_id,
                )
                if reviewer_agent_id:
                    await conn.execute(
                        """
                        INSERT INTO core.agents (id, api_key)
                        VALUES ($1, '')
                        ON CONFLICT (id) DO NOTHING
                        """,
                        reviewer_agent_id,
                    )

                # Map to new schema: id, session_type, status, paused_agent_id, reviewer_agent_id, etc.
                # Store extra fields in resolution JSONB for backward compatibility
                resolution_data = {}
                if reason:
                    resolution_data["reason"] = reason
                if discovery_id:
                    resolution_data["discovery_id"] = discovery_id
                if dispute_type:
                    resolution_data["dispute_type"] = dispute_type
                if topic:
                    resolution_data["topic"] = topic
                if max_synthesis_rounds is not None:
                    resolution_data["max_synthesis_rounds"] = max_synthesis_rounds
                if synthesis_round is not None:
                    resolution_data["synthesis_round"] = synthesis_round
                if paused_agent_state:
                    resolution_data["paused_agent_state"] = paused_agent_state
                
                # Default session_type to 'review' if not provided
                final_session_type = session_type or "review"
                # Initial status is 'thesis' (matches old 'phase' behavior)
                initial_status = "thesis"
                
                await conn.execute("""
                    INSERT INTO core.dialectic_sessions (
                        session_id, session_type, status, paused_agent_id, reviewer_agent_id,
                        created_at, updated_at, resolution
                    ) VALUES ($1, $2, $3, $4, $5, now(), now(), $6)
                """,
                    session_id,
                    final_session_type,
                    initial_status,
                    paused_agent_id,
                    reviewer_agent_id,
                    json.dumps(resolution_data) if resolution_data else None,
                )
                return {"session_id": session_id, "created": True}
            except Exception as e:
                if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                    return {"session_id": session_id, "created": False, "error": "already_exists"}
                raise

    async def get_dialectic_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        async with self.acquire() as conn:
            # Get session (using 'session_id' as primary key)
            row = await conn.fetchrow("""
                SELECT * FROM core.dialectic_sessions WHERE session_id = $1
            """, session_id)
            if not row:
                return None

            session = dict(row)
            
            # Ensure 'session_id' is present (it should already be there)
            if "session_id" not in session:
                session["session_id"] = session_id
            
            # Map 'status' to 'phase' for backward compatibility (status values match old phase values)
            if "status" in session:
                session["phase"] = session["status"]

            # Parse resolution JSONB and extract backward-compat fields
            if session.get("resolution"):
                resolution = session["resolution"]
                if isinstance(resolution, str):
                    resolution = json.loads(resolution)
                session["resolution"] = resolution
                
                # Extract fields from resolution for backward compatibility
                if isinstance(resolution, dict):
                    if "reason" in resolution:
                        session["reason"] = resolution["reason"]
                    if "discovery_id" in resolution:
                        session["discovery_id"] = resolution["discovery_id"]
                    if "dispute_type" in resolution:
                        session["dispute_type"] = resolution["dispute_type"]
                    if "topic" in resolution:
                        session["topic"] = resolution["topic"]
                    if "max_synthesis_rounds" in resolution:
                        session["max_synthesis_rounds"] = resolution["max_synthesis_rounds"]
                    if "synthesis_round" in resolution:
                        session["synthesis_round"] = resolution["synthesis_round"]
                    if "paused_agent_state" in resolution:
                        session["paused_agent_state"] = resolution["paused_agent_state"]

            # Get messages
            rows = await conn.fetch("""
                SELECT * FROM core.dialectic_messages
                WHERE session_id = $1
                ORDER BY message_id ASC
            """, session_id)

            messages = []
            for msg_row in rows:
                msg = dict(msg_row)
                # Parse JSON fields
                if msg.get("proposed_conditions"):
                    msg["proposed_conditions"] = json.loads(msg["proposed_conditions"]) if isinstance(msg["proposed_conditions"], str) else msg["proposed_conditions"]
                if msg.get("observed_metrics"):
                    msg["observed_metrics"] = json.loads(msg["observed_metrics"]) if isinstance(msg["observed_metrics"], str) else msg["observed_metrics"]
                if msg.get("concerns"):
                    msg["concerns"] = json.loads(msg["concerns"]) if isinstance(msg["concerns"], str) else msg["concerns"]
                messages.append(msg)

            session["messages"] = messages
            return session

    async def get_dialectic_session_by_agent(
        self,
        agent_id: str,
        active_only: bool = True,
    ) -> Optional[Dict[str, Any]]:
        async with self.acquire() as conn:
            # Postgres schema uses lifecycle-ish states in `status` (no 'active' value).
            # "Active" sessions are the in-progress phases.
            if active_only:
                pg_active_statuses = tuple(s for s in ACTIVE_DIALECTIC_STATUSES if s != "active")
                status_filter = "AND status = ANY($2::text[])"
                row = await conn.fetchrow(f"""
                    SELECT session_id FROM core.dialectic_sessions
                    WHERE (paused_agent_id = $1 OR reviewer_agent_id = $1)
                    {status_filter}
                    ORDER BY created_at DESC
                    LIMIT 1
                """, agent_id, list(pg_active_statuses))
            else:
                status_filter = ""
                row = await conn.fetchrow(f"""
                    SELECT session_id FROM core.dialectic_sessions
                    WHERE (paused_agent_id = $1 OR reviewer_agent_id = $1)
                    {status_filter}
                    ORDER BY created_at DESC
                    LIMIT 1
                """, agent_id)
            if row:
                return await self.get_dialectic_session(row["session_id"])
            return None

    async def get_all_active_dialectic_sessions_for_agent(
        self,
        agent_id: str,
    ) -> List[Dict[str, Any]]:
        """Get all active sessions where agent is paused agent or reviewer."""
        async with self.acquire() as conn:
            pg_active_statuses = tuple(s for s in ACTIVE_DIALECTIC_STATUSES if s != "active")
            rows = await conn.fetch("""
                SELECT session_id FROM core.dialectic_sessions
                WHERE (paused_agent_id = $1 OR reviewer_agent_id = $1)
                AND status = ANY($2::text[])
                ORDER BY created_at DESC
            """, agent_id, list(pg_active_statuses))
            
            sessions = []
            for row in rows:
                session = await self.get_dialectic_session(row["session_id"])
                if session:
                    sessions.append(session)
            return sessions

    async def update_dialectic_session_phase(
        self,
        session_id: str,
        phase: str,
    ) -> bool:
        async with self.acquire() as conn:
            # Map 'phase' to 'status' (they're the same in new schema)
            result = await conn.execute("""
                UPDATE core.dialectic_sessions
                SET status = $1, updated_at = now()
                WHERE id = $2
            """, phase, session_id)
            return "UPDATE 1" in result

    async def update_dialectic_session_reviewer(
        self,
        session_id: str,
        reviewer_agent_id: str,
    ) -> bool:
        async with self.acquire() as conn:
            result = await conn.execute("""
                UPDATE core.dialectic_sessions
                SET reviewer_agent_id = $1, updated_at = now()
                WHERE id = $2
            """, reviewer_agent_id, session_id)
            return "UPDATE 1" in result

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
        async with self.acquire() as conn:
            message_id = await conn.fetchval("""
                INSERT INTO core.dialectic_messages (
                    session_id, agent_id, message_type, timestamp,
                    root_cause, proposed_conditions, reasoning,
                    observed_metrics, concerns, agrees, signature
                ) VALUES ($1, $2, $3, now(), $4, $5, $6, $7, $8, $9, $10)
                RETURNING message_id
            """,
                session_id,
                agent_id,
                message_type,
                root_cause,
                json.dumps(proposed_conditions) if proposed_conditions else None,
                reasoning,
                json.dumps(observed_metrics) if observed_metrics else None,
                json.dumps(concerns) if concerns else None,
                agrees,
                signature,
            )

            # Update session timestamp
            await conn.execute("""
                UPDATE core.dialectic_sessions SET updated_at = now() WHERE session_id = $1
            """, session_id)

            return message_id

    async def resolve_dialectic_session(
        self,
        session_id: str,
        resolution: Dict[str, Any],
        status: str = "resolved",
    ) -> bool:
        async with self.acquire() as conn:
            result = await conn.execute("""
                UPDATE core.dialectic_sessions
                SET status = $1, resolution = $2, resolved_at = now(), updated_at = now()
                WHERE session_id = $3
            """,
                status,
                json.dumps(resolution),
                session_id,
            )
            return "UPDATE 1" in result

    async def is_agent_in_active_dialectic_session(self, agent_id: str) -> bool:
        async with self.acquire() as conn:
            pg_active_statuses = tuple(s for s in ACTIVE_DIALECTIC_STATUSES if s != "active")
            result = await conn.fetchval("""
                SELECT 1 FROM core.dialectic_sessions
                WHERE (paused_agent_id = $1 OR reviewer_agent_id = $1)
                AND status = ANY($2::text[])
                LIMIT 1
            """, agent_id, list(pg_active_statuses))
            return result is not None

    async def get_pending_dialectic_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get dialectic sessions awaiting a reviewer (reviewer_agent_id IS NULL).

        Used for pull-based discovery: agents check for pending reviews on status().

        Returns:
            List of pending sessions with basic info (session_id, paused_agent_id, reason, created_at)
        """
        async with self.acquire() as conn:
            # Get sessions that are awaiting a reviewer (reviewer_agent_id IS NULL)
            # Status must be 'pending' or 'thesis' (sessions that haven't progressed yet)
            #
            # NOTE: Schema uses `session_id` as primary key.
            # Some schemas may not include `resolution` or `session_type`.
            # We progressively degrade the SELECT to keep the feature non-fatal.
            try:
                rows = await conn.fetch("""
                    SELECT session_id, paused_agent_id, session_type, status,
                           created_at, resolution
                    FROM core.dialectic_sessions
                    WHERE reviewer_agent_id IS NULL
                    AND status IN ('pending', 'thesis')
                    ORDER BY created_at ASC
                    LIMIT $1
                """, limit)
                id_key = "session_id"
            except Exception as e:
                # Fallback for schemas without all columns
                try:
                    rows = await conn.fetch("""
                        SELECT session_id, paused_agent_id, status, created_at
                        FROM core.dialectic_sessions
                        WHERE reviewer_agent_id IS NULL
                        AND status IN ('pending', 'thesis')
                        ORDER BY created_at ASC
                        LIMIT $1
                    """, limit)
                    id_key = "session_id"
                except Exception:
                    # Degrade: no resolution column
                    try:
                        rows = await conn.fetch("""
                            SELECT session_id, paused_agent_id, session_type, status,
                                   created_at
                            FROM core.dialectic_sessions
                            WHERE reviewer_agent_id IS NULL
                            AND status IN ('pending', 'thesis')
                            ORDER BY created_at ASC
                            LIMIT $1
                        """, limit)
                        id_key = "session_id"
                    except Exception:
                        # Final fallback: minimal columns only
                        rows = await conn.fetch("""
                            SELECT session_id, paused_agent_id, status, created_at
                            FROM core.dialectic_sessions
                            WHERE reviewer_agent_id IS NULL
                            AND status IN ('pending', 'thesis')
                            ORDER BY created_at ASC
                            LIMIT $1
                        """, limit)
                        id_key = "session_id"

            sessions = []
            for row in rows:
                session = {
                    "session_id": row[id_key],  # Normalize PK for compatibility
                    "paused_agent_id": row["paused_agent_id"],
                    "session_type": row.get("session_type"),
                    "phase": row["status"],  # Map 'status' to 'phase' for compatibility
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
                # Extract reason and other fields from resolution JSONB
                resolution_val = row.get("resolution") if hasattr(row, "get") else None
                if resolution_val:
                    resolution = resolution_val
                    if isinstance(resolution, str):
                        resolution = json.loads(resolution)
                    if isinstance(resolution, dict):
                        # Extract reason if available
                        if "reason" in resolution:
                            session["reason"] = resolution["reason"]
                        # Include other fields that might be useful
                        if "discovery_id" in resolution:
                            session["discovery_id"] = resolution["discovery_id"]
                        if "dispute_type" in resolution:
                            session["dispute_type"] = resolution["dispute_type"]
                        if "topic" in resolution:
                            session["topic"] = resolution["topic"]
                sessions.append(session)

            return sessions

    # =========================================================================
    # Knowledge Graph (PostgreSQL FTS)
    # =========================================================================

    async def kg_add_discovery(self, discovery) -> None:
        """Add a discovery to the knowledge graph."""
        from datetime import datetime as dt

        async with self.acquire() as conn:
            # Handle response_to
            response_to_id = None
            response_type = None
            if hasattr(discovery, 'response_to') and discovery.response_to:
                response_to_id = discovery.response_to.discovery_id
                response_type = discovery.response_to.response_type

            # Parse timestamp string to datetime
            created_at = None
            if hasattr(discovery, 'timestamp') and discovery.timestamp:
                ts = discovery.timestamp
                if isinstance(ts, str):
                    # Try parsing ISO format
                    try:
                        created_at = dt.fromisoformat(ts.replace('Z', '+00:00'))
                    except ValueError:
                        created_at = dt.now()
                elif isinstance(ts, dt):
                    created_at = ts
                else:
                    created_at = dt.now()

            await conn.execute("""
                INSERT INTO knowledge.discoveries (
                    id, agent_id, type, summary, details, tags, severity, status,
                    references_files, related_to, response_to_id, response_type,
                    provenance, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (id) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    details = EXCLUDED.details,
                    tags = EXCLUDED.tags,
                    status = EXCLUDED.status,
                    updated_at = now()
            """,
                discovery.id,
                discovery.agent_id,
                discovery.type,
                discovery.summary,
                discovery.details or "",
                discovery.tags or [],
                discovery.severity or "low",
                discovery.status or "open",
                discovery.references_files or [],
                discovery.related_to or [],
                response_to_id,
                response_type,
                json.dumps(discovery.provenance) if discovery.provenance else None,
                created_at,
            )

    async def kg_query(
        self,
        agent_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query discoveries with filters."""
        async with self.acquire() as conn:
            conditions = []
            params = []
            param_idx = 1

            if agent_id:
                conditions.append(f"agent_id = ${param_idx}")
                params.append(agent_id)
                param_idx += 1
            if type:
                conditions.append(f"type = ${param_idx}")
                params.append(type)
                param_idx += 1
            if severity:
                conditions.append(f"severity = ${param_idx}")
                params.append(severity)
                param_idx += 1
            if status:
                conditions.append(f"status = ${param_idx}")
                params.append(status)
                param_idx += 1
            if tags:
                conditions.append(f"tags && ${param_idx}")
                params.append(tags)
                param_idx += 1

            where_clause = " AND ".join(conditions) if conditions else "1=1"
            params.append(limit)

            rows = await conn.fetch(f"""
                SELECT * FROM knowledge.discoveries
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ${param_idx}
            """, *params)

            return [self._row_to_discovery_dict(row) for row in rows]

    async def kg_full_text_search(
        self,
        query: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Full-text search using PostgreSQL tsvector."""
        async with self.acquire() as conn:
            # Use websearch_to_tsquery for natural language queries
            rows = await conn.fetch("""
                SELECT *, ts_rank(search_vector, websearch_to_tsquery('english', $1)) as rank
                FROM knowledge.discoveries
                WHERE search_vector @@ websearch_to_tsquery('english', $1)
                ORDER BY rank DESC, created_at DESC
                LIMIT $2
            """, query, limit)

            return [self._row_to_discovery_dict(row) for row in rows]

    async def kg_find_similar(
        self,
        discovery_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Find similar discoveries by tag overlap."""
        async with self.acquire() as conn:
            # First get the source tags
            source_row = await conn.fetchrow(
                "SELECT tags FROM knowledge.discoveries WHERE id = $1",
                discovery_id
            )
            if not source_row or not source_row['tags']:
                return []

            source_tags = source_row['tags']

            # Find similar by tag overlap using array containment
            rows = await conn.fetch("""
                SELECT d.*,
                       cardinality(ARRAY(SELECT unnest(d.tags) INTERSECT SELECT unnest($1::text[]))) as overlap
                FROM knowledge.discoveries d
                WHERE d.id != $2
                  AND d.tags && $1::text[]
                ORDER BY overlap DESC, created_at DESC
                LIMIT $3
            """, source_tags, discovery_id, limit)

            return [self._row_to_discovery_dict(row) for row in rows]

    async def kg_get_discovery(self, discovery_id: str) -> Optional[Dict[str, Any]]:
        """Get a single discovery by ID."""
        async with self.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM knowledge.discoveries WHERE id = $1
            """, discovery_id)

            if row:
                return self._row_to_discovery_dict(row)
            return None

    async def kg_update_status(
        self,
        discovery_id: str,
        status: str,
        resolved_at: Optional[str] = None,
    ) -> bool:
        """Update discovery status."""
        async with self.acquire() as conn:
            if resolved_at:
                result = await conn.execute("""
                    UPDATE knowledge.discoveries
                    SET status = $1, resolved_at = $2, updated_at = now()
                    WHERE id = $3
                """, status, resolved_at, discovery_id)
            else:
                result = await conn.execute("""
                    UPDATE knowledge.discoveries
                    SET status = $1, updated_at = now()
                    WHERE id = $2
                """, status, discovery_id)
            return "UPDATE 1" in result

    def _row_to_discovery_dict(self, row) -> Dict[str, Any]:
        """Convert a database row to discovery dict."""
        d = dict(row)
        # Convert timestamps to ISO strings
        for ts_field in ['created_at', 'updated_at', 'resolved_at']:
            if d.get(ts_field):
                d[ts_field] = d[ts_field].isoformat()
        # Map created_at to timestamp for compatibility
        if 'created_at' in d:
            d['timestamp'] = d['created_at']
        # Parse provenance JSON
        if d.get('provenance') and isinstance(d['provenance'], str):
            d['provenance'] = json.loads(d['provenance'])
        # Remove internal fields
        d.pop('search_vector', None)
        d.pop('rank', None)
        d.pop('overlap', None)
        return d
