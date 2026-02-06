-- Migration 003: Add dialectic_messages table
-- Migrates dialectic messages from SQLite to PostgreSQL
-- Data migration: scripts/migrate_dialectic_to_postgres.py

CREATE TABLE IF NOT EXISTS core.dialectic_messages (
    id                    SERIAL PRIMARY KEY,
    session_id            TEXT NOT NULL REFERENCES core.dialectic_sessions(id) ON DELETE CASCADE,
    message_type          TEXT NOT NULL,
    agent_id              TEXT,
    content               JSONB DEFAULT '{}',
    root_cause            TEXT,
    proposed_conditions   JSONB DEFAULT '[]',
    concerns              JSONB DEFAULT '[]',
    reasoning             TEXT,
    agrees                BOOLEAN,
    observed_metrics      JSONB DEFAULT '{}',
    timestamp             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dialectic_messages_session ON core.dialectic_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_dialectic_messages_type ON core.dialectic_messages(message_type);
CREATE INDEX IF NOT EXISTS idx_dialectic_messages_timestamp ON core.dialectic_messages(timestamp DESC);

-- Migration metadata
INSERT INTO core.schema_migrations (version, name, applied_at)
VALUES (3, 'dialectic_messages', NOW())
ON CONFLICT (version) DO NOTHING;
