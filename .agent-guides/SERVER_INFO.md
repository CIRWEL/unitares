# MCP Server - Background Service Info

## Status: Running Automatically

The MCP server runs as a **persistent background service** via macOS launchd.

## Current Setup

**Service name:** `com.unitares.governance-mcp`
**Port:** 8767
**Status:** Running (PID can be checked with `launchctl list | grep governance`)

## How It Works

```
macOS Login
    ↓
launchd loads: ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
    ↓
Starts: python3 src/mcp_server.py --port 8767
    ↓
Server runs continuously
    ↓
If it crashes → launchd automatically restarts it (KeepAlive: true)
```

## Configuration

**File:** `~/Library/LaunchAgents/com.unitares.governance-mcp.plist`

**Key settings:**
- `RunAtLoad: true` - Starts automatically on login
- `KeepAlive: true` - Restarts if it crashes
- `WorkingDirectory` - Set to project root
- `StandardOutPath` - Logs to data/logs/mcp_server.log
- `StandardErrorPath` - Errors to data/logs/mcp_server_error.log

## For New Agents

**You don't need to start the server!** It's already running.

Just use:
```bash
./scripts/mcp log "agent_id" "work" 0.5
```

## Management Commands

**Check status:**
```bash
launchctl list | grep governance
lsof -i :8767
```

**Restart:**
```bash
launchctl restart com.unitares.governance-mcp
```

**Stop:**
```bash
launchctl stop com.unitares.governance-mcp
```

**Unload (disable auto-start):**
```bash
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

**Reload (enable auto-start):**
```bash
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

## Logs

**Standard output:**
```bash
tail -f /Users/cirwel/projects/governance-mcp-v1/data/logs/mcp_server.log
```

**Errors:**
```bash
tail -f /Users/cirwel/projects/governance-mcp-v1/data/logs/mcp_server_error.log
```

## Why This Matters for Onboarding

**Old assumption:** "New agents need to manually start the server"
**Reality:** Server is always running via launchd

**This means:**
- New agents can immediately use the MCP tools
- No "server not found" errors (unless launchd failed)
- Simpler onboarding - one command works
- Persistent across sessions

## Troubleshooting

### Server not responding

1. **Check if running:**
   ```bash
   lsof -i :8767
   ```

2. **Check launchd status:**
   ```bash
   launchctl list | grep governance
   ```

3. **Check logs:**
   ```bash
   tail -50 data/logs/mcp_server_error.log
   ```

4. **Restart:**
   ```bash
   launchctl restart com.unitares.governance-mcp
   ```

### Port already in use

If something else is using port 8767:
```bash
# Find what's using it
lsof -i :8767

# Kill the process if needed
kill -9 <PID>

# Restart governance service
launchctl restart com.unitares.governance-mcp
```

### Logs not updating

Check file permissions:
```bash
ls -la data/logs/
# Should be writable by your user
```

## For Future Updates

If the server code changes:
1. launchd will keep using the old version until restarted
2. Run: `launchctl restart com.unitares.governance-mcp`
3. Or: Unload and reload the plist

## Integration with MCP Clients

**Cursor, Claude Desktop, etc. connect to this same server:**
- All use the same HTTP endpoint: http://127.0.0.1:8767/mcp/
- State is shared across all connected clients
- launchd ensures the server is always available

**This is why "single source of truth" works** - the persistent background service ensures all clients get the same canonical feedback.

---

**Last Updated:** 2026-02-19 (v2.7.0 - 30 tools, Streamable HTTP)
**Service Status:** Active via launchd
**Onboarding Impact:** Simplified - no manual server management needed
