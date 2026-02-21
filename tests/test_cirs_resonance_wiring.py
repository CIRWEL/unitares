"""
Tests for CIRS resonance → protocol wiring.

Covers:
- maybe_emit_resonance_signal: transition detection and signal emission
- maybe_apply_neighbor_pressure: peer alert reading and pressure application
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

# Import after ensuring path
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

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
            timestamp=datetime.utcnow().isoformat(),
            oi=3.0, phase="integration",
            tau_current=0.42, beta_current=0.58, flips=5,
        )
        _emit_resonance_alert(alert)

        # Coherence report shows high similarity
        _coherence_report_buffer["my-agent:peer-1"] = {
            "source_agent_id": "my-agent",
            "target_agent_id": "peer-1",
            "similarity_score": 0.75,
            "timestamp": datetime.utcnow().isoformat(),
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
            timestamp=datetime.utcnow().isoformat(),
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
            timestamp=datetime.utcnow().isoformat(),
            oi=3.0, phase="integration",
            tau_current=0.42, beta_current=0.58, flips=5,
        )
        _emit_resonance_alert(alert)

        _coherence_report_buffer["my-agent:peer-1"] = {
            "source_agent_id": "my-agent",
            "target_agent_id": "peer-1",
            "similarity_score": 0.3,  # Below 0.5 threshold
            "timestamp": datetime.utcnow().isoformat(),
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
            timestamp=datetime.utcnow().isoformat(),
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
            timestamp=datetime.utcnow().isoformat(),
            oi=0.3, tau_settled=0.40, beta_settled=0.60,
        )
        _emit_stability_restored(restored)

        maybe_apply_neighbor_pressure(
            agent_id="my-agent",
            governor=gov,
        )

        assert gov.state.neighbor_pressure < 0.05  # Decayed
