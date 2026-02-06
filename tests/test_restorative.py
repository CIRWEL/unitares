"""
Tests for src/dual_log/restorative.py - Restorative balance monitoring.

Tests RestorativeStatus dataclass and RestorativeBalanceMonitor using
in-memory fallback (no Redis needed).
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.dual_log.restorative import RestorativeStatus, RestorativeBalanceMonitor


# Mock ContinuityMetrics - minimal shape needed by RestorativeBalanceMonitor
@dataclass
class MockContinuityMetrics:
    timestamp: datetime = None
    complexity_divergence: float = 0.0

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


# ============================================================================
# RestorativeStatus
# ============================================================================

class TestRestorativeStatus:

    def test_creation_defaults(self):
        status = RestorativeStatus(needs_restoration=False)
        assert status.needs_restoration is False
        assert status.reason is None
        assert status.suggested_cooldown_seconds == 0
        assert status.activity_rate == 0.0
        assert status.cumulative_divergence == 0.0

    def test_creation_full(self):
        status = RestorativeStatus(
            needs_restoration=True,
            reason="high activity",
            suggested_cooldown_seconds=60,
            activity_rate=20.0,
            cumulative_divergence=0.5
        )
        assert status.needs_restoration is True
        assert status.reason == "high activity"
        assert status.suggested_cooldown_seconds == 60

    def test_to_dict(self):
        status = RestorativeStatus(
            needs_restoration=True,
            reason="test",
            suggested_cooldown_seconds=30,
            activity_rate=10.0,
            cumulative_divergence=0.3
        )
        d = status.to_dict()
        assert isinstance(d, dict)
        assert d["needs_restoration"] is True
        assert d["reason"] == "test"
        assert d["suggested_cooldown_seconds"] == 30
        assert d["activity_rate"] == 10.0
        assert d["cumulative_divergence"] == 0.3

    def test_to_dict_keys(self):
        status = RestorativeStatus(needs_restoration=False)
        d = status.to_dict()
        expected_keys = {"needs_restoration", "reason", "suggested_cooldown_seconds",
                        "activity_rate", "cumulative_divergence"}
        assert set(d.keys()) == expected_keys

    def test_to_dict_no_restoration(self):
        status = RestorativeStatus(needs_restoration=False)
        d = status.to_dict()
        assert d["needs_restoration"] is False
        assert d["reason"] is None


# ============================================================================
# RestorativeBalanceMonitor - Init
# ============================================================================

class TestRestorativeBalanceMonitorInit:

    def test_default_init(self):
        monitor = RestorativeBalanceMonitor(agent_id="test-agent")
        assert monitor.agent_id == "test-agent"
        assert monitor.redis is None
        assert monitor.activity_threshold == 15
        assert monitor.divergence_threshold == 0.4
        assert monitor.window_seconds == 300

    def test_custom_thresholds(self):
        monitor = RestorativeBalanceMonitor(
            agent_id="test",
            activity_threshold=10,
            divergence_threshold=0.2,
            window_seconds=60
        )
        assert monitor.activity_threshold == 10
        assert monitor.divergence_threshold == 0.2
        assert monitor.window_seconds == 60

    def test_empty_initial_state(self):
        monitor = RestorativeBalanceMonitor(agent_id="test")
        assert len(monitor._timestamps) == 0
        assert len(monitor._divergences) == 0


# ============================================================================
# RestorativeBalanceMonitor - record (in-memory)
# ============================================================================

class TestRestorativeBalanceMonitorRecord:

    def test_record_single(self):
        monitor = RestorativeBalanceMonitor(agent_id="test")
        metrics = MockContinuityMetrics(complexity_divergence=0.1)
        monitor.record(metrics)
        assert len(monitor._timestamps) == 1
        assert len(monitor._divergences) == 1
        assert monitor._divergences[0] == 0.1

    def test_record_multiple(self):
        monitor = RestorativeBalanceMonitor(agent_id="test")
        for i in range(5):
            metrics = MockContinuityMetrics(complexity_divergence=0.1 * i)
            monitor.record(metrics)
        assert len(monitor._timestamps) == 5

    def test_record_prunes_old(self):
        """Entries older than window should be pruned."""
        monitor = RestorativeBalanceMonitor(agent_id="test", window_seconds=60)

        # Add old entry
        old_metrics = MockContinuityMetrics(
            timestamp=datetime.now() - timedelta(seconds=120),
            complexity_divergence=0.5
        )
        monitor.record(old_metrics)

        # Add new entry - should prune the old one
        new_metrics = MockContinuityMetrics(complexity_divergence=0.1)
        monitor.record(new_metrics)

        assert len(monitor._timestamps) == 1
        assert monitor._divergences[0] == 0.1

    def test_record_no_redis_uses_memory(self):
        """Without Redis, should use in-memory storage."""
        monitor = RestorativeBalanceMonitor(agent_id="test", redis_client=None)
        metrics = MockContinuityMetrics(complexity_divergence=0.2)
        monitor.record(metrics)
        assert len(monitor._timestamps) == 1


# ============================================================================
# RestorativeBalanceMonitor - _record_memory
# ============================================================================

class TestRecordMemory:

    def test_appends_timestamp_and_divergence(self):
        monitor = RestorativeBalanceMonitor(agent_id="test")
        metrics = MockContinuityMetrics(
            timestamp=datetime.now(),
            complexity_divergence=0.3
        )
        monitor._record_memory(metrics)
        assert len(monitor._timestamps) == 1
        assert monitor._divergences[0] == 0.3

    def test_prunes_old_entries(self):
        monitor = RestorativeBalanceMonitor(agent_id="test", window_seconds=60)

        # Pre-populate with old data
        old_ts = datetime.now() - timedelta(seconds=120)
        monitor._timestamps = [old_ts]
        monitor._divergences = [0.5]

        # Record new
        metrics = MockContinuityMetrics(complexity_divergence=0.1)
        monitor._record_memory(metrics)

        # Old entry should be pruned
        assert len(monitor._timestamps) == 1
        assert monitor._divergences[0] == 0.1


# ============================================================================
# RestorativeBalanceMonitor - check (in-memory)
# ============================================================================

class TestRestorativeBalanceMonitorCheck:

    def test_no_data_no_restoration(self):
        monitor = RestorativeBalanceMonitor(agent_id="test")
        status = monitor.check()
        assert status.needs_restoration is False
        assert status.activity_rate == 0
        assert status.cumulative_divergence == 0.0

    def test_below_thresholds_no_restoration(self):
        monitor = RestorativeBalanceMonitor(
            agent_id="test",
            activity_threshold=15,
            divergence_threshold=0.4
        )
        # Add a few entries below thresholds
        for i in range(5):
            metrics = MockContinuityMetrics(complexity_divergence=0.05)
            monitor.record(metrics)

        status = monitor.check()
        assert status.needs_restoration is False
        assert status.activity_rate == 5

    def test_high_activity_triggers_restoration(self):
        monitor = RestorativeBalanceMonitor(
            agent_id="test",
            activity_threshold=5
        )
        # Add entries exceeding activity threshold
        for i in range(10):
            metrics = MockContinuityMetrics(complexity_divergence=0.01)
            monitor.record(metrics)

        status = monitor.check()
        assert status.needs_restoration is True
        assert "activity" in status.reason.lower()
        assert status.activity_rate == 10

    def test_high_divergence_triggers_restoration(self):
        monitor = RestorativeBalanceMonitor(
            agent_id="test",
            divergence_threshold=0.3
        )
        # Add entries with high divergence
        for i in range(5):
            metrics = MockContinuityMetrics(complexity_divergence=0.1)
            monitor.record(metrics)

        status = monitor.check()
        assert status.needs_restoration is True
        assert "divergence" in status.reason.lower()
        assert status.cumulative_divergence == pytest.approx(0.5)

    def test_both_thresholds_exceeded(self):
        monitor = RestorativeBalanceMonitor(
            agent_id="test",
            activity_threshold=3,
            divergence_threshold=0.2
        )
        for i in range(5):
            metrics = MockContinuityMetrics(complexity_divergence=0.1)
            monitor.record(metrics)

        status = monitor.check()
        assert status.needs_restoration is True
        assert "activity" in status.reason.lower()
        assert "divergence" in status.reason.lower()

    def test_cooldown_scales_with_severity(self):
        monitor = RestorativeBalanceMonitor(
            agent_id="test",
            activity_threshold=5,
            divergence_threshold=0.3
        )
        # Add many entries with high divergence
        for i in range(20):
            metrics = MockContinuityMetrics(complexity_divergence=0.1)
            monitor.record(metrics)

        status = monitor.check()
        assert status.needs_restoration is True
        assert status.suggested_cooldown_seconds > 30  # Base cooldown

    def test_cooldown_capped_at_300(self):
        monitor = RestorativeBalanceMonitor(
            agent_id="test",
            activity_threshold=1,
            divergence_threshold=0.01
        )
        # Extreme overload
        for i in range(100):
            metrics = MockContinuityMetrics(complexity_divergence=1.0)
            monitor.record(metrics)

        status = monitor.check()
        assert status.suggested_cooldown_seconds <= 300


# ============================================================================
# RestorativeBalanceMonitor - clear
# ============================================================================

class TestRestorativeBalanceMonitorClear:

    def test_clear_resets_memory(self):
        monitor = RestorativeBalanceMonitor(agent_id="test")
        for i in range(5):
            metrics = MockContinuityMetrics(complexity_divergence=0.1)
            monitor.record(metrics)
        assert len(monitor._timestamps) == 5

        monitor.clear()
        assert len(monitor._timestamps) == 0
        assert len(monitor._divergences) == 0

    def test_check_after_clear(self):
        monitor = RestorativeBalanceMonitor(agent_id="test", activity_threshold=3)
        for i in range(10):
            metrics = MockContinuityMetrics(complexity_divergence=0.1)
            monitor.record(metrics)

        # Should need restoration
        status = monitor.check()
        assert status.needs_restoration is True

        # After clear, should not need restoration
        monitor.clear()
        status = monitor.check()
        assert status.needs_restoration is False
