"""
Abstract Base Class for Database Backends

Defines the interface that database backends must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class IdentityRecord:
    """Identity/agent record."""
    identity_id: int
    agent_id: str
    api_key_hash: str
    created_at: datetime
    updated_at: datetime
    status: str = "active"
    parent_agent_id: Optional[str] = None
    spawn_reason: Optional[str] = None
    disabled_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionRecord:
    """Session binding record."""
    session_id: str
    identity_id: int
    agent_id: str  # Denormalized for convenience
    created_at: datetime
    last_active: datetime
    expires_at: datetime
    is_active: bool = True
    client_type: Optional[str] = None
    client_info: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentStateRecord:
    """Agent state snapshot (EISV metrics)."""
    state_id: int
    identity_id: int
    agent_id: str
    recorded_at: datetime
    entropy: float = 0.5
    integrity: float = 0.5
    stability_index: float = 0.5
    void: float = 0.1
    regime: str = "nominal"
    coherence: float = 1.0
    state_json: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditEvent:
    """Audit event record."""
    ts: datetime
    event_id: str
    event_type: str
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    confidence: float = 1.0
    payload: Dict[str, Any] = field(default_factory=dict)
    raw_hash: Optional[str] = None


class DatabaseBackend(ABC):
    """
    Abstract base class for database backends.

    All methods are async to support async PostgreSQL.
    """

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    @abstractmethod
    async def init(self) -> None:
        """Initialize the database (create tables, run migrations)."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close database connections."""
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Return health/status information."""
        pass

    # =========================================================================
    # IDENTITY OPERATIONS
    # =========================================================================

    @abstractmethod
    async def upsert_identity(
        self,
        agent_id: str,
        api_key_hash: str,
        parent_agent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
    ) -> int:
        """
        Create or update an identity.

        Returns: identity_id (primary key)
        """
        pass

    @abstractmethod
    async def get_identity(self, agent_id: str) -> Optional[IdentityRecord]:
        """Get identity by agent_id."""
        pass

    @abstractmethod
    async def get_identity_by_id(self, identity_id: int) -> Optional[IdentityRecord]:
        """Get identity by numeric identity_id."""
        pass

    @abstractmethod
    async def list_identities(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[IdentityRecord]:
        """List identities with optional filtering."""
        pass

    @abstractmethod
    async def update_identity_status(
        self,
        agent_id: str,
        status: str,
        disabled_at: Optional[datetime] = None,
    ) -> bool:
        """Update identity status. Returns True if updated."""
        pass

    @abstractmethod
    async def update_identity_metadata(
        self,
        agent_id: str,
        metadata: Dict[str, Any],
        merge: bool = True,
    ) -> bool:
        """Update identity metadata. If merge=True, merges with existing."""
        pass

    @abstractmethod
    async def upsert_agent(
        self,
        agent_id: str,
        api_key: str,
        status: str = "active",
        purpose: Optional[str] = None,
        notes: Optional[str] = None,
        tags: Optional[List[str]] = None,
        parent_agent_id: Optional[str] = None,
        spawn_reason: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> bool:
        """
        Create or update an agent in core.agents table.
        
        This is required for foreign key references in dialectic_sessions.
        Returns True if successful.
        """
        pass

    @abstractmethod
    async def update_agent_fields(
        self,
        agent_id: str,
        *,
        status: Optional[str] = None,
        purpose: Optional[str] = None,
        notes: Optional[str] = None,
        tags: Optional[List[str]] = None,
        parent_agent_id: Optional[str] = None,
        spawn_reason: Optional[str] = None,
        label: Optional[str] = None,
    ) -> bool:
        """
        Update selected fields on core.agents WITHOUT touching api_key.

        Safer than upsert_agent() for routine metadata edits (purpose/notes/tags),
        because it avoids accidental overwrites of api_key or created_at.
        """
        pass

    @abstractmethod
    async def verify_api_key(self, agent_id: str, api_key: str) -> bool:
        """Verify API key for an identity."""
        pass

    @abstractmethod
    async def get_agent_label(self, agent_id: str) -> Optional[str]:
        """Get agent's display label."""
        pass

    @abstractmethod
    async def find_agent_by_label(self, label: str) -> Optional[str]:
        """Find agent UUID by label (for collision detection)."""
        pass

    # =========================================================================
    # SESSION OPERATIONS
    # =========================================================================

    @abstractmethod
    async def create_session(
        self,
        session_id: str,
        identity_id: int,
        expires_at: datetime,
        client_type: Optional[str] = None,
        client_info: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Create a new session. Returns True if created."""
        pass

    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[SessionRecord]:
        """Get session by session_id."""
        pass

    @abstractmethod
    async def update_session_activity(self, session_id: str) -> bool:
        """Update session last_active timestamp. Returns True if updated."""
        pass

    @abstractmethod
    async def end_session(self, session_id: str) -> bool:
        """Mark session as inactive. Returns True if updated."""
        pass

    @abstractmethod
    async def get_active_sessions_for_identity(
        self,
        identity_id: int,
    ) -> List[SessionRecord]:
        """Get all active sessions for an identity."""
        pass

    @abstractmethod
    async def cleanup_expired_sessions(self) -> int:
        """Delete expired sessions. Returns count deleted."""
        pass

    # =========================================================================
    # AGENT STATE OPERATIONS
    # =========================================================================

    @abstractmethod
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
        """Record a new state snapshot. Returns state_id."""
        pass

    @abstractmethod
    async def get_latest_agent_state(
        self,
        identity_id: int,
    ) -> Optional[AgentStateRecord]:
        """Get most recent state for an identity."""
        pass

    @abstractmethod
    async def get_agent_state_history(
        self,
        identity_id: int,
        limit: int = 100,
    ) -> List[AgentStateRecord]:
        """Get state history for an identity."""
        pass

    # =========================================================================
    # AUDIT OPERATIONS
    # =========================================================================

    @abstractmethod
    async def append_audit_event(self, event: AuditEvent) -> bool:
        """Append an audit event. Returns True if inserted."""
        pass

    @abstractmethod
    async def query_audit_events(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
        order: str = "asc",
    ) -> List[AuditEvent]:
        """Query audit events with filtering."""
        pass

    @abstractmethod
    async def search_audit_events(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[AuditEvent]:
        """Full-text search on audit events."""
        pass

    # =========================================================================
    # CALIBRATION OPERATIONS
    # =========================================================================

    @abstractmethod
    async def get_calibration(self) -> Dict[str, Any]:
        """Get calibration data."""
        pass

    @abstractmethod
    async def update_calibration(self, data: Dict[str, Any]) -> bool:
        """Update calibration data (replaces entire object)."""
        pass

    # =========================================================================
    # GRAPH OPERATIONS (AGE-specific)
    # =========================================================================

    async def graph_query(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query against the graph.

        Default implementation returns empty list (no graph support).
        PostgreSQL backend overrides with AGE implementation.
        """
        return []

    async def graph_available(self) -> bool:
        """Check if graph queries are available."""
        return False

    # =========================================================================
    # TOOL USAGE OPERATIONS
    # =========================================================================

    @abstractmethod
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
        """Record tool usage. Returns True if inserted."""
        pass

    @abstractmethod
    async def query_tool_usage(
        self,
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Query tool usage records."""
        pass

    # =========================================================================
    # DIALECTIC OPERATIONS
    # =========================================================================

    @abstractmethod
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
        """Create a new dialectic session. Returns dict with session_id and created flag."""
        pass

    @abstractmethod
    async def get_dialectic_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get dialectic session by ID with all messages."""
        pass

    @abstractmethod
    async def get_dialectic_session_by_agent(
        self,
        agent_id: str,
        active_only: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Get session where agent is paused agent or reviewer."""
        pass

    @abstractmethod
    async def get_all_active_dialectic_sessions_for_agent(
        self,
        agent_id: str,
    ) -> List[Dict[str, Any]]:
        """Get all active sessions where agent is paused agent or reviewer."""
        pass

    @abstractmethod
    async def update_dialectic_session_phase(
        self,
        session_id: str,
        phase: str,
    ) -> bool:
        """Update session phase. Returns True if updated."""
        pass

    @abstractmethod
    async def update_dialectic_session_reviewer(
        self,
        session_id: str,
        reviewer_agent_id: str,
    ) -> bool:
        """Assign reviewer to session. Returns True if updated."""
        pass

    @abstractmethod
    async def add_dialectic_message(
        self,
        session_id: str,
        agent_id: str,
        message_type: str,  # 'thesis', 'antithesis', 'synthesis'
        root_cause: Optional[str] = None,
        proposed_conditions: Optional[List[str]] = None,
        reasoning: Optional[str] = None,
        observed_metrics: Optional[Dict[str, Any]] = None,
        concerns: Optional[List[str]] = None,
        agrees: Optional[bool] = None,
        signature: Optional[str] = None,
    ) -> int:
        """Add a message to a session. Returns message_id."""
        pass

    @abstractmethod
    async def resolve_dialectic_session(
        self,
        session_id: str,
        resolution: Dict[str, Any],
        status: str = "resolved",
    ) -> bool:
        """Mark session as resolved. Returns True if updated."""
        pass

    @abstractmethod
    async def is_agent_in_active_dialectic_session(self, agent_id: str) -> bool:
        """Check if agent is in an active session (as paused or reviewer)."""
        pass

    async def get_pending_dialectic_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get dialectic sessions awaiting a reviewer (reviewer_agent_id IS NULL).

        Used for pull-based discovery: agents check for pending reviews on status().
        This enables human-in-the-loop and async review without requiring persistent agent pools.

        Default implementation returns empty list.
        PostgreSQL backend overrides with actual query.

        Returns:
            List of session dicts with: session_id, paused_agent_id, session_type,
            phase, created_at, reason (if available)
        """
        return []
