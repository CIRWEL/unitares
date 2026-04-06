"""Stub `governance_core.ethical_drift` — AgentBaseline + compute_ethical_drift."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_baseline_store: Dict[str, "AgentBaseline"] = {}


@dataclass
class EthicalDriftVector:
    calibration_deviation: float = 0.0
    complexity_divergence: float = 0.0
    coherence_deviation: float = 0.0
    stability_deviation: float = 0.0

    def __post_init__(self) -> None:
        self.norm_squared = (
            self.calibration_deviation ** 2
            + self.complexity_divergence ** 2
            + self.coherence_deviation ** 2
            + self.stability_deviation ** 2
        )
        self.norm = float(math.sqrt(self.norm_squared))

    def to_list(self) -> List[float]:
        return [
            self.calibration_deviation,
            self.complexity_divergence,
            self.coherence_deviation,
            self.stability_deviation,
        ]


@dataclass
class AgentBaseline:
    agent_id: str
    alpha: float = 0.2
    update_count: int = 0
    baseline_coherence: float = 0.5
    baseline_confidence: float = 0.6
    baseline_complexity: float = 0.4
    prev_coherence: Optional[float] = None
    prev_confidence: Optional[float] = None
    prev_complexity: Optional[float] = None
    _decision_history: List[str] = field(default_factory=list)

    def update(
        self,
        coherence: Optional[float] = None,
        confidence: Optional[float] = None,
        complexity: Optional[float] = None,
        decision: Optional[str] = None,
    ) -> None:
        if coherence is not None:
            self.prev_coherence = float(coherence)
            self.baseline_coherence = (
                self.alpha * float(coherence)
                + (1 - self.alpha) * self.baseline_coherence
            )
        if confidence is not None:
            self.prev_confidence = float(confidence)
            self.baseline_confidence = (
                self.alpha * float(confidence)
                + (1 - self.alpha) * self.baseline_confidence
            )
        if complexity is not None:
            self.prev_complexity = float(complexity)
            self.baseline_complexity = (
                self.alpha * float(complexity)
                + (1 - self.alpha) * self.baseline_complexity
            )
        if decision is not None:
            self._decision_history.append(decision)
        self.update_count += 1
        _baseline_store[self.agent_id] = self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "alpha": self.alpha,
            "update_count": self.update_count,
            "baseline_coherence": self.baseline_coherence,
            "baseline_confidence": self.baseline_confidence,
            "baseline_complexity": self.baseline_complexity,
            "prev_coherence": self.prev_coherence,
            "prev_confidence": self.prev_confidence,
            "prev_complexity": self.prev_complexity,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentBaseline":
        b = cls(
            agent_id=str(d.get("agent_id", "")),
            alpha=float(d.get("alpha", 0.2)),
            update_count=int(d.get("update_count", 0)),
            baseline_coherence=float(d.get("baseline_coherence", 0.5)),
            baseline_confidence=float(d.get("baseline_confidence", 0.6)),
            baseline_complexity=float(d.get("baseline_complexity", 0.4)),
        )
        b.prev_coherence = d.get("prev_coherence")
        b.prev_confidence = d.get("prev_confidence")
        b.prev_complexity = d.get("prev_complexity")
        if b.agent_id:
            _baseline_store[b.agent_id] = b
        return b


def get_baseline_or_none(agent_id: str) -> Optional[AgentBaseline]:
    return _baseline_store.get(agent_id)


def set_agent_baseline(agent_id: str, baseline: AgentBaseline) -> None:
    baseline.agent_id = agent_id
    _baseline_store[agent_id] = baseline


def clear_baseline(agent_id: str) -> None:
    _baseline_store.pop(agent_id, None)


def get_agent_baseline(agent_id: str) -> AgentBaseline:
    if agent_id not in _baseline_store:
        _baseline_store[agent_id] = AgentBaseline(agent_id=agent_id)
    return _baseline_store[agent_id]


def compute_ethical_drift(
    agent_id: str,
    baseline: AgentBaseline,
    current_coherence: float,
    current_confidence: float,
    complexity_divergence: float,
    calibration_error: Optional[float] = None,
    decision: Optional[str] = None,
    state_velocity: Optional[float] = None,
    task_context: Optional[str] = None,
) -> EthicalDriftVector:
    """Reproduce test expectations for warmup, rate-of-change, velocity floor, attenuation."""

    def _warmup_factor(count: int) -> float:
        return min(1.0, count / 5.0)

    wf = _warmup_factor(baseline.update_count)

    # Coherence / calibration from deviation + rate-of-change
    coh_dev = abs(current_coherence - baseline.baseline_coherence)
    if baseline.prev_coherence is not None:
        coh_dev = max(coh_dev, abs(current_coherence - baseline.prev_coherence))

    cal_dev = abs(current_confidence - baseline.baseline_confidence)
    if baseline.prev_confidence is not None:
        cal_dev = max(cal_dev, abs(current_confidence - baseline.prev_confidence))

    if calibration_error is not None:
        cal_dev = float(calibration_error)

    cpx_dev = float(complexity_divergence)
    stab_dev = 0.02 * cpx_dev

    if state_velocity is not None and abs(state_velocity) >= 0.01:
        vs = min(0.5, abs(float(state_velocity)))
        coh_dev = max(coh_dev, vs * 0.5)
        cal_dev = max(cal_dev, vs * 0.3)

    # Epistemic attenuation
    if task_context in ("introspection", "exploration"):
        cal_dev *= 0.3
        cpx_dev *= 0.3
    elif task_context == "convergent":
        pass  # no attenuation
    elif task_context == "mixed":
        pass

    coh_dev *= wf
    cal_dev *= wf
    cpx_dev *= wf
    stab_dev *= wf

    vec = EthicalDriftVector(
        calibration_deviation=cal_dev,
        complexity_divergence=cpx_dev,
        coherence_deviation=coh_dev,
        stability_deviation=stab_dev,
    )

    # Each check-in advances baseline / prev_* (integration tests rely on this without explicit .update)
    baseline.update(
        coherence=current_coherence,
        confidence=current_confidence,
        complexity=None,
    )
    return vec
