# S21-b — Auth Consistency (Item 3 of the S21-b backlog)

**Status:** Implementation merged. Branch `s21b/auth-consistency`. Closes H14 from the S21-a pass-2 council review (`s21-fix-council-review.md`).

**Origin.** Pass-2 H14 named `require_registered_agent` consulting only the in-memory `agent_metadata` dict as an axiom-#3 violation: post-S21-a `identity()` returns the resumed UUID correctly, but two calls later the auth check rejected the same UUID as "not registered" because the dict had not been hydrated. "The system presents a partial recovery that lies about its own state."

## Pre-implementation council pivot

Closed-set pre-impl framing offered two options:

- **(a)** DB fallback in `require_registered_agent` via `run_in_executor` with a sync client.
- **(b)** Eager-hydrate the dict at every fresh-identity write site.

Council pivoted to **(b) + status gate + reconciler** because:

1. **(a) was larger than it appeared.** No sync PG client exists in this repo (`src/db/__init__.py` returns `PostgresBackend` with all methods async). (a) would have required building a new sync client + connection pool just to be callable from `run_in_executor`.
2. **The "missing from dict" framing was the wrong magnitude.** Live-verifier ground-truth: 1 row, not 67. The actual auth-relevant surface was the **67-row `core.identities.status='active'` / `core.agents.status='archived'` inversion** that neither (a) nor (b) addresses on its own. The dict is loaded from `core.agents`; without a status gate inside the auth check, a stale-active dict entry passes auth even when identity says archived.
3. **Dialectic opened option (c)** — collapse to a single DB-fronted source with a read-through cache owned by the auth module — as the structural fix. **Explicitly deferred** to a follow-up PR with its own council. Rationale: (c) reproduces the dual-source problem at a different boundary unless the chokepoint is a single typed `set_agent_status(uuid, status)` that updates `core.identities`, `core.agents`, and the in-memory dict atomically. That refactor touches every status-write path and warrants its own scope.

## What this PR ships

**Code changes:**

- `src/mcp_handlers/support/agent_auth.py` — allowlist gate inside `require_registered_agent` accepting only `{active, paused, waiting_input}` (council pass-2 dialectic: blocklist is fail-open on unknown future status).
- `src/agent_metadata_persistence.py` — two new helpers:
  - `register_minted_agent_in_dict(agent_uuid, ...)` — eager hydrate after a fresh `core.identities` mint, no-op if already present.
  - `mirror_status_to_dict(agent_uuid, status)` — sync a PG status update into the in-memory dict so `update_identity_status` writes don't drift the dict away.
- `src/mcp_handlers/identity/resolution.py:902-916` — eager hydrate after PATH 3 mint.
- `src/mcp_handlers/updates/phases.py:1039-1046` — eager hydrate in the self-healing path after `agent_storage.create_agent`.
- `src/agent_storage.py` — three status-write sites (`update_agent`, `archive_agent`, `delete_agent`) mirror status into the dict.
- `src/mcp_handlers/identity/handlers.py:1417-1425` — auto-unarchive path during `onboard(resume=True)` now writes both `core.agents.status='active'` AND `core.identities.status='active'`. Pre-S21-b it wrote only `core.agents`, generating the 88-row identity='archived'/agent='active' inversion class the reconciler has to clean up.
- `scripts/ops/s21b_reconcile_status_inversion.py` — operator dry-run reconciler. `--apply` requires explicit `--only {active-to-archived|archived-to-active}` direction. Surfaces orphan identities (`core.identities` rows with no `core.agents` peer) informationally.

**Tests:** 11 new (4 status-rejection + 2 status-pass-through + 1 unknown-status-rejection + 4 helper unit tests). Full suite 7740/7740.

## Live-verifier ground-truth at ship time (2026-04-27)

- 67 active/archived inversions; **0** in last 7 days, **0** with unexpired sessions → safe to reconcile
- 88 archived/active; 16 deleted/archived (the latter unreconcilable here — `core.agents.status` CHECK forbids `'deleted'`)
- 406 orphan identities (no `core.agents` peer); 1 still `status='active'` — H12 ghost class, item-4 scope

## What survives for follow-up

These are NOT bugs in this PR; they are deferred design rows.

1. **Option (c) chokepoint refactor.** Single `set_agent_status(agent_uuid, status)` that updates `core.identities`, `core.agents`, and `agent_metadata` atomically. Today the consistency is per-callsite (every status writer must remember to mirror). The mirror helpers reduce the surface but don't remove it. Memory rule: "memory captures context, not missing guardrails" — this convention will rot unless a typed chokepoint enforces it.

2. **Orphan identity archival policy.** 406 `core.identities` rows have no `core.agents` peer. 1 is still `status='active'`. Pass-2 H12 named the reconciler shape (`status='archived' WHERE parent_agent_id IS NULL AND spawn_reason IS NULL AND status='active'`). That's S21-b item 4's scope.

3. **`db.update_identity_status` is still callable directly** without going through `agent_storage`. Any future caller that doesn't know about the mirror will re-poison the dict. The chokepoint refactor (#1) closes this; until then, code review on new callers must check.

4. **The phases.py keying convention.** `register_minted_agent_in_dict` is called with `agent_id` at `phases.py:1044`, which in current code paths is the same string written to PG (so the dict key matches the load path). Code-reviewer pass-2 flagged this as a long-term inconsistency: if a future caller passes a UUID where the dict was keyed by label, `mirror_status_to_dict(uuid)` misses. Documented in the helper docstring; rename to `agent_key` deferred.

## Methodological notes

- Pre-impl council framed as (a)/(b)/(c) — closed set. Pass-2 ran adversarial framing per memory rule "Council prompts must invite adversarial bug-hunting." Found the 67-row inversion + the no-sync-client constraint that pre-impl framing missed.
- Post-impl council found two more real bugs (handlers.py:1419 auto-unarchive + blocklist-vs-allowlist) and fixed both before commit. Pattern reproduces the S21-a lesson: closed-set prompts under-cover; adversarial second-pass finds real bugs at low cost.
