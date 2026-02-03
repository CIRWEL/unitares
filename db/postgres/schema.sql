-- PostgreSQL Schema for Governance MCP
-- Version: 1.0.0
--
-- Architecture:
--   core.*   - Operational tables (identities, sessions, calibration, agent_state)
--   audit.*  - Time-series event data (partitioned by month)
--   AGE      - Graph data via Apache AGE extension (separate schema)
--
-- Run order: 1) This file  2) partitions.sql  3) AGE graph_schema.cypher

-- =============================================================================
-- EXTENSIONS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- gen_random_uuid(), crypt()
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- Trigram similarity for FTS
CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector: Vector similarity search
-- CREATE EXTENSION IF NOT EXISTS pg_cron;    -- Optional: scheduled partition management

-- =============================================================================
-- CORE SCHEMA - Operational Data
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS core;

-- -----------------------------------------------------------------------------
-- Agents (core agent identity - matches ticket requirements)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.agents (
    id                  TEXT PRIMARY KEY,
    api_key             TEXT NOT NULL,
    status              TEXT DEFAULT 'active'
                        CHECK (status IN ('active', 'paused', 'archived')),
    purpose             TEXT,
    notes               TEXT,
    tags                TEXT[],
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    archived_at         TIMESTAMPTZ,
    parent_agent_id     TEXT REFERENCES core.agents(id),
    spawn_reason        TEXT
);

CREATE INDEX IF NOT EXISTS idx_agents_status ON core.agents(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_agents_parent ON core.agents(parent_agent_id) WHERE parent_agent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agents_created_at ON core.agents(created_at DESC);

-- Helper function for updated_at triggers (must be defined before triggers)
CREATE OR REPLACE FUNCTION core.update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update updated_at
CREATE TRIGGER trg_agents_updated_at
    BEFORE UPDATE ON core.agents
    FOR EACH ROW EXECUTE FUNCTION core.update_timestamp();

-- -----------------------------------------------------------------------------
-- Identities (migrated from agent_metadata) - kept for backward compatibility
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.identities (
    identity_id         BIGSERIAL PRIMARY KEY,
    agent_id            TEXT NOT NULL UNIQUE REFERENCES core.agents(id) ON DELETE CASCADE,
    api_key_hash        TEXT NOT NULL,                    -- bcrypt hash, never raw
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at         TIMESTAMPTZ NULL,

    -- Lineage (shortcut; full lineage in AGE graph)
    parent_agent_id     TEXT NULL REFERENCES core.agents(id),
    spawn_reason        TEXT NULL,

    -- Status
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'archived', 'disabled', 'deleted', 'waiting_input', 'paused')),

    -- Flexible metadata (tags, lifecycle_events, etc.)
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- For FTS on metadata
    metadata_tsv        TSVECTOR GENERATED ALWAYS AS (
                            to_tsvector('english', coalesce(agent_id, '') || ' ' ||
                                        coalesce(metadata->>'description', '') || ' ' ||
                                        coalesce(metadata->>'tags', ''))
                        ) STORED
);

CREATE INDEX IF NOT EXISTS idx_identities_agent_id ON core.identities(agent_id);
CREATE INDEX IF NOT EXISTS idx_identities_status ON core.identities(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_identities_parent ON core.identities(parent_agent_id) WHERE parent_agent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_identities_created_at ON core.identities(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_identities_metadata_gin ON core.identities USING GIN (metadata jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_identities_metadata_tsv ON core.identities USING GIN (metadata_tsv);

-- Trigger to update updated_at (function already defined above)
CREATE TRIGGER trg_identities_updated_at
    BEFORE UPDATE ON core.identities
    FOR EACH ROW EXECUTE FUNCTION core.update_timestamp();

-- -----------------------------------------------------------------------------
-- Agent Sessions (session binding - matches ticket requirements)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.agent_sessions (
    agent_id            TEXT PRIMARY KEY REFERENCES core.agents(id) ON DELETE CASCADE,
    session_key         TEXT,
    bound_at            TIMESTAMPTZ,
    last_activity       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_session_key ON core.agent_sessions(session_key);

-- -----------------------------------------------------------------------------
-- Sessions (migrated from session_identities) - kept for backward compatibility
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.sessions (
    session_id          TEXT PRIMARY KEY,
    identity_id         BIGINT NOT NULL REFERENCES core.identities(identity_id) ON DELETE CASCADE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active         TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL,

    -- Client info
    client_type         TEXT NULL,                        -- sse, stdio, http
    client_info         JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Session state
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sessions_identity_id ON core.sessions(identity_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON core.sessions(expires_at) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_sessions_active ON core.sessions(is_active, last_active DESC);

-- -----------------------------------------------------------------------------
-- Agent State (EISV metrics, regime, coherence)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.agent_state (
    state_id            BIGSERIAL PRIMARY KEY,
    identity_id         BIGINT NOT NULL REFERENCES core.identities(identity_id) ON DELETE CASCADE,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- EISV metrics (denormalized for fast queries)
    entropy             REAL NOT NULL DEFAULT 0.5,
    integrity           REAL NOT NULL DEFAULT 0.5,
    stability_index     REAL NOT NULL DEFAULT 0.5,
    volatility          REAL NOT NULL DEFAULT 0.1,

    -- Derived
    regime              TEXT NOT NULL DEFAULT 'nominal'
                        CHECK (regime IN ('nominal', 'warning', 'critical', 'recovery', 'EXPLORATION', 'CONVERGENCE', 'DIVERGENCE', 'STABLE')),
    coherence           REAL NOT NULL DEFAULT 1.0,

    -- Full state snapshot (for complex queries)
    state_json          JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Unique constraint: one state per identity per timestamp
    UNIQUE (identity_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS idx_agent_state_identity_time ON core.agent_state(identity_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_state_regime ON core.agent_state(regime) WHERE regime != 'nominal';

-- -----------------------------------------------------------------------------
-- Schema Migrations (track applied migrations)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.schema_migrations (
    version             INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    applied_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Insert initial migration marker
INSERT INTO core.schema_migrations (version, name, applied_at)
VALUES (1, 'initial_schema', NOW())
ON CONFLICT (version) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Calibration (single-row config)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.calibration (
    id                  BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id = TRUE),  -- Ensures single row
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    version             INTEGER NOT NULL DEFAULT 1,
    data                JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Insert default row
INSERT INTO core.calibration (id, data)
VALUES (TRUE, '{"lambda1_threshold": 0.3, "lambda2_threshold": 0.7}'::jsonb)
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Dialectic Sessions (matches ticket requirements)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.dialectic_sessions (
    id                  TEXT PRIMARY KEY,
    session_type        TEXT,                           -- review, exploration
    status              TEXT,                           -- pending, thesis, antithesis, negotiation, resolved, timeout
    paused_agent_id     TEXT NOT NULL REFERENCES core.agents(id),
    reviewer_agent_id   TEXT NULL REFERENCES core.agents(id),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ,
    resolution          JSONB,

    -- Constraints
    CHECK (status IN ('pending', 'thesis', 'antithesis', 'negotiation', 'resolved', 'timeout')),
    CHECK (session_type IN ('review', 'exploration'))
);

CREATE INDEX IF NOT EXISTS idx_dialectic_sessions_paused_agent ON core.dialectic_sessions(paused_agent_id);
CREATE INDEX IF NOT EXISTS idx_dialectic_sessions_reviewer ON core.dialectic_sessions(reviewer_agent_id);
CREATE INDEX IF NOT EXISTS idx_dialectic_sessions_status ON core.dialectic_sessions(status);
CREATE INDEX IF NOT EXISTS idx_dialectic_sessions_created_at ON core.dialectic_sessions(created_at DESC);

-- Trigger to update updated_at
CREATE TRIGGER trg_dialectic_sessions_updated_at
    BEFORE UPDATE ON core.dialectic_sessions
    FOR EACH ROW EXECUTE FUNCTION core.update_timestamp();

-- -----------------------------------------------------------------------------
-- Dialectic Messages (migrated from dialectic_messages SQLite table)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.dialectic_messages (
    message_id            BIGSERIAL PRIMARY KEY,
    session_id            TEXT NOT NULL REFERENCES core.dialectic_sessions(id) ON DELETE CASCADE,
    agent_id              TEXT NOT NULL,
    message_type          TEXT NOT NULL,          -- 'thesis', 'antithesis', 'synthesis'
    timestamp             TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Message content
    root_cause            TEXT NULL,
    proposed_conditions   JSONB NULL,            -- JSON array
    reasoning             TEXT NULL,
    observed_metrics      JSONB NULL,             -- JSON object (for antithesis)
    concerns              JSONB NULL,             -- JSON array (for antithesis)
    agrees                BOOLEAN NULL,           -- Boolean for synthesis
    signature             TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_dialectic_messages_session ON core.dialectic_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_dialectic_messages_type ON core.dialectic_messages(message_type);
CREATE INDEX IF NOT EXISTS idx_dialectic_messages_timestamp ON core.dialectic_messages(timestamp DESC);

-- -----------------------------------------------------------------------------
-- Discovery Embeddings (for semantic search via pgvector)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.discovery_embeddings (
    discovery_id        TEXT PRIMARY KEY,
    embedding           vector(384) NOT NULL,       -- all-MiniLM-L6-v2 outputs 384 dims
    model_name          TEXT DEFAULT 'all-MiniLM-L6-v2',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_discovery_embeddings_cosine
    ON core.discovery_embeddings
    USING hnsw (embedding vector_cosine_ops);

COMMENT ON TABLE core.discovery_embeddings IS 'Vector embeddings for semantic search over knowledge graph discoveries';

-- =============================================================================
-- AUDIT SCHEMA - Time-Series Event Data (Partitioned)
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS audit;

-- -----------------------------------------------------------------------------
-- Rate Limits (for knowledge graph rate limiting)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit.rate_limits (
    agent_id            TEXT NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_rate_limits_agent_timestamp ON audit.rate_limits(agent_id, timestamp);

-- -----------------------------------------------------------------------------
-- Audit Events (partitioned by month)
-- Migrated from audit_events SQLite table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit.events (
    ts                  TIMESTAMPTZ NOT NULL,
    event_id            UUID NOT NULL DEFAULT gen_random_uuid(),
    agent_id            TEXT NULL,
    session_id          TEXT NULL,
    event_type          TEXT NOT NULL,
    confidence          REAL NOT NULL DEFAULT 1.0,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Deduplication hash (matches SQLite raw_hash)
    raw_hash            TEXT NULL,

    PRIMARY KEY (ts, event_id)
) PARTITION BY RANGE (ts);

-- FTS on payload
ALTER TABLE audit.events ADD COLUMN IF NOT EXISTS payload_tsv TSVECTOR;

-- Note: Indexes are created per-partition in partitions.sql

-- -----------------------------------------------------------------------------
-- Tool Usage (partitioned by month)
-- Migrated from tool_usage.jsonl
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit.tool_usage (
    ts                  TIMESTAMPTZ NOT NULL,
    usage_id            UUID NOT NULL DEFAULT gen_random_uuid(),
    agent_id            TEXT NULL,
    session_id          TEXT NULL,
    tool_name           TEXT NOT NULL,
    latency_ms          INTEGER NULL,
    success             BOOLEAN NOT NULL DEFAULT TRUE,
    error_type          TEXT NULL,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,

    PRIMARY KEY (ts, usage_id)
) PARTITION BY RANGE (ts);

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Hash API key for storage
CREATE OR REPLACE FUNCTION core.hash_api_key(raw_key TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN crypt(raw_key, gen_salt('bf', 8));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Verify API key
CREATE OR REPLACE FUNCTION core.verify_api_key(raw_key TEXT, stored_hash TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN stored_hash = crypt(raw_key, stored_hash);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Get or create identity (for migration)
CREATE OR REPLACE FUNCTION core.upsert_identity(
    p_agent_id TEXT,
    p_api_key_hash TEXT,
    p_parent_agent_id TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'::jsonb,
    p_created_at TIMESTAMPTZ DEFAULT now()
)
RETURNS BIGINT AS $$
DECLARE
    v_identity_id BIGINT;
BEGIN
    INSERT INTO core.identities (agent_id, api_key_hash, parent_agent_id, metadata, created_at)
    VALUES (p_agent_id, p_api_key_hash, p_parent_agent_id, p_metadata, p_created_at)
    ON CONFLICT (agent_id) DO UPDATE SET
        metadata = core.identities.metadata || p_metadata,
        updated_at = now()
    RETURNING identity_id INTO v_identity_id;

    RETURN v_identity_id;
END;
$$ LANGUAGE plpgsql;

-- Session cleanup (call periodically or via pg_cron)
CREATE OR REPLACE FUNCTION core.cleanup_expired_sessions()
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    WITH deleted AS (
        DELETE FROM core.sessions
        WHERE expires_at < now() OR (is_active = FALSE AND last_active < now() - INTERVAL '1 hour')
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_count FROM deleted;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- VIEWS
-- =============================================================================

-- Active identities with latest state
CREATE OR REPLACE VIEW core.v_active_identities AS
SELECT
    i.identity_id,
    i.agent_id,
    i.status,
    i.created_at,
    i.parent_agent_id,
    i.metadata,
    s.entropy,
    s.integrity,
    s.stability_index,
    s.volatility,
    s.regime,
    s.coherence,
    s.recorded_at as state_recorded_at
FROM core.identities i
LEFT JOIN LATERAL (
    SELECT * FROM core.agent_state
    WHERE identity_id = i.identity_id
    ORDER BY recorded_at DESC
    LIMIT 1
) s ON TRUE
WHERE i.status = 'active';

-- Session activity summary
CREATE OR REPLACE VIEW core.v_session_activity AS
SELECT
    i.agent_id,
    COUNT(s.session_id) as total_sessions,
    COUNT(s.session_id) FILTER (WHERE s.is_active) as active_sessions,
    MAX(s.last_active) as last_active,
    MIN(s.created_at) as first_session
FROM core.identities i
LEFT JOIN core.sessions s ON i.identity_id = s.identity_id
GROUP BY i.identity_id, i.agent_id;

-- =============================================================================
-- GRANTS (adjust for your roles)
-- =============================================================================

-- Example: GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA core TO governance_app;
-- Example: GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA audit TO governance_app;

COMMENT ON SCHEMA core IS 'Core operational tables for governance system';
COMMENT ON SCHEMA audit IS 'Partitioned audit/event tables with retention policy';
