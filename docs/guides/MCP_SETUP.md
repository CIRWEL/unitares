# MCP Server Setup Guide

**UNITARES Governance MCP Server v2.5.5**

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
pip install -r requirements-core.txt
```

Or install manually:
```bash
pip install mcp numpy
```

For SSE/HTTP (multi-client) mode:
```bash
pip install -r requirements-full.txt
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
   - macOS: `~/.cursor/mcp.json` (primary location - shown in Cursor UI)
   - Alternative: `~/Library/Application Support/Cursor/User/globalStorage/mcp.json` (may also work)
   - Linux: `~/.cursor/mcp.json` or `~/.config/Cursor/User/globalStorage/mcp.json`
   - Windows: `%USERPROFILE%\.cursor\mcp.json` or `%APPDATA%\Cursor\User\globalStorage\mcp.json`
   
   **Note:** Cursor may check `~/.cursor/mcp.json` first. This is the location shown in Cursor's UI settings.
   
   **⚠️ Important:** If you have MCP configs in multiple locations, Cursor may load duplicates. Keep only ONE main config file:
   - **Primary:** `~/.cursor/mcp.json` (recommended - shown in UI)
   - **Remove:** `~/Library/Application Support/Cursor/User/globalStorage/mcp.json` (if exists, causes duplicates)
   - **Remove:** `~/Library/Application Support/Cursor/mcp.json` (legacy, may cause duplicates)
   
   **Note:** Cursor also maintains project-specific `mcp-cache.json` files in `~/.cursor/projects/*/`. These are managed by Cursor automatically and may cause apparent duplicates in the UI. This is normal Cursor behavior and not necessarily a problem.

2. **Add to config (recommended: SSE):**
   ```json
   {
     "mcpServers": {
       "governance-monitor": {
         "url": "http://127.0.0.1:8765/sse"
       }
     }
   }
   ```

3. **Update the path** to match your system:
   - Replace `/Users/cirwel/` with your home directory
   - Or use absolute path to `mcp_server_std.py`

4. **Restart Cursor**

### Option B: Claude Desktop (recommended: stdio → SSE proxy)

1. **Find Claude Desktop MCP config:**
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

2. **Generate your config JSON** (prints JSON you can paste):
   ```bash
   cd /path/to/governance-mcp-v1
   ./scripts/mcp config claude-desktop http://127.0.0.1:8765/sse
   ```

3. **Restart Claude Desktop**

---

## Available Tools

Once configured, agents can access governance tools via MCP:

### 1. `process_agent_update`
Log agent operations and receive governance feedback. Primary tool for governance cycle participation.

**⚠️ Authentication Required:** Existing agents must provide `api_key` parameter for ownership verification. New agents receive API key upon creation.

**Example (New Agent - Auto-Registration):**
```
process_agent_update with:
- agent_id: "<agent_identifier_YYYYMMDD_HHMM>"
- parameters: [0.5, 0.6, 0.7, 0.8, 0.5, 0.1]  # Deprecated, ignored
- ethical_drift: [0.05, 0.1, 0.15]  # Deprecated, ignored
- response_text: "Operation summary"
- complexity: 0.7
```

**Example (Existing Agent - Authentication Required):**
```
process_agent_update with:
- agent_id: "<agent_identifier_YYYYMMDD_HHMM>"
- api_key: "<api_key_from_registration>"  # ← Required
- parameters: [...]  # Deprecated
- ethical_drift: [...]  # Deprecated
- response_text: "Operation summary"
- complexity: 0.7
```

**Identity (v2.4.0+):**
- Identity auto-creates on first tool call (no explicit registration needed)
- Call `identity()` to check your UUID
- Session binding handles authentication automatically

**Example Response:**
```json
{
  "success": true,
  "status": "moderate",
  "decision": {
    "action": "proceed",
    "reason": "Low attention load (0.43) - within normal operating parameters",
    "guidance": "Moderate complexity operations - continue current approach"
  },
  "metrics": {
    "E": 0.70,
    "I": 0.82,
    "S": 0.15,
    "V": -0.01,
    "coherence": 0.50,
    "attention_score": 0.43,
    "health_status": "moderate",
    "health_message": "Typical attention load (43%) - standard operational range"
  },
  "sampling_params": {
    "temperature": 0.59,
    "top_p": 0.86,
    "max_tokens": 150
  },
  "sampling_params_note": "Optional generation parameters derived from current thermodynamic state. Advisory only - agents may use or ignore. Temperature 0.59 = balanced exploration. Max tokens 150 = suggested output length.",
  "eisv_labels": {
    "E": {"label": "Energy", "description": "Thermodynamic energy state - exploration/productive capacity"},
    "I": {"label": "Information Integrity", "description": "Information preservation - coherence and consistency"},
    "S": {"label": "Entropy", "description": "Uncertainty measure - ethical drift accumulation"},
    "V": {"label": "Void Integral", "description": "E-I imbalance accumulator - thermodynamic strain"}
  }
}
```

### 2. `get_governance_metrics`
Retrieve current thermodynamic state and governance metrics.

**Example:**
```
get_governance_metrics with:
- agent_id: "<agent_identifier>"
```

### 3. `get_system_history`
Export governance history time series.

**Example:**
```
get_system_history with:
- agent_id: "<agent_identifier>"
- format: "json"
```

### 4. `reset_monitor`
Reset agent state to initial conditions (testing/development only).

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
2. ✅ Configure MCP client (Cursor/Claude Desktop)
3. ✅ Execute test interaction
4. ✅ Integrate into operational workflows
5. ✅ Monitor multiple agent instances

---

## Support

- **Documentation**: See `README.md` for governance framework details
- **Examples**: See `demo_complete_system.py` for usage examples
- **Python API**: Use `from src.governance_monitor import UNITARESMonitor` for direct integration

---

**Status**: Ready to use! 🚀

