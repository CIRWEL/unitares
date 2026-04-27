# Code Review — Refined Phase-5 Evidence Contract

**Reviewer:** `feature-dev:code-reviewer` subagent
**Date:** 2026-04-26
**Spec:** `refined-phase-5-evidence-contract.md`
**Question framed:** B vs C — implementation cost, schema migration impact, identity safety, failure modes, fleet risk.

> **Editorial note (post-review):** the reviewer cited `sequential_calibration.py`'s docstring claiming the prediction_id seam is "phase-two work." The live verifier proved the seam is implemented today. The docstring is stale; the spec includes a docstring fix.

---

## Design B — Structured Evidence Block in response_text

### Schema cost
Zero schema change. `ProcessAgentUpdateParams.response_text` is already `Optional[str]`. The tag is stripped during Phase 5 processing and never surfaces to the schema layer. One new pure function; no Pydantic migration.

### Identity safety
Confirmed safe. Phase 1 (`resolve_identity_and_guards`) calls `get_context_agent_id()` from the `contextvars`-backed `_session_context` ContextVar. That ContextVar is set once at ASGI dispatch entry and is live for the full asyncio task duration. The internal call to `outcome_event` happens in Phase 5 of the same task — same ContextVar scope, same `agent_uuid` binding. No path where the session drops between the regex parse and the `record_outcome_event` call.

### Failure mode
If the regex fails to match (malformed tag, partial truncation, encoding artifact), the block is silently absent and Phase 5 proceeds normally. That is the stated design. The risk is the silent-drop is invisible to the agent: no acknowledgment in the response, no error. If the agent uses this for calibration and the tag is silently malformed, it will believe it submitted evidence it did not. The existing Phase 5 auto-emit still fires independently based on keyword heuristics, so a failed block does not leave the update completely unevidenced — but the structured data (exit_code, command) is lost.

### prediction_id lifecycle
`outcome_events.py` lines 174-183 call `_m.consume_prediction(prediction_id)` on the monitor. The `sequential_calibration.py` docstring explicitly flags this as a known gap: "No prediction_id seam yet... A prediction_id seam is phase-two work." This means `register_prediction` is not fully implemented on the write path — prediction_ids are not yet returned from `process_agent_update` responses. **[Editorial: stale — verifier confirmed end-to-end mint→consume works in `response_mode="full"`. The seam exists; observability of misuse is the actual gap.]**

### Test surface
The regex parser is a pure synchronous function with a well-defined input domain (a string). Easy to property-test: generate strings with valid/invalid/partial/nested tags, assert parse result. No DB or monitor mocks needed. High unit-testability.

### Migration risk
Zero. All existing agents send `response_text` strings. Unknown text is ignored. Vigil, Sentinel, Watcher, Steward, Chronicler, Lumen — all no-op without modification.

---

## Design C — Tool-Call Introspection Field

### Schema cost
Requires adding `recent_tool_results: Optional[List[...]]` to `ProcessAgentUpdateParams`. The nested-list item type needs either a nested `BaseModel` or a `Dict[str, Any]`. Looking at existing patterns in `core.py`: the `detail` field in `OutcomeEventParams` is `Optional[Dict[str, Any]]`; the existing flatten-to-dict pattern in handlers uses `arguments.get(key)` directly. A `List[Dict]` can be extracted with `arguments.get("recent_tool_results") or []` without issue. However, Pydantic v2 with `model_config = ConfigDict(extra="forbid")` is on `BootstrapStateParams` but not explicitly on `ProcessAgentUpdateParams` — adding the field is safe. The schema migration itself is low risk; the migration burden is on clients.

### Identity safety
Same ContextVar guarantee as Design B — the list is processed in Phase 5 of the same task. Identity is safe.

### Failure mode
If `arguments.get("recent_tool_results")` returns a list with a malformed item (missing `tool` key, non-int `exit_code`, etc.), a `try/except` around the per-item processing is required. Without it, one bad item aborts the whole list. If the exception propagates past Phase 5's outer `try/except` (lines 1151-1152 in phases.py confirm Phase 5 is wrapped), the parent update still succeeds but all evidence is dropped silently. The failure mode is structurally the same as Design B — silent drop — but the attack surface is larger: each item in the list is an independent parse site.

### Test surface
Schema-validated input means Pydantic catches type errors before the handler sees the list. The iteration logic is straightforward. But mocking requires constructing valid `ProcessAgentUpdateParams` instances with the new nested field, which adds friction for existing tests that construct params dicts directly. More test surface changes across the suite than Design B.

### Migration risk
This is the real problem. `ProcessAgentUpdateParams` is the hottest tool in the fleet. Every existing call from Vigil, Sentinel, Watcher, Steward, Chronicler, and Lumen goes through it. They all use keyword-arg construction or dict construction. Adding an `Optional` field with a default of `None` is backward-compatible at the Pydantic level — old clients that don't send the field get `None`, which means no-op, which is correct behavior. Agents silently no-op, not silently fail. That is acceptable.

However: any agent that sends an unrecognized field currently gets it passed through via `arguments` (since `ProcessAgentUpdateParams` does not use `extra="forbid"`). If an agent already sends a field named `recent_tool_results` for some other purpose, it will now be parsed as evidence. This is unlikely but not impossible across a six-agent fleet.

---

## Confidence-Rated Risk Ranking

**Design B**

1. **Silent calibration-loss on malformed tag (confidence: 90).** The agent has no confirmation the block was parsed. A truncated `response_text`, an encoding issue, or a whitespace-adjacent close tag drops the evidence with no error signal. The existing auto-emit at lines 1056-1152 uses keyword heuristics that may fire anyway with wrong metadata, creating a spurious positive outcome signal from a failed evidence block.

2. **prediction_id lifecycle is unimplemented (confidence: 95).** [Editorial: stale claim — verifier disproved.]

3. **Agent-controlled string injection into server-side regex (confidence: 82).** The regex parse is applied to `response_text`, which is fully agent-controlled content. A malicious or confused agent can inject a tag with a fabricated `exit_code: 0` and `prediction_id` it doesn't own. The identity check prevents cross-agent spoofing (the outcome_event is bound to the session's agent_uuid), but a rogue agent can falsely report passing tests. This is not new — the existing Phase 5 keyword heuristics already accept agent-reported text — but the structured block raises the stakes by also consuming a prediction_id.

**Design C**

1. **prediction_id lifecycle is unimplemented (confidence: 95).** [Editorial: stale claim — verifier disproved.]

2. **Old client collision on field name (confidence: 82).** If any of the six resident agents or any external client already sends `recent_tool_results` in their payload for a different purpose, the new field silently parses it as evidence. Worth a grep across Vigil/Sentinel/Watcher/Steward/Chronicler agent code before committing to this design.

3. **Per-item failure surface scales with list length (confidence: 83).** Each item in `recent_tool_results` is an independent parse site. A list of 5 tool results with item 3 malformed means items 1-2 are processed, item 3 throws (or silently skips if guarded), and items 4-5 may or may not run depending on guard placement. The failure mode is harder to reason about than the all-or-nothing regex match in Design B.

---

## Deal-Breaker Assessment

Neither design has a deal-breaker exclusive to itself. The shared deal-breaker is the unimplemented `register_prediction` write-path seam. **[Editorial: NOT a deal-breaker — verifier proved seam is implemented; spec addresses observability gap with `prediction_binding` echo.]**

If you proceed without the seam, Design B is lower risk: zero schema migration, zero fleet impact, easy to fuzz, and failure modes are already present in the Phase 5 keyword path. Design C's only advantage — structured validation — is not worth the migration surface until the prediction_id round-trip is real.

**[Editorial conclusion: verifier overrode this recommendation. Seam works; spec proceeds with C, with `prediction_binding` echo + hard TTL closing the silent-degradation hole the reviewer correctly identified as the underlying concern.]**
