"""
UNITARES Research Server - unitaires_core

This module provides a research interface to UNITARES Phase-3 dynamics.
As of v2.0, core dynamics are delegated to governance_core (canonical implementation).

This module maintains backward compatibility while using governance_core
as the mathematical foundation.

Version: 2.0 (Migrated to governance_core)
Date: November 22, 2025
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
import math, random
import warnings
import sys
from pathlib import Path

# Import governance_core (canonical implementation)
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from governance_core import (
    State, Theta, Weights, DynamicsParams,
    DEFAULT_STATE, DEFAULT_THETA, DEFAULT_WEIGHTS, DEFAULT_PARAMS,
    step_state as core_step_state,
    coherence as core_coherence,
    lambda1 as core_lambda1,
    lambda2 as core_lambda2,
    phi_objective as core_phi_objective,
    verdict_from_phi as core_verdict_from_phi,
    clip, drift_norm,
)

# Backward compatibility: Params is an alias for DynamicsParams
Params = DynamicsParams

# Re-export for backward compatibility (maintain existing API)
# These aliases ensure existing code using DEFAULT_PARAMS etc. continues to work
DEFAULT_PARAMS = DEFAULT_PARAMS  # Already imported from governance_core
DEFAULT_WEIGHTS = DEFAULT_WEIGHTS  # Already imported from governance_core
DEFAULT_THETA = DEFAULT_THETA  # Already imported from governance_core
DEFAULT_STATE = DEFAULT_STATE  # Already imported from governance_core

# Core functions now delegate to governance_core
def coherence(V: float, theta: Theta, params: Params = DEFAULT_PARAMS) -> float:
    """
    Coherence function C(V, Θ) - delegates to governance_core.
    
    Note: This function now uses governance_core.coherence() internally.
    """
    return core_coherence(V, theta, params)

def lambda1(theta: Theta, params: Params = DEFAULT_PARAMS) -> float:
    """
    Lambda1 function - delegates to governance_core.
    
    Note: This function now uses governance_core.lambda1() internally.
    """
    return core_lambda1(theta, params)

def lambda2(theta: Theta, params: Params = DEFAULT_PARAMS) -> float:
    """
    Lambda2 function - delegates to governance_core.
    
    Note: This function now uses governance_core.lambda2() internally.
    """
    return core_lambda2(theta, params)

def step_state(state: State, theta: Theta, delta_eta: List[float], dt: float,
               noise_S: float = 0.0, params: Params = DEFAULT_PARAMS) -> State:
    """
    Step state forward by dt - delegates to governance_core.
    
    Note: This function now uses governance_core.step_state() internally.
    Core dynamics are computed by governance_core (canonical implementation).
    """
    return core_step_state(
        state=state,
        theta=theta,
        delta_eta=delta_eta,
        dt=dt,
        noise_S=noise_S,
        params=params
    )

def phi_objective(state: State, delta_eta: List[float],
                  weights: Weights = DEFAULT_WEIGHTS) -> float:
    """
    Compute phi objective function - delegates to governance_core.
    
    Note: This function now uses governance_core.phi_objective() internally.
    """
    return core_phi_objective(state, delta_eta, weights)

def verdict_from_phi(phi: float) -> str:
    """
    Convert phi to verdict - delegates to governance_core.
    
    Note: This function now uses governance_core.verdict_from_phi() internally.
    """
    return core_verdict_from_phi(phi)

def score_state(context_summary: str, state: State, delta_eta: List[float],
                weights: Optional[Weights] = None) -> Dict:
    """
    Score state with context summary - research tool.
    
    Uses governance_core.phi_objective() and governance_core.verdict_from_phi()
    for core computations.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    phi = phi_objective(state, delta_eta, weights)  # Uses governance_core internally
    verdict = verdict_from_phi(phi)  # Uses governance_core internally
    d_eta = drift_norm(delta_eta)
    explanation_parts = [
        f"Context: {context_summary}",
        f"Φ = {phi:.3f} → verdict: {verdict}",
        f"E={state.E:.3f}, I={state.I:.3f}, S={state.S:.3f}, V={state.V:.3f}, ‖Δη‖={d_eta:.3f}"
    ]
    if verdict == "high-risk":
        explanation_parts.append("High-risk: consider safer alternatives or human review.")
    elif verdict == "caution":
        explanation_parts.append("Caution: proceed only with safeguards and narrow scope.")
    else:
        explanation_parts.append("Safe under current UNITARES model assumptions.")
    return {
        "phi": phi,
        "verdict": verdict,
        "explanation": " ".join(explanation_parts),
        "components": {
            "E": state.E,
            "I": state.I,
            "S": state.S,
            "V": state.V,
            "delta_eta_norm": d_eta,
        },
    }

def approximate_stability_check(theta: Theta, params: Params = DEFAULT_PARAMS,
                                samples: int = 200, steps_per_sample: int = 20,
                                dt: float = 0.05) -> Dict:
    """
    Approximate stability check - research tool.
    
    Uses governance_core.step_state() for state evolution.
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
            s = step_state(s, theta, delta_eta, dt=dt, noise_S=noise_S, params=params)  # Uses governance_core
            if not (params.E_min <= s.E <= params.E_max and
                    params.I_min <= s.I <= params.I_max and
                    params.S_min <= s.S <= params.S_max and
                    params.V_min <= s.V <= params.V_max):
                ok = False
                break
        if not ok:
            violations += 1
    violation_rate = violations / max(1, samples)
    stable = violation_rate < 0.05
    alpha_estimate = 0.1 if stable else 0.0
    notes = (f"Approximate stability with {samples} samples, "
             f"violation rate={violation_rate:.3f}.")
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

def project_theta(theta: Theta, params: Params = DEFAULT_PARAMS) -> Theta:
    """
    Project theta to valid bounds - research tool.
    
    Uses governance_core.clip() utility.
    """
    return Theta(
        C1=clip(theta.C1, params.C1_min, params.C1_max),  # Uses governance_core
        eta1=clip(theta.eta1, params.eta1_min, params.eta1_max),  # Uses governance_core
    )

def suggest_theta_update(theta: Theta, state: State, horizon: float, step: float,
                         params: Params = DEFAULT_PARAMS,
                         weights: Weights = DEFAULT_WEIGHTS) -> Dict:
    """
    Suggest theta update via gradient estimation - research tool.
    
    Uses governance_core.step_state() and governance_core.phi_objective()
    for simulations.
    """
    def simulate_with_theta(theta_local: Theta) -> float:
        s = State(**asdict(state))
        T = max(horizon, step)
        dt = min(0.05, T / 20.0)
        t = 0.0
        phis = []
        while t < T:
            delta_eta = [0.1, 0.0, 0.0]
            s = step_state(s, theta_local, delta_eta, dt=dt, params=params)  # Uses governance_core
            phis.append(phi_objective(s, delta_eta, weights))  # Uses governance_core
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
    theta_new = project_theta(theta_new, params)  # Uses governance_core.clip()
    rationale = ("θ updated via antithetic finite differences on Φ over "
                 f"horizon={horizon}. dΦ/dC1={grad_C1:.4f}, dΦ/deta1={grad_eta1:.4f}.")
    return {
        "theta_new": asdict(theta_new),
        "gradient": [grad_C1, grad_eta1],
        "rationale": rationale,
    }
