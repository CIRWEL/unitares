"""
Runtime Configuration Management

Allows runtime access and modification of governance thresholds
without requiring code changes or redeployment.
"""

from typing import Dict, Optional, Any
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

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
        
        # Additional logical validation
        if name == "risk_approve_threshold" and "risk_revise_threshold" in thresholds:
            if value >= thresholds["risk_revise_threshold"]:
                errors.append(f"risk_approve_threshold ({value}) must be < risk_revise_threshold ({thresholds['risk_revise_threshold']})")
                continue
        
        if name == "risk_revise_threshold" and "risk_approve_threshold" in _runtime_overrides:
            if value <= _runtime_overrides.get("risk_approve_threshold", config.RISK_APPROVE_THRESHOLD):
                errors.append(f"risk_revise_threshold ({value}) must be > risk_approve_threshold")
                continue
        
        _runtime_overrides[name] = float(value)
        updated.append(name)
    
    return {
        "success": len(errors) == 0,
        "updated": updated,
        "errors": errors
    }


def get_effective_threshold(threshold_name: str) -> float:
    """
    Get effective threshold value (runtime override or default).
    
    Used internally by governance system.
    """
    config = config_module.GovernanceConfig
    
    if threshold_name == "risk_approve_threshold":
        return _runtime_overrides.get("risk_approve_threshold", config.RISK_APPROVE_THRESHOLD)
    elif threshold_name == "risk_revise_threshold":
        return _runtime_overrides.get("risk_revise_threshold", config.RISK_REVISE_THRESHOLD)
    elif threshold_name == "coherence_critical_threshold":
        return _runtime_overrides.get("coherence_critical_threshold", config.COHERENCE_CRITICAL_THRESHOLD)
    elif threshold_name == "void_threshold_initial":
        return _runtime_overrides.get("void_threshold_initial", config.VOID_THRESHOLD_INITIAL)
    else:
        raise ValueError(f"Unknown threshold: {threshold_name}")


def clear_overrides() -> None:
    """Clear all runtime overrides, revert to defaults"""
    _runtime_overrides.clear()

