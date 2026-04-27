"""
Tests for PostgreSQL pool initialization guard and connection recovery.

Feb 2026 fixes:
- init() guard: don't recreate pool if it already exists
- acquire() tracks which pool a connection was acquired from
- Orphaned connections (from old pool) are closed directly instead of released
"""

import asyncio
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# init() Guard Tests
# ============================================================================

class TestInitGuard:
    """Test that init() does not recreate pool when one already exists."""

    @pytest.mark.asyncio
    async def test_init_skips_when_pool_exists(self):
        """init() should be a no-op when pool already exists."""
        import time
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()
        mock_pool = MagicMock()
        backend._pool = mock_pool
        backend._last_pool_check = time.time()  # Prevent health check from firing

        with patch("asyncpg.create_pool", new_callable=AsyncMock) as create:
            await backend.init()
            # create_pool should NOT have been called
            create.assert_not_called()

        # Pool should be unchanged
        assert backend._pool is mock_pool

    @pytest.mark.asyncio
    async def test_init_creates_pool_when_none(self):
        """init() should create pool when none exists."""
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()
        assert backend._pool is None

        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=True)
        mock_conn.execute = AsyncMock()
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            await backend.init()

        # _create_pool() now wraps the asyncpg pool in ExecutorPool — handlers
        # see the wrapper, but the underlying asyncpg pool is preserved.
        from src.db.executor_pool import ExecutorPool
        assert isinstance(backend._pool, ExecutorPool)
        assert backend._pool._raw_pool is mock_pool

    @pytest.mark.asyncio
    async def test_init_idempotent_across_calls(self):
        """Multiple init() calls should only create pool once."""
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=True)
        mock_conn.execute = AsyncMock()
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool) as create:
            await backend.init()
            await backend.init()
            await backend.init()
            # Should only be called once
            assert create.call_count == 1


# ============================================================================
# Pool Recovery Tests
# ============================================================================

class TestPoolRecovery:
    """Test pool recovery after close() or health check failure."""

    @pytest.mark.asyncio
    async def test_close_sets_pool_to_none(self):
        """close() should set pool to None."""
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()
        mock_pool = AsyncMock()
        backend._pool = mock_pool

        await backend.close()
        assert backend._pool is None

    @pytest.mark.asyncio
    async def test_ensure_pool_creates_after_close(self):
        """_ensure_pool() should recreate pool after close()."""
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()
        backend._pool = None  # Simulate post-close state

        mock_pool = AsyncMock()
        with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            result = await backend._ensure_pool()

        # Wrapped in ExecutorPool — see _create_pool() and src/db/executor_pool.py
        from src.db.executor_pool import ExecutorPool
        assert isinstance(result, ExecutorPool)
        assert result._raw_pool is mock_pool
        assert backend._pool is result

    @pytest.mark.asyncio
    async def test_concurrent_failing_health_checks_log_destroy_once(self, caplog):
        """N concurrent failing health checks must produce ONE destroy log,
        not N. The log must fire inside the lock + after a pool-identity
        re-check, otherwise log fan-in misrepresents the destroy count by
        the concurrency factor (observed 2026-04-27 as 1158:23 ratio).
        """
        import logging
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()

        # Mock pool whose health-check acquire raises (the production trigger
        # is asyncio.TimeoutError when all conns are checked out by slow handlers).
        failing_pool = MagicMock()

        class _FailingAcquire:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                raise asyncio.TimeoutError()

            async def __aexit__(self, *exc):
                return False

        failing_pool.acquire = MagicMock(side_effect=lambda **kw: _FailingAcquire())
        failing_pool.close = AsyncMock()
        failing_pool.get_size = MagicMock(return_value=5)
        failing_pool.get_max_size = MagicMock(return_value=25)

        backend._pool = failing_pool
        # Force the health check to fire (last_pool_check older than 60s).
        backend._last_pool_check = 0.0

        # Mock asyncpg.create_pool so the slow path can recreate without a real DB.
        new_raw_pool = AsyncMock()
        with caplog.at_level(logging.WARNING, logger="src.db.postgres_backend"):
            with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=new_raw_pool):
                # Fire 8 concurrent health-check-failing _ensure_pool calls.
                results = await asyncio.gather(
                    *(backend._ensure_pool() for _ in range(8)),
                    return_exceptions=True,
                )

        # All callers must have gotten the recreated pool back.
        for r in results:
            assert not isinstance(r, Exception), f"unexpected exception: {r!r}"

        destroy_logs = [
            rec for rec in caplog.records
            if "Pool health check failed, destroying pool" in rec.message
        ]
        # Exactly one destroy event regardless of fan-in.
        assert len(destroy_logs) == 1, (
            f"expected exactly 1 destroy log, got {len(destroy_logs)}: "
            f"{[r.message for r in destroy_logs]}"
        )
        # close() on the failing pool happened exactly once.
        assert failing_pool.close.await_count == 1
        # Backend now points at the freshly-created pool.
        from src.db.executor_pool import ExecutorPool
        assert isinstance(backend._pool, ExecutorPool)
        assert backend._pool._raw_pool is new_raw_pool


# ============================================================================
# Orphaned Connection Tests
# ============================================================================

class TestOrphanedConnectionHandling:
    """Test that connections from old pools are handled correctly."""

    @pytest.mark.asyncio
    async def test_release_to_same_pool(self):
        """Connection should be released to the pool it came from."""
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        backend._pool = mock_pool

        ctx = backend.acquire()
        async with ctx as conn:
            assert conn is mock_conn

        # Connection should have been released to the same pool
        mock_pool.release.assert_called_once_with(mock_conn)

    @pytest.mark.asyncio
    async def test_orphan_connection_closed_on_pool_change(self):
        """If pool was recreated mid-operation, orphan connection should be closed."""
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()
        old_pool = AsyncMock()
        new_pool = AsyncMock()
        mock_conn = AsyncMock()
        old_pool.acquire = AsyncMock(return_value=mock_conn)

        backend._pool = old_pool

        ctx = backend.acquire()
        conn = await ctx.__aenter__()
        assert conn is mock_conn

        # Simulate pool recreation mid-operation
        backend._pool = new_pool

        await ctx.__aexit__(None, None, None)

        # Connection should NOT have been released to old pool
        old_pool.release.assert_not_called()
        # Connection should have been closed directly
        mock_conn.close.assert_called_once()
