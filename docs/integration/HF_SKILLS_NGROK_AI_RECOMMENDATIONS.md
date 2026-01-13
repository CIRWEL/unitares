# HF Skills + ngrok.ai Integration - Concrete Recommendations

**Created:** January 1, 2026  
**Status:** Implementation Plan  
**Priority:** High

---

## Recommendations (Based on System Architecture)

### 1. HF Skills Integration Approach

**Recommendation:** Start with **direct API calls** to HF Skills, not local execution.

**Why:**
- Simpler implementation (no local skill installation)
- Works immediately (no environment setup)
- Can add local fallback later if needed
- HF Skills API is well-documented

**Which Skills to Start With:**
1. **`hf-llm-trainer`** - Most valuable for fine-tuning
2. **`hf-embeddings-trainer`** - Directly improves your semantic search
3. Skip others for now (can add later)

**Implementation:**
- Call HF Skills via their API/interface
- Store training artifacts in knowledge graph
- Models uploaded to HF Hub (private repos)

---

### 2. ngrok.ai Model Selection

**Recommendation:** **Hybrid approach** - System auto-selects, agents can override.

**Default Strategy:**
1. **Free tier first:** Gemini Flash (fast, free)
2. **Local fallback:** Llama 3.1 8B via Ollama (if available)
3. **Low-cost fallback:** Gemini Pro (if free tier exhausted)
4. **Trained models:** Custom models from HF Skills (if available)

**Agent Override:**
- Agents can specify `model="claude-haiku"` if they want specific model
- System respects agent choice but logs for cost tracking

**Why This Works:**
- Cost-optimized by default (free → cheap → expensive)
- Agents have control when needed
- Natural self-regulation (agents learn which models work best)

---

### 3. Usage Tracking in EISV

**Recommendation:** Track as **Energy consumption** based on estimated cost.

**Formula:**
```python
# Estimate cost per call
if model == "gemini-flash":
    energy_cost = tokens * 0.00001  # Very cheap
elif model == "llama-3.1-8b":
    energy_cost = tokens * 0.000005  # Local, minimal cost
elif model == "gemini-pro":
    energy_cost = tokens * 0.0001  # Low-cost tier
else:
    energy_cost = tokens * 0.0002  # Default estimate

# Update Energy
monitor.update_energy(energy_cost)
```

**Why:**
- High AI usage → Higher Energy → Natural self-regulation
- Agents learn to use efficiently
- Fits existing EISV dynamics
- No separate metric needed

**Alternative:** If cost tracking is too complex, just increment Energy by fixed amount per call (e.g., +0.01 per call).

---

### 4. Privacy & Security

**Recommendation:** **Route sensitive operations to local Ollama** via ngrok.ai policies.

**What Stays Local:**
- Governance metrics (EISV) - never sent to cloud
- Agent identities - never sent to cloud
- Sensitive discoveries - route to Ollama

**What Can Go to Cloud:**
- General reasoning queries
- Discovery summaries (non-sensitive)
- Model training data (anonymized)

**Implementation:**
```yaml
# ngrok.ai policies
policies:
  - name: governance_sensitive
    route_to: ollama
    models: ["llama-3.1-8b"]
    triggers: ["eisv", "governance", "agent_id"]
  
  - name: general
    route_to: gemini-flash
    cost_optimize: true
```

**Agent Choice:**
- Agents can specify `privacy="local"` to force Ollama routing
- System respects privacy flags

---

## Implementation Plan

### Phase 1: Model Inference Tool (Week 1) ⭐⭐⭐

**Goal:** Get basic model inference working.

**Steps:**
1. Set up ngrok.ai gateway
   - Create endpoint in dashboard
   - Add Gemini Flash (free tier)
   - Add Ollama (local fallback)
   - Test routing

2. Create `call_model` tool
   - Basic inference tool
   - ngrok.ai routing
   - Free tier models only
   - Simple usage tracking (+0.01 Energy per call)

3. Test with agents
   - Have agents call models
   - Verify routing works
   - Check Energy tracking

**Deliverable:** Agents can call free models for reasoning/generation.

**Files to Create:**
- `src/mcp_handlers/model_inference.py`
- `docs/guides/MODEL_INFERENCE.md`

**Configuration:**
```bash
# .env
NGROK_AI_ENDPOINT=https://your-endpoint.ngrok.ai/v1
NGROK_API_KEY=your_key
```

---

### Phase 2: HF Skills Integration (Week 2) ⭐⭐

**Goal:** Add model training capabilities.

**Steps:**
1. Research HF Skills API
   - How to call programmatically
   - Authentication/access
   - Training workflow

2. Create `train_model` tool
   - Uses hf-llm-trainer skill
   - Tracks training progress
   - Stores artifacts in KG

3. Create `fine_tune_embeddings` tool
   - Uses hf-embeddings-trainer skill
   - Fine-tunes on KG data
   - Updates embeddings service

**Deliverable:** Agents can train models using HF Skills.

**Files to Create:**
- `src/mcp_handlers/hf_skills.py`
- `docs/guides/HF_SKILLS.md`

---

### Phase 3: Enhanced Features (Week 3) ⭐

**Goal:** Make existing AI features opt-in tools.

**Steps:**
1. Convert `ai_synthesis.py` to MCP tool
2. Convert `ai_knowledge_search.py` to MCP tool
3. Make them opt-in (agents request when needed)
4. Integrate with knowledge graph

**Deliverable:** AI features available as opt-in tools.

---

## Starting Point: Phase 1 Implementation

### Step 1: Set Up ngrok.ai Gateway

**In ngrok.ai dashboard:**
1. Create AI Gateway endpoint
2. Add providers:
   - Google (Gemini Flash) - free tier
   - Ollama (local) - if available
3. Configure routing:
   - Default: Gemini Flash
   - Fallback: Ollama
4. Get endpoint URL: `https://your-endpoint.ngrok.ai/v1`

### Step 2: Create Model Inference Tool

**File:** `src/mcp_handlers/model_inference.py`

```python
"""
Model Inference Tool - Free/low-cost LLM access for agents.

Uses ngrok.ai for routing, failover, and cost optimization.
"""
from typing import Dict, Any, Sequence
from mcp.types import TextContent
import os

from .utils import success_response, error_response
from .decorators import mcp_tool
from src.logging_utils import get_logger

logger = get_logger(__name__)

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


@mcp_tool("call_model", timeout=30.0)
async def handle_call_model(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Call a free/low-cost LLM for reasoning, generation, or analysis.
    
    Models available:
    - gemini-flash (free, fast) - default
    - llama-3.1-8b (via Ollama, free) - if local available
    - gemini-pro (low-cost) - if free tier exhausted
    
    Routing via ngrok.ai:
    - Automatic failover
    - Cost optimization
    - Rate limit handling
    
    Usage tracked in EISV (Energy consumption).
    """
    if not OPENAI_AVAILABLE:
        return [error_response(
            "OpenAI SDK required. Install with: pip install openai",
            error_code="DEPENDENCY_MISSING"
        )]
    
    prompt = arguments.get("prompt")
    if not prompt:
        return [error_response(
            "Missing required parameter: 'prompt'",
            error_code="MISSING_PARAMETER"
        )]
    
    model = arguments.get("model", "gemini-flash")
    task_type = arguments.get("task_type", "reasoning")  # reasoning, generation, analysis
    
    # Get ngrok.ai endpoint
    base_url = os.getenv("NGROK_AI_ENDPOINT", "https://api.openai.com/v1")
    api_key = os.getenv("NGROK_API_KEY") or os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        return [error_response(
            "NGROK_API_KEY or OPENAI_API_KEY required",
            error_code="MISSING_CONFIG"
        )]
    
    try:
        client = OpenAI(base_url=base_url, api_key=api_key)
        
        # Call model via ngrok.ai
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=arguments.get("max_tokens", 500),
            temperature=arguments.get("temperature", 0.7)
        )
        
        result_text = response.choices[0].message.content
        tokens_used = response.usage.total_tokens if hasattr(response, 'usage') else 0
        
        # Estimate Energy cost (simple: +0.01 per call, can refine later)
        energy_cost = 0.01
        
        # TODO: Update Energy in governance monitor
        # monitor.update_energy(energy_cost)
        
        return success_response({
            "response": result_text,
            "model_used": response.model if hasattr(response, 'model') else model,
            "tokens_used": tokens_used,
            "energy_cost": energy_cost,
            "routed_via": "ngrok.ai" if "ngrok" in base_url.lower() else "direct"
        })
        
    except Exception as e:
        logger.error(f"Model inference failed: {e}")
        return [error_response(
            f"Model inference failed: {e}",
            error_code="INFERENCE_ERROR",
            recovery={
                "action": "Check ngrok.ai configuration and model availability",
                "related_tools": ["health_check", "get_connection_status"]
            }
        )]
```

### Step 3: Register Tool

**File:** `src/mcp_handlers/__init__.py`

Add:
```python
from .model_inference import handle_call_model

# In tool registry:
"call_model": handle_call_model,
```

### Step 4: Add to Tool Schemas

**File:** `src/tool_schemas.py`

Add schema definition for `call_model`.

---

## Testing Plan

### Test 1: Basic Inference
```python
# Agent calls:
call_model(
    prompt="What is thermodynamic governance?",
    model="gemini-flash"
)

# Expected:
# - Response returned
# - Model used: gemini-flash
# - Routed via ngrok.ai
# - Energy tracked
```

### Test 2: Failover
```python
# Simulate Gemini outage
# Agent calls:
call_model(
    prompt="Analyze this code",
    model="gemini-flash"
)

# Expected:
# - ngrok.ai routes to Ollama (fallback)
# - Response returned
# - Failover logged
```

### Test 3: Cost Tracking
```python
# Agent makes 10 calls
# Check governance metrics:
get_governance_metrics()

# Expected:
# - Energy increased by ~0.10 (10 calls * 0.01)
# - Usage tracked
```

---

## Next Steps

1. **This Week:**
   - Set up ngrok.ai gateway
   - Implement `call_model` tool
   - Test with agents

2. **Next Week:**
   - Research HF Skills API
   - Plan training tool implementation

3. **Following Week:**
   - Implement HF Skills integration
   - Test training workflows

---

**Status:** Ready to Implement  
**Start With:** Phase 1 - Model Inference Tool

