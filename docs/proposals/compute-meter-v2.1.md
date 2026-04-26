---
title: Compute Meter (v2.1) — substrate-polymorphic effort metering, hardened
status: ready-to-build (round-3 council inputs incorporated)
supersedes: docs/proposals/compute-meter-v2.md
author: Kenny Wang (with Claude)
date: 2026-04-25
last_amended: 2026-04-25 (round-3 corrections inline)
council_inputs:
  - docs/proposals/compute-meter-v2.dialectic-review.md
  - docs/proposals/compute-meter-v2.code-review.md
  - docs/proposals/compute-meter-v2.1.dialectic-review.md
  - docs/proposals/compute-meter-v2.1.code-review.md
tags: [observability, calibration, ontology, EISV-adjacent]
---

# Compute Meter (v2.1)

Incremental hardening of v2 against round-2 council review. Conceptual model unchanged; structural specifics rewritten where v2 over-claimed enforcement.

## What changed from v2 (and v2.1 round-3 amendments)

Round 2 found two convergent failures:

- **Dialectic**: "v2 has one structural bolt (role denial), not three. Schema separation and AST contract test are decorative without it."
- **Code review**: "`governance_core_runtime` role doesn't exist in this codebase. Basin solver is in-process with the MCP server, sharing one asyncpg pool. Role-level REVOKE as specified is impossible."

v2 claimed *architectural* enforcement it could not deliver — worse than v1's honestly rhetorical posture. v2.1 corrected this and landed six other concrete fixes.

Round 3 dispatched both reviewers against v2.1. Verdict: **build, no v3 needed** — but seven specific in-doc amendments needed. All have been applied to this document inline (see `## Council inputs incorporated` for the round-3 list). The "ready-to-build" status in the frontmatter reflects the post-amendment state.

| # | Fix | Source |
|---|---|---|
| 1 | Role-firewall claim dropped; replaced with startup assertion + AST test + schema separation | both reviews |
| 2 | Partition maintenance for `meter.*` made mandatory in Phase 1 (silent-data-loss prevention) | code review §11 |
| 3 | Action meter gets stricter gating than compute meter (separate proposal required for cross-agent action analysis) | dialectic §4 |
| 4 | `complexity` demotion gets a falsifiable threshold and an owning phase | dialectic §5 |
| 5 | Doctrine renamed: "no cross-substrate combination" replaces "two meters never combined" | dialectic §5 |
| 6 | Resident emission paths corrected (HTTP/REST for Chronicler/Watcher; anima-mcp PR for Lumen; Steward verified) | code review §5 |
| 7 | Local CLAUDE.md compliance: `run_in_executor` not `await wait_for` for meter insert | code review §7 |

Plus the smaller corrections from the code review: `meter` added to `search_path`; three-file `meter_emit` registration enumerated; `ComputeEmissionParams` inherits `AgentIdentityMixin`; Claude Code `stream-json` schema (not API streaming) verified before Phase 0; dashboard "linter" dropped to CSS convention + code review.

## Conceptual model (unchanged)

Two meters, **never combined across substrates** (v2.1 doctrine — see §Doctrine):

- **A. Substrate-polymorphic compute meter.** Each agent class emits effort in its own unit. Units are NOT cross-substrate-summable. Per-substrate dashboard panes only.
- **B. Universal action meter.** Cross-comparable counts of governance-relevant operations. NO effort units. Subject to its own stricter gating (§Action meter gating).

Substrate categories carry the v2 label set (`llm_api`, `local_llm`, `python`, `embodied`, `mixed`) but with an explicit acknowledgement: **substrate is convenience, not physics**. The real partition is the populated-field-set in each emission row. The `mixed` value is *reserved* for a hypothetical future agent class that genuinely combines substrates within one emission cycle — none exists today. (v2.1 originally claimed Vigil dispatched LLM calls; round-3 verification of `agents/vigil/agent.py` found no `anthropic` import and no LLM dispatch — Vigil is `python`. The `mixed` label remains in the enum because reserving it now is cheaper than a migration later, but no agent currently emits with it.)

Adding a new substrate value IS a migration — the table has `CHECK (substrate IN (...))` enforcement. The "field-driven not enum-driven" framing in v2 was overclaim; v2.1 is honest that substrate additions go through migration + council review, not silent label growth. This is the price of the CHECK constraint, and it's the right price.

Per `feedback_eisv-surface-sprawl.md`, this is acceptable for an observability layer (which makes no thermodynamic claims) but would NOT be acceptable for an EISV channel. The schema separation enforces this: `meter.*` is allowed to be convenience; `governance_core/` requires physics.

## Doctrine: no cross-substrate combination

(Renamed from v2's "two meters never combined" per dialectic §5.)

Within-substrate combination IS allowed and useful: `tokens_per_kg_write` for an LLM-API agent, `cpu_ms_per_kg_write` for a pure-Python agent. These are productivity ratios, computed and surfaced **per substrate**.

Across substrates, no combination. The dashboard never aggregates Lumen's `watt_hours_per_kg_write` with dispatch-claude's `dollars_per_kg_write` into a single number. Lumen and dispatch-claude get separate dashboard panes; they are not ranked against each other.

Within-substrate Goodhart pressure is acknowledged: an LLM-API agent that learns "high tokens correlates with operator-flagged slop" will compress. This is *less harmful* than cross-substrate ranking pressure (which would punish embodied agents for being embodied), but it is real. Action meter gating (§below) is the structural mitigation.

**Clarification on Phase 4 calibration analysis** (round-3 dialectic §6): the `complexity` calibration view computes per-agent MAE (Mean Absolute Error) of `complexity_self_report` vs `compute_emitted` on quantile distance, *normalized within substrate*, then surfaces the per-agent MAE values for review. Comparing two normalized MAE numbers (one for an LLM-API agent, one for a Python agent) is permitted because both are dimensionless calibration errors, not raw effort. The doctrine is: **cross-substrate aggregation on raw effort units is forbidden; cross-substrate comparison on dimensionless derived metrics is permitted, with the burden on the deriver to demonstrate normalization is real**. This is a tighter doctrine than v2's blanket "never combined" — and tight enough that the Phase 4a calibration view is consistent with it.

**18-month embarrassment vector** (round-3 dialectic §8): a one-line `ORDER BY tokens_per_kg_write DESC LIMIT 10` PR passes every protection layer here. Within-substrate ratios are explicitly sanctioned. The only thing standing in the way is human review. v2.1 acknowledges this and chooses to ship anyway: stronger structural protection requires either eliminating ratios (defeats the calibration view) or eliminating dashboards (defeats observability). Mitigation: the dashboard pane convention (per-agent only, no top-N tables of agents-by-ratio) is documented in `dashboard/README.md` as a review checklist item, with the specific failure mode named ("ranking by efficiency invites compression"). Not enforcement. Honest.

## Architectural firewall (rewritten)

The basin solver MUST NOT read meter data. v2 specified three layers; one was impossible. v2.1 specifies two layers that ARE implementable, plus one runtime check that adds defense-in-depth:

### Layer 1: Schema separation (DDL)
`meter.*` is its own Postgres schema, separate from `core.*` (operational) and `audit.*` (governance event log). All meter DDL/DML uses fully-qualified names (`meter.compute_emissions`, `meter.actions`). The `search_path` in `src/db/postgres_backend.py:290` gets `meter` added defensively, but the convention is schema-qualified.

### Layer 2: Static AST contract test
`tests/architecture/test_meter_isolation.py` walks the Python import graph of `governance_core/` (using `ast.parse` on every `.py` file under that path) and asserts:
- No module imports any path matching `meter`
- No module imports `src.services.meter*`, `src.db.mixins.meter*`, or `src.mcp_handlers.schemas.meter`

Bound (acknowledged in test docstring): the AST scan catches imports, not data flow. A future PR that passes a meter-derived value as an argument into a `State` or `Theta` factory defeats the test silently. Layer 3 mitigates.

### Layer 3: Runtime startup assertion
A startup background task (registered alongside other tasks in `src/background_tasks.py:start_all_background_tasks`, NOT in `UNITARESMonitor.__init__` which has no async context — round-3 code review §4) attempts a sentinel `SELECT 1 FROM meter.compute_emissions LIMIT 0` from the basin solver's connection path. If the SELECT *succeeds*, the assertion logs a WARN — the basin process can reach meter data, even if it currently doesn't. The codebase shares one pool today, so the SELECT will succeed by design. The WARN is the early-warning signal that flips to ERROR once Layer 4 (future) lands.

**Honest framing of Layer 3** (round-3 dialectic §1): a WARN that fires on every startup by design is not enforcement — it is documentation pretending to be enforcement. v2.1 is honest about this. Layer 3's value is *audit trail*, not prevention: when Layer 4 lands and the WARN flips to ERROR, the deployment that has been silently sharing a pool for months will fail loudly at restart, and ops will know exactly what changed. Until then, Layer 3 is a marker, and the actual structural protection comes from Layers 1 (schema separation) and 2 (AST contract test). The five protection layers in this proposal are ordered by today-strength: 2 > 1 > Action-meter-gating-policy > 3 > 4 (future).

### Layer 4 (future, NOT in this proposal): Process / role separation
A future proposal — out of scope here — splits `governance_core` into a subprocess with its own DB credentials under a `governance_core_runtime` role with `REVOKE SELECT ON SCHEMA meter`. When that lands, the Layer 3 startup assertion flips from WARN to ERROR (succeeds-when-it-shouldn't is a deployment misconfiguration). v2.1 does NOT promise this. v2.1 is honest that the codebase today does not have process isolation.

This is the change from v2: layers 1–3 are concrete and shippable. Layer 4 is acknowledged as a future requirement and given a name. v2 conflated 4 with 1–3 and was wrong.

## Action meter — stricter gating

Per dialectic §4: the action meter is more dangerous than the compute meter, because it is **universal, cross-comparable, and feels like a productivity signal**. The slope from `actions/wall_time` → "low-action agents are guided" is short and locally-reasonable.

v2.1 protects the action meter explicitly:

1. **Read access in dashboards is per-agent only at first.** Phase 4 dashboard panes show one agent's action history at a time. NO cross-agent action ranking ships in any phase covered by this proposal.
2. **Cross-agent action analysis requires its own proposal.** Any PR that introduces a query joining action counts across agents (whether via Chronicler roll-ups, dashboard tables, or governance code) MUST cite a passing council review of a separate proposal. Enforcement: a `// CHECKLIST: cross-agent-action-analysis` PR template item that reviewers must check.
3. **Action types are tightly scoped.** The allowlist (`<proposed>/src/services/meter/actions.py:ACTION_TYPES`) starts with the minimum vocabulary and grows by PR. Each addition requires justifying which substrate emits it and what calibration it supports.
4. **Calibration view (Phase 4) operates on ratios, not raw counts.** `tokens_per_kg_write` is dashboard-allowed (within-substrate ratio). `kg_writes_per_day` ranked across agents is not, even though the data trivially supports it.

These are policy controls, not code controls. They are weaker than schema controls. That is acknowledged. The structural protection comes from the fact that adding a cross-agent ranking query is a deliberate act with a checklist trip, not a one-line dashboard tweak.

## `complexity` demotion — concrete path

Per dialectic §5: v2's "later, out of scope" framing leaves `complexity` load-bearing forever. v2.1 specifies:

### Phase 4a: calibration accumulation
For each agent that has both self-reported `complexity` (from `process_agent_update` calls) AND harness-emitted compute (from `meter.compute_emissions`), Chronicler computes a per-agent calibration error: how well does self-reported complexity predict measured compute, normalized by substrate?

The metric: `MAE(predicted_complexity_quantile, observed_compute_quantile)` per (agent_id, substrate, 7-day rolling window). Stored in `metrics.series`.

### Phase 4b: falsifiable demotion threshold
Once 90 days of calibration data exist across ≥10 distinct agents (where each agent emits ≥30 distinct `complexity` values, NOT a constant or two-valued distribution — round-3 dialectic §3) AND the median per-agent MAE is ≤0.15 (i.e., self-reported complexity tracks observed compute within 15% on quantile distance), `complexity` is eligible for demotion.

**Why the variance floor matters:** verification of `agents/chronicler/agent.py` and `agents/vigil/agent.py` shows several residents emit constant or near-constant complexity values (e.g., `0.4 if failures > 0 else 0.1`). On degenerate input distributions, quantile-MAE is trivially ≤0.15 because there's nothing to mis-predict. Without the variance floor, residents would push the median MAE artificially low and trigger Phase 4c flip prematurely. The floor — ≥30 distinct complexity values per agent over the 90-day window — excludes degenerate self-reporters from the calibration evidence pool. Genuine LLM-driven agents (dispatch-claude, dispatch-codex, claude-code sessions) produce continuous-valued complexity and pass the floor; residents with rule-based complexity do not, and that is correct.

Demotion = removing `complexity` as a primary input to S in `governance_core/dynamics.py`, replacing with a derived signal computed from `meter.compute_emissions` (substrate-normalized). The replacement signal goes through its own dialectic + code review before flipping.

### Phase 4c (the actual flip)
A separate proposal owns the flip. v2.1 does not write it. v2.1 makes the data exist and defines the threshold that triggers it.

If the threshold is never met (e.g., because cross-substrate calibration is genuinely impossible or because agents don't self-report enough), `complexity` stays as the primary input. The honest outcome is that the threshold names the failure rather than silently leaving the worse measurement load-bearing.

This pattern — "specify the threshold for the next decision, don't make it now" — is the way `feedback_design-doc-council-review.md` and `feedback_eisv-bounds-drift.md` recommend handling load-bearing parameter changes.

## Schema (corrected)

### `meter.compute_emissions` (partitioned, schema-qualified)

```sql
CREATE SCHEMA IF NOT EXISTS meter;

CREATE TABLE meter.compute_emissions (
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    emission_id         UUID NOT NULL DEFAULT gen_random_uuid(),
    agent_id            TEXT NOT NULL,         -- TEXT to match audit.outcome_events.agent_id
    client_session_id   TEXT,
    epoch               INTEGER NOT NULL,
    substrate           TEXT NOT NULL CHECK (substrate IN
                          ('llm_api', 'local_llm', 'python', 'embodied', 'mixed')),
    -- Soft reference to outcome event (no FK; outcome_events is partitioned)
    outcome_id          UUID,
    outcome_ts          TIMESTAMPTZ,
    -- LLM-bearing fields (NULL for pure-Python and embodied)
    tokens_in           INTEGER,
    tokens_out          INTEGER,
    cache_read_tokens   INTEGER,
    cache_creation_tokens INTEGER,
    model_id            TEXT,
    -- Universal field
    wall_time_ms        INTEGER,
    -- Pure-Python / Watcher / Lumen fields
    cpu_time_ms         INTEGER,
    io_ops              INTEGER,
    watt_hours_est      REAL,
    -- Embodied (Lumen) fields
    sensor_reads        INTEGER,
    gpio_ops            INTEGER,
    tts_chars           INTEGER,
    display_updates     INTEGER,
    -- Provenance
    source              TEXT NOT NULL CHECK (source IN
                          ('harness_emitted', 'agent_self_reported', 'estimated')),
    PRIMARY KEY (ts, emission_id)
) PARTITION BY RANGE (ts);

CREATE INDEX idx_meter_compute_agent_ts
    ON meter.compute_emissions (agent_id, ts DESC);
CREATE INDEX idx_meter_compute_session
    ON meter.compute_emissions (client_session_id, ts DESC);
```

### `meter.actions` (partitioned)

```sql
CREATE TABLE meter.actions (
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action_id           UUID NOT NULL DEFAULT gen_random_uuid(),
    agent_id            TEXT NOT NULL,         -- TEXT to match audit.outcome_events.agent_id
    client_session_id   TEXT,
    epoch               INTEGER NOT NULL,
    action_type         TEXT NOT NULL,
    action_subtype      TEXT,
    PRIMARY KEY (ts, action_id)
) PARTITION BY RANGE (ts);

CREATE INDEX idx_meter_actions_agent_ts
    ON meter.actions (agent_id, ts DESC);
CREATE INDEX idx_meter_actions_type_ts
    ON meter.actions (action_type, ts DESC);
```

### Partition maintenance (MANDATORY in Phase 1 — code review §11)

```sql
-- Per-table partition creation functions, mirroring audit.create_*_partition
CREATE OR REPLACE FUNCTION meter.create_compute_emissions_partition(
    target_month DATE
) RETURNS VOID AS $$
DECLARE
    partition_name TEXT;
    range_start DATE;
    range_end DATE;
BEGIN
    range_start := DATE_TRUNC('month', target_month);
    range_end := range_start + INTERVAL '1 month';
    partition_name := FORMAT('compute_emissions_%s', TO_CHAR(range_start, 'YYYY_MM'));
    EXECUTE FORMAT(
      'CREATE TABLE IF NOT EXISTS meter.%I PARTITION OF meter.compute_emissions
       FOR VALUES FROM (%L) TO (%L)',
      partition_name, range_start, range_end
    );
    EXECUTE FORMAT(
      'CREATE INDEX IF NOT EXISTS idx_%s_agent_ts ON meter.%I (agent_id, ts DESC)',
      partition_name, partition_name
    );
END;
$$ LANGUAGE plpgsql;

-- Symmetric meter.create_actions_partition()  (omitted for brevity; same shape)

-- Hook into existing partition_maintenance:
-- Either extend audit.partition_maintenance() to also call meter.* functions,
-- OR add a new meter.partition_maintenance() and a parallel background task.
-- v2.1 chooses the latter for clean separation:

CREATE OR REPLACE FUNCTION meter.partition_maintenance() RETURNS VOID AS $$
DECLARE
    target DATE;
BEGIN
    FOR i IN 0..2 LOOP
        target := (DATE_TRUNC('month', NOW()) + (i || ' months')::INTERVAL)::DATE;
        PERFORM meter.create_compute_emissions_partition(target);
        PERFORM meter.create_actions_partition(target);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Bootstrap (current + 2 future months) inside the migration DO block.
```

A new background task `periodic_meter_partition_maintenance` is registered in `src/background_tasks.py` alongside `periodic_partition_maintenance`, calling `meter.partition_maintenance()` weekly. Following the existing convention (see `periodic_partition_maintenance`), the task starts with `await asyncio.sleep(60.0)` to ensure the DB pool is initialized before the first call (round-3 code review §1).

**Without this, meter inserts will silently fail past the bootstrap horizon and the `try/except` fire-and-accept-failure pattern will swallow the failures.** Code review's #1 finding. Phase 1 ships ALL of this together.

**Schema type discipline:** `agent_id` is `TEXT NOT NULL` in both meter tables to match `audit.outcome_events.agent_id` (also `text`, not `uuid`). v2 declared `UUID NOT NULL`, which would have made Phase 4 calibration joins (`JOIN audit.outcome_events e ON e.agent_id = m.agent_id`) silently incorrect or require explicit casting. v2.1 fixes this at schema time, before any data is written. Round-3 dialectic catch.

## Integration (corrected)

### Pydantic schema

`<proposed>/src/mcp_handlers/schemas/meter.py`:

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from .mixins import AgentIdentityMixin

class ComputeEmissionParams(AgentIdentityMixin):
    substrate: Literal['llm_api', 'local_llm', 'python', 'embodied', 'mixed']
    source: Literal['harness_emitted', 'agent_self_reported', 'estimated']
    # Optional outcome reference
    outcome_id: Optional[str] = None
    outcome_ts: Optional[str] = None
    # LLM fields
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_creation_tokens: Optional[int] = None
    model_id: Optional[str] = None
    wall_time_ms: Optional[int] = None
    # Python / Watcher / Lumen fields
    cpu_time_ms: Optional[int] = None
    io_ops: Optional[int] = None
    watt_hours_est: Optional[float] = None
    # Embodied
    sensor_reads: Optional[int] = None
    gpio_ops: Optional[int] = None
    tts_chars: Optional[int] = None
    display_updates: Optional[int] = None

class ActionParams(AgentIdentityMixin):
    action_type: str
    action_subtype: Optional[str] = None
```

`AgentIdentityMixin` inheritance per code review §6 — middleware identity injection works automatically.

### `meter_emit` MCP tool registration (FOUR files)

Per round-3 code review §6: schema inheritance of `AgentIdentityMixin` does NOT drive session injection — the lookup at `src/mcp_server.py:404` is name-based, not schema-based. `meter_emit` must be added to all four registration locations:

1. `src/tool_schemas.py:TOOL_ORDER` — append `meter_emit`
2. `src/tool_schemas.py:_load_pydantic_schemas` — append `"src.mcp_handlers.schemas.meter"` to `mods`
3. `src/tool_modes.py:LITE_MODE_TOOLS` — add `meter_emit` (exposed under default `TOOL_MODE=lite`)
4. **`src/mcp_server.py:TOOLS_NEEDING_SESSION_INJECTION`** — add `"meter_emit"` so FastMCP `Context`-driven `client_session_id` injection fires for interactive sessions

Phase 1 checklist enumerates all four. v2 enumerated three; round-2 review missed the fourth; round-3 caught it.

### anyio-asyncio: `asyncio.wait_for` (pattern 3), NOT `run_in_executor`

Round-3 code review §2 found the `run_in_executor` precedent v2 cited (`verify_agent_ownership` at `src/agent_loop_detection.py:374`) is a pure-Python in-memory function — no DB access. The codebase has NO sync DB client (`src/db/__init__.py:40-53` exports only the asyncpg-based `PostgresBackend`). The `run_in_executor + sync DB client` pattern from v2 cannot be implemented without building new infrastructure.

The `meter_emit` handler uses `asyncio.wait_for(db.record_meter_emission(...), timeout=2.0)` with a `try/except` that logs and continues — pattern 3 from `CLAUDE.md`. This is the same pattern used by `deep_health_probe_task` at `src/background_tasks.py:380` and `_load_binding_from_redis` at `src/mcp_handlers/middleware/identity_step.py`. The `run_in_executor` precedent was cited in error.

For the inline-on-`outcome_event` path (when `compute` is supplied alongside an outcome), the meter insert rides inside the existing 15s `outcome_event` decorator budget. The inner 2.0s `wait_for` provides a hard ceiling on the meter insert's contribution. Failures are caught via `try/except`, logged at INFO, and never block the `outcome_id` return.

(If a future PR adds a sync DB client, the executor pattern becomes available and this proposal can be amended. v2.1 does not block on that work.)

### `search_path`

`src/db/postgres_backend.py:290`:
```python
await conn.execute(f"SET search_path = ag_catalog, core, audit, meter, public")
```
Add `meter` (defensive). All queries remain schema-qualified by convention.

### `epoch` source for REST callers (round-3 code review §10)

`meter.compute_emissions.epoch INTEGER NOT NULL` — but Chronicler/Watcher/`eisv-sync-task` calling via REST have no execution context for `epoch`. Two options:

- **Caller-supplied** with an SDK helper `client.get_current_epoch()` that hits a lightweight REST endpoint
- **Server-defaulted** in the `meter_emit` handler: if `epoch` is absent from arguments, fill from `GovernanceConfig.CURRENT_EPOCH` at insert time

v2.1 picks **server-defaulted**. Rationale: `epoch` is a server-side governance concept, not a client concern. Forcing every caller to track it duplicates state and creates skew when the epoch flips between caller-fetch and server-insert. `GovernanceConfig.CURRENT_EPOCH` is the single source of truth; the handler reads it. If a caller wants to record an emission against a specific historical epoch (e.g., back-fill), they may pass `epoch` explicitly and the server respects it.

## Resident-agent emission (corrected)

### Steward / `eisv-sync-task` (Pi-side, NOT in-process)

Verification: `rg "Steward|eisv_sync"` finds no `Steward` class or `agents/steward/`. The actor is `eisv-sync-task` (literal `agent_id` value seen in `src/db/mixins/audit.py`'s `WHERE agent_id NOT IN ('system', 'eisv-sync-task')` and `tests/test_audit_mixin.py`). It runs Pi-side and POSTs to governance MCP via the same channel as Lumen (`anima-mcp` broker → `http://<tailscale-ip>:8767/mcp/`).

Memory entry `project_eisv-sync-agent-identity.md` calling this "in-process" is stale. Cleanup is a separate task — out of scope for this proposal but flagged.

Emission path: same as Chronicler — call `meter_emit` over MCP/REST. Substrate `python`. Wall-time, cpu-time, io-ops where measurable.

### Chronicler (HTTP/MCP only)

`agents/chronicler/agent.py`: `httpx.Client` for REST, `GovernanceAgent` for MCP. No DB handle. `GovernanceClient` exposes named methods (`checkin()`, `search_knowledge()`, etc.) but NOT `meter_emit()` — emission uses the generic dispatch path: `client.call_tool("meter_emit", {...})`. Substrate `python`. Once per launchd run, summarizing the cycle's compute. (If a named SDK method is added later for ergonomics, fine; the generic path works today and v2.1 does not block on SDK changes.)

### Watcher (REST only)

`agents/watcher/agent.py`: `SyncGovernanceClient` REST transport. Same generic-dispatch note: `client.call_tool("meter_emit", {...})`. Substrate `local_llm`. Emits per-scan with `tokens_in/out` from Ollama's `/v1/chat/completions` response (`usage.prompt_tokens` / `usage.completion_tokens`), `model_id` from the configured Ollama model, `wall_time_ms` from cycle timing, `watt_hours_est` from a fixed estimate (declared `source: 'estimated'` for the watt portion, `harness_emitted` for tokens).

### Vigil (substrate `python` — round-3 correction)

Round-3 code review §7 verified `agents/vigil/agent.py` (full 555 lines) and `agents/vigil/checks/`: NO `anthropic` import, NO LLM dispatch, NO call-model invocation. Vigil runs health checks (HTTP), optional pytest (subprocess), optional KG audit (MCP), and posts a check-in (MCP). It is pure-Python.

**Substrate is `python`, not `mixed`.** `tokens_in/out` always NULL. Each cycle emits one `meter.compute_emissions` row with `cpu_time_ms`, `wall_time_ms`, `io_ops`. (v2 originally claimed Vigil dispatched LLM sub-tasks; that capability does not exist in current code. If Vigil is later extended to dispatch LLMs for hard sub-tasks, that warrants its own proposal — and the `mixed` substrate value is reserved for it. Until then, `mixed` is a placeholder.)

### Sentinel (pure-Python)

Substrate `python`. Emits per-cycle summary via `meter_emit` MCP/REST.

### Lumen (anima-mcp PR required — code review §5)

The Pi→Mac channel is broker→governance OUTBOUND HTTP only (`anima-mcp/CLAUDE.md`). The broker (`stable_creature.py`) currently calls `process_agent_update` via `unitares_bridge.py`. Adding `meter_emit` calls requires modifying `unitares_bridge.py` in the `anima-mcp` repo — a separate PR, not just a unitares Phase 3 wiring task.

Phase 3 description (corrected): "Lumen emission requires (a) `unitares_bridge.py` modification in anima-mcp to call `meter_emit`, (b) a periodic emitter in anima-mcp that aggregates Lumen's sensor reads / GPIO ops / TTS chars / display updates / wall-time / watt-hour estimates, (c) governance-mcp side: nothing new beyond `meter_emit` itself."

### Phase 0 dispatch — Claude Code stream-json schema (corrected)

Per code review §9: Claude Code's `--output-format stream-json` is NOT the Anthropic Messages API streaming format. Token usage in Claude Code stream-json appears in `type: "result"` messages under a `usage` key, not in `message_delta`. Phase 0 implementation:

- `discord-dispatch/src/backends/claude.ts`: add a branch for `type === "result"` events, extract `usage` block. Accumulate per session.
- `discord-dispatch/src/sessions.ts`: add token accumulator on `SessionState`.
- On session end, emit one `meter.compute_emissions` row via the new `meter_emit` MCP tool with `source: 'harness_emitted'`.

For Codex: `codex.ts` exposes no token data in its event types (verified). dispatch-codex emits with `model_id` + `wall_time_ms` + `source: 'estimated'`. This is acknowledged as a likely-permanent limitation, not a gap to close later.

### Phase 0 cross-repo failure mode

Phase 0 ships in `discord-dispatch`. Phase 1 ships in `unitares`. If Phase 0 ships first and the dispatch backends start emitting, but Phase 1 hasn't shipped yet, the `meter_emit` calls fail (tool doesn't exist). The dispatch `try/catch` around governance calls already handles that — emissions become no-ops, dispatched sessions continue working. Phase 0 is independently shippable in this fail-soft sense, but the dispatch backends should NOT log errors for missing-tool failures (otherwise log noise drowns real signal). Phase 0 acceptance: emission path is fail-soft, MCP error responses for missing tool are downgraded to debug logs.

## Phasing (corrected)

| phase | scope | dependencies | risk |
|---|---|---|---|
| 0 | dispatch-claude `result.usage` parser; dispatch-codex `source: estimated` fallback; SessionState token accumulator; fail-soft missing-tool handling | none | low |
| 1 | `meter` schema migration **with partition functions and maintenance task**; `meter_emit` MCP tool with **4-file registration** (TOOL_ORDER + _load_pydantic_schemas + LITE_MODE_TOOLS + TOOLS_NEEDING_SESSION_INJECTION); Pydantic schemas with `AgentIdentityMixin`; AST contract test; runtime startup assertion (Layer 3, registered as background task) | phase 0 (or none, if accepting empty initial data) | medium |
| 2 | inline `compute` field on `outcome_event` (`asyncio.wait_for` pattern 3); resident agent emission paths (Chronicler/Watcher/Vigil/Sentinel/eisv-sync-task) — all via MCP/REST `client.call_tool("meter_emit", ...)` | phase 1 | low |
| 3 | anima-mcp PR for Lumen emission via `unitares_bridge.py`; governance-mcp side already done in phase 1 | phase 1 + anima-mcp PR | medium (cross-repo) |
| 4 | Chronicler roll-ups; per-substrate dashboard panes; calibration view (Phase 4a) | phase 2 + 3 | medium (UI + analysis) |
| 4b | Falsifiable `complexity` demotion threshold met (90d, ≥10 agents, MAE ≤0.15) | phase 4 + time | n/a — analysis trigger |
| 4c | Separate proposal: actually flip `complexity` input | phase 4b threshold met | high — separate proposal |
| (future) | Layer 4 firewall: process / role separation | separate proposal | high |

## Risks and open questions (delta from v2)

1. **Lumen watt-hour estimates are still estimates.** No power meter. `wall_time_seconds * estimated_watts_for_pi_state`. `source: 'estimated'`. Trend-detection only.

2. **Action meter Goodhart drift.** Mitigation is policy-level (PR checklist + per-agent dashboard panes only). Acknowledged weaker than schema controls. Re-evaluate after 90 days of phase 4 data.

3. **Substrate enum drift.** New agent classes don't fit cleanly. The CHECK constraint means adding a substrate IS a migration; this is the right honest framing per round-3 dialectic §4. Document the pattern: new substrate value requires explicit migration + council review, not silent label growth.

4. **Codex usage gap.** Permanent — codex CLI doesn't expose token counts.

5. **Layer 3 startup assertion fires at WARN, not ERROR.** Until Layer 4 (process isolation) lands, the basin can technically reach `meter.*`. Layer 3 documents this honestly rather than pretending the firewall is complete. Watcher should be configured to flag any code path that calls `meter.*` from inside a `governance_core` import context, as a secondary signal.

6. **Phase 4c (complexity flip) is gated on calibration data accumulating.** If the threshold is never met (median MAE > 0.15 across substrates), `complexity` stays load-bearing. The honest outcome.

7. **Memory cleanup deferred.** `project_eisv-sync-agent-identity.md` says Steward is in-process; verification shows the actor is `eisv-sync-task` running Pi-side. Out of scope for this proposal — flagged for separate cleanup.

## Council inputs incorporated (delta from v2 → v2.1 → v2.1 amended)

### Round 2 → v2.1 (originally incorporated)

From `compute-meter-v2.dialectic-review.md`:
- ✅ Firewall claim corrected: 3 layers + 1 future (was: 3 layers, claimed enforcement that didn't exist)
- ✅ Action meter gating made explicit and stricter than compute meter
- ✅ `complexity` demotion: falsifiable threshold + owning phase
- ✅ Doctrine renamed "no cross-substrate combination"
- ✅ Substrate-as-convenience acknowledged

From `compute-meter-v2.code-review.md`:
- ✅ Role-firewall claim dropped; replaced with 3 implementable layers
- ✅ Partition maintenance functions + background task in Phase 1 (silent-data-loss fix)
- ✅ `search_path` extended; schema-qualified convention documented
- ✅ `meter_emit` registration enumerated
- ✅ `ComputeEmissionParams` and `ActionParams` inherit `AgentIdentityMixin`
- ✅ Chronicler / Watcher emission corrected to MCP/REST (not direct DB)
- ✅ Steward verified as `eisv-sync-task` Pi-side; treated like Chronicler
- ✅ Lumen Phase 3 specifies anima-mcp PR explicitly
- ✅ Phase 0 uses Claude Code `result.usage` not Anthropic API `message_delta`
- ✅ Dashboard linter dropped; CSS convention + code review

### Round 3 → v2.1 amended (this revision)

From `compute-meter-v2.1.dialectic-review.md`:
- ✅ Layer 3 honestly framed as audit-trail/marker, not enforcement
- ✅ MAE threshold given a variance floor (≥30 distinct complexity values per agent) to exclude degenerate self-reporters
- ✅ Doctrine clarified: cross-substrate aggregation forbidden on raw effort; permitted on dimensionless derived metrics
- ✅ Schema CHECK constraint contradiction resolved — substrate additions ARE migrations
- ✅ `agent_id` type: `TEXT` not `UUID` (matches `audit.outcome_events.agent_id`)
- ✅ 18-month embarrassment vector (within-substrate ranking PR) named and accepted as policy-controlled

From `compute-meter-v2.1.code-review.md`:
- ✅ `asyncio.wait_for` (pattern 3) replaces incorrect `run_in_executor + sync DB client` claim — no sync DB client exists in codebase
- ✅ `TOOLS_NEEDING_SESSION_INJECTION` added as 4th registration file (schema inheritance does NOT drive injection — name-based lookup)
- ✅ Vigil substrate corrected to `python` (no LLM dispatch in agents/vigil/agent.py); `mixed` reserved for future capability
- ✅ Layer 3 startup assertion explicitly registered as a background task, not in `UNITARESMonitor.__init__` (no async context there)
- ✅ `epoch` source for REST callers: server-defaulted from `GovernanceConfig.CURRENT_EPOCH`, with caller override allowed
- ✅ Chronicler/Watcher emission specifies generic `client.call_tool("meter_emit", ...)` — no named SDK method exists yet
- ✅ Partition task includes 60s startup delay (matches `periodic_partition_maintenance` convention)

## What's still aspirational (named, not promised)

- Layer 4 firewall (process / role separation) — separate proposal
- Phase 4c (`complexity` flip) — separate proposal, gated on data
- Steward memory entry cleanup — separate task
- Cross-agent action analysis (any flavor) — separate proposal required by Action meter gating §2

These are not in this proposal. Naming them prevents the "later" loophole.
