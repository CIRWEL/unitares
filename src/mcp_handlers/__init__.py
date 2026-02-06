"""
MCP Tool Handlers

Handler registry pattern for elegant tool dispatch.
Each tool handler is a separate function for better testability and maintainability.
"""

from typing import Dict, Any, Sequence, Optional
from mcp.types import TextContent
import json
import asyncio
import time
import traceback
from collections import defaultdict, deque

# Import all handlers
from .core import (
    handle_process_agent_update,
    handle_get_governance_metrics,
    handle_simulate_update,
)
from .config import (
    handle_get_thresholds,
    handle_set_thresholds,
)
from .observability import (
    handle_observe_agent,
    handle_compare_agents,
    handle_compare_me_to_similar,
    handle_detect_anomalies,
    handle_aggregate_metrics,
)
from .lifecycle import (
    handle_list_agents,
    handle_get_agent_metadata,
    handle_update_agent_metadata,
    handle_archive_agent,
    handle_delete_agent,
    handle_archive_old_test_agents,
    # handle_get_agent_api_key REMOVED Dec 2025 - aliased to identity()
    handle_mark_response_complete,
    handle_direct_resume_if_safe,
    handle_self_recovery_review,  # Added per SELF_RECOVERY_SPEC.md
    handle_detect_stuck_agents,
    handle_ping_agent,
)
from .export import (
    handle_get_system_history,
    handle_export_to_file,
)
from .admin import (
    handle_reset_monitor,
    handle_get_server_info,
    handle_health_check,
    handle_get_connection_status,
    handle_check_calibration,
    handle_rebuild_calibration,
    handle_update_calibration_ground_truth,
    handle_backfill_calibration_from_dialectic,
    handle_get_telemetry_metrics,
    handle_list_tools,
    handle_cleanup_stale_locks,
    handle_get_workspace_health,
    handle_get_tool_usage_stats,
    handle_validate_file_path,
)
# Knowledge Graph
from .knowledge_graph import (
    handle_store_knowledge_graph,
    handle_search_knowledge_graph,
    handle_get_knowledge_graph,
    handle_list_knowledge_graph,
    handle_update_discovery_status_graph,
    handle_get_discovery_details,
    handle_leave_note,
    handle_cleanup_knowledge_graph,
    handle_get_lifecycle_stats,
)
# Dialectic - full protocol restored (Feb 2026)
from .dialectic import (
    handle_get_dialectic_session,
    handle_list_dialectic_sessions,
    handle_request_dialectic_review,
    handle_submit_thesis,
    handle_submit_antithesis,
    handle_submit_synthesis,
    handle_llm_assisted_dialectic,
)
# Self-Recovery - Simplified recovery without external reviewers (Jan 2026)
# Note: handle_self_recovery_review moved to lifecycle.py per SELF_RECOVERY_SPEC.md
from .self_recovery import (
    handle_self_recovery,  # Consolidated entry point
    handle_quick_resume,  # Hidden, used by dispatcher
    handle_check_recovery_options,  # Hidden, used by dispatcher
    handle_operator_resume_agent,
)
# Identity - v2 simplified (Dec 2025, 3-path architecture)
from .identity_v2 import (
    handle_identity_adapter as handle_identity,
    handle_onboard_v2 as handle_onboard,
    handle_verify_trajectory_identity,
    handle_get_trajectory_status,
)
# Model Inference - Free/low-cost LLM access via ngrok.ai
from .model_inference import handle_call_model
# ROI Metrics - Customer value tracking
from .roi_metrics import handle_get_roi_metrics
# Consolidated tools - reduces cognitive load for agents (Jan 2026)
from .consolidated import (
    handle_knowledge,
    handle_agent,
    handle_calibration,
)
# CIRS Protocol - Multi-agent resonance layer (Feb 2026)
# See: UARG Whitepaper for protocol specification
from .cirs_protocol import (
    handle_cirs_protocol,  # Consolidated entry point
    # Individual handlers (hidden, for backwards compat)
    handle_void_alert,
    handle_state_announce,
    handle_coherence_report,
    handle_boundary_contract,
    handle_governance_action,
    maybe_emit_void_alert,  # Hook for process_agent_update
    auto_emit_state_announce,  # Hook for process_agent_update
)
# Pi Orchestration - Mac→Pi coordination tools (Feb 2026)
# Proxies calls to anima-mcp on Pi via Streamable HTTP transport (MCP 1.24.0+)
from .pi_orchestration import (
    handle_pi_list_tools,
    handle_pi_get_context,
    handle_pi_health,
    handle_pi_sync_eisv,
    handle_pi_display,
    handle_pi_say,
    handle_pi_post_message,
    handle_pi_lumen_qa,
    handle_pi_query,
    handle_pi_workflow,
    handle_pi_git_pull,
    handle_pi_restart_service,  # SSH-based fallback when MCP is down
)
# Keep helper functions from identity_shared.py (used by dispatch_tool)
from .identity_shared import (
    get_bound_agent_id,
    is_session_bound,
)

# Common utilities
from .utils import error_response, success_response

# Error helpers (for exception handlers)
from .error_helpers import timeout_error, system_error, rate_limit_error, tool_not_found_error

# Decorator utilities
from .decorators import get_tool_registry as get_decorator_registry, get_tool_timeout

# Rate limiting
from src.rate_limiter import get_rate_limiter

# Logging
from src.logging_utils import get_logger
logger = get_logger(__name__)

# Handler registry - populated automatically by @mcp_tool decorators
# All tools are decorator-registered, so we start with an empty dict and populate from decorators
# Imports above ensure decorators run and register tools automatically
TOOL_HANDLERS: Dict[str, callable] = {}

# Populate registry from decorator-registered tools
# All handlers use @mcp_tool decorator which auto-registers them
decorator_registry = get_decorator_registry()
for tool_name, handler in decorator_registry.items():
    TOOL_HANDLERS[tool_name] = handler


# Module-level logger (avoid creating new logger on every call)
_logger = get_logger(__name__)

async def dispatch_tool(name: str, arguments: Optional[Dict[str, Any]]) -> Sequence[TextContent] | None:
    """
    Dispatch tool call to appropriate handler with timeout protection and rate limiting.
    
    LITE MODEL SUPPORT: Validates and coerces parameters before calling handlers,
    providing helpful error messages for smaller models that may format parameters incorrectly.
    
    TOOL ALIAS SUPPORT: Automatically resolves aliases for renamed/consolidated tools.
    Old tool names still work and show migration guidance.
    
    Args:
        name: Tool name (may be an alias)
        arguments: Tool arguments
        
    Returns:
        Sequence of TextContent responses, or None if handler not found (fallback to legacy)
    """
    
    # Be defensive: some MCP clients/transports may send `arguments: null`
    # (especially for no-argument tools like list_tools/health_check).
    if arguments is None:
        arguments = {}

    # === RESOLVE SESSION IDENTITY ===
    # Prioritize: 
    # 1. Explicit client_session_id from arguments
    # 2. Fingerprinted ID from request state (set by middleware/ASGI layer)
    # 3. Fallback to stdio PID
    client_session_id = arguments.get("client_session_id")
    request_state_id = None
    try:
        from .context import get_session_context
        # Check contextvars (set by wrapper or earlier)
        ctx = get_session_context()
        request_state_id = ctx.get('governance_client_id')
        
        # Fallback: try to extract from raw request state in context
        if not request_state_id:
            req = ctx.get('request')
            if req and hasattr(req, 'state'):
                request_state_id = getattr(req.state, 'governance_client_id', None)
    except Exception:
        pass

    # ONBOARD PIN: If no explicit client_session_id, check if a recent onboard()
    # pinned an identity for this transport fingerprint. This fixes attribution
    # fragmentation when Claude.ai doesn't echo back client_session_id.
    #
    # We check multiple sources for the transport fingerprint because different
    # ASGI paths store it differently:
    # - governance_client_id: set in ASGI scope["state"] (may not propagate to contextvars)
    # - session_key contextvar: set via set_session_context() in ASGI wrapper
    transport_fingerprint = request_state_id
    if not transport_fingerprint:
        try:
            from .context import get_context_session_key
            transport_fingerprint = get_context_session_key()
        except Exception:
            pass
    _logger.debug(
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
                _logger.info(
                    f"[ONBOARD_PIN] Injected client_session_id={pinned_session_id} "
                    f"for tool={name} from pin recent_onboard:{base_fp}"
                )
        except Exception as e:
            _logger.debug(f"[ONBOARD_PIN] Pin lookup failed: {e}")

    # NOTE: X-Agent-Id injection moved AFTER session resolution (see below).
    # If session binding already resolves to an agent, X-Agent-Id would cause
    # a mismatch error (creature UUID != governance UUID). X-Agent-Id is now
    # only used as a FALLBACK when no session binding exists.

    # Derive session key with explicit priority
    from .identity_v2 import _derive_session_key
    session_key = client_session_id or request_state_id or _derive_session_key(arguments)

    from .identity_v2 import resolve_session_identity
    from .context import set_session_context, reset_session_context

    # Resolve identity using identity_v2's 3-path architecture (Redis → PostgreSQL → Create)
    # This is the SINGLE source of truth for session → UUID mapping
    bound_agent_id = None
    try:
        identity_result = await resolve_session_identity(session_key)
        bound_agent_id = identity_result.get("agent_uuid")

        # LAZY CREATION (Feb 2026 revert): Do NOT eagerly persist new identities.
        # Previous "durability fix" caused ghost agent proliferation (96% ghosts)
        # because HTTP/SSE session keys rotate per request.
        #
        # Design: Let lazy creation work - only persist when:
        # 1. Explicit onboard() call (user commits to identity)
        # 2. First meaningful work (calibration update, knowledge store, etc.)
        #
        # Mark identities created via dispatch as ephemeral - they're just session cache
        if identity_result.get("created") and not identity_result.get("persisted"):
            identity_result["ephemeral"] = True
            identity_result["created_via"] = "dispatch"
            _logger.info(f"[DISPATCH] Ephemeral identity created (not persisted): {bound_agent_id[:8]}...")

        # DURABILITY FIX (Dec 2025/Feb 2026): Update session activity in DB on every call
        # This prevents 24h hard expiry for active agents.
        # Feb 2026: Added retry and logging for better reliability
        if identity_result.get("persisted"):
            ttl_updated = False
            for attempt in range(2):  # 2 attempts max
                try:
                    from src.db import get_db
                    result = await get_db().update_session_activity(session_key)
                    ttl_updated = result if isinstance(result, bool) else True
                    break
                except Exception as e:
                    if attempt == 0:
                        await asyncio.sleep(0.05)  # Brief retry delay
                    else:
                        _logger.warning(f"[DISPATCH] Session TTL update failed for {session_key[:20]}...: {e}")
            # Note: We don't fail the request if TTL update fails - it's best effort
            # The session will still work until expiry, and next call will retry
    except Exception as e:
        _logger.debug(f"Could not resolve session identity: {e}")
    
    # Get client_hint from arguments (injected by HTTP handler from User-Agent)
    client_hint = arguments.get("client_hint") if arguments else None

    # Set context for this request (including client_hint for auto-naming)
    context_token = set_session_context(
        session_key=session_key,
        client_session_id=client_session_id,
        agent_id=bound_agent_id,
        client_hint=client_hint
    )

    # DEBUG: Log entry to dispatch_tool to trace MCP vs REST calls
    _logger.info(f"[DISPATCH_ENTRY] tool={name}, has_kwargs={'kwargs' in arguments}, arg_keys={list(arguments.keys())[:5]}, bound_agent_id={bound_agent_id[:8] + '...' if bound_agent_id else 'None'}")

    # === TRAJECTORY IDENTITY VERIFICATION ===
    # If the incoming arguments include a trajectory_signature AND the agent
    # has a stored genesis signature, run two-tier verification.
    # Non-blocking: verification failure is logged, never blocks execution.
    trajectory_confidence_token = None
    try:
        traj_sig = arguments.get("trajectory_signature") if arguments else None
        if traj_sig and isinstance(traj_sig, dict) and bound_agent_id:
            from src.trajectory_identity import TrajectorySignature, verify_trajectory_identity
            from .context import set_trajectory_confidence

            sig = TrajectorySignature.from_dict(traj_sig)
            verification = await verify_trajectory_identity(bound_agent_id, sig)

            if verification and not verification.get("error"):
                coherence_sim = verification.get("tiers", {}).get("coherence", {}).get("similarity")
                lineage_sim = verification.get("tiers", {}).get("lineage", {}).get("similarity")
                sims = [s for s in [coherence_sim, lineage_sim] if s is not None]
                if sims:
                    traj_conf = min(sims)
                    trajectory_confidence_token = set_trajectory_confidence(traj_conf)

                if not verification.get("verified"):
                    _logger.warning(
                        f"[TRAJECTORY] Verification FAILED for {bound_agent_id[:8]}...: "
                        f"failed_tiers={verification.get('failed_tiers', [])}"
                    )
    except Exception as e:
        _logger.debug(f"[TRAJECTORY] Verification skipped: {e}")

    # === KWARGS UNWRAPPING ===
    # MCP clients may send arguments wrapped as:
    #   {"kwargs": "{\"name\": \"...\"}"}  (string - needs JSON parsing)
    #   OR {"kwargs": {"name": "..."}}     (dict - already parsed by MCP library)
    # Unwrap to expected flat dict format.
    if "kwargs" in arguments:
        kwargs_val = arguments["kwargs"]
        if isinstance(kwargs_val, str):
            # Case 1: JSON string - parse it
            try:
                import json
                kwargs_parsed = json.loads(kwargs_val)
                if isinstance(kwargs_parsed, dict):
                    del arguments["kwargs"]
                    arguments.update(kwargs_parsed)
                    _logger.info(f"[DISPATCH_KWARGS] Unwrapped from string: {list(kwargs_parsed.keys())}")
            except (json.JSONDecodeError, TypeError) as e:
                _logger.warning(f"Failed to parse kwargs string: {e}")
        elif isinstance(kwargs_val, dict):
            # Case 2: Already a dict (MCP library pre-parsed) - just merge
            del arguments["kwargs"]
            arguments.update(kwargs_val)
            _logger.info(f"[DISPATCH_KWARGS] Unwrapped from dict: {list(kwargs_val.keys())}")

    # === TOOL ALIAS RESOLUTION ===
    # Resolve aliases for renamed/consolidated tools (reduces friction from tool churn)
    from .tool_stability import resolve_tool_alias, get_migration_guide
    original_name = name  # Save original for logging
    actual_name, alias_info = resolve_tool_alias(name)

    # If this is an alias, add migration note to response and inject action if needed
    migration_note = None
    if alias_info:
        migration_note = alias_info.migration_note
        name = actual_name  # Use actual tool name for dispatch

        # For consolidated tools, inject the action parameter if not already set
        if alias_info.inject_action and "action" not in arguments:
            arguments["action"] = alias_info.inject_action
            _logger.debug(f"[ALIAS] Injected action='{alias_info.inject_action}' for consolidated tool '{actual_name}'")

    # === SESSION-BASED IDENTITY INJECTION ===
    # MCP session-based identity continuity (per MCP 1.24.0+ spec)
    # Goals: one agent per session, no secrets in tool args, no impersonation
    #
    # NOTE (Dec 2025): bound_id comes from context, which was set at dispatch entry
    # using identity_v2.resolve_session_identity(). This ensures consistency.
    try:
        from .context import get_context_agent_id
        bound_id = get_context_agent_id()  # Already resolved via identity_v2
        provided_id = arguments.get("agent_id")

        if bound_id:
            if not provided_id:
                # Case 1: No agent_id provided, inject from session
                # EXCEPTION: Browsable data tools should NOT auto-filter by agent - they search ALL data
                # Users can explicitly pass agent_id to filter if desired
                # Includes: knowledge graph search, dialectic session browsing
                browsable_data_tools = {
                    "search_knowledge_graph", "query_knowledge_graph", "list_knowledge_graph",
                    "list_dialectic_sessions", "get_dialectic_session"
                }
                _logger.info(f"[DISPATCH] name={name}, in browsable_data_tools={name in browsable_data_tools}, bound_id={bound_id[:8] if bound_id else None}...")
                if name not in browsable_data_tools:
                    arguments["agent_id"] = bound_id
                    _logger.debug(f"Injected session-bound agent_id: {bound_id}")
            elif provided_id != bound_id:
                # Case 2: agent_id provided but differs from session binding
                # This prevents impersonation - reject unless it's an identity tool
                # OR if provided_id is a label that matches the bound_id
                #
                # EXCEPTION: Dialectic tools allow explicit agent_id because:
                # - Sessions validate roles (paused vs reviewer)
                # - Ephemeral agents may not have persistent session bindings
                # - Operator-facilitated dialectic needs to act on behalf of agents
                identity_tools = {"status"}
                dialectic_tools = {
                    "submit_thesis", "submit_antithesis", "submit_synthesis",
                    "request_dialectic_review"
                }
                
                # Check if it's a label match
                is_label_match = False
                try:
                    from .shared import get_mcp_server
                    mcp_server = get_mcp_server()
                    if bound_id in mcp_server.agent_metadata:
                        meta = mcp_server.agent_metadata[bound_id]
                        if getattr(meta, 'label', None) == provided_id:
                            is_label_match = True
                            _logger.debug(f"Label match allowed: {provided_id} -> {bound_id}")
                except Exception:
                    pass

                if name not in identity_tools and name not in dialectic_tools and not is_label_match:
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
                # For identity/dialectic tools, allow the switch (they handle their own validation)
        elif provided_id:
            # Case 3: REST client with X-Agent-Id header but no session binding
            # This only happens if v2 failed - just use the provided_id directly
            _logger.warning(f"[IDENTITY] No session binding but agent_id provided: {provided_id}. V2 may have failed.")
            arguments["agent_id"] = provided_id  # Trust the provided ID
        else:
            # Case 4: No binding and no agent_id
            # This only happens if v2 failed to create an identity
            # For non-identity tools, this is an error state
            identity_tools = {"status", "list_tools", "health_check", "get_server_info",
                             "describe_tool", "debug_request_context", "onboard", "identity"}
            if name not in identity_tools:
                _logger.warning(f"[IDENTITY] No identity for tool {name}. V2 should have created one.")
                # Don't block - v2 may have cached the identity and context wasn't set up properly
                # The tool handler will deal with missing agent_id if needed
    except Exception as e:
        _logger.debug(f"Session identity check skipped: {e}")

    # === LITE MODEL SUPPORT: Smart Parameter Validation ===
    # Catches common mistakes (wrong types, string instead of list, etc.)
    # and provides helpful error messages with examples
    from .validators import validate_and_coerce_params
    coerced_args, validation_error, param_coercions = validate_and_coerce_params(name, arguments)
    if validation_error:
        return [validation_error]
    arguments = coerced_args

    # Store coercions for transparency in response (UX Fix #12)
    # Agents can see what type coercions were applied to their parameters
    if param_coercions:
        arguments["_param_coercions"] = param_coercions
    
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        # Return helpful error with fuzzy suggestions instead of None
        return tool_not_found_error(name, list(TOOL_HANDLERS.keys()))
    
    # Note: Migration note is logged but not added to response to avoid breaking response format
    # Users can call migrate_tool() to get migration guidance
    if migration_note:
        _logger.info(f"Tool alias used: '{original_name}' → '{actual_name}'. Migration: {migration_note}")
    
    # Special rate limiting for expensive read-only tools (like list_agents)
    # These tools bypass general rate limiting but need protection against loops
    # Note: list_agents doesn't have agent_id parameter, so we use global tracking
    # This prevents any agent from looping, but one looping agent won't block others
    expensive_read_only_tools = {'list_agents'}
    if name in expensive_read_only_tools:
        # Use global tracking since list_agents doesn't have agent_id
        # Track by tool name only (prevents global loops)
        if not hasattr(dispatch_tool, '_tool_call_history'):
            dispatch_tool._tool_call_history = defaultdict(lambda: deque())
        
        now = time.time()
        tool_history = dispatch_tool._tool_call_history[name]
        
        # Clean up old calls (keep last 60 seconds)
        cutoff = now - 60
        while tool_history and tool_history[0] < cutoff:
            tool_history.popleft()
        
        # Check for rapid repeated calls (20+ calls in 60 seconds = loop)
        # Higher threshold since this is global (any agent calling)
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
        
        # Record this call
        tool_history.append(now)
    
    # Rate limiting (skip for read-only tools like health_check, get_server_info)
    read_only_tools = {'health_check', 'get_server_info', 'list_tools', 'get_thresholds'}
    if name not in read_only_tools:
        agent_id = arguments.get('agent_id') or 'anonymous'
        rate_limiter = get_rate_limiter()
        allowed, error_msg = rate_limiter.check_rate_limit(agent_id)
        
        if not allowed:
            return rate_limit_error(agent_id, rate_limiter.get_stats(agent_id))
    
    # Timeout protection is handled by @mcp_tool decorator
    # Decorators wrap handlers with appropriate timeouts (e.g., 60s for process_agent_update)
    # No need to wrap again here - decorator timeout will be effective
    # All handlers are decorated with @mcp_tool, which provides timeout and error handling.
    # If an exception escapes the decorator (shouldn't happen), let it propagate to caller.
    # This simplifies error handling - decorator is the single source of truth for tool errors.
    
    # Pattern tracking: detect cognitive loops and code changes
    try:
        from src.pattern_tracker import get_pattern_tracker
        from .utils import get_bound_agent_id
        from .pattern_helpers import record_hypothesis_if_needed, check_untested_hypotheses, mark_hypothesis_tested
        
        tracker = get_pattern_tracker()
        agent_id = get_bound_agent_id(arguments)
        if agent_id:
            # Record tool call for loop detection
            loop_result = tracker.record_tool_call(agent_id, name, arguments)
            if loop_result and loop_result.get("detected"):
                # Log loop detection (don't block, just warn)
                logger.warning(
                    f"[PATTERN_DETECTION] Agent {agent_id[:8]}...: {loop_result['message']}"
                )
            
            # Record code changes as hypotheses
            record_hypothesis_if_needed(agent_id, name, arguments)
            
            # Check for untested hypotheses (warn but don't block)
            hypothesis_warning = check_untested_hypotheses(agent_id)
            if hypothesis_warning:
                logger.warning(
                    f"[PATTERN_DETECTION] Agent {agent_id[:8]}...: {hypothesis_warning}"
                )
            
            # Mark hypotheses as tested if this is a testing tool
            mark_hypothesis_tested(agent_id, name, arguments)
            
            # Record progress (reset time-boxing timer)
            tracker.record_progress(agent_id)
    except Exception as e:
        # Don't fail tool calls if pattern tracking fails
        logger.debug(f"Pattern tracking failed: {e}")
    
    try:
        # Call handler directly - decorator wrapper handles timeout protection
        result = await handler(arguments)
        # Check if handler returned stub error (not yet extracted)
        # result should be a Sequence[TextContent], but handle edge cases
        if result:
            # Handle both single TextContent and Sequence
            if isinstance(result, (list, tuple)) and len(result) > 0:
                text_content = result[0].text
                if "Handler not yet extracted" in text_content:
                    return None  # Fallback to legacy elif chain
            elif hasattr(result, 'text'):
                # Single TextContent object
                if "Handler not yet extracted" in result.text:
                    return None  # Fallback to legacy elif chain
        return result
    finally:
        # Reset contextvars to prevent cross-request contamination
        reset_session_context(context_token)
        if trajectory_confidence_token is not None:
            from .context import reset_trajectory_confidence
            reset_trajectory_confidence(trajectory_confidence_token)

