"""Stub adaptive governor for CIRS tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GovernorConfig:
    flip_threshold: int = 5
    oi_threshold: float = 2.0


@dataclass
class GovernorState:
    tau: float = 0.40
    beta: float = 0.60
    delta: float = 0.0
    neighbor_pressure: float = 0.0
    agents_in_resonance: int = 0
    flips: int = 0
    phase: str = "integration"
    _prev_verdict: Optional[str] = None
    _oi: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tau": self.tau,
            "beta": self.beta,
            "delta": self.delta,
            "neighbor_pressure": self.neighbor_pressure,
            "agents_in_resonance": self.agents_in_resonance,
            "flips": self.flips,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GovernorState":
        return cls(
            tau=float(d.get("tau", 0.40)),
            beta=float(d.get("beta", 0.60)),
            delta=float(d.get("delta", 0.0)),
            neighbor_pressure=float(d.get("neighbor_pressure", 0.0)),
            agents_in_resonance=int(d.get("agents_in_resonance", 0)),
            flips=int(d.get("flips", 0)),
        )


class AdaptiveGovernor:
    def __init__(self, config: Optional[GovernorConfig] = None):
        self.config = config or GovernorConfig()
        self.state = GovernorState()

    def update(
        self,
        coherence: float,
        risk: float,
        verdict: str,
        E_history: Optional[List[float]] = None,
        I_history: Optional[List[float]] = None,
        S_history: Optional[List[float]] = None,
        complexity_history: Optional[List[float]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        pv = self.state._prev_verdict
        if pv is not None and verdict != pv:
            self.state.flips += 1
        self.state._prev_verdict = verdict

        # Oscillation index grows with flips and risk swings
        self.state._oi = min(5.0, self.state.flips * 0.4 + risk * 3.0)
        resonant = (
            self.state.flips >= self.config.flip_threshold
            or self.state._oi >= self.config.oi_threshold
        )

        # "verdict" is the response tier for monitor_cirs (proceed / soft_dampen / …)
        if resonant:
            tier = "soft_dampen"
        elif risk > 0.5:
            tier = "soft_dampen"
        else:
            tier = "proceed"

        return {
            "resonant": resonant,
            "oi": float(self.state._oi),
            "tau": self.state.tau,
            "beta": self.state.beta,
            "flips": self.state.flips,
            "phase": self.state.phase,
            "trigger": "oi" if resonant else None,
            "verdict": tier,
        }

    def apply_neighbor_pressure(self, similarity: float) -> None:
        if similarity >= 0.5:
            self.state.neighbor_pressure = min(
                1.0, self.state.neighbor_pressure + 0.1 * similarity
            )
            self.state.agents_in_resonance = max(1, self.state.agents_in_resonance)

    def decay_neighbor_pressure(self) -> None:
        self.state.neighbor_pressure *= 0.5
        self.state.agents_in_resonance = max(0, self.state.agents_in_resonance - 1)
