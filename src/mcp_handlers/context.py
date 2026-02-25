"""
Session Context Module

Uses Python contextvars to propagate session context through the call stack
without threading arguments through every function call.

This solves the session key mismatch issue where:
- SSE transport binds under client_session_id (e.g., "34.162.136.91:0")
- But handlers call get_bound_agent_id(arguments=None) which falls back to stdio:{pid}

With contextvars, session context is set once at dispatch entry and accessible everywhere.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, Optional
import os


# =============================================================================
# SESSION SIGNALS (unified transport signal capture)
# =============================================================================

@dataclass(frozen=True)
class SessionSignals:
    """Frozen snapshot of all transport-level signals for session key derivation.

    Captured once at the ASGI/HTTP layer, stored in a contextvar, and read by
    the single ``derive_session_key()`` function in identity_v2.py.

    No priority decisions happen here — this is a pure data capture object.
    """
    mcp_session_id: Optional[str] = None      # mcp-session-id header
    x_session_id: Optional[str] = None        # X-Session-ID header
    x_client_id: Optional[str] = None         # X-Client-Id / X-MCP-Client-Id header
    oauth_client_id: Optional[str] = None     # oauth:CLIENT_ID from Bearer token
    ip_ua_fingerprint: Optional[str] = None   # IP:MD5(UA)[:6] fallback
    user_agent: Optional[str] = None          # raw User-Agent
    client_hint: Optional[str] = None         # detected client type (cursor, claude_desktop, etc.)
    x_agent_name: Optional[str] = None        # X-Agent-Name header
    x_agent_id: Optional[str] = None          # X-Agent-Id header
    transport: str = "unknown"                # "mcp", "rest", "sse", "stdio"


# Contextvar for SessionSignals — set once per request at the transport layer
_session_signals: ContextVar[Optional[SessionSignals]] = ContextVar('session_signals', default=None)


def set_session_signals(signals: SessionSignals) -> object:
    """Store SessionSignals for the current request. Returns token for reset."""
    return _session_signals.set(signals)


def get_session_signals() -> Optional[SessionSignals]:
    """Get SessionSignals for the current request, or None if not set."""
    return _session_signals.get()


def reset_session_signals(token: object) -> None:
    """Reset SessionSignals using token from set_session_signals."""
    _session_signals.reset(token)


# Session context - set at request entry, accessible throughout the request lifecycle
_session_context: ContextVar[Dict[str, Any]] = ContextVar('session_context', default={})

# Transport-level client hint - set at ASGI/HTTP layer, before MCP SDK processing
# This allows auto-detection of client type (e.g., "cursor") even when MCP SDK
# doesn't expose HTTP headers to tool handlers
_transport_client_hint: ContextVar[Optional[str]] = ContextVar('transport_client_hint', default=None)

# MCP session ID - extracted from mcp-session-id header at ASGI layer
# This enables implicit identity binding without clients manually passing client_session_id
_mcp_session_id: ContextVar[Optional[str]] = ContextVar('mcp_session_id', default=None)


def set_session_context(
    session_key: Optional[str] = None,
    client_session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    **extra: Any
) -> object:
    """
    Set session context for the current request.

    Call at SSE/REST dispatch entry point. Returns a token for reset.

    Args:
        session_key: The resolved session key for identity binding
        client_session_id: Raw client session ID from transport
        agent_id: The bound agent ID if known
        **extra: Additional context (e.g., request metadata)

    Returns:
        Token for resetting context (use in finally block)
    """
    ctx = {
        'session_key': session_key or client_session_id,
        'client_session_id': client_session_id,
        'agent_id': agent_id,
        **extra
    }
    return _session_context.set(ctx)


def reset_session_context(token: object) -> None:
    """Reset session context using token from set_session_context."""
    _session_context.reset(token)


def get_session_context() -> Dict[str, Any]:
    """Get the current session context dict."""
    return _session_context.get()


def get_context_session_key() -> Optional[str]:
    """
    Get session key from context.

    Returns None if no context is set (caller should use fallback).
    """
    ctx = _session_context.get()
    return ctx.get('session_key')


def get_context_client_session_id() -> Optional[str]:
    """Get raw client_session_id from context."""
    ctx = _session_context.get()
    return ctx.get('client_session_id')


def get_context_agent_id() -> Optional[str]:
    """Get bound agent_id from context if known."""
    ctx = _session_context.get()
    return ctx.get('agent_id')


def update_context_agent_id(agent_id: str) -> None:
    """Update agent_id in context (e.g., after binding)."""
    ctx = _session_context.get()
    if ctx:
        ctx['agent_id'] = agent_id
        _session_context.set(ctx)


def get_context_client_hint() -> Optional[str]:
    """
    Get client_hint from context (e.g., 'cursor', 'chatgpt').

    Checks in order:
    1. Session context (set by dispatch_tool from arguments)
    2. Transport-level contextvar (set by ASGI handler from User-Agent)
    """
    # First check session context
    ctx = _session_context.get()
    hint = ctx.get('client_hint')
    if hint:
        return hint

    # Fall back to transport-level contextvar
    return _transport_client_hint.get()


def set_transport_client_hint(hint: str) -> object:
    """
    Set transport-level client hint (call from ASGI handler).

    Returns token for reset.
    """
    return _transport_client_hint.set(hint)


def reset_transport_client_hint(token: object) -> None:
    """Reset transport-level client hint."""
    _transport_client_hint.reset(token)


def set_mcp_session_id(session_id: str) -> object:
    """
    Set MCP session ID from mcp-session-id header (call from ASGI handler).

    Returns token for reset.
    """
    return _mcp_session_id.set(session_id)


def reset_mcp_session_id(token: object) -> None:
    """Reset MCP session ID."""
    _mcp_session_id.reset(token)


def get_mcp_session_id() -> Optional[str]:
    """
    Get MCP session ID from context.

    This is the implicit session identifier from the MCP protocol's
    mcp-session-id header. Use for identity binding when available.
    """
    return _mcp_session_id.get()


# Trajectory identity confidence - set during dispatch if verification runs
_trajectory_confidence: ContextVar[Optional[float]] = ContextVar('trajectory_confidence', default=None)


def set_trajectory_confidence(confidence: float) -> object:
    """Set trajectory confidence for current request. Returns token for reset."""
    return _trajectory_confidence.set(confidence)


def reset_trajectory_confidence(token: object) -> None:
    """Reset trajectory confidence."""
    _trajectory_confidence.reset(token)


def get_trajectory_confidence() -> Optional[float]:
    """Get trajectory confidence from context, or None if not set."""
    return _trajectory_confidence.get()


def detect_client_from_user_agent(user_agent: str) -> Optional[str]:
    """
    Detect client type from User-Agent string.

    Used for auto-generating meaningful structured_id (e.g., "cursor_20251226").

    Args:
        user_agent: HTTP User-Agent header value

    Returns:
        Client hint string or None if not detected
    """
    if not user_agent:
        return None

    ua = user_agent.lower()

    if "cursor" in ua:
        return "cursor"
    elif "claude" in ua or "anthropic" in ua:
        return "claude_desktop"
    elif "chatgpt" in ua or "openai" in ua:
        return "chatgpt"
    elif "vscode" in ua or "visual studio code" in ua:
        return "vscode"

    return None
