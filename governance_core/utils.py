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


def barrier(x: float, lo: float, hi: float, strength: float, margin: float) -> float:
    """
    Smooth repulsive force near state boundaries. C² continuous.

    Returns a force that pushes x away from [lo] and [hi] when within
    [margin] of either bound. Uses cubic onset for C² smoothness at the
    margin edge (value, first, and second derivatives are zero at onset).

    Args:
        x: Current value
        lo: Lower bound
        hi: Upper bound
        strength: Maximum repulsion force at the boundary
        margin: Distance from bound where barrier activates

    Returns:
        Repulsive force (positive pushes up, negative pushes down)
    """
    force = 0.0
    dist_lo = x - lo
    if dist_lo < margin:
        t = 1.0 - dist_lo / margin  # 1 at boundary, 0 at margin edge
        force += strength * t * t * t
    dist_hi = hi - x
    if dist_hi < margin:
        t = 1.0 - dist_hi / margin
        force -= strength * t * t * t
    return force


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
