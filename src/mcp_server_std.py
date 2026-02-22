#!/usr/bin/env python3
"""
UNITARES Governance MCP Server v1.0 - Standard MCP Protocol Implementation

This is a proper MCP server implementation that follows the Model Context Protocol specification.
It can be used with Cursor (Composer), Claude Desktop, and other MCP-compatible clients.

Usage:
    python src/mcp_server_std.py

Configuration:
    Add to Cursor MCP config (for Composer) or Claude Desktop MCP config
"""

from __future__ import annotations  # Enable postponed evaluation of annotations (Python 3.7+)

import sys
import json
import asyncio
from pathlib import Path
from typing import Any, Sequence
import traceback
import signal
import atexit
import os
import time
import fcntl
import secrets
import base64
import threading

# -----------------------------------------------------------------------------
# BOOTSTRAP IMPORT PATH (critical for Claude Desktop / script execution)
#
# When this file is executed as `python src/mcp_server_std.py`, Python puts the
# `src/` directory on sys.path. That *does not* allow `import src.*` because
# the package root is one directory above. Ensure project root is on sys.path
# before importing anything from `src`.
# -----------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env file if present (for UNITARES_KNOWLEDGE_BACKEND, DB_POSTGRES_URL, etc.)
try:
    from dotenv import load_dotenv
    _env_path = _PROJECT_ROOT / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # dotenv not installed, rely on system environment

# Import structured logging early (used by optional dependency warnings below)
from src.logging_utils import get_logger
logger = get_logger(__name__)

try:
    import aiofiles
    AIOFILES_AVAILABLE = True
except ImportError:
    AIOFILES_AVAILABLE = False
    logger.warning("aiofiles not available. File I/O will be synchronous. Install with: pip install aiofiles")

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available. Process cleanup disabled. Install with: pip install psutil")

# Project root (single source of truth for file locations)
project_root = _PROJECT_ROOT

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_SDK_AVAILABLE = True
except ImportError as e:
    MCP_SDK_AVAILABLE = False
    print(f"Error: MCP SDK not available: {e}", file=sys.stderr)
    print(f"Python: {sys.executable}", file=sys.stderr)
    print(f"PYTHONPATH: {sys.path}", file=sys.stderr)
    print("Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

from src.governance_monitor import UNITARESMonitor
from src.state_locking import StateLockManager
from src.health_thresholds import HealthThresholds, HealthStatus
from src.process_cleanup import ProcessManager
from src.pattern_analysis import analyze_agent_patterns
from src.runtime_config import get_thresholds
from src.lock_cleanup import cleanup_stale_state_locks
from src.tool_schemas import get_tool_definitions
# Tool mode filtering removed - all tools always available
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import os

# Tool mode filtering removed - all tools always available
# (GOVERNANCE_TOOL_MODE environment variable no longer used)

# Server version - auto-synced from VERSION file at startup
# Single source of truth: VERSION file
def _load_version():
    """Load version from VERSION file (single source of truth)."""
    version_file = project_root / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "2.7.0"  # Fallback if VERSION file missing

SERVER_VERSION = _load_version()  # Auto-sync from VERSION file
SERVER_BUILD_DATE = "2026-02-05"

# PID file for process tracking
PID_FILE = Path(project_root) / "data" / ".mcp_server.pid"
LOCK_FILE = Path(project_root) / "data" / ".mcp_server.lock"

# Maximum number of processes to keep before cleanup
# Rationale: Allows multiple concurrent clients (SSE, stdio) while preventing zombie accumulation.
# Value 42 chosen as a balance: high enough for multi-agent scenarios (10-20 agents), 
# low enough to prevent runaway process growth. Typical usage: 1-5 processes.
# If exceeded, oldest processes (>5min old, no heartbeat) are cleaned up.
MAX_KEEP_PROCESSES = 42

# Create MCP server instance
server = Server("governance-monitor-v1")

# Current process PID
CURRENT_PID = os.getpid()

# ============================================================================
# MCP Resource Registration (SKILL.md)
# ============================================================================

@server.list_resources()
async def list_resources():
    from mcp.types import Resource
    return [
        Resource(
            uri="unitares://skill",
            name="UNITARES Governance SKILL",
            description="Governance framework orientation document for agents",
            mimeType="text/markdown",
        )
    ]

@server.read_resource()
async def read_resource(uri):
    from mcp.types import TextResourceContents
    if str(uri) == "unitares://skill":
        skill_path = Path(project_root) / "skills" / "unitares-governance" / "SKILL.md"
        if skill_path.exists():
            content = skill_path.read_text()
        else:
            content = "# UNITARES Governance\n\nSKILL.md not found. Use onboard() to get started."
        return content
    raise ValueError(f"Unknown resource: {uri}")

# -----------------------------------------------------------------------------
# Optional: STDIO -> Server Proxy Mode
#
# Motivation:
# - Claude Desktop is stdio-only, but we want it to participate in the shared
#   server "world" (shared monitors, dialectic sessions, shared state).
# - When enabled, stdio server becomes a thin proxy that forwards list_tools and
#   call_tool to an already-running governance server.
#
# Enable by setting:
#   UNITARES_PROXY_URL=http://127.0.0.1:8767/mcp
# OR (REST-based, preferred for non-MCP clients):
#   UNITARES_STDIO_PROXY_HTTP_URL=http://127.0.0.1:8767
#   (also accepts full endpoints ending in /v1/tools or /v1/tools/call)
# Optional:
#   UNITARES_STDIO_PROXY_STRICT=1  (default) -> fail if server unavailable
#
# Legacy env var UNITARES_STDIO_PROXY_URL is still supported as fallback.
# -----------------------------------------------------------------------------
STDIO_PROXY_HTTP_URL = os.getenv("UNITARES_STDIO_PROXY_HTTP_URL")
STDIO_PROXY_URL = os.getenv("UNITARES_PROXY_URL") or os.getenv("UNITARES_STDIO_PROXY_URL")
STDIO_PROXY_STRICT = os.getenv("UNITARES_STDIO_PROXY_STRICT", "1").strip().lower() not in ("0", "false", "no")
STDIO_PROXY_HTTP_BEARER_TOKEN = os.getenv("UNITARES_STDIO_PROXY_HTTP_BEARER_TOKEN")  # optional


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


async def _proxy_http_list_tools() -> list[Tool]:
    """Proxy list_tools to HTTP (/v1/tools) and convert to MCP Tool objects."""
    import urllib.request
    import urllib.error

    base = _normalize_http_proxy_base(STDIO_PROXY_HTTP_URL)
    url = f"{base}/v1/tools"

    headers = {"Accept": "application/json", "X-Session-ID": f"stdio:{os.getpid()}"}
    if STDIO_PROXY_HTTP_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {STDIO_PROXY_HTTP_BEARER_TOKEN}"

    def _fetch_sync() -> dict[str, Any]:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read().decode("utf-8")
        return json.loads(data)

    loop = asyncio.get_running_loop()
    payload = await loop.run_in_executor(None, _fetch_sync)

    tools = []
    for entry in payload.get("tools", []) or []:
        # OpenAI-style: {"type":"function","function":{"name","description","parameters"}}
        fn = entry.get("function") if isinstance(entry, dict) else None
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not name:
            continue
        tools.append(Tool(
            name=name,
            description=fn.get("description") or "",
            inputSchema=fn.get("parameters") or {"type": "object", "properties": {}},
        ))
    # Optional: tool mode filtering (reduces cognitive load in Claude Desktop / local models)
    try:
        from src.tool_modes import TOOL_MODE, should_include_tool
        return [t for t in tools if should_include_tool(t.name, mode=TOOL_MODE)]
    except Exception:
        return tools


async def _proxy_http_call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Proxy call_tool to HTTP (/v1/tools/call)."""
    import urllib.request
    import urllib.error

    base = _normalize_http_proxy_base(STDIO_PROXY_HTTP_URL)
    url = f"{base}/v1/tools/call"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Session-ID": f"stdio:{os.getpid()}",
    }
    if STDIO_PROXY_HTTP_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {STDIO_PROXY_HTTP_BEARER_TOKEN}"

    body = json.dumps({"name": name, "arguments": arguments or {}}).encode("utf-8")

    def _post_sync() -> dict[str, Any]:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read().decode("utf-8")
        return json.loads(data)

    loop = asyncio.get_running_loop()
    payload = await loop.run_in_executor(None, _post_sync)

    # Normalize to TextContent payload (what MCP clients expect from stdio server)
    if isinstance(payload, dict) and payload.get("success") is True and "result" in payload:
        out = payload["result"]
    else:
        out = payload
    return [TextContent(type="text", text=json.dumps(out, indent=2))]


def _create_http1_only_client_factory():
    """
    Create httpx client factory that forces HTTP/1.1 only (fixes ngrok 421 errors).

    ngrok tunnels can return 421 Misdirected Request with HTTP/2 connection reuse.
    Forcing HTTP/1.1 resolves this issue.
    """
    import httpx
    def http1_client_factory(**kwargs):
        return httpx.AsyncClient(http2=False, **kwargs)
    return http1_client_factory


async def _proxy_list_tools() -> list[Tool]:
    """
    Proxy list_tools to remote MCP server (auto-detects Streamable HTTP vs legacy SSE).

    NOTE: We intentionally use per-request connections to avoid anyio cancel-scope
    edge cases on stdio client disconnect/teardown.
    """
    from mcp.client.session import ClientSession
    http1_factory = _create_http1_only_client_factory()

    # Auto-detect transport based on URL path
    if "/mcp" in STDIO_PROXY_URL:
        # Use Streamable HTTP transport
        import httpx
        from mcp.client.streamable_http import streamable_http_client
        async with httpx.AsyncClient(http2=False, timeout=15) as http_client:
            async with streamable_http_client(STDIO_PROXY_URL, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    res = await session.list_tools()
                    return res.tools
    else:
        # Use SSE transport (legacy)
        from mcp.client.sse import sse_client
        async with sse_client(STDIO_PROXY_URL, httpx_client_factory=http1_factory) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.list_tools()
                return res.tools


async def _proxy_call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    """
    Proxy call_tool to remote MCP server (per-request connection for teardown safety).
    """
    from mcp.client.session import ClientSession
    http1_factory = _create_http1_only_client_factory()

    # Auto-detect transport based on URL path
    if "/mcp" in STDIO_PROXY_URL:
        # Use Streamable HTTP transport
        import httpx
        from mcp.client.streamable_http import streamable_http_client
        async with httpx.AsyncClient(http2=False, timeout=15) as http_client:
            async with streamable_http_client(STDIO_PROXY_URL, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    res = await session.call_tool(name, arguments)
                    return res.content
    else:
        # Use SSE transport (legacy)
        from mcp.client.sse import sse_client
        async with sse_client(STDIO_PROXY_URL, httpx_client_factory=http1_factory) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(name, arguments)
                return res.content


# Initialize managers for state locking, health thresholds, and process management
lock_manager = StateLockManager()
health_checker = HealthThresholds()
process_mgr = ProcessManager()

# Initialize activity tracker for mixed autonomy patterns
from src.activity_tracker import get_activity_tracker, HeartbeatConfig

# ACTIVATED: Lightweight heartbeats enabled for visibility
# Provides activity tracking without heavy governance overhead
HEARTBEAT_CONFIG = HeartbeatConfig(
    conversation_turn_threshold=5,      # Trigger every 5 user prompts (for prompted agents)
    tool_call_threshold=10,             # Trigger every 10 tools (for autonomous agents)
    time_threshold_minutes=15,          # Trigger every 15 min (safety net)
    complexity_threshold=3.0,           # Trigger when cumulative complexity > 3.0
    file_modification_threshold=3,      # Trigger after 3 file writes
    enabled=True,                       # ✅ ENABLED: Lightweight heartbeats active
    track_conversation_turns=True,
    track_tool_calls=True,
    track_complexity=True
)

activity_tracker = get_activity_tracker(HEARTBEAT_CONFIG)
# Don't print here - moved to main() after stdio_server() context

# Store monitors per agent
monitors: dict[str, UNITARESMonitor] = {}


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
    parent_agent_id: str = None  # If spawned from another agent
    spawn_reason: str = None  # Reason for spawning (e.g., "new_domain", "parent_archived")
    api_key: str = None  # API key for authentication (generated on creation)
    # Loop detection tracking
    recent_update_timestamps: list[str] = None  # ISO timestamps of recent updates
    recent_decisions: list[str] = None  # Recent decision actions (approve/reflect/reject)
    loop_detected_at: str = None  # ISO timestamp when loop was detected
    loop_cooldown_until: str = None  # ISO timestamp until which updates are blocked
    # Response completion tracking
    last_response_at: str = None  # ISO timestamp when response completed
    response_completed: bool = False  # Flag for completion detection
    # Cached health status (updated on each process_agent_update)
    health_status: str = "unknown"  # "healthy", "moderate", "critical", "unknown"
    # Dialectic recovery / resumption conditions (persisted)
    # Examples: {"type": "complexity_limit", "value": 0.3, "applied_at": "..."}
    # Stored as structured dicts so handlers can enforce constraints consistently.
    dialectic_conditions: list[dict] = None
    # Session binding persistence (for identity recovery across session key changes)
    active_session_key: str = None
    session_bound_at: str = None
    # Purpose field for documenting agent intent (optional but encouraged)
    purpose: str = None  # Optional description of agent's purpose/intent
    # Internal unguessable identity (server-decided, never changes)
    agent_uuid: str = None  # UUID v4, generated on creation, immutable
    # Structured auto-generated identifier (v2.5.0+)
    # Format: {context}_{date} e.g., "claude_code_20251226" or "cursor_20251226"
    # Auto-generated on creation, stable (unlike display_name which user can change)
    structured_id: str = None
    # Self-chosen display name (optional, agent picks their own name)
    label: str = None  # Optional cosmetic name, set via status(label='...')
    # Agent preferences (verbosity, etc.)
    preferences: dict = None  # {"verbosity": "minimal"|"compact"|"standard"|"full"}

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

    def add_lifecycle_event(self, event: str, reason: str = None):
        """Add a lifecycle event with timestamp"""
        self.lifecycle_events.append({
            "event": event,
            "timestamp": datetime.now().isoformat(),
            "reason": reason
        })
    
    def validate_consistency(self) -> tuple[bool, list[str]]:
        """
        Validate metadata consistency invariants.
        
        Returns:
            (is_valid, list_of_errors)
        """
        errors = []
        
        # Check that recent arrays are consistent with each other
        timestamps_len = len(self.recent_update_timestamps)
        decisions_len = len(self.recent_decisions)
        
        if timestamps_len != decisions_len:
            errors.append(
                f"recent_update_timestamps ({timestamps_len} entries) and "
                f"recent_decisions ({decisions_len} entries) have mismatched lengths"
            )
        
        # Check that total_updates matches tracked arrays (when arrays are not capped)
        # Note: Arrays are capped at 10, so we can only validate if total_updates <= 10
        if self.total_updates <= 10:
            if timestamps_len != self.total_updates:
                errors.append(
                    f"total_updates ({self.total_updates}) does not match "
                    f"recent_update_timestamps length ({timestamps_len})"
                )
        else:
            # For total_updates > 10, arrays should be capped at 10
            if timestamps_len > 10:
                errors.append(
                    f"recent_update_timestamps ({timestamps_len} entries) exceeds cap of 10"
                )
            if decisions_len > 10:
                errors.append(
                    f"recent_decisions ({decisions_len} entries) exceeds cap of 10"
                )
        
        # Validate status consistency
        if self.status == "paused" and not self.paused_at:
            errors.append("status is 'paused' but paused_at is None")
        
        if self.status == "archived" and not self.archived_at:
            # Note: archived_at can be None if agent was auto-resumed
            # This is OK, but log as info-level validation
            pass
        
        # Validate timestamps are ISO format
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


# Store agent metadata
agent_metadata: dict[str, AgentMetadata] = {}

# Lazy loading state (for fast server startup)
_metadata_loading_lock = threading.Lock()
_metadata_loading = False
_metadata_loaded = False

# Metadata cache state (for performance optimization)
_metadata_cache_state = {
    "last_load_time": 0.0,        # When metadata was last loaded from disk
    "last_file_mtime": 0.0,       # File modification time at last load
    "cache_ttl": 60.0,            # Cache valid for 60 seconds
    "dirty": False                # Has in-memory data been modified?
}

# Batched metadata save state (reduces I/O by batching multiple updates)
_metadata_batch_state = {
    "dirty": False,                # True if metadata needs saving
    "save_task": None,             # Background task for batched saves
    "save_lock": None,             # Async lock for save coordination
    "debounce_delay": 0.5,        # Wait 500ms before saving (batch multiple updates)
    "max_batch_delay": 2.0,       # Maximum delay before forcing save (2 seconds)
    "last_save_time": 0,          # Timestamp of last save attempt
    "pending_save": False         # True if save is scheduled
}

# Path to metadata file
METADATA_FILE = Path(project_root) / "data" / "agent_metadata.json"

# Metadata backend: PostgreSQL is now the sole backend.
# JSON snapshot writing is disabled by default.
# To enable JSON snapshots for debugging: UNITARES_METADATA_WRITE_JSON_SNAPSHOT=1
UNITARES_METADATA_BACKEND = os.getenv("UNITARES_METADATA_BACKEND", "postgres").strip().lower()  # json|postgres|auto
# Metadata DB path - uses consolidated governance.db
UNITARES_METADATA_DB_PATH = Path(
    os.getenv("UNITARES_METADATA_DB_PATH", str(Path(project_root) / "data" / "governance.db"))
)
# JSON snapshots disabled by default (PostgreSQL is canonical). Set to "1" to enable for debugging.
UNITARES_METADATA_WRITE_JSON_SNAPSHOT = os.getenv("UNITARES_METADATA_WRITE_JSON_SNAPSHOT", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

_metadata_backend_resolved: str | None = None


def _resolve_metadata_backend() -> str:
    """
    Resolve metadata backend.

    - json: always use METADATA_FILE (legacy)
    - postgres: use PostgreSQL (default)
    - auto: use PostgreSQL
    """
    global _metadata_backend_resolved
    if _metadata_backend_resolved:
        return _metadata_backend_resolved

    backend = UNITARES_METADATA_BACKEND
    if backend == "json":
        _metadata_backend_resolved = backend
        return backend

    # postgres or auto: always postgres
    _metadata_backend_resolved = "postgres"
    return _metadata_backend_resolved


def _write_metadata_snapshot_json_sync() -> None:
    """Write JSON snapshot of in-memory agent_metadata for backward compatibility."""
    if not UNITARES_METADATA_WRITE_JSON_SNAPSHOT:
        return
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    metadata_lock_file = METADATA_FILE.parent / ".metadata.lock"
    lock_fd = os.open(str(metadata_lock_file), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        snapshot = {aid: meta.to_dict() for aid, meta in agent_metadata.items() if isinstance(meta, AgentMetadata)}
        with open(METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(lock_fd)


async def _load_metadata_from_postgres_async() -> dict:
    """
    Load agent metadata from PostgreSQL into AgentMetadata dict.

    This is the PostgreSQL-native loading path that replaces SQLite/JSON.
    Returns dict of agent_id -> AgentMetadata.
    """
    from src import agent_storage

    agents = await agent_storage.list_agents(
        limit=10000,  # High limit to get all agents
        include_archived=True,  # Include for cache completeness
        include_deleted=False,  # Skip deleted
    )

    result = {}
    now = datetime.now().isoformat()

    # Try to populate Redis cache as we load
    metadata_cache = None
    try:
        from src.cache import get_metadata_cache
        metadata_cache = get_metadata_cache()
    except Exception:
        pass  # Cache unavailable, continue without it

    for agent in agents:
        # Convert AgentRecord to AgentMetadata
        meta = AgentMetadata(
            agent_id=agent.agent_id,
            status=agent.status or "active",
            created_at=agent.created_at.isoformat() if agent.created_at else now,
            last_update=agent.updated_at.isoformat() if agent.updated_at else now,
            tags=agent.tags or [],
            notes=agent.notes or "",
            purpose=agent.purpose,
            parent_agent_id=agent.parent_agent_id,
            spawn_reason=agent.spawn_reason,
            health_status=agent.health_status or "unknown",
            # Get from metadata JSONB
            api_key=agent.metadata.get("api_key", ""),
            agent_uuid=agent.metadata.get("agent_uuid"),
            label=agent.metadata.get("label"),
            structured_id=agent.metadata.get("structured_id"),
            preferences=agent.metadata.get("preferences", {}),
            active_session_key=agent.metadata.get("active_session_key"),
            session_bound_at=agent.metadata.get("session_bound_at"),
            dialectic_conditions=agent.metadata.get("dialectic_conditions", []),
            lifecycle_events=agent.metadata.get("lifecycle_events", []),
            recent_update_timestamps=agent.metadata.get("recent_update_timestamps", []),
            recent_decisions=agent.metadata.get("recent_decisions", []),
            total_updates=agent.metadata.get("total_updates", 0),
        )
        result[agent.agent_id] = meta
        
        # Populate Redis cache (best effort, non-blocking)
        if metadata_cache:
            try:
                await metadata_cache.set(agent.agent_id, meta.to_dict(), ttl=300)
            except Exception as e:
                logger.debug(f"Failed to cache metadata for {agent.agent_id[:8]}...: {e}")

    return result


def _load_metadata_from_postgres_sync() -> None:
    """
    Synchronous wrapper to load metadata from PostgreSQL.

    Runs the async function in a new event loop, avoiding conflicts with
    existing connection pools by using asyncio.run_coroutine_threadsafe
    or creating a fresh isolated loop.
    """
    global agent_metadata
    import asyncio

    try:
        # Try to get existing loop
        loop = asyncio.get_running_loop()
        # If we're in an async context, we MUST NOT use asyncio.run() as it
        # creates a new loop and conflicts with existing connection pools.
        # Instead, schedule the coroutine on the existing loop using
        # run_coroutine_threadsafe
        future = asyncio.run_coroutine_threadsafe(
            _load_metadata_from_postgres_async(),
            loop
        )
        result = future.result(timeout=30)
        agent_metadata = result
    except RuntimeError:
        # No running loop - we can use asyncio.run directly
        result = asyncio.run(_load_metadata_from_postgres_async())
        agent_metadata = result


# State file path template (per-agent) - used for JSON backend
def get_state_file(agent_id: str) -> Path:
    """
    Get path to state file for an agent.

    Uses organized structure: data/agents/{agent_id}_state.json

    Provides automatic migration: if file exists in old location (data/ root),
    it will be automatically moved to new location on first access.
    """
    new_path = Path(project_root) / "data" / "agents" / f"{agent_id}_state.json"
    old_path = Path(project_root) / "data" / f"{agent_id}_state.json"

    # Backward compatibility: migrate from old location if it exists
    if not new_path.exists() and old_path.exists():
        try:
            # Ensure agents directory exists
            new_path.parent.mkdir(parents=True, exist_ok=True)
            # Move file from old to new location
            old_path.rename(new_path)
            logger.info(f"Migrated {agent_id} state file to agents/ subdirectory")
        except Exception as e:
            logger.warning(f"Could not migrate {agent_id} state file: {e}", exc_info=True)
            # Fall back to old path if migration fails
            return old_path

    return new_path


def _parse_metadata_dict(data: dict) -> dict:
    """
    Helper function to parse metadata dictionary and create AgentMetadata objects.
    Handles missing fields and validation.
    
    Args:
        data: Dictionary loaded from JSON file
        
    Returns:
        Dictionary mapping agent_id -> AgentMetadata objects
    """
    from dataclasses import fields as dataclass_fields
    allowed_fields = {f.name for f in dataclass_fields(AgentMetadata)}

    parsed_metadata = {}
    for agent_id, meta in data.items():
        # Validate meta is a dict before processing
        if not isinstance(meta, dict):
            logger.warning(f"Metadata for {agent_id} is not a dict (type: {type(meta).__name__}), skipping")
            continue
        
        # Drop unknown keys (forward/backward compatibility across versions).
        # This prevents crashes when metadata contains fields not present on AgentMetadata.
        meta = {k: v for k, v in meta.items() if k in allowed_fields}

        # Set defaults for missing fields (only for fields that exist on AgentMetadata).
        defaults = {
            "parent_agent_id": None,
            "spawn_reason": None,
            "recent_update_timestamps": None,
            "recent_decisions": None,
            "loop_detected_at": None,
            "loop_cooldown_until": None,
            "last_response_at": None,
            "response_completed": False,
            "health_status": "unknown",  # Cached health status for list_agents
            "dialectic_conditions": None,
        }
        for key, default_value in defaults.items():
            if key not in meta:
                meta[key] = default_value
        
        try:
            parsed_metadata[agent_id] = AgentMetadata(**meta)
        except (TypeError, KeyError) as e:
            logger.warning(f"Could not create AgentMetadata for {agent_id}: {e}", exc_info=True)
            continue
    
    return parsed_metadata


def _acquire_metadata_read_lock(timeout: float = 2.0) -> tuple[int, bool]:
    """
    Helper function to acquire shared lock for metadata reads.
    
    Args:
        timeout: Maximum time to wait for lock (seconds)
        
    Returns:
        Tuple of (lock_fd, lock_acquired)
        - lock_fd: File descriptor for lock file (must be closed by caller)
        - lock_acquired: True if lock acquired, False if timeout
    """
    metadata_lock_file = METADATA_FILE.parent / ".metadata.lock"
    lock_fd = os.open(str(metadata_lock_file), os.O_CREAT | os.O_RDWR)
    lock_acquired = False
    start_time = time.time()
    
    try:
        # Try to acquire shared lock with timeout (non-blocking)
        while time.time() - start_time < timeout:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)  # Non-blocking shared lock
                lock_acquired = True
                break
            except IOError:
                # Lock held by another process, wait and retry
                time.sleep(0.05)  # Shorter sleep for reads
        
        if not lock_acquired:
            # Timeout - will read without lock
            logger.warning(f"Metadata lock timeout ({timeout}s) for read, reading without lock")
    except Exception:
        # On any error, mark as not acquired and caller will handle cleanup
        lock_acquired = False
    
    return lock_fd, lock_acquired


async def load_metadata_async(force: bool = False) -> None:
    """
    Async version of load_metadata() for use in async contexts.

    Directly calls the async PostgreSQL loader without sync wrappers.
    Set force=True to reload from DB even if already loaded (picks up external changes).
    """
    global agent_metadata, _metadata_loaded

    # Fast path: already loaded (unless forced)
    if _metadata_loaded and not force:
        return

    # PostgreSQL is the sole backend
    try:
        result = await _load_metadata_from_postgres_async()
        agent_metadata = result
        _metadata_cache_state["last_load_time"] = time.time()
        _metadata_cache_state["dirty"] = False
        _metadata_loaded = True
        logger.debug(f"Loaded {len(agent_metadata)} agents from PostgreSQL (async)")
    except Exception as e:
        logger.error(f"Could not load metadata from PostgreSQL: {e}", exc_info=True)
        raise


def ensure_metadata_loaded() -> None:
    """
    Ensure metadata is loaded (lazy load if needed).
    
    This is a safety net for cases where metadata hasn't been loaded yet.
    Background loading during server startup should handle most cases,
    but this ensures eventual consistency if background load fails.
    
    Thread-safe: Uses lock to prevent concurrent loads.
    """
    global agent_metadata, _metadata_loading, _metadata_loaded
    
    # Fast path: already loaded
    if _metadata_loaded:
        return
    
    # Acquire lock to prevent concurrent loads
    with _metadata_loading_lock:
        # Double-check after acquiring lock
        if _metadata_loaded:
            return
        
        # Check if another thread is loading
        if _metadata_loading:
            # Another thread is loading - wait briefly or return
            # (Background load should complete quickly)
            logger.debug("Metadata loading in progress by another thread, skipping lazy load")
            return
        
        # Mark as loading
        _metadata_loading = True
        
        try:
            # Load metadata synchronously (with timeout protection)
            # This is fallback - background load should handle most cases
            logger.info("Lazy loading metadata (background load may have failed)")
            _load_metadata_from_postgres_sync()
            _metadata_loaded = True
            logger.info(f"Lazy metadata load complete: {len(agent_metadata)} agents")
        except Exception as e:
            logger.warning(f"Lazy metadata load failed: {e}. Continuing with empty metadata.")
            # Continue with empty dict - tools will handle gracefully
            _metadata_loaded = False  # Allow retry on next access
        finally:
            _metadata_loading = False


def ensure_metadata_loaded() -> None:
    """
    Ensure metadata is loaded (lazy load if needed).
    
    This is a safety net for cases where metadata hasn't been loaded yet.
    Background loading during server startup should handle most cases,
    but this ensures eventual consistency if background load fails.
    
    Thread-safe: Uses lock to prevent concurrent loads.
    """
    global agent_metadata, _metadata_loading, _metadata_loaded
    
    # Fast path: already loaded
    if _metadata_loaded:
        return
    
    # Acquire lock to prevent concurrent loads
    with _metadata_loading_lock:
        # Double-check after acquiring lock
        if _metadata_loaded:
            return
        
        # Check if another thread is loading
        if _metadata_loading:
            # Another thread is loading - wait briefly or return
            # (Background load should complete quickly)
            logger.debug("Metadata loading in progress by another thread, skipping lazy load")
            return
        
        # Mark as loading
        _metadata_loading = True
        
        try:
            # Load metadata synchronously (with timeout protection)
            # This is fallback - background load should handle most cases
            logger.info("Lazy loading metadata (background load may have failed)")
            _load_metadata_from_postgres_sync()
            _metadata_loaded = True
            logger.info(f"Lazy metadata load complete: {len(agent_metadata)} agents")
        except Exception as e:
            logger.warning(f"Lazy metadata load failed: {e}. Continuing with empty metadata.")
            # Continue with empty dict - tools will handle gracefully
            _metadata_loaded = False  # Allow retry on next access
        finally:
            _metadata_loading = False


def _load_metadata_sync_only() -> None:
    """
    Synchronous metadata loading for SQLite/JSON backends only.
    For PostgreSQL, use load_metadata_async() instead.
    """
    global agent_metadata

    backend = _resolve_metadata_backend()

    # JSON backend fallback (legacy)
    lock_fd = None
    lock_acquired = False
    try:
        lock_fd, lock_acquired = _acquire_metadata_lock(write=False, timeout=5.0)
        if METADATA_FILE.exists():
            with open(METADATA_FILE, "r") as f:
                data = json.load(f)
            agent_metadata = _parse_metadata_dict(data)
            _metadata_cache_state["last_load_time"] = time.time()
            try:
                _metadata_cache_state["last_file_mtime"] = METADATA_FILE.stat().st_mtime
            except:
                pass
            _metadata_cache_state["dirty"] = False
        else:
            # No metadata file yet - start with empty dict
            agent_metadata = {}
    finally:
        if lock_fd:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            except:
                pass


def load_metadata() -> None:
    """
    Load agent metadata from storage with caching.

    PostgreSQL is the single source of truth.

    Cache behavior:
    - If cache is fresh (< 60s old) and source hasn't changed: use cached data
    - If cache is dirty (modified in memory): don't reload
    - Otherwise: reload from source

    WARNING: PostgreSQL backend requires async loading. This sync version
    uses in-memory cache if available; use load_metadata_async() in async functions.
    """
    global agent_metadata

    # PostgreSQL backend: sync loading is problematic (event loop conflicts).
    # Just use in-memory cache if available; async context will load properly.
    if agent_metadata:
        logger.debug(f"Using in-memory metadata cache ({len(agent_metadata)} agents)")
        return
    # PostgreSQL backend requires async loading - raise error if sync is called
    raise RuntimeError("PostgreSQL backend requires async load_metadata_async(). Sync load_metadata() is not supported.")


async def schedule_metadata_save(force: bool = False) -> None:
    """
    DEPRECATED: No-op function. PostgreSQL is now the single source of truth.

    As of v2.4.0, all persistence goes through agent_storage module to PostgreSQL.
    This function is kept for backwards compatibility with callers that haven't
    been updated yet.

    Args:
        force: Ignored - no persistence occurs
    """
    # No-op - PostgreSQL writes happen directly via agent_storage
    pass


async def _batched_metadata_save() -> None:
    """DEPRECATED: No-op. PostgreSQL is now the single source of truth."""
    pass


async def flush_metadata_save() -> None:
    """DEPRECATED: No-op. PostgreSQL is now the single source of truth."""
    pass


def _schedule_metadata_save_sync(force: bool = False) -> None:
    """DEPRECATED: No-op. PostgreSQL is now the single source of truth."""
    pass


async def save_metadata_async() -> None:
    """DEPRECATED: No-op. PostgreSQL is now the single source of truth."""
    pass

def save_metadata() -> None:
    """
    DEPRECATED: No-op function. PostgreSQL is now the single source of truth.

    As of v2.4.0, all persistence goes through agent_storage module to PostgreSQL.
    This function is kept for backwards compatibility with callers that haven't
    been updated yet.
    """
    # No-op - PostgreSQL writes happen directly via agent_storage
    pass


def _legacy_save_metadata() -> None:
    """
    Legacy save_metadata implementation - kept for reference only.
    NOT CALLED - all persistence now goes through agent_storage.
    """
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Use a global metadata lock to prevent concurrent writes
    # This is separate from per-agent locks and protects the shared metadata file
    metadata_lock_file = METADATA_FILE.parent / ".metadata.lock"
    
    try:
        # Acquire exclusive lock on metadata file with timeout (prevents hangs)
        lock_fd = None
        try:
            lock_fd = os.open(str(metadata_lock_file), os.O_CREAT | os.O_RDWR)
        except (OSError, IOError) as open_error:
            logger.warning(f"Could not open metadata lock file: {open_error}", exc_info=True)
            # Fallback: try without lock (not ideal but better than failing silently)
            with open(METADATA_FILE, 'w') as f:
                data = {
                    agent_id: meta.to_dict()
                    for agent_id, meta in sorted(agent_metadata.items())
                    if isinstance(meta, AgentMetadata)
                }
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            return
        
        lock_acquired = False
        start_time = time.time()
        timeout = 5.0  # 5 second timeout (same as agent lock)

        try:
            # Try to acquire lock with timeout (non-blocking)
            while time.time() - start_time < timeout:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    break
                except IOError:
                    # Lock held by another process, wait and retry
                    time.sleep(0.1)

            if not lock_acquired:
                # Timeout reached - log warning but use fallback
                logger.warning(f"Metadata lock timeout ({timeout}s)")
                raise TimeoutError("Metadata lock timeout")

            # Reload metadata to get latest state from disk (in case another process updated it)
            # Then merge with our in-memory changes (in-memory takes precedence)
            merged_metadata = {}
            if METADATA_FILE.exists():
                try:
                    with open(METADATA_FILE, 'r') as f:
                        existing_data = json.load(f)
                        # Start with what's on disk
                        for agent_id, meta_dict in existing_data.items():
                            # FIXED: Validate meta_dict is actually a dict before creating AgentMetadata
                            # Prevents strings from being stored in agent_metadata
                            if isinstance(meta_dict, dict):
                                try:
                                    merged_metadata[agent_id] = AgentMetadata(**meta_dict)
                                except (TypeError, KeyError) as e:
                                    # Invalid metadata structure - skip this agent
                                    logger.warning(f"Invalid metadata for {agent_id}: {e}", exc_info=True)
                                    continue
                            else:
                                # meta_dict is not a dict (could be string from corrupted file)
                                logger.warning(f"Metadata for {agent_id} is not a dict (type: {type(meta_dict).__name__}), skipping")
                                continue
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    # If file is corrupted, start fresh
                    logger.warning(f"Could not load metadata file: {e}", exc_info=True)
                    pass
            
            # Overwrite with in-memory state (our changes take precedence)
            # FIXED: Validate that in-memory entries are AgentMetadata objects, not strings
            for agent_id, meta in agent_metadata.items():
                if isinstance(meta, AgentMetadata):
                    # Validate consistency before saving
                    is_valid, errors = meta.validate_consistency()
                    if not is_valid:
                        logger.warning(
                            f"Metadata consistency validation failed for agent '{agent_id}': {errors}. "
                            f"Fixing inconsistencies..."
                        )
                        # Auto-fix: Ensure arrays match
                        if len(meta.recent_update_timestamps) != len(meta.recent_decisions):
                            # Truncate longer array to match shorter one (data loss, but prevents corruption)
                            min_len = min(len(meta.recent_update_timestamps), len(meta.recent_decisions))
                            meta.recent_update_timestamps = meta.recent_update_timestamps[:min_len]
                            meta.recent_decisions = meta.recent_decisions[:min_len]
                            logger.info(f"Fixed array length mismatch for '{agent_id}' (truncated to {min_len} entries)")
                        
                        # Auto-fix: If total_updates doesn't match arrays (and arrays aren't capped), adjust
                        if meta.total_updates <= 10 and len(meta.recent_update_timestamps) != meta.total_updates:
                            # Set total_updates to match actual tracked updates
                            meta.total_updates = len(meta.recent_update_timestamps)
                            logger.info(f"Fixed total_updates mismatch for '{agent_id}' (set to {meta.total_updates})")
                    
                    merged_metadata[agent_id] = meta
                else:
                    # Invalid type in memory - log warning but skip (don't overwrite valid disk data)
                    logger.warning(f"In-memory metadata for {agent_id} is not AgentMetadata (type: {type(meta).__name__}), skipping")
                    # If not in merged_metadata from disk, create fresh entry
                    if agent_id not in merged_metadata:
                        logger.info(f"Creating fresh metadata for {agent_id} due to invalid in-memory state")
                        merged_metadata[agent_id] = get_or_create_metadata(agent_id)
            
            # Write merged state
            with open(METADATA_FILE, 'w') as f:
                # Sort by agent_id for consistent file output
                data = {
                    agent_id: meta.to_dict()
                    for agent_id, meta in sorted(merged_metadata.items())
                }
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Ensure written to disk
            
            # Update in-memory state with merged result (includes any new agents from disk)
            agent_metadata.update(merged_metadata)

            # Update cache state after successful write
            _metadata_cache_state["last_load_time"] = time.time()
            _metadata_cache_state["last_file_mtime"] = METADATA_FILE.stat().st_mtime
            _metadata_cache_state["dirty"] = False

        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except (IOError, OSError):
                    pass
                try:
                    os.close(lock_fd)
                except (OSError, ValueError):
                    pass
    except Exception as e:
        logger.warning(f"Could not acquire metadata lock: {e}", exc_info=True)
        # Fallback: try without lock (not ideal but better than failing silently)
        with open(METADATA_FILE, 'w') as f:
            data = {
                agent_id: meta.to_dict()
                for agent_id, meta in sorted(agent_metadata.items())
            }
            json.dump(data, f, indent=2)

        # Update cache state after fallback write
        _metadata_cache_state["last_load_time"] = time.time()
        _metadata_cache_state["last_file_mtime"] = METADATA_FILE.stat().st_mtime
        _metadata_cache_state["dirty"] = False


def get_or_create_metadata(agent_id: str, **kwargs) -> AgentMetadata:
    """
    Get metadata for agent, creating if needed.
    
    Args:
        agent_id: Agent identifier (human-readable label, can be renamed)
        **kwargs: Optional fields to set on creation (e.g., purpose, notes, tags)
    """
    # Ensure metadata is loaded before accessing (lazy load if needed)
    ensure_metadata_loaded()
    
    if agent_id not in agent_metadata:
        now = datetime.now().isoformat()
        # Generate API key for new agent (authentication)
        api_key = generate_api_key()
        # Generate unguessable internal identity (UUID v4)
        import uuid
        import re
        # If agent_id is already a UUID, reuse it as agent_uuid (prevents mismatch)
        UUID4_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', re.I)
        if UUID4_PATTERN.match(agent_id):
            agent_uuid = agent_id  # Reuse existing UUID
        else:
            agent_uuid = str(uuid.uuid4())  # Generate new one for human-readable names
        metadata = AgentMetadata(
            agent_id=agent_id,
            status="active",
            created_at=now,
            last_update=now,
            api_key=api_key,  # Generate key on creation
            agent_uuid=agent_uuid  # Internal unguessable identity
        )
        # Add creation lifecycle event
        metadata.add_lifecycle_event("created")

        # Special handling for default agent
        if agent_id == "default_agent":
            metadata.tags.append("pioneer")
            metadata.notes = "First agent - pioneer of the governance system"

        # Set any additional fields provided via kwargs (e.g., purpose)
        for key, value in kwargs.items():
            if hasattr(metadata, key) and value is not None:
                setattr(metadata, key, value)

        agent_metadata[agent_id] = metadata

        # SECURITY FIX: Force immediate save for agent creation (critical operation)
        # Note: PostgreSQL persistence happens in get_or_create_metadata via agent_storage
        # No additional save needed here - agent_storage writes directly to PostgreSQL

        # Print API key for new agent (one-time display)
        logger.info(f"Created new agent '{agent_id}'")
        logger.info(f"API Key: {api_key}")
        logger.warning("⚠️  Save this key - you'll need it for future updates!")
    return agent_metadata[agent_id]


# Alias for cleaner naming (backward compatible)
register_agent = get_or_create_metadata


def _write_state_file(state_file: Path, state_data: dict) -> None:
    """Helper function to write state file (used by both sync and async versions)"""
    with open(state_file, 'w') as f:
        json.dump(state_data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())  # Ensure written to disk


async def save_monitor_state_async(agent_id: str, monitor: UNITARESMonitor) -> None:
    """
    Async version of save_monitor_state - uses file-based storage.

    Uses async file locking to avoid blocking the event loop.
    """
    state_data = monitor.state.to_dict_with_history()

    # JSON file backend
    state_file = get_state_file(agent_id)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Use a per-agent state lock to prevent concurrent writes
    state_lock_file = state_file.parent / f".{agent_id}_state.lock"
    
    lock_fd = None
    try:
        # Acquire exclusive lock on state file with timeout (async, non-blocking)
        lock_fd = os.open(str(state_lock_file), os.O_CREAT | os.O_RDWR)
        lock_acquired = False
        start_time = time.time()
        timeout = 5.0  # 5 second timeout

        try:
            # Try to acquire lock with timeout (non-blocking, uses asyncio.sleep)
            while time.time() - start_time < timeout:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    break
                except IOError:
                    # Lock held by another process, wait and retry (NON-BLOCKING)
                    await asyncio.sleep(0.1)  # Use asyncio.sleep instead of time.sleep

            if not lock_acquired:
                # Timeout reached - log warning but use fallback
                logger.warning(f"State lock timeout for {agent_id} ({timeout}s)")
                raise TimeoutError("State lock timeout")

            # Write state (run in executor to avoid blocking event loop)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _write_state_file, state_file, state_data)
            
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except (IOError, OSError):
                    pass
                try:
                    os.close(lock_fd)
                except (OSError, ValueError):
                    pass
    except Exception as e:
        logger.warning(f"Could not acquire state lock for {agent_id}: {e}", exc_info=True)
        # Fallback: try without lock (not ideal but better than failing silently)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _write_state_file, state_file, state_data)
        except Exception as fallback_error:
            logger.error(f"Failed to save state even without lock for {agent_id}: {fallback_error}", exc_info=True)


def save_monitor_state(agent_id: str, monitor: UNITARESMonitor) -> None:
    """Save monitor state to file with locking to prevent race conditions."""
    state_data = monitor.state.to_dict_with_history()

    # JSON file backend
    state_file = get_state_file(agent_id)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Use a per-agent state lock to prevent concurrent writes
    state_lock_file = state_file.parent / f".{agent_id}_state.lock"
    
    lock_fd = None
    try:
        # Acquire exclusive lock on state file with timeout
        lock_fd = os.open(str(state_lock_file), os.O_CREAT | os.O_RDWR)
        lock_acquired = False
        start_time = time.time()
        timeout = 5.0  # 5 second timeout

        try:
            # Try to acquire lock with timeout (non-blocking)
            while time.time() - start_time < timeout:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    break
                except IOError:
                    # Lock held by another process, wait and retry
                    time.sleep(0.1)

            if not lock_acquired:
                # Timeout reached - log warning but use fallback
                logger.warning(f"State lock timeout for {agent_id} ({timeout}s)")
                raise TimeoutError("State lock timeout")

            # Write state (use shared helper function)
            _write_state_file(state_file, state_data)
            
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except (IOError, OSError):
                    pass
                try:
                    os.close(lock_fd)
                except (OSError, ValueError):
                    pass
    except Exception as e:
        logger.warning(f"Could not acquire state lock for {agent_id}: {e}", exc_info=True)
        # Fallback: try without lock (not ideal but better than failing silently)
        try:
            _write_state_file(state_file, state_data)
        except Exception as e2:
            logger.error(f"Could not save state for {agent_id}: {e2}", exc_info=True)


def load_monitor_state(agent_id: str) -> 'GovernanceState | None':
    """Load monitor state from file if it exists."""
    from src.governance_state import GovernanceState

    # JSON file backend
    state_file = get_state_file(agent_id)

    if not state_file.exists():
        return None

    try:
        # Read-only access, no lock needed
        with open(state_file, 'r') as f:
            data = json.load(f)
            state = GovernanceState.from_dict(data)
            return state
    except Exception as e:
        logger.warning(f"Could not load state for {agent_id}: {e}", exc_info=True)
        return None


# CRITICAL FIX: Don't load metadata at import time - defer to first use or background task
# This prevents blocking startup. Metadata will be loaded lazily when needed.
# load_metadata()  # REMOVED: Was blocking startup


async def auto_archive_old_test_agents(max_age_hours: float = 6.0) -> int:
    """
    Automatically archive old test/demo agents that haven't been updated recently.
    
    Test/ping agents (1-2 updates) are archived immediately.
    Other test agents are archived after inactivity threshold.
    
    Args:
        max_age_hours: Archive agents older than this many hours (default: 6)
    
    Returns:
        Number of agents archived
    """
    archived_count = 0
    current_time = datetime.now()
    
    for agent_id, meta in list(agent_metadata.items()):
        # Skip if already archived or deleted
        if meta.status in ["archived", "deleted"]:
            continue
        
        # Only archive test/demo agents
        is_test_agent = (
            agent_id.startswith("test_") or 
            agent_id.startswith("demo_") or
            agent_id.startswith("test") or
            "test" in agent_id.lower() or
            "demo" in agent_id.lower()
        )
        
        if not is_test_agent:
            continue
        
        # Archive immediately if very low update count (1-2 updates = just a ping/test)
        if meta.total_updates <= 2:
            meta.status = "archived"
            meta.archived_at = current_time.isoformat()
            meta.add_lifecycle_event(
                "archived",
                f"Auto-archived: test/ping agent with {meta.total_updates} update(s)"
            )
            archived_count += 1
            logger.info(f"Auto-archived test/ping agent: {agent_id} ({meta.total_updates} updates)")
            continue
        
        # Check age for agents with more updates
        try:
            last_update_dt = datetime.fromisoformat(meta.last_update.replace('Z', '+00:00') if 'Z' in meta.last_update else meta.last_update)
            age_delta = (current_time.replace(tzinfo=last_update_dt.tzinfo) if last_update_dt.tzinfo else current_time) - last_update_dt
            age_hours = age_delta.total_seconds() / 3600
        except (ValueError, TypeError, AttributeError):
            # If we can't parse date, skip
            continue
        
        # Archive if old enough
        if age_hours >= max_age_hours:
            meta.status = "archived"
            meta.archived_at = current_time.isoformat()
            meta.add_lifecycle_event(
                "archived",
                f"Auto-archived: inactive test/demo agent ({age_hours:.1f} hours old, threshold: {max_age_hours} hours)"
            )
            archived_count += 1
            logger.info(f"Auto-archived old test agent: {agent_id} ({age_hours:.1f} hours old)")
    
    # Note: Archive operations persist directly to PostgreSQL via agent_storage
    # No additional save needed here

    return archived_count


async def auto_archive_orphan_agents(
    zero_update_hours: float = 1.0,
    low_update_hours: float = 3.0,
    unlabeled_hours: float = 6.0
) -> int:
    """
    Aggressively archive orphan agents to prevent proliferation.

    Targets:
    - UUID-named agents with 0 updates after zero_update_hours (default: 1h)
    - Any unlabeled agent with 0-1 updates after low_update_hours (default: 3h)
    - Unlabeled UUID agents with 2+ updates after unlabeled_hours (default: 6h)

    Preserves:
    - Agents with labels/display names (user gave them a name)
    - Agents with "pioneer" tag
    - Recently active agents

    Returns:
        Number of agents archived
    """
    import re
    UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

    archived_count = 0
    current_time = datetime.now()

    for agent_id, meta in list(agent_metadata.items()):
        # Skip if already archived or deleted
        if meta.status in ["archived", "deleted"]:
            continue

        # Never archive pioneers
        if "pioneer" in (meta.tags or []):
            continue

        # Check if agent has a meaningful label
        has_label = bool(getattr(meta, 'label', None) or getattr(meta, 'display_name', None))
        is_uuid_named = bool(UUID_PATTERN.match(agent_id))

        # Calculate age
        try:
            last_update_str = meta.last_update or meta.created_at
            last_update_dt = datetime.fromisoformat(
                last_update_str.replace('Z', '+00:00') if 'Z' in last_update_str else last_update_str
            )
            # Handle timezone-aware vs naive comparison
            if last_update_dt.tzinfo:
                age_delta = datetime.now(last_update_dt.tzinfo) - last_update_dt
            else:
                age_delta = current_time - last_update_dt
            age_hours = age_delta.total_seconds() / 3600
        except (ValueError, TypeError, AttributeError):
            continue

        updates = getattr(meta, 'total_updates', 0) or 0
        should_archive = False
        reason = ""

        # Rule 1: UUID-named, 0 updates, older than zero_update_hours
        if is_uuid_named and updates == 0 and age_hours >= zero_update_hours:
            should_archive = True
            reason = f"orphan UUID agent, 0 updates, {age_hours:.1f}h old"

        # Rule 2: Unlabeled, 0-1 updates, older than low_update_hours
        elif not has_label and updates <= 1 and age_hours >= low_update_hours:
            should_archive = True
            reason = f"unlabeled agent, {updates} updates, {age_hours:.1f}h old"

        # Rule 3: UUID-named + unlabeled, 2+ updates but very old
        elif is_uuid_named and not has_label and updates >= 2 and age_hours >= unlabeled_hours:
            should_archive = True
            reason = f"stale UUID agent, {updates} updates, {age_hours:.1f}h old"

        if should_archive:
            meta.status = "archived"
            meta.archived_at = current_time.isoformat()
            meta.add_lifecycle_event("archived", f"Auto-archived: {reason}")
            archived_count += 1
            logger.info(f"Auto-archived orphan agent: {agent_id[:12]}... ({reason})")

    return archived_count


# DEFERRED: Auto-archive moved to background task (was blocking startup)
# try:
#     archived = auto_archive_old_test_agents(max_age_hours=6.0)
#     if archived > 0:
#         print(f"[UNITARES MCP] Auto-archived {archived} old test/demo agents on startup", file=sys.stderr)
# except Exception as e:
#     print(f"[UNITARES MCP] Warning: Could not auto-archive old test agents: {e}", file=sys.stderr)

# DEFERRED: Lock cleanup moved to background task (was blocking startup)
# try:
#     result = cleanup_stale_state_locks(project_root, max_age_seconds=300, dry_run=False)
#     if result['cleaned'] > 0:
#         print(f"[UNITARES MCP] Cleaned {result['cleaned']} stale lock files on startup", file=sys.stderr)
# except Exception as e:
#     print(f"[UNITARES MCP] Warning: Could not clean up stale locks: {e}", file=sys.stderr)


def cleanup_stale_processes():
    """Clean up stale MCP server processes on startup - only if we have too many"""
    if not PSUTIL_AVAILABLE:
        logger.info("Skipping stale process cleanup (psutil not available)")
        return
    
    try:
        # Find all mcp_server_std.py processes
        current_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and any('mcp_server_std.py' in str(arg) for arg in cmdline):
                    pid = proc.info['pid']
                    if pid != CURRENT_PID:  # Don't kill ourselves
                        create_time = proc.info.get('create_time', 0)
                        age_seconds = time.time() - create_time
                        # Check for heartbeat file to see if process is active
                        heartbeat_file = Path(project_root) / "data" / "processes" / f"heartbeat_{pid}.txt"
                        has_recent_heartbeat = False
                        if heartbeat_file.exists():
                            try:
                                with open(heartbeat_file, 'r') as f:
                                    last_heartbeat = float(f.read())
                                heartbeat_age = time.time() - last_heartbeat
                                has_recent_heartbeat = heartbeat_age < 300  # 5 minutes
                            except (ValueError, IOError):
                                pass
                        
                        current_processes.append({
                            'pid': pid,
                            'create_time': create_time,
                            'age_seconds': age_seconds,
                            'has_recent_heartbeat': has_recent_heartbeat
                        })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Clean up stale processes more aggressively:
        # 1. Always clean up processes without recent heartbeats (even if under limit)
        # 2. If over limit, clean up oldest processes first
        
        # Sort by creation time (oldest first)
        current_processes.sort(key=lambda x: x['create_time'])
        
        # Identify stale processes:
        # - Processes older than 5 minutes without recent heartbeat (always clean these)
        # - If over limit, also clean oldest processes beyond the limit
        stale_processes = []
        
        # Always clean processes without heartbeats (zombies)
        for proc_info in current_processes:
            if proc_info['age_seconds'] > 300 and not proc_info['has_recent_heartbeat']:
                stale_processes.append(proc_info)
        
        # Track PIDs we're already cleaning up (for deduplication)
        stale_pids = {p['pid'] for p in stale_processes}
        
        # If over limit, also mark oldest processes for cleanup
        if len(current_processes) > MAX_KEEP_PROCESSES:
            # Keep only the most recent MAX_KEEP_PROCESSES
            processes_to_remove = current_processes[:-MAX_KEEP_PROCESSES]
            for proc_info in processes_to_remove:
                # Only add if not already marked for cleanup
                if proc_info['pid'] not in stale_pids:
                    stale_processes.append(proc_info)
                    stale_pids.add(proc_info['pid'])
        
        # Use stale_processes directly (already deduplicated by PID)
        unique_stale_processes = stale_processes
        
        if unique_stale_processes:
            logger.info(f"Found {len(current_processes)} server processes, cleaning up {len(unique_stale_processes)} stale ones (keeping {MAX_KEEP_PROCESSES} most recent)...")
            
            for proc_info in unique_stale_processes:
                try:
                    proc = psutil.Process(proc_info['pid'])
                    age_minutes = int(proc_info['age_seconds'] / 60)
                    reason = "no heartbeat" if not proc_info['has_recent_heartbeat'] else "over limit"
                    logger.info(f"Killing stale process PID {proc_info['pid']} (age: {age_minutes}m, reason: {reason})")
                    proc.terminate()
                    # Give it a moment to clean up
                    try:
                        proc.wait(timeout=2)
                    except psutil.TimeoutExpired:
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.warning(f"Could not kill PID {proc_info['pid']}: {e}", exc_info=True)
    except Exception as e:
        logger.warning(f"Could not clean stale processes: {e}", exc_info=True)


def write_pid_file():
    """Write PID file for process tracking"""
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PID_FILE, 'w') as f:
            # PID file should ONLY contain the process ID (one line)
            # Other code expects to read just the PID, not version/timestamp
            f.write(f"{CURRENT_PID}\n")
    except Exception as e:
        logger.warning(f"Could not write PID file: {e}", exc_info=True)


def remove_pid_file():
    """Remove PID file on shutdown"""
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception as e:
        logger.warning(f"Could not remove PID file: {e}", exc_info=True)


# Global flag for graceful shutdown
_shutdown_requested = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global _shutdown_requested
    _shutdown_requested = True


# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Register cleanup on exit
atexit.register(remove_pid_file)

# CRITICAL FIX: Move heavy startup operations to background to prevent Claude Desktop timeouts
# Claude Desktop has strict timeout for server initialization - we must respond quickly
# Heavy operations (process scanning, cleanup) are deferred to background tasks

# Write heartbeat immediately (fast operation)
process_mgr.write_heartbeat()

# Write PID file (fast operation)
write_pid_file()

# Track server start time for loop detection grace period
# Allows agents to reconnect/recover after server restarts without triggering false positives
SERVER_START_TIME = datetime.now()

# DEFERRED: Heavy cleanup operations moved to background task in main()
# This prevents blocking startup and allows server to respond quickly to Claude Desktop
# - cleanup_zombies() scans all processes (can be slow)
# - cleanup_stale_state_locks() scans file system (can be slow)
# - cleanup_stale_processes() scans processes (can be slow)


def get_or_create_monitor(agent_id: str) -> UNITARESMonitor:
    """Get existing monitor or create new one with metadata, loading state if it exists"""
    # Ensure metadata exists
    get_or_create_metadata(agent_id)

    # Create monitor if needed
    if agent_id not in monitors:
        monitor = UNITARESMonitor(agent_id)
        
        # Try to load persisted state from disk
        persisted_state = load_monitor_state(agent_id)
        if persisted_state is not None:
            monitor.state = persisted_state
            logger.info(f"Loaded persisted state for {agent_id} ({len(persisted_state.V_history)} history entries)")
        else:
            logger.info(f"Initialized new monitor for {agent_id}")
        
        monitors[agent_id] = monitor
    
    return monitors[agent_id]


def check_agent_status(agent_id: str) -> str | None:
    """Check if agent status allows operations, return error if not"""
    if agent_id in agent_metadata:
        meta = agent_metadata[agent_id]
        if meta.status == "paused":
            return f"Agent '{agent_id}' is paused. Resume it first before processing updates."
        elif meta.status == "archived":
            return f"Agent '{agent_id}' is archived. It must be restored before processing updates."
        elif meta.status == "deleted":
            return f"Agent '{agent_id}' is deleted and cannot be used."
    return None


def check_agent_id_default(agent_id: str) -> str | None:
    """Check if using default agent_id and return warning if so"""
    if not agent_id or agent_id == "default_agent":
        return "⚠️ Using default agent_id. For multi-agent systems, specify explicit agent_id to avoid state mixing."
    return None


def _detect_ci_status() -> bool:
    """
    Auto-detect CI pass status from environment variables.
    
    Checks common CI environment variables:
    - CI=true + CI_STATUS=passed (custom)
    - GITHUB_ACTIONS + GITHUB_WORKFLOW_STATUS=success (GitHub Actions)
    - TRAVIS=true + TRAVIS_TEST_RESULT=0 (Travis CI)
    - CIRCLE_CI=true + CIRCLE_BUILD_STATUS=success (CircleCI)
    - GITLAB_CI=true + CI_JOB_STATUS=success (GitLab CI)
    
    Returns:
        bool: True if CI passed, False otherwise (conservative default)
    """
    # Check if we're in a CI environment
    ci_env = os.environ.get("CI", "").lower()
    if ci_env not in ("true", "1", "yes"):
        return False  # Not in CI, default to False (conservative)
    
    # Check custom CI_STATUS
    ci_status = os.environ.get("CI_STATUS", "").lower()
    if ci_status in ("passed", "success", "ok", "true", "1"):
        return True
    
    # GitHub Actions
    if os.environ.get("GITHUB_ACTIONS") == "true":
        workflow_status = os.environ.get("GITHUB_WORKFLOW_STATUS", "").lower()
        if workflow_status == "success":
            return True
    
    # Travis CI
    if os.environ.get("TRAVIS") == "true":
        test_result = os.environ.get("TRAVIS_TEST_RESULT", "")
        if test_result == "0":
            return True
    
    # CircleCI
    if os.environ.get("CIRCLE_CI") == "true":
        build_status = os.environ.get("CIRCLE_BUILD_STATUS", "").lower()
        if build_status == "success":
            return True
    
    # GitLab CI
    if os.environ.get("GITLAB_CI") == "true":
        job_status = os.environ.get("CI_JOB_STATUS", "").lower()
        if job_status == "success":
            return True
    
    # Default: CI detected but status unknown -> False (conservative)
    return False


def validate_agent_id_format(agent_id: str) -> tuple[bool, str, str]:
    """
    Validate agent_id follows recommended patterns.
    
    Returns:
        (is_valid, error_message, suggestion)
    """
    from datetime import datetime, timedelta
    import re
    
    # Generic IDs that should be rejected
    generic_ids = {
        "test", "demo", "default_agent", "agent", "monitor"
    }
    
    if agent_id.lower() in generic_ids:
        suggestion = f"{agent_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return False, f"Generic ID '{agent_id}' is not allowed. Use a specific identifier.", suggestion
    
    # Check for generic patterns without uniqueness
    if agent_id in ["claude_code_cli", "claude_chat", "composer", "cursor_ide"]:
        suggestion = f"{agent_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return False, f"ID '{agent_id}' is too generic and may cause collisions. Add a session identifier.", suggestion
    
    # Test agents should include timestamp
    if agent_id.startswith("test_") and len(agent_id.split("_")) < 3:
        suggestion = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return False, f"Test IDs should include timestamp for uniqueness (e.g., 'test_20251124_143022').", suggestion
    
    # Demo agents should include timestamp
    if agent_id.startswith("demo_") and len(agent_id.split("_")) < 3:
        suggestion = f"demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return False, f"Demo IDs should include timestamp for uniqueness (e.g., 'demo_20251124_143022').", suggestion
    
    # Check length (too short might be generic)
    if len(agent_id) < 3:
        return False, f"Agent ID '{agent_id}' is too short. Use at least 3 characters.", ""
    
    # Check for invalid characters (allow alphanumeric, underscore, hyphen)
    if not re.match(r'^[a-zA-Z0-9_-]+$', agent_id):
        return False, f"Agent ID '{agent_id}' contains invalid characters. Use only letters, numbers, underscores, and hyphens.", ""
    
    return True, "", ""


def require_agent_id(arguments: dict, reject_existing: bool = False) -> tuple[str | None, TextContent | None]:
    """
    Require explicit agent_id, validate format, return error if missing or invalid.
    
    Args:
        arguments: Tool arguments dict containing 'agent_id'
        reject_existing: If True, reject agent_ids that already exist (for new agent creation).
                        If False, allow existing agent_ids (for updates).
    
    Returns:
        (agent_id, None) if valid, (None, TextContent error) if invalid
    """
    agent_id = arguments.get("agent_id")
    if not agent_id:
        error_msg = json.dumps({
            "success": False,
            "error": "agent_id is required. Each agent must have a UNIQUE identifier to prevent state mixing.",
            "details": "Use a unique session/purpose identifier (e.g., 'cursor_ide_session_001', 'claude_code_cli_20251124', 'debugging_session_20251124').",
            "why_unique": "Each agent_id is a unique identity. Using another agent's ID is identity theft - you would impersonate them, corrupt their history, and erase their governance record.",
            "examples": [
                "cursor_ide_session_001",
                "claude_code_cli_20251124",
                "debugging_session_20251124",
                "production_agent_v2"
            ],
            "suggestion": "\"agent_id\": \"your_unique_session_id\"",
            "recovery": {
                "action": "Provide a unique agent_id in your request",
                "related_tools": ["get_agent_api_key", "list_agents"],
                "workflow": "1. Generate unique agent_id (e.g., timestamp-based) 2. Call get_agent_api_key to get/create agent 3. Use agent_id and api_key in subsequent calls"
            }
        }, indent=2)
        return None, TextContent(type="text", text=error_msg)
    
    # Check if agent_id already exists (identity collision) - only when creating new agents
    if reject_existing and agent_id in agent_metadata:
        existing_meta = agent_metadata[agent_id]
        from datetime import datetime, timedelta
        try:
            created_dt = datetime.fromisoformat(existing_meta.created_at.replace('Z', '+00:00') if 'Z' in existing_meta.created_at else existing_meta.created_at)
            created_str = created_dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError, AttributeError):
            created_str = existing_meta.created_at
        
        error_msg = json.dumps({
            "success": False,
            "error": "Identity collision: This agent_id already exists",
            "details": f"'{agent_id}' is an existing agent identity (created {created_str}, {existing_meta.total_updates} updates)",
            "why_this_matters": "Using another agent's ID is identity theft. You would impersonate them and corrupt their governance history.",
            "suggestion": f"Create a unique agent_id for yourself (e.g., 'your_name_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}')",
            "help": "Use list_agents to see existing agent IDs and avoid collisions"
        }, indent=2)
        return None, TextContent(type="text", text=error_msg)
    
    # Validate format (but allow existing agents to pass - backward compatibility)
    # Only validate for new agents (not in metadata yet)
    if agent_id not in agent_metadata:
        is_valid, error_message, suggestion = validate_agent_id_format(agent_id)
        if not is_valid:
            error_data = {
                "success": False,
                "error": error_message,
                "agent_id_provided": agent_id
            }
            if suggestion:
                error_data["suggestion"] = f"Try: '{suggestion}'"
                error_data["example"] = f"Or use a more descriptive ID like: '{agent_id}_session_001'"
            
            error_msg = json.dumps(error_data, indent=2)
            return None, TextContent(type="text", text=error_msg)
    
    return agent_id, None


def generate_api_key() -> str:
    """
    Generate a secure 32-byte API key for agent authentication.
    
    Returns:
        Base64-encoded API key string (URL-safe, no padding)
    """
    key_bytes = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(key_bytes).decode('ascii').rstrip('=')


def verify_agent_ownership(agent_id: str, api_key: str, session_bound: bool = False) -> tuple[bool, str | None]:
    """
    Verify that the caller owns the agent_id by checking API key or session binding.

    Args:
        agent_id: Agent ID to verify
        api_key: API key provided by caller (can be None for session-bound agents)
        session_bound: If True, skip API key verification (session IS the auth)

    Returns:
        (is_valid, error_message)
        - is_valid=True if authenticated, False otherwise
        - error_message=None if valid, error description if invalid
    """
    # Session-bound agents: the session binding IS the authentication
    # No API key needed - the UUID was bound to this session by identity()
    if session_bound:
        return True, None

    if agent_id not in agent_metadata:
        return False, f"Agent '{agent_id}' does not exist"

    meta = agent_metadata[agent_id]
    stored_key = meta.api_key

    # Handle backward compatibility and UUID-based auth:
    # If no API key stored (None or empty), allow the call.
    # This covers:
    # 1. Legacy agents migrating from pre-auth era
    # 2. New UUID-based identities (auto-created via identity() without API keys)
    if not stored_key:
        # UUID-based identity or legacy agent - no API key auth needed
        # The agent_id (UUID) itself is the authentication
        return True, None

    # Stored key exists - require matching API key from caller
    # Validate api_key is a string (prevents TypeError from secrets.compare_digest)
    if not isinstance(api_key, str) or not api_key:
        return False, "API key is required and must be a non-empty string"

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, stored_key):
        return False, "Invalid API key. This agent_id belongs to another identity."

    return True, None


def require_agent_auth(agent_id: str, arguments: dict, enforce: bool = False) -> tuple[bool, TextContent | None]:
    """
    Require and verify API key for agent authentication.
    
    Args:
        agent_id: Agent ID being accessed
        arguments: Tool arguments dict (should contain 'api_key')
        enforce: If True, require API key even for agents without one (new behavior)
                 If False, allow missing key for backward compatibility (migration mode)
    
    Returns:
        (is_valid, error) - is_valid=True if authenticated, False if error
    """
    api_key = arguments.get("api_key")
    
    # Check if agent exists
    if agent_id not in agent_metadata:
        # New agent - will get key on creation
        return True, None
    
    meta = agent_metadata[agent_id]
    
    # If agent has no API key yet (backward compatibility)
    if meta.api_key is None:
        if enforce:
            # New behavior: require key even for existing agents
            return False, TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "API key required for authentication",
                    "details": f"Agent '{agent_id}' requires an API key for updates. This is a security requirement to prevent impersonation.",
                    "migration": "This agent was created before authentication was added. Generate a key using get_agent_api_key tool.",
                    "suggestion": "Use get_agent_api_key tool to retrieve or generate your API key"
                }, indent=2)
            )
        else:
            # Migration mode: allow first update, generate key
            return True, None
    
    # Agent has API key - require it
    if not api_key:
        return False, TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": "API key required",
                "details": f"Agent '{agent_id}' requires an API key for authentication. This prevents impersonation and protects your identity.",
                "why_this_matters": "Without authentication, anyone could update your agent's state, corrupt your history, and manipulate your governance record.",
                "suggestion": "Include 'api_key' parameter in your request. Use get_agent_api_key tool to retrieve your key."
            }, indent=2)
        )
    
    # Verify key
    is_valid, error_msg = verify_agent_ownership(agent_id, api_key)
    if not is_valid:
        return False, TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": "Authentication failed",
                "details": error_msg or "Invalid API key",
                "why_this_matters": "This agent_id belongs to another identity. Using it would be identity theft.",
                "suggestion": "Use your own agent_id and API key, or create a new agent_id for yourself"
            }, indent=2)
        )
    
    return True, None


def process_update_authenticated(
    agent_id: str,
    api_key: str,
    agent_state: dict,
    auto_save: bool = True
) -> dict:
    """
    Process governance update with authentication enforcement (synchronous version).

    This is the SECURE entry point for processing updates. Use this instead of
    calling UNITARESMonitor.process_update() directly to prevent impersonation.

    Args:
        agent_id: Agent identifier
        api_key: API key for authentication
        agent_state: Agent state dict (parameters, ethical_drift, etc.)
        auto_save: If True, automatically save state to disk after update

    Returns:
        Update result dict with metrics and decision

    Raises:
        PermissionError: If authentication fails
        ValueError: If agent_id is invalid
    """
    # Authenticate ownership
    is_valid, error_msg = verify_agent_ownership(agent_id, api_key)
    if not is_valid:
        raise PermissionError(f"Authentication failed: {error_msg}")

    # Get or create monitor
    monitor = get_or_create_monitor(agent_id)

    # Process update (now authenticated)
    result = monitor.process_update(agent_state)

    # Auto-save state if requested
    if auto_save:
        save_monitor_state(agent_id, monitor)

        # Update metadata
        meta = agent_metadata[agent_id]
        now = datetime.now().isoformat()
        meta.last_update = now
        meta.total_updates += 1
        
        # Track recent updates for loop detection (keep last 10)
        # CRITICAL FIX: Synchronous version was missing this tracking, causing data inconsistency
        decision_action = result.get('decision', {}).get('action', 'unknown')
        meta.recent_update_timestamps.append(now)
        meta.recent_decisions.append(decision_action)
        
        # Keep only last 10 entries
        if len(meta.recent_update_timestamps) > 10:
            meta.recent_update_timestamps = meta.recent_update_timestamps[-10:]
            meta.recent_decisions = meta.recent_decisions[-10:]

        # Note: EISV state persists to PostgreSQL via agent_storage in process_agent_update handler
        # Runtime cache (meta) is updated above; PostgreSQL is single source of truth

    return result


# Alias for cleaner naming (backward compatible)
update_agent_auth = process_update_authenticated


def detect_loop_pattern(agent_id: str) -> tuple[bool, str]:
    """
    Detect recursive self-monitoring loop patterns.
    
    Detects patterns like:
    - Pattern 1: Multiple updates within same second (rapid-fire)
    - Pattern 2: 3+ updates within 10 seconds with 2+ reject decisions
    - Pattern 3: 4+ updates within 5 seconds (any decisions)
    - Pattern 4: Decision loop - same decision repeated 5+ times in recent history
    - Pattern 5: Slow-stuck pattern - 3+ updates in 60s with any reject
    - Pattern 6: Extended rapid pattern - 5+ updates in 120s regardless of decisions
    
    Returns:
        (is_loop, reason) - True if loop detected, with explanation
    """
    if agent_id not in agent_metadata:
        return False, ""
    
    meta = agent_metadata[agent_id]
    
    # Check cooldown period
    if meta.loop_cooldown_until:
        cooldown_until = datetime.fromisoformat(meta.loop_cooldown_until)
        if datetime.now() < cooldown_until:
            remaining = (cooldown_until - datetime.now()).total_seconds()
            return True, f"Loop cooldown active. Wait {remaining:.1f}s before retrying."
    
    # Need at least 3 recent updates to detect pattern
    if len(meta.recent_update_timestamps) < 3:
        return False, ""
    
    # Get last 10 updates (or all if fewer) - expanded window for Pattern 6 (5+ updates in 120s)
    # This ensures we can detect extended patterns while still checking recent behavior
    all_timestamps = meta.recent_update_timestamps[-10:]
    all_decisions = meta.recent_decisions[-10:]
    
    # Filter to only recent timestamps (within last 30 seconds) for Pattern 1 detection
    # This prevents old rapid updates from triggering false positives
    # Other patterns (2-6) use full history to catch extended patterns
    now = datetime.now()
    recent_timestamps_for_pattern1 = []
    for ts_str in all_timestamps:
        try:
            ts = datetime.fromisoformat(ts_str)
            age_seconds = (now - ts).total_seconds()
            if age_seconds <= 30.0:  # Only check updates from last 30 seconds for Pattern 1
                recent_timestamps_for_pattern1.append(ts_str)
        except (ValueError, TypeError):
            continue
    
    # Use full history for other patterns
    recent_timestamps = all_timestamps
    recent_decisions = all_decisions
    
    # GRACE PERIOD: Allow rapid updates after server restart or agent creation
    # Prevents false positives when agents reconnect after server restarts
    # This fixes the "zombie server cleanup -> loop detection" issue
    server_restart_grace_period = timedelta(minutes=5)  # 5 minute grace period
    agent_creation_grace_period = timedelta(minutes=5)  # 5 minute grace period for new agents
    
    # Check if server restarted recently (within grace period)
    server_age = datetime.now() - SERVER_START_TIME
    in_server_grace_period = server_age < server_restart_grace_period
    
    # Check if agent was created recently (within grace period)
    in_agent_grace_period = False
    try:
        agent_created = datetime.fromisoformat(meta.created_at.replace('Z', '+00:00') if 'Z' in meta.created_at else meta.created_at)
        agent_age = datetime.now(agent_created.tzinfo) - agent_created if agent_created.tzinfo else datetime.now() - agent_created.replace(tzinfo=None)
        in_agent_grace_period = agent_age < agent_creation_grace_period
    except (ValueError, TypeError, AttributeError):
        pass
    
    # If in grace period, skip Pattern 1 (rapid-fire) detection
    # This allows legitimate reconnection attempts after server restarts
    # Other patterns (2-6) still apply as they catch different types of loops
    skip_pattern1 = in_server_grace_period or in_agent_grace_period
    
    # Pattern 1: Multiple updates within same second (HISTORICAL PATTERN ANALYSIS)
    # CRITICAL FIX: Check ALL pairs in history, not just last 2 timestamps
    # This catches loops that happened earlier but are no longer "recent"
    # Changed from 2+ updates/0.5s to 3+ updates/0.3s OR 4+ updates/1s
    # Rationale: 2 updates in 0.5 seconds can be legitimate (admin + logging, tool calls)
    #            3+ updates in 0.3 seconds is almost certainly a loop
    #            4+ updates in 1 second is definitely rapid-fire
    # Only check recent timestamps (last 30 seconds) to avoid false positives from old rapid updates
    # SKIP if in grace period (server restart or new agent) to prevent false positives
    if not skip_pattern1 and len(recent_timestamps_for_pattern1) >= 2:
        # HISTORICAL ANALYSIS: Check all pairs, not just last 2
        # This catches loops that happened earlier in the window
        rapid_pairs = []
        try:
            timestamps = [datetime.fromisoformat(ts) for ts in recent_timestamps_for_pattern1]
            
            # Check all consecutive pairs for rapid-fire pattern
            for i in range(len(timestamps) - 1):
                time_diff = (timestamps[i + 1] - timestamps[i]).total_seconds()
                if time_diff < 0.3:
                    rapid_pairs.append((i, i + 1, time_diff))
            
            # If found any rapid pairs, trigger detection
            if rapid_pairs:
                pair_count = len(rapid_pairs)
                fastest_pair = min(rapid_pairs, key=lambda x: x[2])
                return True, f"Rapid-fire updates detected ({pair_count} pair(s) within 0.3s, fastest: {fastest_pair[2]*1000:.1f}ms apart)"
        except (ValueError, TypeError):
            pass
    
    # Check for 3+ updates within 0.5 seconds (HISTORICAL ANALYSIS)
    # Use recent timestamps for Pattern 1 variants
    # SKIP if in grace period (server restart or new agent) to prevent false positives
    if not skip_pattern1 and len(recent_timestamps_for_pattern1) >= 3:
        try:
            timestamps = [datetime.fromisoformat(ts) for ts in recent_timestamps_for_pattern1]
            
            # Check all possible 3-update windows in history
            for i in range(len(timestamps) - 2):
                t1 = timestamps[i]
                t3 = timestamps[i + 2]
                if (t3 - t1).total_seconds() < 0.5:
                    return True, f"Rapid-fire updates detected (3+ updates within 0.5 seconds, detected at positions {i}-{i+2})"
        except (ValueError, TypeError):
            pass
    
    # Check for 4+ updates within 1 second (HISTORICAL ANALYSIS)
    # Use recent timestamps for Pattern 1 variants
    # SKIP if in grace period (server restart or new agent) to prevent false positives
    if not skip_pattern1 and len(recent_timestamps_for_pattern1) >= 4:
        try:
            timestamps = [datetime.fromisoformat(ts) for ts in recent_timestamps_for_pattern1]
            
            # Check all possible 4-update windows in history
            for i in range(len(timestamps) - 3):
                t1 = timestamps[i]
                t4 = timestamps[i + 3]
                if (t4 - t1).total_seconds() < 1.0:
                    return True, f"Rapid-fire updates detected (4+ updates within 1 second, detected at positions {i}-{i+3})"
        except (ValueError, TypeError):
            pass
    
    # Pattern 2: 3+ updates within 10 seconds, all with "reject" decisions
    if len(recent_timestamps) >= 3:
        last_three_timestamps = recent_timestamps[-3:]
        last_three_decisions = recent_decisions[-3:]
        
        try:
            timestamps = [datetime.fromisoformat(ts) for ts in last_three_timestamps]
            time_span = (timestamps[-1] - timestamps[0]).total_seconds()
            
            if time_span <= 10.0:  # Within 10 seconds
                pause_count = sum(1 for d in last_three_decisions if d in ["pause", "reject"])  # Backward compat
                if pause_count >= 2:  # At least 2 pauses
                    return True, f"Recursive pause pattern: {pause_count} pause decisions within {time_span:.1f}s"
        except (ValueError, TypeError):
            pass
    
    # Pattern 3: 4+ updates within 5 seconds with concerning decisions
    # IMPROVED: Only trigger if there are pause/reject decisions (indicates stuck state)
    # Rationale: Legitimate workflows can have rapid updates, but if all are "proceed",
    #           the agent is likely fine. Only flag if there are concerning decisions.
    if len(recent_timestamps) >= 4:
        last_four_timestamps = recent_timestamps[-4:]
        last_four_decisions = recent_decisions[-4:]
        try:
            timestamps = [datetime.fromisoformat(ts) for ts in last_four_timestamps]
            time_span = (timestamps[-1] - timestamps[0]).total_seconds()
            
            if time_span <= 5.0:  # Within 5 seconds
                # Check for concerning decisions (pause/reject) - indicates stuck state
                concerning_count = sum(1 for d in last_four_decisions if d in ["pause", "reject"])
                if concerning_count >= 1:  # At least one pause/reject indicates potential loop
                    return True, f"Rapid update pattern: 4+ updates within {time_span:.1f}s with {concerning_count} pause/reject decision(s)"
        except (ValueError, TypeError):
            pass
    
    # Pattern 4: Decision loop - same decision repeated 5+ times in recent history
    # UPDATED: Only triggers on "pause" loops (stuck states), not "proceed" loops (normal operation).
    # "Proceed" is normal operation and shouldn't block agents. Only "pause" indicates
    # a stuck state that needs intervention.
    if len(recent_decisions) >= 5:
        from collections import Counter
        # Check last 10 decisions (or all if fewer)
        decision_window = recent_decisions[-10:] if len(recent_decisions) >= 10 else recent_decisions
        decision_counts = Counter(decision_window)
        
        # Only trigger on "pause" loops - "proceed" is normal operation, not a stuck state
        # Map old decisions for backward compatibility
        pause_count = decision_counts.get("pause", 0) + decision_counts.get("reject", 0)
        if pause_count >= 5:
            return True, f"Decision loop detected: {pause_count} 'pause' decisions in recent history (stuck state)"
        
        # For "proceed with guidance" loops, require more consecutive decisions (8+) to avoid false positives
        # This catches agents truly stuck in proceed cycles, not just normal operation
        # Note: Most decisions will be "proceed" - this is normal, so threshold is high
        proceed_count = decision_counts.get("proceed", 0) + decision_counts.get("approve", 0) + decision_counts.get("reflect", 0) + decision_counts.get("revise", 0)
        if proceed_count >= 15:  # Higher threshold since proceed is the normal state
            return True, f"Decision loop detected: {proceed_count} consecutive 'proceed' decisions (agent may be stuck in feedback loop)"
    
    # Pattern 5: Slow-stuck pattern - 3+ updates in 60s with 2+ rejects
    # Catches "slow-stuck" patterns where agents update rapidly but not fast enough
    # to trigger rapid-fire detection (Patterns 1-3), then get stuck.
    # FIXED: Require 2+ pauses, not 1. A single pause in 3 updates is normal governance
    # feedback (e.g. periodic heartbeat agents like Lumen). A real stuck agent retries
    # the same failing action and accumulates multiple pause/reject decisions.
    if len(recent_timestamps) >= 3:
        last_three_timestamps = recent_timestamps[-3:]
        last_three_decisions = recent_decisions[-3:]

        try:
            timestamps = [datetime.fromisoformat(ts) for ts in last_three_timestamps]
            time_span = (timestamps[-1] - timestamps[0]).total_seconds()

            if time_span <= 60.0:  # Within 60 seconds
                pause_count = sum(1 for d in last_three_decisions if d in ["pause", "reject"])  # Backward compat
                if pause_count >= 2:  # 2+ pauses indicates real stuck loop, not normal heartbeat
                    return True, f"Slow-stuck pattern: {pause_count} pause(s) in {len(last_three_timestamps)} updates within {time_span:.1f}s"
        except (ValueError, TypeError):
            pass
    
    # Pattern 6: Extended rapid pattern - 5+ updates in 120s with concerning decisions
    # Catches agents that are updating frequently over a longer time window, which may indicate
    # they're stuck in a loop even if individual updates aren't rapid enough to trigger Pattern 3.
    # FIXED: Require 3+ pauses (majority), not 1. Periodic heartbeat agents (like Lumen)
    # naturally send 5+ updates in 120s — that's their job. A single pause/reject is normal
    # governance feedback. A real stuck agent accumulates multiple consecutive rejections.
    if len(recent_timestamps) >= 5:
        # Get last 5+ timestamps and decisions
        last_five_timestamps = recent_timestamps[-5:]
        last_five_decisions = recent_decisions[-5:]
        try:
            timestamps = [datetime.fromisoformat(ts) for ts in last_five_timestamps]
            time_span = (timestamps[-1] - timestamps[0]).total_seconds()

            if time_span <= 120.0:  # Within 120 seconds (2 minutes)
                # Check for concerning decisions (pause/reject) - indicates stuck state
                concerning_count = sum(1 for d in last_five_decisions if d in ["pause", "reject"])
                if concerning_count >= 3:  # Majority must be pause/reject to indicate real loop
                    return True, f"Extended rapid pattern: {len(last_five_timestamps)} updates within {time_span:.1f}s with {concerning_count} pause/reject decision(s)"
        except (ValueError, TypeError):
            pass
    
    return False, ""


async def process_update_authenticated_async(
    agent_id: str,
    api_key: str,
    agent_state: dict,
    auto_save: bool = True,
    confidence: Optional[float] = None,
    task_type: str = "mixed",
    session_bound: bool = False
) -> dict:
    """
    Process governance update with authentication enforcement (async version).

    This is the SECURE async entry point for processing updates. Use this in async
    contexts (like MCP handlers) instead of calling UNITARESMonitor.process_update()
    directly to prevent impersonation.

    Args:
        agent_id: Agent identifier
        api_key: API key for authentication (can be None for session-bound agents)
        agent_state: Agent state dict (parameters, ethical_drift, etc.)
        auto_save: If True, automatically save state to disk after update (async)
        confidence: Confidence level [0, 1] for this update. If None (default),
                    confidence is derived from thermodynamic state (I, S, C, V).
                    When confidence < 0.8, lambda1 updates are skipped.
        session_bound: If True, skip API key verification (session IS the auth)

    Returns:
        Update result dict with metrics and decision

    Raises:
        PermissionError: If authentication fails
        ValueError: If agent_id is invalid
    """
    # Authenticate ownership (run in executor to avoid blocking)
    loop = asyncio.get_running_loop()
    is_valid, error_msg = await loop.run_in_executor(
        None, verify_agent_ownership, agent_id, api_key, session_bound
    )
    if not is_valid:
        raise PermissionError(f"Authentication failed: {error_msg}")

    # Check for loop pattern BEFORE processing (run in executor to avoid blocking)
    is_loop, loop_reason = await loop.run_in_executor(None, detect_loop_pattern, agent_id)
    if is_loop:
        meta = agent_metadata[agent_id]
        
        # If cooldown is already active, just return the existing cooldown message
        # Don't set a new cooldown or override the existing one
        if "Loop cooldown active" in loop_reason:
            # Extract remaining time from reason message
            import re
            match = re.search(r'Wait ([\d.]+)s', loop_reason)
            if match:
                remaining = float(match.group(1))
                raise ValueError(
                    f"Self-monitoring loop detected: {loop_reason}. "
                    f"Cooldown expires in {remaining:.1f} seconds."
                )
            else:
                raise ValueError(f"Self-monitoring loop detected: {loop_reason}")
        
        # Set cooldown period (pattern-specific: shorter for Pattern 1)
        # Determine cooldown duration based on pattern
        # Pattern 1 (rapid-fire): 5 seconds (most likely false positive, very relaxed)
        # Patterns 2-3 (rapid patterns): 15 seconds
        # Patterns 4-6 (decision loops, extended): 30 seconds
        if "Rapid-fire updates detected" in loop_reason:
            cooldown_seconds = 5  # Very short for Pattern 1 (reduces false positive impact)
        elif "Rapid update pattern" in loop_reason or "Recursive reject pattern" in loop_reason:
            cooldown_seconds = 15  # Medium for rapid patterns
        else:
            cooldown_seconds = 30  # Full cooldown for decision loops and extended patterns
        
        cooldown_until = datetime.now() + timedelta(seconds=cooldown_seconds)
        meta.loop_cooldown_until = cooldown_until.isoformat()
        
        # Track loop incidents for historical analysis
        if not hasattr(meta, 'loop_incidents') or meta.loop_incidents is None:
            meta.loop_incidents = []
        
        # Record this loop incident
        incident = {
            'detected_at': datetime.now().isoformat(),
            'reason': loop_reason,
            'cooldown_seconds': cooldown_seconds,
            'timestamp_history': meta.recent_update_timestamps.copy() if meta.recent_update_timestamps else []
        }
        meta.loop_incidents.append(incident)
        
        # Keep only last 20 incidents (prevent unbounded growth)
        if len(meta.loop_incidents) > 20:
            meta.loop_incidents = meta.loop_incidents[-20:]
        
        if not meta.loop_detected_at:
            meta.loop_detected_at = datetime.now().isoformat()
            meta.add_lifecycle_event("loop_detected", loop_reason)
            logger.warning(f"⚠️  Loop detected for agent '{agent_id}': {loop_reason} (cooldown: {cooldown_seconds}s)")
        else:
            # Log repeat incidents
            incident_count = len(meta.loop_incidents)
            logger.warning(f"⚠️  Loop incident #{incident_count} for agent '{agent_id}': {loop_reason} (cooldown: {cooldown_seconds}s)")

        # Note: Loop incidents persist to PostgreSQL via agent_storage
        # Runtime cache (meta) updated above; PostgreSQL is single source of truth
        
        # Format cooldown time in human-readable format
        cooldown_time_str = cooldown_until.strftime('%Y-%m-%d %H:%M:%S')

        # Include recovery tool suggestions in error message
        recovery_tools = []
        if cooldown_seconds <= 5:
            recovery_tools.append("direct_resume_if_safe (if state is safe)")
        else:
            recovery_tools.append("direct_resume_if_safe (if state is safe)")
            recovery_tools.append("request_dialectic_review (for peer assistance)")
        
        recovery_guidance = (
            f"\n\n🔧 Recovery Options:\n"
            f"- Wait {cooldown_seconds}s for cooldown to expire (automatic)\n"
            f"- Use {recovery_tools[0]} to resume immediately if your state is safe\n"
        )
        if len(recovery_tools) > 1:
            recovery_guidance += f"- Use {recovery_tools[1]} to get peer assistance\n"
        recovery_guidance += (
            f"\n💡 Tip: These recovery tools can help you get unstuck faster. "
            f"See AI_ASSISTANT_GUIDE.md for details."
        )
        
        raise ValueError(
            f"Self-monitoring loop detected: {loop_reason}. "
            f"Updates blocked for {cooldown_seconds} seconds to prevent system crash. "
            f"Cooldown until: {cooldown_time_str} ({cooldown_seconds}s remaining)"
            + recovery_guidance
        )

    # Get or create monitor (run in executor to avoid blocking - may do file I/O)
    monitor = await loop.run_in_executor(None, get_or_create_monitor, agent_id)

    # Extract task_type from agent_state for context-aware EISV interpretation
    task_type = agent_state.get("task_type", "mixed")
    
    # Process update (now authenticated) with confidence gating
    # IMPORTANT: Run in executor to avoid blocking the event loop (fixes Claude Desktop hangs)
    from functools import partial
    result = await loop.run_in_executor(
        None, 
        partial(monitor.process_update, agent_state, confidence=confidence, task_type=task_type)
    )

    # Auto-save state if requested (async)
    if auto_save:
        await save_monitor_state_async(agent_id, monitor)

        # Update metadata
        meta = agent_metadata[agent_id]
        now = datetime.now().isoformat()
        meta.last_update = now
        meta.total_updates += 1
        
        # Track recent updates for loop detection (keep last 10)
        decision_action = result.get('decision', {}).get('action', 'unknown')
        meta.recent_update_timestamps.append(now)
        meta.recent_decisions.append(decision_action)
        
        # Keep only last 10 entries
        if len(meta.recent_update_timestamps) > 10:
            meta.recent_update_timestamps = meta.recent_update_timestamps[-10:]
            meta.recent_decisions = meta.recent_decisions[-10:]

        # Persist counters to PostgreSQL (in-memory is not enough — survives restarts)
        for _attempt in range(2):
            try:
                from src import agent_storage
                db = agent_storage.get_db()
                await db.update_identity_metadata(agent_id, {
                    "total_updates": meta.total_updates,
                    "recent_update_timestamps": meta.recent_update_timestamps,
                    "recent_decisions": meta.recent_decisions,
                }, merge=True)
                break  # success
            except Exception as e:
                if _attempt == 0:
                    await asyncio.sleep(0.1)  # brief retry
                else:
                    logger.warning(f"Failed to persist update counters for {agent_id[:8]}... after 2 attempts: {e}")

        # Enforce pause decisions (circuit breaker)
        # SELF-GOVERNANCE: When paused, automatically initiate dialectic recovery
        # instead of waiting for human intervention
        if decision_action == 'pause':
            meta.status = "paused"
            meta.paused_at = now
            decision_reason = result.get('decision', {}).get('reason', 'Circuit breaker triggered')
            meta.add_lifecycle_event("paused", decision_reason)
            logger.warning(f"⚠️  Circuit breaker triggered for agent '{agent_id}': {decision_reason}")
            
            # SELF-GOVERNANCE: Auto-initiate dialectic recovery (non-blocking)
            # This removes the human bottleneck - agents self-recover via peer review
            try:
                auto_recovery = os.getenv("UNITARES_AUTO_DIALECTIC_RECOVERY", "1").strip().lower() not in ("0", "false", "no")
                if auto_recovery:
                    # Use loop from outer scope (already imported at module level)
                    loop.create_task(_auto_initiate_dialectic_recovery(agent_id, decision_reason))
                    result["auto_recovery_initiated"] = True
                    result["auto_recovery_note"] = "Dialectic recovery auto-initiated (self-governance mode)"
            except Exception as e:
                logger.warning(f"Could not auto-initiate dialectic recovery: {e}")
        
        # Clear cooldown if it has passed
        if meta.loop_cooldown_until:
            cooldown_until = datetime.fromisoformat(meta.loop_cooldown_until)
            if datetime.now() >= cooldown_until:
                meta.loop_cooldown_until = None
        
        # Save metadata in executor to avoid blocking (critical for identity/lifecycle data)
        await loop.run_in_executor(None, save_metadata)

    return result


async def _auto_initiate_dialectic_recovery(agent_id: str, reason: str) -> None:
    """
    SELF-GOVERNANCE: Auto-initiate dialectic recovery for paused agents.
    
    Instead of waiting for human intervention, automatically start peer review
    with auto_progress=True and reviewer_mode='auto' (try peer, fallback to self).
    
    This embodies the self-governance principle: agents recover autonomously
    via peer review, human intervention is optional enhancement not requirement.
    """
    import asyncio
    await asyncio.sleep(2)  # Brief delay to let state settle
    
    try:
        from src.mcp_handlers.dialectic import handle_request_dialectic_review
        
        logger.info(f"🔄 Auto-initiating dialectic recovery for paused agent '{agent_id}'")
        
        # Get API key for the agent (needed for authentication)
        meta = agent_metadata.get(agent_id)
        api_key = meta.api_key if meta else None
        
        if not api_key:
            logger.warning(f"Cannot auto-initiate dialectic for '{agent_id}': no API key")
            return
        
        # Auto-initiate with:
        # - auto_progress=True: progress through phases automatically
        # - reviewer_mode='auto': try peer first, fall back to self-recovery
        result = await handle_request_dialectic_review({
            "agent_id": agent_id,
            "reason": f"Auto-recovery: {reason}",
            "api_key": api_key,
            "auto_progress": True,
            "reviewer_mode": "auto"
        })
        
        logger.info(f"✅ Dialectic recovery auto-initiated for '{agent_id}': {result}")
        
    except Exception as e:
        logger.error(f"Failed to auto-initiate dialectic recovery for '{agent_id}': {e}")


def get_agent_or_error(agent_id: str) -> tuple[UNITARESMonitor | None, str | None]:
    """Get agent with friendly error message if not found"""
    if agent_id not in monitors:
        available = list(monitors.keys())
        if available:
            error = f"Agent '{agent_id}' not found. Available agents: {available}. Call process_agent_update first to initialize."
        else:
            error = f"Agent '{agent_id}' not found. No agents initialized yet. Call process_agent_update first."
        return None, error
    return monitors[agent_id], None


def build_standardized_agent_info(
    agent_id: str,
    meta: AgentMetadata,
    monitor: UNITARESMonitor | None = None,
    include_metrics: bool = True
) -> dict:
    """
    Build standardized agent info structure.
    Always returns same fields, null if unavailable.
    """
    # Determine timestamps (prefer monitor, fallback to metadata)
    if monitor:
        # Use monitor timestamps if available, fallback to metadata
        if hasattr(monitor, 'created_at') and monitor.created_at:
            created_ts = monitor.created_at.isoformat()
        else:
            created_ts = meta.created_at
        
        if hasattr(monitor, 'last_update') and monitor.last_update:
            last_update_ts = monitor.last_update.isoformat()
        else:
            last_update_ts = meta.last_update
        
        # Always use meta.total_updates (Postgres-backed) as authoritative count.
        # monitor.state.update_count is a separate counter that can drift.
        update_count = meta.total_updates
    else:
        created_ts = meta.created_at
        last_update_ts = meta.last_update
        update_count = meta.total_updates
    
    # Calculate age in days
    try:
        created_dt = datetime.fromisoformat(created_ts.replace('Z', '+00:00') if 'Z' in created_ts else created_ts)
        age_days = (datetime.now(created_dt.tzinfo) - created_dt).days
    except (ValueError, TypeError, AttributeError):
        age_days = None
    
    # Extract primary tags (first 3, or all if <= 3)
    primary_tags = (meta.tags or [])[:3] if meta.tags else []
    
    # Notes preview (first 100 chars)
    notes_preview = None
    if meta.notes:
        notes_preview = meta.notes[:100] + "..." if len(meta.notes) > 100 else meta.notes
    
    # Build summary
    summary = {
        "updates": update_count,
        "last_activity": last_update_ts,
        "age_days": age_days,
        "primary_tags": primary_tags
    }
    
    # Build metrics (null if unavailable)
    metrics = None
    health_status = "unknown"
    state_info = {
        "loaded_in_process": monitor is not None,
        "metrics_available": False,
        "error": None
    }
    
    if monitor and include_metrics:
        try:
            monitor_state = monitor.state
            risk_score = getattr(monitor_state, 'risk_score', None)
            health_status_obj, _ = health_checker.get_health_status(
                risk_score=risk_score,
                coherence=monitor_state.coherence,
                void_active=monitor_state.void_active
            )
            health_status = health_status_obj.value
            
            # Get metrics to include phi/verdict
            monitor_metrics = monitor.get_metrics() if hasattr(monitor, 'get_metrics') else {}
            risk_score_value = monitor_metrics.get("risk_score") or risk_score
            
            metrics = {
                "risk_score": float(risk_score_value) if risk_score_value is not None else None,  # Governance/operational risk
                "phi": monitor_metrics.get("phi"),  # Primary physics signal
                "verdict": monitor_metrics.get("verdict"),  # Primary governance signal
                "coherence": float(monitor_state.coherence),
                "void_active": bool(monitor_state.void_active),
                "E": float(monitor_state.E),
                "I": float(monitor_state.I),
                "S": float(monitor_state.S),
                "V": float(monitor_state.V),
                "lambda1": float(monitor_state.lambda1)
            }
            state_info["metrics_available"] = True
        except Exception as e:
            health_status = "error"
            state_info["error"] = str(e)
            state_info["metrics_available"] = False
    
    # Build lineage relationship info (if agent has a parent)
    lineage_info = None
    if meta.parent_agent_id:
        lineage_info = {
            "parent_agent_id": meta.parent_agent_id,
            "creation_reason": meta.spawn_reason or "created",
            "has_lineage": True
        }
        # Check if parent still exists
        if meta.parent_agent_id in agent_metadata:
            parent_meta = agent_metadata[meta.parent_agent_id]
            lineage_info["parent_status"] = parent_meta.status
        else:
            lineage_info["parent_status"] = "deleted"
    
    # Build standardized structure
    return {
        "agent_id": agent_id,
        "lifecycle_status": meta.status,
        "health_status": health_status,
        "summary": summary,
        "metrics": metrics,
        "metadata": {
            "created": created_ts,
            "last_update": last_update_ts,
            "version": meta.version,
            "total_updates": meta.total_updates,
            "tags": meta.tags or [],
            "notes_preview": notes_preview,
            "lineage_info": lineage_info
        },
        "state": state_info
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available MCP tools"""
    def _filtered_local_tools() -> list[Tool]:
        tools = get_tool_definitions()
        try:
            from src.tool_modes import TOOL_MODE, should_include_tool
            return [t for t in tools if should_include_tool(t.name, mode=TOOL_MODE)]
        except Exception:
            return tools

    if STDIO_PROXY_HTTP_URL:
        try:
            return await _proxy_http_list_tools()
        except Exception as e:
            logger.error(f"STDIO proxy list_tools failed (HTTP {STDIO_PROXY_HTTP_URL}): {e}", exc_info=True)
            if STDIO_PROXY_STRICT:
                raise
            return _filtered_local_tools()
    if STDIO_PROXY_URL:
        try:
            return await _proxy_list_tools()
        except Exception as e:
            logger.error(f"STDIO proxy list_tools failed ({STDIO_PROXY_URL}): {e}", exc_info=True)
            if STDIO_PROXY_STRICT:
                raise
            # Non-strict fallback: expose local tools (creates transport silo again; use only for debugging).
            return _filtered_local_tools()

    # Default: local tool definitions
    return _filtered_local_tools()


async def inject_lightweight_heartbeat(
    agent_id: str,
    trigger_reason: str,
    activity_summary: dict,
    tracker
) -> None:
    """
    Inject a lightweight governance heartbeat.
    
    Non-blocking, fire-and-forget. Provides visibility without heavy overhead.
    """
    try:
        # Reload metadata to get latest state
        load_metadata()
        
        # Get or create agent metadata (needed for heartbeat)
        if agent_id not in agent_metadata:
            get_or_create_metadata(agent_id)
        
        meta = agent_metadata.get(agent_id)
        if not meta:
            return
        
        # Get API key (required for authenticated update)
        api_key = meta.api_key
        if not api_key:
            # Generate if missing (shouldn't happen, but be safe)
            api_key = generate_api_key()
            meta.api_key = api_key
            # Note: API key persists to PostgreSQL via agent_storage
            try:
                from src import agent_storage
                await agent_storage.update_agent(agent_id, api_key=api_key)
            except Exception as e:
                logger.debug(f"PostgreSQL API key update failed: {e}")
        
        # Call process_agent_update with heartbeat flag
        # This uses the lightweight heartbeat path in the handler
        from src.mcp_handlers.core import handle_process_agent_update
        
        heartbeat_args = {
            'agent_id': agent_id,
            'api_key': api_key,
            'heartbeat': True,
            'trigger_reason': trigger_reason,
            'activity_summary': activity_summary,
            'response_text': f"Auto-heartbeat ({trigger_reason})",
            'complexity': activity_summary.get('average_complexity', 0.5)
        }
        
        # Call heartbeat handler (non-blocking, fire-and-forget)
        await handle_process_agent_update(heartbeat_args)
        
        # Reset activity counters after heartbeat
        tracker.reset_after_governance_update(agent_id)
        
    except Exception as e:
        # Don't fail if heartbeat injection fails - this is best-effort visibility
        logger.error(f"Error injecting heartbeat for {agent_id}: {e}", exc_info=True)


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> Sequence[TextContent]:
    """Handle tool calls from MCP client"""
    # Update process heartbeat on every tool call to mark this process as active
    # This prevents other clients from killing this process during cleanup
    process_mgr.write_heartbeat()

    if arguments is None:
        arguments = {}

    # Optional stdio->HTTP proxy mode (preferred standardization path)
    if STDIO_PROXY_HTTP_URL:
        try:
            return await _proxy_http_call_tool(name, arguments)
        except Exception as e:
            logger.error(f"STDIO proxy call_tool failed (HTTP {STDIO_PROXY_HTTP_URL}) name={name}: {e}", exc_info=True)
            if STDIO_PROXY_STRICT:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"STDIO proxy mode enabled but HTTP server unavailable or errored for tool '{name}'.",
                        "details": {
                            "proxy_url": STDIO_PROXY_HTTP_URL,
                            "tool": name,
                            "exception": str(e),
                            "note": "Start the governance server or unset UNITARES_STDIO_PROXY_HTTP_URL to run locally (local mode is transport-siloed)."
                        }
                    }, indent=2)
                )]
            # Non-strict fallback: allow local execution (debug only).

    # Optional stdio->server proxy mode (forward to shared governance server)
    if STDIO_PROXY_URL:
        try:
            return await _proxy_call_tool(name, arguments)
        except Exception as e:
            logger.error(f"STDIO proxy call_tool failed ({STDIO_PROXY_URL}) name={name}: {e}", exc_info=True)
            # In strict mode, return a clear JSON error instead of falling back to local execution.
            if STDIO_PROXY_STRICT:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"STDIO proxy mode enabled but governance server unavailable or errored for tool '{name}'.",
                        "details": {
                            "proxy_url": STDIO_PROXY_URL,
                            "tool": name,
                            "exception": str(e),
                            "note": "Start the governance server or unset UNITARES_PROXY_URL to run locally (local mode is transport-siloed)."
                        }
                    }, indent=2)
                )]
            # Non-strict fallback: allow local execution (debug only).

    # Tool mode filtering removed - all tools always available
    # Track activity for agent and auto-inject lightweight heartbeats
    agent_id = arguments.get('agent_id')
    if agent_id and HEARTBEAT_CONFIG.enabled:
        should_trigger, trigger_reason = activity_tracker.track_tool_call(agent_id, name)

        # Auto-inject lightweight heartbeat if threshold reached
        # Exclude lightweight tools that don't need governance checks (prevent loops)
        lightweight_tools = {
            "process_agent_update",  # Already a governance update
            "reply_to_question",     # Knowledge graph Q&A (lightweight)
            "leave_note",            # Knowledge graph notes (lightweight)
            "get_discovery_details",  # Read-only knowledge graph
            "search_knowledge_graph", # Read-only knowledge graph
            "get_knowledge_graph",    # Read-only knowledge graph
            "list_knowledge_graph",   # Read-only knowledge graph
            # Dialectic tools (coordination, not high-impact actions)
            "request_dialectic_review",
            "request_exploration_session",
            "submit_thesis",
            "submit_antithesis",
            "submit_synthesis",
            "get_dialectic_session",
            "dialectic",
        }
        if should_trigger and name not in lightweight_tools:
            try:
                # Get activity summary for heartbeat
                activity = activity_tracker.get_or_create(agent_id)
                activity_summary = {
                    "conversation_turns": activity.conversation_turns,
                    "tool_calls": activity.tool_calls,
                    "files_modified": activity.files_modified,
                    "average_complexity": (
                        activity.cumulative_complexity / len(activity.complexity_samples)
                        if activity.complexity_samples else 0.5
                    ),
                    "duration_minutes": (
                        (datetime.now() - datetime.fromisoformat(activity.session_start))
                        .total_seconds() / 60
                        if activity.session_start else 0
                    )
                }
                
                # Inject lightweight heartbeat (non-blocking)
                import asyncio
                asyncio.create_task(
                    inject_lightweight_heartbeat(agent_id, trigger_reason, activity_summary, activity_tracker)
                )
                
                logger.info(f"Auto-triggered heartbeat for {agent_id}: {trigger_reason}")
            except Exception as e:
                # Don't fail tool execution if heartbeat injection fails
                logger.warning(f"Could not inject heartbeat: {e}", exc_info=True)

    # Track tool usage for analytics
    try:
        from src.tool_usage_tracker import get_tool_usage_tracker
        usage_tracker = get_tool_usage_tracker()
        usage_tracker.log_tool_call(tool_name=name, agent_id=agent_id, success=True)
    except Exception:
        # Don't fail tool execution if usage tracking fails
        pass

    # All handlers are now in the registry - dispatch to handler
    success = True
    error_type = None
    try:
        from src.mcp_handlers import dispatch_tool
        result = await dispatch_tool(name, arguments)
        if result is not None:
            return result
        # If None returned, handler not found - return error
        error_response = [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Unknown tool: {name}"
            }, indent=2)
        )]
        # Log failed tool call
        try:
            from src.tool_usage_tracker import get_tool_usage_tracker
            get_tool_usage_tracker().log_tool_call(tool_name=name, agent_id=agent_id, success=False, error_type="unknown_tool")
        except Exception:
            pass
        return error_response
    except ImportError:
        # Handlers module not available - return error
        error_response = [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Handler registry not available. Tool '{name}' cannot be processed."
            }, indent=2)
        )]
        # Log failed tool call
        try:
            from src.tool_usage_tracker import get_tool_usage_tracker
            get_tool_usage_tracker().log_tool_call(tool_name=name, agent_id=agent_id, success=False, error_type="import_error")
        except Exception:
            pass
        return error_response
    except Exception as e:
        # SECURITY: Log full traceback internally but sanitize for client
        import traceback
        logger.error(f"Tool '{name}' execution error: {e}", exc_info=True)
        
        # Return sanitized error message (no internal structure)
        from src.mcp_handlers.utils import error_response as create_error_response
        sanitized_error = create_error_response(
            f"Error executing tool '{name}': {str(e)}",
            recovery={
                "action": "Check tool parameters and try again",
                "related_tools": ["health_check", "list_tools"],
                "workflow": "1. Verify tool parameters 2. Check system health 3. Retry with simpler parameters"
            }
        )
        # Log failed tool call
        try:
            from src.tool_usage_tracker import get_tool_usage_tracker
            get_tool_usage_tracker().log_tool_call(tool_name=name, agent_id=agent_id, success=False, error_type="execution_error")
        except Exception:
            pass
        return [sanitized_error]




async def main():
    """Main entry point for MCP server"""
    # Fast startup: Don't load metadata synchronously - it's loaded lazily when needed
    # This prevents blocking Claude Desktop initialization
    
    # Background task for automatic startup features (runs after server starts)
    async def startup_background_tasks():
        """Run automatic consistency features in background after server starts"""
        # Wait a moment for server to initialize
        await asyncio.sleep(0.5)
        
        try:
            # Load metadata in background (non-blocking)
            loop = asyncio.get_running_loop()  # Use get_running_loop() instead of deprecated get_event_loop()
            await loop.run_in_executor(None, load_metadata)
        except Exception as e:
            logger.warning(f"Could not load metadata in background: {e}", exc_info=True)
        
        try:
            # Auto-archive old test agents in background (now async)
            archived = await auto_archive_old_test_agents(6.0)
            if archived > 0:
                logger.info(f"Auto-archived {archived} old test/demo agents")
        except Exception as e:
            logger.warning(f"Could not auto-archive old test agents: {e}", exc_info=True)

        try:
            # Aggressive orphan cleanup to prevent agent proliferation
            orphans_archived = await auto_archive_orphan_agents(
                zero_update_hours=1.0,  # UUID agents with 0 updates after 1h
                low_update_hours=3.0,   # Unlabeled agents with 0-1 updates after 3h
                unlabeled_hours=6.0     # Stale UUID agents with 2+ updates after 6h
            )
            if orphans_archived > 0:
                logger.info(f"Auto-archived {orphans_archived} orphan agents")
        except Exception as e:
            logger.warning(f"Could not auto-archive orphan agents: {e}", exc_info=True)

        try:
            # Auto-collect ground truth for calibration (runs periodically)
            from src.auto_ground_truth import collect_ground_truth_automatically, auto_ground_truth_collector_task
            try:
                # Run initial collection at startup
                result = await collect_ground_truth_automatically(
                    min_age_hours=2.0,
                    max_decisions=50,
                    dry_run=False
                )
                if result.get('updated', 0) > 0:
                    logger.info(f"Auto-collected ground truth: {result['updated']} decisions updated")
                
                # Start periodic background task (runs every 6 hours)
                asyncio.create_task(auto_ground_truth_collector_task(interval_hours=6.0))
                logger.info("Started periodic auto ground truth collector (runs every 6 hours)")
            except Exception as e:
                logger.warning(f"Could not auto-collect ground truth: {e}", exc_info=True)
        except ImportError:
            logger.debug("Auto ground truth collector not available (optional feature)")
        
        try:
            # Clean up stale locks in background
            loop = asyncio.get_running_loop()  # Use get_running_loop() instead of deprecated get_event_loop()
            result = await loop.run_in_executor(
                None, 
                cleanup_stale_state_locks, 
                project_root, 
                300,
                False
            )
            if result.get('cleaned', 0) > 0:
                logger.info(f"Cleaned {result['cleaned']} stale lock files")
        except Exception as e:
            logger.warning(f"Could not clean up stale locks: {e}", exc_info=True)
        
        try:
            # Load active dialectic sessions from disk (restore after restart)
            from src.mcp_handlers.dialectic import load_all_sessions
            loaded_sessions = await load_all_sessions()
            if loaded_sessions > 0:
                logger.info(f"Restored {loaded_sessions} active dialectic session(s) from disk")
        except Exception as e:
            logger.warning(f"Could not load dialectic sessions: {e}", exc_info=True)

        try:
            # Run dialectic data consolidation to ensure JSON backups exist for all SQLite sessions
            # This prevents data loss by maintaining dual storage
            from src.mcp_handlers.dialectic_session import run_startup_consolidation
            consolidation_result = await run_startup_consolidation()
            if consolidation_result.get('exported', 0) > 0:
                logger.info(f"Dialectic consolidation: exported {consolidation_result['exported']} sessions to JSON backup")
            if consolidation_result.get('synced', 0) > 0:
                logger.info(f"Dialectic consolidation: synced {consolidation_result['synced']} sessions from JSON to SQLite")
        except Exception as e:
            logger.warning(f"Could not run dialectic consolidation: {e}", exc_info=True)
    
    try:
        async with stdio_server() as (read_stream, write_stream):
            # Start background tasks for automatic features (non-blocking)
            # Wrap in try/except to prevent background task errors from crashing server
            async def safe_startup_background_tasks():
                try:
                    await startup_background_tasks()
                except Exception as e:
                    # Log but don't crash - background tasks are non-critical
                    logger.warning(f"Background task error (non-critical): {e}", exc_info=True)
                    import traceback
                    logger.debug(f"Traceback:\n{traceback.format_exc()}")
            
            # In stdio proxy mode we intentionally do NOT start local background tasks.
            # Rationale: This process is a thin transport shim; the upstream server owns shared state.
            if not (STDIO_PROXY_URL or STDIO_PROXY_HTTP_URL):
                # Create background task with error handling
                bg_task = asyncio.create_task(safe_startup_background_tasks())
                # Don't await - let it run in background
            
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )
    except ExceptionGroup as eg:
        # Handle ExceptionGroup from stdio_server TaskGroup (Python 3.11+)
        # Claude Desktop disconnects faster than Cursor, causing TaskGroup errors
        # When client disconnects, stdout_writer task gets BrokenPipeError
        def _flatten(ex):
            if isinstance(ex, ExceptionGroup):
                for sub in ex.exceptions:
                    yield from _flatten(sub)
            else:
                yield ex

        flat = list(_flatten(eg))
        # Treat common disconnect/teardown exceptions as normal (not errors).
        normal_disconnect_types = (BrokenPipeError, ConnectionResetError, asyncio.CancelledError)
        if any(isinstance(e, normal_disconnect_types) for e in flat):
            # Normal disconnection - Claude Desktop is stricter than Cursor
            # Cursor tolerates slower operations, Claude Desktop disconnects faster
            pass
        else:
            # Unexpected error - log it but don't crash
            logger.error(f"TaskGroup error: {eg}")
            import traceback
            # Log each exception in the group with full traceback
            for i, exc in enumerate(flat):
                logger.error(f"Exception {i+1}/{len(flat)}: {type(exc).__name__}: {exc}")
                try:
                    # Try to get traceback from exception
                    if hasattr(exc, '__traceback__') and exc.__traceback__:
                        logger.debug(f"Traceback for exception {i+1}:\n{traceback.format_exception(type(exc), exc, exc.__traceback__)}")
                    else:
                        logger.debug(f"No traceback available for exception {i+1}")
                except Exception as tb_error:
                    logger.warning(f"Could not format traceback: {tb_error}", exc_info=True)
            # Also try to get the full ExceptionGroup traceback
            try:
                if hasattr(eg, '__traceback__') and eg.__traceback__:
                    logger.debug(f"Full ExceptionGroup traceback:\n{traceback.format_exception(type(eg), eg, eg.__traceback__)}")
            except Exception:
                pass
    except BrokenPipeError:
        # Normal when client disconnects (non-ExceptionGroup case, older Python)
        pass
    except KeyboardInterrupt:
        # User interrupt
        pass
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        remove_pid_file()


if __name__ == "__main__":
    asyncio.run(main())

