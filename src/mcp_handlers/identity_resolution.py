"""
Core identity resolution logic.

Houses resolve_session_identity, resolve_by_name_claim, and agent ID generation.
"""

from __future__ import annotations

from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import uuid
import re

from src.logging_utils import get_logger
from src.db import get_db
from .identity_persistence import (
    _get_redis,
    _cache_session,
    _agent_exists_in_postgres,
    _get_agent_label,
    _get_agent_id_from_metadata,
    _find_agent_by_label,
)

# Import GovernanceConfig with fallback defaults
try:
    from config.governance_config import GovernanceConfig
except ImportError:
    class GovernanceConfig:
        SESSION_TTL_SECONDS = 86400  # 24 hours
        SESSION_TTL_HOURS = 24

logger = get_logger(__name__)


# =============================================================================
# AGENT ID GENERATION (model+date format)
# =============================================================================

def _generate_agent_id(model_type: Optional[str] = None, client_hint: Optional[str] = None) -> str:
    """
    Generate agent_id in model+client+date format.

    Priority:
    1. model_type (e.g., "claude-opus-4-5") -> "Claude_Opus_4_5_20251227"
    2. client_hint (e.g., "cursor") -> "cursor_20251227"
    3. fallback -> "mcp_20251227"

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
        ("claude-opus-4", "claude-code") -> "claude-code-opus"
        ("claude-sonnet-4", None) -> "sonnet"
        (None, "cursor") -> "cursor"
        (None, None) -> None (can't generate)
    """
    parts = []

    # Client type first (if meaningful)
    if client_hint and client_hint not in ("unknown", "", "mcp"):
        parts.append(client_hint.strip().lower().replace(" ", "-"))

    # Model family (extract short name, drop version numbers)
    if model_type:
        model = model_type.strip().lower()
        # Extract model family: "claude-opus-4-5" -> "opus"
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


def _normalize_model_type(model_type: str) -> str:
    """Normalize model_type to a canonical family name for session key suffixing.

    Used by handle_identity_adapter and handle_onboard_v2 to prevent identity
    collision across different models from the same transport.

    Examples:
        "claude-opus-4-5" -> "claude"
        "gemini-pro" -> "gemini"
        "gpt-4o" -> "gpt"
    """
    normalized = model_type.lower().replace("-", "_").replace(".", "_")
    if "claude" in normalized:
        return "claude"
    elif "gemini" in normalized:
        return "gemini"
    elif "gpt" in normalized or "chatgpt" in normalized:
        return "gpt"
    elif "composer" in normalized or "cursor" in normalized:
        return "composer"
    elif "llama" in normalized:
        return "llama"
    return normalized


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

                        # Legacy format (pre-v2.5.2): treat as both agent_id and UUID fallback
                        # v1 identity deleted Feb 2026 — no new entries in this format

                        agent_uuid = cached_id

                        agent_id = cached_id



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

                        "agent_id": agent_id,   # Human-readable (model+date). UUID for lookup is agent_uuid.

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

                    # Legacy format (pre-v2.5.2): treat as both agent_id and UUID fallback

                    agent_uuid = stored_id

                    agent_id = stored_id



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

                    "agent_id": agent_id,   # Human-readable (model+date). UUID for lookup is agent_uuid.

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
    #
    # IDENTITY INTEGRITY FIX (v2.7.1): Auto-name claims now REQUIRE trajectory
    # signature verification. Without it, every fresh session of the same model
    # type silently inherits prior history and relational context — false continuity.
    # An agent ends up believing it has 30 visits to Lumen when it has none.
    #
    # Rule: only auto-claim an *existing* identity if trajectory_signature is
    # provided and passes verification. Without it, PATH 3 creates a fresh UUID
    # (the auto_label is still assigned so the new agent can be found later).
    if not agent_name and (model_type or client_hint) and trajectory_signature:
        auto_label = _generate_auto_label(model_type, client_hint)
        if auto_label:
            auto_result = await resolve_by_name_claim(
                auto_label, session_key, trajectory_signature
            )
            if auto_result:
                logger.info(f"[AUTO_NAME] Reused identity via auto-label '{auto_label}' (trajectory verified)")
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

            # Create agent in PostgreSQL with UUID as key (label set atomically)
            await db.upsert_agent(
                agent_id=agent_uuid,  # UUID is the primary key
                api_key="",  # Legacy field, not used
                status="active",
                label=label,  # Set auto-label at creation time
            )

            if label:
                logger.info(f"[AUTO_NAME] New agent '{label}' (uuid: {agent_uuid[:8]}...)")

            # Create identity record with agent_id (display name) in metadata
            identity_metadata = {
                "source": "identity_v2",
                "created_at": datetime.now().isoformat(),
                "agent_id": agent_id,  # Human-readable label (model+date)
                "model_type": model_type,
                "total_updates": 0,  # Initialize counter for persistence
            }
            if label:
                identity_metadata["label"] = label
            await db.upsert_identity(
                agent_id=agent_uuid,
                api_key_hash="",
                metadata=identity_metadata,
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
                "agent_id": agent_id,   # Human-readable (model+date). UUID for lookup is agent_uuid.
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
        "agent_id": agent_id,   # Human-readable (model+date). UUID for lookup is agent_uuid.
        "agent_uuid": agent_uuid,
        "display_name": None,
        "label": None,  # backward compat
        "created": True,
        "persisted": False,
        "source": "memory_only",
    }


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
