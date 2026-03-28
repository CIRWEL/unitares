"""Behavioral EISV: observation-first agent state without ODE dynamics.

EMA-smoothed observations of agent behavior. No universal attractor, no
contraction — each agent's state reflects its actual observables.

Modeled after anima-mcp's drawing EISV: proprioceptive signals, EMA smoothing,
wall-clock half-life.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# Per-dimension EMA alphas.
# At 30s cadence: half-life = -30 / ln(1 - alpha)
#   E: alpha=0.12 → ~220s half-life (capacity changes slowly)
#   I: alpha=0.08 → ~350s half-life (integrity is conservative)
#   S: alpha=0.15 → ~175s half-life (entropy responds faster)
#   V: alpha=0.10 → ~270s half-life (imbalance is medium-term)
DEFAULT_ALPHAS = {"E": 0.12, "I": 0.08, "S": 0.15, "V": 0.10}

# Bootstrap defaults — neutral starting point
BOOTSTRAP_E = 0.5
BOOTSTRAP_I = 0.5
BOOTSTRAP_S = 0.2
BOOTSTRAP_V = 0.0

# History cap
MAX_HISTORY = 100

# Number of updates before full confidence in behavioral state
BOOTSTRAP_UPDATES = 10


@dataclass
class BehavioralEISV:
    """EMA-smoothed behavioral EISV state.

    No ODE. No attractor. Just observations smoothed over time.
    V is derived from current E-I gap, not accumulated.
    """

    E: float = BOOTSTRAP_E
    I: float = BOOTSTRAP_I
    S: float = BOOTSTRAP_S
    V: float = BOOTSTRAP_V

    update_count: int = 0
    last_update_time: Optional[float] = None  # monotonic seconds

    # Per-dimension EMA alphas (can be tuned per agent)
    alphas: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ALPHAS))

    # History for trend detection
    E_history: List[float] = field(default_factory=list)
    I_history: List[float] = field(default_factory=list)
    S_history: List[float] = field(default_factory=list)
    V_history: List[float] = field(default_factory=list)

    def update(
        self,
        E_obs: float,
        I_obs: float,
        S_obs: float,
    ) -> None:
        """Update behavioral state from observations.

        Args:
            E_obs: Observed energy [0, 1] — from tool success, decision quality
            I_obs: Observed integrity [0, 1] — from calibration accuracy, coherence
            S_obs: Observed entropy [0, 1] — from drift, instability, divergence
        """
        # Clamp inputs
        E_obs = max(0.0, min(1.0, E_obs))
        I_obs = max(0.0, min(1.0, I_obs))
        S_obs = max(0.0, min(1.0, S_obs))

        # During bootstrap, ramp alpha from 0.5 (fast catch-up) down to configured value
        if self.update_count < BOOTSTRAP_UPDATES:
            ramp = 1.0 - (self.update_count / BOOTSTRAP_UPDATES)
            bootstrap_boost = 0.5 - 0.0  # max extra alpha during bootstrap
            alpha_E = self.alphas["E"] + bootstrap_boost * ramp
            alpha_I = self.alphas["I"] + bootstrap_boost * ramp
            alpha_S = self.alphas["S"] + bootstrap_boost * ramp
        else:
            alpha_E = self.alphas["E"]
            alpha_I = self.alphas["I"]
            alpha_S = self.alphas["S"]

        # EMA update: new = (1 - alpha) * old + alpha * observation
        self.E = (1.0 - alpha_E) * self.E + alpha_E * E_obs
        self.I = (1.0 - alpha_I) * self.I + alpha_I * I_obs
        self.S = (1.0 - alpha_S) * self.S + alpha_S * S_obs

        # V derived from current E-I gap (not accumulated)
        self.V = self.E - self.I

        # Clamp to valid ranges
        self.E = max(0.0, min(1.0, self.E))
        self.I = max(0.0, min(1.0, self.I))
        self.S = max(0.0, min(1.0, self.S))
        self.V = max(-1.0, min(1.0, self.V))

        # Record history
        self.E_history.append(self.E)
        self.I_history.append(self.I)
        self.S_history.append(self.S)
        self.V_history.append(self.V)

        # Trim history
        if len(self.E_history) > MAX_HISTORY:
            self.E_history = self.E_history[-MAX_HISTORY:]
            self.I_history = self.I_history[-MAX_HISTORY:]
            self.S_history = self.S_history[-MAX_HISTORY:]
            self.V_history = self.V_history[-MAX_HISTORY:]

        self.update_count += 1
        self.last_update_time = time.monotonic()

    @property
    def confidence(self) -> float:
        """Confidence in behavioral state — ramps from 0 to 1 over bootstrap period."""
        if self.update_count >= BOOTSTRAP_UPDATES:
            return 1.0
        return self.update_count / BOOTSTRAP_UPDATES

    def trend(self, dimension: str, window: int = 5) -> float:
        """Simple slope of recent history for a dimension.

        Returns positive for improving, negative for declining.
        """
        history = getattr(self, f"{dimension}_history", [])
        if len(history) < 2:
            return 0.0
        recent = history[-window:]
        if len(recent) < 2:
            return 0.0
        n = len(recent)
        x_mean = (n - 1) / 2.0
        y_mean = sum(recent) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(recent))
        den = sum((i - x_mean) ** 2 for i in range(n))
        if den == 0:
            return 0.0
        return num / den

    def to_dict(self) -> Dict:
        """Export current state for inclusion in governance responses."""
        return {
            "E": round(self.E, 4),
            "I": round(self.I, 4),
            "S": round(self.S, 4),
            "V": round(self.V, 4),
            "confidence": round(self.confidence, 2),
            "updates": self.update_count,
        }

    def to_dict_with_history(self) -> Dict:
        """Export state with history for persistence."""
        d = self.to_dict()
        d["E_history"] = [round(v, 4) for v in self.E_history[-MAX_HISTORY:]]
        d["I_history"] = [round(v, 4) for v in self.I_history[-MAX_HISTORY:]]
        d["S_history"] = [round(v, 4) for v in self.S_history[-MAX_HISTORY:]]
        d["V_history"] = [round(v, 4) for v in self.V_history[-MAX_HISTORY:]]
        d["alphas"] = dict(self.alphas)
        return d

    @classmethod
    def from_dict(cls, data: Dict) -> BehavioralEISV:
        """Restore from persisted dict."""
        state = cls()
        state.E = float(data.get("E", BOOTSTRAP_E))
        state.I = float(data.get("I", BOOTSTRAP_I))
        state.S = float(data.get("S", BOOTSTRAP_S))
        state.V = float(data.get("V", BOOTSTRAP_V))
        state.update_count = int(data.get("updates", 0))
        state.E_history = [float(v) for v in data.get("E_history", [])]
        state.I_history = [float(v) for v in data.get("I_history", [])]
        state.S_history = [float(v) for v in data.get("S_history", [])]
        state.V_history = [float(v) for v in data.get("V_history", [])]
        if "alphas" in data:
            state.alphas = {k: float(v) for k, v in data["alphas"].items()}
        return state
