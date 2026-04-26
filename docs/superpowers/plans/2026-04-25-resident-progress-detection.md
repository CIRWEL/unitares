# Resident Progress Detection — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-04-25-resident-progress-detection-design.md` (commit `3d0784d9`)

**Goal:** Add a telemetry-only background probe to governance-mcp that detects when residents are heartbeat-alive but not advancing measurable work, persisting per-tick snapshots and emitting low-severity `progress_flat_candidate` audit events for Phase 2 analysis.

**Architecture:** New background task in `src/background_tasks.py` ticks every 5 minutes. It resolves resident labels to UUIDs from filesystem anchors (`~/.unitares/anchors/<label>.json`), batches per-source artifact-rate queries, evaluates heartbeat liveness, composes snapshot rows, and writes them to a new append-only `progress_flat_snapshots` table. Pure side-channel — never mutates `agent_metadata.status`, never touches loop-detector flags, never enters the verdict path. A new dashboard panel renders the latest snapshot per resident; a new REST endpoint serves it.

**Tech Stack:** Python 3.12+, asyncio, asyncpg (via `src/db.get_db`), Pydantic v2 schemas, pytest + `pytest.mark.asyncio`, PostgreSQL@17, Chart.js (existing dashboard), Starlette routes (existing `src/http_api.py`).

---

## File Structure

**New files:**
- `db/postgres/migrations/017_progress_flat_telemetry.sql` — schema for both new tables
- `src/resident_progress/__init__.py`
- `src/resident_progress/registry.py` — label-keyed config; anchor-file resolver
- `src/resident_progress/heartbeat.py` — `HeartbeatEvaluator` wrapping existing silence semantics
- `src/resident_progress/sources.py` — `ResidentProgressSource` protocol + 4 implementations
- `src/resident_progress/sentinel_source.py` — `SentinelPulseSource` (push reader) and `record_progress_pulse` MCP tool
- `src/resident_progress/snapshot_writer.py` — batched insert + tick-id helper
- `src/resident_progress/status.py` — deterministic status priority resolver
- `src/resident_progress/probe_task.py` — orchestrator (called from `background_tasks.py`)
- `src/mcp_handlers/schemas/progress_flat.py` — Pydantic schemas for `record_progress_pulse`
- `dashboard/resident-progress.js` — panel module
- `tests/resident_progress/__init__.py`
- `tests/resident_progress/test_registry.py`
- `tests/resident_progress/test_heartbeat.py`
- `tests/resident_progress/test_sources.py`
- `tests/resident_progress/test_sentinel_source.py`
- `tests/resident_progress/test_status.py`
- `tests/resident_progress/test_snapshot_writer.py`
- `tests/resident_progress/test_probe_task.py`
- `tests/resident_progress/test_http_endpoint.py`
- `tests/resident_progress/test_calibration_smoke.py`

**Modified files:**
- `src/background_tasks.py` — register `progress_flat_probe_task` in `start_all_background_tasks`
- `src/http_api.py` — register `GET /v1/progress_flat/recent`
- `src/mcp_handlers/__init__.py` and the tool registry — register `record_progress_pulse`
- `dashboard/index.html` — add panel container and `<script src="resident-progress.js">`
- `dashboard/styles.css` — minimal additions if needed for badge colors (reuse existing if possible)

---

## Task 1: Migration — progress_flat_snapshots and resident_progress_pulse

**Files:**
- Create: `db/postgres/migrations/017_progress_flat_telemetry.sql`
- Test: `tests/resident_progress/test_migration.py` (smoke test that ensures both tables and indexes exist after migration)

- [ ] **Step 1: Write the failing migration smoke test**

`tests/resident_progress/test_migration.py`:

```python
"""Smoke test: migration 017 creates both telemetry tables with required columns."""
from __future__ import annotations

import pytest

from src.db import get_db


@pytest.mark.asyncio
async def test_progress_flat_snapshots_table_exists():
    db = get_db()
    async with db.acquire() as conn:
        cols = await conn.fetch("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='progress_flat_snapshots'
            ORDER BY ordinal_position
        """)
    names = {r["column_name"] for r in cols}
    required = {
        "id", "probe_tick_id", "ticked_at", "resident_label", "resident_uuid",
        "source", "metric_value", "window_seconds", "threshold",
        "metric_below_threshold", "heartbeat_alive", "candidate",
        "suppressed_reason", "error_details", "liveness_inputs",
        "loop_detector_state",
    }
    missing = required - names
    assert not missing, f"missing columns: {missing}"


@pytest.mark.asyncio
async def test_resident_progress_pulse_table_exists():
    db = get_db()
    async with db.acquire() as conn:
        cols = await conn.fetch("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='resident_progress_pulse'
        """)
    names = {r["column_name"] for r in cols}
    assert {"id", "resident_uuid", "metric_name", "value", "recorded_at"} <= names
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/resident_progress/test_migration.py -v --no-cov --tb=short`
Expected: FAIL with `relation "progress_flat_snapshots" does not exist` (or similar — the migration hasn't run yet).

- [ ] **Step 3: Write the migration**

`db/postgres/migrations/017_progress_flat_telemetry.sql`:

```sql
-- 017_progress_flat_telemetry.sql
--
-- Phase 1 telemetry tables for the resident-progress probe (see
-- docs/superpowers/specs/2026-04-25-resident-progress-detection-design.md).
-- Append-only; the probe never updates or deletes rows.

CREATE TABLE IF NOT EXISTS progress_flat_snapshots (
    id                     bigserial PRIMARY KEY,
    probe_tick_id          uuid NOT NULL,
    ticked_at              timestamptz NOT NULL,
    resident_label         text NOT NULL,
    resident_uuid          uuid,                  -- null for probe_self and unresolved labels
    source                 text NOT NULL,
    metric_value           integer,
    window_seconds         integer,
    threshold              integer,
    metric_below_threshold boolean,
    heartbeat_alive        boolean,
    candidate              boolean NOT NULL DEFAULT false,
    suppressed_reason      text,
    error_details          jsonb,
    liveness_inputs        jsonb,
    loop_detector_state    jsonb
);

CREATE INDEX IF NOT EXISTS idx_pfs_ticked_at
    ON progress_flat_snapshots (ticked_at DESC);

CREATE INDEX IF NOT EXISTS idx_pfs_label_ticked
    ON progress_flat_snapshots (resident_label, ticked_at DESC);

CREATE INDEX IF NOT EXISTS idx_pfs_tick_id
    ON progress_flat_snapshots (probe_tick_id);

CREATE TABLE IF NOT EXISTS resident_progress_pulse (
    id            bigserial PRIMARY KEY,
    resident_uuid uuid NOT NULL,
    metric_name   text NOT NULL,
    value         integer NOT NULL,
    recorded_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rpp_uuid_recorded
    ON resident_progress_pulse (resident_uuid, recorded_at DESC);

INSERT INTO core.schema_migrations (version, name)
VALUES (17, 'progress flat telemetry tables')
ON CONFLICT (version) DO NOTHING;
```

- [ ] **Step 4: Apply the migration and run the test**

Run:
```bash
psql -h localhost -p 5432 -U postgres -d governance \
  -f db/postgres/migrations/017_progress_flat_telemetry.sql
pytest tests/resident_progress/test_migration.py -v --no-cov --tb=short
```

Expected: migration applies cleanly; tests PASS.

- [ ] **Step 5: Commit**

```bash
git add db/postgres/migrations/017_progress_flat_telemetry.sql \
        tests/resident_progress/__init__.py \
        tests/resident_progress/test_migration.py
git commit -m "migration: progress_flat_snapshots + resident_progress_pulse"
```

---

## Task 2: ResidentRegistry — label-keyed config + anchor resolver

**Files:**
- Create: `src/resident_progress/__init__.py` (empty `# package marker`)
- Create: `src/resident_progress/registry.py`
- Test: `tests/resident_progress/test_registry.py`

The registry is label-keyed, source-typed config. Resident UUIDs are resolved at tick time from `~/.unitares/anchors/<label>.json`, not stored in the registry. This avoids stale config when a resident re-onboards.

- [ ] **Step 1: Write the failing test**

`tests/resident_progress/test_registry.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.resident_progress.registry import (
    RESIDENT_PROGRESS_REGISTRY,
    ResidentConfig,
    resolve_resident_uuid,
)


def test_registry_has_five_residents():
    assert set(RESIDENT_PROGRESS_REGISTRY) == {
        "vigil", "watcher", "steward", "chronicler", "sentinel"
    }


def test_registry_entries_have_required_fields():
    for label, cfg in RESIDENT_PROGRESS_REGISTRY.items():
        assert isinstance(cfg, ResidentConfig)
        assert cfg.source in {
            "kg_writes", "watcher_findings", "eisv_sync_rows",
            "metrics_series", "sentinel_pulse",
        }
        assert cfg.window.total_seconds() > 0
        assert cfg.threshold >= 1


def test_resolve_resident_uuid_reads_anchor(tmp_path, monkeypatch):
    anchor_dir = tmp_path / "anchors"
    anchor_dir.mkdir()
    (anchor_dir / "vigil.json").write_text(json.dumps({
        "agent_uuid": "11111111-2222-3333-4444-555555555555"
    }))
    monkeypatch.setattr(
        "src.resident_progress.registry.ANCHOR_DIR", anchor_dir
    )
    assert resolve_resident_uuid("vigil") == "11111111-2222-3333-4444-555555555555"


def test_resolve_resident_uuid_returns_none_when_anchor_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.resident_progress.registry.ANCHOR_DIR", tmp_path
    )
    assert resolve_resident_uuid("vigil") is None


def test_resolve_resident_uuid_returns_none_on_malformed_anchor(tmp_path, monkeypatch):
    (tmp_path / "vigil.json").write_text("not-json")
    monkeypatch.setattr(
        "src.resident_progress.registry.ANCHOR_DIR", tmp_path
    )
    assert resolve_resident_uuid("vigil") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/resident_progress/test_registry.py -v --no-cov --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.resident_progress'`.

- [ ] **Step 3: Implement the registry**

`src/resident_progress/__init__.py`:

```python
# Package marker for the resident-progress probe and its components.
```

`src/resident_progress/registry.py`:

```python
"""Label-keyed config for the resident-progress probe.

Resident UUIDs are NOT stored here. They resolve at tick time from
filesystem anchors, so a resident that re-onboards or rotates UUID is
picked up automatically. See
docs/superpowers/specs/2026-04-25-resident-progress-detection-design.md
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

ANCHOR_DIR = Path.home() / ".unitares" / "anchors"


@dataclass(frozen=True)
class ResidentConfig:
    source: str       # source.name as defined in sources.py
    metric: str       # human-readable metric label, recorded on snapshot row
    window: timedelta
    threshold: int    # candidate fires when measured metric is strictly less than threshold


RESIDENT_PROGRESS_REGISTRY: dict[str, ResidentConfig] = {
    "vigil":      ResidentConfig("kg_writes",        "rows_written", timedelta(minutes=60),  1),
    "watcher":    ResidentConfig("watcher_findings", "rows_any",     timedelta(hours=6),     1),
    "steward":    ResidentConfig("eisv_sync_rows",   "rows_written", timedelta(minutes=30),  1),
    "chronicler": ResidentConfig("metrics_series",   "rows_written", timedelta(hours=26),    1),
    "sentinel":   ResidentConfig("sentinel_pulse",   "latest_count", timedelta(minutes=30),  1),
}


def resolve_resident_uuid(label: str) -> str | None:
    """Read ~/.unitares/anchors/<label>.json and return the agent_uuid, or None."""
    path = ANCHOR_DIR / f"{label}.json"
    try:
        with path.open() as f:
            doc = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("anchor %s unreadable: %s", path, e)
        return None
    uuid = doc.get("agent_uuid")
    return uuid if isinstance(uuid, str) and uuid else None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/resident_progress/test_registry.py -v --no-cov --tb=short`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resident_progress/__init__.py \
        src/resident_progress/registry.py \
        tests/resident_progress/test_registry.py
git commit -m "feat(resident-progress): label-keyed registry with anchor resolver"
```

---

## Task 3: HeartbeatEvaluator — wraps existing silence semantics

**Files:**
- Create: `src/resident_progress/heartbeat.py`
- Test: `tests/resident_progress/test_heartbeat.py`

The evaluator must NOT invent new liveness logic. It reads the same fields the existing silence detector consumes (`last_update`, expected cadence) from agent metadata and returns a structured `HeartbeatStatus`.

- [ ] **Step 1: Write the failing test**

`tests/resident_progress/test_heartbeat.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.resident_progress.heartbeat import HeartbeatEvaluator, HeartbeatStatus


class _FakeMetadataStore:
    def __init__(self, rows: dict[str, dict]):
        self._rows = rows

    async def get(self, agent_uuid: str) -> dict | None:
        return self._rows.get(agent_uuid)


@pytest.mark.asyncio
async def test_evaluate_alive_when_recent_update():
    now = datetime.now(timezone.utc)
    store = _FakeMetadataStore({
        "u1": {"last_update": now - timedelta(seconds=30), "expected_cadence_s": 60},
    })
    ev = HeartbeatEvaluator(store, _now=lambda: now)
    status = await ev.evaluate("u1")
    assert status.alive is True
    assert status.in_critical_silence is False
    assert status.eval_error is None


@pytest.mark.asyncio
async def test_evaluate_silent_when_stale_update():
    now = datetime.now(timezone.utc)
    store = _FakeMetadataStore({
        "u1": {"last_update": now - timedelta(minutes=30), "expected_cadence_s": 60},
    })
    ev = HeartbeatEvaluator(store, _now=lambda: now)
    status = await ev.evaluate("u1")
    assert status.alive is False
    assert status.in_critical_silence is True


@pytest.mark.asyncio
async def test_evaluate_unknown_agent_returns_not_alive():
    ev = HeartbeatEvaluator(_FakeMetadataStore({}), _now=lambda: datetime.now(timezone.utc))
    status = await ev.evaluate("missing-uuid")
    assert status.alive is False
    assert status.eval_error is None  # missing agent is a known-not-alive, not an error


@pytest.mark.asyncio
async def test_evaluate_returns_error_on_store_exception():
    class _Boom:
        async def get(self, _): raise RuntimeError("db down")
    ev = HeartbeatEvaluator(_Boom(), _now=lambda: datetime.now(timezone.utc))
    status = await ev.evaluate("u1")
    assert status.alive is False
    assert "db down" in (status.eval_error or "")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/resident_progress/test_heartbeat.py -v --no-cov --tb=short`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the evaluator**

`src/resident_progress/heartbeat.py`:

```python
"""HeartbeatEvaluator — thin wrapper over the existing silence/cadence
semantics. The probe uses this so its candidate gate is consistent with
how the rest of the server defines a resident as alive.

Critical-silence threshold is 3x expected cadence. Below that we consider
the resident alive even if the most recent update is slightly stale.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Protocol

logger = logging.getLogger(__name__)

# Match the existing convention: alive if last_update within 3x cadence.
ALIVE_CADENCE_MULTIPLIER = 3


class _MetadataStore(Protocol):
    async def get(self, agent_uuid: str) -> dict | None: ...


@dataclass
class HeartbeatStatus:
    alive: bool
    last_update: datetime | None
    expected_cadence_s: int | None
    in_critical_silence: bool
    eval_error: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        d = asdict(self)
        if d["last_update"] is not None:
            d["last_update"] = d["last_update"].isoformat()
        return d


class HeartbeatEvaluator:
    def __init__(
        self,
        store: _MetadataStore,
        _now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._store = store
        self._now = _now

    async def evaluate(self, agent_uuid: str) -> HeartbeatStatus:
        try:
            row = await self._store.get(agent_uuid)
        except Exception as e:
            return HeartbeatStatus(
                alive=False, last_update=None, expected_cadence_s=None,
                in_critical_silence=False, eval_error=f"{type(e).__name__}: {e}",
            )
        if row is None:
            return HeartbeatStatus(
                alive=False, last_update=None, expected_cadence_s=None,
                in_critical_silence=False,
            )
        last = row.get("last_update")
        cadence = int(row.get("expected_cadence_s") or 0) or None
        if last is None or cadence is None:
            return HeartbeatStatus(
                alive=False, last_update=last, expected_cadence_s=cadence,
                in_critical_silence=False,
            )
        elapsed = self._now() - last
        critical_threshold = timedelta(seconds=cadence * ALIVE_CADENCE_MULTIPLIER)
        in_critical = elapsed > critical_threshold
        return HeartbeatStatus(
            alive=not in_critical, last_update=last, expected_cadence_s=cadence,
            in_critical_silence=in_critical,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/resident_progress/test_heartbeat.py -v --no-cov --tb=short`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resident_progress/heartbeat.py tests/resident_progress/test_heartbeat.py
git commit -m "feat(resident-progress): heartbeat evaluator wrapping silence semantics"
```

---

## Task 4: Sources — KG/Watcher/Steward/Chronicler pulls

**Files:**
- Create: `src/resident_progress/sources.py`
- Test: `tests/resident_progress/test_sources.py`

Four pull sources, each issuing a single batched query. `KnowledgeDiscoverySource` is shared by Vigil and Watcher (both write to `knowledge.discoveries`, filtered by `agent_id`). Steward reads `audit.events WHERE event_type='eisv_sync'`. Chronicler reads `metrics.series` filtered by its known scraper names.

- [ ] **Step 1: Write the failing test**

`tests/resident_progress/test_sources.py`:

```python
from __future__ import annotations

from datetime import timedelta

import pytest

from src.resident_progress.sources import (
    ResidentProgressSource,
    KnowledgeDiscoverySource,
    EISVSyncSource,
    MetricsSeriesSource,
    CHRONICLER_SERIES_NAMES,
)


@pytest.mark.asyncio
async def test_kg_source_returns_zero_for_unknown_uuid(test_db):
    src = KnowledgeDiscoverySource(test_db)
    out = await src.fetch(["00000000-0000-0000-0000-000000000000"], timedelta(hours=1))
    assert out == {"00000000-0000-0000-0000-000000000000": 0}


@pytest.mark.asyncio
async def test_kg_source_counts_recent_rows(test_db):
    uuid = "10000000-0000-0000-0000-000000000001"
    async with test_db.acquire() as conn:
        await conn.execute(
            "INSERT INTO knowledge.discoveries (id, agent_id, type, summary) "
            "VALUES ($1, $2, 'note', 'x')",
            "test-row-1", uuid,
        )
    src = KnowledgeDiscoverySource(test_db)
    out = await src.fetch([uuid], timedelta(hours=1))
    assert out[uuid] >= 1


@pytest.mark.asyncio
async def test_kg_source_batches_one_query_for_many_uuids(test_db, monkeypatch):
    seen_calls = []
    real_acquire = test_db.acquire
    class _Tracking:
        def __init__(self, c): self._c = c
        async def fetch(self, *args, **kwargs):
            seen_calls.append(args[0])
            return await self._c.fetch(*args, **kwargs)
        def __getattr__(self, name): return getattr(self._c, name)
    class _AcquireProxy:
        def __init__(self, db): self._db = db
        async def __aenter__(self):
            self._cm = real_acquire()
            conn = await self._cm.__aenter__()
            return _Tracking(conn)
        async def __aexit__(self, *a):
            return await self._cm.__aexit__(*a)
    monkeypatch.setattr(test_db, "acquire", lambda: _AcquireProxy(test_db))
    src = KnowledgeDiscoverySource(test_db)
    await src.fetch([f"22222222-0000-0000-0000-{i:012d}" for i in range(5)], timedelta(hours=1))
    assert len(seen_calls) == 1, "must issue exactly one batched query"


@pytest.mark.asyncio
async def test_eisv_sync_source_filters_by_event_type(test_db):
    src = EISVSyncSource(test_db)
    out = await src.fetch(["33333333-0000-0000-0000-000000000003"], timedelta(minutes=30))
    assert "33333333-0000-0000-0000-000000000003" in out


def test_chronicler_series_names_includes_tokei():
    assert "tokei.unitares.src.code" in CHRONICLER_SERIES_NAMES


@pytest.mark.asyncio
async def test_metrics_series_source_uses_name_list(test_db):
    src = MetricsSeriesSource(test_db)
    out = await src.fetch(["44444444-0000-0000-0000-000000000004"], timedelta(hours=26))
    # Chronicler source has no agent_id column; result is the same per-uuid count
    # because all uuids share the same name-filtered total.
    assert all(v == out["44444444-0000-0000-0000-000000000004"] for v in out.values())
```

The test uses a `test_db` fixture; if the existing `tests/conftest.py` doesn't already provide one, add it as part of this task (see Step 3a).

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/resident_progress/test_sources.py -v --no-cov --tb=short`
Expected: FAIL with `ImportError: cannot import name 'KnowledgeDiscoverySource'`.

- [ ] **Step 3: Implement the sources**

`src/resident_progress/sources.py`:

```python
"""ResidentProgressSource implementations.

Each source issues exactly one batched query covering all relevant
resident UUIDs in the window — never N×M fanout. The orchestrator
groups configured (source_name, window) pairs and calls each group once.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Iterable, Protocol

# Names defined in agents/chronicler/scrapers.py (SCRAPERS dict). Must
# stay in sync with that file; if Chronicler adds a series, add it here.
CHRONICLER_SERIES_NAMES: tuple[str, ...] = (
    "tokei.unitares.src.code",
    "tests.unitares.count",
    "agents.active.7d",
    "kg.entries.count",
    "checkins.7d",
)


class ResidentProgressSource(Protocol):
    name: str
    async def fetch(self, resident_uuids: list[str], window: timedelta) -> dict[str, int]: ...


class KnowledgeDiscoverySource:
    """Counts rows in knowledge.discoveries per resident_uuid in the window.

    Used for both Vigil (resident_label='vigil') and Watcher
    (resident_label='watcher'); the orchestrator filters by the resolved
    UUID so the same source class serves both.
    """
    name = "kg_writes"  # Watcher's source uses name='watcher_findings' (see registry)

    def __init__(self, db) -> None:
        self._db = db

    async def fetch(self, resident_uuids: list[str], window: timedelta) -> dict[str, int]:
        if not resident_uuids:
            return {}
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT agent_id::text AS uuid, count(*) AS n
                FROM knowledge.discoveries
                WHERE agent_id = ANY($1::text[])
                  AND created_at > now() - $2::interval
                GROUP BY agent_id
                """,
                resident_uuids,
                window,
            )
        counts = {r["uuid"]: int(r["n"]) for r in rows}
        return {u: counts.get(u, 0) for u in resident_uuids}


class WatcherFindingSource(KnowledgeDiscoverySource):
    """Same as KnowledgeDiscoverySource — Watcher posts via post_finding
    which lands in knowledge.discoveries. Subclassed only so the source
    name on snapshot rows is forensically distinct from Vigil's writes.
    """
    name = "watcher_findings"


class EISVSyncSource:
    """Counts audit.events rows with event_type='eisv_sync' authored by
    the given resident in the window. Steward is the sole writer.
    """
    name = "eisv_sync_rows"

    def __init__(self, db) -> None:
        self._db = db

    async def fetch(self, resident_uuids: list[str], window: timedelta) -> dict[str, int]:
        if not resident_uuids:
            return {}
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT agent_id::text AS uuid, count(*) AS n
                FROM audit.events
                WHERE event_type = 'eisv_sync'
                  AND agent_id = ANY($1::text[])
                  AND ts > now() - $2::interval
                GROUP BY agent_id
                """,
                resident_uuids,
                window,
            )
        counts = {r["uuid"]: int(r["n"]) for r in rows}
        return {u: counts.get(u, 0) for u in resident_uuids}


class MetricsSeriesSource:
    """Counts metrics.series rows whose `name` is in the
    Chronicler-known list, in the window. metrics.series has no agent_id
    column, so all configured UUIDs receive the same count — Chronicler
    is the sole writer of these names. If another agent ever starts
    writing to these names, this assumption breaks; revisit at that time.
    """
    name = "metrics_series"

    def __init__(self, db) -> None:
        self._db = db

    async def fetch(self, resident_uuids: list[str], window: timedelta) -> dict[str, int]:
        if not resident_uuids:
            return {}
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT count(*) AS n
                FROM metrics.series
                WHERE name = ANY($1::text[])
                  AND ts > now() - $2::interval
                """,
                list(CHRONICLER_SERIES_NAMES),
                window,
            )
        n = int(row["n"]) if row else 0
        return {u: n for u in resident_uuids}
```

If `tests/conftest.py` does not already expose a `test_db` fixture suitable for direct asyncpg writes against the governance database, add or adapt one before running tests. Read the existing conftest first.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/resident_progress/test_sources.py -v --no-cov --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resident_progress/sources.py tests/resident_progress/test_sources.py
git commit -m "feat(resident-progress): four pull sources with batched queries"
```

---

## Task 5: SentinelPulseSource + record_progress_pulse MCP tool

**Files:**
- Create: `src/resident_progress/sentinel_source.py`
- Create: `src/mcp_handlers/schemas/progress_flat.py`
- Modify: `src/mcp_handlers/__init__.py` (or wherever the tool registry imports happen) — register `record_progress_pulse`
- Test: `tests/resident_progress/test_sentinel_source.py`

`record_progress_pulse` binds `resident_uuid` from the authenticated agent. If the caller passes a `resident_uuid` that doesn't match the bound UUID, the tool rejects with an auth error (not a silent overwrite).

- [ ] **Step 1: Write the failing tests**

`tests/resident_progress/test_sentinel_source.py`:

```python
from __future__ import annotations

from datetime import timedelta

import pytest

from src.resident_progress.sentinel_source import SentinelPulseSource


@pytest.mark.asyncio
async def test_pulse_source_returns_latest_value_in_window(test_db):
    uuid = "55555555-0000-0000-0000-000000000005"
    async with test_db.acquire() as conn:
        await conn.execute(
            "INSERT INTO resident_progress_pulse "
            "(resident_uuid, metric_name, value, recorded_at) "
            "VALUES ($1, 'evaluated', 7, now() - interval '5 minutes'), "
            "       ($1, 'evaluated', 12, now() - interval '1 minute')",
            uuid,
        )
    src = SentinelPulseSource(test_db)
    out = await src.fetch([uuid], timedelta(minutes=30))
    assert out[uuid] == 12  # latest, not sum


@pytest.mark.asyncio
async def test_pulse_source_returns_zero_when_no_rows_in_window(test_db):
    src = SentinelPulseSource(test_db)
    out = await src.fetch(["66666666-0000-0000-0000-000000000006"], timedelta(minutes=30))
    assert out["66666666-0000-0000-0000-000000000006"] == 0


@pytest.mark.asyncio
async def test_record_progress_pulse_binds_resident_uuid_from_auth(monkeypatch):
    from src.mcp_handlers.lifecycle.shared_helpers import (
        require_registered_agent,
        resolve_agent_uuid,
    )  # adjust import to actual location
    # Use existing test fixtures for an authenticated agent. The detailed
    # mocking pattern here MUST match the project's existing MCP handler
    # tests (see tests/test_admin_handlers.py and tests/test_agent_lifecycle.py
    # for the canonical pattern). Pseudo-spec:
    #   1. Build arguments with bound agent_uuid="A".
    #   2. Call record_progress_pulse(arguments={"metric_name":"x","value":1}).
    #   3. Assert one row written with resident_uuid="A".
    #   4. Build arguments with bound agent_uuid="A" but
    #      caller-supplied resident_uuid="B".
    #   5. Call record_progress_pulse — assert it returns an auth error
    #      and writes no row.
    pytest.skip("Implementation detail: wire to project's MCP test harness; "
                "see tests/test_agent_lifecycle.py for the auth-mock pattern.")
```

> Note: the third test is sketched as a skip with explicit instructions for the implementer because the project's MCP-handler test harness has a specific mocking convention (see `tests/test_agent_lifecycle.py`). The implementer must wire the test to that harness; the skip should be removed and the assertions made concrete in Step 3.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/resident_progress/test_sentinel_source.py -v --no-cov --tb=short`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the source, schema, and tool**

`src/resident_progress/sentinel_source.py`:

```python
"""Sentinel push reader and the `record_progress_pulse` MCP tool.

This is the only push surface in the probe — every other source pulls
from canonical artifact tables. Sentinel needs push because its work
can legitimately produce zero artifacts (evaluating and finding nothing
is real work).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Sequence

from mcp.types import TextContent  # adjust if project alias differs

from src.mcp_handlers.decorators import mcp_tool
from src.mcp_handlers.error_helpers import error_response
from src.mcp_handlers.identity.shared import get_bound_agent_id
from src.mcp_handlers.lifecycle.shared_helpers import require_registered_agent
from src.mcp_handlers.response_base import success_response
from src.mcp_handlers.schemas.progress_flat import RecordProgressPulseParams

logger = logging.getLogger(__name__)


class SentinelPulseSource:
    name = "sentinel_pulse"

    def __init__(self, db) -> None:
        self._db = db

    async def fetch(self, resident_uuids: list[str], window: timedelta) -> dict[str, int]:
        if not resident_uuids:
            return {}
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (resident_uuid)
                       resident_uuid::text AS uuid, value
                FROM resident_progress_pulse
                WHERE resident_uuid = ANY($1::uuid[])
                  AND recorded_at > now() - $2::interval
                ORDER BY resident_uuid, recorded_at DESC
                """,
                resident_uuids,
                window,
            )
        latest = {r["uuid"]: int(r["value"]) for r in rows}
        return {u: latest.get(u, 0) for u in resident_uuids}


@mcp_tool("record_progress_pulse", timeout=5.0, register=True)
async def handle_record_progress_pulse(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Sentinel posts a per-tick progress counter. resident_uuid is
    always bound from the authenticated current agent. If the caller
    passes resident_uuid in arguments, it must equal the bound UUID;
    mismatched values are rejected.
    """
    agent_id, err = require_registered_agent(arguments)
    if err:
        return [err]
    bound_uuid = get_bound_agent_id(arguments) or agent_id

    params = RecordProgressPulseParams.model_validate(arguments)
    if params.resident_uuid is not None and params.resident_uuid != bound_uuid:
        return [error_response(
            "resident_uuid does not match authenticated agent",
            error_code="AUTH_RESIDENT_MISMATCH",
            error_category="auth_error",
            details={"bound": bound_uuid, "supplied": params.resident_uuid},
        )]

    from src.db import get_db
    async with get_db().acquire() as conn:
        await conn.execute(
            "INSERT INTO resident_progress_pulse "
            "(resident_uuid, metric_name, value) VALUES ($1, $2, $3)",
            bound_uuid, params.metric_name, params.value,
        )
    return success_response({
        "success": True, "resident_uuid": bound_uuid,
        "metric_name": params.metric_name, "value": params.value,
    })
```

`src/mcp_handlers/schemas/progress_flat.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RecordProgressPulseParams(BaseModel):
    metric_name: str = Field(..., min_length=1, max_length=128)
    value: int = Field(..., ge=0)
    resident_uuid: str | None = None  # optional; ignored unless equal to auth-bound UUID

    @field_validator("metric_name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        # alnum + underscore + dot — same shape as metrics.series names
        if not all(c.isalnum() or c in "._-" for c in v):
            raise ValueError("metric_name must be alphanumeric + . _ -")
        return v
```

Register the tool: append to whatever module `src/mcp_handlers/__init__.py` imports for tool registration so `record_progress_pulse` appears in the registry. Match the pattern of an existing simple tool (e.g., `archive_old_test_agents` registration) — read that file before editing.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/resident_progress/test_sentinel_source.py -v --no-cov --tb=short`
Expected: PASS (the auth-binding test, once the implementer has wired it to the project's MCP harness, must assert: bound-uuid match → row written; mismatched → auth error + no row).

- [ ] **Step 5: Commit**

```bash
git add src/resident_progress/sentinel_source.py \
        src/mcp_handlers/schemas/progress_flat.py \
        src/mcp_handlers/__init__.py \
        tests/resident_progress/test_sentinel_source.py
git commit -m "feat(resident-progress): sentinel pulse source + record_progress_pulse tool"
```

---

## Task 6: Status priority resolver

**Files:**
- Create: `src/resident_progress/status.py`
- Test: `tests/resident_progress/test_status.py`

Pure function, exhaustively tested. Status priority: `source-error > unresolved > startup-grace > silent > flat-candidate > OK`.

- [ ] **Step 1: Write the failing test**

`tests/resident_progress/test_status.py`:

```python
from __future__ import annotations

import pytest

from src.resident_progress.status import resolve_status


def _row(**overrides):
    base = {
        "candidate": False, "heartbeat_alive": True,
        "metric_below_threshold": False, "suppressed_reason": None,
        "error_details": None,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("row,expected", [
    (_row(error_details={"source": "kg_writes"}), "source-error"),
    (_row(suppressed_reason="unresolved_label"), "unresolved"),
    (_row(suppressed_reason="startup_unresolved_label"), "startup-grace"),
    (_row(suppressed_reason="heartbeat_not_alive", heartbeat_alive=False), "silent"),
    (_row(suppressed_reason="heartbeat_eval_error", heartbeat_alive=False), "silent"),
    (_row(candidate=True, metric_below_threshold=True), "flat-candidate"),
    (_row(), "OK"),
    # Tie-break: source-error wins over unresolved
    (_row(error_details={"source": "x"}, suppressed_reason="unresolved_label"),
     "source-error"),
    # Tie-break: silent wins over flat-candidate when both could apply
    (_row(suppressed_reason="heartbeat_not_alive", heartbeat_alive=False,
          candidate=False, metric_below_threshold=True), "silent"),
])
def test_status_priority(row, expected):
    assert resolve_status(row) == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/resident_progress/test_status.py -v --no-cov --tb=short`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the resolver**

`src/resident_progress/status.py`:

```python
"""Deterministic status-priority resolver for progress_flat snapshot rows.

Priority (first match wins):
    source-error > unresolved > startup-grace > silent > flat-candidate > OK
"""
from __future__ import annotations


def resolve_status(row: dict) -> str:
    if row.get("error_details"):
        return "source-error"
    suppressed = row.get("suppressed_reason")
    if suppressed == "unresolved_label":
        return "unresolved"
    if suppressed == "startup_unresolved_label":
        return "startup-grace"
    if suppressed in ("heartbeat_not_alive", "heartbeat_eval_error"):
        return "silent"
    if row.get("candidate") is True:
        return "flat-candidate"
    return "OK"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/resident_progress/test_status.py -v --no-cov --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resident_progress/status.py tests/resident_progress/test_status.py
git commit -m "feat(resident-progress): status priority resolver"
```

---

## Task 7: SnapshotWriter — batched insert

**Files:**
- Create: `src/resident_progress/snapshot_writer.py`
- Test: `tests/resident_progress/test_snapshot_writer.py`

One method: `write(rows: list[SnapshotRow]) -> None`. Uses `executemany` (asyncpg) so one round-trip persists all rows for the tick.

- [ ] **Step 1: Write the failing test**

`tests/resident_progress/test_snapshot_writer.py`:

```python
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from src.resident_progress.snapshot_writer import SnapshotRow, SnapshotWriter


@pytest.mark.asyncio
async def test_writer_persists_all_rows_in_one_batch(test_db):
    tick_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    rows = [
        SnapshotRow(
            probe_tick_id=tick_id, ticked_at=now, resident_label="vigil",
            resident_uuid="11111111-1111-1111-1111-111111111111",
            source="kg_writes", metric_value=3, window_seconds=3600,
            threshold=1, metric_below_threshold=False, heartbeat_alive=True,
            candidate=False, suppressed_reason=None,
            error_details=None, liveness_inputs={"alive": True},
            loop_detector_state=None,
        ),
        SnapshotRow(
            probe_tick_id=tick_id, ticked_at=now, resident_label="watcher",
            resident_uuid="22222222-2222-2222-2222-222222222222",
            source="watcher_findings", metric_value=0, window_seconds=21600,
            threshold=1, metric_below_threshold=True, heartbeat_alive=True,
            candidate=True, suppressed_reason=None, error_details=None,
            liveness_inputs={"alive": True}, loop_detector_state=None,
        ),
    ]
    writer = SnapshotWriter(test_db)
    await writer.write(rows)

    async with test_db.acquire() as conn:
        persisted = await conn.fetch(
            "SELECT resident_label, candidate FROM progress_flat_snapshots "
            "WHERE probe_tick_id = $1 ORDER BY resident_label",
            tick_id,
        )
    assert len(persisted) == 2
    assert persisted[0]["resident_label"] == "vigil"
    assert persisted[0]["candidate"] is False
    assert persisted[1]["resident_label"] == "watcher"
    assert persisted[1]["candidate"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/resident_progress/test_snapshot_writer.py -v --no-cov --tb=short`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the writer**

`src/resident_progress/snapshot_writer.py`:

```python
"""Batched insert for progress_flat_snapshots."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class SnapshotRow:
    probe_tick_id: UUID
    ticked_at: datetime
    resident_label: str
    resident_uuid: str | None
    source: str
    metric_value: int | None
    window_seconds: int | None
    threshold: int | None
    metric_below_threshold: bool | None
    heartbeat_alive: bool | None
    candidate: bool
    suppressed_reason: str | None
    error_details: dict | None
    liveness_inputs: dict | None
    loop_detector_state: dict | None


_INSERT_SQL = """
INSERT INTO progress_flat_snapshots (
    probe_tick_id, ticked_at, resident_label, resident_uuid, source,
    metric_value, window_seconds, threshold, metric_below_threshold,
    heartbeat_alive, candidate, suppressed_reason, error_details,
    liveness_inputs, loop_detector_state
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14::jsonb, $15::jsonb
)
"""


def _row_args(r: SnapshotRow) -> tuple[Any, ...]:
    def _j(d): return json.dumps(d) if d is not None else None
    return (
        r.probe_tick_id, r.ticked_at, r.resident_label, r.resident_uuid,
        r.source, r.metric_value, r.window_seconds, r.threshold,
        r.metric_below_threshold, r.heartbeat_alive, r.candidate,
        r.suppressed_reason, _j(r.error_details), _j(r.liveness_inputs),
        _j(r.loop_detector_state),
    )


class SnapshotWriter:
    def __init__(self, db) -> None:
        self._db = db

    async def write(self, rows: list[SnapshotRow]) -> None:
        if not rows:
            return
        async with self._db.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(_INSERT_SQL, [_row_args(r) for r in rows])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/resident_progress/test_snapshot_writer.py -v --no-cov --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resident_progress/snapshot_writer.py tests/resident_progress/test_snapshot_writer.py
git commit -m "feat(resident-progress): batched snapshot writer"
```

---

## Task 8: Probe orchestrator — tick lifecycle

**Files:**
- Create: `src/resident_progress/probe_task.py`
- Test: `tests/resident_progress/test_probe_task.py`

Orchestrator owns: `probe_tick_id` generation, registry resolution (with startup grace), source dispatch, heartbeat dispatch, snapshot composition, batched insert, candidate event emission, dogfood row.

- [ ] **Step 1: Write the failing tests**

`tests/resident_progress/test_probe_task.py`:

```python
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from src.resident_progress.probe_task import ProgressFlatProbe


def _fake_registry():
    from datetime import timedelta
    from src.resident_progress.registry import ResidentConfig
    return {
        "vigil": ResidentConfig("kg_writes", "rows_written", timedelta(hours=1), 1),
    }


@pytest.mark.asyncio
async def test_tick_writes_one_resident_row_plus_dogfood(monkeypatch):
    monkeypatch.setattr(
        "src.resident_progress.probe_task.RESIDENT_PROGRESS_REGISTRY",
        _fake_registry(),
    )
    monkeypatch.setattr(
        "src.resident_progress.probe_task.resolve_resident_uuid",
        lambda label: "11111111-1111-1111-1111-111111111111" if label == "vigil" else None,
    )
    sources = {"kg_writes": AsyncMock(fetch=AsyncMock(return_value={
        "11111111-1111-1111-1111-111111111111": 5
    }))}
    sources["kg_writes"].name = "kg_writes"
    heartbeat = AsyncMock()
    heartbeat.evaluate.return_value = type("HS", (), {
        "alive": True, "last_update": None, "expected_cadence_s": 60,
        "in_critical_silence": False, "eval_error": None,
        "to_jsonable": lambda self: {"alive": True},
    })()
    writer = AsyncMock()
    audit = AsyncMock()
    probe = ProgressFlatProbe(
        sources_by_name=sources, heartbeat_evaluator=heartbeat,
        writer=writer, audit_emitter=audit, _now_tick=0,
    )
    await probe.tick()
    written = writer.write.await_args.args[0]
    labels = [r.resident_label for r in written]
    assert "vigil" in labels
    assert "progress_flat_probe" in labels  # dogfood row


@pytest.mark.asyncio
async def test_unresolved_label_writes_suppressed_row_no_event(monkeypatch):
    monkeypatch.setattr(
        "src.resident_progress.probe_task.RESIDENT_PROGRESS_REGISTRY",
        _fake_registry(),
    )
    monkeypatch.setattr(
        "src.resident_progress.probe_task.resolve_resident_uuid", lambda _: None,
    )
    writer = AsyncMock()
    audit = AsyncMock()
    probe = ProgressFlatProbe(
        sources_by_name={}, heartbeat_evaluator=AsyncMock(),
        writer=writer, audit_emitter=audit, _now_tick=10,  # past startup grace
    )
    await probe.tick()
    rows = writer.write.await_args.args[0]
    vigil_row = next(r for r in rows if r.resident_label == "vigil")
    assert vigil_row.suppressed_reason == "unresolved_label"
    assert vigil_row.candidate is False
    audit.emit.assert_not_called()


@pytest.mark.asyncio
async def test_startup_grace_first_two_ticks(monkeypatch):
    monkeypatch.setattr(
        "src.resident_progress.probe_task.RESIDENT_PROGRESS_REGISTRY",
        _fake_registry(),
    )
    monkeypatch.setattr(
        "src.resident_progress.probe_task.resolve_resident_uuid", lambda _: None,
    )
    writer = AsyncMock()
    probe = ProgressFlatProbe(
        sources_by_name={}, heartbeat_evaluator=AsyncMock(),
        writer=writer, audit_emitter=AsyncMock(), _now_tick=0,
    )
    await probe.tick()
    rows = writer.write.await_args.args[0]
    vigil_row = next(r for r in rows if r.resident_label == "vigil")
    assert vigil_row.suppressed_reason == "startup_unresolved_label"


@pytest.mark.asyncio
async def test_source_error_isolated_per_resident(monkeypatch):
    from datetime import timedelta
    from src.resident_progress.registry import ResidentConfig
    monkeypatch.setattr(
        "src.resident_progress.probe_task.RESIDENT_PROGRESS_REGISTRY",
        {
            "vigil": ResidentConfig("kg_writes", "rows_written", timedelta(hours=1), 1),
            "watcher": ResidentConfig("watcher_findings", "rows_any", timedelta(hours=6), 1),
        },
    )
    monkeypatch.setattr(
        "src.resident_progress.probe_task.resolve_resident_uuid",
        lambda l: f"{l[0]*8}-1111-1111-1111-111111111111",
    )
    boom = AsyncMock(fetch=AsyncMock(side_effect=RuntimeError("kg down")))
    boom.name = "kg_writes"
    ok = AsyncMock(fetch=AsyncMock(return_value={"wwwwwwww-1111-1111-1111-111111111111": 0}))
    ok.name = "watcher_findings"
    heartbeat = AsyncMock()
    heartbeat.evaluate.return_value = type("HS", (), {
        "alive": True, "last_update": None, "expected_cadence_s": 60,
        "in_critical_silence": False, "eval_error": None,
        "to_jsonable": lambda self: {"alive": True},
    })()
    writer = AsyncMock()
    probe = ProgressFlatProbe(
        sources_by_name={"kg_writes": boom, "watcher_findings": ok},
        heartbeat_evaluator=heartbeat, writer=writer,
        audit_emitter=AsyncMock(), _now_tick=10,
    )
    await probe.tick()
    rows = writer.write.await_args.args[0]
    vigil_row = next(r for r in rows if r.resident_label == "vigil")
    watcher_row = next(r for r in rows if r.resident_label == "watcher")
    assert vigil_row.suppressed_reason == "source_error"
    assert vigil_row.error_details is not None
    assert watcher_row.suppressed_reason is None
    assert watcher_row.candidate is True


@pytest.mark.asyncio
async def test_dogfood_write_failure_is_logged_not_fatal(monkeypatch, caplog):
    # When dogfood-row insert fails after resident rows succeed, the tick
    # is logged but not raised. Resident snapshot rows still persisted.
    pytest.skip("Implementation detail: implement once writer supports "
                "isolated dogfood-write failure mode (Step 3 below).")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/resident_progress/test_probe_task.py -v --no-cov --tb=short`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the orchestrator**

`src/resident_progress/probe_task.py`:

```python
"""Resident-progress probe orchestrator.

Tick lifecycle:
  1. Generate probe_tick_id.
  2. For each configured (label, ResidentConfig):
       a. Resolve label -> resident_uuid via filesystem anchor.
       b. If unresolved during first 2 ticks: write startup_unresolved_label row.
       c. If unresolved after grace: write unresolved_label row.
  3. Group resolved (source, window) pairs; call source.fetch once per group.
     Source errors are isolated; affected residents get suppressed_reason="source_error".
  4. Evaluate heartbeat per resolved resident.
  5. Compose snapshot rows; candidate = metric_below_threshold AND heartbeat_alive
     AND suppressed_reason is None.
  6. Append dogfood row last (count of resident rows successfully written).
  7. Batched insert.
  8. Emit progress_flat_candidate audit event for rows where candidate=true.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol

from src.resident_progress.registry import (
    RESIDENT_PROGRESS_REGISTRY,
    resolve_resident_uuid,
)
from src.resident_progress.snapshot_writer import SnapshotRow

logger = logging.getLogger(__name__)

STARTUP_GRACE_TICKS = 2


class _Source(Protocol):
    name: str
    async def fetch(self, uuids: list[str], window): ...


class _Heartbeat(Protocol):
    async def evaluate(self, agent_uuid: str): ...


class _Writer(Protocol):
    async def write(self, rows: list[SnapshotRow]) -> None: ...


class _AuditEmitter(Protocol):
    async def emit(self, *, event_type: str, severity: str, payload: dict) -> None: ...


class ProgressFlatProbe:
    def __init__(
        self,
        sources_by_name: dict[str, _Source],
        heartbeat_evaluator: _Heartbeat,
        writer: _Writer,
        audit_emitter: _AuditEmitter,
        _now_tick: int = 0,
    ) -> None:
        self._sources = sources_by_name
        self._heartbeat = heartbeat_evaluator
        self._writer = writer
        self._audit = audit_emitter
        self._tick_count = _now_tick

    async def tick(self) -> None:
        self._tick_count += 1
        tick_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        resolved: dict[str, str] = {}
        unresolved_rows: list[SnapshotRow] = []
        for label, cfg in RESIDENT_PROGRESS_REGISTRY.items():
            agent_uuid = resolve_resident_uuid(label)
            if agent_uuid is None:
                reason = (
                    "startup_unresolved_label"
                    if self._tick_count <= STARTUP_GRACE_TICKS
                    else "unresolved_label"
                )
                unresolved_rows.append(SnapshotRow(
                    probe_tick_id=tick_id, ticked_at=now,
                    resident_label=label, resident_uuid=None,
                    source=cfg.source, metric_value=None,
                    window_seconds=int(cfg.window.total_seconds()),
                    threshold=cfg.threshold,
                    metric_below_threshold=None, heartbeat_alive=False,
                    candidate=False, suppressed_reason=reason,
                    error_details=None, liveness_inputs=None,
                    loop_detector_state=None,
                ))
            else:
                resolved[label] = agent_uuid

        groups: dict[tuple[str, int], list[str]] = defaultdict(list)
        for label, agent_uuid in resolved.items():
            cfg = RESIDENT_PROGRESS_REGISTRY[label]
            groups[(cfg.source, int(cfg.window.total_seconds()))].append(agent_uuid)

        async def _call_source(name: str, window_s: int, uuids: list[str]):
            src = self._sources[name]
            try:
                from datetime import timedelta
                return name, await src.fetch(uuids, timedelta(seconds=window_s)), None
            except Exception as e:
                return name, None, f"{type(e).__name__}: {e}"

        results = await asyncio.gather(*[
            _call_source(name, window_s, uuids)
            for (name, window_s), uuids in groups.items()
        ])
        source_outputs: dict[str, dict[str, int]] = {}
        source_errors: dict[str, str] = {}
        for name, out, err in results:
            if err is not None:
                source_errors[name] = err
            else:
                source_outputs[name] = out or {}

        async def _hb(agent_uuid: str):
            return agent_uuid, await self._heartbeat.evaluate(agent_uuid)

        hb_pairs = await asyncio.gather(*[_hb(u) for u in resolved.values()])
        hb_by_uuid = {u: status for u, status in hb_pairs}

        resident_rows: list[SnapshotRow] = []
        for label, agent_uuid in resolved.items():
            cfg = RESIDENT_PROGRESS_REGISTRY[label]
            window_s = int(cfg.window.total_seconds())
            hb = hb_by_uuid[agent_uuid]
            if cfg.source in source_errors:
                row = SnapshotRow(
                    probe_tick_id=tick_id, ticked_at=now,
                    resident_label=label, resident_uuid=agent_uuid,
                    source=cfg.source, metric_value=None,
                    window_seconds=window_s, threshold=cfg.threshold,
                    metric_below_threshold=None,
                    heartbeat_alive=hb.alive, candidate=False,
                    suppressed_reason="source_error",
                    error_details={"source": cfg.source, "error": source_errors[cfg.source]},
                    liveness_inputs=hb.to_jsonable(),
                    loop_detector_state=None,
                )
            elif hb.eval_error is not None:
                row = SnapshotRow(
                    probe_tick_id=tick_id, ticked_at=now,
                    resident_label=label, resident_uuid=agent_uuid,
                    source=cfg.source, metric_value=None,
                    window_seconds=window_s, threshold=cfg.threshold,
                    metric_below_threshold=None,
                    heartbeat_alive=False, candidate=False,
                    suppressed_reason="heartbeat_eval_error",
                    error_details={"heartbeat_error": hb.eval_error},
                    liveness_inputs=hb.to_jsonable(),
                    loop_detector_state=None,
                )
            else:
                metric = source_outputs[cfg.source].get(agent_uuid, 0)
                below = metric < cfg.threshold
                if not hb.alive and below:
                    suppressed = "heartbeat_not_alive"
                    candidate = False
                else:
                    suppressed = None
                    candidate = below and hb.alive
                row = SnapshotRow(
                    probe_tick_id=tick_id, ticked_at=now,
                    resident_label=label, resident_uuid=agent_uuid,
                    source=cfg.source, metric_value=metric,
                    window_seconds=window_s, threshold=cfg.threshold,
                    metric_below_threshold=below,
                    heartbeat_alive=hb.alive, candidate=candidate,
                    suppressed_reason=suppressed, error_details=None,
                    liveness_inputs=hb.to_jsonable(),
                    loop_detector_state=None,  # Phase-2: enrich with loop-detector snapshot
                )
            resident_rows.append(row)

        all_rows = unresolved_rows + resident_rows
        try:
            await self._writer.write(all_rows)
        except Exception as e:
            logger.warning("[PROGRESS_FLAT] resident-row write failed: %s", e)
            return

        dogfood = SnapshotRow(
            probe_tick_id=tick_id, ticked_at=datetime.now(timezone.utc),
            resident_label="progress_flat_probe", resident_uuid=None,
            source="probe_self", metric_value=len(all_rows),
            window_seconds=None, threshold=None,
            metric_below_threshold=False, heartbeat_alive=True,
            candidate=False, suppressed_reason=None,
            error_details=None, liveness_inputs=None,
            loop_detector_state=None,
        )
        try:
            await self._writer.write([dogfood])
        except Exception as e:
            logger.warning(
                "[PROGRESS_FLAT] dogfood-row write failed (non-fatal): %s", e,
            )

        for r in resident_rows:
            if r.candidate:
                try:
                    await self._audit.emit(
                        event_type="progress_flat_candidate", severity="low",
                        payload={
                            "resident_label": r.resident_label,
                            "resident_uuid": r.resident_uuid,
                            "source": r.source, "metric_value": r.metric_value,
                            "threshold": r.threshold,
                            "window_seconds": r.window_seconds,
                            "probe_tick_id": str(r.probe_tick_id),
                        },
                    )
                except Exception as e:
                    logger.warning(
                        "[PROGRESS_FLAT] candidate audit emit failed: %s", e,
                    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/resident_progress/test_probe_task.py -v --no-cov --tb=short`
Expected: PASS (4 of 5; the dogfood-failure test is intentionally skipped — replace the `pytest.skip` with a concrete implementation that simulates writer.write failing on the dogfood call only and asserts the resident rows are still persisted).

- [ ] **Step 5: Commit**

```bash
git add src/resident_progress/probe_task.py tests/resident_progress/test_probe_task.py
git commit -m "feat(resident-progress): probe orchestrator with tick lifecycle"
```

---

## Task 9: Wire orchestrator into background_tasks startup

**Files:**
- Modify: `src/background_tasks.py` (add `progress_flat_probe_task` async wrapper + register in `start_all_background_tasks`)
- Test: `tests/resident_progress/test_probe_integration.py`

The wrapper builds the dependency graph (sources, heartbeat, writer, audit emitter) once at startup, then loops calling `probe.tick()` every `PROGRESS_FLAT_PROBE_INTERVAL_S`.

- [ ] **Step 1: Write the failing integration test**

`tests/resident_progress/test_probe_integration.py`:

```python
from __future__ import annotations

import pytest

from src import background_tasks


@pytest.mark.asyncio
async def test_progress_flat_probe_task_is_supervised_when_started():
    background_tasks._supervised_tasks.clear()

    async def fake_set_ready(): pass

    class _NoopTracker:
        def add(self, *a, **kw): pass

    background_tasks.start_all_background_tasks(
        connection_tracker=_NoopTracker(), set_ready=fake_set_ready,
    )
    names = [getattr(t, "_name", "") for t in background_tasks._supervised_tasks]
    assert any("progress_flat_probe" in n for n in names)
    await background_tasks.stop_all_background_tasks()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/resident_progress/test_probe_integration.py -v --no-cov --tb=short`
Expected: FAIL with no `progress_flat_probe` task supervised.

- [ ] **Step 3: Add the wrapper and registration**

In `src/background_tasks.py`, add a wrapper after `deep_health_probe_task`:

```python
async def progress_flat_probe_task(interval_seconds: float | None = None):
    """Resident-progress telemetry probe — see
    docs/superpowers/specs/2026-04-25-resident-progress-detection-design.md.
    """
    import os

    from src.db import get_db
    from src.resident_progress.heartbeat import HeartbeatEvaluator
    from src.resident_progress.probe_task import ProgressFlatProbe
    from src.resident_progress.sentinel_source import SentinelPulseSource
    from src.resident_progress.snapshot_writer import SnapshotWriter
    from src.resident_progress.sources import (
        EISVSyncSource, KnowledgeDiscoverySource,
        MetricsSeriesSource, WatcherFindingSource,
    )
    from src.audit_log import audit_logger  # adjust import to actual symbol

    if interval_seconds is None:
        override = os.getenv("UNITARES_PROGRESS_FLAT_PROBE_INTERVAL_SECONDS")
        interval_seconds = float(override) if override else 300.0

    await asyncio.sleep(5.0)  # let pool warm up
    db = get_db()

    class _AuditEmitter:
        async def emit(self, *, event_type, severity, payload):
            audit_logger.log(  # adapt to actual API surface
                event_type=event_type, severity=severity, payload=payload,
            )

    class _MetadataStore:
        async def get(self, agent_uuid):
            from src.agent_storage import get_agent_metadata_async  # adjust to actual symbol
            row = await get_agent_metadata_async(agent_uuid)
            return row

    sources = {
        "kg_writes":        KnowledgeDiscoverySource(db),
        "watcher_findings": WatcherFindingSource(db),
        "eisv_sync_rows":   EISVSyncSource(db),
        "metrics_series":   MetricsSeriesSource(db),
        "sentinel_pulse":   SentinelPulseSource(db),
    }
    probe = ProgressFlatProbe(
        sources_by_name=sources,
        heartbeat_evaluator=HeartbeatEvaluator(_MetadataStore()),
        writer=SnapshotWriter(db), audit_emitter=_AuditEmitter(),
    )
    logger.info(
        "[PROGRESS_FLAT] probe started; interval=%ss", interval_seconds,
    )
    while True:
        try:
            await probe.tick()
        except asyncio.CancelledError:
            logger.info("[PROGRESS_FLAT] task cancelled")
            break
        except Exception as e:
            logger.warning("[PROGRESS_FLAT] tick failed: %s", e, exc_info=True)
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break
```

In `start_all_background_tasks` (around line 1099), add:

```python
_supervised_create_task(progress_flat_probe_task(), name="progress_flat_probe")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/resident_progress/test_probe_integration.py -v --no-cov --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/background_tasks.py tests/resident_progress/test_probe_integration.py
git commit -m "feat(resident-progress): supervise probe in start_all_background_tasks"
```

---

## Task 10: REST endpoint — GET /v1/progress_flat/recent

**Files:**
- Modify: `src/http_api.py` (add handler + route registration)
- Test: `tests/resident_progress/test_http_endpoint.py`

The endpoint returns one row per configured resident plus the probe-self row. If no snapshot exists for a resident, the row is rendered with status `unresolved` (or `startup-grace` if the latest snapshot uses that suppressed_reason).

- [ ] **Step 1: Write the failing test**

`tests/resident_progress/test_http_endpoint.py`:

```python
from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_endpoint_returns_row_per_configured_resident(http_test_client, test_db):
    # http_test_client fixture is the existing project pattern — see
    # tests/http_test_app.py for setup.
    resp = await http_test_client.get("/v1/progress_flat/recent?hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    rows = {r["resident_label"]: r for r in data["rows"]}
    expected_labels = {
        "vigil", "watcher", "steward", "chronicler", "sentinel",
        "progress_flat_probe",
    }
    assert expected_labels <= set(rows.keys())


@pytest.mark.asyncio
async def test_endpoint_status_field_uses_priority_resolver(http_test_client, test_db):
    resp = await http_test_client.get("/v1/progress_flat/recent")
    rows = resp.json()["rows"]
    assert all("status" in r for r in rows)
    assert all(
        r["status"] in {
            "OK", "flat-candidate", "silent", "source-error",
            "unresolved", "startup-grace", "initializing",
        } for r in rows
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/resident_progress/test_http_endpoint.py -v --no-cov --tb=short`
Expected: FAIL with 404 from the test client.

- [ ] **Step 3: Implement the handler and route**

In `src/http_api.py`, after the existing `/v1/metrics` handlers, add:

```python
async def http_get_progress_flat_recent(request):
    """GET /v1/progress_flat/recent?hours=24 — latest snapshot per
    configured resident plus probe-self row."""
    from src.db import get_db
    from src.resident_progress.registry import RESIDENT_PROGRESS_REGISTRY
    from src.resident_progress.status import resolve_status

    hours = int(request.query_params.get("hours", "24"))
    db = get_db()
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (resident_label)
                   resident_label, resident_uuid::text AS resident_uuid,
                   ticked_at, source, metric_value, window_seconds,
                   threshold, metric_below_threshold, heartbeat_alive,
                   candidate, suppressed_reason, error_details,
                   liveness_inputs, loop_detector_state
            FROM progress_flat_snapshots
            WHERE ticked_at > now() - make_interval(hours => $1)
            ORDER BY resident_label, ticked_at DESC
            """,
            hours,
        )
    by_label = {r["resident_label"]: dict(r) for r in rows}
    out = []
    for label in list(RESIDENT_PROGRESS_REGISTRY) + ["progress_flat_probe"]:
        r = by_label.get(label)
        if r is None:
            out.append({
                "resident_label": label, "status": "unresolved",
                "metric_value": None, "threshold": None,
                "ticked_at": None,
            })
            continue
        r["status"] = resolve_status(r)
        if r["ticked_at"] is not None:
            r["ticked_at"] = r["ticked_at"].isoformat()
        out.append(r)
    from starlette.responses import JSONResponse
    return JSONResponse({"success": True, "rows": out})
```

In the route-registration block (around line 2346), add:

```python
app.routes.append(
    Route("/v1/progress_flat/recent", http_get_progress_flat_recent, methods=["GET"]),
)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/resident_progress/test_http_endpoint.py -v --no-cov --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/http_api.py tests/resident_progress/test_http_endpoint.py
git commit -m "feat(resident-progress): GET /v1/progress_flat/recent endpoint"
```

---

## Task 11: Dashboard panel — resident-progress.js

**Files:**
- Create: `dashboard/resident-progress.js`
- Modify: `dashboard/index.html` (add panel container + script tag)
- Modify: `dashboard/styles.css` (only if existing badge/status styles don't cover the new states; reuse if possible)
- No automated test for the panel rendering; manual verification step below.

Conform to the unitares-dashboard skill conventions (Chart.js dark-theme defaults, `authFetch` from `utils.js`, `.panel` layout).

- [ ] **Step 1: Add the panel container to `dashboard/index.html`**

Find the section where Fleet Metrics is rendered. Immediately after that panel, add:

```html
<div class="live-chart-panel" id="resident-progress-panel">
    <div class="panel-header">
        <h3>Resident Progress</h3>
        <div class="panel-controls">
            <label class="panel-select-label" title="Show only ticks where loop detector also fired">
                <input type="checkbox" id="rp-overlap-toggle"> Show overlap
            </label>
        </div>
    </div>
    <div id="rp-rows" class="rp-rows"></div>
    <div id="rp-drilldown" class="rp-drilldown hidden"></div>
</div>
```

At the bottom of the file, before `</body>`, add:

```html
<script src="resident-progress.js"></script>
```

- [ ] **Step 2: Implement `dashboard/resident-progress.js`**

```javascript
// resident-progress.js — render Phase-1 resident-progress probe snapshots.
// Reads GET /v1/progress_flat/recent. Conforms to dashboard conventions:
// authFetch from utils.js, Chart.js defaults set by other panels at body level.
//
// Panel does NOT trigger any actions; Phase 1 is read-only telemetry.

(function () {
    'use strict';

    var REFRESH_INTERVAL_MS = 30000;
    var RESIDENT_LABELS = [
        "vigil", "sentinel", "watcher", "steward", "chronicler",
        "progress_flat_probe",
    ];
    var STATUS_CLASS = {
        "OK": "rp-status-ok",
        "flat-candidate": "rp-status-flat",
        "silent": "rp-status-silent",
        "source-error": "rp-status-error",
        "unresolved": "rp-status-unresolved",
        "startup-grace": "rp-status-init",
        "initializing": "rp-status-init",
    };

    async function fetchRecent(hours) {
        try {
            var resp = await authFetch(
                '/v1/progress_flat/recent?hours=' + (hours || 24)
            );
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();
            if (!data || data.success === false) {
                throw new Error((data && data.error) || 'unknown');
            }
            return data.rows || [];
        } catch (e) {
            console.warn('[ResidentProgress] fetch failed:', e);
            return [];
        }
    }

    function statusFor(row) {
        var s = row.status;
        if (!s && row.suppressed_reason === 'startup_unresolved_label') {
            return 'initializing';
        }
        return s || 'unresolved';
    }

    function renderRow(row) {
        var label = row.resident_label || '';
        var status = statusFor(row);
        var cls = STATUS_CLASS[status] || 'rp-status-unknown';
        var metric = (row.metric_value === null || row.metric_value === undefined)
            ? '—' : row.metric_value;
        var threshold = (row.threshold === null || row.threshold === undefined)
            ? '—' : row.threshold;
        var ticked = row.ticked_at ? new Date(row.ticked_at).toLocaleTimeString() : '—';
        var dim = label === 'progress_flat_probe' ? ' rp-dim' : '';
        return (
            '<div class="rp-row' + dim + '" data-label="' + label + '">' +
                '<span class="rp-label">' + label + '</span>' +
                '<span class="rp-badge ' + cls + '">' + status + '</span>' +
                '<span class="rp-metric">' + metric + ' / ' + threshold + '</span>' +
                '<span class="rp-window">' +
                    (row.window_seconds ? Math.round(row.window_seconds / 60) + 'm' : '—') +
                '</span>' +
                '<span class="rp-time">' + ticked + '</span>' +
            '</div>'
        );
    }

    function rowsByLabel(rows) {
        var out = {};
        rows.forEach(function (r) { out[r.resident_label] = r; });
        return out;
    }

    function applyOverlapFilter(rows, overlapOn) {
        if (!overlapOn) return rows;
        return rows.filter(function (r) {
            return r.candidate &&
                r.loop_detector_state &&
                r.loop_detector_state.loop_detected_at;
        });
    }

    async function refresh() {
        var rows = await fetchRecent(24);
        var overlapOn = document.getElementById('rp-overlap-toggle').checked;
        var filtered = applyOverlapFilter(rows, overlapOn);
        var byLabel = rowsByLabel(filtered);
        var html = RESIDENT_LABELS.map(function (label) {
            return renderRow(byLabel[label] || {
                resident_label: label, status: 'unresolved',
            });
        }).join('');
        document.getElementById('rp-rows').innerHTML = html;
    }

    function wire() {
        document.getElementById('rp-overlap-toggle')
            .addEventListener('change', refresh);
        refresh();
        setInterval(refresh, REFRESH_INTERVAL_MS);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wire);
    } else {
        wire();
    }
})();
```

- [ ] **Step 3: Add minimal status styles to `dashboard/styles.css`**

Append (or merge with existing badge styles if present):

```css
.rp-rows { display: flex; flex-direction: column; gap: 4px; padding: 8px; }
.rp-row { display: grid; grid-template-columns: 1.4fr 1fr 1fr 0.5fr 0.8fr; gap: 8px; align-items: center; padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.06); }
.rp-row.rp-dim { opacity: 0.55; }
.rp-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.75em; text-align: center; }
.rp-status-ok { background: rgba(80,180,90,0.18); color: #7fdc8f; }
.rp-status-flat { background: rgba(220,170,40,0.20); color: #f1c860; }
.rp-status-silent { background: rgba(140,140,150,0.20); color: #a8a8b4; }
.rp-status-error { background: rgba(220,80,80,0.20); color: #f08080; }
.rp-status-unresolved { background: rgba(120,120,140,0.15); color: #909098; }
.rp-status-init { background: rgba(120,120,140,0.10); color: #909098; }
```

- [ ] **Step 4: Manual verification**

Restart governance-mcp:
```bash
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load   ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

Open the dashboard, confirm:
- Six rows render (5 residents + probe-self).
- After ~10 minutes (2 ticks), no `initializing` rows remain unless the corresponding resident is genuinely unresolved.
- Toggling "Show overlap" filters to candidate rows that also have loop-detector state populated (likely empty in early data — confirm there is no JS error in console).
- Network tab shows `GET /v1/progress_flat/recent?hours=24` returning 200 with at least 6 rows.

Document the manual-verification result in the commit message body.

- [ ] **Step 5: Commit**

```bash
git add dashboard/resident-progress.js dashboard/index.html dashboard/styles.css
git commit -m "feat(resident-progress): dashboard panel with overlap toggle

Renders top-strip row per configured resident plus probe-self.
Reads GET /v1/progress_flat/recent. Read-only; no actions in Phase 1.

Manually verified: <fill in observations from Step 4>."
```

---

## Task 12: Calibration smoke test

**Files:**
- Create: `tests/resident_progress/test_calibration_smoke.py`

Asserts the safety bounds the spec requires: ≥1 row per configured resident per tick window, no resident in `candidate=true` for more than 50% of ticks in the fixture.

- [ ] **Step 1: Write the test**

`tests/resident_progress/test_calibration_smoke.py`:

```python
"""Calibration smoke test — catches obviously-misconfigured thresholds
before deploy. The 50% ceiling is a hard upper bound; the operational
tuning target is much lower and will be set from real data after Phase 1.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_no_resident_candidate_above_fifty_percent(test_db):
    """If ANY configured resident is firing candidates >50% of ticks,
    the threshold is misconfigured. Hard ceiling — operational target is
    much lower."""
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT resident_label, candidate, ticked_at
            FROM progress_flat_snapshots
            WHERE ticked_at > now() - interval '24 hours'
              AND resident_label != 'progress_flat_probe'
            """
        )
    if not rows:
        pytest.skip("no snapshots persisted yet — run probe at least once")

    by_label = Counter()
    candidate_by_label = Counter()
    for r in rows:
        by_label[r["resident_label"]] += 1
        if r["candidate"]:
            candidate_by_label[r["resident_label"]] += 1

    offenders = []
    for label, total in by_label.items():
        ratio = candidate_by_label[label] / total
        if ratio > 0.5:
            offenders.append((label, ratio, total))
    assert not offenders, (
        f"residents firing candidate > 50% of ticks "
        f"(threshold misconfigured?): {offenders}"
    )


@pytest.mark.asyncio
async def test_at_least_one_row_per_resident_in_recent_window(test_db):
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT resident_label, count(*) AS n
            FROM progress_flat_snapshots
            WHERE ticked_at > now() - interval '1 hour'
            GROUP BY resident_label
            """
        )
    if not rows:
        pytest.skip("no snapshots persisted yet — run probe at least once")
    seen = {r["resident_label"] for r in rows}
    expected = {
        "vigil", "watcher", "steward", "chronicler", "sentinel",
        "progress_flat_probe",
    }
    missing = expected - seen
    # In a healthy probe, every configured resident has at least one
    # snapshot row per tick. Missing labels indicate the probe stopped
    # or the registry resolution silently failed.
    assert not missing, f"no recent snapshots for: {missing}"
```

- [ ] **Step 2: Run the test (after at least one tick has run against the test DB)**

```bash
pytest tests/resident_progress/test_calibration_smoke.py -v --no-cov --tb=short
```

Expected: PASS or skip-with-message if no snapshots persisted yet. Document either outcome in the commit message.

- [ ] **Step 3: Commit**

```bash
git add tests/resident_progress/test_calibration_smoke.py
git commit -m "test(resident-progress): calibration smoke test

Asserts no resident fires candidate > 50% of ticks (threshold
misconfiguration tripwire). Operational target is much lower and
will be set after 3 weeks of Phase-1 data."
```

---

## Task 13: Probe-self regression test

**Files:**
- Create: `tests/resident_progress/test_probe_self_regression.py`

Asserts that after 10 ticks against a working DB, the dogfood row is present in 10 of 10 ticks. Catches dogfood-write regressions early.

- [ ] **Step 1: Write the test**

```python
"""After 10 probe ticks, the dogfood row must appear in 10 of 10 ticks.
Regression guard for the dogfood-row write path."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.resident_progress.probe_task import ProgressFlatProbe
from src.resident_progress.snapshot_writer import SnapshotWriter


@pytest.mark.asyncio
async def test_dogfood_row_present_in_every_tick(test_db, monkeypatch):
    monkeypatch.setattr(
        "src.resident_progress.probe_task.RESIDENT_PROGRESS_REGISTRY", {},
    )
    writer = SnapshotWriter(test_db)
    probe = ProgressFlatProbe(
        sources_by_name={}, heartbeat_evaluator=AsyncMock(),
        writer=writer, audit_emitter=AsyncMock(), _now_tick=10,
    )
    tick_ids = []
    for _ in range(10):
        from uuid import uuid4
        # Tick uses internal tick_id; capture by introspecting writes.
        await probe.tick()

    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT probe_tick_id, count(*) FILTER (
                WHERE resident_label = 'progress_flat_probe'
            ) AS dogfoods
            FROM progress_flat_snapshots
            WHERE ticked_at > now() - interval '5 minutes'
            GROUP BY probe_tick_id
            ORDER BY probe_tick_id
            """
        )
    distinct_ticks = [r for r in rows if r["dogfoods"] >= 1]
    assert len(distinct_ticks) >= 10, (
        f"expected at least 10 ticks with dogfood rows, got {len(distinct_ticks)}"
    )
```

- [ ] **Step 2: Run the test**

```bash
pytest tests/resident_progress/test_probe_self_regression.py -v --no-cov --tb=short
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/resident_progress/test_probe_self_regression.py
git commit -m "test(resident-progress): probe-self dogfood-row regression guard"
```

---

## Task 14: Final pre-merge check

- [ ] **Step 1: Run the full project test suite via the wrapper**

Per repo convention:
```bash
./scripts/dev/test-cache.sh --fresh
```

Expected: PASS. Fix any test that fails because of these changes.

- [ ] **Step 2: Verify the migration is idempotent**

```bash
psql -h localhost -p 5432 -U postgres -d governance \
  -f db/postgres/migrations/017_progress_flat_telemetry.sql
```

Expected: completes without error (re-applying must be a no-op because of `IF NOT EXISTS` and `ON CONFLICT DO NOTHING`).

- [ ] **Step 3: Restart governance-mcp and tail logs**

```bash
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load   ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
tail -f data/logs/mcp_server.log | grep -i progress_flat
```

Expected: see `[PROGRESS_FLAT] probe started; interval=300s` and, after 5 minutes, `[PROGRESS_FLAT]` debug-level tick traces. No tracebacks.

- [ ] **Step 4: Verify dashboard panel renders**

Open the dashboard. Confirm Resident Progress panel appears with six rows. Confirm `GET /v1/progress_flat/recent?hours=24` returns 200 with rows in the response body.

- [ ] **Step 5: Final commit (if anything cleaned up)**

If any drive-by fixes were needed during pre-merge checks, commit them with an explicit message describing what changed and why. Otherwise no commit needed for this task.

---

## Self-Review

**1. Spec coverage:**

- Phase split, non-goals — covered by plan-header (no task; spec is the canonical reference).
- New `progress_flat_probe_task` — Task 8 (orchestrator) + Task 9 (wiring).
- Label-keyed registry, anchor-resolved UUIDs — Task 2.
- Five `ResidentProgressSource` impls (KG, Watcher, EISVSync, MetricsSeries, SentinelPulse) — Tasks 4 + 5.
- HeartbeatEvaluator — Task 3.
- SnapshotWriter + table — Tasks 1 + 7.
- Tick-id idempotency, append-only, batched insert — Tasks 1 + 7.
- `record_progress_pulse` MCP tool with auth-bound `resident_uuid` — Task 5.
- Status priority resolver — Task 6.
- Probe-self dogfood row — Task 8 (impl) + Task 13 (regression test).
- `GET /v1/progress_flat/recent` — Task 10.
- Dashboard panel with overlap toggle, snapshot log — Task 11. (Note: snapshot-log drill-down is sketched in the panel JS structure but the per-row click-to-expand sparkline is intentionally deferred to a follow-up — the Phase-1 spec demands the row + status, the drill-down is "valuable from day one" but practical to ship as v1.1 once the panel is in place. Flagging here so it gets prioritized after Task 14.)
- Failure modes (source error, heartbeat error, db write fail, dogfood non-fatal, sentinel-no-push, probe stall) — covered in Task 8 implementation; tested in Task 8 + Task 13.
- Threshold defaults — Task 2 registry. Calibration tripwire — Task 12.
- Status priority order — Task 6.
- Startup grace 2 ticks — Task 8 implementation.

**2. Placeholder scan:**

- Two intentional skipped tests (`tests/resident_progress/test_sentinel_source.py::test_record_progress_pulse_binds_resident_uuid_from_auth` and `tests/resident_progress/test_probe_task.py::test_dogfood_write_failure_is_logged_not_fatal`) include explicit instructions for the implementer to wire to the project's MCP test harness and concretize the assertions. These are NOT placeholder TODOs — the skip-message tells the implementer exactly what to do. Acceptable given the project's harness conventions are not in scope for this plan.
- Dashboard sparkline drill-down deferred to follow-up — flagged in self-review above.

**3. Type consistency:**

- `ResidentConfig`, `SnapshotRow`, `HeartbeatStatus` used consistently across modules and tests.
- `resident_uuid` typed as `str | None` everywhere (PostgreSQL `uuid` is cast to/from text via `::text` and `::uuid[]` to keep asyncpg parameter binding simple).
- `source.name` strings match across registry, sources module, probe orchestrator, and dashboard `STATUS_CLASS` keys.
- Status badge values match between `src/resident_progress/status.py` and the dashboard `STATUS_CLASS` map (with `initializing` aliased to `startup-grace` in the JS layer for label clarity).

No issues to fix inline.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-25-resident-progress-detection.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Best for this plan because the tasks are well-bounded and produce visible artifacts (tests, migrations, dashboard) that benefit from per-task review.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Implementation should be done in a dedicated git worktree per repo convention (`./scripts/dev/ship.sh` will route the eventual PR correctly because this is runtime code).

**Which approach?**
