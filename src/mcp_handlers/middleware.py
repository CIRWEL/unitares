"""
Dispatch Middleware — Pipeline steps for tool dispatch.

Each step is a standalone async function: (name, arguments, ctx) → (name, arguments, ctx) or list[TextContent].
Returning a list short-circuits the pipeline with that response.
"""

import asyncio
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple, Union

from mcp.types import TextContent

from src.logging_utils import get_logger
from ..rate_limiter import get_rate_limiter
from .utils import error_response
from .error_helpers import rate_limit_error

logger = get_logger(__name__)

# Type alias for middleware return
MiddlewareResult = Union[
    Tuple[str, Dict[str, Any], "DispatchContext"],  # continue
    list,  # short-circuit
]


@dataclass
class DispatchContext:
    """State that flows between dispatch middleware steps."""
    session_key: Optional[str] = None
    client_session_id: Optional[str] = None
    bound_agent_id: Optional[str] = None
    context_token: Optional[object] = None
    trajectory_confidence_token: Optional[object] = None
    migration_note: Optional[str] = None
    original_name: Optional[str] = None
    client_hint: Optional[str] = None
    identity_result: Optional[dict] = None


# ============================================================
# Step 1: Resolve Session Identity
# ============================================================

async def resolve_identity(name: str, arguments: Dict[str, Any], ctx: DispatchContext) -> MiddlewareResult:
    """Extract session identity, resolve onboard pin, bind agent."""
    client_session_id = arguments.get("client_session_id")
    request_state_id = None

    try:
        from .context import get_session_context
        session_ctx = get_session_context()
        request_state_id = session_ctx.get('governance_client_id')
        if not request_state_id:
            req = session_ctx.get('request')
            if req and hasattr(req, 'state'):
                request_state_id = getattr(req.state, 'governance_client_id', None)
    except Exception:
        pass

    # Onboard pin lookup
    transport_fingerprint = request_state_id
    if not transport_fingerprint:
        try:
            from .context import get_context_session_key
            transport_fingerprint = get_context_session_key()
        except Exception:
            pass

    logger.debug(
        f"[ONBOARD_PIN] dispatch entry: tool={name} client_session_id={client_session_id!r} "
        f"request_state_id={request_state_id!r} transport_fingerprint={transport_fingerprint!r}"
    )

    if not client_session_id and transport_fingerprint:
        try:
            from .identity_v2 import _extract_base_fingerprint, lookup_onboard_pin
            base_fp = _extract_base_fingerprint(transport_fingerprint)
            pinned_session_id = await lookup_onboard_pin(base_fp)
            if pinned_session_id:
                client_session_id = pinned_session_id
                arguments["client_session_id"] = pinned_session_id
                logger.info(
                    f"[ONBOARD_PIN] Injected client_session_id={pinned_session_id} "
                    f"for tool={name} from pin recent_onboard:{base_fp}"
                )
        except Exception as e:
            logger.debug(f"[ONBOARD_PIN] Pin lookup failed: {e}")

    # Derive session key
    from .identity_v2 import _derive_session_key
    session_key = client_session_id or request_state_id or _derive_session_key(arguments)

    # Resolve identity (Redis → PostgreSQL → Name Claim → Create)
    from .identity_v2 import resolve_session_identity
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
    # Always extract X-Agent-Id header — needed for both name-claim fallback
    # and PATH 2.75 UUID recovery (even when agent_name is in arguments).
    x_agent_id_header = None
    try:
        from .context import get_session_context
        ctx_data = get_session_context()
        req = ctx_data.get('request')
        if req and hasattr(req, 'headers'):
            x_agent_id_header = req.headers.get("x-agent-id") or req.headers.get("X-Agent-Id")
    except Exception:
        pass
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
        identity_result = await resolve_session_identity(
            session_key,
            agent_name=agent_name_hint,
            trajectory_signature=trajectory_sig,
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
                    from .identity_v2 import _agent_exists_in_postgres, _cache_session
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
    from .context import set_session_context
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


# ============================================================
# Step 2: Verify Trajectory Identity
# ============================================================

async def verify_trajectory(name: str, arguments: Dict[str, Any], ctx: DispatchContext) -> MiddlewareResult:
    """Non-blocking trajectory signature verification."""
    try:
        traj_sig = arguments.get("trajectory_signature") if arguments else None
        if traj_sig and isinstance(traj_sig, dict) and ctx.bound_agent_id:
            from src.trajectory_identity import TrajectorySignature, verify_trajectory_identity
            from .context import set_trajectory_confidence

            sig = TrajectorySignature.from_dict(traj_sig)
            verification = await verify_trajectory_identity(ctx.bound_agent_id, sig)

            if verification and not verification.get("error"):
                coherence_sim = verification.get("tiers", {}).get("coherence", {}).get("similarity")
                lineage_sim = verification.get("tiers", {}).get("lineage", {}).get("similarity")
                sims = [s for s in [coherence_sim, lineage_sim] if s is not None]
                if sims:
                    traj_conf = min(sims)
                    ctx.trajectory_confidence_token = set_trajectory_confidence(traj_conf)

                if not verification.get("verified"):
                    logger.warning(
                        f"[TRAJECTORY] Verification FAILED for {ctx.bound_agent_id[:8]}...: "
                        f"failed_tiers={verification.get('failed_tiers', [])}"
                    )
    except Exception as e:
        logger.debug(f"[TRAJECTORY] Verification skipped: {e}")

    return name, arguments, ctx


# ============================================================
# Step 3: Unwrap kwargs
# ============================================================

async def unwrap_kwargs(name: str, arguments: Dict[str, Any], ctx: DispatchContext) -> MiddlewareResult:
    """Handle MCP clients that wrap arguments in kwargs."""
    if "kwargs" in arguments:
        kwargs_val = arguments["kwargs"]
        if isinstance(kwargs_val, str):
            try:
                kwargs_parsed = json.loads(kwargs_val)
                if isinstance(kwargs_parsed, dict):
                    del arguments["kwargs"]
                    arguments.update(kwargs_parsed)
                    logger.info(f"[DISPATCH_KWARGS] Unwrapped from string: {list(kwargs_parsed.keys())}")
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Failed to parse kwargs string: {e}")
        elif isinstance(kwargs_val, dict):
            del arguments["kwargs"]
            arguments.update(kwargs_val)
            logger.info(f"[DISPATCH_KWARGS] Unwrapped from dict: {list(kwargs_val.keys())}")

    return name, arguments, ctx


# ============================================================
# Step 4: Resolve Tool Alias
# ============================================================

async def resolve_alias(name: str, arguments: Dict[str, Any], ctx: DispatchContext) -> MiddlewareResult:
    """Resolve tool aliases and inject action parameters."""
    from .tool_stability import resolve_tool_alias

    ctx.original_name = name
    actual_name, alias_info = resolve_tool_alias(name)

    if alias_info:
        ctx.migration_note = alias_info.migration_note
        name = actual_name

        if alias_info.inject_action and "action" not in arguments:
            arguments["action"] = alias_info.inject_action
            logger.debug(f"[ALIAS] Injected action='{alias_info.inject_action}' for consolidated tool '{actual_name}'")

    return name, arguments, ctx


# ============================================================
# Step 5: Inject Session Identity
# ============================================================

async def inject_identity(name: str, arguments: Dict[str, Any], ctx: DispatchContext) -> MiddlewareResult:
    """Auto-inject agent_id from session, prevent impersonation."""
    try:
        from .context import get_context_agent_id
        bound_id = get_context_agent_id()
        provided_id = arguments.get("agent_id")

        if bound_id:
            if not provided_id:
                # Browsable data tools should NOT auto-filter by agent
                browsable_data_tools = {
                    "search_knowledge_graph", "query_knowledge_graph", "list_knowledge_graph",
                    "list_dialectic_sessions", "get_dialectic_session", "dialectic"
                }
                logger.info(
                    f"[DISPATCH] name={name}, in browsable_data_tools={name in browsable_data_tools}, "
                    f"bound_id={bound_id[:8] if bound_id else None}..."
                )
                if name not in browsable_data_tools:
                    arguments["agent_id"] = bound_id
                    logger.debug(f"Injected session-bound agent_id: {bound_id}")
            elif provided_id != bound_id:
                # Prevent impersonation
                identity_tools = {"status"}
                dialectic_tools = {
                    "submit_thesis", "submit_antithesis", "submit_synthesis",
                    "request_dialectic_review"
                }

                # Check label match
                is_label_match = False
                try:
                    from .shared import get_mcp_server
                    mcp_server = get_mcp_server()
                    if bound_id in mcp_server.agent_metadata:
                        meta = mcp_server.agent_metadata[bound_id]
                        if getattr(meta, 'label', None) == provided_id:
                            is_label_match = True
                            logger.debug(f"Label match allowed: {provided_id} -> {bound_id}")
                except Exception:
                    pass

                # Operator tools that act on OTHER agents (dashboard resume/archive/observe)
                operator_tools = {
                    "agent", "observe_agent", "detect_stuck_agents",
                    "archive_agent", "archive_old_test_agents",
                    "direct_resume_if_safe", "operator_resume_agent",
                    "ping_agent",
                }
                if name not in identity_tools and name not in dialectic_tools and name not in operator_tools and not is_label_match:
                    return [error_response(
                        f"Session mismatch: you are bound as '{bound_id}' but requested '{provided_id}'",
                        details={
                            "error_type": "identity_mismatch",
                            "bound_agent_id": bound_id,
                            "requested_agent_id": provided_id,
                        },
                        recovery={
                            "action": "Remove agent_id parameter (session binding handles identity)",
                            "note": "Each session is bound to one agent. Identity auto-binds on first tool call.",
                            "related_tools": ["identity"]
                        }
                    )]
        elif provided_id:
            # REST client with X-Agent-Id but no session binding
            logger.warning(f"[IDENTITY] No session binding but agent_id provided: {provided_id}. V2 may have failed.")
            arguments["agent_id"] = provided_id
        else:
            # No binding and no agent_id
            identity_tools = {"status", "list_tools", "health_check", "get_server_info",
                              "describe_tool", "debug_request_context", "onboard", "identity"}
            if name not in identity_tools:
                logger.warning(f"[IDENTITY] No identity for tool {name}. V2 should have created one.")
    except Exception as e:
        logger.debug(f"Session identity check skipped: {e}")

    return name, arguments, ctx


# ============================================================
# Step 6: Validate Parameters
# ============================================================

async def validate_params(name: str, arguments: Dict[str, Any], ctx: DispatchContext) -> MiddlewareResult:
    """Lite model parameter coercion and validation."""
    from .validators import validate_and_coerce_params

    coerced_args, validation_error, param_coercions = validate_and_coerce_params(name, arguments)
    if validation_error:
        return [validation_error]
    arguments = coerced_args

    if param_coercions:
        arguments["_param_coercions"] = param_coercions

    return name, arguments, ctx


# ============================================================
# Step 7: Check Rate Limit
# ============================================================

# Persistent state for expensive-read-only loop detection
_tool_call_history: Dict[str, deque] = defaultdict(lambda: deque())


async def check_rate_limit(name: str, arguments: Dict[str, Any], ctx: DispatchContext) -> MiddlewareResult:
    """Rate limiting for non-read-only tools + loop detection for expensive reads."""

    # Loop detection for expensive read-only tools
    expensive_read_only_tools = {'list_agents'}
    if name in expensive_read_only_tools:
        now = time.time()
        tool_history = _tool_call_history[name]

        # Clean up old calls (keep last 60 seconds)
        cutoff = now - 60
        while tool_history and tool_history[0] < cutoff:
            tool_history.popleft()

        if len(tool_history) >= 20:
            return [error_response(
                f"Tool call loop detected: '{name}' called {len(tool_history)} times globally in the last 60 seconds. "
                f"This may indicate a stuck agent. Please wait 30 seconds before retrying.",
                recovery={
                    "action": "Wait 30 seconds before retrying this tool",
                    "related_tools": ["health_check", "get_governance_metrics"],
                    "workflow": "1. Wait 30 seconds 2. Check agent health 3. Retry if needed"
                },
                context={
                    "tool_name": name,
                    "calls_in_last_minute": len(tool_history),
                    "note": "Global rate limit (list_agents doesn't have agent_id parameter)"
                }
            )]

        tool_history.append(now)

    # General rate limiting (skip for read-only tools)
    read_only_tools = {'health_check', 'get_server_info', 'list_tools', 'get_thresholds', 'search_knowledge_graph', 'get_governance_metrics'}
    if name not in read_only_tools:
        agent_id = arguments.get('agent_id') or 'anonymous'
        rate_limiter = get_rate_limiter()
        allowed, error_msg = rate_limiter.check_rate_limit(agent_id)

        if not allowed:
            return rate_limit_error(agent_id, rate_limiter.get_stats(agent_id))

    return name, arguments, ctx


# ============================================================
# Step 8: Track Patterns
# ============================================================

async def track_patterns(name: str, arguments: Dict[str, Any], ctx: DispatchContext) -> MiddlewareResult:
    """Cognitive loop detection and hypothesis tracking."""
    try:
        from src.pattern_tracker import get_pattern_tracker
        from .utils import get_bound_agent_id
        from .pattern_helpers import record_hypothesis_if_needed, check_untested_hypotheses, mark_hypothesis_tested

        tracker = get_pattern_tracker()
        agent_id = get_bound_agent_id(arguments)
        if agent_id:
            loop_result = tracker.record_tool_call(agent_id, name, arguments)
            if loop_result and loop_result.get("detected"):
                logger.warning(f"[PATTERN_DETECTION] Agent {agent_id[:8]}...: {loop_result['message']}")

            record_hypothesis_if_needed(agent_id, name, arguments)

            hypothesis_warning = check_untested_hypotheses(agent_id)
            if hypothesis_warning:
                logger.warning(f"[PATTERN_DETECTION] Agent {agent_id[:8]}...: {hypothesis_warning}")

            mark_hypothesis_tested(agent_id, name, arguments)
            tracker.record_progress(agent_id)
    except Exception as e:
        logger.debug(f"Pattern tracking failed: {e}")

    return name, arguments, ctx


# ============================================================
# Pipeline orchestrator
# ============================================================

# Steps that must succeed (short-circuit on error)
PRE_DISPATCH_STEPS = [
    resolve_identity,
    verify_trajectory,
    unwrap_kwargs,
    resolve_alias,
    inject_identity,
    validate_params,
]

# Steps that run but don't block (best-effort)
POST_VALIDATION_STEPS = [
    check_rate_limit,
    track_patterns,
]
