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

# Extracted monitor subsystems (Phase 6 decomposition)
from src.monitor_void import check_void_state as _check_void_state, calculate_void_frequency as _calculate_void_frequency
from src.monitor_risk import estimate_risk as _estimate_risk
from src.monitor_decision import make_decision as _make_decision
from src.monitor_regime import detect_regime as _detect_regime
from src.monitor_lambda import update_lambda1 as _update_lambda1

# Import dual-log architecture for grounded EISV inputs (Patent: Dual-Log Architecture)
from src.dual_log import ContinuityLayer, RestorativeBalanceMonitor

# Import drift telemetry for empirical data collection (Patent: De-abstracted Δη)
from src.drift_telemetry import record_drift

# Import UNITARES Phase-3 engine from governance_core (v2.0)
# Core dynamics are now in governance_core module
from src._imports import ensure_project_root

# Ensure project root is in path for imports
ensure_project_root()

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
    # Research tools (migrated from unitaires_core)
    approximate_stability_check, suggest_theta_update,
)

# UNITARES params profile selection (optional v4.1 alignment)
from governance_core.parameters import get_active_params

# Import extracted modules
from src.governance_state import GovernanceState
from src.confidence import derive_confidence
from src.cirs import (
    OscillationDetector, ResonanceDamper, OscillationState,
    classify_response, CIRS_DEFAULTS, HCK_DEFAULTS
)
from src.hck_reflexive import (
    compute_update_coherence as _compute_update_coherence,
    compute_continuity_energy as _compute_continuity_energy,
    modulate_gains as _modulate_gains,
)
from src.monitor_metrics import (
    get_monitor_metrics as _get_monitor_metrics,
    get_eisv_labels as _get_eisv_labels,
    export_monitor_history as _export_monitor_history,
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

    # HCK v3.0: Delegating to src/hck_reflexive.py
    compute_update_coherence = staticmethod(_compute_update_coherence)
    compute_continuity_energy = staticmethod(_compute_continuity_energy)
    modulate_gains = staticmethod(_modulate_gains)

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

        # HCK v3.0: Track previous EISV for update coherence ρ(t) and state velocity
        self._prev_E: Optional[float] = None
        self._prev_I: Optional[float] = None
        self._prev_S: Optional[float] = None
        self._prev_V: Optional[float] = None
        self._last_state_velocity: float = 0.0

        # CIRS: Initialize oscillation detector / adaptive governor
        from config.governance_config import GovernanceConfig as GovConfig
        if GovConfig.ADAPTIVE_GOVERNOR_ENABLED:
            from governance_core.adaptive_governor import AdaptiveGovernor
            self.adaptive_governor = AdaptiveGovernor()
            self.oscillation_detector = None
            self.resonance_damper = None
        else:
            # Legacy v0.1 path
            self.adaptive_governor = None
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
                # Restore AdaptiveGovernor state if available
                gov_dict = getattr(persisted_state, '_governor_state_dict', None)
                if gov_dict and self.adaptive_governor is not None:
                    from governance_core.adaptive_governor import GovernorState
                    self.adaptive_governor.state = GovernorState.from_dict(gov_dict)
                    logger.debug(f"Restored governor state: tau={self.adaptive_governor.state.tau:.3f}, beta={self.adaptive_governor.state.beta:.3f}")
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

        delta = np.asarray(current_params - prev_params, dtype=np.float64)
        with np.errstate(over="ignore"):
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
        delta = np.asarray(current_params - prev_params, dtype=np.float64)
        with np.errstate(over="ignore"):
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
        """Detect current operational regime based on state and history."""
        return _detect_regime(self.state)
    
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

        # Extract sensor EISV for spring coupling (agents with physical sensors, e.g. Lumen)
        sensor_eisv = None
        raw_sensor_eisv = agent_state.get('sensor_eisv')
        if raw_sensor_eisv and isinstance(raw_sensor_eisv, dict):
            try:
                sensor_eisv = State(
                    E=float(np.clip(raw_sensor_eisv.get('E', 0.5), 0.0, 1.0)),
                    I=float(np.clip(raw_sensor_eisv.get('I', 0.5), 0.0, 1.0)),
                    S=float(np.clip(raw_sensor_eisv.get('S', 0.2), 0.001, 2.0)),
                    V=float(np.clip(raw_sensor_eisv.get('V', 0.0), -2.0, 2.0)),
                )
            except (TypeError, ValueError, KeyError):
                sensor_eisv = None

        # Store parameters for potential future use (deprecated - not used in coherence)
        # Note: param_coherence removed in favor of pure thermodynamic signal
        self.prev_parameters = parameters.copy() if len(parameters) > 0 else None

        # Use governance_core step_state() to evolve state (CANONICAL DYNAMICS)
        # Params are profile-selectable (default vs v4.1 paper-aligned) via:
        # - UNITARES_PARAMS_PROFILE=default|v41
        # - UNITARES_PARAMS_JSON='{"beta_I": 0.05, ...}'
        active_params = get_active_params()

        # Apply per-agent delta from adaptive governor
        if self.adaptive_governor is not None:
            from dataclasses import replace as dataclass_replace
            active_params = dataclass_replace(
                active_params, delta=self.adaptive_governor.state.delta
            )

        # Calibration feedback: overconfidence raises entropy S
        # When agents claim high confidence but achieve low trajectory health,
        # the calibration error becomes a thermodynamic price on S.
        calibration_penalty = 0.0
        try:
            metrics = calibration_checker.compute_calibration_metrics()
            if metrics:
                # Find max overconfidence across bins with sufficient data
                for bin_metrics in metrics.values():
                    if bin_metrics.count >= 2:
                        # Positive = expected > actual = overconfident
                        overconfidence = bin_metrics.expected_accuracy - bin_metrics.accuracy
                        if overconfidence > 0:
                            # Dampen penalty for low-sample bins (full weight at 5+ samples)
                            sample_weight = min(1.0, bin_metrics.count / 5.0)
                            calibration_penalty = max(calibration_penalty, 0.2 * overconfidence * sample_weight)
        except Exception:
            pass  # Fail-safe: no penalty if calibration unavailable

        self.state.unitaires_state = step_state(
            state=self.state.unitaires_state,
            theta=self.state.unitaires_theta,
            delta_eta=delta_eta,
            dt=dt,
            noise_S=calibration_penalty,  # Overconfidence raises entropy
            params=active_params,
            complexity=complexity,  # Complexity now affects S dynamics
            sensor_eisv=sensor_eisv,  # Spring coupling to physical sensors (if available)
        )

        # Epistemic humility safeguard: Enforce entropy floor (S >= 0.001) always
        # Perfect equilibrium (S=0.0) is dangerous and brittle - maintain epistemic humility at all times
        if self.state.unitaires_state.S < 0.001:
            # Maintain epistemic humility: "I could be wrong about something I can't see"
            self.state.unitaires_state.S = 0.001

        # V bounds: match ODE's built-in range [-2, 2]
        # Negative V is physically meaningful: coherence(V) is designed for V ∈ [-2, 2]
        self.state.unitaires_state.V = max(-2.0, min(2.0, self.state.unitaires_state.V))

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
        # Also compute 4D state velocity for ethical drift signal injection
        # =================================================================
        import math as _math
        if all(v is not None for v in [self._prev_E, self._prev_I, self._prev_S, self._prev_V]):
            delta_E = float(self.state.E) - self._prev_E
            delta_I = float(self.state.I) - self._prev_I
            delta_S = float(self.state.S) - self._prev_S
            delta_V = float(self.state.V) - self._prev_V
            rho = self.compute_update_coherence(delta_E, delta_I)
            self._last_state_velocity = _math.sqrt(
                delta_E**2 + delta_I**2 + delta_S**2 + delta_V**2
            )
        else:
            rho = 0.0  # First update, no previous state
            self._last_state_velocity = 0.0

        # Update prev values for next iteration
        self._prev_E = float(self.state.E)
        self._prev_I = float(self.state.I)
        self._prev_S = float(self.state.S)
        self._prev_V = float(self.state.V)

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
                    'decision': self.state.decision_history[i] if abs(i) <= len(self.state.decision_history) else None
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
                if not (-2.0 <= self.state.V <= 2.0):
                    self.state.unitaires_state.V = np.clip(self.state.V, -2.0, 2.0)
                    logger.info(f"Auto-fixed V to {self.state.V}")
                if not (0.0 <= self.state.coherence <= 1.0):
                    self.state.coherence = np.clip(self.state.coherence, 0.0, 1.0)
                    logger.info(f"Auto-fixed coherence to {self.state.coherence}")

        # Update time
        self.state.time += dt
        self.state.update_count += 1
    
    def check_void_state(self) -> bool:
        """Checks if system is in void state: |V| > threshold."""
        return _check_void_state(self.state)

    def _calculate_void_frequency(self) -> float:
        """Calculate void frequency from V history."""
        return _calculate_void_frequency(self.state)
    
    def update_lambda1(self) -> float:
        """Updates lambda1 using PI controller based on void frequency and coherence targets."""
        return _update_lambda1(self.state)
    
    def estimate_risk(self, agent_state: Dict, score_result: Dict = None) -> float:
        """Estimate risk score using governance_core phi_objective and verdict_from_phi."""
        return _estimate_risk(self.state, agent_state, score_result)
    
    def make_decision(self, risk_score: float, unitares_verdict: str = None,
                      response_tier: str = None, oscillation_state: 'OscillationState' = None) -> Dict:
        """Makes autonomous governance decision using UNITARES verdict and CIRS response tier."""
        return _make_decision(self.state, risk_score, unitares_verdict, response_tier, oscillation_state)
    
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
            state_velocity=self._last_state_velocity,
            task_context=task_type,
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

        # Track consecutive high-drift updates for auto-dialectic trigger
        drift_dialectic_threshold = 0.7
        if drift_vector.norm > drift_dialectic_threshold:
            self._consecutive_high_drift = getattr(self, '_consecutive_high_drift', 0) + 1
        else:
            self._consecutive_high_drift = 0

        # Convert to list format for dynamics engine (all 4 components)
        drift_vector_list = drift_vector.to_list()

        # Prevent drift signal from vanishing on complex tasks
        complexity = grounded_agent_state.get('complexity', 0.0)
        drift_norm_sq = sum(d ** 2 for d in drift_vector_list)
        if drift_norm_sq < 0.001 and complexity > 0.3:
            # Complex work always has some uncertainty, even with stable baselines
            min_component = 0.05 * complexity / max(1, len(drift_vector_list))
            drift_vector_list = [max(d, min_component) for d in drift_vector_list]

        grounded_agent_state['ethical_drift'] = drift_vector_list

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
            # Relax threshold when coherence is declining — prevents feedback loop
            # where low confidence blocks the controller that would fix declining coherence
            effective_conf_threshold = config.CONTROLLER_CONFIDENCE_THRESHOLD
            if (hasattr(self.state, 'coherence') and
                    self.state.coherence < config.TARGET_COHERENCE and
                    hasattr(self.state, 'coherence_history') and
                    len(self.state.coherence_history) >= 3):
                recent = list(self.state.coherence_history)[-3:]
                if recent[-1] < recent[0]:  # declining trend
                    effective_conf_threshold = 0.40

            if confidence >= effective_conf_threshold:
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
                    threshold=effective_conf_threshold,
                    update_count=self.state.update_count,
                    reason=f"confidence {confidence:.3f} < threshold {effective_conf_threshold}"
                )

                logger.debug(
                    f"Skipping λ₁ update for {self.agent_id}: "
                    f"confidence {confidence:.3f} < threshold {effective_conf_threshold}"
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
        # Prefer explicit function argument; fall back to agent_state
        if task_type == "mixed":
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
        elif task_type in ("exploration", "introspection") and risk_score > 0.5:
            # Honest uncertainty on exploratory/introspective tasks is not degradation.
            # Low confidence is the appropriate epistemic state — don't trigger pause.
            risk_adjustment = -0.08
            risk_score = max(0.45, risk_score + risk_adjustment)  # floor raised to match RISK_APPROVE_THRESHOLD
            task_type_adjustment = {
                "applied": True,
                "reason": f"{task_type} task: low confidence is appropriate epistemic state",
                "original_risk": original_risk_score,
                "adjusted_risk": risk_score,
                "adjustment": "reduced",
                "risk_adjusted_by": risk_adjustment,
            }

        # =================================================================
        # CIRS: Oscillation detection and resonance damping
        # =================================================================
        from config.governance_config import GovernanceConfig as GovConfig

        if GovConfig.ADAPTIVE_GOVERNOR_ENABLED and self.adaptive_governor is not None:
            # CIRS v2: Adaptive Governor — PID-based threshold management
            cirs_result = self.adaptive_governor.update(
                coherence=float(self.state.coherence),
                risk=float(risk_score),
                verdict=unitares_verdict,
                E_history=list(getattr(self.state, 'E_history', [0.5]*6)),
                I_history=list(getattr(self.state, 'I_history', [0.5]*6)),
                S_history=list(getattr(self.state, 'S_history', [0.5]*6)),
                complexity_history=list(getattr(self.state, 'complexity_history', [0.3]*6)),
                V_history=list(getattr(self.state, 'V_history', [0.0]*6)),
            )
            oscillation_state = OscillationState(
                oi=cirs_result['oi'],
                flips=cirs_result['flips'],
                resonant=cirs_result['resonant'],
                trigger=cirs_result['trigger'],
            )
            self._last_oscillation_state = oscillation_state
            response_tier = cirs_result['verdict']
            damping_result = None  # Damping is built into the PID cycle
        else:
            # Legacy v0.1 path (unchanged)
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

            # Use damped thresholds if damping was applied, otherwise static config
            effective_tau = (damping_result.tau_new
                            if damping_result and damping_result.damping_applied
                            else config.COHERENCE_CRITICAL_THRESHOLD)
            effective_beta = (damping_result.beta_new
                              if damping_result and damping_result.damping_applied
                              else config.RISK_REVISE_THRESHOLD)

            # Classify response tier (proceed/soft_dampen/hard_block)
            response_tier = classify_response(
                coherence=float(self.state.coherence),
                risk=float(risk_score),
                tau=effective_tau,
                beta=effective_beta,
                tau_low=CIRS_DEFAULTS['tau_low'],
                beta_high=CIRS_DEFAULTS['beta_high'],
                oscillation_state=oscillation_state
            )

        # Step 5: Make decision (using UNITARES verdict + CIRS oscillation state)
        decision = self.make_decision(
            risk_score,
            unitares_verdict=unitares_verdict,
            response_tier=response_tier,
            oscillation_state=oscillation_state
        )
        
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
        self.state.decision_history.append(decision.get('sub_action', decision['action']))
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

        if GovConfig.ADAPTIVE_GOVERNOR_ENABLED and self.adaptive_governor is not None:
            result['cirs'] = cirs_result  # Full observability from governor
        else:
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
    
    # Metrics and export: delegating to src/monitor_metrics.py
    def get_metrics(self, include_state: bool = True) -> Dict:
        """Returns current governance metrics."""
        return _get_monitor_metrics(self, include_state)

    get_eisv_labels = staticmethod(_get_eisv_labels)

    def export_history(self, format: str = 'json') -> str:
        """Exports complete history for analysis."""
        return _export_monitor_history(self, format)


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
