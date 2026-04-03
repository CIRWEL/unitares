# Database Architecture

**Last Updated**: 2026-04-03

> **Rule**: The canonical UNITARES database is whatever instance `DB_POSTGRES_URL` points to.
> Query the configured instance directly.

## Overview

The governance MCP uses PostgreSQL as the sole database backend:
- **Durability**: PostgreSQL + Apache AGE for all persistent data
- **Performance**: Redis for ephemeral session cache
- **Audit trail**: `audit_log.jsonl` append-only compliance log

---

## Active Databases

### 1. PostgreSQL (Primary Storage)

**Instance**: configured via `DB_POSTGRES_URL`
**Database**: `governance`
**Purpose**: Single source of truth for all persistent data

**What's Stored:**
- **Agent Metadata**
  - Identity, API keys, status, tags, notes
  - Lifecycle events, creation/update timestamps
  - Parent/child agent relationships

- **Agent State** (EISV metrics)
  - Energy (E), Information Integrity (I)
  - Entropy (S), Void Integral (V)
  - Coherence, regime, health status
  - Full state history

- **Knowledge Graph** (Apache AGE extension)
  - Discoveries (nodes)
  - Relationships (edges)
  - Full-text search
  - Graph queries (Cypher-like syntax)

- **Dialectic Sessions**
  - Thesis-antithesis-synthesis negotiations
  - Session state, messages, resolutions

- **Audit Log**
  - Tool calls, governance decisions
  - Agent lifecycle events
  - Full audit trail

- **Calibration Data**
  - Governance decision calibration
  - Ground truth tracking

**Schema Location**: `core` schema in PostgreSQL
**Schema Version**: Tracked in `core.schema_migrations` (current: v2)
**Backup**: `pg_dump` against `DB_POSTGRES_URL` or an equivalent server-level backup

---

### 2. Redis (Session Cache)

**Service**: typically local Redis on `127.0.0.1:6379`
**Purpose**: Fast ephemeral data with persistence across server restarts

**What's Stored:**
- **Session Bindings** (`session:{session_id}`)
  - Maps session_id → agent_id
  - Survives server restarts
  - TTL: Session expiry (configurable)
  - **Why critical**: Enables session continuity for agents reconnecting

- **Distributed Locks** (future: multi-server)
  - Coordination locks for concurrent operations
  - Currently using file locks (single-server)

- **Rate Limits** (future)
  - Per-agent rate limiting
  - Burst protection

- **Metadata Cache** (optional)
  - Fast lookups to reduce PostgreSQL queries

**Fallback**: If Redis unavailable, gracefully falls back to in-memory cache
**Trade-off**: Loss of session persistence across restarts (minor issue)

---

## Configuration

**Required Environment Variable**: `DB_POSTGRES_URL`

```bash
export DB_POSTGRES_URL="postgresql://postgres:postgres@localhost:5432/governance"
```

Optional but recommended for graph queries:

```bash
export DB_AGE_GRAPH="governance_graph"
```

**Code Location**: `src/db/__init__.py` — the shared database accessor always returns `PostgresBackend`.

> **Note**: If PostgreSQL is unavailable, the server exits honestly rather than
> silently degrading.

---

## Why This Architecture?

### PostgreSQL for Persistent Data
- **ACID transactions**: Data integrity for governance decisions
- **Rich queries**: Complex agent relationship queries
- **Graph database**: Apache AGE for knowledge graph
- **Proven scale**: Handles 1000s of agents efficiently

### Redis for Session Cache
- **Sub-millisecond lookups**: Session resolution on every request
- **Persistence**: Sessions survive server restarts/deployments
- **Standard pattern**: Widely used for session management
- **Automatic TTL**: Sessions expire without manual cleanup

---

## Operations

### Health Check

The `health_check` tool returns a three-tier aggregate status:

| Aggregate Status | Condition |
|------------------|-----------|
| `healthy` | All components operational |
| `moderate` | Some warnings/deprecated, no errors |
| `critical` | One or more component errors |

Response includes `status_breakdown` with counts per status type:
```json
{
  "status": "healthy",
  "status_breakdown": {"healthy": 9, "warning": 0, "deprecated": 0, "error": 0},
  "checks": {...}
}
```

```bash
# Server health
curl http://localhost:8767/health

# PostgreSQL
psql "$DB_POSTGRES_URL" -c "SELECT COUNT(*) FROM core.agents;"

# Schema version
psql "$DB_POSTGRES_URL" -c "SELECT * FROM core.schema_migrations;"

# Redis
redis-cli DBSIZE
redis-cli GET "session:test-session-id"
```

### Backup
```bash
# PostgreSQL
pg_dump "$DB_POSTGRES_URL" > backup.sql

# Redis (manual snapshot)
redis-cli BGSAVE
```

### Troubleshooting

**PostgreSQL connection issues:**
```bash
# Check configured database target
echo "$DB_POSTGRES_URL"
pg_isready -d "$DB_POSTGRES_URL"

# Simple connectivity probe
psql "$DB_POSTGRES_URL" -c "SELECT 1;"
```

**Redis unavailable:**
```bash
# Check service
brew services list | grep redis

# Restart
brew services restart redis

# Fallback: Server automatically uses in-memory cache
```

## Performance Characteristics

| Operation | Backend | Latency | Notes |
|-----------|---------|---------|-------|
| Session lookup | Redis | <1ms | In-memory, critical path |
| Agent metadata read | PostgreSQL | 5-10ms | Cached in app memory |
| Agent state write | PostgreSQL | 10-20ms | Transaction + index update |
| Knowledge graph query | PostgreSQL AGE | 50-200ms | Graph traversal |
| Audit log write | PostgreSQL | 15-30ms | Async background write |

---

## Future Considerations

**If deploying multiple servers:**
- Enable Redis distributed locks (replace fcntl file locks)
- Enable Redis rate limiting (per-agent limits)
- Consider PostgreSQL read replicas (if query load high)

**If single server remains:**
- Can remove Redis (lose session persistence across restarts)
- Can simplify to PostgreSQL-only (all subsystems)
- Trade-off: Simplicity vs. performance

**Current recommendation**: Keep hybrid architecture (battle-tested, performant)

---

## Schema Versioning

Schema migrations are tracked in `core.schema_migrations`:

| Version | Name | Description |
|---------|------|-------------|
| 1 | `initial_schema` | Core tables (agents, sessions, dialectic) |
| 2 | `knowledge_schema` | Knowledge graph PostgreSQL FTS tables |

Query current version:
```sql
SELECT MAX(version) FROM core.schema_migrations;
```

---

## Related Documentation

- PostgreSQL Schema: `db/postgres/README.md`
- Knowledge Graph: See AGE graph schema in `db/postgres/graph_schema.cypher`
