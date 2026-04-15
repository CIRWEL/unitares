"""
HTTP REST API endpoints for non-MCP clients (Llama, Mistral, GPT, dashboards, etc.).

Extracted from mcp_server.py to keep the server entry point focused on MCP transport.

Usage:
    from src.http_api import register_http_routes
    register_http_routes(app, ...)
"""

from __future__ import annotations

import ipaddress as _ipaddress
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

_startup_ts = time.time()

from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute

from prometheus_client import REGISTRY, generate_latest, CONTENT_TYPE_LATEST

from src.logging_utils import get_logger
from src.metrics_registry import (
    AGENTS_TOTAL,
    DIALECTIC_SESSIONS_ACTIVE,
    KNOWLEDGE_NODES_TOTAL,
    SERVER_INFO,
    SERVER_UPTIME,
)
from src.connection_tracker import CONNECTIONS_ACTIVE
from src.broadcaster import broadcaster_instance
from src.services.http_tool_service import execute_http_tool

if TYPE_CHECKING:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.websockets import WebSocket
    from src.connection_tracker import ConnectionTracker

logger = get_logger(__name__)


def _build_http_session_signals(request):
    """Build SessionSignals from an HTTP request."""
    from src.mcp_handlers.context import SessionSignals

    ua = request.headers.get("user-agent", "")
    x_session_id = request.headers.get("X-Session-ID") or request.headers.get("x-session-id")

    ip_ua_fp = None
    try:
        host = request.client.host if request.client else "unknown"
        import hashlib
        ua_fp = hashlib.md5(ua.encode()).hexdigest()[:6] if ua else "000000"
        ip_ua_fp = f"{host}:{ua_fp}"
    except Exception:
        pass

    return SessionSignals(
        x_session_id=x_session_id,
        x_client_id=request.headers.get("x-client-id") or request.headers.get("x-mcp-client-id"),
        ip_ua_fingerprint=ip_ua_fp,
        user_agent=ua,
        x_agent_name=request.headers.get("x-agent-name"),
        x_agent_id=request.headers.get("x-agent-id"),
        transport="rest",
    )


def _serialize_mcp_content_item(item):
    """Convert MCP content items into JSON-serializable dicts."""
    if hasattr(item, "model_dump"):
        return item.model_dump(exclude_none=True)
    if isinstance(item, dict):
        return item
    if hasattr(item, "__dict__"):
        return {k: v for k, v in vars(item).items() if v is not None}
    return {"type": "unknown", "value": str(item)}


def _build_http_tool_response(tool_name: str, result) -> dict:
    """Normalize MCP handler output into the HTTP API response contract."""
    if result is None:
        return {
            "name": tool_name,
            "result": None,
            "success": False,
            "error": f"Tool '{tool_name}' returned no result"
        }

    if isinstance(result, (list, tuple)):
        if len(result) == 0:
            return {
                "name": tool_name,
                "result": None,
                "success": False,
                "error": f"Tool '{tool_name}' returned empty result"
            }

        if len(result) == 1 and hasattr(result[0], "text"):
            try:
                parsed = json.loads(result[0].text)
                return {"name": tool_name, "result": parsed, "success": True}
            except json.JSONDecodeError:
                text_result = result[0].text if result[0].text else "{}"
                return {"name": tool_name, "result": text_result, "success": True}

        return {
            "name": tool_name,
            "result": {"content": [_serialize_mcp_content_item(item) for item in result]},
            "success": True,
        }

    if isinstance(result, dict):
        return {"name": tool_name, "result": result, "success": True}

    result_str = str(result) if result else "null"
    return {"name": tool_name, "result": result_str, "success": True}


def _normalize_http_tool_name(body: dict, mcp_server_name: str) -> str:
    """Resolve HTTP tool aliases to the canonical dispatch name."""
    tool_name = body.get("name") or body.get("tool_name") or "unknown"
    if not tool_name or tool_name == "unknown":
        return "unknown"

    # Compatibility: Some MCP clients surface names as `mcp_<server>_<tool>`.
    # The HTTP API always dispatches by the canonical tool name (e.g. `list_tools`).
    mcp_prefix = f"mcp_{mcp_server_name}_"
    if tool_name.startswith(mcp_prefix):
        return tool_name[len(mcp_prefix):]
    return tool_name

# ---------------------------------------------------------------------------
# Trusted networks: localhost, Tailscale CGNAT, private RFC1918 ranges
# ---------------------------------------------------------------------------
_TRUSTED_NETWORKS = [
    _ipaddress.ip_network("127.0.0.0/8"),
    _ipaddress.ip_network("::1/128"),
    _ipaddress.ip_network("100.64.0.0/10"),   # Tailscale CGNAT
    _ipaddress.ip_network("192.168.0.0/16"),
    _ipaddress.ip_network("10.0.0.0/8"),
    _ipaddress.ip_network("172.16.0.0/12"),
]


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _is_trusted_network(request) -> bool:
    """Check if request originates from a trusted network.

    Uses the actual TCP peer address only -- never trust X-Forwarded-For
    since there is no reverse proxy stripping it before us.
    """
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


def _check_http_auth(request, *, http_api_token: str | None) -> bool:
    """Bearer token auth for HTTP endpoints. Trusted networks bypass auth."""
    if _is_trusted_network(request):
        return True
    if not http_api_token:
        return True
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not isinstance(auth, str):
        return False
    if not auth.lower().startswith("bearer "):
        return False
    token = auth.split(" ", 1)[1].strip()
    return secrets.compare_digest(token, http_api_token)


async def _extract_client_session_id(request) -> str:
    """
    Stable per-client session id for HTTP callers.
    Uses SessionSignals + derive_session_key() for unified derivation.
    Falls back to legacy logic if signals unavailable.
    """
    from src.mcp_handlers.identity.handlers import derive_session_key, ua_hash_from_header

    signals = _build_http_session_signals(request)
    ua = signals.user_agent or ""
    x_session_id = signals.x_session_id
    ip_ua_fp = signals.ip_ua_fingerprint

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


async def _resolve_http_bound_agent(tool_name: str, arguments: dict, signals) -> str | None:
    """Resolve an existing identity for HTTP requests before direct tool calls.

    This keeps direct HTTP tools like process_agent_update aligned with the
    fallback middleware path, which would otherwise inject session-bound identity.
    """
    if not isinstance(arguments, dict):
        return None

    # These tools establish or inspect identity; they should not be pre-bound.
    skip_tools = {
        "identity",
        "onboard",
        "bind_session",
        "health_check",
        "list_tools",
        "get_server_info",
        "describe_tool",
        "debug_request_context",
    }
    if tool_name in skip_tools:
        return None

    from src.mcp_handlers.context import update_context_agent_id
    from src.mcp_handlers.identity.handlers import derive_session_key, resolve_session_identity

    # Respect an already explicit UUID.
    explicit_agent_id = arguments.get("agent_id")
    if isinstance(explicit_agent_id, str) and len(explicit_agent_id) == 36 and explicit_agent_id.count("-") == 4:
        update_context_agent_id(explicit_agent_id)
        return explicit_agent_id

    session_key = await derive_session_key(signals, arguments)
    resolved = await resolve_session_identity(
        session_key,
        persist=False,
        model_type=arguments.get("model_type"),
        client_hint=arguments.get("client_hint"),
        resume=True,
    )
    if resolved and not resolved.get("created"):
        agent_uuid = resolved.get("agent_uuid")
        if agent_uuid:
            update_context_agent_id(agent_uuid)
            arguments["agent_id"] = agent_uuid
            return agent_uuid
    return None


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------

async def http_list_tools(request):
    """List all tools in OpenAI-compatible format

    Query params:
        mode: Tool mode filter - "minimal", "lite", "full" (default from GOVERNANCE_TOOL_MODE env)
    """
    http_api_token = os.getenv("UNITARES_HTTP_API_TOKEN")
    try:
        if not _check_http_auth(request, http_api_token=http_api_token):
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

    http_api_token = os.getenv("UNITARES_HTTP_API_TOKEN")
    mcp_server_name = request.state._http_api_mcp_server_name

    # SECURITY: Limit request body size (prevent DoS via large payloads)
    MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB limit
    body = None
    tool_name = "unknown"
    try:
        if not _check_http_auth(request, http_api_token=http_api_token):
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

        tool_name = _normalize_http_tool_name(body, mcp_server_name)
        if not tool_name or tool_name == "unknown":
            return JSONResponse({"success": False, "error": "Missing 'name' field — pass the tool name as 'name', e.g. {\"name\": \"onboard\", \"arguments\": {...}}"}, status_code=400)

        # SECURITY: Validate tool name format (prevent injection)
        if not isinstance(tool_name, str) or len(tool_name) > 100:
            return JSONResponse({
                "success": False,
                "error": "Invalid tool name format"
            }, status_code=400)

        # DEPRECATED: SSE-specific tools removed
        # These tools are no longer registered but kept for backward compat
        if tool_name == "get_connected_clients":
            return JSONResponse({
                "name": tool_name,
                "result": {"error": "Tool deprecated. SSE transport deprecated by MCP. Use Streamable HTTP."},
                "success": False
            })

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
        # This ensures agent_id reflects actual runtime (e.g., Cursor + GPT/Codex)
        if isinstance(arguments, dict):
            ua = (request.headers.get("user-agent") or "").lower()

            # Detect client type
            if "client_hint" not in arguments:
                detected_client = None
                if "cursor" in ua:
                    detected_client = "cursor"
                # Prefer OpenAI/Codex before Claude in mixed/proxy UAs.
                elif "codex" in ua or "chatgpt" in ua or "openai" in ua or "gpt" in ua:
                    detected_client = "chatgpt"
                elif "claude" in ua or "anthropic" in ua:
                    detected_client = "claude_desktop"
                elif "vscode" in ua or "visual studio code" in ua:
                    detected_client = "vscode"

                if detected_client:
                    arguments["client_hint"] = detected_client
                    logger.debug(f"[HTTP] Auto-detected client_hint={detected_client} from UA")

            # Detect model type to prevent identity collision
            if "model_type" not in arguments:
                detected_model = None

                # Prefer explicit model header if available.
                model_header = request.headers.get("x-model") or request.headers.get("X-Model")
                if model_header:
                    detected_model = model_header.strip().lower()

                # Then infer from User-Agent.
                if not detected_model:
                    if "gpt-5.3" in ua and "codex" in ua:
                        detected_model = "gpt-5.3-codex"
                    elif "gpt-5.4" in ua and "codex" in ua:
                        detected_model = "gpt-5.4-codex"
                    elif "gpt-5" in ua and "codex" in ua:
                        detected_model = "gpt-5-codex"
                    elif "composer" in ua:
                        detected_model = "composer"
                    elif "codex" in ua:
                        detected_model = "codex"
                    elif "chatgpt" in ua or "openai" in ua or "gpt-5" in ua or "gpt-4" in ua or "gpt-3" in ua:
                        detected_model = "gpt"
                    elif "claude" in ua and "codex" not in ua and "gpt" not in ua and "openai" not in ua:
                        detected_model = "claude"
                    elif "gemini" in ua:
                        detected_model = "gemini"

                if detected_model:
                    arguments["model_type"] = detected_model
                    logger.debug(f"[HTTP] Auto-detected model_type={detected_model} from headers")

        from src.mcp_handlers.context import (
            reset_session_context,
            reset_session_signals,
            set_session_context,
            set_session_signals,
        )

        signals = _build_http_session_signals(request)
        signals_token = set_session_signals(signals)

        # SET SESSION CONTEXT for contextvars-based identity lookup
        # This allows success_response() and status() to find binding without arguments
        context_token = set_session_context(
            session_key=client_session_id,
            client_session_id=client_session_id,
            agent_id=x_agent_id or (arguments.get("agent_id") if isinstance(arguments, dict) else None),
        )
        try:
            if isinstance(arguments, dict):
                await _resolve_http_bound_agent(tool_name, arguments, signals)
            result = await execute_http_tool(tool_name, arguments)
        finally:
            reset_session_context(context_token)
            reset_session_signals(signals_token)
        return JSONResponse(_build_http_tool_response(tool_name, result))
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
    """Health check endpoint -- always public (monitoring, load balancers)"""

    # These are injected by register_http_routes via request.state
    server_ready = request.state._http_api_server_ready_fn()
    server_start_time = request.state._http_api_server_start_time
    server_version = request.state._http_api_server_version
    conn_tracker: ConnectionTracker = request.state._http_api_connection_tracker
    has_streamable_http = request.state._http_api_has_streamable_http
    http_api_token = os.getenv("UNITARES_HTTP_API_TOKEN")

    # Calculate uptime
    uptime_seconds = time.time() - server_start_time
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
        "status": "ok" if server_ready else "warming_up",
        "version": server_version,
        "uptime": {
            "seconds": int(uptime_seconds),
            "formatted": uptime_str,
            "started_at": datetime.fromtimestamp(server_start_time).isoformat() if server_start_time else None
        },
        "connections": {
            "active": conn_tracker.count,
            "healthy": sum(1 for c in conn_tracker.connections.values() if c.get("health_status") == "healthy")
        },
        "database": db_health,
        "transports": {
            "streamable_http": "/mcp (primary, JSON response mode)" if has_streamable_http else "not available",
        },
        "endpoints": {
            "list_tools": "GET /v1/tools",
            "call_tool": "POST /v1/tools/call",
            "health": "GET /health",
            "metrics": "GET /metrics",
            "dashboard": "GET /dashboard"
        },
        "auth": {
            "enabled": bool(http_api_token),
            "header": "Authorization: Bearer <token>" if http_api_token else None
        },
        "session": {
            "header": "X-Session-ID (recommended for stable identity binding)"
        },
        "identity": {
            "header": "X-Agent-Id",
            "description": "CLI/GPT identity - pass your agent name to maintain identity across REST requests"
        },
        "note": "Use /mcp for MCP clients (Streamable HTTP)."
    })


async def http_health_live(request):
    """Liveness probe — server process is up. Always public, no checks."""
    return JSONResponse({"status": "alive"})


async def http_health_ready(request):
    """Readiness probe — server has completed warmup and is accepting requests."""
    server_ready = request.state._http_api_server_ready_fn()
    if server_ready:
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "warming_up"}, status_code=503)


async def http_health_deep(request):
    """Deep health — reads the cached snapshot produced by deep_health_probe_task.

    Does NOT touch the DB at request time (see
    docs/handoffs/2026-04-10-option-f-spec.md). If the probe has not populated
    the cache yet, returns 503 and instructs the caller to retry.
    """
    from src.services.health_snapshot import (
        get_snapshot,
        is_stale,
        PROBE_INTERVAL_SECONDS,
        STALENESS_THRESHOLD_SECONDS,
    )

    snapshot, age_seconds, produced_at = get_snapshot()
    if snapshot is None:
        return JSONResponse(
            {
                "status": "unavailable",
                "error": "Health snapshot not yet populated — deep probe has not run.",
                "retry_after_seconds": 5,
            },
            status_code=503,
        )

    response = dict(snapshot)
    response["_cache"] = {
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "produced_at": produced_at,
        "stale": is_stale(age_seconds),
        "probe_interval_seconds": PROBE_INTERVAL_SECONDS,
        "staleness_threshold_seconds": STALENESS_THRESHOLD_SECONDS,
    }
    return JSONResponse(response)


async def http_metrics(request):
    """Prometheus metrics endpoint using prometheus-client library"""
    http_api_token = os.getenv("UNITARES_HTTP_API_TOKEN")
    if not _check_http_auth(request, http_api_token=http_api_token):
        return _http_unauthorized()

    # These are injected by register_http_routes via request.state
    server_start_time = request.state._http_api_server_start_time
    server_version = request.state._http_api_server_version
    conn_tracker: ConnectionTracker = request.state._http_api_connection_tracker

    try:
        # Update gauges with current values before generating output
        # Server info (static, set once)
        SERVER_INFO.labels(version=server_version).set(1)

        # Server uptime
        uptime_seconds = time.time() - server_start_time
        SERVER_UPTIME.set(uptime_seconds)

        # Connection metrics
        CONNECTIONS_ACTIVE.set(conn_tracker.count)

        # Agent metrics (from cached metadata — no DB call in handler path)
        try:
            from src.mcp_handlers.shared import get_mcp_server
            mcp_server = get_mcp_server()
            # Read already-loaded metadata dict; background tasks keep it fresh.
            # Do NOT call load_metadata_async() here — it awaits asyncpg.
            status_counts = {"active": 0, "paused": 0, "archived": 0, "waiting_input": 0, "deleted": 0}
            for meta in mcp_server.agent_metadata.values():
                status = getattr(meta, 'status', 'active')
                if status in status_counts:
                    status_counts[status] += 1
                else:
                    status_counts["active"] += 1

            for status, count in status_counts.items():
                AGENTS_TOTAL.labels(status=status).set(count)
        except Exception as e:
            logger.debug(f"Could not load agent metrics: {e}")

        # Dialectic sessions (in-memory, no DB call)
        try:
            from src.mcp_handlers.dialectic.session import ACTIVE_SESSIONS
            DIALECTIC_SESSIONS_ACTIVE.set(len(ACTIVE_SESSIONS))
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
    http_api_token = os.getenv("UNITARES_HTTP_API_TOKEN")
    dashboard_path = Path(__file__).parent.parent / "dashboard" / "index.html"
    if dashboard_path.exists():
        html = dashboard_path.read_text()
        # Cache-bust: append ?v=<startup_ts> to local script/css refs
        import re as _re
        _v = str(int(_startup_ts))
        html = _re.sub(
            r'(src|href)="/dashboard/([^"]+)"',
            rf'\1="/dashboard/\2?v={_v}"',
            html,
        )
        # Inject API token so dashboard JS can authenticate.
        # Always overwrite — token may have rotated since last visit.
        if http_api_token:
            token_script = (
                f'<script>localStorage.setItem("unitares_api_token","{http_api_token}")</script>'
            )
            html = html.replace("</head>", f"{token_script}</head>", 1)
        return Response(
            content=html,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )
    return JSONResponse({
        "error": "Dashboard not found",
        "path": str(dashboard_path)
    }, status_code=404)


async def http_phase(request):
    """Serve the phase-space visualization"""
    http_api_token = os.getenv("UNITARES_HTTP_API_TOKEN")
    phase_path = Path(__file__).parent.parent / "dashboard" / "phase.html"
    if phase_path.exists():
        html = phase_path.read_text()
        if http_api_token:
            token_script = (
                f'<script>if(!localStorage.getItem("unitares_api_token"))'
                f'{{localStorage.setItem("unitares_api_token","{http_api_token}")}}</script>'
            )
            html = html.replace("</head>", f"{token_script}</head>", 1)
        return Response(content=html, media_type="text/html")
    return JSONResponse({"error": "Phase view not found", "path": str(phase_path)}, status_code=404)


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
        "residents.js",
        "styles.css", "dashboard.js",
        "phase.js",
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
            media_type=content_type,
            headers={"Cache-Control": "no-cache"},
        )
    return JSONResponse({
        "error": "File not found",
        "path": str(static_path)
    }, status_code=404)


# HTTP polling fallback for EISV (when WebSocket is blocked by proxy auth)
async def http_eisv_latest(request):
    """Return the latest EISV update as JSON (polling fallback for WebSocket)."""
    if broadcaster_instance.last_update:
        return JSONResponse(broadcaster_instance.last_update)
    return JSONResponse({"type": "no_data", "message": "No EISV updates yet"}, status_code=200)


# Events API endpoint for dashboard
async def http_events(request):
    """Return recent governance events for dashboard."""
    http_api_token = os.getenv("UNITARES_HTTP_API_TOKEN")
    if not _check_http_auth(request, http_api_token=http_api_token):
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


# Incident history endpoint (anomalies + stuck agents from audit log)
async def http_incidents(request):
    """Return historical anomaly and stuck-agent incidents from the audit trail."""
    http_api_token = os.getenv("UNITARES_HTTP_API_TOKEN")
    if not _check_http_auth(request, http_api_token=http_api_token):
        return _http_unauthorized()
    try:
        from src.audit_db import query_audit_events_async

        event_type = request.query_params.get("type")  # "anomaly_detected" or "stuck_detected"
        limit = min(int(request.query_params.get("limit", 200)), 500)

        # Query both types if none specified
        types_to_query = [event_type] if event_type else ["anomaly_detected", "stuck_detected"]
        all_events = []
        for et in types_to_query:
            events = await query_audit_events_async(event_type=et, order="desc", limit=limit)
            all_events.extend(events)

        # Sort by timestamp descending, limit total
        all_events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        all_events = all_events[:limit]

        return JSONResponse({"success": True, "incidents": all_events, "count": len(all_events)})
    except Exception as e:
        logger.error(f"Error fetching incidents: {e}")
        return JSONResponse({"success": False, "error": str(e), "incidents": []}, status_code=500)


# Activity sparkline endpoint
async def http_activity(request):
    """Return check-in activity buckets for sparkline chart."""
    try:
        window = int(request.query_params.get("window", 60))
        bucket = int(request.query_params.get("bucket", 5))
        # Clamp to reasonable limits
        window = max(10, min(window, 360))
        bucket = max(1, min(bucket, 30))
        buckets = broadcaster_instance.get_activity_buckets(
            window_minutes=window, bucket_minutes=bucket
        )
        return JSONResponse({
            "success": True,
            "buckets": buckets,
            "window_minutes": window,
            "bucket_minutes": bucket
        })
    except Exception as e:
        logger.error(f"Error fetching activity: {e}")
        return JSONResponse({
            "success": False,
            "error": str(e),
            "buckets": []
        }, status_code=500)


# ---------------------------------------------------------------------------
# Residents endpoint — per-operator configurable "always-on agents" view
# ---------------------------------------------------------------------------


# Default silence thresholds in seconds — agents that go longer than this without
# a check-in are flagged as "silent" on the dashboard. Only used for agents the
# operator hasn't configured explicitly.
_DEFAULT_RESIDENT_SILENCE_SECONDS: Dict[str, int] = {
    # Long cron cadence agents get generous thresholds.
    "vigil": 40 * 60,      # 30-min cron + buffer
    "sentinel": 15 * 60,   # 5-min continuous + 10min tolerance
    "lumen": 10 * 60,      # continuous poll
    # Event-driven agents may be quiet for a long time and still be healthy.
    "watcher": 24 * 3600,
}


def _resolve_resident_labels(mcp_server_obj) -> list[str]:
    """Figure out which agent labels to treat as residents.

    Precedence (operator choice wins):
    1. ``UNITARES_RESIDENT_AGENTS`` env var — comma-separated labels
    2. Agent metadata with a ``resident`` attribute set to True
    3. Empty list — dashboard will show a "no residents configured" state
    """
    env_value = os.getenv("UNITARES_RESIDENT_AGENTS", "").strip()
    if env_value:
        return [lbl.strip() for lbl in env_value.split(",") if lbl.strip()]

    labels: list[str] = []
    for meta in getattr(mcp_server_obj, "agent_metadata", {}).values():
        if getattr(meta, "resident", False):
            label = getattr(meta, "label", None) or getattr(meta, "display_name", None)
            if label:
                labels.append(label)
    return labels


def _latest_eisv_for_agent(agent_id: str) -> Optional[dict]:
    """Find the most recent eisv_update event for a given agent_id in the broadcaster history."""
    for event in reversed(broadcaster_instance.event_history):
        if not isinstance(event, dict):
            continue
        if event.get("type") != "eisv_update":
            # Broadcaster puts eisv_updates in event_history too; non-eisv events are skipped.
            continue
        if event.get("agent_id") == agent_id:
            return event
    return None


def _extract_eisv_fields(event: dict) -> dict:
    """Pull the data-shape we expose to the dashboard from a raw broadcaster event.

    The broadcaster stores eisv updates with nested ``eisv`` and ``metrics``
    dicts. Surface them flat so the JSON payload is convenient for the
    frontend without re-mapping.
    """
    eisv = event.get("eisv") or {}
    metrics = event.get("metrics") or {}
    decision = event.get("decision") or {}
    return {
        "E": eisv.get("E"),
        "I": eisv.get("I"),
        "S": eisv.get("S"),
        "V": eisv.get("V"),
        "coherence": event.get("coherence") if event.get("coherence") is not None else metrics.get("coherence"),
        "risk_score": metrics.get("risk_score") if metrics.get("risk_score") is not None else event.get("risk"),
        # Verdict can come from decision.action (governance dynamics) or
        # metrics.verdict (behavioral classifier — "safe", "caution", etc.).
        "verdict": decision.get("action") or metrics.get("verdict"),
        "agent_name": event.get("agent_name"),
        "timestamp": event.get("timestamp"),
    }


def _coherence_history_for_agent(agent_id: str, window_minutes: int = 60) -> list[dict]:
    """Collect coherence (plus risk, verdict) data points for a sparkline.

    Pulls from the broadcaster's 2000-entry event ring buffer — this covers
    roughly 6 hours of moderate activity. Each point has ts, coherence, risk.
    """
    cutoff = time.time() - window_minutes * 60
    points: list[dict] = []
    for event in broadcaster_instance.event_history:
        if not isinstance(event, dict):
            continue
        if event.get("type") != "eisv_update":
            continue
        if event.get("agent_id") != agent_id:
            continue
        ts_str = event.get("timestamp")
        try:
            ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        flat = _extract_eisv_fields(event)
        if flat["coherence"] is None:
            continue
        points.append({
            "ts": ts,
            "coherence": float(flat["coherence"]),
            "risk": float(flat["risk_score"]) if flat["risk_score"] is not None else None,
            "verdict": flat["verdict"],
        })
    return points


async def _recent_writes_for_agent(agent_id: str, limit: int = 5) -> list[dict]:
    """Pull recent KG writes authored by this agent, newest first.

    Uses the shared graph query rather than re-reading the broadcaster history,
    so this survives broadcaster restarts and covers more than the last 6h.
    """
    try:
        from src.knowledge_graph import get_knowledge_graph
        graph = await get_knowledge_graph()
        discoveries = await graph.query(agent_id=agent_id, limit=limit)
        out = []
        for d in (discoveries or [])[:limit]:
            out.append({
                "id": getattr(d, "id", None),
                "type": getattr(d, "type", None) or "note",
                "severity": getattr(d, "severity", None) or "low",
                "summary": (getattr(d, "summary", None) or "")[:200],
                "tags": list(getattr(d, "tags", None) or []),
                "timestamp": getattr(d, "timestamp", None),
            })
        return out
    except Exception as exc:
        logger.debug("_recent_writes_for_agent(%s) failed: %s", agent_id, exc)
        return []


async def http_residents(request):
    """Per-resident fleet view for the dashboard.

    Response shape::

        {
            "success": true,
            "configured": ["Vigil", "Sentinel", ...],
            "residents": [
                {
                    "label": "Vigil",
                    "agent_id": "...",
                    "status": "healthy" | "silent" | "paused" | "unknown",
                    "silence_seconds": 142,
                    "silence_threshold_seconds": 2400,
                    "last_checkin_at": "2026-04-14T...",
                    "eisv": {"E": ..., "I": ..., "S": ..., "V": ...},
                    "coherence": 0.48,
                    "risk_score": 0.12,
                    "verdict": "proceed",
                    "history": [{"ts": ..., "coherence": ..., "risk": ...}, ...],
                    "recent_writes": [{"summary": ..., "tags": ..., ...}, ...],
                    "total_updates": 467
                },
                ...
            ],
            "source": "env" | "metadata" | "none"
        }
    """
    http_api_token = os.getenv("UNITARES_HTTP_API_TOKEN")
    if not _check_http_auth(request, http_api_token=http_api_token):
        return _http_unauthorized()

    try:
        from src.mcp_handlers.shared import lazy_mcp_server
        mcp_server_obj = lazy_mcp_server

        labels = _resolve_resident_labels(mcp_server_obj)
        source = (
            "env"
            if os.getenv("UNITARES_RESIDENT_AGENTS", "").strip()
            else ("metadata" if labels else "none")
        )

        # Index agent_metadata by label for O(1) lookup. When the same label
        # appears multiple times (e.g. archived + active duplicates created
        # across server restarts), prefer the most-active live record so the
        # dashboard tracks the agent that's actually running.
        label_to_meta = {}
        for agent_id, meta in list(getattr(mcp_server_obj, "agent_metadata", {}).items()):
            label = getattr(meta, "label", None)
            if not label:
                continue
            existing = label_to_meta.get(label)
            if existing is None:
                label_to_meta[label] = (agent_id, meta)
                continue
            existing_meta = existing[1]
            # Prefer active over archived/paused.
            existing_status = getattr(existing_meta, "status", None)
            new_status = getattr(meta, "status", None)
            existing_active = existing_status == "active"
            new_active = new_status == "active"
            if new_active and not existing_active:
                label_to_meta[label] = (agent_id, meta)
                continue
            if existing_active and not new_active:
                continue
            # Both same activity tier — prefer the one with more updates.
            if (getattr(meta, "total_updates", 0) or 0) > \
               (getattr(existing_meta, "total_updates", 0) or 0):
                label_to_meta[label] = (agent_id, meta)

        residents: list[dict] = []
        now_ts = time.time()
        for label in labels:
            entry = label_to_meta.get(label)
            agent_id = entry[0] if entry else None
            meta = entry[1] if entry else None

            latest = _latest_eisv_for_agent(agent_id) if agent_id else None
            history = _coherence_history_for_agent(agent_id) if agent_id else []
            recent_writes = await _recent_writes_for_agent(agent_id) if agent_id else []

            # Compute silence in seconds — prefer the latest eisv event timestamp,
            # fall back to metadata's last_update.
            last_checkin_str = None
            if latest and latest.get("timestamp"):
                last_checkin_str = latest.get("timestamp")
            elif meta and getattr(meta, "last_update", None):
                last_checkin_str = meta.last_update

            silence_seconds: Optional[float] = None
            if last_checkin_str:
                try:
                    last_dt = datetime.fromisoformat(str(last_checkin_str).replace("Z", "+00:00"))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    silence_seconds = max(0.0, now_ts - last_dt.timestamp())
                except (ValueError, TypeError):
                    pass

            silence_threshold = _DEFAULT_RESIDENT_SILENCE_SECONDS.get(label.lower(), 30 * 60)

            # Status: paused > silent > healthy > unknown.
            status = "unknown"
            if meta:
                if getattr(meta, "status", None) in ("paused", "archived"):
                    status = getattr(meta, "status")
                elif silence_seconds is not None and silence_seconds > silence_threshold:
                    status = "silent"
                elif latest is not None or silence_seconds is not None:
                    status = "healthy"

            flat = _extract_eisv_fields(latest) if latest else None
            residents.append({
                "label": label,
                "agent_id": agent_id,
                "status": status,
                "silence_seconds": round(silence_seconds, 1) if silence_seconds is not None else None,
                "silence_threshold_seconds": silence_threshold,
                "last_checkin_at": last_checkin_str,
                "eisv": {
                    "E": flat["E"],
                    "I": flat["I"],
                    "S": flat["S"],
                    "V": flat["V"],
                } if flat else None,
                "coherence": flat["coherence"] if flat else None,
                "risk_score": flat["risk_score"] if flat else None,
                "verdict": flat["verdict"] if flat else None,
                "history": history,
                "recent_writes": recent_writes,
                "total_updates": getattr(meta, "total_updates", 0) if meta else 0,
            })

        return JSONResponse({
            "success": True,
            "configured": labels,
            "residents": residents,
            "source": source,
        })
    except Exception as exc:
        logger.error("http_residents error: %s", exc)
        return JSONResponse({
            "success": False,
            "error": str(exc),
            "residents": [],
        }, status_code=500)


# ---------------------------------------------------------------------------
# Violation taxonomy endpoint — surface vocabulary for dashboards/bridges
# ---------------------------------------------------------------------------


async def http_taxonomy(request):
    """Return the violation taxonomy + reverse-lookup index as JSON.

    Lets the dashboard (and any other consumer) classify Watcher findings,
    Sentinel findings, and broadcast events into violation classes
    (CON / INT / ENT / REC / BEH / VOI) without having to ship its own copy
    of the YAML.

    Response shape::

        {
            "success": true,
            "version": 1,
            "classes": [{ "id": "INT", "name": "Integrity", ... }, ...],
            "reverse": {
                "watcher_patterns": {"P010": "INT", "P011": "INT", ...},
                "sentinel_findings": {"coordinated_degradation": "CON", ...},
                "broadcast_events": {"identity_drift": "CON", ...}
            }
        }

    Best-effort: if the taxonomy file is missing or malformed, returns a
    success=false response with an empty taxonomy rather than 500. The
    dashboard renders fine without classification — class badges just
    don't appear.
    """
    if not _check_http_auth(request, http_api_token=os.getenv("UNITARES_HTTP_API_TOKEN")):
        return _http_unauthorized()

    try:
        from agents.common import taxonomy as taxonomy_mod
        data = taxonomy_mod.load_taxonomy()
        # Build reverse index (taxonomy.py keeps it private; reconstruct here
        # so we don't depend on its internal _get_reverse implementation).
        reverse: dict = {
            "watcher_patterns": {},
            "sentinel_findings": {},
            "broadcast_events": {},
        }
        for cls in data.get("classes", []):
            cid = cls["id"]
            for kind in reverse:
                for sid in cls.get("surfaces", {}).get(kind, []):
                    reverse[kind][sid] = cid
        return JSONResponse({
            "success": True,
            "version": data.get("version"),
            "classes": data.get("classes", []),
            "reverse": reverse,
        })
    except Exception as exc:
        logger.warning("http_taxonomy failed: %s", exc)
        return JSONResponse({
            "success": False,
            "error": str(exc),
            "classes": [],
            "reverse": {
                "watcher_patterns": {},
                "sentinel_findings": {},
                "broadcast_events": {},
            },
        })


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

async def websocket_eisv_stream(websocket):
    """WebSocket endpoint for live EISV streaming to dashboard."""
    await broadcaster_instance.connect(websocket)
    try:
        while True:
            # Keep connection alive -- client sends pings, we just listen
            await websocket.receive_text()
    except Exception:
        await broadcaster_instance.disconnect(websocket)


# ---------------------------------------------------------------------------
# Debug: memory profiling (tracemalloc)
# ---------------------------------------------------------------------------

async def http_debug_memory(request):
    """Top memory allocations via tracemalloc (if enabled)."""
    import tracemalloc
    if not tracemalloc.is_tracing():
        return JSONResponse({"error": "tracemalloc not enabled"}, status_code=503)

    snapshot = tracemalloc.take_snapshot()
    # Filter out importlib/tracemalloc noise
    snapshot = snapshot.filter_traces([
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
        tracemalloc.Filter(False, tracemalloc.__file__),
    ])

    top_n = int(request.query_params.get("top", "25"))
    stats = snapshot.statistics("lineno")

    current, peak = tracemalloc.get_traced_memory()
    result = {
        "current_mb": round(current / 1024 / 1024, 1),
        "peak_mb": round(peak / 1024 / 1024, 1),
        "top_allocations": [
            {
                "file": str(stat.traceback),
                "size_mb": round(stat.size / 1024 / 1024, 2),
                "count": stat.count,
            }
            for stat in stats[:top_n]
        ],
    }

    # Also include monitor cache size
    try:
        from src.agent_monitor_state import monitors
        result["monitors_cached"] = len(monitors)
    except Exception:
        pass

    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_http_routes(
    app: Starlette,
    *,
    connection_tracker: ConnectionTracker,
    server_ready_fn,
    server_start_time: float,
    server_version: str,
    has_streamable_http: bool,
    mcp_server_name: str = "governance-monitor-v1",
):
    """
    Register all HTTP REST endpoints on the given Starlette ``app``.

    Parameters that vary per-deployment (connection tracker, server readiness,
    version, etc.) are injected via a lightweight ASGI middleware that sets
    ``request.state`` attributes before each handler runs.  This avoids
    module-level globals while keeping handler signatures clean.
    """
    from starlette.middleware import Middleware
    from starlette.types import ASGIApp, Receive, Scope, Send

    # Tiny middleware that injects server context into request.state
    # so endpoint handlers can access connection_tracker, server_version, etc.
    class _InjectContextMiddleware:
        def __init__(self, app: ASGIApp):
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] in ("http", "websocket"):
                state = scope.setdefault("state", {})
                state["_http_api_connection_tracker"] = connection_tracker
                state["_http_api_server_ready_fn"] = server_ready_fn
                state["_http_api_server_start_time"] = server_start_time
                state["_http_api_server_version"] = server_version
                state["_http_api_has_streamable_http"] = has_streamable_http
                state["_http_api_mcp_server_name"] = mcp_server_name
            await self.app(scope, receive, send)

    app.add_middleware(_InjectContextMiddleware)

    # IMPORTANT: Static file route must come BEFORE dashboard route
    # to match /dashboard/utils.js, etc.
    app.routes.append(Route("/dashboard/{file}", http_dashboard_static, methods=["GET"]))
    app.routes.append(Route("/dashboard", http_dashboard, methods=["GET"]))
    app.routes.append(Route("/phase", http_phase, methods=["GET"]))
    app.routes.append(Route("/", http_dashboard, methods=["GET"]))  # Root also serves dashboard
    app.routes.append(Route("/v1/tools", http_list_tools, methods=["GET"]))
    app.routes.append(Route("/v1/tools/call", http_call_tool, methods=["POST"]))
    app.routes.append(Route("/health", http_health, methods=["GET"]))
    app.routes.append(Route("/health/live", http_health_live, methods=["GET"]))
    app.routes.append(Route("/health/ready", http_health_ready, methods=["GET"]))
    app.routes.append(Route("/health/deep", http_health_deep, methods=["GET"]))
    app.routes.append(Route("/metrics", http_metrics, methods=["GET"]))
    app.routes.append(Route("/v1/eisv/latest", http_eisv_latest, methods=["GET"]))
    app.routes.append(Route("/api/events", http_events, methods=["GET"]))
    app.routes.append(Route("/api/activity", http_activity, methods=["GET"]))
    app.routes.append(Route("/api/incidents", http_incidents, methods=["GET"]))
    app.routes.append(Route("/v1/residents", http_residents, methods=["GET"]))
    app.routes.append(Route("/v1/taxonomy", http_taxonomy, methods=["GET"]))
    app.routes.append(WebSocketRoute("/ws/eisv", websocket_eisv_stream))
    app.routes.append(Route("/debug/memory", http_debug_memory, methods=["GET"]))
