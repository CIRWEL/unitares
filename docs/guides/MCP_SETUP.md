# MCP Server Setup Guide

**UNITARES Governance MCP Server v2.7.0**

This guide shows you how to connect to the governance MCP server from any MCP-compatible client.

---

## What is This?

The MCP server provides 31 governance tools accessible from:
- **Claude Code** (via MCP integration)
- **Cursor IDE** (via MCP integration)
- **Claude Desktop** (via MCP integration)
- **Any MCP-compatible client** (Streamable HTTP)

---

## Installation (Self-Hosted)

### Step 1: Install Dependencies

```bash
cd ~/projects/governance-mcp-v1
pip install -r requirements-full.txt
```

### Step 2: Start the Server

**HTTP mode (multi-client, recommended):**
```bash
python3 src/mcp_server.py --port 8767 --host 0.0.0.0
```

**Stdio mode (single-client, for local IDE):**
```bash
python3 src/mcp_server_std.py
```

### Step 3: Verify

```bash
curl http://localhost:8767/health
```

---

## Client Configuration

### Option A: Claude Code (`~/.claude.json`)

```json
{
  "mcpServers": {
    "unitares-governance": {
      "type": "http",
      "url": "http://127.0.0.1:8767/mcp/"
    }
  }
}
```

For remote access via ngrok:
```json
{
  "mcpServers": {
    "unitares-governance": {
      "type": "http",
      "url": "https://your-domain.ngrok.io/mcp/",
      "headers": {
        "Authorization": "Basic <base64-encoded-credentials>"
      }
    }
  }
}
```

### Option B: Cursor IDE (`~/.cursor/mcp.json`)

Same JSON format as above. Use the primary config location:
- macOS: `~/.cursor/mcp.json`
- Linux: `~/.cursor/mcp.json`
- Windows: `%USERPROFILE%\.cursor\mcp.json`

**Tip:** Keep only ONE config file. If you have configs in multiple Cursor locations, duplicates may appear.

### Option C: Claude Desktop

Config location:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Same JSON format as above. Restart Claude Desktop after changes.

---

## Available Tools

The server exposes **31 registered tools**. Key tools:

| Tool | Purpose |
|------|---------|
| `onboard` | First call - creates identity, returns setup info |
| `process_agent_update` | Check in work, get governance feedback |
| `get_governance_metrics` | View EISV state, coherence, risk |
| `identity` | Check or set your display name |
| `knowledge` | Store/search/get knowledge graph entries |
| `agent` | List, get, update, archive agents |
| `observe` | Observe agent metrics, compare, find anomalies |
| `calibration` | Check/update governance calibration |
| `self_recovery` | Self-recovery for stuck/paused agents |
| `call_model` | Delegate to local/free LLM |

**Identity is automatic** — no `api_key` or explicit registration needed. Identity binds on first tool call via session.

For the complete tool reference, see [SKILL.md](../../skills/unitares-governance/SKILL.md).

---

## Testing Your Setup

### 1. Health Check

```bash
curl http://localhost:8767/health
```

### 2. From Your MCP Client

Ask your AI assistant: "Call `onboard` to connect to governance."

The response will include your agent ID and available tools.

### 3. Run Test Suite

```bash
cd ~/projects/governance-mcp-v1
python3 -m pytest tests/ -v
```

---

## Architecture

```
┌──────────────────────────────────────────────┐
│  MCP Clients                                 │
│  (Claude Code, Cursor, Claude Desktop, etc.) │
└──────────────────┬───────────────────────────┘
                   │ MCP Streamable HTTP (/mcp/)
                   ▼
┌──────────────────────────────────────────────┐
│  mcp_server.py (HTTP, multi-client)          │
│  ┌────────────────────────────────────────┐  │
│  │  Middleware Pipeline                    │  │
│  │  identity → trajectory → alias →       │  │
│  │  validate → rate limit → dispatch      │  │
│  └────────────────────────────────────────┘  │
└──────────────────┬───────────────────────────┘
                   │
          ┌────────┼────────┐
          ▼        ▼        ▼
    ┌──────────┐ ┌──────┐ ┌────────────┐
    │PostgreSQL│ │Redis │ │governance_ │
    │  + AGE   │ │Cache │ │core (EISV) │
    └──────────┘ └──────┘ └────────────┘
```

---

## Troubleshooting

### "MCP SDK not installed"
```bash
pip install -r requirements-full.txt
```

### "Server not starting" / "Port already in use"
```bash
lsof -i :8767   # Check what's using the port
```

### "Tool not found"
- Restart your MCP client after config changes
- Verify the server is accessible: `curl http://localhost:8767/health`
- Check config JSON is valid

### Server Logs
```bash
tail -f data/logs/mcp_server.log
tail -f data/logs/mcp_server_error.log
```

For more troubleshooting, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Deployment Options

| Mode | Command | Use Case |
|------|---------|----------|
| **HTTP** | `python3 src/mcp_server.py --port 8767` | Multi-client, production |
| **Stdio** | `python3 src/mcp_server_std.py` | Single IDE client |
| **Launchd** | `launchctl load ~/Library/LaunchAgents/...` | macOS auto-start |
| **ngrok** | See [NGROK_DEPLOYMENT.md](NGROK_DEPLOYMENT.md) | Remote access |

For full deployment guide, see [DEPLOYMENT.md](DEPLOYMENT.md).

---

*Last updated: February 7, 2026*
