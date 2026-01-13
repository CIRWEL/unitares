"""
UNITARES Governance Core - Scoring Functions

Objective function Φ (phi) for evaluating governance quality.

Mathematical Definition:
    Φ = wE·E - wI·(1-I) - wS·S - wV·|V| - wEta·‖Δη‖²

Interpretation:
    - Positive Φ → good governance state
    - Negative Φ → problematic state
    - Φ balances multiple competing objectives

Verdict Thresholds:
    Φ ≥ 0.3  → "safe"
    Φ ≥ 0.0  → "caution"
    Φ < 0.0  → "high-risk"
"""

from typing import List
from .dynamics import State
from .parameters import Weights, DEFAULT_WEIGHTS
from .utils import drift_norm


def phi_objective(
    state: State,
    delta_eta: List[float],
    weights: Weights = DEFAULT_WEIGHTS,
) -> float:
    """
    Compute UNITARES objective function Φ.

    Φ = wE·E - wI·(1-I) - wS·S - wV·|V| - wEta·‖Δη‖²

    Args:
        state: Current UNITARES state (E, I, S, V)
        delta_eta: Ethical drift vector
        weights: Objective weights (wE, wI, wS, wV, wEta)

    Returns:
        Φ score (higher is better)

    Interpretation:
        - Φ rewards high E (energy/exploration capacity)
        - Φ rewards high I (information integrity)
        - Φ penalizes high S (semantic uncertainty)
        - Φ penalizes high |V| (E-I imbalance)
        - Φ penalizes high ‖Δη‖ (ethical drift)

    Notes:
        - This function is used primarily in research/optimization
        - Production UNITARES uses coherence-based decision making
        - Could be integrated into production for multi-objective control
    """
    d_eta = drift_norm(delta_eta)

    phi = (
        weights.wE * state.E                    # Reward energy/exploration capacity
        - weights.wI * (1.0 - state.I)          # Reward information integrity
        - weights.wS * state.S                  # Penalize uncertainty
        - weights.wV * abs(state.V)             # Penalize imbalance
        - weights.wEta * d_eta * d_eta          # Penalize drift
    )

    return phi


def verdict_from_phi(phi: float, safe_threshold: float = 0.15, caution_threshold: float = 0.0) -> str:
    """
    Convert Φ score to verdict category.

    Thresholds (configurable):
        Φ ≥ safe_threshold (default 0.15)  → "safe"
        Φ ≥ caution_threshold (default 0.0) → "caution"
        Φ < caution_threshold              → "high-risk"

    Args:
        phi: Φ objective score
        safe_threshold: Threshold for "safe" verdict (default 0.15, recalibrated Dec 2025)
        caution_threshold: Threshold for "caution" verdict (default 0.0)

    Returns:
        Verdict string: "safe", "caution", or "high-risk"

    Notes:
        - These thresholds are heuristic and tunable
        - "safe" suggests proceeding normally
        - "caution" suggests proceeding with safeguards
        - "high-risk" suggests human review or rejection
        - Default 0.15 matches typical healthy state (E=0.7, I=0.8, S=0.2)
    """
    if phi >= safe_threshold:
        return "safe"
    elif phi >= caution_threshold:
        return "caution"
    else:
        return "high-risk"
