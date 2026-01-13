# Fix: Secret Not Found Error

**Created:** January 1, 2026  
**Issue:** `secrets.get('huggingface', 'hf_token')` - secret doesn't exist  
**Status:** Quick Fix Guide

---

## Problem

**Error:**
```
Failed to resolve secrets.get('huggingface', 'hf_token')
ERROR: sql: no rows in result set
```

**Cause:** The secret `huggingface/hf_token` doesn't exist in ngrok secrets.

---

## Solution 1: Create Secret (Recommended)

### Via Dashboard:

1. **Go to:** https://dashboard.ngrok.com/secrets
   - Or: Dashboard → Secrets → Create Secret

2. **Create Secret:**
   - **Provider:** `huggingface`
   - **Key Name:** `hf_token`
   - **Value:** `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`
   - Click **"Create"**

3. **Verify:** Secret should appear as `huggingface/hf_token`

4. **Test Gateway:**
   ```bash
   curl https://unitares.ngrok.io/v1/models \
     -H "Authorization: Bearer $NGROK_API_KEY"
   ```

---

### Via CLI:

```bash
# Create secret via ngrok CLI
ngrok api secrets create huggingface hf_token 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
```

---

### Via API:

```bash
curl -X POST https://api.ngrok.com/secrets \
  -H "Authorization: Bearer $NGROK_API_KEY" \
  -H "ngrok-version: 2" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "huggingface",
    "key": "hf_token",
    "value": "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"
  }'
```

---

## Solution 2: Use API Key Directly (Quick Fix)

**If you can't create secret right now, use API key directly:**

### Update Traffic Policy:

**Replace:**
```yaml
api_keys:
  - value: ${secrets.get('huggingface', 'hf_token')}
```

**With:**
```yaml
api_keys:
  - value: "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"
```

**Complete config:**
```yaml
on_http_request:
  - actions:
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
```

**Note:** This exposes the API key in Traffic Policy (less secure, but works immediately).

---

## Step-by-Step Fix

### Option A: Create Secret (Best Practice)

1. **Go to:** https://dashboard.ngrok.com/secrets
2. **Click:** "Create Secret"
3. **Fill in:**
   - Provider: `huggingface`
   - Key: `hf_token`
   - Value: `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`
4. **Save**
5. **Keep Traffic Policy as-is** (with `${secrets.get(...)}`)

### Option B: Use Direct API Key (Quick)

1. **Go to:** Gateway → Traffic Policy → Edit
2. **Replace secret reference** with direct value:
   ```yaml
   api_keys:
     - value: "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"
   ```
3. **Save**

---

## Test After Fix

```bash
# Test gateway
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

**Expected:** List of models (no 400 error).

---

## Current Status

✅ **Server:** Running fine (port 8765)  
✅ **Environment:** Configured correctly  
✅ **HF Token:** Valid (`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`)  
❌ **Gateway:** Secret missing → **Fix by creating secret OR using direct API key**

---

## Recommendation

**Quick fix:** Use direct API key in Traffic Policy (Solution 2)  
**Best practice:** Create secret in dashboard (Solution 1)

**Either way works - choose based on your preference!**

---

**Status:** ✅ Issue identified, fix ready  
**Time:** ~2 minutes to fix

