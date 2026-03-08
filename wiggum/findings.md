# Wiggum Research Findings

This file tracks research iterations on the UNITARES governance-mcp codebase. Each iteration investigates one area and implements one improvement when a safe, impactful change is identified.

## Iteration 1: Consolidate health_check DB round-trips (4 → 1)

**File:** `src/db/postgres_backend.py`, lines 250-261
**Category:** Performance
**Date:** 2026-03-07

### Problem

The `PostgresBackend.health_check()` method made 4 sequential database round-trips using individual `fetchval` calls over a single connection. Each call was a separate network round-trip to the PostgreSQL server:

1. `SELECT 1` — basic connectivity test
2. `SELECT MAX(version) FROM core.schema_migrations` — retrieve the current schema migration version
3. `SELECT COUNT(*) FROM core.identities` — count total registered agent identities
4. `SELECT COUNT(*) FROM core.sessions WHERE is_active = TRUE` — count currently active sessions

The first query (`SELECT 1`) is entirely redundant because if any of the subsequent queries succeed, connectivity is already proven. The remaining three queries are independent scalar queries that can be combined into a single SQL statement using scalar subqueries, which PostgreSQL evaluates efficiently within a single round-trip.

While the health_check endpoint is not on the hottest path (it is not called on every `process_agent_update`), it is called by the admin health check handler, by the parallel health check drill tests, and by monitoring integrations. Reducing 4 round-trips to 1 provides a measurable latency improvement for these callers — roughly 3x fewer network round-trips per health check invocation.

### Investigation

Before making the change, the following investigation was performed:

- Verified that no unit tests mock the individual `fetchval` calls within `health_check`. The only tests that exercise this method are integration tests in `test_postgres_backend_integration.py` which use a live database and check the response shape (keys and value types), not the number of internal queries.
- Confirmed that the response dictionary shape is identical after the change — all keys (`status`, `backend`, `pool_size`, `pool_idle`, `pool_free`, `pool_max`, `schema_version`, `identity_count`, `active_session_count`, `age_available`, `age_graph`) remain unchanged.
- Verified that asyncpg's `fetchrow` method returns a `Record` object that supports dictionary-style key access, making the transition from `fetchval` to `fetchrow` straightforward.
- Checked that the scalar subquery pattern (`SELECT (SELECT ...) AS name, (SELECT ...) AS name2`) is standard PostgreSQL and works correctly when any individual subquery returns NULL (e.g., empty `schema_migrations` table).

### Fix

Replaced all 4 sequential `fetchval` calls with a single `fetchrow` call using scalar subqueries:

```sql
SELECT
    (SELECT MAX(version) FROM core.schema_migrations) AS schema_version,
    (SELECT COUNT(*) FROM core.identities) AS identity_count,
    (SELECT COUNT(*) FROM core.sessions WHERE is_active = TRUE) AS active_session_count
```

The results are then extracted from the row using dictionary key access:

```python
row = await conn.fetchrow(query)
version = row["schema_version"]
identity_count = row["identity_count"]
session_count = row["active_session_count"]
```

**Before:** 4 DB round-trips per health check
**After:** 1 DB round-trip per health check (plus 1 for the AGE `LOAD` test)
**Risk:** None — response shape unchanged, no unit tests mock the individual calls
**Tests:** 5478 passed, 35 skipped

### Additional findings catalogued for future iterations

The following findings were identified during research but not actioned in this iteration, either because they require broader changes or have lower impact:

**Dead code in production (tested but unused):**
- `interpret_eisv_quick()` in `src/governance_state.py:577` — defined and tested but never called from any production code path. Only imported in `tests/test_governance_state.py`.
- `explain_anomaly()` and `generate_recovery_coaching()` in `src/mcp_handlers/llm_delegation.py:185,225` — defined and tested but never called from production handlers.
- `create_model_inference_client()` in `src/mcp_handlers/model_inference.py:351` — factory function with no production callers.
- Dead import of `_generate_coherence_recommendation` in `src/mcp_handlers/cirs_protocol.py:99` — imported but never used within that module.
- `auto_archive_old_test_agents()` in `src/agent_lifecycle.py:40` — defined but never called in any production code path.
- Several functions in `src/mcp_handlers/tool_stability.py` (lines 389-414): `get_tool_aliases`, `get_migration_guide`, `is_stable_tool`, `is_experimental_tool` have no external callers in production.

**Code duplication:**
- `_safe_float` helper is duplicated in `src/mcp_handlers/lifecycle.py:39` (default=0.0) and `src/mcp_handlers/self_recovery.py:61` (default=0.5) with different default values. Both are used within their respective modules.

**Intentional design (not a bug):**
- `pool_free` and `pool_idle` both return `self._pool.get_idle_size()` in the health check response (lines 276-277). The comment documents this as an intentional alias for backward compatibility.

## Iteration 2: Eliminate expensive monitor.get_metrics() from hot path enrichment

**File:** `src/mcp_handlers/update_enrichments.py`, lines 211-223
**Category:** Performance
**Date:** 2026-03-07

### Problem

The `enrich_health_status_toplevel()` enrichment function, called during Phase 6 of every `process_agent_update`, checks whether `current_risk` and `mean_risk` keys exist in the response metrics dict. Since `process_update()` returns `risk_score` but never `current_risk` or `mean_risk`, this condition is **always true**, causing the fallback path to execute on **every single update**.

The fallback called `monitor.get_metrics()`, which is an expensive operation defined in `src/monitor_metrics.py:27`. This function performs:

1. `approximate_stability_check(samples=200, steps_per_sample=20)` — runs 200 random ODE trajectories through 20 integration steps each (4000 total ODE evaluations)
2. `phi_objective()` — computes the Phi objective function
3. `verdict_from_phi()` — classifies verdict from phi
4. `HealthThresholds()` — instantiates a new health checker
5. Decision statistics aggregation via `Counter(decision_history)`
6. Void frequency computation with numpy
7. Full CIRS oscillation state extraction
8. Complete state dict construction with all fields

All of this was triggered just to extract 3 simple values:
- `current_risk`: mean of last 10 entries in `state.risk_history`
- `mean_risk`: mean of all entries in `state.risk_history`
- `latest_risk_score`: last entry in `state.risk_history`

### Investigation

- Confirmed `process_update()` returns metrics with `risk_score` key (line 1579 in `governance_monitor.py`) but not `current_risk`, `mean_risk`, or `latest_risk_score`
- Verified the 3 fields are simple aggregates of `state.risk_history` (lines 62-69 in `monitor_metrics.py`): `np.mean(rh[-10:])`, `np.mean(rh)`, `rh[-1]`
- Confirmed `monitor.state.risk_history` is already updated by the time Phase 6 enrichments run (Phase 4 calls `process_update` which appends to `risk_history`)
- Checked that no tests mock `get_metrics()` within the `enrich_health_status_toplevel` path
- Also changed `mcp_server.get_or_create_monitor()` to `mcp_server.monitors.get()` — the monitor is guaranteed to exist by Phase 6 (created in Phase 4), and `.get()` is cheaper and consistent with other enrichments

### Fix

Replaced the `monitor.get_metrics()` call with direct computation from `monitor.state.risk_history` using pure Python arithmetic (no numpy needed):

```python
# Before (expensive — triggers 4000 ODE evaluations per update):
monitor = mcp_server.get_or_create_monitor(ctx.agent_id)
monitor_metrics = monitor.get_metrics()
metrics['current_risk'] = monitor_metrics.get('current_risk')
metrics['mean_risk'] = monitor_metrics.get('mean_risk')
metrics['latest_risk_score'] = monitor_metrics.get('latest_risk_score')

# After (direct — O(n) list arithmetic on ~100-element history):
monitor = mcp_server.monitors.get(ctx.agent_id)
rh = monitor.state.risk_history
metrics['current_risk'] = float(sum(rh[-10:]) / len(rh[-10:]))
metrics['mean_risk'] = float(sum(rh) / len(rh))
metrics['latest_risk_score'] = float(rh[-1])
```

**Before:** ~4000 ODE evaluations + phi + stability check per update (via `get_metrics()`)
**After:** Simple list arithmetic on ~100-element array per update
**Risk:** None — values computed identically, fail-safe try/except preserved
**Tests:** 5478 passed, 35 skipped

### Additional hot-path findings catalogued for future iterations

The following performance issues were identified in the `process_agent_update` hot path during research:

**Behavioral sensor computed before ODE update (stale data):**
- `update_phases.py:420-494` computes `compute_behavioral_sensor_eisv()` during Phase 4, inside the lock, before `process_update()` runs. This queries the DB (`get_recent_outcomes`) and runs calibration metrics on stale state. Should be moved to Phase 6 or made lazy.

**Calibration metrics computed twice:**
- `calibration_checker.compute_calibration_metrics()` is called both in the behavioral sensor (Phase 4) and in `enrich_trajectory_identity` (Phase 6), with no caching between them.

**Monitor accessed 5+ times across enrichments:**
- Each enrichment calls `mcp_server.monitors.get(ctx.agent_id)` independently. Caching the monitor reference in `ctx` during Phase 4 would eliminate redundant dict lookups.

**All enrichments run unconditionally before response mode filtering:**
- 20+ enrichments execute on every update, then `response_formatter.py` may discard most of them if the response mode is "minimal" or "compact". Early mode selection could skip unneeded enrichments.

## Iteration 3: Deduplicate calibration error computation across Phase 4 and Phase 6

**Files:** `src/mcp_handlers/update_context.py`, `src/mcp_handlers/update_phases.py`, `src/mcp_handlers/update_enrichments.py`
**Category:** Code Quality
**Date:** 2026-03-07

### Problem

The calibration error extraction pattern was duplicated verbatim in two hot-path locations:

1. **Phase 4** (`update_phases.py:428-437`): `compute_behavioral_sensor_eisv()` needs `cal_error`
2. **Phase 6** (`update_enrichments.py:578-586`): `enrich_trajectory_identity()` needs `cal_error`

Both locations had this identical 7-line block:

```python
cal_error = None
try:
    metrics = calibration_checker.compute_calibration_metrics()
    if metrics:
        errors = [b.calibration_error for b in metrics.values() if b.count >= 5]
        if errors:
            cal_error = sum(errors) / len(errors)
except Exception:
    pass
```

While `compute_calibration_metrics()` is cheap (O(5) bin iteration), the code duplication is a maintenance hazard — any change to the extraction logic (e.g., changing the `count >= 5` threshold or the aggregation method) must be made in two files. The two calls also produce identical results from the same singleton, making the second call purely redundant.

### Investigation

- Confirmed both call sites use the same singleton (`calibration_checker`) with no arguments
- Confirmed both apply the same extraction logic (filter bins with `count >= 5`, compute mean `calibration_error`)
- Confirmed no tests mock `compute_calibration_metrics` within the Phase 4 or Phase 6 paths
- Verified `UpdateContext` already carries state between phases but had no calibration cache fields
- Confirmed Phase 4 may be skipped (for embodied agents with sensor_eisv), so Phase 6 needs a fallback

### Fix

1. Added `_cal_error` and `_cal_error_ready` cache fields to `UpdateContext` (line 59-60)
2. Extracted a `get_mean_calibration_error(ctx)` function in `update_context.py` (lines 76-90) that computes once and caches on the ctx object
3. Replaced the 7-line block in Phase 4 with a single call: `cal_error = get_mean_calibration_error(ctx)`
4. Replaced the 7-line block in Phase 6 with the same call — if Phase 4 already ran, the cached value is returned immediately; if not, it computes on first access

**Before:** 14 lines of duplicated calibration logic across 2 files, 2 computations per update
**After:** 1 canonical function, 1 computation per update (cached via `_cal_error_ready` flag)
**Risk:** None — identical logic, fail-safe try/except preserved in the helper, fallback for skipped Phase 4
**Tests:** 5478 passed, 35 skipped

## Iteration 4: Eliminate redundant monitor lookups in update pipeline

**File:** `src/mcp_handlers/update_phases.py`, lines 641-642, 706-785
**Category:** Code Quality
**Date:** 2026-03-07

### Problem

Two code quality issues in `update_phases.py`:

**1. `ctx.monitor` field defined but never populated (unused infrastructure)**

`UpdateContext` declares a `monitor: Optional[Any] = None` field (line 42) intended to carry the monitor reference between phases. However, it was never assigned. Every function that needs the monitor performed its own `mcp_server.monitors.get(agent_id)` dict lookup instead.

In `execute_post_update_effects` alone, `mcp_server.monitors.get(agent_id)` was called 4 times for the same agent within the same function invocation:

- Line 712: CIRS state announce
- Line 725: CIRS resonance signal
- Line 747: CIRS neighbor pressure
- Line 791: Drift dialectic trigger

All 4 lookups retrieve the same monitor from the same dict with the same key. While each `.get()` call is O(1), the pattern is noisy — it obscures that these blocks all operate on the same monitor, and each block redundantly shadows the same local `monitor` variable.

**2. Duplicate `getattr(monitor, '_last_continuity_metrics', None)` in Phase 4**

In `compute_behavioral_sensor_eisv` preparation (Phase 4, lines 447-457), the continuity metrics object was fetched from the monitor twice:

```python
# First fetch (line 447):
cm = getattr(monitor, '_last_continuity_metrics', None)
if cm is not None:
    comp_div = getattr(cm, 'complexity_divergence', None)

# Second fetch (line 453) — DUPLICATE:
cm = getattr(monitor, '_last_continuity_metrics', None)
if cm is not None:
    cont_E = getattr(cm, 'E_input', None)
    cont_I = getattr(cm, 'I_input', None)
    cont_S = getattr(cm, 'S_input', None)
```

The second `getattr` call returns exactly the same object. All 4 field extractions should be in a single block.

### Investigation

- Confirmed `ctx.monitor` field exists on `UpdateContext` (line 42) with `monitor: Optional[Any] = None`
- Confirmed `ctx.monitor` is never assigned anywhere in the codebase (`grep 'ctx\.monitor' src/` — 0 matches)
- Confirmed the monitor is guaranteed to exist after `process_update_authenticated_async` returns (Phase 4 creates or updates it)
- Confirmed the 4 Phase 5 lookups all use the same `agent_id` variable (set to `ctx.agent_id` at line 652)
- Confirmed each try/except block already handles `None` monitor (either via `if monitor` guard or by catching AttributeError)
- Confirmed the `cm` object (`_last_continuity_metrics`) is a simple attribute, not a property with side effects

### Fix

**Monitor caching:** Added `ctx.monitor = mcp_server.monitors.get(ctx.agent_id)` at line 642, immediately after the ODE update completes. Then replaced all 4 `mcp_server.monitors.get(agent_id)` calls in `execute_post_update_effects` with `monitor = ctx.monitor`.

**Continuity metrics dedup:** Merged the two `getattr(monitor, '_last_continuity_metrics', None)` blocks into one:

```python
# Before: 2 getattr calls, 2 conditionals, 10 lines
comp_div = None
cm = getattr(monitor, '_last_continuity_metrics', None)
if cm is not None:
    comp_div = getattr(cm, 'complexity_divergence', None)
cont_E, cont_I, cont_S = None, None, None
cm = getattr(monitor, '_last_continuity_metrics', None)
if cm is not None:
    cont_E = getattr(cm, 'E_input', None)
    cont_I = getattr(cm, 'I_input', None)
    cont_S = getattr(cm, 'S_input', None)

# After: 1 getattr call, 1 conditional, 7 lines
comp_div = None
cont_E, cont_I, cont_S = None, None, None
cm = getattr(monitor, '_last_continuity_metrics', None)
if cm is not None:
    comp_div = getattr(cm, 'complexity_divergence', None)
    cont_E = getattr(cm, 'E_input', None)
    cont_I = getattr(cm, 'I_input', None)
    cont_S = getattr(cm, 'S_input', None)
```

**Before:** 4 redundant `monitors.get()` calls in Phase 5, unused `ctx.monitor` field, duplicate `getattr` in Phase 4
**After:** 1 lookup cached on `ctx.monitor`, reused across Phase 5; single `getattr` for continuity metrics
**Risk:** None — `ctx.monitor` is set after the ODE guarantees the monitor exists; each try/except block still catches failures independently
**Tests:** 5478 passed, 35 skipped

### Additional findings catalogued for future iterations

**Phase 6 enrichments still do independent monitor lookups:**
- `update_enrichments.py` lines 26, 46, 214, 568, 701, 874 each call `mcp_server.monitors.get(ctx.agent_id)` or `mcp_server.get_or_create_monitor(ctx.agent_id)` independently. Now that `ctx.monitor` is populated, these could all use `ctx.monitor` instead. Two of them (lines 214, 874) use `get_or_create_monitor` which is unnecessarily expensive post-ODE — the monitor is guaranteed to exist.

**`_safe_float` duplication remains:**
- `lifecycle.py:39` (default=0.0) and `self_recovery.py:61` (default=0.5) — identical logic, different defaults. Could be consolidated into a shared utility with a `default` parameter.
