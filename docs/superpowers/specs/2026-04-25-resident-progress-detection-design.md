# Resident Progress Detection — Phase 1 Design

**Date:** 2026-04-25
**Status:** Approved — ready for implementation plan
**Scope:** UNITARES governance MCP server (`/Users/cirwel/projects/unitares`)

## Problem

The dashboard "unstick" button only reaches a narrow failure mode (loop-detected agents in cooldown). It clears `loop_cooldown_until` and `loop_detected_at`; for residents that are heartbeat-alive but not advancing measurable work, the button has nothing to act on because there is no signal that the resident is stalled.

"Stuck" is now mostly an environmental/structural condition rather than a cognitive one. The dominant resident failure mode is **alive but not advancing** — the loop body runs, the heartbeat is green, and yet no work is being completed. Heartbeat liveness alone does not detect this; the existing loop detector does not detect this either, because the resident is not repeating itself, it is silently producing no artifacts.

This design closes that gap with a telemetry-first detector that is explicitly **not** coupled to verdict, pause, or cooldown machinery. Phase 1 collects evidence; Phase 2 (out of scope here) will design a unified stuck classifier on top of that evidence.

## Non-goals

- Modifying the existing dashboard unstick button.
- Modifying the existing loop detector.
- Wiring progress-flat into the EISV verdict path, risk score, or CIRS coupling.
- Detecting stuck states in ad-hoc agents (Claude Code sessions, Codex dispatch jobs). Phase 1 covers residents only — long-lived processes whose absence-of-work is a meaningful signal over multi-tick windows.
- Auto-pausing or auto-restarting residents based on the new signal.
- Building a unified stuck-classifier (Phase 2).

## Phase split

**Phase 1 (this design):** Telemetry-only detector. Emits `progress_flat_candidate` events at low severity. Persists per-tick snapshots. Surfaces on a new dashboard panel. No governance integration. Records overlap with the existing loop detector for later analysis.

**Phase 2 (deferred, post-3-weeks of data):** Evaluate overlap, false positives, and operator actions. If warranted, promote to a unified `stuck_state` classifier with `stuck_reason`, and route the existing unstick button through that classifier. Phase 2 is the only phase in which progress-flat may produce a `guide` verdict or risk adjustment.

## Architecture

A new background task `progress_flat_probe_task` lives in `src/background_tasks.py`, scheduled by the existing background-task registry (same pattern as `deep_health_probe_task`). On each tick it:

1. Resolves the label-keyed resident registry against live agent metadata to get the current `resident_uuid` per `resident_label`.
2. Reads per-resident progress metrics from canonical artifact tables (Vigil, Watcher, Steward, Chronicler) and from a small push-only `resident_progress_pulse` table (Sentinel).
3. Evaluates each resident against a per-resident `(metric, window, threshold)` config triple.
4. Persists one snapshot row per configured resident plus one dogfood row.
5. For rows where `candidate=true`, emits a `progress_flat_candidate` event to the audit log at severity `low`.

The probe never mutates `agent_metadata.status`, never touches `loop_cooldown_until` or `loop_detected_at`, never enters the verdict path. It is pure side-channel telemetry.

## Components

### 1. `progress_flat_probe_task` (orchestrator)

Location: `src/background_tasks.py`.

Owns scheduling, registry resolution, source dispatch, heartbeat dispatch, snapshot composition, batched insert, candidate event emission, and the dogfood row. Knows nothing about specific residents — all resident-specific logic lives in registry config and source implementations.

Default tick interval: `PROGRESS_FLAT_PROBE_INTERVAL_S = 300` (5 minutes). Configurable via `governance_config.py`.

### 2. `ResidentProgressSource` (interface)

Location: new module `src/resident_progress/sources.py`.

```python
class ResidentProgressSource(Protocol):
    name: str  # "kg_writes" | "watcher_findings" | "eisv_sync_rows" | "metrics_series" | "sentinel_pulse"
    async def fetch(
        self,
        resident_uuids: list[UUID],
        window: timedelta,
    ) -> dict[UUID, int]: ...
```

Five implementations: `KGWriteSource`, `WatcherFindingSource`, `EISVSyncSource`, `MetricsSeriesSource`, `SentinelPulseSource`.

Each implementation issues exactly one batched query covering all relevant residents in the window — no N×M fanout. The orchestrator groups configured pairs by `(source_name, window)` and calls each group once. Sources run in parallel via `asyncio.gather(..., return_exceptions=True)`.

### 3. `ResidentRegistry` (config)

Location: new module `src/resident_progress/registry.py`.

Label-keyed config:

```python
RESIDENT_PROGRESS_REGISTRY: dict[str, ResidentConfig] = {
    "vigil":      ResidentConfig(source="kg_writes",         metric="rows_written",   window=timedelta(minutes=60), threshold=1),
    "watcher":    ResidentConfig(source="watcher_findings",  metric="rows_any",       window=timedelta(hours=6),    threshold=1),
    "steward":    ResidentConfig(source="eisv_sync_rows",    metric="rows_written",   window=timedelta(minutes=30), threshold=1),
    "chronicler": ResidentConfig(source="metrics_series",    metric="rows_written",   window=timedelta(hours=26),   threshold=1),
    "sentinel":   ResidentConfig(source="sentinel_pulse",    metric="latest_count",   window=timedelta(minutes=30), threshold=1),
}
```

Resident UUIDs are **not** stored here. The orchestrator resolves `resident_label → resident_uuid` at tick time from active agent metadata (substrate-anchored UUIDs for the residents). This avoids stale config when a resident re-onboards, the identity ontology shifts, or a UUID rotates. Snapshot rows persist both `resident_label` and the resolved `resident_uuid` for forensic clarity.

Threshold values live in code (not DB) for Phase 1 so changes are git-tracked. Three weeks of snapshot data will inform Phase 2 tuning.

### 4. `HeartbeatEvaluator`

Location: new module `src/resident_progress/heartbeat.py`.

Thin wrapper around the existing silence/cadence semantics. Reuses, does not reinvent.

```python
@dataclass
class HeartbeatStatus:
    alive: bool
    last_update: datetime | None
    expected_cadence_s: int | None
    in_critical_silence: bool
    eval_error: str | None  # populated on evaluator failure
```

Method: `evaluate(resident_uuid: UUID) -> HeartbeatStatus`. The full struct is persisted in the snapshot row's `liveness_inputs` JSONB column.

### 5. `SnapshotWriter` and `progress_flat_snapshots` table

New table:

```sql
CREATE TABLE progress_flat_snapshots (
    id                     bigserial PRIMARY KEY,
    probe_tick_id          uuid NOT NULL,
    ticked_at              timestamptz NOT NULL,
    resident_label         text NOT NULL,
    resident_uuid          uuid,                  -- null for probe_self and unresolved labels
    source                 text NOT NULL,         -- source.name | "probe_self"
    metric_value           integer,               -- null on source error or unresolved
    window_seconds         integer,
    threshold              integer,
    metric_below_threshold boolean,
    heartbeat_alive        boolean,
    candidate              boolean NOT NULL DEFAULT false,
    suppressed_reason      text,                  -- "heartbeat_not_alive" | "unresolved_label" | "startup_unresolved_label" | "source_error" | null
    error_details          jsonb,                 -- source/heartbeat error info, semantically separate from liveness
    liveness_inputs        jsonb,                 -- HeartbeatStatus serialized; semantically clean
    loop_detector_state    jsonb                  -- {loop_detected_at, loop_cooldown_until} for Phase-2 overlap analysis
);

CREATE INDEX idx_pfs_ticked_at      ON progress_flat_snapshots (ticked_at DESC);
CREATE INDEX idx_pfs_label_ticked   ON progress_flat_snapshots (resident_label, ticked_at DESC);
CREATE INDEX idx_pfs_tick_id        ON progress_flat_snapshots (probe_tick_id);
```

The schema separates `error_details` from `liveness_inputs` so liveness semantics stay clean.

The orchestrator writes snapshot rows in one batched `INSERT ... VALUES (...), (...), ...`. Snapshot table is append-only; `probe_tick_id` ensures tick-level idempotency on retry. Table is append-only; no updates, no deletes from the probe path.

### 6. Sentinel push API: `record_progress_pulse`

New MCP tool:

```python
@mcp_tool("record_progress_pulse")
async def record_progress_pulse(arguments: dict) -> ...:
    # resident_uuid is always bound from the authenticated current agent.
    # If `resident_uuid` is present in arguments, it must equal the authenticated
    # agent's UUID; mismatched values are rejected with an auth error.
```

Schema:

```sql
CREATE TABLE resident_progress_pulse (
    id            bigserial PRIMARY KEY,
    resident_uuid uuid NOT NULL,
    metric_name   text NOT NULL,
    value         integer NOT NULL,
    recorded_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_rpp_uuid_recorded ON resident_progress_pulse (resident_uuid, recorded_at DESC);
```

Auth-bound `resident_uuid` prevents Sentinel (or any other agent) from accidentally or intentionally writing another resident's pulse. `SentinelPulseSource.fetch` reads the latest row per resident in the window.

### 7. Candidate emission

When `candidate=true`, the orchestrator calls a single hook `emit_progress_flat_candidate(snapshot_row)`. Phase 1 implementation: write to the existing audit log with `severity="low"`, `event_type="progress_flat_candidate"`. **Does not** call into governance verdict or risk paths. The "may at most produce guide" governance integration is the Phase-2 ceiling, not Phase-1 behavior.

## Data flow — tick lifecycle

Every `PROGRESS_FLAT_PROBE_INTERVAL_S`:

1. Orchestrator generates `probe_tick_id`.
2. **Resolve registry** against live agent metadata. For labels that resolve to a live UUID, proceed. For labels that don't:
   - During the first 2 probe intervals after server start: write a row with `suppressed_reason="startup_unresolved_label"`.
   - After startup grace: write a row with `suppressed_reason="unresolved_label"`.
   - In both cases: `resident_uuid=null`, `metric_value=null`, `heartbeat_alive=false`, `candidate=false`. No event emission.
3. **Group** configured `(source_name, window)` pairs. For each group, call `source.fetch(resolved_uuids, window)` once. Sources run in parallel via `asyncio.gather(return_exceptions=True)`.
4. **Heartbeat** evaluation runs in parallel with sources where possible. Composes `HeartbeatStatus` per resident.
5. **Compose snapshot rows** per resident. `candidate = metric_below_threshold AND heartbeat_alive`. If suppressed, `candidate=false` and `suppressed_reason` is set.
6. **Batched insert** all rows in one statement.
7. **Emit candidate events** — one audit log row per `candidate=true` snapshot row.
8. **Write dogfood row** last, with `resident_label="progress_flat_probe"`, `source="probe_self"`, and `metric_value` set to the count of resident snapshot rows successfully written this tick (excluding the dogfood row itself). This is non-trivial work proof, not just "I ran." If the dogfood insert fails after resident rows succeed, log and continue — the missing probe-self row is itself the signal.

## Failure modes

- **Source query fails or times out.** Affected residents get a snapshot row with `metric_value=null`, `candidate=false`, `suppressed_reason="source_error"`, error info in `error_details`. Probe continues; one bad source does not poison the tick.
- **Heartbeat evaluator fails.** `heartbeat_alive=false`, `suppressed_reason="heartbeat_eval_error"`, error info in `error_details`. Conservative — won't fire a candidate without positive heartbeat evidence.
- **DB write fails (resident rows).** Probe logs and skips the tick. Next tick retries from scratch. Tick-id idempotency prevents partial double-emit.
- **Dogfood write fails (after resident rows succeed).** Logged, tick is not treated as failed. Missing probe-self rows surface as a probe-write-weakness signal.
- **Probe itself stalls.** Caught by the existing background-task supervisor (same machinery that watches `deep_health_probe_task`). The dogfood-row gap on the dashboard is meta-diagnostic.
- **Sentinel hasn't pushed in window.** `SentinelPulseSource` returns 0 for that resident. Combined with heartbeat-alive gate, this produces a valid candidate — Sentinel-alive-but-silent IS the failure mode we want to catch.
- **anyio-asyncio.** Probe is a background task, not an MCP handler — can `await asyncpg` directly. Standard pattern.

## Threshold defaults (Phase 1, conservative)

| Resident | Source | Window | Threshold | Notes |
|---|---|---|---|---|
| Vigil | kg_writes | 60min | < 1 | Cron 30min cadence; one tick of zero KG writes is not enough evidence. |
| Watcher | watcher_findings (any state transition: created, resolved, dismissed) | 6hr | < 1 | Bursty/event-driven cadence; narrow windows would false-positive. Acceptable detection latency for Phase 1. |
| Steward | eisv_sync_rows | 30min | < 1 | Pi→Mac sync every 5min; a 30min gap is meaningful. |
| Chronicler | metrics_series | 26hr | < 1 | Daily cadence; 26h tolerates clock skew and DST without false positives. |
| Sentinel | sentinel_pulse | 30min | < 1 | Continuous loop; a 30min push gap is meaningful. |

These are starting points expected to be wrong. The value of the snapshot table is being able to tune them against three weeks of data.

## Status priority (deterministic)

The dashboard status badge for any snapshot row is the first match in this order:

1. `source-error` (if `error_details` populated for source failure)
2. `unresolved` (if `suppressed_reason="unresolved_label"`)
3. `startup-grace` (if `suppressed_reason="startup_unresolved_label"`)
4. `silent` (if `suppressed_reason="heartbeat_not_alive"` or `heartbeat_eval_error`)
5. `flat-candidate` (if `candidate=true`)
6. `OK` (otherwise)

A row with both metric-flat and heartbeat-failed renders as `silent`, not `flat-candidate`.

## Dashboard surface

One new panel, `Resident Progress`. Lives next to the Fleet Metrics panel. Conforms to existing dashboard conventions (Chart.js dark theme defaults, `authFetch` helper, `.panel` layout, peer JS module under `dashboard/`).

**API endpoint:** `GET /v1/progress_flat/recent?hours=24` returns the latest snapshot per configured resident plus a short history. Returns stable rows for every configured resident even when the latest snapshot is unresolved, startup-suppressed, or source-errored.

**Top strip:** one row per configured resident (always exactly five rows in Phase 1 — Vigil/Sentinel/Watcher/Steward/Chronicler — plus a sixth row for `progress_flat_probe` self-row, visually de-emphasized). For startup-grace-suppressed residents, the top-strip row is shown as `initializing` (grey-faint) rather than hidden. The panel always shows the configured five plus probe self-row.

**Per-row fields:** label, current `metric_value`, threshold, window, status badge (using deterministic priority above), last-tick timestamp.

**Status badges:** `OK` (green), `flat-candidate` (amber), `silent` (grey), `source-error` (red), `unresolved` (grey-faint), `initializing` (grey-faint, startup-grace).

**Drill-down:** clicking a row opens a 24h sparkline of `metric_value` for that resident with the threshold line overlaid, plus a **snapshot log** filtered to that resident's snapshots. The log shows every tick (not just emitted candidate events), because Phase 1's valuable data is every tick. Startup-grace-suppressed snapshots are hidden from the log by default with a toggle to show.

**Overlap toggle:** a small "show overlap" toggle on the panel filters to ticks where `loop_detector_state.loop_detected_at` is non-null AND `candidate=true`. This is the single most important data point for Phase 2 design — how often the two detectors agree, disagree, and which leads which. Cheap to add, valuable from day one.

**No actions in Phase 1.** No "unstick" button on this panel. No links into the existing unstick path. The existing dashboard unstick button keeps doing exactly what it does today.

## Testing

**Unit tests:**

- Each `ResidentProgressSource.fetch` against a fixture DB: returns batched dict, handles empty windows, handles residents with zero rows, handles malformed rows.
- `HeartbeatEvaluator` against fixture metadata: alive / silent / critical-silence / missing-cadence cases.
- Orchestrator with mocked sources: candidate computation matrix (metric × heartbeat × threshold), suppressed-reason routing, batched insert composition, dogfood row emission, dogfood-write-failure non-fatal path.
- Registry resolution: resolved label, unresolved label, unresolved during startup grace.
- Status priority resolver: every input combination resolves deterministically per the spec.

**Integration tests:**

- Full probe tick against the test database with real-shape rows; assert correct snapshot rows persist, correct events emit, no governance verdict path called.
- Source-error isolation: one source raises, others succeed, only one row marked errored, tick completes.
- Tick-id idempotency: simulated mid-tick crash, retry produces no duplicates.
- anyio context: probe runs from background-task scheduler without deadlocking against MCP handlers running concurrently.
- `record_progress_pulse` auth binding: caller-passed `resident_uuid` is rejected; row is persisted with the authenticated agent's UUID only.

**Probe-self regression test:** assert that after 10 ticks with a working DB, the `progress_flat_probe` self-row is present in 10 out of 10 ticks (catches dogfood-write regressions early).

**API contract test:** `/v1/progress_flat/recent` endpoint returns stable rows for every configured resident even when the latest snapshot is unresolved, startup-suppressed, or source-errored. Frontend status mapping is deterministic per the priority order.

**Calibration smoke test:** runs against a recent production-shape snapshot fixture and asserts (a) ≥1 row per configured resident per tick window, (b) no resident is in `candidate=true` for more than 50% of ticks in the fixture (a hard ceiling to catch obviously-misconfigured thresholds before deploy; the operational tuning target is much lower and will be set from real data).

Tests fit the existing `tests/` layout and the `./scripts/dev/test-cache.sh` workflow.

## Phase 2 readiness criteria (informational, out of scope here)

After ~3 weeks of Phase-1 data, evaluate:

- Per-resident `candidate=true` rate per week.
- Overlap between `progress_flat_candidate` and `loop_detected_at` events: how often they coincide, lead, lag.
- Operator actions taken in response to dashboard signals.
- False positive rate, surfaced via operator dismissals or post-hoc verification.

If signal quality justifies promotion, Phase 2 designs:

- Unified `stuck_state` field with `stuck_reason` enum (`loop_detected`, `progress_flat`, `permission_blocked`, etc.).
- The classifier+router behind the unstick button: detect which class of stuck, dispatch the right intervention (operator ping, context summary injection, kill-and-respawn, etc.).
- Up to a `guide` verdict / informational risk adjustment on `progress_flat` candidates. No higher severity.
