# PostgreSQL + Apache AGE Setup

This directory contains the schema and setup files for migrating to PostgreSQL with Apache AGE extension.

## Files

- `schema.sql` - PostgreSQL relational schema (agents, sessions, dialectic, etc.)
- `knowledge_schema.sql` - Knowledge graph relational tables (PostgreSQL FTS fallback)
- `graph_schema.cypher` - AGE graph schema documentation and setup
- `embeddings_schema.sql` - pgvector embeddings for semantic search
- `partitions.sql` - (Optional) Partition management for audit tables
- `migrations/` - Schema versioning migrations

## Setup Instructions

### 1. Install PostgreSQL

```bash
# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib

# macOS
brew install postgresql

# Or use Docker
docker run -d --name postgres-governance \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=governance \
  -p 5432:5432 \
  postgres:15
```

### 2. Install Apache AGE Extension

```bash
# Clone AGE repository
git clone https://github.com/apache/age.git
cd age

# Follow AGE installation instructions
# See the Apache AGE setup guide (docs site).
```

Or use the AGE Docker image:

```bash
docker run -d --name postgres-age \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=governance \
  -p 5432:5432 \
  apache/age:latest
```

### 3. Create Database and Schema

```bash
# Connect to PostgreSQL
psql -U postgres -d governance

# Run schema
\i db/postgres/schema.sql

# Verify AGE extension / graph
SELECT * FROM ag_catalog.create_graph('governance_graph');
```

### 4. Configure Environment

```bash
export DB_BACKEND=postgres
export DB_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/governance
export DB_AGE_GRAPH=governance_graph
```

### 4.1 Graph name convention (important)

This repo standardizes on the AGE graph name **`governance_graph`**.

- **Why**: the Postgres backend uses `DB_AGE_GRAPH` (defaulting to `governance_graph`) when calling `cypher(...)`.
- **Rule**: if you create a different graph name locally, set `DB_AGE_GRAPH` accordingly or graph queries will fail.

### 4.2 Knowledge Graph Backend Selection

The main runtime DB backend is controlled by `DB_BACKEND`, but the **knowledge graph** also supports backend override via `UNITARES_KNOWLEDGE_BACKEND`:

| Backend | Value | Description |
|---------|-------|-------------|
| **AGE** (recommended) | `age` | PostgreSQL + Apache AGE graph database |
| **PostgreSQL FTS** | `postgres` | Native PostgreSQL with tsvector full-text search |
| **SQLite** (legacy) | `sqlite` | Original SQLite FTS5 backend |
| **Auto** (default) | `auto` | Selects `age` if available, falls back to `postgres` if `DB_BACKEND=postgres` |

```bash
# Recommended: Use AGE for graph operations
export UNITARES_KNOWLEDGE_BACKEND=age

# Alternative: PostgreSQL FTS (no AGE dependency)
export UNITARES_KNOWLEDGE_BACKEND=postgres

# Auto-select based on DB_BACKEND setting
export UNITARES_KNOWLEDGE_BACKEND=auto
```

**Note:** When `UNITARES_KNOWLEDGE_BACKEND=auto` (default), the system will:
1. Try AGE if `age` module is available
2. Fall back to PostgreSQL FTS if `DB_BACKEND=postgres`
3. Fall back to SQLite otherwise

### 5. Run Migration

```bash
# Dry run first
python scripts/migrate_to_postgres_age.py --dry-run

# Actual migration
python scripts/migrate_to_postgres_age.py
```

### 5.1 Knowledge Graph Migration (SQLite to PostgreSQL)

If you have existing knowledge graph data in SQLite (`data/governance.db`):

```bash
# Preview what will be migrated
python scripts/migrate_knowledge_to_postgres.py --dry-run

# Run migration
python scripts/migrate_knowledge_to_postgres.py --batch-size 100
```

This migrates discoveries, tags, and edges from SQLite to the PostgreSQL knowledge schema.

## Schema Overview

### Relational Tables (core schema)

- `core.agents` - Agent identity and metadata
- `core.agent_sessions` - Session bindings (fast lookup)
- `core.dialectic_sessions` - Dialectic recovery sessions
- `core.identities` - (Legacy) Identity records for backward compatibility
- `core.schema_migrations` - Schema version tracking

### Knowledge Schema (knowledge schema)

When using PostgreSQL FTS backend (`UNITARES_KNOWLEDGE_BACKEND=postgres`):

- `knowledge.discoveries` - Knowledge discoveries with native tsvector FTS
- `knowledge.discovery_tags` - Normalized tag storage
- `knowledge.discovery_edges` - Graph-like edges (related_to, response_to)

### Graph (AGE)

- **Nodes:**
  - `:Discovery` - Knowledge discoveries (insights, questions, self_observations)
  - `:Agent` - Agent nodes (mirror of relational table)
  - `:Tag` - Tag nodes for efficient traversal

- **Edges:**
  - `:AUTHORED` - (Agent)-[:AUTHORED]->(Discovery)
  - `:RESPONDS_TO` - (Discovery)-[:RESPONDS_TO]->(Discovery)
  - `:RELATED_TO` - (Discovery)-[:RELATED_TO]->(Discovery)
  - `:TAGGED` - (Discovery)-[:TAGGED]->(Tag)
  - `:TEMPORALLY_NEAR` - (Discovery)-[:TEMPORALLY_NEAR]->(Discovery)

## Example Queries

See `db/postgres/graph_schema.cypher` for example Cypher queries.

## Sanity checks (quick validation)

After running the schema, these checks catch 90% of setup mistakes:

```bash
# 1) Confirm Postgres connectivity
psql $DB_POSTGRES_URL -c "SELECT 1"

# 2) Confirm AGE extension exists
psql $DB_POSTGRES_URL -c "SELECT name, installed_version FROM pg_available_extensions WHERE name='age'"

# 3) Confirm the graph exists
psql $DB_POSTGRES_URL -c "SELECT graphid, name FROM ag_catalog.ag_graph WHERE name='governance_graph'"
```

## Schema Versioning

Schema versions are tracked in `core.schema_migrations`:

```sql
SELECT version, name, applied_at FROM core.schema_migrations ORDER BY version;
```

| Version | Migration | Description |
|---------|-----------|-------------|
| 1 | `initial_schema` | Core tables (agents, sessions, dialectic) |
| 2 | `knowledge_schema` | Knowledge graph tables for PostgreSQL FTS |

The health check returns `schema_version` from this table.

## Health Check Status

The `/health_check` tool returns a three-tier aggregate status:

| Status | Condition |
|--------|-----------|
| `healthy` | All components report healthy |
| `moderate` | Some components have warnings/deprecated status, but no errors |
| `critical` | One or more components report error |

The response includes a `status_breakdown` field showing counts per status type.

## Migration Phases

1. **Phase 1**: PostgreSQL tables for agents, sessions (keep JSON/SQLite for discoveries)
2. **Phase 2**: Install AGE, create graph, dual-write discoveries
3. **Phase 3**: Backfill historical discoveries to graph
4. **Phase 4**: Cut over reads to AGE
5. **Phase 5**: Deprecate JSON/SQLite (current state)

## Troubleshooting

### AGE query errors / “cypher function not found”

- Ensure the extension is installed and loaded:
  - `CREATE EXTENSION IF NOT EXISTS age;`
- In some setups you may need to load AGE per-session:
  - `LOAD 'age';`
  - `SET search_path = ag_catalog, "$user", public;`

### AGE Extension Not Found

```sql
-- Check if AGE is installed
SELECT * FROM pg_available_extensions WHERE name = 'age';

-- If not installed, follow AGE installation guide
```

### Graph Already Exists

```sql
-- Drop and recreate (WARNING: deletes all graph data)
SELECT * FROM ag_catalog.drop_graph('governance_graph', true);
SELECT * FROM ag_catalog.create_graph('governance_graph');
```

### Connection Issues

```bash
# Test connection
psql $DB_POSTGRES_URL -c "SELECT 1"

# Check pool settings
export DB_POSTGRES_MIN_CONN=2
export DB_POSTGRES_MAX_CONN=10
```

### Common pitfalls

- **Graph name mismatch**: your graph is not `governance_graph` but `DB_AGE_GRAPH` wasn’t updated.
- **Extension not enabled in the DB**: you installed AGE on the host but didn’t run `CREATE EXTENSION age;` inside the target database.
- **Running migration before schema**: `scripts/migrate_to_postgres_age.py` assumes `db/postgres/schema.sql` has been applied.

