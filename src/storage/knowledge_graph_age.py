"""
AGE-backed Knowledge Graph Implementation

Apache AGE implementation of the knowledge graph interface.
Uses PostgreSQL + AGE for native graph queries.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from pathlib import Path

from src.logging_utils import get_logger
from src.knowledge_graph import DiscoveryNode, ResponseTo
from src.db import get_db
from src.db.age_queries import (
    create_discovery_node,
    create_agent_node,
    create_authored_edge,
    create_responds_to_edge,
    create_related_to_edge,
    create_tagged_edge,
    create_supersedes_edge,
    query_agent_discoveries,
    query_response_chain,
    create_indexes,
)

logger = get_logger(__name__)


class KnowledgeGraphAGE:
    """
    AGE-backed knowledge graph implementation.
    
    Uses Apache AGE for native graph queries while maintaining compatibility
    with the existing KnowledgeGraph interface.
    """

    def __init__(self, graph_name: str = "governance_graph"):
        # Note: the actual AGE graph name used at query time is owned by the DB backend
        # (see PostgresBackend._age_graph). We keep a local copy for SQL operations
        # that reference the graph schema (e.g., CREATE INDEX ON <graph>.Label(...)).
        self.graph_name = graph_name
        self._db = None
        self._indexes_created = False
        self.rate_limit_stores_per_hour = 20  # Max stores per agent per hour

    async def _get_db(self):
        """Get database backend (lazy initialization)."""
        if self._db is None:
            self._db = get_db()
            await self._db.init()

            # Best-effort: align our graph_name with backend config
            try:
                if hasattr(self._db, "_age_graph"):
                    self.graph_name = getattr(self._db, "_age_graph") or self.graph_name
                elif hasattr(self._db, "_postgres") and getattr(self._db, "_postgres_available", False):
                    pg = getattr(self._db, "_postgres")
                    if hasattr(pg, "_age_graph"):
                        self.graph_name = getattr(pg, "_age_graph") or self.graph_name
            except Exception:
                pass
            
            # Create indexes on first use
            if not self._indexes_created:
                await self._create_indexes()
                self._indexes_created = True
        
        return self._db

    async def _create_indexes(self):
        """
        Create AGE indexes for efficient queries.

        Note: AGE stores properties in a JSON-like 'properties' column, not as
        individual columns. Standard SQL indexes on property names don't apply.
        We use GIN indexes on the properties column instead.
        """
        db = await self._get_db()
        if not await db.graph_available():
            logger.warning("AGE not available, skipping index creation")
            return

        # AGE-compatible GIN indexes on properties column
        gin_indexes = [
            f'CREATE INDEX IF NOT EXISTS idx_discovery_props ON {self.graph_name}."Discovery" USING GIN (properties)',
            f'CREATE INDEX IF NOT EXISTS idx_agent_props ON {self.graph_name}."Agent" USING GIN (properties)',
            f'CREATE INDEX IF NOT EXISTS idx_tag_props ON {self.graph_name}."Tag" USING GIN (properties)',
        ]

        for sql in gin_indexes:
            try:
                await self._execute_age_sql(sql)
                logger.debug(f"Created GIN index: {sql[:60]}...")
            except Exception as e:
                # GIN index may already exist or properties column uses unsupported type
                logger.debug(f"GIN index creation skipped: {e}")

    async def _execute_age_sql(self, sql: str) -> None:
        """
        Execute a SQL statement against Postgres (used for AGE DDL like CREATE INDEX).

        Supports DB_BACKEND=postgres and DB_BACKEND=dual (uses the Postgres secondary).
        """
        db = await self._get_db()
        pool = None
        if hasattr(db, "_pool"):
            pool = getattr(db, "_pool")
        elif hasattr(db, "_postgres") and getattr(db, "_postgres_available", False):
            pg = getattr(db, "_postgres")
            pool = getattr(pg, "_pool", None)
        if pool is None:
            raise RuntimeError("PostgreSQL pool unavailable (AGE SQL execution requires Postgres backend)")

        async with pool.acquire() as conn:
            await conn.execute("LOAD 'age'")
            await conn.execute("SET search_path = ag_catalog, core, audit, public")
            await conn.execute(sql)

    async def add_discovery(
        self,
        discovery: DiscoveryNode,
    ) -> None:
        """
        Add a discovery to the graph.
        
        Args:
            discovery: DiscoveryNode to add
            
        NOTE: Temporal/similarity linking is now query-time, not write-time.
        Use get_related_discoveries(id, temporal_window=300) or find_similar(id) at query time.
        """
        # Rate limiting check (security measure)
        await self._check_rate_limit(discovery.agent_id)
        
        db = await self._get_db()
        
        if not await db.graph_available():
            raise RuntimeError("AGE graph not available. Check PostgreSQL AGE extension.")
        
        # Extract EISV fields if this is a self_observation
        eisv_e = None
        eisv_i = None
        eisv_s = None
        eisv_v = None
        regime = None
        coherence = None
        
        if discovery.type == "self_observation" and discovery.provenance:
            prov = discovery.provenance
            eisv_e = prov.get("E") or prov.get("eisv_e")
            eisv_i = prov.get("I") or prov.get("eisv_i")
            eisv_s = prov.get("S") or prov.get("eisv_s")
            eisv_v = prov.get("V") or prov.get("eisv_v")
            regime = prov.get("regime")
            coherence = prov.get("coherence")
        
        # Parse timestamp
        timestamp = None
        if discovery.timestamp:
            try:
                timestamp = datetime.fromisoformat(discovery.timestamp.replace('Z', '+00:00'))
            except Exception:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()
        
        resolved_at = None
        if discovery.resolved_at:
            try:
                resolved_at = datetime.fromisoformat(discovery.resolved_at.replace('Z', '+00:00'))
            except Exception:
                pass
        
        # Create discovery node
        cypher, params = create_discovery_node(
            discovery_id=discovery.id,
            agent_id=discovery.agent_id,
            discovery_type=discovery.type,
            summary=discovery.summary,
            details=discovery.details,
            severity=discovery.severity,
            status=discovery.status,
            timestamp=timestamp,
            resolved_at=resolved_at,
            eisv_e=eisv_e,
            eisv_i=eisv_i,
            eisv_s=eisv_s,
            eisv_v=eisv_v,
            regime=regime,
            coherence=coherence,
            tags=discovery.tags,
            metadata={
                "related_to": discovery.related_to,
                "references_files": discovery.references_files,
                "confidence": discovery.confidence,
                "provenance": discovery.provenance,
                "provenance_chain": discovery.provenance_chain,
            } if any([discovery.related_to, discovery.references_files, 
                     discovery.confidence, discovery.provenance, discovery.provenance_chain]) else None,
        )
        
        # Execute via graph_query
        await db.graph_query(cypher, params)
        
        # Create/update agent node
        agent_cypher, agent_params = create_agent_node(
            agent_id=discovery.agent_id,
            created_at=timestamp,
            updated_at=timestamp,
        )
        await db.graph_query(agent_cypher, agent_params)
        
        # Create AUTHORED edge
        authored_cypher, authored_params = create_authored_edge(
            agent_id=discovery.agent_id,
            discovery_id=discovery.id,
            at=timestamp,
        )
        await db.graph_query(authored_cypher, authored_params)
        
        # Create RESPONDS_TO edge if response_to exists
        if discovery.response_to:
            responds_cypher, responds_params = create_responds_to_edge(
                from_discovery_id=discovery.id,
                to_discovery_id=discovery.response_to.discovery_id,
            )
            await db.graph_query(responds_cypher, responds_params)
        
        # Create RELATED_TO edges
        for related_id in discovery.related_to:
            related_cypher, related_params = create_related_to_edge(
                from_discovery_id=discovery.id,
                to_discovery_id=related_id,
            )
            await db.graph_query(related_cypher, related_params)
        
        # Create TAGGED edges
        for tag in discovery.tags:
            tagged_cypher, tagged_params = create_tagged_edge(
                discovery_id=discovery.id,
                tag_name=tag,
            )
            await db.graph_query(tagged_cypher, tagged_params)

        # Store embedding for semantic search (async, best-effort)
        if await self._pgvector_available():
            try:
                from src.embeddings import get_embeddings_service, embeddings_available
                if embeddings_available():
                    embeddings = await get_embeddings_service()
                    text = f"{discovery.summary}\n{discovery.details[:500] if discovery.details else ''}"
                    emb = await embeddings.embed(text)
                    asyncio.create_task(self._store_embedding(discovery.id, emb))
            except Exception as e:
                logger.debug(f"Failed to create embedding for {discovery.id}: {e}")

        logger.debug(f"Added discovery {discovery.id} to AGE graph")

    async def get_discovery(self, discovery_id: str) -> Optional[DiscoveryNode]:
        """Get a discovery by ID."""
        db = await self._get_db()
        
        cypher = """
            MATCH (d:Discovery {id: ${discovery_id}})
            RETURN d
        """
        
        results = await db.graph_query(cypher, {"discovery_id": discovery_id})
        
        if not results:
            return None

        # Parse result (AGE returns agtype, need to convert)
        # graph_query returns parsed agtype directly
        result = results[0]
        if isinstance(result, dict) and "d" in result:
            node_data = self._parse_agtype_node(result["d"])
        else:
            node_data = self._parse_agtype_node(result)
        return self._node_to_discovery(node_data)

    async def get_response_chain(self, discovery_id: str, max_depth: int = 10) -> List[DiscoveryNode]:
        """
        Get a response chain for a discovery using AGE graph traversal.

        Uses AGE graph traversal where `RESPONDS_TO` edges represent
        replies pointing to their parent.

        Returns:
            Discoveries ordered by depth (root first, then replies).
        """
        db = await self._get_db()
        if not await db.graph_available():
            # Fallback to single-node chain
            root = await self.get_discovery(discovery_id)
            return [root] if root else []

        # Traverse from any node d to the root (discovery_id) via RESPONDS_TO edges.
        # Include depth 0 so the root itself is present in the chain.
        cypher = f"""
            MATCH (root:Discovery {{id: ${{discovery_id}}}})
            MATCH p = (d:Discovery)-[:RESPONDS_TO*0..{max_depth}]->(root:Discovery)
            RETURN d, length(p) AS depth
            ORDER BY depth ASC
        """
        rows = await db.graph_query(cypher, {"discovery_id": discovery_id})

        # Deduplicate by id using smallest depth
        best: Dict[str, tuple[int, DiscoveryNode]] = {}
        for row in rows or []:
            # Handle different result formats
            if isinstance(row, dict):
                node_data = self._parse_agtype_node(row.get("d", row))
                depth = int(row.get("depth", 0))
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                node_data = self._parse_agtype_node(row[0])
                depth = int(row[1]) if row[1] is not None else 0
            else:
                node_data = self._parse_agtype_node(row)
                depth = 0
            d = self._node_to_discovery(node_data)
            if not d or not d.id:
                continue
            prev = best.get(d.id)
            if prev is None or depth < prev[0]:
                best[d.id] = (depth, d)

        ordered = sorted(best.values(), key=lambda x: x[0])
        return [d for _depth, d in ordered]

    async def query(
        self,
        agent_id: Optional[str] = None,
        type: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        exclude_archived: bool = False,
    ) -> List[DiscoveryNode]:
        """
        Query discoveries with filters.

        Args:
            agent_id: Filter by agent
            type: Filter by discovery type
            status: Filter by status
            severity: Filter by severity
            tags: Filter by tags (any match)
            limit: Maximum results
        """
        db = await self._get_db()

        # Check if graph is available
        graph_ok = await db.graph_available()
        if not graph_ok:
            logger.warning("AGE graph not available for query")
            return []

        # Build query
        conditions = []
        params = {}
        
        if agent_id:
            conditions.append("d.agent_id = ${agent_id}")
            params["agent_id"] = agent_id
        
        if type:
            conditions.append("d.type = ${type}")
            params["type"] = type
        
        if status:
            conditions.append("d.status = ${status}")
            params["status"] = status

        if severity:
            conditions.append("d.severity = ${severity}")
            params["severity"] = severity

        # Exclude archived at the Cypher level so LIMIT applies to non-archived rows.
        # Without this, LIMIT N grabs the N most recent rows (mostly archived noise),
        # then post-hoc filtering removes them, returning far fewer than N results.
        if exclude_archived and not status:
            conditions.append("d.status <> 'archived'")

        where_clause = " AND ".join(conditions) if conditions else ""
        
        # Handle tags - AGE doesn't support EXISTS subqueries or re-matching
        # a variable with different labels. We need a single MATCH pattern.
        if tags:
            params["tags"] = tags
            # Combined MATCH: Discovery with tag relationship
            base_match = "MATCH (d:Discovery)-[:TAGGED]->(t:Tag) WHERE t.name IN ${tags}"
            if where_clause:
                cypher = f"""
                    {base_match} AND {where_clause}
                    RETURN d
                    ORDER BY d.timestamp DESC
                    LIMIT ${{limit}}
                """
            else:
                cypher = f"""
                    {base_match}
                    RETURN d
                    ORDER BY d.timestamp DESC
                    LIMIT ${{limit}}
                """
        else:
            # No tag filter
            cypher = f"""
                MATCH (d:Discovery)
                {"WHERE " + where_clause if where_clause else ""}
                RETURN d
                ORDER BY d.timestamp DESC
                LIMIT ${{limit}}
            """
        
        params["limit"] = limit
        
        logger.debug(f"AGE query: {cypher[:200]}... params: {list(params.keys())}")
        results = await db.graph_query(cypher, params)
        logger.debug(f"AGE query returned {len(results)} results")

        discoveries = []
        for result in results:
            # graph_query returns parsed agtype directly, not {"d": node}
            # Handle both dict with "d" key and direct node data
            if isinstance(result, dict) and "d" in result:
                node_data = self._parse_agtype_node(result["d"])
            elif isinstance(result, dict) and "error" in result:
                logger.warning(f"AGE query error: {result.get('error')}")
                continue
            else:
                node_data = self._parse_agtype_node(result)
            discovery = self._node_to_discovery(node_data)
            if discovery:
                discoveries.append(discovery)

        return discoveries

    async def get_agent_discoveries(
        self,
        agent_id: str,
        limit: Optional[int] = None,
    ) -> List[DiscoveryNode]:
        """Get all discoveries for an agent."""
        return await self.query(
            agent_id=agent_id,
            limit=limit or 100,
        )

    def _parse_agtype_node(self, agtype_value: Any) -> Dict[str, Any]:
        """
        Parse AGE agtype node to dictionary.

        AGE returns vertices as {id: internal_id, label: "...", properties: {...}}
        We extract the properties dict which contains our actual data.
        """
        if agtype_value is None:
            return {}

        parsed = None

        # If it's already a dict, use it directly
        if isinstance(agtype_value, dict):
            parsed = agtype_value

        # If it's a string (JSON), parse it
        elif isinstance(agtype_value, str):
            try:
                parsed = json.loads(agtype_value)
            except Exception:
                return {}

        if parsed is None:
            return {}

        # AGE vertex structure: {id: ..., label: ..., properties: {...}}
        # Extract properties if this is a vertex
        if "properties" in parsed and isinstance(parsed["properties"], dict):
            return parsed["properties"]

        return parsed

    def _node_to_discovery(self, node_data: Dict[str, Any]) -> Optional[DiscoveryNode]:
        """Convert AGE node data to DiscoveryNode."""
        if not node_data or "id" not in node_data:
            return None
        
        # Extract metadata if present
        metadata = node_data.get("metadata", {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        
        # Parse response_to if present
        response_to = None
        if "response_to" in metadata:
            resp_data = metadata["response_to"]
            if isinstance(resp_data, dict):
                response_to = ResponseTo(
                    discovery_id=resp_data.get("discovery_id", ""),
                    response_type=resp_data.get("response_type", "extend"),
                )

        # Parse tags (may be stored as JSON string in AGE)
        tags = node_data.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []

        return DiscoveryNode(
            id=node_data.get("id", ""),
            agent_id=node_data.get("agent_id", ""),
            type=node_data.get("type", "insight"),
            summary=node_data.get("summary", ""),
            details=node_data.get("details", ""),
            tags=tags,
            severity=node_data.get("severity"),
            timestamp=node_data.get("timestamp", datetime.now().isoformat()),
            status=node_data.get("status", "open"),
            related_to=metadata.get("related_to", []),
            response_to=response_to,
            references_files=metadata.get("references_files", []),
            resolved_at=node_data.get("resolved_at"),
            updated_at=node_data.get("updated_at"),
            confidence=metadata.get("confidence"),
            provenance=metadata.get("provenance"),
            provenance_chain=metadata.get("provenance_chain"),
        )

    async def update_discovery(self, discovery_id: str, updates: Dict[str, Any]) -> bool:
        """Update discovery fields in AGE graph.

        Supports updating: status, resolved_at, updated_at, tags, severity, type.
        """
        db = await self._get_db()

        if not await db.graph_available():
            logger.warning("AGE graph not available for update")
            return False

        # Build SET clauses for Cypher
        set_parts = []
        params = {"discovery_id": discovery_id}

        for key, value in updates.items():
            if key in ("status", "resolved_at", "updated_at", "severity", "type"):
                param_name = f"val_{key}"
                set_parts.append(f"d.{key} = ${{{param_name}}}")
                params[param_name] = value
            elif key == "tags":
                # Tags stored as JSON array in AGE
                param_name = "val_tags"
                set_parts.append(f"d.tags = ${{{param_name}}}")
                params[param_name] = json.dumps(value if isinstance(value, list) else [value])

        if not set_parts:
            return True  # Nothing to update

        cypher = f"""
            MATCH (d:Discovery {{id: ${{discovery_id}}}})
            SET {', '.join(set_parts)}
            RETURN d.id
        """

        try:
            result = await db.graph_query(cypher, params)
            if result and not (isinstance(result[0], dict) and "error" in result[0]):
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to update discovery {discovery_id}: {e}")
            return False

    async def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics.
        
        Note: AGE doesn't support GROUP BY or multi-column returns well,
        so we use single-column collect() queries and aggregate in Python.
        """
        from collections import Counter
        
        db = await self._get_db()
        
        # Total discoveries
        cypher = "MATCH (d:Discovery) RETURN count(d)"
        total = await db.graph_query(cypher, {})
        total_count = int(total[0]) if total and isinstance(total[0], (int, float)) else 0
        
        # Collect agent_ids (single column - AGE handles this fine)
        cypher = "MATCH (d:Discovery) RETURN collect(d.agent_id)"
        result = await db.graph_query(cypher, {})
        agents = result[0] if result and isinstance(result[0], list) else []
        by_agent = dict(Counter(a for a in agents if a))
        
        # Collect types
        cypher = "MATCH (d:Discovery) RETURN collect(d.type)"
        result = await db.graph_query(cypher, {})
        types = result[0] if result and isinstance(result[0], list) else []
        by_type = dict(Counter(t for t in types if t))
        
        # Collect statuses
        cypher = "MATCH (d:Discovery) RETURN collect(d.status)"
        result = await db.graph_query(cypher, {})
        statuses = result[0] if result and isinstance(result[0], list) else []
        by_status = dict(Counter(s for s in statuses if s))
        
        # Count edges
        cypher = "MATCH ()-[r]->() RETURN count(r)"
        edges_result = await db.graph_query(cypher, {})
        total_edges = int(edges_result[0]) if edges_result and isinstance(edges_result[0], (int, float)) else 0

        # Count tags (from Tag vertices)
        cypher = "MATCH (t:Tag) RETURN count(t) as tag_count"
        tags_result = await db.graph_query(cypher, {})
        # Handle different result formats: direct int, dict with count, or list
        total_tags = 0
        if tags_result:
            first_result = tags_result[0]
            # Check for error dict first
            if isinstance(first_result, dict) and "error" in first_result:
                logger.warning(f"Tag count query failed: {first_result.get('error')}")
                total_tags = 0
            elif isinstance(first_result, (int, float)):
                total_tags = int(first_result)
            elif isinstance(first_result, dict):
                # AGE might return {"tag_count": 1130} or {"count": 1130}
                total_tags = int(first_result.get("tag_count") or first_result.get("count") or 0)
            elif isinstance(first_result, list) and len(first_result) > 0:
                # Nested list case
                total_tags = int(first_result[0]) if isinstance(first_result[0], (int, float)) else 0
            else:
                logger.debug(f"Unexpected tag count result format: {type(first_result)}, value: {first_result}")

        # Collect tag names for by_tag breakdown
        cypher = "MATCH (t:Tag) RETURN collect(t.name)"
        result = await db.graph_query(cypher, {})
        tag_names = result[0] if result and isinstance(result[0], list) else []
        by_tag = dict(Counter(t for t in tag_names if t))

        return {
            "total_discoveries": total_count,
            "by_agent": by_agent,
            "by_type": by_type,
            "by_status": by_status,
            "by_tag": by_tag,
            "total_edges": total_edges,
            "total_agents": len(by_agent),
            "total_tags": total_tags,
        }

    async def health_check(self) -> Dict[str, Any]:
        """
        Lightweight health check for the AGE knowledge graph backend.
        Returns basic stats without heavy queries.
        """
        try:
            # Use get_stats but wrap in try/except for safety
            return await self.get_stats()
        except Exception as e:
            logger.warning(f"Health check failed, returning minimal info: {e}")
            return {
                "status": "degraded",
                "error": str(e),
                "backend": "age",
            }

    async def _check_rate_limit(self, agent_id: str) -> None:
        """
        Check if agent has exceeded rate limit (20 stores/hour).
        Raises ValueError if limit exceeded.
        
        Uses Redis for fast rate limiting, falls back to PostgreSQL.
        """
        # Try Redis first (fast path)
        try:
            from src.cache import get_rate_limiter
            limiter = get_rate_limiter()
            window_seconds = 3600  # 1 hour
            
            # Check rate limit
            if not await limiter.check(
                agent_id,
                limit=self.rate_limit_stores_per_hour,
                window=window_seconds,
                operation="kg_store",
            ):
                # Get current count for error message
                count = await limiter.get_count(agent_id, window_seconds, operation="kg_store")
                raise ValueError(
                    f"Rate limit exceeded: Agent '{agent_id}' has stored {count} "
                    f"discoveries in the last hour (limit: {self.rate_limit_stores_per_hour}/hour). "
                    f"This prevents knowledge graph poisoning flood attacks. "
                    f"Please wait before storing more discoveries."
                )
            
            # Record this operation
            await limiter.record(agent_id, window_seconds, operation="kg_store")
            return  # Success - Redis handled it
        except ValueError:
            # Rate limit exceeded - re-raise
            raise
        except Exception as e:
            # Redis failed - fall back to PostgreSQL
            logger.debug(f"Redis rate limiting failed, falling back to PostgreSQL: {e}")
        
        # Fallback: Use PostgreSQL for persistent rate limit tracking
        db = await self._get_db()
        
        async with db._pool.acquire() as conn:
            from datetime import datetime, timedelta
            one_hour_ago = datetime.now() - timedelta(hours=1)
            
            # Count recent stores
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM audit.rate_limits
                WHERE agent_id = $1 AND timestamp > $2
                """,
                agent_id,
                one_hour_ago,
            )
            
            count = count or 0
            if count >= self.rate_limit_stores_per_hour:
                raise ValueError(
                    f"Rate limit exceeded: Agent '{agent_id}' has stored {count} "
                    f"discoveries in the last hour (limit: {self.rate_limit_stores_per_hour}/hour). "
                    f"This prevents knowledge graph poisoning flood attacks. "
                    f"Please wait before storing more discoveries."
                )
            
            # Record this store for rate limiting
            await conn.execute(
                """
                INSERT INTO audit.rate_limits (agent_id, timestamp)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                agent_id,
                datetime.now(),
            )
            
            # Cleanup old rate limit entries (older than 1 hour)
            await conn.execute(
                """
                DELETE FROM audit.rate_limits
                WHERE timestamp < $1
                """,
                one_hour_ago,
            )

    async def load(self) -> None:
        """
        Load graph (no-op for AGE backend - data is always in PostgreSQL).
        Exists for compatibility with other backends.
        """
        # AGE backend is always persistent, no loading needed
        pass

    async def find_similar(
        self,
        discovery: DiscoveryNode,
        limit: int = 5,
    ) -> List[DiscoveryNode]:
        """
        Find similar discoveries by tag overlap.
        
        Args:
            discovery: Discovery to find similar ones for
            limit: Maximum number of results
            
        Returns:
            List of similar DiscoveryNodes
        """
        if not discovery.tags:
            return []
        
        # Find discoveries with overlapping tags
        db = await self._get_db()
        
        cypher = f"""
            MATCH (d:Discovery)-[:TAGGED]->(t:Tag)
            WHERE t.name IN ${{tags}}
              AND d.id <> ${{exclude_id}}
            WITH d, count(DISTINCT t) AS shared_tags
            ORDER BY shared_tags DESC
            LIMIT ${{limit}}
            RETURN d
        """
        
        params = {
            "tags": discovery.tags,
            "exclude_id": discovery.id,
            "limit": limit,
        }

        results = await db.graph_query(cypher, params)

        similar = []
        for result in results:
            # Handle both dict with "d" key and direct node data
            if isinstance(result, dict) and "d" in result:
                node_data = self._parse_agtype_node(result["d"])
            else:
                node_data = self._parse_agtype_node(result)
            disc = self._node_to_discovery(node_data)
            if disc:
                similar.append(disc)

        return similar

    async def find_similar_by_tags(
        self,
        tags: List[str],
        exclude_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[DiscoveryNode]:
        """
        Find discoveries with overlapping tags.
        
        Args:
            tags: List of tags to match
            exclude_id: Discovery ID to exclude from results
            limit: Maximum number of results
            
        Returns:
            List of similar DiscoveryNodes
        """
        if not tags:
            return []
        
        db = await self._get_db()
        
        exclude_clause = " AND d.id <> ${exclude_id}" if exclude_id else ""
        
        cypher = f"""
            MATCH (d:Discovery)-[:TAGGED]->(t:Tag)
            WHERE t.name IN ${{tags}}{exclude_clause}
            WITH d, count(DISTINCT t) AS shared_tags
            ORDER BY shared_tags DESC
            LIMIT ${{limit}}
            RETURN d
        """
        
        params = {
            "tags": tags,
            "limit": limit,
        }
        if exclude_id:
            params["exclude_id"] = exclude_id

        results = await db.graph_query(cypher, params)

        similar = []
        for result in results:
            # Handle both dict with "d" key and direct node data
            if isinstance(result, dict) and "d" in result:
                node_data = self._parse_agtype_node(result["d"])
            else:
                node_data = self._parse_agtype_node(result)
            disc = self._node_to_discovery(node_data)
            if disc:
                similar.append(disc)

        return similar

    async def _pgvector_available(self) -> bool:
        """Check if pgvector extension and embeddings table exist."""
        db = await self._get_db()
        if not hasattr(db, '_pool') or db._pool is None:
            return False
        
        try:
            async with db._pool.acquire() as conn:
                # Check if vector extension exists
                ext_exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
                )
                if not ext_exists:
                    return False
                
                # Check if embeddings table exists
                table_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_schema = 'core' AND table_name = 'discovery_embeddings'
                    )
                """)
                return table_exists
        except Exception as e:
            logger.debug(f"pgvector check failed: {e}")
            return False

    async def _pgvector_search(
        self,
        query_embedding: List[float],
        limit: int,
        min_similarity: float,
        agent_id: Optional[str] = None,
    ) -> List[tuple[str, float]]:
        """
        Search using pgvector's HNSW index.

        Returns list of (discovery_id, similarity_score) tuples.
        """
        db = await self._get_db()

        # Convert list to pgvector string format: '[0.1, 0.2, ...]'
        embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

        async with db._pool.acquire() as conn:
            # Build query with optional agent filter
            if agent_id:
                # Join with AGE graph to filter by agent
                # Note: This is a hybrid query - pgvector for similarity, then filter
                rows = await conn.fetch("""
                    SELECT de.discovery_id, (1 - (de.embedding <=> $1::vector)) AS similarity
                    FROM core.discovery_embeddings de
                    WHERE (1 - (de.embedding <=> $1::vector)) >= $2
                    ORDER BY de.embedding <=> $1::vector
                    LIMIT $3
                """, embedding_str, min_similarity, limit * 3)
            else:
                rows = await conn.fetch("""
                    SELECT discovery_id, (1 - (embedding <=> $1::vector)) AS similarity
                    FROM core.discovery_embeddings
                    WHERE (1 - (embedding <=> $1::vector)) >= $2
                    ORDER BY embedding <=> $1::vector
                    LIMIT $3
                """, embedding_str, min_similarity, limit)

            return [(row['discovery_id'], float(row['similarity'])) for row in rows]

    async def _store_embedding(self, discovery_id: str, embedding: List[float]) -> None:
        """Store embedding in pgvector table."""
        db = await self._get_db()

        # Convert list to pgvector string format: '[0.1, 0.2, ...]'
        embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'

        try:
            async with db._pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO core.discovery_embeddings (discovery_id, embedding, model_name)
                    VALUES ($1, $2::vector, 'all-MiniLM-L6-v2')
                    ON CONFLICT (discovery_id) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        updated_at = now()
                """, discovery_id, embedding_str)
        except Exception as e:
            logger.debug(f"Failed to store embedding for {discovery_id}: {e}")

    async def get_connectivity_score(self, discovery_id: str) -> float:
        """
        Get connectivity score for a discovery based on inbound edges.

        Higher score = more other discoveries reference this one.
        Used to rank well-connected knowledge above orphaned entries.

        Returns:
            Normalized score in [0, 1] range
        """
        db = await self._get_db()

        if not await db.graph_available():
            return 0.0

        # Count inbound edges (other discoveries pointing to this one)
        # Weight: RESPONDS_TO edges count more than RELATED_TO
        # Return single column as {related: N, responds: M} to work with graph_query
        cypher = """
            MATCH (d:Discovery {id: ${discovery_id}})
            OPTIONAL MATCH (other:Discovery)-[r:RELATED_TO]->(d)
            OPTIONAL MATCH (resp:Discovery)-[rt:RESPONDS_TO]->(d)
            RETURN {related: count(DISTINCT other), responds: count(DISTINCT resp)}
        """

        try:
            results = await db.graph_query(cypher, {"discovery_id": discovery_id})
            if not results:
                return 0.0

            result = results[0]
            # Result is either a dict or a nested structure
            if isinstance(result, dict) and "error" not in result:
                related_count = int(result.get("related", 0) or 0)
                responds_count = int(result.get("responds", 0) or 0)
            else:
                return 0.0

            # Weight responds_to higher (it's a stronger signal)
            raw_score = related_count + (responds_count * 2)

            # Normalize: log scale to prevent a few highly-linked nodes from dominating
            # score = log(1 + raw) / log(1 + max_expected)
            # Assume max ~100 inbound links as ceiling
            import math
            normalized = math.log1p(raw_score) / math.log1p(100)
            return min(1.0, normalized)
        except Exception as e:
            logger.debug(f"Failed to get connectivity score for {discovery_id}: {e}")
            return 0.0

    async def get_connectivity_scores_batch(self, discovery_ids: List[str]) -> Dict[str, float]:
        """
        Get connectivity scores for multiple discoveries in one query.

        More efficient than calling get_connectivity_score() repeatedly.
        """
        if not discovery_ids:
            return {}

        db = await self._get_db()

        if not await db.graph_available():
            return {d: 0.0 for d in discovery_ids}

        # Batch query for all discovery IDs - return single column per row
        # Need WITH clause for proper grouping before RETURN
        # Also count inbound SUPERSEDES edges to penalize superseded entries
        cypher = """
            UNWIND ${ids} as disc_id
            MATCH (d:Discovery {id: disc_id})
            OPTIONAL MATCH (other:Discovery)-[r:RELATED_TO]->(d)
            OPTIONAL MATCH (resp:Discovery)-[rt:RESPONDS_TO]->(d)
            OPTIONAL MATCH (newer:Discovery)-[s:SUPERSEDES]->(d)
            WITH d.id as id, count(DISTINCT other) as related, count(DISTINCT resp) as responds, count(DISTINCT newer) as superseded_by
            RETURN {id: id, related: related, responds: responds, superseded_by: superseded_by}
        """

        try:
            results = await db.graph_query(cypher, {"ids": discovery_ids})
            scores = {}

            import math
            for result in results:
                if not isinstance(result, dict) or "error" in result:
                    continue

                disc_id = result.get("id", "")
                if isinstance(disc_id, str):
                    disc_id = disc_id.strip('"')

                related_count = int(result.get("related", 0) or 0)
                responds_count = int(result.get("responds", 0) or 0)
                superseded_count = int(result.get("superseded_by", 0) or 0)

                raw_score = min(related_count + (responds_count * 2), 50)
                normalized = math.log1p(raw_score) / math.log1p(100)
                # Penalize superseded entries: halve score for each supersession
                if superseded_count > 0:
                    normalized *= 0.5 ** superseded_count
                scores[disc_id] = min(1.0, normalized)

            # Fill in zeros for any missing IDs
            for d in discovery_ids:
                if d not in scores:
                    scores[d] = 0.0

            return scores
        except Exception as e:
            logger.debug(f"Failed to get batch connectivity scores: {e}")
            return {d: 0.0 for d in discovery_ids}

    # Status multipliers for search ranking - resolved/archived entries rank lower
    STATUS_MULTIPLIERS = {
        "open": 1.0,
        "resolved": 0.6,
        "archived": 0.3,
        "disputed": 0.5,
    }

    async def _blend_with_connectivity(
        self,
        raw_results: List[tuple[DiscoveryNode, float]],
        connectivity_weight: float,
        exclude_orphans: bool,
        limit: int,
        temporal_decay: bool = True,
        half_life_days: float = 90.0,
        status_weight: bool = True,
    ) -> List[tuple[DiscoveryNode, float]]:
        """
        Blend similarity scores with connectivity scores, temporal decay, and status weighting.

        Args:
            raw_results: List of (discovery, similarity_score) tuples
            connectivity_weight: Weight for connectivity (0-1)
            exclude_orphans: If True, filter discoveries with 0 inbound links
            limit: Maximum results to return
            temporal_decay: If True, apply age-based decay (newer entries rank higher)
            half_life_days: Half-life for temporal decay in days (default 90)
            status_weight: If True, apply status-based multipliers (archived ranks lower)

        Returns:
            List of (discovery, blended_score) tuples, sorted by score descending
        """
        if not raw_results:
            return []

        # Fetch connectivity scores in batch
        discovery_ids = [d.id for d, _ in raw_results]
        connectivity_scores = await self.get_connectivity_scores_batch(discovery_ids)

        now = datetime.now()

        # Blend scores
        blended_results = []
        for discovery, similarity in raw_results:
            connectivity = connectivity_scores.get(discovery.id, 0.0)

            # Exclude orphans if requested
            if exclude_orphans and connectivity == 0.0:
                continue

            # Base blend: similarity * (1 - weight) + connectivity * weight
            score = (similarity * (1 - connectivity_weight)) + (connectivity * connectivity_weight)

            # Status multiplier: archived/resolved entries rank lower
            if status_weight:
                status_mult = self.STATUS_MULTIPLIERS.get(discovery.status, 1.0)
                score *= status_mult

            # Temporal decay: older entries rank lower
            if temporal_decay and half_life_days > 0:
                try:
                    ts = discovery.timestamp
                    if ts:
                        created = datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+00:00", ""))
                        age_days = max(0, (now - created).total_seconds() / 86400)
                        decay = 1.0 / (1.0 + age_days / half_life_days)
                        score *= decay
                except (ValueError, TypeError):
                    pass  # Can't parse timestamp, skip decay

            blended_results.append((discovery, score))

        # Sort by blended score descending
        blended_results.sort(key=lambda x: x[1], reverse=True)

        # Apply limit
        return blended_results[:limit]

    async def semantic_search(
        self,
        query: str,
        limit: int = 10,
        min_similarity: float = 0.3,
        agent_id: Optional[str] = None,
        connectivity_weight: float = 0.3,
        exclude_orphans: bool = False,
        temporal_decay: bool = True,
        half_life_days: float = 90.0,
        status_weight: bool = True,
    ) -> List[tuple[DiscoveryNode, float]]:
        """
        Semantic search using sentence-transformer embeddings.

        Uses pgvector for fast similarity search when available,
        falls back to in-memory comparison otherwise.

        Blends semantic similarity with connectivity score to rank
        well-connected knowledge above orphaned entries. Applies
        temporal decay and status-based weighting to prevent old
        or archived entries from dominating results.

        Args:
            query: Search query text
            limit: Maximum number of results
            min_similarity: Minimum cosine similarity threshold (0-1)
            agent_id: Optional agent filter
            connectivity_weight: Weight for connectivity in final score (0-1)
                                 Final = similarity*(1-weight) + connectivity*weight
                                 Default 0.3 = 70% similarity, 30% connectivity
            exclude_orphans: If True, filter out discoveries with zero inbound links
            temporal_decay: If True, apply age-based decay (newer entries rank higher)
            half_life_days: Half-life for temporal decay in days (default 90)
            status_weight: If True, apply status multipliers (archived/resolved rank lower)

        Returns:
            List of (DiscoveryNode, final_score) tuples, sorted by score descending
        """
        try:
            from src.embeddings import get_embeddings_service, embeddings_available
        except ImportError:
            logger.warning("Embeddings module not available")
            return []
        
        if not embeddings_available():
            logger.warning("sentence-transformers not installed, semantic search unavailable")
            return []
        
        # Get embedding service and embed query
        embeddings = await get_embeddings_service()
        query_embedding = await embeddings.embed(query)
        
        # Try pgvector first (fast, indexed)
        use_pgvector = await self._pgvector_available()
        
        if use_pgvector:
            logger.debug("Using pgvector for semantic search")
            scored_ids = await self._pgvector_search(
                query_embedding=query_embedding,
                limit=limit,
                min_similarity=min_similarity,
                agent_id=agent_id,
            )
            
            if scored_ids:
                # Fetch full discovery nodes
                raw_results = []
                for discovery_id, similarity in scored_ids:
                    discovery = await self.get_discovery(discovery_id)
                    if discovery:
                        # Apply agent filter if needed (pgvector doesn't filter by agent)
                        if agent_id and discovery.agent_id != agent_id:
                            continue
                        raw_results.append((discovery, similarity))

                if raw_results:
                    # Blend with connectivity scores
                    return await self._blend_with_connectivity(
                        raw_results,
                        connectivity_weight=connectivity_weight,
                        exclude_orphans=exclude_orphans,
                        limit=limit,
                        temporal_decay=temporal_decay,
                        half_life_days=half_life_days,
                        status_weight=status_weight,
                    )
            
            # Fall through to in-memory if pgvector returned nothing
            logger.debug("pgvector returned no results, falling back to in-memory")
        
        # Fallback: In-memory semantic search
        logger.debug("Using in-memory semantic search")
        
        # Get candidate discoveries
        candidates = await self.query(
            agent_id=agent_id,
            limit=limit * 5,
        )
        
        if not candidates:
            return []
        
        # Embed candidates
        candidate_texts = [
            f"{d.summary}\n{d.details[:500] if d.details else ''}"
            for d in candidates
        ]
        
        candidate_embeddings = await embeddings.embed_batch(candidate_texts)
        
        # Store embeddings for future pgvector use (async, best-effort)
        if use_pgvector:
            for discovery, emb in zip(candidates, candidate_embeddings):
                asyncio.create_task(self._store_embedding(discovery.id, emb))
        
        # Rank by similarity
        scored = await embeddings.rank_by_similarity(
            query_embedding=query_embedding,
            candidate_embeddings=list(zip(
                [d.id for d in candidates],
                candidate_embeddings
            )),
            top_k=limit * 2,
        )
        
        # Build raw results
        id_to_discovery = {d.id: d for d in candidates}
        raw_results = []

        for discovery_id, similarity in scored:
            if similarity < min_similarity:
                continue
            if discovery_id in id_to_discovery:
                raw_results.append((id_to_discovery[discovery_id], similarity))

        if not raw_results:
            return []

        # Blend with connectivity scores
        return await self._blend_with_connectivity(
            raw_results,
            connectivity_weight=connectivity_weight,
            exclude_orphans=exclude_orphans,
            limit=limit,
            temporal_decay=temporal_decay,
            half_life_days=half_life_days,
            status_weight=status_weight,
        )

    async def link_discoveries(
        self,
        from_id: str,
        to_id: str,
        reason: Optional[str] = None,
        strength: Optional[float] = None,
        bidirectional: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a RELATED_TO edge between two discoveries.

        This enables agents to organically build the knowledge graph by
        connecting related discoveries they encounter.

        Args:
            from_id: Source discovery ID
            to_id: Target discovery ID
            reason: Optional explanation for the relationship
            strength: Optional relationship strength (0.0-1.0)
            bidirectional: If True, create edges in both directions

        Returns:
            Dict with success status and edge details
        """
        db = await self._get_db()

        if not await db.graph_available():
            return {"success": False, "error": "Graph database not available"}

        # Validate both discoveries exist
        check_cypher = """
            MATCH (d:Discovery)
            WHERE d.id IN [${from_id}, ${to_id}]
            RETURN collect(d.id) as found_ids
        """
        try:
            results = await db.graph_query(check_cypher, {"from_id": from_id, "to_id": to_id})
            if not results:
                return {"success": False, "error": "Failed to validate discoveries"}

            # graph_query returns list of results; single-column returns the value directly
            found_ids_raw = results[0]
            if isinstance(found_ids_raw, dict):
                if "error" in found_ids_raw:
                    return {"success": False, "error": found_ids_raw["error"]}
                found_ids_raw = found_ids_raw.get("found_ids", [])

            # Handle list result (direct value from collect())
            if isinstance(found_ids_raw, list):
                found_ids = [str(x).strip('"') for x in found_ids_raw]
            else:
                found_ids = []

            if from_id not in found_ids:
                return {"success": False, "error": f"Discovery '{from_id}' not found"}
            if to_id not in found_ids:
                return {"success": False, "error": f"Discovery '{to_id}' not found"}
        except Exception as e:
            return {"success": False, "error": f"Validation failed: {e}"}

        # Build the edge creation query
        from src.db.age_queries import create_related_to_edge

        edges_created = []

        # Create forward edge
        cypher, params = create_related_to_edge(
            from_discovery_id=from_id,
            to_discovery_id=to_id,
            strength=strength,
            reason=reason,
        )

        try:
            await db.graph_query(cypher, params)
            edges_created.append({"from": from_id, "to": to_id})
        except Exception as e:
            return {"success": False, "error": f"Failed to create edge: {e}"}

        # Create reverse edge if bidirectional
        if bidirectional:
            cypher, params = create_related_to_edge(
                from_discovery_id=to_id,
                to_discovery_id=from_id,
                strength=strength,
                reason=reason,
            )
            try:
                await db.graph_query(cypher, params)
                edges_created.append({"from": to_id, "to": from_id})
            except Exception as e:
                logger.warning(f"Failed to create reverse edge: {e}")

        return {
            "success": True,
            "edges_created": edges_created,
            "from_id": from_id,
            "to_id": to_id,
            "reason": reason,
            "bidirectional": bidirectional,
            "message": f"Linked '{from_id[:30]}...' to '{to_id[:30]}...'" + (" (bidirectional)" if bidirectional else "")
        }

    async def supersede_discovery(
        self,
        new_id: str,
        old_id: str,
    ) -> Dict[str, Any]:
        """
        Mark a discovery as superseding another.

        Creates a SUPERSEDES edge from new_id to old_id. Superseded entries
        receive a connectivity penalty in search ranking.

        Args:
            new_id: The newer discovery that replaces the old one
            old_id: The older discovery being superseded

        Returns:
            Dict with success status
        """
        db = await self._get_db()

        if not await db.graph_available():
            return {"success": False, "error": "Graph database not available"}

        # Validate both exist
        for did, label in [(new_id, "new"), (old_id, "old")]:
            node = await self.get_discovery(did)
            if not node:
                return {"success": False, "error": f"{label.title()} discovery '{did}' not found"}

        cypher, params = create_supersedes_edge(new_id, old_id)
        try:
            await db.graph_query(cypher, params)
            return {
                "success": True,
                "new_id": new_id,
                "old_id": old_id,
                "message": f"'{new_id[:30]}...' now supersedes '{old_id[:30]}...'"
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create SUPERSEDES edge: {e}"}

    # =========================================================================
    # LIFECYCLE MANAGEMENT
    # =========================================================================

    async def get_orphan_discoveries(
        self,
        limit: int = 100,
        min_age_days: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Find discoveries with no inbound edges (orphans).

        Orphans are discoveries that no other discovery references.
        They may still have outbound edges (referencing others).

        Args:
            limit: Maximum discoveries to return
            min_age_days: Only return orphans older than this many days

        Returns:
            List of orphan discovery summaries with metadata
        """
        db = await self._get_db()

        if not await db.graph_available():
            return []

        # Calculate cutoff date
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=min_age_days)).isoformat()

        cypher = """
            MATCH (d:Discovery)
            WHERE d.id < ${cutoff}
            OPTIONAL MATCH (other:Discovery)-[:RELATED_TO]->(d)
            OPTIONAL MATCH (resp:Discovery)-[:RESPONDS_TO]->(d)
            WITH d, count(other) + count(resp) as inbound_count
            WHERE inbound_count = 0
            RETURN {
                id: d.id,
                summary: d.summary,
                type: d.type,
                status: d.status,
                agent_id: d.agent_id
            } as discovery
            ORDER BY d.id ASC
            LIMIT ${limit}
        """

        try:
            results = await db.graph_query(cypher, {"cutoff": cutoff, "limit": limit})
            orphans = []
            for result in results:
                if isinstance(result, dict) and "error" not in result:
                    orphans.append(result)
            return orphans
        except Exception as e:
            logger.warning(f"Failed to get orphan discoveries: {e}")
            return []

    async def get_stale_discoveries(
        self,
        older_than_days: int = 30,
        status: Optional[str] = "open",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Find stale discoveries that may need attention.

        Stale discoveries are old, unresolved items that might need
        archiving or resolution.

        Args:
            older_than_days: Find discoveries older than this
            status: Filter by status (None = any status)
            limit: Maximum to return

        Returns:
            List of stale discovery summaries
        """
        db = await self._get_db()

        if not await db.graph_available():
            return []

        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=older_than_days)).isoformat()

        # Build status filter
        status_clause = "AND d.status = ${status}" if status else ""

        cypher = f"""
            MATCH (d:Discovery)
            WHERE d.id < ${{cutoff}} {status_clause}
            RETURN {{
                id: d.id,
                summary: d.summary,
                type: d.type,
                status: d.status,
                agent_id: d.agent_id,
                severity: d.severity
            }} as discovery
            ORDER BY d.id ASC
            LIMIT ${{limit}}
        """

        params = {"cutoff": cutoff, "limit": limit}
        if status:
            params["status"] = status

        try:
            results = await db.graph_query(cypher, params)
            stale = []
            for result in results:
                if isinstance(result, dict) and "error" not in result:
                    stale.append(result)
            return stale
        except Exception as e:
            logger.warning(f"Failed to get stale discoveries: {e}")
            return []

    async def archive_discoveries_batch(
        self,
        discovery_ids: List[str],
        reason: str = "lifecycle_cleanup",
    ) -> Dict[str, Any]:
        """
        Archive multiple discoveries in a batch.

        Sets status to 'archived' and adds archive metadata.

        Args:
            discovery_ids: List of discovery IDs to archive
            reason: Reason for archiving

        Returns:
            Dict with success count and any errors
        """
        if not discovery_ids:
            return {"success": True, "archived": 0, "errors": []}

        db = await self._get_db()

        if not await db.graph_available():
            return {"success": False, "error": "Graph database not available"}

        from datetime import datetime
        archived_at = datetime.now().isoformat()

        # Archive in batches
        archived = 0
        errors = []

        for disc_id in discovery_ids:
            cypher = """
                MATCH (d:Discovery {id: ${discovery_id}})
                SET d.status = 'archived',
                    d.archived_at = ${archived_at},
                    d.archive_reason = ${reason}
                RETURN d.id as id
            """

            try:
                result = await db.graph_query(cypher, {
                    "discovery_id": disc_id,
                    "archived_at": archived_at,
                    "reason": reason,
                })
                if result and not (isinstance(result[0], dict) and "error" in result[0]):
                    archived += 1
                else:
                    errors.append({"id": disc_id, "error": "Not found or update failed"})
            except Exception as e:
                errors.append({"id": disc_id, "error": str(e)})

        return {
            "success": len(errors) == 0,
            "archived": archived,
            "errors": errors,
            "reason": reason,
        }

    async def cleanup_stale_discoveries(
        self,
        orphan_age_days: int = 30,
        open_age_days: int = 60,
        dry_run: bool = True,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Clean up stale discoveries in the knowledge graph.

        This is the main lifecycle management entry point. It identifies
        and optionally archives:
        1. Orphan discoveries (no inbound edges) older than orphan_age_days
        2. Open discoveries that have been unresolved for open_age_days

        Args:
            orphan_age_days: Archive orphans older than this (default 30)
            open_age_days: Archive open items older than this (default 60)
            dry_run: If True, report what would be done without doing it
            limit: Max discoveries to process per category

        Returns:
            Dict with cleanup results and statistics
        """
        # Find candidates
        orphans = await self.get_orphan_discoveries(limit=limit, min_age_days=orphan_age_days)
        stale_open = await self.get_stale_discoveries(
            older_than_days=open_age_days,
            status="open",
            limit=limit,
        )

        # Deduplicate (an orphan might also be stale)
        orphan_ids = {o.get("id", o) if isinstance(o, dict) else o for o in orphans}
        stale_ids = {s.get("id", s) if isinstance(s, dict) else s for s in stale_open}
        all_candidates = orphan_ids | stale_ids

        result = {
            "dry_run": dry_run,
            "orphans_found": len(orphan_ids),
            "stale_open_found": len(stale_ids),
            "total_candidates": len(all_candidates),
            "orphan_threshold_days": orphan_age_days,
            "open_threshold_days": open_age_days,
        }

        if dry_run:
            # Just report what would be done
            result["would_archive"] = list(all_candidates)[:20]  # Sample
            result["message"] = f"Dry run: would archive {len(all_candidates)} discoveries"
            return result

        # Actually archive
        if all_candidates:
            archive_result = await self.archive_discoveries_batch(
                list(all_candidates),
                reason=f"lifecycle_cleanup:orphan>{orphan_age_days}d,open>{open_age_days}d",
            )
            result.update({
                "archived": archive_result.get("archived", 0),
                "errors": archive_result.get("errors", []),
                "message": f"Archived {archive_result.get('archived', 0)} discoveries",
            })
        else:
            result["archived"] = 0
            result["message"] = "No discoveries matched cleanup criteria"

        return result

