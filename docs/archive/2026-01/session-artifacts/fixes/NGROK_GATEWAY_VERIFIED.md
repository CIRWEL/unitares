# ngrok.ai Gateway Verification

**Created:** January 1, 2026  
**Status:** Gateway configured and active ✅

---

## ✅ Gateway Status

**From ngrok Dashboard:**
- **Endpoint:** `https://unitares.ngrok.io`
- **Type:** AI Gateway with Traffic Policy
- **Status:** Active (Last updated 7m ago)
- **Tags:** HTTPS, Public, Cloud, Pooled, Traffic Policy, AI Gateway

---

## Configuration Summary

**Gateway Endpoint:**
```
https://unitares.ngrok.io
```

**Environment Variables:**
```bash
NGROK_AI_ENDPOINT=https://unitares.ngrok.io
NGROK_API_KEY=<your_ngrok_api_key>
HF_TOKEN=<your_huggingface_token>
```

---

## Gateway Features

**Configured Providers:**
1. **Hugging Face Inference Providers**
   - Models: `deepseek-ai/DeepSeek-R1`, `deepseek-ai/DeepSeek-R1:fastest`, `openai/gpt-oss-120b`
   - Base URL: `https://router.huggingface.co/v1`
   - API Key: Stored in ngrok secrets (`huggingface/hf_token`)

**Traffic Policy:**
- Automatic failover (hf → gemini → ollama)
- Cost optimization (route to cheapest available)
- Rate limit handling (distribute across providers)

---

## Testing Gateway

### Test 1: Health Check

```bash
curl https://unitares.ngrok.io/health
```

### Test 2: Model Call via Gateway

```bash
curl https://unitares.ngrok.io/v1/chat/completions \
  -H "Authorization: Bearer $NGROK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-ai/DeepSeek-R1:fastest",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 50
  }'
```

### Test 3: Via call_model Tool

```python
# In MCP client
call_model(
    prompt="Test message",
    model="hf:deepseek-ai/DeepSeek-R1",
    provider="auto"
)
```

---

## Next Steps

1. ✅ **Gateway configured** (ngrok dashboard shows active)
2. ✅ **Traffic Policy active** (AI Gateway tag present)
3. ✅ **Providers configured** (Hugging Face in policy)
4. ⏳ **Test model calls** (via `call_model` tool)
5. ⏳ **Verify failover** (if one provider fails)

---

## Troubleshooting

### Issue: Gateway returns 400

**Check:**
- Traffic Policy syntax (YAML format)
- Secrets configured (`huggingface/hf_token`)
- Provider base URLs correct

**Fix:**
- Re-save Traffic Policy in ngrok dashboard
- Verify secret names match policy

---

### Issue: Model not found

**Check:**
- Model ID matches provider format
- Provider routing correct in Traffic Policy

**Fix:**
- Use model IDs from Traffic Policy
- Check provider availability

---

## Gateway Benefits

**Why use ngrok.ai Gateway:**

1. **Unified API** - Single endpoint for multiple providers
2. **Automatic Failover** - Seamless provider switching
3. **Cost Optimization** - Route to cheapest available
4. **Rate Limit Handling** - Distribute requests
5. **Observability** - Track all requests in ngrok dashboard

---

**Status:** Gateway active and ready  
**Action:** Test `call_model` tool with gateway endpoint

