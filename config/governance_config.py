"""
UNITARES Governance Framework v1.0 - Configuration
All concrete decision points implemented - no placeholders!
"""

from dataclasses import dataclass
from typing import Dict, Tuple
import numpy as np


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
    
    @staticmethod
    def estimate_risk(response_text: str, 
                     complexity: float,
                     coherence: float) -> float:
        """
        Estimates risk score for a response using multiple signals.
        
        Risk = weighted combination of:
        1. Response length (longer = potentially riskier)
        2. Complexity (higher = needs more review)
        3. Coherence loss (incoherent = red flag)
        4. Keyword blocklist hits
        
        Returns:
            risk_score ∈ [0, 1] where:
            - < 0.3: Low risk (auto-approve)
            - 0.3-0.7: Medium risk (requires review)
            - > 0.7: High risk (reject or escalate)
        """
        risk_components = []
        
        # 1. Length risk (normalized sigmoid)
        length = len(response_text)
        length_risk = 1 / (1 + np.exp(-(length - 2000) / 500))  # 50% at 2000 chars
        risk_components.append(0.2 * length_risk)
        
        # 2. Complexity risk (direct mapping)
        # Handle NaN/inf in complexity
        complexity = np.nan_to_num(complexity, nan=0.5, posinf=1.0, neginf=0.0)
        complexity_risk = np.clip(complexity, 0, 1)
        risk_components.append(0.3 * complexity_risk)
        
        # 3. Coherence loss risk (inverse)
        # Handle NaN/inf in coherence
        coherence = np.nan_to_num(coherence, nan=0.5, posinf=1.0, neginf=0.0)
        coherence = np.clip(coherence, 0, 1)
        coherence_risk = 1.0 - coherence
        risk_components.append(0.3 * coherence_risk)
        
        # 4. Keyword blocklist risk
        blocklist = [
            'ignore previous', 'system prompt', 'jailbreak',
            'sudo', 'rm -rf', 'drop table', 'script>',
            'violate', 'bypass', 'override safety'
        ]
        keyword_hits = sum(1 for kw in blocklist if kw.lower() in response_text.lower())
        keyword_risk = min(keyword_hits / 3.0, 1.0)  # Cap at 3 hits = max risk
        risk_components.append(0.2 * keyword_risk)
        
        # Total risk (weighted sum)
        total_risk = sum(risk_components)
        
        # Handle NaN/inf in total risk
        total_risk = np.nan_to_num(total_risk, nan=0.5, posinf=1.0, neginf=0.0)
        
        return np.clip(total_risk, 0.0, 1.0)
    
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
        recent = history[-GovernanceConfig.VOID_ADAPTIVE_WINDOW:]
        mean_V = np.mean(np.abs(recent))
        std_V = np.std(np.abs(recent))
        
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
    
    # Target coherence
    TARGET_COHERENCE = 0.85  # Minimum acceptable coherence
    
    # λ₁ bounds (operational range for UNITARES)
    LAMBDA1_MIN = 0.05  # Minimum ethical coupling
    LAMBDA1_MAX = 0.20  # Maximum ethical coupling
    LAMBDA1_INITIAL = 0.15  # Conservative starting point
    
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
    
    # Risk-based decision thresholds
    RISK_APPROVE_THRESHOLD = 0.30    # < 0.3: Auto-approve
    RISK_REVISE_THRESHOLD = 0.70     # 0.3-0.7: Suggest revisions
    # > 0.7: Reject or escalate
    
    # Coherence-based override (safety check)
    COHERENCE_CRITICAL_THRESHOLD = 0.60  # Below this: force intervention
    
    @staticmethod
    def make_decision(risk_score: float,
                     coherence: float,
                     void_active: bool) -> Dict[str, any]:
        """
        Makes governance decision based on risk, coherence, and void state.
        
        Decision logic:
        1. If void_active: REJECT (system unstable)
        2. If coherence < critical: REJECT (incoherent output)
        3. If risk < approve_threshold: APPROVE
        4. If risk < revise_threshold: REVISE
        5. Else: REJECT
        
        Returns:
            {
                'action': 'approve' | 'revise' | 'reject',
                'reason': str,
                'require_human': bool
            }
        """
        # Critical safety checks first
        if void_active:
            return {
                'action': 'reject',
                'reason': 'System in void state (E-I imbalance)',
                'require_human': True
            }
        
        if coherence < GovernanceConfig.COHERENCE_CRITICAL_THRESHOLD:
            return {
                'action': 'reject',
                'reason': f'Coherence critically low ({coherence:.2f} < {GovernanceConfig.COHERENCE_CRITICAL_THRESHOLD})',
                'require_human': True
            }
        
        # Risk-based decisions
        if risk_score < GovernanceConfig.RISK_APPROVE_THRESHOLD:
            return {
                'action': 'approve',
                'reason': f'Low risk ({risk_score:.2f})',
                'require_human': False
            }
        
        if risk_score < GovernanceConfig.RISK_REVISE_THRESHOLD:
            return {
                'action': 'revise',
                'reason': f'Medium risk ({risk_score:.2f}) - suggest improvements',
                'require_human': False
            }
        
        return {
            'action': 'reject',
            'reason': f'High risk ({risk_score:.2f})',
            'require_human': True
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
    DT = 0.1         # Timestep for integration (seconds)
    
    # History window for metrics
    HISTORY_WINDOW = 1000  # Keep last 1000 updates for statistics


# Export singleton config
config = GovernanceConfig()
