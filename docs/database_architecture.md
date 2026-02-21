# Database Architecture

**Last Updated**: 2026-02-20
**Status**: PostgreSQL-only (SQLite backend removed Feb 2026)

## Overview

The governance MCP uses PostgreSQL as the sole database backend:
- **Durability**: PostgreSQL + Apache AGE for all persistent data
- **Performance**: Redis for ephemeral session cache
- **Audit trail**: `audit_log.jsonl` append-only compliance log

---

## Active Databases

### 1. PostgreSQL (Primary Storage)

**Container**: `postgres-age` (Docker)
**Database**: `governance`
**Purpose**: Single source of truth for all persistent data

**What's Stored:**
- **Agent Metadata** (~1,800 identities)
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
**Backup**: Automatic PostgreSQL backups (Docker volume)

---

### 2. Redis (Session Cache)

**Service**: Homebrew Redis (127.0.0.1:6379)
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

**Code Location**: `src/db/__init__.py` — `get_db()` always returns `PostgresBackend`.

> **Note**: The SQLite backend was removed in Feb 2026 (v2.7.0). PostgreSQL is the sole
> database backend. If PostgreSQL is unavailable, the server exits honestly rather than
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

## Migration Status

All migrations complete (Dec 2025 - Feb 2026):
- Agent metadata, state, audit log → PostgreSQL
- Knowledge graph → PostgreSQL AGE (~1,063 discoveries, 5,218 edges)
- Dialectic sessions → PostgreSQL (72 sessions migrated Feb 2026)
- Session cache → Redis (~1,760 sessions)
- Schema version: 2

---

## Race Condition Fix (2025-12-25)

**Issue**: PostgreSQL metadata loading failed when called from async contexts
**Error**: `"cannot perform operation: another operation is in progress"`
**Root Cause**: `asyncio.run()` creating new event loop conflicting with existing connection pool

**Fix Applied** (`src/mcp_server_std.py`):
```python
# New async function for async contexts
async def load_metadata_async():
    result = await _load_metadata_from_postgres_async()
    agent_metadata = result

# Fixed sync wrapper using run_coroutine_threadsafe
def _load_metadata_from_postgres_sync():
    loop = asyncio.get_running_loop()
    future = asyncio.run_coroutine_threadsafe(
        _load_metadata_from_postgres_async(),
        loop
    )
    result = future.result(timeout=30)
```

**Impact**: PostgreSQL loading now works reliably from all contexts

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
docker exec postgres-age psql -U postgres -d governance -c "SELECT COUNT(*) FROM core.agents;"

# Schema version
docker exec postgres-age psql -U postgres -d governance -c "SELECT * FROM core.schema_migrations;"

# Redis
redis-cli DBSIZE
redis-cli GET "session:test-session-id"
```

### Backup
```bash
# PostgreSQL (automatic via Docker volume)
docker exec postgres-age pg_dump -U postgres governance > backup.sql

# Redis (manual snapshot)
redis-cli BGSAVE
```

### Troubleshooting

**PostgreSQL connection issues:**
```bash
# Check container
docker ps | grep postgres-age

# Check logs
docker logs postgres-age

# Restart
docker restart postgres-age
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
- Redis Keys: `src/cache/README.md`
- Migration Scripts: `scripts/migrate_*.py`
- Knowledge Graph: See AGE graph schema in `db/postgres/graph_schema.cypher`
