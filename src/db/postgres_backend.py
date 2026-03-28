"""
PostgreSQL + AGE Backend

Async PostgreSQL backend using asyncpg with Apache AGE for graph queries.
Methods are organized into mixin modules under src/db/mixins/.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, Optional

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore

from .base import DatabaseBackend
from .mixins import (
    IdentityMixin,
    AgentMixin,
    SessionMixin,
    StateMixin,
    AuditMixin,
    CalibrationMixin,
    GraphMixin,
    ToolUsageMixin,
    DialecticMixin,
    KnowledgeGraphMixin,
    BaselineMixin,
    ThreadMixin,
)
from src.logging_utils import get_logger

logger = get_logger(__name__)


class PostgresBackend(
    IdentityMixin,
    AgentMixin,
    SessionMixin,
    StateMixin,
    AuditMixin,
    CalibrationMixin,
    GraphMixin,
    ToolUsageMixin,
    DialecticMixin,
    KnowledgeGraphMixin,
    BaselineMixin,
    ThreadMixin,
    DatabaseBackend,
):
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
        self._init_lock = asyncio.Lock()
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
                    # Health check failed — acquire lock before destroying pool
                    # to prevent race with concurrent _ensure_pool / init calls
                    logger.warning(f"Pool health check failed, destroying pool (backend={id(self)}): {e}")
                    async with self._init_lock:
                        # Only destroy if still the same pool (another task may have already replaced it)
                        if self._pool is not None:
                            try:
                                await self._pool.close()
                            except Exception:
                                pass
                            self._pool = None

        if self._pool is not None:
            return self._pool

        # Slow path: need to create pool
        # Use lock to prevent multiple concurrent pool creations
        async with self._init_lock:
            # Double-check after acquiring lock
            if self._pool is not None:
                return self._pool

            self._pool = await self._create_pool()
            self._last_pool_check = time.time()
            logger.info("PostgreSQL connection pool created")
            return self._pool

    async def _create_pool(self):
        """Create a new connection pool. Caller must hold _init_lock."""
        logger.info("Creating PostgreSQL connection pool...")
        try:
            return await asyncio.wait_for(
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
            raise ConnectionError(
                f"Failed to connect to PostgreSQL at {self._db_url}: {e}. "
                f"Is PostgreSQL running?"
            ) from e

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

    def transaction(self, timeout: float = None):
        """
        Get a connection from the pool wrapped in an explicit transaction.

        Usage:
            async with self.transaction() as conn:
                await conn.execute("INSERT ...")
                await conn.execute("UPDATE ...")
                # auto-commits on exit, auto-rollbacks on exception

        This provides atomicity for multi-statement operations. The
        connection is acquired via acquire() (preserving pool orphan
        protection) and wrapped in asyncpg's conn.transaction().
        """
        class _TransactionContext:
            def __init__(ctx_self, backend, timeout):
                ctx_self.backend = backend
                ctx_self.timeout = timeout
                ctx_self._acquire_ctx = None
                ctx_self._txn = None
                ctx_self.conn = None

            async def __aenter__(ctx_self):
                ctx_self._acquire_ctx = ctx_self.backend.acquire(timeout=ctx_self.timeout)
                ctx_self.conn = await ctx_self._acquire_ctx.__aenter__()
                ctx_self._txn = ctx_self.conn.transaction()
                await ctx_self._txn.start()
                return ctx_self.conn

            async def __aexit__(ctx_self, exc_type, exc_val, exc_tb):
                commit_error = None
                try:
                    if exc_type is not None:
                        await ctx_self._txn.rollback()
                    else:
                        await ctx_self._txn.commit()
                except Exception as e:
                    logger.error(f"Transaction {'rollback' if exc_type else 'commit'} failed: {e}")
                    if exc_type is None:
                        # Commit failed — surface this so callers know the write was lost
                        commit_error = e
                finally:
                    # Release connection back to pool
                    await ctx_self._acquire_ctx.__aexit__(exc_type, exc_val, exc_tb)
                if commit_error is not None:
                    raise commit_error
                return False

        return _TransactionContext(self, timeout)

    async def init(self) -> None:
        """Initialize connection pool and verify schema."""
        already_existed = self._pool is not None
        # Delegate pool creation to _ensure_pool (handles locking, dedup)
        await self._ensure_pool()

        # Skip schema verification if pool already existed (already verified)
        if already_existed:
            return

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
            # Single query for schema version and counts (also proves connectivity)
            row = await conn.fetchrow("""
                SELECT
                    (SELECT MAX(version) FROM core.schema_migrations) AS schema_version,
                    (SELECT COUNT(*) FROM core.identities) AS identity_count,
                    (SELECT COUNT(*) FROM core.sessions WHERE is_active = TRUE) AS active_session_count
            """)
            version = row["schema_version"]
            identity_count = row["identity_count"]
            session_count = row["active_session_count"]

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
                "pool_idle": self._pool.get_idle_size(),
                "pool_free": self._pool.get_idle_size(),  # Alias for compatibility
                "pool_max": self._pool.get_max_size(),
                "schema_version": version,
                "identity_count": identity_count,
                "active_session_count": session_count,
                "age_available": age_available,
                "age_graph": self._age_graph if age_available else None,
            }
