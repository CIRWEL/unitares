"""
Database Abstraction Layer

Provides a unified interface for PostgreSQL+AGE (primary) with SQLite fallback.

Usage:
    from src.db import get_db

    db = get_db()  # Returns configured backend

    # Identity operations
    await db.upsert_identity(agent_id, api_key_hash, metadata)
    identity = await db.get_identity(agent_id)

    # Session operations
    await db.create_session(session_id, identity_id, expires_at)
    await db.update_session_activity(session_id)

    # Audit operations
    await db.append_audit_event(event)
    events = await db.query_audit_events(agent_id=agent_id, limit=100)

    # Graph operations (AGE)
    await db.graph_query("MATCH (a:Agent)-[:COLLABORATED]->(b:Agent) RETURN a, b")

Configuration (environment variables):
    DB_BACKEND=postgres|sqlite|dual  (default: postgres)
    DB_POSTGRES_URL=postgresql://user:pass@host:port/db
    DB_SQLITE_PATH=data/governance.db  (for sqlite fallback)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import DatabaseBackend

# Backend singleton
_db_instance: "DatabaseBackend | None" = None


def get_db() -> "DatabaseBackend":
    """
    Get the configured database backend.

    Backend selection:
    - DB_BACKEND=postgres (default): Use PostgreSQL + AGE
    - DB_BACKEND=sqlite: Use SQLite (fallback/dev mode)
    - DB_BACKEND=dual: Dual-write to both (migration)
    """
    global _db_instance

    if _db_instance is not None:
        return _db_instance

    backend = os.environ.get("DB_BACKEND", "postgres").lower()

    if backend == "sqlite":
        from .sqlite_backend import SQLiteBackend
        _db_instance = SQLiteBackend()
    elif backend == "postgres":
        from .postgres_backend import PostgresBackend
        _db_instance = PostgresBackend()
    elif backend == "dual":
        from .dual_backend import DualWriteBackend
        _db_instance = DualWriteBackend()
    else:
        raise ValueError(f"Unknown DB_BACKEND: {backend}. Use: sqlite, postgres, dual")

    return _db_instance


async def init_db() -> None:
    """Initialize the database (create tables, run migrations)."""
    db = get_db()
    await db.init()


async def close_db() -> None:
    """Close database connections."""
    global _db_instance
    if _db_instance is not None:
        await _db_instance.close()
        _db_instance = None


# Re-export common types
from .base import (
    DatabaseBackend,
    IdentityRecord,
    SessionRecord,
    AuditEvent,
    AgentStateRecord,
)

__all__ = [
    "get_db",
    "init_db",
    "close_db",
    "DatabaseBackend",
    "IdentityRecord",
    "SessionRecord",
    "AuditEvent",
    "AgentStateRecord",
]
