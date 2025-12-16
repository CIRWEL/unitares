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
    handle_get_agent_api_key,
    handle_mark_response_complete,
    handle_direct_resume_if_safe,
)
from .export import (
    handle_get_system_history,
    handle_export_to_file,
)
from .admin import (
    handle_reset_monitor,
    handle_get_server_info,
    handle_health_check,
    handle_check_calibration,
    handle_update_calibration_ground_truth,
    handle_backfill_calibration_from_dialectic,
    handle_get_telemetry_metrics,
    handle_list_tools,
    handle_cleanup_stale_locks,
    handle_get_workspace_health,
    handle_get_tool_usage_stats,
    handle_validate_file_path,
    handle_quick_start,
)
# REMOVED: Knowledge layer handlers (archived November 28, 2025)
# See docs/archive/KNOWLEDGE_LAYER_EXPERIMENT.md
# from .knowledge import (
#     handle_store_knowledge,
#     handle_retrieve_knowledge,
#     handle_search_knowledge,
#     handle_list_knowledge,
#     handle_update_discovery_status,
#     handle_update_discovery,
#     handle_find_similar_discoveries,
# )
# Knowledge Graph (New - Fast, indexed, transparent)
from .knowledge_graph import (
    handle_store_knowledge_graph,
    handle_search_knowledge_graph,
    handle_get_knowledge_graph,
    handle_list_knowledge_graph,
    handle_update_discovery_status_graph,
    handle_find_similar_discoveries_graph,
    handle_get_discovery_details,
    handle_reply_to_question,
    handle_leave_note,
)
# Dialectic (Circuit Breaker Recovery) - Enabled after fixing imports
from .dialectic import (
    handle_request_dialectic_review,
    handle_request_exploration_session,
    handle_submit_thesis,
    handle_submit_antithesis,
    handle_submit_synthesis,
    handle_get_dialectic_session,
)
# Identity (Session binding, recall, spawn) - Added December 2025
# AGI-FORWARD: New aliases who_am_i, authenticate, hello, spawn_child (Dec 2025)
from .identity import (
    handle_bind_identity,
    handle_recall_identity,
    handle_spawn_agent,
    # AGI-forward aliases
    handle_who_am_i,
    handle_authenticate,
    handle_hello,
    handle_spawn_child,
    # Utilities
    get_bound_agent_id,
    get_bound_api_key,
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
    
    Args:
        name: Tool name
        arguments: Tool arguments
        
    Returns:
        Sequence of TextContent responses, or None if handler not found (fallback to legacy)
    """
    
    # Be defensive: some MCP clients/transports may send `arguments: null`
    # (especially for no-argument tools like list_tools/health_check).
    if arguments is None:
        arguments = {}
    
    # === LITE MODEL SUPPORT: Smart Parameter Validation ===
    # Catches common mistakes (wrong types, string instead of list, etc.)
    # and provides helpful error messages with examples
    from .validators import validate_and_coerce_params
    coerced_args, validation_error = validate_and_coerce_params(name, arguments)
    if validation_error:
        return [validation_error]
    arguments = coerced_args
    
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        # Return helpful error with fuzzy suggestions instead of None
        return tool_not_found_error(name, list(TOOL_HANDLERS.keys()))
    
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

