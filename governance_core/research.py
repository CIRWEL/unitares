"""
UNITARES Research Tools

Monte Carlo stability checking and gradient-based theta optimization.
These are research/analysis utilities, not core dynamics.

Migrated from src/unitaires-server/unitaires_core.py during cleanup.
"""

from __future__ import annotations
import random
from dataclasses import asdict
from typing import Dict

from .dynamics import State, DynamicsParams, step_state
from .parameters import Theta, Weights, DEFAULT_PARAMS, DEFAULT_WEIGHTS
from .scoring import phi_objective
from .utils import clip


def approximate_stability_check(
    theta: Theta,
    params: DynamicsParams = DEFAULT_PARAMS,
    samples: int = 200,
    steps_per_sample: int = 20,
    dt: float = 0.05,
) -> Dict:
    """
    Monte Carlo stability check — sample random initial conditions and
    verify the ODE stays within bounds.

    Returns dict with 'stable', 'alpha_estimate', 'violations', 'notes'.
    """
    violations = 0
    for _ in range(samples):
        s = State(
            E=random.uniform(params.E_min, params.E_max),
            I=random.uniform(params.I_min, params.I_max),
            S=random.uniform(params.S_min, params.S_max),
            V=random.uniform(params.V_min, params.V_max),
        )
        ok = True
        for _ in range(steps_per_sample):
            delta_eta = [random.uniform(-0.2, 0.2) for _ in range(3)]
            noise_S = random.uniform(-0.05, 0.05)
            s = step_state(s, theta, delta_eta, dt=dt, noise_S=noise_S, params=params)
            if not (
                params.E_min <= s.E <= params.E_max
                and params.I_min <= s.I <= params.I_max
                and params.S_min <= s.S <= params.S_max
                and params.V_min <= s.V <= params.V_max
            ):
                ok = False
                break
        if not ok:
            violations += 1

    violation_rate = violations / max(1, samples)
    stable = violation_rate < 0.05
    alpha_estimate = 0.1 if stable else 0.0
    notes = (
        f"Approximate stability with {samples} samples, "
        f"violation rate={violation_rate:.3f}."
    )
    if not stable:
        notes += " System appears marginal or unstable."
    else:
        notes += " System appears stable under tested conditions."
    return {
        "stable": stable,
        "alpha_estimate": alpha_estimate,
        "violations": violations,
        "notes": notes,
    }


def _project_theta(theta: Theta, params: DynamicsParams = DEFAULT_PARAMS) -> Theta:
    """Project theta to valid parameter bounds."""
    return Theta(
        C1=clip(theta.C1, params.C1_min, params.C1_max),
        eta1=clip(theta.eta1, params.eta1_min, params.eta1_max),
    )


def suggest_theta_update(
    theta: Theta,
    state: State,
    horizon: float,
    step: float,
    params: DynamicsParams = DEFAULT_PARAMS,
    weights: Weights = DEFAULT_WEIGHTS,
) -> Dict:
    """
    Suggest theta update via antithetic finite-difference gradient estimation.

    Simulates forward from `state` under perturbed theta values and returns
    the gradient direction that improves the Phi objective.
    """

    def simulate_with_theta(theta_local: Theta) -> float:
        s = State(**asdict(state))
        T = max(horizon, step)
        dt = min(0.05, T / 20.0)
        t = 0.0
        phis = []
        while t < T:
            delta_eta = [0.1, 0.0, 0.0]
            s = step_state(s, theta_local, delta_eta, dt=dt, params=params)
            phis.append(phi_objective(s, delta_eta, weights))
            t += dt
        return sum(phis) / max(1, len(phis))

    theta_p = Theta(C1=theta.C1 + step, eta1=theta.eta1)
    theta_m = Theta(C1=theta.C1 - step, eta1=theta.eta1)
    f_p, f_m = simulate_with_theta(theta_p), simulate_with_theta(theta_m)
    grad_C1 = (f_p - f_m) / (2.0 * step)

    theta_p = Theta(C1=theta.C1, eta1=theta.eta1 + step)
    theta_m = Theta(C1=theta.C1, eta1=theta.eta1 - step)
    f_p, f_m = simulate_with_theta(theta_p), simulate_with_theta(theta_m)
    grad_eta1 = (f_p - f_m) / (2.0 * step)

    eps = 0.1
    theta_new = Theta(
        C1=theta.C1 + eps * grad_C1,
        eta1=theta.eta1 + eps * grad_eta1,
    )
    theta_new = _project_theta(theta_new, params)
    rationale = (
        f"θ updated via antithetic finite differences on Φ over "
        f"horizon={horizon}. dΦ/dC1={grad_C1:.4f}, dΦ/deta1={grad_eta1:.4f}."
    )
    return {
        "theta_new": asdict(theta_new),
        "gradient": [grad_C1, grad_eta1],
        "rationale": rationale,
    }
