-- Migration 001: Initial schema setup
-- This is a marker migration - the initial schema is in schema.sql
-- Apply with: psql -f db/postgres/schema.sql

-- Migration metadata
INSERT INTO core.schema_migrations (version, name, applied_at)
VALUES (1, 'initial_schema', NOW())
ON CONFLICT (version) DO NOTHING;
