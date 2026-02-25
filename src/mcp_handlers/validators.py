"""
Parameter validation helpers for MCP tool handlers.

Provides consistent validation for common parameter types (enums, ranges, formats)
with helpful error messages for agents.

LITE MODEL SUPPORT:
- validate_and_coerce_params(): Smart validation that fixes common mistakes
- Helpful error messages guide smaller models on correct formatting
"""

from typing import Dict, Any, Optional, Tuple, List
from mcp.types import TextContent
from .utils import error_response


# ============================================================================
# LITE MODEL SUPPORT: Smart Parameter Validation
# ============================================================================

# Tool parameter schemas for validation (essential tools only for now)
TOOL_PARAM_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "process_agent_update": {
        "required": [],  # agent_id injected from session binding
        "optional": {
            "agent_id": {"type": "string"},  # Optional - server injects from session
            "complexity": {"type": "float", "range": [0.0, 1.0], "default": 0.5},
            "confidence": {"type": "float", "range": [0.0, 1.0]},
            "task_type": {"type": "enum", "values": ["convergent", "divergent", "mixed"], "default": "mixed"},
            "response_text": {"type": "string"},
            "lite": {"type": "bool"},  # Alias for response_mode='minimal'
            "response_mode": {"type": "enum", "values": ["minimal", "compact", "standard", "full", "auto"], "default": "auto"},
        },
        "example": 'process_agent_update(complexity=0.5) or process_agent_update(lite=true)  # agent_id from session',
    },
    "store_knowledge_graph": {
        "required": ["summary"],  # agent_id injected from session binding
        "optional": {
            "agent_id": {"type": "string"},  # Optional - server injects from session
            # LITE-FIRST: defaults to "note" (simplest form)
            "discovery_type": {"type": "enum", "values": ["bug_found", "insight", "pattern", "improvement", "question", "answer", "note", "exploration"], "default": "note"},
            "severity": {"type": "enum", "values": ["low", "medium", "high", "critical"], "default": "medium"},
            "tags": {"type": "list"},
            "details": {"type": "string"},
        },
        "example": 'store_knowledge_graph(summary="Fixed the caching bug")  # agent_id from session',
    },
    "search_knowledge_graph": {
        "required": [],
        "optional": {
            "query": {"type": "string"},
            "agent_id": {"type": "string"},
            "discovery_type": {"type": "enum", "values": ["bug_found", "insight", "pattern", "improvement", "question", "answer", "note", "exploration"]},
            "tags": {"type": "list"},
            "semantic": {"type": "bool", "default": False},
            "include_provenance": {"type": "bool", "default": False},  # Include provenance & lineage chain
            "limit": {"type": "int", "default": 100},
        },
        "example": 'search_knowledge_graph(query="authentication bug", include_provenance=true)',
    },
    "leave_note": {
        "required": ["summary"],  # agent_id injected from session binding
        "optional": {
            "agent_id": {"type": "string"},  # Optional - server injects from session
            "tags": {"type": "list"},
            "response_to": {"type": "object"},  # For threading notes
        },
        "example": 'leave_note(summary="Found a bug in authentication")  # agent_id from session',
    },
    "get_governance_metrics": {
        "required": [],  # agent_id injected from session binding
        "optional": {
            "agent_id": {"type": "string"},  # Optional - server injects from session
            "include_state": {"type": "bool", "default": False},
        },
        "example": 'get_governance_metrics()  # agent_id from session',
    },
    "list_agents": {
        "required": [],
        "optional": {
            "grouped": {"type": "bool", "default": True},
            "summary_only": {"type": "bool", "default": False},
            "status_filter": {"type": "enum", "values": ["all", "active", "waiting_input", "paused", "archived"], "default": "all"},
        },
        "example": 'list_agents(grouped=true, summary_only=true)',
    },
    "identity": {
        "required": [],
        "optional": {
            "name": {"type": "string"},  # Set display name
            "agent_id": {"type": "string"},  # Alias for name
        },
        "example": 'identity() or identity(name="my_agent_opus_20251221")',
    },
    "health_check": {
        "required": [],
        "optional": {},
        "example": 'health_check()',
    },
    "list_tools": {
        "required": [],
        "optional": {
            "lite": {"type": "bool", "default": True},  # LITE-FIRST
            "essential_only": {"type": "bool", "default": False},
            "tier": {"type": "enum", "values": ["all", "essential", "common", "advanced"], "default": "all"},
        },
        "example": 'list_tools(lite=true) or list_tools(essential_only=true)',
    },
}

# ============================================================================
# PARAMETER ALIASES: Accept intuitive names alongside canonical ones
# ============================================================================
# Maps tool_name -> {alias: canonical_name}
# Reduces friction when agents use intuitive but non-canonical param names

# ============================================================================
# MAGNET PATTERN: Accept fuzzy inputs, map to canonical fields
# ============================================================================
# "Loose input, strict output" - agents use varied vocabulary, we normalize
# This is the highest-ROI UX fix for agent friction

PARAM_ALIASES: Dict[str, Dict[str, str]] = {
    "store_knowledge_graph": {
        # All the ways an agent might refer to "the thing I'm storing"
        "discovery": "summary",    # Agent: "I made a discovery" → summary
        "insight": "summary",      # Agent: "Here's my insight" → summary
        "finding": "summary",      # Agent: "My finding is..." → summary
        "content": "summary",      # Agent: "The content is..." → summary
        "text": "summary",         # Agent: "The text..." → summary
        "message": "summary",      # Agent: "Message: ..." → summary
        "note": "summary",         # Agent: "Note: ..." → summary
        "learning": "summary",     # Agent: "I learned..." → summary
        "observation": "summary",  # Agent: "I observed..." → summary
        # Type field synonyms
        "type": "discovery_type",  # "type" → "discovery_type"
        "kind": "discovery_type",  # "kind" → "discovery_type"
        "category": "discovery_type",
    },
    "leave_note": {
        "discovery": "summary",
        "insight": "summary",
        "finding": "summary",
        "text": "summary",
        "note": "summary",
        "content": "summary",
        "message": "summary",
        "learning": "summary",
    },
    "search_knowledge_graph": {
        "search": "query",         # "search" → "query"
        "term": "query",           # "term" → "query"
        "text": "query",           # "text" → "query"
        "find": "query",           # "find" → "query"
    },
    "process_agent_update": {
        # Agents might use different names for response_text
        "text": "response_text",
        "message": "response_text",
        "update": "response_text",
        "content": "response_text",
        "work": "response_text",
        "summary": "response_text",
    },
    "identity": {
        # name/label synonyms
        "label": "name",
        "display_name": "name",
        "nickname": "name",
    },
}


def apply_param_aliases(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Apply parameter aliases - convert intuitive names to canonical ones."""
    aliases = PARAM_ALIASES.get(tool_name)
    if not aliases:
        return arguments

    result = {}
    for key, value in arguments.items():
        canonical = aliases.get(key, key)  # Use alias mapping or keep original
        result[canonical] = value
    return result


# ============================================================================
# GENERIC TYPE COERCION: Works for ALL tools without per-tool schemas
# ============================================================================
# MCP transport sometimes passes strings instead of native types.
# This mapping handles common parameter names across all tools.

GENERIC_PARAM_TYPES: Dict[str, str] = {
    # Float parameters (0.0-1.0 range)
    "complexity": "float_01",
    "confidence": "float_01",
    "similarity_threshold": "float_01",
    "min_similarity": "float_01",
    "connectivity_weight": "float_01",

    # Float parameters (any range)
    "max_age_days": "float",
    "max_age_hours": "float",
    "max_age_seconds": "float",

    # Integer parameters
    "limit": "int",
    "offset": "int",
    "window_hours": "int",
    "recent_days": "int",
    "timeout": "int",
    "head_limit": "int",

    # Boolean parameters
    "include_state": "bool",
    "include_metrics": "bool",
    "include_details": "bool",
    "include_calibration": "bool",
    "include_history": "bool",
    "include_full_description": "bool",
    "include_schema": "bool",
    "include_health_breakdown": "bool",
    "grouped": "bool",
    "summary_only": "bool",
    "loaded_only": "bool",
    "named_only": "bool",
    "standardized": "bool",
    "include_test_agents": "bool",
    "semantic": "bool",
    "exclude_orphans": "bool",
    "force_new": "bool",
    "append_notes": "bool",
    "keep_in_memory": "bool",
    "backup_first": "bool",
    "confirm": "bool",
    "validate": "bool",
    "analyze_patterns": "bool",
    "lite": "bool",
    "essential_only": "bool",
    "include_advanced": "bool",
    "include_details": "bool",
    "include_metrics": "bool",
    "include_state": "bool",
    "include_provenance": "bool",
    "include_calibration": "bool",
    "include_health_breakdown": "bool",
    "include_history": "bool",
    "include_response_chain": "bool",
    "semantic": "bool",
    "dry_run": "bool",
    "complete_package": "bool",
    "multiline": "bool",
    "auto_export_on_significance": "bool",
}


def _apply_generic_coercion(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply generic type coercion for common parameter names.

    This handles MCP transport quirks where strings are passed instead of
    native types (e.g., complexity="0.5" instead of complexity=0.5).

    Works for ALL tools without requiring per-tool schemas.
    """
    if not arguments:
        return arguments

    coerced = dict(arguments)

    for param, value in arguments.items():
        if value is None:
            continue

        param_type = GENERIC_PARAM_TYPES.get(param)
        if not param_type:
            continue

        try:
            if param_type == "float_01":
                # Float with 0.0-1.0 range - coerce type only
                # Range validation is done by schema (with proper error messages)
                if isinstance(value, str):
                    coerced[param] = float(value)
                elif isinstance(value, (int, float)):
                    coerced[param] = float(value)

            elif param_type == "float":
                # Float without range restriction
                if isinstance(value, str):
                    coerced[param] = float(value)
                elif isinstance(value, (int, float)):
                    coerced[param] = float(value)

            elif param_type == "int":
                # Integer
                if isinstance(value, str):
                    coerced[param] = int(float(value))  # Handle "5.0" → 5
                elif isinstance(value, float):
                    coerced[param] = int(value)

            elif param_type == "bool":
                # Boolean - handle various string representations
                if isinstance(value, bool):
                    pass  # Already correct type
                elif isinstance(value, str):
                    lower = value.lower()
                    if lower in ("true", "yes", "1"):
                        coerced[param] = True
                    elif lower in ("false", "no", "0", ""):
                        coerced[param] = False
                elif isinstance(value, int):
                    coerced[param] = bool(value)

        except (ValueError, TypeError):
            # Coercion failed - leave original value for handler to deal with
            pass

    return coerced


def validate_and_coerce_params(
    tool_name: str,
    arguments: Dict[str, Any]
) -> Tuple[Dict[str, Any], Optional[TextContent], List[str]]:
    """
    Smart parameter validation for smaller/lighter models.

    - Catches common formatting mistakes (strings instead of lists, etc.)
    - Coerces types where safe (e.g., "0.5" -> 0.5)
    - Returns helpful error messages with examples
    - Returns list of coercions applied (for transparency)

    Args:
        tool_name: Name of the tool being called
        arguments: Arguments dictionary

    Returns:
        Tuple of (coerced_arguments, error_response, fixes_applied).
        - If validation fails, error_response is provided.
        - fixes_applied is a list of human-readable coercion descriptions.
    """
    # Apply parameter aliases first (e.g., "content" → "summary")
    arguments = apply_param_aliases(tool_name, arguments)
    
    # CRITICAL: Apply generic coercion FIRST (before schema validation)
    # This handles MCP transport quirks where strings are passed instead of native types
    # (e.g., lite="true" instead of lite=true, complexity="0.5" instead of complexity=0.5)
    arguments = _apply_generic_coercion(arguments)

    schema = TOOL_PARAM_SCHEMAS.get(tool_name)
    if not schema:
        # No schema defined - already applied generic coercion above
        return arguments, None, []

    coerced = dict(arguments)
    errors = []
    fixes_applied = []

    # Check required parameters
    for param in schema.get("required", []):
        if param not in arguments or arguments[param] is None:
            errors.append(f"Missing required parameter: '{param}'")

    if errors:
        return arguments, _format_param_error(tool_name, schema, errors, []), []
    
    # Validate and coerce optional parameters
    for param, spec in schema.get("optional", {}).items():
        if param not in arguments or arguments[param] is None:
            continue
            
        value = arguments[param]
        param_type = spec.get("type")
        
        try:
            if param_type == "float":
                # Coerce string to float
                if isinstance(value, str):
                    coerced[param] = float(value)
                    fixes_applied.append(f"Converted '{param}' from string to float")
                elif isinstance(value, (int, float)):
                    coerced[param] = float(value)
                else:
                    errors.append(f"'{param}' must be a number, got {type(value).__name__}")
                    
                # Check range if specified
                if "range" in spec and coerced.get(param) is not None:
                    min_val, max_val = spec["range"]
                    if not (min_val <= coerced[param] <= max_val):
                        errors.append(f"'{param}' must be between {min_val} and {max_val}, got {coerced[param]}")
                        
            elif param_type == "int":
                if isinstance(value, str):
                    coerced[param] = int(value)
                    fixes_applied.append(f"Converted '{param}' from string to int")
                elif isinstance(value, (int, float)):
                    coerced[param] = int(value)
                else:
                    errors.append(f"'{param}' must be an integer, got {type(value).__name__}")
                    
            elif param_type == "bool":
                # Coerce various bool representations
                if isinstance(value, bool):
                    coerced[param] = value
                elif isinstance(value, str):
                    lower = value.lower()
                    if lower in ("true", "yes", "1"):
                        coerced[param] = True
                        fixes_applied.append(f"Converted '{param}' from string to bool")
                    elif lower in ("false", "no", "0"):
                        coerced[param] = False
                        fixes_applied.append(f"Converted '{param}' from string to bool")
                    else:
                        errors.append(f"'{param}' must be true/false, got '{value}'")
                elif isinstance(value, int):
                    coerced[param] = bool(value)
                else:
                    errors.append(f"'{param}' must be true/false, got {type(value).__name__}")
                    
            elif param_type == "string":
                if not isinstance(value, str):
                    coerced[param] = str(value)
                    fixes_applied.append(f"Converted '{param}' to string")
                    
            elif param_type == "list":
                # Handle common mistake: passing comma-separated string instead of list
                if isinstance(value, str):
                    if "," in value:
                        coerced[param] = [item.strip() for item in value.split(",")]
                        fixes_applied.append(f"Converted '{param}' from comma-separated string to list")
                    else:
                        coerced[param] = [value]
                        fixes_applied.append(f"Wrapped '{param}' string in list")
                elif not isinstance(value, list):
                    errors.append(f"'{param}' must be a list, got {type(value).__name__}")
                    
            elif param_type == "enum":
                valid_values = spec.get("values", [])
                
                # DISCOVERY TYPE ALIAS RESOLUTION: Check aliases before validating
                if param == "discovery_type" and value not in valid_values:
                    alias_value = str(value).lower().strip()
                    if alias_value in DISCOVERY_TYPE_ALIASES:
                        coerced[param] = DISCOVERY_TYPE_ALIASES[alias_value]
                        fixes_applied.append(f"Resolved '{param}' alias: '{value}' -> '{coerced[param]}'")
                        continue  # Skip normal enum validation
                
                if value not in valid_values:
                    # Check for case-insensitive match
                    lower_value = str(value).lower()
                    for valid in valid_values:
                        if valid.lower() == lower_value:
                            coerced[param] = valid
                            fixes_applied.append(f"Fixed '{param}' case: '{value}' -> '{valid}'")
                            break
                    else:
                        # For discovery_type, provide alias hint
                        if param == "discovery_type":
                            errors.append(f"'{param}' must be one of {valid_values}, got '{value}'. Common aliases: bug→bug_found, implementation→improvement, observation→insight")
                        else:
                            errors.append(f"'{param}' must be one of {valid_values}, got '{value}'")
                        
        except (ValueError, TypeError) as e:
            errors.append(f"'{param}' conversion failed: {str(e)}")
    
    if errors:
        return arguments, _format_param_error(tool_name, schema, errors, fixes_applied), fixes_applied

    # Apply generic coercion for any params NOT already handled by schema
    # This catches params that exist in GENERIC_PARAM_TYPES but not in the tool's schema
    schema_params = set(schema.get("optional", {}).keys()) | set(schema.get("required", []))
    for param, value in list(coerced.items()):
        if param not in schema_params and value is not None:
            param_type = GENERIC_PARAM_TYPES.get(param)
            if param_type:
                try:
                    if param_type == "float_01":
                        if isinstance(value, str):
                            coerced[param] = max(0.0, min(1.0, float(value)))
                        elif isinstance(value, (int, float)):
                            coerced[param] = max(0.0, min(1.0, float(value)))
                    elif param_type == "float":
                        if isinstance(value, str):
                            coerced[param] = float(value)
                    elif param_type == "int":
                        if isinstance(value, str):
                            coerced[param] = int(float(value))
                        elif isinstance(value, float):
                            coerced[param] = int(value)
                    elif param_type == "bool":
                        if isinstance(value, str):
                            lower = value.lower()
                            if lower in ("true", "yes", "1"):
                                coerced[param] = True
                            elif lower in ("false", "no", "0", ""):
                                coerced[param] = False
                        elif isinstance(value, int):
                            coerced[param] = bool(value)
                except (ValueError, TypeError):
                    pass  # Leave original value

    return coerced, None, fixes_applied


def _format_param_error(
    tool_name: str,
    schema: Dict[str, Any],
    errors: List[str],
    fixes_applied: List[str]
) -> TextContent:
    """Format a helpful error message for parameter validation failures.
    
    Uses standardized error taxonomy with specific error codes.
    """
    from .error_helpers import missing_parameter_error, invalid_parameter_type_error
    
    # Parse errors to determine specific error types
    missing_params = []
    type_errors = []
    
    for err in errors:
        if err.startswith("Missing required parameter"):
            # Extract parameter name: "Missing required parameter: 'param_name'"
            param_match = err.split("'")
            if len(param_match) >= 2:
                missing_params.append(param_match[1])
        elif "must be" in err.lower() and "got" in err.lower():
            # Type error: "Parameter 'x' must be type, got other_type"
            type_errors.append(err)
    
    # If we have specific missing parameters, use standardized error
    if missing_params:
        # Use first missing parameter for primary error
        param_name = missing_params[0]
        return missing_parameter_error(param_name, tool_name=tool_name)[0]
    
    # If we have type errors, try to extract and use standardized error
    if type_errors:
        # Parse first type error
        first_error = type_errors[0]
        # Try to extract parameter name and types
        # Format: "'param' must be type, got other_type"
        import re
        match = re.search(r"'(\w+)' must be (\w+), got (\w+)", first_error)
        if match:
            param_name, expected_type, provided_type = match.groups()
            return invalid_parameter_type_error(
                param_name, expected_type, provided_type, tool_name=tool_name
            )[0]
    
    # Fallback to detailed error message for complex cases
    required = schema.get("required", [])
    optional = schema.get("optional", {})
    example = schema.get("example", "")
    
    error_msg = f"Parameter error for '{tool_name}':\n"
    error_msg += "  Errors:\n"
    for err in errors:
        error_msg += f"    - {err}\n"
    
    if fixes_applied:
        error_msg += "  Fixes attempted:\n"
        for fix in fixes_applied:
            error_msg += f"    - {fix}\n"
    
    error_msg += f"\n  Required parameters: {required if required else 'none'}\n"
    
    if optional:
        error_msg += "  Optional parameters:\n"
        for param, spec in list(optional.items())[:5]:  # Show first 5
            param_type = spec.get("type", "any")
            default = spec.get("default", "")
            values = spec.get("values", [])
            if values:
                error_msg += f"    - {param}: one of {values}"
            else:
                error_msg += f"    - {param}: {param_type}"
            if default:
                error_msg += f" (default: {default})"
            error_msg += "\n"
        if len(optional) > 5:
            error_msg += f"    ... and {len(optional) - 5} more\n"
    
    if example:
        error_msg += f"\n  Example: {example}\n"
    
    return error_response(
        error_msg,
        error_code="PARAMETER_ERROR",
        error_category="validation_error",
        details={
            "tool_name": tool_name,
            "errors": errors,
            "fixes_attempted": fixes_applied,
            "required_params": required,
        },
        recovery={
            "action": "Check parameter types and try again",
            "related_tools": ["describe_tool", "list_tools"],
            "workflow": [
                "1. Use describe_tool(tool_name='" + tool_name + "') for full schema",
                "2. Fix the parameters listed above",
                "3. Retry the tool call"
            ]
        }
    )


# Enum definitions for validation
DISCOVERY_TYPES = {"bug_found", "insight", "pattern", "improvement", "question", "answer", "note", "exploration"}
SEVERITY_LEVELS = {"low", "medium", "high", "critical"}
DISCOVERY_STATUSES = {"open", "resolved", "archived", "disputed"}
TASK_TYPES = {"convergent", "divergent", "mixed"}

# Semantic aliases for task types (maps natural-language task names to governance types)
TASK_TYPE_ALIASES = {
    # convergent: standardization, compliance, reducing entropy
    "refactoring": "convergent", "formatting": "convergent", "cleanup": "convergent",
    "linting": "convergent", "bugfix": "convergent", "bug_fix": "convergent",
    "testing": "convergent", "documentation": "convergent", "migration": "convergent",
    "fix": "convergent", "lint": "convergent", "test": "convergent",
    # divergent: creative exploration, increasing possibility space
    "feature": "divergent", "exploration": "divergent", "research": "divergent",
    "design": "divergent", "brainstorming": "divergent", "prototyping": "divergent",
    "experiment": "divergent", "spike": "divergent",
    # mixed: both convergent and divergent elements
    "debugging": "mixed", "review": "mixed", "integration": "mixed",
    "deployment": "mixed", "maintenance": "mixed", "ops": "mixed",
}
RESPONSE_TYPES = {"extend", "question", "disagree", "support"}
LIFECYCLE_STATUSES = {"active", "waiting_input", "paused", "archived", "deleted"}
HEALTH_STATUSES = {"healthy", "moderate", "critical", "unknown"}

# Semantic aliases for discovery types (maps common variations to canonical types)
DISCOVERY_TYPE_ALIASES = {
    # bug_found aliases
    "bug": "bug_found",
    "bugfix": "bug_found",
    "fix": "bug_found",
    "defect": "bug_found",
    "issue": "bug_found",
    "error": "bug_found",
    
    # improvement aliases
    "implementation": "improvement",
    "enhancement": "improvement",
    "feature": "improvement",
    "refactor": "improvement",
    "optimization": "improvement",
    "upgrade": "improvement",
    "ticket": "improvement",  # Common workflow term
    "task": "improvement",  # Common workflow term
    "story": "improvement",  # Agile term
    "epic": "improvement",  # Agile term
    "ux_feedback": "improvement",  # UX feedback → improvement (ChatGPT friction fix)
    "feedback": "improvement",  # General feedback → improvement
    "ux": "improvement",  # UX → improvement
    
    # insight aliases
    "observation": "insight",
    "finding": "insight",
    "discovery": "insight",
    "learning": "insight",
    "realization": "insight",
    
    # pattern aliases
    "trend": "pattern",
    "recurring": "pattern",
    
    # question aliases
    "query": "question",
    "ask": "question",
    "unknown": "question",
    
    # answer aliases
    "reply": "answer",
    "response": "answer",
    "solution": "answer",
    
    # note aliases
    "memo": "note",
    "comment": "note",
    "remark": "note",
    
    # exploration aliases
    "experiment": "exploration",
    "investigation": "exploration",
    "research": "exploration",
    "analysis": "exploration",
}


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def _find_closest_match(value: str, valid_values: set, max_distance: int = 3) -> Optional[str]:
    """Find closest match using Levenshtein distance."""
    value_lower = value.lower()
    best_match = None
    best_distance = max_distance + 1
    
    for valid in valid_values:
        distance = _levenshtein_distance(value_lower, valid.lower())
        if distance < best_distance:
            best_distance = distance
            best_match = valid
    
    return best_match if best_distance <= max_distance else None


def validate_enum(
    value: Any,
    valid_values: set,
    param_name: str,
    suggestions: Optional[List[str]] = None
) -> Tuple[Optional[str], Optional[TextContent]]:
    """
    Validate an enum parameter value.
    
    Args:
        value: The value to validate
        valid_values: Set of valid enum values
        param_name: Name of the parameter (for error messages)
        suggestions: Optional list of suggested values (for typo detection)
        
    Returns:
        Tuple of (validated_value, error_response). If value is invalid, error_response is provided.
    """
    if value is None:
        return None, None  # None is allowed (optional parameters)
    
    if value not in valid_values:
        # Try to find close matches for typo detection
        close_matches = []
        if suggestions:
            value_lower = str(value).lower()
            for suggestion in suggestions:
                if value_lower in suggestion.lower() or suggestion.lower() in value_lower:
                    close_matches.append(suggestion)
        
        error_msg = f"Invalid {param_name}: '{value}'. Must be one of: {', '.join(sorted(valid_values))}"
        if close_matches:
            error_msg += f". Did you mean: {', '.join(close_matches)}?"
        
        return None, error_response(
            error_msg,
            details={"error_type": "invalid_enum", "param_name": param_name, "provided_value": value},
            recovery={
                "action": f"Use one of the valid {param_name} values",
                "related_tools": ["list_tools"],
                "workflow": [
                    f"1. Check tool description for valid {param_name} values",
                    f"2. Use one of: {', '.join(sorted(valid_values))}",
                    "3. Retry with correct value"
                ]
            }
        )
    
    return value, None


def validate_discovery_type(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """
    Validate discovery_type parameter with smart coercion.
    
    Features:
    - Accepts semantic aliases (e.g., "implementation" → "improvement")
    - Fuzzy matching for typos (e.g., "insigt" → "insight")
    - Clear "did you mean?" suggestions
    
    Returns:
        Tuple of (coerced_value, error_response). Error includes suggestions if invalid.
    """
    if value is None:
        return None, None  # None is allowed (defaults to "note")
    
    value_str = str(value).lower().strip()
    
    # 1. Check exact match (case-insensitive)
    for valid in DISCOVERY_TYPES:
        if value_str == valid.lower():
            return valid, None
    
    # 2. Check semantic aliases
    if value_str in DISCOVERY_TYPE_ALIASES:
        canonical = DISCOVERY_TYPE_ALIASES[value_str]
        # Return coerced value (silent coercion - alias is expected behavior)
        return canonical, None
    
    # 3. Check fuzzy match (typos)
    closest = _find_closest_match(value_str, DISCOVERY_TYPES, max_distance=2)
    if closest:
        # Return error with suggestion - don't auto-coerce typos
        return None, error_response(
            f"Invalid discovery_type: '{value}'. Did you mean '{closest}'?",
            details={
                "error_type": "invalid_discovery_type",
                "provided_value": value,
                "suggestion": closest,
                "valid_types": sorted(DISCOVERY_TYPES)
            },
            recovery={
                "action": f"Use discovery_type='{closest}' or one of the valid types",
                "valid_types": sorted(DISCOVERY_TYPES),
                "aliases": "Common aliases accepted: bug→bug_found, implementation→improvement, observation→insight"
            }
        )
    
    # 4. No match found - return helpful error with all aliases
    # Build comprehensive alias list for error message
    alias_groups = {}
    for alias, canonical in DISCOVERY_TYPE_ALIASES.items():
        if canonical not in alias_groups:
            alias_groups[canonical] = []
        alias_groups[canonical].append(alias)
    
    # Format aliases for display
    alias_display = {}
    for canonical, aliases in alias_groups.items():
        alias_display[canonical] = ", ".join(sorted(aliases))
    
    return None, error_response(
        f"Invalid discovery_type: '{value}'. Must be one of: {', '.join(sorted(DISCOVERY_TYPES))}",
        details={
            "error_type": "invalid_discovery_type",
            "provided_value": value,
            "valid_types": sorted(DISCOVERY_TYPES),
            "all_aliases": alias_display
        },
        recovery={
            "action": "Use one of the valid discovery types or their aliases",
            "valid_types": sorted(DISCOVERY_TYPES),
            "aliases": alias_display,
            "common_examples": {
                "bug_found": "bug, fix, issue, error, defect",
                "improvement": "ticket, task, implementation, enhancement, feature, refactor",
                "insight": "observation, finding, discovery, learning",
                "note": "memo, comment, remark (default if omitted)",
                "exploration": "experiment, investigation, research, analysis"
            },
            "tip": "When in doubt, use 'note' (the simplest form, default)"
        }
    )


def validate_severity(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate severity parameter."""
    return validate_enum(value, SEVERITY_LEVELS, "severity", list(SEVERITY_LEVELS))


def validate_discovery_status(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate discovery status parameter."""
    return validate_enum(value, DISCOVERY_STATUSES, "status", list(DISCOVERY_STATUSES))


def validate_task_type(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate task_type parameter. Accepts governance types or natural-language aliases."""
    if value is None:
        return "mixed", None
    value_str = str(value).strip().lower()
    if not value_str:
        return "mixed", None
    # Exact match
    if value_str in TASK_TYPES:
        return value_str, None
    # Alias match
    if value_str in TASK_TYPE_ALIASES:
        return TASK_TYPE_ALIASES[value_str], None
    # Unknown — return error with valid options
    return None, error_response(
        f"Invalid task_type: '{value}'. Must be one of: {', '.join(sorted(TASK_TYPES))} "
        f"(or aliases like refactoring, feature, debugging, etc.)",
        details={"valid_types": sorted(TASK_TYPES), "aliases": dict(TASK_TYPE_ALIASES)},
    )


def validate_response_type(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate response_type parameter."""
    return validate_enum(value, RESPONSE_TYPES, "response_type", list(RESPONSE_TYPES))


def validate_lifecycle_status(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate lifecycle_status parameter."""
    return validate_enum(value, LIFECYCLE_STATUSES, "lifecycle_status", list(LIFECYCLE_STATUSES))


def validate_health_status(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate health_status parameter."""
    return validate_enum(value, HEALTH_STATUSES, "health_status", list(HEALTH_STATUSES))


def validate_discovery_id(discovery_id: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """
    Validate discovery_id format.
    
    Discovery IDs are ISO timestamp strings (e.g., "2025-12-13T01:23:45.678901")
    or can be custom strings. We validate:
    1. Non-empty string
    2. Reasonable length (< 200 chars to prevent abuse)
    3. No dangerous characters (prevent injection)
    
    Args:
        discovery_id: Discovery ID to validate
        
    Returns:
        Tuple of (validated_id, error_response)
    """
    import re
    from datetime import datetime
    
    if discovery_id is None:
        return None, error_response(
            "discovery_id cannot be empty",
            details={"error_type": "invalid_discovery_id"},
            recovery={"action": "Provide a non-empty discovery_id"}
        )
    
    if isinstance(discovery_id, (int, float)):
        # Defensive coercion: MCP clients sometimes pass numeric IDs (e.g. 2025 instead of "2025-12-20T...")
        discovery_id = str(discovery_id)

    if not isinstance(discovery_id, str):
        return None, error_response(
            f"Invalid discovery_id: must be a string, got {type(discovery_id).__name__}",
            details={"error_type": "invalid_type", "param_name": "discovery_id"},
            recovery={"action": "Provide discovery_id as a string"}
        )
    
    if not discovery_id.strip():
        return None, error_response(
            "discovery_id cannot be empty or whitespace",
            details={"error_type": "invalid_discovery_id"},
            recovery={"action": "Provide a non-empty discovery_id"}
        )
    
    # Length check (prevent abuse)
    if len(discovery_id) > 200:
        return None, error_response(
            f"discovery_id too long: {len(discovery_id)} characters (max: 200)",
            details={"error_type": "discovery_id_too_long", "length": len(discovery_id)},
            recovery={"action": "Provide a discovery_id under 200 characters"}
        )
    
    # Check for dangerous characters (prevent injection)
    # Allow: alphanumeric, ISO timestamp chars (:, -, T, .), and safe separators
    if not re.match(r'^[a-zA-Z0-9_\-:T.]+$', discovery_id):
        invalid_chars = ''.join(set(re.sub(r'[a-zA-Z0-9_\-:T.]', '', discovery_id)))
        return None, error_response(
            f"Invalid discovery_id format: contains invalid characters: {invalid_chars}",
            details={
                "error_type": "invalid_discovery_id_format",
                "invalid_characters": invalid_chars
            },
            recovery={
                "action": "Use only alphanumeric characters, ISO timestamp format, or safe separators",
                "example": "2025-12-13T01:23:45.678901"
            }
        )
    
    return discovery_id, None


def validate_range(
    value: Any,
    min_val: float,
    max_val: float,
    param_name: str,
    inclusive: bool = True
) -> Tuple[Optional[float], Optional[TextContent]]:
    """
    Validate a numeric parameter is within a range.
    
    Args:
        value: The value to validate
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        param_name: Name of the parameter (for error messages)
        inclusive: If True, range is [min, max]. If False, range is (min, max).
        
    Returns:
        Tuple of (validated_value, error_response). If value is invalid, error_response is provided.
    """
    if value is None:
        return None, None  # None is allowed (optional parameters)
    
    try:
        num_value = float(value)
    except (TypeError, ValueError):
        return None, error_response(
            f"Invalid {param_name}: '{value}'. Must be a number.",
            details={"error_type": "invalid_type", "param_name": param_name, "provided_value": value},
            recovery={
                "action": f"Provide a numeric value for {param_name}",
                "workflow": [f"1. Ensure {param_name} is a number", "2. Retry with correct value"]
            }
        )
    
    if inclusive:
        if not (min_val <= num_value <= max_val):
            return None, error_response(
                f"Invalid {param_name}: {num_value}. Must be in range [{min_val}, {max_val}].",
                details={"error_type": "out_of_range", "param_name": param_name, "provided_value": num_value, "valid_range": [min_val, max_val]},
                recovery={
                    "action": f"Provide a value between {min_val} and {max_val}",
                    "workflow": [f"1. Ensure {param_name} is in [{min_val}, {max_val}]", "2. Retry with correct value"]
                }
            )
    else:
        if not (min_val < num_value < max_val):
            return None, error_response(
                f"Invalid {param_name}: {num_value}. Must be in range ({min_val}, {max_val}).",
                details={"error_type": "out_of_range", "param_name": param_name, "provided_value": num_value, "valid_range": (min_val, max_val)},
                recovery={
                    "action": f"Provide a value between {min_val} and {max_val} (exclusive)",
                    "workflow": [f"1. Ensure {param_name} is in ({min_val}, {max_val})", "2. Retry with correct value"]
                }
            )
    
    return num_value, None


def validate_response_text(value: Any, max_length: int = 50000) -> Tuple[Optional[str], Optional[TextContent]]:
    """
    Validate response_text parameter.

    Args:
        value: The response text to validate
        max_length: Maximum allowed length in characters (default: 50KB)

    Returns:
        Tuple of (validated_text, error_response)
    """
    if value is None:
        return "", None  # Empty string if None

    if isinstance(value, str) and not value.strip():
        return None, error_response(
            "response_text cannot be empty. Provide a brief summary of what you did.",
            details={"error_type": "empty_value", "param_name": "response_text"},
            recovery={
                "action": "Provide a non-empty response_text describing your work",
                "example": 'process_agent_update(response_text="Completed code review", complexity=0.5)',
            }
        )

    if not isinstance(value, str):
        return None, error_response(
            f"Invalid response_text: must be a string, got {type(value).__name__}",
            details={"error_type": "invalid_type", "param_name": "response_text"},
            recovery={
                "action": "Provide response_text as a string",
                "workflow": ["1. Ensure response_text is a string", "2. Retry with correct type"]
            }
        )

    if len(value) > max_length:
        return None, error_response(
            f"response_text too long: {len(value)} characters (max: {max_length})",
            details={
                "error_type": "text_too_long",
                "param_name": "response_text",
                "length": len(value),
                "max_length": max_length
            },
            recovery={
                "action": f"Provide response_text under {max_length} characters",
                "workflow": [
                    f"1. Trim response_text to under {max_length} characters",
                    "2. Retry with shorter text"
                ]
            }
        )

    return value, None


def validate_complexity(value: Any) -> Tuple[Optional[float], Optional[TextContent]]:
    """Validate complexity parameter (0.0 to 1.0)."""
    return validate_range(value, 0.0, 1.0, "complexity")


def validate_confidence(value: Any) -> Tuple[Optional[float], Optional[TextContent]]:
    """Validate confidence parameter (0.0 to 1.0)."""
    return validate_range(value, 0.0, 1.0, "confidence")


def validate_ethical_drift(value: Any) -> Tuple[Optional[List[float]], Optional[TextContent]]:
    """
    Validate ethical_drift parameter (list of 3 floats).

    Args:
        value: Should be a list of 3 numbers

    Returns:
        Tuple of (validated_list, error_response)
    """
    if value is None:
        return None, None  # None is allowed (optional)

    if not isinstance(value, list):
        return None, error_response(
            f"Invalid ethical_drift: must be a list of 3 numbers, got {type(value).__name__}",
            details={"error_type": "invalid_type", "param_name": "ethical_drift", "provided_value": value},
            recovery={
                "action": "Provide ethical_drift as a list of 3 numbers: [primary_drift, coherence_loss, complexity_contribution]",
                "workflow": ["1. Format as list: [0.01, 0.02, 0.03]", "2. Retry with correct format"]
            }
        )

    if len(value) not in (3, 4):
        return None, error_response(
            f"Invalid ethical_drift: must have 3 or 4 components, got {len(value)}",
            details={"error_type": "invalid_length", "param_name": "ethical_drift", "provided_value": value},
            recovery={
                "action": "Provide 3 or 4 numbers: [emotional_drift, epistemic_drift, behavioral_drift] or [calibration, complexity, coherence, stability]",
                "workflow": ["1. Format as list of 3-4 numbers: [0.01, 0.02, 0.03]", "2. Retry with correct format"]
            }
        )

    # Validate each component is numeric
    validated = []
    for i, component in enumerate(value):
        num_value, error = validate_range(component, -1.0, 1.0, f"ethical_drift[{i}]")
        if error:
            return None, error
        validated.append(num_value)

    return validated, None


def validate_file_path_policy(file_path: str) -> Tuple[Optional[str], Optional[TextContent]]:
    """
    Validate file path against project policies (anti-proliferation).

    POLICIES:
    1. Test scripts must be in tests/ directory to prevent proliferation.
    2. Markdown files in migration target directories should use knowledge graph instead.

    Args:
        file_path: Path to validate

    Returns:
        Tuple of (warning_message, None) if violation detected, (None, None) if OK.
        Returns warning, not error, to inform but not block.
    """
    import os
    from pathlib import Path

    if file_path is None:
        return None, None

    # Normalize path
    file_path = os.path.normpath(file_path)
    basename = os.path.basename(file_path)
    dirname = os.path.dirname(file_path)
    path_parts = file_path.split(os.sep)

    # Check for test file proliferation (test_*.py or demo_*.py in root)
    if (basename.startswith("test_") or basename.startswith("demo_")) and basename.endswith(".py"):
        # Check if it's in tests/ directory
        if not dirname.endswith("tests") and "tests" not in dirname.split(os.sep):
            warning = (
                f"⚠️ POLICY VIOLATION: Test script '{basename}' should be in 'tests/' directory.\n"
                f"Location: {file_path}\n"
                f"Policy: All test_*.py and demo_*.py files must be in tests/ to prevent proliferation.\n"
                f"Action: Move this file to tests/ directory or rename it."
            )
            return warning, None

    # Check for markdown file proliferation
    if basename.endswith(".md"):
        # Approved markdown files (from policy)
        APPROVED_FILES = {
            'README.md', 'CHANGELOG.md', 'START_HERE.md',
            'docs/README.md',
            'docs/guides/ONBOARDING.md',
            'docs/guides/TROUBLESHOOTING.md',
            'docs/guides/MCP_SETUP.md',
            'docs/guides/THRESHOLDS.md',
            'docs/reference/AI_ASSISTANT_GUIDE.md',
            'governance_core/README.md',
            'scripts/README.md',
            'data/README.md',
            'demos/README.md',
            'tools/README.md',
        }
        
        # Migration target directories (should use knowledge graph instead)
        MIGRATION_TARGET_DIRS = {'analysis', 'fixes', 'reflection', 'proposals'}
        
        # Check if file is in migration target directory
        if 'docs' in path_parts:
            docs_index = path_parts.index('docs')
            if docs_index + 1 < len(path_parts):
                subdir = path_parts[docs_index + 1]
                if subdir in MIGRATION_TARGET_DIRS:
                    rel_path = os.path.relpath(file_path, os.getcwd()) if os.path.isabs(file_path) else file_path
                    if rel_path not in APPROVED_FILES:
                        warning = (
                            f"⚠️ POLICY VIOLATION: Markdown file in migration target directory.\n"
                            f"Location: {file_path}\n"
                            f"Policy: Files in docs/{subdir}/ should use store_knowledge_graph() instead of creating markdown files.\n"
                            f"Action: Use store_knowledge_graph() for insights/discoveries, or consolidate into existing approved docs.\n"
                            f"Approved files: {', '.join(sorted(APPROVED_FILES))}"
                        )
                        return warning, None
        
        # Check if file is not approved and not in guides/reference
        rel_path = os.path.relpath(file_path, os.getcwd()) if os.path.isabs(file_path) else file_path
        if rel_path not in APPROVED_FILES:
            # Check if it's in guides/ or reference/ (these are OK)
            if 'docs' in path_parts:
                docs_index = path_parts.index('docs')
                if docs_index + 1 < len(path_parts):
                    subdir = path_parts[docs_index + 1]
                    if subdir not in {'guides', 'reference', 'archive'}:
                        # Not in approved location - warn
                        warning = (
                            f"⚠️ POLICY WARNING: New markdown file not on approved list.\n"
                            f"Location: {file_path}\n"
                            f"Policy: New markdown files should be ≥500 words and on approved list, or use store_knowledge_graph() instead.\n"
                            f"Action: Consider using store_knowledge_graph() for insights, or ensure file is ≥500 words and consolidate into existing docs.\n"
                            f"Approved files: {', '.join(sorted(APPROVED_FILES))}"
                        )
                        return warning, None

    return None, None


def sanitize_agent_name(raw: str) -> str:
    """
    Sanitize agent name to safe format. Never fails - always returns usable name.

    UX FIX (Dec 2025): Don't reject bad names, fix them.
    "ChatGPT macOS app" → "ChatGPT_macOS_app"
    "my agent!!!" → "my_agent"
    "" or None → auto-generate

    Args:
        raw: Raw agent name (may contain invalid chars, spaces, etc.)

    Returns:
        Sanitized name safe for filesystem/URLs, or auto-generated if empty
    """
    import re
    from datetime import datetime

    if not raw:
        return f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Replace invalid chars with underscore
    clean = re.sub(r'[^a-zA-Z0-9_-]', '_', raw)
    # Collapse multiple underscores
    clean = re.sub(r'_+', '_', clean)
    # Strip leading/trailing underscores
    clean = clean.strip('_-')

    # If too short after cleaning, auto-generate
    if len(clean) < 3:
        return f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    return clean


def validate_agent_id_format(agent_id: str) -> Tuple[Optional[str], Optional[TextContent]]:
    """
    Validate and sanitize agent_id format for safety (filesystem, URLs, etc).

    UX FIX (Dec 2025): Auto-sanitize instead of failing.
    Bad names get fixed, not rejected. Never returns an error.

    Args:
        agent_id: Agent ID to validate/sanitize

    Returns:
        Tuple of (sanitized_id, None) - always succeeds.
    """
    # Sanitize instead of fail - UX improvement for clunky platforms like ChatGPT
    sanitized = sanitize_agent_name(agent_id)

    return sanitized, None


def validate_agent_id_policy(agent_id: str) -> Tuple[Optional[str], Optional[TextContent]]:
    """
    DISABLED: No more policy warnings. Use whatever agent_id you want.
    
    Previously discouraged test/demo agent_ids, but that was annoying.
    Now it's a no-op - use test IDs, demo IDs, whatever. We don't care.
    
    Args:
        agent_id: Agent ID to validate (ignored)

    Returns:
        (None, None) - always passes
    """
    # No-op: No warnings, no blocks, no herding cats
    return None, None


def validate_agent_id_reserved_names(agent_id: str) -> Tuple[Optional[str], Optional[TextContent]]:
    """
    Validate agent_id against reserved/privileged names.

    SECURITY: Block privileged names that could cause confusion or privilege escalation.

    Args:
        agent_id: Agent ID to validate

    Returns:
        Tuple of (None, error_response) if reserved name detected, (agent_id, None) if OK.
    """
    if agent_id is None:
        return None, None

    agent_id_lower = agent_id.lower()

    # Reserved system/privileged names
    RESERVED_NAMES = {
        # System/privileged
        "system", "admin", "root", "superuser", "administrator", "sudo",
        # Special values
        "null", "undefined", "none", "anonymous", "guest", "default",
        # MCP protocol
        "mcp", "server", "client", "handler", "transport",
        # Governance system
        "governance", "monitor", "arbiter", "validator", "auditor",
        # Security
        "security", "auth", "identity", "certificate",
    }

    # Reserved prefixes
    RESERVED_PREFIXES = ("system_", "admin_", "root_", "mcp_", "governance_", "auth_")

    # Check exact match
    if agent_id_lower in RESERVED_NAMES:
        return None, error_response(
            f"SECURITY: agent_id '{agent_id}' is reserved for system use",
            details={
                "error_type": "reserved_agent_id",
                "reason": "Reserved name blocked to prevent privilege confusion"
            },
            recovery={
                "action": "Choose a different agent_id that describes your work",
                "example": "my_agent_work_20251209",
                "note": "Reserved names include: system, admin, root, null, etc."
            }
        )

    # Check reserved prefixes
    if agent_id_lower.startswith(RESERVED_PREFIXES):
        return None, error_response(
            f"SECURITY: agent_id '{agent_id}' uses reserved prefix",
            details={
                "error_type": "reserved_prefix",
                "reason": "Reserved prefixes blocked to prevent privilege confusion"
            },
            recovery={
                "action": "Choose an agent_id without system/admin/governance prefixes",
                "example": "my_agent_work_20251209"
            }
        )

    return agent_id, None


def detect_script_creation_avoidance(response_text: str) -> list:
    """
    Detect if agent is creating scripts to avoid using MCP tools.

    POLICY: Agents should use MCP tools, not create scripts to bypass them.

    Args:
        response_text: Agent's response text

    Returns:
        List of warning messages if avoidance detected
    """
    import re

    warnings = []

    if not response_text:
        return warnings

    text_lower = response_text.lower()

    # Pattern 1: Creating scripts to test instead of using tools
    script_test_patterns = [
        (r'creat(?:e|ing|ed)\s+(?:a\s+)?(?:test\s+)?script\s+to\s+(?:test|verify|check)',
         'Creating scripts to test functionality'),
        (r'writ(?:e|ing|ten)\s+(?:a\s+)?quick\s+(?:test\s+)?script',
         'Writing quick test scripts'),
        (r'make\s+(?:a\s+)?(?:simple\s+)?script\s+to\s+(?:test|verify)',
         'Making scripts to test'),
    ]

    for pattern, description in script_test_patterns:
        if re.search(pattern, text_lower):
            warnings.append(
                f"⚠️ AVOIDANCE DETECTED: {description}\n"
                f"Policy: Use MCP tools instead of creating test scripts.\n"
                f"Recommended: Use process_agent_update, simulate_update, or other governance tools.\n"
                f"Why: Scripts bypass governance tracking and create project clutter."
            )
            break  # Only warn once

    # Pattern 2: Mentions avoiding MCP or tools
    avoidance_patterns = [
        r'(?:avoid|skip|bypass)(?:ing)?\s+(?:the\s+)?(?:mcp|tools?|governance)',
        r'without\s+using\s+(?:mcp|tools?|governance)',
        r'instead\s+of\s+(?:mcp|tools?|calling)',
    ]

    for pattern in avoidance_patterns:
        if re.search(pattern, text_lower):
            warnings.append(
                f"⚠️ AVOIDANCE LANGUAGE DETECTED: Response mentions avoiding MCP/tools\n"
                f"Policy: All work should be logged via process_agent_update for governance tracking.\n"
                f"Why: Bypassing governance defeats the purpose of the monitoring system.\n"
                f"Action: Use MCP tools as intended - they're designed to help, not hinder."
            )
            break

    # Pattern 3: Creating standalone test files
    if re.search(r'(?:creat|writ)(?:e|ing|ed)\s+.*?\.py.*?(?:to\s+test|for\s+testing)', text_lower):
        # Check if it mentions putting in tests/ directory
        if not re.search(r'tests?/', text_lower):
            warnings.append(
                f"⚠️ STANDALONE FILE CREATION: Creating .py files for testing\n"
                f"Policy: Test files belong in tests/ directory, not as standalone scripts.\n"
                f"Better: Use MCP tools directly or write proper pytest tests in tests/.\n"
                f"Why: Standalone test scripts bypass governance and create project clutter."
            )

    return warnings

