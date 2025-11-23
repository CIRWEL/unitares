"""
UNITARES Governance Core - Dynamics Engine

Canonical implementation of UNITARES Phase-3 thermodynamic dynamics.

This module contains the differential equations that govern the evolution
of the UNITARES state (E, I, S, V). This is the single source of truth
for all dynamics computations.

Mathematical Framework:
    dE/dt = α(I - E) - βE·S + γE·‖Δη‖²
    dI/dt = -k·S + βI·C(V,Θ) - γI·I·(1-I)
    dS/dt = -μ·S + λ₁(Θ)·‖Δη‖² - λ₂(Θ)·C(V,Θ) + noise
    dV/dt = κ(E - I) - δ·V

where:
    E: Energy (exploration/productive capacity) [0,1]
    I: Information integrity [0,1]
    S: Semantic uncertainty [0,2]
    V: Void integral (E-I imbalance, like free energy) [-2,2]
    C(V,Θ): Coherence function
    ‖Δη‖: Ethical drift norm
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from .parameters import DynamicsParams, Theta
from .utils import clip, drift_norm
from .coherence import coherence, lambda1, lambda2


@dataclass
class State:
    """
    UNITARES Thermodynamic State

    Represents the four core state variables of the UNITARES system.

    Attributes:
        E: Energy (exploration/productive capacity) [0, 1]
        I: Information integrity [0, 1]
        S: Semantic uncertainty / disorder [0, 2]
        V: Void integral (E-I imbalance, like free energy) [-2, 2]
    """
    E: float
    I: float
    S: float
    V: float

    def to_dict(self) -> dict:
        """Convert state to dictionary"""
        return {
            'E': self.E,
            'I': self.I,
            'S': self.S,
            'V': self.V,
        }


# Default initial state
DEFAULT_STATE = State(E=0.7, I=0.8, S=0.2, V=0.0)


def compute_dynamics(
    state: State,
    delta_eta: List[float],
    theta: Theta,
    params: DynamicsParams,
    dt: float = 0.1,
    noise_S: float = 0.0,
) -> State:
    """
    Compute one time step of UNITARES Phase-3 dynamics.

    This is the canonical dynamics implementation. Both the production
    UNITARES system and the research unitaires system should use this
    function for state evolution.

    Args:
        state: Current UNITARES state (E, I, S, V)
        delta_eta: Ethical drift vector (list of floats)
        theta: Control parameters (C1, eta1)
        params: Dynamics parameters (alpha, beta, etc.)
        dt: Time step for integration
        noise_S: Optional noise term for S dynamics

    Returns:
        New state after dt time evolution

    Mathematical Details:
        The dynamics implement a thermodynamic model where:
        - E and I are coupled resources that flow toward balance
        - S represents disorder/uncertainty that decays and is driven by drift
        - V accumulates E-I imbalance and creates feedback via coherence
        - Coherence C(V,Θ) acts as a stabilizing feedback mechanism

    Implementation Notes:
        - All state variables are clipped to their physical bounds
        - Drift norm ‖Δη‖ is computed once and squared for efficiency
        - Coherence is computed via the coherence module
        - Lambda functions λ₁, λ₂ are Theta-dependent
    """
    # Compute derived quantities
    d_eta = drift_norm(delta_eta)
    d_eta_sq = d_eta * d_eta

    # Compute coherence (depends on V and Theta)
    C = coherence(state.V, theta, params)

    # Compute adaptive lambda values
    lam1 = lambda1(theta, params)
    lam2 = lambda2(theta, params)

    # Extract current state
    E, I, S, V = state.E, state.I, state.S, state.V

    # Compute derivatives
    # E dynamics: coupling to I, damping by S, drift feedback
    dE_dt = (
        params.alpha * (I - E)           # I → E flow
        - params.beta_E * S              # S damping
        + params.gamma_E * d_eta_sq      # Drift feedback
    )

    # I dynamics: S coupling, coherence boost, self-regulation
    dI_dt = (
        -params.k * S                    # S → I coupling
        + params.beta_I * C              # Coherence boost
        - params.gamma_I * I * (1 - I)   # Logistic self-regulation
    )

    # S dynamics: decay, drift drive, coherence reduction, noise
    dS_dt = (
        -params.mu * S                   # Natural decay
        + lam1 * d_eta_sq                # Drift increases uncertainty
        - lam2 * C                       # Coherence reduces uncertainty
        + noise_S                        # Optional noise term
    )

    # V dynamics: E-I imbalance accumulation with decay
    dV_dt = (
        params.kappa * (E - I)           # Accumulate E-I imbalance
        - params.delta * V               # Decay toward zero
    )

    # Euler integration with clipping to physical bounds
    E_new = clip(E + dE_dt * dt, params.E_min, params.E_max)
    I_new = clip(I + dI_dt * dt, params.I_min, params.I_max)
    S_new = clip(S + dS_dt * dt, params.S_min, params.S_max)
    V_new = clip(V + dV_dt * dt, params.V_min, params.V_max)

    return State(E=E_new, I=I_new, S=S_new, V=V_new)


def step_state(
    state: State,
    theta: Theta,
    delta_eta: List[float],
    dt: float,
    noise_S: float = 0.0,
    params: Optional[DynamicsParams] = None,
) -> State:
    """
    Convenience wrapper for compute_dynamics with default params.

    This function maintains API compatibility with the original
    unitaires_core.step_state() function.

    Args:
        state: Current state
        theta: Control parameters
        delta_eta: Ethical drift vector
        dt: Time step
        noise_S: Optional noise for S
        params: Optional parameters (uses DEFAULT_PARAMS if None)

    Returns:
        New state after dt
    """
    from .parameters import DEFAULT_PARAMS

    if params is None:
        params = DEFAULT_PARAMS

    return compute_dynamics(
        state=state,
        delta_eta=delta_eta,
        theta=theta,
        params=params,
        dt=dt,
        noise_S=noise_S,
    )
