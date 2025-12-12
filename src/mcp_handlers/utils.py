"""
Common utilities for MCP tool handlers.
"""

from typing import Dict, Any, Sequence, Tuple, Optional
from mcp.types import TextContent
import json
import sys
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


def error_response(
    message: str, 
    details: Optional[Dict[str, Any]] = None, 
    recovery: Optional[Dict[str, Any]] = None, 
    context: Optional[Dict[str, Any]] = None,
    error_code: Optional[str] = None
) -> TextContent:
    """
    Create an error response with optional recovery guidance and system context.
    
    Returns TextContent containing ErrorResponseDict.
    """
    """
    Create an error response with optional recovery guidance and system context.
    
    SECURITY: Sanitizes error messages to prevent internal structure leakage.
    
    Args:
        message: Error message (will be sanitized)
        details: Optional additional error details (will be sanitized)
        recovery: Optional recovery suggestions for AGI agents
        context: Optional system context (what was happening, system state, etc.)
        error_code: Optional machine-readable error code (e.g., "AGENT_NOT_FOUND")
        
    Returns:
        TextContent with error response
        
    Example:
        >>> error_response(
        ...     "Agent not found",
        ...     error_code="AGENT_NOT_FOUND",
        ...     recovery={"action": "Call get_agent_api_key"}
        ... )
    """
    # SECURITY: Sanitize error message to prevent internal structure leakage
    sanitized_message = _sanitize_error_message(message)
    
    response = {
        "success": False,
        "error": sanitized_message
    }
    
    # Add machine-readable error code if provided
    if error_code:
        response["error_code"] = error_code
    
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
    
    return TextContent(
        type="text",
        text=json.dumps(response, indent=2)
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
        # Limit list size to prevent huge arrays from slowing down
        if len(obj) > 1000:
            return [_make_json_serializable(item) for item in obj[:1000]] + [f"... ({len(obj) - 1000} more items)"]
        return [_make_json_serializable(item) for item in obj]
    
    # Handle sets (convert to list)
    if isinstance(obj, set):
        if len(obj) > 1000:
            return [_make_json_serializable(item) for item in list(obj)[:1000]] + [f"... ({len(obj) - 1000} more items)"]
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
                    
                    calibration_feedback['confidence'] = {
                        'system_accuracy': overall_accuracy,
                        'mean_confidence': mean_confidence,
                        'calibration_error': mean_confidence - overall_accuracy,
                        'message': (
                            f"System-wide calibration: Agents report {mean_confidence:.1%} confidence "
                            f"but achieve {overall_accuracy:.1%} accuracy. "
                            f"{'Consider being more conservative with confidence estimates' if mean_confidence > overall_accuracy + 0.2 else 'Calibration is improving'}."
                        ),
                        'note': 'This is system-wide data - your individual calibration may vary'
                    }
        
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


def success_response(data: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Create a success response.
    
    Returns Sequence[TextContent] containing SuccessResponseDict.
    """
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
    Get required agent_id from arguments and validate format + security checks.
    
    IDENTITY BINDING FALLBACK:
    If agent_id not provided in arguments, checks for session-bound identity.
    This enables agents to call tools without explicitly passing agent_id after
    calling bind_identity() once.

    Args:
        arguments: Arguments dictionary

    Returns:
        Tuple of (agent_id, error_response). If agent_id is missing or invalid, error_response is provided.
    """
    agent_id = arguments.get("agent_id")
    
    # IDENTITY BINDING FALLBACK: Use session-bound identity if not explicitly provided
    if not agent_id:
        try:
            from .identity import get_bound_agent_id
            session_id = arguments.get("session_id")
            bound_id = get_bound_agent_id(session_id=session_id)
            if bound_id:
                agent_id = bound_id
                # Inject into arguments so downstream code sees it
                arguments["agent_id"] = agent_id
                logger.debug(f"Using session-bound identity: {agent_id}")
        except ImportError:
            pass  # Identity module not available, continue with normal flow
    
    if not agent_id:
        return None, error_response(
            "agent_id is required",
            recovery={
                "action": "Provide agent_id or call bind_identity first",
                "workflow": [
                    "Option 1: Pass agent_id explicitly in arguments",
                    "Option 2: Call bind_identity(agent_id, api_key) to bind session identity",
                    "After binding, agent_id is auto-injected via recall"
                ]
            }
        )
    
    # Continue with validation (agent_id now guaranteed to exist)

    # Validate agent_id format (safety check for filesystem/URL issues)
    from .validators import validate_agent_id_format
    validated_id, format_error = validate_agent_id_format(agent_id)
    if format_error:
        return None, format_error

    # SECURITY: Check reserved names (Fix 2 from SECURITY_ADVISORY_AGENT_IDENTITY_20251212.md)
    from .validators import validate_agent_id_reserved_names
    validated_id, reserved_error = validate_agent_id_reserved_names(validated_id)
    if reserved_error:
        return None, reserved_error

    return validated_id, None


def require_registered_agent(arguments: Dict[str, Any]) -> Tuple[str, Optional[TextContent]]:
    """
    Get required agent_id AND verify the agent is registered in the system.
    
    This is the PROACTIVE GATE that prevents unregistered agents from calling
    tools that require an existing agent, avoiding hangs and stale locks.
    
    Args:
        arguments: Arguments dictionary
        
    Returns:
        Tuple of (agent_id, error_response). If agent_id is missing or not registered,
        error_response is provided with onboarding guidance.
    """
    # First check if agent_id is provided
    agent_id, error = require_agent_id(arguments)
    if error:
        return None, error
    
    # Now check if agent is registered (exists in metadata)
    try:
        from .shared import get_mcp_server
        mcp_server = get_mcp_server()
        
        # Reload metadata to ensure we have latest state
        mcp_server.load_metadata()
        
        if agent_id not in mcp_server.agent_metadata:
            return None, error_response(
                f"Agent '{agent_id}' is not registered. You must onboard first.",
                recovery={
                    "error_type": "agent_not_registered",
                    "action": "Call get_agent_api_key first to register this agent_id",
                    "related_tools": ["get_agent_api_key", "list_agents", "list_tools"],
                    "workflow": [
                        "1. Call get_agent_api_key with your agent_id to register",
                        "2. Save the returned API key securely",
                        "3. Then call this tool again with agent_id and api_key"
                    ],
                    "onboarding_sequence": ["list_tools", "get_agent_api_key", "list_agents", "process_agent_update"]
                }
            )
        
        return agent_id, None
        
    except Exception as e:
        # If we can't check registration, fail safe with guidance
        return None, error_response(
            f"Could not verify agent registration: {str(e)}",
            recovery={
                "action": "System error checking agent registration. Try get_agent_api_key first.",
                "related_tools": ["get_agent_api_key", "health_check"],
                "workflow": ["1. Call health_check to verify system", "2. Call get_agent_api_key to register"]
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


