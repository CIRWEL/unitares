"""
UNITARES Governance Core - Dynamics Engine

Canonical implementation of UNITARES v5 thermodynamic dynamics.

This module contains the differential equations that govern the evolution
of the UNITARES state (E, I, S, V). This is the single source of truth
for all dynamics computations.

Mathematical Framework:
    dE/dt = α(I - E) - βE·S + γE·‖Δη‖²
    dI/dt = -k·S + βI·C(V,Θ) - γI·I          [linear mode, default since v5]
         or -k·S + βI·C(V,Θ) - γI·I·(1-I)    [logistic mode, legacy]
    dS/dt = -μ·S + λ₁(Θ)·‖Δη‖² - λ₂(Θ)·C(V,Θ) + β_complexity·C + noise
    dV/dt = κ(E - I) - δ·V

where:
    E: Energy (exploration/productive capacity) [0,1]
    I: Information integrity [0,1]
    S: Semantic uncertainty [0,2]
    V: E-I imbalance integral (damped accumulator, like Helmholtz free energy) [-2,2]
        V > 0: energy surplus (running hot), V < 0: integrity surplus (running careful)
        Feeds back through coherence: C(V,Θ) = Cmax · 0.5 · (1 + tanh(C₁·V))
        Note: "Void" name comes from Lumen mapping V=(1-presence)*0.3; the ODE
        evolves V as a signed integrator, which is a different quantity.
    C(V,Θ): Coherence function
    ‖Δη‖: Ethical drift norm
    C: Task complexity [0,1] - increases entropy S
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
        V: E-I imbalance integral [-2, 2]. Positive=energy surplus, negative=integrity surplus.
           Drives coherence feedback. Named "Void" in Lumen's observation layer.
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
    complexity: float = 0.5,
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
        complexity: Task complexity [0, 1] - increases entropy S (default: 0.5)

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
    # SECURITY: Clip complexity to valid range [0,1] as defense-in-depth
    # Even if validation fails upstream, dynamics equations remain stable
    complexity = max(0.0, min(1.0, complexity))

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
    # E dynamics: coupling to I, E-S cross-coupling, drift feedback
    # UNITARES v4.1 Eq. 7: Ė = α(I - E) - βₑES + γₑ‖Δη‖² + dₑ
    dE_dt = (
        params.alpha * (I - E)           # I → E flow
        - params.beta_E * E * S          # E-S cross-coupling (fixed: was missing E)
        + params.gamma_E * d_eta_sq      # Drift feedback
    )

    # I dynamics: S coupling, coherence boost, self-regulation
    # Forcing term A (isolated for clarity and future extensibility)
    A = params.beta_I * C - params.k * S
    
    # Check dynamics mode (linear default since v5, logistic legacy)
    from .parameters import get_i_dynamics_mode
    i_mode = get_i_dynamics_mode()

    if i_mode == "linear":
        # v5 default: Linear damping prevents boundary saturation
        # dI/dt = A - γ_I·I → stable equilibrium at I* = A/γ_I
        dI_dt = A - params.gamma_I * I
    else:
        # Legacy logistic: can saturate to I=1 if A > γ/4
        # dI/dt = A - γ_I·I·(1-I) → two equilibria, boundary risk
        dI_dt = A - params.gamma_I * I * (1 - I)

    # S dynamics: decay, drift drive, coherence reduction, complexity drive, noise
    dS_dt = (
        -params.mu * S                   # Natural decay
        + lam1 * d_eta_sq                # Drift increases uncertainty
        - lam2 * C                       # Coherence reduces uncertainty
        + params.beta_complexity * complexity  # Complexity increases uncertainty
        + noise_S                        # Optional noise term
    )

    # V dynamics: signed E-I imbalance accumulation with exponential decay
    dV_dt = (
        params.kappa * (E - I)           # E>I → V rises (hot); I>E → V falls (careful)
        - params.delta * V               # Decay toward zero (recent history dominates)
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
    complexity: float = 0.5,
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
        complexity: Task complexity [0, 1] (default: 0.5)

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
        complexity=complexity,
    )


def compute_equilibrium(
    params: DynamicsParams,
    theta: Theta,
    ethical_drift_norm_sq: float = 0.0,
) -> State:
    """
    Compute equilibrium point where all derivatives are zero.

    The UNITARES system with γᵢI(1-I) term has TWO stable equilibria:
    - High equilibrium: I* ≈ 0.91 (healthy operation)
    - Low equilibrium: I* ≈ 0.09 (collapsed state)

    This function returns the HIGH equilibrium (desired operating point).

    Args:
        params: Dynamics parameters
        theta: Control parameters
        ethical_drift_norm_sq: ‖Δη‖² (default 0)

    Returns:
        Equilibrium state (high equilibrium)
    """
    import math

    # At equilibrium with V* ≈ 0:
    # C(0) = Cmax * 0.5 * (1 + tanh(0)) = Cmax/2
    C_0 = params.Cmax / 2.0

    # From Ṡ = 0: S* = (λ₁‖Δη‖² - λ₂C₀) / μ
    lam1 = lambda1(theta, params)
    lam2 = lambda2(theta, params)
    S_star = max(0.0, (lam1 * ethical_drift_norm_sq - lam2 * C_0) / params.mu)

    # From İ = 0 with S*: βᵢC₀ = γᵢI*(1-I*) + kS*
    # Solve quadratic: γᵢI² - γᵢI + (kS* - βᵢC₀) = 0
    a = params.gamma_I
    b = -params.gamma_I
    c = params.k * S_star - params.beta_I * C_0

    discriminant = b**2 - 4*a*c
    if discriminant >= 0 and a != 0:
        # Take the higher root (high equilibrium)
        I_star = (-b + math.sqrt(discriminant)) / (2*a)
        I_star = max(params.I_min, min(params.I_max, I_star))
    else:
        I_star = 0.9  # Default to high equilibrium region

    # From Ė = 0: E* ≈ I* (dominant term)
    E_star = I_star

    # V* ≈ 0 at equilibrium
    V_star = 0.0

    return State(E=E_star, I=I_star, S=S_star, V=V_star)


def estimate_convergence(
    current: State,
    equilibrium: State,
    params: DynamicsParams,
    contraction_rate: float = 0.1,
    target_fraction: float = 0.05,
) -> dict:
    """
    Estimate time/updates to convergence.

    Uses exponential bound from contraction theory:
    ‖x(t) - x*‖ ≤ e^{-αt} ‖x(0) - x*‖

    Args:
        current: Current state
        equilibrium: Target equilibrium
        params: Dynamics parameters (for dt)
        contraction_rate: α from contraction analysis (default 0.1)
        target_fraction: Convergence threshold (default 0.05 = 95%)

    Returns:
        dict with distance, time_to_convergence, updates_to_convergence
    """
    import math

    # Compute distance to equilibrium
    distance = math.sqrt(
        (current.E - equilibrium.E)**2 +
        (current.I - equilibrium.I)**2 +
        (current.S - equilibrium.S)**2 +
        (current.V - equilibrium.V)**2
    )

    if distance < 1e-6:
        return {
            'distance': distance,
            'time_to_convergence': 0.0,
            'updates_to_convergence': 0,
            'converged': True,
        }

    # Time to reach target_fraction: e^{-αt} = target_fraction
    # t = -ln(target_fraction) / α
    dt = 0.1  # Default time step
    time_to_convergence = -math.log(target_fraction) / contraction_rate
    updates_to_convergence = int(math.ceil(time_to_convergence / dt))

    return {
        'distance': distance,
        'time_to_convergence': time_to_convergence,
        'updates_to_convergence': updates_to_convergence,
        'converged': False,
    }


def check_basin(state: State, threshold: float = 0.5) -> str:
    """
    Check which basin of attraction the state is in.

    The bistable UNITARES system has two basins:
    - 'high': I > threshold, converges to high equilibrium
    - 'low': I < threshold, converges to low equilibrium
    - 'boundary': I ≈ threshold, unstable region

    Args:
        state: Current state
        threshold: Basin boundary (default 0.5)

    Returns:
        'high', 'low', or 'boundary'
    """
    margin = 0.05
    if state.I > threshold + margin:
        return 'high'
    elif state.I < threshold - margin:
        return 'low'
    else:
        return 'boundary'


def compute_saturation_diagnostics(
    state: State,
    theta: Theta,
    params: Optional[DynamicsParams] = None,
) -> dict:
    """
    Compute I-channel saturation diagnostics.
    
    This is the "pressure gauge" for understanding boundary saturation behavior.
    Critical for monitoring system stability and validating dynamics mode choice.
    
    Args:
        state: Current UNITARES state
        theta: Control parameters
        params: Dynamics parameters (uses DEFAULT_PARAMS if None)
    
    Returns:
        dict with:
        - A: Forcing term (β_I·C - k·S)
        - gamma_over_4: Maximum logistic damping (γ_I/4)
        - sat_margin: A - γ_I/4 (positive = push-to-boundary in logistic mode)
        - I_equilibrium_linear: Predicted equilibrium under linear damping (A/γ_I)
        - I_equilibrium_logistic: Predicted equilibria under logistic (if they exist)
        - dynamics_mode: Current mode (linear/logistic)
        - will_saturate: Whether logistic mode will saturate to I=1
    """
    from .parameters import DEFAULT_PARAMS, get_i_dynamics_mode
    from .coherence import coherence
    
    if params is None:
        params = DEFAULT_PARAMS
    
    # Compute coherence
    C = coherence(state.V, theta, params)
    
    # Forcing term (isolated input)
    A = params.beta_I * C - params.k * state.S
    
    # Logistic damping maximum
    gamma_over_4 = params.gamma_I / 4.0
    
    # Saturation margin (the "smoking gun" metric)
    sat_margin = A - gamma_over_4
    
    # Linear equilibrium (always exists)
    I_eq_linear = A / params.gamma_I if params.gamma_I > 0 else float('inf')
    
    # Logistic equilibria (may not exist if sat_margin > 0)
    I_eq_logistic = []
    if sat_margin <= 0 and params.gamma_I > 0:
        # Quadratic: γ·I² - γ·I + (k·S - β·C) = 0
        # Roots: I = (1 ± sqrt(1 - 4A/γ)) / 2
        import math
        discriminant = 1 - 4 * A / params.gamma_I
        if discriminant >= 0:
            sqrt_d = math.sqrt(discriminant)
            I_low = (1 - sqrt_d) / 2
            I_high = (1 + sqrt_d) / 2
            if 0 <= I_low <= 1:
                I_eq_logistic.append(('stable_low', I_low))
            if 0 <= I_high <= 1:
                I_eq_logistic.append(('unstable_high', I_high))
    
    dynamics_mode = get_i_dynamics_mode()
    
    return {
        'A': A,
        'C': C,
        'S': state.S,
        'gamma_I': params.gamma_I,
        'gamma_over_4': gamma_over_4,
        'sat_margin': sat_margin,
        'I_current': state.I,
        'I_equilibrium_linear': min(1.0, max(0.0, I_eq_linear)),  # Clipped to valid range
        'I_equilibrium_logistic': I_eq_logistic,
        'dynamics_mode': dynamics_mode,
        'will_saturate': sat_margin > 0 and dynamics_mode == 'logistic',
        'at_boundary': state.I >= params.I_max - 0.001,
    }
