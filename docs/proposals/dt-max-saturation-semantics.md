# DT_MAX Saturation Semantics — Design Note

**Status**: Proposed  
**Date**: 2026-05-11  
**Context**: PR #224 deferred task #7  
**Scope**: `src/governance_monitor.py` · `governance_core` ODE · `unitares-paper-v6/unitares-v6.tex`

## The Problem

PR #224 fixed `last_update` persistence so cross-restart gaps now integrate correctly. A side effect is that the DT_MAX saturation band is very narrow. From `config/governance_config.py`:

```
DT = 0.1                     # base timestep
DT_EXPECTED_INTERVAL = 15.0  # expected check-in cadence (seconds)
DT_MAX = 1.0                 # Euler stability cap
```

The linear scale formula (`process_update`, post-PR #224):

```python
scaled_dt = elapsed_seconds * (DT / DT_EXPECTED_INTERVAL)
effective_dt = max(DT, min(scaled_dt, DT_MAX))
```

`scaled_dt > DT_MAX` when `elapsed > DT_MAX * DT_EXPECTED_INTERVAL / DT = 150 seconds`.

Any gap longer than **2.5 minutes** hits the cap. A 17-hour gap and a 30-hour gap both integrate as `effective_dt = 1.0`. Gap information above 150 s is silently discarded from the ODE. The info-level log added by PR #224 makes this operator-visible, but does not resolve it.

## What the Cap Protects

`DT_MAX` is an Euler stability constraint, not a physical timescale. The forward-Euler step in `governance_core.step_state()` is conditionally stable only for small dt. With the current dynamics (μ = 0.8 decay on S, δ = 0.4 on V), `dt > 1/μ ≈ 1.25` risks instability. `DT_MAX = 1.0` gives a safety margin. This constraint is unrelated to the physical meaning of a long gap.

## Architecture Note: ODE Is Now Diagnostic

Since `BEHAVIORAL_VERDICT_ENABLED = True` (default), the ODE no longer drives verdicts. Behavioral assessment (EMA + z-score) is primary; ODE provides the phi objective, regime detection, and historical continuity. The practical urgency of option (a) is therefore lower than at PR #224 ship time — but the information loss remains real for operators reading EISV traces.

## Three Candidate Resolutions

### Option (a) — Variable-Step Integrator

Replace the Euler step in `governance_core.step_state()` with `scipy.solve_ivp` (RK45 or similar). The integrator handles arbitrarily large gaps without stability concerns.

**Pros**: Physically correct gap integration; no information loss.  
**Cons**: Changes ODE numerics (all existing EISV histories become non-comparable across the cutover); requires paper revalidation of new discretization scheme; scipy in the hot path; not a small change. Requires full council review.

### Option (b) — Explicit Stale-Gap Flag Bypassing ODE Information Loss

Above a gap threshold τ (e.g., 4 hours), continue running the ODE with `effective_dt = DT_MAX` (no numeric change), but emit a `stale_gap: true` flag and `gap_seconds` field in the `process_update` result dict. Callers and operators can surface this signal instead of silently treating a 17h gap as identical to a 150s gap.

**Pros**: No ODE change; no paper-numeric impact; operator-visible; honest about what the model cannot represent; τ is tunable without touching numerics.  
**Cons**: Introduces a new result field that downstream consumers must handle; requires a paper note clarifying stale-gap semantics; τ threshold is a new parameter to maintain.

### Option (c) — Document as Known Approximation

Add a paragraph to `unitares-v6.tex` §sec:equations noting that the discretization uses forward Euler with stability cap `DT_MAX`, and that gaps longer than `DT_MAX * DT_EXPECTED_INTERVAL / DT` seconds are represented as `DT_MAX` in the decay integral. No code change.

**Pros**: Minimal; honest; zero operational risk.  
**Cons**: Leaves the silent information loss in place; a 17h vs 30h gap remains indistinguishable in EISV traces. Only viable if the ODE's diagnostic role is considered permanently secondary.

## Recommendation: Option (b)

Option (b) is recommended for the following reasons:

1. **Saturation is not an edge case.** The cap fires at 150s — any agent offline for > 2.5 minutes hits it. Gap saturation is the normal case for overnight or weekend gaps, not an exception.

2. **The ODE is in a diagnostic role but still read.** Operators inspecting EISV traces or phi plots after a long gap cannot currently tell whether a decay curve reflects a real 30-hour physics event or a clipped 150s step. The stale flag restores that interpretability without changing the physics.

3. **Option (a) changes published numerics.** Any paper-published result or operator dashboard that records EISV histories becomes non-comparable across the cutover. This deserves a separate, deliberate decision with full council review.

4. **Option (c) is honest but incomplete.** Documenting the approximation without exposing it programmatically means operators must manually cross-reference logs against the paper to interpret any saturated trace.

## Implementation Sketch (for operator review — do not implement without approval)

`config/governance_config.py` gains:
```python
DT_STALE_THRESHOLD_SECONDS = 4 * 3600  # 4 hours; tunable
```

`process_update` emits `stale_gap: bool` and `gap_seconds: float` in the result dict, set when `elapsed_seconds > DT_STALE_THRESHOLD_SECONDS`. No change to `effective_dt`. The existing DT_MAX saturation log line stays.

The paper gains a sentence in §sec:equations describing the Euler stability cap and citing `DT_MAX`. This note is owed regardless of which option is chosen — the paper currently has no mention of discretization.

## Paper Scope

The paper repo (`unitares-paper-v6`) is NOT modified in this run per the operator instruction. A §sec:equations discretization note is the minimum required for any of the three options and should be added in the same PR that implements the chosen resolution.

---

*Filed 2026-05-11 as follow-up to PR #224, task #7. No runtime changes made.*
