# Apache AGE Prototype (Optional)

This repo’s **canonical runtime store is SQLite** (`data/governance.db`). If you want to evaluate whether graph-native queries are worth it (multi-hop traversal, path queries, etc.), you can prototype Apache AGE (Postgres + Cypher) **without changing the running server**.

## What this prototype covers

- **Agents (optional; exported by default)**
  - `(:Agent {id, status, created_at, ...})`
  - `(:Agent)-[:SPAWNED]->(:Agent)` from `agent_metadata.parent_agent_id`
  - `(:Agent)-[:HAS_TAG]->(:Tag)` from `agent_metadata.tags_json`

- **Dialectic (optional; exported by default)**
  - `(:DialecticSession {id, status, phase, ...})` from `dialectic_sessions`
  - `(:DialecticMessage {id, seq, message_type, ...})` from `dialectic_messages`
  - Edges:
    - `(:DialecticSession)-[:PAUSED_AGENT]->(:Agent)`
    - `(:DialecticSession)-[:REVIEWER]->(:Agent)`
    - `(:DialecticSession)-[:HAS_MESSAGE]->(:DialecticMessage)`
    - `(:Agent)-[:WROTE]->(:DialecticMessage)`
    - `(:DialecticSession)-[:ABOUT_DISCOVERY]->(:Discovery)` (when `discovery_id` present)

- **Discovery nodes** from SQLite `discoveries`
- **Tag nodes** from SQLite `discovery_tags`
- **Edges**
  - `:RELATED_TO` from SQLite `discovery_edges(edge_type='related_to')`
  - `:RESPONSE_TO {response_type}` from SQLite `discovery_edges(edge_type='response_to')`
  - `:HAS_TAG` edges `Discovery -> Tag`

## Quick start (local Docker)

Start Postgres+AGE:

```bash
docker compose -f scripts/age/docker-compose.age.yml up -d
```

Bootstrap AGE (creates extension + graph):

```bash
docker exec -i postgres-age psql -U postgres -d postgres < scripts/age/bootstrap.sql
```

Export a small slice from SQLite into an AGE import script:

```bash
python3 scripts/age/export_knowledge_sqlite_to_age.py \
  --sqlite data/governance.db \
  --out /tmp/age_import.sql \
  --limit 2000
```

Import into AGE:

```bash
docker exec -i postgres-age psql -U postgres -d postgres < /tmp/age_import.sql
```

### Recommended flags

- **Idempotent imports (default)**: `--mode merge` (safe to rerun; updates node properties)
- **Clean test cycles**: add `--recreate-graph` to drop+create the graph before importing
- **Skip optional layers**: `--no-agents` and/or `--no-dialectic`

Example:

```bash
python3 scripts/age/export_knowledge_sqlite_to_age.py \
  --sqlite data/governance.db \
  --out /tmp/age_import.sql \
  --limit 5000 \
  --mode merge \
  --recreate-graph
```

Run sample queries:

```bash
docker exec -i postgres-age psql -U postgres -d postgres < scripts/age/sample_queries.sql
```

## Notes / gotchas

- **Re-import duplicates**: only happens in `--mode create`. Default `--mode merge` is idempotent.
- **Scope**: this is a **prototype export** (knowledge + optional agents/dialectic) to evaluate Cypher queries. It does **not** change production runtime wiring; keep SQLite as the canonical store unless/until the prototype proves out.


