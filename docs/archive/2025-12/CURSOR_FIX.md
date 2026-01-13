# Fix for Cursor MCP Server Not Loading

## Issue
Cursor is configured to use `https://unitares.ngrok.io/mcp` but the server is running locally.

## Solution Options

### Option 1: Use Local Server (Recommended)
Update your Cursor MCP config at `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "governance": {
      "url": "http://127.0.0.1:8765/sse"
    }
  }
}
```

### Option 2: Use stdio Transport (Alternative)
If you prefer stdio transport (like Claude Desktop):

```json
{
  "mcpServers": {
    "governance": {
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

### Option 3: Fix Ngrok (If you need remote access)
1. Make sure ngrok is running: `ngrok http 8765`
2. Update the URL in Cursor config to match your ngrok URL
3. The server should be accessible at `https://unitares.ngrok.io/mcp`

## Verify Server is Running
```bash
# Check if server is running
ps aux | grep mcp_server_sse

# Test server health
curl http://127.0.0.1:8765/health

# Check server logs
tail -f data/logs/sse_server.log
```

## After Making Changes
1. Restart Cursor completely
2. Check Cursor's MCP connection status
3. Try calling a tool to verify it works

