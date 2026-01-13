# ngrok.ai Gateway Provider Configuration Guide

**Created:** January 1, 2026  
**Gateway:** https://unitares.ngrok.io  
**Status:** Step-by-Step Instructions  
**Reference:** [Official ngrok.ai Docs](https://ngrok.com/docs/ai-gateway/guides/configuring-providers)

**Note:** See `GATEWAY_PROVIDER_SETUP_OFFICIAL.md` for official YAML format configuration.

---

## Overview

Configure providers in your ngrok.ai gateway dashboard to route requests to:
1. **Hugging Face Inference Providers** (free tier, recommended)
2. **Google Gemini** (free tier, optional)
3. **Ollama** (local, optional)

---

## Step 1: Access Gateway Dashboard

1. **Go to:** https://dashboard.ngrok.ai
2. **Find your gateway:** `unitares.ngrok.io`
3. **Click:** "Configure" or "Manage Providers"

---

## Step 2: Add Hugging Face Provider

### Provider Details

**Click "Add Provider" or "Add Backend":**

**Basic Settings:**
- **Provider Name:** `huggingface` (or `hf`)
- **Backend URL:** `https://router.huggingface.co/v1`
- **Provider Type:** `OpenAI Compatible` (or `Custom`)

**Authentication:**
- **Method:** `Bearer Token` or `API Key`
- **API Key:** `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`

**Headers (if custom header option available):**
```
Authorization: Bearer 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
```

**Priority/Routing:**
- **Priority:** `1` (highest - use first)
- **Weight:** `100` (if using weighted routing)

**Models (if manual model configuration):**
- `deepseek-ai/DeepSeek-R1`
- `openai/gpt-oss-120b`
- Or leave empty for auto-discovery

**Click:** "Save" or "Add Provider"

---

## Step 3: Add Google Gemini Provider (Optional)

### Provider Details

**Click "Add Provider":**

**Basic Settings:**
- **Provider Name:** `gemini` (or `google`)
- **Backend URL:** `https://generativelanguage.googleapis.com/v1beta`
- **Provider Type:** `Custom` or `Google`

**Authentication:**
- **Method:** `API Key`
- **API Key:** Your Google AI Studio key
  - Get from: https://aistudio.google.com/app/apikey

**Headers:**
```
Authorization: Bearer YOUR_GOOGLE_AI_API_KEY
```

**Priority/Routing:**
- **Priority:** `2` (fallback after HF)
- **Weight:** `50`

**Models:**
- `gemini-flash`
- `gemini-pro`

**Click:** "Save"

---

## Step 4: Add Ollama Provider (Optional - Local Only)

**Note:** Only works if Ollama is running locally on your machine.

### Provider Details

**Click "Add Provider":**

**Basic Settings:**
- **Provider Name:** `ollama` (or `local`)
- **Backend URL:** `http://localhost:11434/v1`
- **Provider Type:** `OpenAI Compatible`

**Authentication:**
- **Method:** `None` (Ollama doesn't require auth)
- **API Key:** (leave empty)

**Priority/Routing:**
- **Priority:** `3` (privacy mode only)
- **Weight:** `25`

**Models:**
- `llama-3.1-8b`
- `mistral`
- `llama-3.2`

**Click:** "Save"

**Important:** Ollama must be running:
```bash
# Check if running
curl http://localhost:11434/api/tags

# If not running, start it
ollama serve
```

---

## Step 5: Configure Routing Rules

**In gateway dashboard → Routing:**

### Default Routing

**Priority Order:**
1. **Hugging Face** (Priority 1) - First choice
2. **Gemini** (Priority 2) - Fallback
3. **Ollama** (Priority 3) - Privacy/local only

### Failover Rules

**If HF unavailable:**
- Try Gemini
- If Gemini unavailable → Try Ollama (if local)
- If all fail → Return error

**Privacy Mode:**
- If `privacy="local"` → Route to Ollama only
- Bypass cloud providers

---

## Step 6: Verify Configuration

### Test 1: List Models via Gateway

```bash
# Set ngrok API key first
export NGROK_API_KEY=your_ngrok_api_key

# Test gateway
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

**Expected:** List of models from all configured providers.

---

### Test 2: Test via call_model Tool

```python
# This should route through gateway
call_model(
    prompt="Hello!",
    provider="auto"
)
```

**Expected:** Response from HF (or fallback provider).

---

## Step 7: Set ngrok API Key (If Not Already Set)

**Get API Key:**
1. Go to: https://dashboard.ngrok.com/api/keys
2. Click "Create API Key"
3. Copy the key

**Set Environment:**
```bash
export NGROK_API_KEY=your_ngrok_api_key
echo "NGROK_API_KEY=your_ngrok_api_key" >> .env
```

---

## Configuration Summary

**Gateway URL:** `https://unitares.ngrok.io`

**Providers Configured:**

| Provider | Backend URL | API Key | Priority |
|----------|-------------|---------|----------|
| **Hugging Face** | `https://router.huggingface.co/v1` | `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` | 1 |
| **Gemini** | `https://generativelanguage.googleapis.com/v1beta` | Your Google key | 2 |
| **Ollama** | `http://localhost:11434/v1` | None | 3 |

**Environment Variables:**
```bash
NGROK_AI_ENDPOINT=https://unitares.ngrok.io
NGROK_API_KEY=your_ngrok_api_key
HF_TOKEN=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
```

---

## Troubleshooting

### "Provider Not Found" Error

**Problem:** Provider not configured in gateway

**Fix:**
1. Check gateway dashboard → Providers
2. Verify provider is added
3. Check backend URL is correct

---

### "Unauthorized" Error

**Problem:** API key incorrect

**Fix:**
1. Verify HF token: `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`
2. Check token has "Inference Providers" permission
3. Verify token in gateway provider config

---

### "Connection Refused" (Ollama)

**Problem:** Ollama not running locally

**Fix:**
```bash
# Start Ollama
ollama serve

# Verify running
curl http://localhost:11434/api/tags
```

---

### Gateway Not Routing to HF

**Problem:** Provider priority or routing misconfigured

**Fix:**
1. Check provider priority (HF should be 1)
2. Verify backend URL: `https://router.huggingface.co/v1`
3. Check API key is set correctly
4. Test HF directly first (bypass gateway)

---

## Quick Reference

**Dashboard URLs:**
- Gateway: https://dashboard.ngrok.ai
- API Keys: https://dashboard.ngrok.com/api/keys
- Traffic Inspector: Click "Inspect Traffic" in gateway dashboard

**Provider Backend URLs:**
- HF: `https://router.huggingface.co/v1`
- Gemini: `https://generativelanguage.googleapis.com/v1beta`
- Ollama: `http://localhost:11434/v1`

**API Keys:**
- HF Token: `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` ✅
- Google Key: Get from https://aistudio.google.com/app/apikey
- ngrok Key: Get from https://dashboard.ngrok.com/api/keys

---

## Next Steps

1. ✅ **Add Hugging Face provider** (required)
2. ⏳ **Add Gemini provider** (optional)
3. ⏳ **Add Ollama provider** (optional, local only)
4. ⏳ **Set NGROK_API_KEY** environment variable
5. ⏳ **Restart MCP server**
6. ⏳ **Test:** `call_model(prompt="Hello!", provider="auto")`

---

**Status:** Ready to configure providers  
**Minimum:** Just add Hugging Face provider to get started!

