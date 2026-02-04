"""
Core calibration engine.

Tracks prediction confidence vs actual accuracy. Provides correction factors
so when your model says "90% confident" but is historically only 70% accurate,
you can adjust accordingly.
"""

from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from datetime import datetime

__all__ = ["Calibrator", "CalibrationReport"]


@dataclass
class Bin:
    """Statistics for a confidence bin."""
    count: int = 0
    correct: float = 0.0  # Float to support partial credit
    confidence_sum: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.correct / self.count if self.count > 0 else 0.0

    @property
    def mean_confidence(self) -> float:
        return self.confidence_sum / self.count if self.count > 0 else 0.0

    @property
    def error(self) -> float:
        """Calibration error: |accuracy - mean_confidence|"""
        return abs(self.accuracy - self.mean_confidence)

    def to_dict(self) -> Dict:
        return {
            "count": self.count,
            "correct": self.correct,
            "confidence_sum": self.confidence_sum,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Bin":
        b = cls()
        b.count = d.get("count", 0)
        b.correct = d.get("correct", 0.0)
        b.confidence_sum = d.get("confidence_sum", 0.0)
        return b


@dataclass
class CalibrationReport:
    """Result of calibration check."""
    calibrated: bool
    total: int
    issues: List[str]
    bins: Dict[str, Dict]
    correction_factors: Dict[str, float]

    @property
    def summary(self) -> str:
        if self.total == 0:
            return "No data"
        if self.calibrated:
            return f"Well calibrated ({self.total} samples)"
        return f"{len(self.issues)} issues ({self.total} samples)"


class Calibrator:
    """
    Tracks prediction confidence vs actual accuracy.

    Example:
        cal = Calibrator()

        # Record predictions with outcomes
        cal.record_with_outcome(0.9, correct=True)
        cal.record_with_outcome(0.9, correct=False)
        cal.record_with_outcome(0.9, correct=True)

        # Correct future predictions
        raw = 0.9
        adjusted, info = cal.calibrate(raw)
        # If historically 90% confidence = 67% accuracy, adjusted ≈ 0.67

        # Check health
        report = cal.check()
        print(report.summary)  # "2 issues (100 samples)"
    """

    DEFAULT_BINS = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]

    def __init__(
        self,
        bins: List[Tuple[float, float]] = None,
        path: Optional[str | Path] = None,
        min_samples: int = 5,
    ):
        """
        Args:
            bins: Confidence ranges. Default: 5 bins [0-0.5, 0.5-0.7, 0.7-0.8, 0.8-0.9, 0.9-1.0]
            path: File path for persistence. None = memory only.
            min_samples: Minimum samples before applying corrections.
        """
        self.bins = bins or self.DEFAULT_BINS
        self.path = Path(path) if path else None
        self.min_samples = min_samples
        self._data: Dict[str, Bin] = defaultdict(Bin)
        self._pending: List[Dict] = []

        if self.path and self.path.exists():
            self._load()

    def _key(self, conf: float) -> str:
        """Get bin key for confidence value."""
        conf = max(0.0, min(1.0, float(conf)))
        for lo, hi in self.bins:
            if lo <= conf < hi or (hi == 1.0 and conf == 1.0):
                return f"{lo:.1f}-{hi:.1f}"
        return f"{self.bins[-1][0]:.1f}-{self.bins[-1][1]:.1f}"

    def record(self, confidence: float, prediction: Any = None) -> str:
        """
        Record a prediction. Call outcome() later with the result.

        Args:
            confidence: Confidence level 0-1
            prediction: Optional prediction value for tracking

        Returns:
            Prediction ID for matching with outcome()
        """
        pred_id = f"{datetime.now().isoformat()}_{len(self._pending)}"
        self._pending.append({
            "id": pred_id,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "prediction": prediction,
            "ts": datetime.now().isoformat(),
        })
        return pred_id

    def outcome(self, correct: bool, prediction_id: str = None, weight: float = 1.0):
        """
        Record outcome for a prediction.

        Args:
            correct: Whether prediction was correct
            prediction_id: ID from record(). None = oldest pending (FIFO).
            weight: Partial credit 0-1. Use for probabilistic outcomes.
        """
        if not self._pending:
            raise ValueError("No pending predictions")

        if prediction_id:
            idx = next((i for i, p in enumerate(self._pending) if p["id"] == prediction_id), None)
            if idx is None:
                raise ValueError(f"Prediction {prediction_id} not found")
        else:
            idx = 0

        pred = self._pending.pop(idx)
        self._record_internal(pred["confidence"], correct, weight)

    def record_with_outcome(self, confidence: float, correct: bool, weight: float = 1.0):
        """Record prediction and outcome together. Use when outcome is known immediately."""
        self._record_internal(confidence, correct, weight)

    def _record_internal(self, confidence: float, correct: bool, weight: float):
        conf = max(0.0, min(1.0, float(confidence)))
        key = self._key(conf)
        b = self._data[key]
        b.count += 1
        b.confidence_sum += conf
        b.correct += weight if correct else 0
        self._save()

    def calibrate(self, confidence: float) -> Tuple[float, Optional[str]]:
        """
        Apply calibration correction.

        Args:
            confidence: Raw confidence 0-1

        Returns:
            (corrected_confidence, explanation or None)
        """
        conf = max(0.0, min(1.0, float(confidence)))
        key = self._key(conf)
        b = self._data.get(key)

        if not b or b.count < self.min_samples or b.mean_confidence < 0.01:
            return conf, None

        factor = b.accuracy / b.mean_confidence
        factor = max(0.5, min(1.5, factor))
        corrected = max(0.0, min(1.0, conf * factor))

        if abs(factor - 1.0) > 0.05:
            direction = "overconfident" if factor < 1 else "underconfident"
            info = f"{direction}: {b.mean_confidence:.0%} conf → {b.accuracy:.0%} acc (n={b.count}), adjusted to {corrected:.0%}"
            return corrected, info

        return corrected, None

    def check(self, min_per_bin: int = 10, error_threshold: float = 0.15) -> CalibrationReport:
        """
        Check calibration health.

        Args:
            min_per_bin: Minimum samples per bin to include
            error_threshold: Calibration error threshold for flagging issues
        """
        issues = []
        bins_report = {}
        factors = {}

        for key, b in self._data.items():
            if b.count < min_per_bin:
                continue

            bins_report[key] = {
                "count": b.count,
                "accuracy": round(b.accuracy, 3),
                "expected": round(b.mean_confidence, 3),
                "error": round(b.error, 3),
            }

            if b.mean_confidence > 0.01:
                f = b.accuracy / b.mean_confidence
                factors[key] = round(max(0.5, min(1.5, f)), 3)

            if b.error > error_threshold:
                direction = "overconfident" if b.accuracy < b.mean_confidence else "underconfident"
                issues.append(f"{key}: {direction} by {b.error:.0%}")

        return CalibrationReport(
            calibrated=len(issues) == 0,
            total=sum(b.count for b in self._data.values()),
            issues=issues,
            bins=bins_report,
            correction_factors=factors,
        )

    def reset(self):
        """Clear all data."""
        self._data.clear()
        self._pending.clear()
        self._save()

    def _save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "bins": {k: v.to_dict() for k, v in self._data.items()},
            "pending": self._pending,
            "updated": datetime.now().isoformat(),
        }
        self.path.write_text(json.dumps(state, indent=2))

    def _load(self):
        if not self.path or not self.path.exists():
            return
        state = json.loads(self.path.read_text())
        for k, v in state.get("bins", {}).items():
            self._data[k] = Bin.from_dict(v)
        self._pending = state.get("pending", [])
