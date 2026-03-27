"""Per-agent profile metrics — differentiated measurements outside the EISV ODE.

The EISV ODE is a structural health check (contraction-theory thermostat). It ensures
agents stay in a healthy operating range, but by design all agents converge to the same
attractor. That's fine for health — bad for observability.

This module tracks per-agent metrics computed from raw check-in data, NOT from EISV state.
These metrics differentiate agents and make governance responses richer:
  - update_density: how active is this agent? (updates/hour)
  - complexity_distribution: what kind of work does this agent do?
  - confidence_calibration: rolling mean confidence vs outcomes
  - session_tenure: how long has this agent been active?
  - drift_history: does this agent drift? how much?
  - verdict_trajectory: recent verdicts pattern

In-memory with serialization support. Updated on every process_agent_update call.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional, List


# Window sizes
_DENSITY_WINDOW_S = 3600.0       # 1 hour for update density
_VERDICT_HISTORY_SIZE = 20       # Last 20 verdicts
_COMPLEXITY_HISTORY_SIZE = 50    # Last 50 complexity values
_DRIFT_HISTORY_SIZE = 50         # Last 50 drift magnitudes


@dataclass
class AgentProfile:
    """Differentiated per-agent metrics computed from check-in data."""

    # Timestamps of recent updates (for density calculation)
    _recent_timestamps: deque = field(default_factory=lambda: deque(maxlen=100))

    # First check-in time (for tenure)
    first_checkin_at: Optional[float] = None

    # Complexity distribution (Welford online stats)
    _complexity_count: int = 0
    _complexity_mean: float = 0.0
    _complexity_m2: float = 0.0
    _complexity_min: float = 1.0
    _complexity_max: float = 0.0

    # Confidence distribution (Welford online stats)
    _confidence_count: int = 0
    _confidence_mean: float = 0.0
    _confidence_m2: float = 0.0

    # Ethical drift magnitude (Welford + history)
    _drift_count: int = 0
    _drift_mean: float = 0.0
    _drift_m2: float = 0.0
    _drift_max_seen: float = 0.0

    # Verdict trajectory
    _verdict_history: deque = field(default_factory=lambda: deque(maxlen=_VERDICT_HISTORY_SIZE))

    # Total updates (for quick access)
    total_updates: int = 0

    def record_checkin(
        self,
        *,
        complexity: float,
        confidence: Optional[float] = None,
        ethical_drift: Optional[List[float]] = None,
        verdict: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Record a single check-in's data into the profile."""
        now = timestamp or time.time()
        self.total_updates += 1

        if self.first_checkin_at is None:
            self.first_checkin_at = now

        # Update density window
        self._recent_timestamps.append(now)

        # Complexity (Welford)
        self._complexity_count += 1
        delta = complexity - self._complexity_mean
        self._complexity_mean += delta / self._complexity_count
        delta2 = complexity - self._complexity_mean
        self._complexity_m2 += delta * delta2
        self._complexity_min = min(self._complexity_min, complexity)
        self._complexity_max = max(self._complexity_max, complexity)

        # Confidence (Welford)
        if confidence is not None:
            self._confidence_count += 1
            delta = confidence - self._confidence_mean
            self._confidence_mean += delta / self._confidence_count
            delta2 = confidence - self._confidence_mean
            self._confidence_m2 += delta * delta2

        # Ethical drift magnitude
        if ethical_drift:
            mag = math.sqrt(sum(d * d for d in ethical_drift))
            self._drift_count += 1
            delta = mag - self._drift_mean
            self._drift_mean += delta / self._drift_count
            delta2 = mag - self._drift_mean
            self._drift_m2 += delta * delta2
            self._drift_max_seen = max(self._drift_max_seen, mag)

        # Verdict trajectory
        if verdict:
            self._verdict_history.append(verdict)

    # ── Computed metrics ──────────────────────────────────────────

    @property
    def update_density(self) -> float:
        """Updates per hour over the last hour window."""
        if len(self._recent_timestamps) < 2:
            return 0.0
        now = time.time()
        cutoff = now - _DENSITY_WINDOW_S
        recent = [t for t in self._recent_timestamps if t >= cutoff]
        if len(recent) < 2:
            return float(len(recent))
        return len(recent) / ((now - recent[0]) / 3600.0)

    @property
    def session_tenure_hours(self) -> float:
        """Hours since first check-in."""
        if self.first_checkin_at is None:
            return 0.0
        return (time.time() - self.first_checkin_at) / 3600.0

    @property
    def complexity_stats(self) -> Dict[str, float]:
        """Complexity distribution: mean, std, min, max."""
        std = 0.0
        if self._complexity_count >= 2:
            std = math.sqrt(self._complexity_m2 / (self._complexity_count - 1))
        return {
            "mean": round(self._complexity_mean, 4),
            "std": round(std, 4),
            "min": round(self._complexity_min, 4),
            "max": round(self._complexity_max, 4),
            "count": self._complexity_count,
        }

    @property
    def confidence_stats(self) -> Dict[str, float]:
        """Confidence distribution: mean, std."""
        std = 0.0
        if self._confidence_count >= 2:
            std = math.sqrt(self._confidence_m2 / (self._confidence_count - 1))
        return {
            "mean": round(self._confidence_mean, 4),
            "std": round(std, 4),
            "count": self._confidence_count,
        }

    @property
    def drift_stats(self) -> Dict[str, float]:
        """Ethical drift magnitude: mean, std, max."""
        std = 0.0
        if self._drift_count >= 2:
            std = math.sqrt(self._drift_m2 / (self._drift_count - 1))
        return {
            "mean": round(self._drift_mean, 4),
            "std": round(std, 4),
            "max": round(self._drift_max_seen, 4),
            "count": self._drift_count,
        }

    @property
    def verdict_trajectory(self) -> Dict[str, int]:
        """Count of each verdict type in recent history."""
        counts: Dict[str, int] = {}
        for v in self._verdict_history:
            counts[v] = counts.get(v, 0) + 1
        return counts

    @property
    def verdict_trend(self) -> Optional[str]:
        """Simple trend: 'improving', 'stable', 'degrading', or None if insufficient data."""
        history = list(self._verdict_history)
        if len(history) < 4:
            return None
        # Compare last quarter to first quarter
        quarter = len(history) // 4
        early = history[:quarter]
        late = history[-quarter:]

        def severity(v: str) -> int:
            return {"proceed": 0, "guide": 1, "pause": 2, "reject": 3}.get(v, 1)

        early_avg = sum(severity(v) for v in early) / len(early)
        late_avg = sum(severity(v) for v in late) / len(late)
        diff = late_avg - early_avg
        if diff < -0.3:
            return "improving"
        elif diff > 0.3:
            return "degrading"
        return "stable"

    def to_summary(self) -> Dict:
        """Serializable summary for API responses."""
        return {
            "total_updates": self.total_updates,
            "update_density_per_hour": round(self.update_density, 2),
            "session_tenure_hours": round(self.session_tenure_hours, 2),
            "complexity": self.complexity_stats,
            "confidence": self.confidence_stats,
            "drift": self.drift_stats,
            "verdict_trajectory": self.verdict_trajectory,
            "verdict_trend": self.verdict_trend,
        }

    def to_dict(self) -> Dict:
        """Full serialization for persistence."""
        return {
            "first_checkin_at": self.first_checkin_at,
            "total_updates": self.total_updates,
            "complexity": {
                "count": self._complexity_count,
                "mean": self._complexity_mean,
                "m2": self._complexity_m2,
                "min": self._complexity_min,
                "max": self._complexity_max,
            },
            "confidence": {
                "count": self._confidence_count,
                "mean": self._confidence_mean,
                "m2": self._confidence_m2,
            },
            "drift": {
                "count": self._drift_count,
                "mean": self._drift_mean,
                "m2": self._drift_m2,
                "max_seen": self._drift_max_seen,
            },
            "verdict_history": list(self._verdict_history),
            "recent_timestamps": list(self._recent_timestamps)[-20:],  # Keep last 20 for density
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "AgentProfile":
        """Reconstruct from serialized dict."""
        p = cls()
        p.first_checkin_at = d.get("first_checkin_at")
        p.total_updates = d.get("total_updates", 0)

        c = d.get("complexity", {})
        p._complexity_count = c.get("count", 0)
        p._complexity_mean = c.get("mean", 0.0)
        p._complexity_m2 = c.get("m2", 0.0)
        p._complexity_min = c.get("min", 1.0)
        p._complexity_max = c.get("max", 0.0)

        cf = d.get("confidence", {})
        p._confidence_count = cf.get("count", 0)
        p._confidence_mean = cf.get("mean", 0.0)
        p._confidence_m2 = cf.get("m2", 0.0)

        dr = d.get("drift", {})
        p._drift_count = dr.get("count", 0)
        p._drift_mean = dr.get("mean", 0.0)
        p._drift_m2 = dr.get("m2", 0.0)
        p._drift_max_seen = dr.get("max_seen", 0.0)

        vh = d.get("verdict_history", [])
        p._verdict_history = deque(vh, maxlen=_VERDICT_HISTORY_SIZE)

        ts = d.get("recent_timestamps", [])
        p._recent_timestamps = deque(ts, maxlen=100)

        return p


# ── Global registry ───────────────────────────────────────────

_profiles: Dict[str, AgentProfile] = {}


def get_agent_profile(agent_id: str) -> AgentProfile:
    """Get or create the profile for an agent."""
    if agent_id not in _profiles:
        _profiles[agent_id] = AgentProfile()
    return _profiles[agent_id]


def get_all_profiles() -> Dict[str, AgentProfile]:
    """Return the full profiles registry (read-only access)."""
    return _profiles
