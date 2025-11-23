"""
UNITARES Governance Core - Coherence Functions

Coherence is a key feedback mechanism in UNITARES that stabilizes
the system. It depends on the void integral V and control parameters Θ.

Mathematical Definition:
    C(V, Θ) = Cmax · 0.5 · (1 + tanh(Θ.C₁ · V))

    λ₁(Θ) = Θ.η₁ · λ₁_base
    λ₂(Θ) = λ₂_base

Physical Interpretation:
    - C(V, Θ) ∈ [0, Cmax] represents system coherence
    - When V → -∞: C → 0 (incoherent, I >> E)
    - When V → +∞: C → Cmax (coherent, E >> I)
    - Θ.C₁ controls the steepness of the transition
    - Θ.η₁ controls sensitivity to ethical drift
"""

import math
from .parameters import DynamicsParams, Theta


def coherence(V: float, theta: Theta, params: DynamicsParams) -> float:
    """
    Compute UNITARES coherence function.

    C(V, Θ) = Cmax · 0.5 · (1 + tanh(Θ.C₁ · V))

    Args:
        V: Void integral (E-I imbalance accumulator)
        theta: Control parameters (C1, eta1)
        params: Dynamics parameters (for Cmax)

    Returns:
        Coherence value in [0, Cmax]

    Notes:
        - Coherence acts as a stabilizing feedback
        - Higher V (E > I) → higher coherence
        - Lower V (I > E) → lower coherence
        - C1 parameter controls transition steepness
    """
    return params.Cmax * 0.5 * (1.0 + math.tanh(theta.C1 * V))


def lambda1(theta: Theta, params: DynamicsParams) -> float:
    """
    Compute λ₁ adaptive parameter.

    λ₁(Θ) = Θ.η₁ · λ₁_base

    This parameter controls how much ethical drift increases
    semantic uncertainty S.

    Args:
        theta: Control parameters
        params: Dynamics parameters (for lambda1_base)

    Returns:
        λ₁ value (drift → S coupling strength)

    Notes:
        - Higher η₁ → more sensitive to drift
        - This can be tuned/optimized via Θ
    """
    return theta.eta1 * params.lambda1_base


def lambda2(theta: Theta, params: DynamicsParams) -> float:
    """
    Compute λ₂ parameter.

    λ₂(Θ) = λ₂_base

    This parameter controls how much coherence reduces
    semantic uncertainty S.

    Args:
        theta: Control parameters (unused in current implementation)
        params: Dynamics parameters (for lambda2_base)

    Returns:
        λ₂ value (coherence → S reduction strength)

    Notes:
        - Currently not Theta-dependent
        - Could be extended to λ₂(Θ) = θ.η₂ · λ₂_base
    """
    return params.lambda2_base
