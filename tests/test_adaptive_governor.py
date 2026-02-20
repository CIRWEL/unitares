"""Tests for CIRS v2 AdaptiveGovernor.

Covers Tasks 1-2 of the implementation plan:
- Dataclasses, initialization, config defaults
- PID controller update cycle (P, I, D terms)
- Verdict classification with adaptive thresholds
- Phase detection integration
- Threshold decay toward defaults
- Oscillation convergence
- Fuzz testing for hard bounds
"""

import random

import pytest

from governance_core.adaptive_governor import (
    AdaptiveGovernor,
    GovernorConfig,
    GovernorState,
    Verdict,
    _clamp,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_histories():
    """Return EISV histories that detect_phase classifies as 'integration'."""
    return dict(
        E_history=[0.5] * 6,
        I_history=[0.5] * 6,
        S_history=[0.5] * 6,
        complexity_history=[0.3] * 6,
    )


def _exploration_histories():
    """Return EISV histories that detect_phase classifies as 'exploration'.

    I growing, S declining, high complexity -> 3/3 exploration signals.
    Need window+1 = 6 samples for detect_phase with default window=5.
    """
    return dict(
        E_history=[0.30, 0.35, 0.40, 0.45, 0.50, 0.55],
        I_history=[0.30, 0.40, 0.50, 0.60, 0.70, 0.80],
        S_history=[0.70, 0.60, 0.50, 0.40, 0.30, 0.20],
        complexity_history=[0.60, 0.70, 0.80, 0.85, 0.90, 0.95],
    )


# ===========================================================================
# TestInitialization
# ===========================================================================


class TestInitialization:
    """Task 1 -- dataclasses, config, initial state."""

    def test_default_initialization(self):
        gov = AdaptiveGovernor()
        state = gov.state
        assert state.tau == pytest.approx(0.40)
        assert state.beta == pytest.approx(0.60)
        assert state.phase == "integration"
        assert state.error_integral_tau == 0.0
        assert state.error_integral_beta == 0.0
        assert state.prev_error_tau == 0.0
        assert state.prev_error_beta == 0.0
        assert state.oi == 0.0
        assert state.flips == 0
        assert state.neighbor_pressure == 0.0

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

    def test_pid_gains_in_config(self):
        config = GovernorConfig()
        assert config.K_p == 0.05
        assert config.K_i == 0.005
        assert config.K_d == 0.10
        assert config.integral_max == 0.10

    def test_phase_references_in_config(self):
        config = GovernorConfig()
        assert config.exploration_tau_ref == 0.35
        assert config.exploration_beta_ref == 0.55
        assert config.integration_tau_ref == 0.40
        assert config.integration_beta_ref == 0.60

    def test_governor_state_defaults(self):
        state = GovernorState()
        assert state.tau == 0.40
        assert state.beta == 0.60
        assert state.history == []
        assert state.resonant is False
        assert state.trigger is None

    def test_verdict_constants(self):
        assert Verdict.SAFE == "safe"
        assert Verdict.CAUTION == "caution"
        assert Verdict.HIGH_RISK == "high-risk"
        assert Verdict.HARD_BLOCK == "hard_block"


# ===========================================================================
# TestPIDUpdate
# ===========================================================================


class TestPIDUpdate:
    """Task 2 -- core PID threshold adaptation."""

    def test_stable_input_no_change(self):
        """When thresholds are at reference, no adaptation occurs."""
        gov = AdaptiveGovernor()
        # Integration phase: ref is (0.40, 0.60) -- same as defaults.
        result = gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            **_stable_histories(),
        )
        # Thresholds should stay near defaults (tiny float noise OK).
        assert gov.state.tau == pytest.approx(0.40, abs=0.01)
        assert gov.state.beta == pytest.approx(0.60, abs=0.01)
        # Result dict must include key fields.
        assert "verdict" in result
        assert "tau" in result
        assert "beta" in result
        assert "controller" in result
        assert "phase" in result

    def test_p_term_moves_toward_reference(self):
        """P-term nudges thresholds toward phase reference."""
        config = GovernorConfig(K_p=0.10, K_i=0.0, K_d=0.0, decay_rate=0.0)
        gov = AdaptiveGovernor(config=config)
        # Force tau away from integration reference of 0.40.
        gov.state.tau = 0.50
        gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            **_stable_histories(),
        )
        # P-term should pull tau back toward 0.40.
        assert gov.state.tau < 0.50

    def test_p_term_direction_for_beta(self):
        """P-term nudges beta toward phase reference too."""
        config = GovernorConfig(K_p=0.10, K_i=0.0, K_d=0.0, decay_rate=0.0)
        gov = AdaptiveGovernor(config=config)
        # Force beta away from integration reference of 0.60.
        gov.state.beta = 0.50  # below ref
        gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            **_stable_histories(),
        )
        # P-term should push beta back toward 0.60.
        assert gov.state.beta > 0.50

    def test_d_term_damps_oscillation(self):
        """D-term resists rapid error changes (oscillation damping)."""
        config = GovernorConfig(K_p=0.0, K_i=0.0, K_d=0.20, decay_rate=0.0)
        gov = AdaptiveGovernor(config=config)
        histories = _stable_histories()

        # First update: set prev_error from tau=0.45 (error = 0.40-0.45 = -0.05).
        gov.state.tau = 0.45
        gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)
        tau_after_first = gov.state.tau

        # Second update: move tau further away -- D-term should resist.
        gov.state.tau = 0.50
        gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)
        # D-term = K_d * d_factor * (e_new - e_prev).
        # e_new = 0.40 - 0.50 = -0.10, e_prev = -0.05 from first update.
        # D-term = 0.20 * 1.0 * (-0.10 - (-0.05)) = 0.20 * (-0.05) = -0.01.
        # So adjustment is negative, pulling tau down. tau < 0.50.
        assert gov.state.tau < 0.50

    def test_i_term_accumulates(self):
        """I-term accumulates under sustained deviation."""
        config = GovernorConfig(K_p=0.0, K_i=0.05, K_d=0.0, decay_rate=0.0)
        gov = AdaptiveGovernor(config=config)
        gov.state.tau = 0.50  # Sustained deviation from ref 0.40
        histories = _stable_histories()

        # Multiple updates should accumulate integral.
        for _ in range(5):
            gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)

        # Integral should have pulled tau toward ref.
        assert gov.state.tau < 0.50
        # The integral itself should be non-zero.
        assert gov.state.error_integral_tau != 0.0

    def test_hard_bounds_enforced(self):
        """Thresholds cannot exceed hard safety bounds."""
        gov = AdaptiveGovernor()
        gov.state.tau = 0.20  # Below floor
        gov.state.beta = 0.80  # Above ceiling
        gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            **_stable_histories(),
        )
        assert gov.state.tau >= gov.config.tau_floor
        assert gov.state.beta <= gov.config.beta_ceiling

    def test_integral_windup_protection(self):
        """Integral contribution is clamped to prevent runaway."""
        config = GovernorConfig(K_i=1.0, K_p=0.0, K_d=0.0, integral_max=0.10)
        gov = AdaptiveGovernor(config=config)
        gov.state.tau = 0.50  # Large deviation
        histories = _stable_histories()

        for _ in range(100):
            gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)

        # Integral clamped -- tau should not have gone below floor.
        assert gov.state.tau >= gov.config.tau_floor
        assert abs(gov.state.error_integral_tau) <= config.integral_max + 1e-9
        assert abs(gov.state.error_integral_beta) <= config.integral_max + 1e-9

    def test_update_returns_result_dict(self):
        """update() returns a well-formed result dictionary."""
        gov = AdaptiveGovernor()
        result = gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            **_stable_histories(),
        )
        expected_keys = {
            "verdict", "tau", "beta", "tau_default", "beta_default",
            "phase", "controller", "oi", "flips", "resonant", "trigger",
            "response_tier", "neighbor_pressure", "agents_in_resonance",
        }
        assert expected_keys.issubset(set(result.keys()))
        # Controller sub-dict should have PID components.
        ctrl = result["controller"]
        assert "p_tau" in ctrl
        assert "i_tau" in ctrl
        assert "d_tau" in ctrl
        assert "p_beta" in ctrl
        assert "i_beta" in ctrl
        assert "d_beta" in ctrl

    def test_neighbor_pressure_tightens_thresholds(self):
        """Neighbor pressure should raise tau and lower beta (tighten governance)."""
        config = GovernorConfig(K_p=0.0, K_i=0.0, K_d=0.0, decay_rate=0.0)
        gov = AdaptiveGovernor(config=config)
        gov.state.neighbor_pressure = 0.05
        initial_tau = gov.state.tau  # 0.40
        initial_beta = gov.state.beta  # 0.60
        gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            **_stable_histories(),
        )
        # "Tightens" means: higher coherence bar (tau UP), lower risk tolerance (beta DOWN).
        # With PID zeroed and only neighbor_pressure active:
        #   adjustment_tau += neighbor_pressure  -> tau increases
        #   adjustment_beta -= neighbor_pressure -> beta decreases
        assert gov.state.tau > initial_tau, f"tau should increase: {gov.state.tau} vs {initial_tau}"
        assert gov.state.beta < initial_beta, f"beta should decrease: {gov.state.beta} vs {initial_beta}"


# ===========================================================================
# TestVerdict
# ===========================================================================


class TestVerdict:
    """Verdict classification with adaptive thresholds."""

    def test_safe_verdict(self):
        gov = AdaptiveGovernor()
        # coherence >= tau(0.40) AND risk < beta_approve(0.60 + (-0.25) = 0.35)
        assert gov.make_verdict(coherence=0.70, risk=0.20) == Verdict.SAFE

    def test_caution_verdict(self):
        gov = AdaptiveGovernor()
        # coherence >= tau(0.40), risk between beta_approve(0.35) and beta(0.60)
        assert gov.make_verdict(coherence=0.70, risk=0.50) == Verdict.CAUTION

    def test_high_risk_verdict(self):
        gov = AdaptiveGovernor()
        # coherence below tau -> high risk (or risk >= beta)
        assert gov.make_verdict(coherence=0.35, risk=0.50) == Verdict.HIGH_RISK

    def test_high_risk_via_risk(self):
        gov = AdaptiveGovernor()
        # coherence OK but risk >= beta(0.60), but not > beta_ceiling(0.70)
        assert gov.make_verdict(coherence=0.70, risk=0.65) == Verdict.HIGH_RISK

    def test_hard_block_low_coherence(self):
        gov = AdaptiveGovernor()
        assert gov.make_verdict(coherence=0.20, risk=0.20) == Verdict.HARD_BLOCK

    def test_hard_block_high_risk(self):
        gov = AdaptiveGovernor()
        assert gov.make_verdict(coherence=0.70, risk=0.75) == Verdict.HARD_BLOCK

    def test_adaptive_threshold_changes_verdict(self):
        """Lowering tau makes marginal coherence safe."""
        gov = AdaptiveGovernor()
        # With default tau=0.40, coherence 0.38 is below tau -> not safe.
        v1 = gov.make_verdict(coherence=0.38, risk=0.30)
        assert v1 != Verdict.SAFE

        # Lower tau to 0.35 (exploration ref) -- now 0.38 >= tau -> safe.
        gov.state.tau = 0.35
        v2 = gov.make_verdict(coherence=0.38, risk=0.30)
        assert v2 == Verdict.SAFE

    def test_hard_block_coherence_exactly_at_floor(self):
        """Coherence exactly at floor should NOT hard-block (it's >=)."""
        gov = AdaptiveGovernor()
        # coherence == tau_floor (0.25) -> not < floor -> no hard block.
        v = gov.make_verdict(coherence=0.25, risk=0.30)
        assert v != Verdict.HARD_BLOCK

    def test_hard_block_risk_exactly_at_ceiling(self):
        """Risk exactly at ceiling should NOT hard-block (it's <=)."""
        gov = AdaptiveGovernor()
        # risk == beta_ceiling (0.70) -> not > ceiling -> no hard block.
        v = gov.make_verdict(coherence=0.70, risk=0.70)
        assert v != Verdict.HARD_BLOCK


# ===========================================================================
# TestPhaseDetection
# ===========================================================================


class TestPhaseDetection:
    """Phase detection integration -- detect_phase drives reference selection."""

    def test_exploration_phase(self):
        """I growing, S declining, high complexity -> 'exploration'."""
        gov = AdaptiveGovernor()
        gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            **_exploration_histories(),
        )
        assert gov.state.phase == "exploration"

    def test_integration_phase(self):
        """Stable I, stable S, low complexity -> 'integration'."""
        gov = AdaptiveGovernor()
        gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            **_stable_histories(),
        )
        assert gov.state.phase == "integration"

    def test_exploration_shifts_tau_reference_lower(self):
        """In exploration, tau reference is 0.35 (lower than integration 0.40).

        So if tau starts at 0.40, P-term should pull it down.
        """
        config = GovernorConfig(K_p=0.10, K_i=0.0, K_d=0.0, decay_rate=0.0)
        gov = AdaptiveGovernor(config=config)
        # tau starts at default 0.40, exploration ref is 0.35
        gov.update(
            coherence=0.65, risk=0.30, verdict="safe",
            **_exploration_histories(),
        )
        assert gov.state.phase == "exploration"
        # P-term should push tau toward 0.35 (down from 0.40).
        assert gov.state.tau < 0.40


# ===========================================================================
# TestThresholdDecay
# ===========================================================================


class TestThresholdDecay:
    """Threshold decay when stable (OI < threshold and flips == 0)."""

    def test_decay_toward_defaults(self):
        """With P=I=D=0 and tau above default, tau decays back."""
        config = GovernorConfig(K_p=0.0, K_i=0.0, K_d=0.0, decay_rate=0.05)
        gov = AdaptiveGovernor(config=config)
        gov.state.tau = 0.50  # Above default 0.40
        histories = _stable_histories()

        for _ in range(40):
            gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)

        # Should have decayed toward 0.40.
        assert gov.state.tau < 0.50
        assert gov.state.tau == pytest.approx(0.40, abs=0.02)

    def test_decay_toward_defaults_beta(self):
        """Beta also decays toward default when stable."""
        config = GovernorConfig(K_p=0.0, K_i=0.0, K_d=0.0, decay_rate=0.05)
        gov = AdaptiveGovernor(config=config)
        gov.state.beta = 0.50  # Below default 0.60
        histories = _stable_histories()

        for _ in range(40):
            gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)

        assert gov.state.beta > 0.50
        assert gov.state.beta == pytest.approx(0.60, abs=0.02)


# ===========================================================================
# TestOscillationConvergence
# ===========================================================================


class TestOscillationConvergence:
    """Oscillating agents produce non-zero OI and D-term damping."""

    def test_oscillating_agent(self):
        """Alternating safe/high-risk verdicts produce non-zero OI or flips.

        Note: OI tracks sign-transition correlation between coherence and risk.
        When they oscillate in perfect anti-phase (coherence up = risk down),
        the EMA components cancel. Flips are the primary oscillation measure
        in this case, and resonance detection uses both OI and flips.
        """
        gov = AdaptiveGovernor()
        histories = _stable_histories()

        for i in range(20):
            v = "safe" if i % 2 == 0 else "high-risk"
            c = 0.65 if i % 2 == 0 else 0.30
            r = 0.20 if i % 2 == 0 else 0.65
            gov.update(coherence=c, risk=r, verdict=v, **histories)

        # Oscillation should be detected via flips or OI.
        assert gov.state.flips > 0 or abs(gov.state.oi) > 0

    def test_oscillation_tracks_flips(self):
        """Verdict flips are counted in the window."""
        gov = AdaptiveGovernor()
        histories = _stable_histories()

        for i in range(10):
            v = "safe" if i % 2 == 0 else "high-risk"
            c = 0.65 if i % 2 == 0 else 0.30
            r = 0.20 if i % 2 == 0 else 0.65
            gov.update(coherence=c, risk=r, verdict=v, **histories)

        assert gov.state.flips > 0

    def test_resonance_detection(self):
        """Sustained oscillation triggers resonance flag."""
        # Use low flip threshold to trigger more easily.
        config = GovernorConfig(flip_threshold=3)
        gov = AdaptiveGovernor(config=config)
        histories = _stable_histories()

        for i in range(10):
            v = "safe" if i % 2 == 0 else "high-risk"
            c = 0.65 if i % 2 == 0 else 0.30
            r = 0.20 if i % 2 == 0 else 0.65
            gov.update(coherence=c, risk=r, verdict=v, **histories)

        assert gov.state.resonant is True
        assert gov.state.trigger in ("oi", "flips")

    def test_oi_based_resonance(self):
        """Resonance triggered specifically by OI threshold (not just flips)."""
        # Use high flip_threshold so flips won't trigger, only OI can.
        # Use low oi_threshold so OI can realistically trigger.
        config = GovernorConfig(flip_threshold=100, oi_threshold=0.3)
        gov = AdaptiveGovernor(config=config)
        histories = _stable_histories()

        # Oscillate coherence around tau while keeping risk stable.
        # This creates coherence sign transitions without cancelling risk transitions.
        # OI = ema_coherence + ema_risk; if only coherence oscillates,
        # ema_coherence grows while ema_risk stays near 0 → OI > 0.
        for i in range(15):
            c = 0.65 if i % 2 == 0 else 0.30  # oscillates around tau
            r = 0.30  # stable below beta
            v = "safe"  # same verdict each time → no flips
            gov.update(coherence=c, risk=r, verdict=v, **histories)

        # OI should be elevated via coherence oscillation alone
        assert abs(gov.state.oi) >= 0.3
        assert gov.state.resonant is True
        assert gov.state.trigger == "oi"


# ===========================================================================
# TestFuzzBounds
# ===========================================================================


class TestFuzzBounds:
    """Fuzz test: extreme random inputs never push tau/beta past bounds."""

    def test_extreme_inputs(self):
        """200 random updates never violate hard bounds."""
        random.seed(42)
        gov = AdaptiveGovernor()

        for _ in range(200):
            gov.update(
                coherence=random.uniform(-1, 2),
                risk=random.uniform(-1, 2),
                verdict=random.choice(["safe", "caution", "high-risk"]),
                E_history=[random.uniform(0, 1) for _ in range(6)],
                I_history=[random.uniform(0, 1) for _ in range(6)],
                S_history=[random.uniform(0, 1) for _ in range(6)],
                complexity_history=[random.uniform(0, 1) for _ in range(6)],
            )
            assert gov.state.tau >= gov.config.tau_floor, (
                f"tau {gov.state.tau} < floor {gov.config.tau_floor}"
            )
            assert gov.state.tau <= gov.config.tau_ceiling, (
                f"tau {gov.state.tau} > ceiling {gov.config.tau_ceiling}"
            )
            assert gov.state.beta >= gov.config.beta_floor, (
                f"beta {gov.state.beta} < floor {gov.config.beta_floor}"
            )
            assert gov.state.beta <= gov.config.beta_ceiling, (
                f"beta {gov.state.beta} > ceiling {gov.config.beta_ceiling}"
            )


# ===========================================================================
# TestClamp
# ===========================================================================


class TestClamp:
    """Unit tests for the _clamp helper."""

    def test_clamp_within_range(self):
        assert _clamp(0.5, 0.0, 1.0) == 0.5

    def test_clamp_below_floor(self):
        assert _clamp(-0.5, 0.0, 1.0) == 0.0

    def test_clamp_above_ceiling(self):
        assert _clamp(1.5, 0.0, 1.0) == 1.0

    def test_clamp_at_boundary(self):
        assert _clamp(0.0, 0.0, 1.0) == 0.0
        assert _clamp(1.0, 0.0, 1.0) == 1.0


# ===========================================================================
# TestMonitorIntegration
# ===========================================================================


class TestMonitorIntegration:
    """Test AdaptiveGovernor wired into GovernanceMonitor."""

    def test_feature_flag_off_uses_static(self):
        """When flag is off, behavior is identical to current."""
        from config.governance_config import GovernanceConfig
        assert GovernanceConfig.ADAPTIVE_GOVERNOR_ENABLED is False

    def test_governor_config_matches_monitor_defaults(self):
        """AdaptiveGovernor defaults match GovernanceMonitor's static config."""
        from config.governance_config import GovernanceConfig
        gc = GovernorConfig()
        assert gc.tau_default == GovernanceConfig.COHERENCE_CRITICAL_THRESHOLD
        assert gc.beta_default == GovernanceConfig.RISK_REVISE_THRESHOLD


# ===========================================================================
# TestNeighborPressure
# ===========================================================================


class TestNeighborPressure:
    """Multi-agent neighbor pressure system."""

    def test_apply_neighbor_pressure(self):
        """High-similarity neighbor triggers pressure."""
        gov = AdaptiveGovernor()
        gov.apply_neighbor_pressure(similarity=0.8, pressure_factor=0.02)
        assert gov.state.neighbor_pressure > 0
        assert gov.state.agents_in_resonance == 1

    def test_low_similarity_ignored(self):
        """Low-similarity neighbor is ignored."""
        gov = AdaptiveGovernor()
        gov.apply_neighbor_pressure(similarity=0.3, pressure_factor=0.02)
        assert gov.state.neighbor_pressure == 0.0
        assert gov.state.agents_in_resonance == 0

    def test_decay_neighbor_pressure(self):
        """Pressure decays after stability restored."""
        gov = AdaptiveGovernor()
        gov.apply_neighbor_pressure(similarity=0.8, pressure_factor=0.02)
        initial = gov.state.neighbor_pressure
        for _ in range(5):
            gov.decay_neighbor_pressure()
        assert gov.state.neighbor_pressure < initial

    def test_decay_to_zero_clears_agent_count(self):
        """Full decay clears agents_in_resonance count."""
        gov = AdaptiveGovernor()
        gov.apply_neighbor_pressure(similarity=0.8, pressure_factor=0.02)
        assert gov.state.agents_in_resonance == 1
        # Decay until pressure is effectively zero
        for _ in range(50):
            gov.decay_neighbor_pressure()
        assert gov.state.neighbor_pressure == 0.0
        assert gov.state.agents_in_resonance == 0

    def test_multiple_neighbors_accumulate(self):
        """Multiple resonating neighbors accumulate pressure."""
        gov = AdaptiveGovernor()
        gov.apply_neighbor_pressure(similarity=0.6)
        gov.apply_neighbor_pressure(similarity=0.9)
        assert gov.state.agents_in_resonance == 2
        assert gov.state.neighbor_pressure > 0.02  # More than single neighbor

    def test_pressure_affects_update(self):
        """Neighbor pressure actually tightens thresholds during update."""
        config = GovernorConfig(K_p=0.0, K_i=0.0, K_d=0.0, decay_rate=0.0)
        gov = AdaptiveGovernor(config=config)

        # Baseline update with no pressure
        gov_baseline = AdaptiveGovernor(config=config)
        histories = dict(
            E_history=[0.5]*6, I_history=[0.5]*6,
            S_history=[0.5]*6, complexity_history=[0.3]*6,
        )
        gov_baseline.update(coherence=0.65, risk=0.30, verdict="safe", **histories)

        # Update with pressure
        gov.apply_neighbor_pressure(similarity=0.8, pressure_factor=0.05)
        gov.update(coherence=0.65, risk=0.30, verdict="safe", **histories)

        # Pressure should tighten: tau higher, beta lower
        assert gov.state.tau > gov_baseline.state.tau
        assert gov.state.beta < gov_baseline.state.beta
