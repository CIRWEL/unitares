# Sever Fingerprint-Based EISV Inheritance

**Status:** Draft
**Date:** 2026-04-16
**Author:** Ligeti (Claude Opus 4, dogfooding)

## Problem

When `onboard` is called and the server's IP+UA fingerprint resolver matches a prior agent in the same environment, two silent side effects occur:

1. **Lineage claim**: `parent_agent_id` is set on the new identity automatically (`src/mcp_handlers/identity/resolution.py:679-682` and similar paths).
2. **State transplant**: on first `get_or_create_monitor(new_agent_id)`, `src/agent_lifecycle.py:33-39` copies the predecessor's full `GovernanceState` — `V_history`, `E_history`, `I_history`, `S_history`, `coherence_history`, regime tracking, PI controller state, HCK/CIRS metrics, and governor state — onto the new monitor.

These behaviors fire even when the caller picks a brand-new display name and receives `is_new: true` in the onboard response. The response note promises *"Your state was inherited from it"*, so the UX matches reality, but the underlying model is broken: a new agent's trajectory is seeded with another agent's history, and every subsequent check-in updates calibration and verdicts against that inherited baseline. The distortion compounds downstream (a domino effect on the trajectory signal).

The conflation is between two epistemically different things:

- **Fingerprint match** = "we recognize this workstation" (an environmental hint)
- **Lineage claim** = "this is a legitimate successor of that agent" (a positive assertion)

Current code silently converts (a) into (b). It should not.

## Goals

1. A new agent identity never adopts another agent's EISV state implicitly.
2. Lineage (`parent_agent_id`) is only set when the caller explicitly asserts succession.
3. The explicit continuity path — `continuity_token` passed by hooks/SDK — continues to work unchanged.
4. Tests cover the new contract so the bug cannot silently return.

## Non-Goals

- Changing how `continuity_token` works or how hooks cache it.
- Removing fingerprint-based *identity resumption* (`resume=True`, matching an existing agent). That is a different question and is out of scope. This spec only targets fingerprint-based *predecessor linking when a new identity is created*.
- Migrating existing `parent_agent_id` rows in the database. The historical lineage metadata is kept as-is; only future behavior changes.
- Adding opt-in state inheritance (e.g., a `fork_with_state=True` flag). Kenny's guidance: *"maybe in the future"*. Out of scope now.

## Approach

Three changes, coordinated.

### Change 1: Delete the state transplant

File: `src/agent_lifecycle.py`, lines 33–39.

Current:
```python
else:
    # Inherit EISV from predecessor if available
    meta = agent_metadata.get(agent_id)
    if meta and meta.parent_agent_id:
        parent_state = load_monitor_state(meta.parent_agent_id)
        if parent_state:
            monitor.state = parent_state
            logger.info(f"Inherited EISV from predecessor {meta.parent_agent_id[:8]}...")
        else:
            logger.info(f"Initialized new monitor for {agent_id} (predecessor {meta.parent_agent_id[:8]}... had no state)")
    else:
        logger.info(f"Initialized new monitor for {agent_id}")
```

After:
```python
else:
    logger.info(f"Initialized new monitor for {agent_id}")
```

Rationale: this is the sole code path that transplants state via `parent_agent_id`. Deleting it severs the domino at its source. `parent_agent_id` remains a pure lineage record on the `agent_metadata` row.

### Change 2: Stop auto-setting `predecessor_uuid` on fingerprint match

File: `src/mcp_handlers/identity/resolution.py`.

In `resolve_session_identity`:

- **PATH 1** (Redis hit with `resume=False`): remove the `_predecessor_uuid = agent_uuid` assignment. The path continues to return `session_resolution_source` for diagnostics but does not produce a lineage claim.
- **PATH 2** (PostgreSQL hit with `resume=False`): same treatment — no `_predecessor_uuid` assignment.
- **PATH 2.5** (name claim): already doesn't set predecessor; no change.
- **PATH 2.8** (token rebind): already doesn't set predecessor; no change.
- **Explicit `parent_agent_id` arg** passed into onboard: honored as-is and propagated to the agent metadata row. This is the only way a lineage claim is made going forward.

File: `src/mcp_handlers/identity/handlers.py`, lines 1093–1098.

```python
# IDENTITY HONESTY: Wire predecessor from resolve_session_identity
# when resume=False found an existing identity but created a new UUID
if not _parent_agent_id and existing_identity.get("predecessor_uuid"):
    _parent_agent_id = existing_identity["predecessor_uuid"]
    if not _spawn_reason:
        _spawn_reason = "new_session"
```

After Change 2, no current resolver path sets `predecessor_uuid` in `existing_identity`, so this block is fully dormant — it never fires in practice. Keep it in place as defensive scaffolding: if a future resolution path is added that legitimately sets `predecessor_uuid` (e.g., an explicit-forking API that routes through the resolver), the wiring is already in place. No functional harm to leaving it; deleting it is also acceptable — implementer's call.

### Change 3: Response shape honesty

File: `src/services/identity_payloads.py` (predecessor payload construction).

Current:
```python
if parent_agent_id and not force_new:
    result["predecessor"] = {
        "uuid": parent_agent_id,
        "note": "Previous instance in this trajectory. Your state was inherited from it.",
    }
```

After:
```python
if parent_agent_id and not force_new:
    result["predecessor"] = {
        "uuid": parent_agent_id,
        "note": "Lineage record only; no state was inherited.",
    }
```

Because `parent_agent_id` is now only set when the caller explicitly asserted it, the response only surfaces the `predecessor` field in the honest-forking case. Fingerprint-matched new-identity cases no longer have `parent_agent_id`, so the field is naturally omitted.

The diagnostic `session_resolution_source` still reports how the identity was resolved (e.g., `ip_ua_fingerprint`) for operators, but it never implies a state or lineage claim.

## Data Flow Diagram

**Before (current):**
```
client: onboard(name="Ligeti", resume=False)
  ↓
server: fingerprint matches prior agent "Mahler" (uuid=0a190520)
  ↓
resolve_session_identity: _predecessor_uuid = 0a190520   ← silent claim
  ↓
onboard handler: _parent_agent_id ← predecessor_uuid     ← propagate
  ↓
persist new agent row with parent_agent_id=0a190520
  ↓
get_or_create_monitor(new_uuid)
  ↓
monitor.state = load_monitor_state(0a190520)             ← state transplant
  ↓
response: { is_new: true, predecessor: { note: "state inherited" } }
```

**After:**
```
client: onboard(name="Ligeti", resume=False)
  ↓
server: fingerprint matches prior agent "Mahler" (uuid=0a190520)
  ↓
resolve_session_identity: returns session_resolution_source="ip_ua_fingerprint"
  (no predecessor_uuid set)
  ↓
onboard handler: _parent_agent_id remains None
  ↓
persist new agent row with parent_agent_id=NULL
  ↓
get_or_create_monitor(new_uuid)
  ↓
monitor is initialized fresh
  ↓
response: { is_new: true, session_resolution_source: "ip_ua_fingerprint" }
  (no predecessor field)
```

Explicit forking path continues to work:
```
client: onboard(name="B", parent_agent_id="A-uuid")
  ↓
onboard handler: _parent_agent_id = "A-uuid"
  ↓
persist new agent row with parent_agent_id="A-uuid"
  ↓
monitor initialized fresh (Change 1 removes the transplant)
  ↓
response: { predecessor: { uuid: "A-uuid", note: "Lineage record only; no state was inherited." } }
```

## Testing

### New tests

`tests/test_identity_handlers.py` (or a new `tests/test_no_fingerprint_inheritance.py` — judgment call at implementation time):

1. **`test_fingerprint_match_does_not_transplant_state`**
   - Onboard agent A, run several check-ins to populate `V_history`.
   - Onboard agent B with a new name on the same fingerprint (`resume=False`).
   - Assert: B is a new UUID, B's monitor state has empty `V_history`, B's `parent_agent_id` is NULL in metadata, response has no `predecessor` field.

2. **`test_fingerprint_match_no_implicit_lineage_claim`**
   - Onboard agent A, then onboard agent B with a new name.
   - Assert: B's agent metadata row has `parent_agent_id IS NULL` (lineage not auto-claimed).

3. **`test_explicit_parent_agent_id_records_lineage_without_state`**
   - Onboard A, populate state.
   - Onboard B with explicit `parent_agent_id=A.uuid`.
   - Assert: B's monitor state is fresh (empty `V_history`); B's metadata has `parent_agent_id=A.uuid`; response surfaces `predecessor` with the updated "lineage record only" note.

4. **`test_continuity_token_path_unchanged`**
   - Onboard A, capture `continuity_token`.
   - Call any tool with the token.
   - Assert: identity resolves to A (no new UUID created). This guards against regressions in the explicit continuity path.

### Existing tests to update

- `test_identity_handlers.py::test_onboard_resume_false` — if it asserts `result["predecessor"]` is set on fingerprint-match-only cases, update to assert absence.
- Any test in `test_thread_identity.py` that asserts `predecessor` populated from fingerprint-only — update to use explicit `parent_agent_id`.

(Exact list determined during implementation; the explorer's recon found no tests that assert *state* inheritance, so nothing in the coverage for the bad behavior needs to survive.)

### Existing tests expected to keep passing unchanged

- `test_mcp_server_std.py` lineage assertions.
- `test_postgres_backend_integration.py` parent_agent_id persistence tests.
- `test_thread_identity.py` predecessor-metadata context tests where lineage is set explicitly.

## Error Handling

No new error paths. The removed code (state transplant) had only success/log paths. The resolution paths that no longer set `predecessor_uuid` continue to return valid resolution records; callers that read `predecessor_uuid` from the resolution result will get `None` in the fingerprint case, which is already handled (see `handlers.py:1095` guard).

## Rollout

Single PR to `CIRWEL/unitares`. No database migration. No feature flag. Changes are:

- Additive at the test level (new tests added).
- Subtractive at the runtime level (removed state-copy and implicit-lineage code paths).
- Documentation update: the response-note string change.

Existing production agents keep whatever `parent_agent_id` they have in the DB (lineage record). They will no longer have predecessor state transplanted into fresh monitor instances on restart. This is intended behavior — the compounding distortion stops at the first post-deploy monitor initialization.

## Risks

**R1: Anima/Lumen (anima-mcp) may depend on inherited state.**
Recon flagged this as unknown. Mitigation: before merging, run the integration test suite against a live anima-mcp session and verify no behavioral regression. If Lumen does rely on state inheritance, that's a separate design question (should Lumen be a single continuing agent across restarts? If so, it should use `continuity_token`, not fingerprint).

**R2: Bridge / hook behavior on fresh workspaces.**
On a brand-new workspace where no `.unitares/session.json` exists, hooks will onboard fresh. Previously, fingerprint could accidentally link them to a prior workstation agent. Under this spec, they start cleanly. This is the intended behavior and matches the governance-lifecycle skill's documented guidance (*"Strong continuity is better than implicit continuity"*).

**R3: Silent metadata drift for callers that read `predecessor` from onboard response.**
Any external consumer hard-coding the assumption that `result["predecessor"]` is always populated when a fingerprint matches will break. Mitigation: grep the monorepo (unitares, unitares-discord-bridge, anima-mcp) for `predecessor` reads before merging; all known current consumers use it as optional.

## Open Questions

None that block this spec. The anima-mcp audit (R1) is a pre-merge verification step, not a design question.
