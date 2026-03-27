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
        from config.governance_config import GovernanceConfig
        async with self.acquire() as conn:
            state_id = await conn.fetchval(
                """
                INSERT INTO core.agent_state
                    (identity_id, entropy, integrity, stability_index, volatility, regime, coherence, state_json, epoch)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING state_id
                """,
                identity_id, entropy, integrity, stability_index, void,  # void maps to volatility column
                regime, coherence, json.dumps(state_json or {}),
                GovernanceConfig.CURRENT_EPOCH,
            )
            # Matview refresh moved to periodic_matview_refresh() in background_tasks.py
            return state_id

    async def get_latest_agent_state(
        self,
        identity_id: int,
    ) -> Optional[AgentStateRecord]:
        from config.governance_config import GovernanceConfig
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.state_id, s.identity_id, i.agent_id, s.recorded_at,
                       s.entropy, s.integrity, s.stability_index, s.volatility,
                       s.regime, s.coherence, s.state_json
                FROM core.agent_state s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id = $1 AND s.epoch = $2
                ORDER BY s.recorded_at DESC
                LIMIT 1
                """,
                identity_id, GovernanceConfig.CURRENT_EPOCH,
            )
            if not row:
                return None
            return self._row_to_agent_state(row)

    async def get_agent_state_history(
        self,
        identity_id: int,
        limit: int = 100,
    ) -> List[AgentStateRecord]:
        from config.governance_config import GovernanceConfig
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.state_id, s.identity_id, i.agent_id, s.recorded_at,
                       s.entropy, s.integrity, s.stability_index, s.volatility,
                       s.regime, s.coherence, s.state_json
                FROM core.agent_state s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id = $1 AND s.epoch = $2
                ORDER BY s.recorded_at DESC
                LIMIT $3
                """,
                identity_id, GovernanceConfig.CURRENT_EPOCH, limit,
            )
            return [self._row_to_agent_state(r) for r in rows]

    async def get_all_latest_agent_states(self) -> list[AgentStateRecord]:
        """Get latest state per identity, using matview with base-table fallback."""
        async with self.acquire() as conn:
            try:
                rows = await conn.fetch(
                    """
                    SELECT state_id, identity_id, agent_id, recorded_at,
                           entropy, integrity, stability_index, volatility,
                           regime, coherence, state_json
                    FROM core.mv_latest_agent_states
                    """,
                )
            except Exception:
                # Matview may not exist yet — fall back to base table
                from config.governance_config import GovernanceConfig
                logger.debug("Matview unavailable, falling back to base table")
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT ON (s.identity_id)
                           s.state_id, s.identity_id, i.agent_id, s.recorded_at,
                           s.entropy, s.integrity, s.stability_index, s.volatility,
                           s.regime, s.coherence, s.state_json
                    FROM core.agent_state s
                    JOIN core.identities i ON i.identity_id = s.identity_id
                    WHERE s.epoch = $1
                    ORDER BY s.identity_id, s.recorded_at DESC
                    """,
                    GovernanceConfig.CURRENT_EPOCH,
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
                  AND s.epoch = $3
                GROUP BY i.agent_id
                ORDER BY MAX(s.recorded_at) DESC
                LIMIT 5
                """,
                exclude_identity_id, window, GovernanceConfig.CURRENT_EPOCH,
            )
            return [dict(r) for r in rows]

    def _row_to_agent_state(self, row) -> AgentStateRecord:
        sj = json.loads(row["state_json"]) if isinstance(row["state_json"], str) else (row["state_json"] or {})
        return AgentStateRecord(
            state_id=row["state_id"],
            identity_id=row["identity_id"],
            agent_id=row["agent_id"],
            recorded_at=row["recorded_at"],
            energy=sj.get("E", 0.5),
            entropy=row["entropy"],
            integrity=row["integrity"],
            stability_index=row["stability_index"],
            void=row["volatility"],  # Map database column 'volatility' to 'void' field
            regime=row["regime"],
            coherence=row["coherence"],
            state_json=sj,
        )
