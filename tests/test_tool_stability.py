"""
Tests for src/mcp_handlers/tool_stability.py - Tool stability and alias system.

Tests ToolStability enum, ToolAlias/ToolLifecycle dataclasses, and all 7 public
API functions: resolve_tool_alias, get_tool_stability, get_tool_aliases,
get_migration_guide, list_all_aliases, is_stable_tool, is_experimental_tool.
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
    resolve_tool_alias,
    get_tool_stability,
    get_tool_aliases,
    get_migration_guide,
    list_all_aliases,
    is_stable_tool,
    is_experimental_tool,
    _TOOL_ALIASES,
    _ALIAS_REVERSE,
    _TOOL_STABILITY,
    _DEFAULT_STABILITY,
)


# ============================================================================
# ToolStability Enum
# ============================================================================

class TestToolStabilityEnum:

    def test_stable_value(self):
        assert ToolStability.STABLE.value == "stable"

    def test_beta_value(self):
        assert ToolStability.BETA.value == "beta"

    def test_experimental_value(self):
        assert ToolStability.EXPERIMENTAL.value == "experimental"

    def test_enum_members(self):
        members = set(ToolStability)
        assert len(members) == 3

    def test_default_stability_is_beta(self):
        assert _DEFAULT_STABILITY == ToolStability.BETA


# ============================================================================
# ToolAlias dataclass
# ============================================================================

class TestToolAlias:

    def test_creation_required_fields(self):
        alias = ToolAlias(old_name="old", new_name="new", reason="renamed")
        assert alias.old_name == "old"
        assert alias.new_name == "new"
        assert alias.reason == "renamed"
        assert alias.deprecated_since is None
        assert alias.migration_note is None
        assert alias.inject_action is None

    def test_creation_all_fields(self):
        dt = datetime(2026, 1, 1)
        alias = ToolAlias(
            old_name="old", new_name="new", reason="deprecated",
            deprecated_since=dt, migration_note="Use new()",
            inject_action="do_thing"
        )
        assert alias.deprecated_since == dt
        assert alias.migration_note == "Use new()"
        assert alias.inject_action == "do_thing"


# ============================================================================
# ToolLifecycle dataclass
# ============================================================================

class TestToolLifecycle:

    def test_creation_defaults(self):
        lc = ToolLifecycle(
            name="my_tool",
            stability=ToolStability.STABLE,
            created_at=datetime(2026, 1, 1)
        )
        assert lc.name == "my_tool"
        assert lc.stability == ToolStability.STABLE
        assert lc.deprecated_at is None
        assert lc.superseded_by is None
        assert lc.aliases == []
        assert lc.migration_guide is None

    def test_post_init_sets_empty_aliases(self):
        lc = ToolLifecycle(
            name="t", stability=ToolStability.BETA,
            created_at=datetime(2026, 1, 1), aliases=None
        )
        assert lc.aliases == []

    def test_aliases_preserved_when_set(self):
        lc = ToolLifecycle(
            name="t", stability=ToolStability.BETA,
            created_at=datetime(2026, 1, 1),
            aliases=["old_name"]
        )
        assert lc.aliases == ["old_name"]


# ============================================================================
# resolve_tool_alias
# ============================================================================

class TestResolveToolAlias:

    def test_known_alias_resolves(self):
        name, alias = resolve_tool_alias("status")
        assert name == "get_governance_metrics"
        assert alias is not None
        assert alias.old_name == "status"

    def test_non_alias_returns_same(self):
        name, alias = resolve_tool_alias("process_agent_update")
        assert name == "process_agent_update"
        assert alias is None

    def test_unknown_tool_returns_same(self):
        name, alias = resolve_tool_alias("totally_made_up_tool")
        assert name == "totally_made_up_tool"
        assert alias is None

    def test_pi_alias_resolves_to_pi(self):
        name, alias = resolve_tool_alias("pi_health")
        assert name == "pi"
        assert alias.inject_action == "health"

    def test_identity_aliases(self):
        for old_name in ["authenticate", "session", "hello", "bind_identity"]:
            name, alias = resolve_tool_alias(old_name)
            assert name == "identity", f"{old_name} should resolve to identity"

    def test_onboard_aliases(self):
        for old_name in ["start", "init", "register", "login"]:
            name, alias = resolve_tool_alias(old_name)
            assert name == "onboard", f"{old_name} should resolve to onboard"

    def test_knowledge_aliases(self):
        for old_name in ["store_knowledge_graph", "get_knowledge_graph",
                         "list_knowledge_graph", "get_discovery_details"]:
            name, alias = resolve_tool_alias(old_name)
            assert name == "knowledge", f"{old_name} should resolve to knowledge"

    def test_calibration_aliases(self):
        for old_name in ["check_calibration", "rebuild_calibration"]:
            name, alias = resolve_tool_alias(old_name)
            assert name == "calibration", f"{old_name} should resolve to calibration"


# ============================================================================
# get_tool_stability
# ============================================================================

class TestGetToolStability:

    def test_stable_tool(self):
        assert get_tool_stability("identity") == ToolStability.STABLE

    def test_beta_tool(self):
        assert get_tool_stability("get_dialectic_session") == ToolStability.BETA

    def test_experimental_tool(self):
        assert get_tool_stability("simulate_update") == ToolStability.EXPERIMENTAL

    def test_unknown_tool_returns_default(self):
        result = get_tool_stability("nonexistent_tool_xyz")
        assert result == _DEFAULT_STABILITY
        assert result == ToolStability.BETA

    def test_process_agent_update_is_stable(self):
        assert get_tool_stability("process_agent_update") == ToolStability.STABLE

    def test_deprecated_tool_is_experimental(self):
        assert get_tool_stability("direct_resume_if_safe") == ToolStability.EXPERIMENTAL


# ============================================================================
# get_tool_aliases
# ============================================================================

class TestGetToolAliases:

    def test_tool_with_aliases(self):
        aliases = get_tool_aliases("identity")
        assert len(aliases) > 0
        assert "authenticate" in aliases

    def test_tool_without_aliases(self):
        aliases = get_tool_aliases("totally_unknown_tool")
        assert aliases == []

    def test_onboard_has_aliases(self):
        aliases = get_tool_aliases("onboard")
        assert "start" in aliases
        assert "init" in aliases

    def test_pi_has_many_aliases(self):
        aliases = get_tool_aliases("pi")
        assert len(aliases) >= 5
        assert "pi_health" in aliases
        assert "pi_say" in aliases

    def test_knowledge_has_aliases(self):
        aliases = get_tool_aliases("knowledge")
        assert "store_knowledge_graph" in aliases


# ============================================================================
# get_migration_guide
# ============================================================================

class TestGetMigrationGuide:

    def test_known_alias_has_guide(self):
        guide = get_migration_guide("status")
        assert guide is not None
        assert "get_governance_metrics" in guide

    def test_unknown_returns_none(self):
        guide = get_migration_guide("totally_unknown_tool")
        assert guide is None

    def test_pi_alias_guide(self):
        guide = get_migration_guide("pi_health")
        assert guide is not None
        assert "pi" in guide.lower()

    def test_deprecated_tool_guide(self):
        guide = get_migration_guide("direct_resume_if_safe")
        assert guide is not None
        assert "quick_resume" in guide


# ============================================================================
# list_all_aliases
# ============================================================================

class TestListAllAliases:

    def test_returns_dict(self):
        result = list_all_aliases()
        assert isinstance(result, dict)

    def test_returns_copy(self):
        result = list_all_aliases()
        assert result is not _TOOL_ALIASES

    def test_contains_known_aliases(self):
        result = list_all_aliases()
        assert "status" in result
        assert "pi_health" in result

    def test_values_are_tool_alias(self):
        result = list_all_aliases()
        for v in result.values():
            assert isinstance(v, ToolAlias)

    def test_has_many_entries(self):
        result = list_all_aliases()
        assert len(result) >= 30


# ============================================================================
# is_stable_tool / is_experimental_tool
# ============================================================================

class TestIsStableTool:

    def test_stable_tool_returns_true(self):
        assert is_stable_tool("identity") is True

    def test_beta_tool_returns_false(self):
        assert is_stable_tool("get_dialectic_session") is False

    def test_experimental_tool_returns_false(self):
        assert is_stable_tool("simulate_update") is False

    def test_unknown_tool_returns_false(self):
        # Default is BETA, so not stable
        assert is_stable_tool("unknown_tool_xyz") is False


class TestIsExperimentalTool:

    def test_experimental_tool_returns_true(self):
        assert is_experimental_tool("simulate_update") is True

    def test_stable_tool_returns_false(self):
        assert is_experimental_tool("identity") is False

    def test_beta_tool_returns_false(self):
        assert is_experimental_tool("get_dialectic_session") is False

    def test_unknown_tool_returns_false(self):
        # Default is BETA, so not experimental
        assert is_experimental_tool("unknown_tool_xyz") is False


# ============================================================================
# Registry consistency checks
# ============================================================================

class TestRegistryConsistency:

    def test_all_aliases_have_old_and_new_name(self):
        for key, alias in _TOOL_ALIASES.items():
            assert alias.old_name == key, f"Key {key} mismatch with old_name {alias.old_name}"
            assert len(alias.new_name) > 0, f"Alias {key} has empty new_name"

    def test_reverse_map_matches_forward(self):
        for new_name, old_names in _ALIAS_REVERSE.items():
            for old_name in old_names:
                assert old_name in _TOOL_ALIASES
                assert _TOOL_ALIASES[old_name].new_name == new_name

    def test_all_aliases_have_reason(self):
        for key, alias in _TOOL_ALIASES.items():
            assert alias.reason in ("renamed", "consolidated", "deprecated", "intuitive_alias"), \
                f"Alias {key} has unexpected reason: {alias.reason}"

    def test_stability_values_are_valid(self):
        for tool_name, stability in _TOOL_STABILITY.items():
            assert isinstance(stability, ToolStability), \
                f"Tool {tool_name} has invalid stability: {stability}"
