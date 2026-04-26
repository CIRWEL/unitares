"""
PostgreSQL Knowledge Graph Backend

Implements the knowledge graph interface using PostgreSQL with FTS (tsvector).
This provides unified storage with the main database and better FTS than AGE.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from src.knowledge_graph import DiscoveryNode, ResponseTo
from src.logging_utils import get_logger

logger = get_logger(__name__)

_TIMESTAMP_COLUMNS = ("updated_at", "resolved_at")


def _coerce_timestamp(value: Any) -> Any:
    """Accept ISO-format strings for timestamp columns; pass datetimes through.

    asyncpg binds ``timestamp with time zone`` strictly and rejects strings.
    AGE callers serialize timestamps as ISO strings, so the PG backend
    normalizes at the boundary.
    """
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


class KnowledgeGraphPostgres:
    """
    PostgreSQL-backed knowledge graph with full-text search.

    Uses the knowledge.discoveries table with tsvector FTS.
    """

    def __init__(self):
        self._db = None
        self._initialized = False

    async def _get_db(self):
        """Get or initialize the postgres backend."""
        if self._db is None:
            from src.db import get_db
            self._db = get_db()
            if not hasattr(self._db, '_pool') or self._db._pool is None:
                await self._db.init()
        return self._db

    async def load(self) -> None:
        """Initialize connection (compatibility with other backends)."""
        await self._get_db()
        self._initialized = True
        logger.info("PostgreSQL knowledge graph backend initialized")

    async def add_discovery(self, discovery: DiscoveryNode) -> None:
        """Add a discovery to the knowledge graph."""
        db = await self._get_db()
        await db.kg_add_discovery(discovery)

    async def query(
        self,
        agent_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        exclude_archived: bool = False,
    ) -> List[DiscoveryNode]:
        """Query discoveries with filters."""
        db = await self._get_db()
        # If exclude_archived and no explicit status filter, filter to non-archived
        effective_status = status
        if exclude_archived and not status:
            effective_status = "!archived"  # Convention: kg_query handles this
        rows = await db.kg_query(
            agent_id=agent_id,
            tags=tags,
            type=type,
            severity=severity,
            status=effective_status if effective_status != "!archived" else status,
            limit=limit,
        )
        # Post-hoc filter as fallback since kg_query may not support negated status
        if exclude_archived and not status:
            rows = [r for r in rows if r.get("status") != "archived"]
        return [self._dict_to_discovery(r) for r in rows]

    async def full_text_search(
        self, query: str, limit: int = 20, operator: str = "AND",
    ) -> List[DiscoveryNode]:
        """Full-text search using PostgreSQL tsvector. Defaults to AND (#165)."""
        db = await self._get_db()
        rows = await db.kg_full_text_search(query, limit, operator=operator)
        return [self._dict_to_discovery(r) for r in rows]

    async def find_similar(self, discovery: DiscoveryNode, limit: int = 10) -> List[DiscoveryNode]:
        """Find similar discoveries by tag overlap."""
        db = await self._get_db()
        rows = await db.kg_find_similar(discovery.id, limit)
        return [self._dict_to_discovery(r) for r in rows]

    async def get_discovery(self, discovery_id: str) -> Optional[DiscoveryNode]:
        """Get a single discovery by ID."""
        db = await self._get_db()
        row = await db.kg_get_discovery(discovery_id)
        if row:
            return self._dict_to_discovery(row)
        return None

    async def update_discovery_status(
        self,
        discovery_id: str,
        status: str,
        resolved_at: Optional[str] = None,
    ) -> bool:
        """Update discovery status."""
        db = await self._get_db()
        return await db.kg_update_status(discovery_id, status, resolved_at)

    async def update_discovery(self, discovery_id: str, updates: Dict[str, Any]) -> bool:
        """Update discovery fields.

        Supports updating: status, resolved_at, updated_at, tags, severity, type,
        summary, and details.
        """
        from src.knowledge_graph import normalize_tags
        db = await self._get_db()

        # Build dynamic UPDATE query
        set_clauses = []
        params = [discovery_id]
        param_idx = 2

        for key, value in updates.items():
            if key in ("status", "resolved_at", "updated_at", "severity", "type", "summary", "details"):
                set_clauses.append(f"{key} = ${param_idx}")
                if key in _TIMESTAMP_COLUMNS:
                    value = _coerce_timestamp(value)
                params.append(value)
                param_idx += 1
            elif key == "tags":
                # Normalize tags before storage
                tag_list = value if isinstance(value, list) else [value]
                set_clauses.append(f"tags = ${param_idx}")
                params.append(normalize_tags(tag_list))
                param_idx += 1

        if not set_clauses:
            return True  # Nothing to update

        query = f"""
            UPDATE knowledge.discoveries
            SET {', '.join(set_clauses)}
            WHERE id = $1
            RETURNING id
        """

        result = await db._pool.fetchval(query, *params)
        return result is not None

    async def get_stats(self) -> Dict[str, Any]:
        """Get knowledge graph statistics for current epoch."""
        from config.governance_config import GovernanceConfig
        db = await self._get_db()
        epoch = GovernanceConfig.CURRENT_EPOCH

        # Get total discoveries
        total = await db._pool.fetchval(
            "SELECT COUNT(*) FROM knowledge.discoveries WHERE epoch = $1", epoch)

        # Get discoveries by agent
        by_agent_rows = await db._pool.fetch("""
            SELECT agent_id, COUNT(*) as count
            FROM knowledge.discoveries WHERE epoch = $1
            GROUP BY agent_id
        """, epoch)
        by_agent = {row['agent_id']: row['count'] for row in by_agent_rows}

        # Get discoveries by type
        by_type_rows = await db._pool.fetch("""
            SELECT type, COUNT(*) as count
            FROM knowledge.discoveries WHERE epoch = $1
            GROUP BY type
        """, epoch)
        by_type = {row['type']: row['count'] for row in by_type_rows}

        # Get discoveries by status
        by_status_rows = await db._pool.fetch("""
            SELECT status, COUNT(*) as count
            FROM knowledge.discoveries WHERE epoch = $1
            GROUP BY status
        """, epoch)
        by_status = {row['status']: row['count'] for row in by_status_rows}

        return {
            "total_discoveries": total or 0,
            "by_agent": by_agent,
            "by_type": by_type,
            "by_status": by_status,
            "total_agents": len(by_agent),
            "epoch": epoch,
        }

    async def get_agent_discoveries(
        self, agent_id: str, limit: Optional[int] = None
    ) -> List[DiscoveryNode]:
        """Get all discoveries for a specific agent."""
        return await self.query(agent_id=agent_id, limit=limit or 100)

    def _dict_to_discovery(self, d: Dict[str, Any]) -> DiscoveryNode:
        """Convert database dict to DiscoveryNode."""
        # Handle response_to
        response_to = None
        if d.get('response_to_id') and d.get('response_type'):
            response_to = ResponseTo(
                discovery_id=d['response_to_id'],
                response_type=d['response_type'],
            )

        return DiscoveryNode(
            id=d['id'],
            agent_id=d['agent_id'],
            type=d['type'],
            summary=d['summary'],
            details=d.get('details', ''),
            tags=d.get('tags', []),
            severity=d.get('severity'),
            timestamp=d.get('timestamp', d.get('created_at', '')),
            status=d.get('status', 'open'),
            related_to=d.get('related_to', []),
            response_to=response_to,
            references_files=d.get('references_files', []),
            resolved_at=d.get('resolved_at'),
            updated_at=d.get('updated_at'),
            provenance=d.get('provenance'),
        )
