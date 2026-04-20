# KG Retrieval Rebuild — Scoping

**Status:** scoping · **Date:** 2026-04-20 · **Author:** Kenny + Claude (Opus 4.7)
**Related tickets:** `2025-12-29T00:10:19.967967` (hybrid KG search, open 4mo), `2026-04-18T03:06:53.121325` (dogfood evidence of noise-floor scores)

## Why this matters

KG is the only shared-memory surface UNITARES exposes to the fleet. Every cross-session "did someone already solve this?" flows through it. If retrieval is noise, agents re-discover what's been solved, and the paper-v6 claims about fleet-level learning become aspirational rather than operational. Paper v7's empirical work is already gated on corpus maturity; if the corpus isn't usable at scale, v7 is gated on something worse.

**KG quality is load-bearing for the whole system.** This rebuild isn't an optimization, it's a prerequisite.

## What exists today (audit)

Concrete, from `src/` inspection (full citations in audit notes):

| Layer | Current state | File |
|---|---|---|
| **Embedder** | `sentence-transformers/all-MiniLM-L6-v2` (384d, ~2021 vintage) | `src/embeddings.py:32` |
| **Query/passage symmetry** | Symmetric — no prefix asymmetry | `src/embeddings.py:108` |
| **Vector store** | pgvector 0.8 with HNSW index (`vector_cosine_ops`, m=16, ef_construction=64) on `core.discovery_embeddings` | `db/postgres/embeddings_schema.sql:35-38` |
| **FTS** | `tsvector` GIN index on `summary (A) || details (B)`, ranked with `ts_rank` (not BM25, not `ts_rank_cd`), `websearch_to_tsquery` with OR-default | `db/postgres/knowledge_schema.sql:56-71`, `src/db/mixins/knowledge_graph.py:175-178` |
| **Embedding coverage** | Async best-effort on insert; some rows have `NULL` embedding; backfill script exists but unclear if current | `scripts/migration/backfill_embeddings.py` |
| **Connectivity blend** | `final_score = sim*(1-w) + connectivity*w` with `w=0.3`; temporal-decay + status-weight on by default | `src/storage/knowledge_graph_age.py:1613-1614` |
| **Tags in ranking** | Post-filter only; do **not** affect scoring | `src/mcp_handlers/knowledge/handlers.py:786-789, 898-900` |
| **Graph edges in retrieval** | Not walked during search. `response_to` / `related_to` surface only in `get_discovery_details` | `src/storage/knowledge_graph_age.py:1584-1750` (no edge traversals) |
| **Fallback chain** | semantic → FTS → semantic-at-threshold-0.2 (noise floor) | `src/mcp_handlers/knowledge/handlers.py:820-915` |
| **Eval harness** | **None.** No ground-truth labels, no recall@k, no nDCG. Existing tests cover happy-path and embedding math only. | — |

## What's wrong (empirical)

Three defects confirmed by agent complaint + code inspection, plus two structural gaps:

1. **Scores sit at noise floor.** Two test queries just now scored top hits at 0.276 and 0.343. Cosine "real match" on sentence-transformer models typically clears 0.5. Root cause is probably the stale embedder (MiniLM from 2021) compounded by symmetric encoding of heterogeneous technical content.
2. **Tag filter doesn't affect ranking.** Confirmed — tags are post-filter. `tags=["migrations"]` narrows the candidate pool but leaves ordering unchanged.
3. **Threshold fallback leaks below its own floor.** When primary returns 0 and FTS returns 0, the code retries semantic at threshold 0.2, which is random. The noise is confidently returned as if it were a match.
4. **No graph expansion.** Edges between discoveries are a feature on paper but invisible to search. `response_to` threads are only visible if an agent already knows the parent ID.
5. **No eval.** Every proposed fix is guesswork without a measurement floor. This is the blocker for #1–#4 landing responsibly.

## Prior art

Two parallel surveys (2026 SOTA + open-source agent-memory systems) converged on the same recommendation:

**Consensus stack** (hybrid retrieval, 2026 production default):
- **Reciprocal Rank Fusion** (RRF, k=60) over BM25 + dense. Parameter-light, no training, robust — still the default in 2026. Learned fusion overfits below ~1k labeled pairs.
- **Modern embedder**: Qwen3-Embedding-0.6B (late 2025) is the local-on-Mac sweet spot for short English technical text. BGE-M3 as safe fallback. Asymmetric via instruction prefix on queries.
- **Cross-encoder rerank**: `bge-reranker-v2-m3` over top-50 candidates typically adds 50–200ms and lifts nDCG@10 by 10–25 points. **This is the single biggest lever for the noise-floor symptom.**
- **pgvector 0.8 is production-mature.** Don't add a second vector DB. Use `halfvec` to cut storage ~50% with negligible recall loss.
- **Graph-aware**: 1-hop expansion on typed edges into candidate pool before reranking. Skip GraphRAG (community-detection is hype at <5k docs).
- **Eval**: 100 hand-labeled `(query, relevant_doc_ids)` pairs, nDCG@10 primary, Recall@20 secondary, pytest fixture. Re-label monthly.

**Closest structural match in the wild: [Graphiti](https://github.com/getzep/graphiti)** (Zep's OSS graph layer). Typed edges with temporal validity, multi-writer semantics, hybrid retrieval already wired. Our `response_to` / `related_to` map onto its edge model cleanly. We won't adopt Graphiti (different stack, no AGE), but we steal the pattern.

**The one pattern worth stealing (from Graphiti's `search()`):**

```
1. Seed: vector_score + bm25_score (RRF fusion) → top K_seed
2. Expand: allowlisted edge types from seeds, N hops → candidate pool
3. Score:  seed_score · edge_weight · exp(-λ · age)
4. Rerank: cross-encoder on top-K of the pool
```

**Non-obvious win**: the edge-type allowlist is *per query intent*. Queries like "what did we decide about X" follow `response_to`; queries like "what else is like X" follow `related_to`. Same graph, different traversal policy per query.

**What not to do**:
- Mem0-style LLM edge extraction at write time — our agents already write typed edges.
- Whole-graph embedding (GraphSAGE etc.) — overkill at our scale.
- Full GraphRAG community detection — re-index cost is real, wins don't materialize under 5k docs.

## Recommended approach

Keep pgvector + AGE + Postgres. Replace the embedder, layer in hybrid fusion, add graph expansion, add a reranker, and — first — stand up an eval harness so we can tell whether anything actually helped.

## Build sequence

Each step lands in isolation, behind a flag where sensible, measured against the eval harness before proceeding.

**Phase 0: Stop the bleeding** (1 day, 1 PR)
- Kill the 0.2-threshold fallback in `handlers.py:877-915`. Return empty with an honest "no match" message; fall through to FTS-only if FTS has results.
- Ensure `similarity_scores` always included in responses so agents can calibrate.
- Verify NULL-embedding backfill is idempotent; run it.

**Phase 1: Eval harness** (2 days, 1 PR)
- `tests/retrieval_eval/` with 100 hand-labeled `(query, relevant_discovery_ids)` pairs, drawn from real agent query patterns where possible.
- `scripts/eval/retrieval.py` — runs current pipeline, prints nDCG@10, Recall@20, latency p50/p95.
- Baseline numbers captured and pinned as the pre-rebuild floor.

**Phase 2: Embedder swap** (2 days, 1 PR, feature flag)
- Swap MiniLM for Qwen3-Embedding-0.6B (or BGE-M3 if Qwen3 local cost is a problem). Instruction prefix on queries, plain passages.
- Re-embed corpus (one-shot migration). Keep old embeddings column during transition, drop after rollout.
- Expected: Recall@20 up meaningfully; nDCG@10 up somewhat. This is the biggest single lever.

**Phase 3: Cross-encoder rerank** (2 days, 1 PR, feature flag)
- `bge-reranker-v2-m3` over top-50 → top-10.
- Latency budget: +200ms p95 acceptable for `search` (it's not on any hot path).
- Expected: nDCG@10 +10–25 points. This is what collapses the noise-floor problem.

**Phase 4: Hybrid fusion (RRF)** (3 days, 1 PR)
- Parallel BM25 (`ts_rank_cd` not `ts_rank`) + dense fanout; RRF fusion k=60; replaces the sequential fallback chain entirely.
- Tags become a score boost in the fused space (not a post-filter).

**Phase 5: Graph expansion** (3 days, 1 PR)
- After fusion, expand top-K_seed (=20) along allowlisted edges (`response_to`, `related_to`) → candidate pool of ~60.
- Recency decay: `exp(-λ · age_days)` with tunable λ.
- Edge-type allowlist exposed as an optional query param; default = both.
- Rerank applied to the full expanded pool.

**Phase 6 (optional): Query intent classification**
- Light heuristic or small classifier to pick the edge-allowlist per query. Defer until we see whether the default is good enough.

## Success criteria

**Progression (20-pair seed corpus):**

| Metric | V1 (MiniLM) | V2 (BGE-M3) | V3 (+ rerank) | **V4 (hybrid RRF)** | Target |
|---|---|---|---|---|---|
| nDCG@10 (mean) | 0.826 | 0.861 | 0.853 | **0.872** ← best | ≥ 0.90 |
| Recall@20 (mean) | 0.875 | 0.925 | 0.950 | **0.950** | ≥ 0.95 ✓ |
| MRR (mean) | 0.825 | 0.867 | 0.823 | 0.850 | ≥ 0.90 |
| **Flat misses** | 2/20 | 1/20 | 1/20 | 1/20 | 0/20 |
| Latency p50 (steady) | 28–40ms | 80–180ms | 3000–4500ms | **~100ms** | ≤ 500ms |

**Phase 2 landed 2026-04-20.** BGE-M3 (1024d) replaces MiniLM-L6-v2 (384d) behind `UNITARES_EMBEDDING_MODEL=bge-m3`.

- The **"burst 503" flat miss is fixed** — top score 0.137 (noise) → rank-1 at 0.430.
- Two queries that previously hit at rank 2 (`"anyio deadlock"`, `"Watcher false positive"`) now hit at rank 1.
- Top scores across the corpus sit at ~0.35–0.60 (v. ~0.14–0.55 on V1). Clearly off the noise floor.

**Phase 3 landed 2026-04-20 as opt-in (default OFF).** `UNITARES_ENABLE_RERANKER=1` adds the `bge-reranker-v2-m3` cross-encoder over the top-50 first-stage candidates. The infrastructure lands clean; on this seed corpus, **aggregate nDCG@10 dropped 0.008 and MRR dropped 0.044** vs V2 alone, while Recall@20 rose 0.025.

Why V3 underperforms on this corpus:

- The seed labels were hand-crafted with knowledge of the documents — queries share surface vocabulary with their targets, which favors the first-stage embedder.
- In a ~600-doc corpus where V2 already achieves Recall@20 of 0.925, the reranker's headroom is narrow.
- Two queries regressed (rank 1→2 or rank 1→3) while one improved (rank 2→1). Net negative on aggregate at this scale.
- Latency: p50 3–4 seconds on MPS. This is the killer. Loading the 568M cross-encoder and scoring 50 pairs per query dominates.

The reranker is expected to start paying off (per the 2026 SOTA survey) when corpus size pushes first-stage recall down and the reranker has more room to re-sort. For now it ships as opt-in so Kenny can flip when the corpus grows (>5k discoveries) or when specific users want it.

**Phase 4 landed 2026-04-20. Hybrid RRF (BM25+dense fusion) is on-by-default when `UNITARES_ENABLE_HYBRID=1`.**

Wins vs V2 (dense-only):
- `"paper v6 fleet learning corpus maturity"` — rank 3 (V2) / rank 8 (V3) → **rank 1** (V4). Hybrid rescued the paraphrase miss the reranker couldn't.
- `"tag filter doesn't affect ranking"` — 0.61 (V2) → 0.92 (V4). FTS contribution helped.
- Tags still provide a signal when passed, now as an RRF-space boost rather than a hard post-filter.

Trade-offs — three V2 rank-1 hits slipped to rank 2 under V4 RRF. FTS brought neighbors into the fused top-10 that diluted strong-semantic wins. On aggregate net positive (+0.011 nDCG, +0.025 Recall); MRR dropped −0.017 as the visible cost.

**FTS upgrade**: `ts_rank` → `ts_rank_cd` (cover density) — bundled with Phase 4.

- **Dogfood check**: `"hybrid search retrieval rebuild"` returns the Dec-2025 ticket at top-1 under V1–V4.
- **Honest failure mode**: "no match" when nothing matches. Zero 0.2-threshold garbage. (Phase 0.)

Baselines pinned:
- `tests/retrieval_eval/baseline_2026-04-20.json` (V1)
- `tests/retrieval_eval/baseline_2026-04-20_bge_m3.json` (V2)
- `tests/retrieval_eval/baseline_2026-04-20_bge_m3_reranked.json` (V3)
- `tests/retrieval_eval/baseline_2026-04-20_hybrid_rrf.json` (V4)

Re-run:
```bash
# V2 (dense-only)
UNITARES_EMBEDDING_MODEL=bge-m3 UNITARES_KNOWLEDGE_BACKEND=age python scripts/eval/retrieval_eval.py

# V3 (dense + rerank)
UNITARES_EMBEDDING_MODEL=bge-m3 UNITARES_KNOWLEDGE_BACKEND=age python scripts/eval/retrieval_eval.py --rerank

# V4 (hybrid RRF)
UNITARES_EMBEDDING_MODEL=bge-m3 UNITARES_KNOWLEDGE_BACKEND=age python scripts/eval/retrieval_eval.py --hybrid
```

## Non-goals

- Rebuilding the write path — that's separate (already landed: PR #54 stopped silent ephemeral tagging).
- Multi-corpus / per-agent isolation — flat corpus for now.
- Vector DB migration off Postgres — pgvector 0.8 is fine.
- GraphRAG community detection — defer to post-5k-docs.
- LLM-based edge extraction at write time — agents already write typed edges.
- Training a learned fusion model — RRF is sufficient below 1k labeled pairs.

## Open questions

1. **Qwen3-Embedding-0.6B vs BGE-M3** — Qwen is newer and stronger on MTEB but M3 gives us multi-vector + sparse + dense in one model (optional future: ColBERT-style late interaction). Pick based on Phase 1 eval numbers, or just ship BGE-M3 as the safer boring-correct default.
2. **Reranker hardware path** — CPU-only or Metal/MPS? M-series Mac handles `bge-reranker-v2-m3` fine on MPS; acceptable p95?
3. **Eval label source** — pull 100 queries from existing Codex/Claude agent sessions' actual search calls, hand-label top-20 per query for relevance. 2–3 hours of labeling, produces a corpus tied to real usage rather than synthetic.
4. **Do we `paper v6.8` this?** — if the rebuild materially changes retrieval-based fleet-learning claims in paper v6 §11, that's a revision. Probably not — the paper claims the data structure exists, not the retrieval quality floor.

## Total sizing

~2 weeks of focused work, landable as ~6 incrementally-shipped PRs with measurement between each. Phase 0 (1 day) is shippable now independent of the rest.

## Sources

- SOTA survey (2026 hybrid retrieval landscape): captured from agent review run 2026-04-20.
- Agent-memory system comparison (Letta, Mem0, Zep, Graphiti, Cognee, LangMem): captured from agent review run 2026-04-20.
- Codebase audit: `src/embeddings.py`, `src/storage/knowledge_graph_age.py`, `src/db/mixins/knowledge_graph.py`, `src/mcp_handlers/knowledge/handlers.py`, `db/postgres/*_schema.sql`.
