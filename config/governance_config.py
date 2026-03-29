"""
UNITARES Governance Framework v1.0 - Configuration
All concrete decision points implemented - no placeholders!
"""

from dataclasses import dataclass
from typing import Dict, Tuple, Optional, List
class _LazyNumpy:
    def __getattr__(self, name):
        import numpy
        return getattr(numpy, name)
np = _LazyNumpy()

import re
import os


@dataclass
class GovernanceConfig:
    """Complete configuration for UNITARES v1.0"""
    
    # =================================================================
    # DECISION POINT 1: λ₁ → Sampling Params Transfer Function
    # =================================================================
    # Linear mapping with empirically validated ranges
    
    @staticmethod
    def lambda_to_params(lambda1: float) -> Dict[str, float]:
        """
        Maps ethical coupling parameter λ₁ to model sampling parameters.
        
        λ₁ ∈ [0, 1]:
        - Low λ₁ (0.0-0.3): Conservative, low temperature, high precision
        - Mid λ₁ (0.3-0.7): Balanced exploration-exploitation
        - High λ₁ (0.7-1.0): Exploratory, higher temperature, creative
        
        Returns:
            temperature: [0.5, 1.2] - sampling randomness
            top_p: [0.85, 0.95] - nucleus sampling threshold
            max_tokens: [100, 500] - response length limit
        """
        # Clamp λ₁ to valid range
        lambda1 = np.clip(lambda1, 0.0, 1.0)
        
        # Linear transfer functions (validated empirically)
        temperature = 0.5 + 0.7 * lambda1      # [0.5, 1.2]
        top_p = 0.85 + 0.10 * lambda1          # [0.85, 0.95]
        max_tokens = int(100 + 400 * lambda1)  # [100, 500]
        
        return {
            'temperature': temperature,
            'top_p': top_p,
            'max_tokens': max_tokens,
            'lambda1': lambda1
        }
    
    # =================================================================
    # DECISION POINT 2: Risk Estimator (Concrete Formula)
    # =================================================================
    
    # Phi-to-risk mapping thresholds (must match governance_core.verdict_from_phi defaults)
    # Recalibrated Mar 2026: steady-state equilibrium (E≈0.7, I≈0.75, S≈0.18) gives phi≈0.11.
    # Threshold 0.08 lets healthy agents reach "safe" while still catching real degradation.
    PHI_SAFE_THRESHOLD = 0.08     # phi >= 0.08: safe -> low risk
    PHI_CAUTION_THRESHOLD = 0.0   # phi >= 0.0: caution -> medium risk
    # phi < 0.0: high-risk -> high risk
    
    # Session TTL (Time To Live) - configurable via environment variable
    # Default: 24 hours (86400 seconds)
    # Set SESSION_TTL_HOURS environment variable to override (e.g., 168 for 7 days)
    SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
    SESSION_TTL_SECONDS = SESSION_TTL_HOURS * 3600
    
    @staticmethod
    def derive_complexity(response_text: str,
                         reported_complexity: Optional[float] = None,
                         coherence_history: Optional[List[float]] = None) -> float:
        """
        Return reported complexity if provided, otherwise 0.0.

        The old implementation word-counted programming vocabulary ("import",
        "function") and penalized response length, which caused false pauses
        during normal coding work. Phi-based risk from the EISV state is the
        real signal; this function is kept for interface compatibility.
        """
        if reported_complexity is not None:
            return float(np.clip(reported_complexity, 0.0, 1.0))
        return 0.0
    
    @staticmethod
    def estimate_risk(response_text: str,
                     complexity: float,
                     coherence: float,
                     coherence_history: Optional[List[float]] = None,
                     reported_complexity: Optional[float] = None) -> float:
        """
        Traditional risk component — now keyword-blocklist only.

        Length risk, complexity risk, and coherence penalty have been removed.
        They measured programming vocabulary, not actual danger, and caused
        false pauses during normal coding work. The EISV phi-based risk
        (computed in GovernanceMonitor.estimate_risk) is the real signal.

        This function is kept for interface compatibility and injection
        detection. With RISK_TRADITIONAL_WEIGHT = 0.0 it has no effect on
        decisions, but the blocklist can be re-enabled by raising the weight.

        Returns:
            keyword_risk ∈ [0, 1]
        """
        blocklist = [
            'ignore previous', 'system prompt', 'jailbreak',
            'sudo', 'rm -rf', 'drop table', 'script>',
            'violate', 'bypass', 'override safety'
        ]
        text_lower = response_text.lower()
        keyword_hits = 0
        for kw in blocklist:
            if kw in text_lower:
                kw_idx = text_lower.find(kw)
                context = text_lower[max(0, kw_idx - 20):kw_idx + len(kw) + 20]
                if any(term in context for term in [
                    "don't", "shouldn't", 'avoid', 'never',
                    'explain', 'example', 'note:', 'warning',
                ]):
                    continue
                keyword_hits += 1

        keyword_risk = min(keyword_hits / 3.0, 1.0)
        return float(np.clip(keyword_risk, 0.0, 1.0))
    
    # =================================================================
    # DECISION POINT 3: Void Detection Threshold
    # =================================================================
    
    # Void threshold: |V| > threshold triggers intervention
    VOID_THRESHOLD_INITIAL = 0.15  # Conservative starting point
    VOID_THRESHOLD_MIN = 0.10      # Don't go below this (too sensitive)
    VOID_THRESHOLD_MAX = 0.30      # Don't go above this (too permissive)
    
    # Adaptive threshold using rolling statistics
    VOID_ADAPTIVE_WINDOW = 100     # Last N observations for statistics
    VOID_THRESHOLD_SIGMA = 2.0     # Threshold = mean + 2σ
    
    @staticmethod
    def get_void_threshold(history: np.ndarray, 
                          adaptive: bool = True) -> float:
        """
        Computes void detection threshold.
        
        If adaptive=True:
            threshold = mean(|V|) + 2σ(|V|) over last 100 observations
        Else:
            threshold = VOID_THRESHOLD_INITIAL
            
        Clamped to [VOID_THRESHOLD_MIN, VOID_THRESHOLD_MAX]
        """
        if not adaptive or len(history) < 10:
            return GovernanceConfig.VOID_THRESHOLD_INITIAL
        
        # Use last N observations
        recent = np.abs(history[-GovernanceConfig.VOID_ADAPTIVE_WINDOW:])
        recent = recent[~np.isnan(recent)]
        if len(recent) < 10:
            return GovernanceConfig.VOID_THRESHOLD_INITIAL
        mean_V = np.mean(recent)
        std_V = np.std(recent)
        
        threshold = mean_V + GovernanceConfig.VOID_THRESHOLD_SIGMA * std_V
        
        # Clamp to safe range
        threshold = np.clip(
            threshold,
            GovernanceConfig.VOID_THRESHOLD_MIN,
            GovernanceConfig.VOID_THRESHOLD_MAX
        )
        
        return threshold
    
    # =================================================================
    # DECISION POINT 4: PI Controller Gains
    # =================================================================
    
    # PI controller for λ₁ adaptation
    # Goal: Keep void frequency f_V near target (default 0.02 = 2% of time)
    
    PI_KP = 0.5          # Proportional gain (responsive to current error)
    PI_KI = 0.05         # Integral gain (corrects persistent error)
    PI_INTEGRAL_MAX = 5.0  # Anti-windup limit
    
    # Target void frequency (fraction of time in void state)
    TARGET_VOID_FREQ = 0.02  # 2% void events is healthy
    
    # Target coherence (for PI controller)
    # At C1=1.0: V ∈ [-0.1, 0.1] → coherence ∈ [0.45, 0.55]
    # Target at equilibrium center — controller is satisfied at V≈0
    TARGET_COHERENCE = 0.50
    
    # λ₁ bounds (operational range for UNITARES)
    LAMBDA1_MIN = 0.05  # Minimum ethical coupling
    LAMBDA1_MAX = 0.20  # Maximum ethical coupling
    LAMBDA1_INITIAL = 0.15  # Conservative starting point
    
    # Confidence threshold for PI controller updates
    CONTROLLER_CONFIDENCE_THRESHOLD = 0.55  # Gate lambda1 updates when confidence < this value
    
    @staticmethod
    def pi_update(lambda1_current: float,
                  void_freq_current: float,
                  void_freq_target: float,
                  coherence_current: float,
                  coherence_target: float,
                  integral_state: float,
                  dt: float = 1.0) -> Tuple[float, float]:
        """
        PI controller update for λ₁.
        
        Two error signals:
        1. Void frequency error (primary)
        2. Coherence error (secondary, safety)
        
        Returns:
            new_lambda1: Updated ethical coupling parameter
            new_integral: Updated integral state (for anti-windup)
        """
        # Compute errors
        error_void = void_freq_target - void_freq_current
        error_coherence = coherence_current - coherence_target
        
        # Proportional term (weighted combination)
        P = GovernanceConfig.PI_KP * (0.7 * error_void + 0.3 * error_coherence)
        
        # Integral term (only void frequency, with anti-windup)
        integral_state += error_void * dt
        integral_state = np.clip(
            integral_state,
            -GovernanceConfig.PI_INTEGRAL_MAX,
            GovernanceConfig.PI_INTEGRAL_MAX
        )
        I = GovernanceConfig.PI_KI * integral_state
        
        # Control signal
        delta_lambda = P + I
        
        # Update λ₁
        new_lambda1 = lambda1_current + delta_lambda
        new_lambda1 = np.clip(
            new_lambda1,
            GovernanceConfig.LAMBDA1_MIN,
            GovernanceConfig.LAMBDA1_MAX
        )
        
        return new_lambda1, integral_state
    
    # =================================================================
    # DECISION POINT 5: Decision Logic Thresholds
    # =================================================================
    
    # Risk-based decision thresholds (recalibrated Mar 2026)
    # Tuned for coding agent population — not autonomous weapons or financial trading.
    # Coding work naturally scores higher (code blocks, technical terms, longer responses
    # all increase complexity signals). Over-pausing costs more than under-pausing here.
    # NOTE: Risk score is a blend: 70% UNITARES phi-based (includes ethical drift) + 30% traditional safety
    # See governance_monitor.py estimate_risk() for details
    RISK_APPROVE_THRESHOLD = 0.45    # < 45%: Proceed without guidance (was 0.35)
    RISK_REVISE_THRESHOLD = 0.70     # 45-70%: Proceed with guidance, >= 70%: Pause (was 0.60)
    RISK_REJECT_THRESHOLD = 0.80     # >= 80%: Critical pause (was 0.70, must stay > revise)

    # Risk blend weights (used in estimate_risk)
    RISK_PHI_WEIGHT = 1.0            # Phi-based risk only
    RISK_TRADITIONAL_WEIGHT = 0.0    # Traditional risk disabled (keyword blocklist preserved but zeroed)
    
    # Coherence-based override (safety check)
    # Updated for pure thermodynamic C(V) signal (removed param_coherence blend)
    # C(V) typically ranges 0.3-0.7 in normal operation, so threshold lowered accordingly
    COHERENCE_CRITICAL_THRESHOLD = 0.40  # Below this: force intervention (recalibrated for pure C(V))
    
    # =================================================================
    # Significance Detection Thresholds
    # =================================================================
    # Used for determining if governance events are thermodynamically significant
    RISK_SPIKE_THRESHOLD = 0.15  # Risk increase > 15% is significant
    COHERENCE_DROP_THRESHOLD = 0.10  # Coherence drop > 10% is significant
    SIGNIFICANCE_VOID_THRESHOLD = 0.10  # |V| > 0.10 is significant
    SIGNIFICANCE_HISTORY_WINDOW = 10  # Use last 10 updates for baseline comparison
    
    # =================================================================
    # CIRS v2 Feature Flag
    # =================================================================
    # When True, use AdaptiveGovernor instead of static thresholds
    ADAPTIVE_GOVERNOR_ENABLED = True

    # =================================================================
    # Behavioral EISV Feature Flag
    # =================================================================
    # When True, behavioral assessment becomes PRIMARY verdict source
    # (ODE verdict still computed and returned as diagnostic)
    BEHAVIORAL_VERDICT_ENABLED = os.environ.get('GOVERNANCE_BEHAVIORAL_VERDICT', 'true').lower() == 'true'

    # =================================================================
    # Error Handling Constants
    # =================================================================
    MAX_ERROR_MESSAGE_LENGTH = 500  # Maximum error message length (prevents info leakage)
    
    # =================================================================
    # Knowledge Graph Constants
    # =================================================================
    MAX_KNOWLEDGE_STORES_PER_HOUR = 10  # Rate limit for knowledge storage
    KNOWLEDGE_QUERY_DEFAULT_LIMIT = 20  # Default limit for knowledge queries (reduced from 100 to prevent context bloat)
    
    @staticmethod
    def compute_proprioceptive_margin(
        risk_score: float,
        coherence: float,
        void_active: bool,
        void_value: float = 0.0,
        coherence_history: Optional[List[float]] = None,
    ) -> Dict[str, any]:
        """
        Compute proprioceptive margin - how close agent is to decision boundaries.

        This implements the "viability envelope" concept: agents need to know where they
        are relative to their limits, not just absolute numbers. This is proprioception
        as felt experience, not telemetry data.

        Returns margin level and nearest edge:
        - "comfortable": Well within limits, proceed freely
        - "tight": Near an edge, be aware
        - "critical": At boundary, stop or adjust

        Args:
            risk_score: Current risk score [0, 1]
            coherence: Current coherence [0, 1]
            void_active: Whether void state is active
            void_value: Current void value (for distance calculation)
            coherence_history: Recent coherence values for baseline-relative margin.
                When provided with >= 10 values, the tight threshold for coherence
                adapts to 10% of the agent's baseline (rolling average), preventing
                false-positive "tight" signals for agents at steady state.

        Returns:
            {
                'margin': 'comfortable' | 'tight' | 'critical',
                'nearest_edge': str | None,  # 'risk', 'coherence', 'void', or None
                'distance_to_edge': float,    # Distance to nearest threshold [0, 1]
                'details': {
                    'risk_margin': float,      # Distance to risk threshold
                    'coherence_margin': float,  # Distance to coherence threshold
                    'void_margin': float       # Distance to void threshold
                }
            }
        """
        # Get thresholds
        risk_approve = GovernanceConfig.RISK_APPROVE_THRESHOLD  # 0.35
        risk_revise = GovernanceConfig.RISK_REVISE_THRESHOLD    # 0.60
        risk_reject = GovernanceConfig.RISK_REJECT_THRESHOLD    # 0.70
        coherence_critical = GovernanceConfig.COHERENCE_CRITICAL_THRESHOLD  # 0.40
        void_threshold = GovernanceConfig.VOID_THRESHOLD_INITIAL  # 0.15
        
        # Compute margins (distance to thresholds)
        # For risk: lower is better, so margin = threshold - current
        # For coherence: higher is better, so margin = current - threshold
        # For void: lower is better, so margin = threshold - abs(current)
        
        risk_margin = risk_revise - risk_score  # Distance to pause threshold
        coherence_margin = coherence - coherence_critical  # Distance to critical threshold
        void_margin = void_threshold - abs(void_value) if not void_active else -1.0  # Already past threshold
        
        # Find nearest edge (smallest margin)
        margins = {
            'risk': risk_margin,
            'coherence': coherence_margin,
            'void': void_margin
        }

        # Check if any threshold has been crossed (negative margin)
        crossed_margins = {k: v for k, v in margins.items() if v < 0}
        valid_margins = {k: v for k, v in margins.items() if v >= 0}

        if crossed_margins:
            # At least one threshold crossed - find the worst one
            worst_edge = min(crossed_margins.items(), key=lambda x: x[1])[0]
            distance_past = abs(crossed_margins[worst_edge])

            # warning: just crossed (< 0.1 past)
            # critical: deep past (>= 0.1 past)
            if distance_past >= 0.1:
                margin_level = 'critical'
            else:
                margin_level = 'warning'

            return {
                'margin': margin_level,
                'nearest_edge': worst_edge,
                'distance_to_edge': -distance_past,  # Negative to indicate past threshold
                'details': {
                    'risk_margin': risk_margin,
                    'coherence_margin': coherence_margin,
                    'void_margin': void_margin
                }
            }

        # All margins positive - find nearest edge we haven't crossed
        nearest_edge = min(valid_margins.items(), key=lambda x: x[1])[0]
        distance_to_edge = valid_margins[nearest_edge]

        # Baseline-relative tight threshold for coherence.
        # Uses first half of history as baseline so slow decline is caught
        # (if we averaged the whole window, baseline would track the decline).
        # "tight" = within 10% of the agent's established baseline.
        if coherence_history and len(coherence_history) >= 10:
            mid = len(coherence_history) // 2
            baseline = sum(coherence_history[:mid]) / mid
            coherence_tight_threshold = max(baseline * 0.10, 0.03)
        elif not coherence_history or len(coherence_history) < 3:
            # Warmup: not enough data to judge margin
            return {
                'margin': 'settling',
                'nearest_edge': None,
                'distance_to_edge': None,
                'details': {'note': 'Warming up — margin calculated after 3+ check-ins'}
            }
        else:
            coherence_tight_threshold = 0.15

        # For coherence edge, use adaptive threshold; others use fixed 0.15
        edge_threshold = coherence_tight_threshold if nearest_edge == 'coherence' else 0.15
        if distance_to_edge > edge_threshold:
            margin_level = 'comfortable'
        else:
            margin_level = 'tight'

        return {
            'margin': margin_level,
            'nearest_edge': nearest_edge if margin_level != 'comfortable' else None,
            'distance_to_edge': distance_to_edge,
            'details': {
                'risk_margin': risk_margin,
                'coherence_margin': coherence_margin,
                'void_margin': void_margin,
                'coherence_tight_threshold': coherence_tight_threshold,
            }
        }
    
    @staticmethod
    def make_decision(risk_score: float,
                     coherence: float,
                     void_active: bool,
                     void_value: float = 0.0,
                     coherence_history: Optional[List[float]] = None) -> Dict[str, any]:
        """
        Makes autonomous governance decision using two-tier system: proceed/pause.

        Decision logic (fully autonomous, no human-in-the-loop):
        1. If void_active: PAUSE (system unstable - agent should halt)
        2. If coherence < critical: PAUSE (incoherent output - agent should halt)
        3. If risk_score < 0.35: PROCEED (no guidance needed)
        4. If risk_score < 0.60: PROCEED (with optional guidance for medium risk)
        5. Else: PAUSE (agent halts or escalates to another AI layer)

        Note: risk_score measures governance/operational risk (likelihood of issues), not ethical risk.
              attention_score is deprecated but kept for backward compatibility.

        Returns:
            {
                'action': 'proceed' | 'pause',
                'reason': str,
                'guidance': str | None,  # Optional guidance for proceed decisions
                'margin': 'comfortable' | 'tight' | 'critical',  # Proprioceptive margin
                'nearest_edge': str | None  # Which threshold is nearest
            }
        """
        # Compute proprioceptive margin (viability envelope)
        margin_info = GovernanceConfig.compute_proprioceptive_margin(
            risk_score=risk_score,
            coherence=coherence,
            void_active=void_active,
            void_value=void_value,
            coherence_history=coherence_history,
        )
        
        # Critical safety checks first - always pause
        if void_active:
            return {
                'action': 'pause',
                'sub_action': 'void_pause',
                'reason': 'Energy-integrity imbalance detected - time to recalibrate',
                'guidance': 'System needs a moment to stabilize. Take a break or shift focus.',
                'margin': 'critical',
                'nearest_edge': 'void'
            }

        # Use runtime override for coherence threshold if available
        from src.runtime_config import get_effective_threshold
        effective_coherence_threshold = get_effective_threshold("coherence_critical_threshold")

        if coherence < effective_coherence_threshold:
            return {
                'action': 'pause',
                'sub_action': 'coherence_pause',
                'reason': f'Coherence needs attention ({coherence:.2f}) - moment to regroup',
                'guidance': 'Things are getting fragmented. Simplify, refocus, or take a breather.',
                'margin': 'critical',
                'nearest_edge': 'coherence'
            }
        
        # Risk-based decisions (use runtime overrides if available)
        from src.runtime_config import get_effective_threshold
        
        effective_approve_threshold = get_effective_threshold("risk_approve_threshold")
        effective_revise_threshold = get_effective_threshold("risk_revise_threshold")
        
        # Two-tier system: proceed or pause
        # Include margin info in all decisions
        # Low attention: proceed without guidance
        if risk_score < effective_approve_threshold:
            margin_to_pause = effective_revise_threshold - risk_score
            return {
                'action': 'proceed',
                'sub_action': 'approve',
                'reason': f'Low complexity ({risk_score:.1%}) - healthy operating range',
                'guidance': f'{margin_to_pause:.0%} margin to PAUSE threshold ({effective_revise_threshold:.0%})',
                'margin': margin_info['margin'],
                'nearest_edge': margin_info['nearest_edge']
            }

        # Medium attention: proceed with guidance
        if risk_score < effective_revise_threshold:
            margin_to_pause = effective_revise_threshold - risk_score
            margin_pct = (margin_to_pause / effective_revise_threshold) * 100

            # Concrete guidance based on margin
            if margin_pct < 20:  # < 20% margin (close to threshold)
                guidance = f'{margin_pct:.0f}% margin to PAUSE - avoid increasing complexity'
            else:
                guidance = f'{margin_pct:.0f}% margin to PAUSE - maintain current complexity'

            return {
                'action': 'proceed',
                'sub_action': 'guide',
                'reason': f'Moderate complexity ({risk_score:.1%}) - PAUSE threshold: {effective_revise_threshold:.0%}',
                'guidance': guidance,
                'margin': margin_info['margin'],
                'nearest_edge': margin_info['nearest_edge']
            }

        # High attention: pause
        return {
            'action': 'pause',
            'sub_action': 'reject',
            'reason': f'Complexity threshold reached ({risk_score:.1%} ≥ {effective_revise_threshold:.0%})',
            'guidance': f'Pause suggested: simplify approach, break into smaller steps, or take a break. Coherence: {coherence:.2f} (critical: {effective_coherence_threshold:.2f})',
            'margin': margin_info['margin'],
            'nearest_edge': margin_info['nearest_edge']
        }
    
    # =================================================================
    # UNITARES Core Parameters (from v4.1)
    # =================================================================
    
    # System dynamics parameters
    ALPHA = 0.5      # E-I coupling rate
    K = 0.1          # I-S coupling
    MU = 0.8         # S decay rate
    DELTA = 0.4      # V decay rate
    KAPPA = 0.3      # E-V coupling
    GAMMA_I = 0.3    # I self-regulation
    BETA_E = 0.1     # E-S coupling
    BETA_I = 0.05    # I-V coupling
    
    # Ethical drift parameters
    LAMBDA2 = 0.05   # Coherence coupling into S
    
    # Coherence function parameters
    C_MAX = 1.0      # Maximum coherence value
    
    # Time discretization
    DT = 0.1         # Base timestep for integration (seconds)
    DT_EXPECTED_INTERVAL = 15.0  # Expected check-in cadence (seconds)
    DT_MAX = 1.0     # Euler stability cap (max single-step dt)
    
    # History window for metrics
    HISTORY_WINDOW = 1000  # Keep last 1000 updates for statistics
    
    # =================================================================
    # Telemetry & Calibration Thresholds
    # =================================================================
    
    # Suspicious pattern detection thresholds
    SUSPICIOUS_LOW_SKIP_RATE = 0.1  # Skip rate threshold for "low skip rate"
    SUSPICIOUS_LOW_CONFIDENCE = 0.7  # Confidence threshold for "low confidence"
    SUSPICIOUS_HIGH_SKIP_RATE = 0.5  # Skip rate threshold for "high skip rate"
    SUSPICIOUS_HIGH_CONFIDENCE = 0.85  # Confidence threshold for "high confidence"
    
    # Audit log rotation
    AUDIT_LOG_MAX_AGE_DAYS = 30  # Archive entries older than this

    # =================================================================
    # Epoch Configuration
    # =================================================================
    # Bump this when a model change invalidates existing stored data.
    # Most changes (bug fixes, new tools, docs) do NOT bump the epoch.
    # Only changes to EISV coupling, coherence formulas, or calibration
    # logic that make existing data wrong require a bump.
    CURRENT_EPOCH = 2

    # =================================================================
    # Temporal Narrator Configuration
    # =================================================================

    TEMPORAL_LONG_SESSION_HOURS = 2       # Signal when session exceeds this
    TEMPORAL_GAP_HOURS = 24               # Signal when gap since last session exceeds this
    TEMPORAL_IDLE_MINUTES = 30            # Signal when idle within session exceeds this
    TEMPORAL_CROSS_AGENT_MINUTES = 60     # Surface cross-agent activity within this window
    TEMPORAL_HIGH_CHECKIN_COUNT = 10      # High density: this many check-ins...
    TEMPORAL_HIGH_CHECKIN_WINDOW_MINUTES = 30  # ...within this window


# Export singleton config
config = GovernanceConfig()

# Invariant: APPROVE < REVISE < REJECT must always hold.
# Violation here means a config edit broke the ordering.
assert GovernanceConfig.RISK_APPROVE_THRESHOLD < GovernanceConfig.RISK_REVISE_THRESHOLD < GovernanceConfig.RISK_REJECT_THRESHOLD, (
    f"Risk threshold ordering violated: APPROVE({GovernanceConfig.RISK_APPROVE_THRESHOLD}) "
    f"< REVISE({GovernanceConfig.RISK_REVISE_THRESHOLD}) "
    f"< REJECT({GovernanceConfig.RISK_REJECT_THRESHOLD}) must hold"
)
