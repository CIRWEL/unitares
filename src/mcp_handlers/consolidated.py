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
from .export import (
    handle_get_system_history,
    handle_export_to_file,
)
from .observability import (
    handle_observe_agent,
    handle_compare_agents,
    handle_compare_me_to_similar,
    handle_detect_anomalies,
    handle_aggregate_metrics,
)
from .pi_orchestration import (
    handle_pi_list_tools,
    handle_pi_get_context,
    handle_pi_health,
    handle_pi_sync_eisv,
    handle_pi_display,
    handle_pi_say,
    handle_pi_post_message,
    handle_pi_lumen_qa,
    handle_pi_query,
    handle_pi_workflow,
    handle_pi_git_pull,
    handle_pi_system_power,
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


# ============================================================
# Consolidated Export Tool
# ============================================================

@mcp_tool("export", timeout=45.0, description="Unified export operations: history, file")
async def handle_export(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Consolidated export operations.

    Actions:
    - history: Export governance history inline (returns JSON/CSV)
    - file: Export governance history to file on server

    Replaces: get_system_history, export_to_file
    """
    action = arguments.get("action", "history").lower()

    if action == "history":
        return await handle_get_system_history(arguments)

    elif action == "file":
        return await handle_export_to_file(arguments)

    else:
        return [error_response(
            f"Unknown action: {action}",
            recovery={
                "valid_actions": ["history", "file"],
                "examples": [
                    "export(action='history', format='json')",
                    "export(action='file', format='json', filename='my_export')",
                ]
            }
        )]


# ============================================================
# Consolidated Observe Tool
# ============================================================

@mcp_tool("observe", timeout=15.0, description="Unified observability operations: agent, compare, similar, anomalies, aggregate")
async def handle_observe(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Consolidated observability operations.

    Actions:
    - agent: Observe a specific agent's patterns and behavior
    - compare: Compare two agents' behavior patterns
    - similar: Find agents similar to you
    - anomalies: Detect anomalies in agent behavior
    - aggregate: Get fleet-level health overview

    Replaces: observe_agent, compare_agents, compare_me_to_similar,
              detect_anomalies, aggregate_metrics
    """
    action = arguments.get("action", "").lower()

    if not action:
        return [error_response(
            "action parameter required",
            recovery={
                "valid_actions": ["agent", "compare", "similar", "anomalies", "aggregate"],
                "examples": [
                    "observe(action='agent', agent_id='claude-opus-20251215')",
                    "observe(action='compare', agent_ids=['agent1', 'agent2'])",
                    "observe(action='similar')",
                    "observe(action='anomalies')",
                    "observe(action='aggregate')",
                ]
            }
        )]

    if action == "agent":
        return await handle_observe_agent(arguments)

    elif action == "compare":
        return await handle_compare_agents(arguments)

    elif action == "similar":
        return await handle_compare_me_to_similar(arguments)

    elif action == "anomalies":
        return await handle_detect_anomalies(arguments)

    elif action == "aggregate":
        return await handle_aggregate_metrics(arguments)

    else:
        return [error_response(
            f"Unknown action: {action}",
            recovery={
                "valid_actions": ["agent", "compare", "similar", "anomalies", "aggregate"]
            }
        )]


# ============================================================
# Consolidated Pi Orchestration Tool
# ============================================================

@mcp_tool("pi", timeout=120.0, description="Unified Pi/Lumen orchestration: tools, context, health, sync_eisv, display, say, message, qa, query, workflow, git_pull, power")
async def handle_pi(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Consolidated Pi/Lumen orchestration operations.

    Actions:
    - tools: List available tools on Pi's anima-mcp server
    - context: Get Lumen's complete context (identity, anima state, sensors, mood)
    - health: Check Pi health and diagnostics
    - sync_eisv: Sync anima state to EISV governance metrics
    - display: Control Lumen's display (switch screens, show face, navigate)
    - say: Have Lumen express something (text mode)
    - message: Post a message to Lumen's message board
    - qa: List Lumen's unanswered questions OR answer one
    - query: Query Lumen's knowledge/self-knowledge
    - workflow: Execute workflows across anima-mcp and unitares-governance
    - git_pull: Pull latest code from git repository and optionally restart
    - power: Reboot or shutdown the Pi remotely

    Replaces: pi_list_tools, pi_get_context, pi_health, pi_sync_eisv,
              pi_display, pi_say, pi_post_message, pi_lumen_qa, pi_query,
              pi_workflow, pi_git_pull, pi_system_power
    """
    action = arguments.get("action", "").lower()

    if not action:
        return [error_response(
            "action parameter required",
            recovery={
                "valid_actions": ["tools", "context", "health", "sync_eisv", "display", "say", "message", "qa", "query", "workflow", "git_pull", "power"],
                "examples": [
                    "pi(action='tools')",
                    "pi(action='context')",
                    "pi(action='health')",
                    "pi(action='say', text='Hello!')",
                    "pi(action='display', action='switch', screen='face')",
                ]
            }
        )]

    if action == "tools":
        return await handle_pi_list_tools(arguments)

    elif action == "context":
        return await handle_pi_get_context(arguments)

    elif action == "health":
        return await handle_pi_health(arguments)

    elif action == "sync_eisv":
        return await handle_pi_sync_eisv(arguments)

    elif action == "display":
        return await handle_pi_display(arguments)

    elif action == "say":
        return await handle_pi_say(arguments)

    elif action == "message":
        return await handle_pi_post_message(arguments)

    elif action == "qa":
        return await handle_pi_lumen_qa(arguments)

    elif action == "query":
        return await handle_pi_query(arguments)

    elif action == "workflow":
        return await handle_pi_workflow(arguments)

    elif action == "git_pull":
        return await handle_pi_git_pull(arguments)

    elif action == "power":
        return await handle_pi_system_power(arguments)

    else:
        return [error_response(
            f"Unknown action: {action}",
            recovery={
                "valid_actions": ["tools", "context", "health", "sync_eisv", "display", "say", "message", "qa", "query", "workflow", "git_pull", "power"]
            }
        )]