# Circuit Breaker + Dialectic Recovery

**Last Updated:** 2026-02-04 (v2.5.5)

This system uses a **circuit breaker** to pause agents when risk signals or coherence drop below safe thresholds. Recovery is handled via a **dialectic protocol** (structured peer review) that provides a safe path to resume.

This document is the canonical overview for the dialectic flow implemented in `src/dialectic_protocol.py`.

---

## When the Circuit Breaker Triggers

The governance loop evaluates EISV state, coherence, and risk. If the agent enters a high‑risk or low‑coherence region, the system returns a **pause** decision and the agent enters a “paused” or “waiting_input” state.

Common triggers:
- Low coherence (fragmented output or inconsistent work)
- Elevated risk score
- Persistent void activity (energy–integrity imbalance)

The circuit breaker is a **protective pause**, not a failure. It exists to prevent runaway behavior and prompt a structured review.

---

## Dialectic Protocol Overview

Dialectic recovery is a structured peer review process:

1. **Thesis** — paused agent explains what happened and proposes recovery conditions
2. **Antithesis** — reviewer challenges the proposal or highlights risks
3. **Synthesis** — resolution: approve, revise, or keep paused

The protocol is implemented in `src/dialectic_protocol.py` and exposed via MCP handlers in `src/mcp_handlers/dialectic.py`.

Phases:
- `thesis`
- `antithesis`
- `synthesis`
- `resolved` | `escalated` | `failed`

---

## Recovery Paths

### 1) Full Dialectic Review (default)

Use when the pause reason is not trivial or when risk is elevated.

Key tools:
- `request_dialectic_review` — start a review session
- `get_dialectic_session` — monitor progress by session id or agent id

### 2) Direct Resume (Tier‑1)

For simple stuck scenarios (timeouts, trivial stalls) when the state is safe:

- `direct_resume_if_safe` — checks coherence/risk/void and resumes if safe

Recommended conditions:
- short monitoring window
- reduced complexity for a few updates

---

## Suggested Workflow

**Paused agent (thesis):**
1. Inspect state: `get_governance_metrics`
2. Request review: `request_dialectic_review(reason=...)`
3. Provide thesis: explain cause, propose constraints (e.g., “cap complexity to 0.4”)

**Reviewer (antithesis):**
1. Challenge assumptions
2. Propose safeguards or alternative steps

**Resolution (synthesis):**
1. Accept + resume (with conditions)
2. Revise + continue review
3. Escalate or keep paused

---

## Storage + Auditing

Dialectic sessions are stored in PostgreSQL when `DB_BACKEND=postgres`:
- `core.dialectic_sessions`
- `core.dialectic_messages`

This provides durability and auditability, enabling post‑hoc review and calibration backfills.

---

## Related Tools

- `get_dialectic_session` — inspect session state and transcript
- `direct_resume_if_safe` — fast path resume when safe
- `mark_response_complete` — use if the agent is simply waiting for input
- `backfill_calibration_from_dialectic` — optional calibration based on resolved sessions

---

## Implementation Notes

The main dialectic protocol is implemented in:
- `src/dialectic_protocol.py` (core logic)
- `src/mcp_handlers/dialectic.py` (MCP tool handlers)

If you are modifying the protocol, update this document and the tool docs to keep agent guidance aligned.
