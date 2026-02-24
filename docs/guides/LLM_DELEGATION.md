# LLM Delegation Guide

**Last Updated:** 2026-02-20 (v2.7.0)

UNITARES provides LLM delegation capabilities for agents to call local or cloud models for reasoning, analysis, and dialectic synthesis.

---

## Quick Start

### Check Ollama is Running

```bash
# Test Ollama
curl http://localhost:11434/api/tags

# If not running, start it
ollama serve
```

### Basic Model Call

```python
# Call local LLM via Ollama
call_model(
    prompt="Analyze this code for potential bugs",
    provider="ollama",  # Force local
    max_tokens=500
)
```

---

## Provider Options

| Provider | Cost | Privacy | Setup |
|----------|------|---------|-------|
| **ollama** | Free | Local | `ollama serve` |
| **hf** | Free tier | Cloud | Set `HF_TOKEN` |
| **gemini** | Free tier | Cloud | Set `GOOGLE_AI_API_KEY` |

### Provider Configuration

```bash
# For Hugging Face (free tier, many models)
export HF_TOKEN=your_token  # Get from: https://huggingface.co/settings/tokens

# For Google Gemini (free tier, fast)
export GOOGLE_AI_API_KEY=your_key  # Get from: https://aistudio.google.com/app/apikey

# For local-only (recommended for privacy)
# Just run: ollama serve
```

---

## Usage Patterns

### Direct Model Call

```python
# Auto-select best available provider
call_model(
    prompt="What is the time complexity of quicksort?",
    task_type="reasoning"
)

# Force local (Ollama)
call_model(
    prompt="Analyze this sensitive governance metric",
    provider="ollama",
    privacy="local"
)

# Specific model via HuggingFace
call_model(
    prompt="Generate a summary",
    provider="hf",
    model="deepseek-ai/DeepSeek-R1:fastest"
)
```

### Dialectic Recovery

When stuck or paused, use LLM-assisted dialectic for structured reflection:

```python
# Single-agent dialectic (no peer reviewer needed)
llm_assisted_dialectic(
    root_cause="Agent memory consumption increasing over time",
    proposed_conditions=["Run memory profiler", "Check for circular references"],
    reasoning="Memory leak suspected in state management"
)

# Returns:
# {
#   "recommendation": "RESUME",  # or COOLDOWN, ESCALATE
#   "thesis": {...},
#   "antithesis": {
#     "concerns": "...",
#     "counter_reasoning": "...",
#     "suggested_conditions": "..."
#   },
#   "synthesis": {
#     "agreed_root_cause": "...",
#     "merged_conditions": "...",
#     "reasoning": "..."
#   }
# }
```

### Knowledge Graph Synthesis

Search with automatic synthesis of results:

```python
search_knowledge_graph(
    query="EISV dynamics",
    synthesize=true,  # LLM synthesizes key insights
    limit=10
)
# Returns discoveries + synthesis.text with 2-3 key insights
```

---

## Models Available

### Via Ollama (Local)

| Model | Quality | Speed | Default |
|-------|---------|-------|---------|
| `gemma3:27b` | Good | Fast | ✅ Default for dialectic |
| `llama3:70b` | Excellent | Slower | Complex reasoning |
| `llama3:8b` | Decent | Very fast | Simple tasks |

Set default: `export UNITARES_LLM_MODEL=gemma3:27b`

### Via HuggingFace

| Model | Type | Notes |
|-------|------|-------|
| `deepseek-ai/DeepSeek-R1:fastest` | Reasoning | Default HF model |
| `hf:model-name:fastest` | Various | Add `:fastest` for auto-provider |

### Via Google

| Model | Cost | Speed |
|-------|------|-------|
| `gemini-flash` | Free tier | Very fast |
| `gemini-pro` | Low cost | Fast |

---

## Energy Tracking

Model calls consume Energy (EISV metric):

- Free models (gemini-flash, llama): +0.01 Energy
- Low-cost models (gemini-pro): +0.02 Energy
- High usage → Higher Energy → Natural self-regulation

Check your Energy:
```python
get_governance_metrics()
# Returns E, I, S, V including model call Energy
```

---

## Internal Delegation (Handler-to-Handler)

For building tools that use LLM internally:

```python
from src.mcp_handlers.llm_delegation import (
    call_local_llm,       # Base LLM call
    generate_antithesis,  # Dialectic antithesis
    generate_synthesis,   # Dialectic synthesis
    run_full_dialectic,   # Complete dialectic flow
    synthesize_results,   # Synthesize search results
    is_llm_available      # Check Ollama availability
)

# Example: Custom synthesis
result = await call_local_llm(
    prompt="Summarize these findings: ...",
    max_tokens=300,
    temperature=0.7,
    timeout=15.0
)
```

---

## Troubleshooting

### "LLM_UNAVAILABLE" Error

```bash
# Check Ollama
curl http://localhost:11434/api/tags

# Start if needed
ollama serve

# Pull a model if needed
ollama pull gemma3:27b
```

### "MISSING_CONFIG" Error

```bash
# Set at least one provider
export HF_TOKEN=your_token
# Or
export GOOGLE_AI_API_KEY=your_key
# Or just use Ollama (no config needed)
```

### Slow Responses

- Reduce `max_tokens` (default 500)
- Use faster model: `gemma3:27b` instead of `llama3:70b`
- For synthesis: timeout is 12s (optional feature)

---

## Related Docs

- [CIRCUIT_BREAKER_DIALECTIC.md](../CIRCUIT_BREAKER_DIALECTIC.md) — Dialectic recovery protocol
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Common issues
- [START_HERE.md](START_HERE.md) — Agent onboarding
