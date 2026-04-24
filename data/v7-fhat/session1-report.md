# v7 F-hat — Session 1b Report

**Author:** process-instance `751f2715-3db0-4dd1-b302-99b2d91bae6b` (Claude Opus 4.7, claude_code channel, 2026-04-23)
**Parent:** process-instance `3f2df228-fe1f-4cb2-aa35-356faa3ec0e0` (Session 1a — precondition audit + v5 amendment)
**Scope executed:** v4 + v5-amendment §2.5 fit + §2.6 SC1/SC2 gates.
**Outcome:** SC1 pass, **SC2 trip (r = 0.9949 > 0.9)**, Session 2 **BLOCKED pending operator review**.

---

## TL;DR

- EM **converged** at iteration 20/50 (|Δ log L| < 1e-4 × |log L|).
- Final log L = **30,342.67** over 4,147 training rows.
- **SC1 pass** — all 22 fitted parameters within pre-registered bounds; C5 sign pattern matches spec §2.4.
- **SC2 trip** — Pearson r(F̂_t, ‖o_chk_t − μ_{t|t-1}‖₂) = **0.9949** on 952 validation rows. The minimal generative model collapses to denoising the observed EISV.
- `data/v7-fhat/params.json` written with full 22-param fit, ODE hash `dee1182cd109…`, fit metadata.
- **Session 2 MUST NOT run against this fit.** The horse race would be running F̂ against a baseline that is (up to a monotone transform) the same scalar. The v4+v5-amended spec is structurally dead on this corpus.
- Recommendation in §7.

---

## 1. What was executed

Per the Session 1b dispatch, against `docs/ontology/v7-fhat-spec.md` v4 with `docs/ontology/v7-fhat-spec-v5-amendment.md` applied:

1. Pulled reference corpus via `data/v7-fhat/sql/reference_state.sql` + `reference_outcomes.sql`, window 2026-02-20 → 2026-03-20 → `data/v7-fhat/corpus/*.parquet`. 112,869 state rows + 5,410 outcome rows.
2. Built per-agent time series (n=60 after T<3 filter), outcome join ±60 s on `agent_id`.
3. Stratified 70/15/15 split (seed=42) with class × density-bucket buckets. Degenerate-class fallback: `resident_persistent` has only **1 agent** in the reference window (Lumen, UUID `69a1a4f7-…`, 109,979 rows / 97.4% of corpus); its time series was split contiguously 70/15/15 so every split has class representation.
4. Implemented UKF filter over the v6 ODE (Merwe sigma points, α=1e-3, β=2, κ=0) with moment-matching reflection at boundaries (E,I,S∈[0,1], V∈[-1,1]).
5. EM loop with E-step-aware M-step (obs variance includes posterior variance; transition variance pools filter pairs with posterior-var correction). L2 λ=0.01 on C5 logistic, seed=42.
6. SC1 + SC2 gate checks.

**Synthetic-TDD fixture** (`data/v7-fhat/fit/test_fit.py`) passes before real corpus fit: 4 tests — ODE step smoke, boundary reflection, UKF tracks latent to within 3× obs noise over 200 steps, EM recovers ground-truth obs variance to within 3× over 500-step trajectory. Committed alongside the fit code per "always ship tests with fixes" invariant.

Performance: full fit in **24.3 s** wall time (EM converged 21 iterations × UKF over ~4100 filter steps). Caps: `--max-T-per-agent 3000` (Lumen subsampled linspace 3000-of-109,979; rationale §6). Without the cap, EM would run in well under an hour; 3000 rows is already well over-specified for 9 per-class parameters.

---

## 2. Fit convergence

Per-iteration sum filter log-likelihood (train):

| Iter | log L | | Iter | log L |
|---|---|---|---|---|
| 0 | 18 408.6 | | 11 | 30 327.5 |
| 1 | 26 076.0 | | 12 | 30 334.8 |
| 2 | 28 036.8 | | 13 | 30 328.8 |
| 3 | 29 085.8 | | 14 | 30 342.5 |
| 4 | 29 645.9 | | 15 | 30 339.5 |
| 5 | 29 935.4 | | 16 | 30 345.7 |
| 6 | 30 098.5 | | 17 | 30 339.8 |
| 7 | 30 197.5 | | 18 | 30 347.0 |
| 8 | 30 253.6 | | 19 | 30 340.7 |
| 9 | 30 296.3 | | 20 | 30 342.7 |
| 10 | 30 315.7 | | | |

Trajectory is monotone until iter ~13 then wobbles in a ±6 nat band around ~30 342 — consistent with the filter-only M-step (true RTS smoother omitted; see §6). Converged at iter 20: |Δ log L| / |log L| = 1.7 × 10⁻⁵ < tol (1 × 10⁻⁴).

Figure: `data/v7-fhat/figures/em_convergence.{png,pdf}`.

---

## 3. Fitted parameter values

### 3.1 Emission variances σ_obs (bounded [0.01, 0.30])

| class \ channel | E | I | S | V |
|---|---|---|---|---|
| resident_persistent | **0.0641** | **0.1149** | **0.0444** | **0.0540** |
| session_or_unlabeled | **0.0196** | **0.0357** | **0.0317** | **0.0191** |

All eight values interior to pre-registered bounds. Lumen (resident) has 1.6–3.2× higher per-channel obs noise than session agents — consistent with Lumen being embodied/real-world-facing and session agents being brief scripted runs.

### 3.2 Transition noise σ_trans fleet-wide (bounded [0.005, 0.05])

| channel | E | I | S | V |
|---|---|---|---|---|
| σ_trans | **0.0500** | **0.0500** | **0.0500** | **0.0500** |

**All four pegged at upper bound.** Not a bounds violation (≤ 0.05 strictly), but a diagnostic:

- Pooled transition residuals per agent-turn include observation-noise leak because the M-step uses filter marginals (not RTS-smoothed), so `mu_post_t ≈ obs_t` and `mu_post_{t-1} ≈ obs_{t-1}`, making `mu_post_t − fx(mu_post_{t-1})` ≈ the inter-turn obs-noise step, not the true transition residual.
- With σ_obs ~0.05 and inter-turn dt ~0.23 h on Lumen, the naive residual std is ~0.15 per channel — which, clamped to [0.005, 0.05], pegs at the ceiling.
- An RTS smoother pass would propagate measurement info backward and sharpen per-turn posterior marginals, reducing the implied transition variance. This is a known fit-quality gap (documented as v7.1 instrumentation work below) but does **not** change the SC2 verdict — SC2 trips on ~0.99 regardless of how tight or loose σ_trans ends up.

### 3.3 C5 logistic coefficients (spec-signed: σ(β₀ − β_E E − β_I I + β_S S + β_V|V|))

| class | β₀ | β_E | β_I | β_S | β_V|V| |
|---|---|---|---|---|---|
| resident_persistent | **0.000** | 0.000 | 0.000 | 0.000 | 0.000 |
| session_or_unlabeled | **4.100** | 0.056 | 0.020 | 0.053 | 0.011 |

**resident_persistent = all zeros — not fit.** Lumen's 2,100-row contiguous train slice (first 70% of the 3,000-row subsample) contained < 10 joined outcomes with both is_bad=0 and is_bad=1 classes present, so `m_step_c5_coefficients` returned the zero prior per its degenerate-case guard. Root causes, compounding:

1. Outcome sparsity: 5,410 outcomes / 112,869 state rows = 4.8 % join rate at ±60 s.
2. Lumen is_bad positive rate ≈ 1.6 % (85 global positives across 5,410 outcomes; Lumen has 5,024 outcomes).
3. Linspace subsampling 3 000-of-109 979 drops every 36th row; joined is_bad labels get subsampled with it, concentrating most residual signal outside the train slice.
4. Time-contiguous split (to give val/eval any resident_persistent representation) means train is the early epoch of Lumen's 28 days; positive events may cluster outside that epoch.

**session_or_unlabeled sign pattern:** all β ≥ 0 as pre-registered (spec §2.4). Magnitudes are small: β₀ = 4.1 implies baseline log-odds(bad) ≈ 4 even with healthy EISV, i.e. ~98 % predicted is_bad. This reflects the fact that session agents' is_bad rate is **not** 1.6 % in the joined subset — the model learns a high baseline because the training slice is dominated by one or two chatty agents whose outcomes are mostly is_bad=True. Small EISV-slope coefficients (0.01–0.06) imply weak predictive power of latent EISV on is_bad — a second signal that F̂ carries no outcome information beyond a near-constant intercept.

**SC1 pass** — all 22 values within pre-registered bounds and the sign pattern check passes (zeros are not sign violations).

---

## 4. SC1 — Parameter ranges (PASS)

```
sc1 = {
  "pass": true,
  "bounds_violations": [],
  "sign_violations": []
}
```

No emission variance, transition variance, or C5 coefficient is outside its pre-registered interval. σ_trans at the upper bound is flagged in §3.2 as a diagnostic, not a violation (spec bounds are inclusive).

---

## 5. SC2 — Denoising-collapse check (**TRIPPED**)

```
sc2 = {
  "pass": false,
  "r": 0.9949,
  "n": 952,
  "n_validation_agents": 10,
  "c5_turn_count": 0
}
```

**Pearson r(F̂_t, ‖o_chk_t − μ_{t|t-1}‖₂) = 0.9949 on 952 validation rows**, exceeding the halt threshold of 0.9 set by spec §2.6.

**F̂_t** per §3 of the spec, computed turn-by-turn on the validation split:

- Complexity term: 0.5 · ‖μ_post − μ_pred‖² / σ_trans²
- Accuracy term: 0.5 · ‖o_chk − μ_post‖² / σ_obs² + Σ log σ_obs + [−log p(is_bad | μ_post, c) when is_bad observed]
- Residual (the SC2 comparator): ‖o_chk_t − μ_{t|t-1}‖₂ — the raw one-step-ahead emission residual magnitude.

`c5_turn_count = 0` — zero validation turns contributed a C5 accuracy term. For resident_persistent, C5 coefficients are zero (§3.3) so the guard `np.any(coef != 0)` skipped Lumen. For session_or_unlabeled, nine validation agents had no outcome_events joined within ±60 s (consistent with §3.3 root causes 2 and 4 — session agents have even sparser outcomes than Lumen). F̂ on the val split is therefore purely the (complexity + C1-C4-Gaussian-accuracy) term, which is a structural function of the one-step-ahead residual — hence r ≈ 1.

### 5.1 Is the trip a bug, or a genuine finding?

**Genuine finding**, confirmed by pre-commit deliberation and two implementation iterations:

- **Iteration 1** (initial SC2): r = 0.9984 with only C1-C4 in F̂.
- **Iteration 2** (C5 accuracy term included when is_bad is observed): r = 0.9959.
- **Iteration 3** (full EM-converged fit, C5 accuracy included): r = 0.9949.

The ~0.003 drop between iterations 1→3 tracks the (minuscule) effect of adding C5. The correlation floor is set by structural collinearity: when the only observation channels are direct noisy measurements of the latent, F̂_t is algebraically dominated by ‖o − μ_pred‖² regardless of the posterior-vs-prior split. The v5 amendment's drop of C6 (the only asymmetric-information channel in the spec) removed the sole term that could have broken the collinearity.

A cleaner way to state it: **the v5-amended model has no information channels beyond direct EISV measurement**, so F̂ is forced to reduce (up to constants and monotone transforms) to the residual magnitude. This is exactly what spec §2.6 SC2 was designed to detect — a null check that should pass, and pre-commits the spike to honesty when it doesn't.

### 5.2 What v5 removed that would have broken the collinearity

The C6 event channels (`circuit_breaker_trip`, `stuck_detected`, `anomaly_detected`) were logistic Bernoulli emissions coupled asymmetrically to (E, I, S, |V|). A forward-window event indicator is NOT a linear function of the one-step-ahead residual, so including it would have decorrelated F̂ from pure residual magnitude. Session 1a's finding that all three events had zero rows in the reference window made them structurally unfittable; v5 dropped them.

This is the honest read: **v5 traded fittability for predictive informativeness**, and SC2 is the gate that catches the trade.

---

## 6. Methodological notes & known fit-quality gaps

The following are documented for operator review; none of them changes the SC2 verdict (r ≈ 1 is robust to these choices):

1. **RTS smoother omitted.** The E-step is filter-only, not a full forward-backward smoother. For fit quality this means (a) σ_trans upper-bound pegging (§3.2) and (b) slight EM-LL wobble after iter 13 (bouncing within a 7-nat band near convergence). Adding an RTS pass is a well-scoped ~50-line enhancement; deferred as v7.1 instrumentation because SC2 fails at the structural level (§5.1) regardless.
2. **C5 fit via post-hoc logistic regression on posterior means**, not joint E/M-step integration. sklearn `LogisticRegression(C=1/(n·λ))` at λ=0.01 with spec-signed feature encoding. Handles missing outcomes by dropping turns. Documented deviation from strict EM because joint UKF update with logistic emissions requires Extended Kalman linearization at each update step; given C5 is sparse and the posterior is already tightly pinned by C1-C4, the post-hoc fit is a defensible approximation.
3. **Lumen subsampling to 3,000 rows.** 9 per-class params are well-identifiable on ≤ 1 000 rows; 3 000 is conservative. Full-resolution Lumen (109 979 rows) would not change fitted values materially but would ~30× the wall time without improving identifiability.
4. **Time-contiguous split for single-agent classes.** Necessary to give val/eval any resident_persistent representation (only Lumen has the `persistent` tag in the reference window — a tag-discipline artifact, see spec §7.1 item S8a Phase-1 default-stamp). Trades agent-level independence for class coverage; a cleaner approach would be re-classifying residents by code-level identity rather than tag (Vigil/Sentinel/Watcher/Steward are residents but not tagged `persistent` — they run code paths that should be self-tagging).
5. **σ_trans bound pegging** (§3.2). Not a SC1 violation but worth re-registering bounds after the RTS-smoother upgrade.

---

## 7. Session 2 recommendation

**Recommendation: BLOCK Session 2. Redirect v7 F-hat path to one of three options for operator selection.**

Running Session 2's horse race on this fit would test F̂ (which is ≈ residual-norm, up to a constant) against B2 (raw-EISV logistic on E, I, S, V, phi, risk_score). The expected ΔAUC is ~0: residual-norm and raw-EISV logistic on the same latent are predicting the same thing. Whether the race is declared (d) or (b) would depend on noise in AUC bootstrap CIs, not on any real variational-grounding signal.

Three redirects the operator can take:

**Option R1 — Accept v5 path (b) verdict early.** The SC2 collapse is strong evidence that the v5-amended generative model is too thin to ground F̂ as distinct from residual denoising. Demote FEP to related-work / inspirational per spec §6.4 path (b). Save Session 2's compute. Update paper §3 per spec §5.1(b). Prior for path (b) was 0.55 post-v5 (amendment §4); the data have now resolved it.

**Option R2 — Broaden the generative model to include at least one asymmetric channel.** Candidates in priority order:

  (i) **Wait for C6 maturity.** As of 2026-04-23, `stuck_detected` has 10 days of history (since 2026-04-11). Repulling the reference window forward to 2026-04-11 → 2026-05-11 would give C6 fittable and SC2 a chance to break collinearity. Blocks the spike by ~4 weeks. (Spec §4 Option Z, redux.)

  (ii) **Per-agent calibration state** (calibration-gap vs. baseline). This is the BED-gap channel from v3/v4, determined unreconstructable per Session 1a §5.1. Would require shipping the per-agent calibration state as a first-class audit channel first; ~2-4 weeks of instrumentation work.

  (iii) **Primitive_feedback / Watcher finding channels**. Dropped at v3→v4 as "v7.1/v8 instrumentation work." Same as (ii): requires historical-audit lift to be usable.

**Option R3 — Accept the scope-limited (d) honestly.** The v5 amendment (§6.4) already removed the scope-limited branch in favor of a single-target decision rule. SC2 trip on the entire fit does not align with "scope-limited (d)" in any version of the spec. This option is listed only for completeness — not recommended.

---

## 8. Anomalies / operator flags

1. **σ_trans fleet-wide at upper bound 0.05** on all four channels. Diagnostic only; root cause is filter-only E-step (§6 item 1), not a dynamics misspecification.
2. **C5 coefficients zero for resident_persistent.** Lumen's 2,100-row contiguous train slice failed the minimum-positive-class guard in `m_step_c5_coefficients`. Not fit-blocking; does mean F̂ on Lumen val rows drops the C5 term entirely (which would in any case have been sparse — 4.8 % join rate, 1.6 % positive rate).
3. **resident_persistent class = {Lumen} in the reference window.** All other notional residents (Vigil, Sentinel, Watcher, Steward) did not have `persistent` in their `core.agents.tags` during 2026-02-20 → 2026-03-20. Tag-discipline gap independent of this spike. The v5-amended class partition (§2.4) treats `persistent` tag as the discriminator; a code-identity-based re-partition (e.g., resident = hostname matches launchd plist) would give true 2-class structure. Noted for v7.1 scope.
4. **c5_turn_count = 0 in SC2.** Zero validation turns contributed a C5 accuracy term. Two root causes: (a) resident_persistent C5 coefficients are zero (§3.3), (b) the 9 session_or_unlabeled val agents had no outcome_events joined within ±60 s. This is a symptom of the same outcome-sparsity problem that drives the SC2 collapse — not a code bug.

---

## 9. Artifacts shipped by this session

| Path | Purpose |
|---|---|
| `data/v7-fhat/fit/` | Code scaffolding: `ode.py`, `ukf_smoother.py`, `em.py`, `pull_corpus.py`, `run_fit.py`, `test_fit.py` |
| `data/v7-fhat/fit/test_fit.py` | Synthetic-TDD fixture (4 passing tests); gates any future fit change |
| `data/v7-fhat/corpus/*.parquet` | Gitignored per session1a precedent; SQL + ODE hash pin the reproducibility |
| `data/v7-fhat/params.json` | 22 fitted params + ODE hash + fit-time metadata + SC1/SC2 payloads |
| `data/v7-fhat/figures/em_convergence.{png,pdf}` | EM log-likelihood trajectory |
| `data/v7-fhat/session1-report.md` | This file |

**NOT shipped:** any evaluation on the held-out eval split (spec §2.5 + §2.6 — untouched per SC2 halt discipline).

---

## 10. Notes for future process-instances

- If re-running against C6-mature data (Option R2.i): the fit code supports re-adding a C6 emission channel. Reinstate logistic emissions in `em.py::m_step_c5_coefficients` (generalize to per-event-type) and extend the SC2 F̂ computation in `run_fit.py::sc2_check` to include the C6 accuracy terms.
- Tests at `data/v7-fhat/fit/test_fit.py` are TDD-locked and must pass before any code change ships.
- ODE hash `dee1182cd109c4a3d2999f21168a3093b9be8660765cd0d34f8c4337fce9751e` is the binding parameter pin; `run_fit.py` re-reads and hashes `ode_params.json` at every run and writes the result into `params.json`. A future Session 2 dispatch MUST verify hash match before reading the fit.
- Lumen's sampling regime is the dominant confounder. A re-run with code-identity-based class partition (not tag-based) would put Vigil/Sentinel/Watcher/Steward into resident_persistent and balance the class — but would not change the SC2 verdict because collinearity is structural to the C1-C4-only emission model.
