# Hugging Face Embeddings Guide

**Created:** December 26, 2025  
**Last Updated:** December 26, 2025  
**Status:** Active

---

## Overview

This guide covers embedding model selection, optimization, and best practices for the UNITARES knowledge graph semantic search system.

**Current Implementation:**
- Model: `sentence-transformers/all-MiniLM-L6-v2`
- Dimensions: 384
- Size: ~80MB
- Speed: ~10ms per embedding on CPU
- Location: `src/embeddings.py`

---

## Quick Reference

| Model | Dimensions | Size | Speed | Quality | Use Case |
|-------|-----------|------|-------|---------|----------|
| **all-MiniLM-L6-v2** (current) | 384 | 80MB | Fast | Good | General semantic search ✅ |
| all-mpnet-base-v2 | 768 | 420MB | Medium | Excellent | Higher quality needed |
| multi-qa-MiniLM-L6-cos-v1 | 384 | 80MB | Fast | Good | Q&A/retrieval optimized |
| paraphrase-multilingual-MiniLM-L12-v2 | 384 | 420MB | Medium | Good | Multilingual support |

---

## Model Selection Guide

### When to Keep Current Model (`all-MiniLM-L6-v2`)

✅ **Keep if:**
- Search quality is acceptable
- Latency is critical (<20ms per query)
- Running on CPU-only servers
- Memory is constrained (<1GB available)
- Most queries are in English

**Your current setup is well-suited for:**
- Knowledge graph semantic search
- Discovery similarity matching
- Agent behavior pattern detection

### When to Upgrade

#### Option 1: `all-mpnet-base-v2` (Higher Quality)

**Upgrade if:**
- Search results are too generic
- Need better semantic understanding
- Can afford 420MB model size
- Have GPU available (5x faster)

**Performance:**
- Quality: +15-20% better semantic matching
- Speed: ~25ms CPU, ~5ms GPU
- Memory: 420MB

**How to switch:**
```python
# In src/embeddings.py, change:
DEFAULT_MODEL = "sentence-transformers/all-mpnet-base-v2"
EMBEDDING_DIM = 768  # Update dimension
```

**Note:** Requires re-embedding all existing discoveries (run `scripts/regenerate_embeddings.py`).

#### Option 2: `multi-qa-MiniLM-L6-cos-v1` (Q&A Optimized)

**Upgrade if:**
- Queries are question-like ("how does X work?")
- Need better question-answer matching
- Want same speed/size as current model

**Performance:**
- Quality: Better for Q&A, similar for general search
- Speed: Same as current (~10ms)
- Memory: Same (80MB)

**How to switch:**
```python
DEFAULT_MODEL = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
EMBEDDING_DIM = 384  # Same dimensions
```

**No re-embedding needed** (same dimensions, compatible).

#### Option 3: `paraphrase-multilingual-MiniLM-L12-v2` (Multilingual)

**Upgrade if:**
- Need to support non-English queries
- Have international users/agents
- Can afford 420MB model size

**Performance:**
- Quality: Good for 50+ languages
- Speed: ~20ms CPU
- Memory: 420MB

---

## Performance Optimization

### Current Implementation Analysis

Your `EmbeddingsService` is well-designed:
- ✅ Lazy model loading (avoids startup overhead)
- ✅ Async-compatible (non-blocking)
- ✅ Batch processing support
- ✅ Normalized embeddings (cosine similarity ready)

### Optimization Opportunities

#### 1. Batch Processing

**Current:** You have `embed_batch()` but may not be using it optimally.

**Optimize:**
```python
# Instead of:
for text in texts:
    embedding = await service.embed(text)

# Use:
embeddings = await service.embed_batch(texts, batch_size=32)
```

**Impact:** 3-5x faster for bulk operations (e.g., regenerating embeddings).

#### 2. Model Quantization

Reduce model size by 60-75% with minimal quality loss:

```python
from sentence_transformers import SentenceTransformer
import torch

# Load and quantize
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
model = torch.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)

# Save quantized model
model.save("models/all-MiniLM-L6-v2-quantized")
```

**Impact:**
- Size: 80MB → 20-30MB
- Speed: ~15% faster
- Quality: <2% degradation

#### 3. Caching Strategy

**Current:** Embeddings are computed on-demand.

**Add caching:**
```python
# In EmbeddingsService, add:
from functools import lru_cache
import hashlib

def _text_hash(self, text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

async def embed(self, text: str, use_cache: bool = True) -> List[float]:
    if use_cache:
        cache_key = self._text_hash(text)
        cached = await self._cache.get(cache_key)
        if cached:
            return cached
    
    embedding = await self._compute_embedding(text)
    
    if use_cache:
        await self._cache.set(cache_key, embedding, ttl=86400)  # 24h
    
    return embedding
```

**Impact:** 
- Repeated queries: 100x faster (cache hit)
- Memory: ~1.5KB per cached embedding

#### 4. GPU Acceleration

If you have GPU available:

```python
import torch

# Check for GPU
device = "cuda" if torch.cuda.is_available() else "cpu"

# Load model on GPU
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device=device)
```

**Impact:**
- Speed: 5-10x faster (10ms → 1-2ms)
- Batch processing: 20-50x faster

**Note:** Requires `torch` with CUDA support.

---

## Hugging Face Inference Providers

### Modern Approach: InferenceClient

**Recommended:** Use `InferenceClient` from `huggingface_hub` (modern, type-safe API).

**Installation:**
```bash
pip install huggingface_hub
```

**Implementation:**
```python
from huggingface_hub import InferenceClient
import os

HF_TOKEN = os.getenv("HF_TOKEN")  # or HUGGINGFACE_API_TOKEN
client = InferenceClient(token=HF_TOKEN)

async def embed_via_inference_client(text: str) -> List[float]:
    """Use HF Inference Providers for embeddings."""
    # Feature extraction endpoint (embeddings)
    result = client.feature_extraction(
        model="sentence-transformers/all-MiniLM-L6-v2",
        inputs=text
    )
    return result.tolist() if hasattr(result, 'tolist') else list(result)
```

**Benefits over raw API:**
- ✅ Type-safe (better IDE support)
- ✅ Automatic retries
- ✅ Better error handling
- ✅ Supports streaming
- ✅ Works with Inference Providers (cloud-hosted models)

### When to Use HF Inference Providers vs Local

| Factor | Local Model | HF Inference Providers |
|--------|------------|------------------------|
| **Cost** | Free | ~$0.0001 per 1K tokens (free tier available) |
| **Latency** | ~10ms | ~100-200ms (network) |
| **Privacy** | 100% local | Data sent to HF |
| **Scalability** | Limited by CPU/GPU | Unlimited (auto-scaling) |
| **Offline** | Works offline | Requires internet |
| **Model Updates** | Manual | Automatic (always latest) |
| **GPU Access** | Requires local GPU | Included (faster inference) |

### Use HF Inference Providers If:

✅ High-volume production (>10K queries/day)  
✅ Don't want to manage model updates  
✅ Need GPU acceleration without local GPU  
✅ Want automatic scaling  
✅ Have budget for API costs (~$10/month for 100K queries)  
✅ Need access to latest models immediately

### Free Tier

HF offers **free tier** for Inference Providers:
- Limited requests per hour
- Good for development/testing
- Upgrade for production scale

### Batch Embeddings via Inference Providers

```python
# Embed multiple texts efficiently
texts = ["query 1", "query 2", "query 3"]
embeddings = client.feature_extraction(
    model="sentence-transformers/all-MiniLM-L6-v2",
    inputs=texts  # List of texts
)
# Returns: List[List[float]] - one embedding per text
```

**Performance:** Similar to local batch processing, but with GPU acceleration.

---

## Legacy: Hugging Face Inference API (Deprecated)

**Note:** The old Inference API is still available but `InferenceClient` is recommended.

**Old approach (still works):**
```python
import requests
import os

HF_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")
HF_API_URL = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"

async def embed_via_hf_api(text: str) -> List[float]:
    """Legacy: Use old HF Inference API."""
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    response = requests.post(
        HF_API_URL,
        headers=headers,
        json={"inputs": text}
    )
    return response.json()[0]
```

**Migration:** Replace with `InferenceClient` for better reliability and features.

---

## Advanced: Structured Outputs for Knowledge Graph

**Use Case:** Query knowledge graph with structured responses (e.g., extract EISV metrics, agent patterns).

### Implementation

```python
from huggingface_hub import InferenceClient
from pydantic import BaseModel
from typing import List

# Define schema for knowledge graph query results
class DiscoveryResult(BaseModel):
    id: str
    summary: str
    agent_id: str
    similarity_score: float
    tags: List[str]

class KnowledgeGraphQuery(BaseModel):
    query: str
    top_k: int = 5
    min_similarity: float = 0.3

client = InferenceClient(token=os.getenv("HF_TOKEN"))

# Use structured outputs for type-safe knowledge graph queries
def query_knowledge_graph(query: str) -> List[DiscoveryResult]:
    """Query knowledge graph with structured output."""
    result = client.chat_completion(
        model="meta-llama/Meta-Llama-3.1-8B-Instruct",
        messages=[{
            "role": "user",
            "content": f"Search knowledge graph for: {query}"
        }],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "KnowledgeGraphQuery",
                "schema": KnowledgeGraphQuery.model_json_schema(),
                "strict": True
            }
        }
    )
    return [DiscoveryResult(**item) for item in result.choices[0].message.content]
```

**Benefits:**
- Type-safe responses
- Automatic validation
- Better for agent workflows
- Integrates with your MCP system

**Note:** Requires a model that supports structured outputs (e.g., Llama 3.1+, Mistral, GPT-4).

---

## Advanced: Responses API for Agentic Workflows

**Use Case:** Streaming, multi-turn conversations for agent coordination (relevant to your dialectic system).

### Implementation

```python
from huggingface_hub import InferenceClient

client = InferenceClient(token=os.getenv("HF_TOKEN"))

# Streaming responses for real-time agent coordination
def stream_agent_response(prompt: str):
    """Stream response for agentic workflows."""
    stream = client.chat_completion(
        model="meta-llama/Meta-Llama-3.1-8B-Instruct",
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        max_tokens=500
    )
    
    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
```

**Use Cases for Your System:**
- **Dialectic peer review:** Stream thesis/antithesis/synthesis
- **Agent coordination:** Real-time communication between agents
- **Knowledge graph synthesis:** Stream discovery summaries
- **Governance feedback:** Real-time EISV state updates

**Benefits:**
- Lower latency (first token faster)
- Better UX for long responses
- Enables interactive agent workflows
- Works with your SSE transport

---

## Best Practices

### 1. Embedding Normalization

✅ **You're already doing this correctly:**
```python
embedding = model.encode(text, normalize_embeddings=True)
```

**Why it matters:**
- Cosine similarity = dot product (faster)
- Consistent similarity scores
- Better for ranking

### 2. Similarity Thresholds

**Current:** `min_similarity=0.3` in semantic search.

**Recommendations:**
- **0.7+**: Very similar (near-duplicates)
- **0.5-0.7**: Related concepts
- **0.3-0.5**: Loosely related (current threshold)
- **<0.3**: Unrelated (filter out)

**Adjust based on use case:**
```python
# For strict matching (fewer, higher quality results):
min_similarity = 0.5

# For broad discovery (more results, lower quality):
min_similarity = 0.3  # Current
```

### 3. Text Preprocessing

**Current:** Raw text is embedded directly.

**Optimize:**
```python
def preprocess_text(text: str) -> str:
    """Preprocess text for better embeddings."""
    # Remove extra whitespace
    text = " ".join(text.split())
    
    # Truncate very long texts (models have token limits)
    # all-MiniLM-L6-v2: 512 tokens max (~384 words)
    if len(text) > 2000:  # Rough estimate
        text = text[:2000] + "..."
    
    return text.strip()
```

**Impact:** More consistent embeddings, avoids truncation issues.

### 4. Handling Long Texts

**Current:** Long texts are embedded as-is (may be truncated by model).

**Better approach:** Chunk long texts:

```python
def chunk_text(text: str, max_length: int = 500) -> List[str]:
    """Split long text into chunks for embedding."""
    words = text.split()
    chunks = []
    current_chunk = []
    current_length = 0
    
    for word in words:
        if current_length + len(word) > max_length and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_length = len(word)
        else:
            current_chunk.append(word)
            current_length += len(word) + 1
    
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    
    return chunks

# Embed chunks separately, then average:
chunks = chunk_text(long_text)
chunk_embeddings = await service.embed_batch(chunks)
final_embedding = np.mean(chunk_embeddings, axis=0).tolist()
```

**Impact:** Better embeddings for long discoveries (e.g., detailed analysis).

### 5. Model Version Pinning

**Current:** Uses latest model version (may change).

**Pin version for stability:**
```python
# Instead of:
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Use:
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2@v2.2.2"
```

**Why:** Prevents unexpected behavior from model updates.

---

## Troubleshooting

### Issue: Slow Embedding Generation

**Symptoms:** >50ms per embedding on CPU.

**Solutions:**
1. Check if model is loaded (should see log: "Embedding model loaded")
2. Use batch processing for multiple texts
3. Consider GPU if available
4. Check CPU usage (other processes competing?)

### Issue: Low Similarity Scores

**Symptoms:** All similarity scores <0.3, no matches.

**Solutions:**
1. Lower `min_similarity` threshold (try 0.2)
2. Check if embeddings are normalized (should be)
3. Verify model is correct (not corrupted)
4. Try different model (e.g., all-mpnet-base-v2)

### Issue: Out of Memory

**Symptoms:** Model loading fails, OOM errors.

**Solutions:**
1. Use smaller model (current: all-MiniLM-L6-v2 is smallest)
2. Enable model quantization (see above)
3. Use HF Inference API (no local memory needed)
4. Increase available RAM/swap

### Issue: Inconsistent Results

**Symptoms:** Same query returns different results.

**Solutions:**
1. Pin model version (see above)
2. Check text preprocessing (whitespace, encoding)
3. Verify embeddings are cached (if using cache)
4. Ensure model is loaded once (singleton pattern)

---

## Migration Guide

### Switching Models

**Step 1:** Update model name in `src/embeddings.py`:
```python
DEFAULT_MODEL = "sentence-transformers/all-mpnet-base-v2"
EMBEDDING_DIM = 768  # Update if dimensions change
```

**Step 2:** Regenerate embeddings for existing discoveries:
```bash
cd /Users/cirwel/projects/governance-mcp-v1
python scripts/regenerate_embeddings.py
```

**Step 3:** Test semantic search:
```python
# In Python or via MCP tool:
result = await graph.semantic_search(
    query="thermodynamic governance",
    top_k=5,
    min_similarity=0.3
)
```

**Step 4:** Monitor performance:
- Check embedding generation time
- Verify search quality improved
- Watch for memory/CPU issues

### Moving to HF Inference API

**Step 1:** Get HF API token:
1. Sign up at https://huggingface.co
2. Create token: Settings → Access Tokens
3. Set environment variable: `export HUGGINGFACE_API_TOKEN=your_token`

**Step 2:** Modify `EmbeddingsService` to support API mode:
```python
# Add to EmbeddingsService.__init__:
self.use_api = os.getenv("USE_HF_API", "false").lower() == "true"
self.api_token = os.getenv("HUGGINGFACE_API_TOKEN")

# Modify embed() to check use_api flag
```

**Step 3:** Test API mode:
```bash
USE_HF_API=true python -c "from src.embeddings import get_embeddings_service; ..."
```

**Step 4:** Monitor costs:
- Track API calls
- Set budget alerts
- Compare to local model performance

---

## Hugging Face Ecosystem Overview

**The HF ecosystem is vast.** This section helps you navigate what's relevant to your use case.

### Core Libraries (Most Relevant to You)

| Library | Purpose | Relevance | Docs |
|---------|---------|-----------|------|
| **sentence-transformers** | Embeddings | ⭐⭐⭐ Essential | https://www.sbert.net/ |
| **huggingface_hub** | Model/API access | ⭐⭐⭐ Essential | https://huggingface.co/docs/huggingface_hub |
| **transformers** | NLP models | ⭐⭐ If using LLMs | https://huggingface.co/docs/transformers |
| **datasets** | Dataset management | ⭐ If training | https://huggingface.co/docs/datasets |
| **safetensors** | Model format | ⭐⭐ Understanding | https://huggingface.co/docs/safetensors |

### What You're Using Now

✅ **sentence-transformers** - Embeddings for knowledge graph  
✅ **huggingface_hub** - Model downloading (implicit via sentence-transformers)

### What You Might Need Later

**If you add LLM features:**
- `transformers` - For running models locally
- `accelerate` - For GPU optimization
- `peft` - For fine-tuning

**If you optimize model storage:**
- `safetensors` - Secure tensor format (faster than pickle, safer)

**If you use HF Inference:**
- `InferenceClient` - Already covered in this guide

### Safetensors: The Model Format

**What it is:** Secure tensor serialization format (replaces pickle).

**Why it matters:**
- ✅ **Faster:** 2-10x faster loading than pickle
- ✅ **Safer:** No arbitrary code execution risk
- ✅ **Standard:** Most HF models use it now
- ✅ **Cross-framework:** Works with PyTorch, TensorFlow, JAX

**Your models already use it:**
- `sentence-transformers` downloads models in safetensors format
- No action needed - it's automatic

**If you need to work with safetensors directly:**
```python
from safetensors import safe_open

# Load model weights from safetensors
with safe_open("model.safetensors", framework="pt", device="cpu") as f:
    tensor = f.get_tensor("layer.weight")
```

**Docs:** https://huggingface.co/docs/safetensors

### Navigating HF Documentation

**The docs are organized by:**
1. **Library docs** (e.g., `/docs/huggingface_hub/`)
2. **Task guides** (e.g., `/docs/transformers/tasks/`)
3. **API references** (e.g., `/docs/huggingface_hub/v0.25.0/en/package_reference/`)
4. **Model cards** (e.g., `/models/sentence-transformers/all-MiniLM-L6-v2`)

**Finding what you need:**
- **Search:** Use `site:huggingface.co/docs` in search
- **Start here:** https://huggingface.co/docs
- **Library-specific:** Each library has its own docs section

**Key doc sections for your use case:**
- `/docs/huggingface_hub/guides/inference` - Inference API
- `/docs/huggingface_hub/guides/hf_file_system` - File operations
- `/docs/safetensors/` - Model format
- `/docs/transformers/` - If you add LLM features

### Ecosystem Map (What's Where)

```
Hugging Face Ecosystem
├── Hub (Platform)
│   ├── Models (your embeddings here)
│   ├── Datasets
│   └── Spaces (demos)
├── Libraries
│   ├── huggingface_hub (API access) ← You use this
│   ├── sentence-transformers (embeddings) ← You use this
│   ├── transformers (NLP models)
│   ├── datasets (data management)
│   └── safetensors (format) ← Models use this
├── Inference
│   ├── Inference Providers (cloud)
│   ├── InferenceClient (Python) ← Covered in guide
│   └── Responses API (streaming) ← Covered in guide
└── Tools
    ├── Gradio (UI)
    ├── Accelerate (optimization)
    └── PEFT (fine-tuning)
```

### Focus Areas for Your Project

**Current needs (covered in this guide):**
1. ✅ Embeddings (sentence-transformers)
2. ✅ Inference API (InferenceClient)
3. ✅ Model selection

**Future considerations:**
- **Model fine-tuning:** If you want domain-specific embeddings
- **LLM integration:** If you add text generation to knowledge graph
- **Model optimization:** If you need smaller/faster models
- **Multi-modal:** If you add image/audio to knowledge graph

### Getting Help

**Documentation:**
- Main docs: https://huggingface.co/docs
- Library-specific: Each library has `/docs/{library}/`

**Community:**
- Forums: https://discuss.huggingface.co/
- Discord: https://huggingface.co/join/discord
- GitHub: https://github.com/huggingface

**For your specific questions:**
- Embeddings: https://www.sbert.net/docs/
- Inference: https://huggingface.co/docs/huggingface_hub/guides/inference
- Hub API: https://huggingface.co/docs/huggingface_hub

---

## Resources

### Official Documentation

**Core (What You Use):**
- **Sentence Transformers:** https://www.sbert.net/
- **Hugging Face Hub:** https://huggingface.co/docs/huggingface_hub
- **Inference Providers:** https://huggingface.co/docs/inference-endpoints/index
- **Safetensors:** https://huggingface.co/docs/safetensors

**Guides (This Document):**
- **InferenceClient:** https://huggingface.co/docs/huggingface_hub/guides/inference
- **Structured Outputs:** https://huggingface.co/docs/huggingface_hub/guides/inference#structured-outputs
- **Responses API:** https://huggingface.co/docs/huggingface_hub/guides/inference#responses-api
- **HfFileSystem:** https://huggingface.co/docs/huggingface_hub/guides/hf_file_system

**Model Discovery:**
- **Sentence Transformers Models:** https://huggingface.co/models?library=sentence-transformers
- **Model Performance:** https://www.sbert.net/docs/pretrained_models.html

**Ecosystem:**
- **Main Docs Hub:** https://huggingface.co/docs
- **All Libraries:** https://huggingface.co/docs#libraries

### Model Cards

- **all-MiniLM-L6-v2:** https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- **all-mpnet-base-v2:** https://huggingface.co/sentence-transformers/all-mpnet-base-v2
- **multi-qa-MiniLM-L6-cos-v1:** https://huggingface.co/sentence-transformers/multi-qa-MiniLM-L6-cos-v1

### Related Documentation

- [Knowledge Graph Guide](KNOWLEDGE_GRAPH.md)
- [Semantic Search Implementation](../../src/embeddings.py)
- [NGROK Deployment](NGROK_DEPLOYMENT.md) (for API endpoints)

---

## Summary

**Current Setup:** ✅ Well-optimized for your use case

**Recommendations:**
1. **Keep current model** unless search quality is insufficient
2. **Add caching** for frequently queried discoveries
3. **Use batch processing** when regenerating embeddings
4. **Consider HF Inference API** if volume exceeds 10K queries/day

**Next Steps:**
- Monitor search quality metrics
- Test model upgrades in development
- Consider GPU if latency becomes critical
- Evaluate HF Inference API for production scale

---

**Status:** ✅ Production Ready  
**Last Verified:** December 26, 2025

