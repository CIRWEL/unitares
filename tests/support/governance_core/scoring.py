"""Stub `governance_core.scoring` — phi objective and verdict strings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Union

from .dynamics import State
from .parameters import DynamicsParams, get_active_params

DEFAULT_WEIGHTS: Dict[str, float] = {
    "E": 0.25,
    "I": 0.25,
    "S": 0.25,
    "V": 0.25,
}


def phi_objective(
    state: State,
    delta_eta: Optional[Sequence[float]] = None,
    weights: Union[Mapping[str, float], None] = None,
    **kwargs: Any,
) -> float:
    """Scalar objective — higher is healthier. Supports kwargs from different call sites."""
    if kwargs.get("state") is not None and not isinstance(state, State):
        state = kwargs["state"]
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(dict(weights))
    if delta_eta is None:
        delta_eta = []
    drift = sum(float(x) * float(x) for x in delta_eta) ** 0.5
    # Core: distance from ideal interior (E,I high, S low, V near 0)
    core = (
        w.get("E", 0.25) * state.E
        + w.get("I", 0.25) * state.I
        - w.get("S", 0.25) * state.S
        - w.get("V", 0.25) * abs(state.V)
    )
    # Strong drift penalty so stressed verdicts hit high-risk (tests/test_eisv_behavioral.py)
    return float(core - 1.5 * drift - 0.2 * drift * drift)


def verdict_from_phi(phi: float) -> str:
    if phi >= 0.08:
        return "safe"
    if phi >= 0.0:
        return "caution"
    return "high-risk"
