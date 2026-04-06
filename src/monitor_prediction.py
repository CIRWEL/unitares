"""Tactical prediction registry for governance monitor.

Mints per-check-in prediction IDs so outcome_event can reference a specific
(confidence, timestamp) pair exactly instead of relying on temporal proxy.
The registry is in-memory only; orphaned entries are expired by TTL.
"""

import time as _time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional


def register_tactical_prediction(
    open_predictions: Dict[str, Dict],
    confidence: float,
    *,
    decision_action: Optional[str] = None,
    prediction_ttl_seconds: float = 600.0,
) -> str:
    """Mint a prediction id and register it. Returns the prediction_id."""
    expire_old_predictions(open_predictions, prediction_ttl_seconds)

    prediction_id = str(uuid.uuid4())
    open_predictions[prediction_id] = {
        "confidence": float(confidence),
        "decision_action": decision_action,
        "created_at": _time.monotonic(),
        "created_at_iso": datetime.now().isoformat(),
        "consumed": False,
    }
    return prediction_id


def lookup_prediction(
    open_predictions: Dict[str, Dict],
    prediction_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the registered record for prediction_id, or None if unknown."""
    if not prediction_id:
        return None
    record = open_predictions.get(prediction_id)
    if not record:
        return None
    return dict(record)


def consume_prediction(
    open_predictions: Dict[str, Dict],
    prediction_id: str,
) -> Optional[Dict[str, Any]]:
    """Mark a prediction as consumed and return its record.

    Returns None if the id is unknown or already consumed. The record is
    kept in the registry (with consumed=True) until TTL expiry so repeated
    outcome events against the same prediction can be detected by callers.
    """
    if not prediction_id:
        return None
    record = open_predictions.get(prediction_id)
    if not record or record.get("consumed"):
        return None
    record["consumed"] = True
    return dict(record)


def expire_old_predictions(
    open_predictions: Dict[str, Dict],
    ttl_seconds: float = 600.0,
) -> int:
    """Drop prediction records older than ttl_seconds. Returns count removed."""
    now = _time.monotonic()
    stale_ids = [
        pid for pid, rec in open_predictions.items()
        if (now - float(rec.get("created_at", 0.0))) > ttl_seconds
    ]
    for pid in stale_ids:
        open_predictions.pop(pid, None)
    return len(stale_ids)
