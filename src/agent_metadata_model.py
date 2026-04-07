"""
Agent metadata model and shared state.

Contains AgentMetadata dataclass, the in-memory agent registry (agent_metadata dict),
and project-level constants shared across agent_state sub-modules.
"""

from __future__ import annotations

import sys
import os
import threading
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime

# -----------------------------------------------------------------------------
# BOOTSTRAP IMPORT PATH (critical for Claude Desktop / script execution)
# -----------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env file if present
try:
    from dotenv import load_dotenv
    _env_path = _PROJECT_ROOT / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

from src.logging_utils import get_logger
logger = get_logger(__name__)


def _emit_lifecycle_event(agent_id: str, event: str, reason: str | None, timestamp: str):
    """Broadcast a lifecycle event via the event bus. Fire-and-forget."""
    try:
        import asyncio
        from src.broadcaster import broadcaster_instance

        async def _emit():
            try:
                await broadcaster_instance.broadcast_event(
                    event_type=f"lifecycle_{event}",
                    agent_id=agent_id,
                    payload={"reason": reason},
                )
            except Exception as e:
                logger.debug(f"Lifecycle broadcast failed: {e}")

            # Also write to audit DB (best-effort)
            try:
                from src.audit_db import append_audit_event_async
                await append_audit_event_async({
                    "timestamp": timestamp,
                    "event_type": f"lifecycle_{event}",
                    "agent_id": agent_id,
                    "details": {"reason": reason, "event": event},
                })
            except Exception as e:
                logger.debug(f"Lifecycle audit write failed: {e}")

        # Schedule onto the running event loop if available
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_emit())
        except RuntimeError:
            pass  # No event loop — skip broadcast (e.g. during tests)
    except Exception:
        pass  # Never let broadcasting break lifecycle transitions

# Project root (single source of truth for file locations)
project_root = _PROJECT_ROOT

# MCP types used for error responses in auth functions
try:
    from mcp.types import TextContent
except ImportError:
    class TextContent:
        def __init__(self, type: str = "text", text: str = ""):
            self.type = type
            self.text = text

# Server version - auto-synced from VERSION file at startup
from src.versioning import load_version_from_file

def _load_version():
    """Load version from VERSION file (single source of truth)."""
    return load_version_from_file(project_root)

SERVER_VERSION = _load_version()
SERVER_BUILD_DATE = "2026-02-05"


def _normalize_http_proxy_base(url: str) -> str:
    """Normalize HTTP proxy base URL to a plain base (no trailing /v1/tools(/call))."""
    u = (url or "").strip()
    if not u:
        return u
    u = u.rstrip("/")
    if u.endswith("/v1/tools/call"):
        return u[: -len("/v1/tools/call")]
    if u.endswith("/v1/tools"):
        return u[: -len("/v1/tools")]
    return u


@dataclass
class AgentMetadata:
    """Agent lifecycle metadata"""
    agent_id: str
    status: str  # "active", "waiting_input", "paused", "archived", "deleted"
    created_at: str  # ISO format
    last_update: str  # ISO format
    version: str = "v1.0"
    total_updates: int = 0
    tags: list[str] = None
    notes: str = ""
    lifecycle_events: list[dict] = None
    paused_at: str = None
    archived_at: str = None
    parent_agent_id: str = None
    spawn_reason: str = None
    api_key: str = None
    recent_update_timestamps: list[str] = None
    recent_decisions: list[str] = None
    loop_detected_at: str = None
    loop_cooldown_until: str = None
    recovery_attempt_at: str = None
    last_response_at: str = None
    response_completed: bool = False
    health_status: str = "unknown"
    dialectic_conditions: list[dict] = None
    active_session_key: str = None
    session_bound_at: str = None
    thread_id: str = None
    node_index: int = 1
    purpose: str = None
    agent_uuid: str = None
    public_agent_id: str = None
    structured_id: str = None
    label: str = None
    preferences: dict = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.lifecycle_events is None:
            self.lifecycle_events = []
        if self.recent_update_timestamps is None:
            self.recent_update_timestamps = []
        if self.recent_decisions is None:
            self.recent_decisions = []
        if self.dialectic_conditions is None:
            self.dialectic_conditions = []

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)

    MAX_LIFECYCLE_EVENTS = 50

    def add_lifecycle_event(self, event: str, reason: str = None):
        """Add a lifecycle event with timestamp. Broadcasts via event bus."""
        ts = datetime.now().isoformat()
        self.lifecycle_events.append({
            "event": event,
            "timestamp": ts,
            "reason": reason
        })
        if len(self.lifecycle_events) > self.MAX_LIFECYCLE_EVENTS:
            self.lifecycle_events = self.lifecycle_events[-self.MAX_LIFECYCLE_EVENTS:]
        # Fire-and-forget broadcast + audit for sentinel consumption
        _emit_lifecycle_event(self.agent_id, event, reason, ts)

    def validate_consistency(self) -> tuple[bool, list[str]]:
        """
        Validate metadata consistency invariants.

        Returns:
            (is_valid, list_of_errors)
        """
        errors = []

        timestamps_len = len(self.recent_update_timestamps)
        decisions_len = len(self.recent_decisions)

        if timestamps_len != decisions_len:
            errors.append(
                f"recent_update_timestamps ({timestamps_len} entries) and "
                f"recent_decisions ({decisions_len} entries) have mismatched lengths"
            )

        if self.total_updates <= 10:
            if timestamps_len != self.total_updates:
                errors.append(
                    f"total_updates ({self.total_updates}) does not match "
                    f"recent_update_timestamps length ({timestamps_len})"
                )
        else:
            if timestamps_len > 10:
                errors.append(
                    f"recent_update_timestamps ({timestamps_len} entries) exceeds cap of 10"
                )
            if decisions_len > 10:
                errors.append(
                    f"recent_decisions ({decisions_len} entries) exceeds cap of 10"
                )

        if self.status == "paused" and not self.paused_at:
            errors.append("status is 'paused' but paused_at is None")

        try:
            if self.created_at:
                datetime.fromisoformat(self.created_at.replace('Z', '+00:00') if 'Z' in self.created_at else self.created_at)
            if self.last_update:
                datetime.fromisoformat(self.last_update.replace('Z', '+00:00') if 'Z' in self.last_update else self.last_update)
            if self.paused_at:
                datetime.fromisoformat(self.paused_at.replace('Z', '+00:00') if 'Z' in self.paused_at else self.paused_at)
            if self.archived_at:
                datetime.fromisoformat(self.archived_at.replace('Z', '+00:00') if 'Z' in self.archived_at else self.archived_at)
        except (ValueError, AttributeError) as e:
            errors.append(f"Invalid timestamp format: {e}")

        return len(errors) == 0, errors


# Store agent metadata (shared mutable dict — all sub-modules use this reference)
agent_metadata: dict[str, AgentMetadata] = {}

# Lazy loading state (for fast server startup)
_metadata_loading_lock = threading.Lock()
_metadata_loading = False
_metadata_loaded = False
_metadata_loaded_event = threading.Event()

# Metadata cache state
_metadata_cache_state = {
    "last_load_time": 0.0,
    "last_file_mtime": 0.0,
    "cache_ttl": 60.0,
    "dirty": False
}

# Shorter TTL for exploration tools (list_agents, check_continuity_health) so agents
# first exploring the system get fresh agent/system info instead of stale cache.
EXPLORATION_CACHE_TTL = 15.0

# Batched metadata save state
_metadata_batch_state = {
    "dirty": False,
    "save_task": None,
    "save_lock": None,
    "debounce_delay": 0.5,
    "max_batch_delay": 2.0,
    "last_save_time": 0,
    "pending_save": False
}
