# Simple ngrok.ai Setup Guide

**Created:** January 1, 2026  
**Status:** Step-by-Step Setup  
**Priority:** High

---

## Quick Clarification

**Two different things:**
- **ngrok API** (`ngrok.com/docs/api`) - For managing tunnels/endpoints programmatically
- **ngrok.ai** (`ngrok.ai`) - AI Gateway service for routing AI model requests ← **We need this**

For the `call_model` tool, you need **ngrok.ai** (AI Gateway), not the ngrok API.

---

## Step-by-Step Setup

### Step 1: Get ngrok Account & API Key

1. **Sign up for ngrok** (if you don't have an account):
   - Go to: https://ngrok.com/signup
   - Create free account

2. **Get your API Key**:
   - Log in to: https://dashboard.ngrok.com
   - Go to: **API** → **API Keys**
   - Click **"Create API Key"**
   - Copy the key (looks like: `2abc123def456...`)

**Save this key** - you'll need it for Step 3.

---

### Step 2: Set Up ngrok.ai AI Gateway

**Option A: Using ngrok.ai Dashboard (Recommended)**

1. **Go to ngrok.ai dashboard**:
   - Visit: https://dashboard.ngrok.ai (or check if it's integrated in main dashboard)
   - If separate, sign in with your ngrok account

2. **Create AI Gateway Endpoint**:
   - Click **"Create Gateway"** or **"New Endpoint"**
   - Name it: `unitares-ai-gateway` (or whatever you prefer)
   - Choose region: `us` (or closest to you)

3. **Add AI Providers**:
   
   **For Gemini Flash (Free):**
   - Provider: **Google**
   - Model: `gemini-flash` or `gemini-1.5-flash`
   - API Key: Get from [Google AI Studio](https://aistudio.google.com/app/apikey)
   - Priority: **1** (use first)

   **For Ollama (Local - Optional):**
   - Provider: **Ollama**
   - Endpoint: `http://localhost:11434`
   - Models: `llama-3.1-8b`, `mistral`
   - Priority: **2** (fallback)

4. **Get Gateway Endpoint URL**:
   - After creating, you'll get a URL like: `https://abc123.ngrok.ai/v1`
   - **Copy this URL** - you'll need it for Step 3

**Option B: Using ngrok API (Advanced)**

If ngrok.ai isn't available yet, you can use direct provider endpoints:

```bash
# For Gemini Flash (direct)
NGROK_AI_ENDPOINT=https://generativelanguage.googleapis.com/v1beta
NGROK_API_KEY=your_google_ai_studio_key

# Or use OpenAI-compatible endpoint
NGROK_AI_ENDPOINT=https://api.openai.com/v1
NGROK_API_KEY=your_openai_key
```

---

### Step 3: Configure Environment Variables

**Add to your `.env` file** (or export in shell):

```bash
# ngrok.ai AI Gateway endpoint
NGROK_AI_ENDPOINT=https://your-gateway.ngrok.ai/v1

# ngrok API key (from Step 1)
NGROK_API_KEY=2abc123def456...

# Optional: Direct provider keys (if not using gateway)
# GOOGLE_AI_API_KEY=your_google_key
# OPENAI_API_KEY=your_openai_key
```

**Or export in terminal:**

```bash
export NGROK_AI_ENDPOINT=https://your-gateway.ngrok.ai/v1
export NGROK_API_KEY=2abc123def456...
```

---

### Step 4: Install Dependencies

```bash
cd /Users/cirwel/projects/governance-mcp-v1
pip install openai
```

---

### Step 5: Test Configuration

**Quick test script:**

```bash
# Test if environment variables are set
echo "Endpoint: $NGROK_AI_ENDPOINT"
echo "API Key: ${NGROK_API_KEY:0:10}..."  # Show first 10 chars only

# Test OpenAI SDK import
python3 -c "from openai import OpenAI; print('✅ OpenAI SDK installed')"
```

**Expected output:**
```
Endpoint: https://your-gateway.ngrok.ai/v1
API Key: 2abc123def...
✅ OpenAI SDK installed
```

---

### Step 6: Restart MCP Server

```bash
# Stop existing server
pkill -f mcp_server_sse.py

# Start with new environment
cd /Users/cirwel/projects/governance-mcp-v1
python src/mcp_server_sse.py --port 8765
```

---

### Step 7: Test `call_model` Tool

**From an agent or test script:**

```python
# Test basic call
call_model(
    prompt="Hello, what is 2+2?",
    model="gemini-flash"
)
```

**Expected response:**
```json
{
  "success": true,
  "response": "2+2 equals 4.",
  "model_used": "gemini-flash",
  "tokens_used": 10,
  "energy_cost": 0.01,
  "routed_via": "ngrok.ai"
}
```

---

## Troubleshooting

### "MISSING_CONFIG" Error

**Problem:** `NGROK_AI_ENDPOINT` or `NGROK_API_KEY` not set

**Fix:**
```bash
# Check if set
env | grep NGROK

# If not set, add to .env or export
export NGROK_AI_ENDPOINT=https://your-gateway.ngrok.ai/v1
export NGROK_API_KEY=your_key
```

### "DEPENDENCY_MISSING" Error

**Problem:** OpenAI SDK not installed

**Fix:**
```bash
pip install openai
```

### "MODEL_NOT_AVAILABLE" Error

**Problem:** Model not configured in gateway

**Fix:**
1. Check ngrok.ai dashboard
2. Verify model is added to gateway
3. Try default: `gemini-flash`

### Gateway Not Found

**Problem:** ngrok.ai dashboard not accessible

**Alternative:** Use direct provider endpoints:

```bash
# For Gemini (direct)
export NGROK_AI_ENDPOINT=https://generativelanguage.googleapis.com/v1beta
export NGROK_API_KEY=your_google_ai_studio_key

# For OpenAI (direct)
export NGROK_AI_ENDPOINT=https://api.openai.com/v1
export NGROK_API_KEY=your_openai_key
```

---

## What You Actually Need

**Minimum setup:**
1. ✅ ngrok account (free)
2. ✅ ngrok API key (from dashboard)
3. ✅ ngrok.ai gateway endpoint OR direct provider endpoint
4. ✅ Environment variables set
5. ✅ OpenAI SDK installed (`pip install openai`)

**That's it!** The `call_model` tool will work once these are configured.

---

## Quick Reference

**Environment Variables:**
```bash
NGROK_AI_ENDPOINT=https://your-gateway.ngrok.ai/v1  # Gateway URL
NGROK_API_KEY=your_ngrok_api_key                    # From dashboard
```

**Test Command:**
```bash
python3 -c "import os; print('Endpoint:', os.getenv('NGROK_AI_ENDPOINT', 'NOT SET'))"
```

**Restart Server:**
```bash
pkill -f mcp_server_sse.py && python src/mcp_server_sse.py --port 8765
```

---

## Next Steps

1. ✅ Get ngrok account & API key
2. ✅ Set up ngrok.ai gateway (or use direct endpoints)
3. ✅ Configure environment variables
4. ✅ Install dependencies (`pip install openai`)
5. ✅ Restart MCP server
6. ✅ Test `call_model` tool

---

## Questions?

**If ngrok.ai dashboard doesn't exist yet:**
- Use direct provider endpoints (see "Gateway Not Found" above)
- The tool will work with direct endpoints too

**If you're stuck:**
- Check environment variables: `env | grep NGROK`
- Check server logs: `tail -f data/logs/mcp_sse.log`
- Test OpenAI SDK: `python3 -c "from openai import OpenAI; print('OK')"`

---

**Status:** ✅ Ready to configure  
**Difficulty:** Easy (5 minutes if you have ngrok account)

