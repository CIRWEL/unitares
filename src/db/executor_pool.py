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


async def _await_on_loop(target: Any, loop: asyncio.AbstractEventLoop) -> Any:
    """Schedule on `loop` (a different thread's loop) and await the result.

    Accepts either:
    - A **callable** returning a coroutine/awaitable — called *inside* the
      executor loop so any Futures it creates are loop-bound correctly.
      **Use this form for asyncpg ops** (asyncpg internals capture the
      running loop when creating Futures).
    - A coroutine — passed straight to ``run_coroutine_threadsafe``.
      Safe only for plain coroutines that don't internally create Futures
      bound to the calling loop.
    """
    if callable(target):
        async def _call_on_executor():
            result = target()
            if asyncio.iscoroutine(result) or hasattr(result, "__await__"):
                return await result
            return result
        coro = _call_on_executor()
    elif asyncio.iscoroutine(target):
        coro = target
    else:
        async def _wrap():
            return await target
        coro = _wrap()
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
        return await _await_on_loop(lambda: self._raw.__aenter__(), self._loop)

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Any:
        return await _await_on_loop(
            lambda: self._raw.__aexit__(exc_type, exc_val, exc_tb), self._loop
        )


class _Connection:
    """Wraps an asyncpg Connection, dispatching all calls to the executor loop."""

    def __init__(self, raw_conn: Any, loop: asyncio.AbstractEventLoop):
        self._raw = raw_conn
        self._loop = loop

    async def fetchval(self, *args: Any, **kwargs: Any) -> Any:
        return await _await_on_loop(lambda: self._raw.fetchval(*args, **kwargs), self._loop)

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        return await _await_on_loop(lambda: self._raw.fetch(*args, **kwargs), self._loop)

    async def fetchrow(self, *args: Any, **kwargs: Any) -> Any:
        return await _await_on_loop(lambda: self._raw.fetchrow(*args, **kwargs), self._loop)

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return await _await_on_loop(lambda: self._raw.execute(*args, **kwargs), self._loop)

    async def executemany(self, *args: Any, **kwargs: Any) -> Any:
        return await _await_on_loop(lambda: self._raw.executemany(*args, **kwargs), self._loop)

    def transaction(self, *args: Any, **kwargs: Any) -> _Transaction:
        # transaction() is a sync method on asyncpg.Connection that returns
        # a Transaction object — the actual BEGIN/COMMIT happen in __aenter__/
        # __aexit__, both of which must round-trip to the executor loop.
        return _Transaction(self._raw.transaction(*args, **kwargs), self._loop)

    async def close(self) -> None:
        return await _await_on_loop(lambda: self._raw.close(), self._loop)


class _AcquireContext:
    """
    Mirrors asyncpg's PoolAcquireContext: BOTH awaitable AND an async context
    manager. `async with pool.acquire(): ...` auto-releases. `await pool.acquire()`
    returns the connection directly — caller must `pool.release(conn)` later.
    """

    def __init__(self, raw_pool: Any, loop: asyncio.AbstractEventLoop, timeout: Any = None):
        self._raw_pool = raw_pool
        self._loop = loop
        self._timeout = timeout
        self._raw_acquire_ctx: Any = None
        self._raw_conn: Any = None

    def __await__(self):
        async def _direct_acquire():
            def _factory():
                kwargs = {} if self._timeout is None else {"timeout": self._timeout}
                return self._raw_pool.acquire(**kwargs)
            return await _await_on_loop(_factory, self._loop)

        raw_conn = yield from _direct_acquire().__await__()
        return _Connection(raw_conn, self._loop)

    async def __aenter__(self) -> _Connection:
        # The PoolAcquireContext is created on the executor loop AND its
        # __aenter__ is awaited there, so the connection comes back loop-bound
        # to the executor loop. Storing the ctx so __aexit__ can reuse it.
        def _enter_factory():
            kwargs = {} if self._timeout is None else {"timeout": self._timeout}
            self._raw_acquire_ctx = self._raw_pool.acquire(**kwargs)
            return self._raw_acquire_ctx.__aenter__()

        self._raw_conn = await _await_on_loop(_enter_factory, self._loop)
        return _Connection(self._raw_conn, self._loop)

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Any:
        return await _await_on_loop(
            lambda: self._raw_acquire_ctx.__aexit__(exc_type, exc_val, exc_tb),
            self._loop,
        )


class ExecutorPool:
    """
    Wraps an asyncpg.Pool. All DB operations route through a dedicated
    background thread that owns its own asyncio event loop.
    """

    def __init__(self, raw_pool: Any):
        # Direct constructor: caller has already-created pool (mocks, tests).
        # Production code should use `await ExecutorPool.create(coro_factory)`
        # so the asyncpg pool is created on the executor loop — asyncpg
        # connections are loop-bound (architect's per-thread pinning).
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

    @classmethod
    async def create(cls, create_pool_factory: Any) -> "ExecutorPool":
        """Create the asyncpg pool ON the executor loop.

        ``create_pool_factory`` is a callable returning the awaitable from
        ``asyncpg.create_pool(...)`` — calling it inside the executor loop
        means the pool and all its connections are bound to that loop.
        """
        instance = cls.__new__(cls)
        instance._loop = asyncio.new_event_loop()
        instance._loop_ready = threading.Event()
        instance._thread = threading.Thread(
            target=instance._run_loop,
            name="ExecutorPool-loop",
            daemon=True,
        )
        instance._thread.start()
        instance._loop_ready.wait(timeout=5.0)
        # Pass the factory (not the result) so it's called *inside* the
        # executor loop — asyncpg.create_pool's Futures must be loop-bound
        # to the executor loop.
        instance._raw_pool = await _await_on_loop(create_pool_factory, instance._loop)
        return instance

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        self._loop.run_forever()

    def acquire(self, timeout: Any = None) -> _AcquireContext:
        return _AcquireContext(self._raw_pool, self._loop, timeout=timeout)

    async def release(self, conn: _Connection) -> Any:
        # Pair to `await pool.acquire()`. Forwards to raw pool with the
        # underlying asyncpg connection (postgres_backend.py:206).
        return await _await_on_loop(lambda: self._raw_pool.release(conn._raw), self._loop)

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
            await _await_on_loop(lambda: self._raw_pool.close(), self._loop)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            await asyncio.get_event_loop().run_in_executor(
                None, self._thread.join, 5.0
            )
