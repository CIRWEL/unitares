"""Helpers for reporting identity continuity mode across transports and health surfaces."""

from __future__ import annotations

from typing import Any, Dict, Optional


def get_identity_continuity_status(
    *,
    redis_present: Optional[bool] = None,
    redis_operational: Optional[bool] = None,
) -> Dict[str, Any]:
    """Describe whether identity continuity is Redis-backed or degraded-local."""
    if redis_present is None:
        try:
            from src.cache import is_redis_available

            redis_present = bool(is_redis_available())
        except Exception:
            redis_present = False

    mode = "redis" if redis_present else "degraded-local"
    if redis_operational is None:
        redis_operational = bool(redis_present)

    if mode == "redis":
        status = "healthy" if redis_operational else "warning"
        note = (
            "Redis is present; session continuity uses Redis-backed bindings "
            "with PostgreSQL as the durable source of truth."
        )
    else:
        # Degraded-local is an expected fallback in local/dev mode, so surface it
        # explicitly without marking the whole system unhealthy by default.
        status = "healthy"
        note = (
            "Redis is absent; identity continuity is running in degraded-local mode "
            "with process-local session bindings and PostgreSQL persistence."
        )

    payload: Dict[str, Any] = {
        "status": status,
        "mode": mode,
        "redis_present": bool(redis_present),
        "source_of_truth": "postgres",
        "session_binding_backend": (
            "redis-backed session cache" if mode == "redis" else "in-memory fallback cache"
        ),
        "note": note,
    }
    if mode == "redis" and not redis_operational:
        payload["warning"] = (
            "Redis is present but not operating cleanly; fallback session behavior may be active."
        )
    return payload


def format_identity_continuity_startup_message(status: Optional[Dict[str, Any]] = None) -> str:
    """Render a single-line startup message for operators."""
    status = status or get_identity_continuity_status()
    redis_clause = "Redis present" if status.get("redis_present") else "Redis absent"
    return (
        f"Identity continuity mode: {status.get('mode', 'unknown')} "
        f"({redis_clause}; PostgreSQL remains the durable source of truth)"
    )
