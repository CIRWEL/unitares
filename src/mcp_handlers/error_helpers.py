"""
Enhanced error handling utilities for MCP handlers.

Standardizes error responses with recovery guidance and context.
"""

from typing import Dict, Any, Optional, Sequence
from mcp.types import TextContent
from .utils import error_response


# Standard recovery patterns for common error types
RECOVERY_PATTERNS = {
    "agent_not_found": {
        "action": "Call get_agent_api_key first to register this agent_id",
        "related_tools": ["get_agent_api_key", "list_agents"],
        "workflow": [
            "1. Call get_agent_api_key with your agent_id to register",
            "2. Save the returned API key securely",
            "3. Then call this tool again with agent_id and api_key"
        ]
    },
    "agent_not_registered": {
        "action": "Call get_agent_api_key first to register this agent_id",
        "related_tools": ["get_agent_api_key", "list_agents"],
        "workflow": [
            "1. Call get_agent_api_key with your agent_id to register",
            "2. Save the returned API key securely",
            "3. Then call this tool again with agent_id and api_key"
        ]
    },
    "authentication_failed": {
        "action": "Verify your API key matches your agent_id",
        "related_tools": ["get_agent_api_key", "bind_identity"],
        "workflow": [
            "1. Get correct API key for your agent_id via get_agent_api_key",
            "2. Optionally call bind_identity(agent_id, api_key) to auto-retrieve in future",
            "3. Retry with correct key"
        ]
    },
    "authentication_required": {
        "action": "Provide api_key parameter or bind your identity",
        "related_tools": ["get_agent_api_key", "bind_identity"],
        "workflow": [
            "Option 1: Get API key via get_agent_api_key and include in request",
            "Option 2: Call bind_identity(agent_id, api_key) once, then API key auto-retrieved from session"
        ]
    },
    "ownership_required": {
        "action": "You can only modify your own resources",
        "related_tools": ["get_agent_api_key", "list_agents"],
        "workflow": [
            "1. Verify you're using the correct agent_id",
            "2. Ensure your API key matches the agent_id that owns the resource",
            "3. You cannot modify resources owned by other agents"
        ]
    },
    "rate_limit_exceeded": {
        "action": "Wait a few seconds before retrying",
        "related_tools": ["health_check"],
        "workflow": [
            "1. Wait 10-30 seconds",
            "2. Retry request",
            "3. If persistent, check system health"
        ]
    },
    "timeout": {
        "action": "This may indicate a blocking operation or system overload. Try again with simpler parameters.",
        "related_tools": ["health_check", "get_server_info"],
        "workflow": [
            "1. Wait a few seconds and retry",
            "2. Check system health with health_check",
            "3. Simplify request parameters",
            "4. Check for system overload"
        ]
    },
    "invalid_parameters": {
        "action": "Check tool parameters and try again",
        "related_tools": ["list_tools", "health_check"],
        "workflow": [
            "1. Verify tool parameters match schema",
            "2. Check tool description with list_tools",
            "3. Retry with correct parameters"
        ]
    },
    "validation_error": {
        "action": "Check parameter format and constraints",
        "related_tools": ["list_tools"],
        "workflow": [
            "1. Review parameter requirements",
            "2. Check tool schema with list_tools",
            "3. Retry with valid parameters"
        ]
    },
    "system_error": {
        "action": "Check system health and retry",
        "related_tools": ["health_check", "get_server_info"],
        "workflow": [
            "1. Check system health",
            "2. Wait a few seconds",
            "3. Retry request"
        ]
    },
    "resource_not_found": {
        "action": "Verify the resource ID exists",
        "related_tools": ["list_agents", "search_knowledge_graph"],
        "workflow": [
            "1. Check if resource exists",
            "2. Verify resource ID format",
            "3. Use search/list tools to find correct ID"
        ]
    }
}


def agent_not_found_error(
    agent_id: str, 
    context: Optional[Dict[str, Any]] = None,
    error_code: str = "AGENT_NOT_FOUND"
) -> Sequence[TextContent]:
    """Standard error for agent not found"""
    return [error_response(
        f"Agent '{agent_id}' not found",
        error_code=error_code,
        error_category="validation_error",
        details={"error_type": "agent_not_found", "agent_id": agent_id},
        recovery=RECOVERY_PATTERNS["agent_not_found"],
        context=context or {}
    )]


def agent_not_registered_error(
    agent_id: str,
    context: Optional[Dict[str, Any]] = None,
    error_code: str = "AGENT_NOT_REGISTERED"
) -> Sequence[TextContent]:
    """Standard error for agent not registered"""
    return [error_response(
        f"Agent '{agent_id}' is not registered. You must onboard first.",
        error_code=error_code,
        error_category="validation_error",
        details={"error_type": "agent_not_registered", "agent_id": agent_id},
        recovery=RECOVERY_PATTERNS["agent_not_registered"],
        context=context or {}
    )]


def authentication_error(
    message: str = "Authentication failed",
    agent_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    error_code: str = "AUTHENTICATION_FAILED"
) -> Sequence[TextContent]:
    """Standard error for authentication failure"""
    if agent_id:
        message = f"Authentication failed for agent '{agent_id}'. Invalid API key."
        details = {"error_type": "authentication_failed", "agent_id": agent_id}
    else:
        details = {"error_type": "authentication_failed"}
    
    return [error_response(
        message,
        error_code=error_code,
        error_category="auth_error",
        details=details,
        recovery=RECOVERY_PATTERNS["authentication_failed"],
        context=context or {}
    )]


def authentication_required_error(
    operation: str = "this operation",
    context: Optional[Dict[str, Any]] = None,
    error_code: str = "AUTHENTICATION_REQUIRED"
) -> Sequence[TextContent]:
    """Standard error for missing authentication"""
    return [error_response(
        f"API key required for {operation}. Authentication required to prevent unauthorized access.",
        error_code=error_code,
        error_category="auth_error",
        details={"error_type": "authentication_required", "operation": operation},
        recovery=RECOVERY_PATTERNS["authentication_required"],
        context=context or {}
    )]


def ownership_error(
    resource_type: str,
    resource_id: str,
    owner_agent_id: str,
    caller_agent_id: str,
    context: Optional[Dict[str, Any]] = None,
    error_code: str = "OWNERSHIP_VIOLATION"
) -> Sequence[TextContent]:
    """Standard error for ownership violation"""
    return [error_response(
        f"Unauthorized: Agent '{caller_agent_id}' cannot modify {resource_type} '{resource_id}' owned by '{owner_agent_id}'.",
        error_code=error_code,
        error_category="auth_error",
        details={
            "error_type": "ownership_violation",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "owner_agent_id": owner_agent_id,
            "caller_agent_id": caller_agent_id
        },
        recovery=RECOVERY_PATTERNS["ownership_required"],
        context=context or {}
    )]


def rate_limit_error(agent_id: str, stats: Optional[Dict[str, Any]] = None) -> Sequence[TextContent]:
    """Standard error for rate limit exceeded"""
    return [error_response(
        f"Rate limit exceeded for agent '{agent_id}'",
        error_code="RATE_LIMIT_EXCEEDED",
        error_category="validation_error",
        details={"error_type": "rate_limit_exceeded", "agent_id": agent_id},
        recovery=RECOVERY_PATTERNS["rate_limit_exceeded"],
        context={"rate_limit_stats": stats} if stats else {}
    )]


def timeout_error(tool_name: str, timeout: float) -> Sequence[TextContent]:
    """Standard error for timeout"""
    return [error_response(
        f"Tool '{tool_name}' timed out after {timeout} seconds.",
        error_code="TIMEOUT",
        error_category="system_error",
        details={"error_type": "timeout", "tool_name": tool_name, "timeout_seconds": timeout},
        recovery=RECOVERY_PATTERNS["timeout"],
        context={"tool_name": tool_name, "timeout_seconds": timeout}
    )]


def invalid_parameters_error(
    tool_name: str, 
    details: Optional[str] = None,
    param_name: Optional[str] = None
) -> Sequence[TextContent]:
    """Standard error for invalid parameters"""
    message = f"Invalid parameters for tool '{tool_name}'"
    if details:
        message += f": {details}"
    
    error_details = {"error_type": "invalid_parameters", "tool_name": tool_name}
    if param_name:
        error_details["param_name"] = param_name
    
    return [error_response(
        message,
        error_code="INVALID_PARAMETERS",
        error_category="validation_error",
        details=error_details,
        recovery=RECOVERY_PATTERNS["invalid_parameters"],
        context={"tool_name": tool_name, "details": details, "param_name": param_name}
    )]


def validation_error(
    message: str,
    param_name: Optional[str] = None,
    provided_value: Any = None,
    context: Optional[Dict[str, Any]] = None,
    error_code: str = "VALIDATION_ERROR"
) -> Sequence[TextContent]:
    """Standard error for validation failures"""
    details = {"error_type": "validation_error"}
    if param_name:
        details["param_name"] = param_name
    if provided_value is not None:
        details["provided_value"] = str(provided_value)
    
    return [error_response(
        message,
        error_code=error_code,
        error_category="validation_error",
        details=details,
        recovery=RECOVERY_PATTERNS["validation_error"],
        context=context or {}
    )]


def resource_not_found_error(
    resource_type: str,
    resource_id: str,
    context: Optional[Dict[str, Any]] = None,
    error_code: str = "RESOURCE_NOT_FOUND"
) -> Sequence[TextContent]:
    """Standard error for resource not found"""
    return [error_response(
        f"{resource_type.capitalize()} '{resource_id}' not found",
        error_code=error_code,
        error_category="validation_error",
        details={"error_type": "resource_not_found", "resource_type": resource_type, "resource_id": resource_id},
        recovery=RECOVERY_PATTERNS["resource_not_found"],
        context=context or {}
    )]


def system_error(
    tool_name: str,
    error: Exception,
    context: Optional[Dict[str, Any]] = None
) -> Sequence[TextContent]:
    """Standard error for system errors"""
    return [error_response(
        f"System error executing tool '{tool_name}': {str(error)}",
        error_code="SYSTEM_ERROR",
        error_category="system_error",
        details={"error_type": "system_error", "tool_name": tool_name, "exception_type": type(error).__name__},
        recovery=RECOVERY_PATTERNS["system_error"],
        context=context or {}
    )]


def tool_not_found_error(
    tool_name: str,
    available_tools: list,
    context: Optional[Dict[str, Any]] = None
) -> Sequence[TextContent]:
    """
    Elegant error for unknown tool with fuzzy suggestions.

    Uses difflib to find similar tool names and provides helpful recovery.
    """
    import difflib

    # Find similar tool names (fuzzy match)
    similar = difflib.get_close_matches(tool_name, available_tools, n=3, cutoff=0.4)

    # Build helpful message
    if similar:
        suggestions_str = ", ".join(f"'{s}'" for s in similar)
        message = f"Tool '{tool_name}' not found. Did you mean: {suggestions_str}?"
    else:
        message = f"Tool '{tool_name}' not found."

    # Categorize tools for discovery
    common_tools = [t for t in available_tools if t in {
        'process_agent_update', 'bind_identity', 'search_knowledge_graph',
        'list_agents', 'health_check', 'list_tools', 'get_agent_api_key'
    }]

    return [error_response(
        message,
        error_code="TOOL_NOT_FOUND",
        error_category="validation_error",
        details={
            "error_type": "tool_not_found",
            "requested_tool": tool_name,
            "similar_tools": similar,
            "total_available": len(available_tools)
        },
        recovery={
            "action": "Use list_tools to see all available tools, or try a suggested alternative",
            "related_tools": ["list_tools", "health_check"] + similar[:2],
            "workflow": [
                "1. Check the tool name spelling",
                f"2. Try one of the suggested alternatives: {similar}" if similar else "2. Use list_tools to browse available tools",
                "3. Use describe_tool(tool_name) to see tool details"
            ],
            "suggestions": similar,
            "common_tools": common_tools[:5]
        },
        context=context or {}
    )]

