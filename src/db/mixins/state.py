"""Agent state operations mixin for PostgresBackend."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..base import AgentStateRecord
from src.logging_utils import get_logger

logger = get_logger(__name__)


class StateMixin:
    """Agent state (EISV) snapshot operations."""

    async def record_agent_state(
        self,
        identity_id: int,
        entropy: float,
        integrity: float,
        stability_index: float,
        void: float,
        regime: str,
        coherence: float,
        state_json: Optional[Dict[str, Any]] = None,
    ) -> int:
        async with self.acquire() as conn:
            state_id = await conn.fetchval(
                """
                INSERT INTO core.agent_state
                    (identity_id, entropy, integrity, stability_index, volatility, regime, coherence, state_json)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING state_id
                """,
                identity_id, entropy, integrity, stability_index, void,  # void maps to volatility column
                regime, coherence, json.dumps(state_json or {}),
            )
            return state_id

    async def get_latest_agent_state(
        self,
        identity_id: int,
    ) -> Optional[AgentStateRecord]:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.state_id, s.identity_id, i.agent_id, s.recorded_at,
                       s.entropy, s.integrity, s.stability_index, s.volatility,
                       s.regime, s.coherence, s.state_json
                FROM core.agent_state s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id = $1
                ORDER BY s.recorded_at DESC
                LIMIT 1
                """,
                identity_id,
            )
            if not row:
                return None
            return self._row_to_agent_state(row)

    async def get_agent_state_history(
        self,
        identity_id: int,
        limit: int = 100,
    ) -> List[AgentStateRecord]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.state_id, s.identity_id, i.agent_id, s.recorded_at,
                       s.entropy, s.integrity, s.stability_index, s.volatility,
                       s.regime, s.coherence, s.state_json
                FROM core.agent_state s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id = $1
                ORDER BY s.recorded_at DESC
                LIMIT $2
                """,
                identity_id, limit,
            )
            return [self._row_to_agent_state(r) for r in rows]

    async def get_all_latest_agent_states(self) -> list[AgentStateRecord]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (s.identity_id)
                       s.state_id, s.identity_id, i.agent_id, s.recorded_at,
                       s.entropy, s.integrity, s.stability_index, s.volatility,
                       s.regime, s.coherence, s.state_json
                FROM core.agent_state s
                JOIN core.identities i ON i.identity_id = s.identity_id
                ORDER BY s.identity_id, s.recorded_at DESC
                """
            )
            return [self._row_to_agent_state(r) for r in rows]

    async def get_recent_cross_agent_activity(
        self,
        exclude_identity_id: int,
        minutes: int = 60,
    ) -> list[dict]:
        """Get recent activity from other agents, grouped by agent.

        Returns list of dicts with agent_id, recorded_at (most recent), count.
        """
        from config.governance_config import GovernanceConfig
        window = minutes or GovernanceConfig.TEMPORAL_CROSS_AGENT_MINUTES
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT i.agent_id,
                       MAX(s.recorded_at) as recorded_at,
                       COUNT(*) as count
                FROM core.agent_state s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id != $1
                  AND s.recorded_at > now() - ($2 * interval '1 minute')
                GROUP BY i.agent_id
                ORDER BY MAX(s.recorded_at) DESC
                LIMIT 5
                """,
                exclude_identity_id, window,
            )
            return [dict(r) for r in rows]

    def _row_to_agent_state(self, row) -> AgentStateRecord:
        return AgentStateRecord(
            state_id=row["state_id"],
            identity_id=row["identity_id"],
            agent_id=row["agent_id"],
            recorded_at=row["recorded_at"],
            entropy=row["entropy"],
            integrity=row["integrity"],
            stability_index=row["stability_index"],
            void=row["volatility"],  # Map database column 'volatility' to 'void' field
            regime=row["regime"],
            coherence=row["coherence"],
            state_json=json.loads(row["state_json"]) if isinstance(row["state_json"], str) else row["state_json"],
        )
