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
    DEGRADED = "degraded" 
    CRITICAL = "critical"


@dataclass
class HealthThresholds:
    """Define health status based on risk score and other metrics"""
    
    # Risk-based thresholds (recalibrated Nov 2025)
    # Based on observed risk distribution: most agents show 30-60% risk
    risk_healthy_max: float = 0.30    # < 30%: Healthy
    risk_degraded_max: float = 0.60   # 30-60%: Degraded, 60%+: Critical
    
    # Coherence thresholds (fallback if risk not available)
    # Updated for pure thermodynamic C(V) signal (removed param_coherence blend)
    # C(V) typically ranges 0.3-0.7 in normal operation
    coherence_healthy_min: float = 0.60  # Recalibrated for pure C(V)
    coherence_degraded_min: float = 0.40  # Recalibrated for pure C(V)
    
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
        2. risk_score -> HEALTHY/DEGRADED/CRITICAL
        3. coherence -> HEALTHY/DEGRADED/CRITICAL (fallback)
        """
        # Void state always critical
        if void_active:
            return HealthStatus.CRITICAL, "Void state active - system instability detected"
        
        # Use risk score if available
        if risk_score is not None:
            if risk_score < self.risk_healthy_max:
                return HealthStatus.HEALTHY, f"Low risk ({risk_score:.2%})"
            elif risk_score < self.risk_degraded_max:
                return HealthStatus.DEGRADED, f"Medium risk ({risk_score:.2%}) - monitoring closely"
            else:
                return HealthStatus.CRITICAL, f"High risk ({risk_score:.2%}) - intervention may be needed"
        
        # Fallback to coherence if risk not available
        if coherence is not None:
            if coherence >= self.coherence_healthy_min:
                return HealthStatus.HEALTHY, f"High coherence ({coherence:.2f})"
            elif coherence >= self.coherence_degraded_min:
                return HealthStatus.DEGRADED, f"Moderate coherence ({coherence:.2f}) - monitoring"
            else:
                return HealthStatus.CRITICAL, f"Low coherence ({coherence:.2f}) - system degradation"
        
        # Default to degraded if no metrics available
        return HealthStatus.DEGRADED, "Health status unknown - metrics unavailable"
    
    def should_alert(self, risk_score: Optional[float] = None, coherence: Optional[float] = None) -> bool:
        """Determine if risk level warrants an alert"""
        if risk_score is not None:
            return risk_score >= self.risk_degraded_max
        if coherence is not None:
            return coherence < self.coherence_degraded_min
        return False

