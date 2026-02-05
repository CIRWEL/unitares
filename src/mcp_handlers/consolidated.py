"""
Consolidated MCP Tool Handlers

Reduces cognitive load for AI agents by consolidating related tools:
- knowledge: 8 tools → 1 (store, search, get, list, update, note, cleanup, stats)
- agent: 5 core tools → 1 (list, get, update, archive, delete)
- calibration: 4 tools → 1 (check, update, backfill, rebuild)

Each consolidated tool uses an 'action' parameter to select the operation.
Original tools remain available for backwards compatibility.
"""

from typing import Dict, Any, Sequence, Optional, List
from mcp.types import TextContent

from .decorators import mcp_tool
from .utils import success_response, error_response

# Import original handlers to delegate to
from .knowledge_graph import (
    handle_store_knowledge_graph,
    handle_search_knowledge_graph,
    handle_get_knowledge_graph,
    handle_list_knowledge_graph,
    handle_update_discovery_status_graph,
    handle_get_discovery_details,
    handle_leave_note,
    handle_cleanup_knowledge_graph,
    handle_get_lifecycle_stats,
)
from .lifecycle import (
    handle_list_agents,
    handle_get_agent_metadata,
    handle_update_agent_metadata,
    handle_archive_agent,
    handle_delete_agent,
)
from .admin import (
    handle_check_calibration,
    handle_update_calibration_ground_truth,
    handle_backfill_calibration_from_dialectic,
    handle_rebuild_calibration,
)
from .config import (
    handle_get_thresholds,
    handle_set_thresholds,
)


# ============================================================
# Consolidated Knowledge Graph Tool
# ============================================================

@mcp_tool("knowledge", timeout=30.0, description="Unified knowledge graph operations: store, search, get, list, update, note, cleanup, stats")
async def handle_knowledge(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Consolidated knowledge graph operations.

    Actions:
    - store: Store a discovery/insight in the knowledge graph
    - search: Semantic search across discoveries
    - get: Get all knowledge for a specific agent
    - list: Get knowledge graph statistics
    - update: Update discovery status (resolved, archived, etc.)
    - details: Get full details of a specific discovery
    - note: Quick note storage
    - cleanup: Run lifecycle cleanup on stale discoveries
    - stats: Get lifecycle statistics

    Replaces: store_knowledge_graph, search_knowledge_graph, get_knowledge_graph,
              list_knowledge_graph, update_discovery_status_graph, get_discovery_details,
              leave_note, cleanup_knowledge_graph, get_lifecycle_stats
    """
    action = arguments.get("action", "").lower()

    if not action:
        return [error_response(
            "action parameter required",
            recovery={
                "valid_actions": ["store", "search", "get", "list", "update", "details", "note", "cleanup", "stats"],
                "examples": [
                    "knowledge(action='store', summary='Found bug in auth', discovery_type='bug')",
                    "knowledge(action='search', query='authentication issues')",
                    "knowledge(action='note', content='Remember to check cache')",
                ]
            }
        )]

    # Route to appropriate handler
    if action == "store":
        return await handle_store_knowledge_graph(arguments)

    elif action == "search":
        # Map 'query' to expected parameter name if needed
        if "query" in arguments and "search_query" not in arguments:
            arguments["search_query"] = arguments["query"]
        return await handle_search_knowledge_graph(arguments)

    elif action == "get":
        return await handle_get_knowledge_graph(arguments)

    elif action == "list":
        return await handle_list_knowledge_graph(arguments)

    elif action == "update":
        return await handle_update_discovery_status_graph(arguments)

    elif action == "details":
        return await handle_get_discovery_details(arguments)

    elif action == "note":
        # Map 'content' to 'note' if needed
        if "content" in arguments and "note" not in arguments:
            arguments["note"] = arguments["content"]
        return await handle_leave_note(arguments)

    elif action == "cleanup":
        return await handle_cleanup_knowledge_graph(arguments)

    elif action == "stats":
        return await handle_get_lifecycle_stats(arguments)

    else:
        return [error_response(
            f"Unknown action: {action}",
            recovery={
                "valid_actions": ["store", "search", "get", "list", "update", "details", "note", "cleanup", "stats"]
            }
        )]


# ============================================================
# Consolidated Agent Lifecycle Tool
# ============================================================

@mcp_tool("agent", timeout=20.0, description="Unified agent lifecycle operations: list, get, update, archive, delete")
async def handle_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Consolidated agent lifecycle operations.

    Actions:
    - list: List all agents with metadata and health status
    - get: Get detailed metadata for a specific agent
    - update: Update agent tags, notes, preferences
    - archive: Archive agent for long-term storage
    - delete: Delete agent permanently (requires confirmation)

    Replaces: list_agents, get_agent_metadata, update_agent_metadata,
              archive_agent, delete_agent
    """
    action = arguments.get("action", "").lower()

    if not action:
        return [error_response(
            "action parameter required",
            recovery={
                "valid_actions": ["list", "get", "update", "archive", "delete"],
                "examples": [
                    "agent(action='list')",
                    "agent(action='get', agent_id='claude-opus-20251215')",
                    "agent(action='update', tags=['explorer', 'governance'])",
                    "agent(action='archive', agent_id='old-agent-id')",
                ]
            }
        )]

    if action == "list":
        return await handle_list_agents(arguments)

    elif action == "get":
        return await handle_get_agent_metadata(arguments)

    elif action == "update":
        return await handle_update_agent_metadata(arguments)

    elif action == "archive":
        return await handle_archive_agent(arguments)

    elif action == "delete":
        return await handle_delete_agent(arguments)

    else:
        return [error_response(
            f"Unknown action: {action}",
            recovery={
                "valid_actions": ["list", "get", "update", "archive", "delete"]
            }
        )]


# ============================================================
# Consolidated Calibration Tool
# ============================================================

@mcp_tool("calibration", timeout=60.0, description="Unified calibration operations: check, update, backfill, rebuild")
async def handle_calibration(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Consolidated calibration operations.

    Actions:
    - check: Check current calibration status and metrics
    - update: Update calibration with external ground truth
    - backfill: Backfill calibration from resolved dialectics
    - rebuild: Rebuild calibration from scratch (admin)

    Replaces: check_calibration, update_calibration_ground_truth,
              backfill_calibration_from_dialectic, rebuild_calibration
    """
    action = arguments.get("action", "check").lower()

    if action == "check":
        return await handle_check_calibration(arguments)

    elif action == "update":
        return await handle_update_calibration_ground_truth(arguments)

    elif action == "backfill":
        return await handle_backfill_calibration_from_dialectic(arguments)

    elif action == "rebuild":
        return await handle_rebuild_calibration(arguments)

    else:
        return [error_response(
            f"Unknown action: {action}",
            recovery={
                "valid_actions": ["check", "update", "backfill", "rebuild"],
                "examples": [
                    "calibration(action='check')",
                    "calibration(action='update', ground_truth=True)",
                ]
            }
        )]


# ============================================================
# Consolidated Config Tool
# ============================================================

@mcp_tool("config", timeout=15.0, description="Unified configuration operations: get, set thresholds")
async def handle_config(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Consolidated configuration operations.

    Actions:
    - get: Get current governance threshold configuration
    - set: Set runtime threshold overrides (admin only)

    Replaces: get_thresholds, set_thresholds
    """
    action = arguments.get("action", "get").lower()

    if action == "get":
        return await handle_get_thresholds(arguments)

    elif action == "set":
        return await handle_set_thresholds(arguments)

    else:
        return [error_response(
            f"Unknown action: {action}",
            recovery={
                "valid_actions": ["get", "set"],
                "examples": [
                    "config(action='get')",
                    "config(action='set', thresholds={'PAUSE_RISK_THRESHOLD': 0.75})",
                ]
            }
        )]