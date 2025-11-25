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
import sys

from config.governance_config import config

# Import audit logging and calibration for accountability and self-awareness
from src.audit_log import audit_logger
from src.calibration import calibration_checker

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
    E_history: List[float] = field(default_factory=list)  # Energy history
    I_history: List[float] = field(default_factory=list)  # Information integrity history
    S_history: List[float] = field(default_factory=list)  # Entropy history
    V_history: List[float] = field(default_factory=list)  # Void integral history
    coherence_history: List[float] = field(default_factory=list)
    risk_history: List[float] = field(default_factory=list)
    decision_history: List[str] = field(default_factory=list)  # Track approve/revise/reject decisions
    timestamp_history: List[str] = field(default_factory=list)  # Track timestamps for each update
    
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
    
    def to_dict_with_history(self) -> Dict:
        """Export state with full history for persistence"""
        return {
            # Current state values
            'E': float(self.E),
            'I': float(self.I),
            'S': float(self.S),
            'V': float(self.V),
            'coherence': float(self.coherence),
            'lambda1': float(self.lambda1),
            'void_active': bool(self.void_active),
            'time': float(self.time),
            'update_count': int(self.update_count),
            # UNITARES internal state
            'unitaires_state': {
                'E': float(self.unitaires_state.E),
                'I': float(self.unitaires_state.I),
                'S': float(self.unitaires_state.S),
                'V': float(self.unitaires_state.V)
            },
            'unitaires_theta': {
                'C1': float(self.unitaires_theta.C1),
                'eta1': float(self.unitaires_theta.eta1)
            },
            # History arrays
            'E_history': [float(e) for e in self.E_history],
            'I_history': [float(i) for i in self.I_history],
            'S_history': [float(s) for s in self.S_history],
            'V_history': [float(v) for v in self.V_history],
            'coherence_history': [float(c) for c in self.coherence_history],
            'risk_history': [float(r) for r in self.risk_history],
            'decision_history': list(self.decision_history),
            'timestamp_history': list(self.timestamp_history)  # Timestamps for each update
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'GovernanceState':
        """Create GovernanceState from dictionary (for loading persisted state)"""
        from governance_core import State, Theta
        
        # Create state with loaded values
        state = cls()
        
        # Load UNITARES internal state
        if 'unitaires_state' in data:
            us = data['unitaires_state']
            state.unitaires_state = State(
                E=float(us.get('E', DEFAULT_STATE.E)),
                I=float(us.get('I', DEFAULT_STATE.I)),
                S=float(us.get('S', DEFAULT_STATE.S)),
                V=float(us.get('V', DEFAULT_STATE.V))
            )
        else:
            # Fallback: use current state values
            state.unitaires_state = State(
                E=float(data.get('E', DEFAULT_STATE.E)),
                I=float(data.get('I', DEFAULT_STATE.I)),
                S=float(data.get('S', DEFAULT_STATE.S)),
                V=float(data.get('V', DEFAULT_STATE.V))
            )
        
        # Load UNITARES theta
        if 'unitaires_theta' in data:
            ut = data['unitaires_theta']
            state.unitaires_theta = Theta(
                C1=float(ut.get('C1', DEFAULT_THETA.C1)),
                eta1=float(ut.get('eta1', DEFAULT_THETA.eta1))
            )
        
        # Load derived metrics
        state.coherence = float(data.get('coherence', 1.0))
        state.void_active = bool(data.get('void_active', False))
        state.time = float(data.get('time', 0.0))
        state.update_count = int(data.get('update_count', 0))
        
        # Load history arrays
        state.E_history = [float(e) for e in data.get('E_history', [])]
        state.I_history = [float(i) for i in data.get('I_history', [])]
        state.S_history = [float(s) for s in data.get('S_history', [])]
        state.V_history = [float(v) for v in data.get('V_history', [])]
        state.coherence_history = [float(c) for c in data.get('coherence_history', [])]
        state.risk_history = [float(r) for r in data.get('risk_history', [])]
        state.decision_history = list(data.get('decision_history', []))
        state.timestamp_history = list(data.get('timestamp_history', []))  # Load timestamps
        
        return state
    
    def validate(self) -> tuple[bool, list[str]]:
        """
        Validate state invariants and bounds.
        
        Returns:
            (is_valid, list_of_errors)
        """
        errors = []
        
        # Check bounds
        if not (0.0 <= self.E <= 1.0):
            errors.append(f"E out of bounds: {self.E} (expected [0, 1])")
        if not (0.0 <= self.I <= 1.0):
            errors.append(f"I out of bounds: {self.I} (expected [0, 1])")
        if not (0.0 <= self.S <= 1.0):
            errors.append(f"S out of bounds: {self.S} (expected [0, 1])")
        if not (0.0 <= self.coherence <= 1.0):
            errors.append(f"Coherence out of bounds: {self.coherence} (expected [0, 1])")
        
        # Check for NaN/inf
        if np.isnan(self.E) or np.isinf(self.E):
            errors.append(f"E is NaN or Inf: {self.E}")
        if np.isnan(self.I) or np.isinf(self.I):
            errors.append(f"I is NaN or Inf: {self.I}")
        if np.isnan(self.S) or np.isinf(self.S):
            errors.append(f"S is NaN or Inf: {self.S}")
        if np.isnan(self.V) or np.isinf(self.V):
            errors.append(f"V is NaN or Inf: {self.V}")
        if np.isnan(self.coherence) or np.isinf(self.coherence):
            errors.append(f"Coherence is NaN or Inf: {self.coherence}")
        
        # Check lambda1 bounds
        lambda1_val = self.lambda1
        if np.isnan(lambda1_val) or np.isinf(lambda1_val):
            errors.append(f"lambda1 is NaN or Inf: {lambda1_val}")
        elif not (0.0 <= lambda1_val <= 1.0):
            errors.append(f"lambda1 out of bounds: {lambda1_val} (expected [0, 1])")
        
        # Check history consistency
        history_lengths = [
            len(self.E_history),
            len(self.I_history),
            len(self.S_history),
            len(self.V_history),
            len(self.coherence_history),
            len(self.risk_history)
        ]
        if len(set(history_lengths)) > 1:
            # Allow some variance (decision_history can be shorter)
            max_len = max(history_lengths)
            min_len = min(history_lengths)
            if max_len - min_len > 1:  # More than 1 entry difference
                errors.append(f"History length mismatch: E={len(self.E_history)}, I={len(self.I_history)}, S={len(self.S_history)}, V={len(self.V_history)}, coherence={len(self.coherence_history)}, risk={len(self.risk_history)}")
        
        return len(errors) == 0, errors


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
    
    def __init__(self, agent_id: str, load_state: bool = True):
        """
        Initialize monitor for a specific agent
        
        Args:
            agent_id: Unique identifier for the agent
            load_state: If True, attempt to load persisted state from disk
        """
        self.agent_id = agent_id
        self.state = GovernanceState()
        
        # Initialize prev_parameters (needed for coherence calculation)
        # This must be initialized regardless of whether state is loaded
        self.prev_parameters: Optional[np.ndarray] = None
        
        # Initialize last_update timestamp (needed for simulate_update)
        self.last_update = datetime.now()
        
        # Try to load persisted state if requested
        if load_state:
            persisted_state = self.load_persisted_state()
            if persisted_state is not None:
                self.state = persisted_state
                # Ensure created_at is set (fallback to now if not in state)
                if not hasattr(self, 'created_at'):
                    self.created_at = datetime.now()
                print(f"[UNITARES v2.0 + governance_core] Loaded persisted state for agent: {agent_id} ({len(self.state.V_history)} history entries)", file=sys.stderr)
            else:
                # Initialize fresh state
                self._initialize_fresh_state()
                print(f"[UNITARES v2.0 + governance_core] Initialized new monitor for agent: {agent_id}", file=sys.stderr)
        else:
            self._initialize_fresh_state()
            print(f"[UNITARES v2.0 + governance_core] Initialized monitor for agent: {agent_id} (no state loading)", file=sys.stderr)

        print(f"  λ₁ initial: {self.state.lambda1:.4f}", file=sys.stderr)
        print(f"  Void threshold: {config.VOID_THRESHOLD_INITIAL:.4f}", file=sys.stderr)
    
    def _initialize_fresh_state(self):
        """Initialize fresh state with default values"""
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
    
    def load_persisted_state(self) -> Optional[GovernanceState]:
        """Load persisted state from disk if it exists"""
        state_file = Path(project_root) / "data" / f"{self.agent_id}_state.json"
        
        if not state_file.exists():
            return None
        
        try:
            with open(state_file, 'r') as f:
                data = json.load(f)
                return GovernanceState.from_dict(data)
        except Exception as e:
            print(f"[UNITARES Monitor] Warning: Could not load persisted state for {self.agent_id}: {e}", file=sys.stderr)
            return None
    
    def save_persisted_state(self) -> None:
        """Save current state to disk"""
        state_file = Path(project_root) / "data" / f"{self.agent_id}_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            state_data = self.state.to_dict_with_history()
            with open(state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            print(f"[UNITARES Monitor] Warning: Could not save state for {self.agent_id}: {e}", file=sys.stderr)
    
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
        
        **DEPRECATED**: This function is no longer used in coherence calculation.
        Coherence is now pure thermodynamic C(V) signal (removed param_coherence blend).
        
        Kept for potential future use if real parameter extraction is implemented.

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

        # Store parameters for potential future use (deprecated - not used in coherence)
        # Note: param_coherence removed in favor of pure thermodynamic signal
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

        # Update coherence from governance_core coherence function (pure thermodynamic)
        # Removed param_coherence blend - using pure C(V) signal for honest calibration
        C_V = coherence(self.state.V, self.state.unitaires_theta, DEFAULT_PARAMS)
        self.state.coherence = C_V
        self.state.coherence = np.clip(self.state.coherence, 0.0, 1.0)

        # Update history
        # Record full state history (E, I, S, V, coherence)
        self.state.E_history.append(float(self.state.E))
        self.state.I_history.append(float(self.state.I))
        self.state.S_history.append(float(self.state.S))
        self.state.V_history.append(float(self.state.V))
        self.state.coherence_history.append(float(self.state.coherence))
        self.state.timestamp_history.append(datetime.now().isoformat())  # Track timestamp

        # Trim history to window
        if len(self.state.E_history) > config.HISTORY_WINDOW:
            self.state.E_history = self.state.E_history[-config.HISTORY_WINDOW:]
        if len(self.state.I_history) > config.HISTORY_WINDOW:
            self.state.I_history = self.state.I_history[-config.HISTORY_WINDOW:]
        if len(self.state.S_history) > config.HISTORY_WINDOW:
            self.state.S_history = self.state.S_history[-config.HISTORY_WINDOW:]
        if len(self.state.V_history) > config.HISTORY_WINDOW:
            self.state.V_history = self.state.V_history[-config.HISTORY_WINDOW:]
        if len(self.state.coherence_history) > config.HISTORY_WINDOW:
            self.state.coherence_history = self.state.coherence_history[-config.HISTORY_WINDOW:]
        if len(self.state.timestamp_history) > config.HISTORY_WINDOW:
            self.state.timestamp_history = self.state.timestamp_history[-config.HISTORY_WINDOW:]

        # Validate state after update
        is_valid, errors = self.state.validate()
        if not is_valid:
            print(f"[UNITARES Monitor] Warning: State validation failed for {self.agent_id}: {', '.join(errors)}", file=sys.stderr)
            # Attempt to fix common issues
            if not (0.0 <= self.state.E <= 1.0) or np.isnan(self.state.E) or np.isinf(self.state.E):
                self.state.unitaires_state.E = DEFAULT_STATE.E
            if not (0.0 <= self.state.I <= 1.0) or np.isnan(self.state.I) or np.isinf(self.state.I):
                self.state.unitaires_state.I = DEFAULT_STATE.I
            if not (0.0 <= self.state.S <= 1.0) or np.isnan(self.state.S) or np.isinf(self.state.S):
                self.state.unitaires_state.S = DEFAULT_STATE.S
            if np.isnan(self.state.V) or np.isinf(self.state.V):
                self.state.unitaires_state.V = DEFAULT_STATE.V
            self.state.coherence = np.clip(self.state.coherence, 0.0, 1.0)

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
                  f"η1={old_theta.eta1:.3f}→{self.state.unitaires_theta.eta1:.3f})",
                  file=sys.stderr)
        
        return new_lambda1
    
    def estimate_risk(self, agent_state: Dict, score_result: Dict = None) -> float:
        """
        Estimates risk score using governance_core phi_objective and verdict_from_phi.

        Uses UNITARES phi objective and verdict, then maps to risk score [0, 1].
        
        **Risk Score Composition:**
        - 70% UNITARES phi-based risk (includes ethical drift ‖Δη‖², E, I, S, V state)
        - 30% Traditional safety risk (length, complexity, coherence, keywords)
        
        This blend ensures risk reflects both ethical alignment (via phi) and 
        safety/quality concerns (via traditional metrics).

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
        
        # Weighted combination: 70% UNITARES phi-based (ethical), 30% traditional (safety)
        # Configurable weights (defaults match config, but can be overridden)
        phi_weight = getattr(config, 'RISK_PHI_WEIGHT', 0.7)
        traditional_weight = getattr(config, 'RISK_TRADITIONAL_WEIGHT', 0.3)
        risk = phi_weight * risk + traditional_weight * traditional_risk
        
        # Update history
        self.state.risk_history.append(risk)
        if len(self.state.risk_history) > config.HISTORY_WINDOW:
            self.state.risk_history = self.state.risk_history[-config.HISTORY_WINDOW:]
        
        return float(np.clip(risk, 0.0, 1.0))
    
    def make_decision(self, risk_score: float, unitares_verdict: str = None) -> Dict:
        """
        Makes autonomous governance decision using UNITARES Phase-3 verdict and config.make_decision()
        
        If unitares_verdict is provided, it influences the decision:
        - "safe" -> bias toward approve
        - "caution" -> bias toward revise
        - "high-risk" -> bias toward reject
        
        Returns decision dict with action and reason (fully autonomous, no human-in-the-loop).
        """
        # Use UNITARES verdict to influence decision if available
        if unitares_verdict == "high-risk":
            # Override: high-risk verdict -> reject
            return {
                'action': 'reject',
                'reason': f'UNITARES high-risk verdict (risk_score={risk_score:.2f}) - agent should halt'
            }
        elif unitares_verdict == "caution":
            # Caution verdict: bias toward revise (stronger than before)
            # If risk would approve, upgrade to revise due to caution
            if risk_score < config.RISK_APPROVE_THRESHOLD:
                # Low risk but caution -> upgrade to revise (was approve)
                return {
                    'action': 'revise',
                    'reason': f'UNITARES caution verdict (risk_score={risk_score:.2f}) - agent should self-correct despite low risk'
                }
            else:
                # Medium/high risk + caution -> use standard decision (likely revise/reject)
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
    
    def simulate_update(self, agent_state: Dict, confidence: float = 1.0) -> Dict:
        """
        Dry-run governance cycle: Returns decision without persisting state.
        
        Useful for testing decisions before committing. Does NOT modify state.
        
        Args:
            agent_state: Agent state dict with parameters, ethical_drift, response_text, complexity
            confidence: Confidence level [0, 1] for this update. Defaults to 1.0.
        
        Returns:
            Same format as process_update, but state is NOT modified
        """
        import copy
        
        # Save current state completely
        saved_state = copy.deepcopy(self.state)
        saved_prev_params = copy.deepcopy(self.prev_parameters) if self.prev_parameters is not None else None
        saved_last_update = self.last_update
        
        try:
            # Create temporary state copy for simulation
            temp_state = copy.deepcopy(self.state)
            temp_prev_params = copy.deepcopy(self.prev_parameters) if self.prev_parameters is not None else None
            
            # Swap to temporary state
            self.state = temp_state
            self.prev_parameters = temp_prev_params
            
            # Run full governance cycle (modifies temp_state) with confidence
            result = self.process_update(agent_state, confidence=confidence)
            
            # Mark as simulation
            result['simulation'] = True
            result['note'] = 'This was a simulation - state was not modified'
            
            return result
        finally:
            # Always restore original state, even if error occurred
            self.state = saved_state
            self.prev_parameters = saved_prev_params
            self.last_update = saved_last_update
    
    def process_update(self, agent_state: Dict, confidence: float = 1.0) -> Dict:
        """
        Complete governance cycle: Update → Adapt → Decide

        This is the main API method called by the MCP server.

        Args:
            agent_state: Agent state dict with parameters, ethical_drift, response_text, complexity
            confidence: Confidence level [0, 1] for this update. Defaults to 1.0 (fully confident).
                        When confidence < CONTROLLER_CONFIDENCE_THRESHOLD, lambda1 updates are skipped.

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
        
        # Store confidence for audit logging
        self.current_confidence = confidence

        # Step 1: Update thermodynamic state
        self.update_dynamics(agent_state)
        
        # Step 2: Check void state
        void_active = self.check_void_state()
        
        # Step 3: Update λ₁ (every N updates) - WITH CONFIDENCE GATING
        # Updated to every 5 cycles for faster adaptation (was 10)
        lambda1_skipped = False
        if self.state.update_count % 5 == 0:  # Update λ₁ every 5 cycles
            # Gate lambda1 updates based on confidence
            if confidence >= config.CONTROLLER_CONFIDENCE_THRESHOLD:
                self.update_lambda1()
            else:
                # Skip lambda1 update due to low confidence
                lambda1_skipped = True
                # Track skip count
                if not hasattr(self.state, 'lambda1_update_skips'):
                    self.state.lambda1_update_skips = 0
                self.state.lambda1_update_skips += 1
                
                # Log skip via audit logger
                audit_logger.log_lambda1_skip(
                    agent_id=self.agent_id,
                    confidence=confidence,
                    threshold=config.CONTROLLER_CONFIDENCE_THRESHOLD,
                    update_count=self.state.update_count,
                    reason=f"confidence {confidence:.3f} < threshold {config.CONTROLLER_CONFIDENCE_THRESHOLD}"
                )
                
                print(f"[UNITARES Monitor] Skipping λ₁ update for {self.agent_id}: "
                      f"confidence {confidence:.3f} < threshold {config.CONTROLLER_CONFIDENCE_THRESHOLD}",
                      file=sys.stderr)
        
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
        
        # Record prediction for calibration checking
        # We predict "correct" if decision is approve (low risk) or revise (medium risk handled)
        # High risk/reject decisions are predicted as "needs review"
        predicted_correct = decision['action'] in ['approve', 'revise']
        
        # Record for calibration (actual correctness will be updated later via ground truth)
        calibration_checker.record_prediction(
            confidence=confidence,
            predicted_correct=predicted_correct,
            actual_correct=None  # Ground truth not available at decision time
        )
        
        # Log decision via audit logger (for accountability and transparency)
        audit_logger.log_auto_attest(
            agent_id=self.agent_id,
            confidence=confidence,
            ci_passed=False,  # CI status not available in governance_monitor
            risk_score=risk_score,
            decision=decision['action'],
            details={
                'reason': decision.get('reason', ''),
                'coherence': float(self.state.coherence),
                'void_active': void_active,
                'unitares_verdict': unitares_verdict
            }
        )
        
        # Track decision history for governance auditing
        # Backward compatibility: ensure decision_history exists (for instances created before this feature)
        if not hasattr(self.state, 'decision_history'):
            self.state.decision_history = []
        self.state.decision_history.append(decision['action'])
        if len(self.state.decision_history) > config.HISTORY_WINDOW:
            self.state.decision_history = self.state.decision_history[-config.HISTORY_WINDOW:]
        
        # Step 6: Get sampling parameters for next generation
        sampling_params = config.lambda_to_params(self.state.lambda1)
        
        # Determine overall status using health thresholds (recalibrated)
        # Note: MCP server will also calculate health_status separately using health_checker
        # This status field uses decision thresholds for backward compatibility
        if void_active or self.state.coherence < config.COHERENCE_CRITICAL_THRESHOLD:
            status = 'critical'
        elif risk_score > config.RISK_REVISE_THRESHOLD:  # Now 0.50 (was 0.70)
            status = 'degraded'
        else:
            status = 'healthy'
        
        # Build metrics dict
        metrics = {
            'E': float(self.state.E),
            'I': float(self.state.I),
            'S': float(self.state.S),
            'V': float(self.state.V),
            'coherence': float(self.state.coherence),
            'lambda1': float(self.state.lambda1),
            'risk_score': float(risk_score),
            'void_active': bool(void_active),
            'time': float(self.state.time),
            'updates': int(self.state.update_count),
            'confidence': float(confidence),
            'lambda1_skipped': lambda1_skipped
        }
        
        # Add lambda1_skips count if available
        if hasattr(self.state, 'lambda1_update_skips'):
            metrics['lambda1_update_skips'] = int(self.state.lambda1_update_skips)
        
        return {
            'status': status,
            'decision': decision,
            'metrics': metrics,
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
        
        # Calculate status consistently with process_update()
        # Use most recent risk score if available, otherwise use mean
        current_risk = float(np.mean(self.state.risk_history[-10:])) if len(self.state.risk_history) >= 10 else (
            float(np.mean(self.state.risk_history)) if self.state.risk_history else 0.5
        )
        
        # Status calculation matches process_update() logic
        if self.state.void_active or self.state.coherence < config.COHERENCE_CRITICAL_THRESHOLD:
            status = 'critical'
        elif current_risk > config.RISK_REVISE_THRESHOLD:
            status = 'degraded'
        else:
            status = 'healthy'
        
        return {
            'agent_id': self.agent_id,
            'state': self.state.to_dict(),
            'status': status,
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
                'description': 'Exploration capacity / Productive capacity deployed',
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
            'timestamps': self.state.timestamp_history,  # Timestamps for each update
            'E_history': self.state.E_history,  # Full history
            'I_history': self.state.I_history,  # Full history
            'S_history': self.state.S_history,  # Full history
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
            writer.writerow(['update', 'timestamp', 'E', 'I', 'S', 'V', 'coherence', 'risk', 'decision', 'lambda1'])
            
            # Write data rows - use full history for E/I/S
            num_rows = len(self.state.V_history)
            for i in range(num_rows):
                row = [
                    i + 1,
                    self.state.timestamp_history[i] if i < len(self.state.timestamp_history) else '',
                    self.state.E_history[i] if i < len(self.state.E_history) else '',
                    self.state.I_history[i] if i < len(self.state.I_history) else '',
                    self.state.S_history[i] if i < len(self.state.S_history) else '',
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
            print(f"\n[Update {i}]", file=sys.stderr)
            print(f"  Status: {result['status']}", file=sys.stderr)
            print(f"  Decision: {result['decision']['action']}", file=sys.stderr)
            print(f"  Metrics: E={result['metrics']['E']:.3f}, "
                  f"I={result['metrics']['I']:.3f}, "
                  f"V={result['metrics']['V']:.3f}, "
                  f"λ₁={result['metrics']['lambda1']:.3f}", file=sys.stderr)
    
    # Get final metrics
    print("\n" + "="*60, file=sys.stderr)
    print("Final Metrics:", file=sys.stderr)
    print(json.dumps(monitor.get_metrics(), indent=2), file=sys.stderr)
