# Fix: MCP Tools Not Loading

**Created:** January 1, 2026  
**Issue:** Tools won't load in MCP client  
**Status:** Diagnostic Guide

---

## Current Status

✅ **Server:** Running (port 8765)  
✅ **Tools Registered:** 49 tools (including `call_model`)  
✅ **REST API:** Working (`/v1/tools` returns tools)  
❓ **MCP Client:** May not be connecting

---

## Verification

**Server has tools:**
```bash
curl http://localhost:8765/v1/tools | jq '.tools | length'
# Returns: 49
```

**call_model exists:**
```bash
curl http://localhost:8765/v1/tools | jq '.tools[] | select(.function.name == "call_model")'
# Returns: call_model tool definition
```

---

## Possible Issues

### Issue 1: MCP Client Not Connected

**Problem:** Cursor/Claude Desktop not connected to MCP server

**Fix:**
1. **Check MCP configuration** in Cursor settings
2. **Verify server URL:** `http://localhost:8765/sse` or `http://localhost:8765/mcp`
3. **Restart Cursor** after config changes
4. **Check connection status:** Look for MCP connection indicator

---

### Issue 2: Wrong Transport Endpoint

**Problem:** Client using wrong endpoint

**Available endpoints:**
- **SSE (legacy):** `http://localhost:8765/sse`
- **Streamable HTTP (new):** `http://localhost:8765/mcp`

**Fix:** Try both endpoints in MCP config

---

### Issue 3: Server Not Exposing Tools Correctly

**Problem:** Tools registered but not exposed via MCP protocol

**Check:**
```bash
# Test MCP protocol endpoint
curl http://localhost:8765/sse?probe=true
```

**Expected:** SSE connection test response

---

### Issue 4: Cursor MCP Configuration

**Problem:** Cursor MCP config incorrect

**Check Cursor settings:**
```json
{
  "mcpServers": {
    "unitares-governance": {
      "url": "http://localhost:8765/sse",
      "transport": "sse"
    }
  }
}
```

**Or for Streamable HTTP:**
```json
{
  "mcpServers": {
    "unitares-governance": {
      "url": "http://localhost:8765/mcp",
      "transport": "streamable-http"
    }
  }
}
```

---

## Step-by-Step Fix

### Step 1: Verify Server is Running

```bash
curl http://localhost:8765/health
```

**Expected:** `{"status":"ok",...}`

---

### Step 2: Check Tools Available

```bash
curl http://localhost:8765/v1/tools | jq '.tools | length'
```

**Expected:** `49` (or similar number)

---

### Step 3: Test MCP Endpoint

**SSE endpoint:**
```bash
curl http://localhost:8765/sse?probe=true
```

**Streamable HTTP endpoint:**
```bash
curl -X POST http://localhost:8765/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

---

### Step 4: Check Cursor MCP Config

**In Cursor:**
1. Settings → MCP Servers
2. Verify `unitares-governance` is configured
3. Check URL: `http://localhost:8765/sse` or `/mcp`
4. Restart Cursor

---

### Step 5: Check Cursor Logs

**Look for MCP connection errors:**
- Cursor → Help → Show Logs
- Search for "MCP" or "unitares"
- Look for connection errors

---

## Quick Test: Direct Tool Call

**Test if tools work via REST API:**

```bash
curl -X POST http://localhost:8765/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "list_tools",
    "arguments": {}
  }'
```

**Expected:** List of tools returned

---

## Common MCP Client Issues

### Cursor Not Showing Tools

**Possible causes:**
1. MCP server not configured in Cursor
2. Wrong endpoint URL
3. Server not running when Cursor started
4. Connection timeout

**Fix:**
1. Add MCP server config
2. Use correct endpoint (`/sse` or `/mcp`)
3. Restart Cursor after server starts
4. Check Cursor logs for errors

---

### Tools Appear Then Disappear

**Possible causes:**
1. Server restarting
2. Connection dropping
3. Tool registration failing

**Fix:**
1. Check server stability
2. Monitor connection status
3. Check server logs for errors

---

## Verification Checklist

- [ ] Server running (`curl http://localhost:8765/health`)
- [ ] Tools available (`curl http://localhost:8765/v1/tools`)
- [ ] `call_model` in tools list
- [ ] MCP endpoint accessible (`/sse` or `/mcp`)
- [ ] Cursor MCP config correct
- [ ] Cursor restarted after config
- [ ] No errors in Cursor logs

---

## Next Steps

1. **Verify server is running** (already confirmed ✅)
2. **Check Cursor MCP configuration** (user needs to verify)
3. **Test MCP endpoint** (try `/sse` and `/mcp`)
4. **Restart Cursor** (after config changes)
5. **Check Cursor logs** (for connection errors)

---

**Status:** Server OK, tools registered  
**Issue:** Likely MCP client connection/config  
**Next:** Check Cursor MCP configuration

