# Cursor MCP Connection Troubleshooting

**Created:** January 1, 2026  
**Issue:** Server running but Cursor not loading tools  
**Status:** Server verified working ✅

---

## ✅ Server Status: WORKING

**Verified:**
- ✅ Server running on port 8765
- ✅ 49 tools registered
- ✅ `call_model` tool present
- ✅ SSE endpoint responding (`/sse?probe=true`)
- ✅ Health endpoint working (`/health`)

**Server logs show:**
```
[UNITARES] __main__ - INFO - [AUTO_REGISTER] Registered 49 tools with typed signatures
[UNITARES] __main__ - INFO - Starting SSE server on http://127.0.0.1:8765/sse
```

---

## 🔍 Cursor MCP Configuration

### Step 1: Verify Cursor Config Location

**Cursor stores MCP config at:**
```
~/Library/Application Support/Cursor/User/globalStorage/mcp.json
```

**Expected config:**
```json
{
  "mcpServers": {
    "governance-monitor-v1": {
      "url": "http://127.0.0.1:8765/sse"
    }
  }
}
```

---

### Step 2: Check if Config Exists

```bash
cat ~/Library/Application\ Support/Cursor/User/globalStorage/mcp.json
```

**If file doesn't exist:**
1. Create the directory:
   ```bash
   mkdir -p ~/Library/Application\ Support/Cursor/User/globalStorage
   ```

2. Copy config from project:
   ```bash
   cp /Users/cirwel/projects/governance-mcp-v1/config/mcp-config-cursor.json \
      ~/Library/Application\ Support/Cursor/User/globalStorage/mcp.json
   ```

---

### Step 3: Restart Cursor

**After updating config:**
1. **Quit Cursor completely** (Cmd+Q)
2. **Wait 5 seconds**
3. **Reopen Cursor**
4. **Check MCP status** (should show connected)

---

## 🔧 Troubleshooting Steps

### Issue 1: Config File Missing

**Symptom:** Cursor doesn't see MCP server

**Fix:**
```bash
# Create config
mkdir -p ~/Library/Application\ Support/Cursor/User/globalStorage
cat > ~/Library/Application\ Support/Cursor/User/globalStorage/mcp.json << 'EOF'
{
  "mcpServers": {
    "governance-monitor-v1": {
      "url": "http://127.0.0.1:8765/sse"
    }
  }
}
EOF

# Restart Cursor
```

---

### Issue 2: Server Not Running

**Symptom:** Connection refused

**Fix:**
```bash
cd /Users/cirwel/projects/governance-mcp-v1

# Start server
source .env 2>/dev/null || true
python3 src/mcp_server_sse.py --port 8765 &

# Verify
curl http://localhost:8765/health
```

---

### Issue 3: Port Conflict

**Symptom:** Port already in use

**Fix:**
```bash
# Kill existing server
pkill -f mcp_server_sse.py

# Or use different port
python3 src/mcp_server_sse.py --port 8766
# Then update Cursor config to use port 8766
```

---

### Issue 4: Cursor Cache

**Symptom:** Config updated but Cursor still uses old config

**Fix:**
1. **Quit Cursor** (Cmd+Q)
2. **Clear cache:**
   ```bash
   rm -rf ~/Library/Application\ Support/Cursor/Cache/*
   ```
3. **Restart Cursor**

---

## 🧪 Verification Commands

### Test Server Directly

```bash
# Health check
curl http://localhost:8765/health

# List tools
curl http://localhost:8765/v1/tools | jq '.tools | length'

# Check call_model
curl http://localhost:8765/v1/tools | jq '.tools[] | select(.function.name == "call_model")'

# Test SSE endpoint
curl 'http://localhost:8765/sse?probe=true'
```

---

### Test Cursor Connection

**In Cursor:**
1. Open Command Palette (Cmd+Shift+P)
2. Search for "MCP" or "Model Context Protocol"
3. Check if `governance-monitor-v1` appears
4. Check connection status

---

## 📋 Checklist

**Before reporting issue:**

- [ ] Server running (`curl http://localhost:8765/health`)
- [ ] Tools available (`curl http://localhost:8765/v1/tools`)
- [ ] Config file exists (`cat ~/Library/Application\ Support/Cursor/User/globalStorage/mcp.json`)
- [ ] Config URL matches server (`http://127.0.0.1:8765/sse`)
- [ ] Cursor restarted after config change
- [ ] No port conflicts (`lsof -i :8765`)

---

## 🚨 Common Errors

### Error: "Connection refused"

**Cause:** Server not running

**Fix:**
```bash
cd /Users/cirwel/projects/governance-mcp-v1
python3 src/mcp_server_sse.py --port 8765 &
```

---

### Error: "Timeout"

**Cause:** Server slow to respond or locked

**Fix:**
```bash
# Kill and restart
pkill -f mcp_server_sse.py
rm -f data/.mcp_server_sse.lock
python3 src/mcp_server_sse.py --port 8765 &
```

---

### Error: "Tools not found"

**Cause:** Server didn't load tools properly

**Fix:**
```bash
# Check server logs
tail -50 /tmp/mcp_startup.log

# Restart with fresh lock
pkill -f mcp_server_sse.py
rm -f data/.mcp_server_sse.lock data/.mcp_server_sse.pid
python3 src/mcp_server_sse.py --port 8765 &
```

---

## 📝 Next Steps

1. ✅ **Verify server** (commands above)
2. ✅ **Check Cursor config** (create if missing)
3. ✅ **Restart Cursor** (full quit and reopen)
4. ✅ **Check MCP status** (in Cursor UI)
5. ✅ **Test tool** (try calling `call_model`)

---

**Status:** Server working, checking Cursor config  
**Action:** Verify Cursor MCP config exists and restart Cursor

