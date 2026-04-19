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
from src.services.identity_payloads import (
    build_identity_diag_payload,
    build_identity_response_data,
    build_onboard_response_data,
)

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
    extract_token_agent_uuid,
    continuity_token_support_status,
)

# --- identity_persistence ---
from .persistence import (
    _redis_cache,
    _get_redis,
    _cache_session,
    _agent_exists_in_postgres,
    _get_agent_status,
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
    """Best-effort sync of refreshed structured agent_id to memory + DB.

    Updates both `agent_id` and `public_agent_id` in the in-memory metadata
    so lifecycle events and any other readers of `meta.agent_id` see the
    current identity — not the stale pre-rebadge value.
    """
    try:
        if agent_uuid in mcp_server.agent_metadata:
            meta = mcp_server.agent_metadata[agent_uuid]
            meta.agent_id = new_agent_id
            meta.public_agent_id = new_agent_id
    except Exception:
        pass
    try:
        db = get_db()
        await db.upsert_identity(
            agent_id=agent_uuid,
            api_key_hash="",
            metadata={"public_agent_id": new_agent_id, "agent_id": new_agent_id},
        )
    except Exception as e:
        logger.debug(f"[ONBOARD] Could not persist rebadged agent_id: {e}")


async def _collect_identity_aliases(
    agent_uuid: str,
    *,
    primary_agent_id: Optional[str] = None,
    label: Optional[str] = None,
) -> set[str]:
    """Collect acceptable aliases for one canonical UUID."""
    aliases = {str(agent_uuid)}
    for value in (primary_agent_id, label):
        if value:
            aliases.add(str(value))

    try:
        meta = mcp_server.agent_metadata.get(agent_uuid)
        if meta:
            for attr in ("public_agent_id", "structured_id", "label"):
                value = getattr(meta, attr, None)
                if value:
                    aliases.add(str(value))
    except Exception:
        pass

    try:
        from .shared import _session_identities

        for binding in _session_identities.values():
            if binding.get("bound_agent_id") == agent_uuid or binding.get("agent_uuid") == agent_uuid:
                for key in ("display_agent_id", "public_agent_id", "agent_label", "label"):
                    value = binding.get(key)
                    if value:
                        aliases.add(str(value))
    except Exception:
        pass

    try:
        db = get_db()
        identity = await db.get_identity(agent_uuid)
        metadata = getattr(identity, "metadata", None) or {}
        for key in ("public_agent_id", "agent_id", "structured_id", "label"):
            value = metadata.get(key)
            if value:
                aliases.add(str(value))
    except Exception:
        pass

    return aliases

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
    # Resolve session to identity (lazy — doesn't persist yet).
    # Name-claim was removed 2026-04-17: `name` is now a cosmetic label,
    # set via set_agent_label after the session resolves normally.
    name = arguments.get("name")

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
    Optional: Pass agent_uuid='...' to resume a known identity by UUID directly.
              Requires resume=true (default). Skips session/name resolution entirely.
              Returns error if UUID not found or not active — never creates a ghost.
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
    explicit_resume_binding = bool(arguments.get("client_session_id") or arguments.get("continuity_token"))

    def _identity_diag_payload(
        *,
        agent_uuid: str,
        agent_id: str,
        label: Optional[str],
        status: str,
    ) -> Dict[str, Any]:
        from .shared import make_client_session_id

        stable_session_id = make_client_session_id(agent_uuid)
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
            client_hint=arguments.get("client_hint"),
        )
        return build_identity_diag_payload(
            agent_uuid=agent_uuid,
            agent_id=agent_id,
            display_name=label,
            client_session_id=stable_session_id,
            continuity_source=continuity_source,
            continuity_support=continuity_support,
            continuity_token=continuity_token,
            identity_status=status,
        )

    def _identity_success(payload: Dict[str, Any], *, agent_uuid: Optional[str] = None) -> Sequence[TextContent]:
        response_arguments = dict(arguments)
        response_arguments["lite_response"] = True
        return success_response(payload, agent_id=agent_uuid, arguments=response_arguments)

    # PATH 0: Direct UUID lookup (resident agents with stored UUID)
    # Skips all session/name resolution — just verify the UUID exists and is active.
    _direct_uuid = arguments.get("agent_uuid")
    if _direct_uuid and resume:
        # Identity Honesty Part C: PATH 0 must prove UUID ownership.
        # Bare agent_uuid without a matching signed continuity_token would
        # let any caller resurrect any known UUID — effectively making UUIDs
        # lookup keys in disguise (invariant #4 violation). Require a token
        # whose `aid` claim matches the requested UUID.
        _partc_token_aid = None
        if arguments.get("continuity_token"):
            _partc_token_aid = extract_token_agent_uuid(str(arguments["continuity_token"]))
        _partc_owned = _partc_token_aid == _direct_uuid

        if not _partc_owned:
            from config.governance_config import identity_strict_mode
            _partc_mode = identity_strict_mode()
            if _partc_mode == "strict":
                return error_response(
                    (
                        "Bare agent_uuid resume is not permitted. Include "
                        "continuity_token (bound to this UUID) or call "
                        "identity(force_new=true) / onboard() to create a new identity."
                    ),
                    recovery={
                        "reason": "bare_uuid_resume_denied",
                        "agent_uuid": _direct_uuid,
                        "hint": (
                            "Resident agents should load continuity_token from their "
                            "anchor file and pass it on every identity() call."
                        ),
                    },
                )
            elif _partc_mode == "log":
                logger.warning(
                    "[IDENTITY_STRICT] Would reject PATH 0: agent_uuid=%s... without "
                    "matching continuity_token (token_aid=%s). Caller would fork a "
                    "session bound to a UUID it has not proven it owns. Upgrade caller "
                    "to pass continuity_token.",
                    _direct_uuid[:8],
                    (_partc_token_aid[:8] + "...") if _partc_token_aid else "none",
                )
            # mode == "off": unchanged behavior, no log

        # PATH 0 FAST: if the UUID has a live in-process monitor, trust it
        # and skip DB verification entirely. Anyio-deadlock-safe (no awaits).
        # Rationale: monitors are loaded at startup for all persisted agents,
        # so a hit here means the agent is known to governance. Worst case
        # is we briefly serve an agent that was just archived, which the
        # next full check-in will surface via the archival log path.
        #
        # This is the structural fix for the 34-Watcher-fork incident:
        # transient governance slowness can't cascade into forks when
        # UUID-direct resume has a synchronous fallback.
        try:
            from ..shared import get_mcp_server
            srv = get_mcp_server()
            monitors = getattr(srv, "monitors", None) if srv is not None else None
            if monitors is not None and _direct_uuid in monitors:
                try:
                    from ..context import update_context_agent_id, set_session_resolution_source
                    update_context_agent_id(_direct_uuid)
                    set_session_resolution_source("agent_uuid_direct_fastpath")
                except Exception:
                    pass
                payload = _identity_diag_payload(
                    agent_uuid=_direct_uuid,
                    agent_id=_direct_uuid,
                    label=None,
                    status="resumed",
                )
                payload.update({
                    "resumed": True,
                    "resumed_by_uuid": True,
                    "source": "monitor_cache",
                    "message": f"Resumed identity {_direct_uuid[:12]}... via in-process monitor cache",
                })
                return _identity_success(payload, agent_uuid=_direct_uuid)
        except Exception:
            # Any fast-path failure falls through to the DB-backed slow path.
            pass

        exists = await _agent_exists_in_postgres(_direct_uuid)
        if not exists:
            return error_response(
                f"Agent UUID {_direct_uuid[:12]}... not found",
                recovery={"reason": "uuid_not_found", "agent_uuid": _direct_uuid},
            )
        status = await _get_agent_status(_direct_uuid)
        if status != "active":
            return error_response(
                f"Agent UUID {_direct_uuid[:12]}... is not active (status={status})",
                recovery={"reason": "uuid_not_found", "agent_uuid": _direct_uuid, "status": status},
            )
        agent_id = await _get_agent_id_from_metadata(_direct_uuid) or _direct_uuid
        label = await _get_agent_label(_direct_uuid)
        # Update label if requested
        requested_name = arguments.get("name")
        if requested_name and requested_name != label:
            if await set_agent_label(_direct_uuid, requested_name, session_key=base_session_key):
                label = requested_name
        await _cache_session(base_session_key, _direct_uuid, display_agent_id=agent_id)
        try:
            from ..context import update_context_agent_id, set_session_resolution_source
            update_context_agent_id(_direct_uuid)
            set_session_resolution_source("agent_uuid_direct")
        except Exception:
            pass
        payload = _identity_diag_payload(
            agent_uuid=_direct_uuid,
            agent_id=agent_id,
            label=label,
            status="resumed",
        )
        payload.update({
            "resumed": True,
            "resumed_by_uuid": True,
            "message": f"Welcome back! Resumed identity '{label or agent_id}' via UUID",
        })
        return _identity_success(payload, agent_uuid=_direct_uuid)

    # PATH 2.5 (name-claim) removed 2026-04-17. `name` is now a cosmetic
    # label updated after the session resolves; it never drives lookup.
    name = arguments.get("name")

    # Extract agent UUID from continuity token for direct lookup fallback.
    # If session bindings expired, this allows rebinding without forking.
    _token_agent_uuid = None
    if arguments.get("continuity_token"):
        _token_agent_uuid = extract_token_agent_uuid(str(arguments["continuity_token"]))

    # STEP 1: Check for existing identity under BASE key first (unless force_new)
    # Pass resume= through so resolve_session_identity respects the flag
    existing_identity = None
    session_key = base_session_key

    if not force_new:
        existing_identity = await resolve_session_identity(
            base_session_key, persist=False, resume=resume,
            token_agent_uuid=_token_agent_uuid,
        )

        # Token-based resume failed — agent not found or not active
        if existing_identity.get("resume_failed"):
            return error_response(
                existing_identity.get("message", "Could not resume identity"),
                recovery={
                    "reason": "resume_failed",
                    "token_agent_uuid": existing_identity.get("token_agent_uuid"),
                    "hint": "Call onboard(force_new=true) to create a new identity.",
                }
            )

        if not existing_identity.get("created"):
            # EXISTING AGENT FOUND under base key (only happens when resume=True)
            agent_uuid = existing_identity.get("agent_uuid")
            agent_id = existing_identity.get("agent_id", agent_uuid)
            label = existing_identity.get("label")

            # FIX: Don't silently resume archived agents — warn the caller
            if existing_identity.get("archived"):
                logger.info(f"[IDENTITY] Found archived agent {agent_uuid[:8]}... — returning warning instead of silent resume")
                payload = _identity_diag_payload(
                    agent_uuid=agent_uuid,
                    agent_id=agent_id,
                    label=label,
                    status="archived",
                )
                payload.update({
                    "archived": True,
                    "resumed": False,
                    "message": f"Session maps to archived agent '{label or agent_id}'. Use onboard() to reactivate or force_new=true for a fresh identity.",
                    "hint": "onboard() will auto-reactivate this agent. force_new=true creates a new one.",
                    "options": {
                        "reactivate": "Call onboard() to resume this archived agent",
                        "fresh": "Call identity(force_new=true) or onboard(force_new=true) for a new identity"
                    }
                })
                return _identity_success(payload, agent_uuid=agent_uuid)

            logger.info(f"[IDENTITY] Resuming existing agent {agent_uuid[:8]}... (explicit resume=true)")

            # Update label if requested
            if arguments.get("name") and arguments.get("name") != label:
                success = await set_agent_label(agent_uuid, arguments.get("name"), session_key=session_key)
                if success:
                    label = arguments.get("name")

            payload = _identity_diag_payload(
                agent_uuid=agent_uuid,
                agent_id=agent_id,
                label=label,
                status="resumed",
            )
            payload.update({
                "resumed": True,
                "message": f"Welcome back! Resumed identity '{label or agent_id}'",
                "hint": "Use force_new=true to create a new identity instead"
            })
            return _identity_success(payload, agent_uuid=agent_uuid)

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

    # Persist newly-created identities before minting a continuity token.
    #
    # Previously identity() was "lazy": new agents only existed in-memory until
    # the caller also passed name=. But we still issued a continuity_token
    # referencing the in-memory UUID. The token looked durable, but any later
    # rebind via PATH 2.8 hit `agent not active` because the UUID was never
    # written to core.agents. Callers were left holding dead tokens, which
    # manifested as ghost identity proliferation (cf. d4d4370, 718ccd3).
    #
    # Fix: when identity() creates a fresh agent (result.created is True),
    # write it to PostgreSQL before returning so the token's promise is real.
    if result.get("created") and not result.get("persisted"):
        try:
            # parent_agent_id is only set when the caller explicitly asserted
            # succession (post-2026-04-16 EISV inheritance spec). Fingerprint
            # match no longer auto-claims lineage, so no predecessor_uuid to
            # read here.
            _parent = result.get("parent_agent_id")
            _spawn = result.get("spawn_reason") or ("new_session" if _parent else None)
            newly_persisted = await ensure_agent_persisted(
                agent_uuid,
                session_key,
                parent_agent_id=_parent,
                spawn_reason=_spawn,
            )
            if newly_persisted:
                logger.info(
                    f"[IDENTITY] Persisted fresh identity {agent_uuid[:8]}... "
                    f"(parent={_parent[:8] + '...' if _parent else 'none'})"
                )
                result["persisted"] = True
        except Exception as e:
            # Persistence failure is visible but not fatal — caller still gets
            # the identity in the response; the token just won't rebind later.
            logger.warning(
                f"[IDENTITY] Failed to persist fresh identity {agent_uuid[:8]}...: {e}"
            )

    # Get public/structured identity handles from runtime metadata.
    public_agent_id = result.get("public_agent_id") or agent_id
    structured_id = None
    try:
        if agent_uuid in mcp_server.agent_metadata:
            meta = mcp_server.agent_metadata[agent_uuid]
            public_agent_id = getattr(meta, "public_agent_id", None) or public_agent_id
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
    final_agent_id = public_agent_id or structured_id or agent_uuid
    user_name = result.get("label")

    # Derive client_session_id for session continuity
    from .shared import make_client_session_id
    client_session_id = make_client_session_id(agent_uuid)
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
    identity_status = "created" if result.get("created") else "resumed"

    response_data = build_identity_response_data(
        agent_uuid=agent_uuid,
        agent_id=final_agent_id,
        display_name=user_name,
        client_session_id=client_session_id,
        continuity_source=continuity_source,
        continuity_support=continuity_support,
        continuity_token=continuity_token,
        identity_status=identity_status,
        model_type=model_type,
        resumed=False if result.get("created") else (True if result.get("source") else None),
        session_continuity=result.get("session_continuity"),
        verbose=verbose,
    )

    # Auto-bind: automatically perform session binding so agents don't need a separate bind_session call
    auto_bind = coerce_bool(arguments.get("auto_bind", True))
    if auto_bind and not (existing_identity and existing_identity.get("archived")):
        try:
            from ..context import get_session_signals as _abs_signals
            mcp_signals = _abs_signals()
            mcp_key = await derive_session_key(mcp_signals)
            if mcp_key and mcp_key != base_session_key:
                await _perform_session_bind(
                    agent_uuid=agent_uuid,
                    session_key=mcp_key,
                    display_agent_id=final_agent_id,
                    source="identity_auto_bind",
                )
                response_data["auto_bound"] = True
        except Exception as e:
            logger.debug(f"[IDENTITY] Auto-bind failed (non-fatal): {e}")

    # Use lite_response to skip redundant agent_signature (identity already contains all that info)
    if arguments is None:
        arguments = {}
    arguments["lite_response"] = True
    return success_response(response_data, agent_id=final_agent_id, arguments=arguments)


async def _perform_session_bind(
    agent_uuid: str,
    session_key: str,
    display_agent_id: str = None,
    source: str = "auto_bind",
) -> dict:
    """Bind a session key to an agent UUID (Redis + PostgreSQL + sticky transport).

    Shared helper used by both identity() auto-bind and bind_session().
    All steps are best-effort — failures are logged but don't prevent binding.
    """
    bound_info = {"bound": False, "session_key": session_key[:20] + "..." if session_key else None}

    # 1. Redis cache
    try:
        await _cache_session(session_key, agent_uuid, display_agent_id=display_agent_id)
        bound_info["redis"] = True
    except Exception as e:
        logger.debug(f"[{source}] Redis cache failed (non-fatal): {e}")
        bound_info["redis"] = False

    # 2. PostgreSQL session
    try:
        db = get_db()
        if hasattr(db, "init"):
            await db.init()
        identity_record = await db.get_identity(agent_uuid)
        if identity_record:
            client_info = {"agent_uuid": agent_uuid, "bound_via": source}
            if display_agent_id and display_agent_id != agent_uuid:
                client_info["public_agent_id"] = display_agent_id
                client_info["agent_id"] = display_agent_id
            await db.create_session(
                session_id=session_key,
                identity_id=identity_record.identity_id,
                expires_at=datetime.now() + timedelta(hours=GovernanceConfig.SESSION_TTL_HOURS),
                client_type="mcp",
                client_info=client_info,
            )
            bound_info["postgres"] = True
    except Exception as e:
        logger.debug(f"[{source}] PostgreSQL session binding failed (non-fatal): {e}")
        bound_info["postgres"] = False

    # 3. Sticky transport
    try:
        from ..context import get_session_signals as _get_signals
        from ..middleware.identity_step import _transport_cache_key, update_transport_binding
        _signals = _get_signals()
        _tkey = _transport_cache_key(_signals)
        if _tkey:
            update_transport_binding(_tkey, agent_uuid, session_key, source)
            bound_info["transport"] = True
    except Exception:
        bound_info["transport"] = False

    bound_info["bound"] = True
    logger.info(f"[{source}] Bound session {session_key[:20]}... -> agent {agent_uuid[:8]}...")
    return bound_info


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
        accepted_aliases = await _collect_identity_aliases(
            target_uuid,
            primary_agent_id=target_agent_id,
            label=target_label,
        )
        if expected_agent_id not in accepted_aliases:
            return error_response(
                "agent_id mismatch for requested session binding",
                details={
                    "expected_agent_id": expected_agent_id,
                    "resolved_agent_id": target_agent_id,
                    "resolved_agent_uuid": target_uuid,
                    "accepted_aliases": sorted(accepted_aliases),
                    "client_session_id": client_session_id,
                },
                recovery={
                    "action": "Verify client_session_id belongs to the intended agent, or pass the correct agent_id/UUID.",
                    "hint": "Use identity() or get_governance_metrics() to confirm your active identity first.",
                }
            )

    # Rebind: cache the MCP session key → target agent UUID
    if mcp_session_key and mcp_session_key != client_session_id:
        await _perform_session_bind(target_uuid, mcp_session_key, display_agent_id=target_agent_id, source="bind_session")

    # Update request context so subsequent calls in this request use the correct agent
    try:
        from ..context import update_context_agent_id
        update_context_agent_id(target_uuid)
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

    # Extract agent UUID from continuity token for direct lookup fallback (PATH 2.8).
    # Token is a cryptographic proof of identity — stronger than name claim.
    _token_agent_uuid = None
    if arguments.get("continuity_token"):
        _token_agent_uuid = extract_token_agent_uuid(str(arguments["continuity_token"]))

    # STEP 1: Check if an identity already exists for this session (base key)
    # When resume=True (default): reuse existing identity
    # When resume=False: create new identity with predecessor link
    existing_identity = None
    created_fresh_identity = False  # Track if we got a fresh identity to persist
    _was_archived = False  # Track if agent was auto-unarchived
    if not force_new:
        # Token-based resume is the only name-free resume path (PATH 2.8).
        # Name-based reconnection was removed 2026-04-17 — a label alone is
        # not proof of identity. Callers who previously relied on
        # `onboard(name=X, resume=true)` must now pass agent_uuid or
        # continuity_token, or accept a fresh identity via force_new=true.
        if _token_agent_uuid and resume:
            existing_identity = await resolve_session_identity(
                base_session_key, persist=False, resume=resume,
                token_agent_uuid=_token_agent_uuid,
            )
            # Token-based resume failed — agent not found or not active
            if existing_identity.get("resume_failed"):
                return error_response(
                    existing_identity.get("message", "Could not resume identity"),
                    recovery={
                        "reason": "resume_failed",
                        "token_agent_uuid": existing_identity.get("token_agent_uuid"),
                        "hint": "Call onboard(force_new=true) to create a new identity.",
                    }
                )
        else:
            existing_identity = await resolve_session_identity(
                base_session_key, persist=False, resume=resume,
                token_agent_uuid=_token_agent_uuid,
            )
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
                from src.background_tasks import create_tracked_task
                create_tracked_task(
                    _create_spawned_edge_bg(agent_uuid, _parent_agent_id, _spawn_reason),
                    name="spawned_edge",
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

    # Persist the stable session ID too, not just the transport/base session key.
    # Otherwise a Redis miss on the returned client_session_id can fall through to
    # PATH 3 and create an unrelated UUID.
    await _perform_session_bind(
        agent_uuid,
        stable_session_id,
        display_agent_id=agent_id,
        source="onboard_stable_session",
    )

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

    public_agent_id = agent_id if agent_id and agent_id != agent_uuid else None
    structured_id = None
    try:
        # Atomic read via .get — avoids TOCTOU between `in` check and subscript
        # if another task mutates agent_metadata concurrently.
        meta = mcp_server.agent_metadata.get(agent_uuid)
        if meta is not None:
            public_agent_id = getattr(meta, "public_agent_id", None) or public_agent_id
            structured_id = getattr(meta, 'structured_id', None)
    except Exception:
        pass
    response_agent_id = public_agent_id or structured_id or f"agent_{agent_uuid[:8]}"

    tool_mode_info = None
    if verbose:
        try:
            from src.tool_modes import TOOL_MODE, get_tools_for_mode
            from src.tool_schemas import get_tool_definitions
            all_tools = get_tool_definitions()
            mode_tools = get_tools_for_mode(TOOL_MODE)
            tool_mode_info = {
                "current_mode": TOOL_MODE,
                "visible_tools": len(mode_tools),
                "total_tools": len(all_tools),
                "available_modes": ["minimal", "lite", "full"],
                "tip": f"You're seeing {len(mode_tools)}/{len(all_tools)} tools in '{TOOL_MODE}' mode. Use list_tools() for discovery, or ask for ?mode=full if you need more."
            }
        except Exception as e:
            logger.debug(f"Could not add tool_mode info: {e}")

    result = build_onboard_response_data(
        agent_uuid=agent_uuid,
        structured_agent_id=response_agent_id,
        agent_label=agent_label,
        stable_session_id=stable_session_id,
        is_new=is_new,
        force_new=force_new,
        client_hint=client_hint,
        was_archived=_was_archived,
        trajectory_result=trajectory_result,
        parent_agent_id=_parent_agent_id,
        thread_context=thread_context,
        verbose=verbose,
        continuity_source=continuity_source,
        continuity_support=continuity_support,
        continuity_token=continuity_token,
        system_activity=_get_system_evidence() if verbose else None,
        tool_mode_info=tool_mode_info,
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

    # Identity Honesty Part C: onboard-triggered orphan sweep REMOVED.
    # It was the driver of 'agent archived almost immediately' — catching
    # siblings of fresh onboards via the 2h zero_update_hours heuristic.
    # With ghost creation gated upstream (PATH 0 + FALLBACK 2), the nightly
    # sweep in src/background_tasks.py is sufficient. Users who want an
    # immediate sweep can still call the archive_orphan_agents tool.

    # Use lite_response to skip redundant signature
    arguments["lite_response"] = True
    return success_response(result, agent_id=agent_uuid, arguments=arguments)

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
