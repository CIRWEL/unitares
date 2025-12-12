"""
Parameter validation helpers for MCP tool handlers.

Provides consistent validation for common parameter types (enums, ranges, formats)
with helpful error messages for agents.
"""

from typing import Dict, Any, Optional, Tuple, List
from mcp.types import TextContent
from .utils import error_response


# Enum definitions for validation
DISCOVERY_TYPES = {"bug_found", "insight", "pattern", "improvement", "question", "answer", "note"}
SEVERITY_LEVELS = {"low", "medium", "high", "critical"}
DISCOVERY_STATUSES = {"open", "resolved", "archived", "disputed"}
TASK_TYPES = {"convergent", "divergent", "mixed"}
RESPONSE_TYPES = {"extend", "question", "disagree", "support"}
LIFECYCLE_STATUSES = {"active", "waiting_input", "paused", "archived", "deleted"}
HEALTH_STATUSES = {"healthy", "moderate", "critical", "unknown"}


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
    """Validate discovery_type parameter."""
    return validate_enum(value, DISCOVERY_TYPES, "discovery_type", list(DISCOVERY_TYPES))


def validate_severity(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate severity parameter."""
    return validate_enum(value, SEVERITY_LEVELS, "severity", list(SEVERITY_LEVELS))


def validate_discovery_status(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate discovery status parameter."""
    return validate_enum(value, DISCOVERY_STATUSES, "status", list(DISCOVERY_STATUSES))


def validate_task_type(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate task_type parameter."""
    return validate_enum(value, TASK_TYPES, "task_type", list(TASK_TYPES))


def validate_response_type(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate response_type parameter."""
    return validate_enum(value, RESPONSE_TYPES, "response_type", list(RESPONSE_TYPES))


def validate_lifecycle_status(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate lifecycle_status parameter."""
    return validate_enum(value, LIFECYCLE_STATUSES, "lifecycle_status", list(LIFECYCLE_STATUSES))


def validate_health_status(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate health_status parameter."""
    return validate_enum(value, HEALTH_STATUSES, "health_status", list(HEALTH_STATUSES))


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

    if len(value) != 3:
        return None, error_response(
            f"Invalid ethical_drift: must have exactly 3 components, got {len(value)}",
            details={"error_type": "invalid_length", "param_name": "ethical_drift", "provided_value": value},
            recovery={
                "action": "Provide exactly 3 numbers: [primary_drift, coherence_loss, complexity_contribution]",
                "workflow": ["1. Format as list of 3 numbers: [0.01, 0.02, 0.03]", "2. Retry with correct format"]
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


def validate_agent_id_format(agent_id: str) -> Tuple[Optional[str], Optional[TextContent]]:
    """
    Validate agent_id format for safety (filesystem, URLs, etc).

    POLICY: Agent IDs should only contain safe characters: [a-zA-Z0-9_-]

    Args:
        agent_id: Agent ID to validate

    Returns:
        Tuple of (None, error_response) if invalid format, (sanitized_id, None) if OK.
    """
    import re

    if agent_id is None or not agent_id:
        return None, error_response(
            "agent_id cannot be empty",
            details={"error_type": "invalid_agent_id"},
            recovery={"action": "Provide a non-empty agent_id"}
        )

    # Check for invalid characters
    if not re.match(r'^[a-zA-Z0-9_-]+$', agent_id):
        invalid_chars = ''.join(set(re.sub(r'[a-zA-Z0-9_-]', '', agent_id)))
        return None, error_response(
            f"Invalid agent_id format: '{agent_id}' contains invalid characters: {invalid_chars}",
            details={
                "error_type": "invalid_agent_id_format",
                "invalid_characters": invalid_chars
            },
            recovery={
                "action": "Use only letters, numbers, underscores, and hyphens in agent_id",
                "example": "claude_desktop_work_20251209"
            }
        )

    return agent_id, None


def validate_agent_id_policy(agent_id: str) -> Tuple[Optional[str], Optional[TextContent]]:
    """
    Validate agent_id against anti-avoidance policies.

    POLICY: Discourage test/demo agent_ids that suggest avoiding the governance system.

    Args:
        agent_id: Agent ID to validate

    Returns:
        Tuple of (warning_message, None) if policy concern detected, (None, None) if OK.
    """
    if agent_id is None:
        return None, None

    agent_id_lower = agent_id.lower()

    # Patterns that suggest test/temporary usage (avoiding real engagement)
    DISCOURAGED_PATTERNS = [
        ('test_', 'Test agents suggest temporary/experimental usage'),
        ('demo_', 'Demo agents suggest avoiding real governance tracking'),
        ('temp_', 'Temporary agents suggest avoiding persistent governance'),
        ('tmp_', 'Temporary agents suggest avoiding persistent governance'),
        ('fake_', 'Fake agents suggest avoiding real governance'),
        ('_test', 'Test suffix suggests temporary/experimental usage'),
    ]

    # Very generic names that suggest low engagement
    GENERIC_NAMES = {'test', 'demo', 'agent', 'agent1', 'foo', 'bar', 'example', 'sample'}

    # Check for discouraged patterns
    for pattern, reason in DISCOURAGED_PATTERNS:
        if pattern in agent_id_lower:
            warning = (
                f"⚠️ POLICY WARNING: Agent ID '{agent_id}' contains '{pattern}'.\n"
                f"Reason: {reason}.\n"
                f"Note: Test/demo agents are auto-archived after 6 hours and with ≤2 updates.\n"
                f"Suggestion: Use a meaningful agent_id like 'platform_model_purpose_date' for real work.\n"
                f"Examples: 'claude_desktop_analysis_20251209', 'cursor_feature_work_20251209'"
            )
            return warning, None

    # Check for generic names
    if agent_id_lower in GENERIC_NAMES:
        warning = (
            f"⚠️ POLICY WARNING: Agent ID '{agent_id}' is too generic.\n"
            f"Reason: Generic names suggest temporary usage and may cause ID collisions.\n"
            f"Suggestion: Use a descriptive agent_id that identifies platform, purpose, and date.\n"
            f"Examples: 'claude_desktop_analysis_20251209', 'cursor_feature_work_20251209'"
        )
        return warning, None

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
                "example": "claude_desktop_work_20251209",
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
                "example": "claude_desktop_work_20251209"
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

