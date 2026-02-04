# Tool Registration Guide

**For AI agents and developers adding/modifying tools in the governance MCP server.**

## Quick Reference: Adding a New Tool

**Step 1: Define the tool schema** in `src/tool_schemas.py`:
```python
ToolDefinition(
    name="my_new_tool",
    description="What this tool does",
    inputSchema={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
        },
        "required": ["param1"]
    }
)
```

**Step 2: Implement the handler** in `src/mcp_handlers/*.py`:
```python
@mcp_tool("my_new_tool", timeout=10.0)
async def handle_my_new_tool(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    # Your implementation
    return success_response({"result": "..."})
```

**Step 3 (optional): Add to session injection list** if it needs `client_session_id`:
In `src/mcp_server.py`, add to `TOOLS_NEEDING_SESSION_INJECTION`:
```python
TOOLS_NEEDING_SESSION_INJECTION = {
    "my_new_tool",  # Add here if tool needs session identity
    ...
}
```

**That's it!** The tool is automatically registered via `auto_register_all_tools()`.

---

## Architecture Overview

### The Three Registration Points

| File | Purpose | When to Edit |
|------|---------|--------------|
| `src/tool_schemas.py` | Tool definitions (name, description, schema) | Always - defines the tool |
| `src/mcp_handlers/*.py` | Handler implementations with `@mcp_tool` | Always - implements the logic |
| `src/mcp_server.py` | HTTP transport registration | **Rarely** - only for server-specific tools |

### Auto-Registration System

The `auto_register_all_tools()` function in `mcp_server.py`:
1. Reads all tool definitions from `tool_schemas.py`
2. Creates FastMCP wrappers for each tool
3. Injects `client_session_id` for tools in `TOOLS_NEEDING_SESSION_INJECTION`
4. Registers with `mcp.tool()` decorator

**Result:** No manual `@tool_no_schema` decorators needed for most tools.

---

## Session Injection

Some tools need the session's `client_session_id` injected automatically.

**When to add a tool to `TOOLS_NEEDING_SESSION_INJECTION`:**
- Tool uses identity/authentication
- Tool stores data associated with an agent
- Tool needs to know "who is calling"

**Current list (Dec 2025):**
```python
TOOLS_NEEDING_SESSION_INJECTION = {
    "onboard",
    "identity",
    "process_agent_update",
    "get_governance_metrics",
    "store_knowledge_graph",
    "search_knowledge_graph",
    "leave_note",
    "observe_agent",
    "get_agent_metadata",
    "update_agent_metadata",
    "archive_agent",
    "delete_agent",
    "get_system_history",
    "export_to_file",
    "mark_response_complete",
    # "direct_resume_if_safe", # DEPRECATED - use quick_resume
    "update_discovery_status_graph",
    "get_discovery_details",
    "get_dialectic_session",
    "get_knowledge_graph",
    "compare_me_to_similar",
}
```

---

## Tool Tiers (for list_tools filtering)

Tools are organized into tiers in `src/tool_modes.py`:

| Tier | Purpose | Example Tools |
|------|---------|---------------|
| `essential` | Core workflow (~10 tools) | onboard, identity, process_agent_update |
| `common` | Regular use (~20 tools) | observe_agent, get_agent_metadata |
| `advanced` | Rarely used (~15 tools) | cleanup_stale_locks, reset_monitor |

**When adding a new tool, add it to the appropriate tier.**

---

## Tool Aliases (Backwards Compatibility)

When renaming/consolidating tools, add aliases in `src/mcp_handlers/tool_stability.py`:

```python
_TOOL_ALIASES = {
    "old_tool_name": ToolAlias(
        old_name="old_tool_name",
        new_name="new_tool_name",
        reason="renamed",
        migration_note="Use new_tool_name instead"
    ),
}
```

This ensures old code/agents continue to work.

---

## Common Mistakes

### 1. Tool not showing up in MCP clients
**Cause:** Added to `tool_schemas.py` but forgot to add handler with `@mcp_tool`.
**Fix:** Add handler in `src/mcp_handlers/*.py`.

### 2. Tool shows in REST API but not MCP clients
**Cause:** (Pre Dec-2025) Missing registration decorator.
**Fix:** Now auto-registered. Check server logs for registration errors.

### 3. Session identity not working
**Cause:** Tool not in `TOOLS_NEEDING_SESSION_INJECTION`.
**Fix:** Add tool name to the set in `mcp_server.py`.

### 4. Deprecated tool still appearing
**Cause:** Tool not added to aliases in `tool_stability.py`.
**Fix:** Add alias and remove from `tool_schemas.py`.

---

## Verification Commands

```bash
# Check registered tools count
curl -s -X POST "http://localhost:8767/v1/tools/call" \
  -H "Content-Type: application/json" \
  -d '{"name": "list_tools", "arguments": {"lite": false}}' | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Total tools: {len(d.get(\"result\",{}).get(\"tools\",[]))}')"

# Verify specific tool exists
curl -s -X POST "http://localhost:8767/v1/tools/call" \
  -H "Content-Type: application/json" \
  -d '{"name": "describe_tool", "arguments": {"tool_name": "my_new_tool"}}'

# Check server logs for auto-registration
tail -100 /Users/cirwel/projects/governance-mcp-v1/data/logs/mcp_server_error.log | grep "AUTO_REGISTER"
```

---

## Summary

| Task | Files to Edit |
|------|---------------|
| Add new tool | `tool_schemas.py` + `mcp_handlers/*.py` |
| Tool needs session | + `TOOLS_NEEDING_SESSION_INJECTION` in `mcp_server.py` |
| Rename/deprecate tool | `tool_stability.py` (add alias) |
| Categorize for list_tools | `tool_modes.py` (add to tier) |

---

**Last Updated:** 2026-02-03 (SSE deprecated, uses Streamable HTTP)
