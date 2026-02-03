-- Migration 002: Add knowledge schema
-- This adds the knowledge graph tables from knowledge_schema.sql

-- Run the knowledge schema SQL
\i db/postgres/knowledge_schema.sql

-- Migration metadata
INSERT INTO core.schema_migrations (version, name, applied_at)
VALUES (2, 'knowledge_schema', NOW())
ON CONFLICT (version) DO NOTHING;
