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

    async def record_bootstrap_state(
        self,
        identity_id: int,
        entropy: float,
        integrity: float,
        stability_index: float,
        void: float,
        regime: str,
        coherence: float,
        state_json: Dict[str, Any],
    ) -> tuple[int, bool]:
        """Insert a synthetic bootstrap row, idempotent on (identity_id) via the
        unique partial index from migration 018. Returns (state_id, was_written).

        On UniqueViolationError (race lost or already-bootstrapped), looks up
        the existing bootstrap row and returns its state_id with was_written=False.
        Callers use was_written to populate `bootstrap.written` in the response.
        """
        import asyncpg
        from config.governance_config import GovernanceConfig
        async with self.acquire() as conn:
            try:
                state_id = await conn.fetchval(
                    """
                    INSERT INTO core.agent_state
                        (identity_id, entropy, integrity, stability_index, volatility,
                         regime, coherence, state_json, epoch, synthetic)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, true)
                    RETURNING state_id
                    """,
                    identity_id, entropy, integrity, stability_index, void,
                    regime, coherence, json.dumps(state_json),
                    GovernanceConfig.CURRENT_EPOCH,
                )
                return state_id, True
            except asyncpg.UniqueViolationError:
                existing = await conn.fetchval(
                    """
                    SELECT state_id FROM core.agent_state
                    WHERE identity_id = $1 AND synthetic = true
                    """,
                    identity_id,
                )
                return existing, False

    async def get_bootstrap_state(
        self,
        identity_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Return the bootstrap row for an identity, or None if absent.

        Returns {state_id, state_json} — the digest is read from state_json
        by the handler, not pulled out as a separate column.
        """
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT state_id, state_json
                FROM core.agent_state
                WHERE identity_id = $1 AND synthetic = true
                """,
                identity_id,
            )
            if row is None:
                return None
            state_json = row["state_json"]
            if isinstance(state_json, str):
                state_json = json.loads(state_json)
            return {"state_id": row["state_id"], "state_json": state_json}

    async def is_substrate_earned(self, agent_id: str) -> bool:
        """Substrate-earned check for the bootstrap-checkin exemption (§3.5).

        True iff the agent_id is registered in core.substrate_claims (S19's
        canonical resident-attestation registry) OR appears in the small
        Pi-resident allowlist for cross-substrate cases like Lumen.
        """
        from src.mcp_handlers.identity.bootstrap_checkin import (
            PI_RESIDENT_ALLOWLIST,
        )
        if agent_id in PI_RESIDENT_ALLOWLIST:
            return True
        async with self.acquire() as conn:
            return bool(
                await conn.fetchval(
                    "SELECT 1 FROM core.substrate_claims WHERE agent_id = $1",
                    agent_id,
                )
            )

    async def get_latest_agent_state(
        self,
        identity_id: int,
    ) -> Optional[AgentStateRecord]:
        """Latest measured state for an identity. Bootstrap (synthetic) rows
        are excluded by default per onboard-bootstrap-checkin §4.1; this is
        the user-visible "what is this agent's current state" question, and
        a synthetic anchor is not the answer."""
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
                  AND s.synthetic = false
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
        exclude_synthetic: bool = False,
    ) -> List[AgentStateRecord]:
        """State-row history for an identity.

        Per onboard-bootstrap-checkin §4 inclusion rule #2 ("Identity audit /
        lineage queries"), the default INCLUDES synthetic rows — history is
        the audit/lineage record and legitimately wants the full picture.
        Bootstrap rows in the result carry their flag in `state_json` (and
        the underlying row's `synthetic` column is true) so callers can
        introspect.

        Set `exclude_synthetic=True` for measured-only history reads. The
        canonical caller for that mode is `hydrate_from_db_if_fresh` in
        agent_monitor_state.py — the in-memory monitor must NEVER be seeded
        from a synthetic row, because every downstream consumer of
        monitor.state (self-recovery, dialectic, trajectory ODE) treats
        seeded values as measured. See
        docs/proposals/onboard-bootstrap-checkin.filter-audit.md sites #5/#6.
        """
        from config.governance_config import GovernanceConfig
        async with self.acquire() as conn:
            base_sql = """
                SELECT s.state_id, s.identity_id, i.agent_id, s.recorded_at,
                       s.entropy, s.integrity, s.stability_index, s.volatility,
                       s.regime, s.coherence, s.state_json
                FROM core.agent_state s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id = $1 AND s.epoch = $2
            """
            if exclude_synthetic:
                base_sql += " AND s.synthetic = false"
            base_sql += " ORDER BY s.recorded_at DESC LIMIT $3"
            rows = await conn.fetch(
                base_sql,
                identity_id, GovernanceConfig.CURRENT_EPOCH, limit,
            )
            return [self._row_to_agent_state(r) for r in rows]

    async def get_all_latest_agent_states(self) -> list[AgentStateRecord]:
        """Get latest measured state per identity, using matview with base-table fallback.

        The matview is measured-only by definition (migration 019 bakes
        `WHERE synthetic = false` into the matview SELECT), so the matview
        path needs no query-time filter. The base-table fallback queries
        agent_state directly and adds the filter explicitly. Both paths
        agree: bootstrap rows never appear here. Per onboard-bootstrap-
        checkin §4.1.
        """
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
                # Matview may not exist yet — fall back to base table.
                # Filter `synthetic = false` here because the base table
                # contains both measured and synthetic rows.
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
                      AND s.synthetic = false
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
        """Get recent measured activity from other agents, grouped by agent.

        Returns list of dicts with agent_id, recorded_at (most recent), count.
        Bootstrap (synthetic) rows are excluded — the COUNT is "how many real
        check-ins" and a session-start anchor is not activity. Per onboard-
        bootstrap-checkin §4.1.
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
                  AND s.synthetic = false
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
