# ngrok.ai Gateway Provider Configuration (Official Format)

**Created:** January 1, 2026  
**Gateway:** https://unitares.ngrok.io  
**Reference:** [ngrok.ai Provider Configuration Docs](https://ngrok.com/docs/ai-gateway/guides/configuring-providers)

---

## Overview

Configure providers in your AI Gateway Traffic Policy. This guide follows the [official ngrok.ai documentation](https://ngrok.com/docs/ai-gateway/guides/configuring-providers).

---

## Configuration Format

Providers are configured in your **Traffic Policy** using YAML format:

```yaml
on_http_request:
  - type: ai-gateway
    config:
      providers:
        - id: "provider-name"
          base_url: "https://provider-endpoint.com/v1"  # For custom providers
          api_keys:
            - value: ${secrets.get('provider', 'key-name')}
          models:
            - id: "model-name"
```

---

## Provider 1: Hugging Face Inference Providers

**Configuration:**

```yaml
on_http_request:
  - type: ai-gateway
    config:
      providers:
        - id: "huggingface"
          base_url: "https://router.huggingface.co/v1"
          api_keys:
            - value: ${secrets.get('huggingface', 'hf_token')}
          models:
            - id: "deepseek-ai/DeepSeek-R1"
            - id: "openai/gpt-oss-120b"
            - id: "deepseek-ai/DeepSeek-R1:fastest"
            - id: "deepseek-ai/DeepSeek-R1:cheapest"
```

**In Dashboard:**

1. **Go to:** Traffic Policy → Edit
2. **Add Provider:**
   - **ID:** `huggingface`
   - **Base URL:** `https://router.huggingface.co/v1`
   - **API Key:** Store in secrets as `hf_token` with value `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`
   - **Models:** Add models listed above

**Or via API/CLI:**

```bash
# Store API key in secrets first
ngrok api secrets create huggingface hf_token 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

# Then configure in Traffic Policy
```

---

## Provider 2: Google Gemini (Optional)

**Configuration:**

```yaml
providers:
  - id: "google"
    api_keys:
      - value: ${secrets.get('google', 'gemini_key')}
    models:
      - id: "gemini-flash"
      - id: "gemini-pro"
```

**In Dashboard:**

1. **Add Provider:**
   - **ID:** `google` (built-in provider)
   - **API Key:** Store in secrets as `gemini_key`
   - **Models:** `gemini-flash`, `gemini-pro`

**Note:** `google` is a built-in provider, so `base_url` is not needed.

---

## Provider 3: Ollama (Custom - Local)

**Configuration:**

```yaml
providers:
  - id: "ollama-local"
    base_url: "http://localhost:11434/v1"
    models:
      - id: "llama-3.1-8b"
      - id: "mistral"
      - id: "llama-3.2"
```

**In Dashboard:**

1. **Add Provider:**
   - **ID:** `ollama-local` (custom name)
   - **Base URL:** `http://localhost:11434/v1`
   - **API Keys:** (none - Ollama doesn't require auth)
   - **Models:** Add Ollama models

**Note:** Only works if Ollama is running locally.

---

## Complete Multi-Provider Configuration

**Full Traffic Policy Example:**

```yaml
on_http_request:
  - type: ai-gateway
    config:
      only_allow_configured_providers: true
      only_allow_configured_models: true
      
      providers:
        # Hugging Face (Primary)
        - id: "huggingface"
          metadata:
            tier: "primary"
            cost: "free"
          base_url: "https://router.huggingface.co/v1"
          api_keys:
            - value: ${secrets.get('huggingface', 'hf_token')}
          models:
            - id: "deepseek-ai/DeepSeek-R1"
              metadata:
                recommended: true
            - id: "deepseek-ai/DeepSeek-R1:fastest"
            - id: "openai/gpt-oss-120b"
        
        # Google Gemini (Fallback)
        - id: "google"
          metadata:
            tier: "secondary"
            cost: "free"
          api_keys:
            - value: ${secrets.get('google', 'gemini_key')}
          models:
            - id: "gemini-flash"
            - id: "gemini-pro"
        
        # Ollama (Local/Privacy)
        - id: "ollama-local"
          metadata:
            tier: "fallback"
            cost: "free"
            privacy: "local"
          base_url: "http://localhost:11434/v1"
          models:
            - id: "llama-3.1-8b"
            - id: "mistral"
```

---

## Setting Up API Keys in Secrets

**Via Dashboard:**

1. Go to: **Secrets** → **Create Secret**
2. **Provider:** `huggingface`
3. **Key Name:** `hf_token`
4. **Value:** `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`
5. Click **Save**

**Via CLI:**

```bash
# Hugging Face token
ngrok api secrets create huggingface hf_token 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

# Google Gemini key (if using)
ngrok api secrets create google gemini_key YOUR_GOOGLE_KEY
```

**Via API:**

```bash
curl -X POST https://api.ngrok.com/secrets \
  -H "Authorization: Bearer $NGROK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "huggingface",
    "key": "hf_token",
    "value": "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"
  }'
```

---

## Provider Fields Reference

### Required Fields

- **`id`** (string, required): Provider identifier
  - Built-in: `openai`, `anthropic`, `google`, `deepseek`
  - Custom: Any name (e.g., `huggingface`, `ollama-local`)

### Optional Fields

- **`base_url`** (string): Custom endpoint URL
  - Required for custom providers (HF, Ollama)
  - Not needed for built-in providers (Google)

- **`api_keys`** (array): List of API keys
  - Use secrets: `${secrets.get('provider', 'key-name')}`
  - Multiple keys for failover/rotation

- **`models`** (array): List of model configurations
  - **`id`**: Model identifier
  - **`id_aliases`**: Alternative names
  - **`disabled`**: Temporarily disable
  - **`metadata`**: Custom metadata

- **`metadata`** (object): Custom metadata
  - For tracking/organization
  - Available in selection strategies

- **`disabled`** (boolean): Temporarily disable provider

---

## Step-by-Step Dashboard Setup

### Step 1: Store API Keys in Secrets

1. **Go to:** Dashboard → Secrets
2. **Create Secret:**
   - Provider: `huggingface`
   - Key: `hf_token`
   - Value: `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`
3. **Save**

### Step 2: Edit Traffic Policy

1. **Go to:** Gateway → Traffic Policy → Edit
2. **Add Provider Configuration:**

**Hugging Face:**
```yaml
- id: "huggingface"
  base_url: "https://router.huggingface.co/v1"
  api_keys:
    - value: ${secrets.get('huggingface', 'hf_token')}
  models:
    - id: "deepseek-ai/DeepSeek-R1"
    - id: "openai/gpt-oss-120b"
```

**Google (Optional):**
```yaml
- id: "google"
  api_keys:
    - value: ${secrets.get('google', 'gemini_key')}
  models:
    - id: "gemini-flash"
```

**Ollama (Optional - Local):**
```yaml
- id: "ollama-local"
  base_url: "http://localhost:11434/v1"
  models:
    - id: "llama-3.1-8b"
```

3. **Save Traffic Policy**

---

## Testing Configuration

### Test 1: List Models

```bash
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

**Expected:** List of configured models from all providers.

### Test 2: Call Model

```bash
curl https://unitares.ngrok.io/v1/chat/completions \
  -H "Authorization: Bearer $NGROK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-ai/DeepSeek-R1",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Test 3: Via call_model Tool

```python
call_model(
    prompt="Hello!",
    provider="auto",
    model="deepseek-ai/DeepSeek-R1"
)
```

---

## Model Selection Strategies

**Default:** Gateway selects first available provider.

**Custom Strategies:** Configure in Traffic Policy:

```yaml
config:
  model_selection:
    strategy: "fastest"  # or "cheapest", "round-robin", custom
```

**Model Suffixes:**
- `:fastest` - Select fastest provider
- `:cheapest` - Select cheapest provider
- `:provider-name` - Force specific provider

---

## Troubleshooting

### "Provider Not Found"

**Problem:** Provider ID incorrect or not configured

**Fix:**
1. Check Traffic Policy → Providers
2. Verify `id` matches exactly
3. For custom providers, ensure `base_url` is set

---

### "API Key Not Found"

**Problem:** Secret not stored or reference incorrect

**Fix:**
1. Check Secrets → Verify `huggingface/hf_token` exists
2. Verify reference: `${secrets.get('huggingface', 'hf_token')}`
3. Test secret retrieval

---

### "Model Not Available"

**Problem:** Model not configured in provider

**Fix:**
1. Check provider → Models
2. Verify model `id` matches exactly
3. Check if model is `disabled`

---

## Quick Reference

**Dashboard URLs:**
- Gateway: https://dashboard.ngrok.ai
- Traffic Policy: Gateway → Traffic Policy → Edit
- Secrets: Dashboard → Secrets

**Provider Configurations:**

| Provider | ID | Base URL | API Key Secret |
|----------|----|----------|----------------|
| **Hugging Face** | `huggingface` | `https://router.huggingface.co/v1` | `huggingface/hf_token` |
| **Google** | `google` | (built-in) | `google/gemini_key` |
| **Ollama** | `ollama-local` | `http://localhost:11434/v1` | (none) |

**Your Values:**
- HF Token: `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`
- Gateway URL: `https://unitares.ngrok.io`

---

## Next Steps

1. ✅ **Store HF token in secrets** (`huggingface/hf_token`)
2. ✅ **Edit Traffic Policy** → Add Hugging Face provider
3. ✅ **Add models** (`deepseek-ai/DeepSeek-R1`, etc.)
4. ✅ **Save Traffic Policy**
5. ✅ **Test:** `curl https://unitares.ngrok.io/v1/models`

---

**Reference:** [Official ngrok.ai Provider Configuration Docs](https://ngrok.com/docs/ai-gateway/guides/configuring-providers)  
**Status:** Ready to configure using official format

