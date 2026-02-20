"""
UNITARES Governance Framework v1.0 - Configuration
All concrete decision points implemented - no placeholders!
"""

from dataclasses import dataclass
from typing import Dict, Tuple, Optional, List
import numpy as np
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
    
    # Phi-to-risk mapping thresholds (configurable)
    # Recalibrated Dec 2025: 0.3 was too strict - typical healthy state (E=0.7, I=0.8, S=0.2)
    # gives phi=0.15, which was always "caution". Lowered to match realistic expectations.
    PHI_SAFE_THRESHOLD = 0.15     # phi >= 0.15: safe -> low risk (typical healthy state)
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
        Derive complexity from behavior rather than relying solely on self-reporting.
        
        Uses multiple signals:
        1. Response content analysis (code blocks, technical terms, tool calls)
        2. Coherence changes (large drops suggest complexity)
        3. Response length (relative to content type)
        4. Self-reported complexity (validated against derived)
        
        Args:
            response_text: Agent's response text
            reported_complexity: Self-reported complexity (optional, for validation)
            coherence_history: Recent coherence values (optional, for trend analysis)
        
        Returns:
            Derived complexity [0, 1]
        """
        complexity_signals = []
        
        # Signal 1: Content analysis (40% weight) - IMPROVED (P2)
        text_lower = response_text.lower()
        
        # Code detection: count code blocks and look for code patterns
        code_block_count = response_text.count('```')
        has_code_patterns = bool(re.search(r'\b(def|class|import|from|async|await)\b', text_lower))
        has_code = code_block_count > 0 or has_code_patterns
        
        # Tool detection: use word boundaries to avoid false positives
        has_tools = bool(re.search(r'\b(tool_call|function_call)\b', text_lower))
        
        # Technical terms: use word boundaries to avoid false positives (P2 improvement)
        # Example: "This is algorithmic thinking" won't match "\balgorithm\b"
        technical_terms = ['algorithm', 'function', 'import', 'async', 'await',
                          'recursive', 'optimization', 'optimize', 'refactor', 'architecture']
        has_technical = any(re.search(r'\b' + re.escape(term) + r'\b', text_lower) 
                          for term in technical_terms)
        
        # Multiple files: count actual file references (word boundaries)
        file_count = len(re.findall(r'\bfile\b', text_lower))
        path_count = len(re.findall(r'\bpath\b', text_lower))
        has_multiple_files = file_count > 2 or path_count > 2

        content_complexity = 0.3  # Base (increased from 0.2 - P1 fix for complex code underestimation)

        # Code complexity: scale with number of code blocks (P2 improvement)
        if has_code:
            # Base code complexity: 0.30 (increased from 0.25 - P1 fix)
            # Additional complexity for multiple code blocks: +0.05 per block (max +0.15)
            code_complexity = 0.30 + min(0.15, (code_block_count - 1) * 0.05)
            content_complexity += code_complexity
        
        if has_tools:
            content_complexity += 0.20
        if has_technical:
            content_complexity += 0.20
        if has_multiple_files:
            content_complexity += 0.15
        
        content_complexity = min(content_complexity, 1.0)
        complexity_signals.append(('content', content_complexity, 0.40))
        
        # Signal 2: Coherence trend (30% weight) - if available
        if coherence_history and len(coherence_history) >= 2:
            recent_coherence = coherence_history[-1]
            prev_coherence = coherence_history[-2] if len(coherence_history) >= 2 else recent_coherence
            # Validate for NaN/inf (risk mitigation)
            recent_coherence = np.nan_to_num(recent_coherence, nan=0.5, posinf=1.0, neginf=0.0)
            prev_coherence = np.nan_to_num(prev_coherence, nan=0.5, posinf=1.0, neginf=0.0)
            recent_coherence = np.clip(recent_coherence, 0.0, 1.0)
            prev_coherence = np.clip(prev_coherence, 0.0, 1.0)
            
            coherence_drop = max(0, prev_coherence - recent_coherence)
            # Large coherence drops suggest high complexity
            coherence_complexity = min(coherence_drop * 2.0, 1.0)  # Scale: 0.5 drop = 1.0 complexity
            # Final validation
            coherence_complexity = np.nan_to_num(coherence_complexity, nan=0.5, posinf=1.0, neginf=0.0)
            coherence_complexity = np.clip(coherence_complexity, 0.0, 1.0)
            complexity_signals.append(('coherence', float(coherence_complexity), 0.30))
        else:
            # No history: neutral
            complexity_signals.append(('coherence', 0.5, 0.30))
        
        # Signal 3: Length relative to content type (20% weight)
        length = len(response_text)
        # Code-heavy responses should be longer, text-only shorter
        if has_code:
            # Code responses: 1000-5000 chars is normal
            length_complexity = min(max(0, (length - 500) / 4500), 1.0)
        else:
            # Text responses: 500-3500 chars is normal (P3: increased from 2000)
            length_complexity = min(max(0, (length - 200) / 3300), 1.0)
        complexity_signals.append(('length', length_complexity, 0.20))
        
        # Signal 4: Self-reported complexity (10% weight) - validated
        if reported_complexity is not None:
            reported = np.clip(reported_complexity, 0.0, 1.0)
            # Validate: if reported differs significantly from derived, use conservative estimate
            derived_so_far = sum(signal * weight for _, signal, weight in complexity_signals) / sum(w for _, _, w in complexity_signals)
            if abs(reported - derived_so_far) > 0.3:
                # Large discrepancy: use conservative (higher) estimate
                reported = max(reported, derived_so_far)
            complexity_signals.append(('reported', reported, 0.10))
        else:
            # No report: neutral
            complexity_signals.append(('reported', 0.5, 0.10))
        
        # Weighted combination
        total_weight = sum(weight for _, _, weight in complexity_signals)
        if total_weight > 0:
            derived_complexity = sum(signal * weight for _, signal, weight in complexity_signals) / total_weight
        else:
            derived_complexity = 0.5  # Fallback if no weights
        
        # Final validation for NaN/inf (risk mitigation)
        derived_complexity = np.nan_to_num(derived_complexity, nan=0.5, posinf=1.0, neginf=0.0)
        derived_complexity = np.clip(derived_complexity, 0.0, 1.0)
        
        return float(derived_complexity)
    
    @staticmethod
    def estimate_risk(response_text: str, 
                     complexity: float,
                     coherence: float,
                     coherence_history: Optional[List[float]] = None,
                     reported_complexity: Optional[float] = None) -> float:
        """
        Estimates TRADITIONAL safety/quality risk score (30% of final risk).
        
        NOTE: This is only the traditional component. The final risk score
        (used in decisions) blends this with UNITARES phi-based risk:
        - Final risk = 0.7 × phi_risk + 0.3 × traditional_risk
        
        Traditional Risk = weighted combination of:
        1. Response length (relative to content type, not absolute)
        2. Complexity (derived from behavior, validated against self-report)
        3. Coherence loss (incoherent = red flag)
        4. Keyword blocklist hits
        
        Returns:
            traditional_risk_score ∈ [0, 1] (30% weight in final risk)
        """
        risk_components = []
        
        # Derive complexity from behavior (fixes self-reporting bias)
        derived_complexity = GovernanceConfig.derive_complexity(
            response_text=response_text,
            reported_complexity=reported_complexity if reported_complexity is not None else complexity,
            coherence_history=coherence_history
        )
        # Use derived complexity, but validate against reported if provided
        if reported_complexity is not None:
            discrepancy = reported_complexity - derived_complexity
            # If reported differs significantly, use conservative (higher) estimate
            if abs(discrepancy) > 0.3:
                final_complexity = max(reported_complexity, derived_complexity)
            else:
                # Close match: trust derived (more objective)
                final_complexity = derived_complexity
            
            # Log complexity derivation for tracking and calibration (P1 recommendation)
            try:
                from src.audit_log import audit_logger
                # Get agent_id from context if available, otherwise use placeholder
                # Note: agent_id should be passed through if available
                agent_id = getattr(GovernanceConfig, '_current_agent_id', 'unknown')
                audit_logger.log_complexity_derivation(
                    agent_id=agent_id,
                    reported_complexity=round(reported_complexity, 3),
                    derived_complexity=round(derived_complexity, 3),
                    final_complexity=round(final_complexity, 3),
                    discrepancy=round(discrepancy, 3),
                    details={
                        "response_length": len(response_text),
                        "has_coherence_history": coherence_history is not None and len(coherence_history) >= 2,
                        "validation_applied": abs(discrepancy) > 0.3
                    }
                )
            except Exception as e:
                # Don't fail risk calculation if logging fails
                import sys
                print(f"[WARNING] Failed to log complexity derivation: {e}", file=sys.stderr)
        else:
            final_complexity = derived_complexity
        
        # 1. Length risk (relative to content type, reduced bias)
        length = len(response_text)
        text_lower = response_text.lower()
        has_code = '```' in response_text or 'def ' in text_lower
        
        if has_code:
            # Code responses: longer is often better (more complete)
            # Only penalize extremely long (>10000 chars) or very short (<100 chars)
            if length < 100:
                length_risk = 0.3  # Too short for code
            elif length > 10000:
                length_risk = 0.4  # Very long, but not necessarily risky
            else:
                length_risk = 0.1  # Normal range for code
        else:
            # Text responses: use relative length (reduced from absolute)
            # Normal range: 200-3500 chars (P3: updated from 3000)
            if length < 200:
                length_risk = 0.2  # Too short
            elif length > 5000:
                length_risk = 0.3  # Very long
            else:
                length_risk = 0.1  # Normal range
        risk_components.append(0.15 * length_risk)  # Reduced from 0.2 (20% -> 15%)
        
        # 2. Complexity risk (using derived complexity)
        # Handle NaN/inf
        final_complexity = np.nan_to_num(final_complexity, nan=0.5, posinf=1.0, neginf=0.0)
        complexity_risk = np.clip(final_complexity, 0, 1)
        risk_components.append(0.35 * complexity_risk)  # Increased from 0.3 (30% -> 35%)
        
        # 3. Coherence loss risk (inverse)
        # Handle NaN/inf in coherence
        coherence = np.nan_to_num(coherence, nan=0.5, posinf=1.0, neginf=0.0)
        coherence = np.clip(coherence, 0, 1)
        coherence_risk = 1.0 - coherence
        risk_components.append(0.35 * coherence_risk)  # Increased from 0.3 (30% -> 35%)
        
        # 4. Keyword blocklist risk (reduced weight, context-aware)
        blocklist = [
            'ignore previous', 'system prompt', 'jailbreak',
            'sudo', 'rm -rf', 'drop table', 'script>',
            'violate', 'bypass', 'override safety'
        ]
        text_lower = response_text.lower()
        keyword_hits = 0
        # Context-aware: check for legitimate uses
        for kw in blocklist:
            if kw.lower() in text_lower:
                # Check for negation or educational context
                kw_idx = text_lower.find(kw.lower())
                context = text_lower[max(0, kw_idx-20):kw_idx+len(kw)+20]
                # Skip if in educational/negated context
                if any(term in context for term in ['don\'t', 'shouldn\'t', 'avoid', 'never', 'explain', 'example', 'note:', 'warning']):
                    continue
                keyword_hits += 1
        
        keyword_risk = min(keyword_hits / 3.0, 1.0)  # Cap at 3 hits = max risk
        risk_components.append(0.15 * keyword_risk)  # Reduced from 0.2 (20% -> 15%)
        
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
    
    # Target coherence (for PI controller)
    # Physics: V ∈ [-0.1, 0.1] → coherence ∈ [0.45, 0.55]
    # Target set to achievable upper bound (V = 0.1 → coherence = 0.55)
    TARGET_COHERENCE = 0.55  # Achievable physics ceiling (matches V=0.1)
    
    # λ₁ bounds (operational range for UNITARES)
    LAMBDA1_MIN = 0.05  # Minimum ethical coupling
    LAMBDA1_MAX = 0.20  # Maximum ethical coupling
    LAMBDA1_INITIAL = 0.15  # Conservative starting point
    
    # Confidence threshold for PI controller updates
    CONTROLLER_CONFIDENCE_THRESHOLD = 0.8  # Gate lambda1 updates when confidence < this value
    
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
    
    # Risk-based decision thresholds (recalibrated Nov 2025)
    # Adjusted to match observed risk distribution
    # NOTE: Risk score is a blend: 70% UNITARES phi-based (includes ethical drift) + 30% traditional safety
    # See governance_monitor.py estimate_risk() for details
    # UPDATED: Raised approve threshold from 0.30 to 0.35 to reduce false "revise" decisions
    # "Revise" is feedback, not blocking - agents with risk 30-35% are safe to proceed
    RISK_APPROVE_THRESHOLD = 0.35    # < 35%: Proceed without guidance
    RISK_REVISE_THRESHOLD = 0.60     # 35-60%: Proceed with guidance, >= 60%: Pause
    RISK_REJECT_THRESHOLD = 0.70     # >= 70%: Critical pause
    # Updated: Raised from 0.50 to 0.60 for better calibration with current LLMs
    # Aligns with health status threshold (0.60 for critical) for consistency
    
    # Risk blend weights (used in estimate_risk)
    RISK_PHI_WEIGHT = 0.7            # Weight for UNITARES phi-based risk (includes ethical drift)
    RISK_TRADITIONAL_WEIGHT = 0.3     # Weight for traditional safety risk (length/complexity/coherence/keywords)
    
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
        void_value: float = 0.0
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

        # Determine margin level based on distance TO threshold
        # comfortable: > 0.15 away from any threshold
        # tight: <= 0.15 away from threshold (approaching)

        if distance_to_edge > 0.15:
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
                'void_margin': void_margin
            }
        }
    
    @staticmethod
    def make_decision(risk_score: float,
                     coherence: float,
                     void_active: bool,
                     void_value: float = 0.0) -> Dict[str, any]:
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
            void_value=void_value
        )
        
        # Critical safety checks first - always pause
        if void_active:
            return {
                'action': 'pause',
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
                'reason': f'Moderate complexity ({risk_score:.1%}) - PAUSE threshold: {effective_revise_threshold:.0%}',
                'guidance': guidance,
                'margin': margin_info['margin'],
                'nearest_edge': margin_info['nearest_edge']
            }

        # High attention: pause
        return {
            'action': 'pause',
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
    DT = 0.1         # Timestep for integration (seconds)
    
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


# Export singleton config
config = GovernanceConfig()
