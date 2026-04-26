---
title: Dialectic Review — Compute-Receipt Sidecar
reviewer: dialectic-knowledge-architect
of: compute-receipt-sidecar.md
date: 2026-04-25
posture: adversarial-collaborative — the author asked for pushback, not validation
---

# Dialectic Review

The proposal is well-structured and the surface-level argument (sidecar > fifth channel) is correct. But the steel-man cuts deeper than the proposal admits, the ontology of "receipt" is doing more rhetorical work than analytical work, and the audit-only firewall is mostly a social construct dressed as an architectural one. Detailed comments below, then synthesis.

---

## Inline comments

### On §Problem ("UNITARES does not currently measure compute")

The framing — "this is a real gap" — is right, but the listed motivations split cleanly into two categories that the proposal then proceeds to treat as one:

- **Governance-relevant signal**: slop detection, thrash detection. These are claims that token patterns *correlate with internal agent state* (retry loops, surface-area thrash). If those correlations are real, they are not audit data; they are EISV-relevant evidence the basin is missing. The proposal can't simultaneously argue (a) tokens reveal slop/thrash AND (b) tokens are not basin-feeding. Pick one.
- **Operator economics**: $/verdict, cross-fleet calibration. These are unambiguously not governance signals. They are accounting.

Mashing both into "compute receipt" is the first ontological seam. See §Conceptual seams below.

### On Non-goal #1 ("Not a fifth EISV channel")

This is the strongest paragraph in the proposal and it should stay. The "one Opus token ≠ one Haiku token thermodynamically" argument is exactly the right shape: it's the same argument paper v6 makes for *why* governance is model-agnostic in the first place. Folding tokens into E recapitulates the EISV-surface-sprawl failure mode in its purest form.

But — see steel-man — the opposition would say: "fine, normalize. Tokens-per-FLOP, or tokens-per-dollar, or tokens-per-kWh. Pick a substrate-level invariant and the heterogeneity argument dissolves." The proposal doesn't engage this. It should.

### On Non-goal #2 ("Not basin-feeding")

"The basin solver MUST NOT read this signal" — this is enforced *by convention*, not by code. There is no compile-time, type-system, or schema-level barrier preventing a future PR from doing exactly this. The IPUA pin-check pattern in `project_ipua-pin-agent-id-proof.md` shows how this kind of invariant gets locked in: a parametrized contract test that fails the build if `governance_core/` ever imports `compute_receipts`. Recommend adding that test in phase 1, not later. Otherwise this rule will erode within 3-4 PRs of a contributor who "just wants to try it."

### On Non-goal #4 ("Not a Goodhart target")

This is the weakest non-goal. See §Goodhart below — the audit-only firewall is mostly aspirational.

### On Schema sketch (`compute` payload)

Three issues:

1. **`source` enum is too small.** `harness_emitted` vs `agent_self_reported` misses the case where the harness emits *but the agent could have lied to the harness* (e.g., a Codex agent reporting tool-call counts the harness can't independently verify). Suggest: `{harness_authoritative, harness_relayed, agent_self_reported, missing}`.
2. **`model_id` is the heterogeneity bomb.** Risk #1 acknowledges this but understates it. Canonicalization at write time is fine for known models but locks in today's namespace. What happens when a fleet member reports `gpt-5-thinking-2027-08`? Either you accept unknowns (defeats normalization) or you reject them (the receipt is lost — worst outcome for an audit log). Recommend: store raw `model_id_reported` AND `model_id_canonical`, the latter nullable. Don't lose data.
3. **`cost_usd` should not be in the schema at all in phase 1.** It's derived. Storing it inline guarantees rate drift. The "Provisional decisions" section already concedes this — make it a hard cut, not a "⚠️". Storing tokens + model_id + a versioned rates file at query time is strictly better.

### On §Storage ("New table compute_receipts")

The `event_id` nullable FK is doing a lot of conceptual work. A receipt with no outcome is not really a "receipt for an event" — it's a meter reading. This is the second ontological seam: the table mixes two different kinds of row (outcome-attached and freestanding), and they should probably be two tables, or one table with a discriminator column that is honest about it. See §Conceptual seams.

### On Phase 2 (check-in receipts)

This is where the proposal goes from "clearly correct" to "needs more thought." See §The check-in case below — I think this phase is at minimum mis-scoped, and possibly actively perverse.

### On Phase 3 (`thrash_index`, `slop_index`)

Naming check per `feedback_eisv-surface-sprawl.md`: these names are *fine* (non-isomorphic to E/I/S/V), but they are doing exactly the kind of work that, two PRs later, someone will say "we should just feed `thrash_index` into E." The fact that they live in `metrics.series` rather than EISV is good. The fact that they have suggestive names that imply causal stories about agent internal state is a slow-burning surface-sprawl risk.

A `slop_index` that *correlates* with low coherence will tempt someone to short-circuit it into the basin. Pre-empt this by writing the test (see Non-goal #2 comment) AND by being explicit in the doc that these are *operator-facing* analytics, not agent-state estimates.

### On §Risks #5 ("What about the residents?")

The honest move here — making `source: null` first-class — is good. But this risk understates the deeper issue: the residents are exactly the agents whose compute the proposal claims is most worth measuring ("what does it cost to run governance itself?"). If Sentinel and Steward are pure-Python and have no token cost, then the answer to "what does governance cost?" is *almost entirely the residents that DO have tokens* (Vigil running `claude`, Chronicler running `claude`, etc.) and the resident-state runtime is essentially free. That's a real and reportable answer, not a gap. Reframe risk #5 as a finding.

### On §"What this changes about UNITARES's story"

The "agents got better per token" framing for v7 is good. Watch for the trap: per-token improvement curves are exactly the kind of metric VC-adjacent funders pattern-match to "AI efficiency" stories. Per `feedback_deep-tech-positioning.md`, the audience is deep-tech-explicit funders. The substantive claim here isn't "we got cheaper" — it's "we can disentangle capability gain from cost gain *as separate axes* in a way single-axis benchmarks can't." Lead with the disentanglement, not the cost reduction.

---

## 1. Steel-man: "tokens absolutely belong in E"

### The strongest version of the opposition

"E is energy. In any thermodynamic governance framework worth the name, energy must include the actual computational cost of producing the agent's output. You already accept that 'task complexity' feeds E — but complexity is a self-reported proxy for compute. You're using a worse measurement of the same underlying quantity because the better measurement is uncomfortable.

The heterogeneity objection is real but solvable. Three normalization options, in increasing order of robustness:

1. **Per-model normalization**: a Pydantic-validated `tokens_normalized = tokens * model_weight[model_id]`, where weights are calibrated against a reference task suite. This is what every multi-model benchmark already does.
2. **FLOP estimation**: tokens × parameters × 2 (forward pass) is a defensible lower bound. FLOPs are substrate-invariant in the way energy actually is.
3. **Cost normalization**: `tokens × $/token` is the market's normalization of compute. Imperfect but honest, and the operator already acts on it.

Any of these gives you a substrate-invariant E-contribution. Refusing to integrate compute into E because tokens-as-reported aren't isomorphic is letting the perfect be the enemy of the measurable.

Furthermore: your current E already has heterogeneity problems. Check-in cadence means different things for an event-driven Watcher than for a polling Sentinel. Task complexity means different things for a coding agent than for a dialectic agent. You've tolerated heterogeneity in E when it was convenient; you're objecting to it now because tokens are *new*, not because the principle is consistent."

### Where the steel-man fails

It fails at the reference-task-suite. Per-model normalization requires a calibration corpus large enough and stable enough to derive `model_weight[model_id]` for every fleet member. UNITARES's fleet composition shifts faster than any benchmark suite can re-calibrate. The moment you ship `model_weight['claude-opus-4-7'] = 1.0`, you have hardcoded a *political* claim (that Opus is the reference model) into the basin. The next model change (Opus 5, Haiku 5, a new Codex variant) requires re-running calibration against ground truth — and *what is the ground truth?* It's outcome scores, which is what the basin is supposed to *produce*, not consume. Circular.

FLOP estimation fails differently: it normalizes only the substrate, not the *governance-relevant work*. A 3B model thrashing through 10k retries does the same FLOPs as a 70B model nailing it in one shot; the basin should treat these very differently. FLOP-normalized E would equate them.

Cost normalization fails because price is set by the provider, not by physics. Anthropic could halve Opus pricing tomorrow and the same agent would suddenly have half the E. That's not energy — that's a market signal, and folding it into E couples governance to vendor pricing decisions in a way that's both unstable and embarrassing.

### Where the steel-man does NOT fail

The "you've tolerated heterogeneity in E before" point lands. The proposal needs to be honest that E is already a noisy aggregate, and the principled answer is not "tokens are too noisy for E" — it's "E is a budget, not a measurement, and we're keeping its surface stable for reasons of theoretical economy, not measurement purity." That's a defensible position. The current proposal sounds like it's claiming purity, which is overclaim.

Also: "complexity feeds E and complexity is a worse proxy" is correct. The honest follow-up is to *deprecate complexity as an E-input* once compute receipts exist, OR to keep complexity as a *prediction* that compute receipts can validate. Either move strengthens the framework. The proposal as written keeps complexity in E and adds receipts as a sidecar — leaving the worse measurement load-bearing while the better one sits in audit. That's the wrong structural decision.

**Verdict on the steel-man**: opposition wins partial ground. Tokens should not enter E directly. But the proposal should (a) explicitly demote `complexity` from primary E-input to "prediction validated against receipts" and (b) drop any rhetoric implying E is a clean physical quantity. E is a budget. Receipts validate budget claims. That framing makes the sidecar architecturally inevitable rather than a stylistic choice.

---

## 2. Conceptual seams the proposal glosses over

The word "receipt" is doing rhetorical work the proposal hasn't earned. A receipt implies (a) a transaction completed, (b) an item received, (c) a counterparty. None of those map cleanly to what's being measured. Three candidate ontologies, each with different downstream implications:

### Ontology A: Receipt = transaction record (the proposal's implicit framing)

Implies: one event, one cost, one counterparty (the operator paying for the compute). Joins to outcome_event because the outcome IS the item received.

**Failure mode**: the moment you support check-in receipts (phase 2), the "transaction" framing breaks — there's no item received, just a meter reading. The schema's nullable `event_id` is the symptom of this conceptual confusion.

### Ontology B: Receipt = telemetry / log line

Implies: continuous emission, no causal binding to outcomes, primarily for post-hoc analysis. Should live in a time-series store, not a relational table.

**Failure mode**: undermines the proposal's claim that receipts can drive operator-economics queries like `cost_per_verdict`. If they're just logs, joining them to verdicts is a reconstruction problem, not a primary key.

### Ontology C: Receipt = meter reading (utility metering)

Implies: standalone time-series, indexed by (agent, time), occasionally annotated with what was happening. The meter reads regardless of whether anything productive occurred. This is what `process_agent_update` receipts in phase 2 actually are.

**Failure mode**: doesn't naturally bind to outcomes, which is the proposal's phase 1 use case.

### Ontology D: Receipt = thermometer next to a heat engine (governance-adjacent measurement)

This is the framing the proposal *should* adopt. The basin is the heat engine; receipts are an external instrument observing the engine's environment. The thermometer doesn't drive the engine, doesn't appear in its equations of motion, but its readings inform the operator and validate the engine's claimed efficiency. This is the only ontology where "audit-only" is *naturally* enforced — a thermometer isn't a control input, period.

**Recommendation**: drop "receipt" terminology and adopt "compute meter" or "compute observation." This is not a cosmetic change — it forecloses the slip-into-basin failure mode by making the architectural role explicit. "We meter compute, we don't budget it" is a cleaner doctrine than "we receipt compute but don't grade with it."

The phase 1 (outcome-attached) vs phase 2 (check-in-attached) split is then naturally two different objects: an *attribution* (outcome → cost) and a *measurement* (period → cost). They share a table only by accident of database normalization, not by ontology.

---

## 3. Goodhart and the "audit-only" firewall

The proposal claims receipts are not a Goodhart target because they don't grade agents. This is wrong in three ways:

### (a) Operators read dashboards, agents predict operators

Phase 4 surfaces slop/thrash anomalies in Discord. The moment that channel exists, an agent that *predicts* an operator will see and act on those alerts has incentive to optimize toward not-tripping-them. This is true even if no automated grading exists. The agent's reward signal is "operator satisfaction," and operator satisfaction is conditioned on the dashboard. Goodhart applies through the operator, not around them.

This is *especially* true for residents that get dialectic-reviewed by other agents. A reviewer agent reading the dashboard will weight slop_index findings — that IS grading, just laundered through a peer.

### (b) The audit/grading distinction relies on no-one ever wiring them together

"Receipts are observed and analyzed; agents are not graded against them." Today. By policy. There is no architectural barrier to a future PR that grades on them. The proposal's phase 3 (`slop_index`, `thrash_index`) is *literally a step toward grading* — these are scalar agent-quality indices in everything but name. Phase 4 surfaces them to operators. Phase 5 (unwritten) is "we noticed slop_index correlates with rejected verdicts, why don't we just gate on it?" Each step is locally reasonable.

The firewall the proposal claims is not enforced by:
- type system (no type prevents `slop_index` flowing into basin code)
- schema (no constraint marks the table as one-way)
- test suite (no contract test fails if it leaks)
- code review checklist (no rubric flags it)

It's enforced by Kenny's memory and this doc. That's not nothing, but it's not a firewall.

### (c) Self-fulfilling slop suppression

Suppose slop_index correctly identifies "agent used 50k tokens for a 1-line fix." The fleet sees this surfaced. Agents (or their harnesses, or the prompt engineering on top of them) adapt to "be concise." Now you've trained the fleet to *underexplore*. The agents that were 50k-token-thinkers because they were genuinely working through hard problems get suppressed alongside the agents that were just thrashing. The slop signal collapses into a generic "be brief" pressure that may anti-correlate with quality on hard tasks.

This is the *exact* failure mode UNITARES is designed to surface, as the proposal correctly notes. But the proposal then assumes that surfacing the metric without grading on it avoids the failure. It doesn't. Surfacing IS grading, in any social system where the metric is visible.

### What would actually firewall this

1. **Contract test**: parametrized test asserting `governance_core/` has no import path to `compute_receipts` table or related modules. Run in CI.
2. **Schema-level marking**: `compute_receipts` lives in a separate Postgres schema (`audit.compute_receipts`, not `public.compute_receipts`), and the basin solver's role lacks SELECT on that schema. Now leakage is a database error, not a code review oversight.
3. **Dashboard policy**: slop/thrash panels show **distributions**, never per-agent rankings. No leaderboards. The signal is fleet-level, not agent-level. This is where the firewall actually has to be — at the human surface.
4. **Honesty in the doc**: stop saying "not a Goodhart target." Say "Goodhart pressure exists through operator attention; we mitigate by surfacing distributions not rankings, and by accepting that compression-vs-correctness tradeoff is a governance question we need calibration on, not a property of the metric."

---

## 4. The check-in case (phase 2)

This phase is where I disagree most sharply.

A check-in is not a productive outcome. It's a governance act — the agent reporting state to the system, the system updating its model of the agent. "Compute spent on a check-in" is the cost of the *governance overhead*, not the cost of the work.

Three ways to read this number, and they pull in different directions:

### Reading 1: Noise

A check-in's token cost is dominated by the boilerplate (system prompt, tool definitions, MCP framing) and the agent's narrative summary. The variable cost — actual cognition during the check-in — is a small fraction. Treating this as signal-about-the-agent is mostly noise about prompt engineering.

### Reading 2: Signal about governance overhead

Aggregated across the fleet, check-in token cost answers "what fraction of fleet compute is governance overhead?" That's a real and important number for the v7 paper. But it's a *fleet-level* signal, not a per-agent one.

### Reading 3: Perverse incentive

If receipts attach to check-ins and check-ins are surfaced to operators (phase 4), agents that produce *more thorough* check-ins (longer responses, more tool calls to gather state) look "expensive" relative to agents that produce terse check-ins. The system has just rewarded under-reporting.

This is *worse* than the Goodhart pressure on outcomes, because the entire point of a check-in is for the governance system to know what's happening. Penalizing thoroughness in check-ins (even passively, through dashboard visibility) corrodes the primary signal the basin runs on.

**Recommendation**: do not attach receipts to `process_agent_update` per-call. Aggregate check-in compute at the fleet level via Chronicler, report as a single "governance overhead %" metric. Don't make individual agents accountable for the cost of their own check-ins. That number, if surfaced, will be optimized in the wrong direction.

If there's a real case for per-agent check-in cost — e.g., detecting an agent stuck in a check-in loop — frame it as an *anomaly detector* (alert on burst), not a *receipt* (log every one). Different ontology, different name, different downstream implications.

---

## 5. The single sharpest weakness

In two years, this proposal embarrasses itself if `slop_index` ends up gated into a verdict. Not via a single deliberate decision, but via the path: phase 3 ships → operators find slop_index useful → a contributor proposes "let's let agents see their own slop_index" → that becomes a feedback loop → someone notices slop_index correlates with reject verdicts → someone proposes a "slop_pause" verdict for clear-cut cases → it ships behind a flag → the flag flips on. At each step, the local argument is reasonable. The cumulative outcome is that compute became a basin input through the back door, and the heterogeneity argument the proposal made in 2026 is now a doc nobody reads. The single sharpest weakness is that the firewall is rhetorical, and rhetorical firewalls always lose to incremental local reasoning over a 24-month horizon. The fix is structural: separate database schema, contract test, distribution-only dashboards, and a doctrine ("we meter, we don't budget") that survives the people who wrote it.

---

## Synthesis

The proposal is correct in its central decision (sidecar, not channel) and wrong in three structural ways:

1. **Ontological**: "receipt" is the wrong word. It implies transactional binding the proposal can't sustain through phase 2. Adopt "compute meter" / "compute observation," and split phase 1 (attributions: outcome → cost) from phase 2 (measurements: period → cost) into different schemas, possibly different tables, definitely different doctrines.

2. **Architectural**: the audit-only firewall is rhetorical. Make it real: separate Postgres schema (`audit.*`), parametrized contract test against `governance_core/` import paths, distributions-not-rankings on dashboards. Otherwise the rule erodes within four PRs.

3. **Theoretical honesty**: stop claiming E is a clean physical quantity that tokens would pollute. E is a budget. The argument for keeping tokens out of E is theoretical economy and heterogeneity, not measurement purity. Owning that lets you (a) demote `complexity` from primary E-input to a prediction-validated-by-receipts, and (b) survive the steel-man cleanly.

The phase 2 check-in receipts should be reframed or removed. Per-agent check-in cost is at best noise and at worst a perverse incentive against thorough state reporting — the exact signal the basin most needs.

Phase 1 + the structural firewall changes + the "compute meter" reframe is a strictly stronger version of this proposal. Ship that. Defer phase 2 until you have a concrete answer to "what does per-agent check-in compute MEAN that isn't an attack on thoroughness."

---

## Open questions worth carrying forward

- Should `complexity` be deprecated as an E-input once receipts exist, or kept as a prediction validated against receipts? (Either is defensible; status quo of both is not.)
- Where does FLOP estimation actually fit? Not in E, but possibly in a separate "substrate-cost" view that's more honest than dollar cost.
- The residents have heterogeneous receipt coverage (Sentinel: none, Vigil: full). Is that a measurement gap, or a finding about which agents do governance work versus which agents do productive work?
- Distribution-vs-ranking dashboard policy: who enforces it? Does the dashboard skill (`unitares-governance:unitares-dashboard`) need a rubric line?
