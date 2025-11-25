"""
Common utilities for MCP tool handlers.
"""

from typing import Dict, Any, Sequence, Tuple, Optional
from mcp.types import TextContent
import json


def error_response(message: str, details: Dict[str, Any] = None) -> TextContent:
    """
    Create an error response.
    
    Args:
        message: Error message
        details: Optional additional error details
        
    Returns:
        TextContent with error response
    """
    response = {
        "success": False,
        "error": message
    }
    if details:
        response.update(details)
    
    return TextContent(
        type="text",
        text=json.dumps(response, indent=2)
    )


def success_response(data: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Create a success response.
    
    Args:
        data: Response data (will have "success": True added)
        
    Returns:
        Sequence of TextContent with success response
    """
    response = {
        "success": True,
        **data
    }
    
    return [TextContent(
        type="text",
        text=json.dumps(response, indent=2)
    )]


def require_argument(arguments: Dict[str, Any], name: str, 
                    error_message: str = None) -> Tuple[Any, Optional[TextContent]]:
    """
    Get required argument from arguments dict.
    
    Args:
        arguments: Arguments dictionary
        name: Argument name
        error_message: Custom error message (defaults to "{name} is required")
        
    Returns:
        Tuple of (value, error_response). If value is None, error_response is provided.
    """
    value = arguments.get(name)
    if value is None:
        msg = error_message or f"{name} is required"
        return None, error_response(msg)
    return value, None


def require_agent_id(arguments: Dict[str, Any]) -> Tuple[str, Optional[TextContent]]:
    """
    Get required agent_id from arguments.
    
    Args:
        arguments: Arguments dictionary
        
    Returns:
        Tuple of (agent_id, error_response). If agent_id is missing, error_response is provided.
    """
    return require_argument(arguments, "agent_id", "agent_id is required")

