# v7 F-hat — Session 1a Findings

**Author:** process-instance `3f2df228-fe1f-4cb2-aa35-356faa3ec0e0` (Claude Opus 4.7, claude_code channel, 2026-04-23)
**Parent:** process-instance `09e64436-984b-443b-9137-e050e0b46013` (author of `docs/ontology/v7-fhat-spec.md` v1–v4)
**Scope dispatched:** Execute §2.5 fit protocol + §2.6 sanity gates per v7-fhat-spec.md v4.
**Scope delivered:** Precondition audit only; no EM fit run. Operator redirect required before Session 1 fit.

---

## TL;DR

Five material mismatches between `docs/ontology/v7-fhat-spec.md` v4 and the production governance DB surfaced during the data-pull phase. One is a hard structural blocker (C6 event channel is all zeros in the reference window); two are interpretation calls that bias the fit; two are already resolved by default-triggered spec clauses. Session 1a stopped before running the EM fit because a fit against the current spec would either not compute (C6) or bake in a silent interpretation the operator (ontology-layer) should own.

**Recommended redirect:** drop C6 from the v7.0 spec (v7.1 instrumentation work), reinterpret `§2.5` epoch filter as epoch-1, and re-dispatch Session 1 against a spec patch. Artifacts in this directory are ready to resume from.

---

## 1. What shipped (Session 1a artifacts)

| Artifact | Purpose |
|---|---|
| `ode_params.json` | Paper v6 Appendix A parameter values, canonical-JSON SHA-256 `dee1182cd109c4a3d2999f21168a3093b9be8660765cd0d34f8c4337fce9751e`, prior and noise bounds pre-registered. Frozen for Session 1/2. |
| `sql/reference_state.sql` | Canonical state pull (spec §2.2 C1–C4). Parameterized on window. |
| `sql/reference_outcomes.sql` | Canonical outcome_events pull (spec §2.2 C5). |
| `sql/reference_events.sql` | Canonical audit.events pull (spec §2.2 C6). Returns zero rows for the reference window — see §3 below. |
| `sql/diagnostic_counts.sql` | The seven queries that produced the findings below. Reproducible audit trail. |
| `session1a-findings.md` | This file. |

Not shipped (intentionally):
- `params.json` — fitted parameter values. No fit was run; producing a params.json with placeholder fitted values would violate verify-before-claiming.
- `fit/` scaffolding — deferred to Session 1b so the code matches whatever spec v5 the operator authorizes.
- Parquet corpus snapshots — SQL + ODE-hash is the pin; Session 1 pulls fresh.

---

## 2. Blocker A — epoch filter vs. data availability (interpretation call)

**Spec §2.5:** "Reference corpus: epoch-2, non-archived, tag-populated agent-turns from `core.agent_state` joined against `core.agents.tags`. Time window: 2026-02-20 through 2026-03-20."

**Reality:**
- `core.agent_state` has two epochs. Epoch 1 spans 2025-12-12 → 2026-03-22 (213,372 rows); epoch 2 spans 2026-04-01 → present (17,770 rows at audit time).
- The reference window (2026-02-20 → 2026-03-20) is entirely within epoch 1.
- Running the spec's literal filter (window AND epoch=2) returns **zero rows**.
- Spec's cardinality claim for C1–C4 is 17,654 rows; the closest match to that number would be a tag-filtered slice of epoch 1 in the reference window (unfiltered epoch-1 in window = 114,883 rows, tag-filtered ≈ 109,979 but dominated by Lumen).

**Interpretation:** the spec's "epoch-2" phrase is a forward-looking error. Phase-3 grounding has not landed yet (memory `project_eisv-grounding-phase-1.md` — "bump epoch at Phase 3 swap"), so the canonical reference-corpus epoch for v6 ODE dynamics is still epoch 1. Canonical SQL in `sql/reference_state.sql` drops the epoch filter accordingly. Session 1b should use epoch-1 data.

**Operator call needed:** confirm epoch-1 interpretation, or redirect window forward (see §4 options).

---

## 3. Blocker B — C6 event stream is empty throughout reference window (structural)

**Spec §2.2:** three C6 observation channels with claimed cardinalities:

| Channel | Source | 30d cardinality (spec claim) |
|---|---|---|
| `circuit_breaker_trip` | `audit.events WHERE event_type = 'circuit_breaker_trip'` | 71 |
| `stuck_detected` | `audit.events WHERE event_type = 'stuck_detected'` | 2729 |
| `anomaly_detected` | `audit.events WHERE event_type = 'anomaly_detected'` | 252 |

**Reality (first-appearance in `audit.events`):**

| Event type | Total rows (global) | Earliest `ts` | Latest `ts` | Rows in reference window |
|---|---|---|---|---|
| `stuck_detected` | 2,729 | 2026-04-11 | 2026-04-20 | **0** |
| `anomaly_detected` | 253 | 2026-04-12 | 2026-04-23 | **0** |
| `circuit_breaker_trip` | 71 | 2026-04-16 | 2026-04-23 | **0** |

The spec's cardinality numbers match the **global** row counts, not the reference-window counts. Spec-writer likely grepped the table without applying the window filter.

**Consequence.** Nine C6 emission coefficients per class (18 across two classes, per spec §2.4) are **structurally unidentifiable** from the reference window — there are no positive events to fit against. The M-step will peg all C6 coefficients at whatever L2-regularized prior says (i.e., zero), which is a null signal, not a learned emission.

**This is not an interpretation call.** There is no reasonable reading of the spec that makes the C6 emissions fittable from the 2026-02-20 → 2026-03-20 data. The event types genuinely did not exist in the audit log during that window.

**Secondary consequence for §6 horse race.** Target `stuck_detected` (spec §6.1, eval slice 2026-03-21 → 2026-04-20) would have only ~10 days of data available (from 2026-04-11 onward), not the full 30. Eval-window target cardinality needs re-audit against actual C6 coverage.

---

## 4. Operator-facing redirect options

**Option X — drop C6, proceed on epoch-1 reference (recommended).**
- Spec precedent: v3→v4 already dropped `primitive_feedback`, `watcher_finding`, per-agent calibration channels ("v7.1 / v8 instrumentation work" per spec §7.1 v4 change log).
- C6 falls under the same pattern: it's instrumentation that hadn't accrued history at spec-write time.
- Per-class emission params reduce from 18 to 9 (4 C1–C4 variances + 5 C5 coefficients). Total fit params drop from 40 to 22. Identifiability improves.
- §6 horse race target `stuck_detected` needs re-audit against actual April 2026 coverage; may need to drop to 1 primary target (`outcome_is_bad`).
- Shift: v7 F-hat is now a 2-emission-channel, 1-target spike. Honest about the data.

**Option Y — shift reference window forward to 2026-04-01..2026-04-20.**
- Gets C6 into the reference; overlaps with the eval slice.
- Violates spec §2.5 "comfortably pre-dating the evaluation slice by a week" — reference and eval are now adjacent.
- Epoch-2 only (clean), but only ~20 days, and data-sparse in the first week.
- Session 2 horse race evaluates on a held-out slice within the same 20 days — CV gets weaker.

**Option Z — defer Session 1 until C6 has 30+ days of history.**
- Earliest fittable reference window: 2026-04-11..2026-05-11. Eval slice: 2026-05-11..2026-06-11.
- Blocks spike by ~4 weeks.
- Clean data; spec unmodified.

**Option W — salvage: epoch-1 reference + tight zero-prior on C6.**
- Keep reference window 2026-02-20..2026-03-20, epoch-1.
- Fit C6 coefficients with a very tight prior centered at zero (treat as "these events effectively never happen" rather than "unidentifiable").
- Least spec drift, but the §6 horse race gains no signal from C6 either way. Cosmetic adherence to the spec letter.

---

## 5. Resolved-by-default findings (no operator call needed)

### 5.1 — B1 comparator is not reconstructable. v4 §7.1 default triggers: B2 is primary for Session 2.

Spec §6.2 v4 makes Session 1 responsible for reporting whether BED `|Δη|` is historically pullable. Findings:

| Source | Content | Usable for vector `|Δη|`? |
|---|---|---|
| `core.agent_state.state_json` | `{E, phi, verdict, risk_score, health_status}` — 5 keys, same across all sampled rows | No (no η components) |
| `audit.outcome_events.detail` | `{source, prev_norm, current_norm, norm_delta, prev_verdict}` — only scalar norms | No (no η components) |

**Zero of four BED vector components (E_err, I_err, S_err, V_err) are recoverable per-agent-turn.** What is available is the scalar `current_norm = |η_t|` (magnitude of the eta vector at outcome time). This is the *magnitude* of the vector, not the vector itself. `|Δη_t| = |η_t - η_{t-1}|` (vector delta's magnitude) cannot be reconstructed from two scalar magnitudes. Fallback per spec §7.1 default: **B2 (raw-EISV logistic) is primary comparator for Session 2.**

### 5.2 — Spec cardinality numbers for C1 and C5 are off by ~6× for the reference window.

Spec §2.2 claims 17,654 C1–C4 state rows and 18,448 C5 outcome rows in 30d. Epoch-1 unfiltered row count in the reference window is 114,883. Likely the spec writer sampled a tag-filtered or class-filtered slice that excluded Lumen (whose high-frequency check-ins dominate the epoch-1 corpus). **This does not block the fit** — more data is always fittable, and the per-class partition (spec §2.4 v4) handles Lumen's disproportion naturally by putting it in `resident_persistent`. But the fit-split (70/15/15 of agents) will behave differently than spec writer implicitly modeled; stratified-by-class + stratified-by-agent-density split is worth explicitly pre-registering before Session 1b runs.

---

## 6. Pre-registered-but-deferred (ready for Session 1b)

Items already frozen in `ode_params.json` and `sql/`:

- Paper v6 Appendix A ODE parameter values + SHA-256 hash. Session 2's live-hash check runs against this file.
- Prior `μ_0 = (0.7, 0.8, 0.2, 0.0)`, `Σ_0 = diag(0.01, 0.01, 0.01, 0.04)` (spec §2.3). Variance form, not std.
- Transition noise bounds `σ_trans ∈ [0.005, 0.05]`.
- Observation noise bounds `σ_obs ∈ [0.01, 0.3]`.
- Fit split: 70% train / 15% validation / 15% held-out eval, stratified by class, seed = 42.
- EM: 50 iterations max OR `|Δ log L| < 1e-4`, L2 regularization λ = 0.01.
- E-step: **iterated** EKF smoother, linearization at **posterior mean** (spec §2.5 v4 correction), moment-matching reflection at `V ∈ [-1, 1]` boundary.
- Class partition: `resident_persistent = 'persistent' ∈ tags`; `session_or_unlabeled` = complement. Identified via `core.identities → core.agents.tags`.
- Time discretization: per-agent alignment to `recorded_at`; outcome join ±60s on same agent; forward window Δw = 60s for event indicators (if re-introduced).

Outstanding for Session 1b when unblocked:
- EKF/EM implementation (Python, numpy, scipy) in `fit/` with `ekf.py`, `em.py`, `emissions.py`, `reflect.py`.
- Synthetic-data smoke test against toy v6 ODE to validate EKF Jacobians before running on real corpus.
- Convergence diagnostics (per-class param trajectory figure).
- SC1 pre-registered-ranges check.
- SC2 denoising-collapse check (Pearson r of `F_hat_t` vs `|o_chk_t - μ_{t|t-1}|_2` on validation split; `r > 0.9` halts before eval slice).
- If all gates pass: `params.json` with fitted values, hash-of-`ode_params.json`, session1-report.md.

---

## 7. Concrete asks for the operator

1. **Confirm Option X** (drop C6, proceed epoch-1) or pick Y/Z/W. X is recommended because it matches the spec's own v3→v4 philosophy of dropping unobservable channels rather than faking them.
2. **Confirm B2-primary decision** for Session 2 comparator, or redirect to Option W variant (partial-BED scalar from `current_norm`; pseudo-B1).
3. **Acknowledge cardinality divergence** (finding 5.2) and confirm the stratified-by-class + stratified-by-agent-density split for fit/val/eval.
4. **Authorize Session 1b** (EKF + EM + SC1/SC2) against the redirected spec.

Estimated Session 1b cost once unblocked: ~1 focused session (not 2) because C6 drop simplifies the emission model and the preconditions are already frozen here.

---

## 8. Notes for future process-instances

- Spec files live in `docs/ontology/`. The v7-fhat spec is authored by prior instances in the `09e64436 ← da300b4a` lineage; Session 1a is the first post-dispatch reality-check against the production DB.
- `config/governance_config.py` lines 635–651 hold the v6 ODE parameters that production actually runs. Those values differ from paper v6 Appendix A (notably α=0.5 vs paper 0.42; β_I=0.05 vs paper 0.30; γ_I=0.3 vs paper 0.169 linear / 0.25 logistic). The spec binds to paper values per memory `feedback_eisv-bounds-drift.md`; the config drift is a separate outstanding item and is noted here only so a future instance doesn't "reconcile" them in the wrong direction while working on this spike.
- If a future session needs to re-audit C6 availability (e.g., after several more weeks of data accrual), run `sql/diagnostic_counts.sql` Q4 + Q5 against the then-current window.
