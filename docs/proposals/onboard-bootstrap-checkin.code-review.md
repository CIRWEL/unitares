---
title: Code review — onboard-bootstrap-checkin
reviewer: feature-dev:code-reviewer (subagent)
date: 2026-04-25
verdict: implementable-with-amendments — 6 concrete gaps require resolution before code opens; filter-site count is at the council-threshold boundary (7 sites, not "handful"); solo implementation defensible if matview migration risk is acknowledged
---

# Code Review: onboard-bootstrap-checkin.md

All claims verified against live codebase as of 2026-04-25.

---

## Verdict

Implementable, but not cleanly solo yet. The filter-site count lands at 7 verified sites (right at the §8 "escalate if >10" boundary once you include the matview). One site requires a DB schema migration with a matview rebuild — a finding the proposal explicitly defers to "implementation detail." Three additional gaps (concurrent-onboard race, idempotency ambiguity, export-bundle path mismatch) would produce silent correctness bugs if left unresolved. No single finding here warrants a council pass alone; together they warrant a pre-code amendment pass rather than a mid-PR scramble. The "smaller than S19" claim is plausible — S19 was structural (new transport, new module, SDK changes); this is additive columns plus WHERE filters — but it is not comfortable.

---

## Finding 1 — [BLOCKING] Filter-site audit: 7 sites, one requires schema migration

The proposal's §8 threshold is "<10 = solo, >10 = council." The count is 7. That passes the threshold, but the composition matters.

**Confirmed `core.agent_state` read paths that need `synthetic=false`:**

| # | File:line | Function | Risk if unfiltered |
|---|-----------|----------|--------------------|
| 1 | `src/db/mixins/state.py:44` | `get_latest_agent_state()` | Bootstrap row becomes "latest state" forever for a silent agent. Called by `agent_storage.py:120` (get_agent) and `agent_storage.py:466` (list_agents per-identity). Health status reads the bootstrap `state_json`. |
| 2 | `src/db/mixins/state.py:67` | `get_agent_state_history()` | Bootstrap row appears in history. Called by `agent_storage.py:572`. Low direct risk but undermines the "first real check-in timestamp" invariant in §4.5. |
| 3 | `src/db/mixins/state.py:89–118` | `get_all_latest_agent_states()` | **Reads from `core.mv_latest_agent_states` matview with base-table fallback.** Adding `synthetic` to `core.agent_state` and filtering here requires a migration + matview DROP/CREATE. This is the blast-radius expander the proposal doesn't name. |
| 4 | `src/db/mixins/state.py:120–148` | `get_recent_cross_agent_activity()` | `COUNT(*) as count` over recent state rows. A bootstrap row written at hook-fire inflates the neighbor-activity count by 1 for every just-onboarded agent. Sentinel uses this for cross-agent activity heuristics. |
| 5 | `src/db/mixins/tool_usage.py:106–137` | `get_latest_eisv_by_agent_id()` | Called directly by `outcome_event` handler at `src/mcp_handlers/observability/outcome_events.py:94` to snapshot EISV at outcome time. If the bootstrap row is the most recent state when an outcome fires (agent onboards, immediately triggers a test outcome), the correlated EISV is synthetic (confidence=0.5, complexity=0.5). This is the §4.2 "outcome correlation" risk made concrete. |
| 6 | `core.mv_latest_agent_states` matview | (DB object, no Python line) | Must be rebuilt after adding `synthetic` column. On PostgreSQL@17, `ALTER TABLE ... ADD COLUMN synthetic BOOLEAN NOT NULL DEFAULT false` is instant, but the matview rebuild has a brief window where `get_all_latest_agent_states()` falls back to the base table (the existing try/except at `state.py:103`). This is manageable but must be in the migration plan. |
| 7 | `src/auto_ground_truth.py:385,432` | `collect_ground_truth_automatically()` | Queries `audit.events` for `auto_attest` type, not `agent_state` directly. This path is **currently safe by accident** — the exogenous-signal gate at line 432 (`has_exogenous_signals(entry)`) skips any entry without `tests`/`commands`/`files`/`lint` keys, and a bootstrap write presumably won't emit those. But the protection is implicit. The proposal must explicitly state that bootstrap writes MUST NOT emit `auto_attest` audit events. If someone later extends bootstrap context to include a `tests` key, the gate silently fails. |

**What is NOT a filter site:** `total_updates` / `update_count` in `AgentMetadata` and `core.agent_baselines` does NOT come from counting `core.agent_state` rows. It is stored in the identity metadata JSONB blob (`agent_metadata_persistence.py:136`: `total_updates=agent.metadata.get("total_updates", 0)`) and incremented by the monitor loop during `process_agent_update`, not by a state-row insert. The proposal's §4.3 ("trust-tier observation thresholds") concern about `total_updates` is therefore a non-issue — the bootstrap row write does not touch `total_updates`. However, `observation_count` in `trajectory_current`/`trajectory_genesis` metadata (`src/trajectory_identity.py:725`) IS used by `compute_trust_tier` for tier promotion. If the bootstrap row triggers a `store_genesis_signature` call (it shouldn't, but the proposal doesn't specify), that would be a real §4.3 violation.

**Recommendation:** Add matview migration to §8 step 2. The proposal currently reads "State-row tagging (`synthetic`, `source`, `bootstrap_origin` columns or JSONB fields — pick whichever matches existing storage)." The choice is not neutral. See Finding 3.

---

## Finding 2 — [MAJOR] Schema: `Optional[dict]` does not enforce extra-field rejection

**File:** `src/mcp_handlers/schemas/core.py:78` (`ProcessAgentUpdateParams`), `src/mcp_handlers/schemas/mixins.py:4` (`AgentIdentityMixin`)

The proposed `initial_state: Optional[dict]` field is typed as a raw dict. Pydantic v2's default for `BaseModel` (which `AgentIdentityMixin` inherits from at `mixins.py:4`) is `extra='ignore'`, not `extra='forbid'`. A raw dict field accepts any keys without validation — the "4xx-equivalent rejection" the proposal promises at §3.1 does not happen automatically.

The correct implementation is a nested model:

```python
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Literal

class BootstrapStateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_text: Optional[str] = None
    complexity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    task_type: Optional[Literal[
        "convergent", "divergent", "mixed", "refactoring", "bugfix", "testing",
        "documentation", "feature", "exploration", "research", "design", "debugging",
        "review", "deployment", "introspection"
    ]] = None
    ethical_drift: Optional[list[float]] = None
```

With `initial_state: Optional[BootstrapStateParams]` on the onboard params schema, Pydantic rejects extra fields at deserialization before the handler runs. Without this, a caller submitting `initial_state={"synthetic": false}` silently passes the "extra fields rejected" claim — the key is ignored, not rejected — and a future contributor adding a field to `BootstrapStateParams` widens acceptance silently.

The `task_type` Literal must match the exact set at `core.py:122–129` exactly. Copy-pasting is fragile; the proposal should reference the type alias directly.

---

## Finding 3 — [MAJOR] Storage decision: column vs JSONB has a real migration path

The proposal punts "columns vs JSONB fields" to implementation detail. It is not neutral.

**Current schema** (`src/db/mixins/state.py:17–43`): `core.agent_state` has `(identity_id, entropy, integrity, stability_index, volatility, regime, coherence, state_json, epoch)`. `state_json` is JSONB.

**JSONB path:** No column migration. Filter: `(state_json->>'synthetic')::boolean IS NOT TRUE`. Risk: absent key and explicit `false` must both be treated as non-synthetic; JSON type coercion is error-prone; no index unless a partial index on the expression is created; matview still needs rebuilding to project the field.

**Column path:** `ALTER TABLE core.agent_state ADD COLUMN synthetic BOOLEAN NOT NULL DEFAULT false`. On PostgreSQL@17 this is instant (default stored in catalog, not rewritten row-by-row). Filter: `synthetic = false` — clean, index-friendly. Matview must be rebuilt to expose the column.

**Recommendation: column path.** `synthetic` is described as "load-bearing" (§3.2). An indexed boolean column is the right shape for a load-bearing filter key. The matview rebuild is required either way; doing it for a clean column is better than doing it for a JSONB expression index. The migration script must:

1. `ALTER TABLE core.agent_state ADD COLUMN synthetic BOOLEAN NOT NULL DEFAULT false;`
2. `DROP MATERIALIZED VIEW core.mv_latest_agent_states;`
3. Recreate with `synthetic` included.

This must appear in §8 step 2, not in a footnote.

---

## Finding 4 — [MAJOR] Test plan: three missing cases

The 10 tests listed in §7 cover the main paths. Three gaps would allow real correctness bugs to ship undetected:

**Missing: concurrent onboard race (at-most-one-bootstrap invariant).** Tests 1 and 2 cover the sequential case. Two concurrent `onboard(initial_state=...)` calls for the same `agent_uuid` can both pass the "does a bootstrap row exist?" check before either writes, producing two bootstrap rows. This is a real scenario: `scripts/client/onboard_helper.py:38` shows the hook uses per-slot cache files, meaning N parallel `claude` processes in the same workspace each fire their own hook invocation. The proposal does not specify the enforcement mechanism for at-most-one. A DB-level unique partial index `UNIQUE (identity_id) WHERE synthetic = true` is the correct structural fix. Without a test, the constraint can be omitted.

Needed: `test_concurrent_onboard_bootstrap_at_most_one` — two simultaneous onboard calls for the same UUID, assert exactly one bootstrap row after both resolve.

**Missing: export round-trip.** Test 7 checks that "export bundles preserve `synthetic` and `source`." The current export handler at `src/mcp_handlers/introspection/export.py:52` calls `monitor.export_history()`, which reads from the in-memory `UNITARESMonitor.state` history, not from `core.agent_state` DB rows. If the bootstrap row is only in the DB (the in-memory monitor history starts empty for a just-bootstrapped agent), test 7 passes vacuously — the export never sees the bootstrap row. The test must explicitly verify that the DB-sourced state row appears in the export bundle, not just check that the in-memory history round-trips correctly.

**Missing: `synthetic` filter on `get_recent_cross_agent_activity`.** This is finding #4 in the filter-site table and is not covered by any of the 10 tests. A bootstrap-only agent (onboarded, never checked in) currently does not appear in the cross-agent activity window because it has no state rows. After this proposal, it does. The test should assert that a bootstrap-only agent does not appear in `get_recent_cross_agent_activity` results.

---

## Finding 5 — [MAJOR] Idempotency: two underspecified edge cases

**§3.4 is silent on two critical paths:**

**(a) Onboard with `initial_state`, then onboard without it (same UUID, resume).** The second call is a normal resume. Does the response include `bootstrap: {written: false, state_id: "<existing>"}` even when `initial_state` was not in the second call's arguments? If yes, every existing resume response now gains an unexpected `bootstrap` key — that's a de facto API change. If no, the response differs based on whether `initial_state` was supplied, and callers must handle both shapes. The proposal must specify this.

**(b) Onboard without `initial_state`, then onboard with it (bootstrap late-write on resume).** The proposal is silent. If the hook fires on a resumed session (continuity_token in cache), does the bootstrap row get written because `initial_state` is present, even though the agent already has a session? This matters for the §3.5 hook behavior: the hook "SHOULD call onboard with `initial_state`" on every session start, including resumes. If late bootstrap writes are allowed, the at-most-one invariant must cover the resume case too, not just fresh mints. If late writes are disallowed (bootstrap only on identity creation), the proposal must say so.

---

## Finding 6 — [MINOR] Hook integration: DB write inside `handle_onboard_v2` is not anyio-safe by default

The hook fires via `hooks/session-start` with a `--max-time 10` curl timeout (`hooks/session-start:252`). The bootstrap row INSERT is a new DB write inside `handle_onboard_v2` at `src/mcp_handlers/identity/handlers.py:1172`. The existing anyio-deadlock mitigation (CLAUDE.md "Known Issue") requires all new DB writes in handlers to use one of: cached data, `run_in_executor`, or `asyncio.wait_for`. The current `handle_onboard_v2` already has multiple DB awaits in its path (e.g., `ensure_agent_persisted`, `db.upsert_identity`), so it is presumably using the async pool correctly. But the proposal should explicitly state which pattern the bootstrap INSERT uses. Given that bootstrap failure is acceptable (degrade to no bootstrap row, not a crash), `asyncio.wait_for` with a short timeout (500ms, matching the pattern at `src/mcp_handlers/middleware/identity_step.py`) is the correct fit. Without specifying this, the implementer may inadvertently call the DB directly from the handler path and hit the deadlock on startup.

---

## Finding 7 — [NIT] `bootstrap_origin` has one value for the foreseeable lifetime of this spec

§3.2 defines `bootstrap_origin: "onboard"` with a comment `// future: "session-start-hook"`. Since §2 decided that the hook calls `onboard` (not a separate endpoint), `bootstrap_origin` will always be `"onboard"` regardless of whether the call came from the hook. The `"session-start-hook"` value would only materialize if the hook were ever modified to call a separate API surface. This is a premature future-proofing field that adds schema width for zero present discriminating power. Consider removing until a second origin actually exists.

---

## Summary of required amendments before code opens

1. **Filter-site list in §8**: Name all 7 sites explicitly. Add matview migration to step 2 as a non-optional sub-step.
2. **Schema**: Replace `initial_state: Optional[dict]` with a nested `BootstrapStateParams(BaseModel)` using `model_config = ConfigDict(extra="forbid")`.
3. **Storage decision**: Commit to the column path. Add the 3-step migration script (ALTER TABLE → DROP matview → recreate matview) to §8.
4. **Tests**: Add `test_concurrent_onboard_bootstrap_at_most_one`, a DB-round-trip version of `test_export_includes_bootstrap_with_flag`, and `test_cross_agent_activity_excludes_bootstrap`.
5. **Idempotency**: Specify the behavior for cases (a) and (b) in §5 above, and confirm whether the at-most-one invariant applies to resume calls as well as fresh mints.
6. **anyio pattern**: Specify `asyncio.wait_for` with a short timeout for the bootstrap INSERT in §8 step 1.

---

## Verified file:line citations

- `src/db/mixins/state.py:17–165` — `StateMixin`, all read paths, matview query
- `src/db/mixins/tool_usage.py:106–137` — `get_latest_eisv_by_agent_id`
- `src/mcp_handlers/observability/outcome_events.py:94` — `get_latest_eisv_by_agent_id` call site
- `src/auto_ground_truth.py:385, 432` — audit-event query, exogenous-signal gate
- `src/mcp_handlers/schemas/core.py:78–157` — `ProcessAgentUpdateParams`, Pydantic v2, no `extra='forbid'`
- `src/mcp_handlers/schemas/mixins.py:4` — `AgentIdentityMixin(BaseModel)`, no `ConfigDict`
- `scripts/client/onboard_helper.py:38, 153–188` — hook's onboard payload construction, slot behavior
- `hooks/session-start:252–257` — `--max-time 10` curl timeout
- `src/mcp_handlers/introspection/export.py:52` — in-memory monitor history export (not DB rows)
- `src/agent_storage.py:120, 466` — `get_latest_agent_state` call sites in storage layer
- `src/agent_metadata_persistence.py:136` — `total_updates` from JSONB metadata, not row count
- `src/trajectory_identity.py:692–776` — `compute_trust_tier`, `observation_count` source
- `src/mcp_handlers/identity/handlers.py:1172` — `handle_onboard_v2` entry point
