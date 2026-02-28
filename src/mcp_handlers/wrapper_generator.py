"""
Typed Wrapper Generator for MCP Tools

Generates wrapper functions with explicit typed signatures from JSON schemas.
This allows FastMCP to infer correct schemas without kwargs wrapping.

Benefits:
- Claude.ai sends parameters directly (no kwargs wrapper needed)
- CLI's kwargs wrapping still works (dispatch_tool unwraps)
- Proper IDE/client autocomplete from typed signatures
- Schema metadata (descriptions, enums) preserved for MCP clients
"""

import inspect
import logging
from typing import Annotated, Any, Callable, Optional, Union

from pydantic import Field

logger = logging.getLogger(__name__)


def create_typed_wrapper(
    tool_name: str,
    input_schema: dict,
    get_handler: Callable,
    inject_session: bool = False,
    session_extractor: Optional[Callable] = None,
) -> Callable:
    """
    Create a wrapper function with explicit typed parameters from JSON schema.
    
    Args:
        tool_name: Name of the tool being wrapped
        input_schema: JSON Schema defining the tool's parameters
        get_handler: Function that returns the actual handler (e.g., get_tool_wrapper)
        inject_session: Whether to inject session_id from context
        session_extractor: Function to extract session_id from context (ctx -> str)
    
    Returns:
        Async function with typed signature that FastMCP can introspect
    """
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))

    # Build parameter info for signature, preserving schema metadata
    param_info = []
    for param_name, param_def in properties.items():
        param_type = _json_type_to_python(param_def.get("type", "string"))
        is_required = param_name in required
        description = param_def.get("description")
        enum_values = param_def.get("enum")
        param_info.append((param_name, param_type, is_required, description, enum_values))
    
    # Generate the wrapper dynamically
    if inject_session:
        wrapper = _create_session_wrapper(tool_name, param_info, get_handler, session_extractor)
    else:
        wrapper = _create_simple_wrapper(tool_name, param_info, get_handler)
    
    # Set function metadata for FastMCP introspection
    wrapper.__name__ = tool_name
    wrapper.__qualname__ = tool_name
    
    return wrapper


def _json_type_to_python(json_type: Any) -> Any:
    """Convert JSON Schema type to Python type annotation."""
    if isinstance(json_type, list):
        # Handle union types like ["number", "string", "null"]
        non_null = [t for t in json_type if t != "null"]
        has_null = "null" in json_type
        
        if len(non_null) > 1:
            # Multiple non-null types - create Union
            python_types = [_json_type_to_python(t) for t in non_null]
            # Build Union type dynamically
            if len(python_types) == 2:
                union_type = Union[python_types[0], python_types[1]]  # type: ignore
            elif len(python_types) == 3:
                union_type = Union[python_types[0], python_types[1], python_types[2]]  # type: ignore
            else:
                # Fallback: use first type if more than 3 (shouldn't happen in practice)
                union_type = python_types[0]
            
            if has_null:
                return Optional[union_type]  # type: ignore
            return union_type
        elif non_null:
            # Single non-null type, possibly with null
            base_type = _json_type_to_python(non_null[0])
            if has_null:
                return Optional[base_type]  # type: ignore
            return base_type
        else:
            # Only null (shouldn't happen in practice)
            return str
    
    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": Union[str, bool],  # Accept strings for boolean coercion (e.g., "true" → True)
        "array": list,
        "object": dict,
    }
    return type_map.get(json_type, str)


def _build_annotated_type(
    base_type: Any,
    is_required: bool,
    description: Optional[str] = None,
    enum_values: Optional[list] = None,
) -> Any:
    """Build an Annotated type that carries schema metadata through to FastMCP/Pydantic.

    Returns Annotated[type, Field(...)] when metadata exists, plain type otherwise.
    """
    field_kwargs: dict[str, Any] = {}
    if description:
        field_kwargs["description"] = description
    if enum_values:
        field_kwargs["json_schema_extra"] = {"enum": enum_values}

    if not field_kwargs:
        return Optional[base_type] if not is_required else base_type

    if is_required:
        return Annotated[base_type, Field(**field_kwargs)]
    else:
        return Annotated[Optional[base_type], Field(default=None, **field_kwargs)]


def _create_simple_wrapper(
    tool_name: str,
    param_info: list,
    get_handler: Callable,
) -> Callable:
    """Create wrapper for tools that don't need session injection.

    Args:
        tool_name: Name of the tool
        param_info: List of (name, type, is_required, description, enum_values) tuples
        get_handler: Function that returns the actual handler (e.g., get_tool_wrapper)
    """
    # Build proper signature with typed parameters, preserving schema metadata
    params = []
    for name, ptype, is_required, description, enum_values in param_info:
        annotated_type = _build_annotated_type(ptype, is_required, description, enum_values)
        if is_required:
            param = inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotated_type,
            )
        else:
            param = inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=annotated_type,
            )
        params.append(param)
    
    # Create and set the signature
    sig = inspect.Signature(params, return_annotation=dict)
    
    # The actual implementation collects kwargs
    async def typed_wrapper(**kwargs) -> dict:
        # Handle CLI's kwargs wrapping: {"kwargs": {"name": "..."}} -> {"name": "..."}
        if "kwargs" in kwargs:
            wrapped = kwargs.pop("kwargs")
            if isinstance(wrapped, str):
                import json
                try:
                    wrapped = json.loads(wrapped)
                except json.JSONDecodeError:
                    pass
            if isinstance(wrapped, dict):
                kwargs.update(wrapped)

        # Filter out None values for cleaner handler calls
        filtered = {k: v for k, v in kwargs.items() if v is not None}
        handler = get_handler(tool_name)
        return await handler(**filtered)
    
    typed_wrapper.__signature__ = sig
    typed_wrapper.__name__ = tool_name
    typed_wrapper.__qualname__ = tool_name
    
    return typed_wrapper


def _create_session_wrapper(
    tool_name: str,
    param_info: list,
    get_handler: Callable,
    session_extractor: Callable,
) -> Callable:
    """Create wrapper for tools that need session injection.

    Args:
        tool_name: Name of the tool
        param_info: List of (name, type, is_required, description, enum_values) tuples
        get_handler: Function that returns the actual handler (e.g., get_tool_wrapper)
        session_extractor: Function to extract session_id from context (ctx -> str)
    """
    from mcp.server.fastmcp import Context

    # Build signature: ctx first, then typed params
    params = [
        inspect.Parameter(
            "ctx",
            inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=Optional[Context],
        )
    ]

    for name, ptype, is_required, description, enum_values in param_info:
        annotated_type = _build_annotated_type(ptype, is_required, description, enum_values)
        if is_required:
            param = inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotated_type,
            )
        else:
            param = inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=annotated_type,
            )
        params.append(param)
    
    sig = inspect.Signature(params, return_annotation=dict)
    
    async def typed_wrapper(*, ctx=None, **kwargs) -> dict:
        # Handle CLI's kwargs wrapping: {"kwargs": {"name": "..."}} -> {"name": "..."}
        if "kwargs" in kwargs:
            wrapped = kwargs.pop("kwargs")
            if isinstance(wrapped, str):
                import json
                try:
                    wrapped = json.loads(wrapped)
                except json.JSONDecodeError:
                    pass
            if isinstance(wrapped, dict):
                kwargs.update(wrapped)

        # Inject session if available and not already provided
        if session_extractor and ctx:
            session_id = session_extractor(ctx)
            if session_id and "client_session_id" not in kwargs:
                kwargs["client_session_id"] = session_id
                logger.debug(f"[TYPED_WRAPPER] {tool_name}: injected session_id={session_id}")

        # Filter out None values
        filtered = {k: v for k, v in kwargs.items() if v is not None}
        handler = get_handler(tool_name)
        return await handler(**filtered)
    
    typed_wrapper.__signature__ = sig
    typed_wrapper.__name__ = tool_name
    typed_wrapper.__qualname__ = tool_name
    
    return typed_wrapper
