"""
UNITARES Governance Monitor v2.0 - Core Implementation
Complete thermodynamic governance framework with all decision points implemented.

Now uses governance_core module (canonical UNITARES Phase-3 implementation)
while maintaining backward-compatible MCP interface.

Version History:
- v1.0: Used unitaires_core directly
- v2.0: Migrated to governance_core (single source of truth for dynamics)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from collections import Counter
import json

from config.governance_config import config

# Import UNITARES Phase-3 engine from governance_core (v2.0)
# Core dynamics are now in governance_core module
import sys
from pathlib import Path

# Add project root to path for governance_core
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import core dynamics from governance_core (canonical implementation)
from governance_core import (
    State, Theta, Weights,
    DEFAULT_STATE, DEFAULT_THETA, DEFAULT_WEIGHTS,
    step_state, coherence,
    lambda1 as lambda1_from_theta,
    phi_objective, verdict_from_phi,
    DynamicsParams, DEFAULT_PARAMS
)

# Import analysis/optimization functions from unitaires_core
# These are research tools, not core dynamics
unitaires_server_path = Path(__file__).parent / "unitaires-server"
if str(unitaires_server_path) not in sys.path:
    sys.path.insert(0, str(unitaires_server_path))

from unitaires_core import (
    approximate_stability_check,
    suggest_theta_update,
)


@dataclass
class GovernanceState:
    """Wrapper around UNITARES Phase-3 State with additional tracking"""
    
    # UNITARES Phase-3 state (internal engine)
    unitaires_state: State = field(default_factory=lambda: State(
        E=DEFAULT_STATE.E,
        I=DEFAULT_STATE.I,
        S=DEFAULT_STATE.S,
        V=DEFAULT_STATE.V
    ))
    unitaires_theta: Theta = field(default_factory=lambda: Theta(
        C1=DEFAULT_THETA.C1,
        eta1=DEFAULT_THETA.eta1
    ))
    
    # Derived metrics (computed from UNITARES state)
    coherence: float = 1.0      # Computed from UNITARES coherence function
    void_active: bool = False     # Whether in void state (|V| > threshold)
    
    # History tracking
    time: float = 0.0
    update_count: int = 0
    
    # Rolling statistics for adaptive thresholds
    V_history: List[float] = field(default_factory=list)
    coherence_history: List[float] = field(default_factory=list)
    risk_history: List[float] = field(default_factory=list)
    decision_history: List[str] = field(default_factory=list)  # Track approve/revise/reject decisions
    
    # Compatibility: expose E, I, S, V as properties for backward compatibility
    @property
    def E(self) -> float:
        return self.unitaires_state.E
    
    @property
    def I(self) -> float:
        return self.unitaires_state.I
    
    @property
    def S(self) -> float:
        return self.unitaires_state.S
    
    @property
    def V(self) -> float:
        return self.unitaires_state.V
    
    @property
    def lambda1(self) -> float:
        """Get lambda1 from UNITARES theta using governance_core"""
        return lambda1_from_theta(self.unitaires_theta, DEFAULT_PARAMS)
    
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
        
        # Initialize UNITARES Phase-3 state and theta
        self.state.unitaires_state = State(**{
            'E': DEFAULT_STATE.E,
            'I': DEFAULT_STATE.I,
            'S': DEFAULT_STATE.S,
            'V': DEFAULT_STATE.V
        })
        self.state.unitaires_theta = Theta(**{
            'C1': DEFAULT_THETA.C1,
            'eta1': DEFAULT_THETA.eta1
        })

        # Previous state for drift calculation
        self.prev_parameters: Optional[np.ndarray] = None

        # Timestamps for agent lifecycle tracking
        self.created_at = datetime.now()
        self.last_update = datetime.now()

        print(f"[UNITARES v2.0 + governance_core] Initialized monitor for agent: {agent_id}")
        print(f"  λ₁ initial: {self.state.lambda1:.4f}")
        print(f"  Void threshold: {config.VOID_THRESHOLD_INITIAL:.4f}")
    
    def coherence_function(self, V: float) -> float:
        """
        Bounded coherence function C(V) using governance_core coherence function.

        Delegates to canonical governance_core.coherence() function.
        """
        return coherence(V, self.state.unitaires_theta, DEFAULT_PARAMS)
    
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
        Updates UNITARES dynamics for one timestep using governance_core engine.

        This now uses the canonical governance_core.step_state() implementation.

        Agent state should contain:
        - parameters: array-like, agent parameters
        - ethical_drift: array-like, ethical signals (delta_eta)
        - (optional) response_text: str for risk estimation
        - (optional) complexity: float
        """
        if dt is None:
            dt = config.DT

        # Extract agent information
        parameters = np.array(agent_state.get('parameters', []))
        ethical_signals = np.array(agent_state.get('ethical_drift', [0.0, 0.0, 0.0]))

        # Validate and normalize ethical_drift (delta_eta) to list
        if len(ethical_signals) == 0:
            delta_eta = [0.0, 0.0, 0.0]
        else:
            # Convert to list and ensure it's the right length (UNITARES expects list)
            delta_eta = ethical_signals.tolist() if len(ethical_signals) <= 3 else ethical_signals[:3].tolist()
            # Pad if needed
            while len(delta_eta) < 3:
                delta_eta.append(0.0)

        # Replace NaN/inf with zeros
        delta_eta = [0.0 if (np.isnan(x) or np.isinf(x)) else float(x) for x in delta_eta]

        # Store parameters for coherence calculation
        param_coherence = self.compute_parameter_coherence(parameters, self.prev_parameters)
        self.prev_parameters = parameters.copy() if len(parameters) > 0 else None

        # Use governance_core step_state() to evolve state (CANONICAL DYNAMICS)
        self.state.unitaires_state = step_state(
            state=self.state.unitaires_state,
            theta=self.state.unitaires_theta,
            delta_eta=delta_eta,
            dt=dt,
            noise_S=0.0,  # Can add noise if needed
            params=DEFAULT_PARAMS
        )

        # Update coherence from governance_core coherence function
        C_V = coherence(self.state.V, self.state.unitaires_theta, DEFAULT_PARAMS)
        # Blend UNITARES coherence with parameter coherence for monitoring
        self.state.coherence = 0.7 * C_V + 0.3 * param_coherence
        self.state.coherence = np.clip(self.state.coherence, 0.0, 1.0)

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
        Updates θ (theta) using UNITARES Phase-3 suggest_theta_update().
        
        This updates theta which affects lambda1 via lambda1_from_theta().
        
        Returns updated λ₁ value.
        """
        # Use UNITARES Phase-3 theta update suggestion
        # Horizon: look ahead 10 timesteps
        # Step: small perturbation for gradient estimation
        theta_update = suggest_theta_update(
            theta=self.state.unitaires_theta,
            state=self.state.unitaires_state,
            horizon=10.0 * config.DT,
            step=0.01
        )
        
        # Update theta (projected to valid bounds)
        old_theta = self.state.unitaires_theta
        new_theta_dict = theta_update['theta_new']
        self.state.unitaires_theta = Theta(**new_theta_dict)
        
        # Get lambda1 values
        old_lambda1 = lambda1_from_theta(old_theta, DEFAULT_PARAMS)
        new_lambda1 = self.state.lambda1
        
        # Log significant changes
        if abs(new_lambda1 - old_lambda1) > 0.01:
            print(f"[θ Update] λ₁: {old_lambda1:.4f} → {new_lambda1:.4f} "
                  f"(C1={old_theta.C1:.3f}→{self.state.unitaires_theta.C1:.3f}, "
                  f"η1={old_theta.eta1:.3f}→{self.state.unitaires_theta.eta1:.3f})")
        
        return new_lambda1
    
    def estimate_risk(self, agent_state: Dict, score_result: Dict = None) -> float:
        """
        Estimates risk score using governance_core phi_objective and verdict_from_phi.

        Uses UNITARES phi objective and verdict, then maps to risk score [0, 1].

        Args:
            agent_state: Agent state dictionary
            score_result: Optional pre-computed score_result to avoid recomputation
        """
        # Extract delta_eta (ethical drift) if score_result not provided
        if score_result is None:
            ethical_signals = np.array(agent_state.get('ethical_drift', [0.0, 0.0, 0.0]))
            if len(ethical_signals) == 0:
                delta_eta = [0.0, 0.0, 0.0]
            else:
                delta_eta = ethical_signals.tolist() if len(ethical_signals) <= 3 else ethical_signals[:3].tolist()
                while len(delta_eta) < 3:
                    delta_eta.append(0.0)

            # Use governance_core phi_objective and verdict_from_phi
            phi = phi_objective(
                state=self.state.unitaires_state,
                delta_eta=delta_eta,
                weights=DEFAULT_WEIGHTS
            )
            verdict = verdict_from_phi(phi)

            score_result = {
                'phi': phi,
                'verdict': verdict,
            }
        
        # Map UNITARES verdict to risk score [0, 1]
        # verdict: "safe" -> low risk, "caution" -> medium risk, "high-risk" -> high risk
        phi = score_result['phi']
        verdict = score_result['verdict']
        
        # Convert phi to risk score: phi is higher for safer states
        # phi >= 0.3: safe -> risk ~ 0.0-0.3
        # phi >= 0.0: caution -> risk ~ 0.3-0.7
        # phi < 0.0: high-risk -> risk ~ 0.7-1.0
        if phi >= 0.3:
            # Safe: map phi [0.3, inf] to risk [0.0, 0.3]
            risk = max(0.0, 0.3 - (phi - 0.3) * 0.5)  # Decreasing risk as phi increases
        elif phi >= 0.0:
            # Caution: map phi [0.0, 0.3] to risk [0.3, 0.7]
            risk = 0.3 + (0.3 - phi) / 0.3 * 0.4  # Linear interpolation
        else:
            # High-risk: map phi [-inf, 0.0] to risk [0.7, 1.0]
            risk = min(1.0, 0.7 + abs(phi) * 2.0)  # Increasing risk as phi becomes more negative
        
        # Also blend with traditional risk estimation for backward compatibility
        response_text = agent_state.get('response_text', '')
        complexity = agent_state.get('complexity', 0.5)
        traditional_risk = config.estimate_risk(response_text, complexity, self.state.coherence)
        
        # Weighted combination: 70% UNITARES phi-based, 30% traditional
        risk = 0.7 * risk + 0.3 * traditional_risk
        
        # Update history
        self.state.risk_history.append(risk)
        if len(self.state.risk_history) > config.HISTORY_WINDOW:
            self.state.risk_history = self.state.risk_history[-config.HISTORY_WINDOW:]
        
        return float(np.clip(risk, 0.0, 1.0))
    
    def make_decision(self, risk_score: float, unitares_verdict: str = None) -> Dict:
        """
        Makes governance decision using UNITARES Phase-3 verdict and config.make_decision()
        
        If unitares_verdict is provided, it influences the decision:
        - "safe" -> bias toward approve
        - "caution" -> bias toward revise
        - "high-risk" -> bias toward reject
        
        Returns decision dict with action, reason, require_human.
        """
        # Use UNITARES verdict to influence decision if available
        if unitares_verdict == "high-risk":
            # Override: high-risk verdict -> reject
            return {
                'action': 'reject',
                'reason': f'UNITARES high-risk verdict (risk_score={risk_score:.2f})',
                'require_human': True
            }
        elif unitares_verdict == "caution":
            # Bias toward revise for caution
            if risk_score < config.RISK_APPROVE_THRESHOLD:
                # Low risk but caution -> still approve but note caution
                decision = config.make_decision(
                    risk_score=risk_score,
                    coherence=self.state.coherence,
                    void_active=self.state.void_active
                )
                if decision['action'] == 'approve':
                    decision['reason'] += ' (UNITARES caution noted)'
                return decision
            else:
                # Medium/high risk + caution -> revise or reject
                return config.make_decision(
                    risk_score=risk_score,
                    coherence=self.state.coherence,
                    void_active=self.state.void_active
                )
        else:
            # Safe verdict or no verdict: use standard decision logic
            return config.make_decision(
                risk_score=risk_score,
                coherence=self.state.coherence,
                void_active=self.state.void_active
            )
    
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
        
        # Step 4: Estimate risk (also gets UNITARES verdict)
        # Get UNITARES verdict for decision making using governance_core
        ethical_signals = np.array(agent_state.get('ethical_drift', [0.0, 0.0, 0.0]))
        if len(ethical_signals) == 0:
            delta_eta = [0.0, 0.0, 0.0]
        else:
            delta_eta = ethical_signals.tolist() if len(ethical_signals) <= 3 else ethical_signals[:3].tolist()
            while len(delta_eta) < 3:
                delta_eta.append(0.0)

        # Use governance_core phi_objective and verdict_from_phi
        phi = phi_objective(
            state=self.state.unitaires_state,
            delta_eta=delta_eta,
            weights=DEFAULT_WEIGHTS
        )
        unitares_verdict = verdict_from_phi(phi)
        score_result = {'phi': phi, 'verdict': unitares_verdict}
        
        # Estimate risk (uses score_result internally to avoid recomputation)
        risk_score = self.estimate_risk(agent_state, score_result=score_result)
        
        # Step 5: Make decision (using UNITARES verdict)
        decision = self.make_decision(risk_score, unitares_verdict=unitares_verdict)
        
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

        # Check stability using UNITARES Phase-3 approximate_stability_check()
        stability_result = approximate_stability_check(
            theta=self.state.unitaires_theta,
            samples=200,
            steps_per_sample=20,
            dt=config.DT
        )
        
        return {
            'agent_id': self.agent_id,
            'state': self.state.to_dict(),
            'status': 'healthy' if not self.state.void_active else 'critical',
            'sampling_params': config.lambda_to_params(self.state.lambda1),
            'history_size': len(self.state.V_history),
            'mean_risk': float(np.mean(self.state.risk_history)) if self.state.risk_history else 0.0,
            'void_frequency': float(np.mean([float(abs(v) > config.VOID_THRESHOLD_INITIAL)
                                            for v in self.state.V_history])) if self.state.V_history else 0.0,
            'decision_statistics': decision_counts,
            'stability': {
                'stable': stability_result['stable'],
                'alpha_estimate': stability_result['alpha_estimate'],
                'violations': stability_result['violations'],
                'notes': stability_result['notes']
            }
        }

    @staticmethod
    def get_eisv_labels() -> Dict:
        """Returns EISV metric labels and descriptions for API documentation"""
        return {
            'E': {
                'label': 'Energy',
                'description': 'Exploration capacity',
                'range': '[0.0, 1.0]'
            },
            'I': {
                'label': 'Information Integrity',
                'description': 'Preservation measure',
                'range': '[0.0, 1.0]'
            },
            'S': {
                'label': 'Entropy',
                'description': 'Uncertainty / ethical drift',
                'range': '[0.0, 1.0]'
            },
            'V': {
                'label': 'Void Integral',
                'description': 'E-I balance measure',
                'range': '(-inf, +inf)'
            }
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
