"""
Retrieval utilities: Reciprocal Rank Fusion (RRF), tag-overlap boosts.

Separate from the storage backend so fusion logic can be unit-tested without
a live DB, and reused by both the MCP handler and the eval harness.

Phase 4 of docs/plans/2026-04-20-kg-retrieval-rebuild.md.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.logging_utils import get_logger

logger = get_logger(__name__)


def _flag_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def hybrid_enabled() -> bool:
    """True when hybrid RRF retrieval should run. UNITARES_ENABLE_HYBRID."""
    return _flag_enabled("UNITARES_ENABLE_HYBRID", default=False)


def graph_expansion_enabled() -> bool:
    """True when 1-hop typed-edge expansion should run. UNITARES_ENABLE_GRAPH_EXPANSION."""
    return _flag_enabled("UNITARES_ENABLE_GRAPH_EXPANSION", default=False)


def rrf_fuse(
    ranked_lists: Sequence[Sequence[str]],
    k: int = 60,
) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion.

    For each ranked list and each (doc_id, rank_index) within it, accumulate
    `1 / (k + rank_index + 1)` into that doc_id's score. Missing lists count
    as zero. Final output is sorted by score descending.

    Args:
        ranked_lists: sequence of ranked id lists. Order matters: higher
                      position in each list contributes more.
        k: RRF constant. 60 is the standard default from Cormack et al. 2009;
           it's the boring-correct value and barely needs tuning.

    Returns:
        [(doc_id, rrf_score)] sorted by score desc. Scores are small
        (typically < 0.1) but comparable across queries.
    """
    scores: Dict[str, float] = {}
    for ranked in ranked_lists:
        for idx, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + idx + 1)
    items = list(scores.items())
    items.sort(key=lambda kv: kv[1], reverse=True)
    return items


def apply_tag_boost(
    scored: Sequence[Tuple[str, float]],
    doc_tags: Dict[str, Iterable[str]],
    query_tags: Optional[Iterable[str]],
    boost_per_match: float = 0.01,
) -> List[Tuple[str, float]]:
    """Promote docs whose tags overlap the query's tag filter.

    Default boost (0.01) is calibrated against the RRF score scale — one
    rank-1 hit contributes 1/(60+1) ≈ 0.0164, so a tag match is roughly
    half-a-rank of lift. Small enough that semantic/BM25 agreement still
    dominates; big enough to break ties for keyword-tagged queries.

    If `query_tags` is empty/None, returns `scored` unchanged.

    Order is re-sorted by new score descending.
    """
    if not query_tags:
        return list(scored)
    qtags = {t.lower() for t in query_tags if t}
    if not qtags:
        return list(scored)

    boosted: List[Tuple[str, float]] = []
    for doc_id, score in scored:
        dtags = {t.lower() for t in (doc_tags.get(doc_id) or [])}
        overlap = len(qtags & dtags)
        if overlap:
            score = score + boost_per_match * overlap
        boosted.append((doc_id, score))
    boosted.sort(key=lambda kv: kv[1], reverse=True)
    return boosted


def expand_with_neighbors(
    scored: Sequence[Tuple[str, float]],
    seed_neighbors: Dict[str, Iterable[str]],
    edge_weight: float = 0.5,
    max_seeds: int = 10,
) -> List[Tuple[str, float]]:
    """1-hop graph expansion on typed edges.

    For each of the top `max_seeds` scored docs, promote its neighbors (from
    `seed_neighbors[seed_id]`) into the candidate pool with a score inherited
    from the seed, discounted by `edge_weight`. Neighbors already in `scored`
    keep the max of their existing score and the inherited boost.
    """
    expanded: Dict[str, float] = {doc_id: score for doc_id, score in scored}
    seeds = list(scored[:max_seeds])
    for seed_id, seed_score in seeds:
        neighbors = seed_neighbors.get(seed_id) or []
        for nid in neighbors:
            if not nid or nid == seed_id:
                continue
            inherited = seed_score * edge_weight
            if inherited > expanded.get(nid, 0.0):
                expanded[nid] = inherited
    items = list(expanded.items())
    items.sort(key=lambda kv: kv[1], reverse=True)
    return items
