---
title: Compute Meter (v2) — substrate-polymorphic effort metering with universal action axis
status: draft
supersedes: docs/proposals/compute-receipt-sidecar.md
author: Kenny Wang (with Claude)
date: 2026-04-25
council_inputs:
  - docs/proposals/compute-receipt-sidecar.dialectic-review.md
  - docs/proposals/compute-receipt-sidecar.code-review.md
tags: [observability, calibration, ontology, EISV-adjacent]
---

# Compute Meter (v2)

## What changed from v1

v1 ("compute-receipt-sidecar") proposed a token-shaped sidecar attached to `outcome_event` with FK semantics, and was reviewed by both `dialectic-knowledge-architect` and `feature-dev:code-reviewer`. The reviews converged on three structural problems:

1. **"Receipt" is the wrong ontology.** Receipts are transactional; metering is continuous. The framing forecloses on use cases (resident agents, Lumen, check-ins) where there is no transaction.
2. **The audit-only firewall was rhetorical, not architectural.** No type system, schema constraint, or contract test prevented `slop_index` from drifting into `governance_core/` via incremental PRs. Per `feedback_memory-not-guardrail.md`, that is not enforcement.
3. **Token-only metering reproduces the heterogeneity problem.** Lumen, Steward, Chronicler, Sentinel, and parts of Vigil emit zero tokens. A token-only meter would make the embodied and pure-Python substrates structurally invisible — the exact failure mode UNITARES claims to avoid.

Plus blocking implementation issues (FK to a partitioned table is impossible; dispatch backends do not yet capture token usage; missing `epoch` column; wrong type/schema/index conventions).

v2 reframes accordingly.

## Conceptual model

Two meters, never combined:

### A. Substrate-polymorphic compute meter

Each agent class emits effort in **its own unit**. These units are NOT cross-summable. The dashboard never adds them. They live in per-substrate panes.

| substrate | unit(s) emitted | $-bearing? |
|---|---|---|
| LLM-API agent (Claude Code, dispatch-claude) | tokens_in, tokens_out, cache_read, cache_create, model_id, wall_time_ms | yes |
| local-LLM agent (Watcher / Ollama) | tokens_in, tokens_out, model_id, wall_time_ms, watt_hours_est | no |
| pure-Python resident (Steward, Chronicler, Sentinel, Vigil-internal) | cpu_time_ms, wall_time_ms, io_ops | no |
| embodied agent (Lumen) | sensor_reads, gpio_ops, tts_chars, display_updates, wall_time_ms, watt_hours_est | partial (TTS API) |
| mixed (Vigil-claude-call) | emits both pure-Python and LLM-API receipts under same client_session_id | yes |

A single client_session_id may carry multiple substrate emissions if the agent calls out (Vigil's pure-Python supervisory loop dispatching a Claude call for a hard sub-task). Each call is its own row. They are aggregated within a session by client_session_id, not summed across substrates.

### B. Universal action meter

Actions are the cross-comparable axis. Every substrate emits the same action vocabulary:

```
kg_write, kg_resolve, dialectic_submit, checkin, tool_call, file_edit,
verdict_received, sensor_read, gpio_op, knowledge_query, outcome_event_emit
```

Action counts are per-session, per-action-type. They do NOT carry effort units. The action meter answers: "what did this agent actually *do*?" without commingling with "what did it cost?"

The cross-substrate efficiency ratio of interest is `actions_of_type_X / compute_emitted` — and this ratio is computed and surfaced *per substrate*. Lumen's `kg_writes_per_watt_hour` and dispatch-claude's `kg_writes_per_dollar` are both legible, but the dashboard never compares them in the same number.

## Non-goals

1. **No EISV channel.** Neither meter feeds the basin solver. `governance_core/` does not import from the meter modules. Enforced architecturally (see §Firewall).
2. **No agent grading.** Meters are observed, not optimized against. No verdict variant ("slop_pause", "thrash_reject") will be created from meter data without a separate proposal that re-opens this scope.
3. **No cross-substrate cost accounting at the basin layer.** Operator-economics dashboards are deliberately *adjacent* to governance, not part of it.
4. **No phase 2.** v1's phase 2 attached receipts to `process_agent_update`. Removed. Per-check-in compute creates perverse incentives (penalizes thoroughness in the primary basin signal). Aggregate session-level compute via Chronicler instead.

## Architectural firewall

This is the load-bearing change from v1. The audit-only constraint is now enforced in three places:

### 1. Schema separation
Compute and action meter tables live in a new schema `meter.*`, separate from both `core.*` (operational) and `audit.*` (governance event log). Rationale: `governance_core/` already does not import from `audit.*`; making the new tables a third schema makes the boundary explicit at DDL level and lets us apply role-level SELECT denial (below).

### 2. Role-level read denial
A new Postgres role `governance_core_runtime` is created with `REVOKE SELECT ON ALL TABLES IN SCHEMA meter FROM governance_core_runtime`. The basin solver process connects as this role. Any future code that tries to read from `meter.*` from inside the basin solver fails at the database layer, not at code review.

### 3. Parametrized contract test
A new test `tests/architecture/test_meter_isolation.py` walks the import graph of `governance_core/` (using `ast` parsing of every `.py` file under that path) and asserts no module imports from `src/services/meter*`, `src/db/mixins/meter*`, or any module path matching `meter`. Run in CI on every PR. The test exists explicitly to fail loudly if a future PR tries to wire meter signal into the basin.

The combination — schema separation + role denial + import contract test — is what makes the firewall architectural rather than rhetorical. Each layer is independently enforced; defeating the firewall would require a coordinated three-place change that cannot be done quietly.

## Demote `complexity`

Per dialectic-review §2: `complexity` is currently a primary input to S in the EISV ODE, supplied by the agent's self-report. It is the *worse measurement* — uncalibrated, model-of-model, and Goodhart-prone. The compute meter is the *better measurement* — observed, substrate-grounded, harness-emitted.

The structural move: keep `complexity` in the input schema for now (do not break existing callers), but begin treating it as a **prediction** that the meter validates. Phase 4 work (calibration, see below) computes per-agent calibration of `complexity_self_report` against `compute_emitted` (using substrate-appropriate normalization) and surfaces poorly-calibrated agents. This is a calibration signal, not a verdict input.

In a later proposal — out of scope for v2 — `complexity` may be deprecated in favor of harness-emitted compute as the primary S input, contingent on calibration evidence accumulating across substrates. v2 sets up the data; it does not flip the input.

## Schema

Two tables in the new `meter` schema. Both follow the established `audit.*` conventions on column types, epoch handling, and index direction (per code-review §3, §4, §6, §7).

### `meter.compute_emissions`

```sql
CREATE TABLE meter.compute_emissions (
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    emission_id         UUID NOT NULL DEFAULT gen_random_uuid(),
    agent_id            UUID NOT NULL,
    client_session_id   TEXT,
    epoch               INTEGER NOT NULL,
    substrate           TEXT NOT NULL,         -- 'llm_api', 'local_llm', 'python', 'embodied', 'mixed'
    -- Soft reference to outcome event (no FK; outcome_events is partitioned)
    outcome_id          UUID,
    outcome_ts          TIMESTAMPTZ,
    -- LLM-bearing fields (NULL for pure-Python and embodied)
    tokens_in           INTEGER,
    tokens_out          INTEGER,
    cache_read_tokens   INTEGER,
    cache_creation_tokens INTEGER,
    model_id            TEXT,
    -- Universal fields
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
    source              TEXT NOT NULL,         -- 'harness_emitted' | 'agent_self_reported' | 'estimated'
    PRIMARY KEY (ts, emission_id)
) PARTITION BY RANGE (ts);

-- Index follows audit-schema convention: (agent_id, ts DESC)
CREATE INDEX idx_meter_compute_agent_ts
    ON meter.compute_emissions (agent_id, ts DESC);
CREATE INDEX idx_meter_compute_session
    ON meter.compute_emissions (client_session_id, ts DESC);
```

Notes:
- Money values are NOT stored. `cost_usd` is derived at query time from a versioned rates file (`<proposed>/config/compute_rates.toml`), keyed on (substrate, model_id, ts) with a `rate_version` column. This avoids the v1 type-inconsistency issue (no `numeric` columns elsewhere — see code-review §3) and keeps cost calculation honest about rate drift.
- Soft join to `audit.outcome_events`: `JOIN audit.outcome_events e ON e.outcome_id = m.outcome_id AND e.ts = m.outcome_ts`. No FK; partitioned-table FK is impossible per code-review §1. Application-level consistency: the handler inserts the emission with the same `(outcome_id, outcome_ts)` returned by `record_outcome_event`, within the same request boundary, with `try/except` around the meter insert so a meter failure never blocks the outcome write.
- Substrate is an `enum` enforced by `CHECK (substrate IN ('llm_api', 'local_llm', 'python', 'embodied', 'mixed'))`.

### `meter.actions`

```sql
CREATE TABLE meter.actions (
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action_id           UUID NOT NULL DEFAULT gen_random_uuid(),
    agent_id            UUID NOT NULL,
    client_session_id   TEXT,
    epoch               INTEGER NOT NULL,
    action_type         TEXT NOT NULL,         -- 'kg_write', 'checkin', etc.
    action_subtype      TEXT,                  -- optional discriminator
    PRIMARY KEY (ts, action_id)
) PARTITION BY RANGE (ts);

CREATE INDEX idx_meter_actions_agent_ts
    ON meter.actions (agent_id, ts DESC);
CREATE INDEX idx_meter_actions_type_ts
    ON meter.actions (action_type, ts DESC);
```

Action types are checked against an allowlist enforced at write time (`src/services/meter/actions.py:ACTION_TYPES`), not in the DB schema, to allow vocabulary growth without migration.

## Integration

### Pydantic schema

Per code-review §8: existing `handle_outcome_event` does inline validation and has no Pydantic schema. v2 adds the *minimum* schema scope:

- New `src/mcp_handlers/schemas/meter.py` with `ComputeEmissionParams(BaseModel)` and `ActionParams(BaseModel)`. Used by the new `meter_emit` MCP tool (below).
- `outcome_event` does NOT get refactored to a full Pydantic schema. The new optional `compute` field is validated inline alongside the existing inline validation, calling `ComputeEmissionParams.model_validate(arguments["compute"])` and translating Pydantic errors to the existing `error_response` shape. This avoids the unrelated handler-refactor scope expansion.

### MCP tool surface

Two paths into the meter:

1. **Inline on `outcome_event`** — optional `compute` field, for backward-compatible adoption. Fire-and-accept-failure (per code-review §2): `asyncio.wait_for(db.record_compute_emission(...), timeout=2.0)` inside `try/except` that logs and continues. Never extends the 15s outcome budget on failure. Never blocks the `outcome_id` return.

2. **Standalone `meter_emit` tool** — for resident agents and Lumen, which often have no concurrent `outcome_event`. Accepts a `compute_emission` and/or an `actions[]` array. Fire-and-forget from the agent's perspective. Subject to the same 2.0s wait_for budget per insert.

The standalone tool exists because v1's "fold into outcome_event" plan does not work for Steward/Chronicler/Lumen, which produce compute and actions continuously without outcomes. Splitting the surface costs us a second handler but gives the resident substrates a first-class meter path.

### Harness emission

Per code-review §5, dispatch-claude and dispatch-codex do NOT yet capture token usage. v2 promotes that work to **Phase 0**:

- `discord-dispatch/src/backends/claude.ts`: parse `message_delta` events with `usage.input_tokens` / `usage.output_tokens` / cache fields. Accumulate per session.
- `discord-dispatch/src/sessions.ts`: add token accumulator on `SessionState`. Add `recordUsage(usage)` method to `RunnerOutput`.
- On session end OR on each `outcome_event` boundary inside the dispatched session, emit via the new `meter_emit` MCP tool.
- Codex backend: same shape, parsing whatever usage signal the Codex stream protocol exposes (verify per-version; currently unconfirmed). If Codex has no usage signal, dispatch-codex emits `source: 'estimated'` with model_id only and tokens NULL.

Claude Code session (the harness this plan was drafted in) emits via the existing `Stop` hook chain — needs a small addition to the post-session script to read the session usage summary and call `meter_emit`.

### Resident agent emission

- **Steward** (in-process): direct Python call to `db.record_compute_emission(...)` with `substrate='python'`, no MCP round-trip. Lives next to its existing 5-minute Pi→Mac sync.
- **Chronicler** (launchd daily): emits a single per-run summary at end of run. Substrate `python`. Also emits the action counts it generates as part of its existing `metrics.series` writes.
- **Vigil** (launchd 30min): emits per-cycle summary including any sub-dispatched Claude calls (substrate `mixed`).
- **Sentinel** (launchd continuous): emits per-cycle summary; substrate `python`.
- **Watcher** (event-driven): emits on each scan with substrate `local_llm`, model_id `qwen2.5-coder:7b` (or whatever's installed), tokens_in/out from Ollama API response, watt_hours_est from a fixed estimate.
- **Lumen** (Pi-side): the Anima MCP service emits via the standalone `meter_emit` tool over the existing Pi→Mac MCP channel. Sensor reads, GPIO ops, TTS chars, display updates all already counted in anima-mcp internals — needs a small periodic emitter.

This list resolves the v1 blind spot: every agent class has a defined emission path. Some emit `source: 'estimated'`; that's fine and explicit.

## Phasing

| phase | scope | dependencies | risk |
|---|---|---|---|
| 0 | dispatch-claude usage parser; dispatch-codex usage parser (or `source:estimated` fallback); SessionState token accumulator | none | low (TS-only changes, dispatch repo) |
| 1 | `meter` schema migration; `meter.compute_emissions` + `meter.actions` tables; firewall (role denial + contract test); `meter_emit` MCP tool; Pydantic schemas | phase 0 | medium (schema + new tool + contract test) |
| 2 | inline `compute` field on `outcome_event`; resident-agent emission paths (Steward/Chronicler/Sentinel/Vigil/Watcher) | phase 1 | low |
| 3 | Lumen emission via anima-mcp; Pi→Mac channel exercise | phase 1 | medium (cross-process, cross-host) |
| 4 | Chronicler roll-ups into `metrics.series`: per-substrate `tokens_per_action`, `cpu_ms_per_action`, `watt_hours_per_action`; dashboard panes (per-substrate, never combined); calibration view (`complexity` self-report vs measured) | phase 2 + 3 | medium (UI + analysis) |

Phase 0 is the dispatch repo, not unitares. It can ship first and stand alone — dispatch backends emitting usage to logs is useful even before unitares can ingest it. Phases 1–4 are all unitares-side and each shippable in isolation.

## Risks & open questions

1. **Watt-hour estimates are estimates.** No power meter on the Pi or laptops. Lumen's watt-hours are computed as `wall_time_seconds * estimated_watts_for_pi_state`. We carry the estimate explicitly and label it `source: 'estimated'`. Low-precision is acceptable for trend detection; do not present it as ground truth.

2. **Cross-substrate dashboard discipline.** The doctrine "never combine units" is easy to state and easy to violate by a future dashboard PR ("just for the Sankey"). Mitigation: a CSS-level convention that each substrate gets its own card, plus a dashboard linter rule (`<proposed>/scripts/dev/check-dashboard-units.py`) that fails CI if a single chart datapoint sums values across substrate types. Best-effort only — UI conventions can rot.

3. **Watcher's local-LLM tokens.** Ollama returns usage, but cache semantics differ from API Claude. The schema's `cache_read_tokens` / `cache_creation_tokens` fields will be NULL for local-LLM emissions. Acceptable.

4. **Codex usage availability.** Unverified at draft time. If the Codex stream protocol surfaces no usage data, dispatch-codex can only emit `model_id` + `wall_time_ms` + `source: 'estimated'`. Honest, but creates a known gap. Worth filing a separate Codex-side investigation before phase 0 ships.

5. **`meter_emit` is a new tool — calibration drift risk.** Adding any new MCP tool is a small contract risk for clients. Mitigation: tool is optional (no client must call it); failure to register does not break existing clients; documented as observability-only in `docs/dev/TOOL_REGISTRATION.md`.

6. **What about Sentinel's archive of orphan agents?** Sentinel writes events to KG and audit when it archives. Those should emit actions (`kg_write`, `archive_op`) but not compute (Sentinel is pure-Python). The split is clean — actions go to `meter.actions`, no compute row needed. Confirms the two-meter decomposition is right.

7. **Self-reported tokens still allowed.** Some agents may not have harness emission and self-report. `source: 'agent_self_reported'` is preserved as a value but flagged in dashboards. Calibration view (phase 4) can compare self-reported vs harness-emitted for agents that have both.

## What this changes about UNITARES's story

v6.8 promises heterogeneous-fleet governance. The `feedback_eisv-surface-sprawl.md` rule and the v6 §11.6 corpus-maturity caveat both warn against premature axis addition. v2 adds *no* EISV axis. It adds **observability adjacent to** EISV, with the observability layer designed to honor the fleet's actual heterogeneity (substrate, not just model).

For v7 paper work: the *fleet economics* and *substrate-heterogeneity* claims become defensible because there is real data. "Per-token cost dropped 22% over the substrate transition from X to Y" is a paper-worthy claim; "we measure tokens" is not.

For grant-proposal economics (per `feedback_deep-tech-positioning.md`): operator $/verdict is a real number, queryable, with audit lineage. The Schmidt preliminary-data three-pass discipline (`project_schmidt-preliminary-data-three-pass.md`) is honored — verification script can independently rebuild the cost figures from audit.

For Lumen specifically: the embodied substrate stops being structurally invisible to UNITARES's economics layer. Lumen's watt-hours and sensor-reads are first-class. This is the right shape for the eventual Lumen-as-paper-subject angle.

## Council inputs incorporated

From `compute-receipt-sidecar.dialectic-review.md`:
- ✅ "Receipt → meter" reframe
- ✅ Phase 2 dropped (check-in receipts perverse)
- ✅ `complexity` demoted to prediction validated by meter (not promoted)
- ✅ Firewall made architectural (schema + role + contract test)
- ✅ "Distributions, not rankings" — dashboard pane per substrate, never cross-summed

From `compute-receipt-sidecar.code-review.md`:
- ✅ FK dropped; soft join via `(outcome_id, outcome_ts)` plain columns
- ✅ Dispatch usage parser promoted to Phase 0 explicit work
- ✅ `epoch` column added
- ✅ `audit.*` → `meter.*` schema (architectural firewall, also resolves placement issue)
- ✅ `REAL` not `numeric`; cost derived at read-time from versioned rates file
- ✅ Index `(agent_id, ts DESC)` per audit convention
- ✅ Pydantic minimum scope (new schema for meter, no outcome_event refactor)
- ✅ Fire-and-accept-failure with explicit `wait_for(2.0)` budget

## Outstanding decisions for council

1. Is "two meters, never combined" the right ontology, or should there be a third (e.g., a separate "presence" meter for embodied agents)?
2. Is the contract test (AST walk of `governance_core/`) sufficient, or does the firewall need a runtime check too (e.g., a startup assertion that the basin process cannot SELECT from `meter.*`)?
3. Should the rates-file approach for cost (`config/compute_rates.toml`) be paper-trail-versioned in audit, or treated as config? The honest answer probably involves both.
4. Does Phase 0 (dispatch usage parser) need its own dialectic before shipping, given it lands in a different repo?
