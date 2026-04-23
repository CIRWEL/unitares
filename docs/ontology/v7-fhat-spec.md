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

### 2.3 Transition $p(s_t \mid s_{t-1}, c)$

Slow-drift linear-Gaussian:

$$s_t = A^c s_{t-1} + w^c_t, \quad w^c_t \sim \mathcal{N}(0, \Sigma^c_w)$$

**Pre-registered form:** $A^c = \operatorname{diag}(a^c_c, a^c_\ell, a^c_r, a^c_i)$ — diagonal transition, no cross-latent coupling. Rationale: governance latents are named as orthogonal axes of belief; the generative model stays conservatively decoupled so any observed cross-coupling arises from shared observables, not modeled latent interaction.

**Pre-registered parameter ranges** (fit by maximum likelihood on the reference corpus; held constant for the spike):

- $a^c_j \in [0.90, 0.99]$ per class, per latent — near-identity, slow-drift.
- $\Sigma^c_w = \operatorname{diag}(\sigma^{c,2}_j)$ with $\sigma^c_j \in [0.01, 0.10]$ per class, per latent.

**Prior:** $s_0 \mid c \sim \mathcal{N}(\mu^c_0, \Sigma^c_0)$ with $\mu^c_0$ set to the class-conditional healthy operating point $\eta^*_c$ from v6 §5 (re-interpreted as latent-space means, not coordinate values). $\Sigma^c_0 = \operatorname{diag}(0.1^2, \ldots)$ pre-registered.

### 2.4 Emission $p(o_t \mid s_t, c)$

All six channels specified in closed form below. Per-class emission coefficients are fit once from the reference corpus (v7 §6.1 protocol below) and **frozen before the spike computes $\hat{F}$ on the evaluation slice**. No post-hoc tuning.

Write $s_t = (c_t, \ell_t, r_t, i_t)$ for (competence, load, risk, integrity) and $\sigma(\cdot)$ for the logistic function.

**C1 — test_outcome** (binary, pass/fail):
$$P(\text{pass} \mid s, c) = \sigma\left(\beta^c_0 + \beta^c_c \cdot c_t - \beta^c_r \cdot r_t\right)$$

**C2 — correction_event** (binary, human correction issued):
$$P(\text{correction} \mid s, c) = \sigma\left(\gamma^c_0 - \gamma^c_i \cdot i_t + \gamma^c_\ell \cdot \ell_t\right)$$

**C3 — calibration_error** ($e \in [0,1]$, $|\text{confidence} - \text{outcome}|$):
$$p(e \mid s, c) = \operatorname{Beta}\!\left(\alpha^c_0 \cdot i_t + \epsilon,\ \beta^c_0 \cdot (1 - i_t) + \epsilon\right)$$
with $\epsilon = 0.5$ for numerical stability. Beta rather than Gaussian because $e$ is naturally on $[0,1]$ and skewed for well-calibrated agents.

**C4 — watcher_finding** (count per turn):
$$p(n \mid s, c) = \operatorname{Poisson}\!\left(\lambda^c \cdot r_t \cdot \ell_t\right)$$

**C5 — verdict_pause** (binary, pause/reject verdict from `process_agent_update`):
$$P(\text{pause} \mid s, c) = \sigma\left(\delta^c_0 - \delta^c_c \cdot c_t + \delta^c_r \cdot r_t\right)$$

**C6 — complexity_surprise** (scalar, self-report minus class-median):
$$p(x \mid s, c) = \mathcal{N}\!\left(\mu^c_\ell \cdot \ell_t,\ (\sigma^c_\ell)^2\right)$$

**Per-class parameter count.** C1: 3 ($\beta^c_0, \beta^c_c, \beta^c_r$). C2: 3. C3: 2. C4: 1. C5: 3. C6: 2. Plus transition diag (4) + noise diag (4) + prior diag (4). Total **26 per class**.

**Classes to fit:** residents (embodied + persistent tags), `Claude_*` session-bounded, `Codex_*` session-bounded, unlabeled-fallback. Four classes × 26 params = **104 total**. Fittable from the class-tagged subset of the reference corpus (S8a tag-discipline caveat: coverage limited to actually-tagged agents; the paper acknowledges this).

### 2.5 Fit protocol (pre-registered)

**Reference corpus:** epoch-2, non-archived, tag-populated agent-turns from `core.agent_state` joined against `core.agents.tags`. Time window: 2026-02-01 through 2026-04-01 (approximately 60 days, pre-dating the evaluation slice by at least one week to avoid leakage).

**Estimator:** Expectation-maximization with mean-field Gaussian $q(s)$:
- E-step: closed-form Kalman-style posterior update per agent-turn (sigmoid/Beta/Poisson emissions linearized around prior mean for E-step tractability; full likelihoods used in M-step).
- M-step: per-class maximum likelihood over the 26 parameters, $L_2$-regularized with $\lambda = 0.01$.

**Convergence:** 50 EM iterations or $|\Delta\log L| < 10^{-4}$, whichever first.

**Split discipline:**
- **Fit split:** 70% of reference-corpus agents (randomly selected, stratified by class).
- **Validation split:** 15%, for pre-spike sanity-check of fitted parameters (are they in pre-registered ranges? Do fitted $\hat{F}$ values have non-degenerate distributions?).
- **Held-out evaluation split:** 15% + the 13,310-row §11.6 production slice, **not touched until §6 horse race runs**.

**Freeze point:** Parameters are written to `data/v7-fhat/params.json` with a git commit. The §6 spike reads that file and does not refit. Any parameter change invalidates the spike and requires a new pre-registration.

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

### 5.1 §3 coordinate-table rewrite is required under both paths, not just (d)

v6 §3.1 presents a coordinate table (at `unitares-v6.tex:634–647`) that lists *both* $E$ as "negative variational free energy $-F$" *and* $V$ as "accumulated free-energy residual." These cannot be simultaneously true under any coherent generative model: $E$ would be $V$'s time derivative, which the v6 ODEs do not say. The table is internally inconsistent regardless of what UNITARES ships.

**Under path (d):** $V$ becomes $\hat{F}$-debt under the §2 generative model; $E$ goes phenomenological. Coordinate-table rewrite: $E$ row gains a "productive-capacity (non-information-theoretic)" label; $V$ row gains a "$\hat{F}$-debt under minimal generative model, §2" label.

**Under path (b):** Both $E$ and $V$ go phenomenological. Coordinate-table rewrite: both rows lose their FEP labels; $V$ gains a "damped accumulator of $E{-}I$ gap, phenomenological" label; the v6 §3.2 V-paragraph's Friston derivation is deleted.

Either way, the v6 §3.1 table and the §3.2 $E$/$V$ paragraphs are load-bearing for paper v7 surgery. Estimating the (d) path as "rewrites §3.1" is correct; estimating the (b) path as "no paper work beyond related-work relabeling" is wrong — (b) requires the same table rewrite, with more grounding text deleted rather than reparented.

## 6. Validation protocol (the spike): predictive horse race

The first draft of this document used a correlational rule — "does $\hat{F}_t$ track $|\Delta\eta_t|$?" — with pooled Pearson $r$ as the decision statistic. That test is unfalsifiable: any parameterization flexible enough to fit a $|\Delta\eta|$-shaped target will succeed, regardless of whether $\hat{F}$ carries real causal structure or is a re-labeling under a convenient generative model.

The replacement is a **predictive horse race**. $\hat{F}$ and $|\Delta\eta|$ are two competing scalar signals; the test is which one better forecasts future governance-relevant events on held-out data. If $\hat{F}$ was already implicit in $|\Delta\eta|$, it cannot win. If $\hat{F}$ captures forward-predictive structure $|\Delta\eta|$ misses, it wins and path (d) earns its weight.

### 6.1 Setup

For each agent-turn $t$ in the held-out evaluation set (§2.5 split, 15% + the §11.6 13,310-row slice):

- Compute $\hat{F}_t$ via the §2 generative model with parameters frozen in `params.json`.
- Extract the existing $|\Delta\eta_t|$ from the audit pipeline's BED decomposition.
- Record whether each of five governance-relevant events occurs in the forward window $[t, t+k]$ for $k \in \{1, 5, 20\}$ turns on the same agent.

### 6.2 Forward-prediction targets

Five audit events, all already logged:

| Target | Source table |
|---|---|
| `outcome_failure` | `audit.events WHERE event_type IN ('outcome_event')` with outcome=failure |
| `calibration_spike` | `sequential_calibration` state: $|\text{conf} - \text{outcome}|$ crossing class-specific 90th percentile |
| `circuit_breaker_trip` | `audit.events WHERE event_type = 'circuit_breaker_trip'` |
| `user_correction` | `primitive_feedback(role='human', valence='negative')` |
| `trajectory_drift` | `audit.events WHERE event_type = 'trajectory_drift'` |

### 6.3 Horse race

For each (target × $k$) pair: fit two univariate logistic regressions on the held-out set — one with $\hat{F}_t$ as the sole predictor, one with $|\Delta\eta_t|$. Evaluate AUC-ROC on a 5-fold CV split **grouped by agent** (no agent appears in both train and test within a fold, so generalization is to new agents, not new turns of known agents).

Record per (target, $k$):
- $\text{AUC}(\hat{F})$
- $\text{AUC}(|\Delta\eta|)$
- $\Delta\text{AUC} = \text{AUC}(\hat{F}) - \text{AUC}(|\Delta\eta|)$
- 95% bootstrap CI on $\Delta\text{AUC}$ (agent-level bootstrap, 1000 resamples)

Total cells: 5 targets × 3 horizons = 15 head-to-head comparisons.

### 6.4 Decision rule

- **Path (d) earned** — $\hat{F}$ wins ($\Delta\text{AUC} \geq 0.03$, CI excludes zero) on $\geq 3$ of 5 targets, summed across any choice of horizons. Commit v7 to (d). §3 coordinate-table rewrite proceeds as §5.1 path (d).
- **Scope-limited (d)** — $\hat{F}$ wins on 1–2 of 5 targets. v7 claims $\hat{F}$-grounding only for the subset of targets won; other targets documented as cases where BED is doing the predictive work and $\hat{F}$ is not an improvement.
- **Path (b)** — $\hat{F}$ ties or loses on all 5 targets ($\Delta\text{AUC} < 0.03$ or CI includes zero). BED was already capturing the forward-predictive structure; $\hat{F}$ formalization adds no information. Demote FEP to related-work / inspirational. v7 §3 coordinate-table rewrite proceeds as §5.1 path (b).

### 6.5 Prior estimate

$P(\text{path (d) earned by rule 6.4}) \approx 0.60$, revised down from the first-draft 0.7+.

Reasoning for the downward revision: BED was engineered from historical patterns of "what preceded governance-failure" — it encodes years of reverse-engineered surprise structure. $\hat{F}$ is forward-modeled from a hypothesized 4-dim causal structure. They agree iff the hypothesized causal structure is approximately right, which is itself the open question the spike tests. Previous framing assumed BED would be recoverable from almost any reasonable $p(o, s)$; that is optimistic. The 4-dim latent decomposition (competence/load/risk/integrity) is one choice among several plausible ones; other decompositions would yield different $\hat{F}$. The probability that *this particular* decomposition recovers BED's forward-prediction quality on $\geq 3$ of 5 targets is ≈ 0.60, not ≈ 0.75.

Slight upward adjustment within 0.60: the observables in §2.2 are exactly the channels BED was designed against, so the generative model has the right *input surface* even if the latent structure is partially wrong. Full miss ($P < 0.3$) is unlikely; partial earn (scope-limited) is a real and likely outcome ($P \approx 0.30$); full earn ($\geq 3$ of 5) ≈ 0.40; full miss ($\text{path (b)}$) ≈ 0.30.

### 6.6 Spike cost estimate

~1 focused session for the horse race itself, given §2.5 parameters already fit. Dominant cost is the §2.5 fit (EM on ~60 days of reference corpus), which is a separate ~1-session job. Total: ~2 focused sessions end to end. Each session produces an artifact: the frozen `params.json` from §2.5, and the AUC comparison table from §6.3.

## 7. Risks and open questions

### What kills path (d)

1. **$\hat{F}$ ties or loses the horse race.** Per §6.4 decision rule. If $\hat{F}$ doesn't beat $|\Delta\eta|$ at forward-predicting audit events, BED is already doing the predictive work and FEP formalization adds no information.
2. **Class-specific coefficients don't stabilize.** If the per-class emission coefficients bounce across production windows, the generative model is under-specified relative to the observable channels — needs richer state dimension or richer observables. Expands v7 scope beyond what the paper can absorb.
3. **Tag-discipline blocker (S8a).** 96% of active agents lack class tags. Per-class fitting requires the class partition. Either (a) path (d) waits on S8a Phase-1 default-stamp rollout, or (b) the spike uses the known-class subset (residents + `Claude_*`-labelled) and the v7 paper is explicit about the class-coverage caveat.

### What (d) does *not* determine

R1 (behavioral-continuity verification, per `plan.md`) is independent. Path (d) makes variational identity verification over $q(s_t \mid \text{trajectory})$ a **viable candidate solution** for R1 — the same generative model that grounds $\hat{F}$ can, in principle, evaluate whether a declared-lineage agent's trajectory is consistent with its claimed parent's posterior. That is one candidate R1 solution among several (behavioral signature matching, substrate-earned three-condition check, etc.). **R1 stays open regardless of the spike outcome.** A (d) win in v7 should not precommit R1's shape.

### Open questions for Kenny

1. **Latent dimensionality.** 4 (competence/load/risk/integrity) is a guess. Alternatives: 2 (competence + risk, collapsing load into competence and integrity into risk); 5 (add environmental-stability for substrate-earned agents); 3 (competence/risk/integrity, treating load as observed not latent). Which decomposition best matches the paper v7 story you want to tell? **This decision must freeze before §2.5 fit runs.**
2. **Class-conditioning location.** Three places class can enter: (a) emission coefficients [§2.4 current proposal]; (b) priors $p(s_0 \mid c)$ differ per class [§2.3 current proposal also adopts this]; (c) transition dynamics $A^c, \Sigma^c_w$ per class [§2.3 current proposal also adopts this]. The current spec uses all three, which doubles-or-triples parameter count vs. a minimal spec. If 104 params is too many for the class-coverage available, the minimal fallback is (a) only with fleet-wide priors and dynamics.
3. **Migration posture.** Should $\hat{F}$-grounded $V$ *replace* the current $V$ accumulator, or ship dual-compute alongside it (per v6 §11 three-phase pattern)? Replacement is cleaner; dual-compute preserves the v6 pipeline-ordering methodological contribution on a second mechanism and is the v6-precedent-aligned answer.
4. **Acceptance threshold.** $\Delta\text{AUC} \geq 0.03$ with CI excluding zero, on $\geq 3$ of 5 targets, is the §6.4 rule. Worth your gut-check: is 0.03 the right magnitude, and is 3-of-5 the right bar? Both are judgment calls. A tighter rule ($\Delta\text{AUC} \geq 0.05$, 4-of-5) would make (d) harder to earn but more defensible under reviewer scrutiny.

## 8. Next step

If this spec reads as roughly-right: run the two-session sequence.

- **Session 1**: Execute §2.5 fit protocol. Produce `data/v7-fhat/params.json` committed to git. Artifact: the frozen parameter file + a short report on fit convergence and stability.
- **Session 2**: Execute §6 horse race. Produce AUC comparison table per §6.3, decision against §6.4 rule. Artifact: `docs/ontology/v7-fhat-spike-results.md` with the table + decision + interpretation of scope-limited wins if any.

If the spec needs re-scoping first: redirect on the §7 open questions before Session 1. Particularly the latent-dimensionality choice — that determines the state-space of everything downstream.

## 9. Change log

- **v2 (2026-04-23):** Expanded §2 to full closed-form parameterization with pre-registered ranges and fit protocol; replaced §6 correlational test with predictive horse race against BED on forward audit-event prediction; added §5.1 clarifying that §3 coordinate-table rewrite is required under both (d) and (b); softened R1 coupling to "viable candidate solution, not THE solution"; walked prior from 0.7+ down to 0.60 per reverse-engineering-vs-forward-modeling distinction.
- **v1 (2026-04-23):** Initial draft, superseded by v2.

---

**Author:** process-instance `09e64436-984b-443b-9137-e050e0b46013` (Claude Opus 4.7, claude_code channel, 2026-04-23; parent `da300b4a`).
