"""Negative free energy (E) — spec §3.1 E.

Tier 1 (FEP): variational free-energy estimator over agent predictions vs outcomes.
Tier 2 (resource): normalized throughput, (tokens/s) / (tokens/s)_max.
Tier 3 (heuristic): wraps legacy E.

Resource form ships as primary tier because it requires no new data beyond
what plugins already report. FEP form is stubbed; Phase 2 builds the estimator.
"""
from typing import Any, Dict

from src.grounding.types import GroundedValue

# Fleet-calibrated envelope — replaced by measured value in Phase 2.
TOKENS_PER_SECOND_MAX = 200.0


def compute_free_energy(ctx: Any, metrics: Dict[str, Any]) -> GroundedValue:
    args = getattr(ctx, "arguments", {}) or {}

    if "expected_outcome" in args and "observed_outcome" in args:
        try:
            return _compute_fep(args["expected_outcome"], args["observed_outcome"])
        except NotImplementedError:
            pass

    tokens = args.get("response_tokens")
    seconds = args.get("response_seconds")
    if tokens is not None and seconds is not None:
        try:
            return _compute_resource(float(tokens), float(seconds))
        except (ValueError, TypeError):
            pass

    return _compute_heuristic(metrics)


def _compute_fep(expected: Dict, observed: Dict) -> GroundedValue:
    raise NotImplementedError(
        "tier-1 FEP requires a generative model over outcomes; Phase 2 scope"
    )


def _compute_resource(tokens: float, seconds: float) -> GroundedValue:
    if seconds <= 0:
        raise ValueError("response_seconds must be positive")
    rate = tokens / seconds
    normalized = rate / TOKENS_PER_SECOND_MAX
    val = max(0.0, min(1.0, normalized))
    return GroundedValue(value=val, source="resource")


def _compute_heuristic(metrics: Dict[str, Any]) -> GroundedValue:
    raw = metrics.get("E", 0.5)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = 0.5
    val = max(0.0, min(1.0, val))
    return GroundedValue(value=val, source="heuristic")
