"""
Identity V2 - Simplified Session-to-UUID Resolution

Re-export facade — functions have moved to focused modules.
Existing imports continue to work unchanged.

Modules:
  identity_session      — session key derivation, fingerprinting, pin operations
  identity_persistence  — agent persistence, caching, label management
  identity_resolution   — core identity resolution, agent ID generation
"""

from typing import Optional, Dict, Any, Sequence
from datetime import datetime, timedelta
import os
import re

from mcp.types import TextContent

from src.logging_utils import get_logger
from src.db import get_db
from ..utils import success_response, error_response
from ..decorators import mcp_tool
from ..support.coerce import coerce_bool

from config.governance_config import GovernanceConfig

logger = get_logger(__name__)

# --- identity_session (leaf) ---
from .session import (
    derive_session_key,
    _extract_base_fingerprint,
    ua_hash_from_header,
    _PIN_TTL,
    lookup_onboard_pin,
    set_onboard_pin,
    create_continuity_token,
    resolve_continuity_token,
    continuity_token_support_status,
)

# --- identity_persistence ---
from .persistence import (
    _redis_cache,
    _get_redis,
    _cache_session,
    _agent_exists_in_postgres,
    _get_agent_label,
    _get_agent_id_from_metadata,
    _find_agent_by_label,
    ensure_agent_persisted,
    set_agent_label,
)

# --- identity_resolution ---
from .resolution import (
    _generate_agent_id,
    _generate_auto_label,
    _normalize_model_type,
    resolve_session_identity,
    resolve_by_name_claim,
)
from src.mcp_handlers.shared import lazy_mcp_server as mcp_server
# =============================================================================
# SYSTEM EVIDENCE HELPER (real data for onboard response)
# =============================================================================

def _get_system_evidence() -> dict:
    """Compute system activity summary from real data.

    Iterates in-memory agent_metadata and loaded monitors.
    No DB calls — fast, read-only, graceful fallback.
    """
    try:
        counts = {"active": 0, "paused": 0, "archived": 0, "other": 0}
        total_checkins = 0
        pauses_issued = 0

        for _aid, meta in mcp_server.agent_metadata.items():
            status = getattr(meta, "status", None)
            if status in counts:
                counts[status] += 1
            else:
                counts["other"] += 1
            total_checkins += getattr(meta, "total_updates", 0) or 0

            # Count pause lifecycle events
            for evt in getattr(meta, "lifecycle_events", []) or []:
                evt_type = evt.get("event") if isinstance(evt, dict) else None
                if evt_type in ("paused", "pause"):
                    pauses_issued += 1

        # Aggregate verdict distribution from loaded monitors
        verdicts: dict[str, int] = {}
        for _mid, monitor in mcp_server.monitors.items():
            for entry in getattr(monitor, "decision_history", []) or []:
                action = entry.get("action") if isinstance(entry, dict) else None
                if action:
                    verdicts[action] = verdicts.get(action, 0) + 1

        # Count dialectic sessions (if accessible)
        dialectic_sessions = 0
        try:
            if hasattr(mcp_server, "dialectic_sessions"):
                dialectic_sessions = len(mcp_server.dialectic_sessions)
        except Exception:
            pass

        result = {
            "agents": {k: v for k, v in counts.items() if v > 0},
            "total_checkins": total_checkins,
        }
        if verdicts:
            result["verdicts"] = verdicts
        if pauses_issued:
            result["pauses_issued"] = pauses_issued
        if dialectic_sessions:
            result["dialectic_sessions"] = dialectic_sessions
        return result
    except Exception:
        return {}

# =============================================================================
# DATE CONTEXT HELPER (only used by onboard handler)
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


def _infer_model_type_from_signals(explicit_model_type: Optional[str]) -> Optional[str]:
    """Infer model type from transport User-Agent when caller omits model_type."""
    if explicit_model_type:
        return explicit_model_type
    try:
        from ..context import get_session_signals
        signals = get_session_signals()
        ua = (signals.user_agent or "").lower() if signals else ""
        if not ua:
            return explicit_model_type

        # Prefer Codex-specific matches first.
        if re.search(r"gpt[-\s_]?5\.3", ua) and "codex" in ua:
            return "gpt-5.3-codex"
        if re.search(r"gpt[-\s_]?5\.4", ua) and "codex" in ua:
            return "gpt-5.4-codex"
        if re.search(r"gpt[-\s_]?5", ua) and "codex" in ua:
            return "gpt-5-codex"
        if "codex" in ua:
            return "codex"
        if "gpt" in ua or "openai" in ua or "chatgpt" in ua:
            return "gpt"
        if "claude" in ua or "anthropic" in ua:
            return "claude"
        if "gemini" in ua or "google" in ua:
            return "gemini"
    except Exception:
        pass
    return explicit_model_type


def _model_family(model_type: Optional[str]) -> Optional[str]:
    if not model_type:
        return None
    raw = model_type.lower()
    if "gpt" in raw or "openai" in raw or "chatgpt" in raw or "codex" in raw:
        return "gpt"
    if "claude" in raw or "anthropic" in raw:
        return "claude"
    if "gemini" in raw or "google" in raw:
        return "gemini"
    return None


def _should_rebadge_agent_id(current_agent_id: Optional[str], model_type: Optional[str], client_hint: Optional[str]) -> bool:
    """Return True when legacy structured IDs clearly mismatch current runtime."""
    if not current_agent_id or not model_type:
        return False
    aid = current_agent_id.lower()
    family = _model_family(model_type)
    if family == "gpt" and ("gpt" not in aid and "codex" not in aid):
        return True
    if family == "claude" and "claude" not in aid:
        return True
    if family == "gemini" and "gemini" not in aid:
        return True
    if family == "gpt" and "claude" in aid:
        return True
    if family == "claude" and ("gpt" in aid or "codex" in aid):
        return True
    if client_hint and client_hint.lower() == "cursor" and "claude_code" in aid and family == "gpt":
        return True
    return False


async def _persist_rebadged_agent_id(agent_uuid: str, new_agent_id: str) -> None:
    """Best-effort sync of refreshed structured agent_id to memory + DB."""
    try:
        if agent_uuid in mcp_server.agent_metadata:
            mcp_server.agent_metadata[agent_uuid].structured_id = new_agent_id
    except Exception:
        pass
    try:
        db = get_db()
        await db.upsert_identity(
            agent_id=agent_uuid,
            api_key_hash="",
            metadata={"agent_id": new_agent_id},
        )
    except Exception as e:
        logger.debug(f"[ONBOARD] Could not persist rebadged agent_id: {e}")

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
        identity()              -> Returns your UUID and label (lazy, not persisted)
        identity(name="X")      -> Sets your label to X, returns UUID (persists agent)

    This tool does NOT look up other agents. Use get_agent_metadata for that.
    """
    # Resolve session to identity (lazy - doesn't persist yet)
    # Try name-based resolution first (PATH 2.5)
    name = arguments.get("name")
    if name:
        trajectory_sig = arguments.get("trajectory_signature")
        name_result = await resolve_by_name_claim(name, session_key, trajectory_signature=trajectory_sig)
        if name_result:
            # Handle rejection (trajectory required or mismatch)
            if name_result.get("rejected"):
                return {
                    "success": False,
                    "error": name_result.get("reason", "identity_claim_rejected"),
                    "message": name_result.get("message", "Identity claim rejected"),
                    "hint": "Provide trajectory_signature for identity verification, or use force_new=true to create a new identity.",
                }

            agent_uuid = name_result["agent_uuid"]
            agent_id = name_result["agent_id"]
            display_name = name_result.get("label")
            from .shared import make_client_session_id
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
                    "instruction": "Your session is auto-bound. You only need client_session_id if tools don't recognize you.",
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

@mcp_tool("identity", timeout=10.0)
async def handle_identity_adapter(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    IDENTITY - Who am I? Auto-creates identity if first call.

    Simplified v2 implementation with 3 paths:
    - Redis cache (fast)
    - PostgreSQL lookup
    - Create new agent

    Optional: Pass name='...' to set your display name.
    Optional: Pass model_type='...' to create distinct identity per model.
    Optional: Pass resume=false to force a new identity (with predecessor link).
    Optional: Pass force_new=true to create new identity with no predecessor link.
    Defaults to resuming existing identity if one exists for this session.
    """
    arguments = arguments or {}
    force_new = arguments.get("force_new", False)
    resume = arguments.get("resume", True)
    model_type = arguments.get("model_type")

    # Derive base session key (unified)
    from ..context import get_session_signals
    signals = get_session_signals()
    base_session_key = await derive_session_key(signals, arguments)
    normalized_model = None

    # PATH 2.5: Name-based identity claim (only when resume=true, before session resolution)
    # If the caller provides name= + resume=true and isn't forcing new, try to reconnect
    name = arguments.get("name")
    if name and not force_new and resume:
        trajectory_sig = arguments.get("trajectory_signature")
        name_result = await resolve_by_name_claim(name, base_session_key, trajectory_signature=trajectory_sig)
        if name_result:
            # Handle rejection (trajectory required or mismatch)
            if name_result.get("rejected"):
                return error_response(
                    name_result.get("message", "Identity claim rejected"),
                    recovery={
                        "reason": name_result.get("reason"),
                        "hint": "Provide trajectory_signature for identity verification, or use force_new=true to create a new identity.",
                    }
                )

            agent_uuid = name_result["agent_uuid"]
            agent_id = name_result["agent_id"]
            label = name_result.get("label")
            logger.info(f"[IDENTITY] Resolved '{name}' via name claim -> {agent_uuid[:8]}...")

            # Update request context so signature matches
            try:
                from ..context import update_context_agent_id
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
    # Pass resume= through so resolve_session_identity respects the flag
    existing_identity = None
    session_key = base_session_key

    if not force_new:
        existing_identity = await resolve_session_identity(base_session_key, persist=False, resume=resume)
        if not existing_identity.get("created"):
            # EXISTING AGENT FOUND under base key (only happens when resume=True)
            agent_uuid = existing_identity.get("agent_uuid")
            agent_id = existing_identity.get("agent_id", agent_uuid)
            label = existing_identity.get("label")

            # FIX: Don't silently resume archived agents — warn the caller
            if existing_identity.get("archived"):
                logger.info(f"[IDENTITY] Found archived agent {agent_uuid[:8]}... — returning warning instead of silent resume")
                return success_response({
                    "uuid": agent_uuid,
                    "agent_id": agent_id,
                    "display_name": label,
                    "archived": True,
                    "resumed": False,
                    "message": f"Session maps to archived agent '{label or agent_id}'. Use onboard() to reactivate or force_new=true for a fresh identity.",
                    "hint": "onboard() will auto-reactivate this agent. force_new=true creates a new one.",
                    "options": {
                        "reactivate": "Call onboard() to resume this archived agent",
                        "fresh": "Call identity(force_new=true) or onboard(force_new=true) for a new identity"
                    }
                })

            logger.info(f"[IDENTITY] Resuming existing agent {agent_uuid[:8]}... (explicit resume=true)")

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

    # model_type is passed through for agent_id generation, but does NOT fork session keys.
    # All identities for a session use the base session key to prevent fragmentation.

    # Call simplified handler with model_type for agent_id generation
    result = await handle_identity_v2(arguments, session_key, model_type=model_type)
    agent_id = result.get("agent_id", result["agent_uuid"])
    agent_uuid = result["agent_uuid"]

    # CRITICAL: Update request context so signature in response matches resolved identity
    try:
        from ..context import update_context_agent_id
        update_context_agent_id(agent_uuid)
    except Exception as e:
        logger.debug(f"Could not update context in identity: {e}")

    # Get structured_id from metadata (three-tier identity model v2.5.0+)
    structured_id = None
    try:
        if agent_uuid in mcp_server.agent_metadata:
            meta = mcp_server.agent_metadata[agent_uuid]
            structured_id = getattr(meta, 'structured_id', None)

            # If model_type provided and structured_id doesn't include it, regenerate
            if model_type and structured_id and normalized_model and normalized_model not in structured_id:
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
    client_session_id = base_session_key
    continuity_token = create_continuity_token(
        agent_uuid,
        client_session_id,
        model_type=model_type,
        client_hint=arguments.get("client_hint"),
    )
    try:
        from ..context import get_session_resolution_source
        continuity_source = get_session_resolution_source()
    except Exception:
        continuity_source = None
    continuity_support = continuity_token_support_status()

    verbose = coerce_bool(arguments.get("verbose"), default=False) if arguments else False

    response_data = {
        "uuid": agent_uuid,
        "agent_id": final_agent_id,
        "display_name": user_name,
        "client_session_id": client_session_id,
    }
    if model_type:
        response_data["model_type"] = model_type
    if continuity_token:
        response_data["continuity_token"] = continuity_token
    if result.get("created"):
        response_data["resumed"] = False
    elif result.get("source"):
        response_data["resumed"] = True

    # Verbose fields — gated behind verbose=true
    if verbose:
        response_data["quick_reference"] = {
            "for_knowledge_graph": user_name or final_agent_id,
            "for_session_continuity": client_session_id,
            "for_internal_lookup": agent_uuid,
            "to_set_display_name": "identity(name='YourName')"
        }
        if continuity_token:
            response_data["quick_reference"]["for_strong_resume"] = continuity_token

        # Session continuity guidance
        if result.get("session_continuity"):
            response_data["session_continuity"] = dict(result["session_continuity"])
        else:
            response_data["session_continuity"] = {
                "client_session_id": client_session_id,
                "instruction": "Your session is auto-bound. You only need client_session_id if tools don't recognize you.",
            }
            if continuity_token:
                response_data["session_continuity"]["continuity_token"] = continuity_token
                response_data["session_continuity"]["instruction"] = (
                    "Prefer continuity_token for robust resume. "
                    "Use client_session_id when token support is unavailable."
                )
        response_data["session_continuity"]["resolution_source"] = continuity_source
        response_data["session_continuity"]["token_support"] = continuity_support

    # Use lite_response to skip redundant agent_signature (identity already contains all that info)
    if arguments is None:
        arguments = {}
    arguments["lite_response"] = True
    return success_response(response_data, agent_id=final_agent_id, arguments=arguments)


@mcp_tool("bind_session", timeout=5.0)
async def handle_bind_session(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Bind current MCP session to an existing agent identity.

    Bridges the identity gap between REST hooks (which onboard via curl)
    and MCP Streamable HTTP (which uses a different session key).

    Call this once at session start with the client_session_id from your
    startup hook context.
    """
    arguments = arguments or {}
    strict = coerce_bool(arguments.get("strict"))
    resume_requested = coerce_bool(arguments.get("resume"))

    # Safety guard: prevent accidental cross-session reattachment.
    # Callers must explicitly opt in to rebind with resume=true, or use strict mode.
    if not resume_requested and not strict:
        return error_response(
            "bind_session requires explicit resume=true (or strict=true) to prevent accidental reattachment",
            recovery={
                "action": "Pass resume=true when intentionally restoring a prior identity.",
                "example": "bind_session(client_session_id='agent-xxxx', resume=true)",
                "alternative": "Use onboard() for fresh/new identity bootstrap.",
            }
        )

    client_session_id = arguments.get("client_session_id")
    expected_agent_id = arguments.get("agent_id")
    if not client_session_id and arguments.get("continuity_token"):
        from ..context import get_session_signals
        token_signals = get_session_signals()
        client_session_id = resolve_continuity_token(
            str(arguments.get("continuity_token")),
            model_type=arguments.get("model_type"),
            user_agent=token_signals.user_agent if token_signals else None,
        )
    if not client_session_id:
        return error_response("client_session_id or continuity_token is required")
    if strict and not expected_agent_id:
        return error_response(
            "strict bind_session requires agent_id",
            recovery={
                "action": "Provide agent_id (UUID or display agent_id) with strict=true.",
                "example": "bind_session(client_session_id='agent-xxxx', agent_id='Claude_Code_20260315', strict=true)",
            }
        )

    # Get the current MCP session key (the one we want to rebind)
    from ..context import get_session_signals
    signals = get_session_signals()
    mcp_session_key = await derive_session_key(signals)

    # Resolve the agent from the provided client_session_id
    # resume=True is correct here — bind_session is explicitly resuming an existing identity
    target_identity = await resolve_session_identity(client_session_id, persist=False, resume=True)
    if not target_identity or target_identity.get("created"):
        return error_response(
            f"No existing agent found for client_session_id '{client_session_id[:20]}...'. "
            "Ensure the session-start hook onboarded successfully."
        )

    target_uuid = target_identity["agent_uuid"]
    target_label = target_identity.get("label")
    target_agent_id = target_identity.get("agent_id", target_uuid)

    # Guard against accidental cross-binding by allowing callers to pin
    # bind_session to a specific identity (UUID or display agent_id).
    if expected_agent_id:
        expected_agent_id = str(expected_agent_id).strip()
        if expected_agent_id not in (target_uuid, target_agent_id):
            return error_response(
                "agent_id mismatch for requested session binding",
                details={
                    "expected_agent_id": expected_agent_id,
                    "resolved_agent_id": target_agent_id,
                    "resolved_agent_uuid": target_uuid,
                    "client_session_id": client_session_id,
                },
                recovery={
                    "action": "Verify client_session_id belongs to the intended agent, or pass the correct agent_id/UUID.",
                    "hint": "Use identity() or get_governance_metrics() to confirm your active identity first.",
                }
            )

    # Rebind: cache the MCP session key → target agent UUID
    if mcp_session_key and mcp_session_key != client_session_id:
        await _cache_session(mcp_session_key, target_uuid, display_agent_id=target_agent_id)

        # Also create a PostgreSQL session binding for the MCP key
        try:
            db = get_db()
            if hasattr(db, "init"):
                await db.init()
            identity_record = await db.get_identity(target_uuid)
            if identity_record:
                await db.create_session(
                    session_id=mcp_session_key,
                    identity_id=identity_record.identity_id,
                    expires_at=datetime.now() + timedelta(hours=GovernanceConfig.SESSION_TTL_HOURS),
                    client_type="mcp",
                    client_info={"agent_uuid": target_uuid, "bound_via": "bind_session"}
                )
        except Exception as e:
            logger.debug(f"[BIND_SESSION] PostgreSQL session binding failed (non-fatal): {e}")

        logger.info(
            f"[BIND_SESSION] Bound MCP session {mcp_session_key[:20]}... -> "
            f"agent {target_label or target_agent_id} ({target_uuid[:8]}...)"
        )

    # Update request context so subsequent calls in this request use the correct agent
    try:
        from ..context import update_context_agent_id
        update_context_agent_id(target_uuid)
    except Exception:
        pass

    # Update sticky transport binding so subsequent tool calls use this identity
    try:
        from ..context import get_session_signals as _get_signals
        from ..middleware.identity_step import _transport_cache_key, update_transport_binding
        _signals = _get_signals()
        _tkey = _transport_cache_key(_signals)
        if _tkey:
            update_transport_binding(_tkey, target_uuid, mcp_session_key or "", "bind_session")
    except Exception:
        pass

    return success_response({
        "bound": True,
        "agent_uuid": target_uuid,
        "agent_id": target_agent_id,
        "display_name": target_label,
        "mcp_session_key": mcp_session_key[:20] + "..." if mcp_session_key else None,
        "message": f"MCP session bound to agent '{target_label or target_agent_id}'",
    })


@mcp_tool("onboard", timeout=15.0)
async def handle_onboard_v2(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    ONBOARD - Single entry point for new agents.

    This is THE portal tool. Call it first, get back everything you need:
    - Your identity (auto-created)
    - Ready-to-use templates for next calls
    - Client-specific guidance

    Returns a "toolcard" payload with next_calls array.
    """
    from ..shared import get_mcp_server

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
    force_new = coerce_bool(arguments.get("force_new"), default=False)  # Force new identity creation
    model_type = _infer_model_type_from_signals(arguments.get("model_type"))

    # Thread identity parameters (honest forking)
    _parent_agent_id = arguments.get("parent_agent_id")  # UUID of predecessor
    _spawn_reason = arguments.get("spawn_reason")  # compaction|subagent|new_session|explicit
    _thread_id_hint = arguments.get("thread_id")  # Explicit thread to join

    # Auto-detect client_hint from transport if not provided
    client_hint = arguments.get("client_hint")
    if not client_hint or client_hint == "unknown":
        from ..context import get_context_client_hint
        client_hint = get_context_client_hint() or "unknown"

    # Derive base session key (unified — pin lookup integrated in derive_session_key)
    from ..context import get_session_signals
    signals = get_session_signals()
    base_session_key = await derive_session_key(signals, arguments)
    normalized_model = None

    # Session continuity: resume existing identity by default.
    # Agents can pass resume=false for a new identity, or force_new=true for a clean break.
    resume = coerce_bool(arguments.get("resume"), default=True)

    # STEP 1: Check if an identity already exists for this session (base key)
    # When resume=True (default): reuse existing identity
    # When resume=False: create new identity with predecessor link
    existing_identity = None
    created_fresh_identity = False  # Track if we got a fresh identity to persist
    _was_archived = False  # Track if agent was auto-unarchived
    if not force_new:
        # Name-based reconnection ONLY if resume=True is explicitly passed
        # This prevents accidental identity collision when multiple sessions use same name
        if name and resume:
            trajectory_sig = arguments.get("trajectory_signature")
            existing_by_name = await resolve_by_name_claim(name, base_session_key, trajectory_signature=trajectory_sig)
            if existing_by_name:
                # Handle rejection (trajectory required or mismatch)
                if existing_by_name.get("rejected"):
                    return error_response(
                        existing_by_name.get("message", "Identity claim rejected"),
                        recovery={
                            "reason": existing_by_name.get("reason"),
                            "hint": "Provide trajectory_signature for identity verification, or use force_new=true to create a new identity.",
                        }
                    )
                existing_identity = existing_by_name
                agent_uuid = existing_by_name["agent_uuid"]
                agent_id = existing_by_name["agent_id"]
                label = existing_by_name.get("label")
                logger.info(f"[ONBOARD] Resumed '{name}' via name claim -> {agent_uuid[:8]}...")
            else:
                existing_identity = await resolve_session_identity(base_session_key, persist=False, resume=resume)
        else:
            existing_identity = await resolve_session_identity(base_session_key, persist=False, resume=resume)
        if not existing_identity.get("created"):
            if existing_identity.get("archived"):
                # ARCHIVED AGENT — auto-unarchive with same UUID (only when resume=True)
                if resume:
                    agent_uuid = existing_identity.get("agent_uuid")
                    agent_id = existing_identity.get("agent_id", agent_uuid)
                    label = existing_identity.get("label")
                    logger.info(f"[ONBOARD] Found archived agent {agent_uuid[:8]}... — auto-unarchiving")
                    try:
                        db = get_db()
                        await db.update_agent_fields(agent_uuid, status="active")
                        try:
                            srv = get_mcp_server()
                            if agent_uuid in srv.agent_metadata:
                                srv.agent_metadata[agent_uuid].status = "active"
                                srv.agent_metadata[agent_uuid].archived_at = None
                        except Exception:
                            pass
                        try:
                            from src.cache import get_metadata_cache
                            await get_metadata_cache().invalidate(agent_uuid)
                        except Exception:
                            pass
                        try:
                            await srv.load_metadata_async(force=True)
                        except Exception:
                            pass
                        logger.info(f"[ONBOARD] Auto-unarchived agent {agent_uuid[:8]}...")
                        _was_archived = True
                    except Exception as e:
                        logger.warning(f"[ONBOARD] Could not unarchive agent: {e}")
                # If resume=False, archived agent is ignored — fall through to create new
            elif resume:
                # Explicit resume: reuse existing UUID
                agent_uuid = existing_identity.get("agent_uuid")
                agent_id = existing_identity.get("agent_id", agent_uuid)
                label = existing_identity.get("label")
                logger.info(f"[ONBOARD] Resuming existing identity {agent_uuid[:8]}... (explicit resume=true)")
            # If resume=False and not archived: existing_identity.created will be True
            # (resolve_session_identity with resume=False skips to PATH 3)
        else:
            # NEW AGENT - got a fresh identity from persist=False call
            # CRITICAL FIX (v2.5.7): Capture the fresh identity to persist it directly
            # instead of calling resolve_session_identity again (which could create a different UUID
            # if Redis caching failed silently)
            created_fresh_identity = True
            agent_uuid = existing_identity.get("agent_uuid")
            agent_id = existing_identity.get("agent_id", agent_uuid)
            # IDENTITY HONESTY: Wire predecessor from resolve_session_identity
            # when resume=False found an existing identity but created a new UUID
            if not _parent_agent_id and existing_identity.get("predecessor_uuid"):
                _parent_agent_id = existing_identity["predecessor_uuid"]
                if not _spawn_reason:
                    _spawn_reason = "new_session"
            logger.info(f"[ONBOARD] Created fresh identity {agent_uuid[:8]}... (will persist)")

            # Use base session key — model_type goes into metadata, not session key
            session_key = base_session_key
    else:
        # force_new requested — use base session key
        session_key = base_session_key

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
            # THREAD IDENTITY: Create/join thread for new agent
            _thread_id = None
            _thread_position = None
            try:
                from src.thread_identity import generate_thread_id, infer_spawn_reason
                db = get_db()

                _thread_id = _thread_id_hint or generate_thread_id(session_key)
                await db.create_or_get_thread(_thread_id)
                _thread_position = await db.claim_thread_position(_thread_id)

                # Get existing nodes to infer spawn reason
                existing_nodes = await db.get_thread_nodes(_thread_id)
                # Exclude self (just claimed position but not yet persisted)
                prior_nodes = [n for n in existing_nodes if n.get("agent_id") != agent_uuid]
                if not _spawn_reason:
                    _spawn_reason = infer_spawn_reason(arguments, prior_nodes)

                logger.info(
                    f"[THREAD] Agent {agent_uuid[:8]}... -> thread {_thread_id[:12]} "
                    f"position {_thread_position} reason={_spawn_reason}"
                )
            except Exception as e:
                logger.debug(f"[THREAD] Could not assign thread (non-fatal): {e}")

            # Persist the identity we got from the persist=False call
            newly_persisted = await ensure_agent_persisted(
                agent_uuid, session_key,
                parent_agent_id=_parent_agent_id,
                spawn_reason=_spawn_reason,
                thread_id=_thread_id,
                thread_position=_thread_position,
            )
            if newly_persisted:
                logger.info(f"[ONBOARD] Persisted fresh identity {agent_uuid[:8]}... to PostgreSQL")
                # Sync parent_agent_id to in-memory metadata for EISV inheritance
                if _parent_agent_id:
                    try:
                        from src.agent_metadata_model import agent_metadata as _agent_metadata
                        from src.agent_metadata_persistence import get_or_create_metadata
                        meta = get_or_create_metadata(agent_uuid)
                        meta.parent_agent_id = _parent_agent_id
                        meta.spawn_reason = _spawn_reason
                    except Exception as e:
                        logger.debug(f"[ONBOARD] Could not sync parent to metadata: {e}")
            else:
                logger.debug(f"[ONBOARD] Fresh identity {agent_uuid[:8]}... was already persisted")

            # Create SPAWNED edge in AGE graph (non-blocking)
            if _parent_agent_id:
                import asyncio
                asyncio.create_task(
                    _create_spawned_edge_bg(agent_uuid, _parent_agent_id, _spawn_reason)
                )

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
        from ..context import update_context_agent_id
        update_context_agent_id(agent_uuid)
    except Exception as e:
        logger.debug(f"Could not update context in onboard: {e}")

    # Refresh stale structured IDs when runtime model/client clearly changed.
    # Keeps UUID continuity while fixing misattribution (e.g., Claude label in Cursor+Codex).
    if _should_rebadge_agent_id(agent_id, model_type, client_hint):
        refreshed_agent_id = _generate_agent_id(model_type, client_hint)
        if refreshed_agent_id and refreshed_agent_id != agent_id:
            await _persist_rebadged_agent_id(agent_uuid, refreshed_agent_id)
            agent_id = refreshed_agent_id
            identity["agent_id"] = refreshed_agent_id
            logger.info(f"[ONBOARD] Rebadged agent_id -> {refreshed_agent_id}")

    # Set label if requested (and different from current)
    if name and name != agent_label:
        success = await set_agent_label(agent_uuid, name, session_key=session_key)
        if success:
            agent_label = name
            # Refresh identity object
            identity["label"] = name
        else:
            logger.warning(f"[ONBOARD] set_agent_label returned False for {agent_uuid[:8]}... name={name}")
            # Fallback: use the name for this response even if DB persistence failed
            if agent_label is None:
                agent_label = name
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
                logger.info(f"[TRAJECTORY] Stored genesis for {agent_uuid[:8]}... at onboard")
        except Exception as e:
            logger.debug(f"[TRAJECTORY] Could not store genesis at onboard: {e}")
            # Non-blocking - trajectory is optional

    # STEP 3: Generate stable session ID
    # Import helper to ensure consistent format
    from .shared import make_client_session_id
    stable_session_id = make_client_session_id(agent_uuid)

    # STEP 4: Register binding under stable session ID (in v2 cache)
    # This allows future calls using stable_session_id to find the agent
    # even if the transport session key changes
    await _cache_session(stable_session_id, agent_uuid, display_agent_id=agent_id)

    # Also register in O(1) prefix index (legacy support)
    try:
        from .shared import _register_uuid_prefix
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
        await set_onboard_pin(
            base_fp,
            agent_uuid,
            stable_session_id,
            client_hint=client_hint,
            model_type=model_type,
            user_agent=signals.user_agent if signals else None,
        )
    except Exception as e:
        logger.warning(f"[ONBOARD_PIN] Could not set pin: {e}")

    # STEP 5: Build thread context (async — must happen before sync helper)
    thread_context = None
    try:
        db = get_db()
        thread_info = await db.get_agent_thread_info(agent_uuid)
        if thread_info and thread_info.get("thread_id"):
            _tid = thread_info["thread_id"]
            all_nodes = await db.get_thread_nodes(_tid)
            from src.thread_identity import build_fork_context
            thread_context = build_fork_context(
                agent_uuid=agent_uuid,
                thread_id=_tid,
                nodes=all_nodes,
                spawn_reason=_spawn_reason,
            )
    except Exception as e:
        logger.debug(f"[THREAD] Could not build thread context: {e}")

    # STEP 6: Build response
    verbose = coerce_bool(arguments.get("verbose"), default=False)
    result = _build_onboard_response(
        agent_uuid=agent_uuid,
        agent_id=agent_id,
        agent_label=agent_label,
        stable_session_id=stable_session_id,
        model_type=model_type,
        is_new=is_new,
        force_new=force_new,
        client_hint=client_hint,
        _was_archived=_was_archived,
        trajectory_result=trajectory_result,
        _parent_agent_id=_parent_agent_id,
        _spawn_reason=_spawn_reason,
        thread_context=thread_context,
        verbose=verbose,
    )

    # Temporal narrator — contextual time awareness (silence by default)
    try:
        from src.temporal import build_temporal_context
        temporal = await build_temporal_context(agent_uuid, get_db())
        if temporal:
            result["temporal_context"] = temporal
    except Exception:
        pass  # Temporal narrator is non-critical

    logger.info(f"[ONBOARD] Agent {agent_uuid[:8]}... onboarded (is_new={is_new}, label={agent_label})")

    # Fire-and-forget: auto-archive ephemeral agents (0 updates, older than 2 hours)
    import asyncio
    asyncio.create_task(_auto_archive_ephemeral_agents())

    # Use lite_response to skip redundant signature
    arguments["lite_response"] = True
    return success_response(result, agent_id=agent_uuid, arguments=arguments)

def _build_onboard_response(
    *,
    agent_uuid: str,
    agent_id: str,
    agent_label: Optional[str],
    stable_session_id: str,
    model_type: Optional[str],
    is_new: bool,
    force_new: bool,
    client_hint: str,
    _was_archived: bool,
    trajectory_result: Optional[dict],
    _parent_agent_id: Optional[str],
    _spawn_reason: Optional[str],
    thread_context: Optional[dict] = None,
    verbose: bool = False,
) -> dict:
    """Build the onboard response payload (templates, tips, welcome, thread context)."""
    try:
        from ..context import get_session_resolution_source
        continuity_source = get_session_resolution_source()
    except Exception:
        continuity_source = None
    continuity_support = continuity_token_support_status()
    continuity_token = create_continuity_token(
        agent_uuid,
        stable_session_id,
        model_type=model_type,
        client_hint=client_hint,
    )

    next_calls = [
        {
            "tool": "process_agent_update",
            "why": "Log your work. Call after completing tasks.",
            "args_min": {
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
            "args_min": {},
            "args_full": {
                "client_session_id": stable_session_id
            }
        },
        {
            "tool": "identity",
            "why": "Rename yourself or check identity later",
            "args_min": {},
            "args_full": {
                "client_session_id": stable_session_id,
                "name": "YourName"
            }
        }
    ]
    if continuity_token:
        for call in next_calls:
            args_full = call.get("args_full")
            if isinstance(args_full, dict):
                args_full["continuity_token"] = continuity_token

    # Client-specific tips
    client_tips = {
        "chatgpt": "ChatGPT loses session state. ALWAYS include client_session_id in every call.",
        "cursor": "Cursor maintains sessions well. client_session_id optional but recommended.",
        "claude_desktop": "Claude Desktop has stable sessions. client_session_id optional.",
        "unknown": "For best session continuity, include client_session_id in all tool calls."
    }

    # Get structured_id
    structured_id = agent_id if agent_id and agent_id != agent_uuid else None
    if not structured_id:
        try:
            if agent_uuid in mcp_server.agent_metadata:
                meta = mcp_server.agent_metadata[agent_uuid]
                structured_id = getattr(meta, 'structured_id', None)
        except Exception:
            pass

    # Determine friendly name
    if not structured_id:
        structured_id = f"agent_{agent_uuid[:8]}"
    friendly_name = agent_label or structured_id

    # Welcome message — embed session ID directly in welcome so agents can't miss it
    if thread_context:
        if thread_context["is_root"]:
            welcome = (
                f"Your session ID is `{stable_session_id}`. "
                f"You are node 1 in thread {thread_context['thread_id'][:12]}."
            )
        else:
            pred = thread_context.get("predecessor")
            pred_desc = f" (position {pred['position']})" if pred and pred.get("position") else ""
            welcome = (
                f"Your session ID is `{stable_session_id}`. "
                f"You are node {thread_context['position']} in thread {thread_context['thread_id'][:12]}. "
                f"A predecessor exists{pred_desc}."
            )
        welcome_message = thread_context["honest_message"]
    elif is_new:
        welcome = f"Welcome! Your session ID is `{stable_session_id}`. Pass this as `client_session_id` in all calls."
        welcome_message = "Your identity is created. Use the templates below to get started."
    elif _was_archived:
        welcome = f"Reactivated '{friendly_name}'. Session: `{stable_session_id}`."
        welcome_message = f"Your agent was archived and has been reactivated with the same identity. Pass `client_session_id: \"{stable_session_id}\"` in all tool calls for attribution."
    else:
        welcome = f"Resumed identity '{friendly_name}'. Session: `{stable_session_id}`."
        welcome_message = (
            "Existing identity reused. "
            f"Pass `client_session_id: \"{stable_session_id}\"` in all tool calls for consistent attribution."
        )

    # Trim date_context to ground truth signal only
    date_now = datetime.now()
    date_context = {
        "date": date_now.strftime('%Y-%m-%d'),
        "source": "mcp-server",
    }

    result = {
        "success": True,
        "welcome": welcome,

        # Three-tier identity model
        "uuid": agent_uuid,
        "agent_id": structured_id,
        "display_name": agent_label,

        "is_new": is_new,

        # Session continuity
        "client_session_id": stable_session_id,

        # Date context (trimmed to ground truth)
        "date_context": date_context,

        # Single-line next step
        "next_step": "Call process_agent_update with response_text describing your work",
    }

    # Verbose fields — gated behind verbose=true
    if verbose:
        result["welcome_message"] = welcome_message
        result["force_new_applied"] = force_new
        result["session_continuity"] = {
            "client_session_id": stable_session_id,
            "instruction": "Your session is auto-bound. You only need client_session_id if tools don't recognize you.",
            "tip": client_tips.get(client_hint, client_tips["unknown"]),
            "resolution_source": continuity_source,
            "token_support": continuity_support,
        }
        result["next_calls_ref"] = "unitares://skill#workflow"
        result["next_calls"] = next_calls
        result["system_activity"] = _get_system_evidence()
        result["skill_resource"] = {
            "uri": "unitares://skill",
            "tip": "Read this MCP resource for full framework orientation instead of calling list_tools/describe_tool",
        }

    # Add thread context to response (honest forking)
    if thread_context:
        result["thread_context"] = thread_context
    if continuity_token:
        result["continuity_token"] = continuity_token
        if "session_continuity" in result:
            result["session_continuity"]["continuity_token"] = continuity_token
            result["session_continuity"]["instruction"] = (
                "Prefer continuity_token for robust resume across session-key changes. "
                "Use client_session_id when token support is unavailable."
            )

    # Add tool mode and workflow guidance only in verbose mode
    if verbose:
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

        if is_new or force_new:
            result["workflow"] = {
                "step_1": "Copy client_session_id from above",
                "step_2": "Do your work",
                "step_3": "Call process_agent_update with response_text describing what you did",
                "loop": "Repeat steps 2-3. Check metrics with get_governance_metrics when curious."
            }

    # Add predecessor info for new instances continuing a trajectory
    if _parent_agent_id and not force_new:
        result["predecessor"] = {
            "uuid": _parent_agent_id,
            "note": "Previous instance in this trajectory. Your state was inherited from it."
        }

    # Add auto-resume notice for reactivated agents
    if _was_archived:
        result["auto_resumed"] = True
        result["previous_status"] = "archived"

    # Include trajectory result if genesis was stored
    if trajectory_result:
        result["trajectory"] = trajectory_result
        result["trajectory"]["trust_tier"] = {
            "tier": 1,
            "name": "emerging",
            "reason": "Genesis stored at onboard. Identity will mature with behavioral consistency.",
        }

    return result

# =============================================================================
# TRAJECTORY IDENTITY VERIFICATION TOOL
# =============================================================================

@mcp_tool("verify_trajectory_identity", timeout=10.0)
async def handle_verify_trajectory_identity(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    VERIFY_TRAJECTORY_IDENTITY - Two-tier identity verification via trajectory signature.

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
    from ..context import get_context_agent_id
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
    GET_TRAJECTORY_STATUS - Check trajectory identity status for an agent.

    Returns information about the agent's trajectory identity including:
    - Whether genesis signature exists
    - Current signature details
    - Lineage similarity (if both exist)
    - Drift detection status

    No arguments required - uses current session identity.
    """
    # Get agent UUID from context
    from ..context import get_context_agent_id
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

async def _auto_archive_ephemeral_agents():
    """Fire-and-forget: archive agents with 0 updates older than 2 hours."""
    try:
        from datetime import timezone
        cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
        archived = 0
        db = get_db()
        for agent_id, meta in list(mcp_server.agent_metadata.items()):
            if meta.status != "active":
                continue
            if meta.total_updates > 0:
                continue
            # Check age via last_update or created_at
            last = meta.last_update
            if not last:
                continue
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if last_dt >= cutoff:
                    continue
            except Exception:
                continue
            # Archive it
            try:
                await db.update_agent_fields(agent_id, status="archived")
                meta.status = "archived"
                archived += 1
            except Exception:
                pass
        if archived:
            logger.info(f"[AUTO_ARCHIVE] Archived {archived} ephemeral agent(s) (0 updates, >2h old)")
    except Exception as e:
        logger.debug(f"[AUTO_ARCHIVE] Cleanup failed (non-fatal): {e}")


async def _create_spawned_edge_bg(
    child_id: str, parent_id: str, reason: str | None
):
    """Create SPAWNED edge in AGE graph (fire-and-forget background task)."""
    try:
        db = get_db()
        from src.db.age_queries import create_spawned_edge, create_agent_node
        # Ensure both Agent nodes exist
        q, p = create_agent_node(parent_id)
        await db.graph_query(q, p)
        q, p = create_agent_node(child_id)
        await db.graph_query(q, p)
        # Create edge
        q, p = create_spawned_edge(parent_id, child_id, spawn_reason=reason)
        await db.graph_query(q, p)
        logger.info(f"[SPAWNED] Created edge {parent_id[:8]}... -> {child_id[:8]}...")
    except Exception as e:
        logger.debug(f"SPAWNED edge creation failed (non-fatal): {e}")
