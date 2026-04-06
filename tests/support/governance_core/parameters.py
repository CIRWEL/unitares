"""Stub `governance_core.parameters` — aligned with tests/test_unitares_v41.py expectations."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, Dict

# --- Theta / DynamicsParams ------------------------------------------------

@dataclass(frozen=True)
class Theta:
    C1: float = 3.0
    eta1: float = 0.3


@dataclass(frozen=True)
class DynamicsParams:
    alpha: float = 0.5
    beta_E: float = 0.3
    # Tuned so default trajectories stay in the “high” basin (see tests/test_eisv_behavioral.py)
    beta_I: float = 0.5
    gamma_E: float = 0.1
    gamma_I: float = 0.2
    k: float = 0.1
    mu: float = 0.5
    delta: float = 0.4
    kappa: float = 0.5
    lambda1: float = 0.15
    lambda2: float = 0.1
    Cmax: float = 1.0
    beta_c: float = 0.1
    E_min: float = 0.0
    E_max: float = 1.0
    I_min: float = 0.0
    I_max: float = 1.0
    S_min: float = 0.0
    S_max: float = 2.0
    V_min: float = -2.0
    V_max: float = 2.0
    barrier_margin: float = 0.05
    barrier_strength: float = 0.5
    C1_min: float = 1.0
    C1_max: float = 5.0
    eta1_min: float = 0.1
    eta1_max: float = 0.5


DEFAULT_THETA = Theta()
DEFAULT_PARAMS = DynamicsParams()

# Scoring weights — also exposed via governance_core.parameters in src
DEFAULT_WEIGHTS = {
    "E": 0.25,
    "I": 0.25,
    "S": 0.25,
    "V": 0.25,
}

# v4.1 bistability (test_unitares_v41)
V41_PARAMS = DynamicsParams(beta_I=0.05)

_I_DYNAMICS_MODE = "linear"


def get_i_dynamics_mode() -> str:
    return _I_DYNAMICS_MODE


def get_params_profile_name() -> str:
    return os.environ.get("UNITARES_PARAMS_PROFILE", "default")


def get_active_params() -> DynamicsParams:
    """Respect UNITARES_PARAMS_PROFILE and optional JSON overrides."""
    profile = os.environ.get("UNITARES_PARAMS_PROFILE", "default").lower()
    raw = os.environ.get("UNITARES_PARAMS_JSON", "").strip()
    base = V41_PARAMS if profile == "v41" else DEFAULT_PARAMS
    if not raw:
        return base
    try:
        import json
        overrides: Dict[str, Any] = json.loads(raw)
    except Exception:
        return base
    fields = {f.name for f in __import__("dataclasses").fields(DynamicsParams)}
    kwargs = {k: v for k, v in overrides.items() if k in fields}
    return replace(base, **kwargs)
