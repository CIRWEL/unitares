"""
UNITARES Governance Core - Mathematical Foundation

This module contains the canonical implementation of UNITARES Phase-3
thermodynamic dynamics. Both the production UNITARES system and the
research unitaires system use this as their mathematical foundation.

Version: 2.0
Date: November 22, 2025
Status: Active
"""

from .dynamics import (
    State,
    DynamicsParams,
    compute_dynamics,
    step_state,
    compute_saturation_diagnostics,
)

from .coherence import (
    coherence,
    lambda1,
    lambda2,
)

from .scoring import (
    phi_objective,
    verdict_from_phi,
)

from .parameters import (
    Theta,
    Weights,
    DEFAULT_PARAMS,
    DEFAULT_WEIGHTS,
    DEFAULT_THETA,
    get_i_dynamics_mode,
    get_integrator_mode,
)

from .dynamics import DEFAULT_STATE

from .utils import (
    clip,
    drift_norm,
)

from .ethical_drift import (
    EthicalDriftVector,
    AgentBaseline,
    compute_ethical_drift,
    get_agent_baseline,
    clear_baseline,
    get_all_baselines,
    set_agent_baseline,
    get_baseline_or_none,
)

from .adaptive_governor import (
    AdaptiveGovernor,
    GovernorConfig,
    GovernorState,
    Verdict,
)

from .phase_aware import (
    Phase,
    detect_phase,
    get_phase_aware_thresholds,
)

from .research import (
    approximate_stability_check,
    suggest_theta_update,
)

from .stability import (
    compute_jacobian,
    verify_lyapunov_stability,
    gershgorin_stability_bound,
    sweep_stability,
    optimize_stability_metric,
)

__all__ = [
    # Core state and dynamics
    'State',
    'DynamicsParams',
    'compute_dynamics',
    'step_state',
    'compute_saturation_diagnostics',

    # Coherence functions
    'coherence',
    'lambda1',
    'lambda2',

    # Scoring functions
    'phi_objective',
    'verdict_from_phi',

    # Parameters
    'Theta',
    'Weights',
    'DEFAULT_PARAMS',
    'DEFAULT_WEIGHTS',
    'DEFAULT_THETA',
    'DEFAULT_STATE',
    'get_i_dynamics_mode',
    'get_integrator_mode',

    # Utilities
    'clip',
    'drift_norm',

    # Ethical Drift (concrete Δη)
    'EthicalDriftVector',
    'AgentBaseline',
    'compute_ethical_drift',
    'get_agent_baseline',
    'clear_baseline',
    'get_all_baselines',
    'set_agent_baseline',
    'get_baseline_or_none',

    # Phase-Aware
    'Phase',
    'detect_phase',
    'get_phase_aware_thresholds',

    # CIRS v2 Adaptive Governor
    'AdaptiveGovernor',
    'GovernorConfig',
    'GovernorState',
    'Verdict',

    # Research tools
    'approximate_stability_check',
    'suggest_theta_update',

    # Stability verification (Lyapunov)
    'compute_jacobian',
    'verify_lyapunov_stability',
    'gershgorin_stability_bound',
    'sweep_stability',
    'optimize_stability_metric',
]

__version__ = '2.5.0'  # Lyapunov stability verification
