# Governance MCP Server - SSE Mode (Multi-Client)

The SSE (Server-Sent Events) transport enables **multiple clients to share a single governance server instance**. This means Cursor, Claude Desktop, and other MCP clients can all connect simultaneously and share state.

## Quick Start

### Option 1: Run Manually
```bash
# From project root
python src/mcp_server_sse.py

# Or with custom port
python src/mcp_server_sse.py --port 9000
```

### Option 2: Use the Start Script
```bash
./scripts/start_sse_server.sh
```

### Option 3: Run as Background Service (macOS)
```bash
# Install the launchd service
cp config/com.unitares.governance-mcp.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist

# Check status
launchctl list | grep governance

# View logs
tail -f data/logs/sse_server.log

# Stop the service
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

## Client Configuration

### Claude Desktop (`claude_desktop_config.json`)

**Note:** Claude Desktop requires `command` (stdio transport), not `url` (SSE transport).

```json
{
  "mcpServers": {
    "governance-monitor-v1": {
      "command": "python3",
      "args": [
        "/Users/cirwel/projects/governance-mcp-v1/src/mcp_server_std.py"
      ],
      "env": {
        "PYTHONPATH": "/Users/cirwel/projects/governance-mcp-v1"
      }
    }
  }
}
```

**For SSE transport (shared server):** Use Cursor IDE instead, or run SSE server separately and connect via HTTP.

### Cursor (MCP settings)
```json
{
  "governance-monitor-v1": {
    "url": "http://127.0.0.1:8765/sse"
  }
}
```

## Benefits Over stdio Transport

| Feature | stdio | SSE |
|---------|-------|-----|
| Multiple clients | ❌ Each spawns own process | ✅ All share one server |
| Shared state | ❌ Isolated per client | ✅ Real-time sync |
| Multi-agent dialectic | ❌ Can't actually peer review | ✅ True peer review |
| Persistence | ❌ Dies with client | ✅ Survives restarts |
| Resource usage | ❌ N processes for N clients | ✅ 1 process for all |

## Tool Mode Behavior

**Important:** SSE and stdio handle tool mode filtering differently:

| Aspect | stdio | SSE |
|--------|-------|-----|
| **Tool listing** | All 49 tools (tool mode filtering removed) | All 50 tools (49 shared + 1 SSE-only: `get_connected_clients`) |
| **Tool calls** | Filters by `TOOL_MODE` | Filters by `TOOL_MODE` (same as stdio) |

**Why the difference?**

- **SSE `list_tools()`**: Always exposes full tool set because FastMCP automatically exposes all `@mcp.tool` decorated functions. This is intentional for multi-client scenarios where different clients may want different tool sets.

- **SSE `call_tool()`**: Filters tools based on `TOOL_MODE` and client type (e.g., Claude Desktop exclusions), matching stdio behavior. Calls to filtered tools return an error.

**Result:** SSE clients see all tools in `list_tools()` but can only call tools allowed by `TOOL_MODE`. This provides flexibility while maintaining security boundaries.

## SSE-Only Features

### `get_connected_clients`
See who's currently connected to the shared server:
```json
{
  "transport": "SSE",
  "connected_clients": {
    "cursor-123": {"connected_at": "...", "request_count": 42},
    "claude-456": {"connected_at": "...", "request_count": 17}
  },
  "total_clients": 2
}
```

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Cursor    │     │   Claude    │     │  Other MCP  │
│   Agent     │     │   Desktop   │     │   Client    │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       │ HTTP/SSE          │ HTTP/SSE          │ HTTP/SSE
       ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────┐
│           Governance MCP Server (SSE)               │
│                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │  Knowledge  │  │  Dialectic  │  │   Agent     │ │
│  │   Graph     │  │  Sessions   │  │   State     │ │
│  └─────────────┘  └─────────────┘  └─────────────┘ │
│                                                     │
│                   SHARED STATE                      │
└─────────────────────────────────────────────────────┘
```

## Troubleshooting

### Port already in use
```bash
# Find what's using the port
lsof -i :8765

# Kill it
kill -9 <PID>
```

### Server won't start
```bash
# Check dependencies
pip install -r requirements-full.txt

# Check logs
cat data/logs/sse_server_error.log
```

### Clients can't connect
1. Ensure server is running: `curl http://127.0.0.1:8765/sse`
2. Check firewall settings
3. Verify client config URL matches server endpoint
