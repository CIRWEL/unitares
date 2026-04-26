---
title: Compute-Receipt Sidecar — measuring tokens without folding them into EISV
status: draft
author: Kenny Wang (with Claude)
date: 2026-04-25
tags: [observability, calibration, ontology, EISV-adjacent]
---

# Compute-Receipt Sidecar

## Problem

UNITARES does not currently measure compute. Token counts, model identity, wall-time, and per-call cost never enter the governance pipeline. The closest existing proxies — task `complexity` (feeds S) and check-in cadence (feeds E indirectly) — see only what the agent *self-reports*, not what the run actually cost.

This is a real gap, not a cosmetic one:

- **Slop detection**: an agent producing 50k tokens to resolve a 1-line fix is leaking signal we cannot read.
- **Thrash detection**: bursty token spend within a short window correlates with retry loops, but we cannot see it.
- **Operator economics**: $/verdict and $/resolved-finding are the metrics that determine whether a fleet is sustainable. Today they are computed nowhere.
- **Cross-fleet calibration**: when fleet composition shifts (Opus → Haiku, or new agent class added), we have no compute axis to disentangle "agent got better" from "agent got cheaper to run."

## Non-goals (what this is explicitly NOT)

1. **Not a fifth EISV channel.** Tokens are not isomorphic across models — one Opus token ≠ one Haiku token thermodynamically. Folding tokens into E or S would violate the "physics grounding" rule (`feedback_eisv-surface-sprawl.md`) and would fail the heterogeneous-fleet promise that paper v6.8 makes.
2. **Not basin-feeding.** The basin solver (`governance_core`) MUST NOT read this signal. Compute receipts are audit-layer data, joined to verdicts post-hoc.
3. **Not agent-self-reported truth.** When the harness has the data (Claude Code, dispatch-claude, dispatch-codex), the harness emits the receipt — not the agent. Self-reported tokens are advisory at best.
4. **Not a Goodhart target.** Receipts are observed and analyzed; agents are not graded against them. Penalizing high-token agents would optimize for compression at the cost of correctness — the exact failure mode UNITARES is designed to surface, not invert.

## Proposed shape

A new optional `compute` payload accepted by `outcome_event` (and, in phase 2, by `process_agent_update`), persisted to a sidecar table joined by event id.

### Schema sketch

```jsonc
// outcome_event arguments — new optional field
{
  "outcome_type": "task_completed",
  "outcome_score": 1.0,
  // ... existing fields ...
  "compute": {
    "tokens_in": 12450,
    "tokens_out": 3120,
    "cache_read_tokens": 8900,        // optional, harness-provided
    "cache_creation_tokens": 0,
    "model_id": "claude-opus-4-7",     // canonical model identifier
    "wall_time_ms": 4823,
    "tool_calls": 7,                   // optional
    "cost_usd": 0.184,                 // optional, derived; null if rate unknown
    "source": "harness_emitted"        // {harness_emitted, agent_self_reported}
  }
}
```

### Storage

New table `compute_receipts`:

| column | type | notes |
|---|---|---|
| receipt_id | uuid | pk |
| event_id | uuid | fk → outcome_event.id (nullable; check-in receipts have no outcome) |
| agent_id | uuid | fk → agents |
| client_session_id | text | for in-process aggregation |
| tokens_in | int |  |
| tokens_out | int |  |
| cache_read_tokens | int | nullable |
| cache_creation_tokens | int | nullable |
| model_id | text |  |
| wall_time_ms | int |  |
| tool_calls | int | nullable |
| cost_usd | numeric(10,4) | nullable |
| source | text | enum |
| created_at | timestamptz |  |

Index on `(agent_id, created_at)` for per-agent burndown queries.

### Why a sidecar table, not a column on `outcome_event`

- Receipts attach to events that have no outcome (mid-task check-ins, dialectic submissions, knowledge writes) — eventually.
- Joining stays cheap because we keep the FK.
- The basin solver's read path stays untouched. No risk of accidentally reading compute into EISV.

## Hooks / integration

### Phase 1 — outcome-event-only, harness-emitted

- `outcome_event` MCP handler accepts optional `compute`; validates with a Pydantic schema in `src/mcp_handlers/schemas/`.
- `dispatch-claude` and `dispatch-codex` plists already capture per-call usage; they emit it on the `outcome_event` boundary.
- Claude Code session: the `post-edit` hook does not have token data, but the `Stop` / session-end hook does — we add a session-receipt emitter that joins per-tool-call receipts under one `client_session_id`.

### Phase 2 — check-in receipts

- `process_agent_update` accepts `compute`. Used for "this check-in cost N tokens" rather than per-outcome cost. Useful for long-running residents (Sentinel, Steward, Chronicler).

### Phase 3 — derived signals (calibration-only)

Computed nightly by Chronicler (or a new `cost-roller` agent) into `metrics.series`:

- `tokens_per_resolved_outcome` — per agent-class
- `cost_per_verdict` — per (agent-class, verdict) pair
- `thrash_index` — burst variance within a session
- `slop_index` — outlier detection on tokens / outcome_score

These feed dashboards and are surfacable as **calibration evidence**, never as EISV input.

## Phasing

| phase | scope | risk |
|---|---|---|
| 1 | schema + Pydantic + outcome_event field + dispatch-{claude,codex} emitters | low — additive |
| 2 | process_agent_update support; resident-agent self-reporting | low |
| 3 | Chronicler roll-ups, dashboard panel, calibration view | medium — UI / data model |
| 4 | Discord-bridge surfacing of slop / thrash anomalies | medium — operator-facing |

Phases are independently shippable and reversible. Phase 1 alone is a large unlock for grant-proposal economics.

## Risks & open questions

1. **Heterogeneous model_id namespace.** Agents from different harnesses report different model strings ("claude-opus-4-7" vs "claude-3-opus-20240229" vs "opus"). Need a canonicalization layer — either at write or at query time. Suggest write-time, with an unrecognized-model log line.
2. **Cost-rate staleness.** `cost_usd` requires a price table that drifts. Either accept stale dollars (mark with rate_version), or derive cost only at query time from a canonical rates file checked into the repo.
3. **Privacy / leakage.** A token count alone is not sensitive. But pairing high-token outcome with rejected verdict starts to expose internal model behavior. Receipts should not be in any public export by default.
4. **Self-report vs harness gap.** Codex and Gemini harnesses surface usage less reliably than Claude Code. Agents in those environments will have spotty receipts. Acceptable — receipts are advisory, and downstream analyses must report `n_with_compute / n_total`.
5. **What about the residents?** Vigil, Sentinel, Chronicler, Steward run via `claude` / `codex` / direct Python. Some have receipts, some have none (pure-Python). Don't paper over this — make `source: null` a first-class value and let the dashboard flag uncovered agent-classes.
6. **Should this be its own MCP tool?** Considered `compute_receipt(...)` as a peer to `outcome_event`. Rejected for phase 1: forces the harness to make a separate call, doubles failure surface. Folded into existing outcome path. Revisit in phase 2 if check-in receipts justify it.

## Provisional decisions

- ✅ Sidecar table, not column.
- ✅ Optional payload on `outcome_event` for phase 1.
- ✅ Basin solver never reads it — enforced by leaving the read path out of `governance_core`.
- ✅ Harness-emitted preferred; `source` column makes provenance explicit.
- ⚠️ Cost derivation deferred — store tokens, derive dollars at read time from a versioned rates file.
- ⚠️ Discord-bridge surfacing deferred to phase 4.

## What this changes about UNITARES's story

Paper v6 currently does not claim to measure compute. With this in place, the fleet-economics paragraph of v7 can include a real cost-axis: not "agents got better" but "agents got better *per token*." That separation is the kind of thing deep-tech-explicit funders (per `feedback_deep-tech-positioning.md`) read for substance.

It also lets UNITARES answer a question it has been ducking: *what does it cost to run governance itself?* The Steward/Vigil/Chronicler stack has a non-trivial token bill. Surfacing it is the honest move.
