-- Migration 037: knowledge.discoveries.provenance_chain column
--
-- Closes a code-vs-DB schema drift: src/knowledge_graph.py:100 declares
-- DiscoveryNode.provenance_chain as a separate field, src/db/mixins/
-- knowledge_graph.py:80 INSERTs into a `provenance_chain` column on
-- knowledge.discoveries, and src/identity/provenance_index_readiness.py:25-28
-- queries `COUNT(*) FILTER (WHERE provenance_chain IS NOT NULL)` plus a
-- GIN index named idx_knowledge_discoveries_provenance_chain_s7_gin —
-- but no migration ever added the column.
--
-- Effect of the drift: every knowledge(action='store') call returns
-- "column 'provenance_chain' of relation 'discoveries' does not exist"
-- and fails with HTTP 500 / NOT_FOUND. Discovered 2026-05-07 during a
-- deep-dogfood loop trying to record a watcher-hygiene observation.
--
-- Doctor (scripts/dev/unitares_doctor.py) didn't catch it — the doctor's
-- schema_migrations check validates manifest parity (versions in db match
-- versions in source files) but does not validate that columns the code
-- references actually exist in the running DB. Same blind-spot class as
-- the 2026-04-17 last_activity_at incident and the 2026-04-19
-- trigger_source outage.
--
-- Field semantics (per src/provenance_context.py:4): provenance_chain
-- stores S7 lineage snapshots, kept separate from `provenance` (jsonb,
-- already exists) which holds identity-proof / writer-context fields.
-- Column is NULLABLE with no default to preserve the existing code path
-- semantics: kg_add_discovery passes NULL when no chain is set, and the
-- readiness check at src/identity/provenance_index_readiness.py:25
-- counts rows WHERE provenance_chain IS NOT NULL — i.e. rows that
-- explicitly carry lineage data. A NOT NULL DEFAULT '[]' would break
-- both: it would constraint-violate on NULL inserts and would inflate
-- the readiness count to total-row-count.

ALTER TABLE knowledge.discoveries
    ADD COLUMN IF NOT EXISTS provenance_chain jsonb;

COMMENT ON COLUMN knowledge.discoveries.provenance_chain IS
    'S7 lineage snapshots; separate from `provenance` which holds identity-proof / writer-context. NULL when no chain is set. See src/identity/provenance_chain.py and docs/proposals/refined-phase-5-evidence-contract.md for shape.';

-- GIN index named to match what provenance_index_readiness.py:234 reports
-- as a known surface. Partial WHERE clause matches the readiness check's
-- filter so the index serves both readiness counts and lineage queries.
CREATE INDEX IF NOT EXISTS idx_knowledge_discoveries_provenance_chain_s7_gin
    ON knowledge.discoveries USING gin (provenance_chain jsonb_path_ops)
    WHERE provenance_chain IS NOT NULL;

INSERT INTO core.schema_migrations (version, name, applied_at)
VALUES (37, 'discoveries_provenance_chain', NOW())
ON CONFLICT (version) DO NOTHING;
