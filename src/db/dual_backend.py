"""
Dual-Write Backend for Migration

Writes to both SQLite and PostgreSQL during migration phase.
Reads from PostgreSQL (primary) with SQLite fallback.

Usage:
    DB_BACKEND=dual
    DB_POSTGRES_URL=postgresql://...
    DB_SQLITE_PATH=data/governance.db
    DB_DUAL_READ_PRIMARY=postgres  # or sqlite
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import (
    DatabaseBackend,
    IdentityRecord,
    SessionRecord,
    AgentStateRecord,
    AuditEvent,
)
from .sqlite_backend import SQLiteBackend
from .postgres_backend import PostgresBackend

logger = logging.getLogger(__name__)


class DualWriteBackend(DatabaseBackend):
    """
    Dual-write backend for migration.

    Writes go to both backends (SQLite + PostgreSQL).
    Reads come from the primary (configurable, default: postgres).
    Fallback to secondary on primary failure.
    """

    def __init__(self):
        self._sqlite = SQLiteBackend()
        self._postgres = PostgresBackend()
        self._read_primary = os.environ.get("DB_DUAL_READ_PRIMARY", "postgres").lower()
        self._initialized = False

    @property
    def _primary(self) -> DatabaseBackend:
        return self._postgres if self._read_primary == "postgres" else self._sqlite

    @property
    def _secondary(self) -> DatabaseBackend:
        return self._sqlite if self._read_primary == "postgres" else self._postgres

    async def init(self) -> None:
        """Initialize both backends."""
        errors = []

        try:
            await self._sqlite.init()
        except Exception as e:
            errors.append(f"SQLite init failed: {e}")
            logger.error(f"SQLite initialization failed: {e}")

        try:
            await self._postgres.init()
        except Exception as e:
            errors.append(f"PostgreSQL init failed: {e}")
            logger.error(f"PostgreSQL initialization failed: {e}")

        if len(errors) == 2:
            raise RuntimeError(f"Both backends failed to initialize: {errors}")

        self._initialized = True
        logger.info(f"DualWriteBackend initialized. Read primary: {self._read_primary}")

    async def close(self) -> None:
        """Close both backends."""
        await asyncio.gather(
            self._sqlite.close(),
            self._postgres.close(),
            return_exceptions=True,
        )
        self._initialized = False

    async def health_check(self) -> Dict[str, Any]:
        """Return health from both backends."""
        sqlite_health, postgres_health = await asyncio.gather(
            self._sqlite.health_check(),
            self._postgres.health_check(),
            return_exceptions=True,
        )

        return {
            "status": "healthy" if isinstance(sqlite_health, dict) and isinstance(postgres_health, dict) else "degraded",
            "backend": "dual",
            "read_primary": self._read_primary,
            "sqlite": sqlite_health if isinstance(sqlite_health, dict) else {"error": str(sqlite_health)},
            "postgres": postgres_health if isinstance(postgres_health, dict) else {"error": str(postgres_health)},
        }

    async def _dual_write(self, method_name: str, *args, **kwargs) -> Any:
        """Execute a write method on both backends."""
        sqlite_method = getattr(self._sqlite, method_name)
        postgres_method = getattr(self._postgres, method_name)

        results = await asyncio.gather(
            sqlite_method(*args, **kwargs),
            postgres_method(*args, **kwargs),
            return_exceptions=True,
        )

        sqlite_result, postgres_result = results

        # Log any failures
        if isinstance(sqlite_result, Exception):
            logger.warning(f"SQLite {method_name} failed: {sqlite_result}")
        if isinstance(postgres_result, Exception):
            logger.warning(f"PostgreSQL {method_name} failed: {postgres_result}")

        # Return result from primary, fallback to secondary
        if self._read_primary == "postgres":
            if not isinstance(postgres_result, Exception):
                return postgres_result
            elif not isinstance(sqlite_result, Exception):
                return sqlite_result
            else:
                raise postgres_result
        else:
            if not isinstance(sqlite_result, Exception):
                return sqlite_result
            elif not isinstance(postgres_result, Exception):
                return postgres_result
            else:
                raise sqlite_result

    async def _read_with_fallback(self, method_name: str, *args, **kwargs) -> Any:
        """Execute a read method with fallback."""
        primary_method = getattr(self._primary, method_name)
        secondary_method = getattr(self._secondary, method_name)

        try:
            result = await primary_method(*args, **kwargs)
            return result
        except Exception as e:
            logger.warning(f"Primary read {method_name} failed, falling back: {e}")
            return await secondary_method(*args, **kwargs)

    # =========================================================================
    # IDENTITY OPERATIONS
    # =========================================================================

    async def upsert_identity(
        self,
        agent_id: str,
        api_key_hash: str,
        parent_agent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
    ) -> int:
        return await self._dual_write(
            "upsert_identity", agent_id, api_key_hash, parent_agent_id, metadata, created_at
        )

    async def get_identity(self, agent_id: str) -> Optional[IdentityRecord]:
        return await self._read_with_fallback("get_identity", agent_id)

    async def get_identity_by_id(self, identity_id: int) -> Optional[IdentityRecord]:
        return await self._read_with_fallback("get_identity_by_id", identity_id)

    async def list_identities(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[IdentityRecord]:
        return await self._read_with_fallback("list_identities", status, limit, offset)

    async def update_identity_status(
        self,
        agent_id: str,
        status: str,
        disabled_at: Optional[datetime] = None,
    ) -> bool:
        return await self._dual_write("update_identity_status", agent_id, status, disabled_at)

    async def update_identity_metadata(
        self,
        agent_id: str,
        metadata: Dict[str, Any],
        merge: bool = True,
    ) -> bool:
        return await self._dual_write("update_identity_metadata", agent_id, metadata, merge)

    async def verify_api_key(self, agent_id: str, api_key: str) -> bool:
        return await self._read_with_fallback("verify_api_key", agent_id, api_key)

    # =========================================================================
    # SESSION OPERATIONS
    # =========================================================================

    async def create_session(
        self,
        session_id: str,
        identity_id: int,
        expires_at: datetime,
        client_type: Optional[str] = None,
        client_info: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return await self._dual_write(
            "create_session", session_id, identity_id, expires_at, client_type, client_info
        )

    async def get_session(self, session_id: str) -> Optional[SessionRecord]:
        return await self._read_with_fallback("get_session", session_id)

    async def update_session_activity(self, session_id: str) -> bool:
        return await self._dual_write("update_session_activity", session_id)

    async def end_session(self, session_id: str) -> bool:
        return await self._dual_write("end_session", session_id)

    async def get_active_sessions_for_identity(
        self,
        identity_id: int,
    ) -> List[SessionRecord]:
        return await self._read_with_fallback("get_active_sessions_for_identity", identity_id)

    async def cleanup_expired_sessions(self) -> int:
        # Run on both, return max count
        results = await asyncio.gather(
            self._sqlite.cleanup_expired_sessions(),
            self._postgres.cleanup_expired_sessions(),
            return_exceptions=True,
        )
        counts = [r for r in results if isinstance(r, int)]
        return max(counts) if counts else 0

    # =========================================================================
    # AGENT STATE OPERATIONS
    # =========================================================================

    async def record_agent_state(
        self,
        identity_id: int,
        entropy: float,
        integrity: float,
        stability_index: float,
        volatility: float,
        regime: str,
        coherence: float,
        state_json: Optional[Dict[str, Any]] = None,
    ) -> int:
        return await self._dual_write(
            "record_agent_state",
            identity_id, entropy, integrity, stability_index, volatility, regime, coherence, state_json
        )

    async def get_latest_agent_state(
        self,
        identity_id: int,
    ) -> Optional[AgentStateRecord]:
        return await self._read_with_fallback("get_latest_agent_state", identity_id)

    async def get_agent_state_history(
        self,
        identity_id: int,
        limit: int = 100,
    ) -> List[AgentStateRecord]:
        return await self._read_with_fallback("get_agent_state_history", identity_id, limit)

    # =========================================================================
    # AUDIT OPERATIONS
    # =========================================================================

    async def append_audit_event(self, event: AuditEvent) -> bool:
        return await self._dual_write("append_audit_event", event)

    async def query_audit_events(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
        order: str = "asc",
    ) -> List[AuditEvent]:
        return await self._read_with_fallback(
            "query_audit_events", agent_id, event_type, start_time, end_time, limit, order
        )

    async def search_audit_events(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[AuditEvent]:
        return await self._read_with_fallback("search_audit_events", query, agent_id, limit)

    # =========================================================================
    # CALIBRATION OPERATIONS
    # =========================================================================

    async def get_calibration(self) -> Dict[str, Any]:
        return await self._read_with_fallback("get_calibration")

    async def update_calibration(self, data: Dict[str, Any]) -> bool:
        return await self._dual_write("update_calibration", data)

    # =========================================================================
    # GRAPH OPERATIONS (PostgreSQL only)
    # =========================================================================

    async def graph_available(self) -> bool:
        """Graph is only available via PostgreSQL backend."""
        return await self._postgres.graph_available()

    async def graph_query(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Graph queries go directly to PostgreSQL."""
        return await self._postgres.graph_query(cypher, params)

    # =========================================================================
    # TOOL USAGE OPERATIONS
    # =========================================================================

    async def append_tool_usage(
        self,
        agent_id: Optional[str],
        session_id: Optional[str],
        tool_name: str,
        latency_ms: Optional[int],
        success: bool,
        error_type: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return await self._dual_write(
            "append_tool_usage",
            agent_id, session_id, tool_name, latency_ms, success, error_type, payload
        )

    async def query_tool_usage(
        self,
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        return await self._read_with_fallback(
            "query_tool_usage", agent_id, tool_name, start_time, end_time, limit
        )

    # =========================================================================
    # DIALECTIC OPERATIONS
    # =========================================================================

    async def create_dialectic_session(
        self,
        session_id: str,
        paused_agent_id: str,
        reason: str,
        scope: str = "general",
    ) -> bool:
        return await self._dual_write(
            "create_dialectic_session",
            session_id, paused_agent_id, reason, scope
        )

    async def get_dialectic_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return await self._read_with_fallback("get_dialectic_session", session_id)

    async def get_dialectic_session_by_agent(
        self,
        agent_id: str,
    ) -> Optional[Dict[str, Any]]:
        return await self._read_with_fallback("get_dialectic_session_by_agent", agent_id)

    async def update_dialectic_session_phase(
        self,
        session_id: str,
        phase: str,
    ) -> bool:
        return await self._dual_write("update_dialectic_session_phase", session_id, phase)

    async def update_dialectic_session_reviewer(
        self,
        session_id: str,
        reviewer_agent_id: str,
    ) -> bool:
        return await self._dual_write(
            "update_dialectic_session_reviewer",
            session_id, reviewer_agent_id
        )

    async def add_dialectic_message(
        self,
        session_id: str,
        message_type: str,
        agent_id: str,
        content: str,
    ) -> bool:
        return await self._dual_write(
            "add_dialectic_message",
            session_id, message_type, agent_id, content
        )

    async def resolve_dialectic_session(
        self,
        session_id: str,
        resolution: str,
        outcome: Optional[str] = None,
    ) -> bool:
        return await self._dual_write(
            "resolve_dialectic_session",
            session_id, resolution, outcome
        )

    async def is_agent_in_active_dialectic_session(self, agent_id: str) -> bool:
        return await self._read_with_fallback(
            "is_agent_in_active_dialectic_session",
            agent_id
        )
