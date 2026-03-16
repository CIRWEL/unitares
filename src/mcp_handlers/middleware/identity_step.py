"""Step 1: Resolve Session Identity."""

import asyncio
from typing import Any, Dict

from src.logging_utils import get_logger

logger = get_logger(__name__)


async def resolve_identity(name: str, arguments: Dict[str, Any], ctx) -> Any:
    """Extract session identity, resolve onboard pin, bind agent."""
    # Unified session key derivation via SessionSignals + derive_session_key()
    from ..context import get_session_signals
    from ..identity.handlers import derive_session_key

    signals = get_session_signals()
    session_key = await derive_session_key(signals, arguments)
    client_session_id = arguments.get("client_session_id")

    logger.debug(
        f"[SESSION] dispatch entry: tool={name} session_key={session_key[:30] if session_key else 'None'}... "
        f"client_session_id={client_session_id!r} signals={signals.transport if signals else 'None'}"
    )

    # Resolve identity (Redis → PostgreSQL → Name Claim → Create)
    from ..identity.handlers import resolve_session_identity
    agent_name_hint = None
    if arguments:
        # Only use name for identity lookup if resume=True is explicitly passed
        # This prevents accidental identity collision when multiple sessions use same name
        resume_requested = arguments.get("resume", False)
        if resume_requested:
            agent_name_hint = arguments.get("agent_name") or (
                arguments.get("name") if name in ("identity", "onboard") else None
            )
        else:
            # Without resume, only use agent_name (not "name" parameter)
            agent_name_hint = arguments.get("agent_name")
    # Extract X-Agent-Id from SessionSignals (set at transport layer) or fallback to request headers
    x_agent_id_header = signals.x_agent_id if signals else None
    if not x_agent_id_header:
        try:
            from ..context import get_session_context
            ctx_data = get_session_context()
            req = ctx_data.get('request')
            if req and hasattr(req, 'headers'):
                x_agent_id_header = req.headers.get("x-agent-id") or req.headers.get("X-Agent-Id")
        except Exception:
            pass

    # X-Agent-Name auto-resume REMOVED (identity honesty refactor):
    # Silent name claims from transport headers bypass consent.
    # Agents must explicitly pass name= + resume=true in onboard/identity calls.

    # Use header as name-claim fallback only when no name hint from arguments
    if not agent_name_hint and x_agent_id_header:
        is_uuid = len(x_agent_id_header) == 36 and x_agent_id_header.count("-") == 4
        if not is_uuid:
            agent_name_hint = x_agent_id_header
            logger.debug(f"[DISPATCH] Using X-Agent-Id as name claim: {x_agent_id_header}")
    trajectory_sig = arguments.get("trajectory_signature") if arguments else None

    bound_agent_id = None
    identity_result = None
    try:
        # Middleware resolves the CURRENT session's binding (established by
        # onboard/identity earlier). resume=True is correct here — we are NOT
        # creating new identities, we are looking up the existing one.
        identity_result = await resolve_session_identity(
            session_key,
            agent_name=agent_name_hint,
            trajectory_signature=trajectory_sig,
            resume=True,
        )
        bound_agent_id = identity_result.get("agent_uuid")

        # PATH 2.75: X-Agent-Id UUID recovery
        # If session resolution created a NEW identity but X-Agent-Id header contains
        # a known UUID, rebind to the existing agent instead of creating a duplicate.
        # This handles reconnection when session key changes (e.g., Pi restart).
        if identity_result.get("created") and x_agent_id_header:
            is_uuid = len(x_agent_id_header) == 36 and x_agent_id_header.count("-") == 4
            if is_uuid:
                try:
                    from ..identity.handlers import _agent_exists_in_postgres, _cache_session
                    if await _agent_exists_in_postgres(x_agent_id_header):
                        logger.info(
                            f"[DISPATCH] X-Agent-Id recovery: rebinding session to existing "
                            f"agent {x_agent_id_header[:8]}... (was about to create {bound_agent_id[:8]}...)"
                        )
                        bound_agent_id = x_agent_id_header
                        identity_result["agent_uuid"] = x_agent_id_header
                        identity_result["created"] = False
                        identity_result["persisted"] = True
                        identity_result["source"] = "x_agent_id_recovery"
                        # Cache this session → UUID binding for future requests
                        await _cache_session(session_key, x_agent_id_header)
                except Exception as e:
                    logger.debug(f"[DISPATCH] X-Agent-Id recovery failed: {e}")

        # Mark dispatch-created identities as ephemeral
        if identity_result.get("created") and not identity_result.get("persisted"):
            identity_result["ephemeral"] = True
            identity_result["created_via"] = "dispatch"
            logger.info(f"[DISPATCH] Ephemeral identity created (not persisted): {bound_agent_id[:8]}...")

        # Update session TTL for persisted identities
        if identity_result.get("persisted"):
            for attempt in range(2):
                try:
                    from src.db import get_db
                    result = await get_db().update_session_activity(session_key)
                    break
                except Exception as e:
                    if attempt == 0:
                        await asyncio.sleep(0.05)
                    else:
                        logger.warning(f"[DISPATCH] Session TTL update failed for {session_key[:20]}...: {e}")
    except Exception as e:
        logger.debug(f"Could not resolve session identity: {e}")

    # Set context for this request
    from ..context import set_session_context
    client_hint = arguments.get("client_hint") if arguments else None
    context_token = set_session_context(
        session_key=session_key,
        client_session_id=client_session_id,
        agent_id=bound_agent_id,
        client_hint=client_hint,
    )

    logger.info(
        f"[DISPATCH_ENTRY] tool={name}, has_kwargs={'kwargs' in arguments}, "
        f"arg_keys={list(arguments.keys())[:5]}, "
        f"bound_agent_id={bound_agent_id[:8] + '...' if bound_agent_id else 'None'}"
    )

    ctx.session_key = session_key
    ctx.client_session_id = client_session_id
    ctx.bound_agent_id = bound_agent_id
    ctx.context_token = context_token
    ctx.client_hint = client_hint
    ctx.identity_result = identity_result
    return name, arguments, ctx
