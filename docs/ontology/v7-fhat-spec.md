# v7 $\hat{F}$ Spike — Minimal Generative Model for Governance Latents

**Purpose:** Specify a minimum-viable generative model $p(o, s)$ that would make path (d) from the 2026-04-23 FEP-departure decision honest — variational free energy $\hat{F}$ derivable from UNITARES's existing observables, identified with the $V$ accumulator, class-conditional by construction.

**Decides:** Whether path (d) is feasible at v7-scope and what it would look like concretely.

**Does not decide:** Whether to commit v7 to (d) vs (b) demotion. That decision follows the validation spike described in §6 below.

**Companion to:** `paper-positioning.md` (v7 animating thesis), `plan.md` row R1 (behavioral-continuity verification unblocks variational identity work). Supersedes the (a) path framing in `paper-positioning.md` §"Where v6 could resist the ontology."

---

## 1. Why the v6 claim is honest-but-empty

v6 §3.2 defines $E = \sigma(-F / E_{\text{scale}})$ with $-F$ the variational free energy of the agent's internal generative model. The paragraph admits the computation is deferred — production uses a resource-rate heuristic $E_{\text{resource}} = (\text{tokens}/s) / (\text{tokens}/s)_{\max}$ tagged `e_source = "resource"`, "not equivalent to $-F$ and does not approximate it under stationarity in any formal sense."

Two gaps:

1. **Token logprobs are not $F$.** Exposing per-token logprobs gives $-\log p(y_t \mid y_{<t}, x)$ under the language model's own token distribution. That is prediction error over *token sequences*, not variational free energy over *governance latents*. Shipping logprobs improves $S$ (response-distribution entropy) and possibly $I$ (paired-logprob MI). It does not buy $-F$.

2. **$F$ requires a generative model of governance-relevant latents.** $F = E_q[\log q(s) - \log p(o, s)]$ needs a declared $p(o, s)$ over latents $s$ and observations $o$. UNITARES does not ship one. Without it, no computation of $F$ exists; "tier-1 estimator" is undefined.

The good news: the *observations* are already there. What is missing is the model.

## 2. Minimal generative model

### 2.1 Latents $s_t \in \R^4$

Four governance-relevant hidden states the agent does not directly observe about itself:

| Symbol | Name | Intuition |
|---|---|---|
| $c_t \in [0,1]$ | Competence | Posterior belief about task-completion ability within class envelope |
| $\ell_t \in [0,1]$ | Load | Posterior belief about cognitive/computational burden |
| $r_t \in [0,1]$ | Risk | Posterior belief about basin-boundary proximity |
| $i_t \in [0,1]$ | Integrity | Posterior belief about calibration honesty (stated confidence ↔ outcomes) |

These are latent by construction — no single UNITARES observation reveals them; they are inferred from the joint pattern of observations.

### 2.2 Observations $o_t \in \R^6$

Directly observed outcomes from the existing audit + calibration + watcher pipeline:

| Channel | Source | Shape |
|---|---|---|
| `test_outcome` | `auto_ground_truth.py` outcome events | Binary (pass/fail) + confidence |
| `correction_event` | `primitive_feedback(role="human")` | Binary (correction issued) |
| `calibration_error` | `sequential_calibration.py` per-agent state | Scalar \|confidence − outcome\| |
| `watcher_finding` | Watcher post-edit scan | Count / severity |
| `verdict_pause` | `process_agent_update` response | Binary (pause/reject verdict) |
| `complexity_surprise` | `complexity` field vs class median | Scalar (self-report − observed) |

All six are already logged per-agent-turn. Map-from-existing is a one-afternoon SQL job, not a new instrumentation project.

### 2.3 Transition $p(s_t \mid s_{t-1})$

Slow-drift linear-Gaussian:

$$s_t = A s_{t-1} + w_t, \quad w_t \sim \mathcal{N}(0, \Sigma_w)$$

with $A$ near-identity (governance latents evolve slowly compared to observation rate) and $\Sigma_w$ small and diagonal. Per-class parameters.

### 2.4 Emission $p(o_t \mid s_t, c)$

Per-observation-channel emission, conditioned on agent class $c$ (the heterogeneity axis from v6 §4):

$$P(\text{test passed} \mid s, c) = \sigma(\alpha^c_{c} \cdot c_t - \alpha^c_{r} \cdot r_t)$$

$$P(\text{correction} \mid s, c) = \sigma(-\alpha^i_{i} \cdot i_t + \alpha^i_{\ell} \cdot \ell_t)$$

$$p(\text{calibration\_error} \mid s, c) = \mathcal{N}(\mu_c(1 - i_t), \sigma^2_c)$$

... and analogous forms for the remaining channels. The emission coefficients $\{\alpha^\cdot_\cdot\}$ are **class-conditional**: a sensor-agent's emission distribution is different from a coding-assistant's. This is the hook for class-conditional $\hat{F}$ (§4).

Per-class parameter count: ~30 coefficients. Fit from a reference corpus of healthy class-tagged agent-turns, same protocol as v6 §5 class-calibration.

## 3. Variational free energy

Under the above model, the variational free energy of the posterior $q(s_t)$ against the generative model at turn $t$ is:

$$F_t = \underbrace{D_{\text{KL}}[q(s_t) \| p(s_t \mid s_{t-1})]}_{\text{complexity}} - \underbrace{\mathbb{E}_{q(s_t)}[\log p(o_t \mid s_t, c)]}_{\text{accuracy}}$$

Standard decomposition. Complexity: how far the posterior has moved from the transition prior. Accuracy (negated): expected log-likelihood of observed outcomes under the posterior.

**Inference:** Mean-field Gaussian posterior $q(s_t) = \prod_j \mathcal{N}(\mu_{t,j}, \sigma^2_{t,j})$. Per-observation update is a Kalman-filter-style closed-form step (linearizing sigmoid emissions around the prior mean for tractability). Compute cost: $O(\dim(s) \cdot \dim(o)) = O(24)$ per turn. Cheap.

**Per-turn $\hat{F}$:** scalar; bounded below by the log-evidence $-\log p(o_t \mid c)$.

**Accumulated $\hat{F}$:**

$$V_t \equiv \lambda V_{t-1} + (1 - \lambda) \hat{F}_t$$

This is exactly the v6 §3.2 equation (V-grounded) with $F_t - F_{\text{ref}}$ replaced by $\hat{F}_t$ (the reference is now absorbed into the posterior's prior).

**Identification:** $V$ under v7 = exponentially-weighted accumulated $\hat{F}$ under the minimal generative model. No new scalar; the existing accumulator gets a principled definition.

## 4. Class-conditional $\hat{F}$ for free

Because emissions $p(o_t \mid s_t, c)$ are class-conditional, $\hat{F}$ is automatically class-conditional. Two agents producing the same observation sequence but belonging to different classes receive different $\hat{F}$ values because their expected emission distributions differ.

This is the v6 §5 class-calibration mechanism, re-derived from the variational model. Scale constants $\{S_{\text{scale}}, I_{\text{scale}}, E_{\text{scale}}, \|\Delta\|_{\max}\}$ become summary statistics of the class-conditional emission and prior distributions, not independent tuning parameters. The "class-conditional calibration" contribution of v6 gains a generative-model derivation; it was empirically right but theoretically ungrounded under the pure v6 framing.

## 5. What this does not fix: the $E$ coordinate

$\hat{F}$ formalizes $V$. It does **not** formalize $E$.

Under active inference, the natural candidates for an $E$-like scalar are:

- **Precision of posterior** (inverse posterior variance, $-\log \det \Sigma_q$) — but this overlaps with $S$ (response-distribution entropy), and the paper already uses $S$ for that semantic.
- **Expected free energy of policy** ($G = E_{q(o, s \mid \pi)}[F]$ under a planning policy $\pi$) — but this requires an explicit policy model UNITARES does not ship.
- **Evidence lower bound (ELBO)** on the generative model — which is $-F$, already claimed by $V$.

Honest conclusion: **$E$ has no FEP grounding under path (d).** $E$ must be reframed phenomenologically — "productive capacity," grounded in tempo/throughput proxies per class, honestly tagged as a non-information-theoretic coordinate. The current resource-rate heuristic continues; the paper stops claiming $E = -F$ in any sense.

v7 §3 (Information-Theoretic Grounding) contracts: $S, I, V$ have FEP / Shannon grounding; $E$ does not. This is more honest than v6 and carries a real cost — the paper loses the "all four coordinates are information-theoretic quantities" clean-table claim. The gain is that the claims it does make are ones the code can back up.

## 6. Validation protocol (the spike)

The spec above is a design hypothesis. Before committing v7 to path (d), run this spike:

1. **Implement the model** — 4-dim mean-field VI with the emissions from §2.4. Fit per-class coefficients from a clean-slice reference corpus (epoch-2, non-resident, non-archived; same cohort as `project_schmidt-preliminary-data-three-pass.md` used).
2. **Compute $\hat{F}_t$** on the 13,310-row §11.6 production slice.
3. **Extract the existing BED vector $\|\Delta\eta\|$** for the same slice.
4. **Correlate.** Per-agent Pearson $r(\hat{F}, \|\Delta\eta\|)$; pooled correlation; inspect divergence cases.

**Decision rule:**

- Pooled $r \geq 0.7$: path (d) is earned. BED was implicitly variational all along; $\hat{F}$ formalizes it. Commit v7 to (d).
- $0.4 \leq r < 0.7$: partial grounding. $\hat{F}$ correlates with a subset of BED components. Scope-limit v7 claim to that subset.
- $r < 0.4$: BED is genuinely ad-hoc, FEP has no empirical purchase on UNITARES's existing signals. Fall back to path (b) — demote FEP to related-work / inspirational, reframe $V$ and $E$ phenomenologically.

**Spike cost estimate:** ~1 focused session. Model is small, inference is closed-form, observables are already in Postgres, BED vector is already computed in the audit pipeline. The dominant cost is fitting per-class emission coefficients from the reference corpus, which parallels the v6 Phase-2 calibration work.

## 7. Risks and open questions

### What kills path (d)

1. **Low correlation with BED.** See §6 decision rule. If BED and $\hat{F}$ are independent, we have two different surprise signals and the formalization doesn't earn its weight.
2. **Class-specific coefficients don't stabilize.** If the emission parameters $\alpha^\cdot_\cdot$ bounce across production windows, the generative model is under-specified relative to the observable channels — needs richer state dimension or richer observables. Expands v7 scope beyond what the paper can absorb.
3. **Tag-discipline blocker (S8a).** 96% of active agents lack class tags. Per-class fitting requires the class partition. Either (a) path (d) waits on S8a Phase-1 default-stamp rollout, or (b) the spike uses the known-class subset (residents + `Claude_*`-labelled) and the v7 paper is explicit about the class-coverage caveat.

### Open questions for Kenny

1. **Latent dimensionality.** 4 (competence/load/risk/integrity) is a guess. Alternatives: 2 (competence + risk, collapsing load into competence and integrity into risk); 5 (add environmental-stability for substrate-earned agents); 3 (competence/risk/integrity, treating load as observed not latent). Which decomposition best matches the paper v7 story you want to tell?
2. **Class-conditioning location.** Three places class can enter: (a) emission coefficients $\alpha^\cdot_\cdot(c)$ [§2.4 current proposal]; (b) priors $p(s_0 \mid c)$ differ per class; (c) both. Option (c) is most expressive but doubles the parameter count.
3. **Migration posture.** Should $\hat{F}$-grounded $V$ *replace* the current $V$ accumulator, or ship dual-compute alongside it (per v6 §11 three-phase pattern)? Replacement is cleaner; dual-compute preserves the v6 pipeline-ordering methodological contribution on a second mechanism.
4. **Acceptance threshold.** $r = 0.7$ is a guess for "path (d) earned." Too low = we formalize a coincidence. Too high = the spike fails for curve-fitting reasons that don't disqualify the approach. Worth your gut-check before the spike runs.

## 8. Next step

If this spec reads as roughly-right: run the §6 validation spike as a one-session dispatch. Artifact: spike report (pooled and per-agent correlations, divergence-case gallery, decision against the §6 rule) shipped to `docs/ontology/v7-fhat-spike-results.md`.

If the spec needs re-scoping first: redirect on the §7 open questions before the spike runs.

---

**Author:** process-instance `09e64436-984b-443b-9137-e050e0b46013` (Claude Opus 4.7, claude_code channel, 2026-04-23; parent `da300b4a`).
