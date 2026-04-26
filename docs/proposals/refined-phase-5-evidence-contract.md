# Refined Phase-5 Evidence Contract

**Status:** Draft (2026-04-26)
**Companion docs:** `refined-phase-5-evidence-contract.dialectic-review.md`, `.code-review.md`, `.live-verification.md`, `.gpt-review.md`
**Predecessor:** Calibration "honest absence" PR — surfaced the signal-starvation problem this spec resolves the supply side of.

## Problem

The auto-calibration loop (`apply_confidence_correction` in `src/calibration.py`) requires fresh tactical evidence to correct agent-reported confidence. Today the tactical channel is starved — `tactical_evidence.last_updated` was 12 days stale at the time of writing — because nothing in the runtime emits `outcome_event` for normal agent work. The earlier "honest absence" PR makes the starvation visible (the corrector now returns identity when bins are >7d stale), but does not resupply the channel.

The Bash-hook proposal that surfaced first was rejected after council review: it would pair the agent's last self-reported confidence with an unrelated subsequent shell exit code, calibrating against the wrong joint distribution. The dialectic framing: not signal-starved, signal-poisoned.

This spec defines the replacement: a structured evidence contract that an agent populates in the same MCP call where the claim originates, so claim and truth-check share session context, identity binding, and an epistemic moment.

## Non-goals

- **Not** a Bash-tool hook in any agent-host plugin.
- **Not** a free-form regex parser over `response_text` (Design A from the brainstorm — rejected: hidden calibration behavior).
- **Not** server-side classification of arbitrary tool calls. Agents declare evidence; the server validates and records.
- **Not** server-verifiable outcomes from KG/dialectic/state-transitions — that is a deliberate v2 path, with the `verification_source` field added in v1 as the seam.
- **Not** a per-agent-class TTL table or Hermes session-lifecycle work — separate spec.

## Design

### 1. Canonical contract: `recent_tool_results` field on `process_agent_update`

New field on `ProcessAgentUpdateParams`:

```python
class ToolResultEvidence(BaseModel):
    """Self-reported evidence from a tool the agent just invoked.

    Self-report from agents IS the data source. The server treats
    this as `verification_source="agent_reported_tool_result"` and
    will be cross-checked by future server-verified primitives.
    """
    model_config = ConfigDict(extra="forbid")

    kind: Literal["command", "test", "lint", "build", "file_op", "tool_call"]
    tool: str = Field(..., max_length=64)
    summary: str = Field(..., max_length=512)
    exit_code: Optional[int] = None
    is_bad: Optional[bool] = None  # if exit_code is missing, agent must classify
    prediction_id: Optional[str] = None  # links to a prior process_agent_update mint
    observed_at: Optional[datetime] = None  # defaults to server receive time

class ProcessAgentUpdateParams(...):
    # ... existing fields ...
    recent_tool_results: Optional[List[ToolResultEvidence]] = None
```

Strict nested schema (`extra="forbid"`); unknown fields are a 4xx, not silently dropped. Per GPT council: "schema-enforced decomposability" is the value here, not truthfulness — the contract is inspectable at the API boundary, lintable, versionable.

### 2. Phase-5 server-side processing

Inside `src/mcp_handlers/updates/phases.py` (current Phase-5 enrichment region around line 418), iterate `recent_tool_results` after confidence correction:

```python
for evidence in (ctx.arguments.get("recent_tool_results") or []):
    try:
        # validation already done by Pydantic
        outcome_type = _classify_outcome_type(evidence)  # tests pass/fail, etc.
        await _emit_outcome_event_inline(
            agent_id=ctx.agent_id,
            outcome_type=outcome_type,
            is_bad=evidence.get("is_bad", evidence.get("exit_code", 0) != 0),
            prediction_id=evidence.get("prediction_id"),
            confidence=ctx.confidence,  # post-correction
            verification_source="agent_reported_tool_result",
            detail={"tool": evidence["tool"], "summary": evidence["summary"], ...},
        )
    except Exception as e:
        logger.debug("Phase-5 evidence record failed: %s", e)
        # per-item isolation: one bad item must not abort siblings
```

**Per-item isolation rule:** a malformed item must not abort the siblings (code-review #3 risk). Wrap each item in try/except; record the per-item failure to `ctx.warnings` so it surfaces to the agent on the response.

### 3. `verification_source` enum on `outcome_event`

Add to `OutcomeEventParams` and propagate through `db.record_outcome_event`:

```python
verification_source: Literal[
    "agent_reported_tool_result",  # v1 default — this spec
    "server_observation",          # v2 — server-verified outcomes (KG writes, dialectic verdicts, state transitions)
    "external_signal",             # CI webhook, monitoring system
] = Field("agent_reported_tool_result", description="...")
```

Stored on the outcome row. Calibrator can later weight or filter by source. This is the seam the dialectic agent recommended: "deprecate C's contributions without rewriting the calibrator" when v2 server-verified outcomes land.

### 4. Echo `prediction_binding` on `outcome_event` response

Today every misuse of `prediction_id` (fake, stale, replayed, wrong-agent) returns `success: true` and silently falls through to `_prev_confidence` or audit-trail fallback. Verifier called this "the only signal is in DB; not in API response."

Add to `outcome_event` response payload:

```python
"prediction_binding": Literal[
    "registry",                  # the supplied prediction_id was found and consumed
    "ttl_expired_fallback",      # supplied id was found but past TTL — see §5b
    "argument_fallback",         # no id supplied; used the explicit confidence arg
    "prev_confidence_fallback",  # used monitor._prev_confidence
    "audit_trail_fallback",      # used db.get_latest_confidence_before
    "no_binding",                # all four fallbacks failed; calibration NOT recorded
]
```

Agent sees immediately whether their `prediction_id` actually bound. Silent degradation becomes visible.

### 5. Hard TTL enforcement on `consume_prediction`

#### 5a. Hard check on consume

Today TTL is "enforced lazily on each new register call" (verifier). A `consume_prediction` against a 30-min-old id can succeed if no register has fired in between. Move the check from "lazy on register" to "hard on consume":

```python
def consume_prediction(self, prediction_id: str) -> Optional[dict]:
    record = self._open_predictions.get(prediction_id)
    if record is None:
        return None
    if record["consumed"]:
        return None
    if (utcnow() - record["registered_at"]) > self._prediction_ttl:
        # signal ttl_expired_fallback to caller via separate path
        return None
    record["consumed"] = True
    return record
```

#### 5b. Default TTL → 1800s

Bump `_prediction_ttl_seconds` default from 600 to 1800. Verifier called 600s "short for slow outer-loop work (LLM agent that takes 15min to produce a result will systematically miss its registered prediction)." 1800s spans a typical multi-tool reasoning loop.

Per-agent override remains supported via `monitor._prediction_ttl_seconds` — but this spec does not establish per-agent-class defaults (separate spec, per the user's scope decision).

### 6. Expose `prediction_id` in default response mode

Today `prediction_id` is only surfaced when caller passes `response_mode="full"`. Default `auto`/`mirror` strip it. Verifier: "This is the biggest gotcha — clients building on this need to know to crank verbosity."

Update `src/services/update_response_service.py` to surface `prediction_id` on every response_mode that includes any agent-state echo (i.e., not `minimal`). The cost is one string field per response. The benefit is that the contract is discoverable from the default API surface.

Also update `describe_tool("process_agent_update")` to document `prediction_id` in the returns block.

### 7. Sequential-calibration docstring fix

`src/sequential_calibration.py` has a docstring claiming "no prediction_id seam yet... A prediction_id seam is phase-two work." Verifier proved the seam works end-to-end today. Update the docstring to match reality, with a pointer to this spec for the v1 contract.

### 8. Compatibility bridge (Design B as parser-into-internal-model)

Out of scope for v1 unless a real client emerges that cannot update its tool schema. If/when needed: a regex parser for `<eisv-evidence>{...}</eisv-evidence>` blocks in `response_text` produces the same `ToolResultEvidence` records the structured field would. Single internal model. Marked `compatibility-only` in code comments. **Not** implemented in v1 to avoid two surfaces drifting before there's a concrete need.

## Risks the council surfaced and how this spec handles them

| Risk | From | How handled |
|---|---|---|
| Pairing wrong joint distribution (last-confidence ↔ unrelated tool exit) | dialectic | Same-MCP-call binding; `prediction_id` links specific (confidence, timestamp) pair |
| Agent self-report can be fabricated | dialectic, GPT | `verification_source="agent_reported_tool_result"` flagged on every record; server-verified primitive deferred but seam is in place |
| Per-item failure aborts siblings | code-review | Try/except per item; surface failures via `ctx.warnings` |
| `extra="forbid"` collision with existing payloads | code-review | grep fleet for any existing `recent_tool_results` field name (none expected) |
| Silent degradation of `prediction_id` misuse | live verifier | New `prediction_binding` echo |
| TTL bleed (lazy enforcement) | live verifier (refined by user pressure) | Hard check on consume |
| TTL too short for slow agents | live verifier | Default → 1800s; configurable |
| Existing fleet (Vigil, Sentinel, Watcher, Steward, Chronicler, Lumen) breaks on schema change | code-review | `Optional` field, default `None`, old clients no-op |

## Test plan

- Unit: `ToolResultEvidence` Pydantic validation (well-formed, missing required fields, extra fields rejected, malformed exit_code)
- Unit: per-item isolation — list of 5 items with item 3 malformed records items 1-2 and 4-5
- Unit: hard TTL on `consume_prediction` — predictions >TTL return None even if no sweep has fired
- Unit: `prediction_binding` echo correctness for each enum value (mock each fallback path)
- Integration: end-to-end `process_agent_update` with `recent_tool_results` advances tactical_evidence.eligible_samples by N
- Integration: agent that registers a prediction at T=0, references it at T=900s (within 1800s TTL) → `prediction_binding == "registry"`
- Integration: agent that references a prediction_id at T>1800s → `prediction_binding == "ttl_expired_fallback"`
- Integration: agent that omits `prediction_id` → `prediction_binding == "argument_fallback"` or `"prev_confidence_fallback"` depending on arg presence
- Schema migration test: existing `process_agent_update` calls without `recent_tool_results` continue to work (Vigil/Sentinel/Watcher/Steward/Chronicler call signatures)
- Docstring drift test: `sequential_calibration.py` docstring no longer claims the seam is unimplemented

## Implementation order

1. `prediction_binding` echo on `outcome_event` (no schema migration; pure response shape addition)
2. Hard TTL on `consume_prediction` + bump default to 1800s
3. `verification_source` enum on `outcome_event`
4. `ToolResultEvidence` model + `recent_tool_results` field on `ProcessAgentUpdateParams`
5. Phase-5 iteration in `phases.py`
6. Expose `prediction_id` in default response mode
7. Update `describe_tool` returns block
8. `sequential_calibration.py` docstring cleanup
9. Tests in same commits as their behavior changes (per `feedback_tests-with-fixes.md`)

Each step lands as its own commit on the same branch — incremental, reviewable, individually revertable. Final ship via `scripts/dev/ship.sh` after the full suite passes.

## Future work explicitly out of v1 scope

- **Per-agent-class TTL table** (Lumen 6h, Vigil 1h, etc.) — separate spec; needs Hermes session-lifecycle decision first.
- **Hermes adapter `on_session_end` cleanup** — separate spec; folded into the same per-agent-class work.
- **Server-verified outcomes primitive** (`verification_source="server_observation"`) — separate spec; v2 deprecation path for agent-reported.
- **Performative-continuity contract rule** — separate spec; deeper question about which agent-class continuity claims the calibrator can rely on.
- **Design B regex parser** — only if a concrete client emerges that cannot update its tool schema.
