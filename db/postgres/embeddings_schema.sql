-- Embeddings Schema for Semantic Search
-- Version: 1.0.0
--
-- Adds pgvector extension and discovery_embeddings table for semantic search.
-- Run AFTER schema.sql
--
-- Prerequisites:
--   PostgreSQL 15+ with pgvector extension installed
--   brew install pgvector  (macOS)
--   apt install postgresql-15-pgvector  (Ubuntu)

-- =============================================================================
-- PGVECTOR EXTENSION
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- EMBEDDINGS TABLE
-- =============================================================================

-- Store embeddings for knowledge graph discoveries
-- Uses 384 dimensions (sentence-transformers/all-MiniLM-L6-v2)
CREATE TABLE IF NOT EXISTS core.discovery_embeddings (
    discovery_id        TEXT PRIMARY KEY,
    embedding           vector(384) NOT NULL,
    model_name          TEXT NOT NULL DEFAULT 'all-MiniLM-L6-v2',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW index for fast approximate nearest neighbor search
-- ef_construction: higher = better recall, slower build
-- m: connections per node, higher = better recall, more memory
CREATE INDEX IF NOT EXISTS idx_discovery_embeddings_hnsw 
    ON core.discovery_embeddings 
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Also create IVFFlat index as fallback (faster to build, good for smaller datasets)
-- CREATE INDEX IF NOT EXISTS idx_discovery_embeddings_ivfflat
--     ON core.discovery_embeddings
--     USING ivfflat (embedding vector_cosine_ops)
--     WITH (lists = 100);

-- Trigger to update updated_at
CREATE TRIGGER trg_discovery_embeddings_updated_at
    BEFORE UPDATE ON core.discovery_embeddings
    FOR EACH ROW EXECUTE FUNCTION core.update_timestamp();

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Semantic search function
-- Returns discovery_ids with similarity scores, ordered by similarity desc
CREATE OR REPLACE FUNCTION core.semantic_search(
    query_embedding vector(384),
    limit_count INTEGER DEFAULT 10,
    min_similarity REAL DEFAULT 0.3
)
RETURNS TABLE (
    discovery_id TEXT,
    similarity REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        de.discovery_id,
        (1 - (de.embedding <=> query_embedding))::REAL AS similarity
    FROM core.discovery_embeddings de
    WHERE (1 - (de.embedding <=> query_embedding)) >= min_similarity
    ORDER BY de.embedding <=> query_embedding
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql STABLE;

-- Upsert embedding
CREATE OR REPLACE FUNCTION core.upsert_embedding(
    p_discovery_id TEXT,
    p_embedding vector(384),
    p_model_name TEXT DEFAULT 'all-MiniLM-L6-v2'
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO core.discovery_embeddings (discovery_id, embedding, model_name)
    VALUES (p_discovery_id, p_embedding, p_model_name)
    ON CONFLICT (discovery_id) DO UPDATE SET
        embedding = EXCLUDED.embedding,
        model_name = EXCLUDED.model_name,
        updated_at = now();
END;
$$ LANGUAGE plpgsql;

-- Batch upsert embeddings (for backfill)
CREATE OR REPLACE FUNCTION core.batch_upsert_embeddings(
    p_ids TEXT[],
    p_embeddings vector(384)[],
    p_model_name TEXT DEFAULT 'all-MiniLM-L6-v2'
)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    INSERT INTO core.discovery_embeddings (discovery_id, embedding, model_name)
    SELECT unnest(p_ids), unnest(p_embeddings), p_model_name
    ON CONFLICT (discovery_id) DO UPDATE SET
        embedding = EXCLUDED.embedding,
        model_name = EXCLUDED.model_name,
        updated_at = now();
    
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Get embeddings stats
CREATE OR REPLACE FUNCTION core.embeddings_stats()
RETURNS TABLE (
    total_embeddings BIGINT,
    model_name TEXT,
    oldest_embedding TIMESTAMPTZ,
    newest_embedding TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*)::BIGINT,
        de.model_name,
        MIN(de.created_at),
        MAX(de.created_at)
    FROM core.discovery_embeddings de
    GROUP BY de.model_name;
END;
$$ LANGUAGE plpgsql STABLE;
