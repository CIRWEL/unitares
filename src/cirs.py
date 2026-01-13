"""
CIRS v0.1: Coherence-Integrity Resonance System

Implements oscillation detection and resonance damping for UNITARES governance.

Key components:
- OscillationDetector: Detects oscillatory patterns using Oscillation Index (OI)
- ResonanceDamper: Applies damping when resonance is detected
- Response classification: Hard block vs soft dampen

Reference: CIRS v0.1 specification
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
from datetime import datetime


class SignalType(Enum):
    """CIRS Signal Types for structured event logging."""
    SEM_DRIFT = "SEM_DRIFT"           # Semantic/coherence drift
    GOV_BREACH = "GOV_BREACH"         # Governance threshold breach
    RESONANCE = "RESONANCE"           # Oscillation detected
    DAMPING = "DAMPING"               # Damping applied
    HARD_BLOCK = "HARD_BLOCK"         # Hard block triggered
    SOFT_DAMPEN = "SOFT_DAMPEN"       # Soft dampen applied


@dataclass
class CIRSSignal:
    """Structured signal event per CIRS spec."""
    type: SignalType
    timestamp: datetime
    source: str           # e.g., "unitares.governance"
    destination: str      # e.g., "cirs.arbiter"
    confidence: float     # [0, 1]
    payload: Dict

    def to_dict(self) -> Dict:
        return {
            'type': self.type.value,
            't': self.timestamp.isoformat(),
            'src': self.source,
            'dst': self.destination,
            'confidence': self.confidence,
            'payload': self.payload
        }


@dataclass
class OscillationState:
    """State tracked by OscillationDetector."""
    oi: float = 0.0                    # Current Oscillation Index
    flips: int = 0                     # Flip count in window
    resonant: bool = False             # Whether resonance detected
    trigger: Optional[str] = None      # 'oi' or 'flips' or None
    ema_coherence: float = 0.0         # EMA of coherence transitions
    ema_risk: float = 0.0              # EMA of risk transitions


class OscillationDetector:
    """
    Detect oscillatory patterns in governance decisions.
    Implements CIRS v0.1 Oscillation Index.

    OI_t = EMA_λ(sign(Δcoherence_t) - sign(Δcoherence_{t-1})) +
           EMA_λ(sign(Δrisk_t) - sign(Δrisk_{t-1}))

    Triggers resonance when:
    - |OI| >= oi_threshold (oscillation index too high)
    - flips >= flip_threshold (too many decision flips)
    """

    def __init__(self,
                 window: int = 8,
                 ema_lambda: float = 0.3,
                 oi_threshold: float = 3.0,
                 flip_threshold: int = 3):
        """
        Args:
            window: Rolling window size (default 8 per CIRS spec)
            ema_lambda: EMA smoothing factor (0 < λ < 1)
            oi_threshold: OI threshold for resonance trigger (θ_oi)
            flip_threshold: Min flips to trigger resonance (k)
        """
        self.window = window
        self.ema_lambda = ema_lambda
        self.oi_threshold = oi_threshold
        self.flip_threshold = flip_threshold
        self.history: List[Dict] = []
        self.ema_coherence = 0.0
        self.ema_risk = 0.0

    def update(self, coherence: float, risk: float,
               route: str, threshold_coherence: float,
               threshold_risk: float) -> OscillationState:
        """
        Update oscillation state with new observation.

        Args:
            coherence: Current coherence value
            risk: Current risk score
            route: Decision route ('proceed', 'pause', 'reflect')
            threshold_coherence: Coherence threshold (τ)
            threshold_risk: Risk threshold (β)

        Returns:
            OscillationState with current oscillation metrics
        """
        # Compute signed deviations from thresholds
        delta_coh = coherence - threshold_coherence
        delta_risk = risk - threshold_risk

        # Store observation
        self.history.append({
            'coherence': coherence,
            'risk': risk,
            'route': route,
            'sign_coh': 1 if delta_coh >= 0 else -1,
            'sign_risk': 1 if delta_risk >= 0 else -1
        })

        # Maintain window
        if len(self.history) > self.window:
            self.history.pop(0)

        # Compute OI
        oi = self._compute_oi()

        # Count flips
        flips = self._count_flips()

        # Check resonance
        resonant = False
        trigger = None

        if abs(oi) >= self.oi_threshold:
            resonant = True
            trigger = 'oi'
        elif flips >= self.flip_threshold:
            resonant = True
            trigger = 'flips'

        return OscillationState(
            oi=oi,
            flips=flips,
            resonant=resonant,
            trigger=trigger,
            ema_coherence=self.ema_coherence,
            ema_risk=self.ema_risk
        )

    def _compute_oi(self) -> float:
        """Compute Oscillation Index using EMA of sign transitions."""
        if len(self.history) < 2:
            return 0.0

        for i in range(1, len(self.history)):
            # Sign transitions for coherence
            coh_transition = (self.history[i]['sign_coh'] -
                            self.history[i-1]['sign_coh'])
            # Sign transitions for risk
            risk_transition = (self.history[i]['sign_risk'] -
                             self.history[i-1]['sign_risk'])

            # EMA update
            self.ema_coherence = (self.ema_lambda * coh_transition +
                                 (1 - self.ema_lambda) * self.ema_coherence)
            self.ema_risk = (self.ema_lambda * risk_transition +
                           (1 - self.ema_lambda) * self.ema_risk)

        return self.ema_coherence + self.ema_risk

    def _count_flips(self) -> int:
        """Count route flips (decision transitions) in window."""
        if len(self.history) < 2:
            return 0

        flips = 0
        for i in range(1, len(self.history)):
            if self.history[i]['route'] != self.history[i-1]['route']:
                flips += 1

        return flips

    def reset(self):
        """Reset detector state."""
        self.history = []
        self.ema_coherence = 0.0
        self.ema_risk = 0.0


@dataclass
class DampingResult:
    """Result of applying resonance damping."""
    tau_new: float                  # New coherence threshold
    beta_new: float                 # New risk threshold
    damping_applied: bool           # Whether damping was applied
    adjustments: Dict = field(default_factory=dict)  # Details of adjustments


class ResonanceDamper:
    """
    Apply damping when oscillation/resonance detected.
    Implements CIRS v0.1 Section 5.

    When resonance is detected, thresholds are adjusted toward current values
    to reduce oscillation amplitude.
    """

    def __init__(self,
                 kappa_r: float = 0.1,      # Damping gain
                 delta_tau: float = 0.05,   # Max threshold adjustment
                 tau_bounds: Tuple[float, float] = (0.3, 0.7),  # Coherence threshold bounds
                 beta_bounds: Tuple[float, float] = (0.2, 0.5)  # Risk threshold bounds
                ):
        self.kappa_r = kappa_r
        self.delta_tau = delta_tau
        self.tau_bounds = tau_bounds
        self.beta_bounds = beta_bounds

    def apply_damping(self,
                      current_coherence: float,
                      current_risk: float,
                      tau: float,           # Current coherence threshold
                      beta: float,          # Current risk threshold
                      oscillation_state: OscillationState
                     ) -> DampingResult:
        """
        Apply damping adjustments when resonance detected.

        Moves thresholds toward current values to reduce oscillation.

        Args:
            current_coherence: Current coherence value
            current_risk: Current risk score
            tau: Current coherence threshold
            beta: Current risk threshold
            oscillation_state: Current oscillation state from detector

        Returns:
            DampingResult with new thresholds and adjustment details
        """
        if not oscillation_state.resonant:
            return DampingResult(
                tau_new=tau,
                beta_new=beta,
                damping_applied=False,
                adjustments={}
            )

        # Compute deviations (how far current values are from thresholds)
        delta_coh = tau - current_coherence
        delta_risk = beta - current_risk

        # Clamp adjustments to max delta
        d_tau = max(-self.delta_tau, min(self.delta_tau, delta_coh))
        d_beta = max(-self.delta_tau, min(self.delta_tau, delta_risk))

        # Apply damping (move thresholds toward current values)
        tau_new = tau + self.kappa_r * (-d_tau)
        beta_new = beta + self.kappa_r * (-d_beta)

        # Enforce bounds
        tau_new = max(self.tau_bounds[0], min(self.tau_bounds[1], tau_new))
        beta_new = max(self.beta_bounds[0], min(self.beta_bounds[1], beta_new))

        return DampingResult(
            tau_new=tau_new,
            beta_new=beta_new,
            damping_applied=True,
            adjustments={
                'd_tau': tau_new - tau,
                'd_beta': beta_new - beta,
                'trigger': oscillation_state.trigger,
                'oi': oscillation_state.oi,
                'flips': oscillation_state.flips
            }
        )


def classify_response(coherence: float, risk: float,
                      tau: float, beta: float,
                      tau_low: float = 0.3,   # Critical coherence floor
                      beta_high: float = 0.7,  # Critical risk ceiling
                      oscillation_state: Optional[OscillationState] = None) -> str:
    """
    Determine response tier per CIRS v0.1.

    Three tiers:
    - 'proceed': Normal operation
    - 'soft_dampen': Apply damping, continue
    - 'hard_block': Force adjudication/pause

    Args:
        coherence: Current coherence value
        risk: Current risk score
        tau: Coherence threshold
        beta: Risk threshold
        tau_low: Critical coherence floor (hard block below this)
        beta_high: Critical risk ceiling (hard block above this)
        oscillation_state: Optional oscillation state for resonance check

    Returns:
        Response tier: 'proceed', 'soft_dampen', or 'hard_block'
    """
    # Hard block conditions (critical safety)
    if coherence < tau_low:
        return 'hard_block'
    if risk > beta_high:
        return 'hard_block'

    # Soft dampen conditions (resonance detected but not critical)
    if oscillation_state and oscillation_state.resonant:
        if coherence >= tau and risk <= beta:
            return 'soft_dampen'
        else:
            return 'hard_block'

    # Normal operation
    if coherence >= tau and risk <= beta:
        return 'proceed'

    return 'soft_dampen'


# =============================================================================
# HCK/CIRS Configuration Defaults
# =============================================================================

HCK_DEFAULTS = {
    'K_p': 0.5,                    # Proportional gain
    'K_i': 0.05,                   # Integral gain
    'gain_modulation_min': 0.5,   # Minimum gain factor when ρ low
    'CE_window': 10,              # Continuity energy window
    'CE_alpha_state': 0.6,        # CE state weight
    'CE_alpha_decision': 0.4,     # CE decision weight
}

CIRS_DEFAULTS = {
    'window': 8,                   # Observation window
    'ema_lambda': 0.3,            # EMA smoothing
    'oi_threshold': 3.0,          # OI trigger threshold
    'flip_threshold': 3,          # Flip count trigger
    'kappa_r': 0.1,               # Damping gain
    'delta_tau': 0.05,            # Max threshold adjustment
    'tau_bounds': (0.3, 0.7),     # Coherence threshold bounds
    'beta_bounds': (0.2, 0.5),    # Risk threshold bounds
    'tau_low': 0.3,               # Hard block coherence floor
    'beta_high': 0.7,             # Hard block risk ceiling
}
