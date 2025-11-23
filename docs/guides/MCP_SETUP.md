# MCP Server Setup Guide

**UNITARES Governance MCP Server v1.0**

This guide shows you how to set up the custom MCP server for governance monitoring.

---

## What is This?

The MCP server provides governance monitoring tools that can be used directly from:
- **Cursor IDE** (via MCP integration)
- **Claude Desktop** (via MCP integration)
- **Any MCP-compatible client**

You can call governance tools directly from your AI assistant!

---

## Installation

### Step 1: Install Dependencies

```bash
cd ~/projects/governance-mcp-v1
pip install -r requirements-mcp.txt
```

Or install manually:
```bash
pip install mcp numpy
```

### Step 2: Verify Installation

```bash
python3 src/mcp_server_std.py --help
```

You should see the server start (it will wait for stdio input).

---

## Configuration

### Option A: Cursor IDE

1. **Find Cursor MCP config location:**
   - macOS: `~/Library/Application Support/Cursor/User/globalStorage/mcp.json`
   - Linux: `~/.config/Cursor/User/globalStorage/mcp.json`
   - Windows: `%APPDATA%\Cursor\User\globalStorage\mcp.json`

2. **Add to config:**
   ```json
   {
     "mcpServers": {
       "governance-monitor": {
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

3. **Update the path** to match your system:
   - Replace `/Users/cirwel/` with your home directory
   - Or use absolute path to `mcp_server_std.py`

4. **Restart Cursor**

### Option B: Claude Desktop

1. **Find Claude Desktop MCP config:**
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

2. **Add to config** (same as Cursor above)

3. **Restart Claude Desktop**

---

## Available Tools

Once configured, you can use these tools from your AI assistant:

### 1. `process_agent_update`
Run one complete governance cycle.

**Example:**
```
Use the governance-monitor tool process_agent_update with:
- agent_id: "cursor_ide"
- parameters: [0.5, 0.6, 0.7, 0.8, 0.5, 0.1]
- ethical_drift: [0.05, 0.1, 0.15]
- response_text: "Here's how to implement authentication..."
- complexity: 0.7
```

### 2. `get_governance_metrics`
Get current governance state.

**Example:**
```
Use the governance-monitor tool get_governance_metrics with:
- agent_id: "cursor_ide"
```

### 3. `get_system_history`
Export governance history.

**Example:**
```
Use the governance-monitor tool get_system_history with:
- agent_id: "cursor_ide"
- format: "json"
```

### 4. `reset_monitor`
Reset governance state (for testing).

**Example:**
```
Use the governance-monitor tool reset_monitor with:
- agent_id: "cursor_ide"
```

### 5. `list_agents`
List all monitored agents.

**Example:**
```
Use the governance-monitor tool list_agents
```

---

## Testing

### Test 1: Direct Python Test

```bash
cd ~/projects/governance-mcp-v1
python3 src/mcp_server_std.py
```

The server will start and wait for stdio input (this is normal for MCP servers).

### Test 2: Use from Cursor/Claude Desktop

1. Open Cursor or Claude Desktop
2. Ask: "What governance tools are available?"
3. The AI should list the 5 tools above
4. Try: "Use process_agent_update to monitor a test agent"

### Test 3: Integration Test

```bash
cd ~/projects/governance-mcp-v1
python3 -c "
import asyncio
from src.mcp_server_std import get_or_create_monitor
monitor = get_or_create_monitor('test_agent')
print('✅ Monitor created successfully')
"
```

---

## Troubleshooting

### "MCP SDK not installed"
```bash
pip install mcp
```

### "Module not found: src.governance_monitor"
Make sure `PYTHONPATH` includes the project root:
```bash
export PYTHONPATH=$PYTHONPATH:~/projects/governance-mcp-v1
```

### "Server not starting"
- Check Python path in config: `which python3`
- Check file permissions: `chmod +x src/mcp_server_std.py`
- Check logs in Cursor/Claude Desktop MCP panel

### "Tool not found"
- Restart Cursor/Claude Desktop after config change
- Check MCP server is running (should appear in MCP panel)
- Verify config JSON is valid

---

## Usage Examples

### Example 1: Monitor Cursor Interaction

From Cursor chat:
```
I just got a response from Cursor. Can you monitor it using governance?

Use process_agent_update with:
- agent_id: "cursor_ide"
- response_text: "[paste the response]"
- complexity: 0.6
```

### Example 2: Check Governance Status

```
What's the current governance status for cursor_ide?

Use get_governance_metrics with agent_id: "cursor_ide"
```

### Example 3: Export History

```
Export the governance history for cursor_ide as JSON.

Use get_system_history with:
- agent_id: "cursor_ide"
- format: "json"
```

---

## Architecture

```
┌─────────────────────────────────────────┐
│  Cursor / Claude Desktop                │
│  (MCP Client)                          │
└──────────────┬──────────────────────────┘
               │ MCP Protocol (stdio)
               ▼
┌─────────────────────────────────────────┐
│  mcp_server_std.py                      │
│  (MCP Server)                           │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  GovernanceMCPServer                    │
│  (Business Logic)                        │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  UNITARESMonitor                        │
│  (Governance Framework)                 │
└─────────────────────────────────────────┘
```

---

## Benefits

✅ **Direct Integration**: Use governance tools directly from AI assistants  
✅ **Real-time Monitoring**: Monitor interactions as they happen  
✅ **Unified Interface**: Same tools work in Cursor and Claude Desktop  
✅ **No Manual Logging**: AI can call tools automatically  
✅ **Rich Context**: AI has access to governance metrics and decisions  

---

## Next Steps

1. ✅ Install dependencies
2. ✅ Configure Cursor/Claude Desktop
3. ✅ Test with a simple interaction
4. ✅ Integrate into your workflow
5. ✅ Monitor multiple agents

---

## Support

- **Documentation**: See `README.md` for governance framework details
- **Examples**: See `demo_complete_system.py` for usage examples
- **Bridges**: See `scripts/claude_code_bridge.py` and `scripts/cursor_bridge.py`

---

**Status**: Ready to use! 🚀

