"""
Tests for src/holdout_validation.py - Hold-out validation set management.

Uses tmp_path for file I/O isolation.
"""

import pytest
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.holdout_validation import HoldoutValidator


class TestHoldoutValidatorInit:

    def test_creates_with_no_config(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        v = HoldoutValidator(config_file=config_file)
        assert v.holdout_agents == set()
        assert v.enabled is False

    def test_loads_existing_config(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        config_file.write_text(json.dumps({
            "holdout_agents": ["agent-1", "agent-2"],
            "enabled": True
        }))
        v = HoldoutValidator(config_file=config_file)
        assert v.holdout_agents == {"agent-1", "agent-2"}
        assert v.enabled is True

    def test_handles_corrupt_config(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        config_file.write_text("not valid json {{{")
        v = HoldoutValidator(config_file=config_file)
        assert v.holdout_agents == set()
        assert v.enabled is False

    def test_creates_parent_dirs(self, tmp_path):
        config_file = tmp_path / "nested" / "dir" / "holdout_config.json"
        v = HoldoutValidator(config_file=config_file)
        assert config_file.parent.exists()


class TestIsHoldoutAgent:

    def test_returns_true_when_enabled_and_in_set(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        config_file.write_text(json.dumps({
            "holdout_agents": ["agent-1"],
            "enabled": True
        }))
        v = HoldoutValidator(config_file=config_file)
        assert v.is_holdout_agent("agent-1") is True

    def test_returns_false_when_disabled(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        config_file.write_text(json.dumps({
            "holdout_agents": ["agent-1"],
            "enabled": False
        }))
        v = HoldoutValidator(config_file=config_file)
        assert v.is_holdout_agent("agent-1") is False

    def test_returns_false_when_not_in_set(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        v = HoldoutValidator(config_file=config_file)
        v.enabled = True
        assert v.is_holdout_agent("unknown-agent") is False


class TestAddRemoveHoldout:

    def test_add_agent(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        v = HoldoutValidator(config_file=config_file)
        v.add_holdout_agent("agent-1")
        assert "agent-1" in v.holdout_agents
        # Verify persisted
        saved = json.loads(config_file.read_text())
        assert "agent-1" in saved["holdout_agents"]

    def test_remove_agent(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        config_file.write_text(json.dumps({
            "holdout_agents": ["agent-1", "agent-2"],
            "enabled": True
        }))
        v = HoldoutValidator(config_file=config_file)
        v.remove_holdout_agent("agent-1")
        assert "agent-1" not in v.holdout_agents
        assert "agent-2" in v.holdout_agents

    def test_remove_nonexistent_agent_no_error(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        v = HoldoutValidator(config_file=config_file)
        v.remove_holdout_agent("nonexistent")  # Should not raise

    def test_add_duplicate_is_idempotent(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        v = HoldoutValidator(config_file=config_file)
        v.add_holdout_agent("agent-1")
        v.add_holdout_agent("agent-1")
        assert len(v.holdout_agents) == 1


class TestEnableDisable:

    def test_enable(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        v = HoldoutValidator(config_file=config_file)
        assert v.enabled is False
        v.enable()
        assert v.enabled is True
        # Verify persisted
        saved = json.loads(config_file.read_text())
        assert saved["enabled"] is True

    def test_disable(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        config_file.write_text(json.dumps({"holdout_agents": [], "enabled": True}))
        v = HoldoutValidator(config_file=config_file)
        v.disable()
        assert v.enabled is False


class TestGetHoldoutStats:

    def test_stats_empty(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        v = HoldoutValidator(config_file=config_file)
        stats = v.get_holdout_stats()
        assert stats["enabled"] is False
        assert stats["holdout_agents_count"] == 0
        assert stats["holdout_agents"] == []

    def test_stats_with_agents(self, tmp_path):
        config_file = tmp_path / "holdout_config.json"
        config_file.write_text(json.dumps({
            "holdout_agents": ["a", "b", "c"],
            "enabled": True
        }))
        v = HoldoutValidator(config_file=config_file)
        stats = v.get_holdout_stats()
        assert stats["enabled"] is True
        assert stats["holdout_agents_count"] == 3
        assert set(stats["holdout_agents"]) == {"a", "b", "c"}
