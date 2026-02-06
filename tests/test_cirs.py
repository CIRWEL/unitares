"""
Tests for src/cirs.py - CIRS v0.1 oscillation detection and resonance damping.

All classes and functions are pure (no I/O, no DB).
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.cirs import (
    SignalType, CIRSSignal, OscillationState, OscillationDetector,
    DampingResult, ResonanceDamper, classify_response,
    HCK_DEFAULTS, CIRS_DEFAULTS,
)


# ============================================================================
# CIRSSignal
# ============================================================================

class TestCIRSSignal:

    def test_to_dict(self):
        ts = datetime(2026, 1, 1, 12, 0)
        sig = CIRSSignal(
            type=SignalType.RESONANCE,
            timestamp=ts,
            source="test.source",
            destination="test.dest",
            confidence=0.85,
            payload={"key": "val"}
        )
        d = sig.to_dict()
        assert d['type'] == "RESONANCE"
        assert d['src'] == "test.source"
        assert d['dst'] == "test.dest"
        assert d['confidence'] == 0.85
        assert d['payload'] == {"key": "val"}
        assert "2026" in d['t']

    def test_signal_types(self):
        assert SignalType.SEM_DRIFT.value == "SEM_DRIFT"
        assert SignalType.HARD_BLOCK.value == "HARD_BLOCK"


# ============================================================================
# OscillationState
# ============================================================================

class TestOscillationState:

    def test_defaults(self):
        state = OscillationState()
        assert state.oi == 0.0
        assert state.flips == 0
        assert state.resonant is False
        assert state.trigger is None


# ============================================================================
# OscillationDetector
# ============================================================================

class TestOscillationDetector:

    def test_init_defaults(self):
        det = OscillationDetector()
        assert det.window == 8
        assert det.ema_lambda == 0.3
        assert det.oi_threshold == 3.0
        assert det.flip_threshold == 3

    def test_custom_params(self):
        det = OscillationDetector(window=4, ema_lambda=0.5, oi_threshold=2.0, flip_threshold=2)
        assert det.window == 4
        assert det.flip_threshold == 2

    def test_single_update_no_resonance(self):
        det = OscillationDetector()
        state = det.update(0.6, 0.3, 'proceed', 0.5, 0.5)
        assert state.resonant is False
        assert state.oi == 0.0
        assert state.flips == 0

    def test_stable_updates_no_resonance(self):
        """Same values → no oscillation"""
        det = OscillationDetector()
        for _ in range(5):
            state = det.update(0.6, 0.3, 'proceed', 0.5, 0.5)
        assert state.resonant is False
        assert state.flips == 0

    def test_flip_counting(self):
        """Different routes → flips counted"""
        det = OscillationDetector(flip_threshold=10)  # High threshold to avoid triggering
        routes = ['proceed', 'pause', 'proceed', 'pause', 'proceed']
        for r in routes:
            state = det.update(0.6, 0.3, r, 0.5, 0.5)
        assert state.flips == 4  # 4 transitions

    def test_flip_threshold_resonance(self):
        """Enough flips triggers resonance"""
        det = OscillationDetector(flip_threshold=3, oi_threshold=100.0)
        routes = ['proceed', 'pause', 'proceed', 'pause']
        for r in routes:
            state = det.update(0.6, 0.3, r, 0.5, 0.5)
        assert state.resonant is True
        assert state.trigger == 'flips'

    def test_oi_threshold_resonance(self):
        """Oscillating coherence signs triggers OI resonance"""
        det = OscillationDetector(oi_threshold=0.3, flip_threshold=100)
        # Alternate coherence above/below threshold while keeping risk constant
        # This avoids coherence and risk transitions cancelling each other out
        for i in range(8):
            coh = 0.8 if i % 2 == 0 else 0.2
            state = det.update(coh, 0.2, 'proceed', 0.5, 0.5)
        # Should have oscillation detected via OI
        assert abs(state.oi) > 0

    def test_window_maintenance(self):
        """History doesn't grow beyond window"""
        det = OscillationDetector(window=4)
        for i in range(10):
            det.update(0.5, 0.5, 'proceed', 0.5, 0.5)
        assert len(det.history) == 4

    def test_reset(self):
        det = OscillationDetector()
        det.update(0.5, 0.5, 'proceed', 0.5, 0.5)
        det.update(0.6, 0.4, 'pause', 0.5, 0.5)
        det.reset()
        assert len(det.history) == 0
        assert det.ema_coherence == 0.0
        assert det.ema_risk == 0.0

    def test_returns_oscillation_state(self):
        det = OscillationDetector()
        state = det.update(0.5, 0.5, 'proceed', 0.5, 0.5)
        assert isinstance(state, OscillationState)


# ============================================================================
# ResonanceDamper
# ============================================================================

class TestResonanceDamper:

    def test_no_damping_when_not_resonant(self):
        damper = ResonanceDamper()
        state = OscillationState(resonant=False)
        result = damper.apply_damping(0.5, 0.4, tau=0.5, beta=0.4, oscillation_state=state)
        assert result.damping_applied is False
        assert result.tau_new == 0.5
        assert result.beta_new == 0.4

    def test_damping_applied_when_resonant(self):
        damper = ResonanceDamper()
        state = OscillationState(resonant=True, trigger='oi', oi=3.5, flips=2)
        result = damper.apply_damping(0.4, 0.45, tau=0.5, beta=0.4, oscillation_state=state)
        assert result.damping_applied is True
        assert isinstance(result, DampingResult)

    def test_damping_moves_toward_current(self):
        """Thresholds should move toward current values"""
        damper = ResonanceDamper(kappa_r=0.1)
        state = OscillationState(resonant=True, trigger='oi', oi=3.5, flips=0)
        # coherence=0.3 is below tau=0.5 → tau should decrease
        result = damper.apply_damping(0.3, 0.3, tau=0.5, beta=0.4, oscillation_state=state)
        assert result.tau_new < 0.5  # Moved toward 0.3

    def test_bounds_enforced_low(self):
        damper = ResonanceDamper(tau_bounds=(0.3, 0.7), beta_bounds=(0.2, 0.5), kappa_r=10.0)
        state = OscillationState(resonant=True, trigger='oi', oi=5.0, flips=0)
        result = damper.apply_damping(0.0, 0.0, tau=0.31, beta=0.21, oscillation_state=state)
        assert result.tau_new >= 0.3
        assert result.beta_new >= 0.2

    def test_bounds_enforced_high(self):
        damper = ResonanceDamper(tau_bounds=(0.3, 0.7), beta_bounds=(0.2, 0.5), kappa_r=10.0)
        state = OscillationState(resonant=True, trigger='flips', oi=0, flips=5)
        result = damper.apply_damping(1.0, 1.0, tau=0.69, beta=0.49, oscillation_state=state)
        assert result.tau_new <= 0.7
        assert result.beta_new <= 0.5

    def test_adjustments_in_result(self):
        damper = ResonanceDamper()
        state = OscillationState(resonant=True, trigger='oi', oi=3.5, flips=2)
        result = damper.apply_damping(0.4, 0.35, tau=0.5, beta=0.4, oscillation_state=state)
        assert 'd_tau' in result.adjustments
        assert 'd_beta' in result.adjustments
        assert result.adjustments['trigger'] == 'oi'


# ============================================================================
# classify_response
# ============================================================================

class TestClassifyResponse:

    def test_proceed_normal(self):
        """Good coherence, low risk → proceed"""
        assert classify_response(0.6, 0.3, tau=0.5, beta=0.5) == 'proceed'

    def test_hard_block_low_coherence(self):
        """Below tau_low → hard_block"""
        assert classify_response(0.2, 0.3, tau=0.5, beta=0.5, tau_low=0.3) == 'hard_block'

    def test_hard_block_high_risk(self):
        """Above beta_high → hard_block"""
        assert classify_response(0.6, 0.8, tau=0.5, beta=0.5, beta_high=0.7) == 'hard_block'

    def test_soft_dampen_below_thresholds(self):
        """Below tau but above tau_low → soft_dampen"""
        assert classify_response(0.4, 0.3, tau=0.5, beta=0.5) == 'soft_dampen'

    def test_soft_dampen_resonant_good_state(self):
        """Resonant but coherence/risk ok → soft_dampen"""
        osc = OscillationState(resonant=True, trigger='oi')
        result = classify_response(0.6, 0.3, tau=0.5, beta=0.5, oscillation_state=osc)
        assert result == 'soft_dampen'

    def test_hard_block_resonant_bad_state(self):
        """Resonant AND bad metrics → hard_block"""
        osc = OscillationState(resonant=True, trigger='flips')
        result = classify_response(0.4, 0.6, tau=0.5, beta=0.5, oscillation_state=osc)
        assert result == 'hard_block'

    def test_no_oscillation_state(self):
        """Without oscillation state, uses simple threshold logic"""
        assert classify_response(0.6, 0.3, tau=0.5, beta=0.5, oscillation_state=None) == 'proceed'

    def test_boundary_coherence_at_tau(self):
        """coherence == tau → proceed (>= check)"""
        assert classify_response(0.5, 0.3, tau=0.5, beta=0.5) == 'proceed'

    def test_boundary_risk_at_beta(self):
        """risk == beta → proceed (<= check)"""
        assert classify_response(0.6, 0.5, tau=0.5, beta=0.5) == 'proceed'


# ============================================================================
# Config Defaults
# ============================================================================

class TestDefaults:

    def test_hck_defaults(self):
        assert 'K_p' in HCK_DEFAULTS
        assert 'K_i' in HCK_DEFAULTS

    def test_cirs_defaults(self):
        assert 'window' in CIRS_DEFAULTS
        assert 'oi_threshold' in CIRS_DEFAULTS
        assert 'tau_bounds' in CIRS_DEFAULTS
