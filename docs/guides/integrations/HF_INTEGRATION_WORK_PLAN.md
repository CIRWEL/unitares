# Hugging Face Integration Work Plan

**Created:** December 26, 2025  
**Last Updated:** December 26, 2025  
**Status:** On Hold - Future Consideration

---

## Overview

This document breaks down the HF integration work into manageable tasks based on comprehensive system analysis.

**Status Note (2025-12-26):** 
Currently on hold. System is working well with:
- Local sentence-transformers (free, fast)
- OpenAI embeddings via ngrok.ai (already in use)
- No immediate need for additional complexity

**When to reconsider:**
- OpenAI costs become significant (>$50/month)
- Need for better model selection/control
- Desire for open-source model alternatives
- Multi-modal capabilities needed

**System Architecture Understood:**
- ✅ Embeddings: `src/embeddings.py` (local) + `src/ai_knowledge_search.py` (OpenAI via ngrok.ai)
- ✅ Knowledge Graph: `src/storage/knowledge_graph_age.py` (uses embeddings, stores in pgvector)
- ✅ Dialectic: `src/ai_synthesis.py` (OpenAI via ngrok.ai)
- ✅ Database: PostgreSQL + pgvector, Redis, SQLite fallback
- ✅ MCP Server: SSE/HTTP at `https://unitares.ngrok.io`

---

## Work Breakdown Structure

### Phase 1: Embeddings Replacement (Priority: High)

**Goal:** Replace OpenAI embeddings with HF Inference Providers

#### Task 1.1: Add HF Embeddings Service
**Files:** `src/embeddings.py` (enhance existing)

**Work:**
- [ ] Add `InferenceClient` support alongside local model
- [ ] Add environment variable: `USE_HF_EMBEDDINGS` (default: false)
- [ ] Add `HF_TOKEN` environment variable support
- [ ] Implement fallback chain: HF API → Local model → Error
- [ ] Add model selection: `HF_EMBEDDING_MODEL` (default: all-MiniLM-L6-v2)
- [ ] Add batch embedding support via HF API
- [ ] Add error handling and retries

**Dependencies:**
- `huggingface_hub>=0.25.0` (add to requirements-full.txt)

**Estimated Time:** 4-6 hours

**Testing:**
- [ ] Test HF API embedding generation
- [ ] Test fallback to local model
- [ ] Test batch embeddings
- [ ] Verify embedding dimensions match (384 for MiniLM-L6-v2)

---

#### Task 1.2: Update Knowledge Graph to Use HF Embeddings
**Files:** `src/storage/knowledge_graph_age.py`

**Work:**
- [ ] Update `semantic_search()` to use HF embeddings if enabled
- [ ] Ensure embedding dimensions match pgvector schema
- [ ] Test pgvector storage with HF embeddings
- [ ] Verify semantic search quality (compare to OpenAI)

**Dependencies:**
- Task 1.1 complete

**Estimated Time:** 2-3 hours

**Testing:**
- [ ] Semantic search returns correct results
- [ ] Embeddings stored in pgvector correctly
- [ ] Similarity scores are reasonable (0.3-0.9 range)

---

#### Task 1.3: Update Configuration and Documentation
**Files:** 
- `config/governance_config.py` (if needed)
- `docs/guides/HUGGINGFACE_EMBEDDINGS.md` (update)
- `.env.example` (add HF variables)

**Work:**
- [ ] Document HF_TOKEN setup
- [ ] Document USE_HF_EMBEDDINGS toggle
- [ ] Update embedding guide with HF API usage
- [ ] Add troubleshooting section

**Dependencies:**
- Tasks 1.1, 1.2 complete

**Estimated Time:** 1-2 hours

---

### Phase 2: LLM Synthesis Generation (Priority: High)

**Goal:** Add HF LLM capabilities for dialectic synthesis

#### Task 2.1: Create HF LLM Service
**Files:** `src/hf_llm_service.py` (new file)

**Work:**
- [ ] Create `HFLLMService` class using `InferenceClient`
- [ ] Implement `generate_synthesis()` method
- [ ] Implement `summarize_discovery()` method
- [ ] Add model selection: `HF_LLM_MODEL` (default: meta-llama/Meta-Llama-3.1-8B-Instruct)
- [ ] Add error handling and fallbacks
- [ ] Add streaming support (optional, for future)

**Dependencies:**
- `huggingface_hub>=0.25.0`

**Estimated Time:** 6-8 hours

**Testing:**
- [ ] Test synthesis generation with sample thesis/antithesis
- [ ] Test discovery summarization
- [ ] Verify JSON output format
- [ ] Test error handling (API failures)

---

#### Task 2.2: Integrate with Dialectic System
**Files:** `src/mcp_handlers/dialectic.py`, `src/ai_synthesis.py`

**Work:**
- [ ] Add HF LLM service as option in `DialecticAI`
- [ ] Update `suggest_synthesis()` to use HF if available
- [ ] Add environment toggle: `USE_HF_LLM` (default: false)
- [ ] Keep OpenAI as fallback
- [ ] Add model comparison logging

**Dependencies:**
- Task 2.1 complete

**Estimated Time:** 3-4 hours

**Testing:**
- [ ] Dialectic synthesis works with HF LLM
- [ ] Fallback to OpenAI if HF fails
- [ ] Quality comparison (HF vs OpenAI)

---

#### Task 2.3: Add MCP Tool for LLM Synthesis
**Files:** `src/mcp_handlers/knowledge_graph.py` or new handler

**Work:**
- [ ] Create new tool: `generate_dialectic_synthesis`
- [ ] Add to `tool_schemas.py`
- [ ] Register in MCP server
- [ ] Add tool documentation

**Dependencies:**
- Task 2.2 complete

**Estimated Time:** 2-3 hours

**Testing:**
- [ ] Tool callable via MCP
- [ ] Returns valid synthesis
- [ ] Error handling works

---

### Phase 3: Structured Outputs (Priority: Medium)

**Goal:** Add structured outputs for knowledge graph queries

#### Task 3.1: Add Structured Output Support
**Files:** `src/hf_llm_service.py` (extend)

**Work:**
- [ ] Add `extract_discovery_structure()` method
- [ ] Use Pydantic schemas for validation
- [ ] Support multiple extraction schemas (DiscoveryExtract, EISVState, etc.)
- [ ] Add error handling for schema validation

**Dependencies:**
- Task 2.1 complete
- `pydantic>=2.0` (verify in requirements)

**Estimated Time:** 4-5 hours

**Testing:**
- [ ] Extract structured data from discovery text
- [ ] Validate against Pydantic schemas
- [ ] Handle malformed responses

---

#### Task 3.2: Integrate with Knowledge Graph
**Files:** `src/mcp_handlers/knowledge_graph.py`

**Work:**
- [ ] Add optional structured extraction to `store_knowledge_graph`
- [ ] Auto-extract tags, severity, relationships
- [ ] Store extracted data in discovery metadata

**Dependencies:**
- Task 3.1 complete

**Estimated Time:** 3-4 hours

**Testing:**
- [ ] Auto-extraction works on discovery storage
- [ ] Extracted data is accurate
- [ ] Performance acceptable (<500ms per extraction)

---

### Phase 4: Fine-Tuning (Priority: Low, Future)

**Goal:** Fine-tune embeddings for domain-specific knowledge

#### Task 4.1: Export Training Data
**Files:** `scripts/export_training_data.py` (new)

**Work:**
- [ ] Export knowledge graph discoveries
- [ ] Create similar discovery pairs (manual or heuristic)
- [ ] Format for sentence-transformers training
- [ ] Validate training data quality

**Estimated Time:** 8-10 hours (includes data curation)

---

#### Task 4.2: Fine-Tune Model
**Files:** `scripts/fine_tune_embeddings.py` (new)

**Work:**
- [ ] Set up fine-tuning pipeline
- [ ] Train on governance/thermodynamic domain
- [ ] Evaluate on test set
- [ ] Upload to HF Hub (private repo)

**Estimated Time:** 12-16 hours (includes training time)

---

#### Task 4.3: Deploy Fine-Tuned Model
**Files:** `src/embeddings.py`

**Work:**
- [ ] Update to use fine-tuned model
- [ ] Re-embed existing discoveries
- [ ] Compare quality vs base model

**Estimated Time:** 4-6 hours

---

## Implementation Order

### Sprint 1 (Week 1): Embeddings Foundation
1. Task 1.1: Add HF Embeddings Service
2. Task 1.2: Update Knowledge Graph
3. Task 1.3: Configuration & Docs

**Deliverable:** HF embeddings working, OpenAI as fallback

---

### Sprint 2 (Week 2): LLM Capabilities
1. Task 2.1: Create HF LLM Service
2. Task 2.2: Integrate with Dialectic
3. Task 2.3: Add MCP Tool

**Deliverable:** LLM synthesis generation working

---

### Sprint 3 (Week 3): Enhanced Features
1. Task 3.1: Structured Outputs
2. Task 3.2: Knowledge Graph Integration

**Deliverable:** Auto-extraction of structured data

---

### Sprint 4 (Future): Fine-Tuning
1. Tasks 4.1-4.3: Fine-tuning pipeline

**Deliverable:** Domain-specific embeddings

---

## Dependencies

### External
- ✅ Hugging Face account + API token
- ✅ `huggingface_hub>=0.25.0` package
- ✅ HF free tier or paid plan

### Internal
- ✅ PostgreSQL with pgvector extension (for vector storage)
- ✅ Existing embeddings infrastructure
- ✅ Dialectic system architecture

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| **HF API rate limits** | Medium | Implement caching, batch requests, fallback to local |
| **Model quality differences** | Low | A/B test, keep OpenAI as fallback |
| **pgvector dimension mismatch** | Low | Verify dimensions match (384 for MiniLM-L6-v2) |
| **Cost overruns** | Low | Monitor usage, set budget alerts |
| **Integration complexity** | Medium | Incremental rollout, extensive testing |

---

## Success Criteria

### Phase 1 (Embeddings)
- [ ] HF embeddings generate same-quality results as OpenAI
- [ ] Fallback chain works (HF → Local → Error)
- [ ] Cost savings: 25%+ reduction vs OpenAI
- [ ] No performance degradation (<200ms per query)

### Phase 2 (LLM)
- [ ] Synthesis generation quality matches OpenAI
- [ ] Dialectic system uses HF LLM successfully
- [ ] New MCP tool works end-to-end

### Phase 3 (Structured Outputs)
- [ ] Auto-extraction accuracy >80%
- [ ] Performance acceptable (<500ms)
- [ ] Reduces manual tagging effort

---

## Testing Strategy

### Unit Tests
- [ ] `test_hf_embeddings_service.py` - Embedding generation
- [ ] `test_hf_llm_service.py` - LLM synthesis
- [ ] `test_structured_outputs.py` - Extraction validation

### Integration Tests
- [ ] `test_knowledge_graph_hf.py` - Semantic search with HF
- [ ] `test_dialectic_hf.py` - Dialectic with HF LLM
- [ ] `test_end_to_end.py` - Full workflow

### Performance Tests
- [ ] Embedding latency benchmarks
- [ ] LLM response time benchmarks
- [ ] Cost tracking (queries per dollar)

---

## Configuration Changes

### Environment Variables (Add)
```bash
# HF Integration
HF_TOKEN=your_hf_token_here
USE_HF_EMBEDDINGS=false  # Toggle HF vs OpenAI for embeddings
USE_HF_LLM=false  # Toggle HF vs OpenAI for LLM
HF_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
HF_LLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct
```

### Requirements (Update)
```txt
# Add to requirements-full.txt
huggingface_hub>=0.25.0
```

---

## Documentation Updates

### Files to Update
- [ ] `docs/guides/HUGGINGFACE_EMBEDDINGS.md` - Add HF API usage
- [ ] `docs/guides/HF_INTEGRATION_OPPORTUNITIES.md` - Mark tasks complete
- [ ] `README.md` - Add HF integration section
- [ ] `docs/guides/MCP_SETUP.md` - Add HF configuration

### New Documentation
- [ ] `docs/guides/HF_LLM_INTEGRATION.md` - LLM usage guide
- [ ] `docs/guides/HF_TROUBLESHOOTING.md` - Common issues

---

## Next Steps

1. **Review this plan** - Confirm priorities and timeline
2. **Get HF token** - Sign up at https://huggingface.co/settings/tokens
3. **Start Sprint 1** - Begin with Task 1.1 (HF Embeddings Service)
4. **Set up monitoring** - Track API usage and costs
5. **Test incrementally** - Validate each task before moving on

---

**Status:** Ready to Begin  
**Estimated Total Time:** 40-60 hours (Phases 1-3)  
**Recommended Start:** Task 1.1 (HF Embeddings Service)

