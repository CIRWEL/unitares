"""Stub coherence and λ₁/λ₂ — matches tests/test_lambda1_pi_controller.py mapping."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .parameters import DynamicsParams, Theta


def coherence(V: float, theta: "Theta", params: "DynamicsParams") -> float:
    """Bounded coherence C(V) in [0, Cmax]."""
    return float(params.Cmax * 0.5 * (1.0 + math.tanh(theta.C1 * V)))


def lambda1(
    theta: "Theta",
    params: "DynamicsParams",
    lambda1_min: float = 0.05,
    lambda1_max: float = 0.20,
) -> float:
    """Piecewise-linear map η₁ ∈ [0.1, 0.5] → [lambda1_min, lambda1_max]."""
    span = 0.5 - 0.1
    t = (theta.eta1 - 0.1) / span
    t = max(0.0, min(1.0, t))
    return float(lambda1_min + t * (lambda1_max - lambda1_min))


def lambda2(theta: "Theta", params: "DynamicsParams") -> float:
    """Ethical coupling on dS/dt w.r.t. coherence."""
    return float(params.lambda2)
