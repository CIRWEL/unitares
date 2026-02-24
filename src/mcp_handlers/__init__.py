"""
MCP Tool Handlers

Handler registry pattern for elegant tool dispatch.
Each tool handler is a separate function for better testability and maintainability.
"""

from typing import Dict, Any, Sequence, Optional
from mcp.types import TextContent

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
# Outcome Events - EISV validation infrastructure (Feb 2026)
from .outcome_events import handle_outcome_event
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
    maybe_emit_resonance_signal,  # Hook for process_agent_update
    maybe_apply_neighbor_pressure,  # Hook for process_agent_update
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

# Logging
from src.logging_utils import get_logger
logger = get_logger(__name__)

# Re-export for external callers that import from this package
__all__ = ['dispatch_tool', 'TOOL_HANDLERS', 'error_response', 'success_response']

# Handler registry - populated automatically by @mcp_tool decorators
# All tools are decorator-registered, so we start with an empty dict and populate from decorators
# Imports above ensure decorators run and register tools automatically
TOOL_HANDLERS: Dict[str, callable] = {}

# Populate registry from decorator-registered tools
# All handlers use @mcp_tool decorator which auto-registers them
decorator_registry = get_decorator_registry()
for tool_name, handler in decorator_registry.items():
    TOOL_HANDLERS[tool_name] = handler


async def dispatch_tool(name: str, arguments: Optional[Dict[str, Any]]) -> Sequence[TextContent] | None:
    """
    Dispatch tool call to appropriate handler.

    Pipeline: identity → trajectory → kwargs → alias → inject → validate → rate limit → patterns → execute.
    Each step is defined in middleware.py for testability.
    """
    from .middleware import (
        DispatchContext, PRE_DISPATCH_STEPS, POST_VALIDATION_STEPS,
    )
    from .context import reset_session_context, reset_trajectory_confidence

    if arguments is None:
        arguments = {}

    ctx = DispatchContext()

    # Pre-dispatch pipeline (short-circuits on error)
    for step in PRE_DISPATCH_STEPS:
        result = await step(name, arguments, ctx)
        if isinstance(result, list):
            # Short-circuit: clean up context and return error
            if ctx.context_token is not None:
                reset_session_context(ctx.context_token)
            return result
        name, arguments, ctx = result

    # Handler lookup
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        if ctx.context_token is not None:
            reset_session_context(ctx.context_token)
        return tool_not_found_error(name, list(TOOL_HANDLERS.keys()))

    # Log migration note if alias was used
    if ctx.migration_note:
        logger.info(f"Tool alias used: '{ctx.original_name}' → '{name}'. Migration: {ctx.migration_note}")

    # Post-validation pipeline (best-effort, may short-circuit for rate limits)
    for step in POST_VALIDATION_STEPS:
        result = await step(name, arguments, ctx)
        if isinstance(result, list):
            if ctx.context_token is not None:
                reset_session_context(ctx.context_token)
            return result
        name, arguments, ctx = result

    try:
        result = await handler(arguments)
        if result:
            if isinstance(result, (list, tuple)) and len(result) > 0:
                if "Handler not yet extracted" in result[0].text:
                    return None
            elif hasattr(result, 'text'):
                if "Handler not yet extracted" in result.text:
                    return None
        return result
    finally:
        reset_session_context(ctx.context_token)
        if ctx.trajectory_confidence_token is not None:
            reset_trajectory_confidence(ctx.trajectory_confidence_token)

