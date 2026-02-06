"""
Tests for src/pattern_analysis.py - analyze_trend, detect_anomalies, analyze_agent_patterns

Pure function tests with no external dependencies (only numpy).
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock
from collections import deque

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.pattern_analysis import (
    analyze_trend,
    detect_anomalies_in_history,
    analyze_agent_patterns,
)


# --- analyze_trend Tests ---


class TestAnalyzeTrend:
    """Tests for analyze_trend() function."""

    def test_empty_list(self):
        assert analyze_trend([]) == "stable"

    def test_single_value(self):
        assert analyze_trend([0.5]) == "stable"

    def test_constant_values(self):
        assert analyze_trend([0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]) == "stable"

    def test_increasing_trend(self):
        values = [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55]
        assert analyze_trend(values) == "increasing"

    def test_decreasing_trend(self):
        values = [0.55, 0.5, 0.45, 0.4, 0.35, 0.3, 0.25, 0.2, 0.15, 0.1]
        assert analyze_trend(values) == "decreasing"

    def test_small_change_is_stable(self):
        """Changes below 5% threshold should be 'stable'."""
        values = [0.50, 0.50, 0.50, 0.50, 0.50, 0.51, 0.51, 0.51, 0.51, 0.51]
        assert analyze_trend(values) == "stable"

    def test_clear_trend_with_enough_data(self):
        """Need 2*window values for proper trend comparison."""
        # Default window=5, so need 10+ values
        assert analyze_trend([0.1]*5 + [0.5]*5) == "increasing"
        assert analyze_trend([0.5]*5 + [0.1]*5) == "decreasing"

    def test_custom_window(self):
        values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        result = analyze_trend(values, window=3)
        assert result == "increasing"

    def test_short_list_adjusts_window(self):
        """Window should adjust down for short lists."""
        result = analyze_trend([0.2, 0.3, 0.8], window=10)
        assert result in ("increasing", "stable")  # Depends on window adjustment


# --- detect_anomalies_in_history Tests ---


class TestDetectAnomalies:
    """Tests for detect_anomalies_in_history()."""

    def test_empty_history(self):
        assert detect_anomalies_in_history([], [], []) == []

    def test_short_history_no_anomalies(self):
        assert detect_anomalies_in_history([0.3, 0.3], [0.5, 0.5], ["t1", "t2"]) == []

    def test_risk_spike_detected(self):
        """15%+ increase in recent risk should be detected."""
        risk = [0.2, 0.2, 0.2, 0.2, 0.2, 0.5, 0.5, 0.5]
        coherence = [0.5] * 8
        timestamps = [f"t{i}" for i in range(8)]

        anomalies = detect_anomalies_in_history(risk, coherence, timestamps)

        risk_spikes = [a for a in anomalies if a["type"] == "risk_spike"]
        assert len(risk_spikes) >= 1
        assert risk_spikes[0]["severity"] in ("medium", "high")

    def test_high_severity_risk_spike(self):
        """25%+ risk change should be high severity."""
        risk = [0.1, 0.1, 0.1, 0.1, 0.1, 0.6, 0.6, 0.6]
        coherence = [0.5] * 8
        timestamps = [f"t{i}" for i in range(8)]

        anomalies = detect_anomalies_in_history(risk, coherence, timestamps)

        risk_spikes = [a for a in anomalies if a["type"] == "risk_spike"]
        assert len(risk_spikes) >= 1
        assert risk_spikes[0]["severity"] == "high"

    def test_no_risk_spike_when_stable(self):
        risk = [0.3, 0.3, 0.3, 0.3, 0.3, 0.3]
        coherence = [0.5] * 6
        timestamps = [f"t{i}" for i in range(6)]

        anomalies = detect_anomalies_in_history(risk, coherence, timestamps)
        risk_spikes = [a for a in anomalies if a["type"] == "risk_spike"]
        assert len(risk_spikes) == 0

    def test_coherence_drop_detected(self):
        """5%+ coherence drop should be detected."""
        risk = [0.3] * 8
        coherence = [0.8, 0.8, 0.8, 0.8, 0.8, 0.6, 0.6, 0.6]
        timestamps = [f"t{i}" for i in range(8)]

        anomalies = detect_anomalies_in_history(risk, coherence, timestamps)

        drops = [a for a in anomalies if a["type"] == "coherence_drop"]
        assert len(drops) >= 1

    def test_anomaly_includes_context(self):
        """Anomalies should include context dict."""
        risk = [0.1, 0.1, 0.1, 0.1, 0.1, 0.5, 0.5, 0.5]
        coherence = [0.5] * 8
        timestamps = [f"t{i}" for i in range(8)]

        anomalies = detect_anomalies_in_history(risk, coherence, timestamps)

        for a in anomalies:
            assert "type" in a
            assert "severity" in a
            assert "description" in a
            assert "context" in a

    def test_empty_timestamps_handled(self):
        """Should handle empty timestamp list gracefully."""
        risk = [0.1, 0.1, 0.1, 0.5, 0.5, 0.5]
        coherence = [0.5] * 6

        anomalies = detect_anomalies_in_history(risk, coherence, [])
        # Should not crash; timestamp might be None
        for a in anomalies:
            assert a["timestamp"] is None


# --- analyze_agent_patterns Tests ---


class TestAnalyzeAgentPatterns:
    """Tests for analyze_agent_patterns()."""

    def _make_mock_monitor(self, **kwargs):
        """Create a mock monitor with a state object."""
        defaults = {
            "E": 0.7, "I": 0.8, "S": 0.3, "V": 0.2,
            "coherence": 0.52, "lambda1": 0.0,
            "update_count": 10,
            "risk_history": [0.3, 0.3, 0.3, 0.3, 0.3],
            "coherence_history": [0.5, 0.5, 0.5, 0.5, 0.5],
            "E_history": [0.7, 0.7, 0.7, 0.7, 0.7],
            "I_history": [0.8, 0.8, 0.8, 0.8, 0.8],
            "S_history": [0.3, 0.3, 0.3, 0.3, 0.3],
            "V_history": [0.2, 0.2, 0.2, 0.2, 0.2],
            "timestamp_history": [f"t{i}" for i in range(5)],
            "decision_history": ["proceed", "proceed", "proceed", "pause", "proceed"],
        }
        defaults.update(kwargs)

        state = MagicMock()
        for key, value in defaults.items():
            setattr(state, key, value)

        monitor = MagicMock()
        monitor.state = state
        return monitor

    def test_returns_current_state(self):
        monitor = self._make_mock_monitor()
        result = analyze_agent_patterns(monitor)

        assert "current_state" in result
        cs = result["current_state"]
        assert cs["E"] == 0.7
        assert cs["I"] == 0.8
        assert cs["S"] == 0.3
        assert cs["V"] == 0.2
        assert cs["coherence"] == 0.52

    def test_returns_patterns(self):
        monitor = self._make_mock_monitor()
        result = analyze_agent_patterns(monitor)

        assert "patterns" in result
        assert "risk_trend" in result["patterns"]
        assert "coherence_trend" in result["patterns"]
        assert "trend" in result["patterns"]

    def test_stable_patterns(self):
        monitor = self._make_mock_monitor()
        result = analyze_agent_patterns(monitor)
        assert result["patterns"]["trend"] == "stable"

    def test_improving_trend(self):
        monitor = self._make_mock_monitor(
            risk_history=[0.5, 0.5, 0.5, 0.5, 0.5, 0.3, 0.3, 0.3, 0.3, 0.3],
            coherence_history=[0.4, 0.4, 0.4, 0.4, 0.4, 0.6, 0.6, 0.6, 0.6, 0.6],
        )
        result = analyze_agent_patterns(monitor)
        assert result["patterns"]["trend"] == "improving"

    def test_degrading_trend(self):
        monitor = self._make_mock_monitor(
            risk_history=[0.2, 0.2, 0.2, 0.2, 0.2, 0.5, 0.5, 0.5, 0.5, 0.5],
            coherence_history=[0.6, 0.6, 0.6, 0.6, 0.6, 0.4, 0.4, 0.4, 0.4, 0.4],
        )
        result = analyze_agent_patterns(monitor)
        assert result["patterns"]["trend"] == "degrading"

    def test_returns_anomalies(self):
        monitor = self._make_mock_monitor()
        result = analyze_agent_patterns(monitor)
        assert "anomalies" in result
        assert isinstance(result["anomalies"], list)

    def test_returns_summary(self):
        monitor = self._make_mock_monitor()
        result = analyze_agent_patterns(monitor)

        assert "summary" in result
        assert result["summary"]["total_updates"] == 10
        assert "mean_risk" in result["summary"]
        assert "decision_distribution" in result["summary"]

    def test_decision_distribution(self):
        monitor = self._make_mock_monitor(
            decision_history=["proceed", "proceed", "pause", "approve", "reject"]
        )
        result = analyze_agent_patterns(monitor)
        dist = result["summary"]["decision_distribution"]
        # "proceed" counts: proceed(2) + approve(1) + reflect(0) + revise(0) = 3
        assert dist["proceed"] >= 2
        assert dist["pause"] >= 1  # pause(1) + reject(1) = 2

    def test_includes_recent_history(self):
        monitor = self._make_mock_monitor()
        result = analyze_agent_patterns(monitor, include_history=True)
        assert "recent_history" in result
        assert "risk_history" in result["recent_history"]

    def test_excludes_history_when_requested(self):
        monitor = self._make_mock_monitor()
        result = analyze_agent_patterns(monitor, include_history=False)
        assert "recent_history" not in result

    def test_empty_history(self):
        monitor = self._make_mock_monitor(
            risk_history=[], coherence_history=[],
            E_history=[], I_history=[], S_history=[], V_history=[],
            timestamp_history=[]
        )
        result = analyze_agent_patterns(monitor)
        assert result["patterns"]["risk_trend"] == "stable"
        assert result["patterns"]["coherence_trend"] == "stable"
        assert result["summary"]["mean_risk"] == 0.0
