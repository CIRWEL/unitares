#!/usr/bin/env python3
"""
UNITARES Governance MCP Server - Streamable HTTP Transport

Multi-client support! Multiple agents (Cursor, Claude Desktop, etc.) can connect
simultaneously and share state via this single server instance.

Usage:
    python src/mcp_server.py [--port PORT] [--host HOST]

    Default: http://127.0.0.1:8767/mcp

Configuration (in claude_desktop_config.json or cursor mcp config):
    {
      "governance-monitor-v1": {
        "url": "http://127.0.0.1:8765/mcp"
      }
    }

Features:
    - Multiple clients share single server instance
    - Shared state across all agents (knowledge graph, dialectic, etc.)
    - Real multi-agent dialectic (agents can actually review each other!)
    - Persistent service (survives client restarts)
    - Uses MCP Streamable HTTP transport (SSE deprecated)
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

# Load environment variables from ~/.env.mcp
try:
    from dotenv import load_dotenv
    env_path = Path.home() / ".env.mcp"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# Prometheus metrics
from prometheus_client import Counter, Gauge, Histogram, REGISTRY, generate_latest, CONTENT_TYPE_LATEST

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src._imports import ensure_project_root
project_root = ensure_project_root()

from src.logging_utils import get_logger
from src.versioning import load_version_from_file
logger = get_logger(__name__)

# Process management (prevent multiple instances)
SERVER_PID_FILE = Path(project_root) / "data" / ".mcp_server.pid"
SERVER_LOCK_FILE = Path(project_root) / "data" / ".mcp_server.lock"
CURRENT_PID = os.getpid()

# Server readiness flag - prevents "request before initialization" errors
# when multiple clients reconnect simultaneously after a server restart
SERVER_READY = False
SERVER_STARTUP_TIME = None
SERVER_START_TIME = time.time()  # Track server start time for uptime metric

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

# Server uptime and health metrics
SERVER_UPTIME = Gauge(
    'unitares_server_uptime_seconds',
    'Server uptime in seconds'
)

SERVER_ERRORS_TOTAL = Counter(
    'unitares_server_errors_total',
    'Total server errors',
    ['error_type']  # database, tool_call, connection, etc.
)

REQUEST_DURATION = Histogram(
    'unitares_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0)
)

REQUEST_TOTAL = Counter(
    'unitares_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
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

    Uses SessionSignals when available (set by ASGI wrapper), otherwise
    falls back to legacy extraction paths.
    """
    # Check SessionSignals first (set by ASGI wrapper / ConnectionTrackingMiddleware)
    try:
        from src.mcp_handlers.context import get_session_signals
        signals = get_session_signals()
        if signals:
            # Same priority as derive_session_key, minus async pin lookup
            return (
                signals.x_session_id
                or (f"mcp:{signals.mcp_session_id}" if signals.mcp_session_id else None)
                or signals.oauth_client_id
                or signals.x_client_id
                or signals.ip_ua_fingerprint
            )
    except Exception:
        pass

    # Fallback: legacy extraction (for callers before signals are set)
    try:
        from src.mcp_handlers.context import get_mcp_session_id
        mcp_sid = get_mcp_session_id()
        if mcp_sid:
            return f"mcp:{mcp_sid}"
    except Exception:
        pass

    if ctx is None:
        return None

    try:
        req = ctx.request_context.request
        if req is not None:
            client_id = getattr(req.state, "governance_client_id", None)
            if client_id:
                return client_id
    except Exception:
        pass

    try:
        if ctx.client_id:
            return ctx.client_id
    except Exception:
        pass
    return None


# ============================================================================
# Server Version (sync with VERSION file)
# ============================================================================

def _load_version():
    """Load version from VERSION file."""
    return load_version_from_file(project_root)

SERVER_VERSION = _load_version()


# ============================================================================
# FastMCP Server Setup
# ============================================================================

# Import transport security settings for network access
from mcp.server.transport_security import TransportSecuritySettings

# --- OAuth 2.1 configuration (optional, enabled by env var) ---
_oauth_issuer_url = os.environ.get("UNITARES_OAUTH_ISSUER_URL")
_oauth_provider = None
_auth_settings = None

if _oauth_issuer_url:
    try:
        from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
        from src.oauth_provider import GovernanceOAuthProvider

        _oauth_secret = os.environ.get("UNITARES_OAUTH_SECRET")
        _auto_approve = os.environ.get("UNITARES_OAUTH_AUTO_APPROVE", "true").lower() in ("true", "1", "yes")
        _oauth_provider = GovernanceOAuthProvider(secret=_oauth_secret, auto_approve=_auto_approve)
        _auth_settings = AuthSettings(
            issuer_url=_oauth_issuer_url,
            resource_server_url=_oauth_issuer_url,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["mcp:tools"],
                default_scopes=["mcp:tools"],
            ),
        )
        print(f"[FastMCP] OAuth 2.1 enabled (issuer: {_oauth_issuer_url})", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[FastMCP] OAuth setup failed, continuing without auth: {e}", file=sys.stderr, flush=True)
        _oauth_provider = None
        _auth_settings = None

# Create the FastMCP server
# NOTE: host="0.0.0.0" disables auto DNS rebinding protection (needed for network access from Pi)
# We explicitly configure allowed_hosts to include local network IPs
mcp = FastMCP(
    name="governance-monitor-v1",
    host="0.0.0.0",  # Bind to all interfaces
    auth_server_provider=_oauth_provider,
    auth=_auth_settings,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "127.0.0.1:*", "localhost:*", "[::1]:*",  # Localhost
            "192.168.1.151:*", "192.168.1.164:*",  # Mac LAN IPs
            "100.96.201.46:*",  # Mac Tailscale IP
            "unitares.ngrok.io",  # Ngrok tunnel
        ],
        allowed_origins=[
            "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
            "http://192.168.1.151:*", "http://192.168.1.164:*",
            "http://100.96.201.46:*",  # Tailscale
            "https://unitares.ngrok.io",
            "null", "*",  # Allow file:// access (origin is opaque 'null') and wildcards
        ],
    ),
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
            logger.info(f"[TOOL_WRAPPER] {tool_name}: called with keys={list(kwargs.keys())}")
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
# AUTO-REGISTRATION SYSTEM
# ============================================================================
# Instead of manually decorating each tool, we auto-register from tool_schemas.py
# This prevents tools from getting out of sync between schemas and SSE server.

# Tools that need session injection from FastMCP Context
# These tools get client_session_id injected from the SSE connection
TOOLS_NEEDING_SESSION_INJECTION = {
    "onboard",
    "identity",
    "process_agent_update",
    "get_governance_metrics",
    "store_knowledge_graph",
    "search_knowledge_graph",
    "leave_note",
    "observe_agent",
    "get_agent_metadata",
    "update_agent_metadata",
    "archive_agent",
    "delete_agent",
    "get_system_history",
    "export_to_file",
    "mark_response_complete",
    "request_dialectic_review",
    "direct_resume_if_safe",
    "update_discovery_status_graph",
    "get_discovery_details",
    "dialectic",
    "get_knowledge_graph",
    "compare_me_to_similar",
}

def auto_register_all_tools():
    """
    Auto-register tools from tool_schemas.py with typed signatures.

    Only registers tools that are in the decorator registry (register=True).
    Tools with register=False in @mcp_tool decorator are skipped.

    This generates wrappers with explicit parameter signatures from JSON schemas,
    allowing FastMCP to infer correct schemas without kwargs wrapping.

    Benefits:
    - Claude.ai sends parameters directly (no kwargs wrapper needed)
    - CLI's kwargs wrapping still works (dispatch_tool unwraps)
    - Proper client autocomplete from typed signatures
    - Consolidated tools reduce cognitive load (90 → 49 tools)

    Just add the tool to:
    1. tool_schemas.py (definition)
    2. mcp_handlers/*.py (implementation with @mcp_tool)

    The SSE server will automatically pick it up.
    """
    from src.tool_schemas import get_tool_definitions
    from src.mcp_handlers.wrapper_generator import create_typed_wrapper
    from src.mcp_handlers.decorators import get_tool_registry

    tools = get_tool_definitions()
    registered_count = 0
    skipped_count = 0

    # Get tools that are registered (register=True in @mcp_tool decorator)
    registered_tools = get_tool_registry()

    for tool in tools:
        tool_name = tool.name

        # Skip tools not in registry (register=False in decorator)
        if tool_name not in registered_tools:
            skipped_count += 1
            continue

        description = tool.description.split("\n")[0] if tool.description else f"Tool: {tool_name}"
        input_schema = getattr(tool, 'inputSchema', {}) or {}
        inject_session = tool_name in TOOLS_NEEDING_SESSION_INJECTION

        try:
            # Create typed wrapper with explicit parameter signature
            wrapper = create_typed_wrapper(
                tool_name=tool_name,
                input_schema=input_schema,
                get_handler=get_tool_wrapper,
                inject_session=inject_session,
                session_extractor=_session_id_from_ctx,
            )

            # Register with FastMCP - it will infer schema from signature
            mcp.tool(description=description, structured_output=False)(wrapper)
            registered_count += 1

        except Exception as e:
            logger.warning(f"Failed to auto-register tool {tool_name}: {e}")

    logger.info(f"[AUTO_REGISTER] Registered {registered_count} tools, skipped {skipped_count} (consolidated)")
    return registered_count

# Call auto-registration
auto_register_all_tools()

# ============================================================================
# COMMON ALIASES - Register most-guessed tool names as thin MCP wrappers
# ============================================================================
# Aliases are resolved at dispatch time (tool_stability.py), but FastMCP rejects
# unknown tool names before dispatch runs. These register the top aliases so
# agents can use intuitive names like status() without "Unknown tool" errors.

def _register_common_aliases():
    from src.mcp_handlers.tool_stability import resolve_tool_alias
    from src.mcp_handlers.wrapper_generator import create_typed_wrapper

    common = ["status", "list_agents", "observe_agent", "checkin"]
    count = 0
    for alias_name in common:
        actual, info = resolve_tool_alias(alias_name)
        if not info:
            continue

        # Get the actual tool's schema so the alias has matching parameters
        from src.tool_schemas import get_tool_definitions
        actual_schema = {}
        for tool_def in get_tool_definitions():
            if tool_def.name == actual:
                actual_schema = getattr(tool_def, 'inputSchema', {}) or {}
                break

        # If inject_action is set, remove "action" from the alias schema —
        # the alias auto-injects it, so clients shouldn't need to provide it
        if info.inject_action and actual_schema:
            import copy
            actual_schema = copy.deepcopy(actual_schema)
            actual_schema.get("properties", {}).pop("action", None)
            req = actual_schema.get("required", [])
            if "action" in req:
                actual_schema["required"] = [r for r in req if r != "action"]

        try:
            # Create a handler that resolves the alias to the actual tool name
            # and auto-injects the action parameter if the alias defines one
            inject_action = info.inject_action
            def make_alias_handler(actual_name, action_to_inject):
                """Closure factory — captures actual_name and action per alias."""
                base_handler = get_tool_wrapper(actual_name)
                if action_to_inject:
                    async def aliased_handler(**kwargs):
                        kwargs.setdefault("action", action_to_inject)
                        return await base_handler(**kwargs)
                    return aliased_handler
                return base_handler

            alias_handler = make_alias_handler(actual, inject_action)

            # get_handler is called with tool_name at dispatch time, so we
            # return the pre-built alias_handler regardless of the name passed in
            def alias_get_handler(name, _h=alias_handler):
                return _h

            wrapper = create_typed_wrapper(
                tool_name=alias_name,
                input_schema=actual_schema,
                get_handler=alias_get_handler,
                inject_session=actual in TOOLS_NEEDING_SESSION_INJECTION,
                session_extractor=_session_id_from_ctx,
            )
            desc = f"{info.migration_note or f'Alias for {actual}'}"
            mcp.tool(description=desc, structured_output=False)(wrapper)
            count += 1
        except Exception as e:
            logger.debug(f"[ALIAS] Failed to register {alias_name}: {e}")

    if count:
        logger.info(f"[AUTO_REGISTER] Registered {count} common aliases")

_register_common_aliases()

# ============================================================================
# LEGACY MANUAL REGISTRATIONS (kept for reference, will be removed)
# ============================================================================
# The auto_register_all_tools() above handles all tools.
# These manual registrations below are now redundant but kept temporarily
# for any tools with special handling not captured above.

# NOTE: hello/who_am_i removed Dec 2025 - identity auto-binds on first tool call
# Use identity(name='...') for self-naming

# REMOVED: All manual @tool_no_schema decorators
# Tools are now auto-registered from tool_schemas.py

# ============================================================================
# SPECIAL HANDLERS (tools with custom SSE-only logic)
# ============================================================================
# These tools have special logic that can't be auto-generated

@tool_no_schema(description="Debug request context - shows transport, session binding, identity injection, and registry info")
async def debug_request_context(ctx: Context = None) -> dict:
    """Diagnostic tool to debug dispatch path and identity injection."""
    import hashlib
    from datetime import datetime

    session_id = _session_id_from_ctx(ctx)

    # Check session binding
    bound_agent_id = None
    session_bound = False
    try:
        from mcp_handlers.identity import get_bound_agent_id
        bound_agent_id = get_bound_agent_id(arguments={"client_session_id": session_id} if session_id else {})
        session_bound = bool(bound_agent_id)
    except Exception as e:
        bound_agent_id = f"error: {e}"

    # Get tool registry info
    tool_count = len(_tool_wrappers_cache)
    tool_names = sorted(_tool_wrappers_cache.keys())[:10]  # First 10 for brevity
    registry_hash = hashlib.md5(",".join(sorted(_tool_wrappers_cache.keys())).encode()).hexdigest()[:8]

    # Get validator info
    validator_version = "unknown"
    try:
        from mcp_handlers.validators import VALIDATOR_VERSION
        validator_version = VALIDATOR_VERSION
    except ImportError:
        validator_version = "1.0.0"  # Default if not defined

    return {
        "success": True,
        "timestamp": datetime.now().isoformat(),
        "transport": "sse",  # This tool only exists in SSE server
        "session": {
            "session_id_present": bool(session_id),
            "session_id_preview": session_id[:16] + "..." if session_id and len(session_id) > 16 else session_id,
            "bound": session_bound,
            "bound_agent_id": bound_agent_id if session_bound else None,
        },
        "identity_injection": {
            "enabled": True,
            "injection_point": "dispatch_tool (before validation)",
            "auto_create_enabled": True,
        },
        "tool_registry": {
            "count": tool_count,
            "sample_tools": tool_names,
            "registry_hash": registry_hash,
        },
        "validator": {
            "version": validator_version,
        },
        "server": {
            "version": SERVER_VERSION,
        },
    }
# NOTE: All tools are now auto-registered via auto_register_all_tools() above.
# Only SSE-specific tools (that don't exist in tool_schemas.py) need manual registration below.


    # SSE-specific tools (get_connected_clients, get_connection_diagnostics) removed Feb 2026.
    # SSE transport deprecated by MCP — use Streamable HTTP (/mcp/) instead.




# ============================================================================
# Server Entry Point
# ============================================================================

DEFAULT_HOST = "0.0.0.0"  # Changed from 127.0.0.1 to allow network access (ngrok, etc.)
DEFAULT_PORT = 8767  # Standard port for unitares governance on Mac (8766 is anima, 8765 was old default)

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="UNITARES Governance MCP Server (Streamable HTTP)"
    )
    parser.add_argument(
        "--host", 
        default=DEFAULT_HOST,
        help=f"Host to bind to (default: {DEFAULT_HOST}, use 127.0.0.1 for localhost-only)"
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
        help="Force start: clean up any stale lock files and PID files"
    )
    return parser.parse_args()


def is_process_alive(pid: int) -> bool:
    """Check if a process with given PID is still running"""
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks if process exists
        return True
    except (OSError, ProcessLookupError):
        return False


def cleanup_existing_server_processes():
    """Kill any existing server processes before starting new one"""
    if not SERVER_PID_FILE.exists():
        return []
    
    killed = []
    try:
        with open(SERVER_PID_FILE, 'r') as f:
            existing_pid = int(f.read().strip())
        
        if existing_pid != CURRENT_PID and is_process_alive(existing_pid):
            logger.info(f"Found existing server (PID {existing_pid}), terminating...")
            try:
                os.kill(existing_pid, signal.SIGTERM)
                # Wait a bit for graceful shutdown
                time.sleep(1)
                if is_process_alive(existing_pid):
                    os.kill(existing_pid, signal.SIGKILL)
                killed.append(existing_pid)
                logger.info(f"Terminated existing server (PID {existing_pid})")
            except (OSError, ProcessLookupError):
                # Process already dead, just clean up PID file
                pass
        
        # Clean up PID file if process is dead
        if not is_process_alive(existing_pid):
            SERVER_PID_FILE.unlink(missing_ok=True)
    except (ValueError, IOError) as e:
        logger.warning(f"Could not read existing PID file: {e}")
        # Clean up invalid PID file
        SERVER_PID_FILE.unlink(missing_ok=True)
    
    return killed


def write_server_pid_file():
    """Write PID file for server process tracking"""
    try:
        SERVER_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SERVER_PID_FILE, 'w') as f:
            f.write(f"{CURRENT_PID}\n")
        logger.debug(f"Wrote server PID file: {SERVER_PID_FILE} (PID: {CURRENT_PID})")
    except Exception as e:
        logger.warning(f"Could not write server PID file: {e}", exc_info=True)


def remove_server_pid_file():
    """Remove PID file on shutdown"""
    try:
        if SERVER_PID_FILE.exists():
            SERVER_PID_FILE.unlink()
            logger.debug(f"Removed server PID file: {SERVER_PID_FILE}")
    except Exception as e:
        logger.warning(f"Could not remove server PID file: {e}", exc_info=True)


def acquire_server_lock():
    """Acquire lock file to prevent multiple server instances.

    Automatically cleans up stale locks from dead processes.
    """
    lock_fd = None
    try:
        SERVER_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Check for stale lock file before trying to acquire
        if SERVER_LOCK_FILE.exists():
            try:
                with open(SERVER_LOCK_FILE, 'r') as f:
                    lock_info = json.load(f)
                    old_pid = lock_info.get("pid")
                    if old_pid and not is_process_alive(old_pid):
                        logger.info(f"Cleaning up stale lock from dead process (PID: {old_pid})")
                        SERVER_LOCK_FILE.unlink()
            except (json.JSONDecodeError, KeyError, IOError):
                # Corrupt lock file - safe to remove
                logger.info("Cleaning up corrupt lock file")
                try:
                    SERVER_LOCK_FILE.unlink()
                except FileNotFoundError:
                    pass

        lock_fd = os.open(str(SERVER_LOCK_FILE), os.O_CREAT | os.O_RDWR)

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

            logger.debug(f"Acquired server lock file: {SERVER_LOCK_FILE} (PID: {CURRENT_PID})")
            return lock_fd
        except IOError:
            # Lock is held by another process
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                except (OSError, ValueError):
                    pass
            raise RuntimeError(
                f"Server is already running (lock file: {SERVER_LOCK_FILE}). "
                f"Only one server instance can run at a time."
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
        logger.warning(f"Could not acquire server lock: {e}", exc_info=True)
        return None


def release_server_lock(lock_fd):
    """Release lock file"""
    if lock_fd is not None:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            if SERVER_LOCK_FILE.exists():
                SERVER_LOCK_FILE.unlink()
            logger.debug(f"Released server lock file: {SERVER_LOCK_FILE}")
        except Exception as e:
            logger.warning(f"Could not release server lock: {e}", exc_info=True)


async def main():
    """Main entry point for governance MCP server."""
    args = parse_args()

    # --force: Explicitly clean up lock file and PID file before starting
    if args.force:
        logger.info("--force: Cleaning up stale lock and PID files")
        try:
            if SERVER_LOCK_FILE.exists():
                SERVER_LOCK_FILE.unlink()
                logger.info(f"Removed lock file: {SERVER_LOCK_FILE}")
        except Exception as e:
            logger.warning(f"Could not remove lock file: {e}")
        try:
            if SERVER_PID_FILE.exists():
                # Check if PID is actually running before removing
                try:
                    with open(SERVER_PID_FILE, 'r') as f:
                        old_pid = int(f.read().strip())
                    if not is_process_alive(old_pid):
                        SERVER_PID_FILE.unlink()
                        logger.info(f"Removed stale PID file: {SERVER_PID_FILE} (PID {old_pid} not running)")
                    else:
                        logger.warning(f"PID file exists for running process {old_pid}, will terminate it")
                except (ValueError, IOError):
                    # Invalid PID file, safe to remove
                    SERVER_PID_FILE.unlink()
                    logger.info(f"Removed invalid PID file: {SERVER_PID_FILE}")
        except Exception as e:
            logger.warning(f"Could not remove PID file: {e}")

    # Process deduplication: Check for and kill existing server processes
    killed = cleanup_existing_server_processes()
    if killed:
        logger.info(f"Cleaned up {len(killed)} existing server process(es)")

    # Acquire lock to prevent multiple instances
    lock_fd = None
    try:
        lock_fd = acquire_server_lock()
    except RuntimeError as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        print("💡 Tip: Use --force to clean up stale locks", file=sys.stderr)
        sys.exit(1)
    
    # Write PID file
    write_server_pid_file()

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
        logger.info("Database initialized: backend=postgres")
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
        release_server_lock(lock_fd)
        remove_server_pid_file()
    
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (cleanup(), sys.exit(0)))
    
    endpoint = f"http://{args.host}:{args.port}/mcp"
    config_json = f'{{"url": "{endpoint}"}}'

    print(f"""
╔════════════════════════════════════════════════════════════════════╗
║       UNITARES Governance MCP Server                               ║
╠════════════════════════════════════════════════════════════════════╣
║  Version:  {SERVER_VERSION}                                                   ║
║                                                                    ║
║  MCP Transport:                                                    ║
║    Streamable HTTP:    {endpoint:<46}║
║                                                                    ║
║  REST API:                                                         ║
║    List tools:         GET  /v1/tools                              ║
║    Call tool:          POST /v1/tools/call                         ║
║    Health:             GET  /health                                ║
║    Metrics:            GET  /metrics                               ║
╚════════════════════════════════════════════════════════════════════╝
""")
    
    logger.info(f"Starting governance server on http://{args.host}:{args.port}/mcp")

    # Run the governance MCP server
    try:
        import uvicorn
        from starlette.routing import Route, WebSocketRoute
        from starlette.responses import JSONResponse, Response
        from starlette.middleware.cors import CORSMiddleware
        from starlette.websockets import WebSocket
        
        # Get the Starlette app from FastMCP (SSE transport)
        app = mcp.sse_app()
        
        # === Add Streamable HTTP transport (MCP 1.24.0+) ===
        # Clients can connect to /mcp for the new transport with resumability
        try:
            from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
            from mcp.server.streamable_http import StreamableHTTPServerTransport
            
            # Create session manager for Streamable HTTP
            # NOTE: stateless=True allows any client to connect without session management
            # But we still capture mcp-session-id header when present for implicit identity binding
            # This is a hybrid approach: stateless for compatibility, but identity-aware when possible
            _streamable_session_manager = StreamableHTTPSessionManager(
                app=mcp._mcp_server,  # Access the underlying MCP server
                json_response=False,  # Use SSE streams (default, more efficient)
                stateless=True,       # Allow stateless for compatibility (we handle identity separately)
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
                # For /mcp/ path, SessionSignals are already set by the ASGI wrapper
                # so we just read from scope.state if available, otherwise compute here.
                from src.mcp_handlers.context import get_session_signals, SessionSignals, set_session_signals
                signals = get_session_signals()

                if signals and signals.transport == "mcp":
                    # ASGI wrapper already set signals — reuse computed client_id
                    state = scope.get("state", {})
                    base_id = state.get("governance_client_id")
                    if not base_id:
                        base_id = signals.x_client_id or signals.ip_ua_fingerprint or "unknown"
                else:
                    # Legacy paths (SSE, REST) — compute fingerprint and build signals
                    base_id = headers.get("x-client-id") or headers.get("x-mcp-client-id")
                    ua = headers.get("user-agent", "unknown")

                    if not base_id:
                        client = scope.get("client")
                        client_ip = client[0] if (client and len(client) >= 1) else "unknown"
                        import hashlib
                        ua_fingerprint = hashlib.md5(ua.encode()).hexdigest()[:6]
                        base_id = f"{client_ip}:{ua_fingerprint}"

                    # Build SessionSignals for legacy paths (if not already set)
                    if not signals:
                        from src.mcp_handlers.context import detect_client_from_user_agent
                        legacy_signals = SessionSignals(
                            x_client_id=headers.get("x-client-id") or headers.get("x-mcp-client-id"),
                            x_session_id=headers.get("x-session-id"),
                            ip_ua_fingerprint=base_id,
                            user_agent=ua,
                            client_hint=detect_client_from_user_agent(ua),
                            x_agent_name=headers.get("x-agent-name"),
                            x_agent_id=headers.get("x-agent-id"),
                            transport="sse" if is_sse else "rest",
                        )
                        set_session_signals(legacy_signals)

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

                # PROPAGATE IDENTITY via contextvars for tool handlers
                from src.mcp_handlers.context import set_session_context, reset_session_context
                context_token = set_session_context(
                    session_key=client_id,
                    client_session_id=headers.get("x-client-id"),
                    user_agent=headers.get("user-agent")
                )

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
                    return await self.app(scope, wrapped_receive, wrapped_send)
                finally:
                    # Reset contextvars to prevent leakage
                    if 'context_token' in locals():
                        reset_session_context(context_token)
                    
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
                            f"Connection monitoring degraded. Consider restarting the server."
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

        # === Background task: KG lifecycle cleanup (daily) ===
        async def startup_kg_lifecycle():
            """Start periodic KG lifecycle cleanup after server init."""
            await asyncio.sleep(5.0)  # Wait for KG to be available
            try:
                from src.knowledge_graph_lifecycle import kg_lifecycle_background_task, run_kg_lifecycle_cleanup
                # Run initial cleanup at startup
                result = await run_kg_lifecycle_cleanup(dry_run=False)
                archived = result.get("ephemeral_archived", 0) + result.get("discoveries_archived", 0)
                if archived > 0:
                    logger.info(f"KG lifecycle startup: archived {archived} entries")
                # Start periodic task (runs every 24 hours)
                asyncio.create_task(kg_lifecycle_background_task(interval_hours=24.0))
                logger.info("Started periodic KG lifecycle cleanup (runs every 24 hours)")
            except Exception as e:
                logger.warning(f"Could not start KG lifecycle task: {e}", exc_info=True)

        asyncio.create_task(startup_kg_lifecycle())

        # === Background task: Metadata loading (non-blocking) ===
        async def background_metadata_load():
            """Load metadata in background after server starts accepting connections."""
            # Small delay to let server start accepting connections first
            await asyncio.sleep(0.5)
            
            try:
                from src.mcp_server_std import load_metadata_async
                await load_metadata_async()
                logger.info("[STARTUP] Background metadata load complete")
            except Exception as e:
                logger.warning(f"[STARTUP] Background metadata load failed: {e}. Lazy loading will handle on first access.")
                # Non-fatal - lazy loading will handle if needed

        asyncio.create_task(background_metadata_load())

        # === Background task: Orphan agent cleanup ===
        async def startup_orphan_cleanup():
            """Aggressively clean up orphan agents to prevent proliferation."""
            await asyncio.sleep(2.0)  # Wait for server initialization

            try:
                from src.mcp_handlers.lifecycle import handle_archive_orphan_agents
                result = await handle_archive_orphan_agents({
                    "zero_update_hours": 4.0,
                    "low_update_hours": 12.0,
                    "unlabeled_hours": 24.0,
                    "dry_run": False
                })
                # Extract count from response
                if result and len(result) > 0:
                    import json
                    try:
                        data = json.loads(result[0].text)
                        if data.get("archived_count", 0) > 0:
                            logger.info(f"[STARTUP] Orphan cleanup: archived {data['archived_count']} agents")
                    except:
                        pass
            except Exception as e:
                logger.warning(f"Could not run orphan cleanup: {e}", exc_info=True)

        asyncio.create_task(startup_orphan_cleanup())

        # === Background task: Automatic stuck agent recovery ===
        async def stuck_agent_recovery_task():
            """
            Automatically detect and recover stuck agents every 5 minutes.
            
            Uses proprioceptive margin + timeout to detect stuck agents, then
            automatically recovers safe ones (coherence > 0.40, risk < 0.60).
            """
            # Wait for server initialization
            await asyncio.sleep(10.0)  # Give server time to start
            
            interval_minutes = 5.0
            interval_seconds = interval_minutes * 60
            
            logger.info(f"[STUCK_AGENT_RECOVERY] Starting automatic recovery (runs every {interval_minutes} minutes)")
            
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    
                    # Detect and auto-recover stuck agents
                    from src.mcp_handlers.lifecycle import handle_detect_stuck_agents
                    
                    # Call with auto_recover=True to automatically recover safe agents
                    result = await handle_detect_stuck_agents({
                        "max_age_minutes": 30.0,
                        "critical_margin_timeout_minutes": 5.0,
                        "tight_margin_timeout_minutes": 15.0,
                        "auto_recover": True,
                        "min_updates": 1,
                        "note_cooldown_minutes": 120.0
                    })
                    
                    # Parse result (it's a Sequence[TextContent] with JSON content)
                    if result and len(result) > 0:
                        import json
                        try:
                            # Extract text from TextContent
                            from mcp.types import TextContent
                            result_text = result[0].text if isinstance(result[0], TextContent) else str(result[0])
                            
                            # Parse JSON response
                            if result_text.strip().startswith('{'):
                                result_data = json.loads(result_text)
                                stuck_agents = result_data.get('stuck_agents', [])
                                recovered = result_data.get('recovered', [])
                                
                                if len(stuck_agents) > 0 or len(recovered) > 0:
                                    logger.info(
                                        f"[STUCK_AGENT_RECOVERY] Detected {len(stuck_agents)} stuck agent(s), "
                                        f"recovered {len(recovered)} safe agent(s)"
                                    )
                                    # Log details for recovered agents
                                    for rec in recovered:
                                        logger.debug(
                                            f"[STUCK_AGENT_RECOVERY] Recovered agent {rec.get('agent_id', 'unknown')[:8]}... "
                                            f"(reason: {rec.get('reason', 'unknown')})"
                                        )
                        except (json.JSONDecodeError, AttributeError, KeyError) as e:
                            logger.debug(f"[STUCK_AGENT_RECOVERY] Could not parse result: {e}")
                    
                except asyncio.CancelledError:
                    logger.info("[STUCK_AGENT_RECOVERY] Task cancelled")
                    break
                except Exception as e:
                    logger.warning(f"[STUCK_AGENT_RECOVERY] Error in recovery task: {e}", exc_info=True)
                    # Continue running even if one iteration fails
                    await asyncio.sleep(60.0)  # Wait 1 minute before retrying
        
        # Start stuck agent recovery task (non-blocking)
        asyncio.create_task(stuck_agent_recovery_task())

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

        # === Periodic EISV sync from Pi ===
        try:
            from src.mcp_handlers.pi_orchestration import eisv_sync_task
            asyncio.create_task(eisv_sync_task(interval_minutes=5.0))
            logger.info("[EISV_SYNC] Started periodic Pi EISV sync")
        except Exception as e:
            logger.warning(f"[EISV_SYNC] Could not start: {e}")

        # === Periodic expired session cleanup (PG + Redis) ===
        async def session_cleanup_task(interval_hours: float = 6.0):
            """Delete expired sessions from PG and orphaned Redis session cache keys."""
            while True:
                await asyncio.sleep(interval_hours * 3600)
                pg_deleted = 0
                redis_deleted = 0

                # 1. Get expired session keys from PG before deleting
                expired_session_keys = []
                try:
                    db = get_db()
                    pool = db._pool
                    if pool:
                        async with pool.acquire() as conn:
                            # Collect expired session keys for Redis cleanup
                            rows = await conn.fetch(
                                "SELECT session_key FROM core.sessions WHERE expires_at <= now()"
                            )
                            expired_session_keys = [r["session_key"] for r in rows]
                            # Delete expired PG rows
                            result = await conn.execute("DELETE FROM core.sessions WHERE expires_at <= now()")
                            pg_deleted = int(result.split()[-1]) if result else 0
                except Exception as e:
                    logger.warning(f"[SESSION_CLEANUP] PG cleanup failed: {e}")

                # 2. Delete matching Redis session cache keys
                if expired_session_keys:
                    try:
                        from src.cache.redis_client import get_redis
                        redis = await get_redis()
                        if redis is not None:
                            for sk in expired_session_keys:
                                try:
                                    removed = await redis.delete(f"session:{sk}")
                                    if removed:
                                        redis_deleted += 1
                                except Exception:
                                    pass
                    except Exception as e:
                        logger.warning(f"[SESSION_CLEANUP] Redis cleanup failed: {e}")

                if pg_deleted or redis_deleted:
                    logger.info(
                        f"[SESSION_CLEANUP] Deleted {pg_deleted} expired PG sessions, "
                        f"{redis_deleted} Redis cache keys"
                    )

        asyncio.create_task(session_cleanup_task(interval_hours=6.0))
        logger.info("[SESSION_CLEANUP] Started periodic expired session cleanup (every 6h)")

        # === HTTP REST endpoints for non-MCP clients (Llama, Mistral, etc.) ===
        # Any model that can make HTTP calls can use governance
        HTTP_API_TOKEN = os.getenv("UNITARES_HTTP_API_TOKEN")
        HTTP_CORS_ALLOW_ORIGIN = os.getenv("UNITARES_HTTP_CORS_ALLOW_ORIGIN")  # e.g. "*" or "http://localhost:3000"

        # Trusted networks: localhost, Tailscale CGNAT, private RFC1918 ranges
        import ipaddress as _ipaddress
        _TRUSTED_NETWORKS = [
            _ipaddress.ip_network("127.0.0.0/8"),
            _ipaddress.ip_network("::1/128"),
            _ipaddress.ip_network("100.64.0.0/10"),   # Tailscale CGNAT
            _ipaddress.ip_network("192.168.0.0/16"),
            _ipaddress.ip_network("10.0.0.0/8"),
            _ipaddress.ip_network("172.16.0.0/12"),
        ]

        def _is_trusted_network(request) -> bool:
            """Check if request originates from a trusted network."""
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()
            else:
                client_ip = request.client.host if request.client else None
            if not client_ip:
                return False
            try:
                addr = _ipaddress.ip_address(client_ip)
                return any(addr in net for net in _TRUSTED_NETWORKS)
            except ValueError:
                return False

        def _http_unauthorized():
            return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)

        def _check_http_auth(request) -> bool:
            """Bearer token auth for HTTP endpoints. Trusted networks bypass auth."""
            if _is_trusted_network(request):
                return True
            if not HTTP_API_TOKEN:
                return True
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if not auth or not isinstance(auth, str):
                return False
            if not auth.lower().startswith("bearer "):
                return False
            token = auth.split(" ", 1)[1].strip()
            return token == HTTP_API_TOKEN

        async def _extract_client_session_id(request) -> str:
            """
            Stable per-client session id for HTTP callers.
            Uses SessionSignals + derive_session_key() for unified derivation.
            Falls back to legacy logic if signals unavailable.
            """
            from src.mcp_handlers.context import SessionSignals
            from src.mcp_handlers.identity_v2 import derive_session_key, ua_hash_from_header

            # Build SessionSignals from request headers
            ua = request.headers.get("user-agent", "")
            x_session_id = request.headers.get("X-Session-ID") or request.headers.get("x-session-id")

            # Compute IP:UA fingerprint
            ip_ua_fp = None
            try:
                host = request.client.host if request.client else "unknown"
                import hashlib
                ua_fp = hashlib.md5(ua.encode()).hexdigest()[:6] if ua else "000000"
                ip_ua_fp = f"{host}:{ua_fp}"
            except Exception:
                pass

            signals = SessionSignals(
                x_session_id=x_session_id,
                x_client_id=request.headers.get("x-client-id") or request.headers.get("x-mcp-client-id"),
                ip_ua_fingerprint=ip_ua_fp,
                user_agent=ua,
                x_agent_name=request.headers.get("x-agent-name"),
                x_agent_id=request.headers.get("x-agent-id"),
                transport="rest",
            )

            result = await derive_session_key(signals)

            # If derive_session_key returned the raw IP:UA fingerprint (no pin found),
            # and there's no explicit session header, generate a unique ID so REST
            # clients without session headers get distinct identities per request chain.
            if result == ip_ua_fp and not x_session_id:
                try:
                    if hasattr(request, "state") and hasattr(request.state, "governance_client_id"):
                        return str(getattr(request.state, "governance_client_id"))
                except Exception:
                    pass
                import uuid as _uuid
                unique_id = str(_uuid.uuid4())[:12]
                try:
                    host = request.client.host if request.client else "unknown"
                    return f"http:{host}:{unique_id}"
                except Exception:
                    return f"http:unknown:{unique_id}"

            return result
        
        async def http_list_tools(request):
            """List all tools in OpenAI-compatible format

            Query params:
                mode: Tool mode filter - "minimal", "lite", "full" (default from GOVERNANCE_TOOL_MODE env)
            """
            try:
                if not _check_http_auth(request):
                    return _http_unauthorized()
                from src.tool_schemas import get_tool_definitions
                from src.tool_modes import TOOL_MODE, should_include_tool

                # Get mode from query param or env default
                query_mode = request.query_params.get("mode", TOOL_MODE)

                # get_tool_definitions() is synchronous, no await needed
                mcp_tools = get_tool_definitions()

                # Filter tools by mode
                filtered_tools = [t for t in mcp_tools if should_include_tool(t.name, mode=query_mode)]

                openai_tools = []
                for tool in filtered_tools:
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
                    "mode": query_mode,
                    "total_available": len(mcp_tools),
                    "note": f"Showing {len(filtered_tools)}/{len(mcp_tools)} tools in '{query_mode}' mode. Use ?mode=full for all."
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
                
                # DEPRECATED: SSE-specific tools removed
                # These tools are no longer registered but kept for backward compat
                if tool_name == "get_connected_clients":
                    # Return deprecation notice
                    return JSONResponse({
                        "name": tool_name,
                        "result": {"error": "Tool deprecated. SSE transport deprecated by MCP. Use Streamable HTTP."},
                        "success": False
                    })
                    # Old code:
                    # clients = connection_tracker.get_connected_clients()
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
                    # DEPRECATED: SSE-specific tool
                    return JSONResponse({
                        "name": tool_name,
                        "result": {"error": "Tool deprecated. SSE transport deprecated by MCP. Use Streamable HTTP."},
                        "success": False
                    })
                
                # Inject stable client session for identity binding (avoid collision with dialectic session_id)
                client_session_id = None
                if isinstance(arguments, dict) and "client_session_id" not in arguments:
                    client_session_id = await _extract_client_session_id(request)
                    arguments["client_session_id"] = client_session_id
                elif isinstance(arguments, dict):
                    client_session_id = arguments.get("client_session_id")

                # NOTE: X-Agent-Id NOT injected as agent_id pre-dispatch.
                # Session binding via X-Session-ID handles identity.
                x_agent_id = request.headers.get("x-agent-id") or request.headers.get("X-Agent-Id")

                # AUTO-DETECT CLIENT TYPE and MODEL TYPE from User-Agent for better auto-naming
                # This ensures agent_id becomes "cursor_20251226" instead of "mcp_20251226"
                # Also detects model type to prevent identity collision between different models
                if isinstance(arguments, dict):
                    ua = (request.headers.get("user-agent") or "").lower()
                    
                    # Detect client type
                    if "client_hint" not in arguments:
                        detected_client = None
                        if "cursor" in ua:
                            detected_client = "cursor"
                        elif "claude" in ua or "anthropic" in ua:
                            detected_client = "claude_desktop"
                        elif "chatgpt" in ua or "openai" in ua:
                            detected_client = "chatgpt"
                        elif "vscode" in ua or "visual studio code" in ua:
                            detected_client = "vscode"

                        if detected_client:
                            arguments["client_hint"] = detected_client
                            logger.debug(f"[HTTP] Auto-detected client_hint={detected_client} from UA")
                    
                    # Detect model type to prevent identity collision
                    if "model_type" not in arguments:
                        detected_model = None
                        # Check for model identifiers in User-Agent
                        if "composer" in ua or "cursor.*composer" in ua:
                            detected_model = "composer"
                        elif "chatgpt" in ua or "gpt-4" in ua or "gpt-3" in ua:
                            detected_model = "chatgpt"
                        elif "claude" in ua:
                            detected_model = "claude"
                        elif "gemini" in ua:
                            detected_model = "gemini"
                        
                        # Also check X-Model header if available
                        if not detected_model:
                            model_header = request.headers.get("x-model") or request.headers.get("X-Model")
                            if model_header:
                                detected_model = model_header.lower()
                        
                        if detected_model:
                            arguments["model_type"] = detected_model
                            logger.debug(f"[HTTP] Auto-detected model_type={detected_model} from headers")

                # SET SESSION CONTEXT for contextvars-based identity lookup
                # This allows success_response() and status() to find binding without arguments
                from src.mcp_handlers.context import set_session_context, reset_session_context
                context_token = set_session_context(
                    session_key=client_session_id,
                    client_session_id=client_session_id,
                    agent_id=x_agent_id or (arguments.get("agent_id") if isinstance(arguments, dict) else None),
                )
                try:
                    result = await dispatch_tool(tool_name, arguments)
                finally:
                    reset_session_context(context_token)
                
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
            """Health check endpoint — always public (monitoring, load balancers)"""
            
            # Calculate uptime
            uptime_seconds = time.time() - SERVER_START_TIME
            uptime_hours = uptime_seconds / 3600
            uptime_days = uptime_hours / 24
            
            # Format uptime string
            if uptime_days >= 1:
                uptime_str = f"{int(uptime_days)}d {int((uptime_hours % 24))}h {int((uptime_seconds % 3600) / 60)}m"
            elif uptime_hours >= 1:
                uptime_str = f"{int(uptime_hours)}h {int((uptime_seconds % 3600) / 60)}m {int(uptime_seconds % 60)}s"
            else:
                uptime_str = f"{int(uptime_seconds / 60)}m {int(uptime_seconds % 60)}s"
            
            # DB pool health
            db_health = {"status": "unknown"}
            try:
                from src.db import get_db
                db = get_db()
                if hasattr(db, '_pool') and db._pool is not None:
                    pool = db._pool
                    db_health = {
                        "status": "connected",
                        "pool_size": pool.get_size(),
                        "pool_idle": pool.get_idle_size(),
                        "pool_max": pool.get_max_size(),
                    }
                else:
                    db_health = {"status": "no_pool"}
            except Exception as e:
                db_health = {"status": "error", "error": str(e)}

            return JSONResponse({
                "status": "ok" if SERVER_READY else "warming_up",
                "version": SERVER_VERSION,
                "uptime": {
                    "seconds": int(uptime_seconds),
                    "formatted": uptime_str,
                    "started_at": datetime.fromtimestamp(SERVER_START_TIME).isoformat() if SERVER_START_TIME else None
                },
                "connections": {
                    "active": connection_tracker.count,
                    "healthy": sum(1 for c in connection_tracker.connections.values() if c.get("health_status") == "healthy")
                },
                "database": db_health,
                "transports": {
                    "streamable_http": "/mcp (primary, with resumability)" if HAS_STREAMABLE_HTTP else "not available",
                    "sse": "/sse (legacy, deprecated)"
                },
                "endpoints": {
                    "list_tools": "GET /v1/tools",
                    "call_tool": "POST /v1/tools/call",
                    "health": "GET /health",
                    "metrics": "GET /metrics",
                    "dashboard": "GET /dashboard"
                },
                "auth": {
                    "enabled": bool(HTTP_API_TOKEN),
                    "header": "Authorization: Bearer <token>" if HTTP_API_TOKEN else None
                },
                "session": {
                    "header": "X-Session-ID (recommended for stable identity binding)"
                },
                "identity": {
                    "header": "X-Agent-Id",
                    "description": "CLI/GPT identity - pass your agent name to maintain identity across REST requests"
                },
                "note": "Use /mcp for MCP clients (Streamable HTTP). Legacy /sse still works but is deprecated."
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
                
                # Server uptime
                uptime_seconds = time.time() - SERVER_START_TIME
                SERVER_UPTIME.set(uptime_seconds)

                # Connection metrics
                CONNECTIONS_ACTIVE.set(connection_tracker.count)

                # Agent metrics (from metadata file)
                try:
                    from src.mcp_handlers.shared import get_mcp_server
                    mcp_server = get_mcp_server()
                    # Use async version to avoid race condition with PostgreSQL connection pool
                    await mcp_server.load_metadata_async()

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
        
        # Dashboard endpoint
        async def http_dashboard(request):
            """Serve the web dashboard"""
            dashboard_path = Path(__file__).parent.parent / "dashboard" / "index.html"
            if dashboard_path.exists():
                html = dashboard_path.read_text()
                # Inject API token so dashboard JS can authenticate
                if HTTP_API_TOKEN:
                    token_script = (
                        f'<script>if(!localStorage.getItem("unitares_api_token"))'
                        f'{{localStorage.setItem("unitares_api_token","{HTTP_API_TOKEN}")}}</script>'
                    )
                    html = html.replace("</head>", f"{token_script}</head>", 1)
                return Response(
                    content=html,
                    media_type="text/html"
                )
            return JSONResponse({
                "error": "Dashboard not found",
                "path": str(dashboard_path)
            }, status_code=404)
        
        # Dashboard static files (utils.js, components.js)
        async def http_dashboard_static(request):
            """Serve dashboard static files"""
            file_path = request.path_params.get("file", "")
            if not file_path or ".." in file_path:
                return JSONResponse({"error": "Invalid file path"}, status_code=400)
            
            # Only allow specific files for security
            allowed_files = [
                "utils.js", "state.js", "colors.js", "components.js",
                "visualizations.js", "agents.js", "discoveries.js",
                "dialectic.js", "eisv-charts.js", "timeline.js",
                "styles.css", "dashboard.js",
            ]
            if file_path not in allowed_files:
                return JSONResponse({
                    "error": "File not allowed",
                    "requested": file_path,
                    "allowed": allowed_files
                }, status_code=403)
            
            static_path = Path(__file__).parent.parent / "dashboard" / file_path
            if static_path.exists() and static_path.is_file():
                # Determine content type
                content_type = "application/javascript"
                if file_path.endswith(".css"):
                    content_type = "text/css"
                elif file_path.endswith(".json"):
                    content_type = "application/json"
                
                return Response(
                    content=static_path.read_text(),
                    media_type=content_type
                )
            return JSONResponse({
                "error": "File not found",
                "path": str(static_path)
            }, status_code=404)
        
        # Register HTTP endpoints
        # IMPORTANT: Static file route must come BEFORE dashboard route to match /dashboard/utils.js, etc.
        app.routes.append(Route("/dashboard/{file}", http_dashboard_static, methods=["GET"]))
        app.routes.append(Route("/dashboard", http_dashboard, methods=["GET"]))
        app.routes.append(Route("/", http_dashboard, methods=["GET"]))  # Root also serves dashboard
        app.routes.append(Route("/v1/tools", http_list_tools, methods=["GET"]))
        app.routes.append(Route("/v1/tools/call", http_call_tool, methods=["POST"]))
        app.routes.append(Route("/health", http_health, methods=["GET"]))
        app.routes.append(Route("/metrics", http_metrics, methods=["GET"]))

        from src.broadcaster import broadcaster_instance

        async def websocket_eisv_stream(websocket: WebSocket):
            """WebSocket endpoint for live EISV streaming to dashboard."""
            await broadcaster_instance.connect(websocket)
            try:
                while True:
                    # Keep connection alive — client sends pings, we just listen
                    await websocket.receive_text()
            except Exception:
                await broadcaster_instance.disconnect(websocket)

        app.routes.append(WebSocketRoute("/ws/eisv", websocket_eisv_stream))

        # HTTP polling fallback for EISV (when WebSocket is blocked by proxy/ngrok auth)
        async def http_eisv_latest(request):
            """Return the latest EISV update as JSON (polling fallback for WebSocket)."""
            if broadcaster_instance.last_update:
                return JSONResponse(broadcaster_instance.last_update)
            return JSONResponse({"type": "no_data", "message": "No EISV updates yet"}, status_code=200)

        app.routes.append(Route("/v1/eisv/latest", http_eisv_latest, methods=["GET"]))

        # Events API endpoint for dashboard
        async def http_events(request):
            """Return recent governance events for dashboard."""
            if not _check_http_auth(request):
                return _http_unauthorized()
            try:
                from src.event_detector import event_detector

                limit = int(request.query_params.get("limit", 50))
                agent_id = request.query_params.get("agent_id")
                event_type = request.query_params.get("type")
                since_raw = request.query_params.get("since")
                since = int(since_raw) if since_raw is not None else None

                events = event_detector.get_recent_events(
                    limit=limit,
                    agent_id=agent_id,
                    event_type=event_type,
                    since=since
                )

                return JSONResponse({
                    "success": True,
                    "events": events,
                    "count": len(events)
                })
            except Exception as e:
                logger.error(f"Error fetching events: {e}")
                return JSONResponse({
                    "success": False,
                    "error": str(e),
                    "events": []
                }, status_code=500)

        app.routes.append(Route("/api/events", http_events, methods=["GET"]))

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
            
            # Create a pure ASGI app for /mcp that wraps the session manager
            # Using Mount with an ASGI app avoids Starlette's Route handler wrapper
            # which expects a Response to be returned (causing NoneType callable error)
            async def streamable_mcp_asgi(scope, receive, send):
                """ASGI app for Streamable HTTP MCP at /mcp."""
                # Only handle HTTP requests
                if scope.get("type") != "http":
                    return

                if not _streamable_running:
                    # Return 503 if not ready
                    response = JSONResponse({
                        "error": "Streamable HTTP transport not ready",
                        "hint": "Try again in a moment"
                    }, status_code=503)
                    await response(scope, receive, send)
                    return

                # BUILD SESSION SIGNALS — single capture of all transport headers
                # No priority decisions here; derive_session_key() handles that.
                client_hint_token = None
                mcp_session_token = None
                signals_token = None
                try:
                    from starlette.datastructures import Headers
                    from src.mcp_handlers.context import (
                        SessionSignals, set_session_signals, reset_session_signals,
                        detect_client_from_user_agent, set_transport_client_hint, reset_transport_client_hint,
                        set_mcp_session_id, reset_mcp_session_id
                    )
                    headers = Headers(scope=scope)

                    # Extract all headers into SessionSignals (no priority decisions)
                    mcp_sid = headers.get("mcp-session-id")
                    client = scope.get("client")
                    client_ip = client[0] if (client and len(client) >= 1) else "unknown"
                    ua = headers.get("user-agent", "unknown")
                    import hashlib
                    ua_fingerprint = hashlib.md5(ua.encode()).hexdigest()[:6]
                    x_session_id = headers.get("x-session-id")
                    x_client_id = headers.get("x-client-id") or headers.get("x-mcp-client-id")

                    # Extract OAuth client identity from Bearer token
                    oauth_client_id = None
                    auth_header = headers.get("authorization", "")
                    if auth_header.startswith("Bearer "):
                        token = auth_header[7:]
                        try:
                            token_data = _oauth_provider._access_tokens.get(token) if _oauth_provider else None
                            if token_data and hasattr(token_data, "client_id"):
                                oauth_client_id = f"oauth:{token_data.client_id}"
                        except Exception:
                            pass

                    detected_client = detect_client_from_user_agent(ua)
                    ip_ua_fp = f"{client_ip}:{ua_fingerprint}"

                    signals = SessionSignals(
                        mcp_session_id=mcp_sid,
                        x_session_id=x_session_id,
                        x_client_id=x_client_id,
                        oauth_client_id=oauth_client_id,
                        ip_ua_fingerprint=ip_ua_fp,
                        user_agent=ua,
                        client_hint=detected_client,
                        x_agent_name=headers.get("x-agent-name"),
                        x_agent_id=headers.get("x-agent-id"),
                        transport="mcp",
                    )
                    signals_token = set_session_signals(signals)

                    # Backward compat: set individual contextvars that downstream code reads
                    if mcp_sid:
                        mcp_session_token = set_mcp_session_id(mcp_sid)

                    # Backward compat: expose client_id in scope.state for ConnectionTrackingMiddleware consumers
                    client_id = x_session_id or oauth_client_id or x_client_id or ip_ua_fp
                    state = scope.setdefault("state", {})
                    state["governance_client_id"] = client_id

                    # Backward compat: set session context
                    from src.mcp_handlers.context import set_session_context, reset_session_context
                    session_context_token = set_session_context(
                        session_key=signals.ip_ua_fingerprint or "unknown",
                        client_session_id=x_session_id or x_client_id,
                        user_agent=ua,
                    )

                    if detected_client:
                        client_hint_token = set_transport_client_hint(detected_client)

                except Exception as e:
                    logger.debug(f"[/mcp] Could not capture context: {e}")

                try:
                    # Delegate to the session manager - it handles ASGI directly
                    await _streamable_session_manager.handle_request(scope, receive, send)
                except Exception as e:
                    logger.error(f"Streamable HTTP error: {e}", exc_info=True)
                    response = JSONResponse({
                        "error": "Streamable HTTP transport error",
                        "details": str(e)
                    }, status_code=500)
                    await response(scope, receive, send)
                finally:
                    # Reset contextvars
                    if 'session_context_token' in locals() and session_context_token is not None:
                        try:
                            from src.mcp_handlers.context import reset_session_context
                            reset_session_context(session_context_token)
                        except Exception:
                            pass
                    if mcp_session_token is not None:
                        try:
                            from src.mcp_handlers.context import reset_mcp_session_id
                            reset_mcp_session_id(mcp_session_token)
                        except Exception:
                            pass
                    if client_hint_token is not None:
                        try:
                            from src.mcp_handlers.context import reset_transport_client_hint
                            reset_transport_client_hint(client_hint_token)
                        except Exception:
                            pass
                    if signals_token is not None:
                        try:
                            from src.mcp_handlers.context import reset_session_signals
                            reset_session_signals(signals_token)
                        except Exception:
                            pass

            # Mount as ASGI app instead of Route handler (avoids NoneType callable error)
            from starlette.routing import Mount
            app.routes.append(Mount("/mcp", app=streamable_mcp_asgi))
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
            timeout_graceful_shutdown=10,  # Graceful shutdown timeout
            forwarded_allow_ips="*",  # Trust proxy headers (ngrok, etc.) - fixes 421 errors
            proxy_headers=True  # Process X-Forwarded-* headers
        )
        server = uvicorn.Server(config)
        await server.serve()
        
    except ImportError:
        print("Error: uvicorn not installed. Install with: pip install uvicorn", file=sys.stderr)
        release_server_lock(lock_fd)
        remove_server_pid_file()
        sys.exit(1)
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        release_server_lock(lock_fd)
        remove_server_pid_file()
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
        release_server_lock(None)  # Cleanup will be handled by atexit, but try here too
        remove_server_pid_file()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        release_server_lock(None)
        remove_server_pid_file()
        sys.exit(1)
