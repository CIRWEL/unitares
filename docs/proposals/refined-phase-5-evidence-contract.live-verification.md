# Live Verification — `prediction_id` Mechanism

**Reviewer:** `general-purpose` subagent acting as live-call verifier
**Date:** 2026-04-26
**Spec:** `refined-phase-5-evidence-contract.md`
**Question framed:** Verify the actual current behavior of the `prediction_id` seam — both candidate designs depend on it.

---

## prediction_id mechanism — verified ground truth

**Real and exposed today, but only in `response_mode="full"`.** It is *not* a paper-only seam.

### Lifecycle
- **Mint site:** `src/monitor_calibration.py:68` — `monitor.register_tactical_prediction(confidence, decision_action=...)` is called every check-in that includes a confidence value. Stored on `monitor._open_predictions` (in-memory dict, per-agent) and remembered as `monitor._last_prediction_id`.
- **Surface site:** `src/services/update_response_service.py:34-36` — copies `_last_prediction_id` into `response_data["prediction_id"]` as a top-level field.
- **Consume site:** `src/mcp_handlers/observability/outcome_events.py:178` — `monitor.consume_prediction(prediction_id)` flips `consumed=True` and returns the registered confidence.
- **TTL:** 600 seconds (10 min), enforced lazily on each new register call. Configurable via `monitor._prediction_ttl_seconds`.
- **Storage:** `src/monitor_prediction.py` — pure dict, no DB. Lost on server restart.

### Empirical results

1. **Mint:** `process_agent_update(response_mode="full", confidence=0.7)` returned `"prediction_id": "57bb0b1a-..."` as a top-level key.
2. **`mirror` mode (default `auto` lands here for established sessions): `prediction_id` is NOT in the response.** Confirmed empirically. The seam exists in code but `update_response_service` only injects on the full-payload path. `compact`/`minimal`/`mirror` strip it.
3. **Schema/describe_tool:** the documented `RETURNS` block in `describe_tool("process_agent_update")` does **not** mention `prediction_id`. Caller has to know about it.
4. **First use:** `outcome_event(prediction_id=<real>)` returned `success: true`, `outcome_id: 818e...`. No echoed confirmation that the registered confidence was used.
5. **Replay (same id, second call):** `success: true`, **silently no-ops the registry path** (`consume_prediction` returns `None` because `consumed=True`). Falls through to confidence-arg or `_prev_confidence`/audit-trail fallback. No error, no warning.
6. **Fake id (`"fake-uuid-1234"`):** `success: true`, also silent. Falls through to provided `confidence=0.5` arg. No error, no warning.

### Failure modes (all silent — no errors)
- **Stale id (>600s TTL):** dropped from registry, falls through to `argument` or `prev_confidence_fallback` or `audit_trail_fallback`.
- **Replay:** no-op on registry, fallback wins.
- **Wrong agent's id:** `monitor.consume_prediction` is called on the *current* agent's monitor only. Cross-agent ids will silently miss → fallback. **No agent-scope error.**
- **Cross-session within same agent:** works, because `_open_predictions` lives on the in-process `monitor` keyed by `agent_id`, not `client_session_id`.
- **Server restart:** all open predictions vanish (in-memory only).

### Implications for designs B and C
- **Replayability:** one-shot. Designs assuming idempotent re-reference will silently degrade to fallback confidence — outcome still succeeds, but the e-process / sequential calibration loses the precise (confidence, timestamp) pairing.
- **Visibility:** caller must opt into `response_mode="full"` (or read `monitor._last_prediction_id` server-side). Default `auto`/`mirror` does NOT expose it. **This is the biggest gotcha** — clients building on this need to know to crank verbosity.
- **Failure observability:** zero. Every misuse (stale, fake, replayed, wrong-agent) returns `success: true`. The only signal is `detail["prediction_source"]` recorded in the outcome row (`registry` vs `argument` vs `prev_confidence_fallback` vs `audit_trail_fallback`) — visible in DB, not in API response. If B/C depend on registry-binding actually happening, **add a server-side echo** (e.g., return `prediction_used: bool` from outcome_event).
- **TTL = 600s** is short for slow outer-loop work (LLM agent that takes 15min to produce a result will systematically miss its registered prediction).
- **Process-bounded:** server restart wipes all open predictions. Long-lived prediction-id references across deploys won't work.

### Key files
- `/Users/cirwel/projects/unitares/src/monitor_prediction.py` — registry primitives
- `/Users/cirwel/projects/unitares/src/governance_monitor.py:1071-1105` — monitor methods
- `/Users/cirwel/projects/unitares/src/monitor_calibration.py:68` — mint call site
- `/Users/cirwel/projects/unitares/src/services/update_response_service.py:26-36` — response surfacing (full-mode only)
- `/Users/cirwel/projects/unitares/src/mcp_handlers/observability/outcome_events.py:163-225` — consume + 4-tier fallback
- `/Users/cirwel/projects/unitares/src/sequential_calibration.py:246` — downstream e-process consumer

---

## Spec author's notes

The verifier overrode the code-reviewer's "deal-breaker" finding (which was based on a stale docstring) and surfaced two real problems the spec must address:

1. **Silent misuse of `prediction_id`** → spec adds `prediction_binding` echo on `outcome_event` response, with values `registry | ttl_expired_fallback | argument_fallback | prev_confidence_fallback | audit_trail_fallback | no_binding`.

2. **TTL is short and laxly enforced** → spec adds hard TTL check on `consume_prediction` (not lazy-on-register) and bumps default to 1800s.

A third issue the verifier raised — `prediction_id` not exposed in default `response_mode` — the spec resolves by surfacing it on every mode that includes any agent-state echo (i.e., not `minimal`).
