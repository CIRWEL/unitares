"""
Tool Stability and Migration System

Reduces friction from constant tool churn by:
1. Stability tiers (stable/experimental/beta)
2. Automatic aliases for renamed tools
3. Migration helpers
4. Single source of truth for tool lifecycle
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

class ToolStability(Enum):
    """Tool stability tier - helps users know what to expect"""
    STABLE = "stable"  # Production-ready, won't change
    BETA = "beta"  # Mostly stable, minor changes possible
    EXPERIMENTAL = "experimental"  # WIP, may change/break

@dataclass
class ToolAlias:
    """Alias mapping for renamed/consolidated tools"""
    old_name: str
    new_name: str
    reason: str  # "renamed", "consolidated", "deprecated"
    deprecated_since: Optional[datetime] = None
    migration_note: Optional[str] = None

@dataclass
class ToolLifecycle:
    """Complete tool lifecycle information"""
    name: str
    stability: ToolStability
    created_at: datetime
    deprecated_at: Optional[datetime] = None
    superseded_by: Optional[str] = None
    aliases: List[str] = None  # Old names that map to this tool
    migration_guide: Optional[str] = None
    
    def __post_init__(self):
        if self.aliases is None:
            self.aliases = []


# ============================================================================
# Tool Aliases Registry
# ============================================================================
# When tools are renamed/consolidated, add aliases here so old names still work
# This prevents breaking existing code/agents

_TOOL_ALIASES: Dict[str, ToolAlias] = {
    # Identity tools - all point to identity() (the primary identity tool)
    # NOTE: who_am_i has its own handler in admin.py, so NOT aliased
    #
    # Common intuitive aliases for agent "status" checking
    "status": ToolAlias(
        old_name="status",
        new_name="get_governance_metrics",
        reason="intuitive_alias",
        migration_note="Use get_governance_metrics() for EISV status. Use identity() for who you are."
    ),
    "my_status": ToolAlias(
        old_name="my_status",
        new_name="get_governance_metrics",
        reason="intuitive_alias",
        migration_note="Use get_governance_metrics() for EISV status"
    ),
    "check_status": ToolAlias(
        old_name="check_status",
        new_name="get_governance_metrics",
        reason="intuitive_alias",
        migration_note="Use get_governance_metrics() for EISV status"
    ),
    "metrics": ToolAlias(
        old_name="metrics",
        new_name="get_governance_metrics",
        reason="intuitive_alias",
        migration_note="Use get_governance_metrics() for EISV status"
    ),
    "state": ToolAlias(
        old_name="state",
        new_name="get_governance_metrics",
        reason="intuitive_alias",
        migration_note="Use get_governance_metrics() for EISV state"
    ),
    # Onboarding aliases - common first-call guesses
    "start": ToolAlias(
        old_name="start",
        new_name="onboard",
        reason="intuitive_alias",
        migration_note="Use onboard() to start - creates identity and returns templates"
    ),
    "init": ToolAlias(
        old_name="init",
        new_name="onboard",
        reason="intuitive_alias",
        migration_note="Use onboard() to initialize - creates identity and returns templates"
    ),
    "register": ToolAlias(
        old_name="register",
        new_name="onboard",
        reason="intuitive_alias",
        migration_note="Use onboard() to register - creates identity and returns templates"
    ),
    "login": ToolAlias(
        old_name="login",
        new_name="onboard",
        reason="intuitive_alias",
        migration_note="Use onboard() - auto-creates identity, no login needed"
    ),
    # Logging work aliases
    "checkin": ToolAlias(
        old_name="checkin",
        new_name="process_agent_update",
        reason="intuitive_alias",
        migration_note="Use process_agent_update() to check in your work"
    ),
    "log": ToolAlias(
        old_name="log",
        new_name="process_agent_update",
        reason="intuitive_alias",
        migration_note="Use process_agent_update() to log your work"
    ),
    "update": ToolAlias(
        old_name="update",
        new_name="process_agent_update",
        reason="intuitive_alias",
        migration_note="Use process_agent_update() to log your work"
    ),
    "authenticate": ToolAlias(
        old_name="authenticate",
        new_name="identity",
        reason="consolidated",
        migration_note="Use identity() - auto-creates on first call"
    ),
    "session": ToolAlias(
        old_name="session",
        new_name="identity",
        reason="consolidated",
        migration_note="Use identity() - auto-creates on first call"
    ),
    "quick_start": ToolAlias(
        old_name="quick_start",
        new_name="identity",
        reason="consolidated",
        migration_note="Use identity() - auto-creates on first call"
    ),
    "recall_identity": ToolAlias(
        old_name="recall_identity",
        new_name="identity",
        reason="consolidated",
        migration_note="Use identity() - shows bound identity"
    ),
    "bind_identity": ToolAlias(
        old_name="bind_identity",
        new_name="identity",
        reason="consolidated",
        migration_note="Use identity() - auto-creates on first call"
    ),
    "hello": ToolAlias(
        old_name="hello",
        new_name="identity",
        reason="consolidated",
        migration_note="Use identity() - auto-creates on first call"
    ),
    "get_agent_api_key": ToolAlias(
        old_name="get_agent_api_key",
        new_name="identity",
        reason="deprecated",
        migration_note="API keys deprecated - UUID is now auth. Use identity() to see your agent_uuid."
    ),
    # NOTE: who_am_i is NOT aliased - it has its own handler in admin.py

    # Recovery tools - consolidated recovery hierarchy (Jan 2026)
    # direct_resume_if_safe is deprecated in favor of clearer recovery paths
    "direct_resume_if_safe": ToolAlias(
        old_name="direct_resume_if_safe",
        new_name="quick_resume",  # Default to quick_resume, but suggest self_recovery_review if thresholds not met
        reason="deprecated",
        deprecated_since=datetime(2026, 1, 29),
        migration_note="Use quick_resume() if coherence > 0.60 and risk < 0.40, otherwise use self_recovery_review(reflection='...')"
    ),
    
    # Dialectic tools - legacy creation remains archived (except request_dialectic_review restored)
    "request_exploration_session": ToolAlias(
        old_name="request_exploration_session",
        new_name="get_dialectic_session",
        reason="consolidated",
        migration_note="Use get_dialectic_session() to view/manage dialectic sessions"
    ),
    "submit_thesis": ToolAlias(
        old_name="submit_thesis",
        new_name="get_dialectic_session",
        reason="consolidated",
        migration_note="Dialectic creation temporarily disabled - use get_dialectic_session()"
    ),
    "submit_antithesis": ToolAlias(
        old_name="submit_antithesis",
        new_name="get_dialectic_session",
        reason="consolidated",
        migration_note="Dialectic creation temporarily disabled - use get_dialectic_session()"
    ),
    "submit_synthesis": ToolAlias(
        old_name="submit_synthesis",
        new_name="get_dialectic_session",
        reason="consolidated",
        migration_note="Use resolve_interactive_dialectic() to complete session"
    ),
    
    # Knowledge graph tools
    "find_similar_discoveries_graph": ToolAlias(
        old_name="find_similar_discoveries_graph",
        new_name="search_knowledge_graph",
        reason="consolidated",
        migration_note="Use search_knowledge_graph(semantic=true) for similarity search"
    ),
    "get_related_discoveries_graph": ToolAlias(
        old_name="get_related_discoveries_graph",
        new_name="get_discovery_details",
        reason="consolidated",
        migration_note="Use get_discovery_details() - includes related discoveries"
    ),
    "get_response_chain_graph": ToolAlias(
        old_name="get_response_chain_graph",
        new_name="get_discovery_details",
        reason="consolidated",
        migration_note="Use get_discovery_details() - includes response chain"
    ),
    "reply_to_question": ToolAlias(
        old_name="reply_to_question",
        new_name="store_knowledge_graph",
        reason="consolidated",
        migration_note="Use store_knowledge_graph(response_to=question_id) to reply"
    ),
}

# Reverse mapping: new_name -> list of old names
_ALIAS_REVERSE: Dict[str, List[str]] = {}
for alias in _TOOL_ALIASES.values():
    if alias.new_name not in _ALIAS_REVERSE:
        _ALIAS_REVERSE[alias.new_name] = []
    _ALIAS_REVERSE[alias.new_name].append(alias.old_name)


# ============================================================================
# Tool Stability Registry
# ============================================================================
# Mark tools by stability tier to help users know what to expect

_TOOL_STABILITY: Dict[str, ToolStability] = {
    # STABLE: Production-ready, won't change
    "identity": ToolStability.STABLE,  # Primary identity tool (renamed from status)
    "who_am_i": ToolStability.STABLE,  # Quick identity check
    "process_agent_update": ToolStability.STABLE,
    "get_governance_metrics": ToolStability.STABLE,
    "store_knowledge_graph": ToolStability.STABLE,
    "search_knowledge_graph": ToolStability.STABLE,
    "get_knowledge_graph": ToolStability.STABLE,
    "list_knowledge_graph": ToolStability.STABLE,
    "get_discovery_details": ToolStability.STABLE,
    "list_agents": ToolStability.STABLE,
    "health_check": ToolStability.STABLE,
    "list_tools": ToolStability.STABLE,
    "describe_tool": ToolStability.STABLE,
    "self_recovery_review": ToolStability.STABLE,  # Primary recovery path
    "quick_resume": ToolStability.STABLE,  # Fast recovery path
    "check_recovery_options": ToolStability.STABLE,  # Diagnostic tool

    # BETA: Mostly stable, minor changes possible
    "get_dialectic_session": ToolStability.BETA,  # Only active dialectic tool
    "observe_agent": ToolStability.BETA,
    "compare_agents": ToolStability.BETA,
    "archive_agent": ToolStability.BETA,
    "update_discovery_status_graph": ToolStability.BETA,
    "leave_note": ToolStability.BETA,
    "operator_resume_agent": ToolStability.BETA,  # Operator tool
    
    # DEPRECATED: Will be removed in v2.0
    "direct_resume_if_safe": ToolStability.EXPERIMENTAL,  # Deprecated - use quick_resume or self_recovery_review
    "request_dialectic_review": ToolStability.EXPERIMENTAL,  # Deprecated - use self_recovery_review

    # EXPERIMENTAL: WIP, may change/break
    "simulate_update": ToolStability.EXPERIMENTAL,
    "detect_anomalies": ToolStability.EXPERIMENTAL,
    "aggregate_metrics": ToolStability.EXPERIMENTAL,
}

# Default stability for unlisted tools
_DEFAULT_STABILITY = ToolStability.BETA


# ============================================================================
# Public API
# ============================================================================

def resolve_tool_alias(tool_name: str) -> tuple[str, Optional[ToolAlias]]:
    """
    Resolve tool alias to actual tool name.
    
    Returns:
        (actual_tool_name, alias_info) - alias_info is None if not an alias
    """
    if tool_name in _TOOL_ALIASES:
        alias = _TOOL_ALIASES[tool_name]
        return alias.new_name, alias
    return tool_name, None


def get_tool_stability(tool_name: str) -> ToolStability:
    """Get stability tier for a tool"""
    return _TOOL_STABILITY.get(tool_name, _DEFAULT_STABILITY)


def get_tool_aliases(tool_name: str) -> List[str]:
    """Get all aliases (old names) for a tool"""
    return _ALIAS_REVERSE.get(tool_name, [])


def get_migration_guide(old_name: str) -> Optional[str]:
    """Get migration guide for a deprecated/renamed tool"""
    alias = _TOOL_ALIASES.get(old_name)
    if alias:
        return alias.migration_note
    return None


def list_all_aliases() -> Dict[str, ToolAlias]:
    """Get all tool aliases (for admin/debugging)"""
    return _TOOL_ALIASES.copy()


def is_stable_tool(tool_name: str) -> bool:
    """Check if tool is marked as stable"""
    return get_tool_stability(tool_name) == ToolStability.STABLE


def is_experimental_tool(tool_name: str) -> bool:
    """Check if tool is marked as experimental"""
    return get_tool_stability(tool_name) == ToolStability.EXPERIMENTAL

