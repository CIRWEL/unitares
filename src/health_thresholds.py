"""
Health Thresholds for Risk-Based Status Calculation

Defines health status based on risk scores, coherence, and void state.
Provides consistent health assessment across the governance system.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Tuple, Optional


class HealthStatus(Enum):
    HEALTHY = "healthy"
    MODERATE = "moderate"
    CRITICAL = "critical"


@dataclass
class HealthThresholds:
    """Define health status based on risk score and other metrics"""
    
    # Risk-based thresholds (recalibrated Nov 2025, aligned Nov 2025)
    # Based on observed risk distribution: most agents show 30-60% risk
    # Aligned with decision threshold (0.35) to reduce confusion
    risk_healthy_max: float = 0.35    # < 35%: Healthy (aligned with RISK_APPROVE_THRESHOLD)
    risk_moderate_max: float = 0.60   # 35-60%: Moderate, 60%+: Critical
    
    # Coherence thresholds (fallback if risk not available)
    # Updated for pure thermodynamic C(V) signal (removed param_coherence blend)
    # Physics: V ∈ [-0.1, 0.1] → coherence ∈ [0.45, 0.55]
    # Mean V ≈ -0.016 → coherence ≈ 0.49 (conservative operation)
    coherence_uninitialized: float = 0.60  # Placeholder state (coherence=1.0 before first update)
    coherence_healthy_min: float = 0.52   # Achievable, top ~20% of agents (V ≈ 0.05)
    coherence_moderate_min: float = 0.48  # Below mean but acceptable (V ≈ -0.02)
    
    def get_health_status(
        self, 
        risk_score: Optional[float] = None,
        coherence: Optional[float] = None,
        void_active: bool = False
    ) -> Tuple[HealthStatus, str]:
        """
        Determine health status from metrics.
        
        Priority:
        1. void_active -> CRITICAL
        2. risk_score -> HEALTHY/MODERATE/CRITICAL
        3. coherence -> HEALTHY/MODERATE/CRITICAL (fallback)
        """
        # Void state always critical
        if void_active:
            return HealthStatus.CRITICAL, "Void state active - system instability detected"
        
        # Use attention_score (renamed from risk_score) if available
        if risk_score is not None:
            if risk_score < self.risk_healthy_max:
                return HealthStatus.HEALTHY, f"Low attention ({risk_score:.2%})"
            elif risk_score < self.risk_moderate_max:
                return HealthStatus.MODERATE, f"Typical attention ({risk_score:.2%}) - normal for development work"
            else:
                return HealthStatus.CRITICAL, f"High attention ({risk_score:.2%}) - consider simplifying approach"
        
        # Fallback to coherence if risk not available
        if coherence is not None:
            # Check for uninitialized state first (coherence = 1.0 placeholder)
            if coherence >= self.coherence_uninitialized:
                return HealthStatus.HEALTHY, f"Uninitialized state (coherence={coherence:.2f}) - agent not yet governed"
            elif coherence >= self.coherence_healthy_min:
                return HealthStatus.HEALTHY, f"High coherence ({coherence:.2f}) - performing well"
            elif coherence >= self.coherence_moderate_min:
                return HealthStatus.MODERATE, f"Typical coherence ({coherence:.2f}) - normal operation"
            else:
                return HealthStatus.CRITICAL, f"Low coherence ({coherence:.2f}) - needs attention"
        
        # Default to moderate if no metrics available
        return HealthStatus.MODERATE, "Health status unknown - metrics unavailable"
    
    def should_alert(self, risk_score: Optional[float] = None, coherence: Optional[float] = None) -> bool:
        """Determine if risk level warrants an alert"""
        if risk_score is not None:
            return risk_score >= self.risk_moderate_max
        if coherence is not None:
            return coherence < self.coherence_moderate_min
        return False

