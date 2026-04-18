"""Shannon entropy of the agent's response distribution — spec §3.1 S.

Three tiers in preference order:
  1. logprob  — per-token entropy from model logprobs (requires plugin instrumentation)
  2. multisample — k-sample self-consistency over semantic equivalence classes
  3. heuristic — wraps the legacy [0,1] complexity/drift-driven S (degraded mode)
"""
from typing import Any, Dict

from src.grounding.types import GroundedValue


def compute_entropy(ctx: Any, metrics: Dict[str, Any]) -> GroundedValue:
    """Return grounded S value. Always succeeds (tier-3 is a safe fallback)."""
    args = getattr(ctx, "arguments", {}) or {}

    if "logprobs" in args:
        try:
            return _compute_from_logprobs(args["logprobs"])
        except NotImplementedError:
            pass

    if "samples" in args:
        try:
            return _compute_from_samples(args["samples"])
        except NotImplementedError:
            pass

    return _compute_heuristic(metrics)


def _compute_from_logprobs(logprobs: list) -> GroundedValue:
    raise NotImplementedError(
        "tier-1 (logprob) entropy requires plugin-side logprob capture; "
        "see spec §3.1 S 'Computation recipe' and Phase-1 out-of-scope items"
    )


def _compute_from_samples(samples: list) -> GroundedValue:
    raise NotImplementedError(
        "tier-2 (multisample) entropy requires a semantic-equivalence classifier; "
        "deferred from Phase 1"
    )


def _compute_heuristic(metrics: Dict[str, Any]) -> GroundedValue:
    raw = metrics.get("S", 0.5)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = 0.5
    val = max(0.0, min(1.0, val))
    return GroundedValue(value=val, source="heuristic")
