"""Compatibility helpers for asyncpg pool acquisition in tests and runtime."""

from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from typing import Any


@asynccontextmanager
async def compatible_acquire(pool: Any):
    """
    Acquire a DB connection from asyncpg pool with AsyncMock-safe behavior.

    In production, ``pool.acquire()`` returns an async context manager.
    In some tests, mocked pools return an awaitable that resolves to a context
    manager. This helper supports both forms.
    """
    acquire_result = pool.acquire()
    if inspect.isawaitable(acquire_result):
        acquire_result = await acquire_result

    async with acquire_result as conn:
        yield conn
