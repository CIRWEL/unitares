-- BGE-M3 Embeddings Table (Phase 2 of KG retrieval rebuild)
-- Version: 1.0.0
--
-- Parallel table for BGE-M3 (1024d) embeddings. Default `core.discovery_embeddings`
-- remains 384d for MiniLM. Runtime selects between them via UNITARES_EMBEDDING_MODEL.
--
-- See docs/plans/2026-04-20-kg-retrieval-rebuild.md Phase 2.

CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- BGE-M3 EMBEDDINGS TABLE (1024d)
-- =============================================================================

CREATE TABLE IF NOT EXISTS core.discovery_embeddings_bge_m3 (
    discovery_id        TEXT PRIMARY KEY,
    embedding           vector(1024) NOT NULL,
    model_name          TEXT NOT NULL DEFAULT 'BAAI/bge-m3',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_discovery_embeddings_bge_m3_hnsw
    ON core.discovery_embeddings_bge_m3
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Only attach the updated_at trigger if the helper function exists (it's
-- defined in embeddings_schema.sql; this script can run standalone).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'core' AND p.proname = 'update_timestamp'
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_discovery_embeddings_bge_m3_updated_at'
    ) THEN
        EXECUTE $TRG$
            CREATE TRIGGER trg_discovery_embeddings_bge_m3_updated_at
                BEFORE UPDATE ON core.discovery_embeddings_bge_m3
                FOR EACH ROW EXECUTE FUNCTION core.update_timestamp()
        $TRG$;
    END IF;
END $$;
