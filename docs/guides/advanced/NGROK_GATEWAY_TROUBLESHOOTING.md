# Gateway Server Troubleshooting

**Created:** January 1, 2026  
**Issue:** Server won't load after gateway configuration  
**Status:** Diagnostic Guide

---

## Quick Diagnostics

### Check 1: Server Process

```bash
# Check if server is running
ps aux | grep mcp_server_sse

# Check port 8765
lsof -ti:8765
```

### Check 2: Server Logs

```bash
# View recent logs
tail -50 data/logs/mcp_sse.log

# Or check system logs
tail -50 ~/Library/Logs/governance-mcp-sse.log
```

### Check 3: Environment Variables

```bash
# Check if gateway URL is set
echo $NGROK_AI_ENDPOINT

# Check if HF token is set
echo $HF_TOKEN | head -c 20
```

### Check 4: Gateway Status

```bash
# Test gateway endpoint
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

---

## Common Issues

### Issue 1: Gateway Configuration Error

**Problem:** Traffic Policy has syntax error

**Fix:**
1. Go to: Gateway → Traffic Policy → Edit
2. Check YAML syntax
3. Verify `actions` array structure
4. Remove any invalid fields

**Test:**
```bash
# Validate YAML (if you have yq installed)
yq eval . traffic-policy.yaml
```

---

### Issue 2: Missing API Key

**Problem:** `NGROK_API_KEY` not set

**Fix:**
```bash
# Set API key
export NGROK_API_KEY=your_ngrok_api_key

# Add to .env
echo "NGROK_API_KEY=your_ngrok_api_key" >> .env

# Restart server
```

---

### Issue 3: Gateway Not Responding

**Problem:** Gateway endpoint returns error

**Fix:**
1. Check gateway status in dashboard
2. Verify Traffic Policy is saved correctly
3. Check provider configuration
4. Test gateway directly:

```bash
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

---

### Issue 4: Server Startup Error

**Problem:** Server fails to start

**Fix:**
1. Check Python dependencies:
   ```bash
   pip install openai
   ```

2. Check for import errors:
   ```bash
   python3 -c "from openai import OpenAI; print('OK')"
   ```

3. Try starting server manually:
   ```bash
   cd /Users/cirwel/projects/governance-mcp-v1
   python src/mcp_server_sse.py --port 8765
   ```

---

### Issue 5: Environment Variables Not Loaded

**Problem:** `.env` file not loaded

**Fix:**
1. Check `.env` file exists:
   ```bash
   cat .env | grep -E "NGROK|HF_TOKEN"
   ```

2. Load manually:
   ```bash
   export $(cat .env | grep -v '^#' | xargs)
   ```

3. Or restart server with environment:
   ```bash
   source .env
   python src/mcp_server_sse.py --port 8765
   ```

---

## Step-by-Step Recovery

### Step 1: Check What's Wrong

```bash
# 1. Check server status
ps aux | grep mcp_server_sse

# 2. Check logs
tail -50 data/logs/mcp_sse.log

# 3. Check environment
env | grep -E "NGROK|HF_TOKEN"

# 4. Test gateway
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

### Step 2: Fix Configuration

**If gateway config is wrong:**
1. Go to dashboard → Traffic Policy
2. Verify YAML format (use `actions` array)
3. Save

**If environment is wrong:**
1. Check `.env` file
2. Set variables manually
3. Restart server

### Step 3: Restart Server

```bash
# Stop existing server
pkill -f mcp_server_sse.py

# Start fresh
cd /Users/cirwel/projects/governance-mcp-v1
source .env 2>/dev/null || true
python src/mcp_server_sse.py --port 8765
```

---

## Fallback: Use Direct Providers

**If gateway continues to fail, use direct provider routing:**

```bash
# Remove gateway endpoint (use direct routing)
unset NGROK_AI_ENDPOINT

# Keep HF token (direct routing)
export HF_TOKEN=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

# Restart server
pkill -f mcp_server_sse.py
python src/mcp_server_sse.py --port 8765
```

**This bypasses the gateway and routes directly to Hugging Face.**

---

## Diagnostic Commands

**Run these to diagnose:**

```bash
# 1. Server status
ps aux | grep mcp_server_sse | grep -v grep

# 2. Port check
lsof -ti:8765

# 3. Logs
tail -50 data/logs/mcp_sse.log 2>/dev/null || echo "No logs"

# 4. Environment
echo "NGROK_AI_ENDPOINT: $NGROK_AI_ENDPOINT"
echo "HF_TOKEN: ${HF_TOKEN:0:20}..."
echo "NGROK_API_KEY: ${NGROK_API_KEY:0:10}..."

# 5. Gateway test
curl -s https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer ${NGROK_API_KEY:-test}" | head -c 200

# 6. Python imports
python3 -c "from openai import OpenAI; print('OpenAI SDK: OK')" 2>&1
```

---

## Quick Fix: Restart Everything

```bash
# 1. Stop server
pkill -f mcp_server_sse.py

# 2. Load environment
cd /Users/cirwel/projects/governance-mcp-v1
source .env 2>/dev/null || true

# 3. Verify environment
echo "NGROK_AI_ENDPOINT: $NGROK_AI_ENDPOINT"
echo "HF_TOKEN: ${HF_TOKEN:0:20}..."

# 4. Start server
python src/mcp_server_sse.py --port 8765 &
```

---

**Status:** Diagnostic guide ready  
**Next:** Run diagnostics to identify issue

