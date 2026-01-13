# ngrok.ai AI Gateway Configuration Guide

**Created:** January 1, 2026  
**Status:** Step-by-Step Configuration  
**Priority:** High

---

## Overview

When setting up ngrok.ai AI Gateway, you need to configure:

1. **Gateway Endpoint URL** (what you're seeing now)
2. **Provider Backends** (HF, Gemini, Ollama)
3. **Routing Rules** (priority, failover)

---

## Step 1: Gateway Endpoint URL

**In the ngrok.ai dashboard form:**

**Field: "URL" or "Endpoint"**

**What to enter:**

### Option A: Use ngrok.ai Generated URL (Recommended)

Leave it **empty** or let ngrok.ai **auto-generate** a URL for you.

**Example generated URL:**
```
https://abc123def456.ngrok.ai/v1
```

**After creation, you'll get:**
- Gateway URL: `https://abc123def456.ngrok.ai/v1`
- Use this as your `NGROK_AI_ENDPOINT`

---

### Option B: Custom Domain (If Available)

If you have a custom domain configured:
```
https://ai-gateway.yourdomain.com/v1
```

---

## Step 2: Configure Provider Backends

After creating the gateway, add providers:

### Provider 1: Hugging Face Inference Providers

**Configuration:**
- **Provider Name:** `huggingface` or `hf`
- **Backend URL:** `https://router.huggingface.co/v1`
- **API Key:** Your `HF_TOKEN` (already set: `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`)
- **Priority:** `1` (first choice)
- **Models:** Auto-detected from HF router

**Headers to add:**
```
Authorization: Bearer {HF_TOKEN}
```

---

### Provider 2: Google Gemini

**Configuration:**
- **Provider Name:** `gemini` or `google`
- **Backend URL:** `https://generativelanguage.googleapis.com/v1beta`
- **API Key:** Your `GOOGLE_AI_API_KEY` (if you have one)
- **Priority:** `2` (fallback)
- **Models:** `gemini-flash`, `gemini-pro`

**Headers to add:**
```
Authorization: Bearer {GOOGLE_AI_API_KEY}
```

---

### Provider 3: Ollama (Local - Optional)

**Configuration:**
- **Provider Name:** `ollama` or `local`
- **Backend URL:** `http://localhost:11434/v1`
- **API Key:** (none - Ollama doesn't require auth)
- **Priority:** `3` (privacy mode only)
- **Models:** `llama-3.1-8b`, `mistral`, etc.

**Note:** Only works if Ollama is running locally.

---

## Step 3: Routing Configuration

**Priority Order:**
1. **Hugging Face** (first - free tier, many models)
2. **Gemini** (fallback - free tier)
3. **Ollama** (privacy mode only)

**Failover:**
- If HF unavailable → try Gemini
- If Gemini unavailable → try Ollama (if local)
- If all fail → return error

---

## Step 4: Get Gateway Endpoint URL

**After creating the gateway:**

1. **Copy the Gateway URL** from dashboard
   - Example: `https://abc123def456.ngrok.ai/v1`

2. **Set Environment Variable:**
   ```bash
   export NGROK_AI_ENDPOINT=https://abc123def456.ngrok.ai/v1
   export NGROK_API_KEY=your_ngrok_api_key
   ```

3. **Add to .env file:**
   ```bash
   echo "NGROK_AI_ENDPOINT=https://abc123def456.ngrok.ai/v1" >> .env
   echo "NGROK_API_KEY=your_ngrok_api_key" >> .env
   ```

---

## Step 5: Test Gateway

**Test the gateway endpoint:**
```bash
curl https://abc123def456.ngrok.ai/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

**Expected:** List of available models from all providers.

---

## Alternative: Skip Gateway (Use Direct Providers)

**If ngrok.ai gateway setup is complex, you can skip it:**

The `call_model` tool works **directly** with providers:

```bash
# Just set provider tokens (no gateway needed)
export HF_TOKEN=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
export GOOGLE_AI_API_KEY=your_google_key  # Optional

# Tool will route directly to providers
call_model(prompt="Hello!", provider="auto")
```

**Benefits of direct routing:**
- ✅ Simpler setup (no gateway config)
- ✅ Works immediately
- ✅ No extra latency
- ✅ Free tier works fine

**Benefits of gateway:**
- ✅ Unified endpoint
- ✅ Automatic failover
- ✅ Rate limit distribution
- ✅ Single API key

---

## What to Enter in the Form

**For the "URL" field in ngrok.ai dashboard:**

### Recommended: Leave Empty

Let ngrok.ai **auto-generate** the URL for you.

**After creation, you'll get:**
- Gateway URL: `https://[random-id].ngrok.ai/v1`
- Copy this URL
- Use as `NGROK_AI_ENDPOINT`

---

## Quick Setup Summary

1. **Create Gateway:**
   - URL field: **Leave empty** (auto-generate)
   - Click "Create"

2. **Add Providers:**
   - HF: `https://router.huggingface.co/v1` + your HF_TOKEN
   - Gemini: `https://generativelanguage.googleapis.com/v1beta` + Google key
   - Ollama: `http://localhost:11434/v1` (optional)

3. **Get Gateway URL:**
   - Copy from dashboard: `https://[id].ngrok.ai/v1`

4. **Configure:**
   ```bash
   export NGROK_AI_ENDPOINT=https://[id].ngrok.ai/v1
   export NGROK_API_KEY=your_ngrok_key
   ```

5. **Test:**
   ```bash
   curl $NGROK_AI_ENDPOINT/models -H "Authorization: Bearer $NGROK_API_KEY"
   ```

---

## Troubleshooting

### "Invalid URL" Error

**Problem:** URL format incorrect

**Fix:**
- Leave URL **empty** (let ngrok.ai generate it)
- Or use format: `https://your-domain.ngrok.ai/v1`

### "Provider Not Found" Error

**Problem:** Backend URL incorrect

**Fix:**
- HF: Use `https://router.huggingface.co/v1`
- Gemini: Use `https://generativelanguage.googleapis.com/v1beta`
- Ollama: Use `http://localhost:11434/v1`

### Gateway Not Routing

**Problem:** API key or headers incorrect

**Fix:**
- Verify `NGROK_API_KEY` is set
- Check provider API keys in gateway config
- Test direct provider first (bypass gateway)

---

## Recommendation

**For now, skip the gateway** and use direct providers:

```bash
# Already configured ✅
export HF_TOKEN=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

# Test direct routing
call_model(prompt="Hello!", provider="hf")
```

**Gateway is optional** - direct routing works great and is simpler!

---

**Status:** ✅ Gateway optional, direct routing recommended  
**Your HF token:** Already configured and working ✅

