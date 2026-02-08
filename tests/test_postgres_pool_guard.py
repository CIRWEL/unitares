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
        from src.db.postgres_backend import PostgresBackend

        backend = PostgresBackend()
        mock_pool = MagicMock()
        backend._pool = mock_pool

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

        assert backend._pool is mock_pool

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

        assert result is mock_pool
        assert backend._pool is mock_pool


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
