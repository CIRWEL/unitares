-- Migration 006: Thread-Based Identity with Honest Forking
--
-- A thread is the user's conversation — the true identity anchor.
-- A fork is a new agent UUID linked to a parent, with a numbered position.
-- Discontinuities are made legible, not hidden (kintsugi model).

-- Thread registry: one row per user conversation
CREATE TABLE IF NOT EXISTS core.threads (
    thread_id     TEXT PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    next_node_seq INTEGER NOT NULL DEFAULT 1
);

-- Link agents to their thread (nullable — existing agents are unthreaded)
ALTER TABLE core.agents
    ADD COLUMN IF NOT EXISTS thread_id TEXT REFERENCES core.threads(thread_id),
    ADD COLUMN IF NOT EXISTS thread_position INTEGER;

CREATE INDEX IF NOT EXISTS idx_agents_thread
    ON core.agents(thread_id) WHERE thread_id IS NOT NULL;

-- Atomic function: claim next node position in a thread
-- Returns the position number (1-based). Thread must exist.
CREATE OR REPLACE FUNCTION core.claim_thread_position(p_thread_id TEXT)
RETURNS INTEGER AS $$
DECLARE
    v_pos INTEGER;
BEGIN
    UPDATE core.threads
    SET next_node_seq = next_node_seq + 1
    WHERE thread_id = p_thread_id
    RETURNING next_node_seq - 1 INTO v_pos;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Thread not found: %', p_thread_id;
    END IF;

    RETURN v_pos;
END;
$$ LANGUAGE plpgsql;

INSERT INTO core.schema_migrations (version, name)
VALUES (6, 'thread_identity_with_honest_forking')
ON CONFLICT (version) DO NOTHING;
