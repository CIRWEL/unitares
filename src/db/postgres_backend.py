"""
PostgreSQL + AGE Backend

Async PostgreSQL backend using asyncpg with Apache AGE for graph queries.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore

from .base import (
    DatabaseBackend,
    IdentityRecord,
    SessionRecord,
    AgentStateRecord,
    AuditEvent,
)


class PostgresBackend(DatabaseBackend):
    """
    PostgreSQL + AGE backend.

    Requires:
        pip install asyncpg

    Environment:
        DB_POSTGRES_URL=postgresql://user:pass@host:port/dbname
        DB_POSTGRES_MIN_CONN=2
        DB_POSTGRES_MAX_CONN=10
        DB_AGE_GRAPH=governance
    """

    def __init__(self):
        if asyncpg is None:
            raise ImportError("asyncpg is required for PostgreSQL backend. pip install asyncpg")

        self._pool: Optional[asyncpg.Pool] = None
        self._db_url = os.environ.get("DB_POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/governance")
        self._min_conn = int(os.environ.get("DB_POSTGRES_MIN_CONN", "2"))
        self._max_conn = int(os.environ.get("DB_POSTGRES_MAX_CONN", "10"))
        self._age_graph = os.environ.get("DB_AGE_GRAPH", "governance")

    async def init(self) -> None:
        """Initialize connection pool and verify schema."""
        self._pool = await asyncpg.create_pool(
            self._db_url,
            min_size=self._min_conn,
            max_size=self._max_conn,
            command_timeout=30,
        )

        # Verify schema exists
        async with self._pool.acquire() as conn:
            # Check core schema
            result = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core')"
            )
            if not result:
                raise RuntimeError(
                    "PostgreSQL schema not initialized. Run db/postgres/schema.sql first."
                )

            # Check AGE extension
            try:
                await conn.execute("LOAD 'age'")
                await conn.execute(f"SET search_path = ag_catalog, core, audit, public")
            except Exception:
                # AGE not available, graph queries will be disabled
                pass

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def health_check(self) -> Dict[str, Any]:
        """Return health/status information."""
        if not self._pool:
            return {"status": "error", "error": "Pool not initialized"}

        async with self._pool.acquire() as conn:
            # Basic connectivity
            result = await conn.fetchval("SELECT 1")

            # Schema version
            version = await conn.fetchval(
                "SELECT data->>'version' FROM core.calibration WHERE id = TRUE"
            )

            # Counts
            identity_count = await conn.fetchval("SELECT COUNT(*) FROM core.identities")
            session_count = await conn.fetchval("SELECT COUNT(*) FROM core.sessions WHERE is_active = TRUE")

            # AGE status
            age_available = False
            try:
                await conn.execute("LOAD 'age'")
                age_available = True
            except Exception:
                pass

            return {
                "status": "healthy",
                "backend": "postgres",
                "db_url": self._db_url.split("@")[-1] if "@" in self._db_url else "***",  # Hide credentials
                "pool_size": self._pool.get_size(),
                "pool_free": self._pool.get_idle_size(),
                "schema_version": version,
                "identity_count": identity_count,
                "active_session_count": session_count,
                "age_available": age_available,
                "age_graph": self._age_graph if age_available else None,
            }

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
        async with self._pool.acquire() as conn:
            identity_id = await conn.fetchval(
                """
                INSERT INTO core.identities (agent_id, api_key_hash, parent_agent_id, metadata, created_at)
                VALUES ($1, $2, $3, $4, COALESCE($5, now()))
                ON CONFLICT (agent_id) DO UPDATE SET
                    metadata = core.identities.metadata || COALESCE($4, '{}'::jsonb),
                    updated_at = now()
                RETURNING identity_id
                """,
                agent_id,
                api_key_hash,
                parent_agent_id,
                json.dumps(metadata or {}),
                created_at,
            )
            return identity_id

    async def get_identity(self, agent_id: str) -> Optional[IdentityRecord]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                       status, parent_agent_id, spawn_reason, disabled_at, metadata
                FROM core.identities
                WHERE agent_id = $1
                """,
                agent_id,
            )
            if not row:
                return None
            return self._row_to_identity(row)

    async def get_identity_by_id(self, identity_id: int) -> Optional[IdentityRecord]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                       status, parent_agent_id, spawn_reason, disabled_at, metadata
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
        async with self._pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT identity_id, agent_id, api_key_hash, created_at, updated_at,
                           status, parent_agent_id, spawn_reason, disabled_at, metadata
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
                           status, parent_agent_id, spawn_reason, disabled_at, metadata
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
        disabled_at: Optional[datetime] = None,
    ) -> bool:
        async with self._pool.acquire() as conn:
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
        async with self._pool.acquire() as conn:
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

    async def verify_api_key(self, agent_id: str, api_key: str) -> bool:
        async with self._pool.acquire() as conn:
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
            metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
        )

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
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO core.sessions (session_id, identity_id, expires_at, client_type, client_info)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    session_id, identity_id, expires_at, client_type, json.dumps(client_info or {}),
                )
                return True
            except asyncpg.UniqueViolationError:
                return False

    async def get_session(self, session_id: str) -> Optional[SessionRecord]:
        async with self._pool.acquire() as conn:
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
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE core.sessions
                SET last_active = now()
                WHERE session_id = $1 AND is_active = TRUE
                """,
                session_id,
            )
            return "UPDATE 1" in result

    async def end_session(self, session_id: str) -> bool:
        async with self._pool.acquire() as conn:
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
        async with self._pool.acquire() as conn:
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

    async def cleanup_expired_sessions(self) -> int:
        async with self._pool.acquire() as conn:
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
        async with self._pool.acquire() as conn:
            state_id = await conn.fetchval(
                """
                INSERT INTO core.agent_state
                    (identity_id, entropy, integrity, stability_index, volatility, regime, coherence, state_json)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING state_id
                """,
                identity_id, entropy, integrity, stability_index, volatility,
                regime, coherence, json.dumps(state_json or {}),
            )
            return state_id

    async def get_latest_agent_state(
        self,
        identity_id: int,
    ) -> Optional[AgentStateRecord]:
        async with self._pool.acquire() as conn:
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
        async with self._pool.acquire() as conn:
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

    def _row_to_agent_state(self, row) -> AgentStateRecord:
        return AgentStateRecord(
            state_id=row["state_id"],
            identity_id=row["identity_id"],
            agent_id=row["agent_id"],
            recorded_at=row["recorded_at"],
            entropy=row["entropy"],
            integrity=row["integrity"],
            stability_index=row["stability_index"],
            volatility=row["volatility"],
            regime=row["regime"],
            coherence=row["coherence"],
            state_json=json.loads(row["state_json"]) if isinstance(row["state_json"], str) else row["state_json"],
        )

    # =========================================================================
    # AUDIT OPERATIONS
    # =========================================================================

    async def append_audit_event(self, event: AuditEvent) -> bool:
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO audit.events (ts, event_id, agent_id, session_id, event_type, confidence, payload, raw_hash)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT DO NOTHING
                    """,
                    event.ts or datetime.now(timezone.utc),
                    event.event_id or str(uuid.uuid4()),
                    event.agent_id,
                    event.session_id,
                    event.event_type,
                    event.confidence,
                    json.dumps(event.payload),
                    event.raw_hash,
                )
                return True
            except Exception:
                return False

    async def query_audit_events(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
        order: str = "asc",
    ) -> List[AuditEvent]:
        conditions = []
        params = []
        param_idx = 1

        if agent_id:
            conditions.append(f"agent_id = ${param_idx}")
            params.append(agent_id)
            param_idx += 1
        if event_type:
            conditions.append(f"event_type = ${param_idx}")
            params.append(event_type)
            param_idx += 1
        if start_time:
            conditions.append(f"ts >= ${param_idx}")
            params.append(start_time)
            param_idx += 1
        if end_time:
            conditions.append(f"ts <= ${param_idx}")
            params.append(end_time)
            param_idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_clause = "ASC" if order.lower() == "asc" else "DESC"

        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT ts, event_id, agent_id, session_id, event_type, confidence, payload, raw_hash
                FROM audit.events
                {where_clause}
                ORDER BY ts {order_clause}
                LIMIT ${param_idx}
                """,
                *params,
            )
            return [self._row_to_audit_event(r) for r in rows]

    async def search_audit_events(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[AuditEvent]:
        # Use pg_trgm for fuzzy search on payload
        async with self._pool.acquire() as conn:
            if agent_id:
                rows = await conn.fetch(
                    """
                    SELECT ts, event_id, agent_id, session_id, event_type, confidence, payload, raw_hash
                    FROM audit.events
                    WHERE payload::text ILIKE '%' || $1 || '%' AND agent_id = $2
                    ORDER BY ts DESC
                    LIMIT $3
                    """,
                    query, agent_id, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT ts, event_id, agent_id, session_id, event_type, confidence, payload, raw_hash
                    FROM audit.events
                    WHERE payload::text ILIKE '%' || $1 || '%'
                    ORDER BY ts DESC
                    LIMIT $2
                    """,
                    query, limit,
                )
            return [self._row_to_audit_event(r) for r in rows]

    def _row_to_audit_event(self, row) -> AuditEvent:
        return AuditEvent(
            ts=row["ts"],
            event_id=str(row["event_id"]),
            event_type=row["event_type"],
            agent_id=row["agent_id"],
            session_id=row["session_id"],
            confidence=row["confidence"],
            payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            raw_hash=row["raw_hash"],
        )

    # =========================================================================
    # CALIBRATION OPERATIONS
    # =========================================================================

    async def get_calibration(self) -> Dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data, updated_at, version FROM core.calibration WHERE id = TRUE"
            )
            if not row:
                return {}
            data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
            data["_updated_at"] = row["updated_at"].isoformat() if row["updated_at"] else None
            data["_version"] = row["version"]
            return data

    async def update_calibration(self, data: Dict[str, Any]) -> bool:
        # Remove internal fields
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE core.calibration
                SET data = $1::jsonb, updated_at = now(), version = version + 1
                WHERE id = TRUE
                """,
                json.dumps(clean_data),
            )
            return "UPDATE 1" in result

    # =========================================================================
    # GRAPH OPERATIONS (AGE)
    # =========================================================================

    async def graph_available(self) -> bool:
        """Check if AGE graph queries are available."""
        async with self._pool.acquire() as conn:
            try:
                await conn.execute("LOAD 'age'")
                return True
            except Exception:
                return False

    async def graph_query(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query against the AGE graph.
        
        Parameters are validated and safely interpolated since AGE doesn't support
        parameterized Cypher queries ($1, $2 style).
        """
        async with self._pool.acquire() as conn:
            try:
                await conn.execute("LOAD 'age'")
                await conn.execute(f"SET search_path = ag_catalog, core, audit, public")

                # AGE requires wrapping Cypher in cypher() function
                # Parameters must be embedded in the query (AGE doesn't support $1, $2 for Cypher)
                safe_cypher = cypher
                if params:
                    for k, v in params.items():
                        safe_value = self._sanitize_cypher_param(v)
                        # Use regex to replace only parameter placeholders, not arbitrary ${...} patterns
                        safe_cypher = re.sub(rf'\$\{{{re.escape(k)}\}}', safe_value, safe_cypher)

                rows = await conn.fetch(
                    f"SELECT * FROM cypher('{self._age_graph}', $$ {safe_cypher} $$) as (result agtype)"
                )

                results = []
                for row in rows:
                    # Parse agtype JSON
                    result = row["result"]
                    if isinstance(result, str):
                        try:
                            results.append(json.loads(result))
                        except json.JSONDecodeError:
                            results.append(result)
                    elif isinstance(result, (dict, list)):
                        results.append(result)
                    else:
                        # Handle primitive types (int, float, bool, None)
                        results.append(result)
                return results

            except Exception as e:
                # Log error but don't crash
                return [{"error": str(e)}]

    def _sanitize_cypher_param(self, value: Any) -> str:
        """
        Sanitize a parameter value for safe inclusion in a Cypher query.
        
        AGE doesn't support parameterized queries, so we must validate values.
        """
        if value is None:
            return "NULL"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Validate string doesn't contain injection patterns
            # Allow alphanumeric, underscores, hyphens, spaces, and common punctuation
            if not re.match(r'^[\w\s\-._@/:,()#]+$', value, re.UNICODE):
                # For complex strings, escape single quotes and wrap
                escaped = value.replace("\\", "\\\\").replace("'", "\\'")
                return f"'{escaped}'"
            return f"'{value}'"
        elif isinstance(value, (list, dict)):
            # JSON-encode complex types
            json_str = json.dumps(value).replace("'", "\\'")
            return f"'{json_str}'"
        else:
            raise ValueError(f"Unsupported Cypher param type: {type(value)}")

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
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO audit.tool_usage
                        (ts, agent_id, session_id, tool_name, latency_ms, success, error_type, payload)
                    VALUES (now(), $1, $2, $3, $4, $5, $6, $7)
                    """,
                    agent_id, session_id, tool_name, latency_ms, success, error_type,
                    json.dumps(payload or {}),
                )
                return True
            except Exception:
                return False

    async def query_tool_usage(
        self,
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        conditions = []
        params = []
        param_idx = 1

        if agent_id:
            conditions.append(f"agent_id = ${param_idx}")
            params.append(agent_id)
            param_idx += 1
        if tool_name:
            conditions.append(f"tool_name = ${param_idx}")
            params.append(tool_name)
            param_idx += 1
        if start_time:
            conditions.append(f"ts >= ${param_idx}")
            params.append(start_time)
            param_idx += 1
        if end_time:
            conditions.append(f"ts <= ${param_idx}")
            params.append(end_time)
            param_idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT ts, usage_id, agent_id, session_id, tool_name, latency_ms, success, error_type, payload
                FROM audit.tool_usage
                {where_clause}
                ORDER BY ts DESC
                LIMIT ${param_idx}
                """,
                *params,
            )
            return [
                {
                    "ts": r["ts"],
                    "usage_id": str(r["usage_id"]),
                    "agent_id": r["agent_id"],
                    "session_id": r["session_id"],
                    "tool_name": r["tool_name"],
                    "latency_ms": r["latency_ms"],
                    "success": r["success"],
                    "error_type": r["error_type"],
                    "payload": json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"],
                }
                for r in rows
            ]

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
        async with self._pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO core.dialectic_sessions (
                        session_id, paused_agent_id, reviewer_agent_id,
                        phase, status, created_at, updated_at,
                        reason, discovery_id, dispute_type,
                        session_type, topic, max_synthesis_rounds, synthesis_round,
                        paused_agent_state_json
                    ) VALUES ($1, $2, $3, $4, $5, now(), now(), $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                    session_id,
                    paused_agent_id,
                    reviewer_agent_id,
                    "awaiting_thesis",  # Initial phase
                    "active",
                    reason,
                    discovery_id,
                    dispute_type,
                    session_type,
                    topic,
                    max_synthesis_rounds,
                    synthesis_round or 0,
                    json.dumps(paused_agent_state) if paused_agent_state else None,
                )
                return {"session_id": session_id, "created": True}
            except Exception as e:
                if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                    return {"session_id": session_id, "created": False, "error": "already_exists"}
                raise

    async def get_dialectic_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            # Get session
            row = await conn.fetchrow("""
                SELECT * FROM core.dialectic_sessions WHERE session_id = $1
            """, session_id)
            if not row:
                return None

            session = dict(row)

            # Parse JSON fields
            if session.get("paused_agent_state_json"):
                session["paused_agent_state"] = json.loads(session["paused_agent_state_json"]) if isinstance(session["paused_agent_state_json"], str) else session["paused_agent_state_json"]
            if session.get("resolution_json"):
                session["resolution"] = json.loads(session["resolution_json"]) if isinstance(session["resolution_json"], str) else session["resolution_json"]

            # Get messages
            rows = await conn.fetch("""
                SELECT * FROM core.dialectic_messages
                WHERE session_id = $1
                ORDER BY message_id ASC
            """, session_id)

            messages = []
            for msg_row in rows:
                msg = dict(msg_row)
                # Parse JSON fields
                if msg.get("proposed_conditions"):
                    msg["proposed_conditions"] = json.loads(msg["proposed_conditions"]) if isinstance(msg["proposed_conditions"], str) else msg["proposed_conditions"]
                if msg.get("observed_metrics"):
                    msg["observed_metrics"] = json.loads(msg["observed_metrics"]) if isinstance(msg["observed_metrics"], str) else msg["observed_metrics"]
                if msg.get("concerns"):
                    msg["concerns"] = json.loads(msg["concerns"]) if isinstance(msg["concerns"], str) else msg["concerns"]
                messages.append(msg)

            session["messages"] = messages
            return session

    async def get_dialectic_session_by_agent(
        self,
        agent_id: str,
        active_only: bool = True,
    ) -> Optional[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            status_filter = "AND status = 'active'" if active_only else ""
            row = await conn.fetchrow(f"""
                SELECT session_id FROM core.dialectic_sessions
                WHERE (paused_agent_id = $1 OR reviewer_agent_id = $1)
                {status_filter}
                ORDER BY created_at DESC
                LIMIT 1
            """, agent_id)
            if row:
                return await self.get_dialectic_session(row["session_id"])
            return None

    async def update_dialectic_session_phase(
        self,
        session_id: str,
        phase: str,
    ) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE core.dialectic_sessions
                SET phase = $1, updated_at = now()
                WHERE session_id = $2
            """, phase, session_id)
            return "UPDATE 1" in result

    async def update_dialectic_session_reviewer(
        self,
        session_id: str,
        reviewer_agent_id: str,
    ) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE core.dialectic_sessions
                SET reviewer_agent_id = $1, updated_at = now()
                WHERE session_id = $2
            """, reviewer_agent_id, session_id)
            return "UPDATE 1" in result

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
        async with self._pool.acquire() as conn:
            message_id = await conn.fetchval("""
                INSERT INTO core.dialectic_messages (
                    session_id, agent_id, message_type, timestamp,
                    root_cause, proposed_conditions, reasoning,
                    observed_metrics, concerns, agrees, signature
                ) VALUES ($1, $2, $3, now(), $4, $5, $6, $7, $8, $9, $10)
                RETURNING message_id
            """,
                session_id,
                agent_id,
                message_type,
                root_cause,
                json.dumps(proposed_conditions) if proposed_conditions else None,
                reasoning,
                json.dumps(observed_metrics) if observed_metrics else None,
                json.dumps(concerns) if concerns else None,
                agrees,
                signature,
            )

            # Update session timestamp
            await conn.execute("""
                UPDATE core.dialectic_sessions SET updated_at = now() WHERE session_id = $1
            """, session_id)

            return message_id

    async def resolve_dialectic_session(
        self,
        session_id: str,
        resolution: Dict[str, Any],
        status: str = "resolved",
    ) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE core.dialectic_sessions
                SET status = $1, phase = 'resolved', resolution_json = $2, updated_at = now()
                WHERE session_id = $3
            """,
                status,
                json.dumps(resolution),
                session_id,
            )
            return "UPDATE 1" in result

    async def is_agent_in_active_dialectic_session(self, agent_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT 1 FROM core.dialectic_sessions
                WHERE (paused_agent_id = $1 OR reviewer_agent_id = $1)
                AND status = 'active'
                LIMIT 1
            """, agent_id)
            return result is not None
