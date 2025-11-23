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


def verdict_from_phi(phi: float) -> str:
    """
    Convert Φ score to verdict category.

    Thresholds:
        Φ ≥ 0.3  → "safe"
        Φ ≥ 0.0  → "caution"
        Φ < 0.0  → "high-risk"

    Args:
        phi: Φ objective score

    Returns:
        Verdict string: "safe", "caution", or "high-risk"

    Notes:
        - These thresholds are heuristic and tunable
        - "safe" suggests proceeding normally
        - "caution" suggests proceeding with safeguards
        - "high-risk" suggests human review or rejection
    """
    if phi >= 0.3:
        return "safe"
    elif phi >= 0.0:
        return "caution"
    else:
        return "high-risk"
