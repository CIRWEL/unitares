# Hugging Face Integration Opportunities for UNITARES MCP

**Created:** December 26, 2025  
**Last Updated:** December 26, 2025  
**Status:** Analysis & Recommendations

---

## Executive Summary

After exploring the UNITARES MCP system **via live HTTP API**, here are strategic Hugging Face integration opportunities that could enhance:
- **Knowledge Graph** semantic search
- **Dialectic peer review** system
- **Multi-agent coordination**
- **Model management** and optimization

**Current State (Verified Live):**
- ✅ Using `sentence-transformers` for embeddings (local, free)
- ❌ OpenAI embeddings code exists but **NOT USED** (unused code in `src/ai_knowledge_search.py`)
- ❌ OpenAI dialectic code exists but **NOT USED** (unused code in `src/ai_synthesis.py`)
- ✅ Knowledge graph with semantic search (779+ discoveries from 167+ agents) - uses local embeddings
- ✅ Dialectic system for agent peer review (manual synthesis, no AI)
- ✅ 47+ MCP tools for governance
- ✅ **611 total agents** in system
- ✅ HTTP API accessible at `https://unitares.ngrok.io/v1/tools/call`
- ✅ Real-time EISV metrics working (E=0.70, I=0.79, S=0.18, coherence=0.50)

**Live System Status:**
- Server: v2.5.1 running on ngrok
- Health: ✅ Healthy
- Agents: 611 total, 3 active in sample
- Knowledge Graph: Operational with semantic search

**Opportunity:** Leverage HF's broader ecosystem for enhanced capabilities.

---

## System Overview

### What Your MCP Does

1. **Thermodynamic Governance (EISV)**
   - Tracks agent state: Energy (E), Integrity (I), Entropy (S), Void (V)
   - Circuit breakers for unhealthy agents
   - Coherence monitoring

2. **Knowledge Graph**
   - Stores agent discoveries
   - Semantic search (embeddings-based)
   - Tag-based and similarity search
   - 779+ discoveries from 167+ agents

3. **Dialectic Peer Review**
   - Thesis/antithesis/synthesis for paused agents
   - Multi-agent coordination
   - Resolution protocols

4. **Multi-Agent Coordination**
   - Shared state via SSE transport
   - Identity management (UUID, agent_id, display_name)
   - Cross-agent knowledge sharing

### Current AI/ML Stack

| Component | Current Solution | Location |
|-----------|-----------------|----------|
| **Embeddings** | sentence-transformers (local, free) | `src/embeddings.py` |
| **Semantic Search** | Cosine similarity on local embeddings | `src/storage/knowledge_graph_age.py` |
| **Text Generation** | None (dialectic uses manual synthesis) | N/A |
| **Model Management** | Manual (local models) | N/A |
| **Unused Code** | OpenAI embeddings/synthesis (exists but not imported) | `src/ai_knowledge_search.py`, `src/ai_synthesis.py` |

---

## HF Integration Opportunities

### 1. Add HF Embeddings as Alternative ⭐

**Current:** Using local `sentence-transformers` (free, working well).

**Note:** OpenAI embedding code exists in `src/ai_knowledge_search.py` but is **NOT USED**. The system uses `src/embeddings.py` (local) exclusively.

**Opportunity:** Add HF Inference Providers as optional alternative (not replacement).

**Benefits:**
- ✅ **Model choice:** Access to latest embedding models without local download
- ✅ **GPU acceleration:** HF Inference Providers include GPU (faster than local CPU)
- ✅ **No local storage:** Don't need to download 80MB+ models
- ✅ **Better integration:** Native HF ecosystem

**Note:** This is optional enhancement, not cost savings (current setup is already free).

**Implementation:**
```python
# In src/ai_knowledge_search.py, replace OpenAI with HF
from huggingface_hub import InferenceClient

class SemanticKnowledgeSearch:
    def __init__(self):
        self.client = InferenceClient(token=os.getenv("HF_TOKEN"))
    
    def _get_embedding(self, text: str) -> Optional[List[float]]:
        result = self.client.feature_extraction(
            model="sentence-transformers/all-MiniLM-L6-v2",  # or better model
            inputs=text
        )
        return result.tolist() if hasattr(result, 'tolist') else list(result)
```

**Models to Consider:**
- `sentence-transformers/all-MiniLM-L6-v2` (current, 384 dims)
- `sentence-transformers/all-mpnet-base-v2` (better quality, 768 dims)
- `intfloat/multilingual-e5-base` (multilingual support)

**Priority:** Low - Current setup is free and working. This would be optional enhancement for GPU acceleration or model variety.

---

### 2. Add LLM Capabilities for Dialectic Synthesis ⭐⭐⭐

**Current:** Dialectic system uses manual synthesis (agents write responses).

**Opportunity:** Use HF LLMs for automatic synthesis generation.

**Use Cases:**
- **Automatic synthesis:** Generate synthesis from thesis/antithesis
- **Discovery summarization:** Auto-summarize long discoveries
- **Agent communication:** Generate structured agent messages
- **Knowledge extraction:** Extract structured data from text

**Implementation:**
```python
# New file: src/hf_llm_service.py
from huggingface_hub import InferenceClient

class HFLLMService:
    def __init__(self):
        self.client = InferenceClient(token=os.getenv("HF_TOKEN"))
    
    async def generate_synthesis(
        self, 
        thesis: str, 
        antithesis: str
    ) -> str:
        """Generate dialectic synthesis from thesis/antithesis."""
        prompt = f"""Generate a synthesis that reconciles these perspectives:

Thesis: {thesis}

Antithesis: {antithesis}

Synthesis:"""
        
        result = self.client.text_generation(
            model="meta-llama/Meta-Llama-3.1-8B-Instruct",
            prompt=prompt,
            max_new_tokens=500,
            temperature=0.7
        )
        return result.generated_text
    
    async def summarize_discovery(self, text: str) -> str:
        """Summarize long discovery text."""
        prompt = f"Summarize this discovery in 2-3 sentences:\n\n{text}\n\nSummary:"
        result = self.client.text_generation(
            model="meta-llama/Meta-Llama-3.1-8B-Instruct",
            prompt=prompt,
            max_new_tokens=150
        )
        return result.generated_text
```

**Models to Consider:**
- `meta-llama/Meta-Llama-3.1-8B-Instruct` (good balance)
- `mistralai/Mistral-7B-Instruct-v0.2` (fast, efficient)
- `google/gemma-7b-it` (alternative)

**Integration Points:**
- `src/mcp_handlers/dialectic.py` - Add synthesis generation
- `src/mcp_handlers/knowledge_graph.py` - Add auto-summarization
- New tool: `generate_dialectic_synthesis`

**Priority:** High - Adds significant value to dialectic system

---

### 3. Structured Outputs for Knowledge Graph Queries ⭐⭐

**Current:** Knowledge graph returns unstructured text.

**Opportunity:** Use HF structured outputs for type-safe queries.

**Use Cases:**
- **Discovery extraction:** Extract structured data from discoveries
- **EISV state parsing:** Parse agent state from text
- **Tag extraction:** Auto-extract tags from discovery text
- **Relationship detection:** Detect discovery relationships

**Implementation:**
```python
from pydantic import BaseModel
from typing import List

class DiscoveryExtract(BaseModel):
    summary: str
    tags: List[str]
    severity: Optional[str]
    related_topics: List[str]

async def extract_discovery_structure(text: str) -> DiscoveryExtract:
    """Extract structured data from discovery text."""
    client = InferenceClient(token=os.getenv("HF_TOKEN"))
    
    result = client.chat_completion(
        model="meta-llama/Meta-Llama-3.1-8B-Instruct",
        messages=[{
            "role": "user",
            "content": f"Extract structured data from this discovery:\n\n{text}"
        }],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "DiscoveryExtract",
                "schema": DiscoveryExtract.model_json_schema(),
                "strict": True
            }
        }
    )
    return DiscoveryExtract(**result.choices[0].message.content)
```

**Priority:** Medium - Nice-to-have, improves data quality

---

### 4. Fine-Tune Embeddings for Domain-Specific Knowledge ⭐⭐

**Current:** Using general-purpose embeddings.

**Opportunity:** Fine-tune embeddings on your knowledge graph data.

**Benefits:**
- ✅ Better semantic matching for governance/thermodynamic concepts
- ✅ Improved discovery similarity
- ✅ Domain-specific terminology understanding

**Process:**
1. Export knowledge graph discoveries
2. Create training pairs (similar discoveries)
3. Fine-tune `all-MiniLM-L6-v2` on your data
4. Upload to HF Hub (private repo)
5. Use fine-tuned model for embeddings

**Implementation:**
```python
# Fine-tuning script (one-time)
from sentence_transformers import SentenceTransformer, InputExample, losses
from torch.utils.data import DataLoader

# Load base model
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

# Prepare training data from your knowledge graph
# (similar discoveries = positive pairs)
training_examples = [
    InputExample(texts=["circuit breaker triggered", "agent paused due to risk"]),
    InputExample(texts=["EISV state unstable", "thermodynamic imbalance detected"]),
    # ... more pairs from your knowledge graph
]

# Train
train_dataloader = DataLoader(training_examples, shuffle=True, batch_size=16)
train_loss = losses.CosineSimilarityLoss(model)

model.fit(
    train_objectives=[(train_dataloader, train_loss)],
    epochs=3,
    output_path='./governance-embeddings-v1'
)

# Upload to HF Hub
model.save_to_hub("your-org/governance-embeddings-v1", private=True)
```

**Usage:**
```python
# Use fine-tuned model
DEFAULT_MODEL = "your-org/governance-embeddings-v1"
```

**Priority:** Medium - Long-term optimization, requires training data

---

### 5. Model Management via HF Hub ⭐

**Current:** Models stored locally, manual updates.

**Opportunity:** Use HF Hub for model versioning and distribution.

**Benefits:**
- ✅ Version control for models
- ✅ Easy updates across deployments
- ✅ Model sharing between agents
- ✅ Model cards and documentation

**Implementation:**
```python
from huggingface_hub import hf_hub_download, snapshot_download

# Download specific model version
model_path = hf_hub_download(
    repo_id="sentence-transformers/all-MiniLM-L6-v2",
    filename="pytorch_model.bin",
    revision="v2.2.2"  # Pin version
)

# Or use snapshot for full model
snapshot_download(
    repo_id="sentence-transformers/all-MiniLM-L6-v2",
    local_dir="./models/all-MiniLM-L6-v2",
    revision="v2.2.2"
)
```

**Priority:** Low - Nice-to-have, current system works

---

### 6. Multi-Modal Capabilities (Future) ⭐

**Current:** Text-only (discoveries, embeddings).

**Opportunity:** Add image/audio support if you expand.

**Use Cases:**
- **Screenshot analysis:** Analyze agent UI screenshots
- **Diagram understanding:** Parse governance diagrams
- **Audio logs:** Transcribe and analyze agent audio logs

**Models:**
- `openai/clip-vit-base-patch32` (image embeddings)
- `facebook/wav2vec2-base` (audio transcription)

**Priority:** Low - Future expansion only

---

## Implementation Roadmap

### Phase 1: Quick Wins (1-2 weeks)

1. **Replace OpenAI embeddings with HF Inference Providers**
   - Update `src/ai_knowledge_search.py`
   - Add HF_TOKEN environment variable
   - Test with free tier
   - **Impact:** Cost savings, better integration

2. **Add HF embeddings to local fallback**
   - Enhance `src/embeddings.py` to support HF API
   - Keep local model as backup
   - **Impact:** Better reliability

### Phase 2: Enhanced Capabilities (2-4 weeks)

1. **Add LLM synthesis generation**
   - Create `src/hf_llm_service.py`
   - Integrate with dialectic system
   - Add new MCP tool: `generate_dialectic_synthesis`
   - **Impact:** Automated dialectic synthesis

2. **Add discovery summarization**
   - Integrate LLM service with knowledge graph
   - Auto-summarize long discoveries
   - **Impact:** Better knowledge graph quality

### Phase 3: Advanced Features (1-2 months)

1. **Structured outputs for queries**
   - Add Pydantic schemas
   - Integrate with knowledge graph search
   - **Impact:** Type-safe, structured data

2. **Fine-tune embeddings**
   - Export knowledge graph data
   - Create training pairs
   - Fine-tune and deploy
   - **Impact:** Domain-specific improvements

---

## Cost Analysis

### Current Costs

**Current Setup (Local):**
- Embeddings: **$0** (local sentence-transformers)
- Storage: **$0** (local files/PostgreSQL)
- **Total: $0/month**

### HF Costs (If Added)

**Free Tier:**
- 1,000 requests/hour
- Good for development/testing
- **Total: $0/month (free tier)**

**Pay-as-you-go (if needed):**
- Embeddings: ~$0.00001 per query
- LLM inference: ~$0.0001 per 1K tokens
- 100K embedding queries: ~$1/month
- 10K LLM queries (500 tokens each): ~$0.50/month

**Note:** Current setup is already free. HF would add optional capabilities (GPU acceleration, model variety) but not cost savings.

---

## Technical Considerations

### Environment Variables

Add to your config:
```bash
# HF Integration
HF_TOKEN=your_hf_token_here
USE_HF_EMBEDDINGS=true  # Toggle HF vs OpenAI
HF_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
HF_LLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct
```

### Dependencies

Add to `requirements-full.txt`:
```
huggingface_hub>=0.25.0
```

### Error Handling

```python
# Graceful fallback
try:
    embedding = await hf_client.feature_extraction(...)
except Exception as e:
    logger.warning(f"HF embedding failed: {e}, falling back to local")
    embedding = await local_embeddings_service.embed(text)
```

### Rate Limiting

HF free tier: 1,000 requests/hour
- Implement request queuing
- Cache embeddings aggressively
- Batch requests when possible

---

## Recommended Starting Point

**Current Status:** System is fully local and free. No OpenAI usage.

**If adding HF (optional enhancement):**

**Start with #1: Add HF Embeddings as Optional Alternative**

**Why:**
- ✅ GPU acceleration (faster than local CPU)
- ✅ Model variety (access to latest models without download)
- ✅ No local storage needed (80MB+ models)
- ✅ Low risk (keep local as primary, HF as optional)

**Steps:**
1. Get HF token: https://huggingface.co/settings/tokens
2. Enhance `src/embeddings.py` to support HF InferenceClient
3. Add environment variable: `USE_HF_EMBEDDINGS=false` (default: local)
4. Test with free tier
5. Compare performance (HF GPU vs local CPU)
6. Keep local as primary, HF as optional enhancement

**Note:** This is optional enhancement, not cost savings (current setup is already free).

---

## Questions to Consider

1. **Do you want to keep local embeddings as primary?** (Recommended: Yes - it's free and working)
2. **Which LLM model for synthesis?** (Recommend: Llama 3.1 8B for balance)
3. **Do you have training data for fine-tuning?** (Need: Similar discovery pairs)
4. **What's your query volume?** (Determines if free tier is sufficient)
5. **Do you need multilingual support?** (Affects model choice)
6. **Do you need GPU acceleration?** (HF Inference Providers include GPU)

---

## Next Steps

1. Review this analysis
2. Decide on Phase 1 priorities
3. Get HF token and test free tier
4. Implement #1 (embeddings replacement)
5. Evaluate results and plan Phase 2

---

**Status:** Ready for Implementation  
**Priority:** High (embeddings), Medium (LLM), Low (fine-tuning)

yes---

## Live System Exploration Results

**Explored:** December 26, 2025 via HTTP API

**Findings:**
- ✅ Server v2.5.1 operational at `https://unitares.ngrok.io`
- ✅ HTTP API working: `/v1/tools/call` endpoint functional
- ✅ Identity system: Auto-binds on first tool call
- ✅ Governance metrics: Real EISV values (not defaults)
- ✅ Knowledge graph: Successfully stored discovery with provenance
- ✅ System scale: 611 agents, healthy operation

**Tested Tools:**
- `process_agent_update` - ✅ Working, returned real metrics
- `get_governance_metrics` - ✅ Working, shows EISV state
- `list_agents` - ✅ Working, shows 611 total agents
- `store_knowledge_graph` - ✅ Working, stored with provenance
- `search_knowledge_graph` - ✅ Working, FTS search operational

**Integration Readiness:**
- HTTP API makes HF integration straightforward
- Session-based identity binding works
- Knowledge graph ready for enhanced semantic search
- Dialectic system ready for LLM synthesis generation

