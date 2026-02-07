"""
Tests for src/mcp_handlers/tool_stability.py - Tool stability and alias system.

All functions are pure. Tests data classes, alias resolution, stability tiers.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.tool_stability import (
    ToolStability,
    ToolAlias,
    ToolLifecycle,
    _TOOL_ALIASES,
    _TOOL_STABILITY,
    resolve_tool_alias,
    get_tool_stability,
    get_tool_aliases,
    get_migration_guide,
    list_all_aliases,
    is_stable_tool,
    is_experimental_tool,
)


# ============================================================================
# ToolStability Enum
# ============================================================================

class TestToolStabilityEnum:

    def test_values(self):
        assert ToolStability.STABLE.value == "stable"
        assert ToolStability.BETA.value == "beta"
        assert ToolStability.EXPERIMENTAL.value == "experimental"


# ============================================================================
# ToolAlias Dataclass
# ============================================================================

class TestToolAlias:

    def test_creation(self):
        alias = ToolAlias(old_name="old", new_name="new", reason="renamed")
        assert alias.old_name == "old"
        assert alias.new_name == "new"
        assert alias.reason == "renamed"

    def test_optional_fields(self):
        alias = ToolAlias(old_name="old", new_name="new", reason="deprecated",
                          deprecated_since=datetime(2026, 1, 1),
                          migration_note="Use new_tool",
                          inject_action="get")
        assert alias.deprecated_since == datetime(2026, 1, 1)
        assert alias.migration_note == "Use new_tool"
        assert alias.inject_action == "get"


# ============================================================================
# ToolLifecycle Dataclass
# ============================================================================

class TestToolLifecycle:

    def test_creation(self):
        lc = ToolLifecycle(name="test_tool", stability=ToolStability.STABLE, created_at=datetime.now())
        assert lc.name == "test_tool"
        assert lc.aliases == []  # post_init sets empty list

    def test_with_aliases(self):
        lc = ToolLifecycle(name="test", stability=ToolStability.BETA,
                           created_at=datetime.now(), aliases=["old1", "old2"])
        assert lc.aliases == ["old1", "old2"]


# ============================================================================
# resolve_tool_alias
# ============================================================================

class TestResolveToolAlias:

    def test_known_alias(self):
        name, alias = resolve_tool_alias("status")
        assert name == "get_governance_metrics"
        assert alias is not None
        assert alias.old_name == "status"

    def test_not_an_alias(self):
        name, alias = resolve_tool_alias("process_agent_update")
        assert name == "process_agent_update"
        assert alias is None

    def test_start_alias(self):
        name, alias = resolve_tool_alias("start")
        assert name == "onboard"

    def test_login_alias(self):
        name, alias = resolve_tool_alias("login")
        assert name == "onboard"

    def test_checkin_alias(self):
        name, alias = resolve_tool_alias("checkin")
        assert name == "process_agent_update"

    def test_pi_health_alias(self):
        name, alias = resolve_tool_alias("pi_health")
        assert name == "pi"
        assert alias.inject_action == "health"

    def test_list_agents_alias(self):
        name, alias = resolve_tool_alias("list_agents")
        assert name == "agent"
        assert alias.inject_action == "list"


# ============================================================================
# get_tool_stability
# ============================================================================

class TestGetToolStability:

    def test_stable_tool(self):
        assert get_tool_stability("identity") == ToolStability.STABLE

    def test_beta_tool(self):
        assert get_tool_stability("dialectic") == ToolStability.BETA

    def test_experimental_tool(self):
        assert get_tool_stability("simulate_update") == ToolStability.EXPERIMENTAL

    def test_unknown_tool_default(self):
        assert get_tool_stability("totally_unknown") == ToolStability.BETA


# ============================================================================
# get_tool_aliases
# ============================================================================

class TestGetToolAliases:

    def test_tool_with_aliases(self):
        aliases = get_tool_aliases("onboard")
        assert "start" in aliases
        assert "init" in aliases
        assert "register" in aliases

    def test_tool_without_aliases(self):
        aliases = get_tool_aliases("nonexistent_tool")
        assert aliases == []


# ============================================================================
# get_migration_guide
# ============================================================================

class TestGetMigrationGuide:

    def test_known_alias(self):
        guide = get_migration_guide("status")
        assert guide is not None
        assert "get_governance_metrics" in guide

    def test_unknown(self):
        guide = get_migration_guide("nonexistent")
        assert guide is None


# ============================================================================
# list_all_aliases
# ============================================================================

class TestListAllAliases:

    def test_returns_dict(self):
        result = list_all_aliases()
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_returns_copy(self):
        result = list_all_aliases()
        result["test_inject"] = "bad"
        assert "test_inject" not in _TOOL_ALIASES


# ============================================================================
# is_stable_tool / is_experimental_tool
# ============================================================================

class TestStabilityChecks:

    def test_is_stable(self):
        assert is_stable_tool("identity") is True
        assert is_stable_tool("simulate_update") is False

    def test_is_experimental(self):
        assert is_experimental_tool("simulate_update") is True
        assert is_experimental_tool("identity") is False


# ============================================================================
# Alias registry sanity
# ============================================================================

class TestAliasRegistrySanity:

    def test_all_aliases_have_required_fields(self):
        for name, alias in _TOOL_ALIASES.items():
            assert alias.old_name == name
            assert alias.new_name
            assert alias.reason in ("renamed", "consolidated", "deprecated", "intuitive_alias")

    def test_inject_action_set_for_consolidated(self):
        """Consolidated tools should have inject_action set."""
        for name, alias in _TOOL_ALIASES.items():
            if alias.reason == "consolidated":
                assert alias.inject_action is not None, f"Consolidated alias '{name}' missing inject_action"
