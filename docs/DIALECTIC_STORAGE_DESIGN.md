# Dialectic Storage Architecture

## Decision: SQLite as Single Source of Truth

**Date**: 2026-02-05
**Status**: Proposed

## Problem Statement

Dialectic sessions are scattered across:
- `data/dialectic_sessions/*.json` - JSON files per session
- `data/governance.db` - SQLite tables
- `ACTIVE_SESSIONS` dict - In-memory per-process

This causes:
1. Data loss when one backend fails silently
2. Stale data when reads come from wrong source
3. Cross-process blindness (CLI can't see SSE sessions)
4. Dashboard showing incomplete history

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     WRITE PATH                                │
├──────────────────────────────────────────────────────────────┤
│  Agent Request → SQLite (atomic) → Success/Fail to caller    │
│                                                               │
│  NO dual-write. NO JSON on write path.                       │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                     READ PATH                                 │
├──────────────────────────────────────────────────────────────┤
│  Query → SQLite → Return                                      │
│                                                               │
│  For active sessions: light in-memory cache (TTL: 60s)       │
│  Cache is read-through, never authoritative                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                     EXPORT PATH (on-demand)                   │
├──────────────────────────────────────────────────────────────┤
│  export_session(id) → Read SQLite → Write JSON snapshot      │
│  export_all_sessions() → Bulk export for backup              │
│                                                               │
│  JSON is NEVER read for normal operations                    │
└──────────────────────────────────────────────────────────────┘
```

## Schema (governance.db)

```sql
-- Sessions table (existing)
CREATE TABLE dialectic_sessions (
    session_id TEXT PRIMARY KEY,
    paused_agent_id TEXT NOT NULL,
    reviewer_agent_id TEXT,
    phase TEXT NOT NULL DEFAULT 'thesis',
    status TEXT NOT NULL DEFAULT 'active',  -- active|resolved|failed
    created_at TEXT NOT NULL,
    updated_at TEXT,
    topic TEXT,
    session_type TEXT DEFAULT 'review',
    resolution_json TEXT,
    -- Indexes for common queries
    UNIQUE(session_id)
);

CREATE INDEX idx_sessions_agent ON dialectic_sessions(paused_agent_id);
CREATE INDEX idx_sessions_reviewer ON dialectic_sessions(reviewer_agent_id);
CREATE INDEX idx_sessions_phase ON dialectic_sessions(phase);
CREATE INDEX idx_sessions_status ON dialectic_sessions(status);
CREATE INDEX idx_sessions_created ON dialectic_sessions(created_at DESC);

-- Messages table (existing)
CREATE TABLE dialectic_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES dialectic_sessions(session_id),
    agent_id TEXT NOT NULL,
    message_type TEXT NOT NULL,  -- thesis|antithesis|synthesis
    timestamp TEXT NOT NULL,
    reasoning TEXT,
    root_cause TEXT,
    proposed_conditions_json TEXT,
    observed_metrics_json TEXT,
    concerns_json TEXT,
    agrees INTEGER,
    signature TEXT
);

CREATE INDEX idx_messages_session ON dialectic_messages(session_id);
```

## Agent Access Patterns

### 1. Request Dialectic Review
```python
async def request_dialectic_review(...):
    session = DialecticSession(...)

    # Single write - fail fast if it fails
    await db.create_session(session)  # Raises on failure

    return {"session_id": session.session_id}
```

### 2. Submit Thesis/Antithesis/Synthesis
```python
async def submit_thesis(session_id, message):
    # Read current state
    session = await db.get_session(session_id)
    if not session:
        raise SessionNotFound(session_id)

    # Atomic update
    await db.add_message(session_id, message)
    await db.update_phase(session_id, new_phase)
```

### 3. List Sessions for Agent
```python
async def list_my_sessions(agent_id, role="any"):
    # Efficient indexed query
    return await db.query_sessions(
        agent_id=agent_id,
        role=role,  # "requestor" | "reviewer" | "any"
        include_transcript=False  # Default for listings
    )
```

### 4. Get Full Session (for detail view)
```python
async def get_session_detail(session_id):
    session = await db.get_session(session_id)
    messages = await db.get_messages(session_id)
    return {**session, "transcript": messages}
```

## Migration Plan

1. **Phase 1: Consolidate existing data** ✅ Done
   - Migrated JSON archives to SQLite
   - 30 sessions, 121 messages now in governance.db

2. **Phase 2: Remove dual-write**
   - Edit `request_dialectic_review()` to only write SQLite
   - Remove `save_session()` call from write path
   - Make SQLite failure a hard error (not warning)

3. **Phase 3: Add export tool**
   - `export_dialectic_session(session_id)` → JSON file
   - For debugging/archival only

4. **Phase 4: Cleanup**
   - Remove `UNITARES_DIALECTIC_BACKEND` env var
   - Remove `UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT` env var
   - Archive/delete JSON session files

## Why NOT PostgreSQL?

For local MCP servers, SQLite is ideal:
- Zero configuration
- Single file deployment
- Excellent read performance
- WAL mode handles concurrent access
- No network latency

PostgreSQL would be appropriate for:
- Multi-node deployments
- High write concurrency (>100 writes/sec)
- Team/cloud deployments with shared state

The current architecture supports both via `src/db/dual_backend.py` -
just set `UNITARES_DB_BACKEND=postgres` if needed.

## Observability

Add metrics for:
- Session creation latency
- Query latency by type
- Active sessions count
- Failed sessions per hour
- Message throughput

These already flow through EISV tracking.
