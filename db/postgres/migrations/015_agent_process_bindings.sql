-- 015_agent_process_bindings.sql
--
-- Concurrent identity binding invariant (issue #123).
--
-- Records the execution context a client declares at onboard() so the server
-- can detect "one UUID, two concurrently live execution contexts" — the
-- same-UUID siphoning pattern that ip_ua_fingerprint alone does not catch
-- for same-machine clients (IP+UA is identical across two Claude Code
-- instances on the same host).
--
-- V1 is audit-only: rows are recorded on every onboard(), a sweeper marks
-- them stale, and a detection pass emits `identity_concurrent_binding`
-- events when ≥2 live bindings for the same agent have distinct execution
-- contexts and the agent's policy flag `allow_concurrent_contexts` is false
-- (the default). No automatic force-new in v1 — see issue #123 §"Scope".
--
-- Execution-context key is (host_id, pid, pid_start_time, transport).
-- pid_start_time disambiguates PID reuse; host_id disambiguates
-- multi-machine deployments; transport distinguishes stdio / http / ws for
-- the same pid. tty, ppid, and anchor_path_hash are evidence fields, not
-- identity keys.

CREATE TABLE IF NOT EXISTS core.agent_process_bindings (
    id BIGSERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES core.agents(id) ON DELETE CASCADE,

    -- Execution context key (four-tuple)
    host_id TEXT NOT NULL,
    pid INTEGER NOT NULL,
    pid_start_time DOUBLE PRECISION NOT NULL,  -- seconds since epoch, ms precision is enough
    transport TEXT NOT NULL DEFAULT 'unknown',

    -- Evidence fields (not part of the identity key)
    ppid INTEGER NULL,
    tty TEXT NULL,                    -- nullable: daemons have no TTY
    anchor_path_hash TEXT NULL,       -- SHA-256 of anchor file path if resident
    client_session_id TEXT NULL,

    -- Lifecycle
    onboard_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stale_at TIMESTAMPTZ NULL,        -- set by sweeper when binding is no longer live

    CONSTRAINT uq_agent_process_binding
        UNIQUE (agent_id, host_id, pid, pid_start_time, transport)
);

-- Hot path: lookup live bindings for an agent (detection rule).
CREATE INDEX IF NOT EXISTS idx_apb_agent_live
    ON core.agent_process_bindings (agent_id, stale_at)
    WHERE stale_at IS NULL;

-- Sweeper path: find stale candidates by last_seen.
CREATE INDEX IF NOT EXISTS idx_apb_last_seen
    ON core.agent_process_bindings (last_seen)
    WHERE stale_at IS NULL;

-- Diagnose view path: all bindings for an agent ordered by recency.
CREATE INDEX IF NOT EXISTS idx_apb_agent_recency
    ON core.agent_process_bindings (agent_id, last_seen DESC);

-- Policy flags on core.agents. Defaults preserve current behavior:
--   allow_rebind_after_exit = false  — ephemeral agents don't rebind.
--   allow_concurrent_contexts = false — nothing allows concurrent contexts today.
-- Resident agents get allow_rebind_after_exit=true via seeding (separate step,
-- not this migration — residents are configured out-of-band).
ALTER TABLE core.agents
    ADD COLUMN IF NOT EXISTS allow_rebind_after_exit BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE core.agents
    ADD COLUMN IF NOT EXISTS allow_concurrent_contexts BOOLEAN NOT NULL DEFAULT FALSE;

-- Register the migration.
INSERT INTO core.schema_migrations (version, name, applied_at)
VALUES (15, 'agent_process_bindings', NOW())
ON CONFLICT (version) DO NOTHING;
