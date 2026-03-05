# Unified DB Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove SQLite backend from governance-mcp, kill dead files, add drawing_history table to anima-mcp.

**Architecture:** Postgres-only for governance (no fallback, no dual-write). SQLite-only for anima (with new drawing_history table). Clear ownership at the HTTP bridge boundary.

**Tech Stack:** PostgreSQL (asyncpg), SQLite (stdlib sqlite3), Python 3.14

**Design doc:** `docs/plans/2026-02-20-unified-db-architecture-design.md`

---

## Phase 1: Kill Dead Files (governance-mcp)

No code changes. Just removing orphaned files.

### Task 1: Delete dead database files

**Files:**
- Delete: `data/knowledge.db` (0 bytes)
- Delete: `data/knowledge_graph.db` (0 bytes)
- Delete: `data/knowledge_graph.json` (1 node, orphaned)
- Delete: `data/governance_new.db-shm` (32KB orphan)
- Delete: `data/governance_new.db-wal` (0 bytes orphan)
- Delete: `data/knowledge.db-shm` (32KB orphan)
- Delete: `data/knowledge.db-wal` (0 bytes orphan)
- Delete: `data/knowledge.db-shm.__migrated__` (migration artifact)
- Delete: `data/knowledge.db-wal.__migrated__` (migration artifact)

**Step 1: Delete the files**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
rm -f data/knowledge.db data/knowledge_graph.db data/knowledge_graph.json
rm -f data/governance_new.db-shm data/governance_new.db-wal
rm -f data/knowledge.db-shm data/knowledge.db-wal
rm -f data/knowledge.db-shm.__migrated__ data/knowledge.db-wal.__migrated__
```

**Step 2: Delete deprecated directories**

```bash
rm -rf data/agents/ data/activity/
```

**Step 3: Move tool_usage.jsonl to archive (data already in DB)**

```bash
mkdir -p data/archive/2026-02
mv data/tool_usage.jsonl data/archive/2026-02/tool_usage.jsonl.archived
```

**Step 4: Run tests to confirm nothing breaks**

Run: `python3 -m pytest tests/ -x -q --timeout=30`
Expected: All tests pass (dead files had no code references)

**Step 5: Commit**

```bash
git add -A data/
git commit -m "chore: remove dead DB files and deprecated directories

Kill orphaned knowledge.db, knowledge_graph.db, knowledge_graph.json,
governance_new.db WAL files, and deprecated agents/activity dirs.
Archive tool_usage.jsonl."
```

---

## Phase 2: Remove SQLite Backend (governance-mcp)

### Task 2: Delete SQLite backend and dual-write backend

**Files:**
- Delete: `src/db/sqlite_backend.py` (1116 lines)
- Delete: `src/db/dual_backend.py` (~697 lines)
- Delete: `tests/test_sqlite_backend.py` (~1626 lines)
- Delete: `tests/test_dual_backend.py`

**Step 1: Delete the files**

```bash
rm -f src/db/sqlite_backend.py src/db/dual_backend.py
rm -f tests/test_sqlite_backend.py tests/test_dual_backend.py
```

**Step 2: Run tests to see what breaks**

Run: `python3 -m pytest tests/ -x -q 2>&1 | head -50`
Expected: Some tests will fail due to imports. Note which files.

**Step 3: Commit deletions**

```bash
git add -A
git commit -m "chore: delete SQLite and dual-write backend code

Remove sqlite_backend.py (1116 lines), dual_backend.py (~697 lines),
and their test files. Postgres is the sole backend."
```

---

### Task 3: Simplify db/__init__.py

**Files:**
- Modify: `src/db/__init__.py`

**Step 1: Rewrite to Postgres-only**

Replace the entire file with:

```python
"""
Database Abstraction Layer — PostgreSQL Only

Usage:
    from src.db import get_db

    db = get_db()  # Returns PostgresBackend

    # Identity operations
    await db.upsert_identity(agent_id, api_key_hash, metadata)
    identity = await db.get_identity(agent_id)

    # Session operations
    await db.create_session(session_id, identity_id, expires_at)
    await db.update_session_activity(session_id)

    # Audit operations
    await db.append_audit_event(event)
    events = await db.query_audit_events(agent_id=agent_id, limit=100)

    # Graph operations (AGE)
    await db.graph_query("MATCH (a:Agent)-[:COLLABORATED]->(b:Agent) RETURN a, b")

Configuration (environment variables):
    DB_POSTGRES_URL=postgresql://user:pass@host:port/db  (required)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import DatabaseBackend

# Backend singleton
_db_instance: "DatabaseBackend | None" = None


def get_db() -> "DatabaseBackend":
    """Get the PostgreSQL database backend."""
    global _db_instance

    if _db_instance is not None:
        return _db_instance

    from .postgres_backend import PostgresBackend
    _db_instance = PostgresBackend()
    return _db_instance


async def init_db() -> None:
    """Initialize the database (create tables, run migrations)."""
    db = get_db()
    await db.init()


async def close_db() -> None:
    """Close database connections."""
    global _db_instance
    if _db_instance is not None:
        await _db_instance.close()
        _db_instance = None


# Re-export common types
from .base import (
    DatabaseBackend,
    IdentityRecord,
    SessionRecord,
    AuditEvent,
    AgentStateRecord,
)

__all__ = [
    "get_db",
    "init_db",
    "close_db",
    "DatabaseBackend",
    "IdentityRecord",
    "SessionRecord",
    "AuditEvent",
    "AgentStateRecord",
]
```

**Step 2: Run tests**

Run: `python3 -m pytest tests/ -x -q 2>&1 | head -50`
Expected: Failures in files that reference `DB_BACKEND` or SQLite

**Step 3: Commit**

```bash
git add src/db/__init__.py
git commit -m "refactor: simplify db/__init__.py to Postgres-only

Remove dual/sqlite/fallback branching. get_db() always returns
PostgresBackend. No more DB_BACKEND environment variable."
```

---

### Task 4: Update mcp_server.py references

**Files:**
- Modify: `src/mcp_server.py` (lines ~985, ~1311)

**Step 1: Find and fix all SQLite references**

Search for: `sqlite`, `DB_BACKEND`, `"sqlite"`, `backend_type`

Fix line ~985 (reconciliation skip):
```python
# Remove the SQLite check — reconciliation always runs on Postgres
```

Fix line ~1311 (startup):
```python
# Change from:
#   backend_type = os.environ.get("DB_BACKEND", "sqlite")
# To:
logger.info("Database initialized: backend=postgres")
```

**Step 2: Run server startup test**

Run: `python3 -m pytest tests/test_mcp_server*.py -x -q -k "not test_version" 2>&1 | head -30`

**Step 3: Commit**

```bash
git add src/mcp_server.py
git commit -m "refactor: remove SQLite references from mcp_server.py"
```

---

### Task 5: Update mcp_server_std.py references

**Files:**
- Modify: `src/mcp_server_std.py` (lines ~920, ~1120, ~2746)

**Step 1: Find and fix all SQLite references**

Search for: `sqlite`, `DB_BACKEND`, `"sqlite"`, `_should_use_sqlite_state`

Replace all `os.environ.get("DB_BACKEND", "sqlite")` with `"postgres"` or remove the checks entirely.

Remove any `_should_use_sqlite_state()` function if it exists.

**Step 2: Run tests**

Run: `python3 -m pytest tests/test_mcp_server_std.py -x -q 2>&1 | head -30`

**Step 3: Commit**

```bash
git add src/mcp_server_std.py
git commit -m "refactor: remove SQLite references from mcp_server_std.py"
```

---

### Task 6: Update audit_log.py

**Files:**
- Modify: `src/audit_log.py` (lines ~37-53, ~523-573)

**Step 1: Remove SQLite audit writing**

The audit system should:
- Keep JSONL writing (raw truth, append-only)
- Write to Postgres `audit.events` via the DB backend (not direct SQLite)
- Remove `_sqlite_enabled`, `UNITARES_AUDIT_WRITE_SQLITE`, `_should_query_sqlite()`
- Remove `UNITARES_AUDIT_AUTO_BACKFILL` (no more SQLite to backfill)

Replace SQLite writes with `get_db().append_audit_event()` calls.

**Step 2: Run audit tests**

Run: `python3 -m pytest tests/test_audit*.py -x -q 2>&1 | head -30`

**Step 3: Commit**

```bash
git add src/audit_log.py
git commit -m "refactor: remove SQLite from audit_log.py

Audit writes to JSONL (raw) + Postgres (queryable). No more direct
SQLite audit writes or backfill logic."
```

---

### Task 7: Update calibration.py

**Files:**
- Modify: `src/calibration.py` (lines ~108-114)

**Step 1: Remove SQLite backend resolution**

Simplify to always use Postgres backend via `get_db()`.

**Step 2: Run calibration tests**

Run: `python3 -m pytest tests/test_calibration*.py -x -q 2>&1 | head -30`

**Step 3: Commit**

```bash
git add src/calibration.py
git commit -m "refactor: remove SQLite option from calibration.py"
```

---

### Task 8: Update .env.example and environment docs

**Files:**
- Modify: `.env.example`
- Modify: `.env` (if exists)

**Step 1: Remove DB_BACKEND, add clear Postgres-only docs**

```bash
# Database (PostgreSQL required)
DB_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/governance
DB_POSTGRES_MIN_CONN=2
DB_POSTGRES_MAX_CONN=10
```

Remove all `DB_BACKEND` references.

**Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: update .env.example for Postgres-only backend"
```

---

### Task 9: Fix remaining test failures

**Files:**
- Modify: Various test files that reference SQLite

**Step 1: Run full suite and note failures**

Run: `python3 -m pytest tests/ -x -q 2>&1 | head -80`

**Step 2: Fix each failing test**

Common fixes:
- Tests that set `DB_BACKEND=sqlite` → remove or skip
- Tests that import `SQLiteBackend` → delete those test classes
- Tests that reference `_should_query_sqlite` → remove
- Tests that use `governance.db` path → update to use Postgres test DB or mock

**Step 3: Run full suite clean**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -5`
Expected: All tests pass

**Step 4: Commit**

```bash
git add tests/
git commit -m "test: fix test suite for Postgres-only backend"
```

---

## Phase 3: Add drawing_history (anima-mcp)

### Task 10: Write failing test for drawing_history table

**Files:**
- Create: `tests/test_drawing_history.py` (in anima-mcp)

**Step 1: Write the test**

```python
"""Tests for drawing_history table in anima.db."""
import os
import sqlite3
import tempfile
import pytest

from anima_mcp.identity.store import IdentityStore


@pytest.fixture
def store(tmp_path):
    """Create IdentityStore with temp database."""
    db_path = str(tmp_path / "test_anima.db")
    s = IdentityStore(db_path=db_path)
    s.wake("test-creature")
    return s


class TestDrawingHistorySchema:
    """Test that drawing_history table exists and has correct schema."""

    def test_table_exists(self, store):
        conn = store._connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='drawing_history'"
        ).fetchall()
        assert len(tables) == 1, "drawing_history table should exist"

    def test_columns(self, store):
        conn = store._connect()
        info = conn.execute("PRAGMA table_info(drawing_history)").fetchall()
        col_names = {row[1] for row in info}
        expected = {
            "id", "timestamp", "E", "I", "S", "V", "C",
            "marks", "phase", "era", "energy",
            "curiosity", "engagement", "fatigue",
            "arc_phase", "gesture_entropy", "switching_rate", "intentionality",
        }
        assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"

    def test_timestamp_index_exists(self, store):
        conn = store._connect()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='drawing_history'"
        ).fetchall()
        index_names = {row[0] for row in indexes}
        assert "idx_drawing_history_time" in index_names


class TestDrawingHistoryRecording:
    """Test recording and querying drawing_history entries."""

    def test_record_drawing_state(self, store):
        store.record_drawing_state(
            E=0.7, I=0.2, S=0.5, V=-0.1, C=0.47,
            marks=142, phase="building", era="expressive",
            energy=0.6, curiosity=0.5, engagement=0.8, fatigue=0.2,
            arc_phase="developing", gesture_entropy=0.8,
            switching_rate=0.3, intentionality=0.6,
        )
        conn = store._connect()
        rows = conn.execute("SELECT COUNT(*) FROM drawing_history").fetchone()
        assert rows[0] == 1

    def test_get_recent_drawing_history(self, store):
        # Record 3 entries
        for i in range(3):
            store.record_drawing_state(
                E=0.5 + i * 0.1, I=0.2, S=0.5, V=0.0, C=0.5,
                marks=i * 50, phase="building", era="expressive",
                energy=0.8 - i * 0.2, curiosity=0.5, engagement=0.5,
                fatigue=0.1 * i, arc_phase="developing",
                gesture_entropy=0.5, switching_rate=0.3, intentionality=0.6,
            )
        history = store.get_recent_drawing_history(limit=2)
        assert len(history) == 2
        # Should be ascending timestamp order (oldest first)
        assert history[0]["E"] < history[1]["E"]

    def test_record_returns_none_gracefully(self, store):
        """Recording should never raise — best-effort like trajectory_events."""
        # Should not raise even with unusual values
        store.record_drawing_state(
            E=0.0, I=0.0, S=0.0, V=0.0, C=0.0,
            marks=0, phase=None, era=None,
            energy=0.0, curiosity=0.0, engagement=0.0, fatigue=0.0,
            arc_phase=None, gesture_entropy=0.0,
            switching_rate=0.0, intentionality=0.0,
        )
```

**Step 2: Run to verify it fails**

Run: `cd /Users/cirwel/projects/anima-mcp && python3 -m pytest tests/test_drawing_history.py -v`
Expected: FAIL — no `drawing_history` table, no `record_drawing_state` method

**Step 3: Commit**

```bash
cd /Users/cirwel/projects/anima-mcp
git add tests/test_drawing_history.py
git commit -m "test: add failing tests for drawing_history table"
```

---

### Task 11: Implement drawing_history schema and methods

**Files:**
- Modify: `src/anima_mcp/identity/store.py` (add to `_init_schema()` at line 123, add methods)

**Step 1: Add table creation to _init_schema()**

After the `state_history` CREATE TABLE (line 123), add:

```python
            CREATE TABLE IF NOT EXISTS drawing_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                E REAL NOT NULL,
                I REAL NOT NULL,
                S REAL NOT NULL,
                V REAL NOT NULL,
                C REAL NOT NULL,
                marks INTEGER NOT NULL,
                phase TEXT,
                era TEXT,
                energy REAL,
                curiosity REAL,
                engagement REAL,
                fatigue REAL,
                arc_phase TEXT,
                gesture_entropy REAL,
                switching_rate REAL,
                intentionality REAL
            );

            CREATE INDEX IF NOT EXISTS idx_drawing_history_time
                ON drawing_history(timestamp DESC);
```

**Step 2: Add record_drawing_state() method**

After `record_state()` (around line 410), add:

```python
    def record_drawing_state(
        self,
        E: float, I: float, S: float, V: float, C: float,
        marks: int, phase: str | None, era: str | None,
        energy: float, curiosity: float, engagement: float, fatigue: float,
        arc_phase: str | None, gesture_entropy: float,
        switching_rate: float, intentionality: float,
    ) -> None:
        """Record DrawingEISV state snapshot. Best-effort, never raises."""
        try:
            conn = self._connect()
            conn.execute(
                """INSERT INTO drawing_history
                   (timestamp, E, I, S, V, C, marks, phase, era, energy,
                    curiosity, engagement, fatigue, arc_phase,
                    gesture_entropy, switching_rate, intentionality)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().isoformat(),
                    E, I, S, V, C, marks, phase, era, energy,
                    curiosity, engagement, fatigue, arc_phase,
                    gesture_entropy, switching_rate, intentionality,
                ),
            )
            conn.commit()
        except Exception:
            pass  # Best-effort — never crash the drawing loop
```

**Step 3: Add get_recent_drawing_history() method**

```python
    def get_recent_drawing_history(self, limit: int = 100) -> list[dict]:
        """Get recent drawing_history entries, ascending timestamp."""
        conn = self._connect()
        rows = conn.execute(
            """SELECT timestamp, E, I, S, V, C, marks, phase, era, energy,
                      curiosity, engagement, fatigue, arc_phase,
                      gesture_entropy, switching_rate, intentionality
               FROM drawing_history
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        result = []
        for row in reversed(rows):
            result.append({
                "timestamp": row[0], "E": row[1], "I": row[2],
                "S": row[3], "V": row[4], "C": row[5],
                "marks": row[6], "phase": row[7], "era": row[8],
                "energy": row[9], "curiosity": row[10], "engagement": row[11],
                "fatigue": row[12], "arc_phase": row[13],
                "gesture_entropy": row[14], "switching_rate": row[15],
                "intentionality": row[16],
            })
        return result
```

**Step 4: Run tests**

Run: `cd /Users/cirwel/projects/anima-mcp && python3 -m pytest tests/test_drawing_history.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
cd /Users/cirwel/projects/anima-mcp
git add src/anima_mcp/identity/store.py
git commit -m "feat: add drawing_history table to anima.db

Records DrawingEISV snapshots (E, I, S, V, C, marks, phase, era,
attention signals, narrative arc) for time-series analysis.
Best-effort writes — never crashes the drawing loop."
```

---

### Task 12: Wire recording into the drawing loop

**Files:**
- Modify: `src/anima_mcp/display/screens.py` (after _eisv_step ~line 4258)

**Step 1: Add recording call after EISV step**

In the method that calls `_eisv_step()`, after the state update, add a call to record the state. The recording should be throttled (every N marks, not every mark) to avoid excessive I/O.

Find the call site of `_eisv_step()` in the drawing loop. After the return, add:

```python
# Record DrawingEISV for history (every 10 marks to throttle I/O)
if self._intent.mark_count % 10 == 0:
    try:
        from anima_mcp.identity.store import IdentityStore
        store = IdentityStore()  # Uses default path
        eisv = self._intent.eisv
        store.record_drawing_state(
            E=eisv.E, I=eisv.I, S=eisv.S, V=eisv.V,
            C=eisv.coherence(),
            marks=self._intent.mark_count,
            phase=self._canvas.drawing_phase if self._canvas else None,
            era=self._active_era.name if self._active_era else None,
            energy=eisv.derived_energy,
            curiosity=eisv.curiosity,
            engagement=eisv.engagement,
            fatigue=eisv.fatigue,
            arc_phase=eisv.arc_phase,
            gesture_entropy=eisv.S,  # S_signal from _eisv_step
            switching_rate=0.0,  # Compute if available
            intentionality=self._intent.era_state.intentionality() if self._intent.era_state else 0.0,
        )
    except Exception:
        pass  # Never crash drawing for history
```

Note: The exact wiring depends on how IdentityStore is accessed from the drawing context. If there's no direct reference, the store may need to be passed in or accessed via a singleton. The implementer should check how `state_history` recording accesses the store (via handlers) and follow the same pattern — or use a module-level function.

**Step 2: Run existing drawing tests to verify no breakage**

Run: `cd /Users/cirwel/projects/anima-mcp && python3 -m pytest tests/test_drawing_eisv.py tests/test_drawing_feedback.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
cd /Users/cirwel/projects/anima-mcp
git add src/anima_mcp/display/screens.py
git commit -m "feat: wire drawing_history recording into EISV step

Records DrawingEISV state every 10 marks. Best-effort, never
crashes the drawing loop."
```

---

## Phase 4: Verify and Document

### Task 13: Full regression on governance-mcp

**Step 1: Run full test suite**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -q 2>&1 | tail -10`
Expected: ~6400+ passed, 0 failed

**Step 2: If failures, fix and commit**

---

### Task 14: Full regression on anima-mcp

**Step 1: Run full test suite**

Run: `cd /Users/cirwel/projects/anima-mcp && python3 -m pytest tests/ -q 2>&1 | tail -10`
Expected: All pass

**Step 2: If failures, fix and commit**

---

### Task 15: Update documentation

**Files:**
- Modify: `docs/README.md` (governance-mcp) — update project structure, remove SQLite references
- Modify: `docs/UNIFIED_ARCHITECTURE.md` — add "Database Architecture" section
- Modify: `docs/database_architecture.md` — rewrite to reflect Postgres-only

**Step 1: Update docs to reflect new architecture**

Key changes:
- Remove all mentions of SQLite fallback/dual-backend
- Document that PostgreSQL is required
- Document drawing_history table and its purpose
- Update project structure tree

**Step 2: Commit**

```bash
git add docs/
git commit -m "docs: update for Postgres-only DB architecture"
```

---

### Task 16: Deploy drawing_history to Pi

**Step 1: Use deploy-to-pi skill**

Run tests, commit, push, and pull on Pi with restart.

**Step 2: Verify drawing_history accumulates**

After deployment, wait for Lumen to start drawing, then:
```bash
ssh pi "sqlite3 ~/.anima/anima.db 'SELECT COUNT(*) FROM drawing_history;'"
```

Expected: Row count increasing as Lumen draws.

---

## Summary

| Phase | Tasks | Scope | Project |
|-------|-------|-------|---------|
| 1: Kill dead files | 1 | Delete 9 files, 2 dirs | governance-mcp |
| 2: Remove SQLite | 2-9 | Delete 4 files (~3400 lines), modify ~8 files | governance-mcp |
| 3: Add drawing_history | 10-12 | Create 1 test file, modify 2 source files | anima-mcp |
| 4: Verify | 13-16 | Full regression, docs, deploy | both |
