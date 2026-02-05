"""
Knowledge Graph SQLite Backend - Graph-enabled knowledge storage

Migrates from in-memory JSON to SQLite with:
- Graph edges for discovery relationships
- Full-text search via FTS5
- Agent-to-agent knowledge sharing
- Prepared for future vector embeddings

Schema enables queries like:
- "Find discoveries related to mine" (graph traversal)
- "What did agents learn about X?" (FTS search)
- "Show response chains" (recursive CTE)
- "Find agents working on similar problems" (tag overlap)

Maintains backward compatibility with existing KnowledgeGraph interface.
"""

import sqlite3
import json
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Literal, Tuple, Any
from datetime import datetime
from pathlib import Path
import threading
import os

from src.logging_utils import get_logger
logger = get_logger(__name__)


# =============================================================================
# Schema Definition
# =============================================================================

SCHEMA_SQL = """
-- Core discoveries table
CREATE TABLE IF NOT EXISTS discoveries (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    type TEXT NOT NULL,
    severity TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    resolved_at TEXT,
    summary TEXT NOT NULL,
    details TEXT,
    related_files TEXT,  -- JSON array
    confidence REAL,     -- For future calibration integration
    embedding BLOB       -- Vector embedding for semantic search (JSON array of floats)
);

-- Tag many-to-many relationship
CREATE TABLE IF NOT EXISTS discovery_tags (
    discovery_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (discovery_id, tag),
    FOREIGN KEY (discovery_id) REFERENCES discoveries(id) ON DELETE CASCADE
);

-- Graph edges (the key table for agent intelligence)
CREATE TABLE IF NOT EXISTS discovery_edges (
    src_id TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,  -- response_to, related_to, disputes, extends, etc
    response_type TEXT,       -- extend, question, disagree, support (for response_to edges)
    weight REAL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    created_by TEXT,          -- Agent who created the link
    metadata TEXT,            -- JSON for edge-specific context
    PRIMARY KEY (src_id, dst_id, edge_type),
    FOREIGN KEY (src_id) REFERENCES discoveries(id) ON DELETE CASCADE,
    FOREIGN KEY (dst_id) REFERENCES discoveries(id) ON DELETE CASCADE
);

-- Full-text search for semantic queries
CREATE VIRTUAL TABLE IF NOT EXISTS discoveries_fts USING fts5(
    summary,
    details,
    content=discoveries,
    content_rowid=rowid
);

-- FTS triggers for automatic sync
CREATE TRIGGER IF NOT EXISTS discoveries_ai AFTER INSERT ON discoveries BEGIN
    INSERT INTO discoveries_fts(rowid, summary, details)
    VALUES (NEW.rowid, NEW.summary, NEW.details);
END;

CREATE TRIGGER IF NOT EXISTS discoveries_ad AFTER DELETE ON discoveries BEGIN
    INSERT INTO discoveries_fts(discoveries_fts, rowid, summary, details)
    VALUES('delete', OLD.rowid, OLD.summary, OLD.details);
END;

CREATE TRIGGER IF NOT EXISTS discoveries_au AFTER UPDATE ON discoveries BEGIN
    INSERT INTO discoveries_fts(discoveries_fts, rowid, summary, details)
    VALUES('delete', OLD.rowid, OLD.summary, OLD.details);
    INSERT INTO discoveries_fts(rowid, summary, details)
    VALUES (NEW.rowid, NEW.summary, NEW.details);
END;

-- Rate limiting table (replaces in-memory dict)
CREATE TABLE IF NOT EXISTS rate_limits (
    agent_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    PRIMARY KEY (agent_id, timestamp)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_discoveries_agent ON discoveries(agent_id);
CREATE INDEX IF NOT EXISTS idx_discoveries_type ON discoveries(type);
CREATE INDEX IF NOT EXISTS idx_discoveries_status ON discoveries(status);
CREATE INDEX IF NOT EXISTS idx_discoveries_created ON discoveries(created_at);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON discovery_tags(tag);
CREATE INDEX IF NOT EXISTS idx_edges_src ON discovery_edges(src_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON discovery_edges(dst_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON discovery_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_rate_limits_agent ON rate_limits(agent_id, timestamp);

-- Schema version for future migrations (unique table name for consolidated DB)
CREATE TABLE IF NOT EXISTS knowledge_schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Insert initial version if not exists
INSERT OR IGNORE INTO knowledge_schema_version (version, applied_at) VALUES (1, datetime('now'));
"""


# =============================================================================
# Data Classes (compatible with existing code)
# =============================================================================

@dataclass
class ResponseTo:
    """Typed response link to another discovery"""
    discovery_id: str
    response_type: Literal["extend", "question", "disagree", "support"]


@dataclass
class DiscoveryNode:
    """Node in knowledge graph representing a single discovery"""
    id: str
    agent_id: str
    type: str
    summary: str
    details: str = ""
    tags: List[str] = field(default_factory=list)
    severity: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "open"
    related_to: List[str] = field(default_factory=list)
    response_to: Optional[ResponseTo] = None
    responses_from: List[str] = field(default_factory=list)
    references_files: List[str] = field(default_factory=list)
    resolved_at: Optional[str] = None
    updated_at: Optional[str] = None
    confidence: Optional[float] = None
    # ENHANCED PROVENANCE: Agent state at time of creation
    provenance: Optional[Dict[str, Any]] = None
    # PROVENANCE CHAIN: Full lineage context for multi-agent collaboration
    provenance_chain: Optional[List[Dict[str, Any]]] = None

    def to_dict(self, include_details: bool = True) -> dict:
        """Convert to dictionary for JSON serialization"""
        result = {
            "id": self.id,
            "agent_id": self.agent_id,
            "type": self.type,
            "summary": self.summary,
            "tags": self.tags,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "status": self.status,
            "related_to": self.related_to,
            "references_files": self.references_files,
            "resolved_at": self.resolved_at,
            "updated_at": self.updated_at
        }

        if self.response_to:
            result["response_to"] = {
                "discovery_id": self.response_to.discovery_id,
                "response_type": self.response_to.response_type
            }

        if self.responses_from:
            result["responses_from"] = self.responses_from

        if self.confidence is not None:
            result["confidence"] = self.confidence

        # Include provenance if present (agent state at creation)
        if self.provenance:
            result["provenance"] = self.provenance

        # Include provenance chain if present (lineage context)
        if self.provenance_chain:
            result["provenance_chain"] = self.provenance_chain

        if include_details:
            result["details"] = self.details
        else:
            if self.details:
                result["has_details"] = True
                result["details_preview"] = self.details[:100] + "..." if len(self.details) > 100 else self.details

        return result

    @classmethod
    def from_dict(cls, data: dict) -> 'DiscoveryNode':
        """Create from dictionary"""
        response_to = None
        if "response_to" in data and data["response_to"]:
            resp_data = data["response_to"]
            if isinstance(resp_data, dict):
                response_to = ResponseTo(
                    discovery_id=resp_data["discovery_id"],
                    response_type=resp_data["response_type"]
                )

        return cls(
            id=data["id"],
            agent_id=data["agent_id"],
            type=data["type"],
            summary=data["summary"],
            details=data.get("details", ""),
            tags=data.get("tags", []),
            severity=data.get("severity"),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            status=data.get("status", "open"),
            related_to=data.get("related_to", []),
            response_to=response_to,
            responses_from=data.get("responses_from", []),
            references_files=data.get("references_files", []),
            resolved_at=data.get("resolved_at"),
            updated_at=data.get("updated_at"),
            confidence=data.get("confidence")
        )


# =============================================================================
# SQLite Knowledge Graph Implementation
# =============================================================================

class KnowledgeGraphDB:
    """
    SQLite-backed knowledge graph with graph edges.

    Drop-in replacement for in-memory KnowledgeGraph.
    Adds:
    - Graph edge traversal
    - Full-text search
    - Semantic search (vector embeddings)
    - Persistent rate limiting
    - Thread-safe connections
    """

    def __init__(self, db_path: Optional[Path] = None, enable_embeddings: bool = True):
        if db_path is None:
            project_root = Path(__file__).parent.parent
            # Uses consolidated governance.db by default
            db_path = os.getenv("UNITARES_KNOWLEDGE_DB_PATH") or (project_root / "data" / "governance.db")

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Thread-local connections for thread safety
        self._local = threading.local()

        # Rate limiting config
        self.rate_limit_stores_per_hour = 20

        # Embedding configuration - can be disabled via env var
        env_disable = os.getenv("UNITARES_DISABLE_EMBEDDINGS", "").lower() in ("true", "1", "yes")
        self.enable_embeddings = enable_embeddings and not env_disable
        self._embedding_model = None  # Lazy-loaded
        if env_disable:
            logger.info("Embeddings disabled via UNITARES_DISABLE_EMBEDDINGS")

        # Initialize schema
        self._init_schema()
        
        # Migrate schema if needed (add embedding column)
        self._migrate_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA foreign_keys = ON")
            # Concurrency + durability defaults for local multi-client workloads:
            # - WAL allows multiple concurrent readers while a writer is active.
            # - busy_timeout reduces "database is locked" flakes under bursty writes.
            # - synchronous=NORMAL is the common WAL recommendation: strong enough for local,
            #   much faster than FULL; for maximum durability set to FULL.
            self._local.conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn.execute("PRAGMA busy_timeout = 5000")
            self._local.conn.execute("PRAGMA synchronous = NORMAL")
        return self._local.conn

    def close(self):
        """Close thread-local database connection. Call this when done with the instance."""
        if hasattr(self._local, 'conn') and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception:
                pass  # Ignore errors on close
            self._local.conn = None

    def __del__(self):
        """Ensure connection is closed on garbage collection."""
        self.close()

    def _init_schema(self):
        """Initialize database schema"""
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    
    def _migrate_schema(self):
        """Migrate schema to add new columns if needed"""
        conn = self._get_conn()
        cursor = conn.cursor()

        # Check existing columns
        cursor.execute("PRAGMA table_info(discoveries)")
        columns = [row[1] for row in cursor.fetchall()]

        # Add embedding column if missing
        if 'embedding' not in columns:
            logger.info("Adding embedding column to discoveries table")
            cursor.execute("ALTER TABLE discoveries ADD COLUMN embedding BLOB")

        # Add provenance column if missing
        if 'provenance' not in columns:
            logger.info("Adding provenance column to discoveries table")
            cursor.execute("ALTER TABLE discoveries ADD COLUMN provenance TEXT")  # JSON string

        # Add provenance_chain column if missing
        if 'provenance_chain' not in columns:
            logger.info("Adding provenance_chain column to discoveries table")
            cursor.execute("ALTER TABLE discoveries ADD COLUMN provenance_chain TEXT")  # JSON string

        conn.commit()

    def _health_check_sync(self) -> dict:
        """Synchronous DB self-check (run via to_thread to avoid blocking event loop)."""
        conn = self._get_conn()
        cursor = conn.cursor()

        # Basic file info
        info = {
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "db_bytes": (self.db_path.stat().st_size if self.db_path.exists() else 0),
        }

        try:
            cursor.execute("PRAGMA integrity_check;")
            integrity = cursor.fetchone()[0]

            cursor.execute("PRAGMA foreign_key_check;")
            fk_issues = cursor.fetchall()

            # FTS smoke test (doesn't require content)
            cursor.execute("SELECT COUNT(*) FROM discoveries_fts WHERE discoveries_fts MATCH ?", ("sqlite",))
            fts_count = cursor.fetchone()[0]

            info.update({
                "integrity_check": integrity,
                "foreign_key_issues": len(fk_issues),
                "fts_smoke_count": int(fts_count),
            })
        except Exception as e:
            info.update({
                "integrity_check": "error",
                "error": str(e),
            })

        return info

    async def health_check(self) -> dict:
        """
        Lightweight DB self-check for autonomous agents.
        Runs integrity/foreign-key checks + a trivial FTS query.
        """
        return await asyncio.to_thread(self._health_check_sync)

    # =========================================================================
    # Core CRUD Operations (compatible with existing interface)
    # =========================================================================

    async def add_discovery(self, discovery: DiscoveryNode) -> None:
        """Add discovery to graph with rate limiting"""
        await self._check_rate_limit(discovery.agent_id)

        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            # Generate embedding if enabled
            embedding = None
            if self.enable_embeddings:
                # Combine summary and details for embedding
                text_for_embedding = discovery.summary
                if discovery.details:
                    text_for_embedding += " " + discovery.details
                embedding = self._generate_embedding(text_for_embedding)
            
            # Insert discovery
            cursor.execute("""
                INSERT INTO discoveries
                (id, agent_id, type, severity, status, created_at, updated_at,
                 resolved_at, summary, details, related_files, confidence, embedding,
                 provenance, provenance_chain)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                discovery.id,
                discovery.agent_id,
                discovery.type,
                discovery.severity,
                discovery.status,
                discovery.timestamp,
                discovery.updated_at,
                discovery.resolved_at,
                discovery.summary,
                discovery.details,
                json.dumps(discovery.references_files) if discovery.references_files else None,
                discovery.confidence,
                embedding,
                json.dumps(discovery.provenance) if discovery.provenance else None,
                json.dumps(discovery.provenance_chain) if discovery.provenance_chain else None
            ))

            # Insert tags
            for tag in discovery.tags:
                cursor.execute(
                    "INSERT OR IGNORE INTO discovery_tags (discovery_id, tag) VALUES (?, ?)",
                    (discovery.id, tag)
                )

            # Insert response_to edge
            if discovery.response_to:
                cursor.execute("""
                    INSERT OR REPLACE INTO discovery_edges
                    (src_id, dst_id, edge_type, response_type, created_at, created_by)
                    VALUES (?, ?, 'response_to', ?, ?, ?)
                """, (
                    discovery.id,
                    discovery.response_to.discovery_id,
                    discovery.response_to.response_type,
                    discovery.timestamp,
                    discovery.agent_id
                ))

            # Insert related_to edges
            for related_id in discovery.related_to:
                cursor.execute("""
                    INSERT OR IGNORE INTO discovery_edges
                    (src_id, dst_id, edge_type, created_at, created_by)
                    VALUES (?, ?, 'related_to', ?, ?)
                """, (discovery.id, related_id, discovery.timestamp, discovery.agent_id))

            # Record rate limit
            cursor.execute(
                "INSERT INTO rate_limits (agent_id, timestamp) VALUES (?, ?)",
                (discovery.agent_id, discovery.timestamp)
            )

            conn.commit()
            
            # Force FTS index sync to ensure immediate searchability
            # This prevents the "search returns 0 results immediately after insert" issue
            cursor.execute("SELECT 1 FROM discoveries_fts LIMIT 1")
            cursor.fetchone()

        except Exception as e:
            conn.rollback()
            raise e

    async def get_discovery(self, discovery_id: str) -> Optional[DiscoveryNode]:
        """Get discovery by ID"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM discoveries WHERE id = ?", (discovery_id,))
        row = cursor.fetchone()

        if not row:
            return None

        return self._row_to_discovery(row, cursor)

    async def update_discovery(self, discovery_id: str, updates: dict) -> bool:
        """Update discovery fields"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM discoveries WHERE id = ?", (discovery_id,))
        if not cursor.fetchone():
            return False

        try:
            # Handle special fields
            if "tags" in updates:
                cursor.execute("DELETE FROM discovery_tags WHERE discovery_id = ?", (discovery_id,))
                for tag in updates["tags"]:
                    cursor.execute(
                        "INSERT INTO discovery_tags (discovery_id, tag) VALUES (?, ?)",
                        (discovery_id, tag)
                    )
                del updates["tags"]

            if "response_to" in updates:
                # Remove old edge
                cursor.execute(
                    "DELETE FROM discovery_edges WHERE src_id = ? AND edge_type = 'response_to'",
                    (discovery_id,)
                )
                # Add new edge
                resp = updates["response_to"]
                if resp:
                    if isinstance(resp, ResponseTo):
                        resp_id, resp_type = resp.discovery_id, resp.response_type
                    else:
                        resp_id, resp_type = resp["discovery_id"], resp["response_type"]
                    cursor.execute("""
                        INSERT INTO discovery_edges
                        (src_id, dst_id, edge_type, response_type, created_at)
                        VALUES (?, ?, 'response_to', ?, ?)
                    """, (discovery_id, resp_id, resp_type, datetime.now().isoformat()))
                del updates["response_to"]

            # Update other fields
            if updates:
                updates["updated_at"] = datetime.now().isoformat()
                set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
                values = list(updates.values()) + [discovery_id]
                cursor.execute(f"UPDATE discoveries SET {set_clause} WHERE id = ?", values)

            conn.commit()
            return True

        except Exception as e:
            conn.rollback()
            raise e

    async def delete_discovery(self, discovery_id: str) -> bool:
        """Delete discovery (cascades to tags and edges)"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM discoveries WHERE id = ?", (discovery_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted

    # =========================================================================
    # Query Operations
    # =========================================================================

    async def query(self,
                   agent_id: Optional[str] = None,
                   tags: Optional[List[str]] = None,
                   type: Optional[str] = None,
                   severity: Optional[str] = None,
                   status: Optional[str] = None,
                   limit: int = 100) -> List[DiscoveryNode]:
        """Query discoveries with filters"""
        conn = self._get_conn()
        cursor = conn.cursor()

        query = "SELECT DISTINCT d.* FROM discoveries d"
        conditions = []
        params = []

        # Join tags if filtering by tags (OR-default)
        if tags:
            query += " JOIN discovery_tags t ON d.id = t.discovery_id"
            placeholders = ",".join("?" * len(tags))
            conditions.append(f"t.tag IN ({placeholders})")
            params.extend(tags)

        if agent_id:
            conditions.append("d.agent_id = ?")
            params.append(agent_id)

        if type:
            conditions.append("d.type = ?")
            params.append(type)

        if severity:
            conditions.append("d.severity = ?")
            params.append(severity)

        if status:
            conditions.append("d.status = ?")
            params.append(status)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY d.created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return [self._row_to_discovery(row, cursor) for row in cursor.fetchall()]

    async def find_similar(self, discovery: DiscoveryNode, limit: int = 10) -> List[DiscoveryNode]:
        """Find similar discoveries by tag overlap"""
        if not discovery.tags:
            return []

        conn = self._get_conn()
        cursor = conn.cursor()

        # Find discoveries with overlapping tags, scored by overlap count
        placeholders = ",".join("?" * len(discovery.tags))
        cursor.execute(f"""
            SELECT d.*, COUNT(*) as overlap
            FROM discoveries d
            JOIN discovery_tags t ON d.id = t.discovery_id
            WHERE t.tag IN ({placeholders})
            AND d.id != ?
            GROUP BY d.id
            ORDER BY overlap DESC
            LIMIT ?
        """, discovery.tags + [discovery.id, limit])

        return [self._row_to_discovery(row, cursor) for row in cursor.fetchall()]

    async def get_agent_discoveries(self, agent_id: str, limit: Optional[int] = None) -> List[DiscoveryNode]:
        """Get all discoveries for an agent"""
        conn = self._get_conn()
        cursor = conn.cursor()

        query = "SELECT * FROM discoveries WHERE agent_id = ? ORDER BY created_at DESC"
        params = [agent_id]

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        cursor.execute(query, params)
        return [self._row_to_discovery(row, cursor) for row in cursor.fetchall()]

    # =========================================================================
    # Graph Operations (NEW - the key value add)
    # =========================================================================

    async def get_related_discoveries(self, discovery_id: str,
                                      edge_types: Optional[List[str]] = None,
                                      limit: int = 20) -> List[Tuple[DiscoveryNode, str, str]]:
        """
        Get discoveries connected to this one via edges.
        Returns: List of (discovery, edge_type, direction) tuples
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        results = []

        # Outgoing edges (this discovery -> others)
        out_query = """
            SELECT d.*, e.edge_type, e.response_type
            FROM discoveries d
            JOIN discovery_edges e ON d.id = e.dst_id
            WHERE e.src_id = ?
        """
        out_params = [discovery_id]

        if edge_types:
            placeholders = ",".join("?" * len(edge_types))
            out_query += f" AND e.edge_type IN ({placeholders})"
            out_params.extend(edge_types)

        out_query += " LIMIT ?"
        out_params.append(limit)

        cursor.execute(out_query, out_params)
        for row in cursor.fetchall():
            node = self._row_to_discovery(row, cursor)
            results.append((node, row["edge_type"], "outgoing"))

        # Incoming edges (others -> this discovery)
        in_query = """
            SELECT d.*, e.edge_type, e.response_type
            FROM discoveries d
            JOIN discovery_edges e ON d.id = e.src_id
            WHERE e.dst_id = ?
        """
        in_params = [discovery_id]

        if edge_types:
            placeholders = ",".join("?" * len(edge_types))
            in_query += f" AND e.edge_type IN ({placeholders})"
            in_params.extend(edge_types)

        in_query += " LIMIT ?"
        in_params.append(limit)

        cursor.execute(in_query, in_params)
        for row in cursor.fetchall():
            node = self._row_to_discovery(row, cursor)
            results.append((node, row["edge_type"], "incoming"))

        return results[:limit]

    async def get_response_chain(self, discovery_id: str, max_depth: int = 10) -> List[DiscoveryNode]:
        """
        Get the full response chain for a discovery using recursive CTE.
        Returns discoveries in thread order (parent -> children).
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            WITH RECURSIVE thread AS (
                -- Base case: start with the given discovery
                SELECT id, 0 as depth FROM discoveries WHERE id = ?

                UNION ALL

                -- Recursive case: find discoveries that respond to items in thread
                SELECT d.id, t.depth + 1
                FROM discoveries d
                JOIN discovery_edges e ON d.id = e.src_id
                JOIN thread t ON e.dst_id = t.id
                WHERE e.edge_type = 'response_to' AND t.depth < ?
            )
            SELECT d.* FROM discoveries d
            JOIN thread t ON d.id = t.id
            ORDER BY t.depth
        """, (discovery_id, max_depth))

        return [self._row_to_discovery(row, cursor) for row in cursor.fetchall()]

    async def find_agents_with_similar_interests(self, agent_id: str,
                                                  min_overlap: int = 2,
                                                  limit: int = 10) -> List[Tuple[str, int]]:
        """
        Find agents working on similar topics based on tag overlap.
        Returns: List of (agent_id, overlap_count) tuples
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            WITH my_tags AS (
                SELECT DISTINCT t.tag
                FROM discovery_tags t
                JOIN discoveries d ON t.discovery_id = d.id
                WHERE d.agent_id = ?
            )
            SELECT d.agent_id, COUNT(DISTINCT t.tag) as overlap
            FROM discoveries d
            JOIN discovery_tags t ON d.id = t.discovery_id
            JOIN my_tags m ON t.tag = m.tag
            WHERE d.agent_id != ?
            GROUP BY d.agent_id
            HAVING overlap >= ?
            ORDER BY overlap DESC
            LIMIT ?
        """, (agent_id, agent_id, min_overlap, limit))

        return [(row["agent_id"], row["overlap"]) for row in cursor.fetchall()]

    async def full_text_search(self, query: str, limit: int = 20) -> List[DiscoveryNode]:
        """
        Search discoveries using full-text search.
        Supports FTS5 query syntax (AND, OR, NOT, phrases, etc.)

        UX FIX (Dec 2025): Default to OR for multi-term queries.
        FTS5 defaults to AND, but natural language queries expect OR behavior.
        "EISV basin phi" should find docs with ANY of those terms, not ALL.
        """
        # NOTE: Many callers provide natural language queries that may include quotes/apostrophes.
        # Raw FTS5 syntax is brittle (e.g., unbalanced quotes cause "fts5: syntax error").
        # We do a best-effort fallback: if raw query fails, retry with a safely-quoted phrase.
        conn = self._get_conn()
        cursor = conn.cursor()

        # UX FIX: Convert to OR by default unless query already has FTS operators
        processed_query = query
        if query and not any(op in query.upper() for op in [' AND ', ' OR ', ' NOT ', '"']):
            # Split on whitespace, join with OR for broader matching
            terms = query.split()
            if len(terms) > 1:
                processed_query = ' OR '.join(terms)

        sql = """
            SELECT d.* FROM discoveries d
            JOIN discoveries_fts fts ON d.rowid = fts.rowid
            WHERE discoveries_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        try:
            cursor.execute(sql, (processed_query, limit))
        except Exception:
            # Retry: treat as a literal phrase. Double quotes are FTS phrase delimiters.
            # Escape embedded quotes by doubling them.
            safe = (query or "").replace('"', '""')
            cursor.execute(sql, (f"\"{safe}\"", limit))

        return [self._row_to_discovery(row, cursor) for row in cursor.fetchall()]

    async def add_edge(self, src_id: str, dst_id: str, edge_type: str,
                       created_by: Optional[str] = None,
                       response_type: Optional[str] = None,
                       weight: float = 1.0,
                       metadata: Optional[dict] = None) -> bool:
        """Add an edge between two discoveries"""
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO discovery_edges
                (src_id, dst_id, edge_type, response_type, weight, created_at, created_by, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                src_id, dst_id, edge_type, response_type, weight,
                datetime.now().isoformat(), created_by,
                json.dumps(metadata) if metadata else None
            ))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Error adding edge: {e}")
            return False

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self) -> dict:
        """Get graph statistics"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM discoveries")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT agent_id, COUNT(*) as cnt FROM discoveries GROUP BY agent_id")
        by_agent = {row["agent_id"]: row["cnt"] for row in cursor.fetchall()}

        cursor.execute("SELECT type, COUNT(*) as cnt FROM discoveries GROUP BY type")
        by_type = {row["type"]: row["cnt"] for row in cursor.fetchall()}

        cursor.execute("SELECT status, COUNT(*) as cnt FROM discoveries GROUP BY status")
        by_status = {row["status"]: row["cnt"] for row in cursor.fetchall()}

        cursor.execute("SELECT COUNT(DISTINCT tag) FROM discovery_tags")
        total_tags = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM discovery_edges")
        total_edges = cursor.fetchone()[0]

        return {
            "total_discoveries": total,
            "by_agent": by_agent,
            "by_type": by_type,
            "by_status": by_status,
            "total_tags": total_tags,
            "total_agents": len(by_agent),
            "total_edges": total_edges
        }

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    async def _check_rate_limit(self, agent_id: str) -> None:
        """Check rate limit using persistent storage"""
        conn = self._get_conn()
        cursor = conn.cursor()

        one_hour_ago = (datetime.now().timestamp() - 3600)
        one_hour_ago_iso = datetime.fromtimestamp(one_hour_ago).isoformat()

        # Count recent stores
        cursor.execute("""
            SELECT COUNT(*) FROM rate_limits
            WHERE agent_id = ? AND timestamp > ?
        """, (agent_id, one_hour_ago_iso))

        count = cursor.fetchone()[0]

        if count >= self.rate_limit_stores_per_hour:
            raise ValueError(
                f"Rate limit exceeded: Agent '{agent_id}' has stored {count} "
                f"discoveries in the last hour (limit: {self.rate_limit_stores_per_hour}/hour)."
            )

        # Cleanup old rate limit entries
        cursor.execute(
            "DELETE FROM rate_limits WHERE timestamp < ?",
            (one_hour_ago_iso,)
        )
        conn.commit()

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _row_to_discovery(self, row: sqlite3.Row, cursor: sqlite3.Cursor) -> DiscoveryNode:
        """Convert database row to DiscoveryNode"""
        discovery_id = row["id"]

        # Get tags
        cursor.execute(
            "SELECT tag FROM discovery_tags WHERE discovery_id = ?",
            (discovery_id,)
        )
        tags = [r["tag"] for r in cursor.fetchall()]

        # Get response_to edge
        cursor.execute("""
            SELECT dst_id, response_type FROM discovery_edges
            WHERE src_id = ? AND edge_type = 'response_to'
        """, (discovery_id,))
        resp_row = cursor.fetchone()
        response_to = None
        if resp_row:
            response_to = ResponseTo(
                discovery_id=resp_row["dst_id"],
                response_type=resp_row["response_type"] or "extend"
            )

        # Get responses_from (backlinks)
        cursor.execute("""
            SELECT src_id FROM discovery_edges
            WHERE dst_id = ? AND edge_type = 'response_to'
        """, (discovery_id,))
        responses_from = [r["src_id"] for r in cursor.fetchall()]

        # Get related_to edges
        cursor.execute("""
            SELECT dst_id FROM discovery_edges
            WHERE src_id = ? AND edge_type = 'related_to'
        """, (discovery_id,))
        related_to = [r["dst_id"] for r in cursor.fetchall()]

        # Parse related_files JSON
        related_files = []
        if row["related_files"]:
            try:
                related_files = json.loads(row["related_files"])
            except json.JSONDecodeError:
                pass

        # Parse provenance JSON
        provenance = None
        if row["provenance"]:
            try:
                provenance = json.loads(row["provenance"])
            except json.JSONDecodeError:
                pass

        # Parse provenance_chain JSON
        provenance_chain = None
        if row["provenance_chain"]:
            try:
                provenance_chain = json.loads(row["provenance_chain"])
            except json.JSONDecodeError:
                pass

        return DiscoveryNode(
            id=row["id"],
            agent_id=row["agent_id"],
            type=row["type"],
            summary=row["summary"],
            details=row["details"] or "",
            tags=tags,
            severity=row["severity"],
            timestamp=row["created_at"],
            status=row["status"],
            related_to=related_to,
            response_to=response_to,
            responses_from=responses_from,
            references_files=related_files,
            resolved_at=row["resolved_at"],
            updated_at=row["updated_at"],
            confidence=row["confidence"],
            provenance=provenance,
            provenance_chain=provenance_chain
        )

    async def load(self):
        """No-op for compatibility - SQLite is always persistent"""
        pass
    
    # =========================================================================
    # Embedding Generation (for semantic search)
    # =========================================================================
    
    def _get_embedding_model(self):
        """Lazy-load embedding model"""
        if self._embedding_model is None and self.enable_embeddings:
            try:
                from sentence_transformers import SentenceTransformer
                # Use lightweight model (all-MiniLM-L6-v2: 80MB, fast, good quality)
                self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("Loaded embedding model: all-MiniLM-L6-v2")
            except ImportError:
                logger.warning(
                    "sentence-transformers not available. Install with: pip install sentence-transformers"
                )
                self.enable_embeddings = False
            except Exception as e:
                logger.warning(f"Could not load embedding model: {e}")
                self.enable_embeddings = False
        return self._embedding_model
    
    def _generate_embedding(self, text: str) -> Optional[bytes]:
        """Generate embedding for text"""
        if not self.enable_embeddings:
            return None
        
        model = self._get_embedding_model()
        if model is None:
            return None
        
        try:
            # Combine summary and details for embedding
            embedding = model.encode(text, convert_to_numpy=True)
            # Store as JSON array of floats (portable, no numpy dependency)
            return json.dumps(embedding.tolist()).encode('utf-8')
        except Exception as e:
            logger.warning(f"Could not generate embedding: {e}")
            return None
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        import math
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(a * a for a in vec2))
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        
        return dot_product / (magnitude1 * magnitude2)
    
    async def semantic_search(self, query: str, limit: int = 20, min_similarity: float = 0.3) -> List[Tuple[DiscoveryNode, float]]:
        """
        Semantic search using vector embeddings.
        
        Args:
            query: Natural language query
            limit: Maximum number of results
            min_similarity: Minimum cosine similarity threshold (0.0-1.0)
        
        Returns:
            List of (discovery, similarity_score) tuples, sorted by similarity
        """
        if not self.enable_embeddings:
            # Fallback to FTS if embeddings not available
            logger.debug("Embeddings not available, falling back to FTS")
            results = await self.full_text_search(query, limit)
            return [(r, 1.0) for r in results]
        
        # Generate query embedding
        query_embedding_bytes = self._generate_embedding(query)
        if query_embedding_bytes is None:
            # Fallback to FTS
            results = await self.full_text_search(query, limit)
            return [(r, 1.0) for r in results]
        
        query_embedding = json.loads(query_embedding_bytes.decode('utf-8'))
        
        # Search all discoveries with embeddings
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, embedding FROM discoveries
            WHERE embedding IS NOT NULL
        """)
        
        results = []
        for row in cursor.fetchall():
            discovery_id = row["id"]
            embedding_data = row["embedding"]

            if embedding_data:
                try:
                    # Handle both bytes and string storage formats
                    if isinstance(embedding_data, bytes):
                        discovery_embedding = json.loads(embedding_data.decode('utf-8'))
                    else:
                        discovery_embedding = json.loads(embedding_data)
                    similarity = self._cosine_similarity(query_embedding, discovery_embedding)
                    
                    if similarity >= min_similarity:
                        discovery = await self.get_discovery(discovery_id)
                        if discovery:
                            results.append((discovery, similarity))
                except Exception as e:
                    logger.debug(f"Could not decode embedding for {discovery_id}: {e}")
                    continue
        
        # Sort by similarity (descending) and return top N
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]


# =============================================================================
# Global Instance
# =============================================================================

_db_instance: Optional[KnowledgeGraphDB] = None
_db_lock: Optional[asyncio.Lock] = None


async def get_knowledge_graph_db() -> KnowledgeGraphDB:
    """Get global SQLite knowledge graph instance"""
    global _db_instance, _db_lock

    if _db_lock is None:
        _db_lock = asyncio.Lock()

    async with _db_lock:
        if _db_instance is None:
            _db_instance = KnowledgeGraphDB()
        return _db_instance
