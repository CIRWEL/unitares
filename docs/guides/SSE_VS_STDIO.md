# SSE vs stdio Transport Comparison

## Overview

The Governance MCP server supports two transport modes:

1. **stdio** - Single-client, per-process server (default for Claude Desktop)
2. **SSE** - Multi-client, shared server (default for Cursor)

## Registration Points

Both transports use the same underlying handlers, but register tools differently:

| Registration Point | stdio | SSE |
|-------------------|-------|-----|
| **Tool Categories** | `tool_modes.py` (TOOL_CATEGORIES) | Same |
| **Handler Registry** | `mcp_handlers/__init__.py` (TOOL_HANDLERS) | Same |
| **MCP Protocol** | `@server.list_tools()` in `mcp_server_std.py` | `@mcp.tool` decorators in `mcp_server_sse.py` |
| **Handler Implementation** | `@mcp_tool` decorators | Same (via `dispatch_tool`) |

## Tool Mode Filtering

### stdio Transport

- **`list_tools()`**: All tools always available (tool mode filtering removed)
  - stdio server: 45 tools
  - SSE server: 46 tools (45 shared + 1 SSE-only: `get_connected_clients`)
- **`call_tool()`**: Also filters by `TOOL_MODE` and client type (Claude Desktop exclusions)

### SSE Transport

- **`list_tools()`**: Always exposes full tool set (45 tools)
  - FastMCP automatically exposes all `@mcp.tool` decorated functions
  - Intentional for multi-client scenarios where different clients may want different tool sets
- **`call_tool()`**: Filters by `TOOL_MODE` and client type (matches stdio behavior)
  - Calls to filtered tools return an error
  - Provides flexibility while maintaining security boundaries

## Verified Parity

✅ **All 45 handler tools** available in both transports  
✅ **Same error handling** (proper JSON errors)  
✅ **Same authentication** (API key validation)  
✅ **Same data layer** (both persist to same files)  
✅ **Same tool call filtering** (both respect TOOL_MODE at call time)

## Known Divergences (By Design)

| Aspect | stdio | SSE | Reason |
|--------|-------|-----|--------|
| Tool listing | Filters by TOOL_MODE | Always full | Multi-client flexibility |
| Registration | `@server.list_tools()` | `@mcp.tool` decorators | FastMCP architecture |
| Process model | Per-client process | Shared server | Multi-client support |

## When to Use Which?

### Use stdio when:
- Single client (Claude Desktop)
- Need strict tool filtering at listing time
- Want isolated processes per client

### Use SSE when:
- Multiple clients (Cursor + others)
- Need shared state (knowledge graph, dialectic sessions)
- Want true multi-agent peer review
- Need persistent service that survives client restarts

## Configuration

### stdio (Claude Desktop)
```json
{
  "mcpServers": {
    "governance-monitor-v1": {
      "command": "python3",
      "args": ["/path/to/src/mcp_server_std.py"],
      "env": {
        "PYTHONPATH": "/path/to/project",
        "GOVERNANCE_TOOL_MODE": "full"
      }
    }
  }
}
```

### SSE (Cursor)
```json
{
  "governance-monitor-v1": {
    "url": "http://127.0.0.1:8765/sse"
  }
}
```

## Troubleshooting

### Tool appears in `list_tools()` but returns "Tool not found"

**For stdio:** Check that tool is registered in all four places:
1. `TOOL_CATEGORIES` in `tool_modes.py`
2. `TOOL_HANDLERS` in `mcp_handlers/__init__.py`
3. `@server.list_tools()` in `mcp_server_std.py`
4. Handler function with `@mcp_tool` decorator

**For SSE:** Tool must be:
1. Registered in `TOOL_CATEGORIES` (for filtering)
2. Registered in `TOOL_HANDLERS` (for dispatch)
3. Decorated with `@mcp.tool` in `mcp_server_sse.py`
4. Handler function with `@mcp_tool` decorator

**Validation:** Run `python3 scripts/validate_tool_registration.py` to check all registration points.

### Tool filtered out unexpectedly

Check `GOVERNANCE_TOOL_MODE` environment variable:
- `minimal`: Only 3 essential tools
- `lite`: 10 essential tools
- `full`: All 45 tools (default)

For SSE, tools are filtered at call time, not listing time. Check the error message for the specific reason.

