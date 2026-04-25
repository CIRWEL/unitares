-- 016_same_host_ppid_consistent.sql
--
-- Same-host ppid consistency check (issue #128).
--
-- Adds `same_host_ppid_consistent` to core.agent_process_bindings: a
-- *scope-bounded* confidence signal on a child's self-declared
-- parent_agent_id. The server compares child.ppid against the parent's
-- most recent live bindings on the same host_id only.
--
--   NULL  — not checked (no parent live binding on host, or cross-host)
--   TRUE  — child.ppid matches one of the parent's live pids on this host
--   FALSE — parent has live bindings on the host but none match child.ppid
--           (also emits identity_same_host_ppid_mismatch audit event)
--
-- Audit-only — no behavioral change. Same observation-only posture as
-- the parent invariant in #123. The column name and event name are
-- deliberately scoped to "same_host_ppid" to avoid implying that absence
-- of a mismatch event means cross-host lineage was verified.
--
-- See src/mcp_handlers/identity/lineage_verification.py for verdict logic.
--
-- NOTE: applied out-of-order in some environments. Migrations 014 and 015
-- may not yet be applied on long-lived databases that pre-date them.
-- Both are independent ADDs; this one only touches a table created by 015,
-- so 015 must be applied before 016 wherever it is being applied.

ALTER TABLE core.agent_process_bindings
    ADD COLUMN IF NOT EXISTS same_host_ppid_consistent BOOLEAN NULL;

INSERT INTO core.schema_migrations (version, name, applied_at)
VALUES (16, 'same_host_ppid_consistent', NOW())
ON CONFLICT (version) DO NOTHING;
