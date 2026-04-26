---
title: Code review (round 3) — compute-meter-v2.1
reviewer: feature-dev:code-reviewer (subagent)
date: 2026-04-25
verdict: build, with five in-PR fixes (no v3 needed)
prior reviews:
  - docs/proposals/compute-receipt-sidecar.code-review.md (round 1)
  - docs/proposals/compute-meter-v2.code-review.md (round 2)
---

# Code Review (Round 3): compute-meter-v2.1.md

All claims grounded in file:line citations from the live codebase as of 2026-04-25.

## 1. Partition machinery — peer task is the right call

**Verdict: clean.** `src/background_tasks.py:206-218` shows `periodic_partition_maintenance` is self-contained. Adding `periodic_meter_partition_maintenance` as a peer matches the existing pattern at `start_all_background_tasks:1083` (flat list of `_supervised_create_task(...)` calls). SQL body in v2.1 mirrors `audit.partition_maintenance()` correctly.

**Small gap:** v2.1 doesn't specify a startup delay. Existing partition task uses `await asyncio.sleep(60.0)` before entering the loop, ensuring the DB pool is initialized. The meter task PR should mirror this.

## 2. `run_in_executor` precedent is WRONG — no sync DB client exists (Confidence: 100) — BLOCKING

The most concrete implementation gap remaining in v2.1.

v2.1 cites `verify_agent_ownership at src/agent_loop_detection.py:374` as the `run_in_executor + sync DB client` precedent. Verified at `src/agent_loop_detection.py:373-376`:

```python
loop = asyncio.get_running_loop()
is_valid, error_msg = await loop.run_in_executor(
    None, verify_agent_ownership, agent_id, api_key, session_bound
)
```

`verify_agent_ownership` (`src/agent_identity_auth.py:204-234`) is **a pure-Python in-memory function** — reads a module-level `agent_metadata` dict, calls `secrets.compare_digest`, returns a tuple. NO DATABASE ACCESS. This is CPU-bound work pushed to an executor — not a "sync DB client" pattern.

`src/db/__init__.py:40-53` exports only `get_db()` returning asyncpg-based `PostgresBackend`. No `sync_backend.py`, no psycopg2/psycopg3 wrapper, no `SyncPostgresBackend`. The only sync DB path in the codebase is `SyncGovernanceClient` (REST transport in the SDK) — not applicable to in-process handlers.

**Fix:** Replace v2.1 §Integration text:

> The `meter_emit` handler uses `asyncio.wait_for(db.record_meter_emission(...), timeout=2.0)` with a `try/except` that logs and continues — pattern 3 from CLAUDE.md. The `run_in_executor` precedent was cited in error; `verify_agent_ownership` is an in-memory function, not a DB call.

This is the single most important amendment.

## 3. AST contract test feasibility — confirmed

`governance_core/` inventory: `dynamics.py`, `coherence.py`, `parameters.py`, `scoring.py`, `utils.py`, `ethical_drift.py`, `adaptive_governor.py`, `phase_aware.py`, `research.py`, `stability.py`, `__init__.py`. All examined: imports only from within `governance_core/` itself or stdlib. No dynamic imports. `from __future__ import annotations` in `parameters.py:10-14` is stdlib.

AST walk for `Import`/`ImportFrom` containing `"meter"` will not produce false positives. Bound v2.1 acknowledges (data-flow blind) is correct.

**Forward-looking note:** The test should walk `governance_core/**/*.py` (recursively). Currently no subdirectories — but glob recursion should be confirmed in the implementation PR.

## 4. Layer 3 startup assertion — insertion point ambiguous (Confidence: 80)

v2.1 says "at `src/governance_monitor.py` initialization, before the basin solver task starts." Verified `UNITARESMonitor.__init__` at `src/governance_monitor.py:115-178` has NO async context. A `SELECT` is impossible there.

**Fix:** Specify the insertion point explicitly — either a startup background task or the server lifespan coroutine in `mcp_server.py`. "governance_monitor.py initialization" is not a callable-from-async context as written.

Testability: yes, once the insertion point is defined. Mock `get_db().acquire()`, confirm WARN fires, assert future flag flips to ERROR.

## 5. `AgentIdentityMixin` — contract verified

`src/mcp_handlers/schemas/mixins.py` (18 lines): `AgentIdentityMixin(BaseModel)` exists with `continuity_token: Optional[str]`, `client_session_id: Optional[str]`, `agent_id: Optional[str]`. All default `None`.

Pydantic v2 + Literal: no gotcha. `class ComputeEmissionParams(AgentIdentityMixin):` with `substrate: Literal[...]` works correctly. Field-set merging is automatic. The proposal's snippet inheriting only from `AgentIdentityMixin` (not also `BaseModel`) is correct.

## 6. `TOOLS_NEEDING_SESSION_INJECTION` — FOURTH registration file (Confidence: 100)

v2.1 overclaims that `AgentIdentityMixin` inheritance makes session injection automatic. **It does not.**

`src/mcp_server.py:325-348` defines `TOOLS_NEEDING_SESSION_INJECTION` as a hardcoded set of 20 tool names. `mcp_server.py:404`:
```python
inject_session = tool_name in TOOLS_NEEDING_SESSION_INJECTION
```

This is purely **name-based**. Schema inheritance has zero effect on this path. Tools whose schemas inherit `AgentIdentityMixin` but whose names are absent from the set will not get FastMCP `Context`-driven `client_session_id` injection.

**Fix:** Add `"meter_emit"` to `TOOLS_NEEDING_SESSION_INJECTION` at `src/mcp_server.py:325`. Phase 1 checklist becomes FOUR files, not three:
1. `src/tool_schemas.py:TOOL_ORDER`
2. `src/tool_schemas.py:_load_pydantic_schemas`
3. `src/tool_modes.py:LITE_MODE_TOOLS`
4. **`src/mcp_server.py:TOOLS_NEEDING_SESSION_INJECTION`** (new)

## 7. Resident-agent emission paths — three corrections

### Chronicler / Watcher: use generic `client.call_tool("meter_emit", ...)`

`GovernanceClient` exposes named methods: `checkin()`, `search_knowledge()`, `leave_note()`, `audit_knowledge()`, `cleanup_knowledge()`, `self_recovery()`. **No `meter_emit()` method.**

Implementation must use the generic dispatch: `client.call_tool("meter_emit", {...})`. Works fine; v2.1 should specify this explicitly so implementers don't search for a named method that doesn't exist.

### Vigil substrate is `python`, NOT `mixed` (Confidence: 100) — BLOCKING SPECIFICATION ERROR

v2.1 says: "Vigil — pure-Python supervisory loop that may dispatch a Claude API call for hard sub-tasks. Each cycle emits one row with substrate `mixed`, populating both `cpu_time_ms` and `tokens_in/out`."

Verified `agents/vigil/agent.py` (full 555 lines) and `agents/vigil/checks/`: NO `anthropic` import, NO httpx POST to Anthropic API, NO Ollama call, NO call-model invocation. `run_cycle` runs health checks (HTTP), optional pytest (subprocess), optional KG audit (MCP), and posts a check-in (MCP).

**Fix:** Vigil substrate is `python`. `tokens_in/out` will always be NULL. The `mixed` substrate is correctly reserved for hypothetical future Vigil enhancements that dispatch LLM sub-tasks — that requires its own proposal.

### Watcher token extraction

Ollama's `/v1/chat/completions` response includes `usage.prompt_tokens` / `usage.completion_tokens`. Watcher can populate `tokens_in/tokens_out` from this. `model_id` from configured Ollama model name. `wall_time_ms` from cycle timing. `watt_hours_est` from fixed estimate (`source: 'estimated'` for the watt portion).

## 8. Phase 0 dispatch — `result.usage` field path

v2.1's `type === "result"` correction is right directionally. Phase 0 PR should extract:
- `event.usage.input_tokens`
- `event.usage.output_tokens`
- Optional `event.usage.cache_read_input_tokens` / `event.usage.cache_creation_input_tokens`

v2.1 says "extract `usage` block" without field names — sufficient for discovery, not for drop-in implementation. The dispatch PR description should include exact field paths.

## 9. `periodic_meter_partition_maintenance` — no name collision

`src/background_tasks.py` has no function with that name. Existing task is `periodic_partition_maintenance:206`. `start_all_background_tasks:1066` registers it under name `"partition_maintenance"`. New task name `"meter_partition_maintenance"` — no collision with any function name, task name, or `_RESTARTABLE_TASK_FACTORIES` key.

## 10. What v2.1 still misses

### Carry-forward (round 2 #4)
v2.1's three-file `meter_emit` registration checklist is correct as far as it goes — but it MISSES the fourth file (`TOOLS_NEEDING_SESSION_INJECTION`, §6 above). Round 2 didn't catch this either; v2.1 inherited the gap.

### New: async DB pattern
v2.1 introduces `run_in_executor + sync client` claim that cannot be implemented without new infrastructure (§2 above). Must switch to `wait_for` pattern 3.

### New: `epoch` source for REST callers
`meter.compute_emissions` has `epoch INTEGER NOT NULL`. v2.1 doesn't specify where the value comes from for resident agents calling via REST. For interactive MCP sessions, derivable from agent's EISV state. For Chronicler / Watcher / `eisv-sync-task` calling REST, epoch is not in their execution context.

**Fix:** Specify either (a) caller-supplied with SDK helper to retrieve current epoch, or (b) server-side default from `GovernanceConfig.CURRENT_EPOCH` in the handler. Without this, implementers will hardcode `epoch=0` or fail validation.

## 11. Single highest-impact change before shipping

The `run_in_executor` + sync DB client claim is the only structural gap in v2.1 that requires infrastructure that does not exist and has no specified build path. The cited precedent (`verify_agent_ownership`) is an in-memory function, not a DB call. If the implementation PR opens tomorrow, the first engineer to look for the sync client will either invent an undocumented psycopg2 path, fall back to pattern 3 without telling anyone, or block on the question. **One sentence amendment removes this:**

> "The `meter_emit` handler uses `asyncio.wait_for(db.record_meter_emission(...), timeout=2.0)` with a `try/except` that logs and continues — pattern 3 from CLAUDE.md. The `run_in_executor` precedent was cited in error; `verify_agent_ownership` is an in-memory function, not a DB call."

Every other gap can be resolved in PR. This one is structurally specified wrong.

## 12. Verdict: implementable, no v3 needed

v2.1 is implementable without v3, but requires five in-PR fixes:

1. **`TOOLS_NEEDING_SESSION_INJECTION`** — add `"meter_emit"` at `src/mcp_server.py:325`. Fourth file in Phase 1 checklist.
2. **Async DB pattern** — replace `run_in_executor + sync client` with `asyncio.wait_for` (pattern 3). Cited precedent is in-memory, not DB.
3. **Vigil substrate** — `python` not `mixed`. No LLM dispatch exists.
4. **Layer 3 insertion point** — explicit: background task or server lifespan, not `UNITARESMonitor.__init__`.
5. **`epoch` source for REST callers** — caller-supplied (with SDK helper) OR server-defaulted.

None require structural iteration. All are one-line or one-paragraph amendments. Author can emit v2.1.1 patch or capture in PR description.

## Verified file:line citations

- `src/background_tasks.py:206-218, 1066-1118` — partition task pattern
- `src/agent_loop_detection.py:373-376` — `run_in_executor` call (in-memory, not DB)
- `src/agent_identity_auth.py:204-234` — `verify_agent_ownership` (no DB access)
- `src/db/__init__.py:40-53` — asyncpg-only `PostgresBackend`; no sync client
- `src/db/postgres_backend.py:67-72, 290` — single pool, no sync; `search_path` (correct fix as proposed)
- `src/mcp_handlers/schemas/mixins.py:1-17` — `AgentIdentityMixin` fields confirmed
- `src/mcp_server.py:325-348, 404` — `TOOLS_NEEDING_SESSION_INJECTION` name-based, not schema-based
- `src/governance_monitor.py:115-178` — `UNITARESMonitor.__init__` no async context
- `governance_core/dynamics.py:31-37`, `parameters.py:10-14` — intra-package + stdlib only
- `agents/vigil/agent.py:1-555` — no LLM API calls; substrate is `python`
- `agents/chronicler/agent.py:127-188`, `agents/watcher/findings.py:36` — generic `call_tool` path required
