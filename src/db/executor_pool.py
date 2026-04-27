"""
ExecutorPool — wraps asyncpg.Pool so DB operations run on a dedicated
background thread with its own asyncio event loop.

Why: docs/handoffs/2026-04-27-anyio-followup-scope.md. The MCP SDK's anyio
task group conflicts with asyncpg/Redis cancellation semantics. Running
asyncpg coroutines on a separate event loop (in a separate thread) means
the anyio context never sees an asyncpg await — only a future from the
caller's loop, which anyio handles cleanly.

Caller surface is unchanged: handlers still write
    async with db.acquire() as conn:
        await conn.fetchval(...)
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any


async def _await_on_loop(coro: Any, loop: asyncio.AbstractEventLoop) -> Any:
    """Schedule a coroutine on `loop` (a different thread's loop) and await its result."""
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return await asyncio.wrap_future(future)


class _Transaction:
    """
    Wraps an asyncpg transaction so __aenter__/__aexit__ both round-trip
    to the executor loop. asyncpg connections are loop-bound — a transaction
    started on one loop and committed on another silently corrupts.
    """

    def __init__(self, raw_txn: Any, loop: asyncio.AbstractEventLoop):
        self._raw = raw_txn
        self._loop = loop

    async def __aenter__(self) -> Any:
        return await _await_on_loop(self._raw.__aenter__(), self._loop)

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Any:
        return await _await_on_loop(
            self._raw.__aexit__(exc_type, exc_val, exc_tb), self._loop
        )


class _Connection:
    """Wraps an asyncpg Connection, dispatching all calls to the executor loop."""

    def __init__(self, raw_conn: Any, loop: asyncio.AbstractEventLoop):
        self._raw = raw_conn
        self._loop = loop

    async def fetchval(self, *args: Any, **kwargs: Any) -> Any:
        return await _await_on_loop(self._raw.fetchval(*args, **kwargs), self._loop)

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        return await _await_on_loop(self._raw.fetch(*args, **kwargs), self._loop)

    async def fetchrow(self, *args: Any, **kwargs: Any) -> Any:
        return await _await_on_loop(self._raw.fetchrow(*args, **kwargs), self._loop)

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return await _await_on_loop(self._raw.execute(*args, **kwargs), self._loop)

    async def executemany(self, *args: Any, **kwargs: Any) -> Any:
        return await _await_on_loop(self._raw.executemany(*args, **kwargs), self._loop)

    def transaction(self, *args: Any, **kwargs: Any) -> _Transaction:
        # transaction() is a sync method on asyncpg.Connection that returns
        # a Transaction object — the actual BEGIN/COMMIT happen in __aenter__/
        # __aexit__, both of which must round-trip to the executor loop.
        return _Transaction(self._raw.transaction(*args, **kwargs), self._loop)

    async def close(self) -> None:
        return await _await_on_loop(self._raw.close(), self._loop)


class _AcquireContext:
    """Async context manager that acquires a connection on the executor loop."""

    def __init__(self, raw_pool: Any, loop: asyncio.AbstractEventLoop):
        self._raw_pool = raw_pool
        self._loop = loop
        self._raw_acquire_ctx: Any = None
        self._raw_conn: Any = None

    async def __aenter__(self) -> _Connection:
        # Run the asyncpg acquire on the executor loop, not the caller's loop.
        async def _enter():
            ctx = self._raw_pool.acquire()
            self._raw_acquire_ctx = ctx
            return await ctx.__aenter__()

        future = asyncio.run_coroutine_threadsafe(_enter(), self._loop)
        self._raw_conn = await asyncio.wrap_future(future)
        return _Connection(self._raw_conn, self._loop)

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Any:
        async def _exit():
            return await self._raw_acquire_ctx.__aexit__(exc_type, exc_val, exc_tb)

        future = asyncio.run_coroutine_threadsafe(_exit(), self._loop)
        return await asyncio.wrap_future(future)


class ExecutorPool:
    """
    Wraps an asyncpg.Pool. All DB operations route through a dedicated
    background thread that owns its own asyncio event loop.
    """

    def __init__(self, raw_pool: Any):
        self._raw_pool = raw_pool
        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ExecutorPool-loop",
            daemon=True,
        )
        self._thread.start()
        self._loop_ready.wait(timeout=5.0)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        self._loop.run_forever()

    def acquire(self) -> _AcquireContext:
        return _AcquireContext(self._raw_pool, self._loop)

    @property
    def _closed(self) -> Any:
        # Mirror asyncpg's internal `_closed` attribute. dialectic_db.py:55
        # reads this to test pool liveness.
        return self._raw_pool._closed

    def get_size(self) -> Any:
        return self._raw_pool.get_size()

    def get_idle_size(self) -> Any:
        return self._raw_pool.get_idle_size()

    def get_max_size(self) -> Any:
        return self._raw_pool.get_max_size()

    async def close(self) -> None:
        # Teardown order matters (architect): close the raw pool ON the
        # executor loop (asyncpg connections are loop-bound), THEN stop
        # the loop, THEN join the thread.
        try:
            await _await_on_loop(self._raw_pool.close(), self._loop)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            await asyncio.get_event_loop().run_in_executor(
                None, self._thread.join, 5.0
            )
