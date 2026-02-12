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
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
from collections import Counter
from pathlib import Path
import json
import sys

from config.governance_config import config

# Import structured logging
from src.logging_utils import get_logger
logger = get_logger(__name__)

# Import audit logging and calibration for accountability and self-awareness
from src.audit_log import audit_logger
from src.calibration import calibration_checker
from src.runtime_config import get_effective_threshold

# Import dual-log architecture for grounded EISV inputs (Patent: Dual-Log Architecture)
from src.dual_log import ContinuityLayer, RestorativeBalanceMonitor

# Import drift telemetry for empirical data collection (Patent: De-abstracted Δη)
from src.drift_telemetry import record_drift

# Import UNITARES Phase-3 engine from governance_core (v2.0)
# Core dynamics are now in governance_core module
from src._imports import ensure_project_root, ensure_unitaires_server_path

# Ensure project root is in path for imports
ensure_project_root()
ensure_unitaires_server_path()

# Import core dynamics from governance_core (canonical implementation)
from governance_core import (
    State, Theta, Weights,
    DEFAULT_STATE, DEFAULT_THETA, DEFAULT_WEIGHTS,
    step_state, coherence,
    lambda1 as lambda1_from_theta,
    phi_objective, verdict_from_phi,
    DynamicsParams, DEFAULT_PARAMS,
    # Concrete ethical drift (Δη) - measurable components
    EthicalDriftVector, AgentBaseline, compute_ethical_drift, get_agent_baseline,
)

# UNITARES params profile selection (optional v4.1 alignment)
from governance_core.parameters import get_active_params, get_params_profile_name

# Import analysis/optimization functions from unitaires_core
# These are research tools, not core dynamics
from unitaires_core import (
    approximate_stability_check,
    suggest_theta_update,
)

# Import extracted modules
from src.governance_state import GovernanceState
from src.confidence import derive_confidence
from src.cirs import (
    OscillationDetector, ResonanceDamper, OscillationState,
    classify_response, CIRS_DEFAULTS, HCK_DEFAULTS
)


class UNITARESMonitor:
    """
    UNITARES v1.0 Governance Monitor

    Implements complete thermodynamic governance with:
    - 4D state evolution (E, I, S, V)
    - Risk estimation from agent behavior
    - Adaptive λ₁ via PI controller
    - Void detection with adaptive thresholds
    - Decision logic (approve/reflect/reject)
    - HCK v3.0: Update coherence ρ(t) and gain modulation
    - CIRS v0.1: Oscillation detection and resonance damping
    """

    # =================================================================
    # HCK v3.0: Update Coherence and Continuity Energy
    # =================================================================

    @staticmethod
    def compute_update_coherence(delta_E: float, delta_I: float,
                                  epsilon: float = 1e-8) -> float:
        """
        Compute update coherence ρ(t) per HCK v3.0.

        Measures directional alignment between E and I updates.

        Interpretation:
        - ρ ≈ 1: Coherent updates (E and I moving together)
        - ρ ≈ 0: Misaligned or unstable
        - ρ < 0: Adversarial movement (E and I diverging)

        Args:
            delta_E: Change in Energy since last update
            delta_I: Change in Information Integrity since last update
            epsilon: Small value to prevent division by zero

        Returns:
            float in [-1, 1]: Update coherence value
        """
        norm_E = abs(delta_E) + epsilon
        norm_I = abs(delta_I) + epsilon

        # Normalized product gives directional alignment
        rho = (delta_E * delta_I) / (norm_E * norm_I)

        return float(max(-1.0, min(1.0, rho)))

    @staticmethod
    def compute_continuity_energy(state_history: List[Dict],
                                   window: int = 10,
                                   alpha_state: float = 0.6,
                                   alpha_decision: float = 0.4) -> float:
        """
        Compute Continuity Energy CE(t) per HCK v3.0.

        CE tracks how much the system state is changing - the "work required
        to maintain consistency as system evolves."

        Interpretation:
        - High CE: Major state changes requiring stabilization
        - Low CE: Stable operation

        Args:
            state_history: List of recent state snapshots with E, I, S, V, route keys
            window: Number of recent states to consider
            alpha_state: Weight for EISV state changes (default 0.6)
            alpha_decision: Weight for decision/route changes (default 0.4)

        Returns:
            CE value (non-negative float)
        """
        if len(state_history) < 2:
            return 0.0

        recent = state_history[-window:] if len(state_history) > window else state_history

        # State change component: sum of absolute EISV deltas
        state_deltas = []
        for i in range(1, len(recent)):
            prev, curr = recent[i-1], recent[i]
            delta = (
                abs(curr.get('E', 0) - prev.get('E', 0)) +
                abs(curr.get('I', 0) - prev.get('I', 0)) +
                abs(curr.get('S', 0) - prev.get('S', 0)) +
                abs(curr.get('V', 0) - prev.get('V', 0))
            )
            state_deltas.append(delta)

        avg_state_delta = sum(state_deltas) / len(state_deltas) if state_deltas else 0.0

        # Decision change component: count route/decision flips
        decision_changes = 0
        for i in range(1, len(recent)):
            prev_route = recent[i-1].get('route') or recent[i-1].get('decision')
            curr_route = recent[i].get('route') or recent[i].get('decision')
            if prev_route and curr_route and prev_route != curr_route:
                decision_changes += 1

        decision_change_rate = decision_changes / (len(recent) - 1) if len(recent) > 1 else 0.0

        # Weighted combination
        CE = alpha_state * avg_state_delta + alpha_decision * decision_change_rate

        return float(CE)

    @staticmethod
    def modulate_gains(K_p: float, K_i: float, rho: float,
                       min_factor: float = 0.5) -> Tuple[float, float]:
        """
        Adjust PI gains based on update coherence per HCK v3.0.

        When ρ(t) is low (misaligned updates), reduce controller aggressiveness
        to prevent instability.

        Args:
            K_p: Base proportional gain
            K_i: Base integral gain
            rho: Update coherence [-1, 1]
            min_factor: Minimum gain multiplier (default 0.5)

        Returns:
            (K_p_adjusted, K_i_adjusted)
        """
        # Map rho from [-1, 1] to [min_factor, 1.0]
        # rho=1 → factor=1.0, rho=0 → factor=0.75, rho=-1 → factor=0.5
        coherence_factor = max(min_factor, (rho + 1) / 2)

        return K_p * coherence_factor, K_i * coherence_factor
    
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
        
        # Initialize dual-log architecture for grounded EISV inputs
        # ContinuityLayer compares operational (server-derived) vs reflective (agent-reported)
        # to produce grounded complexity, divergence metrics, and EISV inputs
        self.continuity_layer = ContinuityLayer(agent_id=agent_id, redis_client=None)
        self.restorative_monitor = RestorativeBalanceMonitor(agent_id=agent_id, redis_client=None)
        self._last_continuity_metrics = None
        self._last_restorative_status = None
        self._last_drift_vector = None  # Concrete ethical drift (Δη)

        # HCK v3.0: Track previous E and I for update coherence ρ(t) computation
        self._prev_E: Optional[float] = None
        self._prev_I: Optional[float] = None

        # CIRS v0.1: Initialize oscillation detector and resonance damper
        self.oscillation_detector = OscillationDetector(
            window=CIRS_DEFAULTS['window'],
            ema_lambda=CIRS_DEFAULTS['ema_lambda'],
            oi_threshold=CIRS_DEFAULTS['oi_threshold'],
            flip_threshold=CIRS_DEFAULTS['flip_threshold']
        )
        self.resonance_damper = ResonanceDamper(
            kappa_r=CIRS_DEFAULTS['kappa_r'],
            delta_tau=CIRS_DEFAULTS['delta_tau'],
            tau_bounds=CIRS_DEFAULTS['tau_bounds'],
            beta_bounds=CIRS_DEFAULTS['beta_bounds']
        )
        self._last_oscillation_state: Optional[OscillationState] = None
        self._gains_modulated: bool = False  # Track if gains were modulated this cycle
        
        # Try to load persisted state if requested
        if load_state:
            persisted_state = self.load_persisted_state()
            if persisted_state is not None:
                self.state = persisted_state
                # Ensure created_at is set (fallback to now if not in state)
                if not hasattr(self, 'created_at'):
                    self.created_at = datetime.now()
                logger.info(f"Loaded persisted state for agent: {agent_id} ({len(self.state.V_history)} history entries)")
            else:
                # Initialize fresh state
                self._initialize_fresh_state()
                logger.info(f"Initialized new monitor for agent: {agent_id}")
        else:
            self._initialize_fresh_state()
            logger.info(f"Initialized monitor for agent: {agent_id} (no state loading)")

        logger.debug(f"λ₁ initial: {self.state.lambda1:.4f}")
        logger.debug(f"Void threshold: {config.VOID_THRESHOLD_INITIAL:.4f}")
    
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
        # Get project root
        from src._imports import ensure_project_root
        project_root = ensure_project_root()
        
        # Use organized structure: data/agents/
        new_path = Path(project_root) / "data" / "agents" / f"{self.agent_id}_state.json"
        old_path = Path(project_root) / "data" / f"{self.agent_id}_state.json"

        # Check new location first, then old location for backward compatibility
        if new_path.exists():
            state_file = new_path
        elif old_path.exists():
            state_file = old_path
        else:
            return None
        
        try:
            with open(state_file, 'r') as f:
                data = json.load(f)
                return GovernanceState.from_dict(data)
        except Exception as e:
            logger.warning(f"Could not load persisted state for {self.agent_id}: {e}", exc_info=True)
            return None
    
    def save_persisted_state(self) -> None:
        """Save current state to disk"""
        # Use organized structure: data/agents/
        from src._imports import ensure_project_root
        project_root = ensure_project_root()
        state_file = Path(project_root) / "data" / "agents" / f"{self.agent_id}_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            state_data = self.state.to_dict_with_history()
            with open(state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save state for {self.agent_id}: {e}", exc_info=True)
    
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
        - Small changes → coherence ≈ 0.50-0.55 (governed agents)
        - Large changes → coherence → 0.45 (physics floor)

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
    
    def detect_regime(self) -> str:
        """
        Detect current operational regime based on state and history.
        
        Regimes:
        - STABLE: I ≥ 0.999, S ≤ 0.001 (requires 3 consecutive steps)
        - DIVERGENCE: S rising, |V| elevated
        - TRANSITION: S peaked, starting to fall, I increasing
        - CONVERGENCE: S low & falling, I high & stable
        
        Returns:
            regime: str - Current operational regime
        """
        I = self.state.I
        S = self.state.S
        V = abs(self.state.V)
        
        # Thresholds for regime detection
        eps_S = 0.001  # Entropy threshold
        eps_I = 0.001  # Integrity threshold
        I_STABLE_THRESHOLD = 0.999
        S_STABLE_THRESHOLD = 0.001
        V_ELEVATED_THRESHOLD = 0.1  # Elevated void threshold
        
        # Check for STABLE state (requires persistence)
        if I >= I_STABLE_THRESHOLD and S <= S_STABLE_THRESHOLD:
            self.state.locked_persistence_count += 1
            if self.state.locked_persistence_count >= 3:
                return "STABLE"
        else:
            # Reset persistence counter if not at threshold
            self.state.locked_persistence_count = 0
        
        # Need at least 2 history points for delta-based detection
        # Defensive check: ensure history exists and has enough entries
        if (not hasattr(self.state, 'S_history') or not hasattr(self.state, 'I_history') or
            len(self.state.S_history) < 2 or len(self.state.I_history) < 2):
            return "DIVERGENCE"  # Default for early updates
        
        # Get deltas (safe to access [-1] after length check)
        try:
            dS = S - self.state.S_history[-1]
            dI = I - self.state.I_history[-1]
        except (IndexError, AttributeError):
            # Fallback if history access fails
            return "DIVERGENCE"
        
        # DIVERGENCE: S rising (or stable high), |V| elevated
        if dS > eps_S or (S > 0.1 and abs(dS) < eps_S):
            if V > V_ELEVATED_THRESHOLD:
                return "DIVERGENCE"
        
        # TRANSITION: S peaked and starting to fall, I increasing
        if dS < -eps_S and dI > eps_I:
            return "TRANSITION"
        
        # CONVERGENCE: S low & falling, I high & stable
        if S < 0.1 and dS <= 0 and I > 0.8:
            return "CONVERGENCE"
        
        # Default fallback
        return "DIVERGENCE"
    
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
        ethical_signals = np.array(agent_state.get('ethical_drift', [0.0, 0.0, 0.0, 0.0]))

        # Validate and normalize ethical_drift (delta_eta) to list
        # Accept any length — drift_norm() handles variable-length vectors.
        # Governance computes 4 components; agents may send 3. Both are valid.
        if len(ethical_signals) == 0:
            delta_eta = [0.0, 0.0, 0.0]
        else:
            delta_eta = ethical_signals.tolist()

        # Replace NaN/inf with zeros
        delta_eta = [0.0 if (np.isnan(x) or np.isinf(x)) else float(x) for x in delta_eta]

        # Extract complexity (default to 0.5 if not provided)
        complexity = agent_state.get('complexity', 0.5)
        if complexity is None or np.isnan(complexity) or np.isinf(complexity):
            complexity = 0.5
        complexity = float(np.clip(complexity, 0.0, 1.0))  # Ensure in valid range

        # Store parameters for potential future use (deprecated - not used in coherence)
        # Note: param_coherence removed in favor of pure thermodynamic signal
        self.prev_parameters = parameters.copy() if len(parameters) > 0 else None

        # Use governance_core step_state() to evolve state (CANONICAL DYNAMICS)
        # Params are profile-selectable (default vs v4.1 paper-aligned) via:
        # - UNITARES_PARAMS_PROFILE=default|v41
        # - UNITARES_PARAMS_JSON='{"beta_I": 0.05, ...}'
        active_params = get_active_params()
        self.state.unitaires_state = step_state(
            state=self.state.unitaires_state,
            theta=self.state.unitaires_theta,
            delta_eta=delta_eta,
            dt=dt,
            noise_S=0.0,  # Can add noise if needed
            params=active_params,
            complexity=complexity  # Complexity now affects S dynamics
        )

        # Epistemic humility safeguard: Enforce entropy floor (S >= 0.001) always
        # Perfect equilibrium (S=0.0) is dangerous and brittle - maintain epistemic humility at all times
        if self.state.unitaires_state.S < 0.001:
            # Maintain epistemic humility: "I could be wrong about something I can't see"
            self.state.unitaires_state.S = 0.001

        # V bounds: allow negative V (I > E imbalance) — core already clips to [-2, 2]
        # Negative V is physically meaningful: coherence(V) is designed for V ∈ [-2, 2]
        self.state.unitaires_state.V = max(-1.0, min(1.0, self.state.unitaires_state.V))

        # Update coherence from governance_core coherence function (pure thermodynamic)
        # Removed param_coherence blend - using pure C(V) signal for honest calibration
        C_V = coherence(self.state.V, self.state.unitaires_theta, active_params)
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
        
        # Track current lambda1 value (even if not updated this cycle)
        # Backward compatibility: ensure lambda1_history exists
        if not hasattr(self.state, 'lambda1_history'):
            self.state.lambda1_history = []
        # Append current lambda1 (will be same value until update_lambda1() is called)
        current_lambda1 = self.state.lambda1
        self.state.lambda1_history.append(float(current_lambda1))
        
        # Detect and track regime (operational state)
        # Defensive: ensure regime attributes exist (backward compatibility)
        if not hasattr(self.state, 'regime'):
            self.state.regime = 'divergence'
        if not hasattr(self.state, 'regime_history'):
            self.state.regime_history = []
        if not hasattr(self.state, 'locked_persistence_count'):
            self.state.locked_persistence_count = 0
        
        previous_regime = self.state.regime
        new_regime = self.detect_regime()
        self.state.regime = new_regime
        self.state.regime_history.append(new_regime)
        
        # Log regime transitions
        if new_regime != previous_regime:
            logger.info(
                f"Regime transition for {self.agent_id}: {previous_regime} → {new_regime} "
                f"(I={self.state.I:.3f}, S={self.state.S:.3f}, V={self.state.V:.3f})"
            )
        
        # Log STABLE state events (when first reached)
        if new_regime == "STABLE" and previous_regime != "STABLE":
            logger.info(
                f"Reached STABLE state for {self.agent_id} "
                f"(I={self.state.I:.3f}, S={self.state.S:.3f}) - "
                f"system will naturally transition when state changes"
            )

        # =================================================================
        # HCK v3.0: Compute and store update coherence ρ(t) and CE
        # =================================================================
        # Compute ρ(t) from E and I deltas
        if self._prev_E is not None and self._prev_I is not None:
            delta_E = float(self.state.E) - self._prev_E
            delta_I = float(self.state.I) - self._prev_I
            rho = self.compute_update_coherence(delta_E, delta_I)
        else:
            rho = 0.0  # First update, no previous state

        # Update prev values for next iteration
        self._prev_E = float(self.state.E)
        self._prev_I = float(self.state.I)

        # Store ρ(t) in state
        self.state.current_rho = rho
        if not hasattr(self.state, 'rho_history'):
            self.state.rho_history = []
        self.state.rho_history.append(rho)

        # Compute Continuity Energy CE from state history snapshots
        # Build state snapshot list for CE computation
        state_snapshots = []
        history_len = min(10, len(self.state.E_history))
        for i in range(-history_len, 0):
            try:
                snapshot = {
                    'E': self.state.E_history[i],
                    'I': self.state.I_history[i],
                    'S': self.state.S_history[i],
                    'V': self.state.V_history[i],
                    'decision': self.state.decision_history[i] if i < len(self.state.decision_history) else None
                }
                state_snapshots.append(snapshot)
            except IndexError:
                pass

        CE = self.compute_continuity_energy(state_snapshots)
        if not hasattr(self.state, 'CE_history'):
            self.state.CE_history = []
        self.state.CE_history.append(CE)

        # Trim history to window
        if len(self.state.E_history) > config.HISTORY_WINDOW:
            self.state.E_history = self.state.E_history[-config.HISTORY_WINDOW:]
        if len(self.state.I_history) > config.HISTORY_WINDOW:
            self.state.I_history = self.state.I_history[-config.HISTORY_WINDOW:]
        if len(self.state.S_history) > config.HISTORY_WINDOW:
            self.state.S_history = self.state.S_history[-config.HISTORY_WINDOW:]
        if len(self.state.regime_history) > config.HISTORY_WINDOW:
            self.state.regime_history = self.state.regime_history[-config.HISTORY_WINDOW:]
        if len(self.state.V_history) > config.HISTORY_WINDOW:
            self.state.V_history = self.state.V_history[-config.HISTORY_WINDOW:]
        if len(self.state.coherence_history) > config.HISTORY_WINDOW:
            self.state.coherence_history = self.state.coherence_history[-config.HISTORY_WINDOW:]
        if len(self.state.timestamp_history) > config.HISTORY_WINDOW:
            self.state.timestamp_history = self.state.timestamp_history[-config.HISTORY_WINDOW:]
        if len(self.state.lambda1_history) > config.HISTORY_WINDOW:
            self.state.lambda1_history = self.state.lambda1_history[-config.HISTORY_WINDOW:]
        # HCK/CIRS history trimming
        if hasattr(self.state, 'rho_history') and len(self.state.rho_history) > config.HISTORY_WINDOW:
            self.state.rho_history = self.state.rho_history[-config.HISTORY_WINDOW:]
        if hasattr(self.state, 'CE_history') and len(self.state.CE_history) > config.HISTORY_WINDOW:
            self.state.CE_history = self.state.CE_history[-config.HISTORY_WINDOW:]
        if hasattr(self.state, 'oi_history') and len(self.state.oi_history) > config.HISTORY_WINDOW:
            self.state.oi_history = self.state.oi_history[-config.HISTORY_WINDOW:]

        # Validate state after update (STRICT MODE - Issue #1 fix)
        is_valid, errors = self.state.validate()
        if not is_valid:
            # Categorize errors as critical (NaN, Inf) vs minor (bounds violations)
            critical_errors = []
            minor_errors = []

            for error in errors:
                if "NaN" in error or "Inf" in error:
                    critical_errors.append(error)
                else:
                    minor_errors.append(error)

            # CRITICAL ERRORS: Raise exception (don't auto-fix)
            # These indicate corrupt state that should not propagate
            if critical_errors:
                error_msg = (
                    f"CRITICAL: State validation failed for {self.agent_id} - "
                    f"corrupt state detected (NaN/Inf values). "
                    f"Errors: {', '.join(critical_errors)}"
                )
                logger.error(error_msg)
                raise ValueError(error_msg)

            # MINOR ERRORS: Log warning and auto-fix
            # These are bounds violations that can be safely clipped
            if minor_errors:
                logger.warning(f"State validation warnings for {self.agent_id}: {', '.join(minor_errors)}")
                # Auto-fix bounds violations by clipping
                if not (0.0 <= self.state.E <= 1.0):
                    self.state.unitaires_state.E = np.clip(self.state.E, 0.0, 1.0)
                    logger.info(f"Auto-fixed E to {self.state.E}")
                if not (0.0 <= self.state.I <= 1.0):
                    self.state.unitaires_state.I = np.clip(self.state.I, 0.0, 1.0)
                    logger.info(f"Auto-fixed I to {self.state.I}")
                if not (0.0 <= self.state.S <= 1.0):
                    self.state.unitaires_state.S = np.clip(self.state.S, 0.0, 1.0)
                    logger.info(f"Auto-fixed S to {self.state.S}")
                if not (-1.0 <= self.state.V <= 1.0):
                    self.state.unitaires_state.V = np.clip(self.state.V, -1.0, 1.0)
                    logger.info(f"Auto-fixed V to {self.state.V}")
                if not (0.0 <= self.state.coherence <= 1.0):
                    self.state.coherence = np.clip(self.state.coherence, 0.0, 1.0)
                    logger.info(f"Auto-fixed coherence to {self.state.coherence}")

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
    
    def _calculate_void_frequency(self) -> float:
        """
        Calculate void frequency from V history.
        
        Returns fraction of time system was in void state (|V| > threshold).
        Uses adaptive threshold for each historical point.
        """
        if not self.state.V_history or len(self.state.V_history) < 10:
            return 0.0
        
        # Use last 100 observations (or all if fewer)
        window = min(100, len(self.state.V_history))
        recent_V = np.array(self.state.V_history[-window:])
        
        # Calculate adaptive threshold for the window
        threshold = config.get_void_threshold(recent_V, adaptive=True)
        
        # Count void events (|V| > threshold)
        void_count = np.sum(np.abs(recent_V) > threshold)
        void_freq = float(void_count) / len(recent_V)
        
        return void_freq
    
    def update_lambda1(self) -> float:
        """
        Updates λ₁ using PI controller based on void frequency and coherence targets.

        Uses PI controller to adapt lambda1 to maintain:
        - Target void frequency: 2% (TARGET_VOID_FREQ)
        - Target coherence: 55% (TARGET_COHERENCE, matches physics ceiling V=0.1)

        HCK v3.0: When update coherence ρ(t) is low (misaligned E/I updates),
        PI gains are modulated to reduce controller aggressiveness and prevent instability.

        Updates theta.eta1 to reflect new lambda1 value.

        Returns updated λ₁ value.
        """
        # Calculate current metrics
        void_freq_current = self._calculate_void_frequency()
        coherence_current = self.state.coherence

        # Get current lambda1
        lambda1_current = self.state.lambda1

        # Get PI controller integral state (initialize if needed)
        if not hasattr(self.state, 'pi_integral'):
            self.state.pi_integral = 0.0

        # HCK v3.0: Modulate PI gains based on update coherence ρ(t)
        # When ρ is low (E and I moving in opposite directions), reduce aggressiveness
        rho = getattr(self.state, 'current_rho', 0.0)
        base_K_p = config.PI_KP
        base_K_i = config.PI_KI
        K_p_adj, K_i_adj = self.modulate_gains(base_K_p, base_K_i, rho)

        # Track if gains were modulated
        self._gains_modulated = (K_p_adj != base_K_p or K_i_adj != base_K_i)

        # Manual PI calculation with modulated gains (instead of using config.pi_update)
        # This allows us to use the adjusted gains
        error_void = config.TARGET_VOID_FREQ - void_freq_current
        error_coherence = coherence_current - config.TARGET_COHERENCE

        # Proportional term (weighted combination)
        P = K_p_adj * (0.7 * error_void + 0.3 * error_coherence)

        # Integral term (only void frequency, with anti-windup)
        self.state.pi_integral += error_void * 1.0  # dt = 1.0
        self.state.pi_integral = np.clip(
            self.state.pi_integral,
            -config.PI_INTEGRAL_MAX,
            config.PI_INTEGRAL_MAX
        )
        I = K_i_adj * self.state.pi_integral

        # Control signal
        delta_lambda = P + I

        # Update λ₁
        new_lambda1 = lambda1_current + delta_lambda
        new_lambda1 = np.clip(
            new_lambda1,
            config.LAMBDA1_MIN,
            config.LAMBDA1_MAX
        )
        # Note: pi_integral is already updated above with anti-windup

        # Map new lambda1 back to theta.eta1
        # Inverse mapping: lambda1 [LAMBDA1_MIN, LAMBDA1_MAX] → eta1 [0.1, 0.5]
        lambda1_range = config.LAMBDA1_MAX - config.LAMBDA1_MIN
        eta1_min = 0.1
        eta1_max = 0.5
        eta1_range = eta1_max - eta1_min
        
        if lambda1_range > 0:
            # Normalize lambda1 to [0, 1]
            normalized_lambda1 = (new_lambda1 - config.LAMBDA1_MIN) / lambda1_range
            # Map to eta1 range
            new_eta1 = eta1_min + normalized_lambda1 * eta1_range
            # Clamp to valid bounds
            new_eta1 = np.clip(new_eta1, eta1_min, eta1_max)
        else:
            # Fallback if range is zero
            new_eta1 = self.state.unitaires_theta.eta1
        
        # Update theta (preserve C1, update eta1)
        old_theta = self.state.unitaires_theta
        self.state.unitaires_theta = Theta(
            C1=old_theta.C1,  # Keep C1 unchanged (affects coherence, not lambda1)
            eta1=new_eta1     # Update eta1 (affects lambda1)
        )
        
        # Get updated lambda1 (should match new_lambda1 from PI controller)
        updated_lambda1 = self.state.lambda1
        
        # Log significant changes
        if abs(updated_lambda1 - lambda1_current) > 0.01:
            gain_info = ""
            if self._gains_modulated:
                gain_info = f", ρ={rho:.3f}, gains_modulated=True"
            logger.info(
                f"PI Controller λ₁ update: {lambda1_current:.4f} → {updated_lambda1:.4f} "
                f"(void_freq={void_freq_current:.3f}, coherence={coherence_current:.3f}, "
                f"η1={old_theta.eta1:.3f}→{new_eta1:.3f}{gain_info})"
            )

        return updated_lambda1
    
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
            ethical_signals = np.array(agent_state.get('ethical_drift', [0.0, 0.0, 0.0, 0.0]))
            if len(ethical_signals) == 0:
                delta_eta = [0.0, 0.0, 0.0]
            else:
                delta_eta = ethical_signals.tolist()

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
        # Use configurable thresholds (fixes magic number issue)
        phi_safe_threshold = getattr(config, 'PHI_SAFE_THRESHOLD', 0.3)
        phi_caution_threshold = getattr(config, 'PHI_CAUTION_THRESHOLD', 0.0)
        
        # phi >= PHI_SAFE_THRESHOLD: safe -> risk ~ 0.0-0.3
        # phi >= PHI_CAUTION_THRESHOLD: caution -> risk ~ 0.3-0.7
        # phi < PHI_CAUTION_THRESHOLD: high-risk -> risk ~ 0.7-1.0
        if phi >= phi_safe_threshold:
            # Safe: map phi [phi_safe_threshold, inf] to risk [0.0, 0.3]
            risk = max(0.0, 0.3 - (phi - phi_safe_threshold) * 0.5)  # Decreasing risk as phi increases
        elif phi >= phi_caution_threshold:
            # Caution: map phi [phi_caution_threshold, phi_safe_threshold] to risk [0.3, 0.7]
            range_size = phi_safe_threshold - phi_caution_threshold
            if range_size > 0:
                risk = 0.3 + (phi_safe_threshold - phi) / range_size * 0.4  # Linear interpolation
            else:
                risk = 0.5  # Fallback if thresholds are equal
        else:
            # High-risk: map phi [-inf, phi_caution_threshold] to risk [0.7, 1.0]
            risk = min(1.0, 0.7 + abs(phi - phi_caution_threshold) * 2.0)  # Increasing risk as phi becomes more negative
        
        # Also blend with traditional risk estimation for backward compatibility
        response_text = agent_state.get('response_text', '')
        reported_complexity = agent_state.get('complexity', None)  # Optional now
        coherence_history = self.state.coherence_history[-10:] if len(self.state.coherence_history) >= 2 else None
        
        # Set agent_id in config context for logging (used by estimate_risk)
        config._current_agent_id = self.agent_id
        
        traditional_risk = config.estimate_risk(
            response_text, 
            complexity=0.5,  # Will be derived internally
            coherence=self.state.coherence,
            coherence_history=coherence_history,
            reported_complexity=reported_complexity
        )
        
        # Clear agent_id from config context
        if hasattr(config, '_current_agent_id'):
            delattr(config, '_current_agent_id')
        
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
        # Compute margin for proprioceptive feedback
        margin_info = config.compute_proprioceptive_margin(
            risk_score=risk_score,
            coherence=self.state.coherence,
            void_active=self.state.void_active,
            void_value=self.state.V
        )
        
        # Use UNITARES verdict to influence decision if available
        if unitares_verdict == "high-risk":
            # Override: high-risk verdict -> reject (check if critical)
            # Use RISK_REJECT_THRESHOLD if available, otherwise fall back to RISK_REVISE_THRESHOLD + buffer
            try:
                reject_threshold = config.RISK_REJECT_THRESHOLD
            except AttributeError:
                # Fallback: use revise threshold + buffer (0.50 + 0.20 = 0.70)
                reject_threshold = config.RISK_REVISE_THRESHOLD + 0.20
            effective_reject_threshold = get_effective_threshold("risk_reject_threshold", default=reject_threshold)
            is_critical = risk_score >= effective_reject_threshold
            return {
                'action': 'pause',
                'reason': f'UNITARES high-risk verdict (risk_score={risk_score:.2f}) - safety pause suggested',
                'guidance': 'This is a safety check, not a failure. The system detected high ethical risk and is protecting you from potential issues. Consider simplifying your approach.',
                'critical': is_critical,
                'margin': 'critical',
                'nearest_edge': 'risk'
            }
        elif unitares_verdict == "caution":
            # Caution verdict: proceed with guidance
            # If risk would approve, upgrade to proceed with guidance due to caution
            if risk_score < config.RISK_APPROVE_THRESHOLD:
                # Low risk but caution -> proceed with guidance
                return {
                    'action': 'proceed',
                    'reason': f'Proceeding mindfully (risk: {risk_score:.2f})',
                    'guidance': 'Navigating complexity. Worth a moment of reflection.',
                    'critical': False,
                    'verdict_context': 'aware',  # Reframe "caution" as "aware" when proceeding
                    'margin': margin_info['margin'],
                    'nearest_edge': margin_info['nearest_edge']
                }
            else:
                # Medium/high risk + caution -> use standard decision (likely proceed with guidance or pause)
                return config.make_decision(
                    risk_score=risk_score,
                    coherence=self.state.coherence,
                    void_active=self.state.void_active,
                    void_value=self.state.V
                )
        else:
            # Safe verdict or no verdict: use standard decision logic
            return config.make_decision(
                risk_score=risk_score,
                coherence=self.state.coherence,
                void_active=self.state.void_active,
                void_value=self.state.V
            )
    
    def simulate_update(self, agent_state: Dict, confidence: Optional[float] = None) -> Dict:
        """
        Dry-run governance cycle: Returns decision without persisting state.
        
        Useful for testing decisions before committing. Does NOT modify state.
        
        Optimized: Uses shallow copy + selective deep copy instead of full deepcopy.
        Only deep copies mutable collections (history lists) and nested dataclasses.
        This is 10-100x faster for agents with long histories.
        
        Args:
            agent_state: Agent state dict with parameters, ethical_drift, response_text, complexity
            confidence: Confidence level [0, 1] for this update. If None (default),
                        confidence is derived from observed outcomes + EISV uncertainty.
        
        Returns:
            Same format as process_update, but state is NOT modified
        """
        import copy
        
        # Save current state (shallow copy is sufficient for reference)
        saved_state = self.state
        saved_prev_params = self.prev_parameters
        saved_last_update = self.last_update
        
        try:
            # OPTIMIZED: Shallow copy + selective deep copy
            # Shallow copy the state object (fast)
            temp_state = copy.copy(self.state)
            
            # Deep copy only mutable collections (history lists) - these get appended to
            temp_state.E_history = copy.deepcopy(self.state.E_history)
            temp_state.I_history = copy.deepcopy(self.state.I_history)
            temp_state.S_history = copy.deepcopy(self.state.S_history)
            temp_state.V_history = copy.deepcopy(self.state.V_history)
            temp_state.coherence_history = copy.deepcopy(self.state.coherence_history)
            temp_state.risk_history = copy.deepcopy(self.state.risk_history)
            temp_state.decision_history = copy.deepcopy(self.state.decision_history)
            temp_state.timestamp_history = copy.deepcopy(self.state.timestamp_history)
            temp_state.lambda1_history = copy.deepcopy(self.state.lambda1_history)
            
            # Deep copy nested dataclasses (they get modified during update_dynamics)
            temp_state.unitaires_state = copy.deepcopy(self.state.unitaires_state)
            temp_state.unitaires_theta = copy.deepcopy(self.state.unitaires_theta)
            
            # Shallow copy prev_parameters (it's a simple dict or None)
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
    
    def process_update(self, agent_state: Dict, confidence: Optional[float] = None, task_type: str = "mixed") -> Dict:
        """
        Complete governance cycle: Update → Adapt → Decide

        Args:
            agent_state: Agent state dict with parameters, ethical_drift, response_text, complexity
            confidence: Confidence level [0, 1] for this update. If None (default),
                        confidence is derived from thermodynamic state (I, S, C, V).
                        Pass explicit value to override derivation.
            task_type: Task type context ("convergent", "divergent", "mixed").
                      Affects S=0 interpretation: convergent S=0 is healthy (standardization),
                      divergent S=0 may indicate lack of divergence.

        This is the main API method called by the MCP server.

        Confidence derivation (when not explicitly provided):
            - High Integrity (I) → high confidence
            - Low Entropy (S) → high confidence
            - High Coherence (C) → high confidence
            - Low |Void| (V) → high confidence

        Returns:
        {
            'status': 'healthy' | 'moderate' | 'critical',
            'decision': {...},
            'metrics': {...},
            'sampling_params': {...}
        }
        """
        # Update timestamp
        self.last_update = datetime.now()

        # === DUAL-LOG GROUNDING (Patent: Dual-Log Architecture) ===
        # Process through continuity layer to get grounded metrics.
        # This compares operational (server-derived) vs reflective (agent-reported)
        # to produce grounded complexity that feeds into EISV dynamics.
        response_text = agent_state.get('response_text', '')
        self_complexity = agent_state.get('complexity')
        self_confidence = confidence  # May be None at this point
        client_session_id = agent_state.get('client_session_id', '')
        
        continuity_metrics = self.continuity_layer.process_update(
            response_text=response_text,
            self_complexity=self_complexity,
            self_confidence=self_confidence,
            client_session_id=client_session_id,
            task_type=task_type,
        )
        
        # Store for response and downstream use
        self._last_continuity_metrics = continuity_metrics
        
        # Check restorative balance (detect overload)
        self.restorative_monitor.record(continuity_metrics)
        restorative_status = self.restorative_monitor.check()
        self._last_restorative_status = restorative_status
        
        # Use GROUNDED complexity instead of self-reported
        grounded_agent_state = agent_state.copy()
        grounded_agent_state['complexity'] = continuity_metrics.derived_complexity

        # Log grounding if significant divergence
        if continuity_metrics.complexity_divergence > 0.2:
            logger.info(
                f"Dual-log grounding for {self.agent_id}: "
                f"self={self_complexity}, derived={continuity_metrics.derived_complexity:.3f}, "
                f"divergence={continuity_metrics.complexity_divergence:.3f}"
            )

        # === CONCRETE ETHICAL DRIFT (Patent: De-abstracted Δη) ===
        # Compute Δη from MEASURABLE signals, not abstract concepts.
        # This makes ethical drift empirically verifiable.
        agent_baseline = get_agent_baseline(self.agent_id)

        # Get calibration error from calibration system if available
        calibration_error = None
        try:
            cal_status = calibration_checker.check()
            if cal_status.get('calibrated') and cal_status.get('total_samples', 0) > 10:
                # Use trajectory health deviation from 50% baseline
                # Well-calibrated system should show ~50% success rate on challenging predictions
                trajectory_health = cal_status.get('trajectory_health', 0.5)
                if trajectory_health is not None:
                    # Convert percentage to 0-1 and measure deviation from 0.5 (ideal)
                    calibration_error = abs((trajectory_health / 100.0) - 0.5) * 2  # Scale to [0, 1]
        except Exception:
            pass  # Calibration not available, will use fallback

        # Get current coherence for deviation calculation
        active_params = get_active_params()
        current_coherence = coherence(self.state.V, self.state.unitaires_theta, active_params)

        # Compute concrete drift vector from governance-observed signals
        drift_vector = compute_ethical_drift(
            agent_id=self.agent_id,
            baseline=agent_baseline,
            current_coherence=current_coherence,
            current_confidence=self_confidence if self_confidence is not None else 0.6,
            complexity_divergence=continuity_metrics.complexity_divergence,
            calibration_error=calibration_error,
            decision=None,  # Will be updated after decision is made
        )

        # Blend agent-sent drift with governance-computed drift.
        # Agent drift captures proprioceptive signals (e.g. Lumen's warmth/clarity/stability
        # changes) that governance can't observe. Governance drift captures system-level
        # deviations (calibration, complexity divergence, coherence, stability).
        # Both matter — combine them so agent signals actually affect dynamics.
        agent_drift_raw = agent_state.get('ethical_drift', [0.0, 0.0, 0.0])
        if isinstance(agent_drift_raw, (list, tuple)) and len(agent_drift_raw) >= 1:
            agent_drift_norm = sum(d * d for d in agent_drift_raw) ** 0.5
        else:
            agent_drift_norm = 0.0

        # If agent sent non-trivial drift, blend it into the governance vector.
        # Agent drift maps to: [0]=emotional→calibration, [1]=epistemic→coherence,
        # [2]=behavioral→stability. Weight: 30% agent signal, 70% governance signal.
        # This ensures agent signals matter but governance ground-truth dominates.
        if agent_drift_norm > 0.01:
            ad = list(agent_drift_raw) + [0.0] * max(0, 3 - len(agent_drift_raw))
            blend = 0.3
            drift_vector.calibration_deviation = (
                (1 - blend) * drift_vector.calibration_deviation + blend * min(1.0, abs(ad[0]))
            )
            drift_vector.coherence_deviation = (
                (1 - blend) * drift_vector.coherence_deviation + blend * min(1.0, abs(ad[1]))
            )
            drift_vector.stability_deviation = (
                (1 - blend) * drift_vector.stability_deviation + blend * min(1.0, abs(ad[2]))
            )

        # Store for later access and time-series logging
        self._last_drift_vector = drift_vector

        # Convert to list format for dynamics engine (all 4 components)
        grounded_agent_state['ethical_drift'] = drift_vector.to_list()

        # Log drift if significant
        if drift_vector.norm > 0.3:
            logger.info(
                f"Ethical drift for {self.agent_id}: "
                f"||Δη||={drift_vector.norm:.3f} "
                f"[cal={drift_vector.calibration_deviation:.3f}, "
                f"cpx={drift_vector.complexity_divergence:.3f}, "
                f"coh={drift_vector.coherence_deviation:.3f}, "
                f"stab={drift_vector.stability_deviation:.3f}]"
                f"{' (blended with agent signal)' if agent_drift_norm > 0.01 else ''}"
            )

        # Step 1: Update thermodynamic state with GROUNDED inputs
        self.update_dynamics(grounded_agent_state)

        # Step 1b: Confidence handling - OBSERVE what happened, don't ask for reports
        # The system already tracks tool outcomes. Just look.
        if confidence is None:
            confidence, confidence_metadata = derive_confidence(
                self.state,
                agent_id=self.agent_id  # System looks up outcomes for this agent
            )
        else:
            # External/self-reported confidence can saturate at 1.0 (many clients default to it).
            # To keep telemetry/calibration meaningful, cap external confidence by what the system
            # can justify from observed outcomes + EISV uncertainty penalties.
            external_confidence = float(confidence)
            derived_confidence, derived_metadata = derive_confidence(
                self.state,
                agent_id=self.agent_id
            )
            capped_confidence = min(external_confidence, derived_confidence)
            confidence = capped_confidence
            confidence_metadata = {
                'source': 'external_capped',
                'reliability': 'medium',
                'honesty_note': 'External confidence was capped to system-derived confidence to prevent saturation and preserve telemetry/calibration meaning.',
                'external_provided': external_confidence,
                'derived_cap': derived_confidence,
                'capped': external_confidence > derived_confidence,
                'derived_metadata': derived_metadata,
            }

        # Store confidence and metadata for audit logging and transparency
        self.current_confidence = confidence
        self.confidence_metadata = confidence_metadata
        
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
                
                logger.debug(
                    f"Skipping λ₁ update for {self.agent_id}: "
                    f"confidence {confidence:.3f} < threshold {config.CONTROLLER_CONFIDENCE_THRESHOLD}"
                )
        
        # Step 4: Estimate risk (also gets UNITARES verdict)
        # Use GROUNDED ethical drift (governance-computed + agent-blended, all 4 components)
        # Previously used agent_state (raw 3-element) and truncated to 3, dropping stability.
        delta_eta = grounded_agent_state.get('ethical_drift', [0.0, 0.0, 0.0, 0.0])
        if not delta_eta:
            delta_eta = [0.0, 0.0, 0.0, 0.0]

        # Use governance_core phi_objective and verdict_from_phi
        # drift_norm() handles any-length lists — no truncation needed
        phi = phi_objective(
            state=self.state.unitaires_state,
            delta_eta=delta_eta,
            weights=DEFAULT_WEIGHTS
        )
        unitares_verdict = verdict_from_phi(phi)
        score_result = {'phi': phi, 'verdict': unitares_verdict}
        
        # Estimate risk (uses score_result internally to avoid recomputation)
        risk_score = self.estimate_risk(agent_state, score_result=score_result)
        
        # Adjust decision based on task_type context for S=0 interpretation
        # Convergent tasks (standardization): S=0 is healthy compliance
        # Divergent tasks (divergence): S=0 may indicate lack of creative risk-taking
        task_type = agent_state.get("task_type", "mixed")
        task_type_adjustment = None
        original_risk_score = risk_score
        
        if task_type == "convergent" and self.state.S == 0.0:
            # S=0 in convergent work is healthy - don't penalize
            # Reduce risk score adjustment for low entropy in convergent tasks
            if risk_score > 0.3:  # Only adjust if risk is already elevated
                risk_score = max(0.2, risk_score * 0.8)  # Reduce risk by 20%, floor at 0.2
                task_type_adjustment = {
                    "applied": True,
                    "reason": "Convergent task with S=0 (healthy standardization)",
                    "original_risk": original_risk_score,
                    "adjusted_risk": risk_score,
                    "adjustment": "reduced"
                }
        elif task_type == "divergent" and self.state.S == 0.0:
            # S=0 in divergent work may indicate lack of divergence
            # Slightly increase risk awareness (but don't block - divergence needs freedom)
            if risk_score < 0.4:  # Only adjust if risk is low
                risk_score = min(0.5, risk_score * 1.15)  # Increase by 15%, cap at 0.5
                task_type_adjustment = {
                    "applied": True,
                    "reason": "Divergent task with S=0 (may indicate lack of divergence)",
                    "original_risk": original_risk_score,
                    "adjusted_risk": risk_score,
                    "adjustment": "increased"
                }

        # =================================================================
        # CIRS v0.1: Oscillation detection and resonance damping
        # =================================================================
        # Update oscillation detector with current state
        oscillation_state = self.oscillation_detector.update(
            coherence=float(self.state.coherence),
            risk=float(risk_score),
            route=unitares_verdict,  # Use verdict as route proxy
            threshold_coherence=config.COHERENCE_CRITICAL_THRESHOLD,
            threshold_risk=config.RISK_REVISE_THRESHOLD
        )
        self._last_oscillation_state = oscillation_state

        # Track OI in history
        if not hasattr(self.state, 'oi_history'):
            self.state.oi_history = []
        self.state.oi_history.append(oscillation_state.oi)

        # Apply resonance damping if needed
        damping_result = None
        if oscillation_state.resonant:
            # Increment resonance event counter
            if not hasattr(self.state, 'resonance_events'):
                self.state.resonance_events = 0
            self.state.resonance_events += 1

            # Apply damping (threshold adjustment)
            damping_result = self.resonance_damper.apply_damping(
                current_coherence=float(self.state.coherence),
                current_risk=float(risk_score),
                tau=config.COHERENCE_CRITICAL_THRESHOLD,
                beta=config.RISK_REVISE_THRESHOLD,
                oscillation_state=oscillation_state
            )

            if damping_result.damping_applied:
                if not hasattr(self.state, 'damping_applied_count'):
                    self.state.damping_applied_count = 0
                self.state.damping_applied_count += 1

                logger.info(
                    f"CIRS resonance damping for {self.agent_id}: "
                    f"OI={oscillation_state.oi:.3f}, flips={oscillation_state.flips}, "
                    f"trigger={oscillation_state.trigger}"
                )

        # Classify response tier (proceed/soft_dampen/hard_block)
        response_tier = classify_response(
            coherence=float(self.state.coherence),
            risk=float(risk_score),
            tau=config.COHERENCE_CRITICAL_THRESHOLD,
            beta=config.RISK_REVISE_THRESHOLD,
            tau_low=CIRS_DEFAULTS['tau_low'],
            beta_high=CIRS_DEFAULTS['beta_high'],
            oscillation_state=oscillation_state
        )

        # Step 5: Make decision (using UNITARES verdict)
        decision = self.make_decision(risk_score, unitares_verdict=unitares_verdict)
        
        # Record prediction for STRATEGIC calibration (trajectory health)
        #
        # IMPORTANT: This system does not have direct access to "external correctness"
        # (tests passing, user satisfaction, etc.). Strategic calibration therefore
        # uses a dynamic *trajectory health proxy* in [0,1] derived from state.
        #
        # This enables auto-calibration without manual labeling, while staying honest
        # about what is being measured (health/consensus proxy, not ground-truth success).
        #
        # FIXED: predicted_correct is based on confidence, not decision.
        predicted_correct = confidence >= 0.5
        
        # Trajectory health proxy (0..1): higher when risk is lower.
        # This is intentionally simple and monotonic to avoid overfitting.
        trajectory_health = float(max(0.0, min(1.0, 1.0 - float(risk_score))))

        # Record for STRATEGIC calibration (dynamic, no manual ground truth required)
        calibration_checker.record_prediction(
            confidence=confidence,
            predicted_correct=predicted_correct,
            actual_correct=trajectory_health
        )
        
        # Record for TACTICAL calibration (per-decision, fixed at decision time)
        #
        # NOTE (Dec 2025): Previous logic checked if decision matched state, which was
        # tautological (decision IS based on state → always 100% "correct").
        #
        # NEW LOGIC: Tactical calibration measures if CONFIDENCE matched OUTCOME.
        # - High confidence (>=0.6) should predict healthy state (low risk)
        # - Low confidence (<0.4) should predict unhealthy state (high risk)
        # - This gives real calibration signal: "When I was confident, was I right?"
        #
        decision_action = decision['action']

        # Outcome based on trajectory health (same signal as strategic calibration)
        # Using risk_score < 0.4 as "healthy" threshold
        state_was_healthy = risk_score < 0.4

        # Tactical correctness: Did confidence predict the health outcome?
        # - If confident (>=0.6) and state was healthy → correct
        # - If confident (>=0.6) and state was NOT healthy → incorrect (overconfident)
        # - If not confident (<0.6) and state was NOT healthy → correct
        # - If not confident (<0.6) and state was healthy → incorrect (underconfident)
        #
        # This creates real variance in the calibration data.
        if confidence >= 0.6:
            immediate_outcome = state_was_healthy
        else:
            immediate_outcome = not state_was_healthy

        if decision_action in ('proceed', 'pause'):  # Only record known decision types
            calibration_checker.record_tactical_decision(
                confidence=confidence,
                decision=decision_action,
                immediate_outcome=immediate_outcome
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
        
        # Determine overall status using health thresholds (aligned with health_checker)
        # Use same thresholds as health_checker for consistency: risk_healthy_max=0.35, risk_moderate_max=0.60
        from src.health_thresholds import HealthThresholds
        health_checker = HealthThresholds()
        
        if void_active or self.state.coherence < config.COHERENCE_CRITICAL_THRESHOLD:
            status = 'critical'
        elif risk_score >= health_checker.risk_moderate_max:  # >= 0.60: critical
            status = 'critical'
        elif risk_score >= health_checker.risk_healthy_max:  # 0.35-0.60: moderate
            status = 'moderate'
        else:  # < 0.35: healthy
            status = 'healthy'
        
        # Build metrics dict
        # NOTE: risk_score measures governance/operational risk (likelihood of issues), not ethical risk
        # The actual physics is Φ (phi) and verdict - these are the primary governance signals
        metrics = {
            'E': float(self.state.E),
            'I': float(self.state.I),
            'S': float(self.state.S),
            'V': float(self.state.V),
            'coherence': float(self.state.coherence),
            'lambda1': float(self.state.lambda1),
            'risk_score': float(risk_score),  # Governance/operational risk (70% phi-based + 30% traditional)
            'phi': float(phi),  # Primary physics signal: Φ objective function
            'verdict': unitares_verdict,  # Primary governance signal: safe/caution/high-risk
            'void_active': bool(void_active),
            'regime': str(getattr(self.state, 'regime', 'divergence')),  # Operational regime: DIVERGENCE | TRANSITION | CONVERGENCE | STABLE (with fallback)
            'time': float(self.state.time),
            'updates': int(self.state.update_count),
            'confidence': float(confidence),
            'lambda1_skipped': lambda1_skipped
        }
        
        # Add lambda1_skips count if available
        if hasattr(self.state, 'lambda1_update_skips'):
            metrics['lambda1_update_skips'] = int(self.state.lambda1_update_skips)
        
        result = {
            'status': status,
            'decision': decision,
            'metrics': metrics,
            'sampling_params': sampling_params,
            'timestamp': datetime.now().isoformat(),
            # TRANSPARENCY: Surface confidence reliability info (was computed but hidden)
            'confidence_reliability': {
                'reliability': confidence_metadata.get('reliability', 'unknown'),
                'source': confidence_metadata.get('source', 'unknown'),
                'calibration_applied': confidence_metadata.get('calibration_applied', False),
                'calibration_samples': confidence_metadata.get('calibration_samples', 0),
                'honesty_note': confidence_metadata.get('honesty_note', 'No metadata available')
            }
        }
        
        # Add task_type adjustment info if applied (transparency)
        if task_type_adjustment:
            result['task_type_adjustment'] = task_type_adjustment
        
        # Add dual-log continuity metrics (grounded EISV inputs)
        if self._last_continuity_metrics:
            cm = self._last_continuity_metrics
            result['continuity'] = {
                'derived_complexity': cm.derived_complexity,
                'self_reported_complexity': cm.self_complexity,
                'complexity_divergence': cm.complexity_divergence,
                'overconfidence_signal': cm.overconfidence_signal,
                'underconfidence_signal': cm.underconfidence_signal,
                'E_input': cm.E_input,
                'I_input': cm.I_input,
                'S_input': cm.S_input,
                'calibration_weight': cm.calibration_weight,
            }
        
        # Add restorative balance status if needed
        if self._last_restorative_status and self._last_restorative_status.needs_restoration:
            rs = self._last_restorative_status
            result['restorative'] = {
                'needs_restoration': rs.needs_restoration,
                'reason': rs.reason,
                'suggested_cooldown_seconds': rs.suggested_cooldown_seconds,
                'activity_rate': rs.activity_rate,
                'cumulative_divergence': rs.cumulative_divergence,
            }
            result['guidance'] = (
                f"Consider slowing down: {rs.reason}. "
                f"Suggested cooldown: {rs.suggested_cooldown_seconds}s"
            )

        # =================================================================
        # Concrete Ethical Drift (Patent: De-abstracted Δη)
        # =================================================================
        if self._last_drift_vector:
            dv = self._last_drift_vector
            result['ethical_drift'] = {
                'calibration_deviation': dv.calibration_deviation,
                'complexity_divergence': dv.complexity_divergence,
                'coherence_deviation': dv.coherence_deviation,
                'stability_deviation': dv.stability_deviation,
                'norm': dv.norm,
                'norm_squared': dv.norm_squared,
            }

            # Record telemetry for empirical analysis
            try:
                record_drift(
                    drift_vector=dv,
                    agent_id=self.agent_id,
                    update_count=self.state.update_count,
                    baseline=get_agent_baseline(self.agent_id),
                    decision=decision['action'],
                    confidence=confidence,
                )
            except Exception as e:
                logger.debug(f"Failed to record drift telemetry: {e}")

        # =================================================================
        # HCK v3.0 / CIRS v0.1: Add reflexive control and resonance metrics
        # =================================================================
        result['hck'] = {
            'rho': float(getattr(self.state, 'current_rho', 0.0)),
            'CE': float(self.state.CE_history[-1]) if hasattr(self.state, 'CE_history') and self.state.CE_history else 0.0,
            'gains_modulated': getattr(self, '_gains_modulated', False)
        }

        result['cirs'] = {
            'oi': float(oscillation_state.oi),
            'flips': int(oscillation_state.flips),
            'resonant': bool(oscillation_state.resonant),
            'trigger': oscillation_state.trigger,
            'response_tier': response_tier,
            'resonance_events': int(getattr(self.state, 'resonance_events', 0)),
            'damping_applied_count': int(getattr(self.state, 'damping_applied_count', 0))
        }

        # Add damping details if applied this cycle
        if damping_result and damping_result.damping_applied:
            result['cirs']['damping'] = {
                'd_tau': damping_result.adjustments.get('d_tau', 0),
                'd_beta': damping_result.adjustments.get('d_beta', 0)
            }

        return result
    
    def get_metrics(self, include_state: bool = True) -> Dict:
        """
        Returns current governance metrics
        
        Args:
            include_state: If False, excludes the nested 'state' dict to reduce response size.
                          All state values (E, I, S, V, coherence, lambda1) are still included at top level.
                          Default True for backward compatibility.
        """
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
        # Health status uses RECENT TREND (mean of last 10 risk scores), not overall mean
        # This reflects current behavior rather than all-time history
        if len(self.state.risk_history) >= 10:
            current_risk = float(np.mean(self.state.risk_history[-10:]))  # Recent trend (last 10)
        elif self.state.risk_history:
            current_risk = float(np.mean(self.state.risk_history))  # All available if < 10
        else:
            # No risk history: use coherence fallback or default to None (will show "unknown")
            current_risk = None
        
        # FIX 2025-12-05: Use LATEST (point-in-time) risk_score for consistency with process_update
        # This solves state inconsistency bug where get_metrics vs process_agent_update diverge
        # See docs/fixes/STATE_INCONSISTENCY_BUG_20251205.md for full analysis
        latest_risk_score = float(self.state.risk_history[-1]) if self.state.risk_history else None
        
        # Calculate smoothed trend (for historical context, not primary decision making)
        smoothed_risk_score = current_risk  # Smoothed trend (mean of last 10)
        
        # Calculate overall mean risk (for display/comparison)
        mean_risk = float(np.mean(self.state.risk_history)) if self.state.risk_history else 0.0
        
        # Status calculation - USE LATEST VALUE to match process_update behavior
        # This ensures get_metrics and process_update return consistent status
        from src.health_thresholds import HealthThresholds
        health_checker = HealthThresholds()
        
        # Use latest_risk_score for status (matches process_update)
        status_risk = latest_risk_score if latest_risk_score is not None else current_risk
        
        # Calculate health status consistently using health_checker.get_health_status()
        # This ensures get_metrics() and process_agent_update return the same health_status
        # FIX 2025-12-10: Use health_checker.get_health_status() instead of manual threshold checks
        health_status_obj, _ = health_checker.get_health_status(
            risk_score=status_risk,  # Use latest_risk_score or current_risk
            coherence=self.state.coherence,
            void_active=self.state.void_active
        )
        status = health_status_obj.value
        
        # Compute Φ and verdict from current state (using default ethical_drift if not available)
        # This gives us the physics signal even when we don't have the latest ethical drift
        from governance_core.scoring import phi_objective, verdict_from_phi
        from governance_core.parameters import DEFAULT_WEIGHTS
        phi = phi_objective(
            state=self.state.unitaires_state,
            delta_eta=[0.0, 0.0, 0.0],  # Default - get_metrics doesn't have latest ethical_drift
            weights=DEFAULT_WEIGHTS
        )
        verdict = verdict_from_phi(phi)
        
        risk_score_value = current_risk if current_risk is not None else mean_risk
        
        # Get regime with fallback for backward compatibility (old state files may not have regime)
        regime = getattr(self.state, 'regime', 'divergence')
        
        # Honest initialization: return None for computed metrics when no updates yet
        # This avoids the jarring "coherence dropped from 1.0 to 0.55" UX issue
        is_uninitialized = self.state.update_count == 0

        result = {
            'agent_id': self.agent_id,
            # EISV metrics at top level for consistency with process_update()
            'E': float(self.state.E),
            'I': float(self.state.I),
            'S': float(self.state.S),
            'V': float(self.state.V),
            'coherence': None if is_uninitialized else float(self.state.coherence),
            'lambda1': float(self.state.lambda1),
            'regime': str(regime),  # Operational regime: DIVERGENCE | TRANSITION | CONVERGENCE | STABLE
            'status': 'uninitialized' if is_uninitialized else status,
            'initialized': not is_uninitialized,  # Explicit flag: False until first process_update()
            'sampling_params': config.lambda_to_params(self.state.lambda1),
            'history_size': len(self.state.V_history),
            'current_risk': None if is_uninitialized else current_risk,
            'mean_risk': None if is_uninitialized else mean_risk,
            'risk_score': None if is_uninitialized else risk_score_value,
            'latest_risk_score': None if is_uninitialized else latest_risk_score,
            'phi': float(phi),  # Primary physics signal: Φ objective function
            'verdict': verdict,  # Primary governance signal: safe/caution/high-risk
            'void_active': bool(self.state.void_active),
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

        # =============================================================
        # UNITARES v4.1 basin + convergence tracking (lightweight)
        # =============================================================
        profile = get_params_profile_name()

        # Basin boundary warning (bistability around I≈0.5 in v4.1)
        I = float(self.state.I)
        basin = "unknown"
        basin_warning = None
        if profile == "v41":
            if I < 0.45:
                basin = "low"
                basin_warning = "LOW basin: high risk of collapse equilibrium (I well below ~0.5 boundary)"
            elif I < 0.55:
                basin = "boundary"
                basin_warning = "Near basin boundary (~I=0.5): small shocks can flip equilibrium"
            else:
                basin = "high"

        # Convergence estimate: distance to target equilibrium (paper-aligned vs legacy)
        # Note: S has an epistemic floor (S>=0.001) in the runtime.
        S = float(self.state.S)
        if profile == "v41":
            I_target = 0.91
            S_target = 0.001
            E_target = 0.91
        else:
            # Legacy “equilibrium” guidance used in MCP docs/tooling
            I_target = 1.0
            S_target = 0.0
            E_target = 0.7

        # Euclidean distance in (I,S) plane (matches convergence guidance in core handler)
        eq_dist = float(((I_target - I) ** 2 + (S - S_target) ** 2) ** 0.5)

        # Rough contraction-based estimate using α≈0.1 (paper) and dt (config.DT)
        # This is intentionally a heuristic; exact convergence depends on theta, drift, and complexity.
        dt = float(getattr(config, "DT", 0.1))
        alpha = 0.1
        contraction = max(1e-6, 1.0 - alpha * dt)
        eps = 0.02  # “close enough” threshold for guidance purposes
        est_updates = None
        if eq_dist > 0 and contraction < 1.0:
            try:
                import math
                est_updates = int(math.ceil(max(0.0, math.log(eps / eq_dist) / math.log(contraction))))
            except Exception:
                est_updates = None

        result["unitares_v41"] = {
            "params_profile": profile,
            "basin": basin,
            "basin_warning": basin_warning,
            "equilibrium": {
                "I_target": I_target,
                "S_target": S_target,
                "E_target": E_target,
            },
            "convergence": {
                "equilibrium_distance": eq_dist,
                "estimated_updates_to_eps": est_updates,
                "eps": eps,
                "note": "Heuristic estimate (assumes contraction rate α≈0.1 and dt=config.DT).",
            },
        }
        
        # Include nested state dict only if requested (reduces context bloat)
        if include_state:
            result['state'] = self.state.to_dict()

        # =================================================================
        # HCK v3.0 / CIRS v0.1: Reflexive control and resonance metrics
        # =================================================================
        result['hck'] = {
            'rho': float(getattr(self.state, 'current_rho', 0.0)),
            'CE': float(self.state.CE_history[-1]) if hasattr(self.state, 'CE_history') and self.state.CE_history else 0.0,
            'rho_history_len': len(getattr(self.state, 'rho_history', [])),
            'CE_history_len': len(getattr(self.state, 'CE_history', []))
        }

        # Get last oscillation state if available
        last_osc = getattr(self, '_last_oscillation_state', None)
        result['cirs'] = {
            'oi': float(last_osc.oi) if last_osc else 0.0,
            'flips': int(last_osc.flips) if last_osc else 0,
            'resonant': bool(last_osc.resonant) if last_osc else False,
            'trigger': last_osc.trigger if last_osc else None,
            'resonance_events': int(getattr(self.state, 'resonance_events', 0)),
            'damping_applied_count': int(getattr(self.state, 'damping_applied_count', 0)),
            'oi_history_len': len(getattr(self.state, 'oi_history', []))
        }

        return result

    @staticmethod
    def get_eisv_labels() -> Dict:
        """Returns EISV metric labels and descriptions for API documentation
        
        EISV = the four core UNITARES state variables:
        - E: Energy or presence
        - I: Information integrity
        - S: Entropy
        - V: Void integral
        
        Updated 2025-11-26: Removed misleading semantic descriptions.
        These metrics track thermodynamic structure, not semantic content quality.
        """
        return {
            'E': {
                'label': 'Energy',
                'description': 'Energy (divergence/productive capacity)',
                'user_friendly': 'How engaged and energized your work feels',
                'range': '[0.0, 1.0]'
            },
            'I': {
                'label': 'Information Integrity',
                'description': 'Information integrity',
                'user_friendly': 'Consistency and coherence of your approach',
                'range': '[0.0, 1.0]'
            },
            'S': {
                'label': 'Entropy',
                'description': 'Entropy (disorder/uncertainty)',
                'user_friendly': 'How scattered or fragmented things are',
                'range': '[0.0, 1.0]'
            },
            'V': {
                'label': 'Void Integral',
                'description': 'Void integral (E-I imbalance accumulation)',
                'user_friendly': 'Accumulated strain from energy-integrity mismatch',
                'range': '(-inf, +inf)'
            }
        }

    def export_history(self, format: str = 'json') -> str:
        """Exports complete history for analysis"""
        import csv
        import io
        
        # Backward compatibility: ensure decision_history and lambda1_history exist
        decision_history = getattr(self.state, 'decision_history', [])
        lambda1_history = getattr(self.state, 'lambda1_history', [])
        
        history = {
            'agent_id': self.agent_id,
            'timestamps': self.state.timestamp_history,  # Timestamps for each update
            'E_history': self.state.E_history,  # Full history
            'I_history': self.state.I_history,  # Full history
            'S_history': self.state.S_history,  # Full history
            'V_history': self.state.V_history,
            'coherence_history': self.state.coherence_history,
            'risk_history': self.state.risk_history,  # Stores risk_score values over time
            'attention_history': self.state.risk_history,  # DEPRECATED: Use risk_history instead. Kept for backward compatibility.
            'decision_history': decision_history,
            'lambda1_history': lambda1_history,  # Full lambda1 adaptation history
            'lambda1_final': self.state.lambda1,  # Current lambda1 (for backward compatibility)
            'total_updates': self.state.update_count,
            'total_time': self.state.time
        }
        
        if format == 'json':
            return json.dumps(history, indent=2)
        elif format == 'csv':
            # Convert to CSV format
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header - standardized column order
            # Note: 'risk_score' column contains values from risk_history (stores risk_score over time)
            writer.writerow(['update', 'timestamp', 'E', 'I', 'S', 'V', 'coherence', 'risk_score', 'decision', 'lambda1'])
            
            # Write data rows - use full history for E/I/S/V/coherence/risk/decision/lambda1
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
                    lambda1_history[i] if i < len(lambda1_history) else ''  # Full lambda1 history
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
            logger.debug(f"\n[Update {i}]")
            logger.debug(f"  Status: {result['status']}")
            logger.debug(f"  Decision: {result['decision']['action']}")
            logger.debug(f"  Metrics: E={result['metrics']['E']:.3f}, "
                          f"I={result['metrics']['I']:.3f}, S={result['metrics']['S']:.3f}, "
                          f"V={result['metrics']['V']:.3f}, coherence={result['metrics']['coherence']:.3f}, "
                          f"λ₁={result['metrics']['lambda1']:.3f}")
    
    # Get final metrics
    logger.info("\n" + "="*60)
    logger.info("Final Metrics:")
    logger.info(json.dumps(monitor.get_metrics(), indent=2))
