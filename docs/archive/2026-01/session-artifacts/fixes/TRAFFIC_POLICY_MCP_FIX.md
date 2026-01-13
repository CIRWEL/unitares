# Traffic Policy Fix for MCP + AI Gateway

**Created:** January 1, 2026  
**Status:** Fixing - Traffic Policy intercepts all requests

---

## Problem

**Issue:** Traffic Policy on `unitares.ngrok.io` applies AI Gateway to **ALL requests**, including MCP requests to `/mcp`.

**Result:** 
- MCP requests get routed as AI model calls → fails
- Error: "No API key for provider 'anthropic'"

**Root Cause:** The Traffic Policy doesn't have a `match` condition, so it applies to every request.

---

## Solution

**Update Traffic Policy to:**
1. **Apply AI Gateway only to AI endpoints** (`/v1/chat/completions`, etc.)
2. **Pass through other requests** (`/mcp`, `/health`, etc.) to backend

---

## Fixed Traffic Policy

**Copy this YAML to ngrok dashboard:**

```yaml
on_http_request:
  # Only apply AI Gateway to AI endpoints
  - match: |
      req.URL.Path == "/v1/chat/completions" || 
      req.URL.Path == "/v1/completions" ||
      req.URL.Path == "/v1/embeddings"
    actions:
      - type: ai-gateway
        config:
          providers:
            - id: "huggingface"
              base_url: "https://router.huggingface.co/v1"
              api_keys:
                - value: "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"
              models:
                - id: "deepseek-ai/DeepSeek-R1"
                - id: "deepseek-ai/DeepSeek-R1:fastest"
                - id: "openai/gpt-oss-120b"
  # Default: pass through all other requests to backend
  - actions:
      - type: proxy
        config:
          backend_url: "http://localhost:8765"
```

---

## Steps to Fix

**Step 1: Open ngrok Dashboard**

1. Go to: https://dashboard.ngrok.com
2. Navigate to: **Endpoints & Traffic Policy**
3. Click on: `https://unitares.ngrok.io`

**Step 2: Edit Traffic Policy**

1. Click **"Edit Traffic Policy"** or **"Configure"**
2. Replace existing YAML with the fixed version above
3. Click **"Save"**

**Step 3: Verify**

```bash
# Test MCP endpoint (should work now)
curl https://unitares.ngrok.io/mcp

# Test AI endpoint (should route to HF)
curl -X POST https://unitares.ngrok.io/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-ai/DeepSeek-R1","messages":[{"role":"user","content":"test"}]}'
```

---

## How It Works

**Before (Broken):**
```
All requests → AI Gateway → Fails for non-AI requests
```

**After (Fixed):**
```
/v1/chat/completions → AI Gateway → Hugging Face ✅
/mcp → Proxy → localhost:8765 → MCP Server ✅
/health → Proxy → localhost:8765 → MCP Server ✅
```

---

## Alternative: Remove Traffic Policy

**If you don't need AI Gateway routing:**

1. Remove Traffic Policy entirely
2. All requests pass through to `localhost:8765`
3. Use `call_model` tool to route AI calls directly

**Pros:**
- ✅ Simpler configuration
- ✅ MCP works immediately
- ✅ AI calls handled by `call_model` tool

**Cons:**
- ❌ No automatic failover/cost optimization at gateway level
- ❌ AI calls go directly from server (still works)

---

## Current Setup

**ngrok Tunnel:**
- `ngrok http --url=unitares.ngrok.io --pooling-enabled 8765`
- Proxies `unitares.ngrok.io` → `localhost:8765`

**Traffic Policy:**
- Currently: Applies AI Gateway to ALL requests ❌
- Should be: AI Gateway only for AI endpoints, proxy for rest ✅

---

## Verification

**After updating Traffic Policy:**

1. **Test MCP:**
   ```bash
   curl https://unitares.ngrok.io/mcp
   ```
   Should return MCP server response (not AI Gateway error)

2. **Test Health:**
   ```bash
   curl https://unitares.ngrok.io/health
   ```
   Should return `{"status":"ok",...}`

3. **Test AI (via call_model tool):**
   - Use `call_model` tool in MCP client
   - Should route to Hugging Face via gateway

4. **Restart Cursor:**
   - Quit Cursor (Cmd+Q)
   - Wait 5 seconds
   - Reopen Cursor
   - MCP tools should load ✅

---

**Status:** Fixing Traffic Policy to allow MCP + AI Gateway  
**Action:** Update Traffic Policy in ngrok dashboard with conditional routing

