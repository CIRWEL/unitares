"""Session operations mixin for PostgresBackend."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..base import SessionRecord
from src.logging_utils import get_logger

logger = get_logger(__name__)


class SessionMixin:
    """Session CRUD operations."""

    async def create_session(
        self,
        session_id: str,
        identity_id: int,
        expires_at,
        client_type: Optional[str] = None,
        client_info: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Create a new session row.

        Returns True only when a new session is inserted. If the session_id
        already exists, this method returns False and does not mutate existing
        session state.
        """
        async with self.acquire() as conn:
            try:
                result = await conn.execute(
                    """
                    INSERT INTO core.sessions (session_id, identity_id, expires_at, client_type, client_info)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (session_id) DO NOTHING
                    """,
                    session_id, identity_id, expires_at, client_type, json.dumps(client_info or {}),
                )
                return "INSERT 0 1" in result
            except Exception:
                return False

    async def get_session(self, session_id: str) -> Optional[SessionRecord]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.session_id, s.identity_id, i.agent_id, s.created_at, s.last_active,
                       s.expires_at, s.is_active, s.client_type, s.client_info, s.metadata
                FROM core.sessions s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.session_id = $1
                """,
                session_id,
            )
            if not row:
                return None
            return self._row_to_session(row)

    async def update_session_activity(self, session_id: str) -> bool:
        from config.governance_config import GovernanceConfig
        ttl_hours = int(GovernanceConfig.SESSION_TTL_HOURS)
        async with self.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE core.sessions
                SET last_active = now(),
                    expires_at = now() + ($2 * interval '1 hour')
                WHERE session_id = $1 AND is_active = TRUE
                """,
                session_id,
                ttl_hours,
            )
            return "UPDATE 1" in result

    async def end_session(self, session_id: str) -> bool:
        async with self.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE core.sessions
                SET is_active = FALSE
                WHERE session_id = $1
                """,
                session_id,
            )
            return "UPDATE 1" in result

    async def get_active_sessions_for_identity(
        self,
        identity_id: int,
    ) -> List[SessionRecord]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.session_id, s.identity_id, i.agent_id, s.created_at, s.last_active,
                       s.expires_at, s.is_active, s.client_type, s.client_info, s.metadata
                FROM core.sessions s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id = $1 AND s.is_active = TRUE AND s.expires_at > now()
                ORDER BY s.last_active DESC
                """,
                identity_id,
            )
            return [self._row_to_session(r) for r in rows]

    async def get_last_inactive_session(
        self,
        identity_id: int,
    ) -> Optional[SessionRecord]:
        """Get most recent inactive session for an identity."""
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.session_id, s.identity_id, i.agent_id, s.created_at, s.last_active,
                       s.expires_at, s.is_active, s.client_type, s.client_info, s.metadata
                FROM core.sessions s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id = $1 AND s.is_active = FALSE
                ORDER BY s.last_active DESC
                LIMIT 1
                """,
                identity_id,
            )
            if not row:
                return None
            return self._row_to_session(row)

    async def cleanup_expired_sessions(self) -> int:
        async with self.acquire() as conn:
            result = await conn.fetchval("SELECT core.cleanup_expired_sessions()")
            return result or 0

    def _row_to_session(self, row) -> SessionRecord:
        return SessionRecord(
            session_id=row["session_id"],
            identity_id=row["identity_id"],
            agent_id=row["agent_id"],
            created_at=row["created_at"],
            last_active=row["last_active"],
            expires_at=row["expires_at"],
            is_active=row["is_active"],
            client_type=row["client_type"],
            client_info=json.loads(row["client_info"]) if isinstance(row["client_info"], str) else row["client_info"],
            metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
        )
