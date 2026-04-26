---
title: Code review (round 2) — compute-meter-v2
reviewer: feature-dev:code-reviewer (subagent)
date: 2026-04-25
status: blocking issues found (different from round 1)
---

# Code Review (round 2): compute-meter-v2.md

Reviewing `/Users/cirwel/projects/unitares/docs/proposals/compute-meter-v2.md` against the live codebase. Round-1 issues (raised against v1) not repeated here.

## 1. New `meter.*` schema — `search_path` does not include it (Confidence: 95)

`src/db/postgres_backend.py:290`:
```python
await conn.execute(f"SET search_path = ag_catalog, core, audit, public")
```
`meter` is absent. Bare `INSERT INTO compute_emissions ...` will fall through to `public`. Existing mixins all use fully-qualified names (`audit.outcome_events`, `core.agents`), so this is a pattern issue rather than certain failure — but the migration must document that all `meter.*` queries are schema-qualified, AND `meter` should be added to `search_path` defensively.

**Fix:** Add `meter` to `search_path`; require schema-qualified DDL/DML in the new mixin.

## 2. Role-level SELECT denial — `governance_core_runtime` role does not exist; basin solver shares the MCP server's connection pool (Confidence: 100) — BLOCKING

The most significant structural gap in v2.

`src/db/postgres_backend.py:72` reads `DB_POSTGRES_URL` (default `postgresql://postgres:postgres@localhost:5432/governance`). Single asyncpg pool. There is no `governance_core_runtime` role anywhere in `schema.sql`, `partitions.sql`, the migrations, or any mixin code.

`src/governance_monitor.py:52-59` imports from `governance_core` and calls `step_state`, `coherence` directly in Python. `governance_core/dynamics.py` is pure Python — no DB access at all. The basin solver runs as Python calls inside the MCP server process, using the same `get_db()` singleton as every handler.

**There is no separate process, no separate role, no separate connection pool for the basin solver.** The proposal's "basin solver process connects as this role" describes process isolation that does not exist and would require substantial architectural work:
- Either split `governance_core` into a subprocess with its own credentials, OR
- Wire `governance_core` calls through a dedicated connection acquired under a restricted role — which requires restructuring; `step_state` etc. currently take `State` objects as input, not DB context.

**Fix options:**
- (a) Scope role firewall to a future phase that adds process isolation
- (b) Drop the role layer; rely on schema separation + AST contract test as two-layer enforcement
- (c) Specify the connection-pool split work as Phase 1 prerequisite (significant scope expansion)

Files: `src/db/postgres_backend.py:72`, `src/governance_monitor.py:52-59`, `schema.sql` (no role).

## 3. AST contract test — realistic but bounded (Confidence: 88)

`governance_core/` confirmed at top level. `dynamics.py` imports only from `.parameters`, `.utils`, `.coherence` — no `src/` imports. AST walk for `meter` references is meaningful and will not be noisy.

Limit: AST scan catches imports, not data flow. A future PR that passes a meter-derived value as an argument to `State` or `Theta` defeats the test silently. The test is necessary but not sufficient. Document this as the bound, not as the guarantee.

## 4. `meter_emit` registration — THREE files, not one (Confidence: 92)

Per `docs/dev/TOOL_REGISTRATION.md:74, 82-148`:

1. `src/tool_schemas.py:TOOL_ORDER` (line 82-149) — must add `meter_emit`. Tools absent are not exposed.
2. `src/tool_schemas.py:_load_pydantic_schemas` (line 33-47) — hardcoded module list. `meter.py` silently ignored unless `"src.mcp_handlers.schemas.meter"` is appended to `mods`.
3. `src/tool_modes.py:LITE_MODE_TOOLS` — `TOOL_MODE=lite` is default; tools absent from this set are filtered by `auto_register_all_tools()` at `mcp_server.py:398`.

Missing any of the three: tool either invisible in `list_tools` or not callable, with no clear error.

**Fix:** Phase 1 checklist must enumerate all three.

## 5. Resident-agent emission paths — most are wrong

**Steward — not in-process where the proposal thinks (Confidence: 90)**

No `src/steward.py`, no `agents/steward/`, no Steward task in `background_tasks.py:1066-1118` (heartbeat, auto_calibration, concept_extraction, matview_refresh, partition_maintenance, etc. — no `eisv_sync`/`steward`). Memory says "Steward — in-process in governance-mcp; Pi→Mac EISV sync every 5min" — only a comment reference at line 966. Steward may have been removed, renamed, or live in the Pi plugin.

**Fix:** Verify Steward's actual location before committing to direct-DB path.

**Chronicler — HTTP/MCP only, no DB handle (Confidence: 100)**

`agents/chronicler/agent.py:60-80, 144-146`: `httpx.Client` for REST, `GovernanceAgent`/`GovernanceClient` for governance. No `asyncpg`. Proposal says "direct Python call to `db.record_compute_emission(...)`" — wrong. Chronicler must call `meter_emit` via MCP/REST.

**Watcher — SyncGovernanceClient REST only (Confidence: 100)**

`agents/watcher/agent.py:27-38, 133-156`: REST transport only. Same correction as Chronicler — must use `meter_emit`.

**Lumen — Pi→Mac is outbound HTTP, not bidirectional MCP (Confidence: 95)**

`anima-mcp/CLAUDE.md` confirms: broker calls `UNITARES_URL=http://<tailscale-ip>:8767/mcp/` to check in. The connection is broker→governance (Pi→Mac outbound HTTP). For Lumen to call `meter_emit`, anima-mcp's `unitares_bridge.py` needs modification — that's a separate-repo PR (anima-mcp), distinct from unitares Phase 3.

**Fix:** Phase 3 description must specify "anima-mcp PR required" not just "Pi→Mac channel exercise."

## 6. Pydantic schema — `meter_emit` needs `AgentIdentityMixin` (Confidence: 85)

Existing pattern: agent-data schemas inherit `AgentIdentityMixin` (in `mixins.py`), carrying `continuity_token`/`client_session_id`/`agent_id`. The middleware identity injection (`identity_step.py`, `context.py:get_context_agent_id()`) depends on this.

If `ComputeEmissionParams` skips `AgentIdentityMixin`, `agent_id` doesn't get injected by middleware automatically; `TOOLS_NEEDING_SESSION_INJECTION` would need updating too.

**Fix:** Specify inheritance from `AgentIdentityMixin` (or document why not).

## 7. anyio-asyncio — local CLAUDE.md tightens the rule the proposal cites (Confidence: 88)

`.claude/CLAUDE.md` (machine-local overlay): "Any new MCP handler that needs DB access must either read cached data or use `run_in_executor` with a sync client — do not `await` asyncpg directly from a handler."

Main `CLAUDE.md` lists `asyncio.wait_for` as Option 3 (with fallback note). Local overlay tightens to "do not await asyncpg directly." The proposal's `asyncio.wait_for(db.record_compute_emission(...), timeout=2.0)` IS awaiting asyncpg directly.

**Fix:** Either revert to executor pattern (preferred per local overlay), or note the tension and justify `wait_for` here.

## 8. Partition maintenance — `audit.partition_maintenance()` will NOT auto-handle `meter.*` (Confidence: 100) — BLOCKING SILENT DATA LOSS

`partitions.sql:280-335`. Function hardcodes three families: `audit.events`, `audit.tool_usage`, `audit.outcome_events`. No generic mechanism. Every new partitioned table requires:
1. `meter.create_compute_emissions_partition()`
2. `meter.create_actions_partition()`
3. Extension to `audit.partition_maintenance()` (or new `meter.partition_maintenance()`)
4. Bootstrap DO block extension (`partitions.sql:357-371`)

`background_tasks.py:206-218` calls `audit.partition_maintenance()` weekly — won't touch `meter.*`. Once initial partitions roll past, every `meter_emit` insert fails with "no partition of relation found." Because the proposal wraps inserts in `try/except` (fire-and-accept-failure), the failure is **silently swallowed**. Meter data stops accumulating with no visible breakage — only "tables are empty after month boundary."

**Fix:** Phase 1 migration MUST include the two partition-creation functions, the maintenance hook, and the 3-month bootstrap. ~60 lines of SQL not currently in the proposal.

## 9. Phase 0 in dispatch — Claude Code stream format ≠ Anthropic API (Confidence: 90)

`discord-dispatch/src/backends/claude.ts` confirmed: handles `type === "assistant"`, no `usage` extraction.

But: Claude Code's `--output-format stream-json` is NOT the Anthropic Messages API streaming format. It does NOT use `message_delta` events. Token usage in Claude Code stream-json appears in `type: "result"` messages under a `usage` key.

**Fix:** Verify Claude Code stream-json schema before implementing. The proposal's `message_delta` reference is from the API spec, not the CLI spec.

`codex.ts`: confirmed no usage in exposed event types. Likely permanent limitation — codex CLI doesn't expose token counts. `source: 'estimated'` is correct, but should be marked permanent not "gap to close later."

## 10. Dashboard linter — does not exist; cannot exist against current dashboard (Confidence: 100)

`scripts/dev/check-dashboard-units.py` doesn't exist. Dashboard is free-form JS in `dashboard/*.js` — no JSON/YAML config. A static linter detecting cross-substrate sums in arbitrary JavaScript Chart.js construction would require either a JS-AST analyzer (significant) or a declarative config format that replaces current JS construction (substantial dashboard refactor).

The proposal's framing implies a concrete deliverable that cannot be built against the current dashboard. Drop to "CSS convention + code review" or scope a dashboard-config-format proposal.

## 11. Single highest-impact change

**The partition maintenance gap will cause silent data loss in production.** `audit.partition_maintenance()` hardcodes three table families; the new `meter.*` partitioned tables are invisible to it. Initial partitions will be created at migration time; inserts succeed for current month and look-ahead. When the calendar rolls past, every `meter_emit` call fails with "no partition of relation found." Because meter inserts use fire-and-accept-failure (`try/except`), failures are swallowed silently. Meter data stops accumulating with no visible breakage — extremely difficult to diagnose months later. Phase 1 must include `meter.create_compute_emissions_partition()`, `meter.create_actions_partition()`, an extension to `partition_maintenance()`, and a 3-month initial bootstrap DO block — all in the same migration PR as the table DDL.

## Verified Files

- `db/postgres/schema.sql` — schemas: `core`, `audit` only
- `db/postgres/partitions.sql:280-335, 357-371` — `partition_maintenance()` hardcodes 3 families
- `db/postgres/migrations/004_outcome_events.sql`
- `src/db/postgres_backend.py:72, 290` — single DB_POSTGRES_URL, search_path excludes `meter`
- `src/governance_monitor.py:52-59` — `governance_core` in-process
- `governance_core/__init__.py`, `governance_core/dynamics.py` — pure Python, no DB
- `src/background_tasks.py:206-218, 1066-1118` — partition_maintenance weekly, hardcoded; no Steward
- `src/mcp_server.py:72, 290, 325-431, 398` — single pool, `auto_register_all_tools`
- `src/tool_schemas.py:33-47, 82-149` — registration triplet
- `src/tool_modes.py:33-60` — LITE_MODE_TOOLS
- `docs/dev/TOOL_REGISTRATION.md:74, 82-148`
- `src/mcp_handlers/decorators.py:37-139`
- `src/mcp_handlers/observability/outcome_events.py:42-297`
- `src/mcp_handlers/schemas/{mixins,identity}.py`
- `src/mcp_handlers/middleware/identity_step.py:1-120`
- `agents/chronicler/agent.py:56-170` — HTTP only
- `agents/watcher/agent.py:1-160` — REST only
- `discord-dispatch/src/backends/{claude,codex,types}.ts`, `sessions.ts:19-32`
- `anima-mcp/CLAUDE.md` — broker outbound HTTP only
- `dashboard/index.html` — free-form JS
