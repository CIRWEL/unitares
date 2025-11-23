"""
UNITARES Governance Core - Utility Functions

Helper functions for dynamics computations.
"""

from typing import List
import math


def clip(x: float, lo: float, hi: float) -> float:
    """
    Clip value to range [lo, hi].

    Args:
        x: Value to clip
        lo: Lower bound
        hi: Upper bound

    Returns:
        Clipped value in [lo, hi]
    """
    return max(lo, min(hi, x))


def drift_norm(delta_eta: List[float]) -> float:
    """
    Compute L2 norm of ethical drift vector.

    ‖Δη‖ = sqrt(Σ Δη_i²)

    Args:
        delta_eta: List of ethical drift components

    Returns:
        L2 norm of drift vector
    """
    if not delta_eta:
        return 0.0
    return math.sqrt(sum(d * d for d in delta_eta))
