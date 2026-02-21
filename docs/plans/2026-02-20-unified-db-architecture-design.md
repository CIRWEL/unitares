# Unified Database Architecture Design

**Date:** 2026-02-20
**Status:** Approved
**Author:** Claude + Kenny

---

## Problem

Data is scattered across 7 storage backends with no clear ownership:

| # | Backend | Location | Size | Status |
|---|---------|----------|------|--------|
| 1 | PostgreSQL | `localhost:5432/governance` | ? | Primary for governance, currently down |
| 2 | SQLite | `data/governance.db` | 201 MB | Fallback, partially synced |
| 3 | JSONL | `data/audit_log.jsonl` | 532 MB | Append-only, 1.47M lines |
| 4 | Redis | `localhost:6379` | 266 keys | Sessions only |
| 5 | SQLite | `~/.anima/anima.db` | 141 MB | Pi's local DB |
| 6 | JSON files | `~/.anima/*.json` | ~1.5 KB | Day summaries, genesis |
| 7 | Dead files | `data/knowledge*.db`, etc. | 0 bytes | Orphaned |

Agents can't answer "where does X live?" and DrawingEISV telemetry (needed for the companion paper) is persisted nowhere.

## Decision

**PostgreSQL for governance. SQLite for anima. Clear contracts at the boundary.**

Each project uses what fits its deployment reality:
- Governance server handles concurrent MCP clients from multiple agents → PostgreSQL
- Anima is a single creature on a Pi Zero 2W with 512MB RAM → SQLite

The confusion wasn't the technology choice — it was having both technologies in governance-mcp with fallback/dual modes, plus dead files, plus JSONL duplicating the DB.

## Architecture

```
Pi (anima-mcp)                              Mac (governance-mcp)
┌────────────────────────┐                  ┌────────────────────────┐
│  SQLite: ~/.anima/anima.db                │  PostgreSQL: governance │
│  ├─ state_history      │                  │  ├─ core.identities    │
│  ├─ drawing_history  ←NEW   HTTP bridge   │  ├─ core.agent_state   │
│  ├─ memories           │ ──────────────►  │  ├─ audit.events       │
│  ├─ events             │   ~60s check-in  │  ├─ core.discoveries   │
│  ├─ growth tables      │   includes       │  ├─ dialectic.*        │
│  │  (preferences,      │   drawing_eisv   │  ├─ core.calibration   │
│  │   relationships,    │                  │  └─ core.tool_usage    │
│  │   goals, insights)  │                  │                        │
│  ├─ primitives         │                  │  Redis (sessions only) │
│  └─ trajectory_events  │                  │  audit_log.jsonl (raw) │
│                        │                  │                        │
│  canvas.json (pixels)  │                  │                        │
│  trajectory_genesis.json│                  │                        │
└────────────────────────┘                  └────────────────────────┘
```

### Ownership Rules

| Data | Authoritative Source | Why |
|------|---------------------|-----|
| Anima state (warmth, clarity, stability, presence) | Pi: `anima.db:state_history` | Measured on Pi |
| DrawingEISV (E, I, S, V, C, marks, phase, era) | Pi: `anima.db:drawing_history` (NEW) | Computed on Pi |
| Governance EISV (mapped from anima) | Mac: `core.agent_state` | Computed on Mac |
| Agent identity, lifecycle | Mac: `core.identities` | Created by governance |
| Audit trail (raw) | Mac: `audit_log.jsonl` | Append-only compliance |
| Audit trail (queryable) | Mac: `audit.events` (PostgreSQL) | Indexed for queries |
| Knowledge graph | Mac: `core.discoveries` + AGE | Multi-agent knowledge |
| Canvas pixels | Pi: `canvas.json` | Never leaves Pi |
| Trajectory genesis | Pi: `trajectory_genesis.json` | Write-once reference |

### Bridge Contract

**Pi → Mac (every ~60s check-in):**
```json
{
  "anima": {"warmth": 0.4, "clarity": 0.8, "stability": 0.9, "presence": 0.9},
  "eisv": {"E": 0.4, "I": 0.8, "S": 0.1, "V": 0.08},
  "sensor_data": {
    "cpu_temp_c": 53.0, "humidity_pct": 20.0, "light_lux": 424.8,
    "drawing_eisv": {"E": 0.7, "I": 0.2, "S": 0.5, "V": -0.1, "C": 0.47,
                     "marks": 142, "phase": "building", "era": "expressive"}
  },
  "identity": {"awakenings": 2052, "alive_seconds": 1234567}
}
```

**Mac → Pi:**
```json
{
  "action": "proceed",
  "margin": "comfortable",
  "reason": "State healthy"
}
```

DrawingEISV crosses the boundary as telemetry. Pi is authoritative (full resolution in `drawing_history`). Mac gets snapshots (stored in `agent_state.state_json` JSONB).

---

## Changes: governance-mcp

### Kill List

| What | Action | Rationale |
|------|--------|-----------|
| `src/db/sqlite_backend.py` (1116 lines) | Delete | No more SQLite backend |
| `src/db/__init__.py` dual/fallback logic | Simplify | Postgres only, no `DB_BACKEND` switch |
| `data/knowledge.db` (0 bytes) | Delete | Dead file |
| `data/knowledge_graph.db` (0 bytes) | Delete | Dead file |
| `data/knowledge_graph.json` (1 node) | Delete | Dead file |
| `data/governance_new.db-shm` (32KB) | Delete | Orphaned WAL files |
| `data/governance_new.db-wal` (0 bytes) | Delete | Orphaned WAL files |
| `data/knowledge.db-shm` + `.db-wal` | Delete | Orphaned WAL files |
| `data/knowledge.db-shm.__migrated__` + `.wal.__migrated__` | Delete | Migration artifacts |
| `data/agents/` directory | Delete | Deprecated Nov 2025, migrated to DB |
| `data/activity/` directory | Delete | Legacy activity tracking |
| `data/tool_usage.jsonl` | Delete after migration | Data moves to `core.tool_usage` table |

### Code Changes

1. **`src/db/__init__.py`** — Remove dual-backend logic. `get_db()` returns `PostgresBackend` always. Remove `DB_BACKEND` env var parsing.

2. **`src/db/sqlite_backend.py`** — Delete entirely.

3. **`src/mcp_server.py`** — Remove SQLite fallback mentions. On startup: if Postgres is down, log error and exit honestly. No silent degradation.

4. **`src/audit_log.py`** — Keep dual-write (JSONL + Postgres). Remove SQLite audit_events path. The JSONL is the raw compliance log. Postgres `audit.events` is the queryable index.

5. **`.env` / `.env.example`** — Remove `DB_BACKEND` variable. Document that PostgreSQL is required.

6. **`data/.gitignore`** — Update to only track files that should exist.

### What Stays

| What | Why |
|------|-----|
| `data/governance.db` | Keep on disk as historical archive (but code no longer reads/writes it) |
| `data/audit_log.jsonl` | Raw compliance trail, append-only. Rotation via `rotate_log()` |
| `data/README.md` | Update to reflect new architecture |
| Redis | Sessions only, ephemeral, working correctly |
| PostgreSQL | Sole backend. All governance data. |

---

## Changes: anima-mcp

### New Table: `drawing_history`

```sql
CREATE TABLE IF NOT EXISTS drawing_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    -- EISV state
    E REAL NOT NULL,
    I REAL NOT NULL,
    S REAL NOT NULL,
    V REAL NOT NULL,
    C REAL NOT NULL,
    -- Drawing context
    marks INTEGER NOT NULL,
    phase TEXT,           -- exploring, building, reflecting, resting
    era TEXT,             -- expressive, minimal, geometric, etc.
    energy REAL,          -- remaining energy [0, 1]
    -- Attention signals
    curiosity REAL,
    engagement REAL,
    fatigue REAL,
    -- Arc narrative
    arc_phase TEXT,       -- opening, developing, resolving, closing
    -- Inputs that drove this step
    gesture_entropy REAL, -- Shannon entropy over last 20 gestures
    switching_rate REAL,  -- gesture type switching frequency
    intentionality REAL   -- era's intentionality parameter
);

CREATE INDEX IF NOT EXISTS idx_drawing_history_time
    ON drawing_history(timestamp DESC);
```

**Writer:** `screens.py::DrawingState._eisv_step()` — record after each EISV step (or every N marks for throttling)

**Readers:**
- Bridge: include latest snapshot in check-in payload
- Paper analysis: query full time-series for statistical analysis
- Growth system: potential future use for drawing pattern learning

### Cleanup

| What | Action | Rationale |
|------|--------|-----------|
| `day_summaries.json` | Keep for now | Small, useful for quick trend checks. Could become a SQL view later |
| `trajectory_genesis.json` | Keep | Write-once, not relational |
| `canvas.json` | Keep | Pixel data, not relational |

No tables deleted. No schema changes to existing tables. Only addition is `drawing_history`.

---

## Migration Plan

### Phase 1: Kill dead files (governance-mcp, no code changes)
- Delete dead DB files and deprecated directories
- Update `.gitignore`
- Verify tests still pass

### Phase 2: Remove SQLite backend (governance-mcp, code changes)
- Delete `sqlite_backend.py`
- Simplify `db/__init__.py`
- Update `mcp_server.py` startup
- Update `.env.example`
- Migrate `tool_usage.jsonl` data into Postgres
- Run full test suite

### Phase 3: Add drawing_history (anima-mcp, code changes)
- Add table creation to anima.db schema init
- Add recording in `screens.py` EISV step
- Add to bridge payload (if not already included)
- Deploy to Pi

### Phase 4: Verify end-to-end
- Start Postgres on Mac
- Start anima-mcp on Pi
- Verify bridge check-in includes DrawingEISV
- Verify drawing_history accumulates on Pi
- Verify governance stores snapshots in agent_state.state_json
- Query both sides to confirm data flows

---

## Risks

| Risk | Mitigation |
|------|------------|
| Postgres down = governance down | Honest failure. Log, exit, alert. Don't pretend SQLite works. |
| `drawing_history` grows unbounded on Pi | Add rotation: keep last 30 days, archive older. 141MB DB has room. |
| Migration loses SQLite data | Keep `governance.db` file on disk as archive. Don't delete it. |
| Tests depend on SQLite | Update test fixtures to use Postgres test DB or mock backend. |

---

## Success Criteria

After implementation:

1. `governance-mcp` has zero SQLite imports or references
2. `anima-mcp` has a `drawing_history` table with data accumulating
3. Dead files are gone from `data/`
4. An agent can answer "where does X live?" by reading this document
5. DrawingEISV time-series is queryable for the companion paper
