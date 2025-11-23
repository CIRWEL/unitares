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
)

from .dynamics import DEFAULT_STATE

from .utils import (
    clip,
    drift_norm,
)

__all__ = [
    # Core state and dynamics
    'State',
    'DynamicsParams',
    'compute_dynamics',
    'step_state',

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

    # Utilities
    'clip',
    'drift_norm',
]

__version__ = '2.0.0'
