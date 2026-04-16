"""Step 1: Resolve Session Identity."""

import asyncio
import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.logging_utils import get_logger

logger = get_logger(__name__)

# =============================================================================
# STICKY TRANSPORT BINDING CACHE
# =============================================================================
# Once identity resolves on the first tool call from a transport fingerprint,
# reuse it for all subsequent calls. This prevents identity fragmentation
# caused by derive_session_key() producing different keys for different tools
# when using the IP:UA fingerprint path.

_TRANSPORT_CACHE_TTL = 7200  # 2 hours
_TRANSPORT_CACHE_MAX = 10_000


@dataclass
class TransportBinding:
    """Cached identity binding for a transport fingerprint."""
    agent_uuid: str
    session_key: str
    bound_at: float  # monotonic timestamp
    source: str  # e.g. "redis", "postgres", "created"


_transport_identity_cache: Dict[str, TransportBinding] = {}


def _transport_cache_key(signals) -> Optional[str]:
    """Compute sticky cache key from transport signals.

    Uses IP:UA fingerprint as the stable anchor, combined with MCP session ID
    when available. This prevents multiple MCP sessions from the same host
    (e.g. parallel Claude Code processes) from collapsing onto one identity.

    Returns None only for explicitly stable headers (x_session_id, x_client_id,
    oauth_client_id) where caching adds no value.
    """
    if not signals:
        return None
    # Truly stable paths — client controls the session ID, no caching needed
    if signals.x_session_id or signals.x_client_id or signals.oauth_client_id:
        return None
    if not signals.ip_ua_fingerprint:
        return None
    # Include mcp_session_id in the key when present so parallel MCP sessions
    # from the same IP:UA (e.g. multiple Claude Code processes on localhost)
    # each get their own cached identity instead of converging to one UUID.
    if signals.mcp_session_id:
        return f"sticky:{signals.ip_ua_fingerprint}:{signals.mcp_session_id}"
    # Fingerprint-only for REST callers and non-MCP transports.
    return f"sticky:{signals.ip_ua_fingerprint}"


def update_transport_binding(key: str, agent_uuid: str, session_key: str, source: str) -> None:
    """Set or update a sticky transport binding (in-memory + Redis)."""
    _transport_identity_cache[key] = TransportBinding(
        agent_uuid=agent_uuid,
        session_key=session_key,
        bound_at=_time.monotonic(),
        source=source,
    )
    _evict_stale_entries()
    # Persist to Redis so bindings survive server restarts
    _persist_binding_to_redis(key, agent_uuid, session_key, source)


def _persist_binding_to_redis(key: str, agent_uuid: str, session_key: str, source: str) -> None:
    """Best-effort fire-and-forget write of transport binding to Redis."""
    try:
        asyncio.get_running_loop()  # raises RuntimeError if no loop
        from src.background_tasks import create_tracked_task
        create_tracked_task(
            _persist_binding_to_redis_async(key, agent_uuid, session_key, source),
            name="redis_persist_binding",
        )
    except RuntimeError:
        pass  # No event loop — skip Redis persist


async def _persist_binding_to_redis_async(key: str, agent_uuid: str, session_key: str, source: str) -> None:
    """Write transport binding to Redis."""
    try:
        from src.cache.redis_client import get_redis
        import json
        redis = await get_redis()
        if not redis:
            return
        redis_key = f"transport_binding:{key}"
        await redis.setex(redis_key, _TRANSPORT_CACHE_TTL, json.dumps({
            "agent_uuid": agent_uuid,
            "session_key": session_key,
            "source": source,
        }))
    except Exception as e:
        logger.debug(f"[STICKY] Redis persist failed: {e}")


async def _load_binding_from_redis(key: str) -> Optional[TransportBinding]:
    """Try to recover a transport binding from Redis after restart."""
    try:
        from src.cache.redis_client import get_redis
        import json
        redis = await get_redis()
        if not redis:
            return None
        data = await redis.get(f"transport_binding:{key}")
        if not data:
            return None
        parsed = json.loads(data)
        binding = TransportBinding(
            agent_uuid=parsed["agent_uuid"],
            session_key=parsed["session_key"],
            bound_at=_time.monotonic(),  # Treat as fresh since Redis TTL handles expiry
            source=parsed.get("source", "redis_recovery"),
        )
        # Warm the in-memory cache
        _transport_identity_cache[key] = binding
        logger.debug(f"[STICKY] Redis recovery for {key}: agent={binding.agent_uuid[:8]}...")
        return binding
    except Exception as e:
        logger.debug(f"[STICKY] Redis recovery failed: {e}")
        return None


def invalidate_transport_binding(key: str) -> None:
    """Remove a sticky transport binding (e.g. on force_new)."""
    _transport_identity_cache.pop(key, None)
    try:
        asyncio.get_running_loop()
        from src.background_tasks import create_tracked_task
        create_tracked_task(_invalidate_binding_redis_async(key), name="redis_invalidate_binding")
    except RuntimeError:
        pass


async def _invalidate_binding_redis_async(key: str) -> None:
    try:
        from src.cache.redis_client import get_redis
        redis = await get_redis()
        if redis:
            await redis.delete(f"transport_binding:{key}")
    except Exception:
        pass


def _evict_stale_entries() -> None:
    """Lazy TTL eviction + max size enforcement."""
    now = _time.monotonic()
    # TTL eviction
    stale = [k for k, v in _transport_identity_cache.items()
             if (now - v.bound_at) > _TRANSPORT_CACHE_TTL]
    for k in stale:
        del _transport_identity_cache[k]
    # Max size eviction (oldest first)
    if len(_transport_identity_cache) > _TRANSPORT_CACHE_MAX:
        sorted_keys = sorted(_transport_identity_cache, key=lambda k: _transport_identity_cache[k].bound_at)
        for k in sorted_keys[:len(_transport_identity_cache) - _TRANSPORT_CACHE_MAX]:
            del _transport_identity_cache[k]


async def resolve_identity(name: str, arguments: Dict[str, Any], ctx) -> Any:
    """Extract session identity, resolve onboard pin, bind agent."""
    # Unified session key derivation via SessionSignals + derive_session_key()
    from ..context import get_session_signals
    from ..identity.handlers import derive_session_key

    signals = get_session_signals()
    client_session_id = arguments.get("client_session_id")
    force_new = arguments.get("force_new", False)
    continuity_token = arguments.get("continuity_token")

    # --- Sticky transport binding: early return if cached ---
    transport_key = _transport_cache_key(signals)
    ctx._transport_key = transport_key

    _has_agent_uuid = bool(arguments and arguments.get("agent_uuid"))
    if (transport_key
        and not force_new
        and not client_session_id
        and not continuity_token
        and not _has_agent_uuid):
        cached = _transport_identity_cache.get(transport_key)
        # On miss, try Redis (survives restarts)
        if not cached:
            cached = await _load_binding_from_redis(transport_key)
        if cached and (_time.monotonic() - cached.bound_at) < _TRANSPORT_CACHE_TTL:
            logger.debug(
                f"[STICKY] Cache hit for {transport_key}: agent={cached.agent_uuid[:8]}... "
                f"session_key={cached.session_key[:30]}..."
            )
            # Reuse cached binding — set context and return early
            from ..context import set_session_context
            client_hint = arguments.get("client_hint") if arguments else None
            context_token = set_session_context(
                session_key=cached.session_key,
                client_session_id=client_session_id,
                agent_id=cached.agent_uuid,
                client_hint=client_hint,
            )
            ctx.session_key = cached.session_key
            ctx.client_session_id = client_session_id
            ctx.bound_agent_id = cached.agent_uuid
            ctx.context_token = context_token
            ctx.client_hint = client_hint
            ctx.identity_result = {"agent_uuid": cached.agent_uuid, "source": "sticky_cache"}
            return name, arguments, ctx

    # Invalidate cache on force_new
    if force_new and transport_key:
        invalidate_transport_binding(transport_key)

    session_key = await derive_session_key(signals, arguments)

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

    # PATH 0 passthrough: when caller supplies agent_uuid, skip session
    # resolution entirely. The identity/onboard handler will verify the UUID
    # exists; the middleware just needs to bind the session to it so context
    # is set correctly. This prevents ghost creation for resident agents.
    _direct_uuid = arguments.get("agent_uuid") if arguments else None
    if _direct_uuid and name in ("identity", "onboard"):
        from ..context import set_session_context
        client_hint = arguments.get("client_hint") if arguments else None
        context_token = set_session_context(
            session_key=session_key,
            client_session_id=client_session_id,
            agent_id=_direct_uuid,
            client_hint=client_hint,
        )
        ctx.session_key = session_key
        ctx.client_session_id = client_session_id
        ctx.bound_agent_id = _direct_uuid
        ctx.context_token = context_token
        ctx.client_hint = client_hint
        ctx.identity_result = {"agent_uuid": _direct_uuid, "source": "agent_uuid_passthrough"}
        ctx._transport_key = transport_key
        # Populate sticky cache so subsequent tool calls reuse this UUID
        if transport_key:
            update_transport_binding(transport_key, _direct_uuid, session_key, "agent_uuid_passthrough")
        logger.info(f"[DISPATCH] PATH 0 passthrough: agent_uuid={_direct_uuid[:8]}... (skipped resolution)")
        return name, arguments, ctx

    # Extract agent UUID from continuity token for PATH 2.8 direct lookup
    _token_agent_uuid = None
    if arguments and arguments.get("continuity_token"):
        try:
            from ..identity.session import extract_token_agent_uuid
            _token_agent_uuid = extract_token_agent_uuid(str(arguments["continuity_token"]))
        except Exception:
            pass

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
            token_agent_uuid=_token_agent_uuid,
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

    # --- Populate sticky cache after successful resolution ---
    if transport_key and bound_agent_id:
        source = identity_result.get("source", "unknown") if identity_result else "unknown"
        update_transport_binding(transport_key, bound_agent_id, session_key, source)

    return name, arguments, ctx
