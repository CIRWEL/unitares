---
name: Trajectory Audit Tool
description: Ship an on-demand audit view that compares an agent's self-reports against externally-observable signals, plus a small calibration-delta indicator on the existing calibration surface. Pull-based for agents (opt-in tool), push-based for operators (dashboard). No new EISV channel, no parallel pipeline.
status: Draft
author: Kenny Wang
date: 2026-04-17
supersedes: (early draft introduced an `observed_eisv` third channel; revised after review — parallel pipeline was overshoot when existing calibration infrastructure already covers most of the job)
---

# Trajectory Audit Tool — Design Spec

## 1. Problem

UNITARES tracks agent state through `process_agent_update` check-ins. Every check-in is **self-report**: the agent narrates what it did, how complex it was, how confident it is. The server updates `behavioral_eisv` accordingly.

This produces a structural gap: the thing being measured is also the thing doing the measuring. Calibration catches a narrow slice of the drift (overconfidence vs. binary outcomes via `auto_ground_truth`) but doesn't see the shape. An agent that claims `complexity=0.2, confidence=0.8` while actually running 50 tools and breaking 3 tests looks identical to an agent honestly reporting trivial work.

Secondary motivation: observation-style signals (plugin hooks, sensor data from Lumen, subagent reviewers) currently have no semantic home. They either impersonate the agent by posting as it, or sit outside governance. The plugin check-ins shipped tonight tag themselves `metadata.source=plugin_hook` but the tag is cosmetic — nothing downstream reads it.

## 2. Approach

**Do not add a third EISV channel.** Ship two narrow things:

1. **`audit_trajectory(agent_id, window_seconds)` MCP tool** — pull-based, on-demand aggregator. Reads existing tables (`audit.tool_usage`, `outcome_events`, `dialectic_sessions`, check-in history). Returns a diff view: what the agent claimed vs. what externally-visible signals show. Callable by agents (about themselves or, for resident agents / operators, others). No persistent state added; computed from existing records.

2. **`calibration_delta` field on the existing calibration surface.** Per-dimension (E/I/S/V) gap score between recent self-reports and externally-observable signals, populated by the existing calibration pipeline. Exposed on the existing dashboard calibration panel as a small categorical indicator ("aligned" / "drifting"), NOT a numeric score — the magnitude lives only in `audit_trajectory` output, accessible on explicit invocation.

### Why not a new EISV channel

An earlier draft of this spec proposed `observed_eisv` as a third channel peer to `behavioral_eisv` and `ode_eisv`. Review surfaced that the existing calibration system (`calibration_checker` + `auto_ground_truth` + `dialectic/calibration.py`) already compares stated confidence against outcomes and has a coupling pathway to I via entropy. A parallel channel pays full datamodel costs (new table, refresh task, schema field, name that implies physics-equivalence with the other channels) for a v1 that explicitly won't couple. Enrichment + audit-view is the same signal with less commitment.

### What this is NOT

- Not a replacement for behavioral_eisv.
- Not surveillance — pull-based for agents (opt-in invocation), and the dashboard shows categorical status only. The numeric magnitude is explicit-invocation-only to resist accidental ranking.
- Not a trust score. `calibration_delta` measures alignment between self-report and observation, not correctness. The dashboard indicator uses categorical language ("aligned" / "drifting") to reinforce this.
- Not a new EISV channel. The audit produces a diff view; it does not introduce a parallel state vector.

## 3. Design

### 3.1 `audit_trajectory` MCP tool

```
audit_trajectory(
  agent_id: UUID,
  window_seconds: int = 3600,
) -> {
  agent_id: UUID,
  window: {start_ts, end_ts, seconds},

  self_report: {
    checkin_count: int,
    mean_stated_complexity: float,
    mean_stated_confidence: float,
    most_recent_response_text_excerpt: str,  // redacted, truncated to 256 chars
  },

  observations: {
    tool_call_count: int,
    tool_mix: {tool_name: count, ...},
    outcome_events: {success: int, failure: int},  // from auto_ground_truth
    dialectic_participations: int,
    lifecycle_events: [{type, ts}, ...],  // paused, resumed, archived, etc.
    checkin_cadence_seconds: float,  // median interval between check-ins
  },

  calibration_delta: {
    E: float, I: float, S: float, V: float,
    magnitude: float,  // overall, 0.0-1.0
    interpretation: "aligned" | "mild_drift" | "systematic_miscalibration",
    dominant_dimension: "E" | "I" | "S" | "V" | null,
  },

  observation_confidence: float,  // 0.0-1.0, reflects how many signals contributed
  notes: [str, ...],  // narrative observations, e.g. "stated complexity mean 0.2, observed 47 tool calls"
}
```

**Authorization** (deliberate, not open): callers may audit themselves freely. To audit another agent requires `client_hint in ("resident", "operator")` or an explicit governance allow-list entry. Same pattern as `archive_orphan_agents`. Not an open question.

**Implementation pattern:** read-side query only. No new tables. Computation happens at call time from existing tables — `audit.tool_usage`, `audit.outcome_events`, `audit.tool_usage` filtered by tool name for check-ins, `core.dialectic_sessions`. Follows the anyio-asyncio mitigation pattern — pure read, no writes in the handler path.

**Cache (optional, can defer):** last-run result cached in Redis per (agent_id, window_seconds) with short TTL (60s default) so dashboard reads don't re-compute.

### 3.2 `calibration_delta` on the calibration surface

The existing calibration pipeline (`src/mcp_handlers/admin/calibration.py`, `src/mcp_handlers/dialectic/calibration.py`) already compares stated vs. observed for confidence. Extend it to compute per-dimension deltas (E/I/S/V) using the same aggregator that `audit_trajectory` uses internally. Output:

- Add `calibration_delta: {E, I, S, V, magnitude, categorical}` to the response of the existing `calibration` MCP tool
- Surface `categorical` (aligned / drifting) on the dashboard's calibration panel

**Key constraint to prevent double-counting:** calibration_delta is computed from the SAME data sources as `audit_trajectory` (single pipeline). There is not a separate pipeline that would risk double-counting the same signal. When the v2 decision about coupling calibration_delta back into I is made (separate spec), this invariant is what makes coupling safe.

### 3.3 Aggregation formula (v1 concrete, not heuristic)

The spec earlier hand-waved "heuristic aggregation." Commit to something concrete for v1:

- **E_delta** = `tanh( (observed_tool_rate / expected_tool_rate) - 1 )` where expected is derived from `self_report.mean_stated_complexity` via a linear regression fit across historical agent data. Bounded [-1, 1], clipped to the E range.
- **I_delta** = mismatch between stated_confidence and outcome_event success rate in the window. Already computed by calibration_checker — reuse.
- **S_delta** = variance in check-in cadence + tool-mix entropy. High observed entropy relative to low stated complexity = drift.
- **V_delta** = integral of E_delta - I_delta over the window. Mirrors how `behavioral_eisv.V` is computed.

These are v1 formulas. They are NOT grounded in the same thermodynamic physics as `behavioral_eisv`. That is deliberate and named: the output is a *diff* in EISV-shape, not a parallel EISV. The `magnitude` field is what matters; the per-dimension values are interpretive.

If after eyeball time on real data the formulas are wrong, revise them in a follow-up — this is a cheap iteration cycle because no schema change is required.

### 3.4 Prerequisite: audit payload must not be empty (Stage 0)

Today, `audit.tool_usage.payload` is `{}` for every recorded call. Without arguments captured, observation has no window into what check-ins claimed.

Before any of §3.1–3.3 can ship, wire the arguments into `audit.tool_usage.payload` with:

- **Field allowlist:** `process_agent_update` records `response_text`, `complexity`, `confidence`, `task_type`. No `continuity_token`, no `client_session_id`, no free-form metadata. `onboard` records `name`, `model_type`. Other tools: name + minimal params, case-by-case.
- **Redaction:** reuse the 5-pattern secret redactor shipped in the plugin tonight (`unitares-governance-plugin/scripts/_redact.py`) — lift it into `unitares/src/services/` or duplicate. Applied before write.
- **Size cap:** 4 KB per row (payload column). `response_text` truncated to 512 chars after redaction (already the plugin's convention).
- **Owner:** `src/services/tool_usage_recorder.py` needs the change. Single author, small PR.

This is a shippability blocker, not a parenthetical. Tracked as its own work item.

## 4. What ships

One PR-sized change per bullet, roughly:

1. **Stage 0 — populate audit payload with redaction + size cap.** Prerequisite.
2. **Stage 1 — `audit_trajectory` tool.** Read-side aggregator. Returns the diff view.
3. **Stage 2 — calibration_delta on the calibration tool output.** Uses the same aggregator internally.
4. **Stage 3 — dashboard indicator.** Categorical only. Reads from the calibration tool response.

There is no "v2 coupling" staged here. If future work wants to let `calibration_delta` affect I via entropy coupling, that is a separate spec with its own justification. Diagnostic-only is the permanent default unless and until that decision is made explicitly. No implicit gate.

## 5. Open questions (narrower than before)

1. **Observation windowing.** Default 1h rolling, but: some agents work in 15-min bursts with long gaps. Adaptive window based on check-in cadence vs. fixed? Start fixed, revisit if operators find the output noisy.

2. **Tool-mix signal weighting.** Section 3.3 says "tool-mix entropy contributes to S_delta" but the weights aren't defined. Start with: edit tools weigh high, read tools weigh low, tool variety increases S. Empirical tuning after operators use it.

3. **What to do when the window contains zero observable activity.** Agent onboarded but did nothing measurable — return `observation_confidence=0.0` and omit calibration_delta? Or hold last delta? Lean: report zero confidence, let consumers decide what to do with it.

**Deliberately closed:**

- ~~Double-counting risk between calibration and observed_eisv~~ — resolved structurally by single pipeline.
- ~~v2 coupling gate~~ — no v2 in this spec.
- ~~Cross-agent audit authorization~~ — resolved: resident + operator only.
- ~~Trust-score framing~~ — resolved by categorical-only dashboard surface.

## 6. Acceptance (v1)

- `audit.tool_usage.payload` contains redacted, size-capped arguments for every logged `process_agent_update` and `onboard` call
- `audit_trajectory(agent_id, window_seconds)` returns a coherent report for any active agent
- The `calibration` MCP tool includes `calibration_delta` in its response
- Dashboard calibration panel shows an "aligned" / "drifting" indicator
- An operator (Kenny) can call `audit_trajectory` on a known over-reporting agent and see a `magnitude > 0.3` with a coherent narrative in `notes`

## 7. Why this is foundational

The new mechanism is small. The conceptual move is what matters: the system acknowledges that `behavioral_eisv` is self-report, and makes the gap between self-report and observation a first-class readable quantity. This retroactively gives observation-style signals (plugin hooks, sensor data, subagent reviewers) an honest semantic home — they produce records in `audit.tool_usage` and `outcome_events`; `audit_trajectory` reads them.

The philosophical frame ("observer-vs-self distinction as foundational") should land in a separate concept doc under `docs/concepts/` so the architectural reasoning survives independent of this tool's implementation details. This spec is narrow on purpose.
