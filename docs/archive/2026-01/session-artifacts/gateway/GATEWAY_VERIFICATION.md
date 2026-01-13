# Gateway Verification & Testing

**Created:** January 1, 2026  
**Status:** Post-Secret Setup Verification  
**Gateway:** https://unitares.ngrok.io

---

## Verification Steps

### Step 1: Test Gateway Models Endpoint

```bash
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

**Expected:** JSON response with list of models:
```json
{
  "object": "list",
  "data": [
    {
      "id": "deepseek-ai/DeepSeek-R1",
      "object": "model",
      ...
    }
  ]
}
```

---

### Step 2: Test Chat Completions

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

### Step 3: Test via call_model Tool

**From an agent or test script:**

```python
call_model(
    prompt="Hello! What is 2+2?",
    provider="auto",
    model="deepseek-ai/DeepSeek-R1"
)
```

**Expected:** Response routed through gateway.

---

## Troubleshooting

### If Still Getting 400 Error

**Check:**
1. Secret exists: Dashboard → Secrets → Verify `huggingface/hf_token`
2. Traffic Policy format: Verify `actions` array structure
3. Provider configuration: Check provider ID and base URL

**Re-test:**
```bash
curl -v https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY" 2>&1 | grep -A 5 "< HTTP"
```

---

### If Getting 401 Unauthorized

**Problem:** `NGROK_API_KEY` incorrect or missing

**Fix:**
```bash
# Verify API key is set
echo $NGROK_API_KEY

# Get from: https://dashboard.ngrok.com/api/keys
export NGROK_API_KEY=your_ngrok_api_key
```

---

### If Gateway Works But call_model Doesn't

**Check environment:**
```bash
# Verify gateway endpoint is set
echo $NGROK_AI_ENDPOINT

# Should be: https://unitares.ngrok.io
```

**Restart server:**
```bash
pkill -f mcp_server_sse.py
cd /Users/cirwel/projects/governance-mcp-v1
source .env 2>/dev/null || true
python src/mcp_server_sse.py --port 8765
```

---

## Success Indicators

✅ **Gateway responds:** `200 OK` on `/v1/models`  
✅ **Models listed:** See `deepseek-ai/DeepSeek-R1` in response  
✅ **Chat works:** Can call `/v1/chat/completions`  
✅ **call_model works:** Tool routes through gateway  

---

## Next Steps

1. ✅ **Secret created** (done)
2. ⏳ **Verify gateway works** (test above)
3. ⏳ **Test call_model tool** (if gateway works)
4. ⏳ **Use in production** (ready!)

---

**Status:** Ready to verify  
**Test:** Run verification commands above

