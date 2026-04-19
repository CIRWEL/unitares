"""Shared return type for grounding compute functions."""
from dataclasses import dataclass
from typing import Dict

ALLOWED_SOURCES = frozenset({
    "logprob",      # tier-1: model logprobs
    "multisample",  # tier-2: k-sample self-consistency
    "resource",     # tier-3 E: resource-rate form
    "fep",          # E via variational free-energy estimator
    "kl",           # coherence via KL divergence
    "manifold",     # coherence via state-space distance
    "heuristic",    # tier-3 fallback — legacy computation
})


@dataclass(frozen=True)
class GroundedValue:
    """A grounded governance quantity paired with its computation source.

    Value is always in [0, 1] — normalized at the source module.
    """
    value: float
    source: str

    def __post_init__(self) -> None:
        if self.source not in ALLOWED_SOURCES:
            raise ValueError(
                f"unknown grounding source {self.source!r}; "
                f"must be one of {sorted(ALLOWED_SOURCES)}"
            )
        if not (0.0 <= self.value <= 1.0):
            raise ValueError(
                f"GroundedValue.value out of range [0,1]: {self.value}"
            )

    def as_dict(self) -> Dict[str, object]:
        return {"value": self.value, "source": self.source}
