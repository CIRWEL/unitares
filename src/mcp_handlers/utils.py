"""
Common utilities for MCP tool handlers.
"""

from typing import Dict, Any, Sequence, Tuple, Optional
from mcp.types import TextContent
import json
import sys
import asyncio
from datetime import datetime, date
from enum import Enum

# Import type definitions
from .types import (
    ErrorResponseDict,
    SuccessResponseDict,
    AgentMetadataDict,
    GovernanceMetricsDict,
    ToolArgumentsDict
)

# Import structured logging
from src.logging_utils import get_logger
logger = get_logger(__name__)

# Rate-limiting cache for calibration messages
# Only show calibration message if error changed significantly or hasn't been shown recently
_calibration_message_cache = {
    'last_error': None,           # Last calibration error value shown
    'last_shown_update': 0,       # Update count when last shown
    'significance_threshold': 0.05,  # Only show if error changed by >5%
    'min_updates_between': 10     # Minimum updates between showing message
}


def compute_agent_signature(
    agent_id: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Centralized agent signature computation.
    
    Single source of truth for signature logic - called by both 
    success_response() and error_response() to ensure consistency.
    
    Priority order:
    1. Explicit agent_id parameter
    2. Context agent_id (set at dispatch entry)
    3. Session binding lookup
    
    Args:
        agent_id: Explicit agent_id override
        arguments: Tool arguments (for session lookup)
        
    Returns:
        Dict with agent_uuid, label, bound, ts
    """
    try:
        from .context import get_context_agent_id
        from .shared import get_mcp_server
        mcp_server = get_mcp_server()

        # Priority 1: Explicit agent_id
        # Priority 2: Context (set at dispatch entry using identity_v2)
        # NOTE (Dec 2025): We no longer use legacy identity.get_bound_agent_id()
        # The context agent_id is now set by identity_v2.resolve_session_identity()
        # at dispatch entry, ensuring consistency across all tools.
        context_bound_id = get_context_agent_id()
        bound_id = agent_id or context_bound_id

        # Debug at debug level (not info) to reduce noise
        logger.debug(f"compute_agent_signature: agent_id={agent_id}, context={context_bound_id}, final={bound_id}")

        if not bound_id:
            return {"uuid": None}

        # bound_id is AUTHORITATIVE (from identity_v2)
        # Only look up metadata to get the label, NOT to override the UUID
        agent_uuid = bound_id  # ALWAYS use bound_id as the UUID

        # Try to get label and structured_id from metadata
        display_label = None
        structured_id = None
        if bound_id in mcp_server.agent_metadata:
            meta = mcp_server.agent_metadata[bound_id]
            display_label = getattr(meta, 'label', None)
            structured_id = getattr(meta, 'structured_id', None)

        # Clean signature (v2.5.2) - minimal fields
        signature = {"uuid": agent_uuid}
        if structured_id:
            signature["agent_id"] = structured_id
        if display_label:
            signature["display_name"] = display_label
        return signature
            
    except Exception as e:
        logger.debug(f"compute_agent_signature error: {e}")
        return {"uuid": None}


def error_response(
    message: str, 
    details: Optional[Dict[str, Any]] = None, 
    recovery: Optional[Dict[str, Any]] = None, 
    context: Optional[Dict[str, Any]] = None,
    error_code: Optional[str] = None,
    error_category: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None
) -> TextContent:
    """
    Create an error response with optional recovery guidance and system context.
    
    SECURITY: Sanitizes error messages to prevent internal structure leakage.
    
    Args:
        message: Error message (will be sanitized)
        details: Optional additional error details (will be sanitized)
        recovery: Optional recovery suggestions for AGI agents
        context: Optional system context (what was happening, system state, etc.)
        error_code: Optional machine-readable error code (e.g., "AGENT_NOT_FOUND")
        error_category: Optional error category: "validation_error", "auth_error", "system_error"
                      Helps categorize errors for consistent handling
        
    Returns:
        TextContent with error response
        
    Example:
        >>> error_response(
        ...     "Agent not found",
        ...     error_code="AGENT_NOT_FOUND",
        ...     error_category="validation_error",
        ...     recovery={"action": "Call get_agent_api_key"}
        ... )
    """
    # SECURITY: Sanitize error message to prevent internal structure leakage
    sanitized_message = _sanitize_error_message(message)
    
    response = {
        "success": False,
        "error": sanitized_message,
        "server_time": datetime.now().isoformat()  # Time context for agents
    }
    
    # Add machine-readable error code if provided
    if error_code:
        response["error_code"] = error_code
    
    # Add error category if provided (standardized: validation_error, auth_error, system_error)
    if error_category:
        if error_category not in ["validation_error", "auth_error", "system_error"]:
            logger.warning(f"Unknown error_category '{error_category}', using as-is")
        response["error_category"] = error_category
    
    # Sanitize details if provided
    if details:
        sanitized_details = {}
        for key, value in details.items():
            if isinstance(value, str):
                sanitized_details[key] = _sanitize_error_message(value)
            else:
                sanitized_details[key] = value
        response.update(sanitized_details)
    
    # Add recovery guidance if provided
    if recovery:
        response["recovery"] = recovery
    
    # Add system context if provided (helps understand WHY error occurred)
    # Note: Context is user-provided, so less risk of leakage
    if context:
        response["context"] = context
    
    # Add agent signature using centralized computation
    response["agent_signature"] = compute_agent_signature(arguments=arguments)
    
    # FIX: Use _make_json_serializable to prevent JSON parsing errors
    # This matches the pattern used in success_response() for consistency
    try:
        serializable_response = _make_json_serializable(response)
        json_text = json.dumps(serializable_response, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        # Log serialization error but try to recover
        logger.error(f"JSON serialization error in error_response: {e}", exc_info=True)
        # Try one more time with default=str fallback
        try:
            serializable_response = _make_json_serializable(response)
            json_text = json.dumps(serializable_response, indent=2, ensure_ascii=False, default=str)
        except Exception as e2:
            # Last resort: return minimal error response
            logger.error(f"Failed to serialize error response even after conversion: {e2}", exc_info=True)
            minimal_response = {
                "success": False,
                "error": sanitized_message,
                "error_code": error_code or "SERIALIZATION_ERROR",
                "server_time": datetime.now().isoformat()
            }
            json_text = json.dumps(minimal_response, ensure_ascii=False)
    
    return TextContent(
        type="text",
        text=json_text
    )


def format_metrics_report(
    metrics: Dict[str, Any],
    agent_id: str,
    include_timestamp: bool = True,
    include_context: bool = True,
    format_style: str = "structured"
) -> Dict[str, Any]:
    """
    Standardize metric reporting with agent_id and context.
    
    Ensures all metric reports include:
    - agent_id (required)
    - timestamp (optional, default: True)
    - EISV metrics (if available)
    - Health status (if available)
    - Other context (optional)
    
    Args:
        metrics: Dictionary of metrics (may include E, I, S, V, coherence, etc.)
        agent_id: Agent identifier (required)
        include_timestamp: Include ISO timestamp (default: True)
        include_context: Include additional context like health_status (default: True)
        format_style: "structured" (dict) or "text" (formatted string)
    
    Returns:
        Standardized metrics dict with agent_id and context, or formatted string if style="text"
    
    Example:
        >>> metrics = {"E": 0.8, "I": 0.9, "S": 0.1, "V": -0.05}
        >>> report = format_metrics_report(metrics, "agent_123")
        >>> report["agent_id"]  # "agent_123"
        >>> report["timestamp"]  # "2025-12-10T18:30:00.123456"
    """
    standardized = {
        "agent_id": agent_id,
        **metrics  # Include all original metrics
    }
    
    # Always ensure agent_id is present (even if it was in metrics)
    standardized["agent_id"] = agent_id
    
    # Add timestamp if requested
    if include_timestamp:
        standardized["timestamp"] = datetime.now().isoformat()
    
    # Add context if requested
    if include_context:
        # Ensure health_status is accessible
        if "health_status" not in standardized and "health_status" in metrics:
            standardized["health_status"] = metrics["health_status"]
        
        # Ensure EISV metrics are clearly labeled
        # Create eisv dict from flat E, I, S, V if they exist
        eisv_metrics = {}
        for key in ["E", "I", "S", "V"]:
            if key in metrics:
                eisv_metrics[key] = metrics[key]
        if eisv_metrics:
            standardized["eisv"] = eisv_metrics
            # Keep flat E, I, S, V for backward compatibility and easy access
            # Both formats are valid: metrics["E"] and metrics["eisv"]["E"]
    
    if format_style == "text":
        return format_metrics_text(standardized)
    
    return standardized


def format_metrics_text(metrics: Dict[str, Any]) -> str:
    """
    Format metrics as human-readable text with agent_id and context.
    
    Args:
        metrics: Standardized metrics dict (from format_metrics_report)
    
    Returns:
        Formatted string with agent_id, timestamp, and metrics
    """
    lines = []
    
    # Header with agent_id
    agent_id = metrics.get("agent_id", "unknown")
    lines.append(f"Agent: {agent_id}")
    
    # Timestamp
    if "timestamp" in metrics:
        lines.append(f"Timestamp: {metrics['timestamp']}")
    
    # Health status (if available)
    if "health_status" in metrics:
        status = metrics["health_status"]
        lines.append(f"Health: {status}")
    
    # EISV metrics
    if "eisv" in metrics:
        eisv = metrics["eisv"]
        lines.append(f"EISV: E={eisv.get('E', 0):.3f} I={eisv.get('I', 0):.3f} S={eisv.get('S', 0):.3f} V={eisv.get('V', 0):.3f}")
    elif any(k in metrics for k in ["E", "I", "S", "V"]):
        e = metrics.get("E", 0)
        i = metrics.get("I", 0)
        s = metrics.get("S", 0)
        v = metrics.get("V", 0)
        lines.append(f"EISV: E={e:.3f} I={i:.3f} S={s:.3f} V={v:.3f}")
    
    # Other key metrics
    key_metrics = ["coherence", "risk_score", "phi", "verdict", "lambda1"]  # risk_score is primary, attention_score is deprecated
    for key in key_metrics:
        if key in metrics:
            value = metrics[key]
            if isinstance(value, float):
                lines.append(f"{key}: {value:.3f}")
            else:
                lines.append(f"{key}: {value}")
    
    return "\n".join(lines)


def _sanitize_error_message(message: str) -> str:
    """
    Sanitize error messages to prevent internal structure leakage.
    
    Removes:
    - File paths
    - Line numbers
    - Internal variable names
    - Stack traces
    - Module paths
    """
    if not isinstance(message, str):
        return str(message)
    
    import re
    
    # Remove file paths (but keep filename)
    message = re.sub(r'/[^\s]+/([^/\s]+\.py)', r'\1', message)
    
    # Remove line numbers
    message = re.sub(r':\d+:', ':', message)
    message = re.sub(r'line \d+', 'line N', message)
    
    # Remove internal variable names (common patterns)
    message = re.sub(r'\b[A-Z_]{3,}\b', lambda m: m.group() if m.group() in ['RISK', 'ERROR', 'SUCCESS'] else 'CONFIG', message)
    
    # Remove stack trace indicators
    message = re.sub(r'Traceback.*?File', 'Error in', message, flags=re.DOTALL)
    message = re.sub(r'File "[^"]+", line \d+', 'Internal error', message)
    
    # Remove module paths (keep module name)
    message = re.sub(r'[a-z_]+\.([a-z_]+)', r'\1', message)
    
    # Limit length to prevent information leakage
    from config.governance_config import config
    max_length = config.MAX_ERROR_MESSAGE_LENGTH
    if len(message) > max_length:
        message = message[:max_length] + "..."
    
    return message


def _make_json_serializable(obj: Any) -> Any:
    """
    Recursively convert non-JSON-serializable types to JSON-compatible types.
    
    Handles:
    - numpy types (float64, int64, etc.) → float/int
    - numpy arrays → lists
    - datetime/date objects → ISO format strings
    - Enum types → their values
    - Other non-serializable types → strings
    
    Args:
        obj: Object to convert (can be dict, list, tuple, or primitive)
        
    Returns:
        JSON-serializable version of the object
    """
    # Handle None
    if obj is None:
        return None
    
    # Handle numpy types
    try:
        import numpy as np
        if isinstance(obj, (np.integer, np.floating)):
            return float(obj) if isinstance(obj, np.floating) else int(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
    except ImportError:
        pass  # numpy not available
    
    # Handle datetime/date objects
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    
    # Handle Enum types
    if isinstance(obj, Enum):
        return obj.value
    
    # Handle dicts (recursive) - OPTIMIZED: Limit recursion depth to prevent slowdowns
    if isinstance(obj, dict):
        # Limit recursion to prevent deep nesting slowdowns
        return {key: _make_json_serializable(value) for key, value in obj.items()}
    
    # Handle lists and tuples (recursive)
    if isinstance(obj, (list, tuple)):
        # Limit list size to prevent huge arrays from slowing down and filling context
        # Reduced from 1000 to 100 to prevent context bloat
        if len(obj) > 100:
            return [_make_json_serializable(item) for item in obj[:100]] + [f"... ({len(obj) - 100} more items)"]
        return [_make_json_serializable(item) for item in obj]
    
    # Handle sets (convert to list)
    if isinstance(obj, set):
        # Reduced from 1000 to 100 to prevent context bloat
        if len(obj) > 100:
            return [_make_json_serializable(item) for item in list(obj)[:100]] + [f"... ({len(obj) - 100} more items)"]
        return [_make_json_serializable(item) for item in obj]
    
    # Handle basic types that are already JSON-serializable
    if isinstance(obj, (str, int, float, bool)):
        return obj
    
    # Fallback: convert to string for anything else
    try:
        # Try to convert to string, but catch if even that fails
        return str(obj)
    except Exception:
        # Last resort: return a placeholder
        return f"<non-serializable: {type(obj).__name__}>"


def get_calibration_feedback(include_complexity: bool = True) -> Dict[str, Any]:
    """
    Get calibration feedback for agents (complexity and confidence calibration).
    
    This centralizes calibration feedback logic to avoid duplication across handlers.
    
    Args:
        include_complexity: Whether to include complexity calibration feedback
        
    Returns:
        Dict with calibration feedback (empty dict if unavailable)
    """
    calibration_feedback = {}
    
    try:
        from src.calibration import calibration_checker
        is_calibrated, cal_metrics = calibration_checker.check_calibration(include_complexity=include_complexity)
        
        if not is_calibrated:
            bins_data = cal_metrics.get('bins', {})
            total_samples = sum(bin_data.get('count', 0) for bin_data in bins_data.values())
            
            if total_samples > 0:
                # Calculate overall accuracy
                total_correct = sum(
                    int(bin_data.get('count', 0) * bin_data.get('accuracy', 0))
                    for bin_data in bins_data.values()
                )
                overall_accuracy = total_correct / total_samples
                
                # Get mean confidence
                confidence_values = []
                for bin_key, bin_data in bins_data.items():
                    count = bin_data.get('count', 0)
                    expected_acc = bin_data.get('expected_accuracy', 0.0)
                    confidence_values.extend([expected_acc] * count)
                
                if confidence_values:
                    import numpy as np
                    mean_confidence = float(np.mean(confidence_values))
                    calibration_error = mean_confidence - overall_accuracy
                    
                    # Rate-limit calibration messages to reduce noise
                    # Only show if: first time, error changed significantly, or enough updates passed
                    show_message = False
                    cache = _calibration_message_cache
                    
                    if cache['last_error'] is None:
                        # First time showing
                        show_message = True
                    elif abs(calibration_error - cache['last_error']) > cache['significance_threshold']:
                        # Error changed significantly (>5%)
                        show_message = True
                    # Note: We don't track update count globally, so skip that check for now
                    
                    calibration_feedback['confidence'] = {
                        'system_accuracy': overall_accuracy,
                        'mean_confidence': mean_confidence,
                        'calibration_error': calibration_error
                    }
                    
                    if show_message:
                        calibration_feedback['confidence']['message'] = (
                            f"System-wide calibration: Agents report {mean_confidence:.1%} confidence "
                            f"but achieve {overall_accuracy:.1%} accuracy. "
                            f"{'Consider being more conservative with confidence estimates' if mean_confidence > overall_accuracy + 0.2 else 'Calibration is improving'}."
                        )
                        calibration_feedback['confidence']['note'] = 'This is system-wide data - your individual calibration may vary'
                        # Update cache
                        cache['last_error'] = calibration_error
        
        # Add complexity calibration if requested
        if include_complexity:
            complexity_metrics = cal_metrics.get('complexity_calibration', {})
            if complexity_metrics:
                # Calculate overall complexity discrepancy
                total_complexity_samples = sum(
                    bin_data.get('count', 0) for bin_data in complexity_metrics.values()
                )
                if total_complexity_samples > 0:
                    high_discrepancy_total = sum(
                        bin_data.get('count', 0) * bin_data.get('high_discrepancy_rate', 0)
                        for bin_data in complexity_metrics.values()
                    )
                    high_discrepancy_rate = high_discrepancy_total / total_complexity_samples
                    
                    if high_discrepancy_rate > 0.5:
                        calibration_feedback['complexity'] = {
                            'high_discrepancy_rate': high_discrepancy_rate,
                            'message': (
                                f"{high_discrepancy_rate:.1%} of complexity reports show high discrepancy (>0.3). "
                                f"Consider calibrating your complexity estimates against system-derived values."
                            ),
                            'note': 'System derives complexity from EISV state - use this as reference'
                        }
    except Exception as e:
        logger.debug(f"Could not get calibration feedback: {e}")
    
    return calibration_feedback


def success_response(data: Dict[str, Any], agent_id: str = None, arguments: Dict[str, Any] = None) -> Sequence[TextContent]:
    """
    Create a success response with optional agent signature.

    Returns Sequence[TextContent] containing SuccessResponseDict.

    Args:
        data: Response data (will have "success": True added)
        agent_id: Optional explicit agent_id (if not provided, uses session binding)
        arguments: Tool arguments (contains client_session_id for session lookup)
                   - lite_response: If True, omits agent_signature for cleaner output

    Returns:
        Sequence of TextContent with success response

    Agent Signature:
        When a session-bound identity exists, responses include:
        {
            "agent_signature": {
                "agent_id": "...",
                "session_bound": true,
                "ts": "2025-12-21T14:32:00Z"
            }
        }
        This provides provenance/audit trail without polluting the main response.
        Use lite_response=True to suppress this for cleaner output.
    """
    response = {
        "success": True,
        "server_time": datetime.now().isoformat(),  # Time context for agents
        **data
    }

    # UX FIX (Dec 2025): Echo resolved agent ID to help agents track their identity
    # Removed resolved_uuid and resolved_client_session_id to reduce verbosity
    # agent_signature contains full identity details when needed
    from .context import get_context_agent_id
    current_bound_id = get_context_agent_id()

    if current_bound_id:
        response["resolved_agent_id"] = current_bound_id

    # UX FIX (Dec 2025): Support lite_response to reduce output verbosity
    lite_response = (arguments or {}).get("lite_response", False)
    
    if lite_response:
        # Skip agent_signature for cleaner output
        pass
    else:
        # Add agent signature using centralized computation
        response["agent_signature"] = compute_agent_signature(agent_id=agent_id, arguments=arguments)
    
    # Convert non-serializable types before JSON encoding
    # OPTIMIZATION: Use compact JSON (no indent) to speed up serialization and reduce size
    # CRITICAL: Wrap in try/except to prevent server crashes
    try:
        serializable_response = _make_json_serializable(response)
        json_text = json.dumps(serializable_response, ensure_ascii=False)  # Removed indent=2 for speed, ensure_ascii=False for performance
    except (TypeError, ValueError) as e:
        # Log serialization error but try to recover
        logger.error(f"JSON serialization error: {e}", exc_info=True)
        # Try one more time with full conversion and default=str fallback
        try:
            serializable_response = _make_json_serializable(response)
            json_text = json.dumps(serializable_response, ensure_ascii=False, default=str)
        except Exception as e2:
            # Last resort: return minimal error response to prevent server crash
            logger.error(f"Failed to serialize response even after conversion: {e2}", exc_info=True)
            # Return minimal JSON that's guaranteed to work
            try:
                minimal_response = {
                    "success": False,
                    "error": "Response serialization failed",
                    "recovery": {"action": "Check server logs for details"}
                }
                json_text = json.dumps(minimal_response, ensure_ascii=False)
            except Exception as e3:
                # Absolute last resort: hardcoded JSON string
                logger.critical(f"Even minimal response failed: {e3}", exc_info=True)
                json_text = '{"success":false,"error":"Serialization failed"}'
    
    return [TextContent(
        type="text",
        text=json_text
    )]


def require_argument(arguments: Dict[str, Any], name: str, 
                    error_message: str = None) -> Tuple[Any, Optional[TextContent]]:
    """
    Get required argument from arguments dict.
    
    Uses standardized error taxonomy for better agent self-service debugging.
    
    Args:
        arguments: Arguments dictionary
        name: Argument name
        error_message: Custom error message (defaults to standardized missing parameter error)
        
    Returns:
        Tuple of (value, error_response). If value is None, error_response is provided.
    """
    value = arguments.get(name)
    if value is None:
        # Use standardized error taxonomy
        from .error_helpers import missing_parameter_error
        # Try to infer tool name from context if available
        tool_name = arguments.get("_tool_name")  # Set by handlers if available
        # Use custom error message if provided, otherwise use standard
        if error_message:
            # Enhance context with custom message
            context = {"custom_message": error_message}
            return None, missing_parameter_error(name, tool_name=tool_name, context=context)[0]
        return None, missing_parameter_error(name, tool_name=tool_name)[0]
    return value, None


def require_agent_id(arguments: Dict[str, Any]) -> Tuple[str, Optional[TextContent]]:
    """
    Get or auto-generate agent_id - SIMPLIFIED: No more herding cats.
    
    RADICAL SIMPLIFICATION:
    - If agent_id provided: use it (with basic safety validation)
    - If session-bound: use that
    - If neither: auto-generate a UUID-based ID
    - No policy warnings, no test ID blocks, no arbitrary restrictions
    - Only validates format (filesystem safety) and reserved names (security)
    
    CANONICAL ID CLARIFICATION (Dec 2025):
    - Session-bound UUID is the canonical identifier
    - Explicit agent_id parameter is optional and may cause confusion
    - For write operations, session-bound identity is authoritative
    
    Args:
        arguments: Arguments dictionary

    Returns:
        Tuple of (agent_id, error_response). Error only for format/security issues.
    """
    agent_id = arguments.get("agent_id")
    explicit_agent_id = agent_id  # Track if explicitly provided
    
    # FALLBACK 1: Check session-bound identity (via context, set by identity_v2 at dispatch)
    if not agent_id:
        try:
            from .context import get_context_agent_id
            # Use context agent_id which was set at dispatch entry using identity_v2
            bound_id = get_context_agent_id()
            if bound_id:
                # CRITICAL (Dec 2025): Internal maps (monitors, metadata) are keyed by UUID.
                # We MUST return the UUID here, NOT the cosmetic label.
                agent_id = bound_id
                logger.debug(f"Using session-bound identity UUID: {agent_id}")
                arguments["agent_id"] = agent_id
        except Exception as e:
            logger.debug(f"Could not retrieve session-bound identity: {e}")
    
    # CANONICAL ID CLARIFICATION (Dec 2025): Warn if explicit agent_id doesn't match session
    # This helps agents understand which ID is authoritative
    if explicit_agent_id:
        try:
            from .context import get_context_agent_id
            bound_uuid = get_context_agent_id()
            if bound_uuid and explicit_agent_id != bound_uuid:
                # If explicit_agent_id is a label/display_name that matches bound UUID,
                # we still use the UUID for internal operations.
                try:
                    from .shared import get_mcp_server
                    mcp_server = get_mcp_server()
                    if bound_uuid in mcp_server.agent_metadata:
                        meta = mcp_server.agent_metadata[bound_uuid]
                        label = getattr(meta, 'label', None)
                        structured_id = getattr(meta, 'structured_id', None)
                        # If explicit_agent_id matches label or structured_id, switch to UUID
                        if explicit_agent_id in (label, structured_id):
                            logger.debug(f"Explicit agent_id '{explicit_agent_id}' matches label/structured_id, using UUID '{bound_uuid[:8]}...'")
                            agent_id = bound_uuid
                            arguments["agent_id"] = agent_id
                        else:
                            logger.debug(f"Explicit agent_id '{explicit_agent_id}' differs from session-bound UUID '{bound_uuid[:8]}...' - using session-bound UUID")
                            # Use session-bound identity for consistency
                            agent_id = bound_uuid
                            arguments["agent_id"] = agent_id
                except Exception:
                    pass  # Ignore lookup errors, proceed with explicit agent_id
        except Exception:
            pass  # Ignore context errors, proceed with explicit agent_id
    
    # FALLBACK 2: Auto-generate if still missing (no more errors, just generate)
    if not agent_id:
        import uuid
        from datetime import datetime
        # Generate: auto_{timestamp}_{short_uuid}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = str(uuid.uuid4())[:8]
        agent_id = f"auto_{timestamp}_{short_uuid}"
        arguments["agent_id"] = agent_id
        logger.info(f"Auto-generated agent_id: {agent_id}")

    # Only validate format (filesystem safety) and reserved names (security)
    # NO policy warnings, NO test ID blocks, NO arbitrary restrictions
    from .validators import validate_agent_id_format
    validated_id, format_error = validate_agent_id_format(agent_id)
    if format_error:
        return None, format_error

    # SECURITY: Only block truly dangerous reserved names (system, admin, etc.)
    from .validators import validate_agent_id_reserved_names
    validated_id, reserved_error = validate_agent_id_reserved_names(validated_id)
    if reserved_error:
        return None, reserved_error

    return validated_id, None


def require_registered_agent(arguments: Dict[str, Any]) -> Tuple[str, Optional[TextContent]]:
    """
    Get required agent_id AND verify the agent is registered in the system.

    MEANINGFUL IDENTITY (v2.5.4, Dec 2025): Returns agent_id (model+date) for storage.
    - agent_id (e.g., "Claude_Opus_4_20251227") is stored in KG - meaningful to agents and humans
    - UUID is kept internal for session binding, never exposed in KG
    - display_name provides friendly personalization
    - Sets arguments["_agent_display"] = {agent_id, display_name, label}

    This is the PROACTIVE GATE that prevents unregistered agents from calling
    tools that require an existing agent, avoiding hangs and stale locks.

    Args:
        arguments: Arguments dictionary

    Returns:
        Tuple of (agent_id, error_response). Returns agent_id (model+date) for KG storage.
        Display info is set in arguments["_agent_display"] = {agent_id, display_name, label}.
    """
    # First check if agent_id is provided (auto-injects from session if missing)
    agent_id, error = require_agent_id(arguments)
    if error:
        return None, error
    
    # Now check if agent is registered (exists in metadata)
    try:
        from .shared import get_mcp_server
        from .context import get_context_agent_id
        import uuid as uuid_module

        mcp_server = get_mcp_server()

        # Ensure metadata is loaded (lazy load if needed)
        # This is safe - only loads if not already loaded, doesn't overwrite in-memory changes
        try:
            ensure_metadata_loaded = getattr(mcp_server, 'ensure_metadata_loaded', None)
            if ensure_metadata_loaded:
                ensure_metadata_loaded()
        except Exception as e:
            logger.debug(f"Could not ensure metadata loaded: {e}")

        # NOTE: Don't reload metadata here - it overwrites in-memory labels set during
        # identity creation before they're persisted to disk (race condition).
        # The in-memory metadata should already be up-to-date from the identity handlers.
        # mcp_server.load_metadata()  # DISABLED: causes label loss

        # Check if agent_id is a UUID or label
        is_uuid = False
        try:
            # Try to parse as UUID
            uuid_module.UUID(agent_id, version=4)
            is_uuid = True
        except (ValueError, AttributeError):
            pass
        
        # Check if agent exists in metadata (by UUID or by label)
        agent_found = False
        actual_uuid = None
        
        # Track identity info - agent_id (model+date) is the public identifier
        structured_id = None  # model+date format like "Claude_Opus_4_20251227"
        display_name = None   # user-chosen name
        label = None          # nickname

        if is_uuid:
            # Direct UUID lookup
            if agent_id in mcp_server.agent_metadata:
                agent_found = True
                actual_uuid = agent_id
                meta = mcp_server.agent_metadata[agent_id]
                structured_id = getattr(meta, 'structured_id', None)
                display_name = getattr(meta, 'display_name', None) or getattr(meta, 'label', None)
                label = getattr(meta, 'label', None)
        else:
            # Label lookup - search metadata for matching label
            for uuid_key, meta in mcp_server.agent_metadata.items():
                if getattr(meta, 'label', None) == agent_id:
                    agent_found = True
                    actual_uuid = uuid_key
                    structured_id = getattr(meta, 'structured_id', None)
                    display_name = getattr(meta, 'display_name', None) or getattr(meta, 'label', None)
                    label = getattr(meta, 'label', None)
                    break

        # Also check session binding as fallback (for auto-created identities)
        # Use context agent_id (set by identity_v2 at dispatch entry)
        if not agent_found:
            bound_uuid = get_context_agent_id()
            if bound_uuid and bound_uuid in mcp_server.agent_metadata:
                agent_found = True
                actual_uuid = bound_uuid
                meta = mcp_server.agent_metadata[bound_uuid]
                structured_id = getattr(meta, 'structured_id', None)
                display_name = getattr(meta, 'display_name', None) or getattr(meta, 'label', None)
                label = getattr(meta, 'label', None)
        
        if not agent_found:
            # Agent not found - provide helpful onboarding guidance with naming suggestions
            from .naming_helpers import (
                detect_interface_context,
                generate_name_suggestions,
                format_naming_guidance
            )
            
            # Generate naming suggestions
            context = detect_interface_context()
            existing_names = [
                getattr(m, 'label', None)
                for m in mcp_server.agent_metadata.values()
                if getattr(m, 'label', None)
            ]
            suggestions = generate_name_suggestions(
                context=context,
                existing_names=existing_names
            )
            naming_guidance = format_naming_guidance(suggestions=suggestions)
            
            return None, error_response(
                f"Agent '{agent_id}' is not registered. Identity auto-creates on first tool call.",
                recovery={
                    "error_type": "agent_not_registered",
                    "action": "Call onboard() first to create your identity, or call process_agent_update() to auto-create",
                    "related_tools": ["onboard", "process_agent_update", "identity", "list_tools"],
                    "workflow": [
                        "1. Call onboard() - creates identity + gives you templates (recommended)",
                        "   OR call process_agent_update() - identity auto-creates",
                        "2. Save client_session_id from response",
                        "3. Call identity(name='your_name') to name yourself",
                        "4. Include client_session_id in all future calls",
                        "5. Then call this tool again"
                    ],
                    "naming_suggestions": naming_guidance,
                    "onboarding_sequence": ["onboard", "identity", "process_agent_update", "list_tools"],
                    "tip": "onboard() is the START HERE tool - it gives you everything you need in one call!"
                }
            )

        # v2.5.4: Return authoritative UUID for internal operations.
        # public_agent_id (model+date) is for meaningful storage in KG.
        public_agent_id = structured_id or label or f"Agent_{actual_uuid[:8]}"
        arguments["agent_id"] = public_agent_id  # For KG storage
        arguments["_agent_display"] = {
            "agent_id": public_agent_id,
            "display_name": display_name or label or public_agent_id,
            "label": label,
        }
        # authoritative identifier for internal maps
        arguments["_agent_uuid"] = actual_uuid

        return actual_uuid, None
        
    except Exception as e:
        # If we can't check registration, fail safe with guidance
        return None, error_response(
            f"Could not verify agent registration: {str(e)}",
            recovery={
                "action": "System error checking agent registration. Try onboard() or health_check() first.",
                "related_tools": ["onboard", "health_check", "identity"],
                "workflow": [
                    "1. Call health_check() to verify system is healthy",
                    "2. Call onboard() to create your identity",
                    "3. Save client_session_id and include it in future calls"
                ],
                "note": "Identity auto-creates on first tool call. Use onboard() for the best first-time experience."
            }
        )


def log_metrics(agent_id: str, metrics: Dict[str, Any], level: str = "info") -> None:
    """
    Log metrics with standardized format including agent_id.
    
    Ensures all metric logs include agent_id and timestamp for traceability.
    
    Args:
        agent_id: Agent identifier (required)
        metrics: Dictionary of metrics
        level: Log level ("info", "debug", "warning", "error")
    
    Example:
        >>> log_metrics("agent_123", {"E": 0.8, "I": 0.9}, level="info")
        # Logs: [agent_123] E=0.80 I=0.90 S=0.00 V=0.00
    """
    standardized = format_metrics_report(
        metrics=metrics,
        agent_id=agent_id,
        include_timestamp=True,
        include_context=True
    )
    
    # Format for logging
    log_msg_parts = [f"[{agent_id}]"]
    
    # Add EISV if available
    if "eisv" in standardized:
        eisv = standardized["eisv"]
        log_msg_parts.append(f"EISV: E={eisv.get('E', 0):.2f} I={eisv.get('I', 0):.2f} S={eisv.get('S', 0):.2f} V={eisv.get('V', 0):.2f}")
    elif any(k in standardized for k in ["E", "I", "S", "V"]):
        e = standardized.get("E", 0)
        i = standardized.get("I", 0)
        s = standardized.get("S", 0)
        v = standardized.get("V", 0)
        log_msg_parts.append(f"EISV: E={e:.2f} I={i:.2f} S={s:.2f} V={v:.2f}")
    
    # Add key metrics
    if "coherence" in standardized:
        log_msg_parts.append(f"coherence={standardized['coherence']:.3f}")
    risk_val = standardized.get("risk_score")
    if risk_val is not None:
        log_msg_parts.append(f"risk={risk_val:.3f}")
    if "health_status" in standardized:
        log_msg_parts.append(f"health={standardized['health_status']}")
    
    log_msg = " ".join(log_msg_parts)
    
    # Log at appropriate level
    if level == "debug":
        logger.debug(log_msg)
    elif level == "warning":
        logger.warning(log_msg)
    elif level == "error":
        logger.error(log_msg)
    else:  # default to info
        logger.info(log_msg)


def print_metrics(agent_id: str, metrics: Dict[str, Any], title: str = "Metrics") -> None:
    """
    Print metrics with standardized format including agent_id.
    
    For use in scripts and CLI tools. Ensures consistent formatting.
    
    Args:
        agent_id: Agent identifier (required)
        metrics: Dictionary of metrics
        title: Optional title for the metrics section
    
    Example:
        >>> print_metrics("agent_123", {"E": 0.8, "I": 0.9})
        Metrics:
        Agent: agent_123
        Timestamp: 2025-12-10T18:30:00.123456
        EISV: E=0.800 I=0.900 S=0.000 V=0.000
    """
    standardized = format_metrics_report(
        metrics=metrics,
        agent_id=agent_id,
        include_timestamp=True,
        include_context=True
    )
    
    text_output = format_metrics_text(standardized)
    
    if title:
        print(f"\n{title}:")
        print("-" * 60)
    print(text_output)
    if title:
        print("-" * 60)


def verify_agent_ownership(agent_id: str, arguments: Dict[str, Any], allow_operator: bool = False) -> bool:
    """
    Verify that the current session owns/is bound to the given agent_id.

    Dec 2025: UUID-based auth replaces API keys. Session binding is authority.
    If the session is bound to this agent_id (via UUID), the caller is authenticated.

    Jan 2026: Added operator exception for cross-agent operations.
    If allow_operator=True and the calling session is bound to an agent with
    label="Operator" or tags containing "operator", cross-agent access is allowed.

    Args:
        agent_id: The agent to verify ownership of
        arguments: Tool arguments dict (for session lookup)
        allow_operator: If True, allow operator agents to act on other agents

    Returns:
        True if session is bound to this agent_id or caller is operator, False otherwise
    """
    try:
        from .context import get_context_agent_id
        from .shared import get_mcp_server

        mcp_server = get_mcp_server()

        # Use context agent_id (set by identity_v2 at dispatch entry)
        bound_id = get_context_agent_id()
        if bound_id == agent_id:
            return True

        # Also accept if agent_id matches the agent_uuid of the bound agent
        if bound_id:
            meta = mcp_server.agent_metadata.get(bound_id)
            if meta and getattr(meta, 'agent_uuid', None) == agent_id:
                return True

            # Operator exception: If caller is an operator, allow cross-agent access
            if allow_operator and meta:
                label = getattr(meta, 'label', '') or ''
                tags = getattr(meta, 'tags', []) or []
                is_operator = (
                    label.lower() == 'operator' or
                    'operator' in [t.lower() for t in tags]
                )
                if is_operator:
                    logger.info(f"Operator {bound_id} granted cross-agent access to {agent_id}")
                    return True

        return False
    except Exception as e:
        logger.debug(f"verify_agent_ownership failed: {e}")
        return False


def generate_actionable_feedback(
    metrics: Dict[str, Any],
    interpreted_state: Optional[Dict[str, Any]] = None,
    task_type: Optional[str] = None,
    response_text: Optional[str] = None,
    previous_coherence: Optional[float] = None,
) -> list[str]:
    """
    Generate context-aware actionable feedback for agents.

    Instead of generic threshold-based messages, this provides:
    - Trend detection: Did coherence drop or was it always low?
    - Task-specific advice: Different guidance for coding vs research vs debugging
    - Pattern recognition: Detect struggles from response_text
    - Specific actions: Concrete next steps, not vague suggestions

    Args:
        metrics: Current metrics dict with coherence, risk_score, regime, etc.
        interpreted_state: Optional state interpretation (health, mode, basin)
        task_type: Optional task type for context-aware advice
        response_text: Optional agent's response for pattern detection
        previous_coherence: Optional previous coherence value for trend detection

    Returns:
        List of actionable feedback strings
    """
    feedback = []

    coherence = metrics.get('coherence')
    risk_score = metrics.get('risk_score')
    regime = metrics.get('regime', 'exploration').lower()
    void_active = metrics.get('void_active', False)

    # Extract interpreted state
    health = interpreted_state.get('health', 'unknown') if interpreted_state else 'unknown'
    mode = interpreted_state.get('mode', 'unknown') if interpreted_state else 'unknown'
    basin = interpreted_state.get('basin', 'unknown') if interpreted_state else 'unknown'

    # Normalize task_type
    task = (task_type or 'mixed').lower()

    # Check if this is first update (skip coherence feedback - 0.50 is just default)
    updates = metrics.get('updates', 0)
    is_first_update = updates <= 1

    # --- Coherence Feedback (Context-Aware) ---
    # Skip on first update - coherence 0.50 is just the starting default, not meaningful
    if coherence is not None and not is_first_update:
        # Detect trend
        coherence_dropped = previous_coherence is not None and coherence < previous_coherence - 0.1
        coherence_delta = previous_coherence - coherence if previous_coherence else None

        if regime == "exploration":
            # Low coherence is expected during exploration
            if coherence < 0.3:
                if coherence_dropped:
                    feedback.append(
                        f"Coherence dropped significantly ({coherence_delta:.2f}) during exploration. "
                        "This may indicate you're trying too many directions at once. "
                        "Try: Pick your most promising direction and explore it deeper before switching."
                    )
                else:
                    feedback.append(
                        "Very low coherence (<0.3) even for exploration phase. "
                        "Consider: Note down your current hypotheses, then focus on testing one at a time."
                    )
        elif regime == "locked" or regime == "stable":
            # High coherence expected
            if coherence < 0.7:
                if coherence_dropped:
                    feedback.append(
                        f"Unexpected coherence drop ({coherence_delta:.2f}) in stable regime. "
                        "Something disrupted your flow. "
                        "Check: Did requirements change? Did you encounter an unexpected edge case?"
                    )
                else:
                    feedback.append(
                        "Coherence below 0.7 in stable regime indicates drift. "
                        "Action: Review your original plan and verify you're still aligned with the goal."
                    )
        else:
            # Transition/Convergence
            if coherence < 0.5:
                # Task-specific advice based on allowed task types
                if task == 'convergent':
                    # Convergent tasks need focus - low coherence is a problem
                    feedback.append(
                        f"Low coherence ({coherence:.2f}) during convergent task. "
                        "You should be focusing, but your state suggests divergence. "
                        "Tip: Write down your solution in one sentence before continuing."
                    )
                elif task == 'divergent':
                    # Divergent tasks are exploration - low coherence is less concerning
                    if coherence < 0.35:
                        feedback.append(
                            f"Very low coherence ({coherence:.2f}) even for divergent work. "
                            "Tip: Note your top 3 ideas, then explore the most promising one deeper."
                        )
                    # else: Low coherence during divergent work is normal, skip feedback
                else:
                    # Mixed or unknown
                    feedback.append(
                        f"Coherence at {coherence:.2f}. "
                        "Tip: Pause and articulate your current goal in one sentence."
                    )

    # --- Risk Score Feedback ---
    if risk_score is not None:
        if risk_score > 0.7:
            # High complexity - specific advice based on basin
            if basin == 'void':
                feedback.append(
                    f"High complexity ({risk_score:.2f}) in void basin - energy/integrity mismatch. "
                    "This often means working hard on the wrong thing. "
                    "Check: Is this task still relevant to your original goal?"
                )
            else:
                feedback.append(
                    f"High complexity ({risk_score:.2f}) detected. "
                    "Options: (1) Break task into smaller pieces, (2) Pause and document what you've learned, "
                    "or (3) Ask for clarification if requirements are unclear."
                )
        elif risk_score > 0.5:
            # Moderate - acknowledge without prescribing
            if health == 'degraded':
                feedback.append(
                    f"Moderate complexity ({risk_score:.2f}) with degraded health. "
                    "Consider a checkpoint: What would you tell someone taking over this task?"
                )

    # --- Void Detection ---
    if void_active:
        # Void means mismatch between energy and integrity
        e = metrics.get('E', 0.5)
        i = metrics.get('I', 0.5)

        if e > i + 0.2:
            feedback.append(
                "Void detected: High energy but low integrity. "
                "You're working hard but output quality may be suffering. "
                "Suggestion: Slow down and review your recent work for errors."
            )
        elif i > e + 0.2:
            feedback.append(
                "Void detected: High integrity but low energy. "
                "Output is clean but progress is slow. "
                "Suggestion: Is something blocking you? Consider asking for help or taking a break."
            )
        else:
            feedback.append(
                "Void active - energy and integrity are misaligned. "
                "Take a moment to assess: What's causing the disconnect?"
            )

    # --- Response Text Pattern Detection ---
    if response_text:
        text_lower = response_text.lower()

        # Detect confusion patterns
        confusion_patterns = [
            ('not sure', "You mentioned uncertainty. That's valuable self-awareness. "),
            ("don't understand", "You noted confusion. Consider rephrasing the problem. "),
            ('struggling', "You mentioned struggling. Break the problem into smaller parts. "),
            ('stuck', "You said you're stuck. Try explaining the problem to a rubber duck. "),
        ]

        for pattern, prefix in confusion_patterns:
            if pattern in text_lower:
                feedback.append(prefix + "What's the smallest next step you can take?")
                break  # Only add one confusion-based feedback

        # Detect overconfidence patterns
        if any(p in text_lower for p in ['definitely', 'obviously', 'clearly', 'certainly']):
            if coherence and coherence < 0.6:
                feedback.append(
                    "Your language suggests confidence, but metrics show uncertainty. "
                    "Worth double-checking: Are you sure about your assumptions?"
                )

    return feedback

