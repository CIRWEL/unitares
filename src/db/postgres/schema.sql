-- PostgreSQL + AGE Schema for Governance System
-- Run this to initialize the database: psql -d governance -f schema.sql

-- ============================================================================
-- EXTENSIONS
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Note: AGE extension must be installed separately (docker image has it)
-- LOAD 'age'; -- Run manually after connecting

-- ============================================================================
-- SCHEMAS
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS audit;

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Agents (core agent identity - matches ticket requirements)
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

-- Identities (agents) - kept for backward compatibility
CREATE TABLE IF NOT EXISTS core.identities (
    identity_id SERIAL PRIMARY KEY,
    agent_id VARCHAR(255) UNIQUE NOT NULL REFERENCES core.agents(id) ON DELETE CASCADE,
    api_key_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    status VARCHAR(50) DEFAULT 'active',
    parent_agent_id VARCHAR(255) REFERENCES core.agents(id),
    spawn_reason TEXT,
    disabled_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Trigger to update updated_at (function already defined above)
CREATE TRIGGER trg_identities_updated_at
    BEFORE UPDATE ON core.identities
    FOR EACH ROW EXECUTE FUNCTION core.update_timestamp();

CREATE INDEX IF NOT EXISTS idx_identities_agent_id ON core.identities(agent_id);
CREATE INDEX IF NOT EXISTS idx_identities_status ON core.identities(status);
CREATE INDEX IF NOT EXISTS idx_identities_parent ON core.identities(parent_agent_id);

-- Sessions
CREATE TABLE IF NOT EXISTS core.sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    identity_id INTEGER NOT NULL REFERENCES core.identities(identity_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_active TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    client_type VARCHAR(100),
    client_info JSONB DEFAULT '{}'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sessions_identity ON core.sessions(identity_id);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON core.sessions(is_active, expires_at);

-- Agent State (EISV metrics)
CREATE TABLE IF NOT EXISTS core.agent_state (
    state_id SERIAL PRIMARY KEY,
    identity_id INTEGER NOT NULL REFERENCES core.identities(identity_id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ DEFAULT now(),
    entropy DOUBLE PRECISION DEFAULT 0.5,
    integrity DOUBLE PRECISION DEFAULT 0.5,
    stability_index DOUBLE PRECISION DEFAULT 0.5,
    volatility DOUBLE PRECISION DEFAULT 0.1,
    regime VARCHAR(50) DEFAULT 'nominal',
    coherence DOUBLE PRECISION DEFAULT 1.0,
    state_json JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_agent_state_identity ON core.agent_state(identity_id);
CREATE INDEX IF NOT EXISTS idx_agent_state_time ON core.agent_state(identity_id, recorded_at DESC);

-- Calibration (single row, keyed by TRUE)
CREATE TABLE IF NOT EXISTS core.calibration (
    id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id = TRUE),  -- Forces single row
    data JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT now(),
    version INTEGER DEFAULT 1
);

-- Insert default calibration
INSERT INTO core.calibration (id, data, updated_at, version)
VALUES (TRUE, '{"lambda1_threshold": 0.3, "lambda2_threshold": 0.7}', now(), 1)
ON CONFLICT (id) DO NOTHING;

-- Dialectic Sessions
CREATE TABLE IF NOT EXISTS core.dialectic_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    paused_agent_id VARCHAR(255) NOT NULL REFERENCES core.agents(id),
    reviewer_agent_id VARCHAR(255) REFERENCES core.agents(id),
    phase VARCHAR(50) DEFAULT 'thesis',
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    reason TEXT,
    discovery_id VARCHAR(255),
    dispute_type VARCHAR(100),
    session_type VARCHAR(100),
    topic TEXT,
    max_synthesis_rounds INTEGER,
    synthesis_round INTEGER DEFAULT 0,
    paused_agent_state_json JSONB,
    resolution_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_dialectic_paused ON core.dialectic_sessions(paused_agent_id, status);
CREATE INDEX IF NOT EXISTS idx_dialectic_reviewer ON core.dialectic_sessions(reviewer_agent_id, status);

-- Trigger to update updated_at (function already defined above)
CREATE TRIGGER trg_dialectic_sessions_updated_at
    BEFORE UPDATE ON core.dialectic_sessions
    FOR EACH ROW EXECUTE FUNCTION core.update_timestamp();

-- Dialectic Messages
CREATE TABLE IF NOT EXISTS core.dialectic_messages (
    message_id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL REFERENCES core.dialectic_sessions(session_id) ON DELETE CASCADE,
    agent_id VARCHAR(255) NOT NULL,
    message_type VARCHAR(50) NOT NULL,  -- thesis, antithesis, synthesis
    timestamp TIMESTAMPTZ DEFAULT now(),
    root_cause TEXT,
    proposed_conditions JSONB,
    reasoning TEXT,
    observed_metrics JSONB,
    concerns JSONB,
    agrees BOOLEAN,
    signature VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_dialectic_messages_session ON core.dialectic_messages(session_id);

-- ============================================================================
-- AUDIT TABLES
-- ============================================================================

-- Audit Events
CREATE TABLE IF NOT EXISTS audit.events (
    ts TIMESTAMPTZ DEFAULT now(),
    event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id VARCHAR(255),
    session_id VARCHAR(255),
    event_type VARCHAR(100) NOT NULL,
    confidence DOUBLE PRECISION DEFAULT 1.0,
    payload JSONB DEFAULT '{}'::jsonb,
    raw_hash VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_audit_agent_time ON audit.events(agent_id, ts);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit.events(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit.events(ts DESC);

-- Tool Usage
CREATE TABLE IF NOT EXISTS audit.tool_usage (
    usage_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ts TIMESTAMPTZ DEFAULT now(),
    agent_id VARCHAR(255),
    session_id VARCHAR(255),
    tool_name VARCHAR(100) NOT NULL,
    latency_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    error_type VARCHAR(100),
    payload JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_tool_usage_agent ON audit.tool_usage(agent_id, ts);
CREATE INDEX IF NOT EXISTS idx_tool_usage_tool ON audit.tool_usage(tool_name, ts);

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Verify API key (simple hash comparison - uses SHA256)
CREATE OR REPLACE FUNCTION core.verify_api_key(input_key TEXT, stored_hash TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    -- For now, simple comparison. In production, use proper bcrypt or argon2
    RETURN encode(digest(input_key, 'sha256'), 'hex') = stored_hash
        OR encode(digest(input_key, 'sha256'), 'base64') = stored_hash
        OR input_key = stored_hash;  -- Allow plaintext match for migration
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Cleanup expired sessions
CREATE OR REPLACE FUNCTION core.cleanup_expired_sessions()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM core.sessions
    WHERE expires_at < now() OR (is_active = FALSE AND last_active < now() - INTERVAL '7 days');
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- AGE GRAPH (run after LOAD 'age')
-- ============================================================================
-- These commands must be run after loading AGE extension:
--
-- LOAD 'age';
-- SET search_path = ag_catalog, core, audit, public;
-- SELECT create_graph('governance');
--
-- Vertex labels:
-- SELECT create_vlabel('governance', 'Agent');
-- SELECT create_vlabel('governance', 'Discovery');
-- SELECT create_vlabel('governance', 'Session');
-- SELECT create_vlabel('governance', 'Concept');
-- SELECT create_vlabel('governance', 'Topic');
-- SELECT create_vlabel('governance', 'Note');
--
-- Edge labels:
-- SELECT create_elabel('governance', 'DISCOVERED');
-- SELECT create_elabel('governance', 'SPAWNED_FROM');
-- SELECT create_elabel('governance', 'PARTICIPATED_IN');
-- SELECT create_elabel('governance', 'RELATED_TO');
-- SELECT create_elabel('governance', 'EVOLVED_INTO');
-- SELECT create_elabel('governance', 'REFERENCES');
-- SELECT create_elabel('governance', 'AUTHORED');
-- SELECT create_elabel('governance', 'TAGGED_WITH');
-- SELECT create_elabel('governance', 'CONNECTED_TO');
-- SELECT create_elabel('governance', 'INFLUENCES');
-- SELECT create_elabel('governance', 'CONTINUATION_OF');
-- SELECT create_elabel('governance', 'EXTENDS');

-- ============================================================================
-- GRANT PERMISSIONS (adjust user as needed)
-- ============================================================================
-- GRANT USAGE ON SCHEMA core TO governance_app;
-- GRANT USAGE ON SCHEMA audit TO governance_app;
-- GRANT ALL ON ALL TABLES IN SCHEMA core TO governance_app;
-- GRANT ALL ON ALL TABLES IN SCHEMA audit TO governance_app;
-- GRANT ALL ON ALL SEQUENCES IN SCHEMA core TO governance_app;
-- GRANT ALL ON ALL SEQUENCES IN SCHEMA audit TO governance_app;
