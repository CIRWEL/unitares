"""
Tests for src/tool_usage_tracker.py - Tool usage tracking with JSONL I/O.

Uses tmp_path for file isolation.
"""

import json
import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.tool_usage_tracker import ToolUsageEntry, ToolUsageTracker


# ============================================================================
# ToolUsageEntry
# ============================================================================

class TestToolUsageEntry:

    def test_creation(self):
        entry = ToolUsageEntry(
            timestamp="2025-01-01T00:00:00",
            tool_name="search"
        )
        assert entry.tool_name == "search"
        assert entry.success is True
        assert entry.agent_id is None

    def test_full_creation(self):
        entry = ToolUsageEntry(
            timestamp="2025-01-01T00:00:00",
            tool_name="search",
            agent_id="a1",
            success=False,
            error_type="timeout"
        )
        assert entry.agent_id == "a1"
        assert entry.success is False
        assert entry.error_type == "timeout"


# ============================================================================
# ToolUsageTracker - init
# ============================================================================

class TestToolUsageTrackerInit:

    def test_custom_log_file(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        assert tracker.log_file == log_file

    def test_creates_parent_dir(self, tmp_path):
        log_file = tmp_path / "subdir" / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        assert log_file.parent.exists()


# ============================================================================
# ToolUsageTracker - log_tool_call
# ============================================================================

class TestLogToolCall:

    def test_log_creates_file(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        tracker.log_tool_call("search_knowledge_graph")
        assert log_file.exists()

    def test_log_writes_json(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        tracker.log_tool_call("search", agent_id="a1")

        with open(log_file) as f:
            entry = json.loads(f.readline())
        assert entry["tool_name"] == "search"
        assert entry["agent_id"] == "a1"
        assert entry["success"] is True

    def test_log_error(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        tracker.log_tool_call("search", success=False, error_type="timeout")

        with open(log_file) as f:
            entry = json.loads(f.readline())
        assert entry["success"] is False
        assert entry["error_type"] == "timeout"

    def test_log_multiple_entries(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        tracker.log_tool_call("tool1")
        tracker.log_tool_call("tool2")
        tracker.log_tool_call("tool3")

        with open(log_file) as f:
            lines = f.readlines()
        assert len(lines) == 3


# ============================================================================
# ToolUsageTracker - get_usage_stats
# ============================================================================

class TestGetUsageStats:

    def test_empty_stats(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        stats = tracker.get_usage_stats()
        assert stats["total_calls"] == 0
        assert stats["unique_tools"] == 0

    def test_basic_stats(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        tracker.log_tool_call("search")
        tracker.log_tool_call("search")
        tracker.log_tool_call("write")

        stats = tracker.get_usage_stats()
        assert stats["total_calls"] == 3
        assert stats["unique_tools"] == 2
        assert "search" in stats["tools"]
        assert stats["tools"]["search"]["total_calls"] == 2

    def test_filter_by_tool(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        tracker.log_tool_call("search")
        tracker.log_tool_call("write")

        stats = tracker.get_usage_stats(tool_name="search")
        assert stats["total_calls"] == 1

    def test_filter_by_agent(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        tracker.log_tool_call("search", agent_id="a1")
        tracker.log_tool_call("search", agent_id="a2")

        stats = tracker.get_usage_stats(agent_id="a1")
        assert stats["total_calls"] == 1

    def test_success_rate(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        tracker.log_tool_call("search", success=True)
        tracker.log_tool_call("search", success=True)
        tracker.log_tool_call("search", success=False)

        stats = tracker.get_usage_stats()
        assert stats["tools"]["search"]["success_rate"] == pytest.approx(2/3)

    def test_removed_tools_filtered(self, tmp_path):
        """Deprecated tools should be filtered from stats."""
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)

        now = datetime.now().isoformat()
        with open(log_file, 'a') as f:
            json.dump({"timestamp": now, "tool_name": "store_knowledge", "success": True}, f)
            f.write('\n')
            json.dump({"timestamp": now, "tool_name": "search", "success": True}, f)
            f.write('\n')

        stats = tracker.get_usage_stats()
        assert stats["total_calls"] == 1
        assert "store_knowledge" not in stats["tools"]

    def test_most_and_least_used(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        for i in range(5):
            tracker.log_tool_call("popular")
        tracker.log_tool_call("rare")

        stats = tracker.get_usage_stats()
        assert stats["most_used"][0]["tool"] == "popular"

    def test_percentage_of_total(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        tracker.log_tool_call("search")
        tracker.log_tool_call("search")
        tracker.log_tool_call("write")
        tracker.log_tool_call("write")

        stats = tracker.get_usage_stats()
        assert stats["tools"]["search"]["percentage_of_total"] == pytest.approx(50.0)


# ============================================================================
# ToolUsageTracker - get_unused_tools
# ============================================================================

class TestGetUnusedTools:

    def test_all_unused(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        unused = tracker.get_unused_tools(["tool1", "tool2", "tool3"])
        assert set(unused) == {"tool1", "tool2", "tool3"}

    def test_some_used(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        tracker.log_tool_call("tool1")

        unused = tracker.get_unused_tools(["tool1", "tool2", "tool3"])
        assert "tool1" not in unused
        assert "tool2" in unused
        assert "tool3" in unused

    def test_all_used(self, tmp_path):
        log_file = tmp_path / "usage.jsonl"
        tracker = ToolUsageTracker(log_file=log_file)
        tracker.log_tool_call("tool1")
        tracker.log_tool_call("tool2")

        unused = tracker.get_unused_tools(["tool1", "tool2"])
        assert unused == []
