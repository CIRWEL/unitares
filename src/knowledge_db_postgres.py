"""
Knowledge Graph PostgreSQL Backend

Drop-in replacement for KnowledgeGraphDB (SQLite) that uses PostgreSQL.
Uses native FTS (tsvector) instead of FTS5, and integrates with pgvector for embeddings.

The interface is identical to KnowledgeGraphDB so it can be swapped transparently.
"""

import json
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Literal, Tuple, Any
from datetime import datetime
from pathlib import Path

from src.logging_utils import get_logger
logger = get_logger(__name__)

# Import shared types from SQLite implementation for compatibility
from src.knowledge_db import DiscoveryNode, ResponseTo


class KnowledgeGraphDBPostgres:
    """
    PostgreSQL-backed knowledge graph.

    Drop-in replacement for SQLite KnowledgeGraphDB.
    Uses:
    - PostgreSQL native FTS (tsvector + websearch_to_tsquery)
    - pgvector for semantic search
    - Connection pooling via asyncpg
    """

    def __init__(self, enable_embeddings: bool = True):
        """Initialize PostgreSQL knowledge graph backend.

        Args:
            enable_embeddings: If True, generate embeddings for semantic search
        """
        self._backend = None  # Lazy-loaded
        self.enable_embeddings = enable_embeddings
        self._embedding_model = None
        self.rate_limit_stores_per_hour = 20

    async def _get_backend(self):
        """Get or create PostgreSQL backend connection."""
        if self._backend is None:
            from src.db import get_db
            self._backend = get_db()
            # Ensure pool is initialized
            try:
                await self._backend.init()
            except Exception as e:
                # May already be initialized
                logger.debug(f"Backend init (may already be done): {e}")
        return self._backend

    async def health_check(self) -> dict:
        """Perform health check on PostgreSQL knowledge graph."""
        try:
            backend = await self._get_backend()
            info = await backend.health_check()

            # Add knowledge-specific stats
            async with backend.acquire() as conn:
                # Check if knowledge schema exists
                schema_exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'knowledge')"
                )

                if schema_exists:
                    discovery_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM knowledge.discoveries"
                    )
                    edge_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM knowledge.discovery_edges"
                    )
                    # FTS smoke test
                    fts_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM knowledge.discoveries WHERE search_vector @@ to_tsquery('test')"
                    )
                else:
                    discovery_count = 0
                    edge_count = 0
                    fts_count = 0

            return {
                "status": "healthy" if info.get("status") == "healthy" else "error",
                "backend": "postgres",
                "db_url": info.get("db_url", "***"),
                "pool_size": info.get("pool_size"),
                "pool_free": info.get("pool_free"),
                "schema_exists": schema_exists,
                "discovery_count": discovery_count,
                "edge_count": edge_count,
                "fts_smoke_count": fts_count,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }

    # =========================================================================
    # Core CRUD Operations
    # =========================================================================

    async def add_discovery(self, discovery: DiscoveryNode) -> None:
        """Add discovery to graph with rate limiting."""
        await self._check_rate_limit(discovery.agent_id)

        backend = await self._get_backend()

        async with backend.acquire() as conn:
            # Insert discovery
            await conn.execute("""
                INSERT INTO knowledge.discoveries (
                    id, agent_id, type, severity, status, created_at, updated_at,
                    resolved_at, summary, details, tags, references_files, related_to,
                    response_to_id, response_type, confidence, provenance, provenance_chain
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
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
                discovery.severity or 'low',
                discovery.status,
                self._parse_timestamp(discovery.timestamp),
                self._parse_timestamp(discovery.updated_at) if discovery.updated_at else None,
                self._parse_timestamp(discovery.resolved_at) if discovery.resolved_at else None,
                discovery.summary,
                discovery.details or '',
                discovery.tags or [],
                discovery.references_files or [],
                discovery.related_to or [],
                discovery.response_to.discovery_id if discovery.response_to else None,
                discovery.response_to.response_type if discovery.response_to else None,
                discovery.confidence,
                json.dumps(discovery.provenance) if discovery.provenance else None,
                json.dumps(discovery.provenance_chain) if discovery.provenance_chain else None,
            )

            # Insert tags into normalized table
            if discovery.tags:
                for tag in discovery.tags:
                    await conn.execute("""
                        INSERT INTO knowledge.discovery_tags (discovery_id, tag)
                        VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                    """, discovery.id, tag)

            # Insert response_to edge
            if discovery.response_to:
                await conn.execute("""
                    INSERT INTO knowledge.discovery_edges
                    (src_id, dst_id, edge_type, response_type, created_at, created_by)
                    VALUES ($1, $2, 'response_to', $3, $4, $5)
                    ON CONFLICT (src_id, dst_id, edge_type) DO UPDATE SET
                        response_type = EXCLUDED.response_type,
                        created_at = EXCLUDED.created_at
                """,
                    discovery.id,
                    discovery.response_to.discovery_id,
                    discovery.response_to.response_type,
                    self._parse_timestamp(discovery.timestamp),
                    discovery.agent_id,
                )

            # Insert related_to edges
            for related_id in (discovery.related_to or []):
                await conn.execute("""
                    INSERT INTO knowledge.discovery_edges
                    (src_id, dst_id, edge_type, created_at, created_by)
                    VALUES ($1, $2, 'related_to', $3, $4)
                    ON CONFLICT DO NOTHING
                """, discovery.id, related_id, self._parse_timestamp(discovery.timestamp), discovery.agent_id)

            # Record rate limit
            await conn.execute("""
                INSERT INTO knowledge.rate_limits (agent_id, timestamp)
                VALUES ($1, $2)
            """, discovery.agent_id, self._parse_timestamp(discovery.timestamp))

        # Generate and store embedding asynchronously
        if self.enable_embeddings:
            asyncio.create_task(self._store_embedding(discovery))

    async def get_discovery(self, discovery_id: str) -> Optional[DiscoveryNode]:
        """Get discovery by ID."""
        backend = await self._get_backend()

        async with backend.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM knowledge.discoveries WHERE id = $1
            """, discovery_id)

            if not row:
                return None

            return await self._row_to_discovery(row, conn)

    async def update_discovery(self, discovery_id: str, updates: dict) -> bool:
        """Update discovery fields."""
        backend = await self._get_backend()

        async with backend.acquire() as conn:
            # Check exists
            exists = await conn.fetchval(
                "SELECT 1 FROM knowledge.discoveries WHERE id = $1",
                discovery_id
            )
            if not exists:
                return False

            # Handle special fields
            if "tags" in updates:
                await conn.execute(
                    "DELETE FROM knowledge.discovery_tags WHERE discovery_id = $1",
                    discovery_id
                )
                for tag in updates["tags"]:
                    await conn.execute("""
                        INSERT INTO knowledge.discovery_tags (discovery_id, tag)
                        VALUES ($1, $2)
                    """, discovery_id, tag)
                # Also update the array column
                await conn.execute("""
                    UPDATE knowledge.discoveries SET tags = $1, updated_at = now()
                    WHERE id = $2
                """, updates["tags"], discovery_id)
                del updates["tags"]

            if "response_to" in updates:
                await conn.execute("""
                    DELETE FROM knowledge.discovery_edges
                    WHERE src_id = $1 AND edge_type = 'response_to'
                """, discovery_id)

                resp = updates["response_to"]
                if resp:
                    if isinstance(resp, ResponseTo):
                        resp_id, resp_type = resp.discovery_id, resp.response_type
                    else:
                        resp_id, resp_type = resp["discovery_id"], resp["response_type"]
                    await conn.execute("""
                        INSERT INTO knowledge.discovery_edges
                        (src_id, dst_id, edge_type, response_type, created_at)
                        VALUES ($1, $2, 'response_to', $3, now())
                    """, discovery_id, resp_id, resp_type)
                    await conn.execute("""
                        UPDATE knowledge.discoveries
                        SET response_to_id = $1, response_type = $2, updated_at = now()
                        WHERE id = $3
                    """, resp_id, resp_type, discovery_id)
                del updates["response_to"]

            # Update remaining fields
            if updates:
                updates["updated_at"] = datetime.now()
                set_clauses = []
                values = []
                for i, (k, v) in enumerate(updates.items(), start=1):
                    set_clauses.append(f"{k} = ${i}")
                    values.append(v)
                values.append(discovery_id)

                await conn.execute(
                    f"UPDATE knowledge.discoveries SET {', '.join(set_clauses)} WHERE id = ${len(values)}",
                    *values
                )

            return True

    async def delete_discovery(self, discovery_id: str) -> bool:
        """Delete discovery (cascades to tags and edges)."""
        backend = await self._get_backend()

        async with backend.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM knowledge.discoveries WHERE id = $1",
                discovery_id
            )
            return "DELETE 1" in result

    # =========================================================================
    # Query Operations
    # =========================================================================

    async def query(
        self,
        agent_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[DiscoveryNode]:
        """Query discoveries with filters."""
        backend = await self._get_backend()

        conditions = []
        params = []
        param_idx = 1

        if agent_id:
            conditions.append(f"agent_id = ${param_idx}")
            params.append(agent_id)
            param_idx += 1

        if tags:
            conditions.append(f"tags && ${param_idx}")
            params.append(tags)
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

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        async with backend.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT * FROM knowledge.discoveries
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ${param_idx}
            """, *params)

            return [await self._row_to_discovery(row, conn) for row in rows]

    async def find_similar(self, discovery: DiscoveryNode, limit: int = 10) -> List[DiscoveryNode]:
        """Find similar discoveries by tag overlap."""
        if not discovery.tags:
            return []

        backend = await self._get_backend()

        async with backend.acquire() as conn:
            rows = await conn.fetch("""
                SELECT d.*,
                       cardinality(ARRAY(SELECT unnest(d.tags) INTERSECT SELECT unnest($1::text[]))) as overlap
                FROM knowledge.discoveries d
                WHERE d.id != $2
                  AND d.tags && $1::text[]
                ORDER BY overlap DESC
                LIMIT $3
            """, discovery.tags, discovery.id, limit)

            return [await self._row_to_discovery(row, conn) for row in rows]

    async def get_agent_discoveries(self, agent_id: str, limit: Optional[int] = None) -> List[DiscoveryNode]:
        """Get all discoveries for an agent."""
        backend = await self._get_backend()

        async with backend.acquire() as conn:
            if limit:
                rows = await conn.fetch("""
                    SELECT * FROM knowledge.discoveries
                    WHERE agent_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                """, agent_id, limit)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM knowledge.discoveries
                    WHERE agent_id = $1
                    ORDER BY created_at DESC
                """, agent_id)

            return [await self._row_to_discovery(row, conn) for row in rows]

    # =========================================================================
    # Graph Operations
    # =========================================================================

    async def get_related_discoveries(
        self,
        discovery_id: str,
        edge_types: Optional[List[str]] = None,
        limit: int = 20
    ) -> List[Tuple[DiscoveryNode, str, str]]:
        """Get discoveries connected via edges."""
        backend = await self._get_backend()
        results = []

        async with backend.acquire() as conn:
            # Outgoing edges
            if edge_types:
                out_rows = await conn.fetch("""
                    SELECT d.*, e.edge_type, e.response_type
                    FROM knowledge.discoveries d
                    JOIN knowledge.discovery_edges e ON d.id = e.dst_id
                    WHERE e.src_id = $1 AND e.edge_type = ANY($2)
                    LIMIT $3
                """, discovery_id, edge_types, limit)
            else:
                out_rows = await conn.fetch("""
                    SELECT d.*, e.edge_type, e.response_type
                    FROM knowledge.discoveries d
                    JOIN knowledge.discovery_edges e ON d.id = e.dst_id
                    WHERE e.src_id = $1
                    LIMIT $2
                """, discovery_id, limit)

            for row in out_rows:
                node = await self._row_to_discovery(row, conn)
                results.append((node, row["edge_type"], "outgoing"))

            # Incoming edges
            if edge_types:
                in_rows = await conn.fetch("""
                    SELECT d.*, e.edge_type, e.response_type
                    FROM knowledge.discoveries d
                    JOIN knowledge.discovery_edges e ON d.id = e.src_id
                    WHERE e.dst_id = $1 AND e.edge_type = ANY($2)
                    LIMIT $3
                """, discovery_id, edge_types, limit)
            else:
                in_rows = await conn.fetch("""
                    SELECT d.*, e.edge_type, e.response_type
                    FROM knowledge.discoveries d
                    JOIN knowledge.discovery_edges e ON d.id = e.src_id
                    WHERE e.dst_id = $1
                    LIMIT $2
                """, discovery_id, limit)

            for row in in_rows:
                node = await self._row_to_discovery(row, conn)
                results.append((node, row["edge_type"], "incoming"))

        return results[:limit]

    async def get_response_chain(self, discovery_id: str, max_depth: int = 10) -> List[DiscoveryNode]:
        """Get response chain using recursive CTE."""
        backend = await self._get_backend()

        async with backend.acquire() as conn:
            rows = await conn.fetch("""
                WITH RECURSIVE thread AS (
                    SELECT id, 0 AS depth FROM knowledge.discoveries WHERE id = $1
                    UNION ALL
                    SELECT d.id, t.depth + 1
                    FROM knowledge.discoveries d
                    JOIN thread t ON d.response_to_id = t.id
                    WHERE t.depth < $2
                )
                SELECT d.* FROM knowledge.discoveries d
                JOIN thread t ON d.id = t.id
                ORDER BY t.depth
            """, discovery_id, max_depth)

            return [await self._row_to_discovery(row, conn) for row in rows]

    async def find_agents_with_similar_interests(
        self,
        agent_id: str,
        min_overlap: int = 2,
        limit: int = 10
    ) -> List[Tuple[str, int]]:
        """Find agents with similar tags."""
        backend = await self._get_backend()

        async with backend.acquire() as conn:
            rows = await conn.fetch("""
                WITH my_tags AS (
                    SELECT DISTINCT unnest(tags) AS tag
                    FROM knowledge.discoveries
                    WHERE agent_id = $1
                )
                SELECT d.agent_id, COUNT(DISTINCT mt.tag)::INTEGER AS overlap
                FROM knowledge.discoveries d,
                     LATERAL unnest(d.tags) AS dt(tag)
                JOIN my_tags mt ON dt.tag = mt.tag
                WHERE d.agent_id != $1
                GROUP BY d.agent_id
                HAVING COUNT(DISTINCT mt.tag) >= $2
                ORDER BY overlap DESC
                LIMIT $3
            """, agent_id, min_overlap, limit)

            return [(row["agent_id"], row["overlap"]) for row in rows]

    async def full_text_search(self, query: str, limit: int = 20) -> List[DiscoveryNode]:
        """Search using PostgreSQL FTS."""
        backend = await self._get_backend()

        async with backend.acquire() as conn:
            rows = await conn.fetch("""
                SELECT d.*,
                       ts_rank(d.search_vector, websearch_to_tsquery('english', $1)) AS rank
                FROM knowledge.discoveries d
                WHERE d.search_vector @@ websearch_to_tsquery('english', $1)
                ORDER BY rank DESC
                LIMIT $2
            """, query, limit)

            return [await self._row_to_discovery(row, conn) for row in rows]

    async def add_edge(
        self,
        src_id: str,
        dst_id: str,
        edge_type: str,
        created_by: Optional[str] = None,
        response_type: Optional[str] = None,
        weight: float = 1.0,
        metadata: Optional[dict] = None
    ) -> bool:
        """Add edge between discoveries."""
        backend = await self._get_backend()

        async with backend.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO knowledge.discovery_edges
                    (src_id, dst_id, edge_type, response_type, weight, created_at, created_by, metadata)
                    VALUES ($1, $2, $3, $4, $5, now(), $6, $7)
                    ON CONFLICT (src_id, dst_id, edge_type) DO UPDATE SET
                        response_type = EXCLUDED.response_type,
                        weight = EXCLUDED.weight,
                        metadata = EXCLUDED.metadata
                """,
                    src_id, dst_id, edge_type, response_type, weight, created_by,
                    json.dumps(metadata) if metadata else None
                )
                return True
            except Exception as e:
                logger.error(f"Error adding edge: {e}")
                return False

    # =========================================================================
    # Semantic Search (pgvector)
    # =========================================================================

    async def semantic_search(
        self,
        query: str,
        limit: int = 20,
        min_similarity: float = 0.3
    ) -> List[Tuple[DiscoveryNode, float]]:
        """Semantic search using pgvector embeddings."""
        if not self.enable_embeddings:
            results = await self.full_text_search(query, limit)
            return [(r, 1.0) for r in results]

        # Generate query embedding
        embedding = self._generate_embedding(query)
        if embedding is None:
            results = await self.full_text_search(query, limit)
            return [(r, 1.0) for r in results]

        backend = await self._get_backend()

        async with backend.acquire() as conn:
            # Search using pgvector
            rows = await conn.fetch("""
                SELECT
                    d.*,
                    (1 - (e.embedding <=> $1::vector)) AS similarity
                FROM knowledge.discoveries d
                JOIN core.discovery_embeddings e ON d.id = e.discovery_id
                WHERE (1 - (e.embedding <=> $1::vector)) >= $2
                ORDER BY e.embedding <=> $1::vector
                LIMIT $3
            """, embedding, min_similarity, limit)

            results = []
            for row in rows:
                node = await self._row_to_discovery(row, conn)
                results.append((node, float(row["similarity"])))
            return results

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self) -> dict:
        """Get knowledge graph statistics."""
        backend = await self._get_backend()

        async with backend.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM knowledge.discoveries")

            by_agent_rows = await conn.fetch("""
                SELECT agent_id, COUNT(*) AS cnt
                FROM knowledge.discoveries
                GROUP BY agent_id
            """)
            by_agent = {row["agent_id"]: row["cnt"] for row in by_agent_rows}

            by_type_rows = await conn.fetch("""
                SELECT type, COUNT(*) AS cnt
                FROM knowledge.discoveries
                GROUP BY type
            """)
            by_type = {row["type"]: row["cnt"] for row in by_type_rows}

            by_status_rows = await conn.fetch("""
                SELECT status, COUNT(*) AS cnt
                FROM knowledge.discoveries
                GROUP BY status
            """)
            by_status = {row["status"]: row["cnt"] for row in by_status_rows}

            total_tags = await conn.fetchval(
                "SELECT COUNT(DISTINCT tag) FROM knowledge.discovery_tags"
            )
            total_edges = await conn.fetchval(
                "SELECT COUNT(*) FROM knowledge.discovery_edges"
            )

            return {
                "total_discoveries": total,
                "by_agent": by_agent,
                "by_type": by_type,
                "by_status": by_status,
                "total_tags": total_tags,
                "total_agents": len(by_agent),
                "total_edges": total_edges,
            }

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    async def _check_rate_limit(self, agent_id: str) -> None:
        """Check rate limit using PostgreSQL."""
        backend = await self._get_backend()

        async with backend.acquire() as conn:
            count = await conn.fetchval("""
                SELECT COUNT(*) FROM knowledge.rate_limits
                WHERE agent_id = $1 AND timestamp > now() - INTERVAL '1 hour'
            """, agent_id)

            if count >= self.rate_limit_stores_per_hour:
                raise ValueError(
                    f"Rate limit exceeded: Agent '{agent_id}' has stored {count} "
                    f"discoveries in the last hour (limit: {self.rate_limit_stores_per_hour}/hour)."
                )

            # Cleanup old entries opportunistically
            await conn.execute("""
                DELETE FROM knowledge.rate_limits
                WHERE timestamp < now() - INTERVAL '1 hour'
            """)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _parse_timestamp(self, ts) -> Optional[datetime]:
        """Parse timestamp string to datetime."""
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts
        try:
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return datetime.now()

    async def _row_to_discovery(self, row, conn) -> DiscoveryNode:
        """Convert database row to DiscoveryNode."""
        discovery_id = row["id"]

        # Get tags from normalized table (more reliable than array)
        tag_rows = await conn.fetch(
            "SELECT tag FROM knowledge.discovery_tags WHERE discovery_id = $1",
            discovery_id
        )
        tags = [r["tag"] for r in tag_rows] or list(row.get("tags") or [])

        # Build response_to
        response_to = None
        if row.get("response_to_id"):
            response_to = ResponseTo(
                discovery_id=row["response_to_id"],
                response_type=row.get("response_type") or "extend"
            )

        # Get responses_from (backlinks)
        resp_from_rows = await conn.fetch("""
            SELECT src_id FROM knowledge.discovery_edges
            WHERE dst_id = $1 AND edge_type = 'response_to'
        """, discovery_id)
        responses_from = [r["src_id"] for r in resp_from_rows]

        # Parse provenance
        provenance = None
        if row.get("provenance"):
            prov = row["provenance"]
            if isinstance(prov, str):
                provenance = json.loads(prov)
            elif isinstance(prov, dict):
                provenance = prov

        provenance_chain = None
        if row.get("provenance_chain"):
            pchain = row["provenance_chain"]
            if isinstance(pchain, str):
                provenance_chain = json.loads(pchain)
            elif isinstance(pchain, list):
                provenance_chain = pchain

        return DiscoveryNode(
            id=row["id"],
            agent_id=row["agent_id"],
            type=row["type"],
            summary=row["summary"],
            details=row.get("details") or "",
            tags=tags,
            severity=row.get("severity"),
            timestamp=row["created_at"].isoformat() if row.get("created_at") else datetime.now().isoformat(),
            status=row.get("status") or "open",
            related_to=list(row.get("related_to") or []),
            response_to=response_to,
            responses_from=responses_from,
            references_files=list(row.get("references_files") or []),
            resolved_at=row["resolved_at"].isoformat() if row.get("resolved_at") else None,
            updated_at=row["updated_at"].isoformat() if row.get("updated_at") else None,
            confidence=row.get("confidence"),
            provenance=provenance,
            provenance_chain=provenance_chain,
        )

    # =========================================================================
    # Embedding Generation
    # =========================================================================

    def _get_embedding_model(self):
        """Lazy-load embedding model."""
        if self._embedding_model is None and self.enable_embeddings:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("Loaded embedding model: all-MiniLM-L6-v2")
            except ImportError:
                logger.warning("sentence-transformers not available")
                self.enable_embeddings = False
            except Exception as e:
                logger.warning(f"Could not load embedding model: {e}")
                self.enable_embeddings = False
        return self._embedding_model

    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text."""
        if not self.enable_embeddings:
            return None

        model = self._get_embedding_model()
        if model is None:
            return None

        try:
            embedding = model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            logger.warning(f"Could not generate embedding: {e}")
            return None

    async def _store_embedding(self, discovery: DiscoveryNode) -> None:
        """Store embedding for a discovery."""
        text = discovery.summary
        if discovery.details:
            text += " " + discovery.details

        embedding = self._generate_embedding(text)
        if embedding is None:
            return

        try:
            backend = await self._get_backend()
            async with backend.acquire() as conn:
                await conn.execute("""
                    INSERT INTO core.discovery_embeddings (discovery_id, embedding, model_name)
                    VALUES ($1, $2::vector, 'all-MiniLM-L6-v2')
                    ON CONFLICT (discovery_id) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        updated_at = now()
                """, discovery.id, embedding)
        except Exception as e:
            logger.debug(f"Could not store embedding for {discovery.id}: {e}")

    # =========================================================================
    # Compatibility Methods
    # =========================================================================

    async def load(self):
        """No-op for compatibility - PostgreSQL is always persistent."""
        pass

    def close(self):
        """No-op for compatibility - connection pool managed by backend."""
        pass


# =============================================================================
# Global Instance Factory
# =============================================================================

_pg_db_instance: Optional[KnowledgeGraphDBPostgres] = None
_pg_db_lock: Optional[asyncio.Lock] = None


async def get_knowledge_graph_db_postgres() -> KnowledgeGraphDBPostgres:
    """Get global PostgreSQL knowledge graph instance."""
    global _pg_db_instance, _pg_db_lock

    if _pg_db_lock is None:
        _pg_db_lock = asyncio.Lock()

    async with _pg_db_lock:
        if _pg_db_instance is None:
            _pg_db_instance = KnowledgeGraphDBPostgres()
        return _pg_db_instance
