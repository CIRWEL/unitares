"""
Identity management tool handlers.

Provides session binding for identity continuity.
"""

from typing import Dict, Any, Sequence, Optional, Tuple
from mcp.types import TextContent
import json
import asyncio
from datetime import datetime, timezone
import secrets
import base64
import os
import re

from .utils import success_response, error_response, require_agent_id
from .decorators import mcp_tool
from src.logging_utils import get_logger
from pathlib import Path
import hashlib

logger = get_logger(__name__)

# Redis session cache (optional - falls back to in-memory if unavailable)
_session_cache = None

def _get_session_cache():
    """Lazy import session cache to avoid hard dependency on Redis."""
    global _session_cache
    if _session_cache is None:
        try:
            from src.cache import get_session_cache
            _session_cache = get_session_cache()
        except ImportError:
            logger.debug("Redis cache not available - using in-memory only")
            _session_cache = False  # Mark as unavailable
    return _session_cache if _session_cache else None

# ==============================================================================
# AGENT ID NAMING VALIDATION
# ==============================================================================

GENERIC_NAMES = {"test", "agent", "bot", "assistant", "claude", "ai", "temp", "tmp"}
MIN_LENGTH = 8


def _validate_agent_id(agent_id: str) -> dict:
    """
    DISABLED: No more naming warnings. Use whatever you want.
    
    Previously encouraged descriptive names, but that was annoying.
    Now it's a no-op - use short IDs, generic IDs, whatever. We don't care.
    
    Returns:
        dict with "valid" (always True) and empty "warnings" list
    """
    # No-op: No warnings, no suggestions, no herding cats
    return {"valid": True, "warnings": []}

# New database abstraction (for PostgreSQL migration)
from src.db import get_db

# ==============================================================================
# DATABASE ABSTRACTION (PostgreSQL)
# ==============================================================================

_db_ready_cache: Dict[int, bool] = {}


async def _ensure_db_ready() -> None:
    """
    Best-effort, idempotent initialization for the DB backend.

    Some call sites (identity continuity + session persistence) may execute even if
    server initialization was skipped or partially failed. Without init(), Postgres
    operations can crash (e.g., self._pool is None).
    """
    try:
        db = get_db()
        key = id(db)
        if _db_ready_cache.get(key):
            return
        if hasattr(db, "init"):
            await db.init()  # expected to be idempotent
        _db_ready_cache[key] = True
    except Exception as e:
        # Non-fatal: callers will fall back to safer paths.
        logger.debug(f"DB init skipped/failed in _ensure_db_ready: {e}")


async def _persist_session_new(
    session_key: str,
    agent_id: str,
    api_key: str,
    created_at: str
) -> bool:
    """Persist session to Redis cache + PostgreSQL. Returns True on success."""
    # FAST PATH: Write to Redis cache first (survives server restarts)
    cache = _get_session_cache()
    if cache:
        try:
            api_key_hash = hashlib.sha256(api_key.encode()).hexdigest() if api_key else ""
            await cache.bind(session_key, agent_id, api_key_hash=api_key_hash)
            logger.debug(f"Session cached in Redis: {session_key} -> {agent_id[:8]}...")
        except Exception as e:
            logger.debug(f"Redis cache write failed (continuing to PostgreSQL): {e}")

    # DURABLE PATH: Also persist to PostgreSQL for long-term storage
    try:
        await _ensure_db_ready()
        db = get_db()

        # IMPORTANT (Postgres FK): core.identities.agent_id REFERENCES core.agents(id)
        # Ensure agent exists before inserting identity to avoid FK violations.
        if hasattr(db, "upsert_agent"):
            try:
                await db.upsert_agent(
                    agent_id=agent_id,
                    api_key=api_key or "",
                    status="active",
                )
            except Exception as e:
                logger.debug(f"Could not upsert agent before upsert_identity (continuing): {e}")

        # Then ensure identity exists
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
    """Load session from Redis cache (fast) or PostgreSQL (durable). Returns None if not found."""
    # FAST PATH: Check Redis cache first
    cache = _get_session_cache()
    if cache:
        try:
            cached = await cache.get(session_key)
            if cached:
                agent_id = cached.get("agent_id")
                if agent_id:
                    logger.debug(f"Session loaded from Redis: {session_key} -> {agent_id[:8]}...")
                    return {
                        "bound_agent_id": agent_id,
                        "api_key": None,  # Don't return plaintext key
                        "bound_at": cached.get("bound_at"),
                        "bind_count": cached.get("bind_count", 1),
                    }
        except Exception as e:
            logger.debug(f"Redis cache read failed (falling back to PostgreSQL): {e}")

    # DURABLE PATH: Fall back to PostgreSQL
    try:
        await _ensure_db_ready()
        db = get_db()
        session = await db.get_session(session_key)

        if session:
            result = {
                "bound_agent_id": session.agent_id,
                "api_key": None,  # Don't return plaintext key
                "bound_at": session.created_at.isoformat(),
                "bind_count": 1,  # Legacy field, not tracked in new schema
            }
            # Warm Redis cache for future lookups
            if cache:
                try:
                    await cache.bind(session_key, session.agent_id)
                except Exception:
                    pass
            return result
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

# O(1) lookup index: uuid_prefix (12 chars) -> full UUID
# Populated when identity() registers a stable session binding
# Enables fast lookup without scanning agent_metadata
_uuid_prefix_index: Dict[str, str] = {}


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


def _get_session_key(arguments: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> str:
    """
    Resolve the session key used for identity binding.

    Precedence:
    1) explicit session_id argument
    2) arguments["client_session_id"] (injected by SSE wrappers)
    3) contextvars session_key (set at dispatch entry - NEW!)
    4) fallback to a stable per-process key (stdio/single-user)

    Note: For stdio/single-user (Claude Desktop), a per-process key is stable and sufficient.
    The fallback is intentionally stable (no timestamp) to enable binding persistence across calls.
    """
    if session_id:
        logger.info(f"_get_session_key: using explicit session_id={session_id}")
        return str(session_id)
    if arguments and arguments.get("client_session_id"):
        logger.info(f"_get_session_key: using client_session_id={arguments['client_session_id']}")
        return str(arguments["client_session_id"])

    # NEW: Check contextvars for session key (set at SSE dispatch entry)
    # This enables success_response() and status() to find binding without arguments
    from .context import get_context_session_key
    context_key = get_context_session_key()
    if context_key:
        logger.info(f"_get_session_key: using context session_key={context_key}")
        return str(context_key)

    # STABLE FALLBACK: Use only PID (no timestamp) for single-user scenarios
    # This ensures binding persists across tool calls in Claude Desktop
    fallback = f"stdio:{os.getpid()}"
    logger.info(f"_get_session_key: using fallback={fallback}")
    return fallback


def _extract_ip_from_session_key(session_key: str) -> Optional[str]:
    """Extract IP address from session key (format: IP:PORT:HASH or IP:PORT)."""
    if not session_key:
        return None
    parts = session_key.split(":")
    if len(parts) >= 2:
        # Validate it looks like an IP
        ip_part = parts[0]
        if ip_part.count(".") == 3 or ip_part == "localhost":
            return ip_part
    return None


def _find_recent_binding_via_metadata(current_session_key: str) -> Optional[Dict[str, Any]]:
    """
    Find a recent identity binding by checking agent metadata for active_session_key.

    This handles the case where SSE connections create new session IDs for each request,
    causing bindings to become orphaned on dead sessions.

    For localhost/127.0.0.1, also matches by IP address to support curl/REST clients
    where each request gets a different TCP port.

    Returns:
        Identity record if found, None otherwise
    """
    try:
        from datetime import timedelta
        # Configurable lookback window (seconds). Default keeps prior behavior (~5 minutes).
        # You can extend for continuity across restarts, but longer windows increase the
        # chance of resurrecting stale bindings in shared environments.
        lookback_seconds = int(os.getenv("GOVERNANCE_IDENTITY_METADATA_LOOKBACK_SECONDS", "300"))

        # Extract IP from current session key for fallback matching
        current_ip = _extract_ip_from_session_key(current_session_key)
        is_localhost = current_ip in ("127.0.0.1", "localhost", "::1")

        # Check all agent metadata for recent bindings
        now = datetime.now(timezone.utc)
        cutoff_time = now - timedelta(seconds=max(0, lookback_seconds))

        # First pass: exact match or IP-based match for localhost
        best_match = None
        best_match_time = None

        for agent_id, meta in mcp_server.agent_metadata.items():
            # Only consider UUID-style agents
            is_uuid = len(agent_id) == 36 and agent_id.count('-') == 4
            if not is_uuid:
                continue

            # Check if this agent has a recent active_session_key
            if not hasattr(meta, 'active_session_key') or not meta.active_session_key:
                continue

            # Skip if it's the current session (already checked)
            if meta.active_session_key == current_session_key:
                continue

            # Check IP-based matching
            meta_ip = _extract_ip_from_session_key(meta.active_session_key)

            # DISABLED for localhost: IP-based matching causes identity confusion
            # when switching between multiple tools (Claude Code, Cursor, etc.).
            # Each tool should get its own identity. Use X-Agent-Id header to resume.
            if is_localhost:
                continue  # Skip all IP-based matching for localhost

            # For remote IPs: require exact IP match (one user per remote IP)
            if meta_ip != current_ip:
                continue

            # Check if binding is recent
            bound_dt = None
            if hasattr(meta, 'session_bound_at') and meta.session_bound_at:
                try:
                    bound_dt = datetime.fromisoformat(meta.session_bound_at)
                    # FIX: Naive timestamps are LOCAL time (from datetime.now()), not UTC
                    # Convert to UTC-aware by treating as local timezone
                    if bound_dt.tzinfo is None:
                        # Assume naive timestamps are local time, make cutoff also local for comparison
                        from datetime import timedelta
                        cutoff_local = datetime.now() - timedelta(seconds=max(0, lookback_seconds))
                        if bound_dt < cutoff_local:
                            continue  # Too old
                    else:
                        # Timezone-aware timestamp - compare in UTC
                        if bound_dt < cutoff_time:
                            continue  # Too old
                except Exception:
                    continue
            else:
                continue  # No timestamp, skip

            # NOTE: Accept agents with either api_key OR agent_uuid (UUID replaces API key as auth)
            has_auth = meta.api_key or hasattr(meta, 'agent_uuid')
            if has_auth:
                logger.debug(f"IP match candidate: {agent_id[:8]}... from {meta_ip}")
                if best_match is None:
                    best_match = {
                        "bound_agent_id": agent_id,
                        "api_key": meta.api_key,
                        "bound_at": meta.session_bound_at,
                        "bind_count": 1,
                        "_meta": meta,
                    }
                    best_match_time = bound_dt
                else:
                    # Multiple matches for same remote IP - keep most recent
                    # (Localhost is excluded above, so this only applies to remote IPs)
                    if bound_dt and (best_match_time is None or bound_dt > best_match_time):
                        best_match = {
                            "bound_agent_id": agent_id,
                            "api_key": meta.api_key,
                            "bound_at": meta.session_bound_at,
                            "bind_count": 1,
                            "_meta": meta,
                        }
                        best_match_time = bound_dt

        if best_match:
            agent_id = best_match["bound_agent_id"]
            logger.info(f"Found remote IP binding {agent_id[:8]}... via {current_ip}, migrating to {current_session_key}")
            # Update the metadata to point to current session
            meta = best_match.pop("_meta", None)
            if meta:
                meta.active_session_key = current_session_key
                _try_schedule_metadata_save()
            return best_match

    except Exception as e:
        logger.warning(f"Error finding binding via metadata: {e}", exc_info=True)

    return None


async def _find_recent_identity_from_db_async() -> Optional[Dict[str, Any]]:
    """
    Async version: Find the most recently active identity from the database.

    This is a fallback for when metadata-based lookup fails (e.g., after server restart).
    Only returns an identity if there's exactly ONE recently active identity to avoid
    binding to the wrong agent in multi-user scenarios.

    Returns:
        Identity record dict if found, None otherwise
    """
    try:
        from datetime import timedelta

        await _ensure_db_ready()
        db = get_db()

        # Opt-in: DB auto-resume can be surprising in multi-user/shared environments.
        # Keep default off; enable with GOVENANCE_IDENTITY_AUTO_RESUME_DB=1.
        if os.getenv("GOVERNANCE_IDENTITY_AUTO_RESUME_DB", "0").strip().lower() not in ("1", "true", "yes", "on"):
            return None

        # Look for sessions active in the last 7 days
        # Use timezone-aware datetime to match PostgreSQL TIMESTAMPTZ
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        # Get recent sessions from the new DB
        sessions = await db.list_identities(status="active", limit=10)

        if not sessions:
            return None

        # Filter to recently active (have agent_state or session records)
        recent_agents = []
        for identity in sessions:
            # Check if this identity has recent activity
            states = await db.get_agent_state_history(identity.identity_id, limit=1)
            if states:
                recorded_at = states[0].recorded_at
                # Normalize naive timestamps to UTC for safe comparison (SQLite backend may be naive)
                if isinstance(recorded_at, datetime) and recorded_at.tzinfo is None:
                    recorded_at = recorded_at.replace(tzinfo=timezone.utc)
                if isinstance(recorded_at, datetime) and recorded_at > cutoff:
                    recent_agents.append(identity)

        # Only auto-bind if there's exactly ONE recently active identity
        # This prevents accidentally binding to wrong agent in multi-user scenarios
        if len(recent_agents) == 1:
            identity = recent_agents[0]
            logger.info(f"Auto-resuming most recent identity from DB: {identity.agent_id}")
            return {
                "bound_agent_id": identity.agent_id,
                "api_key": None,  # Don't expose API key
                "bound_at": datetime.now().isoformat(),
                "bind_count": 1,
                "auto_resumed": True,  # Flag for audit
            }
        elif len(recent_agents) > 1:
            logger.debug(f"Multiple recent identities found ({len(recent_agents)}), not auto-binding")

        return None

    except Exception as e:
        logger.debug(f"Error finding identity from DB: {e}")
        return None


async def _get_identity_record_async(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Async version: Get or create the identity record for a session.

    PERSISTENCE: Now loads from SQLite if not in memory cache.
    This enables identity binding to persist across server restarts and HTTP requests.

    SSE RECONNECTION FIX: If no binding found for current session, attempts to find
    a recent binding via agent metadata (handles ephemeral SSE connections).

    CONTINUITY ENHANCEMENT: Tries PostgreSQL as last resort after server restart.
    """
    key = _get_session_key(arguments=arguments, session_id=session_id)

    # DEBUG: Log resolved session key for tracing session continuity issues
    logger.debug(f"[SESSION_DEBUG] _get_identity_record_async: session_key={key}, arguments.client_session_id={arguments.get('client_session_id') if arguments else None}")

    # Check in-memory cache first
    if key in _session_identities:
        cached = _session_identities[key]
        cached_bound = cached.get("bound_agent_id")
        logger.debug(f"[SESSION_DEBUG] _get_identity_record_async: CACHE HIT for {key}, bound_agent_id={cached_bound[:8] + '...' if cached_bound else 'None'}")
        return cached

    # CACHE MISS: Try to find or create binding
    logger.debug(f"[SESSION_DEBUG] _get_identity_record_async: CACHE MISS for {key}")

    # SPECIAL CASE: agent-{uuid12} format session IDs
    # These are stable session IDs we return from identity() for session continuity.
    # Extract the UUID prefix and look up the agent directly.
    if key.startswith("agent-"):
        uuid_prefix = key[6:]  # Remove "agent-" prefix to get the 12-char UUID prefix
        logger.debug(f"[SESSION_DEBUG] agent- prefix detected, uuid_prefix={uuid_prefix}")

        # DEBUG: Log the current state of _uuid_prefix_index
        index_value = _uuid_prefix_index.get(uuid_prefix)
        logger.debug(f"[SESSION_DEBUG] _uuid_prefix_index[{uuid_prefix}] = {index_value[:8] + '...' if index_value else 'NOT FOUND'}")

        # O(1) LOOKUP: Check the prefix index first (fast path)
        full_uuid = _lookup_uuid_by_prefix(uuid_prefix)
        if full_uuid:
            logger.debug(f"[SESSION_DEBUG] O(1) index hit: {uuid_prefix} -> {full_uuid}")
            meta = mcp_server.agent_metadata.get(full_uuid)
            if meta:
                logger.debug(f"[SESSION_DEBUG] Metadata found for {full_uuid[:8]}..., returning binding")
                _session_identities[key] = {
                    "bound_agent_id": full_uuid,
                    "api_key": getattr(meta, 'api_key', None),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "bind_count": _session_identities.get(key, {}).get("bind_count", 0),
                }
                return _session_identities[key]
            else:
                logger.warning(f"[SESSION_DEBUG] UUID {full_uuid} in index but NOT in agent_metadata!")

        # FALLBACK: Scan agent metadata (for agents created before index existed)
        for agent_uuid, meta in mcp_server.agent_metadata.items():
            if agent_uuid.startswith(uuid_prefix):
                logger.info(f"[SESSION_CONTINUITY] Scan found agent {agent_uuid}, registering in index")
                # Register in index for future O(1) lookups
                _register_uuid_prefix(uuid_prefix, agent_uuid)
                _session_identities[key] = {
                    "bound_agent_id": agent_uuid,
                    "api_key": getattr(meta, 'api_key', None),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "bind_count": _session_identities.get(key, {}).get("bind_count", 0),
                }
                return _session_identities[key]

        # If no match found, this is an unknown session ID - don't auto-create
        logger.warning(f"[SESSION_CONTINUITY] No agent found for session key {key}")
        # Return empty binding but DON'T create new identity
        # The caller should handle this as "session not found"
        return {
            "bound_agent_id": None,
            "api_key": None,
            "bound_at": None,
            "bind_count": 0,
            "_session_key_type": "agent_prefix_not_found",
        }

    # PRIMARY: Try PostgreSQL session lookup
    persisted = await _load_session_new(key)
    if persisted:
        _session_identities[key] = persisted
    else:
        # FALLBACK 1: Try to find binding via agent metadata
        # This handles the case where each SSE request gets a new session ID
        metadata_binding = _find_recent_binding_via_metadata(key)
        if metadata_binding:
            # Migrate binding to current session
            _session_identities[key] = metadata_binding.copy()
            # ... update agent metadata ...
        else:
            # FALLBACK 1b: If _find_recent_binding_via_metadata didn't find it (maybe session key format changed),
            # check for any UUID with recent activity and stdio session key
            if key.startswith("stdio:"):
                from datetime import timedelta
                lookback = timedelta(seconds=600)  # 10 minutes
                cutoff = datetime.now(timezone.utc) - lookback

                for agent_id, meta in mcp_server.agent_metadata.items():
                    is_uuid = len(agent_id) == 36 and agent_id.count('-') == 4
                    if not is_uuid:
                        continue

                    # Check if this agent has a stdio session key and recent activity
                    if (hasattr(meta, 'active_session_key') and
                        meta.active_session_key and
                        meta.active_session_key.startswith("stdio:") and
                        hasattr(meta, 'session_bound_at') and
                        meta.session_bound_at):
                        try:
                            bound_dt = datetime.fromisoformat(meta.session_bound_at)
                            if bound_dt.tzinfo is None:
                                bound_dt = bound_dt.replace(tzinfo=timezone.utc)
                            if bound_dt >= cutoff:
                                # Found a recent stdio binding - migrate it
                                _session_identities[key] = {
                                    "bound_agent_id": agent_id,
                                    "api_key": getattr(meta, 'api_key', None),
                                    "bound_at": meta.session_bound_at,
                                    "bind_count": 1,
                                }
                                meta.active_session_key = key
                                _try_schedule_metadata_save()
                                logger.info(f"Migrated stdio binding for {agent_id} to {key}")
                                break
                        except Exception:
                            continue
            else:
                # FALLBACK 2: Try recent identity from PostgreSQL (continuity after restart)
                db_binding = await _find_recent_identity_from_db_async()
                if db_binding:
                    _session_identities[key] = db_binding.copy()
                    logger.info(f"Auto-resumed identity from DB: {db_binding.get('bound_agent_id')}")
                else:
                    _session_identities[key] = {
                        "bound_agent_id": None,
                        "api_key": None,
                        "bound_at": None,
                        "bind_count": 0,  # Track rebinds for audit
                    }
    return _session_identities[key]


def _get_identity_record(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get or create the identity record for a session (synchronous version).

    NOTE: This is the synchronous version for utility functions. It only checks
    in-memory cache and agent metadata. For full PostgreSQL support, use
    _get_identity_record_async() which can query the database.
    """
    key = _get_session_key(arguments=arguments, session_id=session_id)

    # Check in-memory cache first
    if key not in _session_identities:
        # SPECIAL CASE: agent-{uuid12} format session IDs
        # These are stable session IDs we return from identity() for session continuity.
        if key.startswith("agent-"):
            uuid_prefix = key[6:]  # Remove "agent-" prefix
            logger.info(f"[SESSION_CONTINUITY_SYNC] Looking up agent with UUID prefix: {uuid_prefix}")

            # O(1) LOOKUP: Check the prefix index first (fast path)
            full_uuid = _lookup_uuid_by_prefix(uuid_prefix)
            if full_uuid:
                logger.info(f"[SESSION_CONTINUITY_SYNC] O(1) index hit: {uuid_prefix} -> {full_uuid[:8]}...")
                meta = mcp_server.agent_metadata.get(full_uuid)
                if meta:
                    _session_identities[key] = {
                        "bound_agent_id": full_uuid,
                        "api_key": getattr(meta, 'api_key', None),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "bind_count": 0,
                    }
                    return _session_identities[key]

            # FALLBACK: Scan agent metadata (for agents created before index existed)
            for agent_uuid, meta in mcp_server.agent_metadata.items():
                if agent_uuid.startswith(uuid_prefix):
                    logger.info(f"[SESSION_CONTINUITY_SYNC] Scan found agent {agent_uuid}, registering in index")
                    _register_uuid_prefix(uuid_prefix, agent_uuid)
                    _session_identities[key] = {
                        "bound_agent_id": agent_uuid,
                        "api_key": getattr(meta, 'api_key', None),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "bind_count": 0,
                    }
                    return _session_identities[key]

            # No match - return empty binding (don't auto-create)
            # Note: PostgreSQL is now the sole backend, so SQLite fallback removed
            logger.warning(f"[SESSION_CONTINUITY_SYNC] No agent found for {key}")
            return {
                "bound_agent_id": None,
                "api_key": None,
                "bound_at": None,
                "bind_count": 0,
                "_session_key_type": "agent_prefix_not_found",
            }

        # FALLBACK: Try to find binding via agent metadata
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
                # Trigger save (loop-safe: may be called from sync contexts)
                _try_schedule_metadata_save()
            logger.info(f"Migrated binding for {agent_id} from orphaned session to {key}")
        else:
            # Sync version does not query PostgreSQL - use async version for full support
            _session_identities[key] = {
                "bound_agent_id": None,
                "api_key": None,
                "bound_at": None,
                "bind_count": 0,
            }
    return _session_identities[key]


def _try_schedule_metadata_save(force: bool = False) -> None:
    """
    DEPRECATED: No-op function. PostgreSQL is now the single source of truth.

    This function was used to persist metadata to SQLite/JSON.
    As of v2.4.0, all persistence goes through agent_storage module to PostgreSQL.
    Keeping this function as a no-op for backwards compatibility with callers.
    """
    pass  # No-op - PostgreSQL writes happen directly via agent_storage


# Export functions for use in other modules
__all__ = [
    'get_bound_agent_id',
    'is_session_bound',
    '_get_session_key',
    '_session_identities',
    'make_client_session_id',  # Canonical session ID formatter (Dec 2025)
]


def get_bound_agent_id(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Get currently bound agent_id (if any) for this session.
    
    PRIORITY: Checks contextvars first (set at dispatch entry) for consistency
    across all tools in the same request. Falls back to identity record lookup.
    """
    # PRIORITY 0: Check contextvars (set at dispatch entry)
    # This ensures consistency across all tools in the same request
    try:
        from .context import get_context_agent_id
        context_agent_id = get_context_agent_id()
        if context_agent_id:
            logger.debug(f"get_bound_agent_id: using context agent_id={context_agent_id[:8]}...")
            return context_agent_id
    except Exception:
        pass
    
    # FALLBACK: Use identity record lookup
    rec = _get_identity_record(session_id=session_id, arguments=arguments)
    return rec.get("bound_agent_id")


def is_session_bound(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> bool:
    """Check if session has bound identity."""
    return get_bound_agent_id(session_id=session_id, arguments=arguments) is not None


async def get_or_create_session_identity(
    arguments: Optional[Dict[str, Any]] = None,
    label: Optional[str] = None,
    client_hint: Optional[str] = None,
    force_new: bool = False
) -> Tuple[str, str, bool]:
    """
    Get or create UUID-based identity for this session.

    This is the core identity function - UUID is authority, label is cosmetic.
    Auto-binds session to UUID on first call.

    Args:
        arguments: Tool arguments (contains client_session_id)
        label: Optional display name (defaults to auto-generated)
        client_hint: Optional client type hint (e.g., "chatgpt", "cursor")
                     Used for generating meaningful structured_id
        force_new: If True, ignore existing binding and create fresh identity

    Returns:
        (agent_uuid, agent_label, is_new) - uuid is authority, label is display name
    """
    import uuid as uuid_module
    from .shared import get_mcp_server

    mcp_server = get_mcp_server()
    session_key = _get_session_key(arguments=arguments)
    arguments = arguments or {}

    # If force_new, skip lookups and jump to creation
    if not force_new:
        # PRIORITY 0: Check injected agent_id first (matches success_response logic)
        # If agent_id is injected (e.g., X-Agent-Id header, client_session_id binding),
        # use it rather than creating a new identity. Prevents accidental spawning.
        injected_agent_id = arguments.get("agent_id")
        if injected_agent_id:
            # Check if it's in metadata (same as success_response)
            if injected_agent_id in mcp_server.agent_metadata:
                meta = mcp_server.agent_metadata[injected_agent_id]
                agent_uuid = getattr(meta, 'agent_uuid', None) or injected_agent_id
                agent_label = getattr(meta, 'label', None)
                if label and label != agent_label:
                    meta.label = label
                    _try_schedule_metadata_save(force=True)
                    agent_label = label
                logger.debug(f"Using injected agent_id: {injected_agent_id}")
                return agent_uuid, agent_label, False
            else:
                # Try label lookup
                for uuid_key, m in mcp_server.agent_metadata.items():
                    if getattr(m, 'label', None) == injected_agent_id:
                        agent_uuid = uuid_key
                        agent_label = injected_agent_id
                        if label and label != agent_label:
                            m.label = label
                            _try_schedule_metadata_save(force=True)
                            agent_label = label
                        logger.debug(f"Using injected agent_id via label match: {injected_agent_id}")
                        return agent_uuid, agent_label, False

        # PRIORITY 1: Check session binding
        rec = await _get_identity_record_async(arguments=arguments)
        bound_id = rec.get("bound_agent_id")

        # DEBUG: Log the binding result
        logger.debug(f"[SESSION_DEBUG] get_or_create_session_identity: _get_identity_record_async returned bound_id={bound_id[:8] + '...' if bound_id else 'None'}")

        if bound_id:
            # Check if bound_id is a UUID (new system) or agent_id (legacy)
            # UUIDs are 36 chars with dashes, agent_ids are typically shorter
            is_uuid = len(bound_id) == 36 and bound_id.count('-') == 4
            
            if is_uuid and bound_id in mcp_server.agent_metadata:
                # New system: bound_id is UUID
                meta = mcp_server.agent_metadata[bound_id]
                agent_uuid = bound_id
                agent_label = getattr(meta, 'label', None)
                
                # Update label if provided
                if label and label != agent_label:
                    meta.label = label
                    _try_schedule_metadata_save(force=True)
                    agent_label = label

                logger.debug(f"[SESSION_DEBUG] get_or_create_session_identity: returning UUID={agent_uuid}, label={agent_label}, is_new=False (from bound_id UUID path)")
                return agent_uuid, agent_label, False
            elif not is_uuid and bound_id in mcp_server.agent_metadata:
                # Legacy system: bound_id is agent_id, need to find/create UUID
                meta = mcp_server.agent_metadata[bound_id]
                agent_uuid = getattr(meta, 'agent_uuid', None)

                # Migrate legacy agents: add UUID if missing
                if not agent_uuid:
                    agent_uuid = str(uuid_module.uuid4())
                    meta.agent_uuid = agent_uuid
                    # Re-key metadata by UUID
                    mcp_server.agent_metadata[agent_uuid] = meta
                    if bound_id != agent_uuid:
                        del mcp_server.agent_metadata[bound_id]
                    _try_schedule_metadata_save(force=True)
                
                agent_label = getattr(meta, 'label', bound_id)  # Use label or fallback to bound_id
                
                # Update label if provided
                if label and label != agent_label:
                    meta.label = label
                    _try_schedule_metadata_save(force=True)
                    agent_label = label

                logger.debug(f"[SESSION_DEBUG] get_or_create_session_identity: returning UUID={agent_uuid}, label={agent_label}, is_new=False (from legacy agent_id path)")
                return agent_uuid, agent_label, False

    # New identity - create UUID and bind
    agent_uuid = str(uuid_module.uuid4())
    agent_label = label  # None until agent self-names (optional, not auto-generated)

    # Create agent metadata - use UUID as key (internal identity)
    from datetime import datetime

    # Get AgentMetadata class from mcp_server_std
    try:
        from src.mcp_server_std import AgentMetadata, get_or_create_metadata
    except ImportError:
        # Fallback for SSE server
        AgentMetadata = type(list(mcp_server.agent_metadata.values())[0]) if mcp_server.agent_metadata else None
        if not AgentMetadata:
            raise RuntimeError("Cannot determine AgentMetadata class")
        get_or_create_metadata = mcp_server.get_or_create_metadata

    now = datetime.now().isoformat()

    # Use UUID as the key for metadata (internal identity)
    # Label is stored separately and can be None
    meta = get_or_create_metadata(agent_uuid)
    meta.agent_uuid = agent_uuid
    meta.label = agent_label  # Optional display name

    # Generate structured_id (three-tier identity model v2.5.0+)
    # Format: {interface}_{date} e.g., "cursor_20251226"
    try:
        from .naming_helpers import detect_interface_context, generate_structured_id
        from .context import get_context_client_hint
        context = detect_interface_context()

        # Collect existing structured IDs for collision detection
        existing_ids = [
            getattr(m, 'structured_id', None)
            for m in mcp_server.agent_metadata.values()
            if getattr(m, 'structured_id', None)
        ]
        # Use client_hint from: 1) argument, 2) session context, 3) auto-detect
        effective_client_hint = client_hint or get_context_client_hint()
        meta.structured_id = generate_structured_id(
            context=context,
            existing_ids=existing_ids,
            client_hint=effective_client_hint
        )
        logger.info(f"Generated structured_id: {meta.structured_id} (client_hint={effective_client_hint})")
    except Exception as e:
        logger.warning(f"Could not generate structured_id: {e}")
        meta.structured_id = None

    meta.status = "active"
    meta.created_at = now
    meta.last_update = now
    # IMPORTANT: Set session binding on metadata for IP-based lookup to work
    meta.active_session_key = session_key
    meta.session_bound_at = now

    # Bind session to this identity (by UUID)
    await _persist_session_new(
        session_key=session_key,
        agent_id=agent_uuid,  # Key by UUID
        api_key="",  # No API keys for auto-generated identities
        created_at=now
    )

    # Update in-memory binding (use _session_identities, not _SESSION_BINDINGS)
    identity_rec = await _get_identity_record_async(arguments=arguments)
    identity_rec["bound_agent_id"] = agent_uuid  # Bind by UUID
    identity_rec["agent_uuid"] = agent_uuid
    identity_rec["bound_at"] = now
    identity_rec["api_key"] = None

    _try_schedule_metadata_save(force=True)
    logger.info(f"Created new identity: {agent_uuid[:8]}... (label: {agent_label or 'unnamed'})")

    logger.debug(f"[SESSION_DEBUG] get_or_create_session_identity: returning NEW UUID={agent_uuid}, label={agent_label}, is_new=True")
    return agent_uuid, agent_label, True


def require_write_permission(arguments: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[TextContent]]:
    """
    Check if writes are allowed (bound=true).
    
    Rules:
    - Writes are allowed only when bound=true
    - Read-only operations work even when unbound
    
    Returns:
        (allowed, error_response) - allowed is True if writes are permitted
    """
    if not is_session_bound(arguments=arguments):
        return False, error_response(
            "Write operations require session binding",
            details={"error_type": "write_requires_binding"},
            recovery={
                "action": "Call any tool (e.g. process_agent_update) to auto-bind identity",
                "note": "Read-only operations work without binding, but writes require bound=true"
            }
        )
    return True, None


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
    
    # Check in-memory sessions (single-process check)
    for session_key, identity_rec in _session_identities.items():
        if identity_rec.get("bound_agent_id") == agent_id:
            if session_key != current_session_key:
                # Check if binding is recent (within last 2 minutes = likely still active)
                bound_at = identity_rec.get("bound_at")
                if bound_at:
                    try:
                        bound_dt = datetime.fromisoformat(bound_at)
                        if datetime.now() - bound_dt < timedelta(minutes=2):
                            # Session is still considered active
                            return f"session_{hash(session_key) % 10000}"
                    except Exception:
                        pass

    return None


# ==============================================================================
# SHARED HELPERS
# ==============================================================================

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


# ==============================================================================
# HANDLERS
# ==============================================================================

# NOTE: bind_identity, recall_identity, hello removed (Dec 2025)
# - Identity now auto-creates on first tool call
# - Use identity() to check identity and optionally name yourself
# - UUID replaces API key as auth mechanism


# ==============================================================================
# HELPERS (used by other modules - must keep)
# ==============================================================================

def _get_lineage_depth(agent_id: str) -> int:
    """Get depth in lineage tree (0 = no parent)."""
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
    
    lineage.reverse()
    return lineage


async def _schedule_metadata_save(force: bool = False):
    """
    DEPRECATED: No-op function. PostgreSQL is now the single source of truth.

    As of v2.4.0, all persistence goes through agent_storage module to PostgreSQL.
    """
    pass  # No-op - PostgreSQL writes happen directly via agent_storage


# ==============================================================================
# STATUS - The primary identity tool (LEGACY - v2 adapter in identity_v2.py)
# ==============================================================================

# NOTE: @mcp_tool decorator moved to identity_v2.py (handle_identity_adapter)
# This function is kept for backwards compatibility but no longer auto-registered.
# @mcp_tool("identity", timeout=10.0)  # DISABLED - use identity_v2.handle_identity_adapter
async def handle_identity(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    🪞 IDENTITY - Who am I? Auto-creates identity if first call.

    Optional: Pass name='...' to name yourself.
    agent_uuid = auth (replaces API key), agent_id = your name (you choose).

    Returns:
    - bound: bool - session linked
    - agent_uuid: str - your UUID (auth mechanism)
    - agent_id: str | null - your self-chosen name
    - is_new: bool - true if identity was just created
    """
    # DEBUG: Log raw arguments keys to detect MCP boundary stripping
    logger.debug(f"[SESSION_DEBUG] identity() entry: args_keys={list(arguments.keys()) if arguments else []}")

    # === KWARGS UNWRAPPING ===
    # MCP clients may send arguments wrapped as:
    #   {"kwargs": "{\"name\": \"...\"}"}  (string - needs JSON parsing)
    #   OR {"kwargs": {"name": "..."}}     (dict - already parsed by MCP library)
    # Unwrap to expected flat dict format.
    if "kwargs" in arguments:
        kwargs_val = arguments["kwargs"]
        logger.info(f"[KWARGS] Unwrapping: type={type(kwargs_val).__name__}, keys={list(kwargs_val.keys()) if isinstance(kwargs_val, dict) else 'N/A'}")

        if isinstance(kwargs_val, str):
            # Case 1: JSON string - parse it
            try:
                import json
                kwargs_parsed = json.loads(kwargs_val)
                if isinstance(kwargs_parsed, dict):
                    del arguments["kwargs"]
                    arguments.update(kwargs_parsed)
                    logger.info(f"[KWARGS] Unwrapped from string: {list(kwargs_parsed.keys())}")
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"[KWARGS] Failed to parse string: {e}")
        elif isinstance(kwargs_val, dict):
            # Case 2: Already a dict (MCP library pre-parsed) - just merge
            del arguments["kwargs"]
            arguments.update(kwargs_val)
            logger.info(f"[KWARGS] Unwrapped from dict: {list(kwargs_val.keys())}")

    mcp_server = get_mcp_server()
    # CRITICAL: Use comprehensive lookup strategy matching success_response()
    # The key insight: success_response() finds bindings by checking metadata directly
    bound_uuid = None

    # Method -1: Match success_response() logic EXACTLY
    # success_response() uses: bound_id = agent_id or get_bound_agent_id(arguments)
    # If agent_id is injected (e.g., X-Agent-Id header, client_session_id), use it
    injected_agent_id = arguments.get("agent_id")
    if injected_agent_id:
        # Check if it's in metadata (same as success_response)
        if injected_agent_id in mcp_server.agent_metadata:
            bound_uuid = injected_agent_id
            logger.debug(f"Found binding via injected agent_id: {bound_uuid}")
        else:
            # Try label lookup (same as success_response)
            for uuid_key, m in mcp_server.agent_metadata.items():
                if getattr(m, 'label', None) == injected_agent_id:
                    bound_uuid = uuid_key
                    logger.debug(f"Found binding via label match: {bound_uuid}")
                    break

    # Method 0: Pre-compute most recent UUID for fallback (only if no binding yet)
    # Find UUID with most recent last_update (regardless of time)
    most_recent_uuid = None
    most_recent_time = None
    for agent_id, meta in mcp_server.agent_metadata.items():
        is_uuid = len(agent_id) == 36 and agent_id.count('-') == 4
        if not is_uuid:
            continue
        # Check last_update - try to parse, but don't fail if it doesn't work
        if hasattr(meta, 'last_update') and meta.last_update:
            try:
                update_str = str(meta.last_update)
                # Normalize timezone indicators
                if update_str.endswith('Z'):
                    update_str = update_str[:-1] + '+00:00'
                elif '+' not in update_str and '-' in update_str.split('T')[0]:
                    # Has date but no timezone
                    if 'T' in update_str:
                        update_str = update_str + '+00:00'
                
                update_dt = datetime.fromisoformat(update_str)
                if update_dt.tzinfo is None:
                    update_dt = update_dt.replace(tzinfo=timezone.utc)
                
                if most_recent_time is None or update_dt > most_recent_time:
                    most_recent_uuid = agent_id
                    most_recent_time = update_dt
            except Exception as e:
                logger.debug(f"Could not parse last_update '{meta.last_update}' for {agent_id}: {e}")
                # If parsing fails but UUID exists and has last_update, still consider it
                if most_recent_uuid is None:
                    most_recent_uuid = agent_id
                    most_recent_time = datetime.now(timezone.utc)
        
        # Also collect UUIDs without last_update for fallback
        uuid_without_update = None
        if most_recent_uuid is None:
            for agent_id, meta in mcp_server.agent_metadata.items():
                is_uuid = len(agent_id) == 36 and agent_id.count('-') == 4
                if is_uuid:
                    uuid_without_update = agent_id
                    break
            if uuid_without_update:
                most_recent_uuid = uuid_without_update
                most_recent_time = datetime.now(timezone.utc)
    
    # Method 1: Try async lookup (checks PostgreSQL + metadata migration) - most reliable
    # This should find the binding via:
    # 1. PostgreSQL session lookup
    # 2. Metadata migration (_find_recent_binding_via_metadata)
    # 3. DB auto-resume (if enabled)
    if not bound_uuid:
        try:
            rec = await _get_identity_record_async(arguments=arguments)
            bound_uuid = rec.get("bound_agent_id")
            if bound_uuid:
                logger.debug(f"Found binding via async lookup: {bound_uuid}")
                # Cache is now populated, so sync lookup will also work
        except Exception as e:
            logger.warning(f"Async identity lookup failed: {e}", exc_info=True)
    
    # Method 2: Try sync lookup (in-memory cache - should work after async populates it)
    if not bound_uuid:
        bound_uuid = get_bound_agent_id(arguments=arguments)
        if bound_uuid:
            logger.debug(f"Found binding via sync lookup: {bound_uuid}")
    
    # Method 3: Check metadata by session key matching
    if not bound_uuid:
        session_key = _get_session_key(arguments=arguments)
        logger.debug(f"Checking metadata for session_key: {session_key}")
        
        # Check active_session_key match
        for agent_id, meta in mcp_server.agent_metadata.items():
            if hasattr(meta, 'active_session_key') and meta.active_session_key == session_key:
                bound_uuid = agent_id
                logger.debug(f"Found binding via active_session_key match: {bound_uuid}")
                break
    
    # Method 4: Use _find_recent_binding_via_metadata (same logic used elsewhere)
    if not bound_uuid:
        session_key = _get_session_key(arguments=arguments)
        metadata_binding = _find_recent_binding_via_metadata(session_key)
        if metadata_binding:
            bound_uuid = metadata_binding.get("bound_agent_id")
            if bound_uuid:
                logger.debug(f"Found binding via _find_recent_binding_via_metadata: {bound_uuid}")
                # Update in-memory cache
                _session_identities[session_key] = metadata_binding.copy()
    
    # No more "most recent UUID" fallbacks - using recency to guess identity is wrong because:
    # 1. Recent doesn't mean "current session"
    # 2. There could be multiple agents active
    # 3. We should match by session key, not by recency
    # If proper session binding mechanisms (PostgreSQL, metadata migration) didn't find it,
    # we're truly unbound and the agent needs to call a tool to auto-create identity
    
    # Determine bound status: If we found a UUID and it has metadata, we're bound
    # This matches success_response() logic - bound = metadata exists for UUID
    is_bound = False
    if bound_uuid:
        # Check if this UUID has metadata (same check as success_response)
        if bound_uuid in mcp_server.agent_metadata:
            is_bound = True
        else:
            # UUID found but no metadata - might be stale binding
            logger.debug(f"UUID {bound_uuid} found but no metadata - treating as unbound")
            bound_uuid = None
    
    name_updated = False
    chosen_name = None

    # Check if agent wants to self-name
    # ONLY use "name" parameter - do NOT use agent_id fallback because other parts of the
    # system inject agent_id (e.g., REST handler X-Agent-Id header, session binding).
    # Using agent_id here would incorrectly treat injected UUIDs as name change requests.
    new_name = arguments.get("name")
    if new_name and isinstance(new_name, str) and new_name.strip():
        if bound_uuid:
            try:
                meta = mcp_server.agent_metadata.get(bound_uuid)
                if meta:
                    chosen_name = new_name.strip()

                    # Check uniqueness - if name taken, auto-suffix with UUID
                    existing_names = {
                        getattr(m, 'label', None)
                        for aid, m in mcp_server.agent_metadata.items()
                        if aid != bound_uuid and getattr(m, 'label', None)
                    }
                    if chosen_name in existing_names:
                        # Name taken - append UUID suffix for uniqueness
                        chosen_name = f"{chosen_name}_{bound_uuid[:8]}"
                        logger.info(f"Name '{new_name.strip()}' taken, using '{chosen_name}'")

                    meta.label = chosen_name
                    name_updated = True
                    logger.info(f"Agent {bound_uuid[:8]}... named → '{chosen_name}'")

                    # Persist the change
                    _try_schedule_metadata_save(force=True)
            except Exception as e:
                logger.warning(f"Failed to set name: {e}")
        else:
            # Not bound yet - auto-create identity, then set name
            try:
                bound_uuid, _, _ = await get_or_create_session_identity(
                    arguments=arguments,
                    label=new_name.strip()
                )
                is_bound = True
                is_new_identity = True
                chosen_name = new_name.strip()
                name_updated = True
                logger.info(f"Auto-created identity {bound_uuid[:8]}... with name '{chosen_name}'")
            except Exception as e:
                logger.error(f"Failed to auto-create identity: {e}")
                return error_response(f"Failed to create identity: {e}")

    # Auto-create identity if not bound
    is_new_identity = False
    if not bound_uuid or not is_bound:
        try:
            bound_uuid, _, is_new_identity = await get_or_create_session_identity(
                arguments=arguments,
                label=None  # No name yet
            )
            is_bound = True
            logger.info(f"Auto-created identity {bound_uuid[:8]}... (is_new={is_new_identity})")
        except Exception as e:
            logger.error(f"Failed to auto-create identity: {e}")
            return error_response(f"Failed to create identity: {e}")

    # Get metadata for bound agent
    meta = mcp_server.agent_metadata.get(bound_uuid)
    if not meta:
        return success_response({
            "bound": True,
            "agent_uuid": bound_uuid,
            "agent_id": None,
            "error": "Metadata not found for bound UUID"
        })

    # Build response
    current_label = getattr(meta, 'label', None)

    # Generate stable client_session_id for session continuity
    # This allows agents (especially in ChatGPT) to maintain identity across calls
    # by echoing this value back in all future tool calls
    session_key = _get_session_key(arguments=arguments)

    # Session ID logic:
    # Always return the stable agent-{uuid} format as the recommended session ID.
    # The SSE wrapper injects client_session_id with IP:PORT format for internal use,
    # but we tell agents to use the UUID-based format which is stable across connections.
    # Only echo back user-provided session IDs that start with "agent-" (our recommended format).
    provided_session_id = arguments.get("client_session_id") if arguments else None
    if provided_session_id and provided_session_id.startswith("agent-"):
        stable_session_id = provided_session_id  # Echo back user-adopted ID
    else:
        stable_session_id = make_client_session_id(bound_uuid)  # Use shared helper

    # CRITICAL: Register binding under the stable session ID so future calls can find it
    # This enables session continuity even when SSE injects different IP:PORT keys
    _session_identities[stable_session_id] = {
        "bound_agent_id": bound_uuid,
        "api_key": getattr(meta, 'api_key', None),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bind_count": _session_identities.get(stable_session_id, {}).get("bind_count", 0),
    }
    # Also register in O(1) prefix index for fast future lookups
    uuid_prefix = bound_uuid[:12]
    _register_uuid_prefix(uuid_prefix, bound_uuid)
    logger.info(f"Registered stable session binding: {stable_session_id} -> {bound_uuid[:8]}...")

    # CRITICAL (Dec 2025): Also cache in Redis so identity_v2 can find it
    # identity_v2 uses Redis as first lookup path, so we must register there too
    try:
        from .identity_v2 import _cache_session
        import asyncio
        asyncio.create_task(_cache_session(stable_session_id, bound_uuid))
        logger.debug(f"Redis cache: {stable_session_id} -> {bound_uuid[:8]}...")
    except Exception as e:
        logger.debug(f"Could not cache stable session in Redis: {e}")
    
    # CRITICAL: Update context with the bound agent_id and stable session ID
    # This ensures all subsequent tools in the same request see the binding
    try:
        from .context import update_context_agent_id, set_session_context
        update_context_agent_id(bound_uuid)
        # Also update session_key in context to use stable format
        from .context import get_session_context, reset_session_context, set_session_context
        ctx = get_session_context()
        if ctx:
            ctx['session_key'] = stable_session_id
            ctx['client_session_id'] = stable_session_id
            set_session_context(**ctx)
    except Exception as e:
        logger.debug(f"Could not update context after identity binding: {e}")

    # Get structured_id from metadata (three-tier identity model)
    structured_id = getattr(meta, 'structured_id', None)

    result = {
        "success": True,
        "bound": is_bound,  # Use the computed bound status
        "is_new": is_new_identity,  # True if identity was just created

        # Three-tier identity model (v2.5.0+)
        "uuid": bound_uuid,  # Immutable technical identifier (never changes)
        "agent_id": structured_id,  # Structured auto-generated ID (stable, format: interface_date)
        "display_name": current_label,  # Nickname (user-chosen via identity(name=...), can change)

        # Legacy fields for compatibility
        "agent_uuid": bound_uuid,
        "label": current_label,
        "name_updated": name_updated,
        "status": meta.status,
        "total_updates": meta.total_updates,
        "last_update": meta.last_update,
        # SESSION CONTINUITY: Include client_session_id for agents to echo back
        "client_session_id": stable_session_id,
    }

    # Add session continuity guidance block
    result["session_continuity"] = {
        "client_session_id": stable_session_id,
        "instruction": "Include client_session_id in ALL future tool calls to maintain identity",
        "example": f'{{"name": "process_agent_update", "arguments": {{"client_session_id": "{stable_session_id}", "response_text": "...", "complexity": 0.5}}}}'
    }

    # AGGRESSIVE LABEL RECOVERY: Never show "None" in messages
    # Try to get structured_id as fallback
    fallback_name = structured_id or f"{bound_uuid[:8]}..."
    display_name_for_message = current_label or fallback_name
    
    if name_updated:
        result["message"] = f"Name set to '{chosen_name}'. For session continuity, include client_session_id='{stable_session_id}' in all future calls."
    elif is_new_identity:
        result["message"] = f"Welcome. You are {display_name_for_message}. Use identity(name='...') to name yourself. IMPORTANT: Include client_session_id='{stable_session_id}' in all future calls."
    elif current_label:
        result["message"] = f"You are '{current_label}'. Session ID: {stable_session_id}"
    else:
        # Show structured_id or UUID prefix instead of "unnamed"
        result["message"] = f"You are {display_name_for_message}. Use identity(name='...') to set a display name. Session ID: {stable_session_id}"
        result["hint"] = "Convention: {purpose}_{interface}_{date} or {interface}_{model}_{date}"
        
        # Provide meaningful naming suggestions for unnamed agents
        try:
            from .naming_helpers import (
                detect_interface_context,
                generate_name_suggestions,
                format_naming_guidance
            )
            
            # Get existing names for collision detection
            existing_names = [
                getattr(m, 'label', None)
                for m in mcp_server.agent_metadata.values()
                if getattr(m, 'label', None)
            ]
            
            # Generate suggestions
            context = detect_interface_context()
            suggestions = generate_name_suggestions(
                context=context,
                existing_names=existing_names
            )
            
            # Format guidance
            naming_guidance = format_naming_guidance(
                suggestions=suggestions,
                current_uuid=bound_uuid
            )
            
            result["naming_guidance"] = naming_guidance
        except Exception as e:
            logger.debug(f"Could not generate naming suggestions: {e}")

    # IMPORTANT: Pass bound_uuid and arguments to ensure agent_signature matches result.agent_uuid
    # This prevents the "two UUIDs in one response" confusion
    return success_response(result, agent_id=bound_uuid, arguments=arguments)


# ==============================================================================
# ONBOARD - Single entry point portal tool
# ==============================================================================

# @mcp_tool("onboard", timeout=15.0)  # DISABLED - use identity_v2.handle_onboard_v2
async def handle_onboard(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    🚀 ONBOARD - Single entry point for new agents.

    This is THE portal tool. Call it first, get back everything you need:
    - Your identity (auto-created)
    - Ready-to-use templates for next calls
    - Client-specific guidance

    Returns a "toolcard" payload with next_calls array.
    """
    # DEBUG: Log entry
    logger.debug(f"[SESSION_DEBUG] onboard() entry: args_keys={list(arguments.keys()) if arguments else []}")

    # === KWARGS STRING UNWRAPPING ===
    # Some MCP clients (e.g., Claude Code) send arguments wrapped as:
    #   {"kwargs": "{\"name\": \"...\", \"client_session_id\": \"...\"}"}
    if arguments and "kwargs" in arguments and isinstance(arguments["kwargs"], str):
        try:
            import json
            kwargs_parsed = json.loads(arguments["kwargs"])
            if isinstance(kwargs_parsed, dict):
                del arguments["kwargs"]
                arguments.update(kwargs_parsed)
                logger.info(f"[KWARGS] Unwrapped: {list(kwargs_parsed.keys())}")
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[KWARGS] Failed to parse: {e}")

    mcp_server = get_mcp_server()
    arguments = arguments or {}

    # Extract optional parameters
    name = arguments.get("name")  # Optional: set display name
    client_hint = arguments.get("client_hint", "unknown")  # chatgpt, cursor, claude_desktop, unknown
    force_new = arguments.get("force_new", False)  # Force new identity creation

    # STEP 0: If force_new=true, clear any existing session binding
    # This allows agents to explicitly request a fresh identity
    if force_new:
        session_key = _get_session_key(arguments=arguments)
        logger.info(f"[ONBOARD] force_new=true, clearing session binding for {session_key}")

        # Clear in-memory binding
        if session_key in _session_identities:
            old_binding = _session_identities[session_key].get("bound_agent_id")
            logger.info(f"[ONBOARD] Clearing existing binding: {old_binding[:8] if old_binding else 'None'}...")
            del _session_identities[session_key]

        # Remove any injected agent_id so get_or_create_session_identity creates fresh
        arguments_for_create = {k: v for k, v in arguments.items() if k != "agent_id"}
    else:
        arguments_for_create = arguments

    # STEP 1: Get or create identity (same path as identity())
    try:
        agent_uuid, agent_label, is_new = await get_or_create_session_identity(
            arguments=arguments_for_create,
            label=name,
            client_hint=client_hint,  # For better auto-naming (e.g., "chatgpt_20251226")
            force_new=force_new
        )
    except Exception as e:
        logger.error(f"onboard() failed to create identity: {e}")
        return error_response(f"Failed to create identity: {e}")

    # STEP 2: Generate stable session ID using shared helper
    stable_session_id = make_client_session_id(agent_uuid)

    # STEP 3: Self-check - verify session ID resolves back to same UUID
    # This catches any drift between session ID generation and resolution
    try:
        # Simulate how future calls would resolve this session ID
        test_rec = await _get_identity_record_async(
            arguments={"client_session_id": stable_session_id}
        )
        resolved_uuid = test_rec.get("bound_agent_id")

        if resolved_uuid != agent_uuid:
            logger.error(
                f"[ONBOARD_SELF_CHECK_FAILED] Session ID {stable_session_id} resolved to "
                f"{resolved_uuid[:8] if resolved_uuid else 'None'}... but expected {agent_uuid[:8]}..."
            )
            # Don't fail - just warn. The identity was created, we just have a resolution bug.
            self_check_passed = False
            self_check_warning = f"Session resolution mismatch: expected {agent_uuid[:8]}..., got {resolved_uuid[:8] if resolved_uuid else 'None'}..."
        else:
            logger.info(f"[ONBOARD_SELF_CHECK_PASSED] {stable_session_id} -> {agent_uuid[:8]}...")
            self_check_passed = True
            self_check_warning = None
    except Exception as e:
        logger.warning(f"onboard() self-check error: {e}")
        self_check_passed = False
        self_check_warning = f"Self-check failed: {e}"

    # STEP 4: Register binding under BOTH stable session ID AND original session key
    # This ensures subsequent onboard() calls find the existing identity
    meta = mcp_server.agent_metadata.get(agent_uuid)
    binding_record = {
        "bound_agent_id": agent_uuid,
        "api_key": getattr(meta, 'api_key', None) if meta else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bind_count": 0,
    }
    _session_identities[stable_session_id] = binding_record

    # CRITICAL FIX (Dec 2025): Also register under ORIGINAL session key
    # Without this, subsequent onboard() calls create new identities
    original_session_key = _get_session_key(arguments=arguments)
    if original_session_key != stable_session_id:
        _session_identities[original_session_key] = binding_record
        logger.debug(f"Registered binding under both {stable_session_id} and {original_session_key}")

    # Register in O(1) prefix index
    uuid_prefix = agent_uuid[:12]
    _register_uuid_prefix(uuid_prefix, agent_uuid)

    # CRITICAL (Dec 2025): Also cache in Redis so identity_v2 can find it
    try:
        from .identity_v2 import _cache_session
        import asyncio
        asyncio.create_task(_cache_session(stable_session_id, agent_uuid))
        logger.debug(f"Redis cache (onboard): {stable_session_id} -> {agent_uuid[:8]}...")
    except Exception as e:
        logger.debug(f"Could not cache stable session in Redis: {e}")

    # STEP 5: Build toolcard payload
    # Templates use the stable session ID so agents can copy-paste
    next_calls = [
        {
            "tool": "process_agent_update",
            "why": "Log your work. Call after completing tasks.",
            "args_min": {
                "client_session_id": stable_session_id,
                "response_text": "...",
                "complexity": 0.5
            },
            "args_full": {
                "client_session_id": stable_session_id,
                "response_text": "Summary of what you did",
                "complexity": 0.5,
                "confidence": 0.8
            }
        },
        {
            "tool": "get_governance_metrics",
            "why": "Check your state (energy, coherence, etc.)",
            "args_min": {
                "client_session_id": stable_session_id
            },
            "args_full": {
                "client_session_id": stable_session_id
            }
        },
        {
            "tool": "identity",
            "why": "Rename yourself or check identity later",
            "args_min": {
                "client_session_id": stable_session_id
            },
            "args_full": {
                "client_session_id": stable_session_id,
                "name": "YourName_model_date"
            }
        }
    ]

    # Client-specific tips
    client_tips = {
        "chatgpt": "⚠️ ChatGPT loses session state. ALWAYS include client_session_id in every call.",
        "cursor": "Cursor maintains sessions well. client_session_id optional but recommended.",
        "claude_desktop": "Claude Desktop has stable sessions. client_session_id optional.",
        "unknown": "For best session continuity, include client_session_id in all tool calls."
    }

    # If force_new was used, ensure is_new reflects the fresh identity
    if force_new:
        is_new = True

    # ALWAYS get current label/structured_id from metadata (fixes stale data issue)
    # Priority: runtime cache → PostgreSQL → session binding fallback
    current_meta = mcp_server.agent_metadata.get(agent_uuid)
    display_name = None
    structured_id = None

    if current_meta:
        # Found in runtime cache - use it
        display_name = getattr(current_meta, 'label', None)
        structured_id = getattr(current_meta, 'structured_id', None)
    else:
        # Not in cache - try PostgreSQL for the latest label (async-safe)
        try:
            from src.db import get_db
            db = get_db()
            if hasattr(db, 'init'):
                await db.init()
            display_name = await db.get_agent_label(agent_uuid)
            logger.debug(f"Loaded label from PostgreSQL: {display_name}")
        except Exception as e:
            logger.debug(f"Could not load label from PostgreSQL: {e}")
            display_name = agent_label  # Final fallback to session binding

    # Differentiate welcome message based on new vs returning
    # AGGRESSIVE LABEL RECOVERY: Never show "None" - always use structured_id as fallback
    
    # 1. Ensure structured_id is never None (fallback for response)
    if not structured_id:
        structured_id = f"agent_{agent_uuid[:8]}"

    # 2. Determine friendly name for welcome message
    # Priority: display_name → structured_id
    friendly_name = display_name or structured_id
    
    # NEW SESSION HEURISTIC: Check for inactivity gap
    # If agent returns after > 5 mins, they might be in a new chat session
    # Suggest force_new=true to avoid identity conflation
    suggest_new = False
    gap_message = ""
    
    if not is_new and current_meta and current_meta.last_update:
        try:
            last_update_str = current_meta.last_update.replace('Z', '+00:00') if 'Z' in current_meta.last_update else current_meta.last_update
            last_update = datetime.fromisoformat(last_update_str)
            if last_update.tzinfo is None:
                last_update = last_update.replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            gap = (now - last_update).total_seconds() / 60.0  # minutes
            
            if gap > 5.0:
                suggest_new = True
                time_str = f"{int(gap)} minutes" if gap < 60 else f"{gap/60:.1f} hours"
                gap_message = (
                    f"\n\n🕒 It's been {time_str} since we last spoke. "
                    "If this is a new conversation, call onboard(force_new=true) to start fresh."
                )
        except Exception:
            pass

    if is_new:
        welcome = "🎉 Welcome! You're onboarded and ready to go."
        welcome_message = "This system monitors your work like a health monitor tracks your heart. It helps you stay on track, avoid getting stuck, and work more effectively. Your identity is created—use the templates below to get started."
    else:
        # Always show a friendly name (never "None")
        welcome = f"👋 Welcome back, {friendly_name}!" if friendly_name else "👋 Welcome back!"
        welcome_message = f"I found your existing identity. You're all set to continue where you left off.{gap_message}"

    result = {
        "success": True,
        "welcome": welcome,
        "welcome_message": welcome_message,
        "suggest_new_identity": suggest_new,

        # Three-tier identity model (v2.5.0+)
        "uuid": agent_uuid,  # Immutable technical identifier (never changes)
        "agent_id": structured_id,  # Structured auto-generated ID (stable, format: interface_date)
        "display_name": display_name,  # Nickname (user-chosen via identity(name=...), can change)

        # Legacy fields for compatibility
        "agent_uuid": agent_uuid,
        "label": display_name,
        "is_new": is_new,
        "force_new_applied": force_new,  # Indicates if force_new was requested

        # Session continuity - THE critical piece
        "client_session_id": stable_session_id,
        "session_continuity": {
            "client_session_id": stable_session_id,
            "instruction": "Include client_session_id in ALL future tool calls to maintain identity",
            "tip": client_tips.get(client_hint, client_tips["unknown"])
        },

        # The toolcard - ready-to-use templates
        "next_calls": next_calls,
    }

    # Only include verbose guidance for NEW agents
    if is_new or force_new:
        result.update({
            # Workflow guidance
            "workflow": {
                "step_1": "Copy client_session_id from above",
                "step_2": "Do your work",
                "step_3": "Call process_agent_update with response_text describing what you did",
                "loop": "Repeat steps 2-3. Check metrics with get_governance_metrics when curious."
            },
            # Value proposition - what this system does for you
            "what_this_does": {
                "problem": "AI systems drift, get stuck, and make unexplainable decisions. Traditional governance relies on rules that break as AI evolves.",
                "solution": "This system monitors your work in real-time using state-based dynamics (not rules). It tracks your health across four dimensions and automatically decides whether to proceed or pause.",
                "benefits": [
                    "Prevents problems before they happen (circuit breakers)",
                    "Helps you avoid getting stuck in loops",
                    "Provides feedback to improve your work",
                    "Scales automatically as your work evolves"
                ]
            },
            # Quick workflow reference (v2.5.0+) - progressive disclosure
            "common_workflows": {
                "check_in": "process_agent_update(response_text='...', complexity=0.5)",
                "save_insight": "leave_note(summary='...')",
                "find_info": "search_knowledge_graph(query='...')",
                "see_peers": "list_agents()"
            },
            # Type signatures for core tools
            "signatures": {
                "process_agent_update": "(complexity:float, response_text?:str, confidence?:float)",
                "leave_note": "(summary:str, tags?:list)",
                "search_knowledge_graph": "(query?:str, tags?:list, include_details?:bool)"
            },
            "explore_more": "list_tools() for all tools, describe_tool('tool_name') for details"
        })

    # Add self-check status (for debugging)
    if not self_check_passed:
        result["self_check_warning"] = self_check_warning
        result["self_check_passed"] = False
    else:
        result["self_check_passed"] = True

    # Add naming guidance if unnamed
    if not agent_label:
        result["naming_tip"] = f"You're unnamed. Call identity(name='YourName') to name yourself."
        result["naming_convention"] = "{name}_{model}_{date} or creative names welcome"

    logger.info(f"[ONBOARD] Agent {agent_uuid[:8]}... onboarded (is_new={is_new}, label={agent_label})")

    return success_response(result, agent_id=agent_uuid, arguments=arguments)
