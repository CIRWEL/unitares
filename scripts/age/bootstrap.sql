-- Apache AGE bootstrap for local prototyping.
--
-- Usage:
--   docker compose -f scripts/age/docker-compose.age.yml up -d
--   docker exec -i postgres-age psql -U postgres -d postgres < scripts/age/bootstrap.sql
--
-- Notes:
-- - AGE requires loading the extension and setting search_path for each session.
-- - We create a single graph named 'governance_graph' to match the codebase default.

CREATE EXTENSION IF NOT EXISTS age;

-- Required per-session, but safe to include here.
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Create graph (idempotent-ish): ignore if it already exists.
DO $$
BEGIN
  PERFORM create_graph('governance_graph');
EXCEPTION
  WHEN duplicate_object THEN
    NULL;
END $$;

-- Optional: sanity check
SELECT * FROM ag_catalog.ag_graph WHERE name = 'governance_graph';

