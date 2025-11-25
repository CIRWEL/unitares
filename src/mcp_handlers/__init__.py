"""
MCP Tool Handlers

Handler registry pattern for elegant tool dispatch.
Each tool handler is a separate function for better testability and maintainability.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
import json

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
    handle_get_telemetry_metrics,
    handle_list_tools,
    handle_cleanup_stale_locks,
)
from .knowledge import (
    handle_store_knowledge,
    handle_retrieve_knowledge,
    handle_search_knowledge,
    handle_list_knowledge,
    handle_update_discovery_status,
    handle_update_discovery,
    handle_find_similar_discoveries,
)
# Dialectic (Circuit Breaker Recovery) - Enabled after fixing imports
from .dialectic import (
    handle_request_dialectic_review,
    handle_submit_thesis,
    handle_submit_antithesis,
    handle_submit_synthesis,
    handle_get_dialectic_session,
)

# Common utilities
from .utils import error_response, success_response


# Handler registry
TOOL_HANDLERS: Dict[str, callable] = {
    # Core governance
    "process_agent_update": handle_process_agent_update,
    "get_governance_metrics": handle_get_governance_metrics,
    "simulate_update": handle_simulate_update,
    
    # Configuration
    "get_thresholds": handle_get_thresholds,
    "set_thresholds": handle_set_thresholds,
    
    # Observability
    "observe_agent": handle_observe_agent,
    "compare_agents": handle_compare_agents,
    "detect_anomalies": handle_detect_anomalies,
    "aggregate_metrics": handle_aggregate_metrics,
    
    # Lifecycle
    "list_agents": handle_list_agents,
    "get_agent_metadata": handle_get_agent_metadata,
    "update_agent_metadata": handle_update_agent_metadata,
    "archive_agent": handle_archive_agent,
    "delete_agent": handle_delete_agent,
    "archive_old_test_agents": handle_archive_old_test_agents,
    "get_agent_api_key": handle_get_agent_api_key,
    
    # Export
    "get_system_history": handle_get_system_history,
    "export_to_file": handle_export_to_file,
    
    # Admin
    "reset_monitor": handle_reset_monitor,
    "get_server_info": handle_get_server_info,
    "health_check": handle_health_check,
    "check_calibration": handle_check_calibration,
    "update_calibration_ground_truth": handle_update_calibration_ground_truth,
    "get_telemetry_metrics": handle_get_telemetry_metrics,
    "list_tools": handle_list_tools,
    "cleanup_stale_locks": handle_cleanup_stale_locks,
    
    # Knowledge
    "store_knowledge": handle_store_knowledge,
    "retrieve_knowledge": handle_retrieve_knowledge,
    "search_knowledge": handle_search_knowledge,
    "list_knowledge": handle_list_knowledge,
    "update_discovery_status": handle_update_discovery_status,
    "update_discovery": handle_update_discovery,
    "find_similar_discoveries": handle_find_similar_discoveries,

    # Dialectic (Circuit Breaker Recovery) - Enabled
    "request_dialectic_review": handle_request_dialectic_review,
    "submit_thesis": handle_submit_thesis,
    "submit_antithesis": handle_submit_antithesis,
    "submit_synthesis": handle_submit_synthesis,
    "get_dialectic_session": handle_get_dialectic_session,
}


async def dispatch_tool(name: str, arguments: Dict[str, Any]) -> Sequence[TextContent] | None:
    """
    Dispatch tool call to appropriate handler.
    
    Args:
        name: Tool name
        arguments: Tool arguments
        
    Returns:
        Sequence of TextContent responses, or None if handler not found (fallback to legacy)
    """
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return None  # Signal to fallback to legacy elif chain
    
    try:
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
    except Exception as e:
        import traceback
        error_msg = f"Error in {name}: {str(e)}\n{traceback.format_exc()}"
        return [error_response(error_msg)]

