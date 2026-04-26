-- 017_substrate_claims.sql
--
-- S19: Resume-time substrate attestation for R4-claiming agents.
--
-- Stores the operator-pre-seeded substrate-claim registry that the governance
-- MCP consults at UDS connection-accept to verify a substrate-anchored
-- resident agent (Vigil, Sentinel, Chronicler) is actually running under its
-- registered launchd label and from its registered binary path.
--
-- See docs/proposals/s19-attestation-mechanism.md (M3-v2) for the full
-- mechanism. Briefly: at UDS connect, server reads kernel-attested peer PID
-- via SO_PEERCRED, queries `launchctl print pid/<peer_pid>` for the actual
-- label, `proc_pidpath` for the actual executable, and `proc_pidinfo` for
-- pid_start_time. Label + executable_path must match the registered values;
-- pid_start_time is cached in-process for PID-reuse mitigation.
--
-- expected_executable_path is the v2 addition that closes the binary-
-- substitution escalation of A2 (adversary-review §1) — without it, an
-- attacker who can write to the binary path can replace the binary,
-- kickstart the launchd job, and pass the label-match check.
--
-- This migration creates the registry table only. The pid_start_time cache
-- is in-process per-server-lifetime (not persisted). Verification logic and
-- enrollment runtime ship in subsequent PRs per v2 §Sequencing steps 2–6.
--
-- Watcher is excluded from S19 scope (per proposal v2). Substrate-claim
-- registry rows are NOT expected for Watcher.

CREATE TABLE IF NOT EXISTS core.substrate_claims (
    -- The agent's UUID (stored as TEXT per project convention; see
    -- core.identities.agent_id and core.agents.id). One row per substrate-
    -- anchored agent.
    agent_id TEXT PRIMARY KEY REFERENCES core.agents(id) ON DELETE CASCADE,

    -- The launchd label this UUID is registered under (e.g.
    -- 'com.unitares.sentinel'). Verified at connection-accept against
    -- `launchctl print pid/<peer_pid>` output.
    expected_launchd_label TEXT NOT NULL,

    -- The absolute filesystem path of the resident's executable. Verified at
    -- connection-accept against `proc_pidpath(peer_pid)`. Closes the binary-
    -- substitution escalation of A2.
    expected_executable_path TEXT NOT NULL,

    -- TRUE when the operator ran enroll_resident.py with explicit input.
    -- A future TOFU mode (not v1) would set this FALSE; v1 enrollment always
    -- runs operator-seeded, so this column is informational + future-proofing.
    enrolled_by_operator BOOLEAN NOT NULL DEFAULT TRUE,

    -- Recorded when the operator ran enrollment. Useful for incident review:
    -- if a substrate-claim row is older than the resident's deployment, it
    -- predates the deployment and should be re-enrolled.
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Free-form notes from the operator at enrollment time (e.g. the binary-
    -- path-writable warning text, the deployment context). Audit-friendly.
    notes TEXT NULL
);

-- Audit path: list all substrate claims by enrollment recency.
-- (Hot-path lookup at connection-accept is by primary key; no extra index needed.)
CREATE INDEX IF NOT EXISTS idx_substrate_claims_enrolled_at
    ON core.substrate_claims (enrolled_at DESC);

-- Register the migration.
INSERT INTO core.schema_migrations (version, name, applied_at)
VALUES (17, 'substrate_claims', NOW())
ON CONFLICT (version) DO NOTHING;
