"""
Knowledge Graph Storage Backends

Contains both the AGE (Apache Graph Extension) and PostgreSQL FTS backends
for the knowledge graph. The factory in src/knowledge_graph.py selects
which backend to instantiate based on environment configuration.

Classes:
    KnowledgeGraphAGE — Native graph queries via AGE + pgvector semantic search
    KnowledgeGraphPostgres — PostgreSQL FTS (tsvector) with unified database storage
"""

# ---------------------------------------------------------------------------
# Re-export both backend classes from their implementation files.
# This lets callers import from a single location:
#     from src.storage.knowledge_graph import KnowledgeGraphAGE, KnowledgeGraphPostgres
#
# The actual implementations remain in their own modules to keep diffs clean
# and git-blame intact. This file acts as a consolidation facade.
# ---------------------------------------------------------------------------

from src.storage.knowledge_graph_age import KnowledgeGraphAGE
from src.storage.knowledge_graph_postgres import KnowledgeGraphPostgres

__all__ = [
    "KnowledgeGraphAGE",
    "KnowledgeGraphPostgres",
]
