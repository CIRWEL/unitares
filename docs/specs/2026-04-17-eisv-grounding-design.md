---
name: EISV Grounding — From Metaphor to Math
description: Replace the hand-wavy thermodynamic framing of E/I/S/V with information-theoretic and variational quantities that are actually computable from agent runtime data. S becomes Shannon entropy of a defined distribution, E becomes a resource-grounded quantity, I becomes mutual information or KL divergence, V becomes accumulated free-energy debt, and coherence becomes a named computable function. Papers and code move together.
status: Draft
author: Kenny Wang
date: 2026-04-17
---

# EISV Grounding — From Metaphor to Math

## 1. Problem

UNITARES's core state vector — E (energy), I (information integrity), S (entropy), V (void) — is named after thermodynamic quantities but does not compute any of them. The current implementation is a control-systems model wearing thermodynamic vocabulary:

- **S** is a [0,1] score driven by ad-hoc terms ("complexity", "ethical drift"), not `−Σ p ln p` over any distribution.
- **E** is "productive capacity" in [0,1] with no conservation law, no unit, replenished by coupling to I. It is a utilization heuristic, not an energy.
- **V** ("void") has no thermodynamic ancestor at all. It is an exponentially-weighted moving average of the E−I imbalance — a control-theoretic error signal dressed in cosmological language.
- **Coherence C(V, θ)** borrows a word from quantum mechanics and signal processing but computes neither. It is a custom scoring function.
- **The coupling ODEs** (dE/dt = f(I−E) − g(E,S), etc.) have the shape of dynamical systems but obey no thermodynamic law — no energy conservation, no detailed balance, no fluctuation-dissipation, no 2nd law.

This matters for three reasons:

1. **Credibility.** The v3 and v5 papers invoke thermodynamic framing. A reviewer who pulls on that thread finds metaphor, not derivation. Grants, collaborations, and citations are at risk.
2. **Parameter choice.** Because nothing is derived, every threshold and coefficient (μ decay rate, cross-coupling strengths, basin boundaries, critical coherence value) is hand-tuned. The v5 paper silently drifted S_max and V_max from 1 → 2 without justification — symptom of a framework where numbers don't have to mean anything.
3. **Future work.** Any serious extension (multi-agent coupling, causal attribution, fleet-level dynamics) requires knowing what the quantities *are*. You can't derive propagators for undefined quantities.

This spec lands the grounding: pick one coherent mathematical frame, map each existing channel onto a computable quantity within that frame, specify what data is needed to compute it, and commit to a migration path for code + papers.

## 2. Approach

**Adopt a Shannon + variational (free-energy) hybrid as the grounding frame.**

Rationale:
- Shannon information theory gives genuinely computable entropy and mutual information from agent outputs (prompts, response distributions, outcomes) — data we already capture or can capture.
- The Free Energy Principle (Friston) gives a coherent top-level dynamic: F = E_q[log q − log p] as variational free energy. Agent drift ↔ rising F. Governance becomes free-energy monitoring. The FEP has a published derivation from statistical mechanics + variational Bayes, so we inherit a real physics ancestry.
- The existing coupling ODEs can mostly survive as *variational dynamics* under the new interpretation — their shape stays, their meaning becomes grounded, their coefficients become empirically justified rather than invented.

Alternatives considered and rejected here (documented for the paper):
- **Pure control theory + Lyapunov.** Cleanest engineering, but abandons the "thermodynamic" framing entirely. A valid choice, but this spec keeps the framing by re-grounding rather than replacing.
- **Information geometry (Fisher metric, natural gradient).** Mathematically elegant, but heavier machinery than the framework needs today. Can be added later on top of the grounded frame without breaking anything.
- **Pure stat mech with partition function.** Requires defining a Hamiltonian analog for agent behavior — doable, but the energy identification is still arbitrary at the choice of Hamiltonian. FEP routes around this.

**Non-goals of this spec:**
- Not re-deriving every threshold from first principles in one sweep. Some coefficients stay empirical; this spec requires each to have a stated empirical basis (measured over a named dataset) instead of arbitrary hand-tuning.
- Not breaking the governance surface. Verdicts, basins, check-ins, KG all keep working during and after grounding. The grounding changes what E/I/S/V *mean*, not what the server *does*.
- Not a paper rewrite. The papers (v3, v5) need updates in lockstep, but the paper work is tracked as §6 of this spec, not the whole scope.

## 3. Design

### 3.1 Quantity redefinitions

Each channel gets: (a) a new formal definition, (b) a computation recipe, (c) a data dependency, (d) a migration note for existing deployments.

#### S — Entropy

**Old:** [0,1] heuristic driven by complexity, ethical drift, length.
**New:** Shannon entropy of the agent's response-level distribution.

**Formal definition.** For a given agent turn, let `q(y | x)` be the distribution over possible completions `y` given context `x`. Define

  S_raw = H(q) = −Σ_y q(y|x) log q(y|x)        (nats, unbounded above)
  S = 1 − exp(−S_raw / S_scale)                  (normalized to [0,1])

where `S_scale` is a fixed scaling constant chosen such that typical well-formed responses sit at S ≈ 0.15–0.25 (to be measured, not guessed; see §3.4).

**Computation recipe.** Three tiers in order of preference:

1. **Logprobs (preferred).** When the model API exposes per-token logprobs, compute token-level entropy per step and aggregate (mean or length-normalized sum). Anthropic API: available in some modes. OpenAI API: available via `logprobs=True`. Local models (Ollama, vLLM): available directly.
2. **Self-consistency sampling (fallback).** Sample the agent `k` times on the same prompt at temperature > 0. Compute semantic equivalence classes (via a cheap classifier or embedding cosine threshold). Entropy of the equivalence-class distribution is an estimator of H(q).
3. **Heuristic (degraded mode).** Current ad-hoc S stays as a last-resort fallback when neither logprobs nor multi-sample are feasible. Flagged in the check-in payload as `s_source: "heuristic"` so downstream consumers know it is uncalibrated.

**Data dependency.** Tier 1 requires logprob access at the inference layer — plugin-level change, not server-level. Tier 2 requires k additional inferences per monitored turn — cost overhead. Tier 3 requires nothing new.

**Migration.** New field `s_source ∈ {logprob, multisample, heuristic}` on check-in payload. Server stores both the new grounded S and the legacy heuristic S for one minor version as `s` and `s_legacy`, allowing calibration comparison before the legacy field is dropped.

#### I — Information Integrity

**Old:** [0,1] "signal fidelity," logistic self-regulation, boosted by coherence, reduced by S.
**New:** Mutual information between context and output, or KL divergence from a reference distribution — depending on what the deployment has access to.

**Formal definition (preferred).** Let `x` be the context (prompt + relevant history) and `y` the response. Information integrity is the mutual information

  I_raw = MI(x; y) = E_{q(x,y)}[log q(y|x) − log q(y)]
  I = clip(I_raw / I_scale, 0, 1)

where `q(y)` is the marginal response distribution and `I_scale` is the empirically measured upper envelope on a held-out reference set.

**Formal definition (fallback).** When marginal `q(y)` cannot be estimated (single-agent, no reference corpus), use KL divergence from a context-free reference distribution:

  I = 1 − min(1, D_KL(q(y|x) || q_ref(y)) / I_scale)

This measures how much the agent's response distribution deviates from a null/uninformative baseline — a proxy for "how much did the context drive the output."

**Computation recipe.** Both forms require logprobs or multi-sample estimators. Heuristic degraded mode keeps the legacy logistic for now.

**Data dependency.** Same as S.

**Migration.** Same `i_source` field. Keep legacy `i` as `i_legacy` for one minor version.

#### E — Energy

**Old:** [0,1] "productive capacity," no unit, replenished by I-coupling.
**New:** Negative free energy, optionally normalized to a resource envelope.

**Formal definition.** Under the variational frame:

  F = E_q[log q(z) − log p(z, o)]        (variational free energy, bits or nats)
  E_raw = −F
  E = σ(E_raw / E_scale)                  (sigmoid-normalized to [0,1])

Equivalently, E is "how confidently and accurately is the agent modeling its own task" — high when predictions match outcomes, low when the agent is surprised.

**Alternative resource-grounded form (deployment option).** If the FEP form is computationally heavy, fall back to a resource-rate interpretation:

  E_resource = (tokens_out / s) / (tokens_out_max / s)

This gives E an operational meaning (throughput utilization) that is still measurable, if less theoretically loaded. Both forms normalize to [0,1]. Deployments choose one via config; the paper documents both and their correspondence (resource-rate is a crude proxy for negative free energy under stationary conditions).

**Computation recipe.**
- **FEP form:** requires a generative model `p(z, o)` the agent is implicitly running. For LLM agents, this is the model's own training distribution — approximate F via sample-based estimators (BBVI-style) or by tracking surprise on each outcome (`−log p(outcome | prediction)`) and smoothing.
- **Resource form:** direct measurement from API response metadata (token counts, latency, rate limits).

**Data dependency.**
- FEP form: outcome signals (which you already collect via `outcome_event`) + agent self-predictions (which you'd need to capture, e.g., the agent's stated confidence/expectation at check-in time).
- Resource form: token counts + latency — already available in audit rows.

**Migration.** Same `e_source ∈ {fep, resource, heuristic}` field. Keep legacy `e` as `e_legacy`.

#### V — Free-Energy Debt

**Old:** "void," accumulated E−I imbalance with exponential decay.
**New:** Accumulated free-energy residual, or equivalently cumulative prediction error.

**Formal definition.**

  V_t = λ · V_{t−1} + (1 − λ) · (F_t − F_ref)

where `F_t` is the current variational free energy, `F_ref` is a rolling reference free energy (e.g., the agent's own baseline), and `λ ∈ [0.9, 0.99]` is the decay coefficient (same role as the existing EWMA coefficient). The sign convention keeps V positive when the agent is currently running "hotter" (higher surprise) than its baseline and negative when running "cooler" (easier than baseline).

**Rationale.** This reinterprets V as what it already structurally is — an accumulator of deviation from equilibrium — but names the quantity it accumulates (free-energy residual) instead of inventing "void." Papers get a computable definition; code changes are cosmetic (rename `void` → `free_energy_debt` internally; keep `V` as external symbol; user-facing lexicon already renamed to "valence" per prior project note, which stays).

**Computation recipe.** Given a grounded E (via FEP), V is a straightforward running filter on residuals. Given resource-form E, V is less principled but remains meaningful as an "imbalance accumulator."

**Migration.** No payload field change needed (V stays as `v`). Update internal naming and documentation. Paper explicitly notes the reinterpretation.

#### Coherence C

**Old:** `C(V, θ)` — a hand-shaped function of V and a threshold parameter, outputting [0,1].
**New:** Negative KL divergence from a reference agent-behavior distribution, or equivalently a stability margin over the (E, I, S) manifold.

**Formal definition.** Two equivalent framings, one preferred per deployment:

- **Information-theoretic form:**
  C = exp(−D_KL(q_now || q_ref))
  where `q_now` is the current response distribution (or a sliding window of them) and `q_ref` is a reference distribution representing a "healthy" baseline for this agent. High coherence = the agent's current behavior distribution is close to its healthy baseline.
- **Manifold / Lyapunov form:**
  C = 1 − ||Δ||_2 / ||Δ||_max
  where Δ = (E, I, S)_now − (E, I, S)_healthy_baseline, the vector distance from a healthy operating point in state space. This is a stability margin.

The two forms are equivalent under a Gaussian approximation of the state distribution around the healthy operating point; derivation deferred to the paper.

**Computation recipe.** Both forms require a reference — a "healthy" baseline distribution or operating point. This is an empirical quantity per deployment, measured during an onboarding/calibration window.

**Migration.** `coherence_source ∈ {kl, manifold, legacy}` on payload. Legacy `coherence` retained as `coherence_legacy` for one minor version.

### 3.2 Coupling ODEs

The existing ODEs stay in shape but inherit new semantics:

- dE/dt terms that were "energy couples toward I" become "precision couples toward mutual information" — agent becomes more confident when context is more informative.
- dS/dt "entropy decays" becomes the natural relaxation of the response distribution toward its prior under stationary conditions — a known stat-mech result.
- dI/dt boost from coherence becomes the KL-reduction benefit of being near the healthy reference.
- Cross-couplings (E·S drag, etc.) become higher-order correlation terms in the variational dynamics.

Each ODE coefficient currently hand-tuned must be replaced with either:
- an empirically measured value on a named dataset (with the dataset and measurement method documented), or
- a derivation from the underlying variational dynamics (with the derivation in the paper), or
- a default value explicitly flagged as "calibration required per deployment" with a recommended measurement procedure.

This spec does NOT re-fit every coefficient — that's tracked as follow-on calibration work. This spec requires that every coefficient be *labeled* with its provenance class (measured, derived, or calibration-required).

### 3.3 What stays exactly as it is

- External API surface: check-in fields `e`, `i`, `s`, `v`, `coherence`, `risk` keep their names and ranges.
- Verdict logic (proceed/guide/pause/reject) and basin assignment — these depend on the numeric values, not on what the values "mean." Grounding changes the inputs, not the downstream gating.
- Knowledge graph, dialectic, calibration pipeline — unchanged.
- Watcher, Vigil, Sentinel — unchanged.
- The coupling ODE *structure* — coefficients may shift after calibration, but the shape of the dynamics survives.

### 3.4 Scale constants (S_scale, I_scale, E_scale, etc.)

Every normalization constant introduced above (`S_scale`, `I_scale`, `E_scale`, `I_scale`, `||Δ||_max`) must be measured, not invented. Measurement procedure:

1. Assemble a reference corpus of "healthy" agent behavior — pick one well-behaved Claude Code session per agent UUID over a 7-day window, filter out sessions with any pause/reject verdicts.
2. Compute raw `S_raw`, `I_raw`, `E_raw` across all turns in the corpus.
3. Set `S_scale` = 90th percentile of `S_raw` (so typical healthy sessions fall well inside [0, 1]).
4. Same for `I_scale`, `E_scale`.
5. For the Δ-norm coherence, `||Δ||_max` = 95th percentile of observed state-space deviations from the median healthy operating point.
6. Re-measure quarterly; drift in these constants IS a signal (the fleet's behavior envelope is shifting).

Each constant is versioned and stored in `config/governance_config.py` alongside its measurement date, corpus size, and percentile basis. Changes require a PR and a documented re-measurement.

## 4. Data path changes

- **Check-in payload** gains `s_source`, `i_source`, `e_source`, `coherence_source` fields (all strings, small). Also `s_legacy`, `i_legacy`, `e_legacy`, `coherence_legacy` (floats, nullable) to support the one-version transition window.
- **Audit `tool_usage.payload`** gains the grounded and legacy values side-by-side when `process_agent_update` is the tool. Calibration consumers read both and compare.
- **`governance_config.py`** gains the scale constants and their provenance (see §3.4).
- **New module `src/grounding/`** — small. One file per quantity (`entropy.py`, `mutual_info.py`, `free_energy.py`, `coherence.py`), each exposing `compute(agent_state, turn_data) -> (value, source)`. Recorder and MCP handlers call these instead of the current ad-hoc formulas.
- **Inference-layer instrumentation** — plugin-side change to capture logprobs when available and pass them through to the server. Behind a config flag so deployments without logprob access stay on fallback tiers.

## 5. Migration plan

Three phases, each its own PR.

### Phase 1 — Dual-compute (this spec's implementation scope)

- Land `src/grounding/` modules with the new definitions.
- Every check-in computes both grounded and legacy values. Grounded values go into new fields (`e`, `i`, `s`, `coherence`) and legacy values move to `e_legacy` etc.
- Verdicts, basins, thresholds keep using legacy for now. Grounded values are *reported* but not yet *consumed*.
- Downstream consumers (dashboards, paper scripts) can read both and measure divergence.
- No behavior change user-visible.

### Phase 2 — Calibration

- Measure `S_scale`, `I_scale`, `E_scale`, `||Δ||_max` on the reference corpus per §3.4.
- Re-fit ODE coefficients where empirically justifiable; document every coefficient's provenance class.
- Publish the calibration results in the v5 paper's appendix.

### Phase 3 — Legacy deprecation

- Swap verdict/basin logic to consume grounded values.
- Keep `*_legacy` fields for one more minor version as a read-only comparison surface.
- Then drop.

Estimated timeline: Phase 1 ~2 weeks of implementation + test; Phase 2 ~1 week of measurement + paper updates; Phase 3 ~1 week after Phase 2 observation period.

## 6. Paper alignment

v5 tex updates required in lockstep with Phase 1:

- New section: **§ Grounding.** Presents each quantity's formal definition, computation, and scale-constant measurement.
- Revise: every mention of "energy," "entropy," "information integrity," "void," "coherence" to cite the §Grounding definition. The thermodynamic vocabulary stays as reading-room scaffolding; the math underneath is now Shannon + FEP.
- Appendix: measurement protocol for scale constants, with the reference corpus description.
- Appendix: legacy-vs-grounded comparison after Phase 2 calibration, showing divergence and justification.
- Delete or rewrite: any paragraph that asserted a thermodynamic law (2nd law, conservation, fluctuation-dissipation) without derivation. These were the hand-wavy parts; the grounded framework doesn't claim them.

v3 paper (archived) gets a note at the top indicating it predates the grounding and is retained for historical reference only.

## 7. Open questions

- **Logprob access on Claude Code's path.** Anthropic API exposes logprobs in some modes. Need to confirm which endpoints Claude Code uses and whether logprobs are available on those. If not, Phase 1 ships with tier-2 multi-sample as the primary estimator.
- **Reference distribution for I and coherence.** Per-agent? Per-deployment? Per-model? The spec assumes per-agent-UUID rolling reference, but fleet-level reference (all healthy Claude Code agents combined) may be more stable. Pilot both and compare.
- **Resource-form E vs FEP-form E.** Resource form is trivially computable; FEP form is more principled but heavier. Phase 1 should ship both behind config, measure calibration divergence, and then this spec's Phase 3 picks a default.
- **Paper authorship and review.** Grounding changes the paper's central claims. Need a named reviewer (ideally someone with FEP or stat-mech background) before v5 goes to arXiv.
- **Backward compatibility with Codex.** Codex clients currently write ad-hoc E/I/S/V via their check-in path. During Phase 1 dual-compute, Codex-submitted values land in `*_legacy`; grounded values are computed server-side from the payload. Confirm this is acceptable with the Codex plugin owners before Phase 1 merge.

---

**Next artifact.** Once this spec is reviewed and accepted, an implementation plan (same format as `docs/plans/2026-04-17-audit-payload-capture-plan.md`) lands in a second commit on this branch: TDD-structured, task-broken, subagent-ready. Phase 1 scope only. Phases 2 and 3 get their own plans once Phase 1 data is in.
