# AI-Powered Governance Features

## Overview

This document describes AI-powered features that enhance the governance MCP system using ngrok.ai for intelligent provider routing.

## Why ngrok.ai Makes These Features Better

### **Provider Routing Strategy**

Each feature uses different AI models optimally:

| Feature | Primary Model | Fallback | Cost-Optimized | Why |
|---------|--------------|----------|----------------|-----|
| **Dialectic Synthesis** | Claude Sonnet | GPT-4o | DeepSeek-R1 | Best reasoning, critical decisions |
| **Knowledge Search** | OpenAI Embeddings | Local model | - | Cheapest embeddings ($0.00002/query) |
| **Behavior Analysis** | GPT-4o | Claude | GPT-4o-mini | Good analysis, frequent use |
| **Circuit Breaker Prediction** | GPT-4o-mini | GPT-4o | - | Very cheap, called often |

### **Automatic Failover Scenarios**

```
Scenario 1: OpenAI Outage
├─ Dialectic synthesis request sent
├─ OpenAI timeout (30s)
└─ ngrok.ai auto-routes → Claude Sonnet
   └─ Dialectic continues (no downtime)

Scenario 2: Rate Limit Hit
├─ 10 agents analyzing behavior simultaneously
├─ OpenAI rate limit reached
└─ ngrok.ai distributes load:
   ├─ 5 requests → OpenAI key #1
   ├─ 3 requests → OpenAI key #2
   └─ 2 requests → Claude (overflow)

Scenario 3: Cost Optimization
├─ Batch analysis of 100 agents
├─ Non-critical background job
└─ ngrok.ai routes → DeepSeek-R1
   └─ 90% cost savings vs GPT-4
```

---

## Feature 1: Semantic Dialectic Synthesis

### **File**: `src/ai_synthesis.py`

### **What It Does**

Replaces basic word-overlap convergence detection with semantic understanding.

**Current System** (no AI):
```python
# Two proposals must have 60% word overlap to match
conditions_a = ["Reduce complexity to 0.3"]
conditions_b = ["Lower complexity threshold to 30%"]
# ❌ No match (different words)
```

**With AI**:
```python
ai = DialecticAI()
match = ai.semantic_compare_conditions(conditions_a, conditions_b)
# ✅ Match (similarity_score: 0.95)
# suggested_merge: "Set complexity threshold to 0.3"
```

### **Use Cases**

1. **Detect Hidden Agreement**
   - Agents use different terminology but mean the same thing
   - Speeds up dialectic convergence

2. **Suggest Synthesis**
   - When agents are stuck after 3 rounds
   - AI suggests compromise both might accept

3. **Identify Contradictions**
   - Where agents fundamentally disagree
   - Helps focus discussion

### **ngrok.ai Value**

- **Failover**: Claude primary (best reasoning) → GPT-4o fallback
- **Critical path**: Dialectic sessions block agent recovery, can't afford downtime
- **Cost routing**: Use cheaper models for contradiction detection (less critical)

### **Example**

```python
from src.ai_synthesis import create_dialectic_ai

ai = create_dialectic_ai()

# Thesis from paused agent
thesis = {
    "root_cause": "Too many concurrent tasks",
    "proposed_conditions": ["Limit to 5 concurrent tasks"],
    "reasoning": "I was overwhelmed by task switching"
}

# Antithesis from reviewer
antithesis = {
    "observed_metrics": {"risk_score": 0.65, "task_count": 12},
    "concerns": ["5 is too restrictive", "Need gradual reduction"],
    "reasoning": "Dropping to 5 immediately might cause delays"
}

# AI suggests synthesis
synthesis = ai.suggest_synthesis(thesis, antithesis)
print(synthesis)
# {
#   "suggested_conditions": [
#     "Reduce to 8 tasks immediately",
#     "Further reduce to 5 after 24h stable operation",
#     "Monitor task completion rate"
#   ],
#   "merged_root_cause": "Task overload with insufficient gradual scaling",
#   "confidence": 0.85,
#   "model_used": "claude-3-5-sonnet"  # via ngrok.ai
# }
```

---

## Feature 2: Semantic Knowledge Graph Search

### **File**: `src/ai_knowledge_search.py`

### **What It Does**

Semantic search over discoveries using embeddings instead of just tag matching.

**Current System**:
```python
# Tag-based search
discoveries = knowledge_graph.search(tags=["auth"])
# Only finds discoveries tagged "auth"
```

**With AI**:
```python
search = SemanticKnowledgeSearch()
results = search.search("authentication problems", discoveries)
# Finds: "login failures", "credential issues", "token errors", "auth"
# Even if not tagged the same way!
```

### **Use Cases**

1. **Natural Language Search**
   - Ask: "What issues did we have with APIs last week?"
   - Get relevant discoveries, even if not tagged "API"

2. **Auto-relate Discoveries**
   - Find conceptually similar issues
   - Better than manual "related_to" tagging

3. **Cluster Analysis**
   - "What are the themes in our discoveries?"
   - Auto-group related issues

### **ngrok.ai Value**

- **Cost**: Embeddings are VERY cheap ($0.00002 per query)
- **Volume**: Can embed thousands of discoveries affordably
- **Fallback**: Local sentence-transformers if OpenAI down (slower but works)

### **Example**

```python
from src.ai_knowledge_search import create_semantic_search
from src.knowledge_graph import DiscoveryNode

search = create_semantic_search()

# Index discoveries
for discovery in all_discoveries:
    search.index_discovery(discovery)

# Natural language search
results = search.search(
    query="Why do agents keep getting paused?",
    discoveries=all_discoveries,
    top_k=5
)

for result in results:
    print(f"Score: {result.relevance_score:.2f}")
    print(f"Discovery: {result.discovery.summary}")
    print(f"Reason: {result.match_reason}\n")

# Output:
# Score: 0.89
# Discovery: Agent hit rate limit during batch processing
# Reason: Semantic similarity: 0.89
#
# Score: 0.82
# Discovery: Circuit breaker triggered due to high risk score
# Reason: Semantic similarity: 0.82
```

---

## Feature 3: Agent Behavior Analysis

### **File**: `src/ai_behavior_analysis.py`

### **What It Does**

Analyzes agent metrics over time to detect patterns and predict issues.

### **Use Cases**

1. **Pattern Detection**
   ```python
   analyzer = AgentBehaviorAnalyzer()
   patterns = analyzer.analyze_agent_trajectory(
       agent_id="agent_123",
       history=agent_governance_history
   )

   # Finds:
   # - "This agent hits circuit breaker every Monday morning"
   # - "Risk score increasing linearly (0.3 → 0.6 over 2 weeks)"
   # - "Coherence drops when working on database tasks"
   ```

2. **Agent Compatibility**
   ```python
   comparison = analyzer.compare_agents(agent_a_history, agent_b_history)

   # Output:
   # {
   #   "compatibility_score": 0.85,
   #   "recommendation": "Excellent dialectic pair - complementary strengths",
   #   "potential_conflicts": ["Different risk tolerance levels"]
   # }
   ```

3. **Early Warning System**
   ```python
   prediction = analyzer.predict_circuit_breaker(
       current_metrics={"risk_score": 0.48, "coherence": 0.52},
       recent_trend=last_10_updates
   )

   # Output:
   # {
   #   "will_trigger": true,
   #   "estimated_time": "2-3 hours at current trajectory",
   #   "confidence": 0.78,
   #   "preventive_actions": ["Reduce task complexity", "Take shorter tasks"]
   # }
   ```

### **ngrok.ai Value**

- **Frequency**: Predictions run every update (100s per day)
- **Cost routing**: Use GPT-4o-mini ($0.15/1M tokens) for predictions
- **Batch analysis**: Route bulk agent analysis to DeepSeek-R1 (very cheap)
- **Critical decisions**: Use Claude for agent compatibility (better reasoning)

---

## Integration with MCP

### **Adding AI Tools to MCP Server**

```python
# In src/mcp_handlers/core.py

from src.ai_synthesis import create_dialectic_ai
from src.ai_knowledge_search import create_semantic_search
from src.ai_behavior_analysis import create_behavior_analyzer

# Initialize AI features (lazy loading)
_dialectic_ai = None
_semantic_search = None
_behavior_analyzer = None

def get_dialectic_ai():
    global _dialectic_ai
    if _dialectic_ai is None:
        _dialectic_ai = create_dialectic_ai()
    return _dialectic_ai

# Add new MCP tools:
# - ai_synthesize_dialectic
# - ai_search_knowledge
# - ai_analyze_behavior
# - ai_predict_circuit_breaker
```

### **Environment Variables**

```bash
# ngrok.ai endpoint (configured in dashboard)
export NGROK_AI_ENDPOINT="https://unitares-ai.ngrok.ai/v1"
export NGROK_API_KEY="your_ngrok_api_key"

# Fallback to direct providers if ngrok unavailable
export OPENAI_API_KEY="your_openai_key"
export ANTHROPIC_API_KEY="your_anthropic_key"
```

---

## Cost Analysis

### **Monthly Cost Estimates** (assuming 10 active agents)

| Feature | Volume | Primary Model | Est. Cost/Month |
|---------|--------|--------------|-----------------|
| Dialectic Synthesis | ~50 sessions | Claude Sonnet | $15 |
| Knowledge Search | ~1000 queries | OpenAI Embeddings | $0.20 |
| Behavior Analysis | ~3000 checks | GPT-4o-mini | $1.50 |
| Circuit Prediction | ~10,000 checks | GPT-4o-mini | $3.00 |
| **Total** | | | **~$20/month** |

### **With ngrok.ai Cost Optimization**

- Route non-critical to DeepSeek: **-60% ($8/month savings)**
- Batch embeddings: **-20% ($0.04 savings)**
- **Optimized total: ~$12/month**

### **Without ngrok.ai (if manual provider switching)**

- All on GPT-4: **$95/month** (8x more expensive)
- No failover: **Downtime cost >> $20**

---

## Observability

### **Prometheus Metrics** (add to `mcp_server_sse.py`)

```python
# AI feature metrics
AI_CALLS_TOTAL = Counter('unitares_ai_calls_total', 'AI calls', ['feature', 'model'])
AI_CALL_DURATION = Histogram('unitares_ai_call_duration_seconds', 'AI latency', ['feature'])
AI_COST_ESTIMATE = Counter('unitares_ai_cost_estimate_usd', 'Est. AI cost', ['model'])
AI_FAILOVERS = Counter('unitares_ai_failovers_total', 'Provider failovers', ['from', 'to'])
```

### **ngrok Dashboard Integration**

ngrok.ai dashboard shows:
- Which models are actually used
- Failover events
- Cost per agent
- Rate limit events
- Latency distribution

Combines with your existing Prometheus metrics for full observability.

---

## Next Steps

1. **Set up ngrok.ai**
   - Configure endpoint in dashboard
   - Add provider API keys
   - Test failover

2. **Start with Feature 1** (Dialectic Synthesis)
   - Highest impact
   - Easy to test with existing dialectic sessions

3. **Add Observability**
   - Track AI costs
   - Monitor failover events
   - Measure improvement in dialectic convergence time

4. **Expand Gradually**
   - Add knowledge search
   - Add behavior analysis
   - Tune model routing based on real costs

---

## FAQ

### **Q: What if I don't use ngrok.ai?**
A: Features work with direct OpenAI/Anthropic connections. You lose:
- Automatic failover
- Cost optimization
- Rate limit handling
- Unified observability

### **Q: Can I use local models?**
A: Yes! Configure ngrok.ai to include Ollama endpoint:
```yaml
providers:
  - provider: ollama
    endpoint: http://localhost:11434
    models: ["llama3", "mixtral"]
    use_for: ["pii_sensitive"]
```

### **Q: What about latency?**
A: ngrok.ai adds ~20-50ms overhead. For governance decisions (not real-time), this is negligible.

### **Q: Privacy concerns?**
A: Route sensitive operations to local Ollama via ngrok.ai policies. PII never leaves your machine.
