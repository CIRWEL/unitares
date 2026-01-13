# ngrok.ai Gateway Environment Setup

**Created:** January 1, 2026  
**Status:** Gateway active, need to configure environment variables

---

## ✅ Gateway Status

**From ngrok Dashboard:**
- **Endpoint:** `https://unitares.ngrok.io` ✅ Active
- **Traffic Policy:** Configured ✅
- **AI Gateway:** Enabled ✅
- **Providers:** Hugging Face configured ✅

---

## Required Environment Variables

**For `call_model` tool to use ngrok.ai gateway:**

```bash
# ngrok.ai Gateway endpoint
NGROK_AI_ENDPOINT=https://unitares.ngrok.io

# ngrok API key (for authentication)
NGROK_API_KEY=<your_ngrok_api_key>

# Hugging Face token (for HF provider)
HF_TOKEN=<your_huggingface_token>
```

---

## Setup Steps

### Step 1: Get ngrok API Key

1. Go to ngrok dashboard: https://dashboard.ngrok.com
2. Navigate to **API** section
3. Copy your **API Key**

### Step 2: Get Hugging Face Token

1. Go to: https://huggingface.co/settings/tokens
2. Create new token (or use existing)
3. Copy token (starts with `hf_`)

### Step 3: Set Environment Variables

**Option A: Add to `.env` file**

```bash
cd /Users/cirwel/projects/governance-mcp-v1

# Add to .env file
cat >> .env << 'EOF'
NGROK_AI_ENDPOINT=https://unitares.ngrok.io
NGROK_API_KEY=<your_ngrok_api_key>
HF_TOKEN=<your_huggingface_token>
EOF
```

**Option B: Export in shell**

```bash
export NGROK_AI_ENDPOINT=https://unitares.ngrok.io
export NGROK_API_KEY=<your_ngrok_api_key>
export HF_TOKEN=<your_huggingface_token>
```

---

## Verification

### Test 1: Check Variables

```bash
cd /Users/cirwel/projects/governance-mcp-v1
source .env 2>/dev/null || true

echo "NGROK_AI_ENDPOINT: ${NGROK_AI_ENDPOINT:-not set}"
echo "NGROK_API_KEY: ${NGROK_API_KEY:+set}"
echo "HF_TOKEN: ${HF_TOKEN:+set}"
```

### Test 2: Test Gateway Connection

```bash
python3 -c "
import os
from openai import OpenAI

endpoint = os.getenv('NGROK_AI_ENDPOINT')
api_key = os.getenv('NGROK_API_KEY')

if endpoint and api_key:
    client = OpenAI(base_url=endpoint, api_key=api_key)
    print('✅ Gateway client created')
    print(f'✅ Endpoint: {endpoint}')
else:
    print('❌ Missing environment variables')
"
```

### Test 3: Test call_model Tool

**After restarting server with env vars:**

```python
# In MCP client
call_model(
    prompt="Hello, test message",
    model="hf:deepseek-ai/DeepSeek-R1",
    provider="auto"
)
```

---

## How It Works

**When `call_model` is called:**

1. **Check provider/model:**
   - If `provider="hf"` or model starts with `hf:` → Use Hugging Face
   - If `provider="auto"` → Use ngrok.ai gateway (routes automatically)

2. **Route via gateway:**
   - `NGROK_AI_ENDPOINT` → `https://unitares.ngrok.io`
   - Gateway Traffic Policy routes to Hugging Face
   - Uses `HF_TOKEN` for Hugging Face authentication

3. **Return response:**
   - Model response via gateway
   - Tracked in EISV (Energy consumption)

---

## Gateway Routing Logic

**Current Traffic Policy routes:**
- `hf:` models → Hugging Face Inference Providers
- `deepseek-ai/DeepSeek-R1` → Hugging Face
- `openai/gpt-oss-120b` → Hugging Face

**Auto-routing:**
- Gateway selects fastest/cheapest provider
- Automatic failover if provider unavailable

---

## Restart Server After Setup

**After setting environment variables:**

```bash
cd /Users/cirwel/projects/governance-mcp-v1

# Stop server
pkill -f mcp_server_sse.py

# Start with env vars
source .env 2>/dev/null || true
python3 src/mcp_server_sse.py --port 8765 &
```

---

## Troubleshooting

### Issue: "MISSING_CONFIG" error

**Symptom:** `call_model` returns missing config error

**Fix:**
- Set `NGROK_AI_ENDPOINT` and `NGROK_API_KEY`
- Restart server after setting vars

---

### Issue: Gateway returns 400

**Symptom:** Gateway rejects requests

**Fix:**
- Check Traffic Policy in ngrok dashboard
- Verify secrets configured (`huggingface/hf_token`)
- Re-save Traffic Policy

---

### Issue: Model not found

**Symptom:** "Model not available" error

**Fix:**
- Use model IDs from Traffic Policy:
  - `deepseek-ai/DeepSeek-R1`
  - `deepseek-ai/DeepSeek-R1:fastest`
  - `openai/gpt-oss-120b`
- Or use `hf:` prefix: `hf:deepseek-ai/DeepSeek-R1`

---

## Next Steps

1. ✅ **Gateway configured** (ngrok dashboard)
2. ⏳ **Set environment variables** (NGROK_AI_ENDPOINT, NGROK_API_KEY, HF_TOKEN)
3. ⏳ **Restart server** (to load env vars)
4. ⏳ **Test call_model** (verify gateway routing)

---

**Status:** Gateway ready, need env vars  
**Action:** Set environment variables and restart server

