#!/usr/bin/env python3
"""
UNITARES Governance MCP Server - SSE (Server-Sent Events) Transport

Multi-client support! Multiple agents (Cursor, Claude Desktop, etc.) can connect
simultaneously and share state via this single server instance.

Usage:
    python src/mcp_server_sse.py [--port PORT] [--host HOST]
    
    Default: http://127.0.0.1:8765/sse

Configuration (in claude_desktop_config.json or cursor mcp config):
    {
      "governance-monitor-v1": {
        "url": "http://127.0.0.1:8765/sse"
      }
    }

Features vs stdio transport:
    - Multiple clients share single server instance
    - Shared state across all agents (knowledge graph, dialectic, etc.)
    - Real multi-agent dialectic (agents can actually review each other!)
    - Persistent service (survives client restarts)
    - Connection tracking (see who's connected)
"""

from __future__ import annotations

import sys
import os
import asyncio
import argparse
import signal
import atexit
import fcntl
import time
from pathlib import Path
from typing import Any, Dict, Set, Optional
from datetime import datetime
from contextlib import asynccontextmanager
import json
import traceback
import uuid

# Prometheus metrics
from prometheus_client import Counter, Gauge, Histogram, REGISTRY, generate_latest, CONTENT_TYPE_LATEST

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src._imports import ensure_project_root
project_root = ensure_project_root()

from src.logging_utils import get_logger
logger = get_logger(__name__)

# Process management for SSE server (prevent multiple instances)
SSE_PID_FILE = Path(project_root) / "data" / ".mcp_server_sse.pid"
SSE_LOCK_FILE = Path(project_root) / "data" / ".mcp_server_sse.lock"
CURRENT_PID = os.getpid()

# Server readiness flag - prevents "request before initialization" errors
# when multiple clients reconnect simultaneously after a server restart
SERVER_READY = False
SERVER_STARTUP_TIME = None

# ============================================================================
# Prometheus Metrics Definitions
# ============================================================================

# Tool call metrics
TOOL_CALLS_TOTAL = Counter(
    'unitares_tool_calls_total',
    'Total tool calls',
    ['tool_name', 'status']  # status: success, error
)

TOOL_CALL_DURATION = Histogram(
    'unitares_tool_call_duration_seconds',
    'Tool call duration in seconds',
    ['tool_name'],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

# Connection metrics
CONNECTIONS_ACTIVE = Gauge(
    'unitares_connections_active',
    'Number of active SSE connections'
)

# Agent metrics
AGENTS_TOTAL = Gauge(
    'unitares_agents_total',
    'Total agents by status',
    ['status']  # active, paused, archived, waiting_input
)

# Governance metrics
GOVERNANCE_DECISIONS = Counter(
    'unitares_governance_decisions_total',
    'Total governance decisions',
    ['action']  # proceed, pause, etc.
)

GOVERNANCE_ENERGY = Gauge(
    'unitares_governance_energy',
    'Current governance energy level',
    ['agent_id']
)

GOVERNANCE_COHERENCE = Gauge(
    'unitares_governance_coherence',
    'Current governance coherence',
    ['agent_id']
)

# Knowledge graph metrics
KNOWLEDGE_NODES_TOTAL = Gauge(
    'unitares_knowledge_nodes_total',
    'Total knowledge graph nodes'
)

# Dialectic metrics
DIALECTIC_SESSIONS_ACTIVE = Gauge(
    'unitares_dialectic_sessions_active',
    'Number of active dialectic sessions'
)

# Server info (static)
SERVER_INFO = Gauge(
    'unitares_server_info',
    'Server version info',
    ['version']
)

# Try to import MCP SDK
try:
    from mcp.server import FastMCP
    from mcp.server.fastmcp import Context
    from mcp.types import TextContent
    MCP_SDK_AVAILABLE = True
except ImportError as e:
    MCP_SDK_AVAILABLE = False
    print(f"Error: MCP SDK not available: {e}", file=sys.stderr)
    print("Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

# Import dispatch_tool from handlers (reuse all existing tool logic)
from src.mcp_handlers import dispatch_tool, TOOL_HANDLERS

# Tool schemas are now in src/tool_schemas.py (shared module)

# ============================================================================
# Connection Tracking for Multi-Agent Awareness
# ============================================================================

# Prometheus metrics for connection tracking
CONNECTION_EVENTS = Counter(
    'unitares_connection_events_total',
    'Connection lifecycle events',
    ['event_type']  # connected, disconnected, reconnected, stale_cleaned
)

CONNECTION_DURATION = Histogram(
    'unitares_connection_duration_seconds',
    'Duration of client connections',
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600)
)

CONNECTION_HEALTH = Gauge(
    'unitares_connection_health',
    'Connection health status (1=healthy, 0=unhealthy)',
    ['client_id']
)


class ConnectionTracker:
    """
    Enhanced connection tracker for multi-agent awareness and reliability.
    
    Features:
    - Reconnection tracking (detects clients that reconnect frequently)
    - Connection health monitoring (idle time, request rate)
    - Detailed diagnostics for debugging
    - History for forensics
    """
    
    def __init__(self):
        self.connections: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        # Track connection history for diagnostics (limited to last 100 events)
        self._history: list = []
        self._max_history = 100
        # Track reconnections by base client ID (IP)
        self._reconnection_counts: Dict[str, int] = {}
        # Track disconnection reasons
        self._disconnection_reasons: Dict[str, str] = {}
    
    def _log_event(self, event_type: str, client_id: str, details: Dict[str, Any] = None):
        """Log connection event to history and metrics."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "event": event_type,
            "client_id": client_id,
            "details": details or {}
        }
        self._history.append(event)
        # Trim history if needed
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        
        # Update Prometheus metrics
        CONNECTION_EVENTS.labels(event_type=event_type).inc()
        
        # Log at appropriate level
        if event_type in ("disconnected", "stale_cleaned"):
            logger.info(f"[CONNECTION] {event_type}: {client_id} - {details}")
        else:
            logger.info(f"[CONNECTION] {event_type}: {client_id}")
    
    def _get_base_client_id(self, client_id: str) -> str:
        """Extract base client ID (IP) for reconnection tracking."""
        # client_id format is typically "IP:PORT" or "IP:PORT:uuid"
        parts = client_id.split(":")
        return parts[0] if parts else client_id
    
    async def add_connection(self, client_id: str, metadata: Dict[str, Any] = None):
        """Register a new client connection with reconnection detection."""
        now = datetime.now()
        now_iso = now.isoformat()
        base_id = self._get_base_client_id(client_id)
        
        # Track reconnection
        reconnect_count = self._reconnection_counts.get(base_id, 0)
        is_reconnect = reconnect_count > 0
        
        connection_data = {
            "connected_at": now_iso,
            "last_activity": now_iso,
            "metadata": metadata or {},
            "request_count": 0,
            "reconnect_count": reconnect_count,
            "health_status": "healthy",
            "last_health_check": now_iso
        }
        
        async with self._lock:
            # Check if connection already exists (collision detection)
            if client_id in self.connections:
                existing = self.connections[client_id]
                prev_connected = existing.get('connected_at', 'unknown')
                prev_requests = existing.get('request_count', 0)
                
                # Calculate duration of previous connection
                try:
                    prev_connected_dt = datetime.fromisoformat(prev_connected)
                    duration = (now - prev_connected_dt).total_seconds()
                    CONNECTION_DURATION.observe(duration)
                except (ValueError, TypeError):
                    duration = 0
                
                logger.warning(
                    f"[CONNECTION] Client ID collision: '{client_id}' replacing existing. "
                    f"Previous: connected={prev_connected}, requests={prev_requests}, duration={duration:.1f}s"
                )
                
                # Increment reconnection count
                self._reconnection_counts[base_id] = reconnect_count + 1
                connection_data["reconnect_count"] = reconnect_count + 1
                
                self._log_event("reconnected", client_id, {
                    "previous_duration_seconds": duration,
                    "previous_requests": prev_requests,
                    "reconnect_count": reconnect_count + 1
                })
            else:
                self._reconnection_counts[base_id] = reconnect_count + 1
                event_type = "reconnected" if is_reconnect else "connected"
                self._log_event(event_type, client_id, {
                    "user_agent": (metadata or {}).get("user_agent", "unknown"),
                    "reconnect_count": reconnect_count if is_reconnect else 0
                })
            
            self.connections[client_id] = connection_data
            
            # Update Prometheus gauge
            CONNECTIONS_ACTIVE.set(len(self.connections))
            CONNECTION_HEALTH.labels(client_id=client_id).set(1)
            
            logger.info(
                f"[CONNECTION] Client {'reconnected' if is_reconnect else 'connected'}: "
                f"{client_id} (total: {len(self.connections)}, reconnects: {connection_data['reconnect_count']})"
            )
    
    async def remove_connection(self, client_id: str, reason: str = "client_disconnect"):
        """Remove a client connection with reason tracking."""
        async with self._lock:
            if client_id in self.connections:
                conn_data = self.connections[client_id]
                connected_at = conn_data.get("connected_at")
                request_count = conn_data.get("request_count", 0)
                
                # Calculate connection duration
                try:
                    connected_dt = datetime.fromisoformat(connected_at)
                    duration = (datetime.now() - connected_dt).total_seconds()
                    CONNECTION_DURATION.observe(duration)
                except (ValueError, TypeError):
                    duration = 0
                
                del self.connections[client_id]
                self._disconnection_reasons[client_id] = reason
                
                # Update Prometheus
                CONNECTIONS_ACTIVE.set(len(self.connections))
                try:
                    CONNECTION_HEALTH.remove(client_id)
                except Exception:
                    pass  # Label may not exist
                
                self._log_event("disconnected", client_id, {
                    "reason": reason,
                    "duration_seconds": duration,
                    "request_count": request_count
                })
                
                logger.info(
                    f"[CONNECTION] Client disconnected: {client_id} "
                    f"(reason={reason}, duration={duration:.1f}s, requests={request_count}, total: {len(self.connections)})"
                )
    
    async def update_activity(self, client_id: str):
        """Update last activity timestamp for a client."""
        now = datetime.now().isoformat()
        
        async with self._lock:
            if client_id in self.connections:
                self.connections[client_id]["last_activity"] = now
                self.connections[client_id]["request_count"] += 1
    
    async def check_health(self, client_id: str) -> Dict[str, Any]:
        """Check health of a specific connection."""
        now = datetime.now()
        
        async with self._lock:
            if client_id not in self.connections:
                return {"healthy": False, "reason": "not_connected"}
            
            conn = self.connections[client_id]
            
            # Check idle time
            try:
                last_activity = datetime.fromisoformat(conn["last_activity"])
                idle_seconds = (now - last_activity).total_seconds()
            except (ValueError, TypeError):
                idle_seconds = float('inf')
            
            # Check connection age
            try:
                connected_at = datetime.fromisoformat(conn["connected_at"])
                age_seconds = (now - connected_at).total_seconds()
            except (ValueError, TypeError):
                age_seconds = 0
            
            # Determine health status
            issues = []
            if idle_seconds > 300:  # 5 minutes idle
                issues.append(f"idle for {idle_seconds:.0f}s")
            if conn.get("reconnect_count", 0) > 5:
                issues.append(f"reconnected {conn['reconnect_count']} times")
            
            healthy = len(issues) == 0
            health_status = "healthy" if healthy else "degraded"
            
            # Update stored health status
            conn["health_status"] = health_status
            conn["last_health_check"] = now.isoformat()
            
            # Update Prometheus
            CONNECTION_HEALTH.labels(client_id=client_id).set(1 if healthy else 0)
            
            return {
                "healthy": healthy,
                "status": health_status,
                "idle_seconds": idle_seconds,
                "age_seconds": age_seconds,
                "request_count": conn.get("request_count", 0),
                "reconnect_count": conn.get("reconnect_count", 0),
                "issues": issues if issues else None
            }
    
    async def cleanup_stale_connections(self, max_idle_minutes: float = 30.0):
        """Remove connections that haven't been active recently."""
        now = datetime.now()
        stale = []
        
        # First pass: identify stale connections
        async with self._lock:
            for client_id, conn_data in self.connections.items():
                last_activity_str = conn_data.get("last_activity")
                if last_activity_str:
                    try:
                        last_activity = datetime.fromisoformat(last_activity_str)
                        idle_minutes = (now - last_activity).total_seconds() / 60
                        if idle_minutes > max_idle_minutes:
                            stale.append((client_id, idle_minutes))
                    except (ValueError, TypeError):
                        stale.append((client_id, float('inf')))
        
        # Second pass: remove stale connections
        if stale:
            for client_id, idle_mins in stale:
                await self.remove_connection(client_id, reason=f"stale_idle_{idle_mins:.1f}min")
            
            self._log_event("stale_cleaned", "batch", {
                "count": len(stale),
                "clients": [c[0] for c in stale]
            })
            
            logger.info(f"[CONNECTION] Cleaned up {len(stale)} stale connection(s)")
    
    async def get_diagnostics(self) -> Dict[str, Any]:
        """Get comprehensive connection diagnostics."""
        now = datetime.now()
        
        async with self._lock:
            clients = []
            for client_id, conn in self.connections.items():
                try:
                    connected_at = datetime.fromisoformat(conn["connected_at"])
                    last_activity = datetime.fromisoformat(conn["last_activity"])
                    age = (now - connected_at).total_seconds()
                    idle = (now - last_activity).total_seconds()
                except (ValueError, TypeError):
                    age = idle = 0
                
                clients.append({
                    "client_id": client_id,
                    "user_agent": conn.get("metadata", {}).get("user_agent", "unknown"),
                    "connected_at": conn["connected_at"],
                    "age_seconds": age,
                    "idle_seconds": idle,
                    "request_count": conn.get("request_count", 0),
                    "reconnect_count": conn.get("reconnect_count", 0),
                    "health_status": conn.get("health_status", "unknown")
                })
            
            # Sort by most recent activity
            clients.sort(key=lambda x: x["idle_seconds"])
            
            # Get recent events
            recent_events = self._history[-20:] if self._history else []
            
            # Identify potentially problematic clients
            problematic = [c for c in clients if c["reconnect_count"] > 3 or c["idle_seconds"] > 300]
            
            return {
                "timestamp": now.isoformat(),
                "total_connections": len(self.connections),
                "connections": clients,
                "recent_events": recent_events,
                "problematic_clients": problematic,
                "reconnection_summary": dict(self._reconnection_counts),
                "health_summary": {
                    "healthy": len([c for c in clients if c["health_status"] == "healthy"]),
                    "degraded": len([c for c in clients if c["health_status"] != "healthy"]),
                }
            }
    
    def get_connected_clients(self) -> Dict[str, Dict[str, Any]]:
        """Get all connected clients."""
        return dict(self.connections)
    
    @property
    def count(self) -> int:
        """Number of connected clients."""
        return len(self.connections)


# Global connection tracker
connection_tracker = ConnectionTracker()

def _session_id_from_ctx(ctx: Context | None) -> str | None:
    """
    Resolve a stable per-client session identifier for identity binding.

    Prefer FastMCP's Context.client_id when available. If absent, attempt to
    read the Starlette request state set by ConnectionTrackingMiddleware.
    """
    if ctx is None:
        return None
    try:
        if ctx.client_id:
            return ctx.client_id
    except Exception:
        pass
    try:
        req = ctx.request_context.request
        if req is not None and hasattr(req, "state") and hasattr(req.state, "governance_client_id"):
            return getattr(req.state, "governance_client_id")
    except Exception:
        pass
    return None


# ============================================================================
# Server Version (sync with VERSION file)
# ============================================================================

def _load_version():
    """Load version from VERSION file."""
    version_file = project_root / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "2.3.0"

SERVER_VERSION = _load_version()


# ============================================================================
# FastMCP Server Setup
# ============================================================================

# Create the FastMCP server
mcp = FastMCP(
    name="governance-monitor-v1",
)


# Custom decorator that disables outputSchema to avoid schema validation errors
# FastMCP auto-generates outputSchema based on return type, but our tools return
# complex dicts that don't match the simple {"result": string} schema.
def tool_no_schema(description: str):
    """Decorator for registering tools without outputSchema validation."""
    return mcp.tool(description=description, structured_output=False)


# ============================================================================
# Tool Registration Helper (Optimized)
# ============================================================================

# Cache tool wrappers to avoid recreating functions on every call
# Max size: 100 tools (future-proofing for dynamic tool registration)
# Current tool count: ~51 tools, so plenty of headroom
_MAX_TOOL_WRAPPER_CACHE_SIZE = 100
_tool_wrappers_cache: Dict[str, callable] = {}

def get_tool_wrapper(tool_name: str):
    """
    Get cached tool wrapper or create new one.

    Optimized version that caches wrappers to avoid function creation overhead.
    Each wrapper calls dispatch_tool which routes to @mcp_tool decorated handlers.

    Cache has size limit (100 tools) to prevent unbounded growth if dynamic
    tool registration is added in the future.
    """
    if tool_name not in _tool_wrappers_cache:
        # Check cache size limit (future-proofing)
        if len(_tool_wrappers_cache) >= _MAX_TOOL_WRAPPER_CACHE_SIZE:
            logger.warning(
                f"Tool wrapper cache size limit reached ({_MAX_TOOL_WRAPPER_CACHE_SIZE}). "
                f"Cache contains {len(_tool_wrappers_cache)} tools. "
                f"Consider increasing _MAX_TOOL_WRAPPER_CACHE_SIZE if dynamic tool registration is used."
            )
            # Don't fail - allow cache to grow slightly beyond limit
            # But log warning for visibility
        async def wrapper(**kwargs):
            start_time = time.time()
            try:
                # Dispatch to existing handler (which has @mcp_tool timeout protection)
                result = await dispatch_tool(tool_name, kwargs)

                # Record successful call metrics
                duration = time.time() - start_time
                TOOL_CALLS_TOTAL.labels(tool_name=tool_name, status="success").inc()
                TOOL_CALL_DURATION.labels(tool_name=tool_name).observe(duration)

                if result is None:
                    TOOL_CALLS_TOTAL.labels(tool_name=tool_name, status="not_found").inc()
                    return {"success": False, "error": f"Tool '{tool_name}' not found"}

                # Extract structured payload from TextContent response
                # Many MCP clients enforce outputSchema and require structured output.
                # Our handlers return JSON in TextContent.text; parse it and return an object.
                if isinstance(result, (list, tuple)) and len(result) > 0:
                    first_result = result[0]
                    if hasattr(first_result, 'text'):
                        text = first_result.text
                        try:
                            return json.loads(text)
                        except Exception:
                            return {"success": True, "text": text}

                return {"success": True, "result": str(result)}

            except (KeyboardInterrupt, SystemExit):
                # Let system exceptions propagate (for proper shutdown)
                # These should not be caught by error handlers
                raise
            except Exception as e:
                # Record error metrics
                duration = time.time() - start_time
                TOOL_CALLS_TOTAL.labels(tool_name=tool_name, status="error").inc()
                TOOL_CALL_DURATION.labels(tool_name=tool_name).observe(duration)

                # Log error for visibility
                # Note: @mcp_tool decorator on handlers also catches exceptions,
                # but dispatch_tool may raise before reaching handler (e.g., rate limit)
                logger.error(f"Error in tool wrapper {tool_name}: {e}", exc_info=True)
                return {"success": False, "error": str(e), "error_type": type(e).__name__}

        wrapper.__name__ = tool_name
        wrapper.__doc__ = f"Wrapper for {tool_name} tool"
        _tool_wrappers_cache[tool_name] = wrapper

    return _tool_wrappers_cache[tool_name]


# ============================================================================
# Register Core Tools with FastMCP
# ============================================================================

# Health & Admin tools
@tool_no_schema(description="🚀 SIMPLEST ONBOARDING - hello() shows last active, hello(agent_id='name') to register/resume")
async def hello(agent_id: str = None) -> dict:
    """hello() asks 'is this you?', hello(agent_id='name') registers or resumes that agent."""
    if agent_id:
        return await get_tool_wrapper("hello")(agent_id=agent_id)
    else:
        return await get_tool_wrapper("hello")()

@tool_no_schema(description="🔍 IDENTITY RECOVERY - Find yourself after session restart. No args needed.")
async def who_am_i() -> dict:
    """Lost? This shows recent agents with rich context so you can recognize yourself."""
    return await get_tool_wrapper("who_am_i")()

@tool_no_schema(description="Quick health check - returns system status, version, and component health")
async def health_check() -> dict:
    return await get_tool_wrapper("health_check")()

@tool_no_schema(description="Get MCP server version, process info, and health status")
async def get_server_info() -> dict:
    return await get_tool_wrapper("get_server_info")()

@tool_no_schema(description="Get comprehensive workspace health status")
async def get_workspace_health() -> dict:
    return await get_tool_wrapper("get_workspace_health")()

@tool_no_schema(description="List all available governance tools with descriptions and categories")
async def list_tools(
    essential_only: bool = False,
    include_advanced: bool = True,
    tier: str = "all",
    lite: bool = False,
) -> dict:
    return await get_tool_wrapper("list_tools")(
        essential_only=essential_only,
        include_advanced=include_advanced,
        tier=tier,
        lite=lite,
    )


@tool_no_schema(description="Describe a single tool (full description + full schema) on demand")
async def describe_tool(
    tool_name: str,
    include_schema: bool = True,
    include_full_description: bool = True,
    lite: bool = True,
) -> str:
    return await get_tool_wrapper("describe_tool")(
        tool_name=tool_name,
        include_schema=include_schema,
        include_full_description=include_full_description,
        lite=lite,
    )

@tool_no_schema(description="🚀 Streamlined onboarding - One call to get started! Checks if agent exists, creates/binds if needed, returns ready-to-use credentials.")
async def quick_start(
    agent_id: str = None,
    auto_bind: bool = True,
) -> dict:
    """quick_start(agent_id) - Streamlined onboarding with auto-creation and binding"""
    return await get_tool_wrapper("quick_start")(
        agent_id=agent_id,
        auto_bind=auto_bind,
    )


# Core Governance tools
@tool_no_schema(description="Share your work and get supportive feedback. Main governance update tool.")
async def process_agent_update(
    agent_id: str,
    api_key: str = None,
    complexity: float = 0.5,
    parameters: list = None,
    ethical_drift: list = None,
    response_text: str = None,
    confidence: Optional[float] = None,
    task_type: str = "mixed",
    auto_export_on_significance: bool = False,
    response_mode: str = "full",
) -> str:
    args = {
        "agent_id": agent_id,
        "complexity": complexity,
        "parameters": parameters or [],
        "ethical_drift": ethical_drift or [0, 0, 0],
        "task_type": task_type,
        "auto_export_on_significance": auto_export_on_significance,
        "response_mode": response_mode,
    }
    # IMPORTANT: If confidence is omitted, allow the governance monitor to derive it
    # from thermodynamic state. Do not default to 1.0 (overconfidence bug).
    if confidence is not None:
        args["confidence"] = confidence
    if api_key:
        args["api_key"] = api_key
    if response_text:
        args["response_text"] = response_text
    return await get_tool_wrapper("process_agent_update")(**args)

@tool_no_schema(description="Get current governance state and metrics for an agent without updating state")
async def get_governance_metrics(agent_id: str, include_state: bool = False) -> str:
    return await get_tool_wrapper("get_governance_metrics")(agent_id=agent_id, include_state=include_state)

@tool_no_schema(description="Dry-run governance cycle. Returns decision without persisting state.")
async def simulate_update(
    agent_id: str,
    api_key: str = None,
    complexity: float = 0.5,
    parameters: list = None,
    ethical_drift: list = None,
    response_text: str = None,
    confidence: Optional[float] = None
) -> str:
    args = {
        "agent_id": agent_id,
        "complexity": complexity,
        "parameters": parameters or [],
        "ethical_drift": ethical_drift or [0, 0, 0]
    }
    if confidence is not None:
        args["confidence"] = confidence
    if api_key:
        args["api_key"] = api_key
    if response_text:
        args["response_text"] = response_text
    return await get_tool_wrapper("simulate_update")(**args)

# Agent Lifecycle tools
@tool_no_schema(description="List all agents currently being monitored with lifecycle metadata and health status. By default, test/demo agents are filtered out for cleaner views.")
async def list_agents(
    status_filter: str = "all",
    include_metrics: bool = True,
    loaded_only: bool = False,
    grouped: bool = True,
    summary_only: bool = False,
    standardized: bool = True,
    include_test_agents: bool = False,
    offset: int = 0,
    limit: int = None
) -> str:
    args = {
        "status_filter": status_filter,
        "include_metrics": include_metrics,
        "loaded_only": loaded_only,
        "grouped": grouped,
        "summary_only": summary_only,
        "standardized": standardized,
        "include_test_agents": include_test_agents,
        "offset": offset
    }
    if limit is not None:
        args["limit"] = limit
    return await get_tool_wrapper("list_agents")(**args)

@tool_no_schema(description="Get or generate API key for an agent")
async def get_agent_api_key(agent_id: str, regenerate: bool = False, api_key: str = None, ctx: Context = None) -> str:
    session_id = _session_id_from_ctx(ctx)
    args: Dict[str, Any] = {"agent_id": agent_id, "regenerate": regenerate}
    if api_key is not None:
        args["api_key"] = api_key
    if session_id:
        args["client_session_id"] = session_id
    return await get_tool_wrapper("get_agent_api_key")(**args)

@tool_no_schema(description="Bind this session to an agent identity (SSE-safe; scoped per connected client)")
async def bind_identity(agent_id: str, api_key: str | None = None, ctx: Context = None) -> str:
    session_id = _session_id_from_ctx(ctx)
    args: Dict[str, Any] = {"agent_id": agent_id}
    if api_key is not None:
        args["api_key"] = api_key
    if session_id:
        # Avoid collision with dialectic session_id arguments used by submit_* tools.
        args["client_session_id"] = session_id
    return await get_tool_wrapper("bind_identity")(**args)

@tool_no_schema(description="Recall identity bound to this session (SSE-safe; scoped per connected client)")
async def recall_identity(ctx: Context = None) -> str:
    session_id = _session_id_from_ctx(ctx)
    args: Dict[str, Any] = {}
    if session_id:
        args["client_session_id"] = session_id
    return await get_tool_wrapper("recall_identity")(**args)

@tool_no_schema(description="Get complete metadata for an agent")
async def get_agent_metadata(agent_id: str) -> str:
    return await get_tool_wrapper("get_agent_metadata")(agent_id=agent_id)


# Knowledge Graph tools
@tool_no_schema(description="Store knowledge discovery/discoveries in graph - single or batch (max 10) - fast, non-blocking, transparent")
async def store_knowledge_graph(
    agent_id: str,
    # Single-discovery mode (original)
    discovery_type: str = None,
    summary: str = None,
    details: str = None,
    tags: list = None,
    severity: str = None,
    related_files: list = None,
    auto_link_related: bool = False,
    response_to: dict = None,
    # Batch mode
    discoveries: list = None,
    api_key: str = None
) -> str:
    # Batch mode: pass through discoveries array exactly as provided
    if discoveries is not None:
        args = {"agent_id": agent_id, "discoveries": discoveries}
        if api_key:
            args["api_key"] = api_key
        return await get_tool_wrapper("store_knowledge_graph")(**args)

    # Single mode: keep backward compatibility with prior signature
    args = {"agent_id": agent_id, "auto_link_related": auto_link_related}
    if discovery_type is not None:
        args["discovery_type"] = discovery_type
    if summary is not None:
        args["summary"] = summary
    if details:
        args["details"] = details
    if tags:
        args["tags"] = tags
    if severity:
        args["severity"] = severity
    if related_files:
        args["related_files"] = related_files
    if response_to:
        args["response_to"] = response_to
    if api_key:
        args["api_key"] = api_key
    return await get_tool_wrapper("store_knowledge_graph")(**args)

@tool_no_schema(description="Search knowledge graph - indexed filters, optional full-text query when SQLite backend is active")
async def search_knowledge_graph(
    agent_id: str = None,
    tags: list = None,
    query: str = None,
    discovery_type: str = None,
    severity: str = None,
    status: str = None,
    include_details: bool = False,
    limit: int = 100,
    semantic: bool = False,
    min_similarity: float = 0.3
) -> str:
    args = {"limit": limit, "include_details": include_details}
    if agent_id:
        args["agent_id"] = agent_id
    if tags:
        args["tags"] = tags
    if query:
        args["query"] = query
    if discovery_type:
        args["discovery_type"] = discovery_type
    if severity:
        args["severity"] = severity
    if status:
        args["status"] = status
    if semantic:
        args["semantic"] = semantic
        args["min_similarity"] = min_similarity
    return await get_tool_wrapper("search_knowledge_graph")(**args)

@tool_no_schema(description="Get full details for a specific discovery")
async def get_discovery_details(discovery_id: str) -> str:
    return await get_tool_wrapper("get_discovery_details")(discovery_id=discovery_id)

@tool_no_schema(description="Graph traversal: get discoveries related to a given discovery (edges if SQLite; best-effort fallback if JSON)")
async def get_related_discoveries_graph(
    discovery_id: str,
    edge_types: list = None,
    include_details: bool = False,
    limit: int = 20
) -> str:
    args = {"discovery_id": discovery_id, "include_details": include_details, "limit": limit}
    if edge_types:
        args["edge_types"] = edge_types
    return await get_tool_wrapper("get_related_discoveries_graph")(**args)

@tool_no_schema(description="Graph traversal: get response chain for a discovery (SQLite recursive CTE; best-effort fallback if JSON)")
async def get_response_chain_graph(
    discovery_id: str,
    max_depth: int = 10,
    include_details: bool = False
) -> str:
    args = {"discovery_id": discovery_id, "max_depth": max_depth, "include_details": include_details}
    return await get_tool_wrapper("get_response_chain_graph")(**args)

@tool_no_schema(description="List knowledge graph statistics")
async def list_knowledge_graph() -> str:
    return await get_tool_wrapper("list_knowledge_graph")()

@tool_no_schema(description="Leave a quick note in the knowledge graph")
async def leave_note(agent_id: str, text: str, tags: list = None, response_to: dict = None) -> str:
    args = {"agent_id": agent_id, "text": text}
    if tags:
        args["tags"] = tags
    if response_to:
        args["response_to"] = response_to
    return await get_tool_wrapper("leave_note")(**args)


# Dialectic tools (for multi-agent recovery)
@tool_no_schema(description="Request a dialectic review for a paused/critical agent")
async def request_dialectic_review(
    agent_id: str,
    api_key: str = None,
    reason: str = "Circuit breaker triggered",
    discovery_id: str = None,
    dispute_type: str = None,
    reviewer_agent_id: str = None,
    auto_progress: bool = False,
    reviewer_mode: str = "peer",
    root_cause: str = None,
    proposed_conditions: list = None,
    reasoning: str = None,
    ctx: Context = None,
) -> str:
    args = {"agent_id": agent_id, "reason": reason, "auto_progress": auto_progress, "reviewer_mode": reviewer_mode}
    session_id = _session_id_from_ctx(ctx)
    if session_id:
        args["client_session_id"] = session_id
    if api_key:
        args["api_key"] = api_key
    if discovery_id:
        args["discovery_id"] = discovery_id
    if dispute_type:
        args["dispute_type"] = dispute_type
    if reviewer_agent_id:
        args["reviewer_agent_id"] = reviewer_agent_id
    if root_cause:
        args["root_cause"] = root_cause
    if proposed_conditions:
        args["proposed_conditions"] = proposed_conditions
    if reasoning:
        args["reasoning"] = reasoning
    return await get_tool_wrapper("request_dialectic_review")(**args)

@tool_no_schema(description="Request a collaborative exploration session between two active agents")
async def request_exploration_session(
    agent_id: str,
    api_key: str = None,
    partner_agent_id: str = None,
    topic: str = None,
    ctx: Context = None,
) -> str:
    args = {"agent_id": agent_id}
    session_id = _session_id_from_ctx(ctx)
    if session_id:
        args["client_session_id"] = session_id
    if api_key:
        args["api_key"] = api_key
    if partner_agent_id:
        args["partner_agent_id"] = partner_agent_id
    if topic:
        args["topic"] = topic
    return await get_tool_wrapper("request_exploration_session")(**args)

@tool_no_schema(description="Paused agent submits thesis in dialectic recovery")
async def submit_thesis(
    session_id: str,
    agent_id: str,
    api_key: str = None,
    root_cause: str = None,
    proposed_conditions: list = None,
    reasoning: str = None,
    ctx: Context = None,
) -> str:
    args = {"session_id": session_id, "agent_id": agent_id}
    client_session_id = _session_id_from_ctx(ctx)
    if client_session_id:
        args["client_session_id"] = client_session_id
    if api_key:
        args["api_key"] = api_key
    if root_cause:
        args["root_cause"] = root_cause
    if proposed_conditions:
        args["proposed_conditions"] = proposed_conditions
    if reasoning:
        args["reasoning"] = reasoning
    return await get_tool_wrapper("submit_thesis")(**args)

@tool_no_schema(description="Reviewer agent submits antithesis in dialectic recovery")
async def submit_antithesis(
    session_id: str,
    agent_id: str,
    api_key: str = None,
    observed_metrics: dict = None,
    concerns: list = None,
    reasoning: str = None,
    ctx: Context = None,
) -> str:
    args = {"session_id": session_id, "agent_id": agent_id}
    client_session_id = _session_id_from_ctx(ctx)
    if client_session_id:
        args["client_session_id"] = client_session_id
    if api_key:
        args["api_key"] = api_key
    if observed_metrics:
        args["observed_metrics"] = observed_metrics
    if concerns:
        args["concerns"] = concerns
    if reasoning:
        args["reasoning"] = reasoning
    return await get_tool_wrapper("submit_antithesis")(**args)

@tool_no_schema(description="Either agent submits synthesis proposal during negotiation")
async def submit_synthesis(
    session_id: str,
    agent_id: str,
    api_key: str = None,
    proposed_conditions: list = None,
    root_cause: str = None,
    reasoning: str = None,
    agrees: bool = False,
    ctx: Context = None,
) -> str:
    args = {"session_id": session_id, "agent_id": agent_id, "agrees": agrees}
    client_session_id = _session_id_from_ctx(ctx)
    if client_session_id:
        args["client_session_id"] = client_session_id
    if api_key:
        args["api_key"] = api_key
    if proposed_conditions:
        args["proposed_conditions"] = proposed_conditions
    if root_cause:
        args["root_cause"] = root_cause
    if reasoning:
        args["reasoning"] = reasoning
    return await get_tool_wrapper("submit_synthesis")(**args)

@tool_no_schema(description="Get current state of a dialectic session")
async def get_dialectic_session(session_id: str = None, agent_id: str = None, check_timeout: bool = True) -> str:
    args = {"check_timeout": check_timeout}
    if session_id:
        args["session_id"] = session_id
    if agent_id:
        args["agent_id"] = agent_id
    return await get_tool_wrapper("get_dialectic_session")(**args)

@tool_no_schema(description="Nudge a dialectic/exploration session that appears stuck (reports next actor + idle time; optional audit event)")
async def nudge_dialectic_session(session_id: str, post: bool = False, note: str = None, agent_id: str = None, ctx: Context = None) -> str:
    args = {"session_id": session_id, "post": post}
    session_key = _session_id_from_ctx(ctx)
    if session_key:
        args["client_session_id"] = session_key
    if note:
        args["note"] = note
    if agent_id:
        args["agent_id"] = agent_id
    return await get_tool_wrapper("nudge_dialectic_session")(**args)

# ============================================================================
# SSE-Specific Tools (Multi-Agent Awareness)
# ============================================================================

@tool_no_schema(description="""
Get information about connected clients (SSE-only feature).
Shows all clients currently connected to this shared governance server.
Useful for multi-agent coordination and seeing who's active.

Returns:
{
  "success": true,
  "transport": "SSE",
  "server_version": "string",
  "connected_clients": {
    "client_id": {
      "connected_at": "ISO timestamp",
      "last_activity": "ISO timestamp",
      "request_count": int
    }
  },
  "total_clients": int,
  "message": "string"
}
""")
async def get_connected_clients() -> str:
    """Get information about connected clients (SSE-only)."""
    clients = connection_tracker.get_connected_clients()
    
    # Enrich with health info
    enriched_clients = {}
    for client_id, data in clients.items():
        health = await connection_tracker.check_health(client_id)
        enriched_clients[client_id] = {
            **data,
            "health": health
        }
    
    return json.dumps({
        "success": True,
        "transport": "SSE",
        "server_version": SERVER_VERSION,
        "connected_clients": enriched_clients,
        "total_clients": connection_tracker.count,
        "message": f"{connection_tracker.count} client(s) currently connected"
    }, indent=2)


@tool_no_schema(description="""Get detailed connection diagnostics for debugging reliability issues.

Returns comprehensive information about all connections including:
- Connection health status (healthy/degraded)
- Reconnection history (how many times each client reconnected)
- Recent connection events (connects, disconnects, cleanups)
- Problematic clients (frequent reconnects, stale connections)

Use this tool when experiencing connection instability between clients.
""")
async def get_connection_diagnostics() -> str:
    """Get comprehensive connection diagnostics for debugging."""
    diagnostics = await connection_tracker.get_diagnostics()
    
    return json.dumps({
        "success": True,
        "diagnostics": diagnostics,
        "recommendations": _generate_connection_recommendations(diagnostics)
    }, indent=2)


def _generate_connection_recommendations(diagnostics: Dict[str, Any]) -> list:
    """Generate actionable recommendations based on connection diagnostics."""
    recommendations = []
    
    # Check for frequent reconnections
    for client_id, count in diagnostics.get("reconnection_summary", {}).items():
        if count > 5:
            recommendations.append({
                "severity": "warning",
                "issue": f"Client {client_id} has reconnected {count} times",
                "suggestion": "Check network stability or client configuration. High reconnection rate may indicate SSE transport issues."
            })
    
    # Check for problematic clients
    for client in diagnostics.get("problematic_clients", []):
        if client.get("idle_seconds", 0) > 300:
            recommendations.append({
                "severity": "info",
                "issue": f"Client {client['client_id']} idle for {client['idle_seconds']:.0f}s",
                "suggestion": "Connection may be stale. Will be auto-cleaned after 30 min idle."
            })
    
    # General health
    health = diagnostics.get("health_summary", {})
    if health.get("degraded", 0) > 0:
        recommendations.append({
            "severity": "warning",
            "issue": f"{health['degraded']} connection(s) in degraded state",
            "suggestion": "Review recent_events for disconnection patterns."
        })
    
    if not recommendations:
        recommendations.append({
            "severity": "ok",
            "issue": "No connection issues detected",
            "suggestion": "All connections are healthy."
        })
    
    return recommendations


# Observability tools
@tool_no_schema(description="Observe another agent's governance state with pattern analysis")
async def observe_agent(
    agent_id: str,
    include_history: bool = True,
    analyze_patterns: bool = True
) -> str:
    return await get_tool_wrapper("observe_agent")(
        agent_id=agent_id,
        include_history=include_history,
        analyze_patterns=analyze_patterns
    )

@tool_no_schema(description="Compare governance patterns across multiple agents")
async def compare_agents(agent_ids: list, compare_metrics: list = None) -> str:
    args = {"agent_ids": agent_ids}
    if compare_metrics:
        args["compare_metrics"] = compare_metrics
    return await get_tool_wrapper("compare_agents")(**args)

@tool_no_schema(description="Compare yourself to similar agents automatically")
async def compare_me_to_similar(agent_id: str, similarity_threshold: float = 0.15) -> str:
    args = {"agent_id": agent_id, "similarity_threshold": similarity_threshold}
    return await get_tool_wrapper("compare_me_to_similar")(**args)

@tool_no_schema(description="Get fleet-level health overview")
async def aggregate_metrics(agent_ids: list = None, include_health_breakdown: bool = True) -> str:
    args = {"include_health_breakdown": include_health_breakdown}
    if agent_ids:
        args["agent_ids"] = agent_ids
    return await get_tool_wrapper("aggregate_metrics")(**args)

@tool_no_schema(description="Get comprehensive telemetry metrics")
async def get_telemetry_metrics(
    agent_id: str = None,
    window_hours: float = 24,
    include_calibration: bool = False,
) -> str:
    args = {"window_hours": window_hours, "include_calibration": include_calibration}
    if agent_id:
        args["agent_id"] = agent_id
    return await get_tool_wrapper("get_telemetry_metrics")(**args)


# Config tools
@tool_no_schema(description="Get current governance threshold configuration")
async def get_thresholds() -> str:
    return await get_tool_wrapper("get_thresholds")()

@tool_no_schema(description="Set runtime threshold overrides")
async def set_thresholds(thresholds: dict, agent_id: str = None, api_key: str = None, validate: bool = True) -> str:
    args = {"thresholds": thresholds, "validate": validate}
    if agent_id:
        args["agent_id"] = agent_id
    if api_key:
        args["api_key"] = api_key
    return await get_tool_wrapper("set_thresholds")(**args)


# ============================================================================
# Remaining Tools (Full Feature Parity with stdio server)
# ============================================================================

# Calibration tools
@tool_no_schema(description="Check calibration of confidence estimates (trajectory/consensus proxy by default)")
async def check_calibration() -> str:
    return await get_tool_wrapper("check_calibration")()

@tool_no_schema(description="Record external truth signal for calibration (optional; use only when you have one)")
async def update_calibration_ground_truth(
    actual_correct: bool,
    confidence: float = None,
    predicted_correct: bool = None,
    timestamp: str = None,
    agent_id: str = None
) -> str:
    args = {"actual_correct": actual_correct}
    if confidence is not None:
        args["confidence"] = confidence
    if predicted_correct is not None:
        args["predicted_correct"] = predicted_correct
    if timestamp:
        args["timestamp"] = timestamp
    if agent_id:
        args["agent_id"] = agent_id
    return await get_tool_wrapper("update_calibration_ground_truth")(**args)

# Lifecycle tools (remaining)
@tool_no_schema(description="Update agent tags and notes")
async def update_agent_metadata(
    agent_id: str,
    tags: list = None,
    notes: str = None,
    append_notes: bool = False,
    api_key: str = None
) -> str:
    args = {"agent_id": agent_id, "append_notes": append_notes}
    if tags:
        args["tags"] = tags
    if notes:
        args["notes"] = notes
    if api_key:
        args["api_key"] = api_key
    return await get_tool_wrapper("update_agent_metadata")(**args)

@tool_no_schema(description="Archive an agent for long-term storage")
async def archive_agent(agent_id: str, reason: str = None, keep_in_memory: bool = False, api_key: str = None, ctx: Context = None) -> str:
    session_id = _session_id_from_ctx(ctx)
    args: Dict[str, Any] = {"agent_id": agent_id, "keep_in_memory": keep_in_memory}
    if reason:
        args["reason"] = reason
    if api_key is not None:
        args["api_key"] = api_key
    if session_id:
        args["client_session_id"] = session_id
    return await get_tool_wrapper("archive_agent")(**args)

@tool_no_schema(description="Delete an agent and archive its data")
async def delete_agent(agent_id: str, confirm: bool = False, backup_first: bool = True, api_key: str = None) -> str:
    args = {"agent_id": agent_id, "confirm": confirm, "backup_first": backup_first}
    if api_key:
        args["api_key"] = api_key
    return await get_tool_wrapper("delete_agent")(**args)

@tool_no_schema(description="Archive old test/demo agents that haven't been updated recently")
async def archive_old_test_agents(max_age_hours: float = 6, max_age_days: float = None) -> str:
    args = {"max_age_hours": max_age_hours}
    if max_age_days is not None:
        args["max_age_days"] = max_age_days
    return await get_tool_wrapper("archive_old_test_agents")(**args)

@tool_no_schema(description="Mark agent as having completed response, waiting for input")
async def mark_response_complete(agent_id: str, api_key: str = None, summary: str = None) -> str:
    args = {"agent_id": agent_id}
    if api_key:
        args["api_key"] = api_key
    if summary:
        args["summary"] = summary
    return await get_tool_wrapper("mark_response_complete")(**args)

@tool_no_schema(description="Direct resume without dialectic if agent state is safe")
async def direct_resume_if_safe(
    agent_id: str,
    api_key: str,
    conditions: list = None,
    reason: str = None
) -> str:
    args = {"agent_id": agent_id, "api_key": api_key}
    if conditions:
        args["conditions"] = conditions
    if reason:
        args["reason"] = reason
    return await get_tool_wrapper("direct_resume_if_safe")(**args)

# Export tools
@tool_no_schema(description="Export complete governance history for an agent")
async def get_system_history(agent_id: str, format: str = "json") -> str:
    return await get_tool_wrapper("get_system_history")(agent_id=agent_id, format=format)

@tool_no_schema(description="Export governance history to a file")
async def export_to_file(
    agent_id: str,
    format: str = "json",
    filename: str = None,
    complete_package: bool = False
) -> str:
    args = {"agent_id": agent_id, "format": format, "complete_package": complete_package}
    if filename:
        args["filename"] = filename
    return await get_tool_wrapper("export_to_file")(**args)

# Admin tools (remaining)
@tool_no_schema(description="Reset governance state for an agent")
async def reset_monitor(agent_id: str) -> str:
    return await get_tool_wrapper("reset_monitor")(agent_id=agent_id)

@tool_no_schema(description="Clean up stale lock files")
async def cleanup_stale_locks(max_age_seconds: float = 300, dry_run: bool = False) -> str:
    return await get_tool_wrapper("cleanup_stale_locks")(
        max_age_seconds=max_age_seconds, dry_run=dry_run
    )

@tool_no_schema(description="Validate file path against markdown proliferation policy")
async def validate_file_path(file_path: str) -> str:
    return await get_tool_wrapper("validate_file_path")(file_path=file_path)

@tool_no_schema(description="Backfill calibration data from dialectic protocol history")
async def backfill_calibration_from_dialectic(
    lookback_days: int = 30,
    min_confidence: float = 0.5,
    dry_run: bool = False
) -> str:
    return await get_tool_wrapper("backfill_calibration_from_dialectic")(
        lookback_days=lookback_days,
        min_confidence=min_confidence,
        dry_run=dry_run
    )

@tool_no_schema(description="Get tool usage statistics")
async def get_tool_usage_stats(
    window_hours: float = 168,
    tool_name: str | None = None,
    agent_id: str | None = None
) -> str:
    args = {"window_hours": window_hours}
    if tool_name:
        args["tool_name"] = tool_name
    if agent_id:
        args["agent_id"] = agent_id
    return await get_tool_wrapper("get_tool_usage_stats")(**args)

# Anomaly detection
@tool_no_schema(description="Detect anomalies across agents")
async def detect_anomalies(
    agent_ids: list = None,
    anomaly_types: list = None,
    min_severity: str = "medium"
) -> str:
    args = {"min_severity": min_severity}
    if agent_ids:
        args["agent_ids"] = agent_ids
    if anomaly_types:
        args["anomaly_types"] = anomaly_types
    return await get_tool_wrapper("detect_anomalies")(**args)

# Knowledge graph (remaining)
@tool_no_schema(description="Get all knowledge for an agent")
async def get_knowledge_graph(agent_id: str, limit: int = None, include_details: bool = False) -> str:
    args = {"agent_id": agent_id, "include_details": include_details}
    if limit:
        args["limit"] = limit
    return await get_tool_wrapper("get_knowledge_graph")(**args)

@tool_no_schema(description="Update discovery status")
async def update_discovery_status_graph(discovery_id: str, status: str, agent_id: str = None, api_key: str = None) -> str:
    args = {"discovery_id": discovery_id, "status": status}
    if agent_id:
        args["agent_id"] = agent_id
    if api_key:
        args["api_key"] = api_key
    return await get_tool_wrapper("update_discovery_status_graph")(**args)

@tool_no_schema(description="Find similar discoveries by tag overlap")
async def find_similar_discoveries_graph(discovery_id: str, limit: int = 10) -> str:
    return await get_tool_wrapper("find_similar_discoveries_graph")(
        discovery_id=discovery_id, limit=limit
    )

@tool_no_schema(description="Reply to a question in the knowledge graph")
async def reply_to_question(
    agent_id: str,
    question_id: str,
    summary: str,
    api_key: str = None,
    details: str = None,
    tags: list = None,
    severity: str = None,
    mark_question_resolved: bool = False
) -> str:
    args = {
        "agent_id": agent_id,
        "question_id": question_id,
        "summary": summary,
        "mark_question_resolved": mark_question_resolved
    }
    if api_key:
        args["api_key"] = api_key
    if details:
        args["details"] = details
    if tags:
        args["tags"] = tags
    if severity:
        args["severity"] = severity
    return await get_tool_wrapper("reply_to_question")(**args)

# ============================================================================
# Server Entry Point
# ============================================================================

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="UNITARES Governance MCP Server (SSE Transport)"
    )
    parser.add_argument(
        "--host", 
        default=DEFAULT_HOST,
        help=f"Host to bind to (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=DEFAULT_PORT,
        help=f"Port to bind to (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force start: clean up any stale lock files"
    )
    return parser.parse_args()


def is_process_alive(pid: int) -> bool:
    """Check if a process with given PID is still running"""
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks if process exists
        return True
    except (OSError, ProcessLookupError):
        return False


def cleanup_existing_sse_processes():
    """Kill any existing SSE server processes before starting new one"""
    if not SSE_PID_FILE.exists():
        return []
    
    killed = []
    try:
        with open(SSE_PID_FILE, 'r') as f:
            existing_pid = int(f.read().strip())
        
        if existing_pid != CURRENT_PID and is_process_alive(existing_pid):
            logger.info(f"Found existing SSE server (PID {existing_pid}), terminating...")
            try:
                os.kill(existing_pid, signal.SIGTERM)
                # Wait a bit for graceful shutdown
                time.sleep(1)
                if is_process_alive(existing_pid):
                    os.kill(existing_pid, signal.SIGKILL)
                killed.append(existing_pid)
                logger.info(f"Terminated existing SSE server (PID {existing_pid})")
            except (OSError, ProcessLookupError):
                # Process already dead, just clean up PID file
                pass
        
        # Clean up PID file if process is dead
        if not is_process_alive(existing_pid):
            SSE_PID_FILE.unlink(missing_ok=True)
    except (ValueError, IOError) as e:
        logger.warning(f"Could not read existing PID file: {e}")
        # Clean up invalid PID file
        SSE_PID_FILE.unlink(missing_ok=True)
    
    return killed


def write_sse_pid_file():
    """Write PID file for SSE server process tracking"""
    try:
        SSE_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SSE_PID_FILE, 'w') as f:
            f.write(f"{CURRENT_PID}\n")
        logger.debug(f"Wrote SSE PID file: {SSE_PID_FILE} (PID: {CURRENT_PID})")
    except Exception as e:
        logger.warning(f"Could not write SSE PID file: {e}", exc_info=True)


def remove_sse_pid_file():
    """Remove PID file on shutdown"""
    try:
        if SSE_PID_FILE.exists():
            SSE_PID_FILE.unlink()
            logger.debug(f"Removed SSE PID file: {SSE_PID_FILE}")
    except Exception as e:
        logger.warning(f"Could not remove SSE PID file: {e}", exc_info=True)


def acquire_sse_lock():
    """Acquire lock file to prevent multiple SSE server instances.

    Automatically cleans up stale locks from dead processes.
    """
    lock_fd = None
    try:
        SSE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Check for stale lock file before trying to acquire
        if SSE_LOCK_FILE.exists():
            try:
                with open(SSE_LOCK_FILE, 'r') as f:
                    lock_info = json.load(f)
                    old_pid = lock_info.get("pid")
                    if old_pid and not is_process_alive(old_pid):
                        logger.info(f"Cleaning up stale lock from dead process (PID: {old_pid})")
                        SSE_LOCK_FILE.unlink()
            except (json.JSONDecodeError, KeyError, IOError):
                # Corrupt lock file - safe to remove
                logger.info("Cleaning up corrupt lock file")
                try:
                    SSE_LOCK_FILE.unlink()
                except FileNotFoundError:
                    pass

        lock_fd = os.open(str(SSE_LOCK_FILE), os.O_CREAT | os.O_RDWR)

        try:
            # Try to acquire exclusive lock (non-blocking)
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Write PID and timestamp to lock file
            lock_info = {
                "pid": CURRENT_PID,
                "timestamp": time.time(),
                "started_at": datetime.now().isoformat()
            }
            os.ftruncate(lock_fd, 0)
            os.write(lock_fd, json.dumps(lock_info).encode())
            os.fsync(lock_fd)

            logger.debug(f"Acquired SSE lock file: {SSE_LOCK_FILE} (PID: {CURRENT_PID})")
            return lock_fd
        except IOError:
            # Lock is held by another process
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                except (OSError, ValueError):
                    pass
            raise RuntimeError(
                f"SSE server is already running (lock file: {SSE_LOCK_FILE}). "
                f"Only one SSE server instance can run at a time."
            )
    except RuntimeError:
        # Re-raise RuntimeError (already running) without cleanup
        raise
    except Exception as e:
        # Clean up lock_fd if it was opened
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except (OSError, ValueError):
                pass
        logger.warning(f"Could not acquire SSE lock: {e}", exc_info=True)
        return None


def release_sse_lock(lock_fd):
    """Release lock file"""
    if lock_fd is not None:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            if SSE_LOCK_FILE.exists():
                SSE_LOCK_FILE.unlink()
            logger.debug(f"Released SSE lock file: {SSE_LOCK_FILE}")
        except Exception as e:
            logger.warning(f"Could not release SSE lock: {e}", exc_info=True)


async def main():
    """Main entry point for SSE server."""
    args = parse_args()

    # --force: Explicitly clean up lock file before starting
    if args.force and SSE_LOCK_FILE.exists():
        logger.info(f"--force: Removing lock file {SSE_LOCK_FILE}")
        try:
            SSE_LOCK_FILE.unlink()
        except Exception as e:
            logger.warning(f"Could not remove lock file: {e}")

    # Process deduplication: Check for and kill existing SSE processes
    killed = cleanup_existing_sse_processes()
    if killed:
        logger.info(f"Cleaned up {len(killed)} existing SSE server process(es)")

    # Acquire lock to prevent multiple instances
    lock_fd = None
    try:
        lock_fd = acquire_sse_lock()
    except RuntimeError as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        print("💡 Tip: Use --force to clean up stale locks", file=sys.stderr)
        sys.exit(1)
    
    # Write PID file
    write_sse_pid_file()

    # Clean up stale agent locks from crashed processes
    try:
        from src.lock_cleanup import cleanup_stale_state_locks
        cleanup_result = cleanup_stale_state_locks(
            project_root=Path(project_root),
            max_age_seconds=300.0  # 5 minutes
        )
        if cleanup_result.get('cleaned', 0) > 0:
            logger.info(f"Cleaned up {cleanup_result['cleaned']} stale agent lock(s) at startup")
    except Exception as e:
        logger.warning(f"Could not clean up stale locks at startup: {e}")

    # Initialize database abstraction layer
    try:
        from src.db import init_db, close_db, get_db
        await init_db()
        db = get_db()
        backend_type = os.environ.get("DB_BACKEND", "sqlite")
        logger.info(f"Database initialized: backend={backend_type}")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        print(f"\n❌ Database initialization failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Register cleanup handlers
    def cleanup():
        # Close database connections
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(close_db())
            loop.close()
        except Exception as e:
            logger.warning(f"Error closing database: {e}")
        release_sse_lock(lock_fd)
        remove_sse_pid_file()
    
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (cleanup(), sys.exit(0)))
    
    endpoint = f"http://{args.host}:{args.port}/sse"
    config_json = f'{{"url": "{endpoint}"}}'
    
    print(f"""
╔════════════════════════════════════════════════════════════════════╗
║       UNITARES Governance MCP Server                               ║
╠════════════════════════════════════════════════════════════════════╣
║  Version:  {SERVER_VERSION}                                                   ║
║                                                                    ║
║  MCP Transports:                                                   ║
║    SSE (legacy):       {endpoint:<46}║
║    Streamable HTTP:    http://{args.host}:{args.port}/mcp                              ║
║                                                                    ║
║  REST API:                                                         ║
║    List tools:         GET  /v1/tools                              ║
║    Call tool:          POST /v1/tools/call                         ║
║    Health:             GET  /health                                ║
║    Metrics:            GET  /metrics                               ║
║                                                                    ║
║  One server, all transports.                                       ║
╚════════════════════════════════════════════════════════════════════╝
""")
    
    logger.info(f"Starting SSE server on http://{args.host}:{args.port}/sse")
    
    # Run the FastMCP SSE server
    try:
        import uvicorn
        from starlette.routing import Route
        from starlette.responses import JSONResponse
        from starlette.middleware.cors import CORSMiddleware
        
        # Get the Starlette app from FastMCP (SSE transport)
        app = mcp.sse_app()
        
        # === Add Streamable HTTP transport (MCP 1.24.0+) ===
        # Clients can connect to /mcp for the new transport with resumability
        try:
            from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
            from mcp.server.streamable_http import StreamableHTTPServerTransport
            
            # Create session manager for Streamable HTTP
            _streamable_session_manager = StreamableHTTPSessionManager(
                app=mcp._mcp_server,  # Access the underlying MCP server
                json_response=False,  # Use SSE streams (default, more efficient)
                stateless=False,      # Track sessions for resumability
            )
            
            HAS_STREAMABLE_HTTP = True
            logger.info("Streamable HTTP transport available at /mcp")
        except Exception as e:
            HAS_STREAMABLE_HTTP = False
            _streamable_session_manager = None
            logger.info(f"Streamable HTTP transport not available: {e}")
        
        # === Add CORS support for web-based GPT/Gemini clients ===
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # Allow all origins (restrict in production)
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["*"],
        )
        
        # === Connection Tracking Middleware (ASGI-safe for streaming SSE) ===
        #
        # IMPORTANT:
        # Do NOT use Starlette's BaseHTTPMiddleware here. It is known to break streaming
        # responses (like SSE) and can trigger:
        #   AssertionError: Unexpected message: {'type': 'http.response.start', ...}
        #
        # This middleware is implemented as a pure ASGI middleware to be safe for /sse.
        from starlette.datastructures import Headers

        class ConnectionTrackingMiddleware:
            def __init__(self, app):
                self.app = app

            async def __call__(self, scope, receive, send):
                if scope.get("type") != "http":
                    return await self.app(scope, receive, send)

                path = scope.get("path", "")
                is_sse = path == "/sse"
                headers = Headers(scope=scope)
                
                # === SSE Probe Safeguard ===
                # Prevent agents from hanging by providing ?probe=true to test connectivity
                # Returns immediately with server status instead of starting streaming connection
                if is_sse:
                    query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
                    if "probe=true" in query_string or "probe=1" in query_string:
                        response_body = json.dumps({
                            "status": "ready" if SERVER_READY else "warming_up",
                            "endpoint": "/sse",
                            "transport": "SSE",
                            "message": "SSE endpoint is available. Remove ?probe to start streaming connection." if SERVER_READY else "Server is warming up, please retry in 2 seconds.",
                            "hint": "Use /health for quick health checks, /sse for MCP client connections",
                            "server_version": SERVER_VERSION,
                        }).encode("utf-8")
                        await send({
                            "type": "http.response.start",
                            "status": 200 if SERVER_READY else 503,
                            "headers": [[b"content-type", b"application/json"]],
                        })
                        await send({
                            "type": "http.response.body",
                            "body": response_body,
                        })
                        return
                
                # === Server Warmup Check ===
                # Prevent "request before initialization" errors when clients reconnect
                # too quickly after a server restart. SSE connections are allowed (they need
                # to establish to complete MCP initialization), but health checks report status.
                if path == "/health" and not SERVER_READY:
                    response_body = json.dumps({
                        "status": "warming_up",
                        "message": "Server is starting up, please retry in 2 seconds",
                        "hint": "This prevents 'request before initialization' errors during multi-client reconnection",
                        "server_version": SERVER_VERSION,
                    }).encode("utf-8")
                    await send({
                        "type": "http.response.start",
                        "status": 503,
                        "headers": [
                            [b"content-type", b"application/json"],
                            [b"retry-after", b"2"],
                        ],
                    })
                    await send({
                        "type": "http.response.body",
                        "body": response_body,
                    })
                    return

                # Generate base id (stable per SSE connection, unique per HTTP request)
                base_id = headers.get("x-client-id")
                if not base_id:
                    client = scope.get("client")
                    if client and len(client) >= 2:
                        base_id = f"{client[0]}:{client[1]}"
                    else:
                        base_id = "unknown"

                if is_sse:
                    client_id = base_id
                else:
                    client_id = f"{base_id}:{uuid.uuid4().hex[:8]}"

                # Expose to downstream tool calls via FastMCP Context.request_context.request.state
                try:
                    state = scope.setdefault("state", {})
                    state["governance_client_id"] = client_id
                except Exception:
                    pass

                # Track SSE connections (long-lived); HTTP requests are ephemeral.
                if is_sse:
                    await connection_tracker.add_connection(client_id, {
                        "type": "sse",
                        "path": path,
                        "user_agent": headers.get("user-agent", "unknown"),
                    })

                disconnected = False

                async def wrapped_receive():
                    nonlocal disconnected
                    try:
                        message = await receive()
                        if message.get("type") == "http.disconnect":
                            disconnected = True
                            if is_sse:
                                try:
                                    await connection_tracker.remove_connection(client_id)
                                except Exception:
                                    pass
                        return message
                    except Exception as e:
                        # Handle receive errors gracefully
                        logger.debug(f"Error in wrapped_receive for {client_id}: {e}")
                        disconnected = True
                        if is_sse:
                            try:
                                await connection_tracker.remove_connection(client_id)
                            except Exception:
                                pass
                        raise

                # CRITICAL FIX: Wrap send to handle streaming responses properly
                # SSE responses are streaming, so we need to pass through all messages
                # without interfering with the ASGI protocol
                async def wrapped_send(message):
                    try:
                        # Pass through all ASGI messages unchanged for SSE streaming
                        await send(message)
                        # Only update activity after response starts (not on every chunk)
                        if is_sse and message.get("type") == "http.response.start":
                            try:
                                await connection_tracker.update_activity(client_id)
                            except Exception:
                                pass  # Don't fail on activity update errors
                    except Exception as e:
                        # If send fails, mark as disconnected
                        logger.debug(f"Error in wrapped_send for {client_id}: {e}")
                        disconnected = True
                        if is_sse:
                            try:
                                await connection_tracker.remove_connection(client_id)
                            except Exception:
                                pass
                        raise

                try:
                    await self.app(scope, wrapped_receive, wrapped_send)
                    # Update activity after successful completion (for non-streaming responses)
                    if is_sse and not disconnected:
                        try:
                            await connection_tracker.update_activity(client_id)
                        except Exception:
                            pass
                except Exception as e:
                    # If SSE request errors, ensure connection is cleared.
                    logger.debug(f"Error handling request for {client_id}: {e}")
                    if is_sse and not disconnected:
                        try:
                            await connection_tracker.remove_connection(client_id)
                        except Exception:
                            pass
                    raise
                finally:
                    # Only remove non-SSE connections (HTTP REST endpoints)
                    if not is_sse:
                        await connection_tracker.remove_connection(client_id)

        app.add_middleware(ConnectionTrackingMiddleware)
        
        # === Background task: Connection heartbeat and health monitoring ===
        async def connection_heartbeat_task():
            """
            Comprehensive connection health monitoring:
            - Clean up stale connections every 5 minutes
            - Check health of all connections every 2 minutes
            - Log diagnostic summary every 10 minutes
            """
            consecutive_failures = 0
            max_consecutive_failures = 5
            iteration = 0
            
            while True:
                try:
                    await asyncio.sleep(60)  # Run every minute
                    iteration += 1
                    
                    # Health check every 2 minutes (iteration % 2 == 0)
                    if iteration % 2 == 0:
                        for client_id in list(connection_tracker.connections.keys()):
                            try:
                                health = await connection_tracker.check_health(client_id)
                                if not health.get("healthy"):
                                    logger.warning(
                                        f"[HEARTBEAT] Unhealthy connection: {client_id} - {health.get('issues', [])}"
                                    )
                            except Exception as e:
                                logger.debug(f"[HEARTBEAT] Health check failed for {client_id}: {e}")
                    
                    # Stale cleanup every 5 minutes (iteration % 5 == 0)
                    if iteration % 5 == 0:
                        await connection_tracker.cleanup_stale_connections(max_idle_minutes=30.0)
                    
                    # Diagnostic summary every 10 minutes (iteration % 10 == 0)
                    if iteration % 10 == 0:
                        diagnostics = await connection_tracker.get_diagnostics()
                        health_summary = diagnostics.get("health_summary", {})
                        reconnect_summary = diagnostics.get("reconnection_summary", {})
                        
                        # Log summary
                        logger.info(
                            f"[HEARTBEAT] Connection summary: "
                            f"{diagnostics['total_connections']} connected, "
                            f"{health_summary.get('healthy', 0)} healthy, "
                            f"{health_summary.get('degraded', 0)} degraded"
                        )
                        
                        # Alert on high reconnection rates
                        high_reconnectors = {k: v for k, v in reconnect_summary.items() if v > 5}
                        if high_reconnectors:
                            logger.warning(
                                f"[HEARTBEAT] High reconnection clients: {high_reconnectors}. "
                                f"Check network stability."
                            )
                        
                        # Update Prometheus metrics for connections
                        CONNECTIONS_ACTIVE.set(diagnostics['total_connections'])
                    
                    consecutive_failures = 0  # Reset on success
                    
                except asyncio.CancelledError:
                    logger.info("[HEARTBEAT] Connection heartbeat task cancelled")
                    break
                except Exception as e:
                    consecutive_failures += 1
                    logger.warning(
                        f"[HEARTBEAT] Error (failure {consecutive_failures}/{max_consecutive_failures}): {e}",
                        exc_info=True
                    )
                    
                    # Alert if task fails repeatedly
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(
                            f"[HEARTBEAT] Failed {consecutive_failures} times consecutively. "
                            f"Connection monitoring degraded. Consider restarting SSE server."
                        )
                        consecutive_failures = 0  # Reset to avoid spam
        
        # Start background heartbeat task
        heartbeat_task = asyncio.create_task(connection_heartbeat_task())
        logger.info("[HEARTBEAT] Connection health monitoring started")
        
        # === Background task: Automatic ground truth collection ===
        async def startup_auto_calibration():
            """Start automatic ground truth collection at startup and periodically."""
            # Wait a moment for server to initialize
            await asyncio.sleep(1.0)
            
            try:
                from src.auto_ground_truth import collect_ground_truth_automatically, auto_ground_truth_collector_task
                
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
                logger.warning(f"Could not start auto ground truth collector: {e}", exc_info=True)
        
        # Start auto calibration task (non-blocking)
        asyncio.create_task(startup_auto_calibration())
        
        # === Server warmup task ===
        # Prevents "request before initialization" errors when multiple clients
        # reconnect simultaneously after a server restart
        async def server_warmup_task():
            """Set server ready flag after short warmup to allow MCP initialization."""
            global SERVER_READY, SERVER_STARTUP_TIME
            SERVER_STARTUP_TIME = datetime.now()
            
            # Short delay to ensure MCP transport is initialized
            await asyncio.sleep(2.0)
            
            SERVER_READY = True
            logger.info(f"[WARMUP] Server ready to accept requests (warmup complete)")
        
        asyncio.create_task(server_warmup_task())
        
        # === HTTP REST endpoints for non-MCP clients (Llama, Mistral, etc.) ===
        # Any model that can make HTTP calls can use governance
        HTTP_API_TOKEN = os.getenv("UNITARES_HTTP_API_TOKEN")
        HTTP_CORS_ALLOW_ORIGIN = os.getenv("UNITARES_HTTP_CORS_ALLOW_ORIGIN")  # e.g. "*" or "http://localhost:3000"

        def _http_unauthorized():
            return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)

        def _check_http_auth(request) -> bool:
            """Optional bearer token auth for HTTP endpoints."""
            if not HTTP_API_TOKEN:
                return True
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if not auth or not isinstance(auth, str):
                return False
            if not auth.lower().startswith("bearer "):
                return False
            token = auth.split(" ", 1)[1].strip()
            return token == HTTP_API_TOKEN

        def _extract_client_session_id(request) -> str:
            """
            Stable per-client session id for HTTP callers.
            - Prefer explicit header X-Session-ID
            - Fall back to ConnectionTrackingMiddleware id if present
            - Otherwise use remote addr + user-agent (best-effort)
            """
            sid = request.headers.get("X-Session-ID") or request.headers.get("x-session-id")
            if sid:
                return str(sid)
            try:
                if hasattr(request, "state") and hasattr(request.state, "governance_client_id"):
                    return str(getattr(request.state, "governance_client_id"))
            except Exception:
                pass
            try:
                host = request.client.host if request.client else "unknown"
                ua = request.headers.get("user-agent", "unknown")
                return f"http:{host}:{ua}"
            except Exception:
                return "http:unknown"
        
        async def http_list_tools(request):
            """List all tools in OpenAI-compatible format"""
            try:
                if not _check_http_auth(request):
                    return _http_unauthorized()
                from src.tool_schemas import get_tool_definitions
                
                # get_tool_definitions() is synchronous, no await needed
                mcp_tools = get_tool_definitions()
                openai_tools = []
                for tool in mcp_tools:
                    description = tool.description.split("\n")[0] if tool.description else f"Tool: {tool.name}"
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": description,
                            "parameters": tool.inputSchema
                        }
                    })
                return JSONResponse({
                    "tools": openai_tools,
                    "count": len(openai_tools),
                    "note": f"All {len(mcp_tools)} tools available (tool mode filtering removed)"
                })
            except Exception as e:
                logger.error(f"Error listing tools: {e}", exc_info=True)
                return JSONResponse({
                    "tools": [],
                    "count": 0,
                    "error": str(e)
                }, status_code=500)
        
        async def http_call_tool(request):
            """Execute tool via HTTP - any model can call this"""
            # CRITICAL FIX: Ensure all code paths return valid JSONResponse
            # Empty or malformed responses cause Starlette ASGI protocol violations
            # (AssertionError: Unexpected message: http.response.start vs http.response.body)
            
            # SECURITY: Limit request body size (prevent DoS via large payloads)
            MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB limit
            body = None
            tool_name = "unknown"
            try:
                if not _check_http_auth(request):
                    return _http_unauthorized()
                # Check content length before parsing
                content_length = request.headers.get("content-length")
                if content_length:
                    try:
                        size = int(content_length)
                        if size > MAX_REQUEST_SIZE:
                            return JSONResponse({
                                "success": False,
                                "error": "Request body too large",
                                "max_size_mb": MAX_REQUEST_SIZE // (1024 * 1024)
                            }, status_code=413)
                    except ValueError:
                        pass  # Invalid content-length, let JSON parsing handle it
                
                body = await request.json()
                
                # SECURITY: Validate request structure
                if not isinstance(body, dict):
                    return JSONResponse({"success": False, "error": "Request body must be a JSON object"}, status_code=400)
                
                # SECURITY: Limit arguments dictionary size (prevent DoS via large dicts)
                arguments = body.get("arguments", {})
                if isinstance(arguments, dict) and len(arguments) > 100:
                    return JSONResponse({
                        "success": False,
                        "error": "Too many arguments",
                        "max_arguments": 100
                    }, status_code=400)
                
                tool_name = body.get("name") or "unknown"
                if not tool_name or tool_name == "unknown":
                    return JSONResponse({"success": False, "error": "Missing 'name' field", "name": None}, status_code=400)
                
                # SECURITY: Validate tool name format (prevent injection)
                if not isinstance(tool_name, str) or len(tool_name) > 100:
                    return JSONResponse({
                        "success": False,
                        "error": "Invalid tool name format"
                    }, status_code=400)

                # Compatibility: Some MCP clients surface names as `mcp_<server>_<tool>`.
                # The HTTP API always dispatches by the canonical tool name (e.g. `list_tools`).
                # Accept the prefixed form to reduce client-side friction.
                mcp_prefix = f"mcp_{mcp.name}_"
                if tool_name.startswith(mcp_prefix):
                    tool_name = tool_name[len(mcp_prefix):]
                
                # SSE-specific tools: handle directly (not in dispatch_tool)
                if tool_name == "get_connected_clients":
                    clients = connection_tracker.get_connected_clients()
                    # Enrich with health info
                    enriched_clients = {}
                    for client_id, data in clients.items():
                        health = await connection_tracker.check_health(client_id)
                        enriched_clients[client_id] = {**data, "health": health}
                    
                    result_data = {
                        "success": True,
                        "transport": "SSE",
                        "server_version": SERVER_VERSION,
                        "connected_clients": enriched_clients,
                        "total_clients": connection_tracker.count,
                        "message": f"{connection_tracker.count} client(s) currently connected"
                    }
                    return JSONResponse({"name": tool_name, "result": result_data, "success": True})
                
                if tool_name == "get_connection_diagnostics":
                    diagnostics = await connection_tracker.get_diagnostics()
                    result_data = {
                        "success": True,
                        "diagnostics": diagnostics,
                        "recommendations": _generate_connection_recommendations(diagnostics)
                    }
                    return JSONResponse({"name": tool_name, "result": result_data, "success": True})
                
                # Inject stable client session for identity binding (avoid collision with dialectic session_id)
                if isinstance(arguments, dict) and "client_session_id" not in arguments:
                    arguments["client_session_id"] = _extract_client_session_id(request)

                result = await dispatch_tool(tool_name, arguments)
                
                # CRITICAL FIX: Ensure we always return a valid JSONResponse with non-empty body
                # Empty responses cause Starlette middleware AssertionError (http.response.start vs http.response.body)
                if result and len(result) > 0 and hasattr(result[0], 'text'):
                    import json as json_mod
                    try:
                        parsed = json_mod.loads(result[0].text)
                        # Ensure parsed result is not None/empty
                        response_data = {"name": tool_name, "result": parsed, "success": True}
                        return JSONResponse(response_data)
                    except json_mod.JSONDecodeError:
                        # Fallback: use raw text (ensure it's not empty)
                        text_result = result[0].text if result[0].text else "{}"
                        response_data = {"name": tool_name, "result": text_result, "success": True}
                        return JSONResponse(response_data)
                
                # Handle empty/None results - always return valid JSON
                if result is None:
                    response_data = {
                        "name": tool_name,
                        "result": None,
                        "success": False,
                        "error": f"Tool '{tool_name}' returned no result"
                    }
                elif isinstance(result, (list, tuple)) and len(result) == 0:
                    response_data = {
                        "name": tool_name,
                        "result": None,
                        "success": False,
                        "error": f"Tool '{tool_name}' returned empty result"
                    }
                else:
                    # Convert result to string, ensure non-empty
                    result_str = str(result) if result else "null"
                    response_data = {"name": tool_name, "result": result_str, "success": True}
                
                # CRITICAL: Always return a properly formatted JSONResponse
                # This prevents Starlette middleware AssertionError from empty/corrupted responses
                return JSONResponse(response_data)
            except json.JSONDecodeError as e:
                # SECURITY: Sanitize JSON parsing errors
                logger.error(f"Invalid JSON in request: {e}", exc_info=True)
                return JSONResponse({
                    "success": False,
                    "error": "Invalid JSON format",
                    "error_type": "JSONDecodeError"
                }, status_code=400)
            except ValueError as e:
                # SECURITY: Safe to expose validation errors
                logger.warning(f"Validation error: {e}")
                return JSONResponse({
                    "success": False,
                    "error": str(e),
                    "error_type": "ValidationError"
                }, status_code=400)
            except KeyError as e:
                # SECURITY: Safe to expose missing key errors
                logger.warning(f"Missing required field: {e}")
                return JSONResponse({
                    "success": False,
                    "error": f"Missing required field: {str(e)}",
                    "error_type": "KeyError"
                }, status_code=400)
            except Exception as e:
                # SECURITY: Sanitize internal errors (don't expose stack traces, file paths, etc.)
                tool_name_safe = body.get("name", "unknown") if body else "unknown"
                logger.error(f"Error calling tool '{tool_name_safe}': {e}", exc_info=True)
                
                # Only expose safe error information
                error_msg = "An error occurred processing your request"
                error_type = type(e).__name__
                
                # For known error types, provide more specific messages
                if isinstance(e, (AttributeError, TypeError)):
                    error_msg = "Invalid request format"
                elif isinstance(e, RuntimeError):
                    error_msg = "Service temporarily unavailable"
                
                return JSONResponse({
                    "name": tool_name_safe if isinstance(tool_name_safe, str) else None,
                    "result": None,
                    "success": False,
                    "error": error_msg,
                    "error_type": error_type
                }, status_code=500)
        
        async def http_health(request):
            """Health check endpoint"""
            if not _check_http_auth(request):
                return _http_unauthorized()
            return JSONResponse({
                "status": "ok" if SERVER_READY else "warming_up",
                "version": SERVER_VERSION,
                "transports": {
                    "sse": "/sse (legacy, stable)",
                    "streamable_http": "/mcp (new, with resumability)" if HAS_STREAMABLE_HTTP else "not available"
                },
                "endpoints": {
                    "list_tools": "GET /v1/tools",
                    "call_tool": "POST /v1/tools/call",
                    "health": "GET /health",
                    "metrics": "GET /metrics",
                    "sse_probe": "GET /sse?probe=true (quick connectivity test)"
                },
                "auth": {
                    "enabled": bool(HTTP_API_TOKEN),
                    "header": "Authorization: Bearer <token>" if HTTP_API_TOKEN else None
                },
                "session": {
                    "header": "X-Session-ID (recommended for stable identity binding)"
                },
                "note": "Use /sse for legacy MCP clients, /mcp for new Streamable HTTP clients (Cursor 0.43+)"
            })
        
        async def http_metrics(request):
            """Prometheus metrics endpoint using prometheus-client library"""
            if not _check_http_auth(request):
                return _http_unauthorized()

            try:
                from starlette.responses import Response

                # Update gauges with current values before generating output
                # Server info (static, set once)
                SERVER_INFO.labels(version=SERVER_VERSION).set(1)

                # Connection metrics
                CONNECTIONS_ACTIVE.set(connection_tracker.count)

                # Agent metrics (from metadata file)
                try:
                    from src.mcp_handlers.shared import get_mcp_server
                    mcp_server = get_mcp_server()
                    mcp_server.load_metadata()

                    # Count by status (waiting_input and active are separate statuses)
                    status_counts = {"active": 0, "paused": 0, "archived": 0, "waiting_input": 0, "deleted": 0}
                    for meta in mcp_server.agent_metadata.values():
                        status = getattr(meta, 'status', 'active')
                        # Map status to valid Prometheus label
                        if status in status_counts:
                            status_counts[status] += 1
                        else:
                            # Unknown status - default to active for metrics
                            status_counts["active"] += 1

                    for status, count in status_counts.items():
                        AGENTS_TOTAL.labels(status=status).set(count)
                except Exception as e:
                    logger.debug(f"Could not load agent metrics: {e}")

                # Knowledge graph metrics
                try:
                    from src.knowledge_graph import get_knowledge_graph
                    import asyncio
                    loop = asyncio.get_running_loop()
                    kg = await get_knowledge_graph()
                    stats = await kg.get_stats()
                    KNOWLEDGE_NODES_TOTAL.set(stats.get("total_discoveries", 0))
                except Exception as e:
                    logger.debug(f"Could not load knowledge graph metrics: {e}")

                # Dialectic sessions
                try:
                    from src.dialectic_db import DialecticDB
                    from src.mcp_handlers.dialectic_session import ACTIVE_SESSIONS
                    import asyncio
                    loop = asyncio.get_running_loop()
                    # Use in-memory ACTIVE_SESSIONS dict (faster than DB query)
                    # This is populated by dialectic handlers and reflects current state
                    active_count = len(ACTIVE_SESSIONS)
                    DIALECTIC_SESSIONS_ACTIVE.set(active_count)
                except Exception as e:
                    logger.debug(f"Could not load dialectic metrics: {e}")

                # Generate Prometheus exposition format using the library
                output = generate_latest(REGISTRY)

                return Response(
                    content=output,
                    media_type=CONTENT_TYPE_LATEST
                )
            except Exception as e:
                logger.error(f"Error generating metrics: {e}", exc_info=True)
                return JSONResponse({
                    "error": "Failed to generate metrics",
                    "details": str(e)
                }, status_code=500)
        
        # Register HTTP endpoints
        app.routes.append(Route("/v1/tools", http_list_tools, methods=["GET"]))
        app.routes.append(Route("/v1/tools/call", http_call_tool, methods=["POST"]))
        app.routes.append(Route("/health", http_health, methods=["GET"]))
        app.routes.append(Route("/metrics", http_metrics, methods=["GET"]))
        
        # === Streamable HTTP endpoint (/mcp) ===
        # New MCP 1.24.0+ transport with resumability and bidirectional streaming
        _streamable_task_group = None
        _streamable_running = False
        
        if HAS_STREAMABLE_HTTP and _streamable_session_manager is not None:
            import anyio
            
            async def start_streamable_http():
                """Start the Streamable HTTP session manager in background."""
                nonlocal _streamable_task_group, _streamable_running
                try:
                    async with anyio.create_task_group() as tg:
                        _streamable_session_manager._task_group = tg
                        _streamable_session_manager._has_started = True
                        _streamable_running = True
                        logger.info("[STREAMABLE] Session manager started")
                        # Keep running until cancelled
                        await asyncio.Event().wait()
                except asyncio.CancelledError:
                    logger.info("[STREAMABLE] Session manager shutting down")
                    _streamable_running = False
                except Exception as e:
                    logger.error(f"[STREAMABLE] Session manager error: {e}", exc_info=True)
                    _streamable_running = False
            
            # Start the session manager as a background task
            streamable_task = asyncio.create_task(start_streamable_http())
            
            async def streamable_mcp_handler(request):
                """Handle Streamable HTTP MCP requests at /mcp."""
                if not _streamable_running:
                    return JSONResponse({
                        "error": "Streamable HTTP transport not ready",
                        "hint": "Try again in a moment"
                    }, status_code=503)
                try:
                    # Delegate to the session manager
                    await _streamable_session_manager.handle_request(
                        request.scope,
                        request.receive,
                        request._send
                    )
                except Exception as e:
                    logger.error(f"Streamable HTTP error: {e}", exc_info=True)
                    return JSONResponse({
                        "error": "Streamable HTTP transport error",
                        "details": str(e)
                    }, status_code=500)
            
            # Register the /mcp route for all methods (GET for SSE stream, POST for messages, DELETE for disconnect)
            app.routes.append(Route("/mcp", streamable_mcp_handler, methods=["GET", "POST", "DELETE"]))
            logger.info("Registered /mcp endpoint for Streamable HTTP transport")

        # Optional CORS for browser-based clients
        if HTTP_CORS_ALLOW_ORIGIN:
            try:
                from starlette.middleware.cors import CORSMiddleware
                app.add_middleware(
                    CORSMiddleware,
                    allow_origins=[HTTP_CORS_ALLOW_ORIGIN],
                    allow_credentials=False,
                    allow_methods=["GET", "POST", "OPTIONS"],
                    allow_headers=["*"],
                    max_age=600,
                )
                logger.info(f"Enabled CORS for HTTP endpoints allow_origin={HTTP_CORS_ALLOW_ORIGIN}")
            except Exception as e:
                logger.warning(f"Could not enable CORS middleware: {e}", exc_info=True)
        
        # Run with uvicorn
        # SECURITY: Add connection limits and timeouts to prevent DoS
        config = uvicorn.Config(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
            reload=args.reload,
            limit_concurrency=100,  # Max concurrent connections
            limit_max_requests=1000,  # Max requests per worker before restart
            timeout_keep_alive=5,  # Keep-alive timeout (seconds)
            timeout_graceful_shutdown=10  # Graceful shutdown timeout
        )
        server = uvicorn.Server(config)
        try:
            await server.serve()
        finally:
            # Cancel background cleanup task on shutdown
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
        
    except ImportError:
        print("Error: uvicorn not installed. Install with: pip install uvicorn", file=sys.stderr)
        release_sse_lock(lock_fd)
        remove_sse_pid_file()
        sys.exit(1)
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        release_sse_lock(lock_fd)
        remove_sse_pid_file()
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
        release_sse_lock(None)  # Cleanup will be handled by atexit, but try here too
        remove_sse_pid_file()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        release_sse_lock(None)
        remove_sse_pid_file()
        sys.exit(1)
