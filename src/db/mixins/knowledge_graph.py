"""Knowledge graph operations mixin for PostgresBackend."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.logging_utils import get_logger

logger = get_logger(__name__)


class KnowledgeGraphMixin:
    """Knowledge graph (PostgreSQL FTS) discovery operations."""

    async def kg_add_discovery(self, discovery) -> None:
        """Add a discovery to the knowledge graph."""
        from datetime import datetime as dt
        from src.knowledge_graph import normalize_tags

        if hasattr(discovery, 'tags') and discovery.tags:
            discovery.tags = normalize_tags(discovery.tags)

        async with self.acquire() as conn:
            response_to_id = None
            response_type = None
            if hasattr(discovery, 'response_to') and discovery.response_to:
                response_to_id = discovery.response_to.discovery_id
                response_type = discovery.response_to.response_type

            created_at = None
            if hasattr(discovery, 'timestamp') and discovery.timestamp:
                ts = discovery.timestamp
                if isinstance(ts, str):
                    try:
                        created_at = dt.fromisoformat(ts.replace('Z', '+00:00'))
                    except ValueError:
                        created_at = dt.now()
                elif isinstance(ts, dt):
                    created_at = ts
                else:
                    created_at = dt.now()

            await conn.execute("""
                INSERT INTO knowledge.discoveries (
                    id, agent_id, type, summary, details, tags, severity, status,
                    references_files, related_to, response_to_id, response_type,
                    provenance, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (id) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    details = EXCLUDED.details,
                    tags = EXCLUDED.tags,
                    status = EXCLUDED.status,
                    updated_at = now()
            """,
                discovery.id,
                discovery.agent_id,
                discovery.type,
                discovery.summary,
                discovery.details or "",
                discovery.tags or [],
                discovery.severity or "low",
                discovery.status or "open",
                discovery.references_files or [],
                discovery.related_to or [],
                response_to_id,
                response_type,
                json.dumps(discovery.provenance) if discovery.provenance else None,
                created_at,
            )

    async def kg_query(
        self,
        agent_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        created_after: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query discoveries with filters."""
        async with self.acquire() as conn:
            conditions = []
            params = []
            param_idx = 1

            if agent_id:
                conditions.append(f"agent_id = ${param_idx}")
                params.append(agent_id)
                param_idx += 1
            if type:
                conditions.append(f"type = ${param_idx}")
                params.append(type)
                param_idx += 1
            if severity:
                conditions.append(f"severity = ${param_idx}")
                params.append(severity)
                param_idx += 1
            if status:
                conditions.append(f"status = ${param_idx}")
                params.append(status)
                param_idx += 1
            if tags:
                from src.knowledge_graph import normalize_tags
                conditions.append(f"tags && ${param_idx}")
                params.append(normalize_tags(tags))
                param_idx += 1
            if created_after:
                conditions.append(f"created_at > ${param_idx}")
                params.append(created_after)
                param_idx += 1

            where_clause = " AND ".join(conditions) if conditions else "1=1"
            params.append(limit)

            rows = await conn.fetch(f"""
                SELECT * FROM knowledge.discoveries
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ${param_idx}
            """, *params)

            results = [self._row_to_discovery_dict(row) for row in rows]

            if results:
                ids = [r["id"] for r in results]
                backlink_rows = await conn.fetch("""
                    SELECT response_to_id, id FROM knowledge.discoveries
                    WHERE response_to_id = ANY($1)
                    ORDER BY created_at
                """, ids)
                backlinks_map: Dict[str, List[str]] = {}
                for br in backlink_rows:
                    backlinks_map.setdefault(br["response_to_id"], []).append(br["id"])
                for r in results:
                    if r["id"] in backlinks_map:
                        r["responses_from"] = backlinks_map[r["id"]]

            return results

    async def kg_full_text_search(
        self,
        query: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Full-text search using PostgreSQL tsvector."""
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT *, ts_rank(search_vector, websearch_to_tsquery('english', $1)) as rank
                FROM knowledge.discoveries
                WHERE search_vector @@ websearch_to_tsquery('english', $1)
                ORDER BY rank DESC, created_at DESC
                LIMIT $2
            """, query, limit)

            return [self._row_to_discovery_dict(row) for row in rows]

    async def kg_find_similar(
        self,
        discovery_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Find similar discoveries by tag overlap."""
        async with self.acquire() as conn:
            source_row = await conn.fetchrow(
                "SELECT tags FROM knowledge.discoveries WHERE id = $1",
                discovery_id
            )
            if not source_row or not source_row['tags']:
                return []

            source_tags = source_row['tags']

            rows = await conn.fetch("""
                SELECT d.*,
                       cardinality(ARRAY(SELECT unnest(d.tags) INTERSECT SELECT unnest($1::text[]))) as overlap
                FROM knowledge.discoveries d
                WHERE d.id != $2
                  AND d.tags && $1::text[]
                ORDER BY overlap DESC, created_at DESC
                LIMIT $3
            """, source_tags, discovery_id, limit)

            return [self._row_to_discovery_dict(row) for row in rows]

    async def kg_get_discovery(self, discovery_id: str) -> Optional[Dict[str, Any]]:
        """Get a single discovery by ID, including backlinks."""
        async with self.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM knowledge.discoveries WHERE id = $1
            """, discovery_id)

            if not row:
                return None

            d = self._row_to_discovery_dict(row)

            backlinks = await conn.fetch("""
                SELECT id FROM knowledge.discoveries
                WHERE response_to_id = $1
                ORDER BY created_at
            """, discovery_id)
            if backlinks:
                d["responses_from"] = [r["id"] for r in backlinks]

            return d

    async def kg_update_status(
        self,
        discovery_id: str,
        status: str,
        resolved_at: Optional[str] = None,
    ) -> bool:
        """Update discovery status."""
        async with self.acquire() as conn:
            if resolved_at:
                result = await conn.execute("""
                    UPDATE knowledge.discoveries
                    SET status = $1, resolved_at = $2, updated_at = now()
                    WHERE id = $3
                """, status, resolved_at, discovery_id)
            else:
                result = await conn.execute("""
                    UPDATE knowledge.discoveries
                    SET status = $1, updated_at = now()
                    WHERE id = $2
                """, status, discovery_id)
            return "UPDATE 1" in result

    def _row_to_discovery_dict(self, row) -> Dict[str, Any]:
        """Convert a database row to discovery dict."""
        d = dict(row)
        for ts_field in ['created_at', 'updated_at', 'resolved_at']:
            if d.get(ts_field):
                d[ts_field] = d[ts_field].isoformat()
        if 'created_at' in d:
            d['timestamp'] = d['created_at']
        if d.get('provenance') and isinstance(d['provenance'], str):
            d['provenance'] = json.loads(d['provenance'])
        d.pop('search_vector', None)
        d.pop('rank', None)
        d.pop('overlap', None)
        return d
