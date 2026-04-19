"""Coherence — spec §3.1 Coherence.

Two grounded forms:
  - manifold:  C = 1 - ||Δ||_2 / ||Δ||_max, Δ = (E,I,S) - (E,I,S)_healthy
  - kl:        C = exp(-D_KL(q_now || q_ref)), requires reference distribution

Manifold form ships as primary (needs only existing EISV). KL stubbed for Phase 2.
"""
import math
from typing import Any, Dict

from src.grounding.types import GroundedValue


def compute_coherence(ctx: Any, metrics: Dict[str, Any]) -> GroundedValue:
    if "q_now" in metrics and "q_ref" in metrics:
        try:
            return _compute_kl(metrics["q_now"], metrics["q_ref"])
        except NotImplementedError:
            pass

    agent_class = getattr(ctx, "agent_class", None) or "default"

    try:
        return _compute_manifold(
            E=float(metrics["E"]),
            I=float(metrics["I"]),
            S=float(metrics["S"]),
            agent_class=agent_class,
        )
    except (KeyError, TypeError, ValueError):
        pass

    return _compute_heuristic(metrics)


def _compute_kl(q_now: list, q_ref: list) -> GroundedValue:
    raise NotImplementedError(
        "tier-1 KL coherence requires a calibrated reference distribution q_ref; "
        "Phase 2 scope"
    )


def _compute_manifold(E: float, I: float, S: float, agent_class: str = "default") -> GroundedValue:
    """Manifold distance from healthy (E,I,S) baseline.

    Uses class-conditional ||Δ||_max if the class has a measured value;
    otherwise falls back to the fleet-wide default.
    """
    from config.governance_config import BASIN_HIGH, get_delta_norm_max

    healthy_E = BASIN_HIGH.E_min
    healthy_I = BASIN_HIGH.I_min
    healthy_S = 0.0

    dx = E - healthy_E
    dy = I - healthy_I
    dz = S - healthy_S
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    ratio = norm / get_delta_norm_max(agent_class).value
    val = 1.0 - max(0.0, min(1.0, ratio))
    return GroundedValue(value=val, source="manifold")


def _compute_heuristic(metrics: Dict[str, Any]) -> GroundedValue:
    raw = metrics.get("coherence", 0.5)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = 0.5
    val = max(0.0, min(1.0, val))
    return GroundedValue(value=val, source="heuristic")
