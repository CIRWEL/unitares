"""
Agent persistence, caching, and label management.

Houses _get_redis, _cache_session, ensure_agent_persisted, set_agent_label,
and DB helper functions for identity resolution.
"""

from __future__ import annotations

from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import json

from src.logging_utils import get_logger
from src.db import get_db

from config.governance_config import GovernanceConfig

logger = get_logger(__name__)
from src.mcp_handlers.shared import lazy_mcp_server as mcp_server
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
# CACHE HELPERS
# =============================================================================

async def _cache_session(
    session_key: str,
    agent_uuid: str,
    display_agent_id: str = None,
    trajectory_required: bool = False,
    label: str = None,
) -> None:
    """Cache session->UUID mapping in Redis, with optional display agent_id.

    Args:
        trajectory_required: If True, indicates this identity has a stored
            trajectory genesis. Lets PATH 1 skip the get_trajectory_status()
            call on subsequent hits (optimization hint).
        label: Auto-generated or user-set label to store alongside the binding.
    """
    session_cache = _get_redis()
    if session_cache:
        try:
            # Store both UUID and display agent_id if provided
            if display_agent_id and display_agent_id != agent_uuid:
                # Get raw Redis client for custom write
                from src.cache.redis_client import get_redis
                from datetime import timezone
                redis = await get_redis()
                if redis:
                    data = {
                        "agent_id": agent_uuid,
                        "display_agent_id": display_agent_id,
                        "bound_at": datetime.now(timezone.utc).isoformat(),
                        "trajectory_required": trajectory_required,
                    }
                    if label:
                        data["label"] = label
                    key = f"session:{session_key}"
                    await redis.setex(key, GovernanceConfig.SESSION_TTL_SECONDS, json.dumps(data))
                    # Keep SessionCache's in-memory fallback coherent with the richer
                    # raw Redis payload so subsequent lookups see the same binding
                    # even if they fall back from Redis during this process lifetime.
                    try:
                        from src.cache import session_cache as _session_cache_mod
                        _session_cache_mod._fallback_cache[session_key] = data
                    except Exception:
                        pass
                else:
                    # Fallback to normal bind without display_agent_id
                    await session_cache.bind(session_key, agent_uuid)
            else:
                await session_cache.bind(session_key, agent_uuid)
        except Exception as e:
            # WARNING level (v2.5.7): Cache failures can cause identity loss
            logger.warning(f"Redis cache write failed for session {session_key[:20]}...: {e}")

# =============================================================================
# DB HELPERS
# =============================================================================

async def _agent_exists_in_postgres(agent_uuid: str) -> bool:
    """Check if agent exists in PostgreSQL."""
    try:
        db = get_db()
        identity = await db.get_identity(agent_uuid)
        return identity is not None
    except Exception:
        return False

async def _get_agent_status(agent_uuid: str) -> Optional[str]:
    """Fetch agent's status from PostgreSQL (e.g., 'active', 'archived', 'deleted').

    Returns None if agent not found or on error.
    """
    try:
        db = get_db()
        identity = await db.get_identity(agent_uuid)
        if identity and hasattr(identity, "status"):
            return identity.status
        return None
    except Exception:
        return None

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

# =============================================================================
# LAZY CREATION HELPERS (v2.4.1+)
# =============================================================================

async def ensure_agent_persisted(
    agent_uuid: str,
    session_key: str,
    *,
    parent_agent_id: Optional[str] = None,
    spawn_reason: Optional[str] = None,
    thread_id: Optional[str] = None,
    thread_position: Optional[int] = None,
) -> bool:
    """
    Persist agent to PostgreSQL if not already persisted.

    Call this from write operations (process_agent_update, identity(name=...))
    to ensure the agent exists before recording state.

    Args:
        agent_uuid: The agent's UUID (from resolve_session_identity)
        session_key: The session key for session binding
        parent_agent_id: UUID of parent agent (for thread/fork lineage)
        spawn_reason: Why this fork was created
        thread_id: Thread this agent belongs to
        thread_position: Node position within thread

    Returns:
        True if newly persisted, False if already existed
    """
    try:
        db = get_db()
        # Note: db.init() is called once at startup (mcp_server.py:1306).
        # Do NOT call it here — it was creating a new connection pool on every request.

        identity = await db.get_identity(agent_uuid)
        agent_record = await db.get_agent(agent_uuid)

        if identity and agent_record:
            return False  # Already fully persisted

        if not agent_record:
            await db.upsert_agent(
                agent_id=agent_uuid,
                api_key="",
                status="active",
                parent_agent_id=parent_agent_id,
                spawn_reason=spawn_reason,
                thread_id=thread_id,
                thread_position=thread_position,
            )

        if not identity:
            await db.upsert_identity(
                agent_id=agent_uuid,
                api_key_hash="",
                parent_agent_id=parent_agent_id,
                metadata={
                    "source": "lazy_creation",
                    "created_at": datetime.now().isoformat(),
                    "total_updates": 0,  # Initialize counter for persistence
                    "thread_id": thread_id,
                    "thread_position": thread_position,
                    "node_index": thread_position,  # AgentMetadata uses node_index
                }
            )
            identity = await db.get_identity(agent_uuid)

        # Create session binding once we have a durable identity row.
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
# LABEL MANAGEMENT
# =============================================================================

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
            # Sync label into core.identities.metadata JSONB so both sources agree
            try:
                identity = await db.get_identity(agent_uuid)
                if identity:
                    await db.upsert_identity(
                        agent_id=agent_uuid,
                        api_key_hash="",
                        metadata={"label": label},
                    )
            except Exception as e:
                logger.debug(f"Could not sync label to identities metadata: {e}")

            # Sync label to runtime cache so compute_agent_signature can find it
            try:
                if agent_uuid in mcp_server.agent_metadata:
                    meta = mcp_server.agent_metadata[agent_uuid]
                    meta.label = label

                    # Generate structured_id if missing (migration for pre-v2.5.0 agents)
                    if not getattr(meta, 'structured_id', None):
                        try:
                            from ..support.naming_helpers import detect_interface_context, generate_structured_id
                            from ..context import get_context_client_hint
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
                    from src.agent_state import AgentMetadata
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
                        from ..support.naming_helpers import detect_interface_context, generate_structured_id
                        from ..context import get_context_client_hint
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
                    from .shared import _session_identities
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
