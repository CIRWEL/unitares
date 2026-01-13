# Remove Traffic Policy - Quick Fix

**Created:** January 1, 2026  
**Status:** Removing AI Gateway Traffic Policy to restore MCP

---

## Problem

AI Gateway Traffic Policy is intercepting ALL requests (including MCP), breaking the server.

---

## Solution: Remove Traffic Policy

**Step 1: Open ngrok Dashboard**

1. Go to: https://dashboard.ngrok.com/endpoints
2. Find endpoint: `https://unitares.ngrok.io`
3. Click on it

**Step 2: Remove Traffic Policy**

1. Look for **"Traffic Policy"** section
2. Click **"Edit"** or **"Remove"** or **"Clear"**
3. **Delete all YAML content** (or click "Remove Policy")
4. Click **"Save"**

**Step 3: Verify**

```bash
# Should return MCP server health, not AI Gateway error
curl https://unitares.ngrok.io/health
```

**Expected:** `{"status":"ok","version":"2.5.4",...}`

---

## After Removal

**What works:**
- ✅ MCP endpoint: `https://unitares.ngrok.io/mcp`
- ✅ Health endpoint: `https://unitares.ngrok.io/health`
- ✅ All MCP tools

**What doesn't work:**
- ❌ AI Gateway routing (but `call_model` tool handles this anyway)

**Note:** The `call_model` tool routes AI calls directly to providers, so removing the Traffic Policy doesn't break AI functionality.

---

## Alternative: Keep AI Gateway, Fix Routing

If you want to keep AI Gateway, update Traffic Policy to only apply to AI endpoints:

```yaml
on_http_request:
  - match: req.URL.Path == "/v1/chat/completions"
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
```

**But simpler:** Just remove it entirely - `call_model` tool handles AI routing.

---

**Status:** Remove Traffic Policy to restore MCP  
**Action:** Go to ngrok dashboard and clear Traffic Policy

