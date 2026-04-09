"""JSON serialization utilities for MCP responses."""
from typing import Any
from datetime import datetime, date
from enum import Enum


def _make_json_serializable(obj: Any) -> Any:
    """
    Recursively convert non-JSON-serializable types to JSON-compatible types.

    Handles:
    - numpy types (float64, int64, etc.) -> float/int
    - numpy arrays -> lists
    - datetime/date objects -> ISO format strings
    - Enum types -> their values
    - Other non-serializable types -> strings
    """
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
        pass

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()

    if isinstance(obj, Enum):
        return obj.value

    if isinstance(obj, dict):
        if len(obj) > 100:
            items = list(obj.items())[:100]
            result = {key: _make_json_serializable(value) for key, value in items}
            result[f"... ({len(obj) - 100} more keys)"] = "..."
            return result
        return {key: _make_json_serializable(value) for key, value in obj.items()}

    if isinstance(obj, (list, tuple)):
        if len(obj) > 100:
            return [_make_json_serializable(item) for item in obj[:100]] + [f"... ({len(obj) - 100} more items)"]
        return [_make_json_serializable(item) for item in obj]

    if isinstance(obj, set):
        if len(obj) > 100:
            return [_make_json_serializable(item) for item in list(obj)[:100]] + [f"... ({len(obj) - 100} more items)"]
        return [_make_json_serializable(item) for item in obj]

    if isinstance(obj, (str, int, float, bool)):
        return obj

    try:
        return str(obj)
    except Exception:
        return f"<non-serializable: {type(obj).__name__}>"
