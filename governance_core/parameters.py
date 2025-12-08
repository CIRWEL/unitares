"""
UNITARES Governance Core - Parameter Definitions

Canonical parameter definitions for UNITARES Phase-3 dynamics.

This is the single source of truth for all parameter values,
bounds, and default configurations.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class DynamicsParams:
    """
    UNITARES Phase-3 Dynamics Parameters

    These parameters control the thermodynamic evolution of the
    governance state (E, I, S, V).

    Source: UNITARES Phase-3 specification
    """

    # E dynamics
    alpha: float = 0.4           # I → E coupling strength
    beta_E: float = 0.1          # S damping on E
    gamma_E: float = 0.0         # Drift feedback to E

    # I dynamics
    k: float = 0.1               # S → I coupling
    beta_I: float = 0.3          # Coherence boost to I
    gamma_I: float = 0.25        # I self-regulation

    # S dynamics
    mu: float = 0.8              # S decay rate
    lambda1_base: float = 0.3    # Drift → S coupling base
    lambda2_base: float = 0.05   # Coherence → S reduction base

    # V dynamics
    kappa: float = 0.3           # (E-I) → V coupling
    delta: float = 0.4           # V decay rate

    # Coherence parameters
    Cmax: float = 1.0            # Maximum coherence value
    coherence_scale: float = 1.0  # V scaling factor (1.0 = pure thermodynamic, no scaling)

    # State bounds
    E_min: float = 0.0
    E_max: float = 1.0
    I_min: float = 0.0
    I_max: float = 1.0
    S_min: float = 0.001  # Epistemic humility floor - prevents S=0.0 without external validation
    S_max: float = 2.0
    V_min: float = -2.0
    V_max: float = 2.0

    # Control parameter bounds (for Theta optimization)
    C1_min: float = 0.5
    C1_max: float = 1.5
    eta1_min: float = 0.1
    eta1_max: float = 0.5


@dataclass
class Theta:
    """
    UNITARES Control Parameters

    These parameters are tunable for optimization and adaptation.

    Attributes:
        C1: Coherence function control parameter (affects tanh steepness)
        eta1: Ethical drift sensitivity multiplier
    """
    C1: float
    eta1: float


@dataclass
class Weights:
    """
    Objective Function Weights

    Used in computing Φ (phi) governance score.

    Φ = wE·E - wI·(1-I) - wS·S - wV·|V| - wEta·‖Δη‖²
    """
    wE: float = 0.5      # Weight for energy/exploration capacity
    wI: float = 0.5      # Weight for information integrity
    wS: float = 0.5      # Weight for semantic uncertainty
    wV: float = 0.5      # Weight for void imbalance
    wEta: float = 0.5    # Weight for ethical drift


# Default configurations
DEFAULT_PARAMS: DynamicsParams = DynamicsParams()
DEFAULT_THETA: Theta = Theta(C1=1.0, eta1=0.3)
DEFAULT_WEIGHTS: Weights = Weights()

# Default initial state
# This is imported from dynamics.py to avoid circular imports
# See dynamics.py for State definition
