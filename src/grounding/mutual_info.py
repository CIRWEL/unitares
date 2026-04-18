"""Mutual information MI(x; y) between context and response — spec §3.1 I.

Tier 1: MI from paired logprobs (context-only vs context+response).
Tier 2: multi-sample via KL divergence from a reference distribution.
Tier 3: wraps the legacy [0,1] I heuristic.
"""
from typing import Any, Dict

from src.grounding.types import GroundedValue


def compute_mutual_info(ctx: Any, metrics: Dict[str, Any]) -> GroundedValue:
    args = getattr(ctx, "arguments", {}) or {}

    if "logprobs" in args and "context_logprobs" in args:
        try:
            return _compute_from_logprobs(
                args["logprobs"], args["context_logprobs"]
            )
        except NotImplementedError:
            pass

    if "samples" in args:
        try:
            return _compute_from_samples(args["samples"])
        except NotImplementedError:
            pass

    return _compute_heuristic(metrics)


def _compute_from_logprobs(logprobs: list, context_logprobs: list) -> GroundedValue:
    raise NotImplementedError(
        "tier-1 MI requires paired context/response logprobs; "
        "see spec §3.1 I 'Computation recipe'"
    )


def _compute_from_samples(samples: list) -> GroundedValue:
    raise NotImplementedError(
        "tier-2 MI requires reference-distribution estimator; deferred from Phase 1"
    )


def _compute_heuristic(metrics: Dict[str, Any]) -> GroundedValue:
    raw = metrics.get("I", 0.5)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = 0.5
    val = max(0.0, min(1.0, val))
    return GroundedValue(value=val, source="heuristic")
