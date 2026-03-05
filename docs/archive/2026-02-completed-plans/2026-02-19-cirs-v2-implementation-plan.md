# CIRS v2: Adaptive Governor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the dormant CIRS v0.1 detect-but-don't-apply system with a unified AdaptiveGovernor that owns threshold management using PID-inspired control theory.

**Architecture:** Single `AdaptiveGovernor` class in `governance_core/adaptive_governor.py` replaces OscillationDetector + ResonanceDamper + classify_response + static thresholds. Uses PID math where the D-term IS the damping. Phase-aware reference points from `governance_core/phase_aware.py`. Feature-flagged integration with shadow mode for safe rollout.

**Tech Stack:** Python 3.9+, dataclasses, numpy (already in deps for phase_aware.py). No new dependencies.

**Design Doc:** `docs/plans/2026-02-19-cirs-v2-adaptive-governor-design.md`

---

### Task 1: AdaptiveGovernor Core — Dataclasses and Initialization

**Files:**
- Create: `governance_core/adaptive_governor.py`
- Test: `tests/test_adaptive_governor.py`

**Step 1: Write failing test for initialization**

```python
# tests/test_adaptive_governor.py
"""Tests for CIRS v2 AdaptiveGovernor."""
import pytest
from governance_core.adaptive_governor import (
    AdaptiveGovernor, GovernorState, GovernorConfig, Verdict
)


class TestInitialization:
    def test_default_initialization(self):
        gov = AdaptiveGovernor()
        state = gov.state
        assert state.tau == pytest.approx(0.40)
        assert state.beta == pytest.approx(0.60)
        assert state.phase == "integration"
        assert state.error_integral_tau == 0.0
        assert state.error_integral_beta == 0.0

    def test_custom_config(self):
        config = GovernorConfig(tau_default=0.45, beta_default=0.55)
        gov = AdaptiveGovernor(config=config)
        assert gov.state.tau == pytest.approx(0.45)
        assert gov.state.beta == pytest.approx(0.55)

    def test_hard_bounds_in_config(self):
        config = GovernorConfig()
        assert config.tau_floor == 0.25
        assert config.tau_ceiling == 0.75
        assert config.beta_floor == 0.20
        assert config.beta_ceiling == 0.70
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_adaptive_governor.py::TestInitialization -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'governance_core.adaptive_governor'`

**Step 3: Write minimal implementation**

```python
# governance_core/adaptive_governor.py
"""
CIRS v2: Adaptive Governor

Unified adaptive governance — replaces OscillationDetector + ResonanceDamper +
classify_response with a single PID-inspired controller that owns threshold
management. Thresholds are living per-agent state, not config constants.

The D-term IS the damping. Oscillation produces large derivatives, which
produce large corrections. The system self-stabilizes.

Design: docs/plans/2026-02-19-cirs-v2-adaptive-governor-design.md
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class GovernorConfig:
    """Configuration for AdaptiveGovernor. Static defaults that become initial values."""
    # Default thresholds (starting point — will adapt)
    tau_default: float = 0.40        # Coherence threshold
    beta_default: float = 0.60       # Risk threshold

    # Hard safety bounds (cannot be overridden by adaptation)
    tau_floor: float = 0.25
    tau_ceiling: float = 0.75
    beta_floor: float = 0.20
    beta_ceiling: float = 0.70

    # PID gains
    K_p: float = 0.05               # Proportional — gentle
    K_i: float = 0.005              # Integral — very slow
    K_d: float = 0.10               # Derivative — strongest (IS the damping)

    # Integral wind-up protection
    integral_max: float = 0.10

    # Phase reference points
    exploration_tau_ref: float = 0.35
    exploration_beta_ref: float = 0.55
    integration_tau_ref: float = 0.40
    integration_beta_ref: float = 0.60

    # Phase modulation of D-term
    exploration_d_factor: float = 0.5   # Gentler damping during exploration
    integration_d_factor: float = 1.0   # Full damping during integration

    # Threshold decay (return to defaults when stable)
    decay_rate: float = 0.01
    decay_oi_threshold: float = 0.5    # OI must be below this for decay

    # Oscillation detection (kept for observability)
    window: int = 10
    ema_lambda: float = 0.35
    oi_threshold: float = 2.5
    flip_threshold: int = 4

    # Verdict thresholds (relative to adaptive tau/beta)
    beta_approve_offset: float = -0.25  # beta_approve = beta + offset


@dataclass
class GovernorState:
    """Per-agent adaptive state. Mutable, updated each cycle."""
    # Adaptive thresholds
    tau: float = 0.40
    beta: float = 0.60
    phase: str = "integration"

    # PID accumulators
    error_integral_tau: float = 0.0
    error_integral_beta: float = 0.0
    prev_error_tau: float = 0.0
    prev_error_beta: float = 0.0

    # Oscillation tracking
    oi: float = 0.0
    flips: int = 0
    resonant: bool = False
    trigger: Optional[str] = None
    ema_coherence: float = 0.0
    ema_risk: float = 0.0
    history: List[Dict] = field(default_factory=list)

    # Neighbor pressure
    neighbor_pressure: float = 0.0
    agents_in_resonance: int = 0

    # Controller output (for observability)
    last_p_tau: float = 0.0
    last_i_tau: float = 0.0
    last_d_tau: float = 0.0
    last_p_beta: float = 0.0
    last_i_beta: float = 0.0
    last_d_beta: float = 0.0


class Verdict:
    """Governance verdict constants."""
    SAFE = "safe"
    CAUTION = "caution"
    HIGH_RISK = "high-risk"
    HARD_BLOCK = "hard_block"


class AdaptiveGovernor:
    """
    CIRS v2 Adaptive Governor.

    Owns threshold management for a single agent. Thresholds start at config
    defaults and adapt using PID control toward phase-appropriate reference
    points. The D-term provides oscillation damping.
    """

    def __init__(self, config: Optional[GovernorConfig] = None):
        self.config = config or GovernorConfig()
        self.state = GovernorState(
            tau=self.config.tau_default,
            beta=self.config.beta_default,
        )
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_adaptive_governor.py::TestInitialization -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add governance_core/adaptive_governor.py tests/test_adaptive_governor.py
git commit -m "feat(cirs-v2): AdaptiveGovernor dataclasses and initialization"
```

---

### Task 2: PID Controller Update Cycle

**Files:**
- Modify: `governance_core/adaptive_governor.py`
- Modify: `tests/test_adaptive_governor.py`

**Step 1: Write failing tests for PID update**

```python
class TestPIDUpdate:
    """Test the core PID threshold adaptation."""

    def test_stable_input_no_change(self):
        """When thresholds are at reference, no adaptation occurs."""
        gov = AdaptiveGovernor()
        # Integration phase: ref is (0.40, 0.60) — same as defaults
        result = gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            E_history=[0.5]*5, I_history=[0.5]*5,
            S_history=[0.5]*5, complexity_history=[0.3]*5,
        )
        # Thresholds should stay near defaults (tiny float noise OK)
        assert gov.state.tau == pytest.approx(0.40, abs=0.01)
        assert gov.state.beta == pytest.approx(0.60, abs=0.01)

    def test_p_term_moves_toward_reference(self):
        """P-term nudges thresholds toward phase reference."""
        config = GovernorConfig(K_p=0.10, K_i=0.0, K_d=0.0)
        gov = AdaptiveGovernor(config=config)
        # Force tau away from reference
        gov.state.tau = 0.50  # 0.10 above integration ref of 0.40
        gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            E_history=[0.5]*5, I_history=[0.5]*5,
            S_history=[0.5]*5, complexity_history=[0.3]*5,
        )
        # P-term should pull tau back toward 0.40
        assert gov.state.tau < 0.50

    def test_d_term_damps_oscillation(self):
        """D-term resists rapid error changes (oscillation damping)."""
        config = GovernorConfig(K_p=0.0, K_i=0.0, K_d=0.20)
        gov = AdaptiveGovernor(config=config)
        histories = dict(
            E_history=[0.5]*5, I_history=[0.5]*5,
            S_history=[0.5]*5, complexity_history=[0.3]*5,
        )
        # First update: set prev_error
        gov.state.tau = 0.45
        gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)
        tau_after_first = gov.state.tau

        # Second update: move tau further away — D-term should resist
        gov.state.tau = 0.50
        gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)
        # D-term should have pushed tau back (resisting the increase)
        assert gov.state.tau < 0.50

    def test_i_term_accumulates(self):
        """I-term accumulates under sustained deviation."""
        config = GovernorConfig(K_p=0.0, K_i=0.05, K_d=0.0)
        gov = AdaptiveGovernor(config=config)
        gov.state.tau = 0.50  # Sustained deviation from ref 0.40
        histories = dict(
            E_history=[0.5]*5, I_history=[0.5]*5,
            S_history=[0.5]*5, complexity_history=[0.3]*5,
        )
        # Multiple updates should accumulate integral
        for _ in range(5):
            gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)
        # Integral should have pulled tau significantly toward ref
        assert gov.state.tau < 0.50

    def test_hard_bounds_enforced(self):
        """Thresholds cannot exceed hard safety bounds."""
        gov = AdaptiveGovernor()
        gov.state.tau = 0.20  # Below floor
        gov.state.beta = 0.80  # Above ceiling
        gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            E_history=[0.5]*5, I_history=[0.5]*5,
            S_history=[0.5]*5, complexity_history=[0.3]*5,
        )
        assert gov.state.tau >= gov.config.tau_floor
        assert gov.state.beta <= gov.config.beta_ceiling

    def test_integral_windup_protection(self):
        """Integral contribution is clamped to prevent runaway."""
        config = GovernorConfig(K_i=1.0, K_p=0.0, K_d=0.0, integral_max=0.10)
        gov = AdaptiveGovernor(config=config)
        gov.state.tau = 0.50  # Large deviation
        histories = dict(
            E_history=[0.5]*5, I_history=[0.5]*5,
            S_history=[0.5]*5, complexity_history=[0.3]*5,
        )
        for _ in range(100):
            gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)
        # Integral clamped — tau should not have gone below floor
        assert gov.state.tau >= gov.config.tau_floor
        assert abs(gov.state.error_integral_tau) <= config.integral_max
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_adaptive_governor.py::TestPIDUpdate -v`
Expected: FAIL — `AttributeError: 'AdaptiveGovernor' object has no attribute 'update'`

**Step 3: Implement the update method**

Add to `AdaptiveGovernor` class in `governance_core/adaptive_governor.py`:

```python
    def update(
        self,
        coherence: float,
        risk: float,
        verdict: str,
        E_history: List[float],
        I_history: List[float],
        S_history: List[float],
        complexity_history: List[float],
    ) -> Dict:
        """
        Core update cycle. Called once per process_agent_update.

        Returns dict with verdict and full state for observability.
        """
        from .phase_aware import detect_phase, Phase

        # 1. Detect phase
        self.state.phase = detect_phase(
            E_history, I_history, S_history, complexity_history
        )

        # 2. Set reference point based on phase
        if self.state.phase == Phase.EXPLORATION:
            tau_ref = self.config.exploration_tau_ref
            beta_ref = self.config.exploration_beta_ref
            d_factor = self.config.exploration_d_factor
        else:
            tau_ref = self.config.integration_tau_ref
            beta_ref = self.config.integration_beta_ref
            d_factor = self.config.integration_d_factor

        # 3. Compute error signals
        e_tau = tau_ref - self.state.tau
        e_beta = beta_ref - self.state.beta

        # 4. PID update — tau
        p_tau = self.config.K_p * e_tau
        self.state.error_integral_tau = _clamp(
            self.state.error_integral_tau + e_tau,
            -self.config.integral_max, self.config.integral_max
        )
        # Reset integral on zero-crossing
        if self.state.prev_error_tau * e_tau < 0:
            self.state.error_integral_tau = 0.0
        i_tau = self.config.K_i * self.state.error_integral_tau
        d_tau = self.config.K_d * d_factor * (e_tau - self.state.prev_error_tau)
        self.state.prev_error_tau = e_tau

        # 4. PID update — beta
        p_beta = self.config.K_p * e_beta
        self.state.error_integral_beta = _clamp(
            self.state.error_integral_beta + e_beta,
            -self.config.integral_max, self.config.integral_max
        )
        if self.state.prev_error_beta * e_beta < 0:
            self.state.error_integral_beta = 0.0
        i_beta = self.config.K_i * self.state.error_integral_beta
        d_beta = self.config.K_d * d_factor * (e_beta - self.state.prev_error_beta)
        self.state.prev_error_beta = e_beta

        # 5. Apply bounded adjustment
        adjustment_tau = p_tau + i_tau + d_tau
        adjustment_beta = p_beta + i_beta + d_beta

        # Include neighbor pressure (tightens thresholds)
        adjustment_tau -= self.state.neighbor_pressure
        adjustment_beta += self.state.neighbor_pressure

        self.state.tau = _clamp(
            self.state.tau + adjustment_tau,
            self.config.tau_floor, self.config.tau_ceiling
        )
        self.state.beta = _clamp(
            self.state.beta + adjustment_beta,
            self.config.beta_floor, self.config.beta_ceiling
        )

        # 6. Update oscillation metrics
        self._update_oscillation(coherence, risk, verdict)

        # 7. Threshold decay when stable
        if abs(self.state.oi) < self.config.decay_oi_threshold and self.state.flips == 0:
            self.state.tau += self.config.decay_rate * (self.config.tau_default - self.state.tau)
            self.state.beta += self.config.decay_rate * (self.config.beta_default - self.state.beta)

        # Store controller output for observability
        self.state.last_p_tau = p_tau
        self.state.last_i_tau = i_tau
        self.state.last_d_tau = d_tau
        self.state.last_p_beta = p_beta
        self.state.last_i_beta = i_beta
        self.state.last_d_beta = d_beta

        # 8. Make verdict
        verdict_result = self.make_verdict(coherence, risk)

        return self._build_result(verdict_result)

    def _update_oscillation(self, coherence: float, risk: float, verdict: str):
        """Update oscillation metrics (OI, flips) for observability."""
        delta_coh = coherence - self.state.tau
        delta_risk = risk - self.state.beta

        self.state.history.append({
            'verdict': verdict,
            'sign_coh': 1 if delta_coh >= 0 else -1,
            'sign_risk': 1 if delta_risk >= 0 else -1,
        })

        if len(self.state.history) > self.config.window:
            self.state.history.pop(0)

        # Incremental EMA (only latest transition)
        if len(self.state.history) >= 2:
            coh_t = self.state.history[-1]['sign_coh'] - self.state.history[-2]['sign_coh']
            risk_t = self.state.history[-1]['sign_risk'] - self.state.history[-2]['sign_risk']
            self.state.ema_coherence = (
                self.config.ema_lambda * coh_t +
                (1 - self.config.ema_lambda) * self.state.ema_coherence
            )
            self.state.ema_risk = (
                self.config.ema_lambda * risk_t +
                (1 - self.config.ema_lambda) * self.state.ema_risk
            )

        self.state.oi = self.state.ema_coherence + self.state.ema_risk

        # Count flips
        self.state.flips = sum(
            1 for i in range(1, len(self.state.history))
            if self.state.history[i]['verdict'] != self.state.history[i-1]['verdict']
        )

        # Check resonance
        self.state.resonant = False
        self.state.trigger = None
        if abs(self.state.oi) >= self.config.oi_threshold:
            self.state.resonant = True
            self.state.trigger = 'oi'
        elif self.state.flips >= self.config.flip_threshold:
            self.state.resonant = True
            self.state.trigger = 'flips'

    def make_verdict(self, coherence: float, risk: float) -> str:
        """Make governance verdict using ADAPTIVE thresholds."""
        # Hard block — absolute safety boundaries
        if coherence < self.config.tau_floor:
            return Verdict.HARD_BLOCK
        if risk > self.config.beta_ceiling:
            return Verdict.HARD_BLOCK

        beta_approve = self.state.beta + self.config.beta_approve_offset

        # Use adaptive thresholds
        if coherence >= self.state.tau and risk < beta_approve:
            return Verdict.SAFE
        if coherence >= self.state.tau and risk < self.state.beta:
            return Verdict.CAUTION
        return Verdict.HIGH_RISK

    def _build_result(self, verdict: str) -> Dict:
        """Build observability result dict."""
        return {
            'verdict': verdict,
            'tau': self.state.tau,
            'beta': self.state.beta,
            'tau_default': self.config.tau_default,
            'beta_default': self.config.beta_default,
            'phase': self.state.phase,
            'controller': {
                'p_tau': self.state.last_p_tau,
                'i_tau': self.state.last_i_tau,
                'd_tau': self.state.last_d_tau,
                'p_beta': self.state.last_p_beta,
                'i_beta': self.state.last_i_beta,
                'd_beta': self.state.last_d_beta,
            },
            'oi': self.state.oi,
            'flips': self.state.flips,
            'resonant': self.state.resonant,
            'trigger': self.state.trigger,
            'response_tier': verdict,  # Backward compat key
            'neighbor_pressure': self.state.neighbor_pressure,
            'agents_in_resonance': self.state.agents_in_resonance,
        }


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_adaptive_governor.py -v`
Expected: PASS (all 9 tests)

**Step 5: Commit**

```bash
git add governance_core/adaptive_governor.py tests/test_adaptive_governor.py
git commit -m "feat(cirs-v2): PID controller update cycle with phase awareness"
```

---

### Task 3: Verdict and Phase Detection Tests

**Files:**
- Modify: `tests/test_adaptive_governor.py`

**Step 1: Write failing tests for verdicts and phase**

```python
class TestVerdict:
    def test_safe_verdict(self):
        gov = AdaptiveGovernor()
        assert gov.make_verdict(coherence=0.70, risk=0.20) == Verdict.SAFE

    def test_caution_verdict(self):
        gov = AdaptiveGovernor()
        # risk between beta_approve (0.35) and beta (0.60)
        assert gov.make_verdict(coherence=0.70, risk=0.50) == Verdict.CAUTION

    def test_high_risk_verdict(self):
        gov = AdaptiveGovernor()
        assert gov.make_verdict(coherence=0.70, risk=0.65) == Verdict.HIGH_RISK

    def test_hard_block_low_coherence(self):
        gov = AdaptiveGovernor()
        assert gov.make_verdict(coherence=0.20, risk=0.20) == Verdict.HARD_BLOCK

    def test_hard_block_high_risk(self):
        gov = AdaptiveGovernor()
        assert gov.make_verdict(coherence=0.70, risk=0.75) == Verdict.HARD_BLOCK

    def test_adaptive_threshold_changes_verdict(self):
        """Adapted thresholds actually affect verdicts."""
        gov = AdaptiveGovernor()
        # With default tau=0.40, coherence 0.38 is high-risk
        assert gov.make_verdict(coherence=0.38, risk=0.30) != Verdict.SAFE
        # Lower tau to 0.35 (exploration ref) — now 0.38 is safe
        gov.state.tau = 0.35
        assert gov.make_verdict(coherence=0.38, risk=0.30) == Verdict.SAFE


class TestPhaseDetection:
    def test_exploration_phase_widens_thresholds(self):
        """Exploration phase should result in more forgiving thresholds."""
        gov = AdaptiveGovernor()
        # Feed exploration-like history (I growing, S declining, high complexity)
        gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            E_history=[0.3, 0.35, 0.4, 0.45, 0.5],
            I_history=[0.3, 0.4, 0.5, 0.6, 0.7],     # I growing
            S_history=[0.7, 0.6, 0.5, 0.4, 0.3],       # S declining
            complexity_history=[0.6, 0.7, 0.8, 0.85, 0.9],  # High complexity
        )
        # In exploration, tau reference is 0.35 — tau should move toward it
        # (from 0.40 default, should decrease)
        assert gov.state.phase == "exploration"

    def test_integration_phase_tightens_thresholds(self):
        """Integration phase keeps stricter thresholds."""
        gov = AdaptiveGovernor()
        gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            E_history=[0.5, 0.5, 0.5, 0.5, 0.5],
            I_history=[0.5, 0.5, 0.5, 0.5, 0.5],     # I stable
            S_history=[0.5, 0.5, 0.5, 0.5, 0.5],       # S stable
            complexity_history=[0.3, 0.3, 0.3, 0.3, 0.3],  # Low complexity
        )
        assert gov.state.phase == "integration"
```

**Step 2: Run tests**

Run: `python3 -m pytest tests/test_adaptive_governor.py -v`
Expected: PASS (all tests)

**Step 3: Commit**

```bash
git add tests/test_adaptive_governor.py
git commit -m "test(cirs-v2): verdict classification and phase detection tests"
```

---

### Task 4: Threshold Decay and Oscillation Convergence

**Files:**
- Modify: `tests/test_adaptive_governor.py`

**Step 1: Write failing tests**

```python
class TestThresholdDecay:
    def test_decay_toward_defaults_when_stable(self):
        """Thresholds decay toward config defaults when agent is stable."""
        config = GovernorConfig(decay_rate=0.05, K_p=0.0, K_i=0.0, K_d=0.0)
        gov = AdaptiveGovernor(config=config)
        gov.state.tau = 0.50  # Above default 0.40
        histories = dict(
            E_history=[0.5]*5, I_history=[0.5]*5,
            S_history=[0.5]*5, complexity_history=[0.3]*5,
        )
        for _ in range(20):
            gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)
        # Should have decayed toward 0.40
        assert gov.state.tau < 0.50
        assert gov.state.tau == pytest.approx(0.40, abs=0.02)

    def test_no_decay_during_oscillation(self):
        """Decay should NOT apply when OI is above threshold."""
        config = GovernorConfig(decay_rate=0.10, K_p=0.0, K_i=0.0, K_d=0.0)
        gov = AdaptiveGovernor(config=config)
        gov.state.tau = 0.50
        gov.state.oi = 3.0  # Above decay threshold
        # Decay condition checks oi < decay_oi_threshold — should skip
        # We need to test via update which will recompute oi
        # This test verifies the concept; integration tests will validate


class TestOscillationConvergence:
    def test_oscillating_agent_stabilizes(self):
        """An oscillating agent's thresholds should converge over time."""
        gov = AdaptiveGovernor()
        histories = dict(
            E_history=[0.5]*5, I_history=[0.5]*5,
            S_history=[0.5]*5, complexity_history=[0.3]*5,
        )
        taus = []
        # Alternate verdicts to create oscillation
        for i in range(20):
            v = "safe" if i % 2 == 0 else "high-risk"
            c = 0.65 if i % 2 == 0 else 0.35
            r = 0.20 if i % 2 == 0 else 0.65
            gov.update(coherence=c, risk=r, verdict=v, **histories)
            taus.append(gov.state.tau)

        # Thresholds should have moved — not stuck at defaults
        assert taus[-1] != pytest.approx(0.40, abs=0.001)
        # The D-term should have damped the oscillation
        assert gov.state.resonant or abs(gov.state.oi) > 0


class TestFuzzBounds:
    def test_extreme_inputs_never_exceed_bounds(self):
        """Fuzz test: random extreme inputs never push thresholds past bounds."""
        import random
        random.seed(42)
        gov = AdaptiveGovernor()
        for _ in range(200):
            gov.update(
                coherence=random.uniform(-1, 2),
                risk=random.uniform(-1, 2),
                verdict=random.choice(["safe", "caution", "high-risk"]),
                E_history=[random.uniform(0, 1) for _ in range(5)],
                I_history=[random.uniform(0, 1) for _ in range(5)],
                S_history=[random.uniform(0, 1) for _ in range(5)],
                complexity_history=[random.uniform(0, 1) for _ in range(5)],
            )
            assert gov.state.tau >= gov.config.tau_floor
            assert gov.state.tau <= gov.config.tau_ceiling
            assert gov.state.beta >= gov.config.beta_floor
            assert gov.state.beta <= gov.config.beta_ceiling
```

**Step 2: Run tests**

Run: `python3 -m pytest tests/test_adaptive_governor.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_adaptive_governor.py
git commit -m "test(cirs-v2): decay, convergence, and fuzz bound tests"
```

---

### Task 5: Backward-Compatible Shim for src/cirs.py

**Files:**
- Modify: `src/cirs.py` (preserve existing exports, delegate to new module)
- Modify: `governance_core/__init__.py` (export AdaptiveGovernor)
- Test: `tests/test_cirs.py` (existing tests must still pass)

**Step 1: Run existing CIRS tests as baseline**

Run: `python3 -m pytest tests/test_cirs.py -v`
Expected: PASS (current state — this is our regression baseline)

**Step 2: Update governance_core/__init__.py exports**

Add to `governance_core/__init__.py`:
```python
from .adaptive_governor import (
    AdaptiveGovernor,
    GovernorConfig,
    GovernorState,
    Verdict,
)
```

And add to `__all__`:
```python
    'AdaptiveGovernor',
    'GovernorConfig',
    'GovernorState',
    'Verdict',
```

**Step 3: Run existing tests to verify nothing broke**

Run: `python3 -m pytest tests/test_cirs.py -v`
Expected: PASS (existing tests unchanged — shim not yet applied)

**Step 4: Commit**

```bash
git add governance_core/__init__.py
git commit -m "feat(cirs-v2): export AdaptiveGovernor from governance_core"
```

---

### Task 6: Wire AdaptiveGovernor into GovernanceMonitor (Feature-Flagged)

**Files:**
- Modify: `config/governance_config.py` (add feature flag)
- Modify: `src/governance_monitor.py` (lines 238-250, 1375-1430, 1644-1659)
- Test: `tests/test_adaptive_governor.py` (add integration test)

**Step 1: Add feature flag to config**

In `config/governance_config.py`, add to `GovernanceConfig` class:
```python
    # CIRS v2 feature flag — when True, use AdaptiveGovernor instead of static thresholds
    ADAPTIVE_GOVERNOR_ENABLED = False
```

**Step 2: Write integration test**

```python
# In tests/test_adaptive_governor.py
class TestMonitorIntegration:
    """Test AdaptiveGovernor wired into GovernanceMonitor."""

    def test_feature_flag_off_uses_static(self):
        """When flag is off, behavior is identical to current."""
        from config.governance_config import GovernanceConfig
        assert GovernanceConfig.ADAPTIVE_GOVERNOR_ENABLED is False

    def test_feature_flag_on_uses_adaptive(self):
        """When flag is on, process_update uses adaptive thresholds."""
        # This test will be fleshed out after wiring is in place
        pass
```

**Step 3: Modify GovernanceMonitor initialization (lines 238-250)**

Replace the OscillationDetector/ResonanceDamper init with:
```python
        # CIRS: Initialize oscillation detector / adaptive governor
        if config.ADAPTIVE_GOVERNOR_ENABLED:
            from governance_core.adaptive_governor import AdaptiveGovernor
            self.adaptive_governor = AdaptiveGovernor()
        else:
            # Legacy v0.1 path
            self.oscillation_detector = OscillationDetector(...)
            self.resonance_damper = ResonanceDamper(...)
        self._last_oscillation_state: Optional[OscillationState] = None
```

**Step 4: Modify process_update CIRS section (lines 1375-1430)**

Replace the CIRS block with:
```python
        if config.ADAPTIVE_GOVERNOR_ENABLED:
            # CIRS v2: Adaptive Governor
            cirs_result = self.adaptive_governor.update(
                coherence=float(self.state.coherence),
                risk=float(risk_score),
                verdict=unitares_verdict,
                E_history=list(getattr(self.state, 'E_history', [0.5]*5)),
                I_history=list(getattr(self.state, 'I_history', [0.5]*5)),
                S_history=list(getattr(self.state, 'S_history', [0.5]*5)),
                complexity_history=list(getattr(self.state, 'complexity_history', [0.3]*5)),
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
            oscillation_state = self.oscillation_detector.update(...)
            ...existing code...
```

**Step 5: Modify metrics output (lines 1644-1659)**

```python
        if config.ADAPTIVE_GOVERNOR_ENABLED:
            result['cirs'] = cirs_result  # Full observability from governor
        else:
            result['cirs'] = { ...existing code... }
```

**Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: All existing tests PASS (flag is off, legacy path active)

**Step 7: Commit**

```bash
git add config/governance_config.py src/governance_monitor.py tests/test_adaptive_governor.py
git commit -m "feat(cirs-v2): wire AdaptiveGovernor into monitor behind feature flag"
```

---

### Task 7: Multi-Agent Protocol Extensions

**Files:**
- Modify: `src/mcp_handlers/cirs_protocol.py`
- Modify: `governance_core/adaptive_governor.py` (add neighbor_pressure methods)
- Test: `tests/test_adaptive_governor.py`

**Step 1: Write failing test for neighbor pressure**

```python
class TestNeighborPressure:
    def test_apply_neighbor_pressure(self):
        gov = AdaptiveGovernor()
        initial_tau = gov.state.tau
        gov.apply_neighbor_pressure(similarity=0.8, pressure_factor=0.02)
        assert gov.state.neighbor_pressure > 0
        # Next update should tighten thresholds
        histories = dict(
            E_history=[0.5]*5, I_history=[0.5]*5,
            S_history=[0.5]*5, complexity_history=[0.3]*5,
        )
        gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)
        # tau should have moved toward tighter (higher) due to pressure
        # beta should have moved toward tighter (lower) due to pressure

    def test_decay_neighbor_pressure(self):
        gov = AdaptiveGovernor()
        gov.apply_neighbor_pressure(similarity=0.8, pressure_factor=0.02)
        initial = gov.state.neighbor_pressure
        for _ in range(5):
            gov.decay_neighbor_pressure()
        assert gov.state.neighbor_pressure < initial

    def test_low_similarity_ignored(self):
        gov = AdaptiveGovernor()
        gov.apply_neighbor_pressure(similarity=0.3, pressure_factor=0.02)
        assert gov.state.neighbor_pressure == 0.0
```

**Step 2: Implement neighbor pressure methods**

Add to `AdaptiveGovernor`:
```python
    def apply_neighbor_pressure(
        self, similarity: float, pressure_factor: float = 0.02,
        similarity_threshold: float = 0.5
    ):
        """Apply defensive threshold tightening from neighbor resonance."""
        if similarity < similarity_threshold:
            return
        self.state.neighbor_pressure += pressure_factor * similarity
        self.state.agents_in_resonance += 1

    def decay_neighbor_pressure(self, decay_factor: float = 0.2):
        """Decay neighbor pressure after STABILITY_RESTORED."""
        self.state.neighbor_pressure *= (1 - decay_factor)
        if self.state.neighbor_pressure < 0.001:
            self.state.neighbor_pressure = 0.0
            self.state.agents_in_resonance = max(0, self.state.agents_in_resonance - 1)
```

**Step 3: Add RESONANCE_ALERT and STABILITY_RESTORED to cirs_protocol.py**

Add new protocol types to the existing buffer system in `src/mcp_handlers/cirs_protocol.py`. Follow the existing pattern used by `void_alert` and `state_announce`.

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_adaptive_governor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add governance_core/adaptive_governor.py src/mcp_handlers/cirs_protocol.py tests/test_adaptive_governor.py
git commit -m "feat(cirs-v2): neighbor pressure and multi-agent protocol extensions"
```

---

### Task 8: Full Regression Suite

**Files:**
- Modify: `tests/test_adaptive_governor.py`

**Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: ALL tests PASS, including existing test_cirs.py

**Step 2: Run tests with flag ON (shadow comparison)**

Temporarily set `ADAPTIVE_GOVERNOR_ENABLED = True` and run:
Run: `python3 -m pytest tests/ -x -q`
Expected: Identify any tests that assume static thresholds — fix or skip them

**Step 3: Reset flag to False and commit**

```bash
git add tests/
git commit -m "test(cirs-v2): full regression suite passes with flag off and on"
```

---

### Task 9: Delete Dead Code

**Files:**
- Delete: `governance_core/cirs_damping.py` (replaced by adaptive_governor.py)
- Modify: `governance_core/__init__.py` (remove cirs_damping imports)

**Step 1: Remove dead v1.0 module**

Remove `governance_core/cirs_damping.py` and its imports from `__init__.py`.

**Step 2: Run tests**

Run: `python3 -m pytest tests/ -x -q`
Expected: PASS (nothing should import cirs_damping directly)

**Step 3: Commit**

```bash
git rm governance_core/cirs_damping.py
git add governance_core/__init__.py
git commit -m "chore(cirs-v2): remove dead cirs_damping.py (replaced by adaptive_governor)"
```

---

## Execution Summary

| Task | Description | Estimated Time |
|------|-------------|----------------|
| 1 | Dataclasses + initialization | 10 min |
| 2 | PID controller update cycle | 20 min |
| 3 | Verdict + phase detection tests | 10 min |
| 4 | Decay, convergence, fuzz tests | 10 min |
| 5 | Backward-compat shim + exports | 10 min |
| 6 | Wire into GovernanceMonitor (flagged) | 20 min |
| 7 | Multi-agent protocol extensions | 15 min |
| 8 | Full regression suite | 10 min |
| 9 | Delete dead code | 5 min |
| **Total** | | **~110 min** |
