-- Migration 011: Behavioral baselines table for Welford online stats persistence
-- Stores per-agent Welford stats (mean, variance, count) for behavioral signals
-- so they survive server restarts.

CREATE TABLE IF NOT EXISTS core.agent_behavioral_baselines (
    agent_id    TEXT PRIMARY KEY REFERENCES core.agents(id) ON DELETE CASCADE,
    stats       JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Record migration
INSERT INTO core.schema_migrations (version, name)
VALUES (11, 'behavioral baselines welford stats')
ON CONFLICT (version) DO NOTHING;
