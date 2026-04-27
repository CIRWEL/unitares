"""Deterministic status-priority resolver for progress_flat snapshot rows.

Priority (first match wins):
    source-error > unresolved > startup-grace > silent > flat-candidate > OK
"""
from __future__ import annotations


def resolve_status(row: dict) -> str:
    if row.get("error_details"):
        return "source-error"
    suppressed = row.get("suppressed_reason")
    if suppressed == "unresolved_label":
        return "unresolved"
    if suppressed == "startup_unresolved_label":
        return "startup-grace"
    if suppressed in ("heartbeat_not_alive", "heartbeat_eval_error"):
        return "silent"
    if row.get("candidate") is True:
        return "flat-candidate"
    return "OK"
