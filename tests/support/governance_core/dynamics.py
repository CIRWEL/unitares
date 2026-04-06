"""
Stub `governance_core.dynamics` — ODE + barriers aligned with
`scripts/analysis/contraction_analysis.py` Jacobian comments.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Sequence

import numpy as np

from .coherence import coherence, lambda2
from .parameters import DynamicsParams, Theta, get_i_dynamics_mode
from .utils import drift_norm

if TYPE_CHECKING:
    pass


@dataclass
class State:
    E: float
    I: float
    S: float
    V: float


DEFAULT_STATE = State(E=0.7, I=0.8, S=0.2, V=0.0)


def _barrier_term(x: float, lo: float, hi: float, strength: float, margin: float) -> float:
    """Scalar barrier push — matches contraction_analysis._barrier_derivative as d/dx of this sum."""
    term = 0.0
    dist_lo = x - lo
    if dist_lo < margin:
        t = 1.0 - dist_lo / margin
        term += strength * (t ** 3)
    dist_hi = hi - x
    if dist_hi < margin:
        t = 1.0 - dist_hi / margin
        term -= strength * (t ** 3)
    return float(term)


def _derivatives(
    state: State,
    d_eta_sq: float,
    theta: Theta,
    params: DynamicsParams,
    noise_S: float,
    complexity: float,
    sensor_eisv: Optional[State],
) -> List[float]:
    E, I, S, V = state.E, state.I, state.S, state.V
    C = coherence(V, theta, params)
    lam2_val = lambda2(theta, params)
    m = params.barrier_margin
    s = params.barrier_strength
    S_range = params.S_max - params.S_min
    V_range = params.V_max - params.V_min

    bE = _barrier_term(E, params.E_min, params.E_max, s, m)
    bI = _barrier_term(I, params.I_min, params.I_max, s, m)
    bS = _barrier_term(S, params.S_min, params.S_max, s, m * S_range)
    bV = _barrier_term(V, params.V_min, params.V_max, s, m * V_range)

    stress_I = 0.12 * min(d_eta_sq, 2.0)
    stress_S = 0.08 * min(d_eta_sq, 2.0)

    dE = (
        params.alpha * (I - E)
        - params.beta_E * E * S
        + params.gamma_E * d_eta_sq
        + bE
    )
    i_mode = get_i_dynamics_mode()
    if i_mode == "linear":
        dI = params.beta_I * C - params.k * S - params.gamma_I * I - stress_I + bI
    else:
        dI = params.beta_I * C - params.k * S - params.gamma_I * I * (1.0 - I) - stress_I + bI

    dS = (
        -params.mu * S
        + params.lambda1 * d_eta_sq
        - lam2_val * C
        + params.beta_c * complexity
        + noise_S
        + stress_S
        + bS
    )
    dV = params.kappa * (E - I) - params.delta * V + bV

    if sensor_eisv is not None:
        k_sp = 0.05
        dE += k_sp * (sensor_eisv.E - E)
        dI += k_sp * (sensor_eisv.I - I)
        dS += k_sp * (sensor_eisv.S - S)
        dV += k_sp * (sensor_eisv.V - V)

    return [dE, dI, dS, dV]


def compute_dynamics(
    state: State,
    delta_eta: Sequence[float],
    theta: Theta,
    params: DynamicsParams,
    dt: float = 0.1,
    complexity: float = 0.5,
    noise_S: float = 0.0,
    sensor_eisv: Optional[State] = None,
) -> State:
    """One Euler step with clipping to valid bounds."""
    if delta_eta is None:
        delta_eta = []
    d_eta = drift_norm(delta_eta)
    d_eta_sq = d_eta * d_eta
    dE, dI, dS, dV = _derivatives(
        state, d_eta_sq, theta, params, noise_S, complexity, sensor_eisv
    )
    E = float(np.clip(state.E + dt * dE, params.E_min + 1e-6, params.E_max - 1e-6))
    I = float(np.clip(state.I + dt * dI, params.I_min + 1e-6, params.I_max - 1e-6))
    S = float(np.clip(state.S + dt * dS, params.S_min + 1e-6, params.S_max - 1e-6))
    V = float(np.clip(state.V + dt * dV, params.V_min + 1e-6, params.V_max - 1e-6))
    return State(E=E, I=I, S=S, V=V)


def compute_equilibrium(
    params: DynamicsParams,
    theta: Theta,
    complexity: float = 0.5,
) -> State:
    """Approximate fixed point (V≈0 linearization) — good enough for analysis tests."""
    # Solve I* from I equation with V=0, S from S equation, E from E equation
    C0 = coherence(0.0, theta, params)
    lam2_val = lambda2(theta, params)
    # dI/dt = beta_I*C0 - k*S - gamma_I*I = 0, dS/dt = -mu*S - lam2*C0 + beta_c*c = 0
    S_star = max(
        params.S_min + 1e-3,
        min(
            params.S_max - 1e-3,
            (-lam2_val * C0 + params.beta_c * complexity) / max(params.mu, 1e-6),
        ),
    )
    I_star = max(
        params.I_min + 1e-3,
        min(
            params.I_max - 1e-3,
            (params.beta_I * C0 - params.k * S_star) / max(params.gamma_I, 1e-6),
        ),
    )
    E_star = max(
        params.E_min + 1e-3,
        min(
            params.E_max - 1e-3,
            (params.alpha * I_star + params.gamma_E * 0.0) / max(params.alpha + params.beta_E * S_star, 1e-6),
        ),
    )
    V_star = max(
        params.V_min + 1e-3,
        min(
            params.V_max - 1e-3,
            params.kappa * (E_star - I_star) / max(params.delta, 1e-6),
        ),
    )
    # One refinement step using full dynamics at guessed point
    s = State(E=E_star, I=I_star, S=S_star, V=V_star)
    for _ in range(30):
        d = _derivatives(s, 0.0, theta, params, 0.0, complexity, None)
        if max(abs(x) for x in d) < 1e-8:
            break
        s = State(
            E=float(np.clip(s.E + 0.5 * d[0], params.E_min + 1e-6, params.E_max - 1e-6)),
            I=float(np.clip(s.I + 0.5 * d[1], params.I_min + 1e-6, params.I_max - 1e-6)),
            S=float(np.clip(s.S + 0.5 * d[2], params.S_min + 1e-6, params.S_max - 1e-6)),
            V=float(np.clip(s.V + 0.5 * d[3], params.V_min + 1e-6, params.V_max - 1e-6)),
        )
    return s


def check_basin(state: State) -> str:
    if state.I > 0.6:
        return "high"
    if state.I < 0.4:
        return "low"
    return "boundary"


def estimate_convergence(
    current: State,
    equilibrium: State,
    params: DynamicsParams,
) -> dict:
    d = math.sqrt(
        (current.E - equilibrium.E) ** 2
        + (current.I - equilibrium.I) ** 2
        + (current.S - equilibrium.S) ** 2
        + (current.V - equilibrium.V) ** 2
    )
    return {
        "distance": d,
        "converged": d < 0.05,
        "updates_to_convergence": int(max(1, min(500, d / 0.01))),
    }


