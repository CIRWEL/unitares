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

    @pytest.mark.asyncio
    async def test_null_before_close_releases_lock_when_close_hangs(self):
        """The recovery path's null-before-close + bounded wait_for: when
        the failed pool's close() hangs (executor-loop-wedged scenario,
        observed live 2026-04-27), _init_lock must be released within the
        bounded timeout so concurrent acquires take the slow-path create
        branch instead of blocking forever.

        Pre-fix sequence: lock held → close hangs → next acquire 5s-times
        out → reschedules close → cascading wedge.
        Post-fix: pool nulled first, close timeout-bounds, lock released,
        slow-path proceeds.
        """
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()

        # Build a failing-health-check pool whose close() never resolves.
        failing_pool = MagicMock()

        class _FailingAcquire:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                raise asyncio.TimeoutError()
            async def __aexit__(self, *exc):
                return False

        failing_pool.acquire = MagicMock(
            side_effect=lambda **kw: _FailingAcquire()
        )

        # close() that hangs forever — the wedged-executor signature.
        async def hung_close():
            await asyncio.sleep(3600)

        failing_pool.close = hung_close
        failing_pool.get_size = MagicMock(return_value=5)
        failing_pool.get_max_size = MagicMock(return_value=25)

        backend._pool = failing_pool
        backend._last_pool_check = 0.0

        # Shrink production 10s timeout to 0.5s for fast test.
        import src.db.postgres_backend as pg_mod
        original_close_timeout = pg_mod.POOL_CLOSE_TIMEOUT_SECONDS
        pg_mod.POOL_CLOSE_TIMEOUT_SECONDS = 0.5

        new_raw_pool = AsyncMock()
        try:
            with patch(
                "asyncpg.create_pool",
                new_callable=AsyncMock,
                return_value=new_raw_pool,
            ):
                # Bounded wall-clock: the whole recovery (including the
                # hung close timing out + recreate) must finish well under
                # the pre-fix forever-wait. 8s gives slack above the 0.5s
                # close + 2s thread-join + asyncpg.create_pool latency.
                result = await asyncio.wait_for(
                    backend._ensure_pool(), timeout=8.0,
                )
        finally:
            pg_mod.POOL_CLOSE_TIMEOUT_SECONDS = original_close_timeout

        # Backend now points at the freshly-created pool — proves the
        # slow-path recreate ran after the bounded close.
        from src.db.executor_pool import ExecutorPool
        assert isinstance(result, ExecutorPool)
        assert result._raw_pool is new_raw_pool
        assert backend._pool is result
        # _init_lock must be released (we just acquired+released it via
        # the slow-path; if it were still held this assertion proves
        # nothing, but the asyncio.wait_for(timeout=8) above is the real
        # gate — if the lock were stuck, that timeout would have fired).
        assert not backend._init_lock.locked()

    @pytest.mark.asyncio
    async def test_ensure_pool_recovers_with_real_executor_pool_wedged(self):
        """End-to-end test: the recovery path must release _init_lock
        when wrapping a REAL ExecutorPool whose underlying raw_pool.close()
        hangs. The previous test used a MagicMock pool which bypasses the
        cross-loop bridge — the production wedge has TWO nested wait_for
        calls (postgres_backend → ExecutorPool), and a MagicMock test
        only exercises one. (Council finding from feature-dev:code-reviewer.)
        """
        from src.db.postgres_backend import PostgresBackend
        from src.db.executor_pool import ExecutorPool
        import src.db.executor_pool as ep_mod
        import src.db.postgres_backend as pg_mod

        backend = PostgresBackend()

        # Real raw_pool whose close() hangs forever. Wrap in a real
        # ExecutorPool so close() goes through _await_on_loop's
        # cross-thread schedule.
        async def hung_raw_close():
            await asyncio.sleep(3600)

        async def fail_acquire(**kw):
            raise asyncio.TimeoutError()

        raw_pool = MagicMock()
        raw_pool.close = hung_raw_close

        class _FailingAcquire:
            def __init__(self, *a, **kw):
                pass
            async def __aenter__(self):
                raise asyncio.TimeoutError()
            async def __aexit__(self, *exc):
                return False

        raw_pool.acquire = MagicMock(
            side_effect=lambda **kw: _FailingAcquire()
        )
        raw_pool.get_size = MagicMock(return_value=5)
        raw_pool.get_max_size = MagicMock(return_value=25)

        wedged_executor_pool = ExecutorPool(raw_pool)
        backend._pool = wedged_executor_pool
        backend._last_pool_check = 0.0

        # Shrink BOTH timeouts so the test runs fast.
        # Production: 10s (postgres_backend) + 10s (ExecutorPool).
        original_pg_timeout = pg_mod.POOL_CLOSE_TIMEOUT_SECONDS
        original_ep_timeout = ep_mod.CLOSE_TIMEOUT_SECONDS
        original_join = ep_mod.THREAD_JOIN_TIMEOUT_SECONDS
        pg_mod.POOL_CLOSE_TIMEOUT_SECONDS = 1.0
        ep_mod.CLOSE_TIMEOUT_SECONDS = 0.5
        ep_mod.THREAD_JOIN_TIMEOUT_SECONDS = 0.5

        new_raw_pool = AsyncMock()
        try:
            with patch(
                "asyncpg.create_pool",
                new_callable=AsyncMock,
                return_value=new_raw_pool,
            ):
                # Must finish well under the pre-fix forever-wait. The
                # outer 8s gate proves both nested timeouts fired and
                # _init_lock was released.
                result = await asyncio.wait_for(
                    backend._ensure_pool(), timeout=8.0,
                )
        finally:
            pg_mod.POOL_CLOSE_TIMEOUT_SECONDS = original_pg_timeout
            ep_mod.CLOSE_TIMEOUT_SECONDS = original_ep_timeout
            ep_mod.THREAD_JOIN_TIMEOUT_SECONDS = original_join

        # Recovery succeeded: backend points at a fresh ExecutorPool
        # wrapping new_raw_pool, and _init_lock is released.
        assert isinstance(result, ExecutorPool)
        assert result is not wedged_executor_pool
        assert backend._pool is result
        assert not backend._init_lock.locked()
        # The wedged pool's close was at least started (close_done set).
        assert wedged_executor_pool._closed_flag is True

    @pytest.mark.asyncio
    async def test_executor_pool_close_is_idempotent_and_serialized(self):
        """Two concurrent close() callers must serialize: the second
        awaits the first's completion via _close_done, not return early
        while raw_pool.close() is still in flight (council finding:
        TOCTOU race on _closed_flag).
        """
        from src.db.executor_pool import ExecutorPool

        # Slow but completing close — 0.2s.
        close_started = asyncio.Event()
        close_finished = asyncio.Event()

        async def slow_close():
            close_started.set()
            await asyncio.sleep(0.2)
            close_finished.set()

        raw_pool = MagicMock()
        raw_pool.close = slow_close

        wrapped = ExecutorPool(raw_pool)

        # Fire two concurrent close() calls.
        results = await asyncio.gather(
            wrapped.close(),
            wrapped.close(),
            return_exceptions=True,
        )

        for r in results:
            assert not isinstance(r, Exception), f"unexpected: {r!r}"

        # Both callers returned only after raw_pool.close() finished.
        # close_finished.is_set() must be True at this point.
        assert close_finished.is_set(), (
            "second caller returned before raw_pool.close() completed — "
            "TOCTOU race regressed"
        )
        assert wrapped._closed_flag is True
        assert wrapped._close_done.is_set()


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


# ============================================================================
# _TransactionContext Acquire-then-Fail Tests
# ============================================================================

class TestTransactionContextLeakSafety:
    """Test that transaction() releases the underlying connection when
    txn-start raises after the inner acquire succeeded. Pre-fix: __aenter__
    raised before returning, so the outer 'async with' never invoked
    __aexit__, and the connection was leaked until GC reclaimed it. Under
    the wedged-executor symptom class this branch fixes, that contributed
    to "Exceeded concurrency limit" warnings observed live 2026-04-27.
    """

    @pytest.mark.asyncio
    async def test_txn_start_failure_releases_connection(self):
        """If conn.transaction().start() raises, the inner acquire's
        __aexit__ must run so the connection returns to the pool."""
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        # transaction() returns a Transaction whose start() raises.
        failing_txn = MagicMock()
        failing_txn.start = AsyncMock(side_effect=RuntimeError("server hangup"))
        mock_conn.transaction = MagicMock(return_value=failing_txn)

        backend._pool = mock_pool

        with pytest.raises(RuntimeError, match="server hangup"):
            async with backend.transaction():
                pytest.fail("body should not execute when __aenter__ raises")

        # The acquired connection MUST be released back to the pool.
        mock_pool.release.assert_called_once_with(mock_conn)

    @pytest.mark.asyncio
    async def test_txn_start_cancelled_releases_connection(self):
        """CancelledError is the realistic wedge trigger (BaseException in
        3.8+). The fix catches BaseException, not just Exception, so the
        conn is still released when start() is cancelled mid-flight."""
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        failing_txn = MagicMock()
        failing_txn.start = AsyncMock(side_effect=asyncio.CancelledError())
        mock_conn.transaction = MagicMock(return_value=failing_txn)

        backend._pool = mock_pool

        with pytest.raises(asyncio.CancelledError):
            async with backend.transaction():
                pytest.fail("body should not execute when __aenter__ raises")

        mock_pool.release.assert_called_once_with(mock_conn)

    @pytest.mark.asyncio
    async def test_release_failure_does_not_mask_original_error(self):
        """If conn release also fails after a txn-start failure, the
        ORIGINAL txn-start error must still propagate — the release
        warning is logged, not raised."""
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock(side_effect=RuntimeError("release failed"))

        failing_txn = MagicMock()
        failing_txn.start = AsyncMock(side_effect=RuntimeError("original txn-start failure"))
        mock_conn.transaction = MagicMock(return_value=failing_txn)

        backend._pool = mock_pool

        # The ORIGINAL error wins; the release error is swallowed.
        with pytest.raises(RuntimeError, match="original txn-start failure"):
            async with backend.transaction():
                pytest.fail("body should not execute when __aenter__ raises")
