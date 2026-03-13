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

# Prometheus metrics (REGISTRY, generate_latest, CONTENT_TYPE_LATEST used in http_api.py)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src._imports import ensure_project_root
project_root = ensure_project_root()

from src.logging_utils import get_logger
from src.versioning import load_version_from_file
logger = get_logger(__name__)

# Server readiness flag - prevents "request before initialization" errors
# when multiple clients reconnect simultaneously after a server restart
SERVER_READY = False
SERVER_STARTUP_TIME = None
SERVER_START_TIME = time.time()  # Track server start time for uptime metric

# ============================================================================
# Prometheus Metrics & Connection Tracking
# ============================================================================
from src.metrics_registry import (
    TOOL_CALLS_TOTAL, TOOL_CALL_DURATION,
)
from src.connection_tracker import (
    ConnectionTracker, ConnectionTrackingMiddleware,
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
# (ConnectionTracker and ConnectionTrackingMiddleware live in src/connection_tracker.py)
# ============================================================================

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
            "null",  # Allow file:// access (origin is opaque 'null')
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
    from src.mcp_handlers.support.wrapper_generator import create_typed_wrapper
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
    from src.mcp_handlers.support.wrapper_generator import create_typed_wrapper

    common = ["status", "list_agents", "observe_agent"]
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
        from src.mcp_handlers.identity.shared import get_bound_agent_id
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


from src.process_management import (
    is_process_alive, cleanup_existing_server_processes,
    write_server_pid_file, remove_server_pid_file,
    acquire_server_lock, release_server_lock,
    SERVER_PID_FILE, SERVER_LOCK_FILE, CURRENT_PID,
)


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
        # CORS: restrict to known origins (dashboard, local dev, Tailscale)
        _cors_allow_origin = os.getenv("UNITARES_HTTP_CORS_ALLOW_ORIGIN")
        _cors_origins = [
            "http://localhost:8767",
            "http://127.0.0.1:8767",
            "http://192.168.1.0/16",
        ]
        if _cors_allow_origin:
            _cors_origins.append(_cors_allow_origin)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_cors_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["*"],
        )
        
        # === Connection Tracking Middleware (ASGI-safe for streaming SSE) ===
        # Class lives in src/connection_tracker.py — see ConnectionTrackingMiddleware
        app.add_middleware(
            ConnectionTrackingMiddleware,
            connection_tracker=connection_tracker,
            server_ready_fn=lambda: SERVER_READY,
            server_version=SERVER_VERSION,
        )
        
        # === Start all background tasks ===
        from src.background_tasks import start_all_background_tasks

        def _set_server_ready():
            global SERVER_READY, SERVER_STARTUP_TIME
            SERVER_READY = True
            SERVER_STARTUP_TIME = datetime.now()

        start_all_background_tasks(
            connection_tracker=connection_tracker,
            set_ready=_set_server_ready,
        )

        # === HTTP REST endpoints for non-MCP clients (Llama, Mistral, etc.) ===
        HTTP_CORS_ALLOW_ORIGIN = os.getenv("UNITARES_HTTP_CORS_ALLOW_ORIGIN")  # e.g. "*" or "http://localhost:3000"

        from src.http_api import register_http_routes
        register_http_routes(
            app,
            connection_tracker=connection_tracker,
            server_ready_fn=lambda: SERVER_READY,
            server_start_time=SERVER_START_TIME,
            server_version=SERVER_VERSION,
            has_streamable_http=HAS_STREAMABLE_HTTP,
            mcp_server_name=mcp.name,
        )

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
                            client_id = _oauth_provider.get_token_client_id(token) if _oauth_provider else None
                            if client_id:
                                oauth_client_id = f"oauth:{client_id}"
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

        # NOTE: CORS middleware is already registered above (line ~780).
        # HTTP_CORS_ALLOW_ORIGIN is merged into the main CORS config there.
        # Do not add a second CORSMiddleware — duplicate registration causes confusing behavior.
        
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
