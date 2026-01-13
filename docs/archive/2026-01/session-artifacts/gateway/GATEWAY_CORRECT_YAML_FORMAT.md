# Correct ngrok.ai AI Gateway Traffic Policy Format

**Created:** January 1, 2026  
**Issue:** Unknown field 'type' and 'config' errors  
**Solution:** Use `actions` array structure

---

## Problem

**Error:**
```
unknown field 'type' on traffic policy rule
unknown field 'config' on traffic policy rule
```

**Cause:** The `type` and `config` must be inside an `actions` array, not directly under `on_http_request`.

---

## Correct Format

### Structure

```yaml
on_http_request:
  - actions:
      - type: ai-gateway
        config:
          providers: []
```

**Key:** `type` and `config` are inside `actions` array.

---

## Complete Correct Configuration

### For Hugging Face Provider:

```yaml
on_http_request:
  - actions:
      - type: ai-gateway
        config:
          providers:
            - id: "huggingface"
              base_url: "https://router.huggingface.co/v1"
              api_keys:
                - value: ${secrets.get('huggingface', 'hf_token')}
              models:
                - id: "deepseek-ai/DeepSeek-R1"
                - id: "deepseek-ai/DeepSeek-R1:fastest"
                - id: "deepseek-ai/DeepSeek-R1:cheapest"
                - id: "openai/gpt-oss-120b"
```

---

## If You Have Existing Rules

### Merge with Existing Policy:

**If your existing policy has other actions:**

```yaml
on_http_request:
  - actions:
      - type: request-headers
        config:
          add:
            X-Custom-Header: "value"
  
  - actions:
      - type: ai-gateway
        config:
          providers:
            - id: "huggingface"
              base_url: "https://router.huggingface.co/v1"
              api_keys:
                - value: ${secrets.get('huggingface', 'hf_token')}
              models:
                - id: "deepseek-ai/DeepSeek-R1"
                - id: "deepseek-ai/DeepSeek-R1:fastest"
```

**Notice:** Each rule has its own `actions` array.

---

## Complete Example with All Providers

```yaml
on_http_request:
  - actions:
      - type: ai-gateway
        config:
          providers:
            # Hugging Face (Primary)
            - id: "huggingface"
              base_url: "https://router.huggingface.co/v1"
              api_keys:
                - value: ${secrets.get('huggingface', 'hf_token')}
              models:
                - id: "deepseek-ai/DeepSeek-R1"
                - id: "deepseek-ai/DeepSeek-R1:fastest"
                - id: "openai/gpt-oss-120b"
            
            # Google Gemini (Optional)
            - id: "google"
              api_keys:
                - value: ${secrets.get('google', 'gemini_key')}
              models:
                - id: "gemini-flash"
                - id: "gemini-pro"
            
            # Ollama (Optional - Local)
            - id: "ollama-local"
              base_url: "http://localhost:11434/v1"
              models:
                - id: "llama-3.1-8b"
                - id: "mistral"
```

---

## Key Differences

### ❌ Wrong Format (What You Tried):

```yaml
on_http_request:
  - type: ai-gateway  # ← ERROR: type not allowed here
    config:            # ← ERROR: config not allowed here
      providers: []
```

### ✅ Correct Format:

```yaml
on_http_request:
  - actions:           # ← Required: actions array
      - type: ai-gateway  # ← type goes inside actions
        config:           # ← config goes inside actions
          providers: []
```

---

## Step-by-Step Fix

### Step 1: Edit Traffic Policy

1. Go to: Gateway → Traffic Policy → Edit
2. Clear any incorrect YAML

### Step 2: Use Correct Format

**Copy this exact format:**

```yaml
on_http_request:
  - actions:
      - type: ai-gateway
        config:
          providers:
            - id: "huggingface"
              base_url: "https://router.huggingface.co/v1"
              api_keys:
                - value: ${secrets.get('huggingface', 'hf_token')}
              models:
                - id: "deepseek-ai/DeepSeek-R1"
                - id: "deepseek-ai/DeepSeek-R1:fastest"
                - id: "openai/gpt-oss-120b"
```

### Step 3: Save

Click "Save" or "Apply"

### Step 4: Verify

**Test:**
```bash
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

**Expected:** List of models, no errors.

---

## Important Notes

1. **`actions` is required** - Don't skip this array
2. **Indentation matters** - Use 2 spaces
3. **`type` and `config`** go inside `actions`, not directly under `on_http_request`
4. **Multiple rules** = multiple `actions` arrays

---

## Quick Copy-Paste (Ready to Use)

```yaml
on_http_request:
  - actions:
      - type: ai-gateway
        config:
          providers:
            - id: "huggingface"
              base_url: "https://router.huggingface.co/v1"
              api_keys:
                - value: ${secrets.get('huggingface', 'hf_token')}
              models:
                - id: "deepseek-ai/DeepSeek-R1"
                - id: "deepseek-ai/DeepSeek-R1:fastest"
                - id: "openai/gpt-oss-120b"
```

**Make sure:**
- Secret `huggingface/hf_token` exists
- Value is: `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`

---

**Status:** ✅ Correct format identified  
**Fix:** Use `actions` array structure

