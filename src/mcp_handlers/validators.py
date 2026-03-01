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
PARAM_ALIASES: Dict[str, Dict[str, str]] = {'store_knowledge_graph': {'discovery': 'summary', 'insight': 'summary', 'finding': 'summary', 'content': 'summary', 'text': 'summary', 'message': 'summary', 'note': 'summary', 'learning': 'summary', 'observation': 'summary', 'type': 'discovery_type', 'kind': 'discovery_type', 'category': 'discovery_type'}, 'leave_note': {'discovery': 'summary', 'insight': 'summary', 'finding': 'summary', 'text': 'summary', 'note': 'summary', 'content': 'summary', 'message': 'summary', 'learning': 'summary'}, 'search_knowledge_graph': {'search': 'query', 'term': 'query', 'text': 'query', 'find': 'query'}, 'process_agent_update': {'text': 'response_text', 'message': 'response_text', 'update': 'response_text', 'content': 'response_text', 'work': 'response_text', 'summary': 'response_text'}, 'identity': {'label': 'name', 'display_name': 'name', 'nickname': 'name'}, 'agent': {'op': 'action'}}

def apply_param_aliases(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Apply parameter aliases - convert intuitive names to canonical ones."""
    aliases = PARAM_ALIASES.get(tool_name)
    if not aliases:
        return arguments
    result = {}
    for key, value in arguments.items():
        canonical = aliases.get(key, key)
        result[canonical] = value
    return result
VALIDATOR_VERSION = '2.0.0'

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
            if param_type == 'float_01':
                if isinstance(value, str):
                    coerced[param] = float(value)
                elif isinstance(value, (int, float)):
                    coerced[param] = float(value)
            elif param_type == 'float':
                if isinstance(value, str):
                    coerced[param] = float(value)
                elif isinstance(value, (int, float)):
                    coerced[param] = float(value)
            elif param_type == 'int':
                if isinstance(value, str):
                    coerced[param] = int(float(value))
                elif isinstance(value, float):
                    coerced[param] = int(value)
            elif param_type == 'bool':
                if isinstance(value, bool):
                    pass
                elif isinstance(value, str):
                    lower = value.lower()
                    if lower in ('true', 'yes', '1'):
                        coerced[param] = True
                    elif lower in ('false', 'no', '0', ''):
                        coerced[param] = False
                elif isinstance(value, int):
                    coerced[param] = bool(value)
            elif param_type == 'list':
                if isinstance(value, str):
                    if ',' in value:
                        coerced[param] = [item.strip() for item in value.split(',')]
                    else:
                        coerced[param] = [value]
        except (ValueError, TypeError):
            pass
    if 'discovery_type' in coerced and isinstance(coerced['discovery_type'], str):
        dtype = coerced['discovery_type'].lower().strip()
        if dtype in DISCOVERY_TYPE_ALIASES:
            coerced['discovery_type'] = DISCOVERY_TYPE_ALIASES[dtype]
    return coerced
SEVERITY_LEVELS = {'low', 'medium', 'high', 'critical'}
DISCOVERY_STATUSES = {'open', 'resolved', 'archived', 'disputed'}
RESPONSE_TYPES = {'extend', 'question', 'disagree', 'support'}
LIFECYCLE_STATUSES = {'active', 'waiting_input', 'paused', 'archived', 'deleted'}
HEALTH_STATUSES = {'healthy', 'moderate', 'critical', 'unknown'}
DISCOVERY_TYPE_ALIASES = {'bug': 'bug_found', 'bugfix': 'bug_found', 'fix': 'bug_found', 'defect': 'bug_found', 'issue': 'bug_found', 'error': 'bug_found', 'implementation': 'improvement', 'enhancement': 'improvement', 'feature': 'improvement', 'refactor': 'improvement', 'optimization': 'improvement', 'upgrade': 'improvement', 'ticket': 'improvement', 'task': 'improvement', 'story': 'improvement', 'epic': 'improvement', 'ux_feedback': 'improvement', 'feedback': 'improvement', 'ux': 'improvement', 'observation': 'insight', 'finding': 'insight', 'discovery': 'insight', 'learning': 'insight', 'realization': 'insight', 'trend': 'pattern', 'recurring': 'pattern', 'query': 'question', 'ask': 'question', 'unknown': 'question', 'reply': 'answer', 'response': 'answer', 'solution': 'answer', 'memo': 'note', 'comment': 'note', 'remark': 'note', 'experiment': 'exploration', 'investigation': 'exploration', 'research': 'exploration', 'analysis': 'exploration'}

def validate_enum(value: Any, valid_values: set, param_name: str, suggestions: Optional[List[str]]=None) -> Tuple[Optional[str], Optional[TextContent]]:
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
        return (None, None)
    if value not in valid_values:
        close_matches = []
        if suggestions:
            value_lower = str(value).lower()
            for suggestion in suggestions:
                if value_lower in suggestion.lower() or suggestion.lower() in value_lower:
                    close_matches.append(suggestion)
        error_msg = f"Invalid {param_name}: '{value}'. Must be one of: {', '.join(sorted(valid_values))}"
        if close_matches:
            error_msg += f". Did you mean: {', '.join(close_matches)}?"
        return (None, error_response(error_msg, details={'error_type': 'invalid_enum', 'param_name': param_name, 'provided_value': value}, recovery={'action': f'Use one of the valid {param_name} values', 'related_tools': ['list_tools'], 'workflow': [f'1. Check tool description for valid {param_name} values', f"2. Use one of: {', '.join(sorted(valid_values))}", '3. Retry with correct value']}))
    return (value, None)

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
        return (None, None)
    value_str = str(value).lower().strip()
    for valid in DISCOVERY_TYPES:
        if value_str == valid.lower():
            return (valid, None)
    if value_str in DISCOVERY_TYPE_ALIASES:
        canonical = DISCOVERY_TYPE_ALIASES[value_str]
        return (canonical, None)
    closest = _find_closest_match(value_str, DISCOVERY_TYPES, max_distance=2)
    if closest:
        return (None, error_response(f"Invalid discovery_type: '{value}'. Did you mean '{closest}'?", details={'error_type': 'invalid_discovery_type', 'provided_value': value, 'suggestion': closest, 'valid_types': sorted(DISCOVERY_TYPES)}, recovery={'action': f"Use discovery_type='{closest}' or one of the valid types", 'valid_types': sorted(DISCOVERY_TYPES), 'aliases': 'Common aliases accepted: bug→bug_found, implementation→improvement, observation→insight'}))
    alias_groups = {}
    for alias, canonical in DISCOVERY_TYPE_ALIASES.items():
        if canonical not in alias_groups:
            alias_groups[canonical] = []
        alias_groups[canonical].append(alias)
    alias_display = {}
    for canonical, aliases in alias_groups.items():
        alias_display[canonical] = ', '.join(sorted(aliases))
    return (None, error_response(f"Invalid discovery_type: '{value}'. Must be one of: {', '.join(sorted(DISCOVERY_TYPES))}", details={'error_type': 'invalid_discovery_type', 'provided_value': value, 'valid_types': sorted(DISCOVERY_TYPES), 'all_aliases': alias_display}, recovery={'action': 'Use one of the valid discovery types or their aliases', 'valid_types': sorted(DISCOVERY_TYPES), 'aliases': alias_display, 'common_examples': {'bug_found': 'bug, fix, issue, error, defect', 'improvement': 'ticket, task, implementation, enhancement, feature, refactor', 'insight': 'observation, finding, discovery, learning', 'note': 'memo, comment, remark (default if omitted)', 'exploration': 'experiment, investigation, research, analysis'}, 'tip': "When in doubt, use 'note' (the simplest form, default)"}))

def validate_severity(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate severity parameter."""
    return validate_enum(value, SEVERITY_LEVELS, 'severity', list(SEVERITY_LEVELS))

def validate_discovery_status(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate discovery status parameter."""
    return validate_enum(value, DISCOVERY_STATUSES, 'status', list(DISCOVERY_STATUSES))

def validate_response_type(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate response_type parameter."""
    return validate_enum(value, RESPONSE_TYPES, 'response_type', list(RESPONSE_TYPES))

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
        return (None, error_response('discovery_id cannot be empty', details={'error_type': 'invalid_discovery_id'}, recovery={'action': 'Provide a non-empty discovery_id'}))
    if isinstance(discovery_id, (int, float)):
        discovery_id = str(discovery_id)
    if not isinstance(discovery_id, str):
        return (None, error_response(f'Invalid discovery_id: must be a string, got {type(discovery_id).__name__}', details={'error_type': 'invalid_type', 'param_name': 'discovery_id'}, recovery={'action': 'Provide discovery_id as a string'}))
    if not discovery_id.strip():
        return (None, error_response('discovery_id cannot be empty or whitespace', details={'error_type': 'invalid_discovery_id'}, recovery={'action': 'Provide a non-empty discovery_id'}))
    if len(discovery_id) > 200:
        return (None, error_response(f'discovery_id too long: {len(discovery_id)} characters (max: 200)', details={'error_type': 'discovery_id_too_long', 'length': len(discovery_id)}, recovery={'action': 'Provide a discovery_id under 200 characters'}))
    if not re.match('^[a-zA-Z0-9_\\-:T.]+$', discovery_id):
        invalid_chars = ''.join(set(re.sub('[a-zA-Z0-9_\\-:T.]', '', discovery_id)))
        return (None, error_response(f'Invalid discovery_id format: contains invalid characters: {invalid_chars}', details={'error_type': 'invalid_discovery_id_format', 'invalid_characters': invalid_chars}, recovery={'action': 'Use only alphanumeric characters, ISO timestamp format, or safe separators', 'example': '2025-12-13T01:23:45.678901'}))
    return (discovery_id, None)

def validate_range(value: Any, min_val: float, max_val: float, param_name: str, inclusive: bool=True) -> Tuple[Optional[float], Optional[TextContent]]:
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
        return (None, None)
    try:
        num_value = float(value)
    except (TypeError, ValueError):
        return (None, error_response(f"Invalid {param_name}: '{value}'. Must be a number.", details={'error_type': 'invalid_type', 'param_name': param_name, 'provided_value': value}, recovery={'action': f'Provide a numeric value for {param_name}', 'workflow': [f'1. Ensure {param_name} is a number', '2. Retry with correct value']}))
    if inclusive:
        if not min_val <= num_value <= max_val:
            return (None, error_response(f'Invalid {param_name}: {num_value}. Must be in range [{min_val}, {max_val}].', details={'error_type': 'out_of_range', 'param_name': param_name, 'provided_value': num_value, 'valid_range': [min_val, max_val]}, recovery={'action': f'Provide a value between {min_val} and {max_val}', 'workflow': [f'1. Ensure {param_name} is in [{min_val}, {max_val}]', '2. Retry with correct value']}))
    elif not min_val < num_value < max_val:
        return (None, error_response(f'Invalid {param_name}: {num_value}. Must be in range ({min_val}, {max_val}).', details={'error_type': 'out_of_range', 'param_name': param_name, 'provided_value': num_value, 'valid_range': (min_val, max_val)}, recovery={'action': f'Provide a value between {min_val} and {max_val} (exclusive)', 'workflow': [f'1. Ensure {param_name} is in ({min_val}, {max_val})', '2. Retry with correct value']}))
    return (num_value, None)

def validate_response_text(value: Any, max_length: int=50000) -> Tuple[Optional[str], Optional[TextContent]]:
    """
    Validate response_text parameter.

    Args:
        value: The response text to validate
        max_length: Maximum allowed length in characters (default: 50KB)

    Returns:
        Tuple of (validated_text, error_response)
    """
    if value is None:
        return ('', None)
    if isinstance(value, str) and (not value.strip()):
        return (None, error_response('response_text cannot be empty. Provide a brief summary of what you did.', details={'error_type': 'empty_value', 'param_name': 'response_text'}, recovery={'action': 'Provide a non-empty response_text describing your work', 'example': 'process_agent_update(response_text="Completed code review", complexity=0.5)'}))
    if not isinstance(value, str):
        return (None, error_response(f'Invalid response_text: must be a string, got {type(value).__name__}', details={'error_type': 'invalid_type', 'param_name': 'response_text'}, recovery={'action': 'Provide response_text as a string', 'workflow': ['1. Ensure response_text is a string', '2. Retry with correct type']}))
    if len(value) > max_length:
        return (None, error_response(f'response_text too long: {len(value)} characters (max: {max_length})', details={'error_type': 'text_too_long', 'param_name': 'response_text', 'length': len(value), 'max_length': max_length}, recovery={'action': f'Provide response_text under {max_length} characters', 'workflow': [f'1. Trim response_text to under {max_length} characters', '2. Retry with shorter text']}))
    return (value, None)

def validate_complexity(value: Any) -> Tuple[Optional[float], Optional[TextContent]]:
    """Validate complexity parameter (0.0 to 1.0)."""
    return validate_range(value, 0.0, 1.0, 'complexity')

def validate_confidence(value: Any) -> Tuple[Optional[float], Optional[TextContent]]:
    """Validate confidence parameter (0.0 to 1.0)."""
    return validate_range(value, 0.0, 1.0, 'confidence')

VALID_TASK_TYPES = {
    "convergent", "divergent", "mixed", "refactoring", "bugfix", "testing",
    "documentation", "feature", "exploration", "research", "design", "debugging",
    "review", "deployment",
}


def validate_task_type(value: Any) -> Tuple[Optional[str], Optional[TextContent]]:
    """Validate task_type parameter against known types."""
    return validate_enum(value, VALID_TASK_TYPES, "task_type")


def validate_ethical_drift(value: Any) -> Tuple[Optional[List[float]], Optional[TextContent]]:
    """
    Validate ethical_drift parameter (list of 3 floats).

    Args:
        value: Should be a list of 3 numbers

    Returns:
        Tuple of (validated_list, error_response)
    """
    if value is None:
        return (None, None)
    if not isinstance(value, list):
        return (None, error_response(f'Invalid ethical_drift: must be a list of 3 numbers, got {type(value).__name__}', details={'error_type': 'invalid_type', 'param_name': 'ethical_drift', 'provided_value': value}, recovery={'action': 'Provide ethical_drift as a list of 3 numbers: [primary_drift, coherence_loss, complexity_contribution]', 'workflow': ['1. Format as list: [0.01, 0.02, 0.03]', '2. Retry with correct format']}))
    if len(value) not in (3, 4):
        return (None, error_response(f'Invalid ethical_drift: must have 3 or 4 components, got {len(value)}', details={'error_type': 'invalid_length', 'param_name': 'ethical_drift', 'provided_value': value}, recovery={'action': 'Provide 3 or 4 numbers: [emotional_drift, epistemic_drift, behavioral_drift] or [calibration, complexity, coherence, stability]', 'workflow': ['1. Format as list of 3-4 numbers: [0.01, 0.02, 0.03]', '2. Retry with correct format']}))
    validated = []
    for i, component in enumerate(value):
        num_value, error = validate_range(component, -1.0, 1.0, f'ethical_drift[{i}]')
        if error:
            return (None, error)
        validated.append(num_value)
    return (validated, None)

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
        return (None, None)
    file_path = os.path.normpath(file_path)
    basename = os.path.basename(file_path)
    dirname = os.path.dirname(file_path)
    path_parts = file_path.split(os.sep)
    if (basename.startswith('test_') or basename.startswith('demo_')) and basename.endswith('.py'):
        if not dirname.endswith('tests') and 'tests' not in dirname.split(os.sep):
            warning = f"⚠️ POLICY VIOLATION: Test script '{basename}' should be in 'tests/' directory.\nLocation: {file_path}\nPolicy: All test_*.py and demo_*.py files must be in tests/ to prevent proliferation.\nAction: Move this file to tests/ directory or rename it."
            return (warning, None)
    if basename.endswith('.md'):
        APPROVED_FILES = {'README.md', 'CHANGELOG.md', 'START_HERE.md', 'docs/README.md', 'docs/guides/ONBOARDING.md', 'docs/guides/TROUBLESHOOTING.md', 'docs/guides/MCP_SETUP.md', 'docs/guides/THRESHOLDS.md', 'docs/reference/AI_ASSISTANT_GUIDE.md', 'governance_core/README.md', 'scripts/README.md', 'data/README.md', 'demos/README.md', 'tools/README.md'}
        MIGRATION_TARGET_DIRS = {'analysis', 'fixes', 'reflection', 'proposals'}
        if 'docs' in path_parts:
            docs_index = path_parts.index('docs')
            if docs_index + 1 < len(path_parts):
                subdir = path_parts[docs_index + 1]
                if subdir in MIGRATION_TARGET_DIRS:
                    rel_path = os.path.relpath(file_path, os.getcwd()) if os.path.isabs(file_path) else file_path
                    if rel_path not in APPROVED_FILES:
                        warning = f"⚠️ POLICY VIOLATION: Markdown file in migration target directory.\nLocation: {file_path}\nPolicy: Files in docs/{subdir}/ should use store_knowledge_graph() instead of creating markdown files.\nAction: Use store_knowledge_graph() for insights/discoveries, or consolidate into existing approved docs.\nApproved files: {', '.join(sorted(APPROVED_FILES))}"
                        return (warning, None)
        rel_path = os.path.relpath(file_path, os.getcwd()) if os.path.isabs(file_path) else file_path
        if rel_path not in APPROVED_FILES:
            if 'docs' in path_parts:
                docs_index = path_parts.index('docs')
                if docs_index + 1 < len(path_parts):
                    subdir = path_parts[docs_index + 1]
                    if subdir not in {'guides', 'reference', 'archive'}:
                        warning = f"⚠️ POLICY WARNING: New markdown file not on approved list.\nLocation: {file_path}\nPolicy: New markdown files should be ≥500 words and on approved list, or use store_knowledge_graph() instead.\nAction: Consider using store_knowledge_graph() for insights, or ensure file is ≥500 words and consolidate into existing docs.\nApproved files: {', '.join(sorted(APPROVED_FILES))}"
                        return (warning, None)
    return (None, None)

def sanitize_agent_name(agent_id: str) -> str:
    """Strip invalid characters from agent_id, keeping only [a-zA-Z0-9_-]."""
    import re
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', agent_id)
    # Collapse multiple underscores and strip leading/trailing
    sanitized = re.sub(r'_+', '_', sanitized).strip('_-')
    # Ensure minimum length
    if len(sanitized) < 3:
        sanitized = sanitized + '_agent'
    return sanitized


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
    sanitized = sanitize_agent_name(agent_id)
    return (sanitized, None)

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
        return (None, None)
    agent_id_lower = agent_id.lower()
    RESERVED_NAMES = {'system', 'admin', 'root', 'superuser', 'administrator', 'sudo', 'null', 'undefined', 'none', 'anonymous', 'guest', 'default', 'mcp', 'server', 'client', 'handler', 'transport', 'governance', 'monitor', 'arbiter', 'validator', 'auditor', 'security', 'auth', 'identity', 'certificate'}
    RESERVED_PREFIXES = ('system_', 'admin_', 'root_', 'mcp_', 'governance_', 'auth_')
    if agent_id_lower in RESERVED_NAMES:
        return (None, error_response(f"SECURITY: agent_id '{agent_id}' is reserved for system use", details={'error_type': 'reserved_agent_id', 'reason': 'Reserved name blocked to prevent privilege confusion'}, recovery={'action': 'Choose a different agent_id that describes your work', 'example': 'my_agent_work_20251209', 'note': 'Reserved names include: system, admin, root, null, etc.'}))
    if agent_id_lower.startswith(RESERVED_PREFIXES):
        return (None, error_response(f"SECURITY: agent_id '{agent_id}' uses reserved prefix", details={'error_type': 'reserved_prefix', 'reason': 'Reserved prefixes blocked to prevent privilege confusion'}, recovery={'action': 'Choose an agent_id without system/admin/governance prefixes', 'example': 'my_agent_work_20251209'}))
    return (agent_id, None)


def validate_agent_id_policy(agent_id: str) -> Tuple[Optional[str], Optional[TextContent]]:
    """Policy check on agent_id (reserved names only).

    Returns (warning_string, None) if concern, (None, None) if OK.
    Never blocks — warnings are advisory.
    """
    if not agent_id:
        return (None, None)
    _, err = validate_agent_id_reserved_names(agent_id)
    if err:
        return ("Agent ID uses a reserved name", None)
    return (None, None)


def detect_script_creation_avoidance(response_text: str) -> List[str]:
    """Detect patterns in response text that suggest test/script avoidance.

    Returns list of warning strings (empty if no concerns).
    """
    if not response_text:
        return []
    warnings = []
    avoidance_phrases = [
        "skipping tests",
        "no tests needed",
        "tests not necessary",
        "skip test creation",
    ]
    lower = response_text.lower()
    for phrase in avoidance_phrases:
        if phrase in lower:
            warnings.append(f"Possible test avoidance detected: '{phrase}'")
    return warnings