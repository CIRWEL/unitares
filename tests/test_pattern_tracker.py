"""
Tests for src/pattern_tracker.py - PatternTracker

Tests loop detection, time-boxing, hypothesis tracking, and arg normalization.
All pure/in-memory - no external dependencies.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.pattern_tracker import (
    PatternTracker,
    ToolCallPattern,
    InvestigationSession,
    Hypothesis,
    get_pattern_tracker,
)


# --- ToolCallPattern Tests ---


class TestToolCallPattern:
    """Tests for ToolCallPattern dataclass."""

    def test_basic_creation(self):
        now = datetime.now(timezone.utc)
        p = ToolCallPattern(
            tool_name="search", args_hash="abc123", timestamp=now, agent_id="agent-1"
        )
        assert p.tool_name == "search"
        assert p.args_hash == "abc123"
        assert p.agent_id == "agent-1"

    def test_string_timestamp_parsing(self):
        p = ToolCallPattern(
            tool_name="search", args_hash="abc",
            timestamp="2026-01-15T10:00:00Z", agent_id="a1"
        )
        assert isinstance(p.timestamp, datetime)
        assert p.timestamp.tzinfo is not None

    def test_naive_timestamp_gets_utc(self):
        naive = datetime(2026, 1, 15, 10, 0, 0)
        p = ToolCallPattern(
            tool_name="search", args_hash="abc",
            timestamp=naive, agent_id="a1"
        )
        assert p.timestamp.tzinfo == timezone.utc


# --- normalize_args Tests ---


class TestNormalizeArgs:
    """Tests for PatternTracker.normalize_args()."""

    def setup_method(self):
        self.tracker = PatternTracker()

    def test_same_args_same_hash(self):
        h1 = self.tracker.normalize_args("tool_a", {"query": "hello", "limit": 10})
        h2 = self.tracker.normalize_args("tool_a", {"query": "hello", "limit": 10})
        assert h1 == h2

    def test_different_args_different_hash(self):
        h1 = self.tracker.normalize_args("tool_a", {"query": "hello"})
        h2 = self.tracker.normalize_args("tool_a", {"query": "world"})
        assert h1 != h2

    def test_different_tools_different_hash(self):
        h1 = self.tracker.normalize_args("tool_a", {"query": "hello"})
        h2 = self.tracker.normalize_args("tool_b", {"query": "hello"})
        assert h1 != h2

    def test_ignores_timestamp(self):
        h1 = self.tracker.normalize_args("search", {"query": "x", "timestamp": "2026-01-01"})
        h2 = self.tracker.normalize_args("search", {"query": "x", "timestamp": "2026-02-01"})
        assert h1 == h2

    def test_ignores_agent_id(self):
        h1 = self.tracker.normalize_args("search", {"query": "x", "agent_id": "a1"})
        h2 = self.tracker.normalize_args("search", {"query": "x", "agent_id": "a2"})
        assert h1 == h2

    def test_ignores_client_session_id(self):
        h1 = self.tracker.normalize_args("search", {"query": "x", "client_session_id": "s1"})
        h2 = self.tracker.normalize_args("search", {"query": "x", "client_session_id": "s2"})
        assert h1 == h2

    def test_normalizes_file_paths(self):
        """Long file paths should be normalized to last 2 components."""
        h1 = self.tracker.normalize_args("read", {"file_path": "/a/b/c/d/file.py"})
        h2 = self.tracker.normalize_args("read", {"file_path": "/x/y/z/d/file.py"})
        assert h1 == h2  # Same last 2 parts: d/file.py

    def test_list_values_normalized(self):
        """Lists should be normalized to type and length."""
        h1 = self.tracker.normalize_args("tool", {"items": [1, 2, 3]})
        h2 = self.tracker.normalize_args("tool", {"items": [4, 5, 6]})
        assert h1 == h2  # Both list[3]

    def test_dict_values_normalized(self):
        """Dicts should be normalized to keys."""
        h1 = self.tracker.normalize_args("tool", {"config": {"a": 1, "b": 2}})
        h2 = self.tracker.normalize_args("tool", {"config": {"a": 99, "b": 88}})
        assert h1 == h2  # Both dict[a,b]


# --- Loop Detection Tests ---


class TestLoopDetection:
    """Tests for record_tool_call() loop detection."""

    def setup_method(self):
        self.tracker = PatternTracker(window_minutes=30, loop_threshold=3)

    def test_no_loop_on_first_call(self):
        result = self.tracker.record_tool_call("a1", "search", {"query": "test"})
        assert result is None

    def test_no_loop_below_threshold(self):
        for _ in range(2):
            result = self.tracker.record_tool_call("a1", "search", {"query": "test"})
        assert result is None

    def test_loop_detected_at_threshold(self):
        for _ in range(2):
            self.tracker.record_tool_call("a1", "search", {"query": "test"})

        result = self.tracker.record_tool_call("a1", "search", {"query": "test"})
        assert result is not None
        assert result["detected"] is True
        assert result["type"] == "loop"
        assert result["count"] >= 3
        assert result["tool_name"] == "search"

    def test_different_args_no_loop(self):
        """Different args should not trigger loop."""
        for i in range(5):
            result = self.tracker.record_tool_call("a1", "search", {"query": f"test_{i}"})
        assert result is None

    def test_different_agents_independent(self):
        """Loop detection is per-agent."""
        for _ in range(2):
            self.tracker.record_tool_call("a1", "search", {"query": "test"})
        for _ in range(2):
            self.tracker.record_tool_call("a2", "search", {"query": "test"})

        # Neither should be at threshold yet
        result_a1 = self.tracker.record_tool_call("a1", "search", {"query": "test"})
        assert result_a1 is not None  # 3rd call for a1

        # a2 only has 2, third call should trigger
        result_a2 = self.tracker.record_tool_call("a2", "search", {"query": "test"})
        assert result_a2 is not None

    def test_custom_threshold(self):
        tracker = PatternTracker(loop_threshold=5)
        for _ in range(4):
            result = tracker.record_tool_call("a1", "search", {"query": "x"})
        assert result is None  # 4 < 5

        result = tracker.record_tool_call("a1", "search", {"query": "x"})
        assert result is not None  # 5 >= 5


# --- Investigation / Time-Boxing Tests ---


class TestTimeBoxing:
    """Tests for investigation time-boxing."""

    def setup_method(self):
        self.tracker = PatternTracker()

    def test_no_investigation_returns_none(self):
        result = self.tracker.check_time_box("a1")
        assert result is None

    def test_active_investigation_within_limit(self):
        self.tracker.start_investigation("a1", "debugging issue")
        result = self.tracker.check_time_box("a1", max_minutes=10)
        assert result is None  # Just started, within limit

    def test_time_box_exceeded(self):
        self.tracker.start_investigation("a1", "debugging issue")
        # Manually set last_progress_time to 15 minutes ago
        inv = self.tracker.investigations["a1"]
        inv.last_progress_time = datetime.now(timezone.utc) - timedelta(minutes=15)

        result = self.tracker.check_time_box("a1", max_minutes=10)
        assert result is not None
        assert result["detected"] is True
        assert result["type"] == "time_box"
        assert result["minutes_since_progress"] >= 10

    def test_record_progress_resets_timer(self):
        self.tracker.start_investigation("a1", "debugging")
        inv = self.tracker.investigations["a1"]
        inv.last_progress_time = datetime.now(timezone.utc) - timedelta(minutes=15)

        self.tracker.record_progress("a1")

        result = self.tracker.check_time_box("a1", max_minutes=10)
        assert result is None  # Timer reset

    def test_record_progress_increments_tool_calls(self):
        self.tracker.start_investigation("a1")
        assert self.tracker.investigations["a1"].tool_calls == 0

        self.tracker.record_progress("a1")
        assert self.tracker.investigations["a1"].tool_calls == 1

        self.tracker.record_progress("a1")
        assert self.tracker.investigations["a1"].tool_calls == 2


# --- Hypothesis Tracking Tests ---


class TestHypothesisTracking:
    """Tests for hypothesis tracking."""

    def setup_method(self):
        self.tracker = PatternTracker()

    def test_record_hypothesis(self):
        self.tracker.record_hypothesis(
            "a1", "code_edit", ["src/main.py"], "fix the bug"
        )
        assert len(self.tracker.hypotheses["a1"]) == 1
        assert self.tracker.hypotheses["a1"][0].change_type == "code_edit"
        assert not self.tracker.hypotheses["a1"][0].tested

    def test_no_untested_warning_when_recent(self):
        self.tracker.record_hypothesis("a1", "code_edit", ["src/main.py"])
        result = self.tracker.check_untested_hypotheses("a1", max_minutes=5)
        assert result is None  # Just created, not old enough

    def test_untested_warning_when_old(self):
        self.tracker.record_hypothesis("a1", "code_edit", ["src/main.py"])
        # Make it old
        self.tracker.hypotheses["a1"][0].created_time = (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        )

        result = self.tracker.check_untested_hypotheses("a1", max_minutes=5)
        assert result is not None
        assert result["detected"] is True
        assert result["type"] == "untested_hypothesis"
        assert result["change_type"] == "code_edit"

    def test_mark_hypothesis_tested(self):
        self.tracker.record_hypothesis("a1", "code_edit", ["src/main.py"])
        # Make old
        self.tracker.hypotheses["a1"][0].created_time = (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        )

        self.tracker.mark_hypothesis_tested("a1", ["src/main.py"])

        assert self.tracker.hypotheses["a1"][0].tested is True
        result = self.tracker.check_untested_hypotheses("a1", max_minutes=5)
        assert result is None

    def test_no_hypotheses_returns_none(self):
        result = self.tracker.check_untested_hypotheses("nonexistent")
        assert result is None

    def test_all_tested_returns_none(self):
        self.tracker.record_hypothesis("a1", "code_edit", ["src/main.py"])
        self.tracker.mark_hypothesis_tested("a1", ["src/main.py"])
        result = self.tracker.check_untested_hypotheses("a1")
        assert result is None


# --- get_patterns Tests ---


class TestGetPatterns:
    """Tests for get_patterns() aggregation."""

    def test_empty_agent(self):
        tracker = PatternTracker()
        result = tracker.get_patterns("unknown_agent")
        assert result["agent_id"] == "unknown_agent"
        assert result["patterns"] == []
        assert result["has_investigation"] is False
        assert result["untested_hypotheses"] == 0

    def test_with_investigation(self):
        tracker = PatternTracker()
        tracker.start_investigation("a1", "testing")
        result = tracker.get_patterns("a1")
        assert result["has_investigation"] is True

    def test_counts_untested_hypotheses(self):
        tracker = PatternTracker()
        tracker.record_hypothesis("a1", "code_edit", ["a.py"])
        tracker.record_hypothesis("a1", "config_change", ["b.py"])
        result = tracker.get_patterns("a1")
        assert result["untested_hypotheses"] == 2


# --- Global Instance Tests ---


def test_get_pattern_tracker_returns_instance():
    tracker = get_pattern_tracker()
    assert isinstance(tracker, PatternTracker)


def test_get_pattern_tracker_returns_same_instance():
    t1 = get_pattern_tracker()
    t2 = get_pattern_tracker()
    assert t1 is t2
