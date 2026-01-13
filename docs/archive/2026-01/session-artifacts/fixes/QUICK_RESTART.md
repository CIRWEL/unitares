# Quick Server Restart Guide

**Created:** January 1, 2026  
**Issue:** Tools not loading after code changes  
**Solution:** Clean restart

---

## Quick Restart Commands

### Stop Server

```bash
pkill -f mcp_server_sse.py
```

### Start Server

```bash
cd /Users/cirwel/projects/governance-mcp-v1
source .env 2>/dev/null || true
python3 src/mcp_server_sse.py --port 8765 &
```

### Verify

```bash
# Check health
curl http://localhost:8765/health

# Check tools
curl http://localhost:8765/v1/tools | jq '.tools | length'

# Check call_model
curl http://localhost:8765/v1/tools | jq '.tools[] | select(.function.name == "call_model")'
```

---

## One-Liner Restart

```bash
cd /Users/cirwel/projects/governance-mcp-v1 && pkill -f mcp_server_sse.py && sleep 2 && source .env 2>/dev/null || true && python3 src/mcp_server_sse.py --port 8765 > /tmp/mcp_server.log 2>&1 & sleep 3 && curl -s http://localhost:8765/health | jq -r '.status'
```

---

## After Restart

1. ✅ **Server running** (`curl http://localhost:8765/health`)
2. ✅ **Tools available** (49 tools registered)
3. ✅ **call_model present** (in tools list)
4. ⏳ **Restart Cursor** (to reconnect to server)

---

**Status:** Restart script ready  
**Action:** Run restart commands above

