# Fix: Server Won't Load

**Created:** January 1, 2026  
**Issue:** Server won't start/load  
**Status:** Diagnostic Guide

---

## Quick Diagnostics

### Check 1: Is Server Running?

```bash
ps aux | grep mcp_server_sse | grep -v grep
```

**If running:** Check logs for errors  
**If not running:** Try starting manually

---

### Check 2: Port Availability

```bash
lsof -ti:8765
```

**If port in use:** Kill existing process or use different port  
**If port free:** Server should be able to start

---

### Check 3: Check Logs

```bash
# Check various log locations
tail -50 data/mcp_server_sse.log
tail -50 data/logs/mcp_sse.log
tail -50 logs/launchd.log
```

**Look for:**
- Import errors
- Connection errors
- Configuration errors
- Gateway connection failures

---

### Check 4: Environment Variables

```bash
echo "NGROK_AI_ENDPOINT: $NGROK_AI_ENDPOINT"
echo "HF_TOKEN: ${HF_TOKEN:0:20}..."
echo "NGROK_API_KEY: ${NGROK_API_KEY:0:10}..."
```

**Verify:** All required variables are set

---

## Common Issues

### Issue 1: Gateway Connection Failure on Startup

**Problem:** Server tries to connect to gateway on startup and fails

**Fix:** Server shouldn't connect to gateway on startup - it only connects when `call_model` is called.

**Check:** Look for gateway connection attempts in logs.

---

### Issue 2: Missing Dependencies

**Problem:** OpenAI SDK or other dependencies missing

**Fix:**
```bash
pip install openai
pip install -r requirements.txt
```

---

### Issue 3: Environment Variables Not Loaded

**Problem:** `.env` file not loaded when server starts

**Fix:**
```bash
# Load environment manually
source .env

# Or start server with explicit env
cd /Users/cirwel/projects/governance-mcp-v1
source .env 2>/dev/null || true
python src/mcp_server_sse.py --port 8765
```

---

### Issue 4: Port Already in Use

**Problem:** Another process using port 8765

**Fix:**
```bash
# Find and kill process
lsof -ti:8765 | xargs kill -9

# Or use different port
python src/mcp_server_sse.py --port 8766
```

---

### Issue 5: Import Errors

**Problem:** Python can't import modules

**Fix:**
```bash
# Check Python path
python3 -c "import sys; print(sys.path)"

# Install dependencies
pip install -r requirements.txt

# Check imports
python3 -c "from src.mcp_handlers.model_inference import handle_call_model; print('OK')"
```

---

## Step-by-Step Recovery

### Step 1: Stop All Server Processes

```bash
pkill -f mcp_server_sse.py
sleep 2
```

---

### Step 2: Check Environment

```bash
cd /Users/cirwel/projects/governance-mcp-v1

# Load environment
source .env 2>/dev/null || true

# Verify
echo "NGROK_AI_ENDPOINT: $NGROK_AI_ENDPOINT"
echo "HF_TOKEN: ${HF_TOKEN:0:20}..."
```

---

### Step 3: Try Starting Manually

```bash
cd /Users/cirwel/projects/governance-mcp-v1
source .env 2>/dev/null || true
python src/mcp_server_sse.py --port 8765
```

**Watch for errors** - this will show what's failing.

---

### Step 4: Check for Specific Errors

**If you see errors, note them:**
- Import errors → Install dependencies
- Connection errors → Check gateway/network
- Config errors → Check environment variables
- Port errors → Change port or kill existing process

---

## Fallback: Disable Gateway Temporarily

**If gateway is causing startup issues:**

```bash
# Remove gateway endpoint (use direct routing)
unset NGROK_AI_ENDPOINT

# Keep HF token for direct routing
export HF_TOKEN=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

# Update .env
sed -i '' '/NGROK_AI_ENDPOINT/d' .env

# Start server
python src/mcp_server_sse.py --port 8765
```

**This bypasses gateway and routes directly to Hugging Face.**

---

## What "Won't Load" Means

**Clarify:**
1. **Server won't start?** (process doesn't start)
2. **Server starts but crashes?** (starts then exits)
3. **Server runs but gateway calls fail?** (server OK, gateway broken)
4. **Server runs but tools don't work?** (server OK, tool issue)

**Each has different fixes.**

---

## Quick Test: Minimal Start

**Try starting with minimal config:**

```bash
# Stop everything
pkill -f mcp_server_sse.py

# Start fresh
cd /Users/cirwel/projects/governance-mcp-v1
python src/mcp_server_sse.py --port 8765 --verbose
```

**Watch output for errors.**

---

**Status:** Diagnostic guide ready  
**Next:** Run diagnostics to identify specific issue

