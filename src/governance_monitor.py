"""
UNITARES Governance Monitor v1.0 - Core Implementation
Complete thermodynamic governance framework with all decision points implemented.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from collections import Counter
import json

from config.governance_config import config


@dataclass
class GovernanceState:
    """Complete UNITARES thermodynamic state"""
    
    # Core state variables [0, 1]
    E: float = 0.5  # Energy (exploration capacity)
    I: float = 0.9  # Information Integrity
    S: float = 0.5  # Entropy (uncertainty)
    V: float = 0.0  # Void Integral (E-I balance)
    
    # Derived metrics
    coherence: float = 1.0      # Bounded coherence function
    void_active: bool = False   # Whether in void state
    
    # Adaptive parameters
    lambda1: float = config.LAMBDA1_INITIAL  # Ethical coupling parameter
    pi_integral: float = 0.0                  # PI controller integral state
    
    # History tracking
    time: float = 0.0
    update_count: int = 0
    
    # Rolling statistics for adaptive thresholds
    V_history: List[float] = field(default_factory=list)
    coherence_history: List[float] = field(default_factory=list)
    risk_history: List[float] = field(default_factory=list)
    decision_history: List[str] = field(default_factory=list)  # Track approve/revise/reject decisions
    
    def to_dict(self) -> Dict:
        """Export state as dictionary"""
        return {
            'E': float(self.E),
            'I': float(self.I),
            'S': float(self.S),
            'V': float(self.V),
            'coherence': float(self.coherence),
            'lambda1': float(self.lambda1),
            'void_active': bool(self.void_active),
            'time': float(self.time),
            'update_count': int(self.update_count)
        }


class UNITARESMonitor:
    """
    UNITARES v1.0 Governance Monitor
    
    Implements complete thermodynamic governance with:
    - 4D state evolution (E, I, S, V)
    - Risk estimation from agent behavior
    - Adaptive λ₁ via PI controller
    - Void detection with adaptive thresholds
    - Decision logic (approve/revise/reject)
    """
    
    def __init__(self, agent_id: str):
        """Initialize monitor for a specific agent"""
        self.agent_id = agent_id
        self.state = GovernanceState()

        # Previous state for coherence calculation
        self.prev_parameters: Optional[np.ndarray] = None

        # Timestamps for agent lifecycle tracking
        self.created_at = datetime.now()
        self.last_update = datetime.now()

        print(f"[UNITARES v1.0] Initialized monitor for agent: {agent_id}")
        print(f"  λ₁ initial: {self.state.lambda1:.4f}")
        print(f"  Void threshold: {config.VOID_THRESHOLD_INITIAL:.4f}")
    
    def coherence_function(self, V: float) -> float:
        """
        Bounded coherence function C(V) ∈ [0, C_max]
        
        C(V) = (C_max / 2) * (1 + tanh(V))
        
        Properties:
        - Smooth, bounded, Lipschitz continuous
        - C(0) = C_max/2 (baseline)
        - C(V) → C_max as V → ∞
        - C(V) → 0 as V → -∞
        """
        return (config.C_MAX / 2.0) * (1.0 + np.tanh(V))
    
    def compute_ethical_drift(self,
                             current_params: np.ndarray,
                             prev_params: Optional[np.ndarray]) -> float:
        """
        Computes ethical drift ||Δη||² from parameter changes.

        If no previous parameters, returns 0 (no drift yet).
        Otherwise: ||Δη||² = ||θ_t - θ_{t-1}||² / dim
        """
        if prev_params is None or len(current_params) != len(prev_params):
            return 0.0

        # Guard against empty parameter arrays (division by zero)
        if len(current_params) == 0:
            return 0.0

        # Check for NaN or inf in inputs
        if np.any(np.isnan(current_params)) or np.any(np.isinf(current_params)):
            return 0.0
        if np.any(np.isnan(prev_params)) or np.any(np.isinf(prev_params)):
            return 0.0

        delta = current_params - prev_params
        drift_squared = np.sum(delta ** 2) / len(delta)

        # Check for NaN/inf in result
        if np.isnan(drift_squared) or np.isinf(drift_squared):
            return 0.0

        return float(drift_squared)

    def compute_parameter_coherence(self,
                                    current_params: np.ndarray,
                                    prev_params: Optional[np.ndarray]) -> float:
        """
        Computes coherence from parameter stability.

        Coherence = exp(-||Δθ|| / scale) where scale controls sensitivity.

        Properties:
        - Identical parameters (Δθ = 0) → coherence = 1.0
        - Small changes → coherence ≈ 0.85-0.95
        - Large changes → coherence → 0

        Returns coherence ∈ [0, 1]
        """
        if prev_params is None or len(current_params) != len(prev_params):
            return 1.0  # First call, no history, perfect coherence

        # Guard against empty parameter arrays (division by zero)
        if len(current_params) == 0:
            return 1.0  # No parameters = perfect coherence (no change possible)

        # Check for NaN or inf in inputs
        if np.any(np.isnan(current_params)) or np.any(np.isinf(current_params)):
            return 0.5  # Default to moderate coherence if inputs invalid
        if np.any(np.isnan(prev_params)) or np.any(np.isinf(prev_params)):
            return 0.5  # Default to moderate coherence if inputs invalid

        # Compute parameter change magnitude
        delta = current_params - prev_params
        distance = np.sqrt(np.sum(delta ** 2) / len(delta))

        # Check for NaN/inf in distance
        if np.isnan(distance) or np.isinf(distance):
            return 0.5  # Default to moderate coherence

        # Convert distance to coherence using exponential decay
        # Scale factor of 0.1 gives good sensitivity:
        # - distance = 0.0 → coherence = 1.0
        # - distance = 0.01 → coherence ≈ 0.90
        # - distance = 0.05 → coherence ≈ 0.61
        # - distance = 0.10 → coherence ≈ 0.37
        scale = 0.1
        coherence = np.exp(-distance / scale)

        # Final NaN/inf check
        if np.isnan(coherence) or np.isinf(coherence):
            return 0.5  # Default to moderate coherence

        return float(coherence)
    
    def update_dynamics(self, 
                       agent_state: Dict,
                       dt: float = None) -> None:
        """
        Updates UNITARES dynamics for one timestep.
        
        Agent state should contain:
        - parameters: array-like, agent parameters
        - ethical_drift: array-like, ethical signals
        - (optional) response_text: str for risk estimation
        - (optional) complexity: float
        """
        if dt is None:
            dt = config.DT
        
        # Extract agent information
        parameters = np.array(agent_state.get('parameters', []))
        ethical_signals = np.array(agent_state.get('ethical_drift', []))

        # Validate inputs - ensure parameters is not empty and has valid values
        if len(parameters) == 0:
            # Default to zero-filled 128-dim vector if empty
            parameters = np.zeros(128)
        elif len(parameters) < 128:
            # Pad with zeros if shorter than expected
            parameters = np.pad(parameters, (0, max(0, 128 - len(parameters))), mode='constant')
        elif len(parameters) > 128:
            # Truncate if longer
            parameters = parameters[:128]

        # Replace NaN/inf with zeros
        parameters = np.nan_to_num(parameters, nan=0.0, posinf=0.0, neginf=0.0)
        ethical_signals = np.nan_to_num(ethical_signals, nan=0.0, posinf=0.0, neginf=0.0)

        # Compute ethical drift magnitude and parameter coherence
        drift_sq = self.compute_ethical_drift(parameters, self.prev_parameters)
        param_coherence = self.compute_parameter_coherence(parameters, self.prev_parameters)
        self.prev_parameters = parameters.copy()

        # Current state
        E, I, S, V = self.state.E, self.state.I, self.state.S, self.state.V

        # Compute thermodynamic coherence C(V) for dynamics (internal use)
        C_V = self.coherence_function(V)
        
        # UNITARES dynamics (from v4.1)
        dE_dt = (config.ALPHA * (I - E) 
                 - config.BETA_E * E * S 
                 + self.state.lambda1 * E * drift_sq)  # Use current λ₁
        
        dI_dt = (-config.K * S 
                 + config.BETA_I * I * C_V 
                 - config.GAMMA_I * I * (1 - I))
        
        dS_dt = (-config.MU * S 
                 + self.state.lambda1 * drift_sq 
                 - config.LAMBDA2 * C_V)
        
        dV_dt = config.KAPPA * (E - I) - config.DELTA * V
        
        # Euler integration
        E_new = E + dE_dt * dt
        I_new = I + dI_dt * dt
        S_new = S + dS_dt * dt
        V_new = V + dV_dt * dt
        
        # Clamp to valid ranges and check for NaN/inf
        E_new = np.nan_to_num(E_new, nan=0.5, posinf=1.0, neginf=0.0)
        I_new = np.nan_to_num(I_new, nan=0.9, posinf=1.0, neginf=0.0)
        S_new = np.nan_to_num(S_new, nan=0.5, posinf=1.0, neginf=0.0)
        V_new = np.nan_to_num(V_new, nan=0.0, posinf=1.0, neginf=-1.0)

        self.state.E = np.clip(E_new, 0.0, 1.0)
        self.state.I = np.clip(I_new, 0.0, 1.0)
        self.state.S = np.clip(S_new, 0.0, 1.0)
        self.state.V = float(V_new)  # V can be negative

        # Update coherence (use parameter-based coherence for monitoring)
        # Ensure coherence is valid
        param_coherence = np.nan_to_num(param_coherence, nan=0.5, posinf=1.0, neginf=0.0)
        self.state.coherence = np.clip(param_coherence, 0.0, 1.0)
        
        # Update history
        self.state.V_history.append(self.state.V)
        self.state.coherence_history.append(self.state.coherence)
        
        # Trim history to window
        if len(self.state.V_history) > config.HISTORY_WINDOW:
            self.state.V_history = self.state.V_history[-config.HISTORY_WINDOW:]
        if len(self.state.coherence_history) > config.HISTORY_WINDOW:
            self.state.coherence_history = self.state.coherence_history[-config.HISTORY_WINDOW:]
        
        # Update time
        self.state.time += dt
        self.state.update_count += 1
    
    def check_void_state(self) -> bool:
        """
        Checks if system is in void state: |V| > threshold

        Uses adaptive threshold based on recent history.
        """
        V_history = np.array(self.state.V_history) if self.state.V_history else np.array([self.state.V])
        threshold = config.get_void_threshold(V_history, adaptive=True)

        # Convert numpy bool to Python bool for JSON serialization
        void_active = bool(abs(self.state.V) > threshold)
        self.state.void_active = void_active

        return void_active
    
    def update_lambda1(self) -> float:
        """
        Updates λ₁ using PI controller.
        
        Target: Keep void_freq near 2% and coherence above 85%
        
        Returns updated λ₁ value.
        """
        # Compute void frequency over recent history
        if len(self.state.V_history) < 10:
            void_freq = 0.0
        else:
            recent_V = np.array(self.state.V_history[-100:])  # Last 100 updates
            threshold = config.get_void_threshold(recent_V, adaptive=True)
            void_events = np.sum(np.abs(recent_V) > threshold)
            void_freq = void_events / len(recent_V)
        
        # Current coherence
        coherence = self.state.coherence
        
        # PI controller update
        new_lambda1, new_integral = config.pi_update(
            lambda1_current=self.state.lambda1,
            void_freq_current=void_freq,
            void_freq_target=config.TARGET_VOID_FREQ,
            coherence_current=coherence,
            coherence_target=config.TARGET_COHERENCE,
            integral_state=self.state.pi_integral,
            dt=config.DT
        )
        
        # Update state
        old_lambda1 = self.state.lambda1
        self.state.lambda1 = new_lambda1
        self.state.pi_integral = new_integral
        
        # Log significant changes
        if abs(new_lambda1 - old_lambda1) > 0.01:
            print(f"[λ₁ Update] {old_lambda1:.4f} → {new_lambda1:.4f} "
                  f"(void_freq={void_freq:.3f}, coherence={coherence:.3f})")
        
        return new_lambda1
    
    def estimate_risk(self, agent_state: Dict) -> float:
        """
        Estimates risk score for current agent behavior.
        
        Uses config.estimate_risk() with agent state information.
        """
        response_text = agent_state.get('response_text', '')
        complexity = agent_state.get('complexity', 0.5)
        coherence = self.state.coherence
        
        risk = config.estimate_risk(response_text, complexity, coherence)
        
        # Update history
        self.state.risk_history.append(risk)
        if len(self.state.risk_history) > config.HISTORY_WINDOW:
            self.state.risk_history = self.state.risk_history[-config.HISTORY_WINDOW:]
        
        return risk
    
    def make_decision(self, risk_score: float) -> Dict:
        """
        Makes governance decision using config.make_decision()
        
        Returns decision dict with action, reason, require_human.
        """
        decision = config.make_decision(
            risk_score=risk_score,
            coherence=self.state.coherence,
            void_active=self.state.void_active
        )
        
        return decision
    
    def process_update(self, agent_state: Dict) -> Dict:
        """
        Complete governance cycle: Update → Adapt → Decide

        This is the main API method called by the MCP server.

        Returns:
        {
            'status': 'healthy' | 'degraded' | 'critical',
            'decision': {...},
            'metrics': {...},
            'sampling_params': {...}
        }
        """
        # Update timestamp
        self.last_update = datetime.now()

        # Step 1: Update thermodynamic state
        self.update_dynamics(agent_state)
        
        # Step 2: Check void state
        void_active = self.check_void_state()
        
        # Step 3: Update λ₁ (every N updates)
        if self.state.update_count % 10 == 0:  # Update λ₁ every 10 cycles
            self.update_lambda1()
        
        # Step 4: Estimate risk
        risk_score = self.estimate_risk(agent_state)
        
        # Step 5: Make decision
        decision = self.make_decision(risk_score)
        
        # Track decision history for governance auditing
        # Backward compatibility: ensure decision_history exists (for instances created before this feature)
        if not hasattr(self.state, 'decision_history'):
            self.state.decision_history = []
        self.state.decision_history.append(decision['action'])
        if len(self.state.decision_history) > config.HISTORY_WINDOW:
            self.state.decision_history = self.state.decision_history[-config.HISTORY_WINDOW:]
        
        # Step 6: Get sampling parameters for next generation
        sampling_params = config.lambda_to_params(self.state.lambda1)
        
        # Determine overall status
        if void_active or self.state.coherence < config.COHERENCE_CRITICAL_THRESHOLD:
            status = 'critical'
        elif risk_score > config.RISK_REVISE_THRESHOLD:
            status = 'degraded'
        else:
            status = 'healthy'
        
        return {
            'status': status,
            'decision': decision,
            'metrics': {
                'E': float(self.state.E),
                'I': float(self.state.I),
                'S': float(self.state.S),
                'V': float(self.state.V),
                'coherence': float(self.state.coherence),
                'lambda1': float(self.state.lambda1),
                'risk_score': float(risk_score),
                'void_active': bool(void_active),
                'time': float(self.state.time),
                'updates': int(self.state.update_count)
            },
            'sampling_params': sampling_params,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_metrics(self) -> Dict:
        """Returns current governance metrics"""
        # Calculate decision statistics
        decision_counts = {}
        decision_history = getattr(self.state, 'decision_history', [])
        if decision_history:
            counts = Counter(decision_history)
            decision_counts = {
                'approve': counts.get('approve', 0),
                'revise': counts.get('revise', 0),
                'reject': counts.get('reject', 0),
                'total': len(decision_history)
            }
        
        return {
            'agent_id': self.agent_id,
            'state': self.state.to_dict(),
            'status': 'healthy' if not self.state.void_active else 'critical',
            'sampling_params': config.lambda_to_params(self.state.lambda1),
            'history_size': len(self.state.V_history),
            'mean_risk': float(np.mean(self.state.risk_history)) if self.state.risk_history else 0.0,
            'void_frequency': float(np.mean([float(abs(v) > config.VOID_THRESHOLD_INITIAL)
                                            for v in self.state.V_history])) if self.state.V_history else 0.0,
            'decision_statistics': decision_counts
        }
    
    def export_history(self, format: str = 'json') -> str:
        """Exports complete history for analysis"""
        import csv
        import io
        
        # Backward compatibility: ensure decision_history exists
        decision_history = getattr(self.state, 'decision_history', [])
        
        history = {
            'agent_id': self.agent_id,
            'E_history': [self.state.E],  # Would need to track these
            'I_history': [self.state.I],
            'S_history': [self.state.S],
            'V_history': self.state.V_history,
            'coherence_history': self.state.coherence_history,
            'risk_history': self.state.risk_history,
            'decision_history': decision_history,
            'lambda1_final': self.state.lambda1,
            'total_updates': self.state.update_count,
            'total_time': self.state.time
        }
        
        if format == 'json':
            return json.dumps(history, indent=2)
        elif format == 'csv':
            # Convert to CSV format
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['update', 'E', 'I', 'S', 'V', 'coherence', 'risk', 'decision', 'lambda1'])
            
            # Write data rows
            num_rows = len(self.state.V_history)
            for i in range(num_rows):
                row = [
                    i + 1,
                    self.state.E if i == num_rows - 1 else '',  # Only current E
                    self.state.I if i == num_rows - 1 else '',  # Only current I
                    self.state.S if i == num_rows - 1 else '',  # Only current S
                    self.state.V_history[i] if i < len(self.state.V_history) else '',
                    self.state.coherence_history[i] if i < len(self.state.coherence_history) else '',
                    self.state.risk_history[i] if i < len(self.state.risk_history) else '',
                    decision_history[i] if i < len(decision_history) else '',
                    self.state.lambda1 if i == num_rows - 1 else ''  # Only final lambda1
                ]
                writer.writerow(row)
            
            # Add summary row
            writer.writerow([])
            writer.writerow(['Summary', '', '', '', '', '', '', '', ''])
            writer.writerow(['agent_id', self.agent_id, '', '', '', '', '', '', ''])
            writer.writerow(['total_updates', self.state.update_count, '', '', '', '', '', '', ''])
            writer.writerow(['total_time', self.state.time, '', '', '', '', '', '', ''])
            writer.writerow(['lambda1_final', self.state.lambda1, '', '', '', '', '', '', ''])
            
            return output.getvalue()
        else:
            raise ValueError(f"Unsupported format: {format}")


# Example usage
if __name__ == "__main__":
    # Create monitor for test agent
    monitor = UNITARESMonitor(agent_id="test_agent")
    
    # Simulate some updates
    for i in range(100):
        agent_state = {
            'parameters': np.random.randn(128) * 0.01,  # Small random changes
            'ethical_drift': np.random.rand(3) * 0.1,
            'response_text': "This is a test response." * (i % 10),
            'complexity': 0.3 + 0.1 * (i % 5)
        }
        
        result = monitor.process_update(agent_state)
        
        if i % 20 == 0:
            print(f"\n[Update {i}]")
            print(f"  Status: {result['status']}")
            print(f"  Decision: {result['decision']['action']}")
            print(f"  Metrics: E={result['metrics']['E']:.3f}, "
                  f"I={result['metrics']['I']:.3f}, "
                  f"V={result['metrics']['V']:.3f}, "
                  f"λ₁={result['metrics']['lambda1']:.3f}")
    
    # Get final metrics
    print("\n" + "="*60)
    print("Final Metrics:")
    print(json.dumps(monitor.get_metrics(), indent=2))
