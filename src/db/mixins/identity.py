"""Identity operations mixin for PostgresBackend."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..base import IdentityRecord
from src.logging_utils import get_logger

logger = get_logger(__name__)


class IdentityMixin:
    """Identity CRUD operations."""

    async def upsert_identity(
        self,
        agent_id: str,
        api_key_hash: str,
        parent_agent_id: Optional[str] = None,
        spawn_reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at=None,
    ) -> int:
        async with self.acquire() as conn:
            identity_id = await conn.fetchval(
                """
                INSERT INTO core.identities (
                    agent_id, api_key_hash, parent_agent_id, spawn_reason, metadata, created_at
                )
                VALUES ($1, $2, $3, $4, $5, COALESCE($6, now()))
                ON CONFLICT (agent_id) DO UPDATE SET
                    parent_agent_id = COALESCE(EXCLUDED.parent_agent_id, core.identities.parent_agent_id),
                    spawn_reason = COALESCE(EXCLUDED.spawn_reason, core.identities.spawn_reason),
                    metadata = core.identities.metadata || COALESCE($5, '{}'::jsonb),
                    updated_at = now()
                RETURNING identity_id
                """,
                agent_id,
                api_key_hash,
                parent_agent_id,
                spawn_reason,
                json.dumps(metadata or {}),
                created_at,
            )
            return identity_id

    async def get_identity(self, agent_id: str) -> Optional[IdentityRecord]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                       status, parent_agent_id, spawn_reason, disabled_at, last_activity_at, metadata
                FROM core.identities
                WHERE agent_id = $1
                """,
                agent_id,
            )
            if not row:
                return None
            return self._row_to_identity(row)

    async def get_identities_batch(self, agent_ids: list[str]) -> dict[str, Optional[IdentityRecord]]:
        """Load identities for multiple agent IDs in a single query."""
        if not agent_ids:
            return {}
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                       status, parent_agent_id, spawn_reason, disabled_at, last_activity_at, metadata
                FROM core.identities
                WHERE agent_id = ANY($1::text[])
                """,
                agent_ids,
            )
            result = {}
            for row in rows:
                identity = self._row_to_identity(row)
                result[identity.agent_id] = identity
            return result

    async def get_identity_by_id(self, identity_id: int) -> Optional[IdentityRecord]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                       status, parent_agent_id, spawn_reason, disabled_at, last_activity_at, metadata
                FROM core.identities
                WHERE identity_id = $1
                """,
                identity_id,
            )
            if not row:
                return None
            return self._row_to_identity(row)

    async def list_identities(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[IdentityRecord]:
        async with self.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                           status, parent_agent_id, spawn_reason, disabled_at, last_activity_at, metadata
                    FROM core.identities
                    WHERE status = $1
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    status, limit, offset,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                           status, parent_agent_id, spawn_reason, disabled_at, last_activity_at, metadata
                    FROM core.identities
                    ORDER BY created_at DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit, offset,
                )
            return [self._row_to_identity(r) for r in rows]

    async def update_identity_status(
        self,
        agent_id: str,
        status: str,
        disabled_at=None,
    ) -> bool:
        async with self.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE core.identities
                SET status = $2, disabled_at = $3, updated_at = now()
                WHERE agent_id = $1
                """,
                agent_id, status, disabled_at,
            )
            return result == "UPDATE 1"

    async def update_identity_metadata(
        self,
        agent_id: str,
        metadata: Dict[str, Any],
        merge: bool = True,
    ) -> bool:
        async with self.acquire() as conn:
            if merge:
                result = await conn.execute(
                    """
                    UPDATE core.identities
                    SET metadata = metadata || $2::jsonb, updated_at = now()
                    WHERE agent_id = $1
                    """,
                    agent_id, json.dumps(metadata),
                )
            else:
                result = await conn.execute(
                    """
                    UPDATE core.identities
                    SET metadata = $2::jsonb, updated_at = now()
                    WHERE agent_id = $1
                    """,
                    agent_id, json.dumps(metadata),
                )
            return "UPDATE 1" in result

    async def increment_update_count(
        self,
        agent_id: str,
        extra_metadata: Dict[str, Any] | None = None,
    ) -> int:
        """Atomically increment total_updates in PostgreSQL and return the new value."""
        async with self.acquire() as conn:
            if extra_metadata:
                new_count = await conn.fetchval(
                    """
                    UPDATE core.identities
                    SET metadata = jsonb_set(
                            metadata || $2::jsonb,
                            '{total_updates}',
                            (COALESCE((metadata->>'total_updates')::int, 0) + 1)::text::jsonb
                        ),
                        updated_at = now(),
                        last_activity_at = now()
                    WHERE agent_id = $1
                    RETURNING (metadata->>'total_updates')::int
                    """,
                    agent_id, json.dumps(extra_metadata),
                )
            else:
                new_count = await conn.fetchval(
                    """
                    UPDATE core.identities
                    SET metadata = jsonb_set(
                            metadata,
                            '{total_updates}',
                            (COALESCE((metadata->>'total_updates')::int, 0) + 1)::text::jsonb
                        ),
                        updated_at = now(),
                        last_activity_at = now()
                    WHERE agent_id = $1
                    RETURNING (metadata->>'total_updates')::int
                    """,
                    agent_id,
                )
            return new_count or 0

    async def verify_api_key(self, agent_id: str, api_key: str) -> bool:
        async with self.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT core.verify_api_key($2, api_key_hash)
                FROM core.identities
                WHERE agent_id = $1
                """,
                agent_id, api_key,
            )
            return bool(result)

    def _row_to_identity(self, row) -> IdentityRecord:
        return IdentityRecord(
            identity_id=row["identity_id"],
            agent_id=row["agent_id"],
            api_key_hash=row["api_key_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=row["status"],
            parent_agent_id=row["parent_agent_id"],
            spawn_reason=row["spawn_reason"],
            disabled_at=row["disabled_at"],
            last_activity_at=row.get("last_activity_at"),
            metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
        )
