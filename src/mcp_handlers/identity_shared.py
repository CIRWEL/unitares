"""
Shared identity utilities used by identity_v2.py and other modules.

This module contains the shared data structures and utility functions that
were previously in identity.py. Separating these prevents circular imports
and makes the dependency structure cleaner.

Data structures:
- _session_identities: In-memory session -> agent binding cache
- _uuid_prefix_index: UUID prefix -> full UUID for O(1) lookup

Key functions:
- get_bound_agent_id(): Get bound agent for current session
- is_session_bound(): Check if session has bound identity
- make_client_session_id(): Generate stable session ID from UUID
- require_write_permission(): Check if writes are allowed
- _get_lineage(): Get agent lineage chain
"""

from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from mcp.types import TextContent
import os

from src.logging_utils import get_logger

logger = get_logger(__name__)


# =============================================================================
# SHARED SESSION STATE
# =============================================================================
# This is the in-memory cache of session -> agent bindings.
# It's shared across all identity modules to prevent binding conflicts.

_session_identities: Dict[str, Dict[str, Any]] = {}

# O(1) lookup index: uuid_prefix (12 chars) -> full UUID
# Populated when identity() registers a stable session binding
_uuid_prefix_index: Dict[str, str] = {}


# =============================================================================
# UUID PREFIX INDEX
# =============================================================================

def _register_uuid_prefix(uuid_prefix: str, full_uuid: str) -> None:
    """Register a UUID prefix -> full UUID mapping for O(1) lookup.

    Handles collision detection: if prefix already exists for a different UUID,
    logs a warning (collisions are rare with 12 chars but possible).
    """
    existing = _uuid_prefix_index.get(uuid_prefix)
    if existing and existing != full_uuid:
        logger.warning(f"[UUID_PREFIX_COLLISION] Prefix {uuid_prefix} already maps to {existing[:8]}..., not updating to {full_uuid[:8]}...")
        return
    _uuid_prefix_index[uuid_prefix] = full_uuid
    logger.debug(f"[UUID_PREFIX] Registered {uuid_prefix} -> {full_uuid[:8]}...")


def _lookup_uuid_by_prefix(uuid_prefix: str) -> Optional[str]:
    """O(1) lookup of full UUID by prefix. Returns None if not found."""
    return _uuid_prefix_index.get(uuid_prefix)


# =============================================================================
# SESSION KEY DERIVATION
# =============================================================================

def _get_session_key(arguments: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> str:
    """
    DEPRECATED: Use ``await identity_v2.derive_session_key(signals, arguments)`` instead.

    This sync version is kept for callers that cannot be made async (e.g.,
    ``_get_identity_record_sync``). New code should use the unified async version.

    Precedence:
    1) explicit session_id argument
    2) arguments["client_session_id"] (injected by SSE wrappers)
    3) contextvars session_key (set at dispatch entry)
    4) fallback to a stable per-process key (stdio/single-user)
    """
    if session_id:
        logger.debug(f"_get_session_key: using explicit session_id={session_id}")
        return str(session_id)
    if arguments and arguments.get("client_session_id"):
        logger.debug(f"_get_session_key: using client_session_id={arguments['client_session_id']}")
        return str(arguments["client_session_id"])

    # Check contextvars for session key (set at SSE dispatch entry)
    from .context import get_context_session_key
    context_key = get_context_session_key()
    if context_key:
        logger.debug(f"_get_session_key: using context session_key={context_key}")
        return str(context_key)

    # STABLE FALLBACK: Use only PID (no timestamp) for single-user scenarios
    fallback = f"stdio:{os.getpid()}"
    logger.debug(f"_get_session_key: using fallback={fallback}")
    return fallback


# =============================================================================
# SESSION ID FORMATTING
# =============================================================================

def make_client_session_id(agent_uuid: str) -> str:
    """
    Generate a stable client_session_id from an agent UUID.

    This is THE canonical formatter for session IDs. All code that generates
    session IDs must use this function to prevent format drift.

    Format: "agent-{uuid_prefix_12}"
    Example: "agent-5e728ecb1234"

    Args:
        agent_uuid: The full 36-char UUID

    Returns:
        Stable session ID in format "agent-{uuid[:12]}"
    """
    if not agent_uuid or len(agent_uuid) < 12:
        raise ValueError(f"Invalid UUID: {agent_uuid}")
    return f"agent-{agent_uuid[:12]}"


# =============================================================================
# BOUND AGENT LOOKUP
# =============================================================================

def _get_identity_record_sync(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get identity record for a session (synchronous, in-memory only).

    This is a lightweight sync version that only checks in-memory cache.
    For full PostgreSQL support, use the async version in identity_v2.py.
    """
    from .shared import get_mcp_server
    mcp_server = get_mcp_server()

    key = _get_session_key(arguments=arguments, session_id=session_id)

    # Check in-memory cache first
    if key in _session_identities:
        return _session_identities[key]

    # SPECIAL CASE: agent-{uuid12} format session IDs
    if key.startswith("agent-"):
        uuid_prefix = key[6:]  # Remove "agent-" prefix

        # O(1) LOOKUP via index
        full_uuid = _lookup_uuid_by_prefix(uuid_prefix)
        if full_uuid:
            meta = mcp_server.agent_metadata.get(full_uuid)
            if meta:
                _session_identities[key] = {
                    "bound_agent_id": full_uuid,
                    "api_key": getattr(meta, 'api_key', None),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "bind_count": 0,
                }
                return _session_identities[key]

        # FALLBACK: Scan agent metadata
        for agent_uuid, meta in mcp_server.agent_metadata.items():
            if agent_uuid.startswith(uuid_prefix):
                _register_uuid_prefix(uuid_prefix, agent_uuid)
                _session_identities[key] = {
                    "bound_agent_id": agent_uuid,
                    "api_key": getattr(meta, 'api_key', None),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "bind_count": 0,
                }
                return _session_identities[key]

        # No match
        return {
            "bound_agent_id": None,
            "api_key": None,
            "bound_at": None,
            "bind_count": 0,
            "_session_key_type": "agent_prefix_not_found",
        }

    # Not in cache, return empty (async version handles DB lookup)
    if key not in _session_identities:
        _session_identities[key] = {
            "bound_agent_id": None,
            "api_key": None,
            "bound_at": None,
            "bind_count": 0,
        }
    return _session_identities[key]


def get_bound_agent_id(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Get currently bound agent_id (if any) for this session.

    PRIORITY: Checks contextvars first (set at dispatch entry) for consistency
    across all tools in the same request. Falls back to identity record lookup.
    """
    # PRIORITY 0: Check contextvars (set at dispatch entry)
    try:
        from .context import get_context_agent_id
        context_agent_id = get_context_agent_id()
        if context_agent_id:
            logger.debug(f"get_bound_agent_id: using context agent_id={context_agent_id[:8]}...")
            return context_agent_id
    except Exception:
        pass

    # FALLBACK: Use identity record lookup
    rec = _get_identity_record_sync(session_id=session_id, arguments=arguments)
    return rec.get("bound_agent_id")


def is_session_bound(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> bool:
    """Check if session has bound identity."""
    return get_bound_agent_id(session_id=session_id, arguments=arguments) is not None


# =============================================================================
# WRITE PERMISSION
# =============================================================================

def require_write_permission(arguments: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[TextContent]]:
    """
    Check if writes are allowed (bound=true).

    Rules:
    - Writes are allowed only when bound=true
    - Read-only operations work even when unbound

    Returns:
        (allowed, error_response) - allowed is True if writes are permitted
    """
    from .utils import error_response as make_error

    if not is_session_bound(arguments=arguments):
        return False, make_error(
            "Write operations require session binding",
            details={"error_type": "write_requires_binding"},
            recovery={
                "action": "Call any tool (e.g. process_agent_update) to auto-bind identity",
                "note": "Read-only operations work without binding, but writes require bound=true"
            }
        )
    return True, None


# =============================================================================
# LINEAGE HELPERS
# =============================================================================

def _get_lineage_depth(agent_id: str) -> int:
    """Get depth in lineage tree (0 = no parent)."""
    from .shared import get_mcp_server
    mcp_server = get_mcp_server()

    depth = 0
    current = agent_id
    seen = set()

    while current and current not in seen:
        seen.add(current)
        meta = mcp_server.agent_metadata.get(current)
        if meta and meta.parent_agent_id:
            depth += 1
            current = meta.parent_agent_id
        else:
            break

    return depth


def _get_lineage(agent_id: str) -> list:
    """Get full lineage as list [oldest_ancestor, ..., parent, self]."""
    from .shared import get_mcp_server
    mcp_server = get_mcp_server()

    lineage = []
    current = agent_id
    seen = set()

    while current and current not in seen:
        seen.add(current)
        lineage.append(current)
        meta = mcp_server.agent_metadata.get(current)
        if meta and meta.parent_agent_id:
            current = meta.parent_agent_id
        else:
            break

    lineage.reverse()  # Oldest ancestor first
    return lineage


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Data structures
    '_session_identities',
    '_uuid_prefix_index',
    # UUID prefix functions
    '_register_uuid_prefix',
    '_lookup_uuid_by_prefix',
    # Session key functions
    '_get_session_key',
    'make_client_session_id',
    # Identity lookup
    'get_bound_agent_id',
    'is_session_bound',
    '_get_identity_record_sync',
    # Write permission
    'require_write_permission',
    # Lineage
    '_get_lineage',
    '_get_lineage_depth',
]
