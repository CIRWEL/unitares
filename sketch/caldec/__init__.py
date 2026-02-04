"""
caldec - Calibrated Decisions

Confidence calibration for systems that make repeated predictions.

Quick start:
    from caldec import Calibrator

    cal = Calibrator()
    cal.record_with_outcome(confidence=0.9, correct=True)
    cal.record_with_outcome(confidence=0.9, correct=False)

    adjusted = cal.calibrate(0.9)  # Returns corrected confidence
    report = cal.check()           # Returns calibration health
"""

from .calibrator import Calibrator
from .drift import DriftDetector
from .outcomes import evaluate, Evaluator

__version__ = "0.1.0"
__all__ = ["Calibrator", "DriftDetector", "evaluate", "Evaluator"]
