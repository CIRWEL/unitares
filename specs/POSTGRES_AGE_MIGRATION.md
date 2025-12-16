# PostgreSQL + AGE Migration Spec

## Overview

Migration from SQLite to PostgreSQL + Apache AGE for:
- Better concurrency (PostgreSQL vs SQLite file locking)
- Native graph queries (AGE/Cypher for knowledge graph)
- Partitioned audit tables (retention policies, performance)
- Production-ready scaling

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                         │
│  (src/mcp_handlers/, src/mcp_server_*.py)                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Database Abstraction Layer                      │
│                     src/db/                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐              │
│  │  SQLite  │  │ Postgres │  │  DualWrite   │              │
│  │ Backend  │  │ Backend  │  │   Backend    │              │
│  └──────────┘  └──────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────┘
        │                │                │
        ▼                ▼                ▼
   ┌─────────┐    ┌─────────────────────────────┐
   │ SQLite  │    │        PostgreSQL           │
   │governance│   │  ┌───────┐  ┌───────────┐  │
   │   .db   │    │  │ core  │  │   audit   │  │
   └─────────┘    │  │schema │  │ (partitioned)│
                  │  └───────┘  └───────────┘  │
                  │       ┌───────────┐        │
                  │       │    AGE    │        │
                  │       │  (graph)  │        │
                  │       └───────────┘        │
                  └─────────────────────────────┘
```

## Schema Summary

### PostgreSQL Relational (core + audit schemas)

| Table | Purpose | Notes |
|-------|---------|-------|
| `core.identities` | Agent identity records | Replaces `agent_metadata` |
| `core.sessions` | Session bindings | Replaces `session_identities` |
| `core.agent_state` | EISV metrics history | New, normalized from JSON |
| `core.calibration` | System config | Single-row JSONB |
| `audit.events` | Audit trail | Partitioned by month, 180d retention |
| `audit.tool_usage` | Tool call metrics | Partitioned by month, 90d retention |

### AGE Graph (existing prototype)

| Node | Properties | From |
|------|------------|------|
| `Agent` | id, status, created_at, ... | `agent_metadata` |
| `Discovery` | id, type, summary, ... | `discoveries` |
| `Tag` | name | `discovery_tags` |
| `DialecticSession` | id, status, phase, ... | `dialectic_sessions` |
| `DialecticMessage` | id, seq, type, ... | `dialectic_messages` |

| Edge | Meaning |
|------|---------|
| `[:SPAWNED]` | Agent lineage |
| `[:HAS_TAG]` | Discovery/Agent tags |
| `[:RELATED_TO]` | Discovery relationships |
| `[:RESPONSE_TO]` | Question/answer links |
| `[:PAUSED_AGENT]` | Dialectic participant |
| `[:REVIEWER]` | Dialectic reviewer |
| `[:HAS_MESSAGE]` | Session messages |
| `[:WROTE]` | Message authorship |

## Files Created

```
db/
├── postgres/
│   ├── schema.sql        # Core + audit DDL
│   └── partitions.sql    # Partition management functions
└── age/
    └── (existing prototype files)

src/db/
├── __init__.py           # Backend selection, get_db()
├── base.py               # Abstract interface
├── sqlite_backend.py     # SQLite implementation
├── postgres_backend.py   # PostgreSQL + AGE implementation
└── dual_backend.py       # Dual-write for migration
```

## Migration Steps

### Phase 1: Preparation (No Production Impact)

1. **Install PostgreSQL + AGE locally**
   ```bash
   # Using existing AGE prototype
   docker compose -f scripts/age/docker-compose.age.yml up -d
   ```

2. **Create PostgreSQL schema**
   ```bash
   docker exec -i postgres-age psql -U postgres -d postgres < db/postgres/schema.sql
   docker exec -i postgres-age psql -U postgres -d postgres < db/postgres/partitions.sql
   ```

3. **Set up AGE graph** (already done via prototype)
   ```bash
   ./scripts/age/run_agent_prototype.sh
   ```

### Phase 2: Backfill Historical Data

1. **Export SQLite → PostgreSQL relational**
   ```bash
   python3 scripts/migrate_sqlite_to_postgres.py \
     --sqlite data/governance.db \
     --postgres postgresql://postgres:postgres@localhost:5432/governance \
     --tables identities,sessions,agent_state,audit_events,tool_usage,calibration
   ```

2. **Export SQLite → AGE graph** (existing prototype)
   ```bash
   python3 scripts/age/export_knowledge_sqlite_to_age.py \
     --sqlite data/governance.db \
     --out /tmp/age_import.sql \
     --mode merge
   docker exec -i postgres-age psql -U postgres -d postgres < /tmp/age_import.sql
   ```

3. **Verify counts and checksums**
   ```bash
   python3 scripts/verify_migration.py --sqlite --postgres
   ```

### Phase 3: Dual-Write (Zero Downtime)

1. **Enable dual-write mode**
   ```bash
   export DB_BACKEND=dual
   export DB_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/governance
   export DB_SQLITE_PATH=data/governance.db
   export DB_DUAL_READ_PRIMARY=sqlite  # Start with SQLite as read primary
   ```

2. **Restart servers with dual-write**
   - All writes go to both SQLite and PostgreSQL
   - Reads come from SQLite (known-good)

3. **Monitor for write failures**
   - Check logs for `PostgreSQL ... failed` warnings
   - Fix any schema mismatches

### Phase 4: Shadow Read Validation

1. **Switch read primary to PostgreSQL**
   ```bash
   export DB_DUAL_READ_PRIMARY=postgres
   ```

2. **Run validation queries**
   - Compare query results between backends
   - Check for data drift

3. **Run for 24-48 hours with PostgreSQL as read primary**

### Phase 5: Cutover

1. **Stop dual-write, switch to PostgreSQL only**
   ```bash
   export DB_BACKEND=postgres
   ```

2. **Archive SQLite file**
   ```bash
   mv data/governance.db data/archive/governance_$(date +%Y%m%d).db
   ```

3. **Remove SQLite dependencies** (optional, can keep as fallback)

### Phase 6: Operationalize

1. **Set up partition maintenance**
   ```sql
   -- Via pg_cron or external cron
   SELECT cron.schedule('partition-maintenance', '0 3 * * 0', 'SELECT audit.partition_maintenance()');
   ```

2. **Configure backups**
   ```bash
   pg_dump -Fc governance > governance_backup_$(date +%Y%m%d).dump
   ```

3. **Set up connection pooling** (production)
   - PgBouncer or application-level pooling via asyncpg

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_BACKEND` | `sqlite` | Backend: `sqlite`, `postgres`, `dual` |
| `DB_POSTGRES_URL` | `postgresql://postgres:postgres@localhost:5432/governance` | PostgreSQL connection string |
| `DB_SQLITE_PATH` | `data/governance.db` | SQLite database path |
| `DB_POSTGRES_MIN_CONN` | `2` | Min pool connections |
| `DB_POSTGRES_MAX_CONN` | `10` | Max pool connections |
| `DB_AGE_GRAPH` | `governance` | AGE graph name |
| `DB_DUAL_READ_PRIMARY` | `postgres` | Primary for reads in dual mode |

## Rollback Plan

If issues during migration:

1. **During dual-write phase**: Simply set `DB_BACKEND=sqlite`
2. **After cutover**: Restore from archived SQLite file
3. **PostgreSQL issues**: AGE graph is optional; relational queries still work

## Dependencies

```
# requirements.txt additions
asyncpg>=0.29.0
```

## Testing

```bash
# Unit tests for abstraction layer
pytest tests/test_db_backends.py

# Integration test with PostgreSQL
DB_BACKEND=postgres pytest tests/test_db_integration.py

# Dual-write test
DB_BACKEND=dual pytest tests/test_db_dual_write.py
```

## Timeline

| Phase | Duration | Risk |
|-------|----------|------|
| Preparation | 1 day | Low |
| Backfill | 1-2 hours | Low |
| Dual-write | 1-2 days | Medium |
| Shadow read | 1-2 days | Low |
| Cutover | 30 min | Medium |
| Operationalize | 1 day | Low |

Total: ~1 week with validation buffers

## Open Questions

1. **Cloud deployment**: AWS Aurora PostgreSQL + AGE, or self-hosted?
2. **Connection pooling**: PgBouncer vs asyncpg built-in?
3. **Backup strategy**: pg_dump + S3, or managed backups?
