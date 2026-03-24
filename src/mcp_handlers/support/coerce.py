"""Shared type coercion utilities for MCP handlers."""

from typing import Any, Dict


def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert a value to float, returning default on failure."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def coerce_bool(value: Any, default: bool = False) -> bool:
    """Coerce bool-ish values from tool arguments.

    Handles string representations commonly passed through MCP transport:
    true/false, 1/0, yes/no, on/off (case-insensitive).
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def resolve_agent_uuid(arguments: Dict[str, Any], agent_id: str) -> str:
    """Resolve authoritative agent UUID from arguments or fall back to agent_id."""
    return arguments.get("_agent_uuid") or agent_id
