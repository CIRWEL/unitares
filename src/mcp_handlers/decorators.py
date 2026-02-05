"""
MCP Tool Decorators - Auto-registration and utilities

Reduces boilerplate and enables auto-discovery of tools.
"""

from typing import Dict, Any, Callable, Optional
from functools import wraps
import asyncio
import sys
import time
from mcp.types import TextContent

# Import structured logging
from src.logging_utils import get_logger
from .utils import error_response  # Fixed: Move import to top (was inside exception handlers)

logger = get_logger(__name__)

# Global registry (populated by decorators)
_TOOL_REGISTRY: Dict[str, Callable] = {}
_TOOL_TIMEOUTS: Dict[str, float] = {}
_TOOL_DESCRIPTIONS: Dict[str, str] = {}
_TOOL_METADATA: Dict[str, Dict[str, Any]] = {}  # New: stores deprecated, hidden, superseded_by


def mcp_tool(
    name: Optional[str] = None,
    timeout: float = 30.0,
    description: Optional[str] = None,
    rate_limit_exempt: bool = False,
    deprecated: bool = False,
    hidden: bool = False,
    superseded_by: Optional[str] = None,
    register: bool = True
):
    """
    Decorator for MCP tool handlers with auto-registration and timeout protection.

    Provides:
    - Automatic timeout protection
    - Performance timing/observability (warns if >80% of timeout)
    - Error handling with recovery guidance
    - Tool registration for discovery
    - Deprecation and hiding support

    Usage:
        @mcp_tool("process_agent_update", timeout=60.0)
        async def handle_process_agent_update(arguments: Dict[str, Any]) -> Sequence[TextContent]:
            ...

        @mcp_tool("old_tool", deprecated=True, superseded_by="new_tool")
        async def handle_old_tool(...): ...

        @mcp_tool("internal_helper", register=False)  # Not exposed to MCP clients
        async def handle_internal_helper(...): ...

    Args:
        name: Tool name (defaults to function name without 'handle_' prefix)
        timeout: Timeout in seconds (default: 30.0)
        description: Tool description (defaults to function docstring)
        rate_limit_exempt: If True, skip rate limiting for this tool
        deprecated: If True, tool still works but warns users to use superseded_by
        hidden: If True, tool is not shown in list_tools (internal use only)
        superseded_by: Name of tool that replaces this one (for deprecation messages)
        register: If False, tool is NOT registered (for internal handlers called by consolidated tools)

    Returns:
        Decorated handler function (wrapper with timeout protection)

    Note: Future improvement could split into composable decorators:
        @mcp_tool("name") @with_timeout(60) @with_timing @with_error_handling
    This would allow mixing/matching features, but current monolithic approach works well.
    """
    def decorator(func: Callable) -> Callable:
        # Determine tool name
        tool_name = name or func.__name__.replace('handle_', '')
        
        # Get description from docstring if not provided
        tool_description = description or (func.__doc__ and func.__doc__.split('\n')[0].strip()) or ""
        
        # Add metadata to function
        func._mcp_tool_name = tool_name
        func._mcp_timeout = timeout
        func._mcp_rate_limit_exempt = rate_limit_exempt
        func._mcp_deprecated = deprecated
        func._mcp_hidden = hidden
        func._mcp_superseded_by = superseded_by
        
        @wraps(func)
        async def wrapper(arguments: Dict[str, Any]):
            """Wrapper with automatic timeout protection and timing"""
            start_time = time.time()
            try:
                # Apply timeout automatically
                result = await asyncio.wait_for(
                    func(arguments),
                    timeout=timeout
                )
                elapsed = time.time() - start_time
                
                # Observability: Warn if tool took >80% of timeout
                if elapsed > timeout * 0.8:
                    logger.warning(
                        f"Tool '{tool_name}' took {elapsed:.2f}s ({elapsed/timeout*100:.1f}% of {timeout}s timeout). "
                        f"Consider optimizing or increasing timeout."
                    )
                
                return result
            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                logger.warning(f"Tool '{tool_name}' timed out after {timeout}s (actual: {elapsed:.2f}s)")
                return [error_response(
                    f"Tool '{tool_name}' timed out after {timeout} seconds.",
                    recovery={
                        "action": "This may indicate a blocking operation or system overload. Try again with simpler parameters.",
                        "related_tools": ["health_check", "get_server_info"],
                        "workflow": f"1. Wait a few seconds and retry 2. Check system health 3. Simplify request parameters"
                    }
                )]
            except Exception as e:
                elapsed = time.time() - start_time
                # Log internally but sanitize for client
                logger.error(f"Tool '{tool_name}' error after {elapsed:.2f}s: {e}", exc_info=True)
                
                return [error_response(
                    f"Error executing tool '{tool_name}': {str(e)}",
                    recovery={
                        "action": "Check tool parameters and try again",
                        "related_tools": ["health_check", "list_tools"],
                        "workflow": "1. Verify tool parameters 2. Check system health 3. Retry with simpler parameters"
                    }
                )]
        
        # Only register if register=True (default)
        # Use register=False for internal handlers called by consolidated tools
        if register:
            _TOOL_REGISTRY[tool_name] = wrapper
            _TOOL_TIMEOUTS[tool_name] = timeout
            _TOOL_DESCRIPTIONS[tool_name] = tool_description
            _TOOL_METADATA[tool_name] = {
                "deprecated": deprecated,
                "hidden": hidden,
                "superseded_by": superseded_by
            }

        return wrapper
    return decorator


def get_tool_registry() -> Dict[str, Callable]:
    """Get the registered tool handlers"""
    return _TOOL_REGISTRY.copy()


def get_tool_timeout(tool_name: str) -> float:
    """Get timeout for a tool"""
    return _TOOL_TIMEOUTS.get(tool_name, 30.0)


def get_tool_description(tool_name: str) -> str:
    """Get description for a tool"""
    return _TOOL_DESCRIPTIONS.get(tool_name, "")


def get_tool_metadata(tool_name: str) -> Dict[str, Any]:
    """Get metadata for a tool (deprecated, hidden, superseded_by)"""
    return _TOOL_METADATA.get(tool_name, {})


def is_tool_deprecated(tool_name: str) -> bool:
    """Check if a tool is deprecated"""
    return _TOOL_METADATA.get(tool_name, {}).get("deprecated", False)


def is_tool_hidden(tool_name: str) -> bool:
    """Check if a tool is hidden from list_tools"""
    return _TOOL_METADATA.get(tool_name, {}).get("hidden", False)


def list_registered_tools(include_hidden: bool = False, include_deprecated: bool = True) -> list[str]:
    """List all registered tool names, optionally filtering hidden/deprecated"""
    tools = []
    for name in sorted(_TOOL_REGISTRY.keys()):
        meta = _TOOL_METADATA.get(name, {})
        if meta.get("hidden") and not include_hidden:
            continue
        if meta.get("deprecated") and not include_deprecated:
            continue
        tools.append(name)
    return tools
    """List all registered tool names"""
    return sorted(_TOOL_REGISTRY.keys())

