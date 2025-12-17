"""
Dual-Write Backend for Migration

Writes to both SQLite (primary) and PostgreSQL (secondary).
Reads from SQLite. Used during migration to keep both databases in sync.

Set DB_BACKEND=dual to use this backend.
"""

from __future__ import annotations

import asyncio
import logging
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
    Dual-write backend for safe migration from SQLite to PostgreSQL.

    - Reads from SQLite (primary, source of truth)
    - Writes to both SQLite and PostgreSQL
    - Logs discrepancies for investigation
    """

    def __init__(self):
        self._sqlite = SQLiteBackend()
        self._postgres = PostgresBackend()
        self._postgres_available = False

    async def init(self) -> None:
        """Initialize both backends."""
        await self._sqlite.init()

        try:
            await self._postgres.init()
            self._postgres_available = True
            logger.info("Dual-write: PostgreSQL backend initialized")
        except Exception as e:
            logger.warning(f"Dual-write: PostgreSQL unavailable, SQLite-only mode: {e}")
            self._postgres_available = False

    async def close(self) -> None:
        """Close both backends."""
        await self._sqlite.close()
        if self._postgres_available:
            try:
                await self._postgres.close()
            except Exception as e:
                logger.warning(f"Error closing PostgreSQL: {e}")

    async def health_check(self) -> Dict[str, Any]:
        """Return health from both backends."""
        sqlite_health = await self._sqlite.health_check()

        postgres_health = {"status": "unavailable"}
        if self._postgres_available:
            try:
                postgres_health = await self._postgres.health_check()
            except Exception as e:
                postgres_health = {"status": "error", "error": str(e)}

        return {
            "backend": "dual",
            "primary": sqlite_health,
            "secondary": postgres_health,
            "postgres_available": self._postgres_available,
        }

    # =========================================================================
    # HELPER: Dual-write with error handling
    # =========================================================================

    async def _write_both(self, op_name: str, sqlite_coro, postgres_coro):
        """Execute write on both backends, log errors on secondary."""
        # Always write to SQLite first (primary)
        result = await sqlite_coro

        # Write to PostgreSQL if available (secondary, async)
        if self._postgres_available:
            try:
                await postgres_coro
            except Exception as e:
                logger.error(f"Dual-write {op_name} failed on PostgreSQL: {e}")

        return result

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
        return await self._write_both(
            "upsert_identity",
            self._sqlite.upsert_identity(agent_id, api_key_hash, parent_agent_id, metadata, created_at),
            self._postgres.upsert_identity(agent_id, api_key_hash, parent_agent_id, metadata, created_at),
        )

    async def get_identity(self, agent_id: str) -> Optional[IdentityRecord]:
        return await self._sqlite.get_identity(agent_id)

    async def get_identity_by_id(self, identity_id: int) -> Optional[IdentityRecord]:
        return await self._sqlite.get_identity_by_id(identity_id)

    async def list_identities(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[IdentityRecord]:
        return await self._sqlite.list_identities(status, limit, offset)

    async def update_identity_status(
        self,
        agent_id: str,
        status: str,
        disabled_at: Optional[datetime] = None,
    ) -> bool:
        return await self._write_both(
            "update_identity_status",
            self._sqlite.update_identity_status(agent_id, status, disabled_at),
            self._postgres.update_identity_status(agent_id, status, disabled_at),
        )

    async def update_identity_metadata(
        self,
        agent_id: str,
        metadata: Dict[str, Any],
        merge: bool = True,
    ) -> bool:
        return await self._write_both(
            "update_identity_metadata",
            self._sqlite.update_identity_metadata(agent_id, metadata, merge),
            self._postgres.update_identity_metadata(agent_id, metadata, merge),
        )

    async def verify_api_key(self, agent_id: str, api_key: str) -> bool:
        return await self._sqlite.verify_api_key(agent_id, api_key)

    async def upsert_agent(
        self,
        agent_id: str,
        api_key: str,
        status: str = "active",
        purpose: Optional[str] = None,
        notes: Optional[str] = None,
        tags: Optional[List[str]] = None,
        parent_agent_id: Optional[str] = None,
        spawn_reason: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> bool:
        """
        Create or update an agent in core.agents table (PostgreSQL only).
        
        This is required for foreign key references in dialectic_sessions.
        SQLite doesn't have this table, so we only write to PostgreSQL.
        """
        if self._postgres_available:
            try:
                return await self._postgres.upsert_agent(
                    agent_id, api_key, status, purpose, notes, tags,
                    parent_agent_id, spawn_reason, created_at
                )
            except Exception as e:
                logger.error(f"Dual-write upsert_agent failed on PostgreSQL: {e}")
                return False
        return False

    async def update_agent_fields(
        self,
        agent_id: str,
        *,
        status: Optional[str] = None,
        purpose: Optional[str] = None,
        notes: Optional[str] = None,
        tags: Optional[List[str]] = None,
        parent_agent_id: Optional[str] = None,
        spawn_reason: Optional[str] = None,
    ) -> bool:
        """
        Partial update of core.agents (PostgreSQL only). SQLite has no core.agents table.
        """
        if self._postgres_available:
            try:
                return await self._postgres.update_agent_fields(
                    agent_id,
                    status=status,
                    purpose=purpose,
                    notes=notes,
                    tags=tags,
                    parent_agent_id=parent_agent_id,
                    spawn_reason=spawn_reason,
                )
            except Exception as e:
                logger.error(f"Dual-write update_agent_fields failed on PostgreSQL: {e}")
                return False
        return False

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
        return await self._write_both(
            "create_session",
            self._sqlite.create_session(session_id, identity_id, expires_at, client_type, client_info),
            self._postgres.create_session(session_id, identity_id, expires_at, client_type, client_info),
        )

    async def get_session(self, session_id: str) -> Optional[SessionRecord]:
        return await self._sqlite.get_session(session_id)

    async def update_session_activity(self, session_id: str) -> bool:
        return await self._write_both(
            "update_session_activity",
            self._sqlite.update_session_activity(session_id),
            self._postgres.update_session_activity(session_id),
        )

    async def end_session(self, session_id: str) -> bool:
        return await self._write_both(
            "end_session",
            self._sqlite.end_session(session_id),
            self._postgres.end_session(session_id),
        )

    async def get_active_sessions_for_identity(
        self,
        identity_id: int,
    ) -> List[SessionRecord]:
        return await self._sqlite.get_active_sessions_for_identity(identity_id)

    async def cleanup_expired_sessions(self) -> int:
        result = await self._sqlite.cleanup_expired_sessions()
        if self._postgres_available:
            try:
                await self._postgres.cleanup_expired_sessions()
            except Exception as e:
                logger.warning(f"PostgreSQL session cleanup failed: {e}")
        return result

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
        return await self._write_both(
            "record_agent_state",
            self._sqlite.record_agent_state(
                identity_id, entropy, integrity, stability_index, volatility, regime, coherence, state_json
            ),
            self._postgres.record_agent_state(
                identity_id, entropy, integrity, stability_index, volatility, regime, coherence, state_json
            ),
        )

    async def get_latest_agent_state(
        self,
        identity_id: int,
    ) -> Optional[AgentStateRecord]:
        return await self._sqlite.get_latest_agent_state(identity_id)

    async def get_agent_state_history(
        self,
        identity_id: int,
        limit: int = 100,
    ) -> List[AgentStateRecord]:
        return await self._sqlite.get_agent_state_history(identity_id, limit)

    # =========================================================================
    # AUDIT OPERATIONS
    # =========================================================================

    async def append_audit_event(self, event: AuditEvent) -> bool:
        return await self._write_both(
            "append_audit_event",
            self._sqlite.append_audit_event(event),
            self._postgres.append_audit_event(event),
        )

    async def query_audit_events(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
        order: str = "asc",
    ) -> List[AuditEvent]:
        return await self._sqlite.query_audit_events(
            agent_id, event_type, start_time, end_time, limit, order
        )

    async def search_audit_events(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[AuditEvent]:
        return await self._sqlite.search_audit_events(query, agent_id, limit)

    # =========================================================================
    # CALIBRATION OPERATIONS
    # =========================================================================

    async def get_calibration(self) -> Dict[str, Any]:
        return await self._sqlite.get_calibration()

    async def update_calibration(self, data: Dict[str, Any]) -> bool:
        return await self._write_both(
            "update_calibration",
            self._sqlite.update_calibration(data),
            self._postgres.update_calibration(data),
        )

    # =========================================================================
    # GRAPH OPERATIONS
    # =========================================================================

    async def graph_available(self) -> bool:
        if self._postgres_available:
            return await self._postgres.graph_available()
        return False

    async def graph_query(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if self._postgres_available:
            return await self._postgres.graph_query(cypher, params)
        return []

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
        return await self._write_both(
            "append_tool_usage",
            self._sqlite.append_tool_usage(
                agent_id, session_id, tool_name, latency_ms, success, error_type, payload
            ),
            self._postgres.append_tool_usage(
                agent_id, session_id, tool_name, latency_ms, success, error_type, payload
            ),
        )

    async def query_tool_usage(
        self,
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        return await self._sqlite.query_tool_usage(
            agent_id, tool_name, start_time, end_time, limit
        )

    # =========================================================================
    # DIALECTIC OPERATIONS
    # =========================================================================

    async def create_dialectic_session(
        self,
        session_id: str,
        paused_agent_id: str,
        reviewer_agent_id: Optional[str] = None,
        reason: Optional[str] = None,
        discovery_id: Optional[str] = None,
        dispute_type: Optional[str] = None,
        session_type: Optional[str] = None,
        topic: Optional[str] = None,
        max_synthesis_rounds: Optional[int] = None,
        synthesis_round: Optional[int] = None,
        paused_agent_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await self._write_both(
            "create_dialectic_session",
            self._sqlite.create_dialectic_session(
                session_id, paused_agent_id, reviewer_agent_id, reason, discovery_id,
                dispute_type, session_type, topic, max_synthesis_rounds, synthesis_round, paused_agent_state
            ),
            self._postgres.create_dialectic_session(
                session_id, paused_agent_id, reviewer_agent_id, reason, discovery_id,
                dispute_type, session_type, topic, max_synthesis_rounds, synthesis_round, paused_agent_state
            ),
        )

    async def get_dialectic_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return await self._sqlite.get_dialectic_session(session_id)

    async def get_dialectic_session_by_agent(
        self,
        agent_id: str,
        active_only: bool = True,
    ) -> Optional[Dict[str, Any]]:
        return await self._sqlite.get_dialectic_session_by_agent(agent_id, active_only)

    async def get_all_active_dialectic_sessions_for_agent(
        self,
        agent_id: str,
    ) -> List[Dict[str, Any]]:
        return await self._sqlite.get_all_active_dialectic_sessions_for_agent(agent_id)

    async def update_dialectic_session_phase(
        self,
        session_id: str,
        phase: str,
    ) -> bool:
        return await self._write_both(
            "update_dialectic_session_phase",
            self._sqlite.update_dialectic_session_phase(session_id, phase),
            self._postgres.update_dialectic_session_phase(session_id, phase),
        )

    async def update_dialectic_session_reviewer(
        self,
        session_id: str,
        reviewer_agent_id: str,
    ) -> bool:
        return await self._write_both(
            "update_dialectic_session_reviewer",
            self._sqlite.update_dialectic_session_reviewer(session_id, reviewer_agent_id),
            self._postgres.update_dialectic_session_reviewer(session_id, reviewer_agent_id),
        )

    async def add_dialectic_message(
        self,
        session_id: str,
        agent_id: str,
        message_type: str,
        root_cause: Optional[str] = None,
        proposed_conditions: Optional[List[str]] = None,
        reasoning: Optional[str] = None,
        observed_metrics: Optional[Dict[str, Any]] = None,
        concerns: Optional[List[str]] = None,
        agrees: Optional[bool] = None,
        signature: Optional[str] = None,
    ) -> int:
        return await self._write_both(
            "add_dialectic_message",
            self._sqlite.add_dialectic_message(
                session_id, agent_id, message_type, root_cause, proposed_conditions,
                reasoning, observed_metrics, concerns, agrees, signature
            ),
            self._postgres.add_dialectic_message(
                session_id, agent_id, message_type, root_cause, proposed_conditions,
                reasoning, observed_metrics, concerns, agrees, signature
            ),
        )

    async def resolve_dialectic_session(
        self,
        session_id: str,
        resolution: Dict[str, Any],
        status: str = "resolved",
    ) -> bool:
        return await self._write_both(
            "resolve_dialectic_session",
            self._sqlite.resolve_dialectic_session(session_id, resolution, status),
            self._postgres.resolve_dialectic_session(session_id, resolution, status),
        )

    async def is_agent_in_active_dialectic_session(self, agent_id: str) -> bool:
        return await self._sqlite.is_agent_in_active_dialectic_session(agent_id)
