# Correct ngrok.ai AI Gateway Traffic Policy Format

**Created:** January 1, 2026  
**Issue:** Unknown field 'type' and 'config' errors  
**Status:** Finding correct format

---

## Problem

**Error:**
```
unknown field 'type' on traffic policy rule
unknown field 'config' on traffic policy rule
```

**Cause:** The Traffic Policy format for ngrok.ai AI Gateway might be different from regular ngrok Traffic Policies.

---

## Possible Formats

### Format 1: Direct Provider Configuration (No Traffic Policy)

**AI Gateway might be configured directly, not via Traffic Policy:**

**In Gateway Dashboard:**
1. Go to: Gateway → **Providers** (not Traffic Policy)
2. Click: **"Add Provider"**
3. Fill in form fields directly (not YAML)

**Form Fields:**
- **Provider Name:** `huggingface`
- **Backend URL:** `https://router.huggingface.co/v1`
- **API Key:** Select secret or enter directly
- **Models:** Add model IDs

---

### Format 2: Simplified Traffic Policy

**If Traffic Policy is required, try this format:**

```yaml
providers:
  - id: "huggingface"
    base_url: "https://router.huggingface.co/v1"
    api_keys:
      - value: ${secrets.get('huggingface', 'hf_token')}
    models:
      - id: "deepseek-ai/DeepSeek-R1"
        - id: "deepseek-ai/DeepSeek-R1:fastest"
```

**Without the `on_http_request` wrapper.**

---

### Format 3: Gateway-Specific Configuration

**AI Gateway might have its own configuration section:**

```yaml
ai_gateway:
  providers:
    - id: "huggingface"
      base_url: "https://router.huggingface.co/v1"
      api_keys:
        - value: ${secrets.get('huggingface', 'hf_token')}
      models:
        - id: "deepseek-ai/DeepSeek-R1"
```

---

## Recommended: Use Dashboard UI Instead

**Since YAML format is causing errors, use the dashboard form:**

### Step 1: Access Provider Configuration

1. **Go to:** https://dashboard.ngrok.ai
2. **Select Gateway:** `unitares.ngrok.io`
3. **Look for:** "Providers" tab or "Configure Providers" button
4. **NOT** "Traffic Policy" - that's for regular ngrok rules

### Step 2: Add Provider via Form

**Click "Add Provider" and fill form:**

- **Provider ID/Name:** `huggingface`
- **Base URL:** `https://router.huggingface.co/v1`
- **API Key:** 
  - Select: "Use Secret"
  - Provider: `huggingface`
  - Key: `hf_token`
  - OR enter directly: `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`

- **Models:** Click "Add Model"
  - Model ID: `deepseek-ai/DeepSeek-R1`
  - Add more: `deepseek-ai/DeepSeek-R1:fastest`, `openai/gpt-oss-120b`

### Step 3: Save

Click "Save" or "Apply"

---

## Alternative: Check Gateway API

**If dashboard doesn't work, try API:**

```bash
# Get gateway configuration
curl https://api.ngrok.com/cloud_endpoints \
  -H "Authorization: Bearer $NGROK_API_KEY" \
  -H "ngrok-version: 2"

# Update gateway (check API docs for exact format)
curl -X PATCH https://api.ngrok.com/cloud_endpoints/{endpoint_id} \
  -H "Authorization: Bearer $NGROK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "providers": [{
      "id": "huggingface",
      "base_url": "https://router.huggingface.co/v1",
      "api_keys": [{
        "value": "${secrets.get(\"huggingface\", \"hf_token\")}"
      }],
      "models": [{
        "id": "deepseek-ai/DeepSeek-R1"
      }]
    }]
  }'
```

---

## Troubleshooting Steps

### Step 1: Check Dashboard Structure

1. **Go to:** https://dashboard.ngrok.ai
2. **Select:** Your gateway (`unitares.ngrok.io`)
3. **Look for tabs/sections:**
   - "Providers" ← Try this first
   - "Configuration"
   - "Settings"
   - "Traffic Policy" ← This might be for different rules

### Step 2: Check Documentation

**Look for:**
- "Adding Providers" guide
- "Provider Configuration" section
- "AI Gateway Setup" tutorial

### Step 3: Try Minimal Config

**If Traffic Policy is required, try absolute minimal:**

```yaml
providers:
  - id: huggingface
    base_url: https://router.huggingface.co/v1
```

**No `on_http_request`, no `type`, no `config` - just providers.**

---

## What to Look For in Dashboard

**In ngrok.ai dashboard, providers might be configured:**

1. **Separate from Traffic Policy**
   - Look for "Providers" tab
   - Or "AI Providers" section
   - Or "Backend Configuration"

2. **Via Form Interface**
   - Not YAML editor
   - Form fields for provider name, URL, API key

3. **In Gateway Settings**
   - Gateway → Settings → Providers
   - Or Gateway → Configure → Providers

---

## Quick Test: Check Current Configuration

**See what format your gateway currently uses:**

```bash
# Get gateway config
curl https://api.ngrok.com/cloud_endpoints \
  -H "Authorization: Bearer $NGROK_API_KEY" \
  -H "ngrok-version: 2" | jq '.'
```

**This will show the actual structure your gateway expects.**

---

## Next Steps

1. ✅ **Try Dashboard UI first** (Providers tab/form)
2. ✅ **Check current gateway config** (via API)
3. ✅ **Look for "Providers" section** (not Traffic Policy)
4. ✅ **Use form fields** (not YAML if causing errors)

---

**Status:** ⚠️ Format needs verification  
**Recommendation:** Use dashboard UI form instead of YAML

