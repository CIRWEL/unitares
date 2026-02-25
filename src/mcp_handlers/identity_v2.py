"""
Identity V2 - Simplified Session-to-UUID Resolution

Design principles:
1. ONE source of truth: PostgreSQL (core.agents + core.sessions)
2. ONE cache layer: Redis (for performance)
3. THREE paths only: Redis hit → PostgreSQL hit → Create new
4. LAZY CREATION: Don't persist until first real work (v2.4.1+)

Separates two concerns that were previously conflated:
- resolve_session_identity(): "Who am I?" (session → UUID)
- lookup_agent(): "Who is agent X?" (moved to get_agent_metadata)

Lazy creation (v2.4.1):
- resolve_session_identity(persist=False) returns UUID without PostgreSQL write
- ensure_agent_persisted() persists on first real work (process_agent_update)
- Prevents orphan agents from discovery/testing calls

Three-tier identity (v2.5.3):
- UUID: Immutable technical identifier, used for lookup/persistence (primary key)
- agent_id: Model+date format (e.g., "Claude_Opus_20251227") - system generated, useful for tracking
- display_name: User-chosen name (set via identity(name='...')), also aliased as 'label' in responses

UUID is ALWAYS the cached/stored value. agent_id provides model awareness.
Same UUID = same agent.
"""

from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import uuid
import hashlib
import os

from src.logging_utils import get_logger
from src.db import get_db
from .utils import success_response, error_response

# Import GovernanceConfig with fallback defaults
try:
    from config.governance_config import GovernanceConfig
except ImportError:
    # Fallback if config module not available
    class GovernanceConfig:
        SESSION_TTL_SECONDS = 86400  # 24 hours
        SESSION_TTL_HOURS = 24

logger = get_logger(__name__)

# =============================================================================
# CACHE LAYER (Redis)
# =============================================================================

_redis_cache = None

def _get_redis():
    """Lazy load Redis connection."""
    global _redis_cache
    if _redis_cache is None:
        try:
            from src.cache import get_session_cache
            _redis_cache = get_session_cache()
        except Exception as e:
            logger.debug(f"Redis not available: {e}")
            _redis_cache = False  # Mark as unavailable
    return _redis_cache if _redis_cache else None


# =============================================================================
# DATE CONTEXT HELPER
# =============================================================================

def _get_date_context() -> dict:
    """Generate date context for onboard response (replaces separate date-context MCP)."""
    now = datetime.now()
    from datetime import timezone
    utc_now = datetime.now(timezone.utc)
    return {
        "full": now.strftime('%B %d, %Y'),
        "short": now.strftime('%Y-%m-%d'),
        "compact": now.strftime('%Y%m%d'),
        "iso": now.isoformat(),
        "iso_utc": utc_now.isoformat().replace('+00:00', 'Z'),
        "year": now.strftime('%Y'),
        "month": now.strftime('%B'),
        "weekday": now.strftime('%A'),
    }


# =============================================================================
# AGENT ID GENERATION (model+date format)
# =============================================================================

def _generate_agent_id(model_type: Optional[str] = None, client_hint: Optional[str] = None) -> str:
    """
    Generate agent_id in model+client+date format.

    Priority:
    1. model_type (e.g., "claude-opus-4-5") → "Claude_Opus_4_5_20251227"
    2. client_hint (e.g., "cursor") → "cursor_20251227"
    3. fallback → "mcp_20251227"

    Args:
        model_type: Model identifier (e.g., "claude-opus-4-5", "gemini-pro")
        client_hint: Client identifier (e.g., "cursor", "vscode", "claude_desktop")

    Returns:
        Human-readable agent_id string
    """
    timestamp = datetime.now().strftime("%Y%m%d")

    if model_type:
        # Normalize and format model name
        model = model_type.strip()
        # Capitalize first letter of each word, replace separators with underscore
        model = model.replace("-", " ").replace(".", " ").replace("_", " ")
        model = "_".join(word.capitalize() for word in model.split())
        return f"{model}_{timestamp}"
    elif client_hint and client_hint not in ("unknown", ""):
        # Use client as fallback identifier
        client = client_hint.strip().lower().replace(" ", "_")
        return f"{client}_{timestamp}"
    else:
        return f"mcp_{timestamp}"


def _generate_auto_label(model_type: Optional[str] = None, client_hint: Optional[str] = None) -> Optional[str]:
    """
    Generate a stable, deterministic label from client signals.

    Unlike _generate_agent_id (which includes date), this produces a
    time-independent label so repeated sessions converge to one identity.

    Examples:
        ("claude-opus-4", "claude-code") → "claude-code-opus"
        ("claude-sonnet-4", None) → "sonnet"
        (None, "cursor") → "cursor"
        (None, None) → None (can't generate)
    """
    parts = []

    # Client type first (if meaningful)
    if client_hint and client_hint not in ("unknown", "", "mcp"):
        parts.append(client_hint.strip().lower().replace(" ", "-"))

    # Model family (extract short name, drop version numbers)
    if model_type:
        model = model_type.strip().lower()
        # Extract model family: "claude-opus-4-5" → "opus"
        for family in ["opus", "sonnet", "haiku"]:
            if family in model:
                parts.append(family)
                break
        else:
            # Non-Claude model: use full name
            parts.append(model.replace(" ", "-"))

    if not parts:
        return None

    return "-".join(parts)


async def _find_agent_by_id(agent_id: str) -> Optional[Dict[str, Any]]:
    """
    Find existing agent by agent_id.

    DEPRECATED (v2.5.2): This function is for backward compatibility only.
    New code should use UUID directly - the agent_id (model+date) is just
    a display label, not a lookup key.

    Checks both PostgreSQL and in-memory cache.

    Returns:
        Agent dict with agent_uuid, label etc. or None if not found
    """
    # Check PostgreSQL first
    try:
        db = get_db()
        if hasattr(db, "init"):
            await db.init()

        # Look up agent by ID
        agent = await db.get_agent(agent_id)
        if agent:
            # Get identity for UUID
            identity = await db.get_identity(agent_id)
            agent_uuid = None
            if identity and identity.metadata:
                agent_uuid = identity.metadata.get("agent_uuid")
            # Fallback: use agent_id as UUID if not stored separately
            if not agent_uuid:
                agent_uuid = agent_id

            display_name = getattr(agent, "label", None) or getattr(agent, "display_name", None)
            return {
                "agent_id": agent_id,
                "agent_uuid": agent_uuid,
                "display_name": display_name,
                "label": display_name,  # backward compat alias
                "status": getattr(agent, "status", "active"),
            }
    except Exception as e:
        logger.debug(f"PostgreSQL agent lookup failed for {agent_id}: {e}")

    # Check in-memory cache
    try:
        from .shared import get_mcp_server
        mcp_server = get_mcp_server()
        if agent_id in mcp_server.agent_metadata:
            meta = mcp_server.agent_metadata[agent_id]
            display_name = getattr(meta, "label", None)
            return {
                "agent_id": agent_id,
                "agent_uuid": getattr(meta, "agent_uuid", agent_id),
                "display_name": display_name,
                "label": display_name,  # backward compat alias
                "status": getattr(meta, "status", "active"),
            }
    except Exception as e:
        logger.debug(f"In-memory agent lookup failed for {agent_id}: {e}")

    return None


# =============================================================================
# CORE IDENTITY RESOLUTION (3 paths)
# =============================================================================

async def resolve_session_identity(

    session_key: str,

    persist: bool = False,

    model_type: Optional[str] = None,

    client_hint: Optional[str] = None,

    force_new: bool = False,

    agent_name: Optional[str] = None,

    trajectory_signature: Optional[dict] = None,

) -> Dict[str, Any]:

    """

    Resolve session to agent identity. Optionally creates new agent in PostgreSQL.



    This is the ONLY identity resolution function. All tools use this.



    Args:

        session_key: The session identifier (from SSE connection or stdio PID)

        persist: If True, create agent in PostgreSQL. If False (default),

                 return UUID without persisting (lazy creation).

        model_type: Model identifier (e.g., "claude-opus-4", "gemini"). Used to

                    generate agent_id in model+date format.

        client_hint: Client/interface hint (e.g., "cursor", "vscode"). Used in

                     agent_id generation.

        force_new: If True, ignore existing binding and create fresh identity.



    Returns:

        {

            "agent_id": str,        # The agent's ID (model+date format, e.g., "claude_20251227")

            "agent_uuid": str,      # Internal UUID (immutable)

            "label": str | None,    # Display name (if set)

            "created": bool,        # True if newly created this call

            "persisted": bool,      # True if agent exists in PostgreSQL

            "source": str,          # "redis" | "postgres" | "created" | "memory_only"

        }

    """

    if not session_key:
        raise ValueError("session_key is required")

    # SECURITY (Feb 2026): Validate and sanitize session_key to prevent injection attacks
    # Session keys should be reasonable length and contain only safe characters
    MAX_SESSION_KEY_LENGTH = 256
    if len(session_key) > MAX_SESSION_KEY_LENGTH:
        logger.warning(f"[SECURITY] Session key too long ({len(session_key)} chars), truncating")
        session_key = session_key[:MAX_SESSION_KEY_LENGTH]

    # Sanitize: Replace potentially dangerous characters
    # Allow: alphanumeric, dash, underscore, colon, dot, at-sign (for email-like IDs)
    import re
    if not re.match(r'^[\w\-.:@]+$', session_key):
        # Contains characters outside allowed set - sanitize
        original = session_key
        session_key = re.sub(r'[^\w\-.:@]', '_', session_key)
        logger.warning(f"[SECURITY] Session key sanitized: {original[:30]}... -> {session_key[:30]}...")

    # If force_new is requested, skip lookup paths and go straight to creation

    if not force_new:

        # PATH 1: Redis cache (fast path)

        # NOTE: As of v2.5.2, we always cache UUID (the true identity).

        # The model+date agent_id is just a display label in metadata.

        redis = _get_redis()

        if redis:

            try:

                cached = await redis.get(session_key)

                if cached and cached.get("agent_id"):

                    cached_id = cached["agent_id"]

                    # Detect format: UUID (correct) vs model+date (legacy, pre-v2.5.2)

                    is_uuid = len(cached_id) == 36 and cached_id.count("-") == 4

                    if is_uuid:

                        # Correct format: cached value is UUID

                        agent_uuid = cached_id

                        # First check if display_agent_id is in cache (v2.5.2+)

                        agent_id = cached.get("display_agent_id")

                        if not agent_id:

                            # Fall back to metadata lookup

                            agent_id = await _get_agent_id_from_metadata(agent_uuid) or agent_uuid

                    else:

                        # Legacy format (pre-v2.5.2): cached value was model+date

                        agent_id = cached_id

                        existing = await _find_agent_by_id(agent_id)

                        agent_uuid = existing.get("agent_uuid", agent_id) if existing else agent_id



                    # Check if persisted in PostgreSQL

                    persisted = await _agent_exists_in_postgres(agent_uuid)

                    # Fetch label

                    label = await _get_agent_label(agent_uuid) if persisted else None



                    # SLIDING TTL: Refresh Redis expiry on every hit (v2.5.5)

                    try:

                        from src.cache.redis_client import get_redis

                        raw_redis = await get_redis()

                        if raw_redis:
                            await raw_redis.expire(f"session:{session_key}", GovernanceConfig.SESSION_TTL_SECONDS)

                    except Exception:

                        pass



                    return {

                        "agent_id": agent_id,

                        "agent_uuid": agent_uuid,

                        "display_name": label,

                        "label": label,  # backward compat

                        "created": False,

                        "persisted": persisted,

                        "source": "redis",

                    }

            except Exception as e:
                # INFO level (v2.5.7): Redis lookup failures are recoverable but should be visible
                logger.info(f"Redis lookup failed for session {session_key[:20]}...: {e}")



        # PATH 2: PostgreSQL session lookup

        # NOTE: As of v2.5.2, sessions reference agents by UUID.

        try:

            db = get_db()

            if hasattr(db, "init"):

                await db.init()



            session = await db.get_session(session_key)

            if session and session.agent_id:

                stored_id = session.agent_id

                # Detect format: UUID (correct) vs model+date (legacy)

                is_uuid = len(stored_id) == 36 and stored_id.count("-") == 4

                if is_uuid:

                    agent_uuid = stored_id

                    # Fetch agent_id (model+date) from metadata

                    agent_id = await _get_agent_id_from_metadata(agent_uuid) or agent_uuid

                else:

                    # Legacy: stored value was model+date - phase out

                    agent_id = stored_id

                    existing = await _find_agent_by_id(agent_id)

                    agent_uuid = existing.get("agent_uuid", agent_id) if existing else agent_id



                label = await _get_agent_label(agent_uuid)



                # Warm Redis cache for next time (cache UUID + display agent_id)

                # This also resets the TTL to 24h (sliding window)

                await _cache_session(session_key, agent_uuid, display_agent_id=agent_id)



                # Update DB last_active (non-blocking best effort)

                try:

                    await db.update_session_activity(session_key)

                except Exception:

                    pass



                return {

                    "agent_id": agent_id,

                    "agent_uuid": agent_uuid,

                    "display_name": label,

                    "label": label,  # backward compat

                    "created": False,

                    "persisted": True,  # Found in PostgreSQL = persisted

                    "source": "postgres",

                }

        except Exception as e:

            logger.debug(f"PostgreSQL session lookup failed: {e}")



    # PATH 2.5: Name-based identity claim
    # If agent provides a name, try to resolve to existing identity by label.
    # This enables reconnection even when session keys rotate.
    if agent_name:
        name_result = await resolve_by_name_claim(
            agent_name, session_key, trajectory_signature
        )
        if name_result:
            return name_result

    # PATH 2.75: Auto-name from client signals (prevents ghost proliferation)
    # If no explicit agent_name was provided, generate a stable label from
    # model_type + client_hint and try to claim an existing identity.
    if not agent_name and (model_type or client_hint):
        auto_label = _generate_auto_label(model_type, client_hint)
        if auto_label:
            auto_result = await resolve_by_name_claim(
                auto_label, session_key, trajectory_signature
            )
            if auto_result:
                logger.info(f"[AUTO_NAME] Reused identity via auto-label '{auto_label}'")
                return auto_result

    # PATH 3: Create new agent

    # UUID is the true identity (for lookup/persistence)
    # agent_id is human-readable label (model+date format, for display)
    agent_uuid = str(uuid.uuid4())
    agent_id = _generate_agent_id(model_type, client_hint)
    # Auto-assign label from client signals to prevent future ghosts
    label = _generate_auto_label(model_type, client_hint) if not agent_name else None

    if persist:
        # Persist immediately to PostgreSQL
        try:
            db = get_db()

            # Create agent in PostgreSQL with UUID as key
            await db.upsert_agent(
                agent_id=agent_uuid,  # UUID is the primary key
                api_key="",  # Legacy field, not used
                status="active",
            )

            # Set auto-generated label so future sessions can claim this identity
            if label:
                await db.update_agent_fields(agent_uuid, label=label)
                logger.info(f"[AUTO_NAME] New agent '{label}' (uuid: {agent_uuid[:8]}...)")

            # Create identity record with agent_id (display name) in metadata
            await db.upsert_identity(
                agent_id=agent_uuid,
                api_key_hash="",
                metadata={
                    "source": "identity_v2",
                    "created_at": datetime.now().isoformat(),
                    "agent_id": agent_id,  # Human-readable label (model+date)
                    "model_type": model_type,
                    "total_updates": 0,  # Initialize counter for persistence
                }
            )

            # Create session binding
            identity = await db.get_identity(agent_uuid)
            if identity:
                await db.create_session(
                    session_id=session_key,
                    identity_id=identity.identity_id,
                    expires_at=datetime.now() + timedelta(hours=GovernanceConfig.SESSION_TTL_HOURS),
                    client_type="mcp",
                    client_info={"agent_uuid": agent_uuid, "agent_id": agent_id}
                )

            # Cache in Redis (session -> UUID + display agent_id)
            await _cache_session(session_key, agent_uuid, display_agent_id=agent_id)

            logger.info(f"Created new agent: {agent_id} (uuid: {agent_uuid[:8]}...)")

            return {
                "agent_id": agent_id,
                "agent_uuid": agent_uuid,
                "display_name": label,
                "label": label,
                "created": True,
                "persisted": True,
                "source": "created",
            }

        except Exception as e:
            logger.warning(f"Failed to persist new agent: {e}")
            # Fall through to memory-only path

    # Lazy creation: just cache in Redis, don't write to PostgreSQL
    # Cache UUID + display agent_id for retrieval on next call
    await _cache_session(session_key, agent_uuid, display_agent_id=agent_id)
    logger.debug(f"Created new agent (lazy): {agent_id} (uuid: {agent_uuid[:8]}...)")

    return {
        "agent_id": agent_id,
        "agent_uuid": agent_uuid,
        "display_name": None,
        "label": None,  # backward compat
        "created": True,
        "persisted": False,
        "source": "memory_only",
    }


async def set_agent_label(agent_uuid: str, label: str, session_key: Optional[str] = None) -> bool:
    """
    Set display name for an agent.

    This is a simple UPDATE, not identity resolution.
    Label uniqueness is NOT enforced - duplicates get UUID suffix.

    If agent is not yet persisted (lazy creation), this will persist it first.
    """
    if not agent_uuid or not label:
        return False

    try:
        # Ensure agent is persisted before setting label (lazy creation support)
        if session_key:
            await ensure_agent_persisted(agent_uuid, session_key)

        db = get_db()

        # Check for duplicate labels
        existing = await _find_agent_by_label(label)
        if existing and existing != agent_uuid:
            # Append UUID suffix to make unique
            label = f"{label}_{agent_uuid[:8]}"
            logger.info(f"Label collision, using: {label}")

        # Update agent label using the proper backend method
        success = await db.update_agent_fields(agent_uuid, label=label)

        if success:
            # Sync label to runtime cache so compute_agent_signature can find it
            try:
                from .shared import get_mcp_server
                mcp_server = get_mcp_server()
                if agent_uuid in mcp_server.agent_metadata:
                    meta = mcp_server.agent_metadata[agent_uuid]
                    meta.label = label

                    # Generate structured_id if missing (migration for pre-v2.5.0 agents)
                    if not getattr(meta, 'structured_id', None):
                        try:
                            from .naming_helpers import detect_interface_context, generate_structured_id
                            from .context import get_context_client_hint
                            context = detect_interface_context()
                            existing_ids = [
                                getattr(m, 'structured_id', None)
                                for m in mcp_server.agent_metadata.values()
                                if getattr(m, 'structured_id', None)
                            ]
                            meta.structured_id = generate_structured_id(
                                context=context,
                                existing_ids=existing_ids,
                                client_hint=get_context_client_hint()
                            )
                            logger.info(f"Migrated structured_id: {meta.structured_id}")
                        except Exception as e:
                            logger.debug(f"Could not generate structured_id: {e}")

                    logger.info(f"Synced label '{label}' to existing cache entry for {agent_uuid[:8]}")
                else:
                    # Agent not in cache yet - create proper AgentMetadata entry
                    # Import the real AgentMetadata class to avoid missing attribute errors
                    from src.mcp_server_std import AgentMetadata
                    from datetime import datetime
                    now = datetime.now().isoformat()
                    meta = AgentMetadata(
                        agent_id=agent_uuid,
                        status='active',
                        created_at=now,
                        last_update=now,
                    )
                    meta.label = label  # Set label after creation
                    meta.agent_uuid = agent_uuid  # Set UUID attribute

                    # Generate structured_id (three-tier identity model v2.5.0+)
                    try:
                        from .naming_helpers import detect_interface_context, generate_structured_id
                        from .context import get_context_client_hint
                        context = detect_interface_context()
                        existing_ids = [
                            getattr(m, 'structured_id', None)
                            for m in mcp_server.agent_metadata.values()
                            if getattr(m, 'structured_id', None)
                        ]
                        meta.structured_id = generate_structured_id(
                            context=context,
                            existing_ids=existing_ids,
                            client_hint=get_context_client_hint()
                        )
                        logger.info(f"Generated structured_id: {meta.structured_id}")
                    except Exception as e:
                        logger.debug(f"Could not generate structured_id: {e}")

                    mcp_server.agent_metadata[agent_uuid] = meta
                    logger.info(f"Created cache entry with label '{label}' for {agent_uuid[:8]}")

                # Also update session binding cache so get_or_create_session_identity returns correct label
                try:
                    from .identity_shared import _session_identities
                    for session_key, binding in _session_identities.items():
                        if binding.get("bound_agent_id") == agent_uuid or binding.get("agent_uuid") == agent_uuid:
                            binding["agent_label"] = label
                            logger.debug(f"Updated session binding label for {session_key}")
                except Exception as e:
                    logger.debug(f"Could not update session binding cache: {e}")
            except Exception as e:
                logger.warning(f"Runtime cache sync failed: {e}")

            # Invalidate any other cached data
            redis = _get_redis()
            if redis:
                try:
                    from src.cache import get_metadata_cache
                    await get_metadata_cache().invalidate(agent_uuid)
                except Exception:
                    pass

        return success

    except Exception as e:
        logger.warning(f"Failed to set label: {e}")
        return False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def _get_agent_label(agent_uuid: str) -> Optional[str]:
    """Fetch agent's label from PostgreSQL."""
    try:
        db = get_db()
        return await db.get_agent_label(agent_uuid)
    except Exception:
        return None


async def _get_agent_id_from_metadata(agent_uuid: str) -> Optional[str]:
    """Fetch agent_id (model+date format) from identity metadata."""
    try:
        db = get_db()
        identity = await db.get_identity(agent_uuid)
        if identity and identity.metadata:
            return identity.metadata.get("agent_id")
    except Exception:
        pass
    return None


async def _find_agent_by_label(label: str) -> Optional[str]:
    """Find agent UUID by label (for collision detection)."""
    try:
        db = get_db()
        return await db.find_agent_by_label(label)
    except Exception:
        return None


async def resolve_by_name_claim(
    agent_name: str,
    session_key: str,
    trajectory_signature: Optional[dict] = None,
) -> Optional[Dict[str, Any]]:
    """
    PATH 2.5: Resolve identity by name claim.

    If an agent provides its name, look up the existing identity by label
    in PostgreSQL. If found, bind this session to that identity.
    Optional trajectory verification prevents impersonation.
    """
    if not agent_name or len(agent_name) < 2:
        return None

    # Look up existing agent by label
    agent_uuid = await _find_agent_by_label(agent_name)
    if not agent_uuid:
        logger.debug(f"[NAME_CLAIM] No agent found with label '{agent_name}'")
        return None

    # Optional: trajectory verification (anti-impersonation)
    if trajectory_signature and isinstance(trajectory_signature, dict):
        try:
            from src.trajectory_identity import verify_trajectory_identity
            verification = await verify_trajectory_identity(agent_uuid, trajectory_signature)
            if verification and not verification.get("verified", True):
                lineage_sim = verification.get("tiers", {}).get("lineage", {}).get("similarity", 1.0)
                if lineage_sim < 0.6:
                    logger.warning(
                        f"[NAME_CLAIM] Trajectory mismatch for '{agent_name}' "
                        f"(lineage={lineage_sim:.3f}) - rejecting claim"
                    )
                    return None
        except Exception as e:
            logger.debug(f"[NAME_CLAIM] Trajectory verification skipped: {e}")

    # Fetch display metadata
    agent_id = await _get_agent_id_from_metadata(agent_uuid) or agent_uuid
    label = await _get_agent_label(agent_uuid) or agent_name

    # Bind this session to the existing identity (Redis + PG)
    await _cache_session(session_key, agent_uuid, display_agent_id=agent_id)
    try:
        db = get_db()
        identity = await db.get_identity(agent_uuid)
        if identity:
            await db.create_session(
                session_id=session_key,
                identity_id=identity.identity_id,
                expires_at=datetime.now() + timedelta(hours=GovernanceConfig.SESSION_TTL_HOURS),
                client_type="mcp",
                client_info={"agent_uuid": agent_uuid, "resumed_by_name": True}
            )
    except Exception as e:
        logger.debug(f"[NAME_CLAIM] Session persist failed (non-fatal): {e}")

    logger.info(f"[NAME_CLAIM] Resolved '{agent_name}' -> {agent_uuid[:8]}... via name claim")

    return {
        "agent_id": agent_id,
        "agent_uuid": agent_uuid,
        "display_name": label,
        "label": label,
        "created": False,
        "persisted": True,
        "source": "name_claim",
        "resumed_by_name": True,
    }


async def _cache_session(session_key: str, agent_uuid: str, display_agent_id: str = None) -> None:
    """Cache session→UUID mapping in Redis, with optional display agent_id."""
    session_cache = _get_redis()
    if session_cache:
        try:
            # Store both UUID and display agent_id if provided
            if display_agent_id and display_agent_id != agent_uuid:
                # Get raw Redis client for custom write
                from src.cache.redis_client import get_redis
                import json
                from datetime import datetime, timezone
                redis = await get_redis()
                if redis:
                    data = {
                        "agent_id": agent_uuid,
                        "display_agent_id": display_agent_id,
                        "bound_at": datetime.now(timezone.utc).isoformat(),
                    }
                    key = f"session:{session_key}"
                    await redis.setex(key, GovernanceConfig.SESSION_TTL_SECONDS, json.dumps(data))
                else:
                    # Fallback to normal bind without display_agent_id
                    await session_cache.bind(session_key, agent_uuid)
            else:
                await session_cache.bind(session_key, agent_uuid)
        except Exception as e:
            # WARNING level (v2.5.7): Cache failures can cause identity loss
            logger.warning(f"Redis cache write failed for session {session_key[:20]}...: {e}")


async def _agent_exists_in_postgres(agent_uuid: str) -> bool:
    """Check if agent exists in PostgreSQL."""
    try:
        db = get_db()
        identity = await db.get_identity(agent_uuid)
        return identity is not None
    except Exception:
        return False


# =============================================================================
# LAZY CREATION HELPERS (v2.4.1+)
# =============================================================================

async def ensure_agent_persisted(agent_uuid: str, session_key: str) -> bool:
    """
    Persist agent to PostgreSQL if not already persisted.

    Call this from write operations (process_agent_update, identity(name=...))
    to ensure the agent exists before recording state.

    Args:
        agent_uuid: The agent's UUID (from resolve_session_identity)
        session_key: The session key for session binding

    Returns:
        True if newly persisted, False if already existed
    """
    try:
        db = get_db()
        # Note: db.init() is called once at startup (mcp_server.py:1306).
        # Do NOT call it here — it was creating a new connection pool on every request.

        # Check if already persisted
        identity = await db.get_identity(agent_uuid)
        if identity:
            return False  # Already persisted

        # Persist now
        await db.upsert_agent(
            agent_id=agent_uuid,
            api_key="",
            status="active",
        )

        await db.upsert_identity(
            agent_id=agent_uuid,
            api_key_hash="",
            metadata={
                "source": "lazy_creation",
                "created_at": datetime.now().isoformat(),
                "total_updates": 0,  # Initialize counter for persistence
            }
        )

        # Create session binding
        identity = await db.get_identity(agent_uuid)
        if identity:
            await db.create_session(
                session_id=session_key,
                identity_id=identity.identity_id,
                expires_at=datetime.now() + timedelta(hours=GovernanceConfig.SESSION_TTL_HOURS),
                client_type="mcp",
                client_info={"agent_id": agent_uuid, "lazy_created": True}
            )

        logger.info(f"Lazy-persisted agent on first work: {agent_uuid[:8]}...")
        return True

    except Exception as e:
        logger.warning(f"Failed to persist agent: {e}")
        return False


# =============================================================================
# TOOL HANDLER (replaces identity() tool)
# =============================================================================

async def handle_identity_v2(
    arguments: Dict[str, Any],
    session_key: str,
    model_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    identity() tool handler - simplified.

    Usage:
        identity()              → Returns your UUID and label (lazy, not persisted)
        identity(name="X")      → Sets your label to X, returns UUID (persists agent)

    This tool does NOT look up other agents. Use get_agent_metadata for that.
    """
    # Resolve session to identity (lazy - doesn't persist yet)
    # Try name-based resolution first (PATH 2.5)
    name = arguments.get("name")
    if name:
        name_result = await resolve_by_name_claim(name, session_key)
        if name_result:
            agent_uuid = name_result["agent_uuid"]
            agent_id = name_result["agent_id"]
            display_name = name_result.get("label")
            from .identity_shared import make_client_session_id
            stable_session_id = make_client_session_id(agent_uuid)
            return {
                "success": True,
                "agent_id": agent_id,
                "agent_uuid": agent_uuid,
                "display_name": display_name,
                "label": display_name,
                "bound": True,
                "persisted": True,
                "source": "name_claim",
                "created": False,
                "resumed_by_name": True,
                "client_session_id": stable_session_id,
                "message": f"Resumed identity: {display_name or agent_id}",
                "session_continuity": {
                    "client_session_id": stable_session_id,
                    "instruction": "Include client_session_id in ALL future tool calls for stable identity",
                },
            }

    # Pass model_type to generate proper agent_id (model+date format)
    identity = await resolve_session_identity(
        session_key,
        persist=False,
        model_type=model_type or arguments.get("model_type")
    )
    agent_id = identity.get("agent_id", identity["agent_uuid"])
    agent_uuid = identity["agent_uuid"]
    persisted = identity.get("persisted", False)

    # Set label if requested (this will persist the agent)
    if name:
        success = await set_agent_label(agent_uuid, name, session_key=session_key)
        if success:
            identity["label"] = name
            identity["label_set"] = True
            persisted = True  # set_agent_label calls ensure_agent_persisted

    display_name = identity.get("label")  # label is stored internally, exposed as display_name
    return {
        "success": True,
        "agent_id": agent_id,  # model+date format (e.g., "Claude_Opus_20251227")
        "agent_uuid": agent_uuid,  # internal UUID
        "display_name": display_name,  # user-chosen name (three-tier identity)
        "label": display_name,  # DEPRECATED alias for display_name (backward compat)
        "bound": True,
        "persisted": persisted,
        "source": identity.get("source"),
        "created": identity.get("created", False),
        "message": f"Identity: {display_name or agent_id}",
    }


# =============================================================================
# DECORATOR-COMPATIBLE ADAPTER
# =============================================================================

from typing import Sequence
from mcp.types import TextContent
from .decorators import mcp_tool
from .utils import success_response
import os


def _extract_stable_identifier(session_key: str) -> Optional[str]:
    """
    Extract stable identifier from session key for recovery across server restarts.
    
    For client_session_id format "IP:port:suffix", extracts the suffix.
    This allows recovery even when IP changes.
    
    Args:
        session_key: Full session key (e.g., "217.216.112.229:8767:6d79c4")
    
    Returns:
        Stable identifier (e.g., "6d79c4") or None if not extractable
    """
    if not session_key:
        return None
    
    # Pattern: IP:port:suffix or IP:suffix
    parts = session_key.split(":")
    if len(parts) >= 2:
        # Take the last part as stable identifier
        suffix = parts[-1]
        # Validate it looks like a fingerprint (hex, reasonable length)
        if len(suffix) >= 4 and all(c in '0123456789abcdef' for c in suffix.lower()):
            return suffix
    
    return None


def _derive_session_key(arguments: Dict[str, Any]) -> str:
    """
    Derive session key from arguments or context.

    Precedence:
    1. arguments["client_session_id"] (Explicit session ID from client)
    2. MCP session ID from mcp-session-id header (MCP Streamable HTTP transport)
    3. contextvars session_key (Fingerprinted ID from transport layer)
    4. stdio fallback (Claude Desktop / single-user)

    CRITICAL (Feb 2026): Priority 2 enables MCP Streamable HTTP clients to maintain
    stable identity across requests without manually passing client_session_id.
    """
    if arguments.get("client_session_id"):
        return str(arguments["client_session_id"])

    # 2. Check MCP session ID (set by ASGI wrapper from mcp-session-id header)
    # This is the implicit identity mechanism for MCP Streamable HTTP transport
    try:
        from .context import get_mcp_session_id
        mcp_sid = get_mcp_session_id()
        if mcp_sid:
            logger.debug(f"[SESSION] Using mcp-session-id: {mcp_sid[:16]}...")
            return f"mcp:{mcp_sid}"
    except Exception:
        pass

    # 3. Check contextvars (set by transport layer at request entry)
    try:
        from .context import get_context_session_key
        ctx_key = get_context_session_key()
        if ctx_key:
            return str(ctx_key)
    except Exception:
        pass

    # 4. Stable fallback for stdio
    return f"stdio:{os.getpid()}"


def _extract_base_fingerprint(session_key: str) -> Optional[str]:
    """Extract stable base fingerprint from a session key.

    For HTTP transports, session keys follow the pattern IP:UA_hash or
    IP:UA_hash:random_suffix. Claude.ai's proxy pool rotates IPs per
    request, so we pin by UA_hash ONLY — the UA string is stable across
    requests from the same conversation/model.

    Returns None for keys that already provide stable identity (mcp:*,
    stdio:*, agent-*) since those don't need onboard pinning.
    """
    if not session_key:
        return None
    # Keys with stable identity don't need pinning
    if session_key.startswith(("mcp:", "stdio:", "agent-")):
        logger.debug(f"[ONBOARD_PIN] Skipping stable key: {session_key[:30]}...")
        return None
    # Pattern: IP:UA_hash or IP:UA_hash:random_suffix or IP:UA_hash:model_hint
    # Pin by UA_hash only (parts[1]) — IP rotates across Claude.ai proxy pool
    parts = session_key.split(":")
    if len(parts) >= 2:
        ua_hash = parts[1]
        logger.debug(f"[ONBOARD_PIN] extract_fp: raw={session_key!r} ({len(parts)} parts) -> ua_hash={ua_hash!r}")
        return f"ua:{ua_hash}"
    # Single-part key (unusual) — return as-is
    logger.debug(f"[ONBOARD_PIN] extract_fp: raw={session_key!r} (single part) -> as-is")
    return session_key


def ua_hash_from_header(user_agent: str) -> Optional[str]:
    """Compute the canonical UA hash from a raw User-Agent string.

    This is the SINGLE SOURCE OF TRUTH for UA hash computation.
    Both REST and MCP paths must use this to ensure pin keys match.

    Returns: "ua:{md5_prefix}" or None if no user_agent.
    """
    if not user_agent:
        return None
    import hashlib
    ua_hash = hashlib.md5(user_agent.encode()).hexdigest()[:6]
    return f"ua:{ua_hash}"


_PIN_TTL = 1800  # 30 minutes — refresh on use


async def lookup_onboard_pin(base_fingerprint: str, *, refresh_ttl: bool = True) -> Optional[str]:
    """Look up a pinned client_session_id from a recent onboard.

    Shared by REST path (_extract_client_session_id) and MCP dispatcher
    (dispatch_tool) to eliminate duplication and divergence risk.

    Args:
        base_fingerprint: Output of _extract_base_fingerprint() or ua_hash_from_header(),
                          e.g. "ua:d20c2f"
        refresh_ttl: Whether to extend the pin's TTL on successful lookup (default True)

    Returns: The pinned client_session_id, or None.
    """
    if not base_fingerprint:
        return None
    try:
        from src.cache.redis_client import get_redis
        import json as _json
        raw_redis = await get_redis()
        if not raw_redis:
            return None
        pin_key = f"recent_onboard:{base_fingerprint}"
        pin_data = await raw_redis.get(pin_key)
        if not pin_data:
            logger.debug(f"[ONBOARD_PIN] No pin at {pin_key}")
            return None
        pin = _json.loads(pin_data if isinstance(pin_data, str) else pin_data.decode())
        pinned_session_id = pin.get("client_session_id")
        if pinned_session_id and refresh_ttl:
            await raw_redis.expire(pin_key, _PIN_TTL)
        return pinned_session_id
    except Exception as e:
        logger.debug(f"[ONBOARD_PIN] Pin lookup failed: {e}")
        return None


async def set_onboard_pin(base_fingerprint: str, agent_uuid: str, client_session_id: str) -> bool:
    """Set a pin mapping a transport fingerprint to an onboarded agent.

    Called by handle_onboard_v2() after successful onboard.

    Args:
        base_fingerprint: Output of _extract_base_fingerprint(), e.g. "ua:d20c2f"
        agent_uuid: The newly onboarded agent's UUID
        client_session_id: The stable session ID to inject on subsequent calls

    Returns: True if the pin was set successfully.
    """
    if not base_fingerprint:
        logger.debug("[ONBOARD_PIN] No fingerprint — skip pin-set")
        return False
    try:
        from src.cache.redis_client import get_redis
        import json as _json
        raw_redis = await get_redis()
        if not raw_redis:
            logger.warning("[ONBOARD_PIN] Redis not available for pin-setting")
            return False
        pin_key = f"recent_onboard:{base_fingerprint}"
        pin_data = _json.dumps({
            "agent_uuid": agent_uuid,
            "client_session_id": client_session_id,
        })
        await raw_redis.setex(pin_key, _PIN_TTL, pin_data)
        logger.info(f"[ONBOARD_PIN] Set {pin_key} -> {agent_uuid[:8]}...")
        return True
    except Exception as e:
        logger.warning(f"[ONBOARD_PIN] Could not set pin: {e}")
        return False


@mcp_tool("identity", timeout=10.0)
async def handle_identity_adapter(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    🪞 IDENTITY - Who am I? Auto-creates identity if first call.

    Simplified v2 implementation with 3 paths:
    - Redis cache (fast)
    - PostgreSQL lookup
    - Create new agent

    Optional: Pass name='...' to set your display name.
    Optional: Pass model_type='...' to create distinct identity per model.
    Optional: Pass resume=true to explicitly resume existing identity (after prompt).
    Optional: Pass force_new=true to create new identity even if one exists.
    """
    arguments = arguments or {}
    force_new = arguments.get("force_new", False)
    resume = arguments.get("resume", False)
    model_type = arguments.get("model_type")

    # Derive base session key
    base_session_key = _derive_session_key(arguments)
    normalized_model = None

    # PATH 2.5: Name-based identity claim (before any session resolution)
    # If the caller provides name= and isn't forcing new, try to reconnect to existing identity
    name = arguments.get("name")
    if name and not force_new:
        name_result = await resolve_by_name_claim(name, base_session_key)
        if name_result:
            agent_uuid = name_result["agent_uuid"]
            agent_id = name_result["agent_id"]
            label = name_result.get("label")
            logger.info(f"[IDENTITY] Resolved '{name}' via name claim -> {agent_uuid[:8]}...")

            # Update request context so signature matches
            try:
                from .context import update_context_agent_id
                update_context_agent_id(agent_uuid)
            except Exception:
                pass

            return success_response({
                "uuid": agent_uuid,
                "agent_id": agent_id,
                "display_name": label,
                "resumed": True,
                "resumed_by_name": True,
                "message": f"Welcome back! Resumed identity '{label or agent_id}'",
                "hint": "Use force_new=true to create a new identity instead"
            })

    # STEP 1: Check for existing identity under BASE key first (unless force_new)
    # This prevents identity bifurcation when model_type is passed inconsistently
    # FIX (Feb 2026): Match onboard() pattern - check base key first, then model-suffixed
    existing_identity = None
    session_key = base_session_key

    if not force_new:
        existing_identity = await resolve_session_identity(base_session_key, persist=False)
        if not existing_identity.get("created"):
            # EXISTING AGENT FOUND under base key - use it regardless of model_type
            agent_uuid = existing_identity.get("agent_uuid")
            agent_id = existing_identity.get("agent_id", agent_uuid)
            label = existing_identity.get("label")
            logger.info(f"[IDENTITY] Auto-resuming existing agent {agent_uuid[:8]}... (found under base key)")

            # Update label if requested
            if arguments.get("name") and arguments.get("name") != label:
                success = await set_agent_label(agent_uuid, arguments.get("name"), session_key=session_key)
                if success:
                    label = arguments.get("name")

            return success_response({
                "uuid": agent_uuid,
                "agent_id": agent_id,
                "display_name": label,
                "resumed": True,
                "message": f"Welcome back! Resumed identity '{label or agent_id}'",
                "hint": "Use force_new=true to create a new identity instead"
            })

    # STEP 2: No existing identity under base key - use model differentiation if provided
    # This only affects NEW identity creation, not resumption
    if model_type:
        # Normalize model type
        normalized_model = model_type.lower().replace("-", "_").replace(".", "_")
        if "claude" in normalized_model:
            normalized_model = "claude"
        elif "gemini" in normalized_model:
            normalized_model = "gemini"
        elif "gpt" in normalized_model or "chatgpt" in normalized_model:
            normalized_model = "gpt"
        elif "composer" in normalized_model or "cursor" in normalized_model:
            normalized_model = "composer"
        elif "llama" in normalized_model:
            normalized_model = "llama"
        # Append model to session key for distinct binding (prevents identity collision)
        session_key = f"{base_session_key}:{normalized_model}"
        logger.info(f"[IDENTITY] Creating NEW identity with model-specific session_key: {session_key}")

    # STEP 3: Check for existing identity under model-suffixed key (for force_new=false case)
    # This handles the case where identity was created with model_type previously
    if not force_new and model_type and session_key != base_session_key:
        existing_identity = await resolve_session_identity(session_key, persist=False)
        if not existing_identity.get("created"):
            # EXISTING AGENT FOUND - auto-resume
            agent_uuid = existing_identity.get("agent_uuid")
            agent_id = existing_identity.get("agent_id", agent_uuid)
            label = existing_identity.get("label")
            logger.info(f"[IDENTITY] Auto-resuming existing agent {agent_uuid[:8]}...")

            # Update label if requested
            if arguments.get("name") and arguments.get("name") != label:
                success = await set_agent_label(agent_uuid, arguments.get("name"), session_key=session_key)
                if success:
                    label = arguments.get("name")

            return success_response({
                "uuid": agent_uuid,
                "agent_id": agent_id,
                "display_name": label,
                "resumed": True,
                "message": f"Welcome back! Resumed identity '{label or agent_id}'",
                "hint": "Use force_new=true to create a new identity instead"
            })

    # Call simplified handler with model_type for agent_id generation
    result = await handle_identity_v2(arguments, session_key, model_type=model_type)
    agent_id = result.get("agent_id", result["agent_uuid"])
    agent_uuid = result["agent_uuid"]

    # CRITICAL: Update request context so signature in response matches resolved identity
    try:
        from .context import update_context_agent_id
        update_context_agent_id(agent_uuid)
    except Exception as e:
        logger.debug(f"Could not update context in identity: {e}")

    # Get structured_id from metadata (three-tier identity model v2.5.0+)
    structured_id = None
    try:
        from .shared import get_mcp_server
        mcp_server = get_mcp_server()
        if agent_uuid in mcp_server.agent_metadata:
            meta = mcp_server.agent_metadata[agent_uuid]
            structured_id = getattr(meta, 'structured_id', None)

            # If model_type provided and structured_id doesn't include it, regenerate
            if model_type and structured_id and normalized_model and normalized_model not in structured_id:
                from .naming_helpers import detect_interface_context, generate_structured_id
                from .context import get_context_client_hint
                context = detect_interface_context()
                existing_ids = [
                    getattr(m, 'structured_id', None)
                    for m in mcp_server.agent_metadata.values()
                    if getattr(m, 'structured_id', None)
                ]
                meta.structured_id = generate_structured_id(
                    context=context,
                    existing_ids=existing_ids,
                    client_hint=get_context_client_hint(),
                    model_type=model_type
                )
                structured_id = meta.structured_id
                logger.info(f"[IDENTITY] Regenerated structured_id with model: {structured_id}")
    except Exception as e:
        logger.debug(f"Could not get/update structured_id: {e}")

    # Format response - four-tier identity (v2.5.2)
    final_agent_id = agent_id or structured_id or agent_uuid
    user_name = result.get("label")
    
    # Derive client_session_id for session continuity
    client_session_id = _derive_session_key(arguments) if arguments else None
    
    response_data = {
        "uuid": agent_uuid,
        "agent_id": final_agent_id,
        "display_name": user_name,
        "label": user_name,
    }
    if model_type:
        response_data["model_type"] = model_type
    
    # UX ENHANCEMENT: Comprehensive identity summary (all fields in one place)
    # This consolidates all identity-related fields to reduce confusion
    response_data["identity_summary"] = {
        "uuid": {
            "value": agent_uuid,
            "description": "Immutable technical identifier (primary key, never changes)",
            "usage": "Internal lookup and persistence - don't expose in user-facing content"
        },
        "agent_id": {
            "value": final_agent_id,
            "description": "Structured auto-generated ID (model+date format, e.g., 'Claude_Opus_20251227')",
            "usage": "Display in knowledge graph entries, logs, reports"
        },
        "display_name": {
            "value": user_name,
            "description": "User-chosen display name (set via identity(name='...'))",
            "usage": "Human-readable attribution in knowledge graph and reports",
            "set_via": "identity(name='YourName')"
        },
        "client_session_id": {
            "value": client_session_id,
            "description": "Session continuity token - include in ALL future tool calls",
            "usage": "Echo this value back in all tool calls to maintain identity across sessions",
            "critical": True
        }
    }
    
    # Add quick reference for common use cases
    response_data["quick_reference"] = {
        "for_knowledge_graph": user_name or final_agent_id,
        "for_session_continuity": client_session_id,
        "for_internal_lookup": agent_uuid,
        "to_set_display_name": "identity(name='YourName')"
    }
    
    # Session continuity guidance (if not already set)
    if not result.get("session_continuity"):
        response_data["session_continuity"] = {
            "client_session_id": client_session_id,
            "instruction": "Include client_session_id in ALL future tool calls to maintain identity",
            "example": f'{{"name": "process_agent_update", "arguments": {{"client_session_id": "{client_session_id}", "response_text": "...", "complexity": 0.5}}}}'
        }

    # Use lite_response to skip redundant agent_signature (identity already contains all that info)
    if arguments is None:
        arguments = {}
    arguments["lite_response"] = True
    return success_response(response_data, agent_id=final_agent_id, arguments=arguments)


# =============================================================================
# MIGRATION HELPERS
# =============================================================================

async def migrate_from_v1(old_session_identities: Dict[str, Dict]) -> int:
    """
    Migrate existing session bindings from identity.py to v2 format.

    Call once during upgrade to populate PostgreSQL with existing bindings.
    Returns number of sessions migrated.
    """
    count = 0
    db = get_db()

    for session_key, binding in old_session_identities.items():
        agent_uuid = binding.get("bound_agent_id")
        if not agent_uuid:
            continue

        try:
            # Ensure agent exists
            await db.upsert_agent(
                agent_id=agent_uuid,
                api_key=binding.get("api_key", ""),
                status="active",
            )

            # Ensure identity exists
            await db.upsert_identity(
                agent_id=agent_uuid,
                api_key_hash="",
                metadata={"migrated_from": "v1", "total_updates": 0}
            )

            # Create session
            identity = await db.get_identity(agent_uuid)
            if identity:
                await db.create_session(
                    session_id=session_key,
                    identity_id=identity.identity_id,
                    expires_at=datetime.now() + timedelta(hours=GovernanceConfig.SESSION_TTL_HOURS),
                    client_type="mcp",
                    client_info={"migrated": True}
                )

            count += 1

        except Exception as e:
            logger.warning(f"Failed to migrate session {session_key[:20]}...: {e}")

    logger.info(f"Migrated {count} sessions from v1 to v2")
    return count


@mcp_tool("onboard", timeout=15.0)
async def handle_onboard_v2(arguments: Dict[str, Any]) -> Sequence[TextContent]:
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

    arguments = arguments or {}

    # Extract optional parameters
    name = arguments.get("name")  # Optional: set display name
    force_new = arguments.get("force_new", False)  # Force new identity creation
    model_type = arguments.get("model_type")

    # Auto-detect client_hint from transport if not provided
    client_hint = arguments.get("client_hint")
    if not client_hint or client_hint == "unknown":
        from .context import get_context_client_hint
        client_hint = get_context_client_hint() or "unknown"

    # Derive base session key
    base_session_key = _derive_session_key(arguments)
    normalized_model = None

    # Extract resume flag early (before checking existing identity)
    resume = arguments.get("resume", False)
    
    # STEP 1: Check if an identity already exists for this session (base key)
    # This prevents forking when model_type is passed for an existing agent
    # Skip this check if force_new is requested
    # Auto-resume existing identity by default (no prompt needed)
    existing_identity = None
    created_fresh_identity = False  # Track if we got a fresh identity to persist
    _was_archived = False  # Track if agent was auto-unarchived
    if not force_new:
        # Name-based reconnection ONLY if resume=True is explicitly passed
        # This prevents accidental identity collision when multiple sessions use same name
        if name and resume:
            existing_by_name = await resolve_by_name_claim(name, base_session_key)
            if existing_by_name:
                existing_identity = existing_by_name
                agent_uuid = existing_by_name["agent_uuid"]
                agent_id = existing_by_name["agent_id"]
                label = existing_by_name.get("label")
                logger.info(f"[ONBOARD] Resumed '{name}' via name claim -> {agent_uuid[:8]}...")
            else:
                existing_identity = await resolve_session_identity(base_session_key, persist=False)
        else:
            existing_identity = await resolve_session_identity(base_session_key, persist=False)
        if not existing_identity.get("created"):
            # EXISTING AGENT FOUND - auto-resume
            agent_uuid = existing_identity.get("agent_uuid")
            agent_id = existing_identity.get("agent_id", agent_uuid)
            label = existing_identity.get("label")
            logger.info(f"[ONBOARD] Auto-resuming existing agent {agent_uuid[:8]}...")
            # Check if agent is archived — auto-unarchive on explicit reconnect
            try:
                db = get_db()
                identity_record = await db.get_identity(agent_uuid)
                if identity_record and identity_record.status == "archived":
                    await db.update_agent_fields(agent_uuid, status="active")
                    logger.info(f"[ONBOARD] Auto-unarchived agent {agent_uuid[:8]}... (reconnected via onboard)")
                    _was_archived = True
            except Exception as e:
                logger.warning(f"[ONBOARD] Could not check/unarchive agent: {e}")
            # Mark for resume flow below
            resume = True
        else:
            # NEW AGENT - got a fresh identity from persist=False call
            # CRITICAL FIX (v2.5.7): Capture the fresh identity to persist it directly
            # instead of calling resolve_session_identity again (which could create a different UUID
            # if Redis caching failed silently)
            created_fresh_identity = True
            agent_uuid = existing_identity.get("agent_uuid")
            agent_id = existing_identity.get("agent_id", agent_uuid)
            logger.info(f"[ONBOARD] Created fresh identity {agent_uuid[:8]}... (will persist)")

            # Adjust session_key for fleet tracking
            session_key = base_session_key
            if model_type:
                normalized_model = model_type.lower().replace("-", "_").replace(".", "_")
                if "claude" in normalized_model:
                    normalized_model = "claude"
                elif "gemini" in normalized_model:
                    normalized_model = "gemini"
                elif "gpt" in normalized_model:
                    normalized_model = "gpt"
                elif "llama" in normalized_model:
                    normalized_model = "llama"
                session_key = f"{base_session_key}:{normalized_model}"
                logger.info(f"[ONBOARD] NEW agent with model_type={model_type} → session_key includes model: {session_key}")
    else:
        # force_new requested - use model-suffixed key if model_type provided
        session_key = base_session_key
        if model_type:
            normalized_model = model_type.lower().replace("-", "_").replace(".", "_")
            if "claude" in normalized_model:
                normalized_model = "claude"
            elif "gemini" in normalized_model:
                normalized_model = "gemini"
            elif "gpt" in normalized_model:
                normalized_model = "gpt"
            elif "llama" in normalized_model:
                normalized_model = "llama"
            session_key = f"{base_session_key}:{normalized_model}"
            logger.info(f"[ONBOARD] force_new with model_type={model_type} → session_key: {session_key}")

    # STEP 2: Handle resume flag (explicit consent to resume existing identity)
    # (resume was extracted earlier at STEP 1)
    if resume and existing_identity and not existing_identity.get("created"):
        # User explicitly chose to resume - use existing identity
        agent_uuid = existing_identity.get("agent_uuid")
        agent_id = existing_identity.get("agent_id", agent_uuid)
        agent_label = existing_identity.get("label")
        session_key = base_session_key  # Use base key, don't fork
        is_new = False
        identity = existing_identity
        logger.info(f"[ONBOARD] Resuming existing agent {agent_uuid[:8]}... (explicit resume=true)")
    elif created_fresh_identity:
        # CRITICAL FIX (v2.5.7): Persist the fresh identity we already created
        # instead of calling resolve_session_identity again (which could create a different UUID)
        try:
            # Persist the identity we got from the persist=False call
            newly_persisted = await ensure_agent_persisted(agent_uuid, session_key)
            if newly_persisted:
                logger.info(f"[ONBOARD] Persisted fresh identity {agent_uuid[:8]}... to PostgreSQL")
            else:
                logger.debug(f"[ONBOARD] Fresh identity {agent_uuid[:8]}... was already persisted")

            # Cache with the adjusted session_key (may include model suffix)
            await _cache_session(session_key, agent_uuid, display_agent_id=agent_id)

            identity = existing_identity
            identity["persisted"] = True
            identity["source"] = "created"
            is_new = True
            agent_label = None
        except Exception as e:
            logger.error(f"[ONBOARD] Failed to persist fresh identity: {e}")
            return error_response(f"Failed to persist identity: {e}")
    else:
        # STEP 2b: Get or create identity (using v2 logic)
        try:
            # resolve_session_identity creates new if needed (PATH 3)
            # We use force_new=True if requested to bypass cache/DB lookup
            identity = await resolve_session_identity(
                session_key,
                persist=True,  # Onboard always persists (it's an explicit "I am here" action)
                model_type=model_type,
                client_hint=client_hint,
                force_new=force_new
            )
            agent_uuid = identity["agent_uuid"]
            agent_id = identity.get("agent_id", agent_uuid)
            is_new = identity.get("created", False) or force_new
            agent_label = identity.get("label")
        except Exception as e:
            logger.error(f"onboard() failed to create identity: {e}")
            return error_response(f"Failed to create identity: {e}")

    # CRITICAL: Update request context so signature in response matches new identity
    try:
        from .context import update_context_agent_id
        update_context_agent_id(agent_uuid)
    except Exception as e:
        logger.debug(f"Could not update context in onboard: {e}")

    # Set label if requested (and different from current)
    if name and name != agent_label:
        success = await set_agent_label(agent_uuid, name, session_key=session_key)
        if success:
            agent_label = name
            # Refresh identity object
            identity["label"] = name

    # TRAJECTORY IDENTITY: Store genesis signature if provided (optional, non-blocking)
    # Agents from anima-mcp can include trajectory_signature in their onboard call
    trajectory_result = None
    trajectory_signature = arguments.get("trajectory_signature")
    if trajectory_signature and isinstance(trajectory_signature, dict):
        try:
            from src.trajectory_identity import TrajectorySignature, store_genesis_signature
            sig = TrajectorySignature.from_dict(trajectory_signature)
            stored = await store_genesis_signature(agent_uuid, sig)
            if stored:
                trajectory_result = {
                    "genesis_stored": True,
                    "confidence": sig.identity_confidence,
                    "observations": sig.observation_count,
                }
                logger.info(f"[TRAJECTORY] Stored genesis Σ₀ for {agent_uuid[:8]}... at onboard")
        except Exception as e:
            logger.debug(f"[TRAJECTORY] Could not store genesis at onboard: {e}")
            # Non-blocking - trajectory is optional

    # STEP 3: Generate stable session ID
    # Import helper to ensure consistent format
    from .identity_shared import make_client_session_id
    stable_session_id = make_client_session_id(agent_uuid)

    # STEP 4: Register binding under stable session ID (in v2 cache)
    # This allows future calls using stable_session_id to find the agent
    # even if the transport session key changes
    await _cache_session(stable_session_id, agent_uuid, display_agent_id=agent_id)
    
    # Also register in O(1) prefix index (legacy support)
    try:
        from .identity_shared import _register_uuid_prefix
        uuid_prefix = agent_uuid[:12]
        _register_uuid_prefix(uuid_prefix, agent_uuid)
    except ImportError:
        pass

    # STEP 4b: Pin onboard identity for transport-level session continuity
    # When Claude.ai doesn't pass client_session_id, dispatch_tool() can
    # use this pin to inject the correct session ID based on transport fingerprint.
    # This prevents knowledge graph attribution from scattering across random UUIDs.
    try:
        logger.debug(f"[ONBOARD_PIN] base_session_key={base_session_key!r}")
        base_fp = _extract_base_fingerprint(base_session_key)
        await set_onboard_pin(base_fp, agent_uuid, stable_session_id)
    except Exception as e:
        logger.warning(f"[ONBOARD_PIN] Could not set pin: {e}")

    # STEP 5: Build toolcard payload
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

    # Get structured_id - USE agent_id from resolve_session_identity (properly generated with model_type)
    # Only fall back to metadata lookup if agent_id was not properly set
    structured_id = agent_id if agent_id and agent_id != agent_uuid else None
    if not structured_id:
        try:
            from .shared import get_mcp_server
            mcp_server = get_mcp_server()
            if agent_uuid in mcp_server.agent_metadata:
                meta = mcp_server.agent_metadata[agent_uuid]
                structured_id = getattr(meta, 'structured_id', None)
        except Exception:
            pass

    # Determine friendly name - final fallback to UUID-based if nothing else
    if not structured_id:
        structured_id = f"agent_{agent_uuid[:8]}"
    friendly_name = agent_label or structured_id

    # Welcome message — embed session ID directly in welcome so agents can't miss it
    if is_new:
        welcome = f"Welcome! Your session ID is `{stable_session_id}`. Pass this as `client_session_id` in all calls."
        welcome_message = "This system monitors your work like a health monitor tracks your heart. It helps you stay on track, avoid getting stuck, and work more effectively. Your identity is created—use the templates below to get started."
    else:
        welcome = f"Welcome back, {friendly_name}! Your session ID is `{stable_session_id}`."
        welcome_message = f"I found your existing identity. Pass `client_session_id: \"{stable_session_id}\"` in all tool calls for best attribution."
        if _was_archived:
            welcome_message += " (Note: your agent was archived and has been reactivated.)"

    result = {
        "success": True,
        "welcome": welcome,
        "welcome_message": welcome_message,
        "suggest_new_identity": False,

        # Three-tier identity model
        "uuid": agent_uuid,
        "agent_id": structured_id,
        "display_name": agent_label,

        # Legacy fields
        "agent_uuid": agent_uuid,
        "label": agent_label,
        "is_new": is_new,
        "force_new_applied": force_new,

        # Session continuity
        "client_session_id": stable_session_id,
        "session_continuity": {
            "client_session_id": stable_session_id,
            "instruction": "Include client_session_id in ALL future tool calls to maintain identity",
            "tip": client_tips.get(client_hint, client_tips["unknown"])
        },

        # The toolcard
        "next_calls": next_calls,

        # Date context (implicit - no separate tool needed)
        "date_context": _get_date_context(),

        # Skill document resource (eliminates 3-5 orientation tool calls)
        "skill_resource": {
            "uri": "unitares://skill",
            "tip": "Read this MCP resource for full framework orientation instead of calling list_tools/describe_tool",
        },
    }

    # Add tool mode info so agents know what subset they're seeing
    try:
        from src.tool_modes import TOOL_MODE, get_tools_for_mode
        from src.tool_schemas import get_tool_definitions
        all_tools = get_tool_definitions()
        mode_tools = get_tools_for_mode(TOOL_MODE)
        result["tool_mode"] = {
            "current_mode": TOOL_MODE,
            "visible_tools": len(mode_tools),
            "total_tools": len(all_tools),
            "available_modes": ["minimal", "lite", "full"],
            "tip": f"You're seeing {len(mode_tools)}/{len(all_tools)} tools in '{TOOL_MODE}' mode. Use list_tools() for discovery, or ask for ?mode=full if you need more."
        }
    except Exception as e:
        logger.debug(f"Could not add tool_mode info: {e}")

    # Add workflow guidance for new agents
    if is_new or force_new:
        result.update({
            "workflow": {
                "step_1": "Copy client_session_id from above",
                "step_2": "Do your work",
                "step_3": "Call process_agent_update with response_text describing what you did",
                "loop": "Repeat steps 2-3. Check metrics with get_governance_metrics when curious."
            },
            "what_this_does": {
                "problem": "AI systems drift, get stuck, and make unexplainable decisions.",
                "solution": "This system monitors your work in real-time using state-based dynamics (not rules).",
                "benefits": ["Prevents problems", "Avoids loops", "Provides feedback", "Scales automatically"]
            }
        })

    # Include trajectory result if genesis was stored
    if trajectory_result:
        result["trajectory"] = trajectory_result
        result["trajectory"]["trust_tier"] = {
            "tier": 1,
            "name": "emerging",
            "reason": "Genesis stored at onboard. Identity will mature with behavioral consistency.",
        }

    logger.info(f"[ONBOARD] Agent {agent_uuid[:8]}... onboarded (is_new={is_new}, label={agent_label})")

    # Use lite_response to skip redundant signature
    arguments["lite_response"] = True
    return success_response(result, agent_id=agent_uuid, arguments=arguments)


# =============================================================================
# TRAJECTORY IDENTITY VERIFICATION TOOL
# =============================================================================

@mcp_tool("verify_trajectory_identity", timeout=10.0)
async def handle_verify_trajectory_identity(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    🔬 VERIFY_TRAJECTORY_IDENTITY - Two-tier identity verification via trajectory signature.

    Verifies agent identity using the Trajectory Identity framework:
    - Tier 1 (Coherence): Compare to recent signature (short-term consistency)
    - Tier 2 (Lineage): Compare to genesis signature (long-term identity continuity)

    Args:
        trajectory_signature: The current trajectory signature to verify (dict with:
            preferences, beliefs, attractor, recovery, relational, stability_score,
            identity_confidence, observation_count)
        coherence_threshold: Optional threshold for Tier 1 (default: 0.7)
        lineage_threshold: Optional threshold for Tier 2 (default: 0.6)

    Returns:
        Verification result with tier details and overall verdict.
    """
    # Get agent UUID from context
    from .context import get_context_agent_id
    agent_uuid = get_context_agent_id()

    if not agent_uuid:
        return error_response("Identity not resolved. Call identity() or onboard() first.")

    trajectory_signature = arguments.get("trajectory_signature")
    if not trajectory_signature or not isinstance(trajectory_signature, dict):
        return error_response(
            "trajectory_signature is required",
            recovery={
                "action": "Include your trajectory signature from anima-mcp",
                "example": "verify_trajectory_identity(trajectory_signature={...})"
            }
        )

    coherence_threshold = arguments.get("coherence_threshold", 0.7)
    lineage_threshold = arguments.get("lineage_threshold", 0.6)

    try:
        from src.trajectory_identity import TrajectorySignature, verify_trajectory_identity

        sig = TrajectorySignature.from_dict(trajectory_signature)
        result = await verify_trajectory_identity(
            agent_uuid,
            sig,
            coherence_threshold=coherence_threshold,
            lineage_threshold=lineage_threshold
        )

        if result.get("error"):
            return error_response(result["error"])

        return success_response(result, agent_id=agent_uuid, arguments=arguments)

    except Exception as e:
        logger.error(f"[TRAJECTORY] Verification failed: {e}")
        return error_response(f"Trajectory verification failed: {e}")


@mcp_tool("get_trajectory_status", timeout=10.0)
async def handle_get_trajectory_status(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    📊 GET_TRAJECTORY_STATUS - Check trajectory identity status for an agent.

    Returns information about the agent's trajectory identity including:
    - Whether genesis signature exists
    - Current signature details
    - Lineage similarity (if both exist)
    - Drift detection status

    No arguments required - uses current session identity.
    """
    # Get agent UUID from context
    from .context import get_context_agent_id
    agent_uuid = get_context_agent_id()

    if not agent_uuid:
        return error_response("Identity not resolved. Call identity() or onboard() first.")

    try:
        from src.trajectory_identity import get_trajectory_status

        result = await get_trajectory_status(agent_uuid)

        if result.get("error"):
            return error_response(result["error"])

        # Add trust tier to status response
        try:
            from src.trajectory_identity import compute_trust_tier
            from src.db import get_db
            identity = await get_db().get_identity(agent_uuid)
            if identity and identity.metadata:
                result["trust_tier"] = compute_trust_tier(identity.metadata)
        except Exception:
            pass

        return success_response(result, agent_id=agent_uuid, arguments=arguments)

    except Exception as e:
        logger.error(f"[TRAJECTORY] Status check failed: {e}")
        return error_response(f"Trajectory status check failed: {e}")
