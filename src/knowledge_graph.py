"""
Knowledge Graph - Data types and backend factory

Provides DiscoveryNode/ResponseTo data types used by all backends,
and get_knowledge_graph() factory for backend selection.

Backends:
- AGE (PostgreSQL + Apache AGE) - primary, configured via UNITARES_KNOWLEDGE_BACKEND=age
- PostgreSQL FTS - fallback, configured via UNITARES_KNOWLEDGE_BACKEND=postgres
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal, Any
from datetime import datetime
import os
import asyncio

# Import structured logging
from src.logging_utils import get_logger
logger = get_logger(__name__)


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
    type: str  # "bug_found", "insight", "pattern", "improvement", "question", "answer"
    summary: str
    details: str = ""
    tags: List[str] = field(default_factory=list)
    severity: Optional[str] = None  # "low", "medium", "high", "critical"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "open"  # "open", "resolved", "archived", "disputed"
    related_to: List[str] = field(default_factory=list)  # IDs of related discoveries (backward compat)
    response_to: Optional[ResponseTo] = None  # Typed response to parent discovery
    responses_from: List[str] = field(default_factory=list)  # IDs of discoveries that respond to this one (backlinks)
    references_files: List[str] = field(default_factory=list)
    resolved_at: Optional[str] = None
    updated_at: Optional[str] = None
    confidence: Optional[float] = None
    # ENHANCED PROVENANCE: Agent state at time of creation (2025-12-15)
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
            "created_at": self.timestamp,  # Alias for timestamp (UX consistency)
            "status": self.status,
            "related_to": self.related_to,
            "references_files": self.references_files,
            "resolved_at": self.resolved_at,
            "updated_at": self.updated_at
        }

        # Add typed response_to if present
        if self.response_to:
            result["response_to"] = {
                "discovery_id": self.response_to.discovery_id,
                "response_type": self.response_to.response_type
            }

        # Add backlinks (responses_from)
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
            # Include truncated hint if details exist
            if self.details:
                result["has_details"] = True
                result["details_preview"] = self.details[:100] + "..." if len(self.details) > 100 else self.details
        return result

    @classmethod
    def from_dict(cls, data: dict) -> 'DiscoveryNode':
        """Create from dictionary"""
        # Parse response_to if present
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
            confidence=data.get("confidence"),
            provenance=data.get("provenance"),
            provenance_chain=data.get("provenance_chain"),
        )


# Global graph instance (initialized on first use)
_graph_instance: Optional[Any] = None
_graph_lock: Optional[asyncio.Lock] = None  # Created lazily to avoid binding to wrong event loop


async def get_knowledge_graph() -> Any:
    """
    Get global knowledge graph instance (singleton).

    Backend selection (priority order):
    1. UNITARES_KNOWLEDGE_BACKEND env var (explicit override)
       - age     -> AGE (PostgreSQL + Apache AGE) backend
       - postgres -> PostgreSQL FTS backend
       - auto    -> see below
    2. DB_BACKEND env var (implicit selection when UNITARES_KNOWLEDGE_BACKEND=auto)
       - postgres -> PostgreSQL FTS backend

    If PostgreSQL is unavailable, the server fails honestly rather than
    silently degrading to an in-memory store.
    """
    global _graph_instance, _graph_lock

    # Create lock lazily in the current event loop (fixes import-time binding issue)
    if _graph_lock is None:
        _graph_lock = asyncio.Lock()

    async with _graph_lock:
        if _graph_instance is not None:
            return _graph_instance

        backend = os.getenv("UNITARES_KNOWLEDGE_BACKEND", "auto").strip().lower()
        db_backend = os.getenv("DB_BACKEND", "postgres").strip().lower()

        # If auto and main database is PostgreSQL, use PostgreSQL for knowledge graph too
        if backend == "auto" and db_backend == "postgres":
            backend = "postgres"
            logger.info("Auto-selecting PostgreSQL knowledge backend (DB_BACKEND=postgres)")

        # AGE backend (PostgreSQL + Apache AGE)
        if backend == "age":
            from src.storage.knowledge_graph_age import KnowledgeGraphAGE
            _graph_instance = KnowledgeGraphAGE()
            await _graph_instance.load()
            logger.info("Using AGE (PostgreSQL + Apache AGE) knowledge graph backend")
            return _graph_instance

        # PostgreSQL FTS backend (unified with main database)
        if backend in ("postgres", "auto"):
            from src.storage.knowledge_graph_postgres import KnowledgeGraphPostgres
            _graph_instance = KnowledgeGraphPostgres()
            await _graph_instance.load()
            logger.info("Using PostgreSQL FTS knowledge graph backend")
            return _graph_instance

        raise RuntimeError(
            f"Unknown knowledge backend '{backend}'. "
            f"Set UNITARES_KNOWLEDGE_BACKEND to 'age' or 'postgres'."
        )
