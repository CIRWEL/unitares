# Fix Gateway 400 Error

**Created:** January 1, 2026  
**Issue:** Gateway returns 400 Bad Request  
**Status:** Troubleshooting

---

## Problem

**Gateway returns:** `400 Bad Request`

**Possible causes:**
1. Traffic Policy configuration error
2. Provider not configured correctly
3. API key/secret reference incorrect
4. Model configuration issue

---

## Quick Fixes

### Fix 1: Verify Traffic Policy Format

**Check your Traffic Policy uses correct format:**

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
```

**Common mistakes:**
- Missing `actions` array
- Wrong indentation
- Secret reference incorrect
- Provider ID typo

---

### Fix 2: Verify Secret Exists

**Check secret is stored correctly:**

1. Go to: Dashboard → Secrets
2. Verify: `huggingface/hf_token` exists
3. Check value: `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`

**If secret doesn't exist:**
- Create it: Provider=`huggingface`, Key=`hf_token`, Value=`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`

---

### Fix 3: Test Gateway Directly

**Test with direct API key (bypass secret):**

**Temporarily modify Traffic Policy:**

```yaml
on_http_request:
  - actions:
      - type: ai-gateway
        config:
          providers:
            - id: "huggingface"
              base_url: "https://router.huggingface.co/v1"
              api_keys:
                - value: "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"  # Direct value (temporary)
              models:
                - id: "deepseek-ai/DeepSeek-R1"
```

**Test:**
```bash
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

**If this works:** Secret reference is the issue.  
**If this fails:** Provider configuration is wrong.

---

### Fix 4: Simplify Configuration

**Try minimal config first:**

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
```

**Remove:**
- Model aliases (`:fastest`, `:cheapest`)
- Multiple models
- Metadata
- Other providers

**Test with minimal config first, then add complexity.**

---

### Fix 5: Check Gateway Dashboard

**In ngrok.ai dashboard:**

1. **Go to:** Gateway → Traffic Inspector
2. **Check recent requests:**
   - Look for error messages
   - Check request/response details
   - See what's failing

3. **Check Provider Status:**
   - Gateway → Providers
   - Verify Hugging Face provider is active
   - Check backend URL is correct

---

## Alternative: Use Direct Routing (Bypass Gateway)

**If gateway continues to fail, use direct provider routing:**

```bash
# Remove gateway endpoint
unset NGROK_AI_ENDPOINT

# Keep HF token for direct routing
export HF_TOKEN=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

# Update .env
sed -i '' '/NGROK_AI_ENDPOINT/d' .env

# Restart server
pkill -f mcp_server_sse.py
cd /Users/cirwel/projects/governance-mcp-v1
python src/mcp_server_sse.py --port 8765
```

**This routes directly to Hugging Face, bypassing the gateway.**

---

## Step-by-Step Recovery

### Step 1: Check Gateway Error Details

```bash
# Get detailed error
curl -v https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY" 2>&1 | grep -A 10 "< HTTP"
```

### Step 2: Verify Traffic Policy

1. Go to: Gateway → Traffic Policy → Edit
2. Copy entire YAML
3. Validate syntax (check indentation, brackets)
4. Verify secret reference format

### Step 3: Test Minimal Config

**Replace with minimal:**
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
```

### Step 4: Test Again

```bash
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

---

## Common 400 Error Causes

1. **Invalid YAML syntax** → Check indentation, brackets
2. **Secret not found** → Verify secret exists
3. **Provider ID wrong** → Check exact spelling
4. **Base URL incorrect** → Verify URL format
5. **Model ID invalid** → Check model exists on provider
6. **API key format wrong** → Verify key format

---

## Quick Test: Direct Provider (Bypass Gateway)

**Test if Hugging Face works directly:**

```bash
# Test HF directly (bypass gateway)
curl https://router.huggingface.co/v1/models \
  -H "Authorization: Bearer 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"
```

**If this works:** Gateway configuration is the issue.  
**If this fails:** HF token or provider issue.

---

**Status:** Diagnostic guide  
**Next:** Check gateway error details and verify Traffic Policy format

