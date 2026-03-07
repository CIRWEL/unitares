"""
Runtime Configuration Management

Allows runtime access and modification of governance thresholds
without requiring code changes or redeployment.
"""

from typing import Dict, Optional, Any

# Ensure project root is in path for imports
from src._imports import ensure_project_root
ensure_project_root()

from config import governance_config as config_module


# Runtime overrides (None = use class defaults)
_runtime_overrides: Dict[str, float] = {}


def get_thresholds() -> Dict[str, float]:
    """
    Get current threshold configuration (runtime overrides + defaults).
    
    Returns all decision thresholds for governance system.
    """
    config = config_module.GovernanceConfig
    
    return {
        "risk_approve_threshold": _runtime_overrides.get(
            "risk_approve_threshold",
            config.RISK_APPROVE_THRESHOLD
        ),
        "risk_revise_threshold": _runtime_overrides.get(
            "risk_revise_threshold",
            config.RISK_REVISE_THRESHOLD
        ),
        # Note: reject threshold is implicit (risk > revise_threshold triggers reject)
        "coherence_critical_threshold": _runtime_overrides.get(
            "coherence_critical_threshold",
            config.COHERENCE_CRITICAL_THRESHOLD
        ),
        "void_threshold_initial": _runtime_overrides.get(
            "void_threshold_initial",
            config.VOID_THRESHOLD_INITIAL
        ),
        "void_threshold_min": config.VOID_THRESHOLD_MIN,
        "void_threshold_max": config.VOID_THRESHOLD_MAX,
        "lambda1_min": config.LAMBDA1_MIN,
        "lambda1_max": config.LAMBDA1_MAX,
        "target_coherence": config.TARGET_COHERENCE,
        "target_void_freq": config.TARGET_VOID_FREQ,
    }


def set_thresholds(thresholds: Dict[str, float], validate: bool = True) -> Dict[str, Any]:
    """
    Set runtime threshold overrides.
    
    Args:
        thresholds: Dict of threshold_name -> value
        validate: If True, validate values are in reasonable ranges
    
    Returns:
        {
            "success": bool,
            "updated": List[str],
            "errors": List[str]
        }
    """
    config = config_module.GovernanceConfig
    updated = []
    errors = []
    
    # Validation ranges
    valid_ranges = {
        "risk_approve_threshold": (0.0, 1.0),
        "risk_revise_threshold": (0.0, 1.0),
        "coherence_critical_threshold": (0.0, 1.0),
        "void_threshold_initial": (0.0, 1.0),
    }
    
    for name, value in thresholds.items():
        if name not in valid_ranges:
            errors.append(f"Unknown threshold: {name}")
            continue
        
        if validate:
            min_val, max_val = valid_ranges[name]
            if not (min_val <= value <= max_val):
                errors.append(f"{name}={value} out of range [{min_val}, {max_val}]")
                continue
        
        # Additional logical validation: enforce APPROVE < REVISE < REJECT invariant.
        # Always validate against the effective value (pending update or current override or class default).
        if name in ("risk_approve_threshold", "risk_revise_threshold", "risk_reject_threshold"):
            # Build the effective triple after this update would apply
            effective_approve = (
                thresholds.get("risk_approve_threshold",
                               _runtime_overrides.get("risk_approve_threshold", config.RISK_APPROVE_THRESHOLD))
            )
            effective_revise = (
                thresholds.get("risk_revise_threshold",
                               _runtime_overrides.get("risk_revise_threshold", config.RISK_REVISE_THRESHOLD))
            )
            effective_reject = (
                thresholds.get("risk_reject_threshold",
                               _runtime_overrides.get("risk_reject_threshold", config.RISK_REJECT_THRESHOLD))
            )
            # Override the one being set
            if name == "risk_approve_threshold":
                effective_approve = value
            elif name == "risk_revise_threshold":
                effective_revise = value
            elif name == "risk_reject_threshold":
                effective_reject = value

            if not (effective_approve < effective_revise < effective_reject):
                errors.append(
                    f"Ordering violated: APPROVE({effective_approve}) "
                    f"< REVISE({effective_revise}) "
                    f"< REJECT({effective_reject}) must hold"
                )
                continue
        
        _runtime_overrides[name] = float(value)
        updated.append(name)
    
    return {
        "success": len(errors) == 0,
        "updated": updated,
        "errors": errors
    }


def get_effective_threshold(threshold_name: str, default: Optional[float] = None) -> float:
    """
    Get effective threshold value (runtime override or default).
    
    Used internally by governance system.
    
    Args:
        threshold_name: Name of threshold to get
        default: Optional default value if threshold not found (for backward compatibility)
    
    Returns:
        Effective threshold value
    """
    config = config_module.GovernanceConfig
    
    if threshold_name == "risk_approve_threshold":
        return _runtime_overrides.get("risk_approve_threshold", config.RISK_APPROVE_THRESHOLD)
    elif threshold_name == "risk_revise_threshold":
        return _runtime_overrides.get("risk_revise_threshold", config.RISK_REVISE_THRESHOLD)
    elif threshold_name == "risk_reject_threshold":
        return _runtime_overrides.get("risk_reject_threshold", default if default is not None else config.RISK_REJECT_THRESHOLD)
    elif threshold_name == "coherence_critical_threshold":
        return _runtime_overrides.get("coherence_critical_threshold", config.COHERENCE_CRITICAL_THRESHOLD)
    elif threshold_name == "void_threshold_initial":
        return _runtime_overrides.get("void_threshold_initial", config.VOID_THRESHOLD_INITIAL)
    else:
        if default is not None:
            return default
        raise ValueError(f"Unknown threshold: {threshold_name}")


def clear_overrides() -> None:
    """Clear all runtime overrides, revert to defaults"""
    _runtime_overrides.clear()

