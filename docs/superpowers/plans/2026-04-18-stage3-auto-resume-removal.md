# Stage 3: Remove process_agent_update Auto-Resume — Scoping

> **Status:** deferred. Safe closure of the 2026-04-18 incident was achieved in Stage 1 (PRs #33, #34) and Stage 2 (PR #37). Stage 3 as originally conceived ("just rip auto-resume") turns out to require more work than its value justifies. This doc captures the honest scope for when it's picked up.

**Original premise:** Now that sticky archive + cooldown + in-process gate are in place, the `process_agent_update` auto-resume code in `src/mcp_handlers/updates/phases.py:367-400` is philosophically redundant — any silent resurrection is already refused. Remove it for architectural cleanliness.

**Why it's not a simple removal:** the audit in Stage 2 revealed that auto-resume is load-bearing for one unhandled case: **orphan-sweep false-positives on live residents**. If `archive_orphan_agents` ever incorrectly archives an active Watcher/Vigil/Sentinel/Steward, the next check-in silently un-archives it and the resident keeps running. Today that's a feature, not a bug — the SDK has no recovery path to fall back on.

## What would actually be required

### 3a: Remove auto-resume from phases.py (~50 lines)

Replace the block at `src/mcp_handlers/updates/phases.py:315-410` with a flat refusal for any `meta.status == "archived"`:

```python
if meta and meta.status == "archived":
    return [error_response(
        f"Agent '{agent_id}' is archived. Use self_recovery(action='quick') "
        f"to restore, or onboard(force_new=true) for a new identity.",
        recovery={
            "action": "Use self_recovery(action='quick')",
            "related_tools": ["self_recovery", "onboard"],
        },
        context={"agent_id": agent_id, "status": "archived"},
    )]
```

Delete:
- cooldown + marker + too-old gating (all paths collapse into the single refusal)
- `audit_logger.log_auto_resume` call
- `ctx.auto_resume_info` field + downstream usage in `enrichments.py`

Update tests that assert auto-resume success:
- `tests/test_sticky_archive.py::test_old_archive_outside_cooldown_can_still_auto_resume` — flip to assert failure
- `tests/test_sticky_archive.py::test_cooldown_env_override` — delete (no longer meaningful)
- `tests/test_core_update.py::test_full_response_contract_preserves_archived_error_shape` — already asserts failure, stays green

### 3b: Add SDK recovery path for AGENT_ARCHIVED (~100 lines + tests)

Currently in `agents/sdk/src/unitares_sdk/agent.py:149-163`, the `run_forever` loop catches generic `Exception`, logs, sleeps, and retries. If a resident's identity gets sweep-archived mid-run, every subsequent cycle will raise `AGENT_ARCHIVED` on `client.checkin()`, and the resident will spin on it indefinitely.

What's needed:
- Catch `AGENT_ARCHIVED` specifically in `_handle_cycle_result` (around `client.checkin` call).
- Call `client.self_recovery(action="quick")` — which un-archives the agent and resets its state.
- Retry the check-in once. If that fails, escalate to normal error path.
- Test coverage: simulate `AGENT_ARCHIVED` response, verify self_recovery + retry sequence.

Touch points:
- `agents/sdk/src/unitares_sdk/agent.py` — add recovery in `_handle_cycle_result`.
- `agents/sdk/src/unitares_sdk/client.py` — may need a typed exception for `AGENT_ARCHIVED` so SDK consumers can catch it specifically (today it's a generic `GovernanceToolError`).
- `agents/sdk/tests/test_agent_recovery.py` — new test file.

### 3c: Harden orphan-sweep heuristic (optional but related)

Root cause avoidance: `archive_orphan_agents` uses an age + update-count heuristic that can false-positive on low-activity residents (e.g., a Watcher that's been quiet for 6 hours because the user wasn't coding). Options:

- Exempt agents tagged `persistent` from the sweep (Steward already uses this — see `unitares-pi-plugin/src/unitares_pi_plugin/steward_identity.py:91`). Extend to all residents.
- Require an explicit `inactive_hours` + `total_updates=0` conjunction rather than heuristic tiers.
- Make sweep opt-in via flag rather than a periodic default.

Without 3c, 3b is the safety net. With 3c, 3b is belt-and-suspenders.

## Effort estimate

| Piece | Lines | Tests | Risk |
|---|---|---|---|
| 3a | ~50 deleted, ~10 added | 3 tests flipped | Low (if 3b lands first) |
| 3b | ~80 added in SDK | ~30 lines of test | Medium — changes SDK error semantics |
| 3c | ~30 in agent_lifecycle.py | ~20 of test | Low-medium |

Roughly 1–2 days end to end with careful testing.

## Recommendation

**Don't do Stage 3 yet.** The incident is closed. The bypass is closed. What remains is architectural cleanup that becomes worth it once one of these happens:

- An orphan-sweep false-positive actually breaks a resident (forcing 3c anyway).
- SDK adds richer error handling for other reasons (making 3b trivial to tack on).
- A decision to expand the SDK into a broader "fleet client" surface that benefits from clean semantics.

Until then, the current state — "auto-resume is a safety net for sweep false-positives, with explicit archives sticky and cooldown-protected" — is coherent and correct.

## References

- Incident: 2026-04-18, UUID `acd8a774-0a05`, archive→resurrect in 10s, circuit-broke 45min later.
- Stage 1 PRs: #33 (sticky archive + cooldown), #34 (P011 persist fix).
- Stage 2 PR: #37 (in-process gate for Steward bypass).
- Stage 2 audit: Watcher, Vigil, Sentinel all explicitly `identity(resume=true)`; Steward uses in-process path (gated by PR #37).
