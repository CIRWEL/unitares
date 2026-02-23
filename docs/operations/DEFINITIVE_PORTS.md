# DEFINITIVE PORT CONFIGURATION

**DO NOT CHANGE THESE PORTS WITHOUT UPDATING THIS DOCUMENT**

## Standard Port Assignments

| Port | Service | Host | Location | Purpose |
|------|---------|------|----------|---------|
| **8766** | Anima MCP | Pi (lumen) | `/etc/systemd/system/anima.service` | Lumen's MCP server |
| **8767** | Unitares Governance | Mac | `src/mcp_server.py` DEFAULT_PORT | Governance MCP server |

## Anima MCP (Pi) - Port 8766

**Service File:** `/etc/systemd/system/anima.service` (on Pi)
```bash
ExecStart=/home/unitares-anima/anima-mcp/.venv/bin/anima --http --host 0.0.0.0 --port 8766
```

**Code Default:** `anima-mcp/src/anima_mcp/server.py`
```python
parser.add_argument("--port", type=int, default=8766, help="HTTP server port (default: 8766)")
```

**URLs:**
- LAN: `http://192.168.1.165:8766/mcp/` (may change via DHCP)
- Tailscale: `http://100.79.215.83:8766/mcp/` (verify with `tailscale status` — IPs can change)
- ngrok: `https://lumen-anima.ngrok.io/mcp/`

**Auth:** OAuth 2.1 enforced only via ngrok host (`lumen-anima.ngrok.io`). LAN and Tailscale are open.

## Unitares Governance (Mac) - Port 8767

**Code Default:** `governance-mcp-v1/src/mcp_server.py` line 1056
```python
DEFAULT_PORT = 8767  # Standard port for unitares governance on Mac (8766 is anima, 8765 was old default)
```

**URL:** `http://localhost:8767/mcp` (or via Tailscale: `http://100.96.201.46:8767/mcp` — verify with `tailscale status`)

## Configuration Files That Must Match

### 1. Governance → Anima Connection
**File:** `governance-mcp-v1/src/mcp_handlers/pi_orchestration.py`
```python
PI_MCP_URL = os.environ.get("PI_MCP_URL", "http://100.79.215.83:8766/mcp/")
```
**MUST BE:** Port **8766** (matches anima service). IP set via `PI_MCP_URL` env var — update if Tailscale IP changes (`tailscale status`).

### 2. Anima Service File (on Pi)
**File:** `/etc/systemd/system/anima.service` (on Pi)
```bash
ExecStart=... --port 8766
```
**MUST BE:** Port **8766**

### 3. Governance Server Default
**File:** `governance-mcp-v1/src/mcp_server.py` line 1056
```python
DEFAULT_PORT = 8767
```
**MUST BE:** Port **8767**

## Why These Ports?

- **8766** = Anima (Pi) - Reserved for Lumen's MCP server
- **8767** = Governance (Mac) - Standard port, avoids conflicts
- **8765** = DEPRECATED - Old default, caused conflicts, DO NOT USE

## Verification Commands

```bash
# Get current Tailscale IPs
tailscale status

# Check governance on Mac
lsof -i :8767 | grep python

# Test connections (verify IPs with `tailscale status` first)
curl http://localhost:8767/health                    # governance (local)
curl http://100.79.215.83:8766/health                # anima (via Tailscale)
curl https://lumen-anima.ngrok.io/health             # anima (via ngrok)
```

## If Ports Don't Match

1. **Check actual running service:**
   ```bash
   # On Pi
   systemctl status anima
   ps aux | grep anima | grep --port
   
   # On Mac
   lsof -i :8767
   ```

2. **Update configuration files** (all of them)
3. **Restart services**
4. **Update this document**

## DO NOT

- ❌ Change ports without updating ALL references
- ❌ Use port 8765 (deprecated)
- ❌ Guess ports - check actual running services
- ❌ Change one file without changing others
