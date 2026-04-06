"""
Test-only stub for the private `unitares-core` (`governance_core`) package.

Loaded from tests/conftest.py when the real wheel is not installed.
When `unitares-core` is present, that implementation is used unchanged.

**Do not import this from production code.**
"""

from __future__ import annotations

__unitares_stub__ = True

from typing import Any, Dict

from .adaptive_governor import AdaptiveGovernor, GovernorConfig, GovernorState
from .coherence import coherence, lambda1, lambda2
from .dynamics import (
    DEFAULT_STATE,
    State,
    compute_dynamics,
    compute_equilibrium,
    check_basin,
    estimate_convergence,
)
from .ethical_drift import (
    AgentBaseline,
    EthicalDriftVector,
    compute_ethical_drift,
    clear_baseline,
    get_agent_baseline,
    get_baseline_or_none,
    set_agent_baseline,
)
from .parameters import (
    DEFAULT_PARAMS,
    DEFAULT_THETA,
    DynamicsParams,
    Theta,
    V41_PARAMS,
    get_active_params,
    get_params_profile_name,
)
from .scoring import DEFAULT_WEIGHTS, phi_objective, verdict_from_phi
from .utils import drift_norm


def step_state(*args: Any, **kwargs: Any) -> State:
    """One-step dynamics — positional (behavioral_trajectory) or keyword (governance_monitor)."""
    if kwargs.get("state") is not None:
        state = kwargs["state"]
        theta = kwargs.get("theta", DEFAULT_THETA)
        delta_eta = kwargs.get("delta_eta", [0.0, 0.0, 0.0])
        dt = kwargs.get("dt", 0.1)
        noise_S = kwargs.get("noise_S", 0.0)
        params = kwargs.get("params", get_active_params())
        complexity = kwargs.get("complexity", 0.5)
        sensor_eisv = kwargs.get("sensor_eisv", None)
        return compute_dynamics(
            state,
            list(delta_eta) if delta_eta is not None else [0.0, 0.0, 0.0],
            theta,
            params,
            dt=dt,
            complexity=complexity,
            noise_S=noise_S,
            sensor_eisv=sensor_eisv,
        )
    if args and isinstance(args[0], State):
        state = args[0]
        theta = args[1] if len(args) > 1 else kwargs.get("theta", DEFAULT_THETA)
        delta_eta = kwargs.get("delta_eta", [0.0, 0.0, 0.0])
        dt = kwargs.get("dt", 0.1)
        noise_S = kwargs.get("noise_S", 0.0)
        params = kwargs.get("params", get_active_params())
        complexity = kwargs.get("complexity", 0.5)
        sensor_eisv = kwargs.get("sensor_eisv", None)
        return compute_dynamics(
            state,
            list(delta_eta) if delta_eta is not None else [0.0, 0.0, 0.0],
            theta,
            params,
            dt=dt,
            complexity=complexity,
            noise_S=noise_S,
            sensor_eisv=sensor_eisv,
        )
    raise TypeError("step_state: expected state=... kwargs or (State, Theta, ...)")


def approximate_stability_check(theta: Theta, dt: float = 0.1) -> Dict[str, Any]:
    return {
        "stable": True,
        "alpha_estimate": 0.1,
        "violations": [],
        "notes": "stub",
    }


def compute_saturation_diagnostics(state: State, theta: Theta) -> Dict[str, Any]:
    return {
        "sat_margin": -0.1,
        "dynamics_mode": "linear",
        "will_saturate": False,
        "at_boundary": False,
        "I_equilibrium_linear": 0.75,
        "A": 0.0,
    }


__all__ = [
    "State",
    "Theta",
    "DynamicsParams",
    "DEFAULT_STATE",
    "DEFAULT_THETA",
    "DEFAULT_PARAMS",
    "DEFAULT_WEIGHTS",
    "V41_PARAMS",
    "step_state",
    "coherence",
    "phi_objective",
    "verdict_from_phi",
    "compute_ethical_drift",
    "EthicalDriftVector",
    "AgentBaseline",
    "get_agent_baseline",
    "get_baseline_or_none",
    "set_agent_baseline",
    "clear_baseline",
    "approximate_stability_check",
    "compute_saturation_diagnostics",
    "AdaptiveGovernor",
    "GovernorConfig",
    "GovernorState",
]
