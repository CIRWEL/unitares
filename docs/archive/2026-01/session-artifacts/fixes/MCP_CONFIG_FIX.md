# MCP Configuration Fix

**Created:** January 1, 2026  
**Status:** Fixed - ngrok gateway was misconfigured

---

## Problem

**Issue:** MCP config points to `https://unitares.ngrok.io/mcp`, but that endpoint is configured as an **AI Gateway** (for model inference), not a reverse proxy to the MCP server.

**Error:** Gateway returns HTML error: "All providers failed: API key selection failed: No API key for provider 'anthropic'"

**Root Cause:** The ngrok endpoint `unitares.ngrok.io` has a Traffic Policy configured for AI Gateway, which routes requests to AI providers (Hugging Face, Gemini, etc.), not to the local MCP server.

---

## Solution

**Option 1: Use localhost (Recommended)**

Update `.cursor/mcp.json` to point to local server:

```json
{
    "mcpServers": {
        "unitares-governance": {
            "type": "http",
            "url": "http://127.0.0.1:8765/mcp"
        }
    }
}
```

**Pros:**
- ✅ Works immediately
- ✅ No ngrok configuration needed
- ✅ Faster (no network hop)
- ✅ More secure (local only)

**Cons:**
- ❌ Only works on local machine
- ❌ Requires server running locally

---

**Option 2: Create separate ngrok endpoint for MCP**

Create a **new** ngrok endpoint (different from AI Gateway) that proxies to localhost:

1. **Create new endpoint in ngrok:**
   ```bash
   ngrok http 8765 --domain=mcp-unitares.ngrok.io
   ```

2. **Update MCP config:**
   ```json
   {
       "mcpServers": {
           "unitares-governance": {
               "type": "http",
               "url": "https://mcp-unitares.ngrok.io/mcp"
           }
       }
   }
   ```

**Pros:**
- ✅ Works from anywhere
- ✅ Can share with others
- ✅ Separate from AI Gateway

**Cons:**
- ❌ Requires ngrok account
- ❌ Requires separate endpoint
- ❌ More complex setup

---

## Current Configuration

**AI Gateway Endpoint:**
- `https://unitares.ngrok.io` → AI Gateway (for model inference)
- Traffic Policy: Routes to Hugging Face, Gemini, etc.
- **NOT for MCP server**

**MCP Server Endpoint:**
- `http://127.0.0.1:8765/mcp` → Local MCP server
- Streamable HTTP transport
- **Use this for Cursor MCP config**

---

## Fix Steps

**Step 1: Update MCP config**

Edit `~/.cursor/mcp.json`:

```json
{
    "mcpServers": {
        "unitares-governance": {
            "type": "http",
            "url": "http://127.0.0.1:8765/mcp"
        }
    }
}
```

**Step 2: Verify server is running**

```bash
curl http://127.0.0.1:8765/health
```

**Step 3: Restart Cursor**

1. Quit Cursor completely (Cmd+Q)
2. Wait 5 seconds
3. Reopen Cursor
4. Check MCP tools load

---

## Verification

**Test local endpoint:**

```bash
curl -X POST http://127.0.0.1:8765/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

**Expected:** JSON response with tool list

---

## Why This Happened

**Timeline:**
1. ✅ MCP config originally worked (probably pointed to localhost or different endpoint)
2. ✅ Added AI Gateway configuration (`unitares.ngrok.io` with Traffic Policy)
3. ❌ AI Gateway Traffic Policy routes ALL requests to AI providers
4. ❌ MCP requests to `/mcp` get routed as AI model calls → fails

**Key Insight:** 
- **AI Gateway** = Routes requests to AI providers (Hugging Face, Gemini)
- **Reverse Proxy** = Routes requests to local server (MCP server)

These are **different use cases** and need **separate endpoints**.

---

## Architecture

**Current Setup:**

```
┌─────────────┐
│   Cursor    │
└──────┬──────┘
       │
       │ MCP requests
       ▼
┌─────────────────────┐
│  Local MCP Server    │
│  http://127.0.0.1    │
│  :8765/mcp           │
└─────────────────────┘

┌─────────────┐
│  call_model │
└──────┬──────┘
       │
       │ AI requests
       ▼
┌─────────────────────┐
│  ngrok AI Gateway   │
│  unitares.ngrok.io  │
│  (Traffic Policy)   │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│  Hugging Face /     │
│  Gemini / Ollama    │
└─────────────────────┘
```

**Two separate paths:**
1. **MCP → Local Server** (for tools, identity, etc.)
2. **call_model → AI Gateway → Providers** (for model inference)

---

## Next Steps

1. ✅ **Update MCP config** to `http://127.0.0.1:8765/mcp`
2. ✅ **Restart Cursor**
3. ✅ **Verify tools load**
4. ✅ **Test `call_model` tool** (uses AI Gateway separately)

---

**Status:** Fixed - use localhost for MCP, ngrok gateway for AI  
**Action:** Update `.cursor/mcp.json` to point to localhost

