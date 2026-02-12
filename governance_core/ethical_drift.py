"""
UNITARES Governance Core - Ethical Drift Vector

Concrete, measurable implementation of the ethical drift vector Δη.

THEORETICAL FOUNDATION:
The patent critiques correctly identified that "ethical drift" was abstract.
This module makes it CONCRETE by defining Δη as a vector of measurable deviations:

    Δη = (
        calibration_deviation,    # |predicted_correct - actual_correct|
        complexity_divergence,    # |derived_complexity - self_complexity|
        coherence_deviation,      # |current_coherence - baseline_coherence|
        stability_deviation       # Decision pattern instability
    )

Each component is computed from OBSERVABLE SIGNALS, not abstract concepts.
The L2 norm ||Δη|| feeds into the EISV dynamics (dS/dt, dE/dt).

MAPPING TO PATENT TERMINOLOGY:
- "Fairness deviation" → calibration_deviation (confidence vs outcome)
- "Explainability deviation" → complexity_divergence (derived vs reported)
- "Robustness deviation" → coherence_deviation (current vs baseline)
- "Consistency deviation" → stability_deviation (decision patterns)

This is the "instrumentation layer" that converts abstract governance into
measurable engineering signals, satisfying the patent claims.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import math


@dataclass
class EthicalDriftVector:
    """
    Concrete ethical drift vector with measurable components.

    Each component is in [0, 1] and represents a deviation from ideal.
    Lower values = better calibration/alignment.

    Attributes:
        calibration_deviation: Confidence-outcome mismatch (from calibration system)
        complexity_divergence: Gap between derived and self-reported complexity
        coherence_deviation: Gap between current and baseline coherence
        stability_deviation: Decision pattern instability over time
        timestamp: When this vector was computed
        agent_id: Which agent this applies to
    """
    calibration_deviation: float = 0.0
    complexity_divergence: float = 0.0
    coherence_deviation: float = 0.0
    stability_deviation: float = 0.0
    timestamp: Optional[datetime] = None
    agent_id: Optional[str] = None

    def __post_init__(self):
        """Validate and clip components to [0, 1]."""
        self.calibration_deviation = max(0.0, min(1.0, self.calibration_deviation))
        self.complexity_divergence = max(0.0, min(1.0, self.complexity_divergence))
        self.coherence_deviation = max(0.0, min(1.0, self.coherence_deviation))
        self.stability_deviation = max(0.0, min(1.0, self.stability_deviation))
        if self.timestamp is None:
            self.timestamp = datetime.now()

    @property
    def norm(self) -> float:
        """
        L2 norm of the drift vector.

        This is ||Δη|| that feeds into EISV dynamics.
        Range: [0, 2] (max when all components are 1.0)
        """
        return math.sqrt(
            self.calibration_deviation ** 2 +
            self.complexity_divergence ** 2 +
            self.coherence_deviation ** 2 +
            self.stability_deviation ** 2
        )

    @property
    def norm_squared(self) -> float:
        """||Δη||² - Used directly in dS/dt and dE/dt equations."""
        return (
            self.calibration_deviation ** 2 +
            self.complexity_divergence ** 2 +
            self.coherence_deviation ** 2 +
            self.stability_deviation ** 2
        )

    def to_list(self) -> List[float]:
        """
        Convert to list format for compatibility with existing dynamics code.

        Returns 4-element list [calibration, complexity, coherence, stability].
        """
        return [
            self.calibration_deviation,
            self.complexity_divergence,
            self.coherence_deviation,
            self.stability_deviation,
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage and API responses."""
        return {
            'calibration_deviation': self.calibration_deviation,
            'complexity_divergence': self.complexity_divergence,
            'coherence_deviation': self.coherence_deviation,
            'stability_deviation': self.stability_deviation,
            'norm': self.norm,
            'norm_squared': self.norm_squared,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'agent_id': self.agent_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EthicalDriftVector':
        """Deserialize from storage."""
        return cls(
            calibration_deviation=data.get('calibration_deviation', 0.0),
            complexity_divergence=data.get('complexity_divergence', 0.0),
            coherence_deviation=data.get('coherence_deviation', 0.0),
            stability_deviation=data.get('stability_deviation', 0.0),
            timestamp=datetime.fromisoformat(data['timestamp']) if data.get('timestamp') else None,
            agent_id=data.get('agent_id'),
        )

    @classmethod
    def zero(cls, agent_id: Optional[str] = None) -> 'EthicalDriftVector':
        """Create a zero drift vector (perfect alignment)."""
        return cls(
            calibration_deviation=0.0,
            complexity_divergence=0.0,
            coherence_deviation=0.0,
            stability_deviation=0.0,
            agent_id=agent_id,
        )


@dataclass
class AgentBaseline:
    """
    Baseline measurements for an agent, used to compute deviations.

    Updated incrementally with exponential moving average.
    """
    agent_id: str

    # Baseline values (exponential moving averages)
    baseline_coherence: float = 0.5
    baseline_confidence: float = 0.6
    baseline_complexity: float = 0.4

    # Decision pattern tracking
    recent_decisions: List[str] = field(default_factory=list)  # Last N decision outcomes
    decision_consistency: float = 0.8  # How consistent are decisions

    # Update count for weighting
    update_count: int = 0

    # EMA smoothing factor (higher = more responsive, lower = more stable)
    alpha: float = 0.1

    # Last update timestamp
    last_updated: Optional[datetime] = None

    def update(
        self,
        coherence: Optional[float] = None,
        confidence: Optional[float] = None,
        complexity: Optional[float] = None,
        decision: Optional[str] = None,
    ):
        """
        Update baselines with new observations using EMA.

        EMA formula: baseline = alpha * new_value + (1 - alpha) * old_baseline
        """
        if coherence is not None:
            self.baseline_coherence = (
                self.alpha * coherence + (1 - self.alpha) * self.baseline_coherence
            )

        if confidence is not None:
            self.baseline_confidence = (
                self.alpha * confidence + (1 - self.alpha) * self.baseline_confidence
            )

        if complexity is not None:
            self.baseline_complexity = (
                self.alpha * complexity + (1 - self.alpha) * self.baseline_complexity
            )

        if decision is not None:
            self.recent_decisions.append(decision)
            # Keep only last 20 decisions
            if len(self.recent_decisions) > 20:
                self.recent_decisions = self.recent_decisions[-20:]
            # Compute consistency as mode frequency
            self._update_decision_consistency()

        self.update_count += 1
        self.last_updated = datetime.now()

    def _update_decision_consistency(self):
        """Compute decision consistency from recent decisions."""
        if len(self.recent_decisions) < 2:
            self.decision_consistency = 0.8  # Default
            return

        # Count transitions (decision changes)
        transitions = sum(
            1 for i in range(1, len(self.recent_decisions))
            if self.recent_decisions[i] != self.recent_decisions[i-1]
        )

        # Stability = 1 - (transitions / possible_transitions)
        max_transitions = len(self.recent_decisions) - 1
        if max_transitions > 0:
            stability = 1.0 - (transitions / max_transitions)
            # Smooth with current value
            self.decision_consistency = (
                0.3 * stability + 0.7 * self.decision_consistency
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            'agent_id': self.agent_id,
            'baseline_coherence': self.baseline_coherence,
            'baseline_confidence': self.baseline_confidence,
            'baseline_complexity': self.baseline_complexity,
            'recent_decisions': self.recent_decisions,
            'decision_consistency': self.decision_consistency,
            'update_count': self.update_count,
            'alpha': self.alpha,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentBaseline':
        """Deserialize from storage."""
        baseline = cls(agent_id=data['agent_id'])
        baseline.baseline_coherence = data.get('baseline_coherence', 0.5)
        baseline.baseline_confidence = data.get('baseline_confidence', 0.6)
        baseline.baseline_complexity = data.get('baseline_complexity', 0.4)
        baseline.recent_decisions = data.get('recent_decisions', [])
        baseline.decision_consistency = data.get('decision_consistency', 0.8)
        baseline.update_count = data.get('update_count', 0)
        baseline.alpha = data.get('alpha', 0.1)
        if data.get('last_updated'):
            baseline.last_updated = datetime.fromisoformat(data['last_updated'])
        return baseline


def compute_ethical_drift(
    agent_id: str,
    baseline: AgentBaseline,
    current_coherence: float,
    current_confidence: float,
    complexity_divergence: float,
    calibration_error: Optional[float] = None,
    decision: Optional[str] = None,
) -> EthicalDriftVector:
    """
    Compute concrete ethical drift vector from measurable signals.

    This is THE function that makes Δη concrete. It takes observable
    measurements and converts them into the drift vector.

    Args:
        agent_id: Agent identifier
        baseline: Agent's baseline measurements (for deviation calculation)
        current_coherence: Current coherence value C(V, Θ)
        current_confidence: Current confidence level [0, 1]
        complexity_divergence: |derived_complexity - self_complexity|
        calibration_error: Calibration deviation (if available)
        decision: Current decision outcome (for stability tracking)

    Returns:
        EthicalDriftVector with all components computed

    MEASUREMENT DEFINITIONS:

    1. calibration_deviation: How well confidence predicts outcomes
       - Uses calibration_error if provided
       - Otherwise uses |confidence - baseline_confidence|
       - Range: [0, 1]

    2. complexity_divergence: Gap between derived and reported complexity
       - Directly passed from dual-log continuity layer
       - Range: [0, 1]

    3. coherence_deviation: Current vs baseline coherence
       - |current_coherence - baseline_coherence|
       - Range: [0, 1]

    4. stability_deviation: Decision pattern instability
       - Inverse of decision_consistency
       - Range: [0, 1]
    """

    # 1. Calibration deviation
    if calibration_error is not None:
        calibration_deviation = min(1.0, abs(calibration_error))
    else:
        # Fallback: use confidence deviation from baseline
        calibration_deviation = abs(current_confidence - baseline.baseline_confidence)

    # 2. Complexity divergence (passed directly)
    # Already computed by dual-log continuity layer
    complexity_dev = min(1.0, abs(complexity_divergence))

    # 3. Coherence deviation
    coherence_dev = abs(current_coherence - baseline.baseline_coherence)

    # 4. Stability deviation (inverse of consistency)
    stability_dev = 1.0 - baseline.decision_consistency

    # Warmup dampening: deviations from uninitialized baselines are meaningless.
    # For the first few updates, the baseline is just defaults (0.6, 0.5, 0.8 etc.)
    # so large "deviations" are artifacts, not real drift signals.
    # Ramp from 0→1 over 5 updates so drift reflects actual observed patterns.
    warmup_updates = 5
    if baseline.update_count < warmup_updates:
        warmup_factor = baseline.update_count / warmup_updates
        calibration_deviation *= warmup_factor
        # complexity_divergence is measured directly, not from baseline — no dampening needed
        coherence_dev *= warmup_factor
        stability_dev *= warmup_factor

    # Update baseline with current observations
    baseline.update(
        coherence=current_coherence,
        confidence=current_confidence,
        complexity=1.0 - complexity_divergence,  # Low divergence = high complexity accuracy
        decision=decision,
    )

    return EthicalDriftVector(
        calibration_deviation=calibration_deviation,
        complexity_divergence=complexity_dev,
        coherence_deviation=coherence_dev,
        stability_deviation=stability_dev,
        agent_id=agent_id,
    )


# Baseline storage (in-memory, can be extended to Redis)
_baseline_cache: Dict[str, AgentBaseline] = {}


def get_agent_baseline(agent_id: str) -> AgentBaseline:
    """Get or create baseline for an agent."""
    if agent_id not in _baseline_cache:
        _baseline_cache[agent_id] = AgentBaseline(agent_id=agent_id)
    return _baseline_cache[agent_id]


def clear_baseline(agent_id: str):
    """Clear baseline for an agent (for testing or reset)."""
    if agent_id in _baseline_cache:
        del _baseline_cache[agent_id]


def get_all_baselines() -> Dict[str, AgentBaseline]:
    """Get all baselines (for debugging/inspection)."""
    return _baseline_cache.copy()
