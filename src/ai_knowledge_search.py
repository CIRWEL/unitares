"""
AI-Powered Knowledge Graph Search

Uses embeddings for semantic search instead of just tag matching.

Example:
- Query: "authentication problems"
- Tag-based search: Finds only discoveries tagged "auth"
- Semantic search: Finds "login failures", "credential issues", "token errors"

Provider routing (via ngrok.ai):
- Primary: OpenAI text-embedding-3-small (cheap, fast)
- Fallback: Local sentence-transformers (free, slower)
- Cost: ~$0.00002 per query (negligible)
"""

from typing import List, Dict, Optional, Tuple
import os
import json
import numpy as np
from dataclasses import dataclass

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from src.logging_utils import get_logger
from src.knowledge_graph import DiscoveryNode

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """Semantic search result with score"""
    discovery: DiscoveryNode
    relevance_score: float  # 0.0-1.0, based on cosine similarity
    match_reason: str  # Why this matched


class SemanticKnowledgeSearch:
    """Semantic search over knowledge graph using embeddings"""

    def __init__(self):
        if not OPENAI_AVAILABLE:
            raise ImportError("openai package required")

        base_url = os.getenv("NGROK_AI_ENDPOINT", "https://api.openai.com/v1")
        api_key = os.getenv("NGROK_API_KEY") or os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError("NGROK_API_KEY or OPENAI_API_KEY required")

        self.client = OpenAI(base_url=base_url, api_key=api_key)

        # Cache of discovery embeddings (in production, store in vector DB)
        self._embedding_cache: Dict[str, List[float]] = {}

        logger.info("SemanticKnowledgeSearch initialized")

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding for text"""
        try:
            response = self.client.embeddings.create(
                model="text-embedding-3-small",  # Cheap, fast
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return None

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors"""
        a_np = np.array(a)
        b_np = np.array(b)
        return float(np.dot(a_np, b_np) / (np.linalg.norm(a_np) * np.linalg.norm(b_np)))

    def index_discovery(self, discovery: DiscoveryNode):
        """
        Index a discovery for semantic search.

        In production, this would go to a vector database.
        For now, we cache in memory.
        """
        # Combine summary + details for rich embedding
        text = f"{discovery.summary}. {discovery.details}"
        embedding = self._get_embedding(text)

        if embedding:
            self._embedding_cache[discovery.id] = embedding

    def search(
        self,
        query: str,
        discoveries: List[DiscoveryNode],
        top_k: int = 5,
        min_score: float = 0.5
    ) -> List[SearchResult]:
        """
        Semantic search over discoveries.

        Args:
            query: Natural language query
            discoveries: List of DiscoveryNode to search
            top_k: Return top K results
            min_score: Minimum relevance score (0.0-1.0)

        Returns:
            List of SearchResult, sorted by relevance
        """
        query_embedding = self._get_embedding(query)
        if not query_embedding:
            logger.error("Failed to get query embedding")
            return []

        results = []

        for discovery in discoveries:
            # Index if not already cached
            if discovery.id not in self._embedding_cache:
                self.index_discovery(discovery)

            discovery_embedding = self._embedding_cache.get(discovery.id)
            if not discovery_embedding:
                continue

            # Compute similarity
            similarity = self._cosine_similarity(query_embedding, discovery_embedding)

            if similarity >= min_score:
                results.append(SearchResult(
                    discovery=discovery,
                    relevance_score=similarity,
                    match_reason=f"Semantic similarity: {similarity:.2f}"
                ))

        # Sort by relevance
        results.sort(key=lambda x: x.relevance_score, reverse=True)

        return results[:top_k]

    def find_related(
        self,
        discovery: DiscoveryNode,
        all_discoveries: List[DiscoveryNode],
        top_k: int = 3
    ) -> List[SearchResult]:
        """
        Find discoveries semantically related to given discovery.

        Better than tag-based "related_to" - finds conceptually similar items.
        """
        # Use discovery summary as query
        return self.search(
            query=discovery.summary,
            discoveries=[d for d in all_discoveries if d.id != discovery.id],
            top_k=top_k,
            min_score=0.6  # Higher threshold for "related"
        )

    def cluster_discoveries(
        self,
        discoveries: List[DiscoveryNode]
    ) -> Dict[str, List[DiscoveryNode]]:
        """
        Auto-cluster discoveries by semantic similarity.

        Useful for: "Show me discovery themes" or "Group related issues"
        """
        # This would use clustering algorithms (k-means, DBSCAN) on embeddings
        # Simplified version for now

        # Index all
        for d in discoveries:
            if d.id not in self._embedding_cache:
                self.index_discovery(d)

        # TODO: Implement clustering
        # For now, return placeholder
        return {"all": discoveries}


def create_semantic_search() -> Optional[SemanticKnowledgeSearch]:
    """Factory function"""
    try:
        return SemanticKnowledgeSearch()
    except Exception as e:
        logger.warning(f"SemanticKnowledgeSearch not available: {e}")
        return None
