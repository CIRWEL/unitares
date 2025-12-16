"""
Database Abstraction Layer

Provides a unified interface for SQLite (current) and PostgreSQL+AGE (future) backends.
Supports dual-write during migration and seamless cutover.

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

    # Graph operations (AGE only, graceful fallback on SQLite)
    await db.graph_query("MATCH (a:Agent)-[:COLLABORATED]->(b:Agent) RETURN a, b")

Configuration (environment variables):
    DB_BACKEND=sqlite|postgres|dual  (default: sqlite)
    DB_POSTGRES_URL=postgresql://user:pass@host:port/db
    DB_SQLITE_PATH=data/governance.db
    DB_DUAL_WRITE=true|false  (for migration phase)
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
    - DB_BACKEND=sqlite (default): Use SQLite
    - DB_BACKEND=postgres: Use PostgreSQL + AGE
    - DB_BACKEND=dual: Dual-write to both (for migration)
    """
    global _db_instance

    if _db_instance is not None:
        return _db_instance

    backend = os.environ.get("DB_BACKEND", "sqlite").lower()

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
