# S21-a — Council Review of the Fix Proposal

**Filed:** 2026-04-27, second council pass (the first was on the diagnosis; this one is on the proposed fix in `s21-session-resolution-bypass-incident.md` §S21-a).
**Composition:** `dialectic-knowledge-architect` + `feature-dev:code-reviewer` + `live-verifier`, parallel.
**Verdict:** ship S21-a with modifications. Six high-severity findings + three test gaps. Three premises in the original plan doc need updating before code lands.

---

## HIGH — must address before merge

### H1. anyio-asyncio violation in Change 1 (code-reviewer)
The proposed "check if existing `agent_uuid` is `status='active'` in `core.identities`, then skip" path adds a new async Postgres call inside `_cache_session_redis_write` at `persistence.py:157+`. That function is invoked from PATH 2 (`resolution.py:617`) and PATH 3 (`resolution.py:861/883`), both inside the anyio task group. CLAUDE.md "Known Issue: anyio-asyncio Conflict" prohibits new `await asyncpg` from handler paths.

**Fix:** PATH 2 already fetches `agent_status` at `resolution.py:607`. Pass it down as a parameter to `_cache_session` → `_cache_session_redis_write`. No new round-trip.

### H2. `_session_identities` in-memory dict overwrite is unguarded (code-reviewer)
NX in Redis blocks one write path. `persistence.py:96` writes to the in-memory `_session_identities` dict unconditionally before the Redis path runs. Even with NX correctly preserving Redis, the in-memory layer is still being overwritten on every PATH 3 mint. Other in-process readers consult that dict.

**Fix:** apply the same "don't overwrite if active binding exists" guard at `persistence.py:96`. Both layers must be gated, not just Redis.

### H3. No eviction of already-installed ghosts (code-reviewer)
NX prevents *future* overwrites. Redis slots already polluted by ghosts (e.g., the active sessions producing the chronic 92.3% rate) are not repaired by the proposal. Live-verifier confirmed slot `session:agent-6648432c-a50` is currently bound to `3fe12516-3f53-4106-b02a-8c8489d71773` (a different agent), TTL ~24h.

**Fix:** S21-a must include either (a) a one-shot Redis sweep at deploy time, (b) explicit eviction of stale entries where the bound agent is `status=archived`, or (c) PR description must call out that 24h TTL drains the existing pollution.

### H4. `resume=True` is the default — fail-closed will brick legitimate first callers (code-reviewer + dialectic)
`handlers.py:858`: `resume = arguments.get("resume", True)`. A first-time caller with explicit `client_session_id="agent-foo"` and no prior session row will hit the new fail-closed gate by default. Live-verifier confirmed external callers exist: dashboard, discord-bridge, plus any HTTP script that "tries `identity()` first."

**Fix:** either change the handler default to `resume=False` and require explicit `resume=True` for continuity intent, OR add a second discriminator (e.g., only fail-closed when a tombstone says the row existed and was bypassed). Also: MISS response should suggest `onboard(force_new=true)` so callers self-heal. Consider env flag `UNITARES_PATH2_FAIL_CLOSED=1` for a one-release canary.

**External-caller audit required in S21-a:** grep `identity(` callsites in `unitares-governance-plugin`, `unitares-discord-bridge`, dashboard JS, `agents/*/agent.py`.

### H5. Plan-doc schema description is wrong (live-verifier)
Plan says join `core.sessions.identity_id` → `core.identities.agent_id (UUID)`. Reality: `core.sessions.identity_id` is `bigint` FK to `core.identities.identity_id` (bigint PK). `agent_id` is a separate `text` column holding the UUID string.

**Fix:** any SQL written off the plan's description will fail. Update plan doc + ensure regression tests use the right column.

### H6. status enum has six values, not three (live-verifier)
Production: `active, archived, deleted` observed; CHECK constraint permits `active, archived, disabled, deleted, waiting_input, paused`. The NX guard says "skip if status='active'" — must explicitly decide what to do for the other four non-active-non-archived states. A `paused` agent's binding should probably be preserved; a `deleted` agent's slot should evict.

---

## MEDIUM

### M1. Redis key format in production
Live keys are `session:{ip}:{port_fragment}:{hash}` (e.g. `session:127.0.0.1:51befd:d0d017f3`), not `session:agent-{uuid[:12]}`. The incident example `session:agent-6648432c-a50` is the *display form* in the doc, not the actual key. Doesn't change the fix logic — NX is still keyed on whatever `session_key` the caller passes — but test fixtures should use realistic key formats.

### M2. Ghost-fork rate is 92.3%, not 95.1%
Re-run on 2026-04-27: 2032 ghosts / 2201 total / 92.3% over 30d. Chronic, unmitigated. Plan-doc figures are stale; phenomenon is real.

### M3. Archived-agent in Redis (TOCTOU)
If Redis holds a binding to an agent that was subsequently archived, naive NX refuses the legitimate re-bind. Need to evict-then-bind when bound agent's status is non-resumable.

### M4. S21-a/S21-b honesty gap (dialectic)
Between merges, master has correct PATH 2 resume *and* `require_registered_agent` (`agent_auth.py:256`) still consulting only `mcp_server.agent_metadata` (S21-b §6). Dogfood will see "not registered" errors after S21-a and conclude the fix didn't work. Either fold §6 into S21-a or call out the residual breakage explicitly in the PR body.

### M5. NX semantics implicitly grant cross-process-instance continuity (dialectic)
NX-preservation is anchored in `core.sessions` (substrate) so it's earned, not performative — but the implementer should write a one-line comment naming this so future readers don't mis-read it as token-style resume.

---

## TEST GAPS

The three proposed regression tests cover (i) 14-min idle resume, (ii) NX preservation, (iii) PATH 2 fail-closed. Missing:

1. **Archived-agent-in-Redis** — NX correctly refuses, leaving the stale binding stuck (issue M3 / H6).
2. **In-memory `_session_identities` overwrite** — verify the dict is also guarded, not just Redis (issue H2).
3. **Middleware + handler double-resolution with first-call MISS** — interaction between `identity_step.py:414` and `handlers.py:890` when the middleware MISS is uncached and the handler re-runs PATH 2 (S21-b defers the consolidation but S21-a's fail-closed change affects both callsites).

---

## VERIFIED

- All six file:line references match: `persistence.py:157` (`_cache_session_redis_write`), `resolution.py:580` (PATH 2 gate), `resolution.py:661` (`logger.debug`), `resolution.py:861/883` (PATH 3 mint), `session_cache.py:98` (bind), `agent_auth.py:256` (`require_registered_agent`).
- `session_resolution_source` already exists in live `identity()` response.
- `identity_resolution_outcome` correctly identified as a proposed addition (S21-b §7).
- One slot per session — single write key confirmed at `persistence.py:188` and `session_cache.py:98`. The "two write paths" concern from the diagnosis is not a separate-key concern; both write the same key.
- All five named ghost UUIDs survive in `core.identities`; four still `active`.

---

## Verdict

**Ship S21-a with modifications.** Required changes:

1. Pass `agent_status` from PATH 2 down to `_cache_session_redis_write` instead of adding a DB call (H1).
2. Gate the in-memory dict write at `persistence.py:96` with the same NX logic (H2).
3. Add explicit ghost-eviction OR document 24h TTL drain (H3).
4. Decide `resume` default semantics + run external-caller audit (H4).
5. Fix plan-doc schema description (H5) + handle full status enum (H6).
6. Either fold S21-b §6 (`require_registered_agent`) into S21-a or explicitly document the residual breakage in the PR body (M4).
7. Add the three missing regression tests.

S21-b row remains correctly scoped — no changes proposed there from this pass.
