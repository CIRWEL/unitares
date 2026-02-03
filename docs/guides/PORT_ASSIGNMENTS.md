# Port Assignments Reference

## Standard Ports

| Port | Service | Host | Tailscale IP |
|------|---------|------|--------------|
| **8766** | Anima MCP (SSE) | Pi (lumen) | `100.111.166.37` |
| **8767** | Unitares Governance (SSE) | Mac (the-cirwel-group) | `100.96.201.46` |

## Tailscale Network (Recommended)

All communication uses Tailscale - no ngrok, no SSH tunnels, no auth needed.

| Service | URL |
|---------|-----|
| Anima | `http://100.111.166.37:8766/sse` |
| Governance | `http://100.96.201.46:8767/sse` |

Works from any device logged into your Tailscale network (phone, laptop, anywhere).

## Claude Desktop Config

```json
{
  "mcpServers": {
    "anima": {
      "command": "python3",
      "args": ["/Users/cirwel/projects/governance-mcp-v1/src/mcp_server_std.py"],
      "env": {
        "PYTHONPATH": "/Users/cirwel/projects/governance-mcp-v1",
        "UNITARES_STDIO_PROXY_SSE_URL": "http://100.111.166.37:8766/sse"
      }
    },
    "unitares-governance": {
      "command": "python3",
      "args": ["/Users/cirwel/projects/governance-mcp-v1/src/mcp_server_std.py"],
      "env": {
        "PYTHONPATH": "/Users/cirwel/projects/governance-mcp-v1",
        "UNITARES_STDIO_PROXY_SSE_URL": "http://100.96.201.46:8767/sse"
      }
    }
  }
}
```

## Starting Services

```bash
# Governance on Mac
cd /Users/cirwel/projects/governance-mcp-v1
python src/mcp_server_sse.py --port 8767 --host 0.0.0.0

# Anima on Pi (systemd service)
sudo systemctl start anima
```

## Legacy: ngrok Setup (Deprecated)

Previously used ngrok for remote access with basic auth:
- `lumen-anima.ngrok.io` → localhost:8766
- `unitares.ngrok.io` → localhost:8767

**No longer needed** - Tailscale provides secure remote access without extra auth.

The ngrok scripts remain in `scripts/deploy_ngrok.sh` if needed for non-Tailscale access.

## Troubleshooting

### Can't connect to anima (Pi)
```bash
# Check Pi is online
tailscale ping 100.111.166.37

# Check anima service
ssh unitares-anima@lumen.tail76aee6.ts.net "systemctl status anima"
```

### Can't connect to governance (Mac)
```bash
# Check it's running
curl http://100.96.201.46:8767/health

# Start if needed
python src/mcp_server_sse.py --port 8767 --host 0.0.0.0
```

### Claude Desktop shows "not connected"
1. Restart Claude Desktop after config changes
2. Check logs: `tail -f ~/Library/Logs/Claude/mcp-server-*.log`
