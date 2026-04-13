# Codex Dogfood UX Tightening

**Date:** 2026-04-12
**Status:** Proposed

## Why this exists

A live Codex dogfood run against the local UNITARES server surfaced a useful pattern:

- the system already provides real operational value around continuity and reflective nudges
- the response surface still makes the agent assemble too many partially-overlapping status vocabularies on its own

This spec is about tightening the agent-facing UX so check-ins feel like instrumented runtime support, not ceremony.

## Live run summary

### What was actually useful

`onboard()` resumed an older Codex identity and immediately returned:

```json
{
  "display_name": "Codex Dogfood",
  "is_new": false,
  "temporal_context": "Idle: 10 days since last check-in."
}
```

That is real value. The runtime told the agent something concrete about continuity without extra work.

`process_agent_update(..., response_mode="mirror")` returned:

```json
{
  "verdict": "proceed",
  "mirror": ["Calibration: 74% accuracy over 91 decisions ..."],
  "question": "You're close to a coherence edge. What's the smallest next step that would simplify the plan?",
  "margin": "tight",
  "nearest_edge": "coherence",
  "identity_assurance": {"tier": "strong"}
}
```

That also felt real. It compressed the state into one nudge plus one question.

### What felt cognitively messy

`get_governance_metrics(lite=false)` for the same identity returned:

```json
{
  "status": "healthy",
  "verdict": "safe",
  "state": {
    "health": "moderate",
    "basin": "high",
    "mode": "building_alone"
  },
  "summary": "moderate | building_alone | high basin",
  "primary_eisv_source": "ode_fallback",
  "behavioral_eisv": {
    "confidence": 0.1,
    "warmup": {
      "phase": "bootstrapping",
      "updates_completed": 1,
      "baseline_target": 30
    }
  }
}
```

Individually, these fields make sense. Collectively, they are too easy to misread:

- `proceed`
- `safe`
- `healthy`
- `moderate`
- `high basin`
- `margin: tight`
- `ode_fallback`

The runtime knows what these mean together. The agent should not have to synthesize that every time.

## Problem statement

UNITARES currently emits good raw state, but the top-level UX still has three friction points:

1. **Too many overlapping summary languages**
   - Decision language: `proceed / guide / pause / reject`
   - ODE/diagnostic language: `safe / caution / high-risk`, `healthy / moderate / critical`
   - topological language: `high basin`, `boundary`, `building_alone`
   - margin language: `comfortable / tight / critical`

   These are all defensible internally. They are not yet cleanly composed for the caller.

2. **Behavioral-vs-ODE authority is technically exposed but not operationally obvious**
   - `primary_eisv_source = "ode_fallback"` is present
   - `behavioral_eisv.warmup` is present
   - `state_semantics` explains the hierarchy

   But the actual user experience still makes the agent mentally merge these pieces. The important fact is simpler:

   `Behavioral governance is still warming up, so the current verdict is provisional and ODE-backed.`

3. **Identity success payloads still contain a contradictory signature artifact**
   - `identity()` returned a valid bound identity
   - the same response also included `agent_signature: {"uuid": null}`

   Even if this is harmless, it degrades trust. A successful identity response should never contain a null identity marker.

## Goal

Keep the depth. Reduce the interpretive burden.

The agent should be able to answer, from one pass through the response:

1. Who am I right now?
2. Did UNITARES resume me or create me?
3. Can I proceed?
4. How close am I to trouble?
5. Is the current verdict behavioral, or is the system still in ODE fallback while warming up?

## Proposed changes

### 1. Add one authoritative top-level operational summary

Add a small synthesized object to both `process_agent_update()` and `get_governance_metrics()`:

```json
{
  "operational_summary": {
    "action": "proceed",
    "state": "warmup_boundary",
    "authority": "ode_fallback",
    "edge": "coherence",
    "note": "Proceed, but behavioral governance is still bootstrapping and coherence is near the tight edge."
  }
}
```

This should be the first thing an agent reads.

It does not replace the existing fields. It composes them.

### 2. Make authority and warmup explicit in plain language

When `primary_eisv_source != "behavioral"`, emit a short human-readable sentence near the top level:

```json
{
  "authority_notice": {
    "source": "ode_fallback",
    "reason": "behavioral_warmup",
    "message": "Behavioral governance is still bootstrapping (1/30 updates). Current verdicts are ODE-backed until behavioral confidence matures."
  }
}
```

This is better than making the caller infer it from:

- `primary_eisv_source`
- `behavioral_eisv.confidence`
- `behavioral_eisv.warmup`
- `state_semantics.hierarchy`

### 3. Tighten mirror mode around one grounded nudge

`mirror` mode is strongest when it returns:

- one operational stance
- one grounded observation
- one question

It gets weaker when the agent sees a warning question but has to inspect another tool to understand why.

For tight-margin cases, prefer:

```json
{
  "verdict": "proceed",
  "operational_summary": {
    "action": "proceed",
    "state": "tight_margin",
    "authority": "ode_fallback",
    "edge": "coherence",
    "note": "Coherence is near the tight edge during behavioral warmup."
  },
  "question": "What's the smallest next step that would simplify the plan?"
}
```

The question already exists in `src/mcp_handlers/updates/enrichments.py`. The missing piece is the short grounding sentence.

### 4. Fix the identity response contradiction

A successful `identity()` or `onboard()` response should do one of two things:

- omit `agent_signature` entirely when `lite_response=true`
- or populate it from the resolved identity payload, never as `{"uuid": null}`

This is a trust bug, not just a cosmetic bug.

### 5. Preserve the continuity wins

Do not remove these:

- `temporal_context` on onboarding/resume
- strong `identity_assurance` reporting
- the mirror-mode reflective question

These are the parts that made the dogfood run feel substantive.

## Concrete implementation targets

### `src/services/runtime_queries.py`

Add a synthesized authority/warmup notice and a compact `operational_summary` for read APIs.

Current relevant logic:

- `_build_eisv_semantics()`
- `primary_eisv_source = "behavioral" if behavioral_confidence >= 0.3 else "ode_fallback"`

This file already has the raw material. It needs one cleaner top-level composition layer.

### `src/mcp_handlers/response_formatter.py`

Teach `mirror` mode to include the same compact operational summary that ties:

- `decision.action`
- `decision.margin`
- `decision.nearest_edge`
- authority source

into one line of meaning before the reflective question.

### `src/mcp_handlers/updates/enrichments.py`

Keep the question generator mostly as-is. It is already doing the right thing.

The main opportunity here is better grounding text for `_has_tight_margin()` and warmup-aware contexts.

### `src/mcp_handlers/identity/handlers.py`
### `src/mcp_handlers/response_base.py`

Audit why `identity()` still surfaced `agent_signature: {"uuid": null}` despite `arguments["lite_response"] = True`.

The fix is likely small, but it should be made intentionally rather than papered over.

## Non-goals

- changing the actual governance math
- removing ODE diagnostics
- hiding warmup details from advanced callers
- flattening all state into a single simplistic status word

The problem is not that UNITARES is too rich. The problem is that its richest caller-facing paths still need one more pass of composition.

## Success criteria

This work is successful if a real dogfood agent can answer the following without cross-referencing multiple fields:

1. `Did I get resumed or created?`
2. `Am I safe to continue right now?`
3. `Is this verdict behavioral or provisional?`
4. `What is the single most important caution?`
5. `What should I do next?`

## Taste test

After this change, a good mirror response should feel like:

`Proceed. Behavioral governance is still warming up, and coherence is near the tight edge. Simplify the next step.`

Not like:

`Proceed / safe / healthy / moderate / high basin / tight margin / ode_fallback`
