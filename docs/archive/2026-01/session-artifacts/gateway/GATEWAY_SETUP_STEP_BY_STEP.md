# Step-by-Step Gateway Provider Configuration

**Created:** January 1, 2026  
**Gateway:** https://unitares.ngrok.io  
**Status:** Ready to Follow

---

## Quick Start (5 Minutes)

Follow these exact steps to configure your Hugging Face provider.

---

## Step 1: Store HF Token in Secrets

### Via Dashboard:

1. **Go to:** https://dashboard.ngrok.com/secrets
   - Or: Dashboard → Secrets → Create Secret

2. **Create Secret:**
   - **Provider:** `huggingface`
   - **Key Name:** `hf_token`
   - **Value:** `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`
   - Click **"Create"** or **"Save"**

3. **Verify:** Secret should appear in list as `huggingface/hf_token`

---

## Step 2: Edit Traffic Policy

### Via Dashboard:

1. **Go to:** https://dashboard.ngrok.ai
2. **Find your gateway:** `unitares.ngrok.io`
3. **Click:** "Traffic Policy" or "Edit Policy"
4. **Click:** "Edit" or "Configure"

### Add Provider Configuration:

**In the Traffic Policy editor, add this YAML:**

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
            - id: "deepseek-ai/DeepSeek-R1:fastest"
            - id: "deepseek-ai/DeepSeek-R1:cheapest"
            - id: "openai/gpt-oss-120b"
```

**Or if using a form-based editor:**

- **Provider ID:** `huggingface`
- **Base URL:** `https://router.huggingface.co/v1`
- **API Key:** Select secret `huggingface/hf_token`
- **Models:** Add each model ID listed above

5. **Click:** "Save" or "Apply"

---

## Step 3: Verify Configuration

### Test 1: List Models

```bash
# Set ngrok API key (if not already set)
export NGROK_API_KEY=your_ngrok_api_key

# Test gateway
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

**Expected:** JSON response with list of models including `deepseek-ai/DeepSeek-R1`, etc.

---

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

**Expected:** Response from Hugging Face model.

---

### Test 3: Via call_model Tool

```python
call_model(
    prompt="Hello! What is 2+2?",
    provider="auto",
    model="deepseek-ai/DeepSeek-R1"
)
```

**Expected:** Response routed through gateway.

---

## Complete Configuration Example

**If you want to add all three providers, use this complete config:**

```yaml
on_http_request:
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
        
        # Google Gemini (Optional - requires Google API key)
        - id: "google"
          api_keys:
            - value: ${secrets.get('google', 'gemini_key')}
          models:
            - id: "gemini-flash"
            - id: "gemini-pro"
        
        # Ollama (Optional - local only)
        - id: "ollama-local"
          base_url: "http://localhost:11434/v1"
          models:
            - id: "llama-3.1-8b"
            - id: "mistral"
```

---

## Troubleshooting

### "Secret Not Found"

**Problem:** Secret not created or name incorrect

**Fix:**
1. Go to Secrets dashboard
2. Verify `huggingface/hf_token` exists
3. Check exact name matches: `huggingface` (provider) and `hf_token` (key)

---

### "Provider Not Found"

**Problem:** Provider not configured in Traffic Policy

**Fix:**
1. Check Traffic Policy → Providers
2. Verify `id: "huggingface"` exists
3. Verify `base_url` is set correctly

---

### "Model Not Available"

**Problem:** Model not in provider's model list

**Fix:**
1. Check provider → Models
2. Add model ID: `deepseek-ai/DeepSeek-R1`
3. Save Traffic Policy

---

### "Unauthorized"

**Problem:** API key incorrect or secret reference wrong

**Fix:**
1. Verify secret value: `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`
2. Check reference format: `${secrets.get('huggingface', 'hf_token')}`
3. Verify secret exists in dashboard

---

## Configuration Checklist

- [ ] **Step 1:** Store HF token in secrets (`huggingface/hf_token`)
- [ ] **Step 2:** Edit Traffic Policy → Add Hugging Face provider
- [ ] **Step 3:** Add models (`deepseek-ai/DeepSeek-R1`, etc.)
- [ ] **Step 4:** Save Traffic Policy
- [ ] **Step 5:** Set `NGROK_API_KEY` environment variable
- [ ] **Step 6:** Test: `curl https://unitares.ngrok.io/v1/models`
- [ ] **Step 7:** Restart MCP server
- [ ] **Step 8:** Test: `call_model(prompt="Hello!", provider="auto")`

---

## Values Reference

**Your Gateway:**
- URL: `https://unitares.ngrok.io`

**Hugging Face:**
- Provider ID: `huggingface`
- Base URL: `https://router.huggingface.co/v1`
- Secret: `huggingface/hf_token`
- Token Value: `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`

**Models to Add:**
- `deepseek-ai/DeepSeek-R1`
- `deepseek-ai/DeepSeek-R1:fastest`
- `deepseek-ai/DeepSeek-R1:cheapest`
- `openai/gpt-oss-120b`

---

## Quick Copy-Paste Config

**Minimal Configuration (just copy this):**

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
            - id: "deepseek-ai/DeepSeek-R1:fastest"
            - id: "openai/gpt-oss-120b"
```

**After adding this:**
1. Make sure secret `huggingface/hf_token` exists
2. Save Traffic Policy
3. Test!

---

**Status:** ✅ Ready to configure  
**Time:** ~5 minutes  
**Difficulty:** Easy (just copy-paste YAML)

