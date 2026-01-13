# Multi-Provider Model Inference Setup

**Created:** January 1, 2026  
**Status:** Complete Setup Guide  
**Priority:** High

---

## Overview

The `call_model` tool now supports **three free providers**:

1. **Hugging Face Inference Providers** (free tier, OpenAI-compatible)
2. **Google Gemini Flash** (free tier)
3. **Ollama** (local, free)

All providers work seamlessly through the same `call_model` tool interface.

---

## Quick Setup (Choose Your Provider)

### Option 1: Hugging Face Inference Providers (Recommended)

**Why:** Free tier, OpenAI-compatible, many models, auto-failover

**Setup:**

1. **Get HF Token** (free):
   - Go to: https://huggingface.co/settings/tokens
   - Click **"New token"**
   - Name: `unitares-inference`
   - Permissions: ✅ `Make calls to Inference Providers`
   - Click **"Generate token"**
   - **Copy the token**

2. **Set Environment Variable:**
   ```bash
   export HF_TOKEN=your_hf_token_here
   ```

3. **Test:**
   ```python
   call_model(
       prompt="Hello!",
       provider="hf",
       model="deepseek-ai/DeepSeek-R1:fastest"
   )
   ```

**Available Models:**
- `deepseek-ai/DeepSeek-R1:fastest` (recommended, free)
- `openai/gpt-oss-120b:fastest` (open-source, free)
- Browse more: https://huggingface.co/models?inference_provider=all&sort=trending

**Documentation:** [HF Inference Providers](https://huggingface.co/docs/inference-providers/index)

---

### Option 2: Google Gemini Flash

**Why:** Free tier, fast, Google-backed

**Setup:**

1. **Get Google AI Studio API Key** (free):
   - Go to: https://aistudio.google.com/app/apikey
   - Click **"Create API Key"**
   - **Copy the key**

2. **Set Environment Variable:**
   ```bash
   export GOOGLE_AI_API_KEY=your_google_key_here
   ```

3. **Test:**
   ```python
   call_model(
       prompt="Hello!",
       provider="gemini",
       model="gemini-flash"
   )
   ```

---

### Option 3: Ollama (Local)

**Why:** Privacy, local processing, no API keys needed

**Setup:**

1. **Install Ollama** (if not installed):
   ```bash
   # macOS
   brew install ollama
   
   # Or download from: https://ollama.ai/download
   ```

2. **Start Ollama:**
   ```bash
   ollama serve
   ```

3. **Pull a model:**
   ```bash
   ollama pull llama-3.1-8b
   ```

4. **Test (no API key needed):**
   ```python
   call_model(
       prompt="Hello!",
       provider="ollama",
       model="llama-3.1-8b",
       privacy="local"
   )
   ```

---

## ngrok.ai Gateway Setup (Optional)

If you want unified routing through ngrok.ai:

### Step 1: Get ngrok API Key

1. Sign up: https://ngrok.com/signup
2. Dashboard: https://dashboard.ngrok.com/api/keys
3. Create API key
4. Copy key

### Step 2: Configure ngrok.ai Gateway

**In ngrok.ai dashboard:**

1. **Create AI Gateway:**
   - Name: `unitares-ai-gateway`
   - Region: `us`

2. **Add Providers:**

   **Hugging Face:**
   - Provider: `Hugging Face`
   - Endpoint: `https://router.huggingface.co/v1`
   - API Key: Your `HF_TOKEN`
   - Priority: **1** (first choice)

   **Google Gemini:**
   - Provider: `Google`
   - Endpoint: `https://generativelanguage.googleapis.com/v1beta`
   - API Key: Your `GOOGLE_AI_API_KEY`
   - Priority: **2** (fallback)

   **Ollama (Local):**
   - Provider: `Ollama`
   - Endpoint: `http://localhost:11434/v1`
   - Priority: **3** (privacy mode)

3. **Get Gateway URL:**
   - Copy endpoint URL: `https://your-gateway.ngrok.ai/v1`

### Step 3: Configure Environment

```bash
# ngrok.ai gateway (unified routing)
export NGROK_AI_ENDPOINT=https://your-gateway.ngrok.ai/v1
export NGROK_API_KEY=your_ngrok_api_key

# Provider fallbacks (if gateway unavailable)
export HF_TOKEN=your_hf_token
export GOOGLE_AI_API_KEY=your_google_key
```

---

## Usage Examples

### Auto-Select Provider (Recommended)

```python
# System auto-selects best available provider
call_model(
    prompt="What is thermodynamic governance?",
    provider="auto"  # Tries HF → Gemini → Ollama
)
```

### Explicit Provider Selection

```python
# Hugging Face
call_model(
    prompt="Analyze this code",
    provider="hf",
    model="deepseek-ai/DeepSeek-R1:fastest"
)

# Google Gemini
call_model(
    prompt="Write a summary",
    provider="gemini",
    model="gemini-flash"
)

# Ollama (local, privacy)
call_model(
    prompt="Sensitive data analysis",
    provider="ollama",
    privacy="local"
)
```

### Model Selection

```python
# HF with auto-provider selection
call_model(
    prompt="Hello!",
    model="deepseek-ai/DeepSeek-R1:fastest"  # :fastest selects fastest provider
)

# HF with cheapest provider
call_model(
    prompt="Hello!",
    model="deepseek-ai/DeepSeek-R1:cheapest"  # :cheapest selects cheapest
)

# Specific HF provider
call_model(
    prompt="Hello!",
    model="deepseek-ai/DeepSeek-R1:sambanova"  # Force specific provider
)
```

---

## Environment Variables Summary

**Minimum (HF only):**
```bash
export HF_TOKEN=your_hf_token
```

**Full setup (all providers):**
```bash
# Hugging Face
export HF_TOKEN=your_hf_token

# Google Gemini
export GOOGLE_AI_API_KEY=your_google_key

# ngrok.ai gateway (optional)
export NGROK_AI_ENDPOINT=https://your-gateway.ngrok.ai/v1
export NGROK_API_KEY=your_ngrok_key
```

**Ollama:** No API key needed (runs locally)

---

## Provider Comparison

| Provider | Cost | Speed | Privacy | Setup |
|----------|------|-------|---------|-------|
| **HF Inference** | Free tier | Fast | Cloud | Easy (token only) |
| **Gemini Flash** | Free tier | Very Fast | Cloud | Easy (API key) |
| **Ollama** | Free | Medium | Local | Medium (install) |

**Recommendation:** Start with **HF Inference Providers** (easiest, most flexible).

---

## Troubleshooting

### "MISSING_CONFIG" Error

**Problem:** Provider token/key not set

**Fix:**
```bash
# Check what's set
env | grep -E "HF_TOKEN|GOOGLE_AI_API_KEY|NGROK"

# Set missing ones
export HF_TOKEN=your_token
export GOOGLE_AI_API_KEY=your_key
```

### "MODEL_NOT_AVAILABLE" Error

**Problem:** Model not found on provider

**Fix:**
- **HF:** Check model exists: https://huggingface.co/models?inference_provider=all
- **Gemini:** Use `gemini-flash` or `gemini-pro`
- **Ollama:** Pull model first: `ollama pull llama-3.1-8b`

### Ollama Connection Refused

**Problem:** Ollama not running

**Fix:**
```bash
# Start Ollama
ollama serve

# Check if running
curl http://localhost:11434/api/tags
```

---

## Next Steps

1. ✅ Choose provider (recommend HF Inference Providers)
2. ✅ Get API token/key
3. ✅ Set environment variable
4. ✅ Install dependencies: `pip install openai`
5. ✅ Restart MCP server
6. ✅ Test `call_model` tool

---

## References

- **HF Inference Providers:** https://huggingface.co/docs/inference-providers/index
- **HF Models:** https://huggingface.co/models?inference_provider=all
- **Google AI Studio:** https://aistudio.google.com/app/apikey
- **Ollama:** https://ollama.ai
- **ngrok.ai:** https://ngrok.ai

---

**Status:** ✅ Ready to use  
**Recommended:** Start with Hugging Face Inference Providers (free, easy, flexible)

