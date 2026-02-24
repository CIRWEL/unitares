-- Migration 004: Outcome Events
-- Adds audit.outcome_events table for pairing EISV snapshots with measurable outcomes
-- This enables validation of the EISV model: do verdicts/phi predict real results?

-- Outcome events table (partitioned by timestamp, same pattern as tool_usage)
CREATE TABLE IF NOT EXISTS audit.outcome_events (
    ts              TIMESTAMPTZ NOT NULL,
    outcome_id      UUID NOT NULL DEFAULT gen_random_uuid(),
    agent_id        TEXT NOT NULL,
    session_id      TEXT,
    outcome_type    TEXT NOT NULL,       -- drawing_completed, drawing_abandoned, test_passed, test_failed, tool_rejected, task_completed, task_failed
    outcome_score   REAL,               -- 0.0=worst, 1.0=best (drawing: satisfaction, test: pass rate)
    is_bad          BOOLEAN NOT NULL,
    -- Embedded EISV snapshot at outcome time
    eisv_e          REAL,
    eisv_i          REAL,
    eisv_s          REAL,
    eisv_v          REAL,
    eisv_phi        REAL,
    eisv_verdict    TEXT,
    eisv_coherence  REAL,
    eisv_regime     TEXT,
    detail          JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (ts, outcome_id)
) PARTITION BY RANGE (ts);

-- Indexes (created on parent; inherited by partitions)
CREATE INDEX IF NOT EXISTS idx_outcome_events_agent_ts
    ON audit.outcome_events (agent_id, ts DESC);

CREATE INDEX IF NOT EXISTS idx_outcome_events_type_ts
    ON audit.outcome_events (outcome_type, ts DESC);

CREATE INDEX IF NOT EXISTS idx_outcome_events_bad_ts
    ON audit.outcome_events (is_bad, ts DESC);

-- Record migration
INSERT INTO core.schema_migrations (version, name)
VALUES (4, 'Add audit.outcome_events for EISV validation')
ON CONFLICT (version) DO NOTHING;
