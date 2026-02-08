# Tool Surfacing Audit

**Date:** 2026-02-06 (updated)
**Status:** ✅ Fixed

## Summary

Fixed tool registration inconsistencies:
- ✅ Created missing consolidated tools: `export`, `observe`, `pi`
- ✅ Fixed broken aliases pointing to non-existent tools
- ✅ All registered tools now have schemas (auto-generated if missing)
- ✅ All schemas are either registered or aliased (no orphans)

## Tool Categories

### Active Tools (50 tools, register=True)

These are the tools actually exposed via MCP:

**Consolidated Tools:**
- `agent` - Agent lifecycle (list, get, update, archive, delete)
- `knowledge` - Knowledge graph operations (store, search, get, list, update, details, note, cleanup, stats)
- `calibration` - Calibration operations (check, update, backfill, rebuild)
- `config` - Configuration (get, set thresholds)
- `export` - Export operations (history, file)
- `observe` - Observability (agent, compare, similar, anomalies, aggregate, telemetry, roi)
- `pi` - Pi/Lumen orchestration (tools, context, health, sync_eisv, display, say, message, qa, query, workflow, git_pull, power)

**Core Governance:**
- `onboard` - First-time agent setup
- `identity` - Identity management
- `process_agent_update` - Main governance cycle
- `get_governance_metrics` - Get current state
- `simulate_update` - Dry-run governance cycle

**Dialectic:**
- `request_dialectic_review` - Request peer review
- `get_dialectic_session` - Get session state
- `list_dialectic_sessions` - List all sessions
- `submit_thesis` - Submit thesis
- `submit_antithesis` - Submit antithesis
- `submit_synthesis` - Submit synthesis

**Observability:**
- `detect_stuck_agents` - Find stuck agents
- `observe(action='telemetry')` - System telemetry (via consolidated observe)
- `observe(action='roi')` - ROI calculations (via consolidated observe)

**Admin:**
- `health_check` - System health
- `get_server_info` - Server info
- `list_tools` - Tool discovery
- `describe_tool` - Tool details
- `cleanup_stale_locks` - Cleanup
- `reset_monitor` - Reset agent state

**And 20+ more...**

### Internal Tools (33 tools, register=False)

These tools are **not directly exposed** but are callable via aliases or consolidated tools:

**Export:**
- `get_system_history` → `export(action='history')`
- `export_to_file` → `export(action='file')`

**Pi Orchestration:**
- `pi_list_tools` → `pi(action='tools')`
- `pi_get_context` → `pi(action='context')`
- `pi_health` → `pi(action='health')`
- `pi_sync_eisv` → `pi(action='sync_eisv')`
- `pi_display` → `pi(action='display')`
- `pi_say` → `pi(action='say')`
- `pi_post_message` → `pi(action='message')`
- `pi_lumen_qa` → `pi(action='qa')`
- `pi_query` → `pi(action='query')`
- `pi_workflow` → `pi(action='workflow')`
- `pi_git_pull` → `pi(action='git_pull')`
- `pi_system_power` → `pi(action='power')`

**Observability:**
- `observe_agent` → `observe(action='agent')`
- `compare_agents` → `observe(action='compare')`
- `compare_me_to_similar` → `observe(action='similar')`
- `detect_anomalies` → `observe(action='anomalies')`
- `aggregate_metrics` → `observe(action='aggregate')`

**Agent Lifecycle:**
- `list_agents` → `agent(action='list')`
- `get_agent_metadata` → `agent(action='get')`
- `update_agent_metadata` → `agent(action='update')`
- `archive_agent` → `agent(action='archive')`
- `delete_agent` → `agent(action='delete')`

**Knowledge Graph:**
- `store_knowledge_graph` → `knowledge(action='store')`
- `get_knowledge_graph` → `knowledge(action='get')`
- `list_knowledge_graph` → `knowledge(action='list')`
- `update_discovery_status_graph` → `knowledge(action='update')`
- `get_discovery_details` → `knowledge(action='details')`
- `cleanup_knowledge_graph` → `knowledge(action='cleanup')`
- `get_lifecycle_stats` → `knowledge(action='stats')`

**Calibration:**
- `check_calibration` → `calibration(action='check')`
- `update_calibration_ground_truth` → `calibration(action='update')`
- `backfill_calibration_from_dialectic` → `calibration(action='backfill')`
- `rebuild_calibration` → `calibration(action='rebuild')`

### Deprecated Tools (0 tools)

No deprecated tools currently. All deprecated tools have been removed or replaced.

## How Tool Registration Works

1. **Handler Definition:** Tool handler with `@mcp_tool("tool_name", register=True)` decorator
2. **Schema Definition:** Tool schema in `tool_schemas.py` (or auto-generated)
3. **Auto-Registration:** `auto_register_all_tools()` in `mcp_server.py`:
   - Reads schemas from `tool_schemas.py`
   - Filters to only tools with `register=True` in decorator
   - Creates FastMCP wrappers
   - Registers with MCP server

**Key Point:** A tool must be in BOTH:
- `tool_schemas.py` (or auto-generated)
- `@mcp_tool` decorator with `register=True` (default)

## Aliases

Aliases provide backward compatibility for renamed/consolidated tools. Defined in `src/mcp_handlers/tool_stability.py`.

When an old tool name is called:
1. Check if it's in `_TOOL_ALIASES`
2. If yes, redirect to new tool with `action` parameter injected
3. If no, check if it's registered directly

## Schema Auto-Generation

If a tool is registered (`register=True`) but has no schema in `tool_schemas.py`, the system auto-generates a basic schema using:
- Tool name from decorator
- Description from decorator docstring
- Empty inputSchema (FastMCP will infer from handler signature)

This ensures all registered tools are discoverable even if schemas aren't manually defined.

## Fixes Applied

1. ✅ Created `export` consolidated tool (was aliased but didn't exist)
2. ✅ Created `observe` consolidated tool (was aliased but didn't exist)
3. ✅ Created `pi` consolidated tool (was aliased but didn't exist)
4. ✅ Fixed `get_system_history` alias to point to `export(action='history')`
5. ✅ Fixed `export_to_file` alias to point to `export(action='file')`
6. ✅ Fixed `aggregate_metrics` alias to point to `observe(action='aggregate')`
7. ✅ Removed duplicate `export_to_file` alias entry

## Verification

Run this to verify tool registration:
```python
from mcp_handlers.decorators import get_tool_registry
registered = get_tool_registry()
print(f"Total registered: {len(registered)}")
assert "export" in registered
assert "observe" in registered
assert "pi" in registered
```

## Next Steps

- [ ] Add detailed schemas for `export` and `observe` in `tool_schemas.py` (currently auto-generated)
- [ ] Consider marking internal tools in schemas with a note that they're callable via aliases
- [ ] Document consolidated tool patterns for future tool additions
