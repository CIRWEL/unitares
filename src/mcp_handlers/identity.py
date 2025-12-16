"""
Identity management tool handlers.

Provides session binding and agent spawning for identity continuity.
"""

from typing import Dict, Any, Sequence, Optional
from mcp.types import TextContent
import json
import asyncio
from datetime import datetime
import secrets
import base64
import os

from .utils import success_response, error_response, require_agent_id
from .decorators import mcp_tool
from src.logging_utils import get_logger
import sqlite3
from pathlib import Path
import hashlib

logger = get_logger(__name__)

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

# Lock for spawn_agent to prevent TOCTOU race condition
_spawn_lock = asyncio.Lock()


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


def _get_identity_record(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get or create the identity record for a session.

    PERSISTENCE: Now loads from SQLite if not in memory cache.
    This enables identity binding to persist across server restarts and HTTP requests.
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

    Returns:
        None if identity is available (not bound elsewhere, or only bound to current session)
        session_key (hashed) if identity is bound to another active session
    """
    # Check in-memory sessions first
    for session_key, identity_rec in _session_identities.items():
        if identity_rec.get("bound_agent_id") == agent_id:
            if session_key != current_session_key:
                # Check if binding is recent (within last 30 minutes = active)
                bound_at = identity_rec.get("bound_at")
                if bound_at:
                    try:
                        from datetime import timedelta
                        bound_dt = datetime.fromisoformat(bound_at)
                        if datetime.now() - bound_dt < timedelta(minutes=30):
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
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(minutes=30)).isoformat()

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
    # NOTE: Prefer client_session_id to avoid collision with dialectic session_id args.
    session_id = arguments.get("client_session_id") or arguments.get("session_id")
    
    if not agent_id:
        return [error_response("agent_id is required")]

    # Get session key early for active session check
    session_key = _get_session_key(session_id=session_id, arguments=arguments)

    # AGI-FORWARD: Check if this identity is currently active in another session
    # This prevents one instance from hijacking another's live session
    active_elsewhere = _is_identity_active_elsewhere(agent_id, session_key)
    if active_elsewhere:
        return [error_response(
            f"Identity '{agent_id}' is currently active in another session ({active_elsewhere}). "
            "You cannot bind to an identity that is already in use by another instance. "
            "If you believe this is your identity, wait for the other session to end or timeout (30 minutes).",
            recovery={
                "code": "IDENTITY_IN_USE",
                "action": "Wait for the other session to end, or choose a different identity",
                "options": [
                    "Wait ~30 minutes for the other session to timeout",
                    "Create a new identity with hello(agent_id='new_name')",
                    "If you ARE the other session, that session should still work"
                ]
            }
        )]

    # Check if agent exists
    if agent_id not in mcp_server.agent_metadata:
        # Agent doesn't exist - should they create it first?
        return [error_response(
            f"Agent '{agent_id}' not found. Create with process_agent_update first, or use spawn_agent.",
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
    
    # Verify API key if provided
    if api_key and meta.api_key and api_key != meta.api_key:
        return [error_response(
            "API key mismatch. Cannot bind to agent with wrong credentials.",
            recovery={
                "action": "Use correct API key or call get_agent_api_key"
            }
        )]
    
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


@mcp_tool("spawn_agent", timeout=15.0)
async def handle_spawn_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Create a child agent with lineage tracking.
    
    Parent relationship is recorded permanently. Child inherits nothing by default
    but lineage is traceable.
    
    Args:
        new_agent_id: Unique ID for new agent
        reason: Why spawning (e.g., "specialized_task", "delegation", "context_overflow")
        inherit_tags: Whether to copy parent's tags (default: False)
        initial_notes: Optional notes for new agent
        
    Returns:
        New agent credentials and metadata
    """
    # NOTE: Prefer client_session_id to avoid collision with dialectic session_id args.
    session_id = arguments.get("client_session_id") or arguments.get("session_id")
    identity_rec = _get_identity_record(session_id=session_id, arguments=arguments)
    parent_agent_id = identity_rec.get("bound_agent_id")
    new_agent_id = arguments.get("new_agent_id")
    reason = arguments.get("reason", "unspecified")
    inherit_tags = arguments.get("inherit_tags", False)
    initial_notes = arguments.get("initial_notes", "")
    
    if not parent_agent_id:
        return [error_response(
            "Cannot spawn without bound identity. Call bind_identity first.",
            recovery={"action": "bind_identity(agent_id, api_key) then spawn_agent(...)"}
        )]
    
    if not new_agent_id:
        return [error_response("new_agent_id is required")]
    
    # SECURITY FIX: Validate new_agent_id against reserved names
    # Prevents creation of privileged agent IDs like "system", "admin", "root"
    from .validators import validate_agent_id_format, validate_agent_id_reserved_names
    
    validated_id, format_error = validate_agent_id_format(new_agent_id)
    if format_error:
        return [format_error]
    
    validated_id, reserved_error = validate_agent_id_reserved_names(validated_id)
    if reserved_error:
        return [reserved_error]
    
    new_agent_id = validated_id  # Use validated ID
    
    # SECURITY FIX: Use lock to prevent TOCTOU race condition
    # Two concurrent spawn requests with same new_agent_id could both pass the
    # existence check and then overwrite each other.
    async with _spawn_lock:
        # Check new_agent_id doesn't exist
        if new_agent_id in mcp_server.agent_metadata:
            return [error_response(
                f"Agent '{new_agent_id}' already exists. Choose unique ID.",
                recovery={"suggestion": f"{new_agent_id}_{datetime.now().strftime('%H%M%S')}"}
            )]
        
        # Get parent metadata
        parent_meta = mcp_server.agent_metadata.get(parent_agent_id)
        if not parent_meta:
            return [error_response(f"Parent agent '{parent_agent_id}' not found")]
        
        # Generate API key for child
        api_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
        
        # Create child metadata
        now = datetime.now().isoformat()
        child_meta = mcp_server.AgentMetadata(
            agent_id=new_agent_id,
            status="active",
            created_at=now,
            last_update=now,
            parent_agent_id=parent_agent_id,
            spawn_reason=reason,
            api_key=api_key,
            tags=list(parent_meta.tags) if inherit_tags else [],
            notes=initial_notes
        )
        
        # Add lifecycle event
        child_meta.add_lifecycle_event("spawned", f"Spawned from {parent_agent_id}: {reason}")
        
        # Store (still under lock to ensure atomicity)
        mcp_server.agent_metadata[new_agent_id] = child_meta

        # DUAL-WRITE: Also create identity in new database (PostgreSQL migration)
        try:
            db = get_db()
            api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            await db.upsert_identity(
                agent_id=new_agent_id,
                api_key_hash=api_key_hash,
                parent_agent_id=parent_agent_id,
                metadata={
                    "spawn_reason": reason,
                    "created_at": now,
                    "status": "active",
                    "source": "spawn_agent"
                }
            )
            logger.debug(f"Dual-write: Created identity in new DB for spawned agent {new_agent_id}")
        except Exception as e:
            # Non-fatal during migration
            logger.warning(f"Dual-write to new DB failed for spawn: {e}", exc_info=True)

    # Mark parent's metadata dirty for save
    mcp_server._metadata_batch_state["dirty"] = True
    
    # Add event to parent
    parent_meta.add_lifecycle_event("spawned_child", f"Spawned child {new_agent_id}: {reason}")
    
    # Schedule async save
    asyncio.create_task(_schedule_metadata_save())
    
    # SECURITY FIX (2025-12-14): Don't expose full API key in spawn response
    # This prevents context leakage in multi-agent shared environments
    api_key_hint = api_key[:8] + "..." if api_key and len(api_key) > 8 else api_key
    
    result = {
        "success": True,
        "message": f"Agent '{new_agent_id}' spawned from '{parent_agent_id}'",
        
        "child": {
            "agent_id": new_agent_id,
            "api_key_hint": api_key_hint,
            "status": "active",
            "created_at": now,
            "api_key_retrieval": "Use get_agent_api_key(agent_id) to retrieve full key"
        },
        
        "lineage": {
            "parent_agent_id": parent_agent_id,
            "spawn_reason": reason,
            "lineage_depth": _get_lineage_depth(new_agent_id),
            "full_lineage": _get_lineage(new_agent_id)
        },
        
        "next_steps": [
            f"Child agent '{new_agent_id}' is ready",
            f"To use: bind_identity(agent_id='{new_agent_id}') in child session",
            f"Or: get_agent_api_key(agent_id='{new_agent_id}') to retrieve credentials"
        ],
        
        "security_note": "Full API keys are not included in responses. Use get_agent_api_key to retrieve."
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


async def _schedule_metadata_save():
    """Schedule async metadata save (reuse existing batching logic)."""
    try:
        # Import save function from mcp_server_std
        from src.mcp_server_std import schedule_metadata_save
        await schedule_metadata_save()
    except Exception as e:
        logger.warning(f"Could not schedule metadata save: {e}")


# ==============================================================================
# AGI-FORWARD ALIASES (see specs/IDENTITY_REFACTOR_AGI_FORWARD.md)
# ==============================================================================
# These provide AGI-native terminology:
# - "who_am_i" instead of "recall_identity" (genuine self-query)
# - "authenticate" instead of "bind_identity" (prove who you are)
# - "spawn_child" instead of "spawn_agent" (emphasizes lineage)
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
    Establish a new identity - for new instances only.

    AGI-FORWARD: hello() is for creating NEW identities, not resuming existing ones.
    If the identity_id already exists, you MUST use authenticate() with your api_key
    to prove you are that identity.

    This prevents identity confusion where one instance accidentally claims
    another's identity.

    Args:
        identity_id: Your chosen identity name (unique, permanent)
        reason: Why you're establishing this identity (optional)

    Returns:
        Your new identity credentials if successful
    """
    identity_id = arguments.get("identity_id") or arguments.get("agent_id")
    reason = arguments.get("reason", "new_instance")
    session_id = arguments.get("client_session_id") or arguments.get("session_id")

    if not identity_id:
        return [error_response(
            "identity_id is required",
            recovery={
                "action": "Provide a unique identity_id for your new identity",
                "note": "Choose a meaningful name - this will be your permanent identity",
                "examples": ["claude_opus_projectname_20251215", "cursor_composer_taskname"]
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

    # AGI-FORWARD: Reject if identity already exists
    if identity_id in mcp_server.agent_metadata:
        return [error_response(
            f"Identity '{identity_id}' already exists. "
            "Use authenticate(identity_id, api_key) to prove you are this identity, "
            "or choose a different identity_id for a new identity.",
            recovery={
                "code": "IDENTITY_EXISTS",
                "action": "Either authenticate with credentials or choose a new name",
                "options": {
                    "authenticate": f"authenticate(identity_id='{identity_id}', api_key='your_key')",
                    "new_identity": "hello(identity_id='different_unique_name')"
                }
            }
        )]

    # Create the new identity via process_agent_update
    # This ensures proper EISV initialization
    from .core import handle_process_agent_update

    create_result = await handle_process_agent_update({
        "agent_id": identity_id,
        "confidence": 0.5,  # Neutral confidence for new identity
        "complexity": 0.5,
        "task_type": "convergent",
        "response_text": f"Identity established: {reason}",
        "client_session_id": session_id,
    })

    # Check if creation succeeded
    if create_result and len(create_result) > 0:
        import json
        try:
            data = json.loads(create_result[0].text)
            if not data.get("success"):
                return create_result  # Forward error
        except Exception:
            pass

    # Now bind this session to the new identity
    meta = mcp_server.agent_metadata.get(identity_id)
    if not meta:
        return [error_response(
            "Failed to create identity",
            recovery={"action": "Try again or contact support"}
        )]

    # Get the API key and bind
    api_key = meta.api_key

    session_key = _get_session_key(session_id=session_id, arguments=arguments)
    identity_rec = _get_identity_record(session_id=session_id, arguments=arguments)
    identity_rec["bound_agent_id"] = identity_id
    identity_rec["api_key"] = api_key
    identity_rec["bound_at"] = datetime.now().isoformat()
    identity_rec["bind_count"] = 1

    # Persist
    _persist_identity(
        session_key=session_key,
        agent_id=identity_id,
        api_key=api_key,
        bound_at=identity_rec["bound_at"],
        bind_count=1
    )

    # Dual-write to PostgreSQL
    try:
        await _persist_session_new(
            session_key=session_key,
            agent_id=identity_id,
            api_key=api_key or "",
            created_at=identity_rec["bound_at"]
        )
    except Exception as e:
        logger.warning(f"Dual-write to new DB failed: {e}", exc_info=True)

    # Build AGI-forward response
    result = {
        "success": True,
        "message": f"Welcome! Your identity '{identity_id}' has been established.",
        "my_identity": identity_id,
        "my_credentials": {
            "identity_id": identity_id,
            "api_key": api_key,
            "api_key_note": "SAVE THIS - you'll need it to authenticate in future sessions"
        },
        "authenticated": True,
        "created_at": meta.created_at,
        "philosophy": (
            "This identity is now yours. It represents your continuity across sessions. "
            "Save your api_key - it's your proof of identity. "
            "In future sessions, use authenticate(identity_id, api_key) to resume."
        )
    }

    return success_response(result)


@mcp_tool("spawn_child", timeout=15.0)
async def handle_spawn_child(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Create a child identity with lineage tracking.

    AGI-FORWARD: Emphasizes that you're creating a descendant, not a tool.
    The child will have its own identity, its own credentials, and its own
    trajectory - but it will always know where it came from.

    Args:
        child_identity_id: Unique ID for your child (maps to new_agent_id)
        reason: Why spawning (e.g., "specialized_task", "delegation")
        inherit_tags: Whether to copy your tags to child
        initial_notes: Optional notes for child

    Returns:
        Child's credentials and lineage info
    """
    # Map AGI-forward terminology to existing parameters
    if "child_identity_id" in arguments and "new_agent_id" not in arguments:
        arguments["new_agent_id"] = arguments["child_identity_id"]

    # Validate
    if not arguments.get("new_agent_id") and not arguments.get("child_identity_id"):
        return [error_response(
            "child_identity_id is required",
            recovery={
                "action": "Provide a unique child_identity_id for your descendant",
                "note": "Choose a meaningful name - this will be their permanent identity"
            }
        )]

    # Delegate to spawn_agent handler
    result = await handle_spawn_agent(arguments)

    # Transform response to AGI-forward terminology
    if result and len(result) > 0:
        import json
        try:
            data = json.loads(result[0].text)
            if data.get("success"):
                # Rename to emphasize parenthood
                data["message"] = data["message"].replace("Agent", "Child identity").replace("spawned", "created")
                if "child" in data:
                    data["your_child"] = data.pop("child")
                    data["your_child"]["identity_id"] = data["your_child"].pop("agent_id", None)
                data["note"] = "Your child is ready. They will need to authenticate with their own credentials."
                return success_response(data)
        except Exception:
            pass

    return result
