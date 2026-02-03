# Central Operator Agent - Usage Guide

**Created:** January 26, 2026  
**Status:** Phase 1-2 Implementation  
**Script:** `scripts/operator_agent.py`

---

## Quick Start

### Prerequisites

1. **MCP Server Running:**
   ```bash
   python src/mcp_server_sse.py --port 8765
   ```

2. **Environment Setup:**
   ```bash
   cd governance-mcp-v1
   # No additional setup needed - script sets GOVERNANCE_TOOL_MODE automatically
   ```

### Test Run (Once)

Run operator checks once to verify setup:

```bash
python3 scripts/operator_agent.py --once
```

**Ngrok example (SSE + basic auth):**
```bash
MCP_SERVER_URL=https://USER:PASS@your-tunnel.ngrok.io/sse \
python3 scripts/operator_agent.py --once
```

**Expected output:**
```
🚀 Central Operator Agent - Phase 1 (Read-Only)
   MCP Server: http://127.0.0.1:8765/sse
   Tool Mode: operator_readonly

✅ Operator identity configured: Operator
[2026-01-26T12:00:00] Checking for stuck agents...
✅ No stuck agents detected
[2026-01-26T12:00:01] Checking system health...
✅ Health check complete: healthy
[2026-01-26T12:00:02] Checking knowledge graph lifecycle...
✅ KG check complete: KG lifecycle stats: 5 open, 12 resolved, 3 archived

✅ Operator checks complete
```

### Daemon Mode (Production)

Run operator as background daemon:

```bash
# Run in foreground (for testing)
python3 scripts/operator_agent.py --daemon

# Phase 2 recovery enabled (operator_resume_agent)
python3 scripts/operator_agent.py --daemon --enable-recovery

# Run in background
nohup python3 scripts/operator_agent.py --daemon > operator.log 2>&1 &

# Or use systemd/service manager (see below)
```

---

## Configuration

### Environment Variables

```bash
# MCP server URL (default: http://127.0.0.1:8765/sse)
export MCP_SERVER_URL=http://127.0.0.1:8765/sse

# Ngrok (SSE + basic auth)
# export MCP_SERVER_URL=https://USER:PASS@your-tunnel.ngrok.io/sse

# Operator label (default: Operator)
export OPERATOR_LABEL=Operator

# Check intervals (seconds)
export OPERATOR_STUCK_INTERVAL=300      # 5 minutes
export OPERATOR_HEALTH_INTERVAL=3600   # 1 hour
export OPERATOR_KG_INTERVAL=86400      # 24 hours

# Enable Phase 2 recovery (default: 0)
export OPERATOR_ENABLE_RECOVERY=1
```

### Command-Line Options

```bash
python3 scripts/operator_agent.py \
  --url http://127.0.0.1:8765/sse \
  --label "Operator" \
  --stuck-interval 300 \
  --health-interval 3600 \
  --kg-interval 86400 \
  --enable-recovery \
  --daemon
```

---

## What It Does

### Phase 1: Read-Only Observability

The operator performs three types of checks:

1. **Stuck Agent Detection** (every 5 minutes)
   - Calls `detect_stuck_agents` with default thresholds
   - Logs findings to knowledge graph
   - Tags: `["operator", "observation", "stuck-detection"]`

2. **System Health Check** (every hour)
   - Calls `health_check`, `get_workspace_health`, `get_telemetry_metrics`
   - Logs summary to knowledge graph
   - Tags: `["operator", "health-check", "<status>"]`

3. **Knowledge Graph Lifecycle** (daily)
   - Calls `get_lifecycle_stats`
   - Logs open/resolved/archived counts
   - Tags: `["operator", "kg-report", "lifecycle"]`

### Knowledge Graph Entries

All operator observations are logged to the knowledge graph with:
- **Discovery type:** `observation`
- **Tags:** Include `["operator"]` plus specific tags
- **Severity:** `info` (normal) or `warning` (issues detected)
- **Metadata:** Includes full tool responses and timestamps

**Query operator logs:**
```bash
python3 scripts/mcp_agent.py search_knowledge_graph \
  --json '{"query": "operator observations", "tags": ["operator"]}'
```

### Phase 2: Recovery Actions (Optional)

When `--enable-recovery` is set, the operator will attempt automated recovery:
- Calls `check_recovery_options` to verify safety.
- Calls `operator_resume_agent` if eligible.
- Honors hard safety limits (void/risk/coherence).

---

## Running as a Service

### systemd (Linux)

Create `/etc/systemd/system/operator-agent.service`:

```ini
[Unit]
Description=Central Operator Agent (Phase 1)
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/governance-mcp-v1
Environment="MCP_SERVER_URL=http://127.0.0.1:8765/sse"
Environment="OPERATOR_LABEL=Operator"
ExecStart=/usr/bin/python3 scripts/operator_agent.py --daemon
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl enable operator-agent
sudo systemctl start operator-agent
sudo systemctl status operator-agent
```

### launchd (macOS)

Create `~/Library/LaunchAgents/com.unitares.operator-agent.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.unitares.operator-agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/governance-mcp-v1/scripts/operator_agent.py</string>
        <string>--daemon</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/governance-mcp-v1</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>MCP_SERVER_URL</key>
        <string>http://127.0.0.1:8765/sse</string>
        <key>OPERATOR_LABEL</key>
        <string>Operator</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/operator-agent.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/operator-agent.error.log</string>
</dict>
</plist>
```

**Load and start:**
```bash
launchctl load ~/Library/LaunchAgents/com.unitares.operator-agent.plist
launchctl start com.unitares.operator-agent
```

---

## Monitoring

### Check Operator Logs

**If running in foreground:**
- Logs print to stdout/stderr

**If running as daemon:**
```bash
# Check systemd logs
sudo journalctl -u operator-agent -f

# Check launchd logs
tail -f /tmp/operator-agent.log
```

### Verify Operator Activity

Check knowledge graph for operator entries:

```bash
# Recent operator observations
python3 scripts/mcp_agent.py search_knowledge_graph \
  --json '{
    "query": "operator observations",
    "tags": ["operator"],
    "limit": 10
  }'

# Stuck agent detections
python3 scripts/mcp_agent.py search_knowledge_graph \
  --json '{
    "query": "stuck agents",
    "tags": ["operator", "stuck-detection"],
    "limit": 10
  }'
```

### Health Check

Verify operator is running and can connect:

```bash
# Test connection
python3 scripts/operator_agent.py --once

# Check if MCP server is accessible
curl http://127.0.0.1:8765/health
```

---

## Troubleshooting

### Operator Can't Connect

**Error:** `Failed to connect to MCP server`

**Solutions:**
1. Verify MCP server is running: `curl http://127.0.0.1:8765/health`
2. Check URL: `--url http://127.0.0.1:8765/sse`
3. Check firewall/network settings

### Operator Identity Not Created

**Error:** `Failed to configure operator identity`

**Solutions:**
1. Verify `onboard` tool is available (check tool mode)
2. Check MCP server logs for errors
3. Verify `GOVERNANCE_TOOL_MODE=operator_readonly` is set (script sets this automatically)

### No Observations Logged

**Symptoms:** Operator runs but no KG entries

**Solutions:**
1. Check if `store_knowledge_graph` tool is available in operator mode
2. Verify operator has write access to KG (should be read-only, but `store_knowledge_graph` is allowed)
3. Check MCP server logs for tool call errors

### High CPU/Memory Usage

**Symptoms:** Operator consumes too many resources

**Solutions:**
1. Increase check intervals: `--stuck-interval 600` (10 minutes)
2. Reduce check frequency: `--health-interval 7200` (2 hours)
3. Check for connection leaks (should reconnect each iteration)

---

## Next Steps

**Phase 1 Complete:** ✅ Read-only observability

**Phase 2:** Add lifecycle tools (`mark_response_complete`, `request_dialectic_review`)

**Phase 3:** Add safe recovery (`direct_resume_if_safe` with session binding bypass)

**Phase 4:** Add KG maintenance (auto-tagging, summarization, archival)

See [CENTRAL_OPERATOR_AGENT_IMPLEMENTATION.md](./CENTRAL_OPERATOR_AGENT_IMPLEMENTATION.md) for implementation checklist.

---

## References

- [Design Spec](./CENTRAL_OPERATOR_AGENT.md)
- [Implementation Checklist](./CENTRAL_OPERATOR_AGENT_IMPLEMENTATION.md)
- [Runbook](./CENTRAL_OPERATOR_AGENT_RUNBOOK.md)
- [Review](./CENTRAL_OPERATOR_AGENT_REVIEW.md)
