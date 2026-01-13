# Restart Server After Code Changes

**Created:** January 1, 2026  
**Issue:** Tools stopped working after code changes  
**Solution:** Server needs restart to pick up new tools

---

## Problem

**After adding `call_model` tool:**
- Code changes made ✅
- Tool registered ✅
- Server still running old code ❌
- Tools not appearing in client ❌

**Cause:** Server needs restart to load new code.

---

## Solution: Restart Server

### Step 1: Stop Server

```bash
pkill -f mcp_server_sse.py
```

**Or find and kill specific process:**
```bash
ps aux | grep mcp_server_sse.py
kill <PID>
```

---

### Step 2: Start Server Fresh

```bash
cd /Users/cirwel/projects/governance-mcp-v1

# Load environment
source .env 2>/dev/null || true

# Start server
python src/mcp_server_sse.py --port 8765
```

**Or use startup script:**
```bash
./scripts/start_with_deps.sh
```

---

### Step 3: Verify Tools Loaded

```bash
# Check health
curl http://localhost:8765/health

# Check tools
curl http://localhost:8765/v1/tools | jq '.tools | length'

# Check call_model exists
curl http://localhost:8765/v1/tools | jq '.tools[] | select(.function.name == "call_model")'
```

---

## Quick Restart Script

**Create `restart_server.sh`:**

```bash
#!/bin/bash
cd /Users/cirwel/projects/governance-mcp-v1

echo "🛑 Stopping server..."
pkill -f mcp_server_sse.py
sleep 2

echo "🚀 Starting server..."
source .env 2>/dev/null || true
python src/mcp_server_sse.py --port 8765 &

sleep 3

echo "✅ Checking server..."
curl -s http://localhost:8765/health | jq -r '.status' && echo "Server is running!" || echo "Server failed to start"
```

**Make executable:**
```bash
chmod +x restart_server.sh
./restart_server.sh
```

---

## Why Restart is Needed

**Python modules are cached:**
- Imported modules stay in memory
- New code changes not loaded until restart
- Tool registration happens at startup

**After code changes:**
1. ✅ Code updated
2. ✅ Imports work (when tested)
3. ❌ Running server still has old code
4. ✅ Restart loads new code

---

## Verification Checklist

After restart:

- [ ] Server responds (`curl http://localhost:8765/health`)
- [ ] Tools available (`curl http://localhost:8765/v1/tools`)
- [ ] `call_model` in tools list
- [ ] No import errors in logs
- [ ] MCP client can see tools

---

## Common Issues After Restart

### Issue 1: Port Already in Use

**Error:** `Address already in use`

**Fix:**
```bash
# Kill process using port
lsof -ti:8765 | xargs kill -9

# Or use different port
python src/mcp_server_sse.py --port 8766
```

---

### Issue 2: Import Errors

**Error:** `ModuleNotFoundError` or `ImportError`

**Fix:**
```bash
# Check imports
python3 -c "from src.mcp_handlers.model_inference import handle_call_model"

# Install dependencies
pip install -r requirements.txt
```

---

### Issue 3: Environment Variables Not Loaded

**Error:** Missing `HF_TOKEN` or `NGROK_AI_ENDPOINT`

**Fix:**
```bash
# Load from .env
source .env

# Or set manually
export HF_TOKEN=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
export NGROK_AI_ENDPOINT=https://unitares.ngrok.io
```

---

## Auto-Restart on Code Changes

**For development, use a file watcher:**

```bash
# Install watchdog
pip install watchdog

# Watch for changes and restart
watchdog --patterns="*.py" --recursive --command='pkill -f mcp_server_sse.py && sleep 1 && python src/mcp_server_sse.py --port 8765' src/
```

---

## Next Steps

1. ✅ **Restart server** (to load new code)
2. ✅ **Verify tools** (check `call_model` appears)
3. ✅ **Test tool** (try calling `call_model`)
4. ✅ **Check client** (Cursor should see tools)

---

**Status:** Server restart needed  
**Action:** Restart server to pick up `call_model` tool

