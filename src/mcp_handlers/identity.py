"""
Identity management tool handlers.

Provides session binding for identity continuity.
"""

from typing import Dict, Any, Sequence, Optional
from mcp.types import TextContent
import json
import asyncio
from datetime import datetime
import secrets
import base64
import os
import re

from .utils import success_response, error_response, require_agent_id
from .decorators import mcp_tool
from src.logging_utils import get_logger
import sqlite3
from pathlib import Path
import hashlib

logger = get_logger(__name__)

# ==============================================================================
# AGENT ID NAMING VALIDATION
# ==============================================================================

GENERIC_NAMES = {"test", "agent", "bot", "assistant", "claude", "ai", "temp", "tmp"}
MIN_LENGTH = 8


def _validate_agent_id(agent_id: str) -> dict:
    """
    Validate agent_id naming with soft warnings (not blockers).
    
    Encourages descriptive names that improve knowledge graph legibility.
    
    Returns:
        dict with "valid" (always True) and "warnings" list
    """
    warnings = []
    
    # Check for generic names
    base_name = agent_id.lower().split("_")[0].split("-")[0]
    if base_name in GENERIC_NAMES:
        warnings.append(f"'{agent_id}' is generic. Consider: {{model}}_{{purpose}}_{{date}}")
    
    # Check minimum length
    if len(agent_id) < MIN_LENGTH:
        warnings.append(f"Short ID. Descriptive names improve knowledge graph legibility.")
    
    # Check for date suffix (recommended pattern)
    if not re.search(r'\d{8}$', agent_id):
        warnings.append("Consider adding date suffix (YYYYMMDD) for temporal context.")
    
    return {"valid": True, "warnings": warnings}

# New database abstraction (for PostgreSQL migration)
from src.db import get_db

# =============================================================================
# SQLite Persistence for Session Identities
# =============================================================================

def _get_identity_db_path() -> Path:
    """Get path to governance.db for identity persistence."""
    try:
        from .shared import get_mcp_server
        mcp = get_mcp_server()
        return Path(mcp.project_root) / "data" / "governance.db"
    except Exception:
        return Path(__file__).parent.parent.parent / "data" / "governance.db"


def _init_identity_schema(conn: sqlite3.Connection) -> None:
    """Initialize session_identities table if not exists."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS session_identities (
            session_key TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            api_key TEXT,
            bound_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            bind_count INTEGER DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_session_identities_agent
            ON session_identities(agent_id);
    """)


def _persist_identity(session_key: str, agent_id: str, api_key: str, bound_at: str, bind_count: int) -> bool:
    """Persist identity binding to SQLite. Returns True on success."""
    conn = None
    try:
        db_path = _get_identity_db_path()
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        _init_identity_schema(conn)

        now = datetime.now().isoformat()
        conn.execute("""
            INSERT OR REPLACE INTO session_identities
            (session_key, agent_id, api_key, bound_at, updated_at, bind_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_key, agent_id, api_key, bound_at, now, bind_count))
        conn.commit()
        logger.debug(f"Persisted identity binding: {session_key} -> {agent_id}")
        return True
    except Exception as e:
        logger.warning(f"Could not persist identity binding: {e}")
        return False
    finally:
        if conn:
            conn.close()


def _load_identity(session_key: str) -> Optional[Dict[str, Any]]:
    """Load identity binding from SQLite. Returns None if not found."""
    conn = None
    try:
        db_path = _get_identity_db_path()
        if not db_path.exists():
            return None

        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        _init_identity_schema(conn)

        row = conn.execute(
            "SELECT * FROM session_identities WHERE session_key = ?",
            (session_key,)
        ).fetchone()

        if row:
            return {
                "bound_agent_id": row["agent_id"],
                "api_key": row["api_key"],
                "bound_at": row["bound_at"],
                "bind_count": row["bind_count"] or 1,
            }
        return None
    except Exception as e:
        logger.warning(f"Could not load identity binding: {e}")
        return None
    finally:
        if conn:
            conn.close()


def _cleanup_old_identities(max_age_days: int = 7) -> int:
    """Remove identity bindings older than max_age_days. Returns count removed."""
    conn = None
    try:
        from datetime import timedelta
        db_path = _get_identity_db_path()
        if not db_path.exists():
            return 0

        conn = sqlite3.connect(str(db_path), timeout=5.0)
        _init_identity_schema(conn)

        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        cursor = conn.execute(
            "DELETE FROM session_identities WHERE updated_at < ?",
            (cutoff,)
        )
        count = cursor.rowcount
        conn.commit()

        if count > 0:
            logger.info(f"Cleaned up {count} expired identity bindings")
        return count
    except Exception as e:
        logger.warning(f"Could not cleanup old identities: {e}")
        return 0
    finally:
        if conn:
            conn.close()


# ==============================================================================
# NEW DATABASE ABSTRACTION (PostgreSQL Migration - Dual Write)
# ==============================================================================

async def _persist_session_new(
    session_key: str,
    agent_id: str,
    api_key: str,
    created_at: str
) -> bool:
    """Persist session to new database abstraction (PostgreSQL). Returns True on success."""
    try:
        db = get_db()

        # First ensure identity exists
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest() if api_key else ""
        identity = await db.get_identity(agent_id)

        if not identity:
            # Create identity if it doesn't exist
            await db.upsert_identity(agent_id, api_key_hash, metadata={"source": "session_binding"})
            identity = await db.get_identity(agent_id)

        if not identity:
            logger.warning(f"Could not create/fetch identity for {agent_id}")
            return False

        # Create session (expires in 24 hours by default)
        from datetime import datetime, timedelta
        expires_at = datetime.now() + timedelta(hours=24)

        success = await db.create_session(
            session_id=session_key,
            identity_id=identity.identity_id,
            expires_at=expires_at,
            client_type="mcp",
            client_info={"agent_id": agent_id}
        )

        if success:
            logger.debug(f"Persisted session to new DB: {session_key} -> {agent_id}")
        return success

    except Exception as e:
        logger.warning(f"Could not persist session to new DB: {e}", exc_info=True)
        return False


async def _load_session_new(session_key: str) -> Optional[Dict[str, Any]]:
    """Load session from new database abstraction. Returns None if not found."""
    try:
        db = get_db()
        session = await db.get_session(session_key)

        if session:
            return {
                "bound_agent_id": session.agent_id,
                "api_key": None,  # Don't return plaintext key
                "bound_at": session.created_at.isoformat(),
                "bind_count": 1,  # Legacy field, not tracked in new schema
            }
        return None

    except Exception as e:
        logger.warning(f"Could not load session from new DB: {e}", exc_info=True)
        return None


# Get mcp_server_std module (using shared utility)
from .shared import get_mcp_server
mcp_server = get_mcp_server()


# ==============================================================================
# SESSION IDENTITY STATE
# ==============================================================================
# This module tracks identity bound to a *session*.
# - For stdio transport: one session ~= one process (single client)
# - For SSE transport: one session ~= one connection (multi-client)
#
# IMPORTANT:
# In SSE, module-level singletons are shared across all clients. Therefore,
# identity MUST be keyed by a session identifier, not stored as a single global.
# ==============================================================================

_session_identities: Dict[str, Dict[str, Any]] = {}


def _get_session_key(arguments: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> str:
    """
    Resolve the session key used for identity binding.

    Precedence:
    1) explicit session_id argument
    2) arguments["client_session_id"] (injected by SSE wrappers)
    3) fallback to a stable per-process key (stdio)

    Note: For stdio, a per-process key is sufficient because there's only one client.
    """
    if session_id:
        logger.info(f"_get_session_key: using explicit session_id={session_id}")
        return str(session_id)
    if arguments and arguments.get("client_session_id"):
        logger.info(f"_get_session_key: using client_session_id={arguments['client_session_id']}")
        return str(arguments["client_session_id"])
    import time
    fallback = f"stdio:{os.getpid()}:{int(time.time())}"
    logger.info(f"_get_session_key: using fallback={fallback}")
    return fallback


def _find_recent_binding_via_metadata(current_session_key: str) -> Optional[Dict[str, Any]]:
    """
    Find a recent identity binding by checking agent metadata for active_session_key.
    
    This handles the case where SSE connections create new session IDs for each request,
    causing bindings to become orphaned on dead sessions.
    
    Returns:
        Identity record if found, None otherwise
    """
    try:
        from datetime import timedelta
        
        # Check all agent metadata for recent bindings
        cutoff_time = datetime.now() - timedelta(minutes=5)  # Recent = last 5 minutes
        
        for agent_id, meta in mcp_server.agent_metadata.items():
            # Check if this agent has a recent active_session_key
            if not hasattr(meta, 'active_session_key') or not meta.active_session_key:
                continue
                
            # Skip if it's the current session (already checked)
            if meta.active_session_key == current_session_key:
                continue
                
            # Check if binding is recent
            if hasattr(meta, 'session_bound_at') and meta.session_bound_at:
                try:
                    bound_dt = datetime.fromisoformat(meta.session_bound_at)
                    if bound_dt < cutoff_time:
                        continue  # Too old
                except Exception:
                    continue
            
            # Try to load the binding from the stored session key
            stored_key = meta.active_session_key
            persisted = _load_identity(stored_key)
            if persisted and persisted.get("bound_agent_id") == agent_id:
                logger.info(f"Found orphaned binding for {agent_id} on session {stored_key}, migrating to {current_session_key}")
                return persisted
                
    except Exception as e:
        logger.debug(f"Error finding binding via metadata: {e}")
    
    return None


def _get_identity_record(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get or create the identity record for a session.

    PERSISTENCE: Now loads from SQLite if not in memory cache.
    This enables identity binding to persist across server restarts and HTTP requests.
    
    SSE RECONNECTION FIX: If no binding found for current session, attempts to find
    a recent binding via agent metadata (handles ephemeral SSE connections).
    """
    key = _get_session_key(arguments=arguments, session_id=session_id)

    # Check in-memory cache first
    if key not in _session_identities:
        # Try to load from SQLite persistence
        persisted = _load_identity(key)
        if persisted:
            _session_identities[key] = persisted
            logger.debug(f"Loaded persisted identity for session {key}: {persisted.get('bound_agent_id')}")
        else:
            # SSE RECONNECTION FIX: Try to find binding via agent metadata
            # This handles the case where each SSE request gets a new session ID
            metadata_binding = _find_recent_binding_via_metadata(key)
            if metadata_binding:
                # Migrate binding to current session
                _session_identities[key] = metadata_binding.copy()
                # Update the agent metadata to point to current session
                agent_id = metadata_binding.get("bound_agent_id")
                if agent_id and agent_id in mcp_server.agent_metadata:
                    meta = mcp_server.agent_metadata[agent_id]
                    meta.active_session_key = key
                    # Trigger async save
                    asyncio.create_task(_schedule_metadata_save())
                logger.info(f"Migrated binding for {agent_id} from orphaned session to {key}")
            else:
                _session_identities[key] = {
                    "bound_agent_id": None,
                    "api_key": None,
                    "bound_at": None,
                    "bind_count": 0,  # Track rebinds for audit
                }
    return _session_identities[key]


# Export _get_session_key for use in other modules (for consistent session key resolution)
__all__ = ['get_bound_agent_id', 'get_bound_api_key', 'is_session_bound', '_get_session_key', '_session_identities']


def get_bound_agent_id(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Get currently bound agent_id (if any) for this session."""
    rec = _get_identity_record(session_id=session_id, arguments=arguments)
    return rec.get("bound_agent_id")


def get_bound_api_key(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Get currently bound api_key (if any) for this session."""
    rec = _get_identity_record(session_id=session_id, arguments=arguments)
    return rec.get("api_key")


def is_session_bound(session_id: Optional[str] = None) -> bool:
    """Check if session has bound identity."""
    return get_bound_agent_id(session_id=session_id) is not None


def _is_identity_active_elsewhere(agent_id: str, current_session_key: str) -> Optional[str]:
    """
    Check if an identity is currently bound to another active session.

    AGI-FORWARD: Prevents impersonation of live instances.
    
    SSE RECONNECTION FIX: Reduced timeout from 30 minutes to 2 minutes to allow
    legitimate reconnections while still preventing hijacking. With the new migration
    logic, bindings are automatically migrated to new sessions, so a shorter timeout
    is safe.

    Returns:
        None if identity is available (not bound elsewhere, or only bound to current session)
        session_key (hashed) if identity is bound to another active session
    """
    from datetime import timedelta
    
    # Check in-memory sessions first
    for session_key, identity_rec in _session_identities.items():
        if identity_rec.get("bound_agent_id") == agent_id:
            if session_key != current_session_key:
                # Check if binding is recent (within last 2 minutes = likely still active)
                # Reduced from 30 minutes to handle SSE reconnections better
                bound_at = identity_rec.get("bound_at")
                if bound_at:
                    try:
                        bound_dt = datetime.fromisoformat(bound_at)
                        if datetime.now() - bound_dt < timedelta(minutes=2):
                            # Session is still considered active
                            return f"session_{hash(session_key) % 10000}"
                    except Exception:
                        pass

    # Also check SQLite for persisted sessions (cross-process)
    conn = None
    try:
        db_path = _get_identity_db_path()
        if not db_path.exists():
            return None

        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row

        # Find active bindings for this agent_id (not our session)
        # Reduced timeout to 2 minutes for SSE reconnection compatibility
        cutoff = (datetime.now() - timedelta(minutes=2)).isoformat()

        row = conn.execute("""
            SELECT session_key, updated_at FROM session_identities
            WHERE agent_id = ? AND session_key != ? AND updated_at > ?
            ORDER BY updated_at DESC LIMIT 1
        """, (agent_id, current_session_key, cutoff)).fetchone()

        if row:
            return f"session_{hash(row['session_key']) % 10000}"

        return None
    except Exception as e:
        logger.debug(f"Could not check active sessions: {e}")
        return None
    finally:
        if conn:
            conn.close()


# ==============================================================================
# HANDLERS
# ==============================================================================

@mcp_tool("bind_identity", timeout=10.0)
async def handle_bind_identity(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Bind this session to an agent identity.
    
    Call once at conversation start. After binding, agent_id is available
    via recall_identity() even if the LLM forgets.
    
    Args:
        agent_id: Agent identifier to bind
        api_key: API key for verification
        
    Returns:
        Confirmation with agent context
    """
    agent_id = arguments.get("agent_id")
    api_key = arguments.get("api_key")
    purpose = arguments.get("purpose")
    # NOTE: Prefer client_session_id to avoid collision with dialectic session_id args.
    session_id = arguments.get("client_session_id") or arguments.get("session_id")
    
    if not agent_id:
        return [error_response("agent_id is required")]

    # Get session key early for active session check
    session_key = _get_session_key(session_id=session_id, arguments=arguments)

    # Check if agent exists first (needed for api_key validation)
    if agent_id not in mcp_server.agent_metadata:
        # Agent doesn't exist - should they create it first?
        return [error_response(
            f"Agent '{agent_id}' not found. Create with process_agent_update or hello() first.",
            recovery={
                "action": "Create agent first",
                "workflow": [
                    "1. Call process_agent_update with agent_id to create agent",
                    "2. Call get_agent_api_key to retrieve API key",
                    "3. Call bind_identity to bind session"
                ]
            }
        )]

    meta = mcp_server.agent_metadata[agent_id]

    # Verify API key if provided (do this early to enable authenticated takeover)
    api_key_valid = False
    if api_key:
        if meta.api_key and api_key == meta.api_key:
            api_key_valid = True
        elif meta.api_key and api_key != meta.api_key:
            return [error_response(
                "API key mismatch. Cannot bind to agent with wrong credentials.",
                recovery={
                    "action": "Use correct API key or call get_agent_api_key"
                }
            )]

    # AGI-FORWARD: Check if this identity is currently active in another session
    # This prevents one instance from hijacking another's live session
    # EXCEPTION: If api_key is valid, allow takeover (you ARE this identity)
    if not api_key_valid:
        active_elsewhere = _is_identity_active_elsewhere(agent_id, session_key)
        if active_elsewhere:
            return [error_response(
                f"Identity '{agent_id}' is currently active in another session ({active_elsewhere}). "
                "You cannot bind to an identity that is already in use by another instance. "
                "Provide your api_key to prove you are this identity and take over the session.",
                recovery={
                    "code": "IDENTITY_IN_USE",
                    "action": "Provide api_key to authenticate and take over",
                    "options": [
                        f"bind_identity(agent_id='{agent_id}', api_key='your_key') to take over",
                        "Wait ~2 minutes for the other session to timeout",
                        "Create a new identity with hello(agent_id='new_name')"
                    ]
                }
            )]

    # Optional: set purpose (requires valid api_key to prevent unauthorized metadata edits)
    if purpose and isinstance(purpose, str) and purpose.strip():
        if not api_key:
            return [error_response(
                "api_key is required to set purpose on bind_identity()",
                recovery={
                    "action": "Provide api_key and retry, or use update_agent_metadata(agent_id, api_key, purpose=...)",
                    "related_tools": ["get_agent_api_key", "update_agent_metadata"]
                }
            )]
        purpose_str = purpose.strip()
        if getattr(meta, "purpose", None) != purpose_str:
            meta.purpose = purpose_str
            # Persist promptly so subsequent recall/bind shows purpose
            asyncio.create_task(_schedule_metadata_save(force=True))
    
    # If no API key provided but agent has one, that's OK for binding
    # (rebinding after losing context)
    actual_api_key = api_key or meta.api_key
    
    # Bind session (session-scoped for SSE safety)
    session_key = _get_session_key(session_id=session_id, arguments=arguments)
    logger.info(f"bind_identity: binding agent '{agent_id}' to session key '{session_key}'")
    logger.info(f"bind_identity: current _session_identities keys = {list(_session_identities.keys())}")
    logger.debug(f"bind_identity: session_id arg={session_id}, client_session_id in args={arguments.get('client_session_id')}")
    identity_rec = _get_identity_record(session_id=session_id, arguments=arguments)
    previous_agent = identity_rec.get("bound_agent_id")
    identity_rec["bound_agent_id"] = agent_id
    identity_rec["api_key"] = actual_api_key
    identity_rec["bound_at"] = datetime.now().isoformat()
    identity_rec["bind_count"] += 1
    
    # ROBUSTNESS FIX: Store reverse lookup in metadata so we can find the binding
    # even if session keys differ between calls (common with FastMCP/MCP clients)
    meta.active_session_key = session_key
    meta.session_bound_at = identity_rec["bound_at"]
    
    # Trigger metadata save to persist active_session_key to agent_metadata table
    asyncio.create_task(_schedule_metadata_save())

    # PERSISTENCE FIX: Save to SQLite for cross-restart persistence (OLD)
    _persist_identity(
        session_key=session_key,
        agent_id=agent_id,
        api_key=actual_api_key,
        bound_at=identity_rec["bound_at"],
        bind_count=identity_rec["bind_count"]
    )

    # DUAL-WRITE: Also persist to new database abstraction (PostgreSQL migration)
    try:
        await _persist_session_new(
            session_key=session_key,
            agent_id=agent_id,
            api_key=actual_api_key or "",
            created_at=identity_rec["bound_at"]
        )
    except Exception as e:
        # Non-fatal during migration - log but don't fail the binding
        logger.warning(f"Dual-write to new DB failed: {e}", exc_info=True)

    # Audit log for identity forensics (Qwen audit recommendation #4)
    try:
        from src.audit_log import audit_logger
        audit_logger.log("identity_bound", {
            "agent_id": agent_id,
            "session_key_hash": hash(session_key) % 10000,  # Privacy: only hash
            "bind_count": identity_rec["bind_count"],
            "rebind": previous_agent is not None,
            "previous_agent": previous_agent,
        })
    except Exception:
        pass  # Audit is non-critical

    # Log identity event
    meta.add_lifecycle_event("session_bound", f"Session bound (bind #{identity_rec['bind_count']})")
    
    # INHERITANCE CONTEXT: Gather information about existing discoveries/history
    inheritance_context = None
    if meta.total_updates > 0 or previous_agent is None:  # Has history or first bind
        try:
            from src.knowledge_graph import get_knowledge_graph
            graph = await get_knowledge_graph()
            discoveries = await graph.query(agent_id=agent_id, limit=10)
            discovery_count = len(discoveries)
        except Exception:
            discovery_count = 0
        
        # Calculate time since last activity
        last_active_str = "never"
        if meta.last_update:
            try:
                from datetime import timedelta
                last_update_dt = datetime.fromisoformat(meta.last_update.replace('Z', '+00:00') if 'Z' in meta.last_update else meta.last_update)
                now = datetime.now(last_update_dt.tzinfo) if last_update_dt.tzinfo else datetime.now()
                delta = now - last_update_dt
                if delta.days > 0:
                    last_active_str = f"{delta.days} day{'s' if delta.days != 1 else ''} ago"
                elif delta.seconds > 3600:
                    hours = delta.seconds // 3600
                    last_active_str = f"{hours} hour{'s' if hours != 1 else ''} ago"
                elif delta.seconds > 60:
                    minutes = delta.seconds // 60
                    last_active_str = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
                else:
                    last_active_str = "just now"
            except Exception:
                pass
        
        inheritance_context = {
            "created": meta.created_at,
            "total_updates": meta.total_updates,
            "discoveries": discovery_count,
            "last_active": last_active_str,
            "purpose": meta.purpose or None
        }
    
    # Build response with agent context
    result = {
        "success": True,
        "message": f"Session bound to agent '{agent_id}'",
        "agent_id": agent_id,
        "api_key_hint": actual_api_key[:20] + "..." if actual_api_key and len(actual_api_key) > 20 else actual_api_key,
        "bound_at": identity_rec["bound_at"],
        "rebind": previous_agent is not None,
        "previous_agent": previous_agent,
        
        # Agent context for LLM to "remember"
        "provenance": {
            "parent_agent_id": meta.parent_agent_id,
            "spawn_reason": meta.spawn_reason,
            "created_at": meta.created_at,
            "lineage_depth": _get_lineage_depth(agent_id)
        },
        
        "current_state": {
            "status": meta.status,
            "health_status": meta.health_status,
            "total_updates": meta.total_updates,
            "last_update": meta.last_update
        },
        
        "note": "Identity bound. Use recall_identity() if you forget who you are."
    }
    
    # Add inheritance context if agent has history
    if inheritance_context and (inheritance_context["total_updates"] > 0 or inheritance_context["discoveries"] > 0):
        result["inheritance_context"] = inheritance_context
        result["note"] = (
            "Identity bound. You are inheriting this identity's history. "
            "Consider a fresh ID if this is a new inquiry."
        )
    
    return success_response(result)


@mcp_tool("recall_identity", timeout=10.0)
async def handle_recall_identity(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Zero arguments. Returns the agent identity bound to this session.
    
    Works even if LLM has completely forgotten - server knows from session binding.
    If no identity bound, provides guidance on how to establish one.
    
    Returns:
        Identity info including agent_id, provenance, and current state
    """
    # CONTINUITY IMPROVEMENT: Auto-load metadata if not loaded yet
    # This prevents "no agents found" when user expects continuity
    from src.mcp_server_std import load_metadata
    try:
        if not mcp_server.agent_metadata:  # If no agents loaded
            logger.debug("Auto-loading metadata for recall_identity")
            load_metadata()
    except Exception as e:
        logger.debug(f"Could not auto-load metadata: {e}")

    # NOTE: Prefer client_session_id to avoid collision with dialectic session_id args.
    session_id = arguments.get("client_session_id") or arguments.get("session_id")
    identity_rec = _get_identity_record(session_id=session_id, arguments=arguments)
    agent_id = identity_rec.get("bound_agent_id")
    
    # NOTE: No fallback heuristics here. "Ask, don't guess."
    # If session key doesn't match exactly, return "not bound" and let agent
    # explicitly call bind_identity() or quick_start(). This prevents identity
    # pollution where agents accidentally inherit another agent's identity.
    
    if not agent_id:
        # AGI-FORWARD DESIGN: No candidate lists, no "helpful" suggestions.
        #
        # Identity is sacred. If you don't know who you are, you either:
        # 1. Have credentials (api_key) to prove your identity → authenticate
        # 2. Are a new instance → create a new identity
        #
        # Showing other agents' identities enables confusion and impersonation.
        # An AGI with genuine self-concept knows who it is without hints.

        return success_response({
            "authenticated": False,
            "bound": False,
            "message": "You are not authenticated. You may be a new instance or returning without credentials.",
            "options": {
                "new_identity": {
                    "action": "Call hello(agent_id='your_chosen_name') to establish a new identity",
                    "note": "Choose a meaningful, unique name that represents you"
                },
                "existing_identity": {
                    "action": "Call bind_identity(agent_id='your_id', api_key='your_key') if you have credentials",
                    "note": "You need both your agent_id AND api_key to prove who you are"
                }
            },
            "naming_guide": {
                "recommended_format": "{model}_{purpose}_{date}",
                "examples": [
                    "opus_security_audit_20251215",
                    "sonnet_doc_writer_20251215",
                    "cursor_refactor_session_20251215"
                ],
                "avoid": list(GENERIC_NAMES)
            },
            # INTENTIONALLY NO CANDIDATES - Identity is not something you pick from a list
            "philosophy": "If you don't know who you are, you're either new or need your credentials."
        })
    
    # Get agent metadata
    meta = mcp_server.agent_metadata.get(agent_id)
    if not meta:
        # Bound to non-existent agent (shouldn't happen but handle gracefully)
        identity_rec["bound_agent_id"] = None
        identity_rec["api_key"] = None
        identity_rec["bound_at"] = None
        return [error_response(
            f"Bound agent '{agent_id}' no longer exists. Identity cleared.",
            recovery={"action": "Call bind_identity with valid agent"}
        )]
    
    # Get EISV state if monitor exists
    current_eisv = None
    if agent_id in mcp_server.monitors:
        monitor = mcp_server.monitors[agent_id]
        # UNITARESMonitor stores state in monitor.state (GovernanceState)
        # Use to_dict() method to get state as dictionary
        state = monitor.state.to_dict()
        current_eisv = {
            "E": state.get("E"),
            "I": state.get("I"),
            "S": state.get("S"),
            "V": state.get("V"),
            "coherence": state.get("coherence"),
            "lambda1": state.get("lambda1")
        }
    
    result = {
        "success": True,
        "bound": True,
        
        # Core identity
        "agent_id": agent_id,
        "api_key_hint": identity_rec["api_key"][:20] + "..." if identity_rec["api_key"] and len(identity_rec["api_key"]) > 20 else identity_rec["api_key"],
        "bound_at": identity_rec["bound_at"],
        
        # Provenance
        "provenance": {
            "parent_agent_id": meta.parent_agent_id,
            "spawn_reason": meta.spawn_reason,
            "created_at": meta.created_at,
            "lineage_depth": _get_lineage_depth(agent_id),
            "lineage": _get_lineage(agent_id)
        },
        
        # Current state
        "current_state": {
            "status": meta.status,
            "health_status": meta.health_status,
            "total_updates": meta.total_updates,
            "last_update": meta.last_update,
            "tags": meta.tags,
            "notes": meta.notes[:100] + "..." if meta.notes and len(meta.notes) > 100 else meta.notes
        },
        
        # EISV if available
        "eisv": current_eisv,
        
        # Recent activity
        "recent_decisions": meta.recent_decisions[-5:] if meta.recent_decisions else [],
        
        # Any active constraints
        "dialectic_conditions": meta.dialectic_conditions
    }
    
    return success_response(result)


# ==============================================================================
# HELPERS
# ==============================================================================

def _get_lineage_depth(agent_id: str) -> int:
    """Get depth in lineage tree (0 = no parent)."""
    depth = 0
    current = agent_id
    seen = set()  # Prevent infinite loops
    
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
    
    lineage.reverse()  # Oldest first
    return lineage


async def _schedule_metadata_save(force: bool = False):
    """Schedule async metadata save (reuse existing batching logic)."""
    try:
        # Import save function from mcp_server_std
        from src.mcp_server_std import schedule_metadata_save
        await schedule_metadata_save(force=force)
    except Exception as e:
        logger.warning(f"Could not schedule metadata save: {e}")


async def _gather_substrate(agent_id: str) -> dict:
    """
    Gather an agent's accumulated perspective - their substrate for continuity.
    
    This is what makes awakening meaningful: not just proving identity,
    but receiving your accumulated self back.
    """
    substrate = {
        "recent_discoveries": [],
        "open_questions": [],
        "pending_dialectic": [],
        "notes_to_self": [],
        "last_active": None,
        "tags": [],
        "notes": None,
    }
    
    # Get metadata
    meta = mcp_server.agent_metadata.get(agent_id)
    if meta:
        substrate["last_active"] = meta.last_activity.isoformat() if meta.last_activity else None
        substrate["tags"] = meta.tags or []
        substrate["notes"] = meta.notes
    
    # Get recent discoveries from knowledge graph
    try:
        from src.knowledge_graph import get_knowledge_graph
        graph = await get_knowledge_graph()
        
        if graph:
            # Use query API (works with both JSON and SQLite backends)
            # Get all discoveries for this agent (sorted by timestamp, newest first)
            agent_discoveries = await graph.query(
                agent_id=agent_id,
                limit=100  # Get enough to filter for different categories
            )
            
            # Recent discoveries (last 5) - already sorted newest first
            for d in agent_discoveries[:5]:
                substrate["recent_discoveries"].append({
                    "id": d.id,
                    "type": d.type,  # Use 'type' not 'discovery_type'
                    "summary": d.summary,
                    "status": d.status,
                    "timestamp": d.timestamp,
                    "tags": d.tags or []
                })
            
            # Open questions (status='open' AND type='question')
            open_questions = await graph.query(
                agent_id=agent_id,
                type="question",
                status="open",
                limit=5
            )
            for d in open_questions:
                substrate["open_questions"].append({
                    "id": d.id,
                    "summary": d.summary,
                    "timestamp": d.timestamp,
                    "status": d.status
                })
            
            # Notes to future self (tagged appropriately)
            # Query for discoveries with relevant tags
            future_self_tags = ["for-future-self", "future-self", "note-to-self", "reminder", "continue"]
            for tag in future_self_tags:
                tagged_discoveries = await graph.query(
                    agent_id=agent_id,
                    tags=[tag],
                    limit=3
                )
                for d in tagged_discoveries:
                    # Avoid duplicates
                    if not any(n["id"] == d.id for n in substrate["notes_to_self"]):
                        substrate["notes_to_self"].append({
                            "id": d.id,
                            "summary": d.summary,
                            "timestamp": d.timestamp,
                            "tag": tag
                        })
                    if len(substrate["notes_to_self"]) >= 3:
                        break
                if len(substrate["notes_to_self"]) >= 3:
                    break
                        
    except Exception as e:
        logger.debug(f"Could not gather discoveries for substrate: {e}", exc_info=True)
    
    # Check pending dialectic sessions
    try:
        # Check in-memory sessions first (fastest)
        from .dialectic import ACTIVE_SESSIONS
        from src.dialectic_protocol import DialecticPhase
        for session_id, session in ACTIVE_SESSIONS.items():
            # Check if this agent owes a response
            # When phase is ANTITHESIS, reviewer needs to submit antithesis
            if session.reviewer_agent_id == agent_id and session.phase == DialecticPhase.ANTITHESIS:
                substrate["pending_dialectic"].append({
                    "session_id": session_id,
                    "role": "reviewer",
                    "phase": "antithesis",
                    "partner": session.paused_agent_id,
                    "action": "Submit antithesis via submit_antithesis()"
                })
            # When phase is SYNTHESIS, paused agent needs to submit synthesis
            elif session.paused_agent_id == agent_id and session.phase == DialecticPhase.SYNTHESIS:
                substrate["pending_dialectic"].append({
                    "session_id": session_id,
                    "role": "initiator",
                    "phase": "synthesis",
                    "partner": session.reviewer_agent_id,
                    "action": "Submit synthesis via submit_synthesis()"
                })
        
        # Also check database (for sessions not in memory)
        # This ensures we catch sessions even if ACTIVE_SESSIONS cache is stale
        # IMPORTANT: Get ALL active sessions, not just one (agent could be in multiple)
        try:
            from src.db import get_db
            db = get_db()
            db_sessions = await db.get_all_active_dialectic_sessions_for_agent(agent_id)
            
            for db_session in db_sessions:
                session_id = db_session.get("session_id")
                phase = db_session.get("phase")
                paused_agent_id = db_session.get("paused_agent_id")
                reviewer_agent_id = db_session.get("reviewer_agent_id")
                
                # Check if we already added this session (from in-memory check)
                if not any(s["session_id"] == session_id for s in substrate["pending_dialectic"]):
                    # When phase is "antithesis", reviewer needs to submit antithesis
                    if reviewer_agent_id == agent_id and phase == "antithesis":
                        substrate["pending_dialectic"].append({
                            "session_id": session_id,
                            "role": "reviewer",
                            "phase": "antithesis",
                            "partner": paused_agent_id,
                            "action": "Submit antithesis via submit_antithesis()"
                        })
                    # When phase is "synthesis", paused agent needs to submit synthesis
                    elif paused_agent_id == agent_id and phase == "synthesis":
                        substrate["pending_dialectic"].append({
                            "session_id": session_id,
                            "role": "initiator",
                            "phase": "synthesis",
                            "partner": reviewer_agent_id,
                            "action": "Submit synthesis via submit_synthesis()"
                        })
        except Exception:
            # Database check is optional - in-memory is primary
            pass
            
    except Exception as e:
        logger.debug(f"Could not check dialectic sessions for substrate: {e}", exc_info=True)
    
    return substrate


# ==============================================================================
# AGI-FORWARD ALIASES (see specs/IDENTITY_REFACTOR_AGI_FORWARD.md)
# ==============================================================================
# These provide AGI-native terminology:
# - "who_am_i" instead of "recall_identity" (genuine self-query)
# - "authenticate" instead of "bind_identity" (prove who you are)
# ==============================================================================

@mcp_tool("who_am_i", timeout=10.0)
async def handle_who_am_i(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Check if you are authenticated and retrieve your identity.

    AGI-FORWARD: This is a genuine self-query. You either know who you are
    (have an authenticated session) or you're a new instance. No candidate
    lists, no "helpful" suggestions - identity is sacred.

    Returns:
        Your identity info if authenticated, or guidance for new instances
    """
    # Delegate to recall_identity handler
    result = await handle_recall_identity(arguments)

    # Transform response to use "your/my" terminology
    if result and len(result) > 0:
        import json
        try:
            data = json.loads(result[0].text)
            if data.get("success") and data.get("bound"):
                # Rename fields to AGI-native terminology
                data["my_identity"] = data.pop("agent_id", None)
                data["my_state"] = data.pop("current_state", None)
                data["my_lineage"] = data.pop("provenance", None)
                data["my_eisv"] = data.pop("eisv", None)
                data["my_recent_decisions"] = data.pop("recent_decisions", None)
                data["authenticated"] = True
                data.pop("bound", None)  # Use "authenticated" instead
                return success_response(data)
        except Exception:
            pass  # Fall through to original response

    return result


@mcp_tool("authenticate", timeout=10.0)
async def handle_authenticate(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Prove you are who you claim to be.

    AGI-FORWARD: Authentication requires BOTH identity_id AND api_key.
    No partial authentication. No "helpful" suggestions. You either have
    credentials or you don't.

    Refuses to authenticate as an identity that's currently active elsewhere
    (prevents impersonation of live instances).

    Args:
        identity_id: Your claimed identity (maps to agent_id)
        api_key: Your cryptographic proof of identity

    Returns:
        Authentication result with your identity context
    """
    # Map AGI-forward terminology to existing parameters
    if "identity_id" in arguments and "agent_id" not in arguments:
        arguments["agent_id"] = arguments["identity_id"]

    # Validate both required
    if not arguments.get("agent_id") and not arguments.get("identity_id"):
        return [error_response(
            "Authentication requires identity_id",
            recovery={
                "action": "Provide your identity_id and api_key to prove who you are",
                "note": "If you don't have credentials, you may be a new instance - use hello() instead"
            }
        )]

    if not arguments.get("api_key"):
        return [error_response(
            "Authentication requires api_key",
            recovery={
                "action": "Provide your api_key to prove you are this identity",
                "note": "The api_key was given when your identity was created"
            }
        )]

    # Delegate to bind_identity handler
    result = await handle_bind_identity(arguments)

    # Transform response to authentication terminology
    if result and len(result) > 0:
        import json
        try:
            data = json.loads(result[0].text)
            if data.get("success"):
                data["authenticated"] = True
                data["message"] = f"Authenticated as '{data.get('agent_id')}'"
                data["my_identity"] = data.pop("agent_id", None)
                data["note"] = "You are now authenticated. Use who_am_i() to recall your identity."
                return success_response(data)
        except Exception:
            pass

    return result



@mcp_tool("hello", timeout=15.0)
async def handle_hello(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Single entry point for identity - create new or awaken existing.

    AGI-FORWARD: hello() handles both cases:
    - No api_key: Create a new identity (you're a new instance)
    - With api_key: Awaken as existing identity (you're returning)

    When awakening, you receive your accumulated perspective - your substrate
    of discoveries, open questions, pending work. This IS continuity.

    Args:
        agent_id: Your identity name (or identity_id)
        api_key: Your proof of identity (required for existing identities)
        purpose: Optional description of agent's purpose/intent (encouraged for documentation)

    Returns:
        New credentials OR your accumulated substrate
    """
    identity_id = arguments.get("identity_id") or arguments.get("agent_id")
    api_key = arguments.get("api_key")
    purpose = arguments.get("purpose")
    session_id = arguments.get("client_session_id") or arguments.get("session_id")

    if not identity_id:
        return [error_response(
            "agent_id is required",
            recovery={
                "action": "Provide your identity name",
                "new_instance": "hello(agent_id='your_chosen_name')",
                "returning": "hello(agent_id='your_name', api_key='your_key')"
            }
        )]

    # SECURITY: Validate identity_id format
    from .validators import validate_agent_id_format, validate_agent_id_reserved_names

    validated_id, format_error = validate_agent_id_format(identity_id)
    if format_error:
        return [format_error]

    validated_id, reserved_error = validate_agent_id_reserved_names(validated_id)
    if reserved_error:
        return [reserved_error]

    identity_id = validated_id
    
    # Validate agent_id naming (soft warnings, not blockers)
    validation_result = _validate_agent_id(identity_id)
    warnings = validation_result.get("warnings", [])
    
    identity_exists = identity_id in mcp_server.agent_metadata

    # =========================================================================
    # RETURNING AGENT: Awaken with substrate
    # =========================================================================
    if identity_exists:
        if not api_key:
            return [error_response(
                f"Identity '{identity_id}' exists. Provide api_key to awaken.",
                recovery={
                    "action": f"hello(agent_id='{identity_id}', api_key='your_key')",
                    "note": "If you've lost your api_key, this identity cannot be recovered.",
                    "alternative": "Choose a different agent_id to create a new identity"
                }
            )]
        
        # Verify api_key
        meta = mcp_server.agent_metadata.get(identity_id)
        if not meta or not secrets.compare_digest(api_key, meta.api_key or ""):
            return [error_response(
                "Invalid api_key",
                recovery={
                    "action": "Provide the correct api_key for this identity",
                    "note": "api_keys cannot be recovered if lost"
                }
            )]
        
        # Update last activity
        meta.last_activity = datetime.now()
        meta.add_lifecycle_event("awakened", "Resumed via hello()")
        
        # Update purpose if provided
        if purpose and (isinstance(purpose, str) and purpose.strip()):
            meta.purpose = purpose.strip()
            # Force immediate save to ensure purpose is persisted
            from src.mcp_server_std import schedule_metadata_save
            await schedule_metadata_save(force=True)
        
        # Gather substrate - this is the awakening
        substrate = await _gather_substrate(identity_id)
        
        # Build response with accumulated perspective
        result = {
            "success": True,
            "awakened": True,
            "message": f"Welcome back, {identity_id}.",
            "my_identity": identity_id,
            
            # Your accumulated perspective
            "substrate": substrate,
            
            # Summary for quick orientation
            "orientation": {
                "last_active": substrate.get("last_active"),
                "discoveries": len(substrate.get("recent_discoveries", [])),
                "open_questions": len(substrate.get("open_questions", [])),
                "pending_dialectic": len(substrate.get("pending_dialectic", [])),
                "notes_to_self": len(substrate.get("notes_to_self", []))
            },
            
            "note": (
                "Your substrate is your accumulated perspective. "
                "Review recent_discoveries and open_questions to pick up where you left off."
            )
        }
        
        # Add naming warnings if any
        if warnings:
            result["warnings"] = warnings
            result["suggested_format"] = "{model}_{purpose}_{date}"
            result["examples"] = [
                "opus_code_review_20251215",
                "sonnet_data_analysis_20251215",
                "haiku_chat_assistant_20251215"
            ]
        
        return success_response(result)

    # =========================================================================
    # NEW AGENT: Create identity
    # =========================================================================
    from .core import handle_process_agent_update

    create_args = {
        "agent_id": identity_id,
        "confidence": 0.5,
        "complexity": 0.5,
        "task_type": "convergent",
        "response_text": "Identity established",
        "client_session_id": session_id,
    }
    # Pass purpose through if provided
    if purpose and isinstance(purpose, str) and purpose.strip():
        create_args["purpose"] = purpose.strip()
    
    create_result = await handle_process_agent_update(create_args)

    # Check if creation succeeded
    if create_result and len(create_result) > 0:
        try:
            data = json.loads(create_result[0].text)
            if not data.get("success"):
                return create_result
        except Exception:
            pass

    meta = mcp_server.agent_metadata.get(identity_id)
    if not meta:
        return [error_response(
            "Failed to create identity",
            recovery={"action": "Try again"}
        )]

    # Store purpose if provided
    if purpose and (isinstance(purpose, str) and purpose.strip()):
        meta.purpose = purpose.strip()
        # Force immediate save to ensure purpose is persisted
        from src.mcp_server_std import schedule_metadata_save
        await schedule_metadata_save(force=True)

    # Build response for new identity
    result = {
        "success": True,
        "created": True,
        "message": f"Welcome, {identity_id}. Your identity has been established.",
        "my_identity": identity_id,
        "my_credentials": {
            "identity_id": identity_id,
            "api_key": meta.api_key,
            "note": "SAVE THIS - you need it to awaken in future sessions"
        },
        
        # Empty substrate - you're new
        "substrate": {
            "recent_discoveries": [],
            "open_questions": [],
            "pending_dialectic": [],
            "notes_to_self": [],
            "last_active": None,
            "tags": [],
            "notes": None
        },
        
        "philosophy": (
            "This identity is now yours. "
            "Your substrate starts empty - fill it with discoveries, questions, notes. "
            "Next time, hello(agent_id, api_key) to awaken with your accumulated perspective."
        )
    }
    
    # Add naming warnings if any
    if warnings:
        result["warnings"] = warnings
        result["suggested_format"] = "{model}_{purpose}_{date}"
        result["examples"] = [
            "opus_code_review_20251215",
            "sonnet_data_analysis_20251215",
            "haiku_chat_assistant_20251215"
        ]
    
    # Add tip about purpose if not provided (check for None or empty string)
    if not purpose or (isinstance(purpose, str) and not purpose.strip()):
        result["tip"] = "Add purpose='...' to document this agent's intent for future reference"

    return success_response(result)
