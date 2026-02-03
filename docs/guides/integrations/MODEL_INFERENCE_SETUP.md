# Model Inference Tool Setup Guide

**Created:** January 1, 2026  
**Status:** Implementation Complete  
**Priority:** High

---

## Overview

The `call_model` tool provides free/low-cost LLM access for agents via ngrok.ai routing.

**Features:**
- ✅ Free tier models (Gemini Flash, Llama 3.1 8B)
- ✅ Automatic failover via ngrok.ai
- ✅ Cost optimization
- ✅ Usage tracked in EISV (Energy consumption)
- ✅ Privacy controls (local routing option)

---

## Quick Start

### 1. Set Up ngrok.ai Gateway

**In ngrok.ai dashboard:**
1. Create AI Gateway endpoint
2. Add providers:
   - Google (Gemini Flash) - free tier
   - Ollama (local) - if available: `http://localhost:11434`
3. Configure routing:
   - Default: Gemini Flash
   - Fallback: Ollama (if local available)
4. Get endpoint URL: `https://your-endpoint.ngrok.ai/v1`

### 2. Configure Environment Variables

**Add to `.env` or environment:**
```bash
# ngrok.ai endpoint (required)
NGROK_AI_ENDPOINT=https://your-endpoint.ngrok.ai/v1

# API key (required)
NGROK_API_KEY=your_ngrok_api_key

# Fallback (optional - if not using ngrok.ai gateway)
OPENAI_API_KEY=your_openai_key
```

### 3. Install Dependencies

```bash
pip install openai
```

### 4. Restart MCP Server

```bash
# Restart SSE server
pkill -f mcp_server_sse.py
python src/mcp_server_sse.py --port 8765
```

---

## Usage

### Basic Example

```python
# Agent calls:
call_model(
    prompt="What is thermodynamic governance?",
    model="gemini-flash"
)

# Response:
{
  "success": true,
  "response": "Thermodynamic governance is...",
  "model_used": "gemini-flash",
  "tokens_used": 150,
  "energy_cost": 0.01,
  "routed_via": "ngrok.ai"
}
```

### Privacy Mode (Local Routing)

```python
# Force local routing for sensitive data
call_model(
    prompt="Analyze this governance metric",
    privacy="local"  # Routes to Ollama (stays local)
)
```

### Task Types

```python
# Reasoning
call_model(
    prompt="Analyze this code for bugs",
    task_type="reasoning"
)

# Generation
call_model(
    prompt="Write a summary of...",
    task_type="generation"
)

# Analysis
call_model(
    prompt="What patterns do you see?",
    task_type="analysis"
)
```

---

## Models Available

| Model | Cost | Speed | Use Case |
|-------|------|-------|----------|
| **gemini-flash** | Free | Fast | Default, general purpose |
| **llama-3.1-8b** | Free (local) | Medium | Privacy-sensitive, local only |
| **gemini-pro** | Low-cost | Fast | Higher quality when needed |

---

## Energy Tracking

**How it works:**
- Each model call consumes Energy (EISV metric)
- Free models: +0.01 Energy per call
- Low-cost models: +0.02 Energy per call
- High usage → Higher Energy → Natural self-regulation

**Check Energy:**
```python
get_governance_metrics()
# Returns: E, I, S, V metrics including Energy from model calls
```

---

## ngrok.ai Configuration

### Basic Setup

**In ngrok.ai dashboard:**

```yaml
providers:
  - provider: google
    endpoint: https://generativelanguage.googleapis.com
    models: ["gemini-flash", "gemini-pro"]
    priority: 1  # Free tier first
  
  - provider: ollama
    endpoint: http://localhost:11434
    models: ["llama-3.1-8b", "mistral"]
    priority: 2  # Local fallback
```

### Privacy Policies

**Route sensitive operations to local:**

```yaml
policies:
  - name: governance_sensitive
    route_to: ollama
    models: ["llama-3.1-8b"]
    triggers: ["eisv", "governance", "agent_id"]
  
  - name: general
    route_to: gemini-flash
    cost_optimize: true
```

---

## Troubleshooting

### "DEPENDENCY_MISSING" Error

**Problem:** OpenAI SDK not installed

**Solution:**
```bash
pip install openai
```

### "MISSING_CONFIG" Error

**Problem:** NGROK_API_KEY or OPENAI_API_KEY not set

**Solution:**
```bash
export NGROK_API_KEY=your_key
# Or
export OPENAI_API_KEY=your_key
```

### "MODEL_NOT_AVAILABLE" Error

**Problem:** Requested model not available

**Solution:**
- Try default model: `gemini-flash`
- Check ngrok.ai dashboard for available models
- Verify Ollama is running (if using local)

### "TIMEOUT" Error

**Problem:** Model call took too long

**Solution:**
- Reduce `max_tokens` parameter
- Try a simpler prompt
- Check network connectivity

---

## Testing

### Test 1: Basic Inference

```python
call_model(
    prompt="Hello, how are you?",
    model="gemini-flash"
)
```

**Expected:** Response returned, Energy tracked

### Test 2: Failover

```python
# Simulate Gemini outage
# Call should failover to Ollama
call_model(
    prompt="Test failover",
    model="gemini-flash"
)
```

**Expected:** Routed to Ollama (if available)

### Test 3: Privacy Mode

```python
call_model(
    prompt="Sensitive data",
    privacy="local"
)
```

**Expected:** Routed to Ollama (local only)

---

## Next Steps

1. **Set up ngrok.ai gateway** (dashboard configuration)
2. **Configure environment variables** (NGROK_AI_ENDPOINT, NGROK_API_KEY)
3. **Test with agents** (have agents call models)
4. **Monitor usage** (check Energy tracking in governance metrics)

---

## Related Documentation

- [HF Skills + ngrok.ai Integration](../integration/HF_SKILLS_NGROK_AI_INTEGRATION.md)
- [HF Skills + ngrok.ai Recommendations](../integration/HF_SKILLS_NGROK_AI_RECOMMENDATIONS.md)
- [ngrok.ai Deployment Guide](NGROK_DEPLOYMENT.md)

---

**Status:** ✅ Implementation Complete - Ready for Testing  
**Next:** Set up ngrok.ai gateway and test with agents

