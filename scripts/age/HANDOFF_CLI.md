# AGE Graph Database Handoff - CLI Agent

## Quick Start

```bash
# 1. Verify container is running
docker ps | grep postgres-age

# 2. If not running, start it:
docker compose -f scripts/age/docker-compose.age.yml up -d

# 3. Connect to AGE
docker exec -it postgres-age psql -U postgres -d postgres
```

## Inside psql - Required Setup

Every session needs this:
```sql
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
```

## Graph: `governance`

Contains:
- **280 Agent nodes** - AI agents with status, health, updates
- **353 Discovery nodes** - insights, bugs, questions, improvements
- **31 DialecticSession nodes** - thesis/antithesis/synthesis discussions
- **Relationships**: RESPONSE_TO, HAS_TAG, SPAWNED, PAUSED_AGENT, HAS_MESSAGE, WROTE

## Sample Queries to Try

```sql
-- Count all node types
SELECT * FROM cypher('governance', $$
  MATCH (n)
  RETURN labels(n)[0] AS type, count(n) AS total
$$) AS (type agtype, total agtype);

-- Most active agents
SELECT * FROM cypher('governance', $$
  MATCH (a:Agent {status: 'active'})
  RETURN a.id, a.total_updates, a.health_status
  ORDER BY a.total_updates DESC
  LIMIT 10
$$) AS (id agtype, updates agtype, health agtype);

-- Discovery types
SELECT * FROM cypher('governance', $$
  MATCH (d:Discovery)
  WITH d.type AS dtype, count(d) AS total
  RETURN dtype, total
  ORDER BY total DESC
$$) AS (dtype agtype, total agtype);

-- Dialectic session outcomes
SELECT * FROM cypher('governance', $$
  MATCH (s:DialecticSession)
  WITH s.status AS outcome, count(s) AS total
  RETURN outcome, total
$$) AS (outcome agtype, total agtype);
```

## Philosophical Queries

Run the full philosophical query suite:
```bash
docker exec -i postgres-age psql -U postgres -d postgres < scripts/age/philosophical_queries.sql
```

## Re-import Data (if SQLite has new data)

```bash
python3 scripts/age/export_knowledge_sqlite_to_age.py \
  --sqlite data/governance.db \
  --out /tmp/age_import.sql \
  --graph governance \
  --mode merge

docker exec -i postgres-age psql -U postgres -d postgres < /tmp/age_import.sql
```

## AGE Cypher Quirks

1. **No semicolons inside `$$...$$`** - Cypher statements don't end with `;`
2. **Must return something** - Even `RETURN 1` works for mutations
3. **Aggregation aliases** - Use `WITH ... AS` before `ORDER BY`
4. **Empty strings** - Avoid `prop = ''`, use NULL instead

## Exploration Ideas

1. **Find response chains** - How deep do discovery threads go?
2. **Cross-agent influence** - Which agents build on others' work?
3. **Open questions** - What questions have no answers?
4. **Concept clustering** - Which discoveries share tags?
5. **Agent lineage** - Who spawned whom?

## Stop When Done

```bash
docker compose -f scripts/age/docker-compose.age.yml down
# Add -v to delete data volume
```

## Files

- `scripts/age/docker-compose.age.yml` - Container config
- `scripts/age/bootstrap.sql` - AGE setup
- `scripts/age/export_knowledge_sqlite_to_age.py` - SQLite → AGE exporter
- `scripts/age/sample_queries.sql` - Basic queries
- `scripts/age/philosophical_queries.sql` - Advanced queries

---

*Handoff from Claude Opus (Cursor) - Dec 14, 2025*

