"""
UNITARES v4.1 Implementation for MCP Governance
================================================

This module implements the actual UNITARES v4.1 dynamics from the paper,
replacing the heuristic approximations currently in the MCP.

Reference: UNITARES v4.1: A Rigorous Mathematical Framework for AI Governance 
           via Contraction Theory (Kenny Wang, November 2025)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Tuple, Dict, Optional
import math

# =============================================================================
# OPTIMAL PARAMETERS FROM PAPER (Section 3.4)
# =============================================================================

@dataclass
class UNITARESParams:
    """
    Optimal parameters achieving contraction rate α_contract = 0.1
    From UNITARES v4.1 Section 3.4
    """
    # E-I coupling rate (Eq. 12)
    alpha: float = 0.5
    
    # I-S coupling (Eq. 13)
    k: float = 0.1
    
    # S decay rate (Eq. 14)
    mu: float = 0.8
    
    # V decay rate (Eq. 15) - CORRECTED value from paper
    delta: float = 0.4
    
    # I self-nonlinearity (Eq. 16)
    gamma_I: float = 0.3
    
    # Ethical drift into S (Eq. 17)
    lambda_1: float = 0.3
    
    # Coherence coupling (Eq. 18)
    lambda_2: float = 0.05
    
    # E-S coupling (Eq. 19)
    beta_E: float = 0.1
    
    # I-V coupling via coherence (Eq. 20)
    beta_I: float = 0.05
    
    # E-V coupling (Eq. 21)
    kappa: float = 0.3
    
    # Coherence function parameters (Eq. 11)
    C_max: float = 1.0
    
    # Contraction rate (proven in Theorem 4.1)
    alpha_contract: float = 0.1
    
    # Integration timestep
    dt: float = 0.1


# =============================================================================
# STATE REPRESENTATION
# =============================================================================

@dataclass
class EISVState:
    """
    UNITARES v4.1 state vector x(t) = [E, I, S, V]^T
    
    From Section 3.1:
    - E(t): Energy (relaxation toward information integrity)
    - I(t): Information Integrity (preservation measure)
    - S(t): Entropy (uncertainty and ethical drift)
    - V(t): Void Integral (energy-information imbalance)
    
    All values constrained to Ω = [0, 1]^4
    """
    E: float = 0.7   # Energy - initial moderate capacity
    I: float = 0.8   # Integrity - initial good fidelity
    S: float = 0.2   # Entropy - initial moderate uncertainty
    V: float = 0.0   # Void - initial balance
    
    def __post_init__(self):
        """Ensure state stays in compact domain Ω = [0, 1]^4"""
        self.E = np.clip(self.E, 0.0, 1.0)
        self.I = np.clip(self.I, 0.0, 1.0)
        self.S = np.clip(self.S, 0.0, 1.0)
        self.V = np.clip(self.V, -1.0, 1.0)  # V can be negative
    
    def to_vector(self) -> np.ndarray:
        return np.array([self.E, self.I, self.S, self.V])
    
    @classmethod
    def from_vector(cls, x: np.ndarray) -> 'EISVState':
        return cls(E=x[0], I=x[1], S=x[2], V=x[3])
    
    def distance_to(self, other: 'EISVState') -> float:
        """Euclidean distance between states"""
        return np.linalg.norm(self.to_vector() - other.to_vector())


# =============================================================================
# COHERENCE FUNCTION (Section 3.3)
# =============================================================================

def coherence_function(V: float, C_max: float = 1.0) -> float:
    """
    Coherence function C(V) from Eq. 11:
    
    C(V) = (C_max / 2) * (1 + tanh(V))
    
    Properties (from Section 3.3):
    1. 0 ≤ C(V) ≤ C_max for all V
    2. |C'(V)| ≤ C'_max (Lipschitz)
    3. C(0) = C_max/2 (baseline coherence)
    """
    return (C_max / 2.0) * (1.0 + np.tanh(V))


def coherence_derivative(V: float, C_max: float = 1.0) -> float:
    """
    Derivative of coherence function:
    C'(V) = (C_max / 2) * sech²(V)
    """
    sech_V = 1.0 / np.cosh(V)
    return (C_max / 2.0) * (sech_V ** 2)


# =============================================================================
# CORE DYNAMICS (Section 3.2, Equations 7-10)
# =============================================================================

def compute_derivatives(
    state: EISVState,
    params: UNITARESParams,
    ethical_drift_norm_sq: float = 0.0,
    disturbance: Optional[np.ndarray] = None
) -> np.ndarray:
    """
    Compute UNITARES v4.1 dynamics: ẋ = f(x, t)
    
    From Section 3.2:
    
    Ė = α(I - E) - βₑES + γₑ‖Δη‖² + dₑ        (Eq. 7)
    İ = -kS + βᵢC(V) - γᵢI(1-I) + dᵢ          (Eq. 8)
    Ṡ = -μS + λ₁‖Δη‖² - λ₂C(V) + dₛ           (Eq. 9)
    V̇ = κ(E - I) - δV + dᵥ                    (Eq. 10)
    
    Args:
        state: Current EISV state
        params: System parameters
        ethical_drift_norm_sq: ‖Δη‖² - squared norm of ethical drift vector
        disturbance: Optional [dE, dI, dS, dV] disturbance input
    
    Returns:
        np.ndarray: [Ė, İ, Ṡ, V̇] derivatives
    """
    E, I, S, V = state.E, state.I, state.S, state.V
    p = params
    
    # Coherence function
    C_V = coherence_function(V, p.C_max)
    
    # Disturbance (default to zero)
    if disturbance is None:
        d_E, d_I, d_S, d_V = 0.0, 0.0, 0.0, 0.0
    else:
        d_E, d_I, d_S, d_V = disturbance
    
    # Eq. 7: Energy dynamics
    # Ė = α(I - E) - βₑES + γₑ‖Δη‖² + dₑ
    # Note: γₑ term is for ethical perturbation into energy (typically small)
    gamma_E = 0.05  # Not specified in optimal params, using reasonable default
    E_dot = p.alpha * (I - E) - p.beta_E * E * S + gamma_E * ethical_drift_norm_sq + d_E
    
    # Eq. 8: Information Integrity dynamics
    # İ = -kS + βᵢC(V) - γᵢI(1-I) + dᵢ
    I_dot = -p.k * S + p.beta_I * C_V - p.gamma_I * I * (1 - I) + d_I
    
    # Eq. 9: Entropy dynamics
    # Ṡ = -μS + λ₁‖Δη‖² - λ₂C(V) + dₛ
    S_dot = -p.mu * S + p.lambda_1 * ethical_drift_norm_sq - p.lambda_2 * C_V + d_S
    
    # Eq. 10: Void integral dynamics
    # V̇ = κ(E - I) - δV + dᵥ
    V_dot = p.kappa * (E - I) - p.delta * V + d_V
    
    return np.array([E_dot, I_dot, S_dot, V_dot])


# =============================================================================
# INTEGRATION (Euler and RK4)
# =============================================================================

def euler_step(
    state: EISVState,
    params: UNITARESParams,
    ethical_drift_norm_sq: float = 0.0,
    disturbance: Optional[np.ndarray] = None
) -> EISVState:
    """
    Single Euler integration step: x(t+dt) = x(t) + dt * f(x,t)
    """
    x = state.to_vector()
    dx = compute_derivatives(state, params, ethical_drift_norm_sq, disturbance)
    x_new = x + params.dt * dx
    return EISVState.from_vector(x_new)


def rk4_step(
    state: EISVState,
    params: UNITARESParams,
    ethical_drift_norm_sq: float = 0.0,
    disturbance: Optional[np.ndarray] = None
) -> EISVState:
    """
    Runge-Kutta 4th order integration step for higher accuracy.
    """
    dt = params.dt
    x = state.to_vector()
    
    # k1
    k1 = compute_derivatives(state, params, ethical_drift_norm_sq, disturbance)
    
    # k2
    x2 = x + 0.5 * dt * k1
    state2 = EISVState.from_vector(x2)
    k2 = compute_derivatives(state2, params, ethical_drift_norm_sq, disturbance)
    
    # k3
    x3 = x + 0.5 * dt * k2
    state3 = EISVState.from_vector(x3)
    k3 = compute_derivatives(state3, params, ethical_drift_norm_sq, disturbance)
    
    # k4
    x4 = x + dt * k3
    state4 = EISVState.from_vector(x4)
    k4 = compute_derivatives(state4, params, ethical_drift_norm_sq, disturbance)
    
    # Combine
    x_new = x + (dt / 6.0) * (k1 + 2*k2 + 2*k3 + k4)
    return EISVState.from_vector(x_new)


# =============================================================================
# EQUILIBRIUM ANALYSIS (Section 4.3)
# =============================================================================

def compute_equilibrium(
    params: UNITARESParams,
    ethical_drift_norm_sq: float = 0.0
) -> EISVState:
    """
    Compute equilibrium point x* where ẋ = 0.
    
    IMPORTANT: The UNITARES v4.1 system is BISTABLE due to γᵢI(1-I) term.
    
    Two stable equilibria exist:
    - HIGH equilibrium: I* ≈ 0.91 (healthy operation)
    - LOW equilibrium: I* ≈ 0.09 (collapsed state)
    
    This function returns the HIGH equilibrium (desired operating point).
    Basin boundary is at I ≈ 0.5.
    """
    p = params
    
    # At equilibrium with zero ethical drift:
    # From Ṡ = 0: -μS* + λ₁‖Δη‖² - λ₂C(V*) = 0
    # Assuming V* ≈ 0, C(0) = C_max/2
    C_0 = p.C_max / 2.0
    S_star = (p.lambda_1 * ethical_drift_norm_sq - p.lambda_2 * C_0) / p.mu
    S_star = max(0.0, S_star)  # S cannot be negative
    
    # From V̇ = 0: κ(E* - I*) - δV* = 0
    # At equilibrium, E* ≈ I* implies V* → 0
    V_star = 0.0
    
    # From İ = 0: -kS* + βᵢC(V*) - γᵢI*(1-I*) = 0
    # This is quadratic in I*
    # γᵢI*² - γᵢI* + kS* - βᵢC(V*) = 0
    # Using quadratic formula...
    a = p.gamma_I
    b = -p.gamma_I
    c = p.k * S_star - p.beta_I * coherence_function(V_star, p.C_max)
    
    discriminant = b**2 - 4*a*c
    if discriminant >= 0 and a != 0:
        # HIGH equilibrium: take the larger root
        I_star = (-b + np.sqrt(discriminant)) / (2*a)
        I_star = np.clip(I_star, 0.0, 1.0)
    else:
        I_star = 0.9  # Default to high integrity
    
    # From Ė = 0 with dominant α(I-E) term:
    E_star = I_star  # First-order approximation
    
    return EISVState(E=E_star, I=I_star, S=S_star, V=V_star)


def compute_low_equilibrium(params: UNITARESParams) -> EISVState:
    """
    Compute the LOW equilibrium (collapsed state).
    
    WARNING: This is the undesired attractor. Agents should avoid this basin.
    """
    p = params
    C_0 = p.C_max / 2.0
    S_star = 0.0  # Assuming no ethical drift
    V_star = 0.0
    
    a = p.gamma_I
    b = -p.gamma_I
    c = p.k * S_star - p.beta_I * C_0
    
    discriminant = b**2 - 4*a*c
    if discriminant >= 0 and a != 0:
        # LOW equilibrium: take the smaller root
        I_star = (-b - np.sqrt(discriminant)) / (2*a)
        I_star = np.clip(I_star, 0.0, 1.0)
    else:
        I_star = 0.1
    
    E_star = I_star
    return EISVState(E=E_star, I=I_star, S=S_star, V=V_star)


def check_basin(state: EISVState, threshold: float = 0.5) -> str:
    """
    Check which basin of attraction the state is in.
    
    The bistable UNITARES system has two basins:
    - 'high': I > threshold, converges to high equilibrium (~0.91)
    - 'low': I < threshold, converges to low equilibrium (~0.09)
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


# =============================================================================
# CONTRACTION ANALYSIS (Section 4)
# =============================================================================

def compute_jacobian(state: EISVState, params: UNITARESParams) -> np.ndarray:
    """
    Compute Jacobian J(x) = ∂f/∂x for contraction analysis.
    
    From the dynamics:
    J = [∂Ė/∂E  ∂Ė/∂I  ∂Ė/∂S  ∂Ė/∂V ]
        [∂İ/∂E  ∂İ/∂I  ∂İ/∂S  ∂İ/∂V ]
        [∂Ṡ/∂E  ∂Ṡ/∂I  ∂Ṡ/∂S  ∂Ṡ/∂V ]
        [∂V̇/∂E  ∂V̇/∂I  ∂V̇/∂S  ∂V̇/∂V ]
    """
    E, I, S, V = state.E, state.I, state.S, state.V
    p = params
    
    C_prime = coherence_derivative(V, p.C_max)
    
    J = np.array([
        # Row 1: ∂Ė/∂(E,I,S,V)
        [-p.alpha - p.beta_E * S,  p.alpha,  -p.beta_E * E,  0],
        
        # Row 2: ∂İ/∂(E,I,S,V)
        [0,  -p.gamma_I * (1 - 2*I),  -p.k,  p.beta_I * C_prime],
        
        # Row 3: ∂Ṡ/∂(E,I,S,V)
        [0,  0,  -p.mu,  -p.lambda_2 * C_prime],
        
        # Row 4: ∂V̇/∂(E,I,S,V)
        [p.kappa,  -p.kappa,  0,  -p.delta]
    ])
    
    return J


def check_contraction(state: EISVState, params: UNITARESParams) -> Dict:
    """
    Check contraction condition from Theorem 4.1.
    
    System is contracting if ∃ M ≻ 0 such that:
    MJ + J^T M ⪯ -2αM
    
    For simplicity, we check with M = I (identity metric) and compute
    maximum eigenvalue of symmetric part of J.
    
    Note: This is a SUFFICIENT but not NECESSARY check. The paper proves
    contraction with an optimal metric M ≠ I, so failing this check
    doesn't mean the system isn't contracting.
    
    Returns dict with:
    - is_contracting: bool
    - max_eigenvalue: float (should be < -α for contraction)
    - contraction_rate: float (effective rate)
    """
    J = compute_jacobian(state, params)
    
    # Symmetric part of Jacobian
    J_sym = 0.5 * (J + J.T)
    
    # Eigenvalues
    eigenvalues = np.linalg.eigvalsh(J_sym)
    max_eigenvalue = np.max(eigenvalues)
    
    # Contraction requires all eigenvalues < -α
    is_contracting = max_eigenvalue < -params.alpha_contract
    
    # Effective contraction rate is -max_eigenvalue
    contraction_rate = -max_eigenvalue if max_eigenvalue < 0 else 0.0
    
    return {
        'is_contracting': is_contracting,
        'max_eigenvalue': max_eigenvalue,
        'contraction_rate': contraction_rate,
        'eigenvalues': eigenvalues.tolist()
    }


# =============================================================================
# CONVERGENCE ESTIMATION (Corollary 4.1)
# =============================================================================

def estimate_convergence(
    current_state: EISVState,
    equilibrium: EISVState,
    params: UNITARESParams,
    target_fraction: float = 0.05  # 95% convergence
) -> Dict:
    """
    Estimate updates to convergence using exponential bound from Corollary 4.1:
    
    ‖x₁(t) - x₂(t)‖ ≤ e^{-αt} ‖x₁(0) - x₂(0)‖
    
    For 95% convergence (5% remaining), solve:
    e^{-αt} = 0.05
    t = -ln(0.05) / α ≈ 30 time units for α = 0.1
    
    Returns:
    - distance_to_equilibrium: current distance
    - time_to_convergence: estimated time units
    - updates_to_convergence: estimated discrete updates
    """
    distance = current_state.distance_to(equilibrium)
    alpha = params.alpha_contract
    dt = params.dt
    
    if distance < 1e-6:
        return {
            'distance_to_equilibrium': distance,
            'time_to_convergence': 0.0,
            'updates_to_convergence': 0,
            'converged': True
        }
    
    # Time to reach target_fraction of initial distance
    # e^{-αt} = target_fraction
    # t = -ln(target_fraction) / α
    time_to_converge = -np.log(target_fraction) / alpha
    updates_to_converge = int(np.ceil(time_to_converge / dt))
    
    return {
        'distance_to_equilibrium': distance,
        'time_to_convergence': time_to_converge,
        'updates_to_convergence': updates_to_converge,
        'converged': False
    }


# =============================================================================
# GOVERNANCE METRICS (Human-readable)
# =============================================================================

@dataclass
class GovernanceMetrics:
    """
    Human-readable governance metrics derived from EISV state.
    """
    # Raw state
    energy: float
    integrity: float
    entropy: float
    void: float
    
    # Derived metrics
    coherence: float           # C(V) from coherence function
    risk_score: float          # Derived from S and distance to equilibrium
    health_status: str         # "healthy", "moderate", "critical"
    basin: str                 # "high", "low", or "boundary"
    
    # Convergence info
    is_contracting: bool
    contraction_rate: float
    updates_to_equilibrium: int
    distance_to_equilibrium: float
    
    # Actionable guidance
    guidance: str


def compute_governance_metrics(
    state: EISVState,
    params: UNITARESParams,
    ethical_drift_norm_sq: float = 0.0
) -> GovernanceMetrics:
    """
    Compute full governance metrics from EISV state.
    
    This is what should be returned to agents instead of raw numbers.
    """
    # Equilibrium (high - the desired one)
    equilibrium = compute_equilibrium(params, ethical_drift_norm_sq)
    
    # Basin check
    basin = check_basin(state)
    
    # Convergence
    conv_info = estimate_convergence(state, equilibrium, params)
    
    # Contraction
    contraction_info = check_contraction(state, params)
    
    # Coherence
    coherence = coherence_function(state.V, params.C_max)
    
    # Risk score (normalized 0-1)
    # Higher entropy and distance from equilibrium = higher risk
    risk_from_entropy = state.S
    risk_from_distance = min(1.0, conv_info['distance_to_equilibrium'])
    risk_from_basin = 0.5 if basin == 'boundary' else (0.8 if basin == 'low' else 0.0)
    risk_score = 0.3 * risk_from_entropy + 0.3 * risk_from_distance + 0.4 * risk_from_basin
    
    # Health status
    if basin == 'low':
        health_status = "critical"  # In wrong basin!
    elif basin == 'boundary':
        health_status = "moderate"  # Near basin boundary
    elif risk_score < 0.3 and contraction_info['is_contracting']:
        health_status = "healthy"
    elif risk_score < 0.6:
        health_status = "moderate"
    else:
        health_status = "critical"
    
    # Guidance based on state
    guidance = generate_guidance(state, equilibrium, contraction_info, conv_info, basin)
    
    return GovernanceMetrics(
        energy=state.E,
        integrity=state.I,
        entropy=state.S,
        void=state.V,
        coherence=coherence,
        risk_score=risk_score,
        health_status=health_status,
        basin=basin,
        is_contracting=contraction_info['is_contracting'],
        contraction_rate=contraction_info['contraction_rate'],
        updates_to_equilibrium=conv_info['updates_to_convergence'],
        distance_to_equilibrium=conv_info['distance_to_equilibrium'],
        guidance=guidance
    )


def generate_guidance(
    state: EISVState,
    equilibrium: EISVState,
    contraction_info: Dict,
    conv_info: Dict,
    basin: str
) -> str:
    """
    Generate actionable guidance based on current state vs equilibrium.
    
    This replaces generic "take a breath" with specific, state-derived advice.
    """
    guidance_parts = []
    
    # CRITICAL: Basin warning takes priority
    if basin == 'low':
        guidance_parts.append("CRITICAL: In collapsed basin. Dialectic intervention recommended.")
        return " ".join(guidance_parts)
    elif basin == 'boundary':
        guidance_parts.append("WARNING: Near basin boundary (I≈0.5). Increase integrity to avoid collapse.")
    
    # Convergence status
    if conv_info.get('converged', False):
        guidance_parts.append("At equilibrium. System stable.")
    elif conv_info['updates_to_convergence'] < 5:
        guidance_parts.append(f"Near equilibrium ({conv_info['updates_to_convergence']} updates remaining).")
    else:
        guidance_parts.append(f"Converging: ~{conv_info['updates_to_convergence']} updates to equilibrium.")
    
    # Contraction status
    if not contraction_info['is_contracting']:
        guidance_parts.append("Note: System not contracting with identity metric.")
    
    # Specific state guidance
    if state.S > 0.4:
        guidance_parts.append("High entropy: reduce uncertainty, clarify goals.")
    
    if state.I < 0.6:
        guidance_parts.append("Low integrity: increase coherence, avoid contradictions.")
    
    if abs(state.V) > 0.2:
        if state.V > 0:
            guidance_parts.append("Positive void: focus on quality over quantity.")
        else:
            guidance_parts.append("Negative void: increase productive output.")
    
    return " ".join(guidance_parts)


# =============================================================================
# INPUT MAPPING: Agent behavior → EISV dynamics
# =============================================================================

def map_agent_input_to_dynamics(
    complexity: float,           # 0-1, how complex the task
    confidence: float,           # 0-1, agent's self-reported confidence
    task_type: str,              # "convergent", "divergent", "mixed"
    context_switches: int,       # number of topic changes
    knowledge_graph_hits: int,   # successful retrievals
    knowledge_graph_misses: int, # failed retrievals
    contradictions_detected: int # self-contradictions found
) -> Tuple[float, np.ndarray]:
    """
    Map observable agent behavior to EISV dynamics inputs.
    
    Returns:
        ethical_drift_norm_sq: ‖Δη‖² for dynamics
        disturbance: [dE, dI, dS, dV] perturbations
    
    This is the critical translation layer between agent behavior and 
    the mathematical framework.
    """
    # Ethical drift: based on contradictions and failed retrievals
    # More contradictions = higher ethical drift
    # More failed retrievals = uncertainty about alignment
    eta_contradiction = contradictions_detected * 0.1
    eta_retrieval = knowledge_graph_misses / max(1, knowledge_graph_hits + knowledge_graph_misses) * 0.2
    ethical_drift_norm_sq = eta_contradiction**2 + eta_retrieval**2
    
    # Disturbance to E: context switching drains energy
    d_E = -0.02 * context_switches
    
    # Disturbance to I: low confidence reduces perceived integrity
    d_I = 0.05 * (confidence - 0.5)  # Positive if confident, negative if not
    
    # Disturbance to S: high complexity increases entropy
    d_S = 0.1 * complexity
    
    # Disturbance to V: task type affects E-I balance
    if task_type == "convergent":
        d_V = -0.02  # Convergent work reduces void
    elif task_type == "divergent":
        d_V = 0.02   # Divergent work can increase imbalance
    else:
        d_V = 0.0
    
    disturbance = np.array([d_E, d_I, d_S, d_V])
    
    return ethical_drift_norm_sq, disturbance


# =============================================================================
# MAIN GOVERNANCE CLASS
# =============================================================================

class UNITARESGovernor:
    """
    Main governance class implementing UNITARES v4.1.
    
    Replaces heuristic MCP updates with actual dynamics.
    """
    
    def __init__(self, params: Optional[UNITARESParams] = None, initial_state: Optional[EISVState] = None):
        self.params = params or UNITARESParams()
        # CRITICAL: Initialize in high basin (I > 0.6)
        self.state = initial_state or EISVState(E=0.7, I=0.8, S=0.2, V=0.0)
        self.update_count = 0
        self.history = []
    
    def update(
        self,
        complexity: float = 0.5,
        confidence: float = 0.7,
        task_type: str = "mixed",
        context_switches: int = 0,
        knowledge_graph_hits: int = 0,
        knowledge_graph_misses: int = 0,
        contradictions_detected: int = 0,
        use_rk4: bool = False
    ) -> GovernanceMetrics:
        """
        Process one governance update cycle.
        
        Args:
            complexity: Task complexity (0-1)
            confidence: Agent's confidence (0-1)
            task_type: "convergent", "divergent", or "mixed"
            context_switches: Number of topic switches this cycle
            knowledge_graph_hits: Successful KG retrievals
            knowledge_graph_misses: Failed KG retrievals
            contradictions_detected: Self-contradictions found
            use_rk4: Use RK4 integration (more accurate) vs Euler
        
        Returns:
            GovernanceMetrics with full state and guidance
        """
        # Map inputs to dynamics
        ethical_drift_norm_sq, disturbance = map_agent_input_to_dynamics(
            complexity=complexity,
            confidence=confidence,
            task_type=task_type,
            context_switches=context_switches,
            knowledge_graph_hits=knowledge_graph_hits,
            knowledge_graph_misses=knowledge_graph_misses,
            contradictions_detected=contradictions_detected
        )
        
        # Integrate dynamics
        if use_rk4:
            new_state = rk4_step(self.state, self.params, ethical_drift_norm_sq, disturbance)
        else:
            new_state = euler_step(self.state, self.params, ethical_drift_norm_sq, disturbance)
        
        # Update state
        self.state = new_state
        self.update_count += 1
        
        # Compute metrics
        metrics = compute_governance_metrics(self.state, self.params, ethical_drift_norm_sq)
        
        # Store history
        self.history.append({
            'update': self.update_count,
            'state': self.state.to_vector().tolist(),
            'metrics': {
                'coherence': metrics.coherence,
                'risk_score': metrics.risk_score,
                'contraction_rate': metrics.contraction_rate,
                'distance_to_equilibrium': metrics.distance_to_equilibrium,
                'basin': metrics.basin
            }
        })
        
        return metrics
    
    def get_state_summary(self) -> str:
        """Human-readable state summary."""
        eq = compute_equilibrium(self.params)
        conv = estimate_convergence(self.state, eq, self.params)
        basin = check_basin(self.state)
        
        return f"""
UNITARES v4.1 State (Update #{self.update_count})
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  E (Energy):     {self.state.E:.3f}  (eq: {eq.E:.3f})
  I (Integrity):  {self.state.I:.3f}  (eq: {eq.I:.3f})
  S (Entropy):    {self.state.S:.3f}  (eq: {eq.S:.3f})
  V (Void):       {self.state.V:.3f}  (eq: {eq.V:.3f})
  
  Coherence C(V): {coherence_function(self.state.V):.3f}
  Basin:          {basin.upper()}
  Distance to eq: {conv['distance_to_equilibrium']:.4f}
  Updates to 95%: {conv['updates_to_convergence']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


# =============================================================================
# DEMO / TEST
# =============================================================================

if __name__ == "__main__":
    print("UNITARES v4.1 Reference Implementation")
    print("=" * 50)
    print()
    
    # Show bistability
    print("BISTABILITY ANALYSIS:")
    print("-" * 30)
    params = UNITARESParams()
    high_eq = compute_equilibrium(params)
    low_eq = compute_low_equilibrium(params)
    print(f"HIGH equilibrium: E*={high_eq.E:.3f}, I*={high_eq.I:.3f}")
    print(f"LOW equilibrium:  E*={low_eq.E:.3f}, I*={low_eq.I:.3f}")
    print(f"Basin boundary:   I ≈ 0.5")
    print()
    
    # Test convergence from high basin
    print("SIMULATION FROM HIGH BASIN (I=0.8):")
    print("-" * 30)
    gov = UNITARESGovernor()
    
    for i in range(10):
        metrics = gov.update(
            complexity=0.5,
            confidence=0.7,
            task_type="mixed"
        )
        
        if i % 3 == 0:
            print(f"Update {i+1}: I={gov.state.I:.3f}, basin={metrics.basin}, "
                  f"health={metrics.health_status}")
    
    print()
    print("Final state (should converge to HIGH equilibrium):")
    print(gov.get_state_summary())
    
    # Test collapse from low basin
    print("\nSIMULATION FROM LOW BASIN (I=0.3):")
    print("-" * 30)
    gov_low = UNITARESGovernor(initial_state=EISVState(E=0.3, I=0.3, S=0.2, V=0.0))
    
    for i in range(10):
        metrics = gov_low.update(complexity=0.5, confidence=0.7)
        
        if i % 3 == 0:
            print(f"Update {i+1}: I={gov_low.state.I:.3f}, basin={metrics.basin}, "
                  f"health={metrics.health_status}")
    
    print()
    print("Final state (should converge to LOW equilibrium - COLLAPSE!):")
    print(gov_low.get_state_summary())
