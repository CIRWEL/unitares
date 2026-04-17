---
name: Observed EISV & Trajectory Audit
description: Add a third EISV channel — observed_eisv, derived from external ground truth rather than agent self-report. Makes the observer-vs-self distinction first-class in UNITARES. Diagnostic in v1; coupled in v2.
status: Draft
author: Kenny Wang
date: 2026-04-17
---

# Observed EISV & Trajectory Audit — Design Spec

## 1. Problem

UNITARES tracks agent state through `process_agent_update` check-ins. Every check-in is **self-report**: the agent narrates what it did, how complex it was, how confident it is. The server updates `behavioral_eisv` accordingly.

This produces a structural gap: **the thing being measured is also the thing doing the measuring.** Three concrete failure modes follow from it:

1. **Flattering self-report is indistinguishable from honest self-report.** An agent that claims `complexity=0.2, confidence=0.8` on work that actually changed 2000 lines and broke three tests moves through governance with the same signal as an agent reporting the same numbers on work that really was trivial. Calibration catches a narrow slice of this (overconfidence vs. binary outcomes) but doesn't see the shape of the drift.

2. **Plugin-hook check-ins are tagged but not semantically distinct.** Tonight (2026-04-17) we shipped `metadata.source=plugin_hook` on hook-emitted check-ins — a surveillance-style observation narrated on the agent's behalf — but the server treats them identically to agent-composed check-ins. Two different signal types, one EISV channel. The tag is cosmetic.

3. **The "agent on behalf of agent" pattern has no honest home.** Plugin hooks, subagents that inspect EISV, sensor-derived signals — all of them are observations *about* agents, not self-reports *from* agents. Currently they either (a) impersonate the agent by posting as it, (b) pollute behavioral_eisv with mixed semantics, or (c) sit outside governance entirely. There's no place for observations to live with their nature preserved.

UNITARES claims to give agents "digital proprioception." Proprioception is the agent knowing itself. But there's no such thing as calibrated self-knowledge without an external reference — nervous-system proprioception is calibrated against vision, touch, gravity. UNITARES currently has no external reference channel.

## 2. Approach

Add `observed_eisv` as a **third EISV channel** alongside `behavioral_eisv` (self-reported) and `ode_eisv` (theoretical dynamics). Derive it from ground-truth signals the agent cannot compose: actual tool usage, code diffs, test outcomes, timings.

Stage rollout:

- **v1 (this spec): diagnostic only.** `observed_eisv` is computed, stored, exposed via `audit_trajectory` and `get_governance_metrics`, and visible on the dashboard. It does NOT feed back into verdicts or coherence. The gap between `behavioral` and `observed` is surfaced as `calibration_delta` for operators and agents to read.

- **v2 (future, out of scope here): coupled.** Sustained `calibration_delta` degrades I (Information Integrity) via the existing entropy-coupling pathway that already penalizes overconfidence. Dialectic reviews can cite it. Operators can set thresholds.

Diagnostic-first matches how UNITARES has historically added channels (behavioral_eisv was added before being made primary; calibration was tracked before penalizing I). It also means v1 is safe to ship — it cannot break any current verdict; it only adds a read-only view.

### What this is NOT

- Not a replacement for behavioral_eisv. The agent's self-model remains first-class. Observation is the *reference*, not the truth.
- Not surveillance. Observations are derived from data the agent's actions already produce (tool calls, git commits). No keylogging, no screen-scraping.
- Not a perfect ground truth. Observed_eisv is a heuristic aggregation of ground signals — fallible, but fallible in different ways than self-report.
- Not a trust score for agents. The signal is calibration (how well self-report matches observation), not correctness.

## 3. Design

### 3.1 The `observed_eisv` channel

Schema mirrors behavioral_eisv:

```
observed_eisv: {
  E: 0.0-1.0,
  I: 0.0-1.0,
  S: 0.0-1.0,
  V: -1.0-1.0,
  confidence: 0.0-1.0,   // how many observation signals contributed
  window_seconds: int,   // the window over which this was computed
  last_updated: timestamp,
}
```

Computed from observation signals (§3.2), not from check-ins. Stored in `core.observed_state` (new table, same shape as `core.agent_state`). Exposed in `get_governance_metrics` output alongside the existing channels.

**Who computes it?** Governance server. Not the auditor agent, not the plugin. The server owns every EISV channel because the server owns the invariant. Letting an external auditor *submit* observed_eisv would re-introduce the observer-as-agent fiction we're fixing.

The server has a background task (similar to the existing `deep_health_probe_task` pattern for avoiding anyio-asyncio deadlock) that periodically refreshes `observed_eisv` per active agent by aggregating signal sources (§3.2) over a rolling window.

### 3.2 Observation sources

Every signal must be data the agent produces by acting, not by reporting. Initial source set:

| Source | Already recorded? | Signal |
|---|---|---|
| `audit.tool_usage` | Yes (2026-04-17) | Tool-call rate, mix, latency — drives observed E and observed S |
| Check-in frequency and regularity | Yes | Cadence — supports observed I (consistent behavior → high) |
| `auto_ground_truth` outcome_events | Yes | Test pass/fail, exit codes — supports observed I |
| Knowledge graph contributions | Yes | Notes/discoveries published — supports observed E |
| Dialectic participation | Yes | Paused/resumed, thesis/synthesis — supports observed V |
| Lifecycle events (paused, archived) | Yes | Operator interventions — supports observed V and S |

**Observation gap to close first (prerequisite):** `audit.tool_usage.payload` is currently `{}` — the audit records that `process_agent_update` was called but drops the arguments. For observed_eisv to see "what the check-in claimed" vs "what the tools did," the payload must be written. Tracked as a blocker (see §5).

**Deliberately out of the initial source set:**

- Git diff size / commit content — requires operator-hook plumbing we do not have in governance. Defer to v2 when plugin hooks stabilize and can push diff summaries as observation events.
- Browser / IDE activity — too noisy, too invasive.
- Model token usage — tempting but not shaped to EISV.

### 3.3 `audit_trajectory` MCP tool

```
audit_trajectory(
  agent_id: UUID,
  window_seconds: int = 3600,  // default 1 hour
) -> {
  behavioral_eisv: {...},
  observed_eisv: {...},
  calibration_delta: {
    E: float,  // observed.E - behavioral.E
    I: float,
    S: float,
    V: float,
    magnitude: float,  // overall gap score, 0-1
    interpretation: "aligned" | "mild_drift" | "systematic_miscalibration",
  },
  dominant_gap: "E" | "I" | "S" | "V",  // largest delta
  observation_confidence: float,
  sources_used: [{source: str, weight: float}, ...],
  window_seconds: int,
}
```

Callable by any agent (about itself or about others, when authorized) and by operators. Returns a diff view, not a verdict. Intentionally text-heavy in its "interpretation" field so the output supports narrative review.

### 3.4 `calibration_delta` as an exposed metric

Add to `get_governance_metrics` output:

```
calibration_delta: {
  E: float, I: float, S: float, V: float,
  magnitude: float,
  since: timestamp,
}
```

Surfaces in dashboard as a small indicator ("calibration ±0.XX over last hour"). No verdict implications in v1.

### 3.5 Who runs the audit loop

Two layers:

- **Server background task** (new): `observed_eisv_refresh_task` runs every N seconds (default 60), updates `core.observed_state` for each active agent. Same hardening pattern as `deep_health_probe_task` — runs outside the MCP request path so it cannot hit the anyio-asyncio deadlock.

- **Resident auditor agent** (new, optional in v1): a Sentinel-analogue that periodically reads `calibration_delta` across the fleet, surfaces notable gaps as knowledge-graph notes. Deferred. The server task alone produces the data; the agent is a convenience for ongoing fleet-level observation.

## 4. Staged rollout

**Stage 0 (prerequisite):** Close the audit-payload gap. `audit.tool_usage.payload` currently `{}`. Wire the arguments in (with redaction of secrets and sensible size cap). Without this, observation has no window into what the agent claimed.

**Stage 1: schema + read path.**
- Create `core.observed_state` table
- Add `observed_eisv_refresh_task` that computes from existing sources, writes to the table
- Extend `get_governance_metrics` to include `observed_eisv` and `calibration_delta`

**Stage 2: the `audit_trajectory` tool.** Surface the data for on-demand inspection.

**Stage 3: dashboard integration.** Calibration-delta indicator on the fleet view.

**Stage 4 (v2, separate spec): coupling.** `calibration_delta` feeds I via the entropy pathway. Dialectic reviews cite it. Verdicts may reference it.

## 5. Open questions

1. **Observation windowing.** Fixed 1-hour rolling window vs. exponential moving average vs. calibration-event-driven updates? Affects responsiveness and stability.

2. **Observation weighting.** How much does `audit.tool_usage` weigh vs `auto_ground_truth` outcome events? Initial default: outcome events heaviest (they are the cleanest ground truth), tool_usage middle, cadence/lifecycle lightest. Tune empirically.

3. **Empty-observation periods.** An agent that did nothing observable for a window — idle, paused, external-blocked — has observed_eisv uncertainty. Fall back to `ode_eisv`? Or hold the last observation? Or widen the window?

4. **Cross-agent audit authorization.** `audit_trajectory(agent_id=<other agent>)` — should any agent be able to audit any other? Restrict to resident agents? Require operator approval? Start restrictive.

5. **Audit-payload size budget.** Writing full `process_agent_update` arguments to `audit.tool_usage.payload` is unbounded. Cap at 4KB? 16KB? Compressed? Tie to `UNITARES_CHECKIN_MODE` verbosity once that's built.

6. **Calibration-delta interpretation thresholds.** "aligned / mild_drift / systematic_miscalibration" needs numeric cutoffs that depend on the EISV range and observation confidence. Needs empirical tuning — ship with conservative defaults, adjust once operators have eyeball time on the data.

## 6. Acceptance (v1)

Done when:

- `audit.tool_usage.payload` contains arguments for every logged tool call (stage 0)
- `core.observed_state` exists and is populated continuously (stage 1)
- `get_governance_metrics` returns `observed_eisv` and `calibration_delta` (stage 1)
- `audit_trajectory` tool returns a coherent report for any active agent (stage 2)
- Dashboard shows calibration delta next to behavioral EISV (stage 3)
- An operator (Kenny) can eyeball a known over-reporting agent and see it flagged

v2 scope — coupling calibration_delta into I, surfacing in verdicts, auditor-agent fleet analysis — lives in a later spec.

## 7. Why this is foundational

Without this, UNITARES has a persistent semantic dependency on the agent's honesty. Calibration catches narrow overconfidence but not the broader class of self-report drift. Adding a genuinely external observation channel — one the agent cannot author — is what makes the claim of "agent proprioception" honest.

It also retroactively gives every observation-style signal in the system (plugin hooks, subagent reviewers, sensor-derived metrics from Lumen) a semantic home. They feed `observed_eisv`, not `behavioral_eisv`. The difference is the point.
