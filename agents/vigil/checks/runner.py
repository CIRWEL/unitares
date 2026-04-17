"""Runs all registered checks in order, tolerating per-check exceptions.

This is the single integration point Vigil's run_cycle uses. Keeping it
separate from the registry means the runner can evolve (timeouts, concurrency,
prev_state handling) without touching the registration protocol.
"""

from __future__ import annotations

import inspect
from typing import Any, List, Tuple

from .base import Check, CheckResult
from . import registry


async def run_health_checks(
    prev_state: dict[str, Any] | None = None,
) -> List[Tuple[Check, CheckResult]]:
    """Execute every registered check in registration order.

    A check may define run() or run(prev_state=...). Both shapes are supported
    so plugin authors aren't forced into a wider signature they don't need.
    A check that raises is converted to an unhealthy CheckResult — Vigil must
    keep checking in even when a single plugin misbehaves.
    """
    prev_state = prev_state or {}
    out: List[Tuple[Check, CheckResult]] = []
    for check in registry.all_checks():
        try:
            sig = inspect.signature(check.run)
            if "prev_state" in sig.parameters:
                result = await check.run(prev_state=prev_state)
            else:
                result = await check.run()
        except Exception as e:
            result = CheckResult(
                ok=False,
                summary=f"{getattr(check, 'name', '?')}: crashed ({e})",
                severity="critical",
                fingerprint_key=f"{getattr(check, 'service_key', 'unknown')}_crashed",
            )
        out.append((check, result))
    return out
