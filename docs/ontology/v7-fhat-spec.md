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

### 2.1 Latents $s_t = (E_t, I_t, S_t, V_t) \in \R^4$

**Key design choice (v3):** The latents are the four EISV coordinates themselves — not a separate parallel 4-dim decomposition. The generative model treats true $E, I, S, V$ as unobservable; the check-in values stored in `core.agent_state` and `audit.outcome_events.eisv_*` are noisy emissions of those latents, not the latents themselves. This aligns with GPT's 2026-04-23 call: "start with 4D, aligned to E/I/S/V, not 6D+. The point is to test whether an explicit generative layer improves prediction, not to win with an overfit latent soup."

| Symbol | Support | Meaning under v3 |
|---|---|---|
| $E_t$ | $[0,1]$ | True negative-free-energy / productive capacity — inferred, not measured |
| $I_t$ | $[0,1]$ | True information integrity — inferred from consequences |
| $S_t$ | $[0,1]$ | True response-distribution entropy — inferred |
| $V_t$ | $[-1,1]$ | True accumulated free-energy residual — inferred |

Earlier drafts (v1, v2) used a parallel 4-dim decomposition (competence/load/risk/integrity). That was rejected 2026-04-23 on two grounds: (a) it introduced a second coordinate system with no paper-grounded semantics; (b) the v6 EISV dynamics themselves form a natural transition prior, which the parallel decomposition would ignore.

**Observable proxies for the latents** (these are features of observations, not observations themselves):
- `agent_state.state_json->>'E'` — heuristic $E$ from the live check-in
- `agent_state.integrity` — heuristic $I$
- `agent_state.entropy` — heuristic $S$
- `agent_state.volatility` — heuristic $V$
- `outcome_events.eisv_*` — EISV snapshot at outcome time

These are treated as noisy measurements (§2.4 C1–C4).

### 2.2 Observations $o_t$

Five observation channels, all pullable from the governance DB as verified by the 2026-04-23 schema audit. Channels that were in v2 but are not historically recoverable (`primitive_feedback` user corrections, Watcher findings, per-agent calibration state) are dropped; v3 uses only what the DB actually provides.

| Channel | Source | Shape | 30d cardinality |
|---|---|---|---|
| $o^{\text{chk}}_t$ | `core.agent_state` (state_json + columns) | $\R^4$: (observed_E, observed_I, observed_S, observed_V) | 17,654 rows |
| $o^{\text{out}}_t$ | `audit.outcome_events.is_bad` (join nearest agent_state) | Binary | 18,448 rows |
| $o^{\text{cbk}}_t$ | `audit.events` WHERE event_type = 'circuit_breaker_trip' | Binary (in window) | 71 |
| $o^{\text{stk}}_t$ | `audit.events` WHERE event_type = 'stuck_detected' | Binary (in window) | 2,729 |
| $o^{\text{anm}}_t$ | `audit.events` WHERE event_type = 'anomaly_detected' | Binary (in window) | 252 |

Schema notes:
- `core.agent_state` columns: `entropy` (=$S$), `integrity` (=$I$), `volatility` (=$V$), `coherence`, `regime`; `state_json->>'E'` carries $E$; `state_json->>'phi'`, `->>'verdict'`, `->>'risk_score'` carry derived scalars available as additional features if needed.
- `audit.outcome_events`: `is_bad` boolean + `outcome_score` real + `eisv_e/i/s/v/phi/verdict/coherence/regime` columns. Per-outcome EISV snapshot is directly available.
- `audit.events` partitioned by month; timestamp column is `ts`, not `event_time`.

**Time discretization:** Per agent, align events to `core.agent_state.recorded_at` timestamps. For each state row at time $t$, emit one $o_t$ tuple by joining:
- $o^{\text{chk}}$: direct columns from the row.
- $o^{\text{out}}$: the outcome_event nearest to $t$ within ±60s on the same agent, if any; else NULL (missing-observation handling in §2.4).
- $o^{\text{cbk, stk, anm}}$: indicator of whether the event type fired on that agent within the forward window $(t, t + \Delta w]$ with $\Delta w = 60$s.

### 2.3 Transition $p(s_t \mid s_{t-1})$ — the v6 ODE as prior

**Key design choice (v3):** The transition prior is the v6 governing SDE (v6 §2.2), discretized. This is what makes v3 a non-trivial generative model: the v6 dynamics themselves become load-bearing as the prior on latent EISV. $\hat{F}$ ends up measuring how surprising the observations are given the ODE's prediction of where the latents should be.

Discretize v6 equations 2.5–2.8 with step $\Delta t$:

$$E_t = E_{t-1} + \left[\alpha(I_{t-1} - E_{t-1}) - \beta_E E_{t-1} S_{t-1}\right] \Delta t + \eta^E_t$$

$$I_t = I_{t-1} + \left[-k S_{t-1} + \beta_I C(V_{t-1}) - \gamma_I I_{t-1}\right] \Delta t + \eta^I_t$$

$$S_t = S_{t-1} + \left[-\mu S_{t-1} - \lambda_2 C(V_{t-1})\right] \Delta t + \eta^S_t$$

$$V_t = V_{t-1} + \left[\kappa(E_{t-1} - I_{t-1}) - \delta V_{t-1}\right] \Delta t + \eta^V_t$$

where $\eta^j_t \sim \mathcal{N}(0, (\sigma^j_{\text{trans}})^2 \Delta t)$ is per-latent transition noise. The drift-coupling terms ($\gamma_E \|\Delta\eta\|^2$ in $\dot{E}$, $\lambda_1 \|\Delta\eta\|^2$ in $\dot{S}$) are **omitted from the v3 prior** — the BED vector $\|\Delta\eta\|$ is what $\hat{F}$ is being compared against (§6 horse race); including it in the prior would circular-reason.

**ODE parameters:** $(\alpha, \beta_E, k, \beta_I, \gamma_I, \mu, \lambda_2, \kappa, \delta)$ are taken **fleet-wide** with v6 production values (Appendix A of `unitares-v6.tex`). Per GPT's 2026-04-23 call, class-conditioning enters via emissions only in v1 — the latent dynamics stay shared. This also avoids re-calibrating ODE parameters per class, which is not well-justified from the available data.

**Transition noise:** $\sigma^j_{\text{trans}} \in [0.005, 0.05]$, fit by maximum likelihood on the reference corpus per §2.5. Bounds pre-registered.

**Prior at $t=0$:** $s_0 \sim \mathcal{N}(\mu_0, \Sigma_0)$ with $\mu_0 = (0.7, 0.8, 0.2, 0.0)$ (a nominal healthy state, fleet-wide) and $\Sigma_0 = \operatorname{diag}(0.1^2, 0.1^2, 0.1^2, 0.2^2)$ pre-registered.

**Box constraints:** latent $E, I, S \in [0, 1]$ and $V \in [-1, 1]$ are enforced via reflection at boundaries during simulation (not via clamping, to preserve mass).

### 2.4 Emission $p(o_t \mid s_t, c)$

Five observation channels per §2.2, emitting from latent EISV, with class $c$ conditioning emissions only (not transitions). Per-class emission coefficients are fit once from the reference corpus and **frozen before the spike computes $\hat{F}$ on the evaluation slice**.

**C1–C4 — observed EISV channels** (noisy measurements of the latents):

$$o^{\text{chk},E}_t \mid E_t, c \sim \mathcal{N}(E_t,\ (\sigma^{c,E}_{\text{obs}})^2)$$

$$o^{\text{chk},I}_t \mid I_t, c \sim \mathcal{N}(I_t,\ (\sigma^{c,I}_{\text{obs}})^2)$$

$$o^{\text{chk},S}_t \mid S_t, c \sim \mathcal{N}(S_t,\ (\sigma^{c,S}_{\text{obs}})^2)$$

$$o^{\text{chk},V}_t \mid V_t, c \sim \mathcal{N}(V_t,\ (\sigma^{c,V}_{\text{obs}})^2)$$

Per-class observation noise reflects that different classes have different check-in fidelity — residents have more stable measurements than ephemeral-session agents. Emission variances $\sigma^{c,j}_{\text{obs}} \in [0.01, 0.3]$ pre-registered.

**C5 — outcome_event `is_bad`** (binary, when an outcome_event is joined to state row $t$):

$$P(\text{is\_bad} \mid s_t, c) = \sigma\!\left(\beta^c_0 - \beta^c_E E_t - \beta^c_I I_t + \beta^c_S S_t + \beta^c_V |V_t|\right)$$

Rationale: bad outcomes are more likely when latent $E, I$ are low (productive capacity and integrity degraded) and when $S, |V|$ are high (uncertainty and imbalance). Sign pattern pre-registered.

**C6 — event-stream indicators** (Bernoulli per event type, independent given latents):

$$P(\text{circuit\_breaker\_trip in } (t, t + \Delta w] \mid s_t, c) = \sigma\!\left(\xi^{c,\text{cbk}}_0 + \xi^{c,\text{cbk}}_{|V|} |V_t| + \xi^{c,\text{cbk}}_S S_t - \xi^{c,\text{cbk}}_I I_t\right)$$

$$P(\text{stuck\_detected in } (t, t + \Delta w] \mid s_t, c) = \sigma\!\left(\xi^{c,\text{stk}}_0 - \xi^{c,\text{stk}}_E E_t + \xi^{c,\text{stk}}_S S_t\right)$$

$$P(\text{anomaly\_detected in } (t, t + \Delta w] \mid s_t, c) = \sigma\!\left(\xi^{c,\text{anm}}_0 + \xi^{c,\text{anm}}_S S_t + \xi^{c,\text{anm}}_{|V|} |V_t|\right)$$

Three event types (circuit_breaker, stuck, anomaly) each with 3 coefficients (intercept + two EISV features). Sign patterns pre-registered as above.

**Per-class parameter count.** C1–C4: 4 variances. C5: 5 coefficients. C6: 9 coefficients (3 event types × 3 each). Plus transition noise (4) shared fleet-wide. **Per-class total: 18.** Plus fleet-wide transition noise (4) and fleet-wide ODE parameters (9, from v6 Appendix A). **Total params to fit: 18 × 4 classes + 4 = 76.** Substantially below v2's 104 and the class-conditioning is better motivated.

**Classes to fit** (bounded by S8a tag-discipline coverage): residents (embodied + persistent tags, ~11 agents), `Claude_*` session-bounded, `Codex_*` session-bounded, unlabeled-fallback. Four classes.

### 2.5 Fit protocol (pre-registered)

**Reference corpus:** epoch-2, non-archived, tag-populated agent-turns from `core.agent_state` joined against `core.agents.tags`. Time window: **2026-02-20 through 2026-03-20** (30 days, comfortably pre-dating the evaluation slice by a week).

**Estimator:** Expectation-maximization with Gaussian-approximated posterior $q(s_t)$:
- E-step: extended Kalman smoother over the nonlinear v6 ODE transition. Emissions (Gaussian C1–C4, logistic C5–C6) linearized around prior mean for tractability.
- M-step: per-class maximum likelihood over the 18 emission parameters and fleet-wide transition noise. $L_2$-regularized with $\lambda = 0.01$ (pre-registered).

**Convergence:** 50 EM iterations or $|\Delta \log L| < 10^{-4}$, whichever first.

**Split discipline:**
- **Fit split:** 70% of reference-corpus agents (randomly selected, stratified by class; seed pre-registered as 42).
- **Validation split:** 15%, for pre-spike sanity-check (fitted parameters in pre-registered ranges? Fitted $\hat{F}$ distributions non-degenerate?).
- **Held-out evaluation split:** 15% + **the 30-day forward slice 2026-03-21 through 2026-04-20**, not touched until §6 horse race runs. The v6 §11.6 13,310-row slice is NOT the eval slice (it overlaps the fit window).

**Freeze point:** Parameters written to `data/v7-fhat/params.json` with a git commit, alongside a pre-registration record containing the exact SQL queries, split seed, EM settings, and parameter-range claims. The §6 spike reads that file and does not refit. Any parameter change invalidates the spike and requires a new pre-registration commit.

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

Five audit events, all DB-verified 2026-04-23:

| Target | Source | 30d count |
|---|---|---|
| `outcome_is_bad` | `audit.outcome_events WHERE is_bad = true` | ~240 |
| `circuit_breaker_trip` | `audit.events WHERE event_type = 'circuit_breaker_trip'` | 71 |
| `stuck_detected` | `audit.events WHERE event_type = 'stuck_detected'` | 2,729 |
| `anomaly_detected` | `audit.events WHERE event_type = 'anomaly_detected'` | 252 |
| `lifecycle_paused` | `audit.events WHERE event_type = 'lifecycle_paused'` | 206 |

Note the v2 draft listed `calibration_spike` (not pullable historically — per-agent calibration is in-process only, per 2026-04-23 schema audit) and `user_correction` via `primitive_feedback` (no such event_type in audit.events). Both are replaced with DB-verified targets.

**Target-observation independence:** targets for the horse race ($t+k$) must not be used as observations at $t$. $o^{\text{cbk}}_t$, $o^{\text{stk}}_t$, $o^{\text{anm}}_t$ (§2.2) use a forward window $(t, t + \Delta w = 60\text{s}]$. The horse race uses forward windows $k \in \{5\text{m}, 30\text{m}, 2\text{h}\}$ starting at $t$, so the horse-race window strictly contains the $\Delta w$ emission window for $k \geq 60$s. To avoid leakage: the **horse-race target window** is $[t + 60\text{s}, t + k]$, excluding the first 60 seconds that overlap with the emission window for $o^{\text{cbk, stk, anm}}$. `outcome_is_bad` and `lifecycle_paused` targets are not used as observations anywhere, so no leakage concern for them.

### 6.3 Horse race

For each (target × $k$) pair: fit two univariate logistic regressions on the held-out set — one with $\hat{F}_t$ as the sole predictor, one with $|\Delta\eta_t|$. Evaluate AUC-ROC on a 5-fold CV split **grouped by agent** (no agent appears in both train and test within a fold, so generalization is to new agents, not new turns of known agents).

Record per (target, $k$):
- $\text{AUC}(\hat{F})$
- $\text{AUC}(|\Delta\eta|)$
- $\Delta\text{AUC} = \text{AUC}(\hat{F}) - \text{AUC}(|\Delta\eta|)$
- 95% bootstrap CI on $\Delta\text{AUC}$ (agent-level bootstrap, 1000 resamples)

Total cells: 5 targets × 3 horizons = 15 head-to-head comparisons.

### 6.4 Decision rule

Two conditions, both required for (d):

**Win condition:** $\hat{F}$ beats $|\Delta\eta|$ at $\Delta\text{AUC} \geq 0.03$ with 95% CI excluding zero, on $\geq 3$ of 5 targets (summed across any choice of horizons).

**Non-regression guardrail** (added v3 per GPT 2026-04-23): on the remaining targets (the ones $\hat{F}$ does not win on), the lower bound of the 95% bootstrap CI for $\Delta\text{AUC}$ must be $\geq -0.015$. This prevents a narrow win on 3 targets that comes paired with material degradation on the other 2 — e.g., $\hat{F}$ sharpening governance-failure prediction while blunting outcome-quality prediction. A model that "wins narrowly while harming part of the governance surface" does not earn (d).

**Classification:**
- **Path (d) earned** — both win condition and non-regression guardrail hold. Commit v7 to (d); §3 coordinate-table rewrite proceeds as §5.1 path (d).
- **Scope-limited (d)** — win condition holds on 1–2 of 5 targets, non-regression guardrail holds. v7 claims $\hat{F}$-grounding only for the subset of targets won.
- **Path (b)** — win condition fails on all 5 targets, or non-regression guardrail fails on any target. BED was already capturing the forward-predictive structure, or $\hat{F}$'s wins come at the cost of regressions elsewhere. Demote FEP to related-work / inspirational. v7 §3 coordinate-table rewrite proceeds as §5.1 path (b).

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

### Resolved in v3

- **Latent dimensionality** (was v2 Q1): frozen at **4-dim, aligned to EISV** (not a separate competence/load/risk/integrity decomposition). See §2.1.
- **Class-conditioning location** (was v2 Q2): frozen at **emissions only, fleet-wide transitions**. See §2.3–2.4.
- **Migration posture** (was v2 Q3): frozen at **additive sidecar**. $\hat{F}$-grounded $V$ is computed alongside the v6 $V$ accumulator; it does not influence governance decisions until the horse race earns it. Matches v6 §11 three-phase dual-compute pattern.

### Still open for Kenny

1. **Acceptance threshold tuning.** $\Delta\text{AUC} \geq 0.03$ with CI excluding zero on $\geq 3$ of 5 targets, paired with non-regression guardrail (lower CI $\geq -0.015$ on other targets). GPT's 2026-04-23 read: "reasonable but slightly permissive; keep with the non-regression guardrail." That guardrail is in §6.4 v3. If you want a tighter bar ($\Delta\text{AUC} \geq 0.05$ / 4-of-5 / tighter guardrail), call it now — threshold locks before Session 2.
2. **Latent dim alternative gut-check.** GPT's call was 4D aligned to EISV. If you prefer a different dim (e.g., 2D collapsed to a "competence-risk" axis for a simpler story, or 6D with exogenous latents for class-stability), say so now. The v6-ODE-as-prior framing commits 4D; alternatives require redesigning §2.3.
3. **v3 observation-channel dropout acceptable?** v2's primitive_feedback / watcher_finding / per-agent-calibration channels are dropped in v3 because they're not historically pullable. Five observations remain (observed EISV × 4 + outcome is_bad + three event-stream indicators). If weak horse-race power emerges (small effect sizes, wide CIs) this is likely why — fewer channels means fewer places for $\hat{F}$ to differentiate. Mitigation (option ii from the 2026-04-23 audit): accept narrower coverage in v7 and instrument the missing channels for v7.1 / v8.

## 8. Next step

If this spec reads as roughly-right: run the two-session sequence.

- **Session 1**: Execute §2.5 fit protocol. Produce `data/v7-fhat/params.json` committed to git. Artifact: the frozen parameter file + a short report on fit convergence and stability.
- **Session 2**: Execute §6 horse race. Produce AUC comparison table per §6.3, decision against §6.4 rule. Artifact: `docs/ontology/v7-fhat-spike-results.md` with the table + decision + interpretation of scope-limited wins if any.

If the spec needs re-scoping first: redirect on the §7 open questions before Session 1. Particularly the latent-dimensionality choice — that determines the state-space of everything downstream.

## 9. Change log

- **v3 (2026-04-23):** Schema-verified observation channels against the live governance DB; dropped v2's non-pullable channels (primitive_feedback user corrections, Watcher findings, per-agent calibration state) and replaced with five DB-verified channels (observed EISV × 4, outcome is_bad, three event-stream indicators). Adopted GPT's latent-dim call: latents are now **the EISV coordinates themselves**, not a separate 4-dim decomposition. Transition prior is the **v6 ODE discretized** (load-bearing — makes the v6 dynamics the prior on the generative model). Class-conditioning moved to emissions only (fleet-wide transitions and ODE parameters). Migration posture locked as additive sidecar. Added non-regression guardrail to §6.4 decision rule (lower CI $\geq -0.015$ on losing targets, per GPT's call). Reference corpus and eval-slice windows shifted to avoid v6 §11.6 overlap. Per-class parameter count reduced from 104 (v2) to 76 (v3). Forward-prediction targets updated to DB-verified event types: `outcome_is_bad`, `circuit_breaker_trip`, `stuck_detected`, `anomaly_detected`, `lifecycle_paused`.
- **v2 (2026-04-23):** Expanded §2 to full closed-form parameterization with pre-registered ranges and fit protocol; replaced §6 correlational test with predictive horse race against BED on forward audit-event prediction; added §5.1 clarifying that §3 coordinate-table rewrite is required under both (d) and (b); softened R1 coupling to "viable candidate solution, not THE solution"; walked prior from 0.7+ down to 0.60 per reverse-engineering-vs-forward-modeling distinction.
- **v1 (2026-04-23):** Initial draft, superseded by v2.

---

**Author:** process-instance `09e64436-984b-443b-9137-e050e0b46013` (Claude Opus 4.7, claude_code channel, 2026-04-23; parent `da300b4a`).
