"""
Embeddings Service for Semantic Search

Provides text embeddings using sentence-transformers for semantic similarity
queries over the knowledge graph.

Model: all-MiniLM-L6-v2 (fast, small, good quality)
- 384 dimensions
- ~80MB model size
- ~10ms per embedding on CPU

Usage:
    from src.embeddings import get_embeddings_service
    
    service = await get_embeddings_service()
    embedding = await service.embed("circuit breaker triggered")
    similar = await service.find_similar(embedding, top_k=5)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from src.logging_utils import get_logger

logger = get_logger(__name__)

# Model configuration
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

# Check if sentence-transformers is available
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning(
        "sentence-transformers not available. Install with: "
        "pip install sentence-transformers"
    )


class EmbeddingsService:
    """
    Embeddings service with lazy model loading.
    
    Thread-safe, async-compatible via run_in_executor.
    Model loaded on first use to avoid startup overhead.
    """
    
    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self._model: Optional[SentenceTransformer] = None
        self._load_lock: Optional[asyncio.Lock] = None
    
    async def _ensure_model(self) -> SentenceTransformer:
        """Lazy load model on first use."""
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
        
        if self._model is not None:
            return self._model
        
        # Create lock lazily to avoid event loop binding issues
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        
        async with self._load_lock:
            # Double-check after acquiring lock
            if self._model is not None:
                return self._model
            
            # Load model in executor (blocking I/O)
            loop = asyncio.get_running_loop()
            
            def _load_model():
                logger.info(f"Loading embedding model: {self.model_name}")
                model = SentenceTransformer(self.model_name)
                logger.info(f"Embedding model loaded: {self.model_name}")
                return model
            
            self._model = await loop.run_in_executor(None, _load_model)
            return self._model
    
    async def embed(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats (384 dimensions for MiniLM-L6-v2)
        """
        model = await self._ensure_model()
        loop = asyncio.get_running_loop()
        
        def _encode():
            # normalize_embeddings=True for cosine similarity
            embedding = model.encode(text, normalize_embeddings=True)
            return embedding.tolist()
        
        return await loop.run_in_executor(None, _encode)
    
    async def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """
        Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            batch_size: Batch size for encoding
            
        Returns:
            List of embeddings (each 384 dimensions)
        """
        if not texts:
            return []
        
        model = await self._ensure_model()
        loop = asyncio.get_running_loop()
        
        def _encode_batch():
            embeddings = model.encode(
                texts,
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=len(texts) > 100
            )
            return [emb.tolist() for emb in embeddings]
        
        return await loop.run_in_executor(None, _encode_batch)
    
    async def similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """
        Compute cosine similarity between two embeddings.
        
        Since embeddings are normalized, dot product = cosine similarity.
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise RuntimeError("numpy not available")
        
        arr1 = np.array(embedding1)
        arr2 = np.array(embedding2)
        return float(np.dot(arr1, arr2))
    
    async def rank_by_similarity(
        self,
        query_embedding: List[float],
        candidate_embeddings: List[Tuple[str, List[float]]],
        top_k: int = 10
    ) -> List[Tuple[str, float]]:
        """
        Rank candidates by similarity to query.
        
        Args:
            query_embedding: Query embedding
            candidate_embeddings: List of (id, embedding) tuples
            top_k: Number of results to return
            
        Returns:
            List of (id, similarity_score) tuples, sorted by score descending
        """
        if not candidate_embeddings:
            return []
        
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise RuntimeError("numpy not available")
        
        loop = asyncio.get_running_loop()
        
        def _rank():
            query = np.array(query_embedding)
            
            scores = []
            for doc_id, emb in candidate_embeddings:
                candidate = np.array(emb)
                # Dot product of normalized vectors = cosine similarity
                score = float(np.dot(query, candidate))
                scores.append((doc_id, score))
            
            # Sort by score descending
            scores.sort(key=lambda x: x[1], reverse=True)
            return scores[:top_k]
        
        return await loop.run_in_executor(None, _rank)
    
    def is_available(self) -> bool:
        """Check if embeddings service is available."""
        return SENTENCE_TRANSFORMERS_AVAILABLE


# Global singleton
_embeddings_service: Optional[EmbeddingsService] = None
_service_lock: Optional[asyncio.Lock] = None


async def get_embeddings_service() -> EmbeddingsService:
    """Get global embeddings service singleton."""
    global _embeddings_service, _service_lock
    
    if _service_lock is None:
        _service_lock = asyncio.Lock()
    
    async with _service_lock:
        if _embeddings_service is None:
            _embeddings_service = EmbeddingsService()
        return _embeddings_service


def embeddings_available() -> bool:
    """Check if embeddings are available (sentence-transformers installed)."""
    return SENTENCE_TRANSFORMERS_AVAILABLE
