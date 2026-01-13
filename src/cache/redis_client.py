"""
Redis client with graceful fallback.

Connection management:
- Lazy initialization (connects on first use)
- Auto-reconnect on connection loss
- Graceful fallback to in-memory if Redis unavailable

Environment variables:
- REDIS_URL: Redis connection URL (default: redis://localhost:6379/0)
- REDIS_ENABLED: Set to "0" to disable Redis entirely (force fallback)
"""

from __future__ import annotations

import os
import asyncio
from typing import Optional, Any
from contextlib import asynccontextmanager

from src.logging_utils import get_logger

logger = get_logger(__name__)

# Lazy import to avoid hard dependency
_redis_module: Optional[Any] = None
_redis_client: Optional[Any] = None
_redis_available: Optional[bool] = None


def _get_redis_module():
    """Lazy import of redis module."""
    global _redis_module
    if _redis_module is None:
        try:
            import redis.asyncio as redis
            _redis_module = redis
        except ImportError:
            logger.warning("redis package not installed - using fallback mode")
            _redis_module = False
    return _redis_module if _redis_module else None


async def get_redis() -> Optional[Any]:
    """
    Get async Redis client instance.

    Returns:
        Redis client if available, None if Redis is disabled or unavailable.

    Thread-safe: Uses module-level singleton with lazy initialization.
    """
    global _redis_client, _redis_available

    # Check if Redis is explicitly disabled
    if os.getenv("REDIS_ENABLED", "1").lower() in ("0", "false", "no"):
        return None

    # Check if we already know Redis is unavailable
    if _redis_available is False:
        return None

    # Return existing client if available
    if _redis_client is not None:
        try:
            # Quick health check
            await _redis_client.ping()
            return _redis_client
        except Exception:
            # Connection lost, try to reconnect
            _redis_client = None

    # Get redis module (lazy import)
    redis_mod = _get_redis_module()
    if redis_mod is None:
        _redis_available = False
        return None

    # Connect to Redis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        _redis_client = redis_mod.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        # Verify connection
        await _redis_client.ping()
        _redis_available = True
        logger.info(f"Redis connected: {redis_url}")
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis unavailable ({redis_url}): {e} - using fallback mode")
        _redis_available = False
        _redis_client = None
        return None


def is_redis_available() -> bool:
    """
    Check if Redis is available (non-blocking).

    Returns cached availability status. Use get_redis() to trigger
    actual connection attempt.
    """
    global _redis_available

    # If explicitly disabled, return False
    if os.getenv("REDIS_ENABLED", "1").lower() in ("0", "false", "no"):
        return False

    # Return cached status if known
    if _redis_available is not None:
        return _redis_available

    # Status unknown - we haven't tried to connect yet
    # Return True optimistically; actual check happens on first use
    return True


async def close_redis() -> None:
    """Close Redis connection (call on shutdown)."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.close()
        except Exception:
            pass
        _redis_client = None


def reset_redis_state() -> None:
    """Reset Redis state (for testing)."""
    global _redis_client, _redis_available
    _redis_client = None
    _redis_available = None
