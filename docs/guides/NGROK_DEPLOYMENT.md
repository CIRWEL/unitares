# ngrok Deployment Guide

Status: specialized deployment reference. Not primary onboarding or default local setup.

**Last Updated:** March 2026
**Transport:** Streamable HTTP (`/mcp/` endpoint)
**Port:** 8767

> **Note:** This guide uses placeholder values. Replace `your-domain.ngrok.io` with your own [ngrok reserved domain](https://dashboard.ngrok.com/domains).

---

## Overview

Deploy your UNITARES MCP server publicly via ngrok for:
- Multi-client access (Cursor, Claude Code, Claude Desktop)
- Remote collaboration
- Production deployments

---

## Quick Start

### 1. Start the MCP Server

The server runs as a launchd service:

```bash
# Check if running
launchctl list | grep governance

# Restart if needed
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

### 2. Deploy ngrok Tunnel

```bash
# Start ngrok tunnel manually:
ngrok http 8767 --domain your-domain.ngrok.io
```

**Verify:**
```
curl https://your-domain.ngrok.io/health
==========================================

✅ MCP server running on port 8767
📍 Using reserved domain: your-domain.ngrok.io

🔗 Your UNITARES MCP Server is available at:
   https://your-domain.ngrok.io/mcp/
```

---

## Client Configuration

### Cursor IDE

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "unitares-governance": {
      "type": "http",
      "url": "https://your-domain.ngrok.io/mcp/"
    }
  }
}
```

### Claude Code CLI

Add to `~/.claude.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "unitares-governance": {
      "type": "http",
      "url": "https://your-domain.ngrok.io/mcp/"
    }
  }
}
```

> **Optional:** Add `"headers": {"Authorization": "Basic <token>"}` if you've configured ngrok Traffic Policy with authentication.

### Local Development (No ngrok)

For local-only access:

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

---

## Production Deployment

### Using launchd (Auto-Start)

The MCP server uses launchd for automatic restart:

```bash
# Check status
launchctl list | grep governance

# View logs
tail -f /path/to/governance-mcp-v1/data/logs/mcp_server.log
tail -f /path/to/governance-mcp-v1/data/logs/mcp_server_error.log
```

### ngrok as a Service

For a persistent ngrok tunnel, install as a launchd service:

```bash
# Create a launchd plist for persistent ngrok tunnel.
# See ngrok docs for plist format, then:
launchctl load ~/Library/LaunchAgents/com.unitares.ngrok-governance.plist
```

Or use tmux for quick testing:

```bash
tmux new -s ngrok
./scripts/deploy_ngrok.sh
# Detach: Ctrl+B, then D
```

---

## Monitoring

### Health Check

```bash
# Via ngrok
curl -s https://your-domain.ngrok.io/health

# Local
curl -s http://127.0.0.1:8767/health
```

### Server Logs

```bash
# MCP server logs
tail -f data/logs/mcp_server.log

# Error logs
tail -f data/logs/mcp_server_error.log
```

### ngrok Dashboard

Access: https://dashboard.ngrok.com

---

## Troubleshooting

### "Connection refused"

**Cause:** MCP server not running.

**Fix:**
```bash
# Check if running
lsof -ti:8767

# Restart service
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

### "Tunnel not found"

**Cause:** ngrok domain not reserved or authtoken missing.

**Fix:**
```bash
# Check ngrok config
cat ~/Library/Application\ Support/ngrok/ngrok.yml

# Verify domain
ngrok domains list
```

### "502 Bad Gateway"

**Cause:** Server crashed or not responding.

**Fix:**
```bash
# Check error logs
tail -50 data/logs/mcp_server_error.log

# Restart service
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

---

## Production Checklist

Before deploying:

- [x] Reserved domain created (your-domain.ngrok.io)
- [ ] MCP server running (`lsof -ti:8767`)
- [ ] launchd auto-start enabled
- [ ] ngrok tunnel running (`./scripts/deploy_ngrok.sh`)
- [ ] Health check passes (`curl https://your-domain.ngrok.io/health`)
- [ ] Tool discovery works (`health_check` tool)
- [ ] Logs monitored

---

## Support

**Logs:**
- Server: `data/logs/mcp_server.log`
- Errors: `data/logs/mcp_server_error.log`

**Service Management:**
```bash
# Restart
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

---

**Status:** ✅ Ready for deployment
**Transport:** Streamable HTTP (`/mcp/` endpoint)
**Port:** 8767
