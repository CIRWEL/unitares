"""
Drift detection - monitors for calibration changes over time.

Answers: "Is my system getting worse?"
"""

from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from collections import deque

__all__ = ["DriftDetector", "DriftReport"]


@dataclass
class Sample:
    ts: str
    confidence: float
    correct: bool
    error: float = 0.0

    def to_dict(self) -> Dict:
        return {"ts": self.ts, "confidence": self.confidence, "correct": self.correct, "error": self.error}

    @classmethod
    def from_dict(cls, d: Dict) -> "Sample":
        return cls(d["ts"], d["confidence"], d["correct"], d.get("error", 0))


@dataclass
class DriftReport:
    drifting: bool
    drift_type: Optional[str]  # "accuracy", "calibration", "confidence", "oscillation"
    direction: Optional[str]   # "improving", "degrading", "unstable"
    severity: float
    recommendation: str
    details: Dict


class DriftDetector:
    """
    Monitors for drift in prediction quality.

    Example:
        drift = DriftDetector()

        for pred in stream:
            drift.record(pred.confidence, pred.was_correct)

        report = drift.check()
        if report.drifting:
            print(f"Alert: {report.drift_type} - {report.recommendation}")
    """

    def __init__(
        self,
        window: int = 100,
        threshold: float = 0.1,
        path: Optional[str | Path] = None,
    ):
        """
        Args:
            window: Samples to track
            threshold: Minimum change to flag as drift
            path: File for persistence. None = memory only.
        """
        self.window = window
        self.threshold = threshold
        self.path = Path(path) if path else None
        self._samples: deque = deque(maxlen=window)

        if self.path and self.path.exists():
            self._load()

    def record(self, confidence: float, correct: bool):
        """Record a prediction outcome."""
        self._samples.append(Sample(
            ts=datetime.now().isoformat(),
            confidence=float(confidence),
            correct=bool(correct),
            error=abs(confidence - (1.0 if correct else 0.0)),
        ))
        self._save()

    def check(self) -> DriftReport:
        """Analyze for drift."""
        samples = list(self._samples)
        min_needed = 20

        if len(samples) < min_needed:
            return DriftReport(
                drifting=False, drift_type=None, direction=None, severity=0.0,
                recommendation=f"Need {min_needed} samples, have {len(samples)}",
                details={},
            )

        mid = len(samples) // 2
        early = self._metrics(samples[:mid])
        recent = self._metrics(samples[mid:])

        drift_type, direction, severity = None, None, 0.0
        details = {"early": early, "recent": recent}

        # Check accuracy drift
        acc_delta = recent["accuracy"] - early["accuracy"]
        if abs(acc_delta) > self.threshold:
            drift_type = "accuracy"
            severity = abs(acc_delta)
            direction = "improving" if acc_delta > 0 else "degrading"

        # Check calibration error drift
        cal_delta = recent["error"] - early["error"]
        if abs(cal_delta) > self.threshold and abs(cal_delta) > severity:
            drift_type = "calibration"
            severity = abs(cal_delta)
            direction = "improving" if cal_delta < 0 else "degrading"

        # Check oscillation
        osc = self._oscillation(samples)
        if osc > 0.5 and osc > severity:
            drift_type = "oscillation"
            severity = osc
            direction = "unstable"

        rec = self._recommendation(drift_type, direction, severity)

        return DriftReport(
            drifting=drift_type is not None,
            drift_type=drift_type,
            direction=direction,
            severity=round(severity, 3),
            recommendation=rec,
            details=details,
        )

    def trend(self, window: int = 10) -> List[Tuple[str, float]]:
        """Get accuracy trend for plotting. Returns [(timestamp, accuracy), ...]"""
        samples = list(self._samples)
        if len(samples) < window:
            return []
        result = []
        for i in range(window, len(samples) + 1):
            w = samples[i - window:i]
            acc = sum(1 for s in w if s.correct) / len(w)
            result.append((w[-1].ts, round(acc, 3)))
        return result

    def _metrics(self, samples: List[Sample]) -> Dict:
        if not samples:
            return {"count": 0, "accuracy": 0, "confidence": 0, "error": 0}
        correct = sum(1 for s in samples if s.correct)
        return {
            "count": len(samples),
            "accuracy": round(correct / len(samples), 3),
            "confidence": round(sum(s.confidence for s in samples) / len(samples), 3),
            "error": round(sum(s.error for s in samples) / len(samples), 3),
        }

    def _oscillation(self, samples: List[Sample]) -> float:
        """Detect flip-flopping. Returns oscillation rate 0-1."""
        if len(samples) < 10:
            return 0.0
        w = max(5, len(samples) // 10)
        accs = [sum(1 for s in samples[i:i+w] if s.correct) / w for i in range(len(samples) - w + 1)]
        if len(accs) < 3:
            return 0.0
        changes = sum(1 for i in range(2, len(accs)) if (accs[i] - accs[i-1]) * (accs[i-1] - accs[i-2]) < 0)
        return changes / (len(accs) - 2)

    def _recommendation(self, dtype: str, direction: str, severity: float) -> str:
        if not dtype:
            return "Stable. No drift detected."
        msgs = {
            ("accuracy", "degrading"): "Accuracy declining. Check for distribution shift.",
            ("accuracy", "improving"): "Accuracy improving. Current approach working.",
            ("calibration", "degrading"): "Calibration degrading. Consider recalibration.",
            ("calibration", "improving"): "Calibration improving.",
            ("oscillation", "unstable"): "Unstable. Check for feedback loops.",
        }
        msg = msgs.get((dtype, direction), f"{dtype} drift ({direction})")
        return f"URGENT: {msg}" if severity > 0.2 else msg

    def _save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "samples": [s.to_dict() for s in self._samples],
            "updated": datetime.now().isoformat(),
        }))

    def _load(self):
        if not self.path or not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        for s in data.get("samples", []):
            self._samples.append(Sample.from_dict(s))
