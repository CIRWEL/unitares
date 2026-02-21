# Port Configuration - Why It Keeps Changing

**Created:** February 3, 2026  
**Purpose:** Document port assignments and prevent configuration drift

---

## The Problem

The port configuration kept getting altered because there were **multiple conflicting sources**:

1. **Code default**: `DEFAULT_PORT = 8765` (old)
2. **deploy_ngrok.sh**: Expected `8767` 
3. **start_unitares.sh**: Hardcoded `8765`
4. **Plist**: Was `8765`, but ngrok configured for `8767`
5. **Manual starts**: Different ports used in different contexts

**Result:** Port mismatch → Server runs on wrong port → MCP tools don't work

---

## Standard Port Assignments

| Port | Service | Host | Purpose |
|------|---------|------|---------|
| **8767** | Unitares Governance | Mac | **Standard port** (use this!) |
| **8766** | Anima MCP | Pi | Tunneled from Pi |
| **8765** | ~~Old default~~ | ~~Mac~~ | **Deprecated** - caused conflicts |

---

## Current Configuration (Standardized)

### ✅ Code Default
```python
# src/mcp_server.py
DEFAULT_PORT = 8767  # Standard port for unitares governance
```

### ✅ Launchd Plist
```xml
<!-- ~/Library/LaunchAgents/com.unitares.governance-mcp.plist -->
<string>--port</string>
<string>8767</string>
```

### ✅ Start Scripts
```bash
# scripts/start_unitares.sh
python3 src/mcp_server.py --port 8767

# scripts/deploy_ngrok.sh
MCP_PORT="${MCP_PORT:-8767}"  # Defaults to 8767
```

### ✅ Ngrok Configuration
```bash
# ngrok forwards your-domain.ngrok.io → localhost:8767
ngrok http 8767 --url=your-domain.ngrok.io
```

---

## Why Port 8767?

**From `deploy_ngrok.sh` comments:**
```
# NOTE: 8767 is the standard port for unitares governance on Mac
#       8766 is used by anima (tunneled from Pi)
#       8765 was the old default but caused conflicts
```

**Reasons:**
- ✅ **8766** reserved for anima (Pi tunnel)
- ✅ **8767** avoids conflicts
- ✅ **8765** caused port conflicts (deprecated)

---

## How It Gets Altered

### 1. **Manual Script Execution**

If someone runs `start_unitares.sh` with old hardcoded port:
```bash
# OLD (wrong):
python3 src/mcp_server.py --port 8765

# NEW (correct):
python3 src/mcp_server.py --port 8767
```

### 2. **Code Default Override**

If code default doesn't match scripts:
```python
# OLD (wrong):
DEFAULT_PORT = 8765

# NEW (correct):
DEFAULT_PORT = 8767
```

### 3. **Plist Mismatch**

If plist port doesn't match what's actually running:
```xml
<!-- OLD (wrong): -->
<string>8765</string>

<!-- NEW (correct): -->
<string>8767</string>
```

### 4. **Ngrok Configuration**

If ngrok forwards wrong port:
```bash
# OLD (wrong):
ngrok http 8765

# NEW (correct):
ngrok http 8767
```

---

## Prevention: Single Source of Truth

**All configurations now use port 8767:**

1. ✅ **Code default** → `8767`
2. ✅ **Plist** → `8767`
3. ✅ **Scripts** → `8767`
4. ✅ **Ngrok** → `8767`
5. ✅ **Documentation** → `8767`

**If you need to change the port:**
1. Update `DEFAULT_PORT` in `src/mcp_server.py`
2. Update plist: `config/com.unitares.governance-mcp.plist`
3. Update scripts: `scripts/start_unitares.sh`, `scripts/deploy_ngrok.sh`
4. Update ngrok command
5. Reload launchd: `launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist && launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist`

---

## Verification

**Check what port is actually running:**
```bash
# Check what's listening
lsof -i :8767

# Check health endpoint
curl http://localhost:8767/health

# Check plist configuration
cat ~/Library/LaunchAgents/com.unitares.governance-mcp.plist | grep -A 1 port
```

**If port mismatch detected:**
1. Stop server: `launchctl stop com.unitares.governance-mcp`
2. Update plist to match code default
3. Reload: `launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist`
4. Verify: `curl http://localhost:8767/health`

---

## Summary

**Root cause:** Multiple configuration sources with different ports  
**Solution:** Standardized everything to port **8767**  
**Prevention:** Single source of truth - code default matches all configs

**Current status:** ✅ All configurations aligned to port 8767

---

*Last updated: February 3, 2026*
