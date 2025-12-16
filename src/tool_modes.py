"""
Tool Modes - Define subsets of tools for different use cases

Minimal mode: 4 essential tools - perfect for getting started (includes list_tools for discovery)
Lite mode: Essential tools only (~10 tools) - optimized for local models
Full mode: All tools (49 tools) - for cloud models with large context windows
Note: Tool-mode filtering is applied by servers that choose to enforce it (e.g. stdio list_tools).
      Full mode should always include *all* schema tools even if categories lag behind.

Client-specific exclusions:
- Claude Desktop: Excludes tools that cause hangs (web search, heavy operations)
"""

from typing import Set
import os

# Read tool mode from environment (default: full)
TOOL_MODE = os.getenv("GOVERNANCE_TOOL_MODE", "full").lower()

# Minimal mode: Essential tools + list_tools for discovery
MINIMAL_MODE_TOOLS: Set[str] = {
    "get_agent_api_key",      # Register/get API key (once)
    "process_agent_update",   # Log your work (ongoing)
    "get_governance_metrics", # Check your status (as needed)
    "list_tools",             # Discover available tools (bootstrap)
    "describe_tool",          # Pull full details for a specific tool (lazy schema)
}

# Core/essential tools for lite mode (optimized for local models)
LITE_MODE_TOOLS: Set[str] = {
    # Core governance (3 tools)
    "process_agent_update",      # Log agent work
    "get_governance_metrics",     # Check agent status
    "simulate_update",            # Test potential updates

    # Identity/registration (2 tools)
    "get_agent_api_key",         # Register new agents
    "list_agents",               # View all agents
    "bind_identity",             # Bind session to agent identity
    "recall_identity",           # Recall session-bound identity

    # System health (3 tools)
    "health_check",              # System status
    "get_server_info",           # Server information
    "list_tools",                # See available tools
    "describe_tool",             # Pull full tool details on demand (reduces list bloat)

    # Data access (2 tools)
    "get_system_history",        # View agent history
    "export_to_file",            # Export data
}

# Tool categories for selective loading
TOOL_CATEGORIES = {
    "core": {
        "process_agent_update",
        "get_governance_metrics",
        "simulate_update",
    },
    "identity": {
        "bind_identity",
        "recall_identity",
        "get_agent_api_key",
        "list_agents",
        "get_agent_metadata",
    },
    "admin": {
        "health_check",
        "get_server_info",
        "list_tools",
        "describe_tool",
        "nudge_dialectic_session",
        "get_tool_usage_stats",
        "cleanup_stale_locks",
        "get_workspace_health",
        "check_calibration",
        "get_telemetry_metrics",
        "update_calibration_ground_truth",
        "reset_monitor",
        "validate_file_path",
        "backfill_calibration_from_dialectic",
    },
    "export": {
        "get_system_history",
        "export_to_file",
    },
    "config": {
        "get_thresholds",
        "set_thresholds",
    },
    "lifecycle": {
        "archive_agent",
        "delete_agent",
        "update_agent_metadata",
        "mark_response_complete",
        "direct_resume_if_safe",
        "archive_old_test_agents",
    },
    "observability": {
        "observe_agent",
        "compare_agents",
        "compare_me_to_similar",
        "detect_anomalies",
        "aggregate_metrics",
    },
    "knowledge": {
        "store_knowledge_graph",
        "search_knowledge_graph",
        "get_knowledge_graph",
        "list_knowledge_graph",
        "find_similar_discoveries_graph",
        "get_discovery_details",
        "get_related_discoveries_graph",
        "get_response_chain_graph",
        "reply_to_question",
        "leave_note",
        "update_discovery_status_graph",
    },
    "dialectic": {
        "request_dialectic_review",
        "request_exploration_session",
        "submit_thesis",
        "submit_antithesis",
        "submit_synthesis",
        "get_dialectic_session",
        "nudge_dialectic_session",
    },
}


def get_tools_for_mode(mode: str = "full") -> Set[str]:
    """
    Get tool set for specified mode

    Args:
        mode: "minimal", "lite", "full", or category name (e.g., "core", "admin")

    Returns:
        Set of tool names to include
    """
    if mode == "minimal":
        return MINIMAL_MODE_TOOLS.copy()
    
    if mode == "lite":
        return LITE_MODE_TOOLS.copy()

    if mode == "full":
        # IMPORTANT: Full mode must include *all* tools defined in the schema, not just
        # what happens to be listed in TOOL_CATEGORIES. This prevents accidental
        # omissions when new tools are added but categories aren't updated yet.
        try:
            from src.tool_schemas import get_tool_definitions
            return {t.name for t in get_tool_definitions()}
        except Exception:
            # Fallback (best-effort): union of categories
            all_tools = set()
            for tools in TOOL_CATEGORIES.values():
                all_tools.update(tools)
            return all_tools

    # Check if it's a category name
    if mode in TOOL_CATEGORIES:
        return TOOL_CATEGORIES[mode].copy()

    # Default to full
    all_tools = set()
    for tools in TOOL_CATEGORIES.values():
        all_tools.update(tools)
    return all_tools


def is_claude_desktop_client() -> bool:
    """
    Detect if MCP client is Claude Desktop (vs Cursor or other clients).
    
    Claude Desktop is more sensitive to hangs, so we exclude problematic tools.
    
    Returns:
        True if client appears to be Claude Desktop
    """
    # Check parent process name (most reliable)
    try:
        import psutil
        current_process = psutil.Process()
        parent = current_process.parent()
        if parent:
            parent_name = parent.name().lower()
            if "claude" in parent_name:
                return True
            # Check up the process tree
            for _ in range(3):
                try:
                    if parent:
                        parent = parent.parent()
                        if parent:
                            parent_name = parent.name().lower()
                            if "claude" in parent_name:
                                return True
                except (psutil.NoSuchProcess, AttributeError):
                    break
    except (ImportError, AttributeError, psutil.NoSuchProcess):
        pass
    
    # Check environment variables
    if os.getenv("CLAUDE_DESKTOP") or os.getenv("ANTHROPIC_CLAUDE"):
        return True
    
    return False


# Tools to exclude for Claude Desktop (causes hangs/freezes)
CLAUDE_DESKTOP_EXCLUDED_TOOLS: Set[str] = {
    # Add tools here that cause Claude Desktop to hang
    # Example: "web_search", "heavy_operation", etc.
    # Currently empty - add tools as issues are discovered
}


def should_include_tool(tool_name: str, mode: str = "full", client_type: str = None) -> bool:
    """
    Check if a tool should be included in the specified mode and client type

    Args:
        tool_name: Name of the tool
        mode: "minimal", "lite", "full", or category name
        client_type: Optional client type override ("claude_desktop" or None for auto-detect)

    Returns:
        True if tool should be included
    """
    # Always include discovery tools so agents can recover from over-filtering.
    # This matches the onboarding docs: list_tools should be available in any mode.
    if tool_name in {"list_tools", "describe_tool"}:
        return True

    # Check mode filtering first
    allowed_tools = get_tools_for_mode(mode)
    if tool_name not in allowed_tools:
        return False
    
    # Check Claude Desktop exclusions
    if client_type == "claude_desktop" or (client_type is None and is_claude_desktop_client()):
        if tool_name in CLAUDE_DESKTOP_EXCLUDED_TOOLS:
            return False
    
    return True
