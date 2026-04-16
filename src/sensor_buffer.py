"""In-memory buffer for the latest Pi sensor readings.

The eisv_sync background task writes here; Lumen's check-ins read from
here. No agent identity, no governance calls — just a shared mailbox.
"""
import threading
import time
from typing import Optional

_lock = threading.Lock()
_buffer: dict = {
    "eisv": None,
    "anima": None,
    "timestamp": None,
}


def update_sensor_eisv(eisv: dict, anima: dict) -> None:
    """Store the latest sensor-derived EISV and raw anima readings."""
    with _lock:
        _buffer["eisv"] = eisv
        _buffer["anima"] = anima
        _buffer["timestamp"] = time.time()


def get_latest_sensor_eisv(max_age_seconds: float = 600.0) -> Optional[dict]:
    """Read the latest sensor EISV if fresh enough.

    Args:
        max_age_seconds: Data older than this is considered stale (default: 10 min,
            i.e. 2x the 5-min sync interval).

    Returns:
        Dict with keys ``eisv``, ``anima``, ``timestamp``, or None if no data
        or data is stale.
    """
    with _lock:
        if _buffer["eisv"] is None or _buffer["timestamp"] is None:
            return None
        age = time.time() - _buffer["timestamp"]
        if age > max_age_seconds:
            return None
        return {
            "eisv": _buffer["eisv"],
            "anima": _buffer["anima"],
            "timestamp": _buffer["timestamp"],
        }
