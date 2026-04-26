---
title: Code review — compute-receipt-sidecar proposal
reviewer: feature-dev:code-reviewer (subagent)
date: 2026-04-25
status: blocking issues found
---

# Code Review: compute-receipt-sidecar.md

Reviewing `/Users/cirwel/projects/unitares/docs/proposals/compute-receipt-sidecar.md` against the live unitares + discord-dispatch codebases.

## Critical Issues

### 1. The FK target does not exist — `outcome_event.id` is a partitioned composite key, not a standalone UUID column (Confidence: 100)

The proposal says: "event_id | uuid | fk → outcome_event.id"

The actual table definition is in `db/postgres/migrations/004_outcome_events.sql`:

```sql
CREATE TABLE IF NOT EXISTS audit.outcome_events (
    ts              TIMESTAMPTZ NOT NULL,
    outcome_id      UUID NOT NULL DEFAULT gen_random_uuid(),
    ...
    PRIMARY KEY (ts, outcome_id)
) PARTITION BY RANGE (ts);
```

There is no column named `id`. The primary key is composite `(ts, outcome_id)` — and it is on a partitioned table. PostgreSQL prohibits foreign keys that reference partitioned tables entirely (the referenced table must not be partitioned). This is not a schema-naming mismatch fixable by renaming `event_id` to `outcome_id`. The FK as designed cannot be created at all.

**Fix required:** Drop the FK. Store `outcome_id UUID` and `outcome_ts TIMESTAMPTZ` as plain columns on `compute_receipts` so the receipt joins the outcome event with `JOIN audit.outcome_events e ON e.outcome_id = r.outcome_id AND e.ts = r.outcome_ts`, but without a declarative FK. Document this explicitly in the proposal and the migration DDL. The "sidecar joined by FK" framing is wrong for this schema.

Files: `db/postgres/migrations/004_outcome_events.sql:6-25`; proposal Storage table, "event_id" row.

### 2. anyio-asyncio constraint: `record_outcome_event` already `await`s asyncpg directly — the sidecar insert must follow the same pattern, and the proposal doesn't name it (Confidence: 90)

`CLAUDE.md`: "Any new MCP handler that needs DB access must use cached / executor / wait_for+fallback."

`handle_outcome_event` (`src/mcp_handlers/observability/outcome_events.py:94, 227`) already calls `await db.get_latest_eisv_by_agent_id(...)` and `await db.record_outcome_event(...)`. It satisfies the rule via the `@mcp_tool("outcome_event", timeout=15.0)` decorator (`src/mcp_handlers/decorators.py:91-94`), which wraps the handler in `asyncio.wait_for`. So pattern 3 is the implicit insulator.

The proposal puts the sidecar insert inside the same handler. Fine — it rides inside the existing `wait_for` budget. But the proposal doesn't acknowledge this, and the 15-second budget already absorbs EISV fetch + confidence resolution + calibration write + outcome insert. A second `INSERT INTO compute_receipts` that fails silently is acceptable iff its failure path returns early and never blocks the `outcome_id` return.

**Fix:** Wrap the compute insert in `asyncio.wait_for(db.record_compute_receipt(...), timeout=2.0)` with `try/except` that logs and continues. Make it explicit: compute insert is fire-and-accept-failure.

### 3. `numeric(10,4)` for `cost_usd` — no other `numeric` columns exist in this schema (Confidence: 85)

Every money-adjacent value in this codebase is `REAL` or `FLOAT` — `outcome_score REAL`, `eisv_e REAL`, `eisv_phi REAL` throughout `004_outcome_events.sql` and `schema.sql`. There are no `NUMERIC`/`DECIMAL` columns anywhere. Introducing one means asyncpg deserializes to `Decimal`, requiring an explicit `float()` cast in every reader.

**Fix:** Use `REAL` (or `DOUBLE PRECISION` if precision matters). Document the tradeoff in the migration comment.

### 4. Index shape mismatch — `(agent_id, created_at)` should be `(agent_id, created_at DESC)` per audit-schema convention (Confidence: 85)

`db/postgres/partitions.sql:49` establishes `(agent_id, ts DESC)` as the standard. `004_outcome_events.sql:28` follows it. Per-agent burndown queries always read newest-first; missing `DESC` forces backward scans.

**Fix:** `(agent_id, created_at DESC)`.

### 5. Dispatch harnesses have no token data at the `outcome_event` boundary — Phase 1 emission claim is unsupported (Confidence: 90)

Proposal Phase 1: "dispatch-claude and dispatch-codex plists already capture per-call usage; they emit it on the outcome_event boundary."

Actual: `discord-dispatch/src/backends/claude.ts` processes `--output-format stream-json` line by line, handles `type === "assistant"` and `tool_use`. `codex.ts` handles `thread.started`, `agent_message`, `command_execution`. Neither parses `usage` blocks (`message_delta` with `usage.input_tokens`/`usage.output_tokens`). `sessions.ts` has no token accumulator. The `RunnerOutput` interface has no `recordUsage` method.

Dispatch does not "already capture per-call usage." Phase 1 requires adding a usage parser to `claude.ts` and a token accumulator to `SessionManager` before any emission is possible. **Real work, not wiring.**

**Fix:** Revise Phase 1 scope to include "add Claude stream usage-block parser to dispatch-claude" and "add token accumulator to SessionManager."

### 6. Schema placement: `compute_receipts` defaults to `public`, inconsistent with two-schema layout (Confidence: 85)

Codebase convention (`db/postgres/schema.sql:1-9`): `core.*` operational, `audit.*` time-series. `outcome_events` is `audit.*`. Per-event data belongs in `audit`.

**Fix:** `audit.compute_receipts` in DDL and all references.

### 7. No `epoch` column — every audit-schema table with agent data carries `epoch` (Confidence: 80)

`record_outcome_event` (`src/db/mixins/tool_usage.py:69-70`) passes `GovernanceConfig.CURRENT_EPOCH` as a 15th parameter. `agent_baselines` (`005_agent_baselines.sql:16`) has `epoch`. State queries filter on `s.epoch = $2`. When Phase 2 of EISV grounding swaps the epoch, receipt queries will lose per-epoch separation.

**Fix:** Add `epoch INTEGER NOT NULL DEFAULT <current>` to `compute_receipts` and populate it at insert time.

### 8. Pydantic schema convention — no schema file exists for `outcome_event` parameters (Confidence: 80)

Proposal: "validates with a Pydantic schema in `src/mcp_handlers/schemas/`." No `outcome_event.py` exists there (only `dialectic.py`, `identity.py`, `mixins.py`). Current `handle_outcome_event` does inline validation. Adding `ComputeReceiptParams` as a nested Pydantic model would be the first nested model in this codebase — works in Pydantic v2 but forces a choice: (a) full handler refactor to `OutcomeEventParams(AgentIdentityMixin)` with nested `compute`, or (b) inline validation.

**Fix:** Pick (a) and account for the handler refactor in scope, or (b) and note `ComputeReceiptParams` is DB-layer only.

### 9. AGE interaction — no issue (Confidence: 95)

`compute_receipts` is plain relational. AGE operates on `governance_graph` in `ag_catalog`. `search_path` (`postgres_backend.init():290`) already includes `audit`. No triggers or catalog hooks affect non-graph tables.

## Single Highest-Impact Change

**Drop the FK.** "Joined by FK → outcome_event.id" is the load-bearing assumption — and PostgreSQL prohibits FK references to partitioned tables. Replace with soft reference (`outcome_id UUID, outcome_ts TIMESTAMPTZ` stored as plain columns, joined explicitly). Document that `compute_receipts` cannot enforce referential integrity at the DB layer and relies on application-level consistency: handler inserts the receipt with the same `outcome_id` just returned by `record_outcome_event`, within the same request boundary. The failure mode (outcome insert succeeds, receipt insert fails) must be specified — fix-before-code, not fix-in-migration-PR.

## Verified Files

- `db/postgres/migrations/004_outcome_events.sql`
- `db/postgres/partitions.sql:49, 109-151`
- `db/postgres/schema.sql:1-9, 296-353`
- `src/db/mixins/tool_usage.py:43-80`
- `src/mcp_handlers/observability/outcome_events.py:42, 94, 227`
- `src/mcp_handlers/decorators.py:91-94`
- `src/mcp_handlers/schemas/{mixins,dialectic,identity}.py`
- `discord-dispatch/src/backends/{claude,codex}.ts`
- `discord-dispatch/src/sessions.ts`
