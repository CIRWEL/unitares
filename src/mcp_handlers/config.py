"""
Configuration tool handlers.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
import json
from .utils import success_response, error_response


async def handle_get_thresholds(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle get_thresholds tool"""
    from src.runtime_config import get_thresholds
    
    thresholds = get_thresholds()
    
    return success_response({
        "thresholds": thresholds,
        "note": "These are the effective thresholds (runtime overrides + defaults)"
    })


async def handle_set_thresholds(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle set_thresholds tool"""
    from src.runtime_config import set_thresholds, get_thresholds
    
    thresholds = arguments.get("thresholds", {})
    validate = arguments.get("validate", True)
    
    result = set_thresholds(thresholds, validate=validate)
    
    current_thresholds = get_thresholds() if result["success"] else None
    
    response_data = {
        "success": result["success"],
        "updated": result["updated"],
        "errors": result["errors"]
    }
    
    if current_thresholds:
        response_data["current_thresholds"] = current_thresholds
    
    return success_response(response_data)

