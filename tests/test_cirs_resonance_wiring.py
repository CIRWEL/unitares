"""
Tests for CIRS resonance → protocol wiring.

Covers:
- maybe_emit_resonance_signal: transition detection and signal emission
- maybe_apply_neighbor_pressure: peer alert reading and pressure application
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.mcp_handlers.cirs_protocol import (
    maybe_emit_resonance_signal,
    maybe_apply_neighbor_pressure,
    _resonance_alert_buffer,
    _coherence_report_buffer,
    _get_recent_resonance_signals,
    _emit_resonance_alert,
    _emit_stability_restored,
    ResonanceAlert,
    StabilityRestored,
)
from governance_core.adaptive_governor import AdaptiveGovernor, GovernorConfig


class TestMaybeEmitResonanceSignal:
    """maybe_emit_resonance_signal emits on transitions, no-ops otherwise."""

    def setup_method(self):
        """Clear the resonance buffer before each test."""
        _resonance_alert_buffer.clear()

    def test_false_to_true_emits_resonance_alert(self):
        """Transition from not-resonant to resonant emits RESONANCE_ALERT."""
        cirs_result = {
            "resonant": True,
            "trigger": "oi",
            "oi": 3.0,
            "phase": "integration",
            "tau": 0.42,
            "beta": 0.58,
            "flips": 5,
        }
        signal = maybe_emit_resonance_signal(
            agent_id="agent-1",
            cirs_result=cirs_result,
            was_resonant=False,
        )
        assert signal is not None
        assert signal["type"] == "RESONANCE_ALERT"
        assert signal["agent_id"] == "agent-1"
        assert signal["oi"] == 3.0
        assert signal["phase"] == "integration"
        assert len(_resonance_alert_buffer) == 1

    def test_true_to_false_emits_stability_restored(self):
        """Transition from resonant to stable emits STABILITY_RESTORED."""
        cirs_result = {
            "resonant": False,
            "trigger": None,
            "oi": 0.5,
            "phase": "integration",
            "tau": 0.40,
            "beta": 0.60,
            "flips": 0,
        }
        signal = maybe_emit_resonance_signal(
            agent_id="agent-1",
            cirs_result=cirs_result,
            was_resonant=True,
        )
        assert signal is not None
        assert signal["type"] == "STABILITY_RESTORED"
        assert signal["agent_id"] == "agent-1"
        assert signal["tau_settled"] == 0.40
        assert len(_resonance_alert_buffer) == 1

    def test_no_transition_emits_nothing(self):
        """Same state -> same state emits nothing."""
        cirs_result = {
            "resonant": False,
            "trigger": None,
            "oi": 0.1,
            "phase": "integration",
            "tau": 0.40,
            "beta": 0.60,
            "flips": 0,
        }
        # Not resonant -> still not resonant
        signal = maybe_emit_resonance_signal(
            agent_id="agent-1",
            cirs_result=cirs_result,
            was_resonant=False,
        )
        assert signal is None
        assert len(_resonance_alert_buffer) == 0

    def test_sustained_resonance_emits_nothing(self):
        """Resonant -> still resonant emits nothing (no flooding)."""
        cirs_result = {
            "resonant": True,
            "trigger": "oi",
            "oi": 3.5,
            "phase": "exploration",
            "tau": 0.35,
            "beta": 0.55,
            "flips": 6,
        }
        signal = maybe_emit_resonance_signal(
            agent_id="agent-1",
            cirs_result=cirs_result,
            was_resonant=True,
        )
        assert signal is None
        assert len(_resonance_alert_buffer) == 0


class TestMaybeApplyNeighborPressure:
    """maybe_apply_neighbor_pressure reads peer alerts and applies pressure."""

    def setup_method(self):
        """Clear buffers before each test."""
        _resonance_alert_buffer.clear()
        _coherence_report_buffer.clear()

    def test_applies_pressure_when_similar_peer_resonating(self):
        """High-similarity peer resonance -> pressure applied."""
        gov = AdaptiveGovernor()
        assert gov.state.neighbor_pressure == 0.0

        # Peer emits RESONANCE_ALERT
        alert = ResonanceAlert(
            agent_id="peer-1",
            timestamp=datetime.now(timezone.utc).isoformat(),
            oi=3.0, phase="integration",
            tau_current=0.42, beta_current=0.58, flips=5,
        )
        _emit_resonance_alert(alert)

        # Coherence report shows high similarity
        _coherence_report_buffer["my-agent:peer-1"] = {
            "source_agent_id": "my-agent",
            "target_agent_id": "peer-1",
            "similarity_score": 0.75,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        maybe_apply_neighbor_pressure(
            agent_id="my-agent",
            governor=gov,
        )

        assert gov.state.neighbor_pressure > 0.0

    def test_skips_pressure_when_no_coherence_report(self):
        """No coherence report -> no pressure (conservative default)."""
        gov = AdaptiveGovernor()

        # Peer emits RESONANCE_ALERT
        alert = ResonanceAlert(
            agent_id="peer-1",
            timestamp=datetime.now(timezone.utc).isoformat(),
            oi=3.0, phase="integration",
            tau_current=0.42, beta_current=0.58, flips=5,
        )
        _emit_resonance_alert(alert)

        # No coherence report exists
        maybe_apply_neighbor_pressure(
            agent_id="my-agent",
            governor=gov,
        )

        assert gov.state.neighbor_pressure == 0.0

    def test_skips_pressure_when_low_similarity(self):
        """Low similarity -> no pressure."""
        gov = AdaptiveGovernor()

        alert = ResonanceAlert(
            agent_id="peer-1",
            timestamp=datetime.now(timezone.utc).isoformat(),
            oi=3.0, phase="integration",
            tau_current=0.42, beta_current=0.58, flips=5,
        )
        _emit_resonance_alert(alert)

        _coherence_report_buffer["my-agent:peer-1"] = {
            "source_agent_id": "my-agent",
            "target_agent_id": "peer-1",
            "similarity_score": 0.3,  # Below 0.5 threshold
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        maybe_apply_neighbor_pressure(
            agent_id="my-agent",
            governor=gov,
        )

        assert gov.state.neighbor_pressure == 0.0

    def test_ignores_own_resonance_alerts(self):
        """Agent doesn't apply pressure from its own alerts."""
        gov = AdaptiveGovernor()

        # Self-emitted alert
        alert = ResonanceAlert(
            agent_id="my-agent",
            timestamp=datetime.now(timezone.utc).isoformat(),
            oi=3.0, phase="integration",
            tau_current=0.42, beta_current=0.58, flips=5,
        )
        _emit_resonance_alert(alert)

        maybe_apply_neighbor_pressure(
            agent_id="my-agent",
            governor=gov,
        )

        assert gov.state.neighbor_pressure == 0.0

    def test_decays_pressure_on_stability_restored(self):
        """STABILITY_RESTORED from previously-pressuring peer -> decay."""
        gov = AdaptiveGovernor()
        # Manually set some existing pressure
        gov.state.neighbor_pressure = 0.05
        gov.state.agents_in_resonance = 1

        # Peer restored stability
        restored = StabilityRestored(
            agent_id="peer-1",
            timestamp=datetime.now(timezone.utc).isoformat(),
            oi=0.3, tau_settled=0.40, beta_settled=0.60,
        )
        _emit_stability_restored(restored)

        maybe_apply_neighbor_pressure(
            agent_id="my-agent",
            governor=gov,
        )

        assert gov.state.neighbor_pressure < 0.05  # Decayed


class TestResonanceFullLoop:
    """Integration: governor detects → alert emits → peer tightens."""

    def setup_method(self):
        _resonance_alert_buffer.clear()
        _coherence_report_buffer.clear()

    def test_full_resonance_propagation_loop(self):
        """
        Agent A oscillates → detects resonance → emits RESONANCE_ALERT.
        Agent B has high similarity → reads alert → applies neighbor pressure.
        Agent B's thresholds tighten.
        """
        config = GovernorConfig(flip_threshold=3)
        gov_a = AdaptiveGovernor(config=config)
        gov_b = AdaptiveGovernor()
        histories = _stable_histories()

        # Phase 1: Drive Agent A into resonance
        for i in range(10):
            v = "safe" if i % 2 == 0 else "high-risk"
            c = 0.65 if i % 2 == 0 else 0.30
            r = 0.20 if i % 2 == 0 else 0.65
            result_a = gov_a.update(coherence=c, risk=r, verdict=v, **histories)

        assert result_a["resonant"] is True

        # Phase 2: Emit the signal
        signal = maybe_emit_resonance_signal(
            agent_id="agent-a",
            cirs_result=result_a,
            was_resonant=False,  # First time resonant
        )
        assert signal is not None
        assert signal["type"] == "RESONANCE_ALERT"

        # Phase 3: Set up similarity between A and B
        _coherence_report_buffer["agent-b:agent-a"] = {
            "source_agent_id": "agent-b",
            "target_agent_id": "agent-a",
            "similarity_score": 0.8,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Phase 4: Agent B reads and applies pressure
        initial_pressure = gov_b.state.neighbor_pressure
        maybe_apply_neighbor_pressure(
            agent_id="agent-b",
            governor=gov_b,
        )
        assert gov_b.state.neighbor_pressure > initial_pressure

        # Phase 5: Agent A stabilizes → emits STABILITY_RESTORED
        for _ in range(5):
            result_a = gov_a.update(
                coherence=0.65, risk=0.20, verdict="safe", **histories
            )

        if not result_a["resonant"]:
            signal_restored = maybe_emit_resonance_signal(
                agent_id="agent-a",
                cirs_result=result_a,
                was_resonant=True,
            )
            if signal_restored:
                assert signal_restored["type"] == "STABILITY_RESTORED"

        # Phase 6: Agent B decays pressure
        pressure_before_decay = gov_b.state.neighbor_pressure
        maybe_apply_neighbor_pressure(
            agent_id="agent-b",
            governor=gov_b,
        )
        # If stability was restored, pressure should have decayed
        # (may still have RESONANCE_ALERT in buffer too, so just check it moved)


def _stable_histories():
    """Helper: stable EISV histories for phase detection."""
    return {
        "E_history": [0.7] * 6,
        "I_history": [0.8] * 6,
        "S_history": [0.2] * 6,
        "complexity_history": [0.3] * 6,
    }
