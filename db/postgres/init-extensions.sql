-- Initialize extensions for governance database
-- This runs automatically when the container starts with an empty data volume

-- Core extensions (already in apache/age)
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Log success
DO $$ BEGIN RAISE NOTICE 'Extensions initialized: age, pgcrypto, pg_trgm, uuid-ossp, vector'; END $$;
