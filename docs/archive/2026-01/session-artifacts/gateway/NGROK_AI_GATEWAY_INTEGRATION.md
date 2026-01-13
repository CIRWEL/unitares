# ngrok.ai AI Gateway Integration Guide

**Created:** January 1, 2026  
**Status:** Integration Instructions  
**Priority:** High

---

## Overview

Once you create your ngrok.ai AI Gateway, you'll get a URL like:
```
https://unitares.ngrok.io
```

This gateway will route requests to your configured providers (HF, Gemini, Ollama).

---

## Step 1: Get Your Gateway URL

**After creating the gateway in ngrok.ai dashboard:**

1. **Copy the Gateway URL**
   - Example: `https://unitares.ngrok.io`
   - Or: `https://abc123def456.ngrok.ai`

2. **Set Environment Variable:**
   ```bash
   export NGROK_AI_ENDPOINT=https://unitares.ngrok.io
   export NGROK_API_KEY=your_ngrok_api_key
   ```

3. **Add to .env:**
   ```bash
   echo "NGROK_AI_ENDPOINT=https://unitares.ngrok.io" >> .env
   echo "NGROK_API_KEY=your_ngrok_api_key" >> .env
   ```

---

## Step 2: Configure Providers in Gateway

**In ngrok.ai dashboard → Your Gateway → Configure:**

### Provider 1: Hugging Face

**Settings:**
- **Provider Name:** `huggingface`
- **Backend URL:** `https://router.huggingface.co/v1`
- **API Key:** `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` (your HF token)
- **Priority:** `1`

**Headers:**
```
Authorization: Bearer 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
```

---

### Provider 2: Google Gemini (Optional)

**Settings:**
- **Provider Name:** `gemini`
- **Backend URL:** `https://generativelanguage.googleapis.com/v1beta`
- **API Key:** Your `GOOGLE_AI_API_KEY`
- **Priority:** `2`

---

### Provider 3: Ollama (Optional - Local)

**Settings:**
- **Provider Name:** `ollama`
- **Backend URL:** `http://localhost:11434/v1`
- **API Key:** (none)
- **Priority:** `3`
- **Note:** Only works if Ollama is running locally

---

## Step 3: How Our Code Uses the Gateway

**Our `call_model` tool already supports ngrok.ai gateway!**

When `NGROK_AI_ENDPOINT` is set, the tool automatically uses it:

```python
# In model_inference.py
base_url = os.getenv("NGROK_AI_ENDPOINT", "https://api.openai.com/v1")
api_key = os.getenv("NGROK_API_KEY") or os.getenv("OPENAI_API_KEY")

client = OpenAI(base_url=base_url, api_key=api_key)
```

**This matches the ngrok.ai documentation pattern:**
```python
# ngrok.ai docs example
const provider = createOpenAI({
    baseUrl: 'https://unitares.ngrok.io'
});

# Our implementation (equivalent)
client = OpenAI(
    base_url='https://unitares.ngrok.io',
    api_key=ngrok_api_key
)
```

---

## Step 4: Test Gateway Integration

**Test 1: List Models**
```bash
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

**Expected:** List of models from all configured providers.

---

**Test 2: Call Model via Gateway**
```python
# Via our call_model tool
call_model(
    prompt="Hello!",
    provider="auto"  # Will route through gateway
)
```

**Expected:** Response from gateway (routed to HF/Gemini/Ollama).

---

## Step 5: Model IDs in Gateway

**After configuring providers, models will be available as:**

- **HF Models:** `deepseek-ai/DeepSeek-R1`, `openai/gpt-oss-120b`, etc.
- **Gemini Models:** `gemini-flash`, `gemini-pro`
- **Ollama Models:** `llama-3.1-8b`, `mistral`, etc.

**Use them in `call_model`:**
```python
call_model(
    prompt="Hello!",
    model="deepseek-ai/DeepSeek-R1",  # Model ID from gateway
    provider="auto"
)
```

---

## How It Works

**Request Flow:**

```
Agent calls call_model()
    ↓
Tool checks NGROK_AI_ENDPOINT
    ↓
If set → Routes to ngrok.ai gateway
    ↓
Gateway routes to configured provider (HF/Gemini/Ollama)
    ↓
Provider processes request
    ↓
Response flows back through gateway
    ↓
Tool returns to agent
```

**Fallback:**
- If `NGROK_AI_ENDPOINT` not set → Routes directly to providers
- If gateway unavailable → Falls back to direct provider routing

---

## Configuration Summary

**Environment Variables:**
```bash
# Gateway (unified routing)
NGROK_AI_ENDPOINT=https://unitares.ngrok.io
NGROK_API_KEY=your_ngrok_api_key

# Provider fallbacks (if gateway unavailable)
HF_TOKEN=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
GOOGLE_AI_API_KEY=your_google_key  # Optional
```

**Gateway Configuration:**
- HF: `https://router.huggingface.co/v1` + HF_TOKEN
- Gemini: `https://generativelanguage.googleapis.com/v1beta` + Google key
- Ollama: `http://localhost:11434/v1` (optional)

---

## Benefits of Using Gateway

✅ **Unified Endpoint:** Single URL for all providers  
✅ **Automatic Failover:** HF → Gemini → Ollama  
✅ **Rate Limit Distribution:** Spreads load across providers  
✅ **Traffic Inspection:** See all requests in ngrok dashboard  
✅ **Single API Key:** Use `NGROK_API_KEY` for all requests  

---

## Troubleshooting

### "Gateway Not Found"

**Problem:** `NGROK_AI_ENDPOINT` incorrect

**Fix:**
```bash
# Verify URL
echo $NGROK_AI_ENDPOINT

# Should be: https://unitares.ngrok.io (or your gateway URL)
```

---

### "Unauthorized" Error

**Problem:** `NGROK_API_KEY` incorrect or missing

**Fix:**
```bash
# Set API key
export NGROK_API_KEY=your_ngrok_api_key

# Verify
echo $NGROK_API_KEY
```

---

### "Model Not Available"

**Problem:** Model not configured in gateway

**Fix:**
1. Check gateway dashboard → Configure → Models
2. Verify provider is added
3. Check model ID matches gateway configuration

---

## Next Steps

1. ✅ **Create gateway** in ngrok.ai dashboard
2. ✅ **Copy gateway URL** (e.g., `https://unitares.ngrok.io`)
3. ✅ **Configure providers** (HF, Gemini, Ollama)
4. ✅ **Set environment variables:**
   ```bash
   export NGROK_AI_ENDPOINT=https://unitares.ngrok.io
   export NGROK_API_KEY=your_ngrok_key
   ```
5. ✅ **Restart MCP server**
6. ✅ **Test:** `call_model(prompt="Hello!", provider="auto")`

---

## Code Integration

**Our code already supports this!** No changes needed.

The `call_model` tool automatically:
- ✅ Uses `NGROK_AI_ENDPOINT` if set
- ✅ Falls back to direct providers if not set
- ✅ Works with OpenAI SDK (compatible with ngrok.ai gateway)

**Just set the environment variables and it works!**

---

**Status:** ✅ Ready to integrate  
**Your Gateway URL:** Set `NGROK_AI_ENDPOINT` to your gateway URL

