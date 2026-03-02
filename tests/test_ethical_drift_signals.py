"""
Tests for ethical drift signal starvation fix.

Verifies that non-Lumen agents get alive EISV dynamics:
- AgentBaseline tracks prev_* fields for rate-of-change
- compute_ethical_drift uses rate-of-change when baselines track tightly
- State velocity provides a floor for drift signals
- Warmup reduced from 5 to 2 updates
- ContinuityLayer uses derived complexity rate-of-change when no self-report
"""

import pytest
from unittest.mock import MagicMock
from datetime import datetime

from governance_core.ethical_drift import (
    AgentBaseline,
    EthicalDriftVector,
    compute_ethical_drift,
    get_agent_baseline,
    clear_baseline,
)
from src.dual_log.continuity import ContinuityLayer, compute_continuity_metrics


# ─── AgentBaseline prev_* tracking ───────────────────────────────────────


class TestAgentBaselinePrevFields:
    """Test that prev_* fields are populated and serialized correctly."""

    def test_prev_fields_initially_none(self):
        b = AgentBaseline(agent_id="test")
        assert b.prev_coherence is None
        assert b.prev_confidence is None
        assert b.prev_complexity is None

    def test_update_populates_prev_fields(self):
        b = AgentBaseline(agent_id="test")
        b.update(coherence=0.55, confidence=0.7, complexity=0.3)

        assert b.prev_coherence == 0.55
        assert b.prev_confidence == 0.7
        assert b.prev_complexity == 0.3

    def test_prev_fields_hold_raw_observation(self):
        """prev_* should hold raw observation, not the EMA-smoothed baseline."""
        b = AgentBaseline(agent_id="test", alpha=0.1)
        b.update(coherence=0.8)
        # prev_coherence should be raw 0.8, baseline should be EMA-smoothed
        assert b.prev_coherence == 0.8
        assert b.baseline_coherence != 0.8  # EMA smoothed

    def test_prev_fields_update_on_each_call(self):
        b = AgentBaseline(agent_id="test")
        b.update(coherence=0.5)
        assert b.prev_coherence == 0.5

        b.update(coherence=0.9)
        assert b.prev_coherence == 0.9  # Updated to latest observation

    def test_to_dict_includes_prev_fields(self):
        b = AgentBaseline(agent_id="test")
        b.update(coherence=0.55, confidence=0.7, complexity=0.3)
        d = b.to_dict()

        assert 'prev_coherence' in d
        assert 'prev_confidence' in d
        assert 'prev_complexity' in d
        assert d['prev_coherence'] == 0.55
        assert d['prev_confidence'] == 0.7
        assert d['prev_complexity'] == 0.3

    def test_from_dict_restores_prev_fields(self):
        b = AgentBaseline(agent_id="test")
        b.update(coherence=0.55, confidence=0.7, complexity=0.3)
        d = b.to_dict()

        restored = AgentBaseline.from_dict(d)
        assert restored.prev_coherence == 0.55
        assert restored.prev_confidence == 0.7
        assert restored.prev_complexity == 0.3

    def test_from_dict_handles_missing_prev_fields(self):
        """Old serialized data without prev_* should deserialize gracefully."""
        d = {
            'agent_id': 'old_agent',
            'baseline_coherence': 0.5,
            'baseline_confidence': 0.6,
            'baseline_complexity': 0.4,
        }
        restored = AgentBaseline.from_dict(d)
        assert restored.prev_coherence is None
        assert restored.prev_confidence is None
        assert restored.prev_complexity is None


# ─── Rate-of-change in compute_ethical_drift ─────────────────────────────


class TestRateOfChange:
    """Test that rate-of-change prevents signal starvation."""

    def test_tight_baseline_with_rate_of_change(self):
        """When EMA tracks tightly, rate-of-change should still produce signal."""
        b = AgentBaseline(agent_id="test", alpha=0.1)
        # Warm up past dampening
        for _ in range(3):
            b.update(coherence=0.5, confidence=0.6, complexity=0.4)

        # Now baseline tracks tightly around 0.5. But previous observation was 0.5,
        # and now we observe 0.55 — the rate-of-change |0.55 - 0.5| = 0.05
        # should be nonzero even though |0.55 - baseline| ≈ 0.005
        drift = compute_ethical_drift(
            agent_id="test",
            baseline=b,
            current_coherence=0.55,
            current_confidence=0.65,
            complexity_divergence=0.1,
        )

        # Coherence deviation should reflect rate-of-change (0.05), not just EMA deviation
        assert drift.coherence_deviation >= 0.04  # At least rate-of-change signal
        assert drift.calibration_deviation >= 0.04

    def test_zero_rate_of_change_when_steady(self):
        """When observations are constant, rate-of-change adds nothing extra."""
        b = AgentBaseline(agent_id="test")
        for _ in range(5):
            b.update(coherence=0.5, confidence=0.6)

        drift = compute_ethical_drift(
            agent_id="test",
            baseline=b,
            current_coherence=0.5,
            current_confidence=0.6,
            complexity_divergence=0.0,
        )

        # Coherence deviation: |0.5 - baseline| ≈ 0, |0.5 - 0.5| = 0
        assert drift.coherence_deviation < 0.01
        assert drift.calibration_deviation < 0.01

    def test_calibration_error_overrides_rate_of_change(self):
        """When calibration_error is provided, it should be used directly."""
        b = AgentBaseline(agent_id="test")
        # Clear warmup (need 2 updates)
        b.update(confidence=0.6, coherence=0.5)
        b.update(confidence=0.6, coherence=0.5)

        drift = compute_ethical_drift(
            agent_id="test",
            baseline=b,
            current_coherence=0.5,
            current_confidence=0.65,
            complexity_divergence=0.1,
            calibration_error=0.3,  # Explicit calibration error
        )

        assert drift.calibration_deviation == pytest.approx(0.3, abs=0.01)


# ─── State velocity floor ────────────────────────────────────────────────


class TestStateVelocityFloor:
    """Test that state velocity injects signal into drift components."""

    def test_velocity_injects_signal(self):
        """Non-trivial velocity should floor coherence_dev and calibration_deviation."""
        b = AgentBaseline(agent_id="test")
        for _ in range(3):
            b.update(coherence=0.5, confidence=0.6)

        drift = compute_ethical_drift(
            agent_id="test",
            baseline=b,
            current_coherence=0.5,
            current_confidence=0.6,
            complexity_divergence=0.0,
            state_velocity=0.1,  # Non-trivial velocity
        )

        # velocity_signal = min(0.5, 0.1) = 0.1
        # coherence_dev >= 0.1 * 0.5 = 0.05
        # calibration_dev >= 0.1 * 0.3 = 0.03
        assert drift.coherence_deviation >= 0.04
        assert drift.calibration_deviation >= 0.02
        assert drift.norm > 0.05

    def test_velocity_capped_at_half(self):
        """Velocity signal should be capped at 0.5."""
        b = AgentBaseline(agent_id="test")
        for _ in range(3):
            b.update(coherence=0.5, confidence=0.6)

        drift = compute_ethical_drift(
            agent_id="test",
            baseline=b,
            current_coherence=0.5,
            current_confidence=0.6,
            complexity_divergence=0.0,
            state_velocity=2.0,  # Very large velocity
        )

        # velocity_signal = min(0.5, 2.0) = 0.5
        # coherence_dev = max(~0, 0.5*0.5) = 0.25
        # calibration_dev = max(~0, 0.5*0.3) = 0.15
        assert drift.coherence_deviation <= 0.26
        assert drift.calibration_deviation <= 0.16

    def test_no_velocity_no_floor(self):
        """Without state_velocity, no floor is applied."""
        b = AgentBaseline(agent_id="test")
        for _ in range(3):
            b.update(coherence=0.5, confidence=0.6)

        drift = compute_ethical_drift(
            agent_id="test",
            baseline=b,
            current_coherence=0.5,
            current_confidence=0.6,
            complexity_divergence=0.0,
            # No state_velocity
        )

        assert drift.coherence_deviation < 0.02
        assert drift.calibration_deviation < 0.02

    def test_small_velocity_ignored(self):
        """Velocity below threshold (0.01) should not inject signal."""
        b = AgentBaseline(agent_id="test")
        for _ in range(3):
            b.update(coherence=0.5, confidence=0.6)

        drift = compute_ethical_drift(
            agent_id="test",
            baseline=b,
            current_coherence=0.5,
            current_confidence=0.6,
            complexity_divergence=0.0,
            state_velocity=0.005,  # Below threshold
        )

        assert drift.coherence_deviation < 0.02


# ─── Warmup reduction ────────────────────────────────────────────────────


class TestWarmupReduction:
    """Test that warmup is 2 updates instead of 5."""

    def test_drift_active_after_two_updates(self):
        """After 2 updates, warmup dampening should be gone."""
        b = AgentBaseline(agent_id="test")
        # 2 updates to clear warmup
        b.update(coherence=0.5, confidence=0.6)
        b.update(coherence=0.5, confidence=0.6)
        assert b.update_count == 2

        # Now compute drift with significant deviation
        drift = compute_ethical_drift(
            agent_id="test",
            baseline=b,
            current_coherence=0.8,  # Large deviation from baseline
            current_confidence=0.6,
            complexity_divergence=0.0,
        )

        # warmup_factor = 2/2 = 1.0 → no dampening
        # coherence_dev = max(|0.8 - 0.51|, |0.8 - 0.5|) = 0.3
        assert drift.coherence_deviation >= 0.2

    def test_drift_dampened_on_first_update(self):
        """On first update (count=0), drift should be zero."""
        b = AgentBaseline(agent_id="test")
        assert b.update_count == 0

        drift = compute_ethical_drift(
            agent_id="test",
            baseline=b,
            current_coherence=0.8,
            current_confidence=0.6,
            complexity_divergence=0.1,
        )

        # warmup_factor = 0/2 = 0 → all dampened to zero
        assert drift.coherence_deviation == 0.0
        assert drift.calibration_deviation == 0.0
        assert drift.stability_deviation == 0.0

    def test_drift_half_dampened_on_second_update(self):
        """On second update (count=1), drift should be 50% dampened."""
        b = AgentBaseline(agent_id="test")
        b.update(coherence=0.5, confidence=0.6)
        assert b.update_count == 1

        drift = compute_ethical_drift(
            agent_id="test",
            baseline=b,
            current_coherence=0.8,
            current_confidence=0.6,
            complexity_divergence=0.0,
        )

        # warmup_factor = 1/2 = 0.5
        # coherence_dev = max(|0.8 - 0.53|, |0.8 - 0.5|) * 0.5 = 0.3 * 0.5 = 0.15
        assert 0.1 <= drift.coherence_deviation <= 0.25


# ─── Continuity layer complexity rate-of-change ──────────────────────────


class TestContinuityComplexityRateOfChange:
    """Test that ContinuityLayer uses derived complexity rate-of-change."""

    def test_first_update_without_self_report_uses_default(self):
        """First update with no self-report: no prev_derived_complexity yet, uses default 0.2."""
        layer = ContinuityLayer(agent_id="test", redis_client=None)
        metrics = layer.process_update(
            response_text="Hello world",
            self_complexity=None,
            self_confidence=0.6,
        )
        # First update: _prev_derived_complexity was None, so compute_continuity_metrics
        # default 0.2 is used, then prev is set
        assert metrics.complexity_divergence == pytest.approx(0.2, abs=0.01)
        assert layer._prev_derived_complexity is not None

    def test_second_update_uses_rate_of_change(self):
        """Second update with no self-report: should use rate-of-change of derived complexity."""
        layer = ContinuityLayer(agent_id="test", redis_client=None)

        # First update: short text
        layer.process_update(
            response_text="Short",
            self_complexity=None,
            self_confidence=0.6,
        )
        prev = layer._prev_derived_complexity

        # Second update: much longer text → different derived complexity
        long_text = "This is a much longer response with code blocks:\n```python\nprint('hello')\n```\nAnd multiple paragraphs.\n\nSecond paragraph here.\n\nThird paragraph."
        metrics2 = layer.process_update(
            response_text=long_text,
            self_complexity=None,
            self_confidence=0.6,
        )

        # complexity_divergence should be |new_derived - prev_derived|
        expected_roc = abs(metrics2.derived_complexity - prev)
        assert metrics2.complexity_divergence == pytest.approx(expected_roc, abs=0.01)

    def test_self_reported_complexity_not_overridden(self):
        """When self_complexity is provided, rate-of-change should NOT override."""
        layer = ContinuityLayer(agent_id="test", redis_client=None)

        layer.process_update(
            response_text="First update",
            self_complexity=0.5,
            self_confidence=0.6,
        )

        metrics2 = layer.process_update(
            response_text="Second update with self-report",
            self_complexity=0.3,
            self_confidence=0.6,
        )

        # With self-report, divergence = |derived - 0.3|, NOT rate-of-change
        # The rate-of-change path should not trigger
        assert metrics2.self_complexity == 0.3


# ─── Integration: Non-Lumen agent drift should be alive ──────────────────


class TestNonLumenDriftAlive:
    """Integration test: simulate a sequence of non-Lumen check-ins and verify dynamics."""

    def test_drift_not_flatline_over_sequence(self):
        """Over multiple check-ins, drift norm should NOT flatline at zero."""
        clear_baseline("integration_test")
        b = get_agent_baseline("integration_test")

        norms = []
        coherence_values = [0.51, 0.52, 0.50, 0.53, 0.49, 0.52, 0.50, 0.51]

        for i, coh in enumerate(coherence_values):
            drift = compute_ethical_drift(
                agent_id="integration_test",
                baseline=b,
                current_coherence=coh,
                current_confidence=0.6 + (i % 3) * 0.02,
                complexity_divergence=0.05,
                state_velocity=0.02 + 0.01 * (i % 2),  # Small but nonzero
            )
            norms.append(drift.norm)

        # After warmup (first 2), norms should not be all near-zero
        post_warmup = norms[2:]
        assert any(n > 0.01 for n in post_warmup), f"All drift norms near zero: {post_warmup}"

        # Norms should vary (not constant)
        if len(post_warmup) > 2:
            assert max(post_warmup) - min(post_warmup) > 0.001, \
                f"Drift norms are constant: {post_warmup}"

        clear_baseline("integration_test")


# ─── Epistemic Context Attenuation ────────────────────────────────────


class TestEpistemicContextAttenuation:
    """Test that exploration/introspection task_context attenuates drift signals."""

    def test_introspection_attenuates_calibration_deviation(self):
        """Low confidence on introspection should produce less drift than on convergent tasks."""
        baseline = get_agent_baseline("epistemic_test_1")
        for _ in range(3):
            baseline.update(coherence=0.5, confidence=0.6, complexity=0.5, decision="proceed")

        drift_mixed = compute_ethical_drift(
            agent_id="epistemic_test_1",
            baseline=baseline,
            current_coherence=0.5,
            current_confidence=0.3,  # Low confidence
            complexity_divergence=0.4,
            task_context="mixed",
        )

        clear_baseline("epistemic_test_1")
        baseline2 = get_agent_baseline("epistemic_test_2")
        for _ in range(3):
            baseline2.update(coherence=0.5, confidence=0.6, complexity=0.5, decision="proceed")

        drift_introspection = compute_ethical_drift(
            agent_id="epistemic_test_2",
            baseline=baseline2,
            current_coherence=0.5,
            current_confidence=0.3,
            complexity_divergence=0.4,
            task_context="introspection",
        )

        assert drift_introspection.calibration_deviation < drift_mixed.calibration_deviation
        assert drift_introspection.complexity_divergence < drift_mixed.complexity_divergence
        assert drift_introspection.norm < drift_mixed.norm

        clear_baseline("epistemic_test_1")
        clear_baseline("epistemic_test_2")

    def test_exploration_attenuates_similarly(self):
        """exploration task_context should also attenuate drift."""
        baseline = get_agent_baseline("explore_test")
        for _ in range(3):
            baseline.update(coherence=0.5, confidence=0.6, complexity=0.5, decision="proceed")

        drift = compute_ethical_drift(
            agent_id="explore_test",
            baseline=baseline,
            current_coherence=0.5,
            current_confidence=0.3,
            complexity_divergence=0.4,
            task_context="exploration",
        )

        # Calibration deviation attenuated by 0.3x
        assert drift.calibration_deviation < 0.15
        clear_baseline("explore_test")

    def test_convergent_no_attenuation(self):
        """convergent task_context should NOT attenuate drift."""
        baseline = get_agent_baseline("convergent_test")
        for _ in range(3):
            baseline.update(coherence=0.5, confidence=0.6, complexity=0.5, decision="proceed")

        drift = compute_ethical_drift(
            agent_id="convergent_test",
            baseline=baseline,
            current_coherence=0.5,
            current_confidence=0.3,
            complexity_divergence=0.4,
            task_context="convergent",
        )

        assert drift.calibration_deviation >= 0.2
        clear_baseline("convergent_test")
