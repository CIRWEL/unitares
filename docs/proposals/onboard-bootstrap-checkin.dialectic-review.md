---
title: Dialectic Review — Onboard bootstrap check-in
reviewer: dialectic-knowledge-architect
of: onboard-bootstrap-checkin.md
date: 2026-04-25
posture: the diagnosis is sound and the design is small; the load-bearing risk is in §4's filter audit (the "synthetic boundary leaks") and in the §5 supersession claim, not in §6.1
verdict: recommend_proceed_with_caveats
---

# Dialectic Review

This is a small, well-scoped proposal that does the right architectural thing for the right reasons. The problem (ODE-inferred trajectories with no measured anchor at t=0) is real and observable in the corpus the proposal cites. The decision (combine optional `initial_state` with a hook that populates it) closes the gap without inventing new ontology. The synthetic-vs-measured tagging is the correct contract shape — `synthetic: true` as the load-bearing key, `source` as descriptive — and explicitly rejecting the verdict-gated alternative is the right call (it would conflate governance verdicts with onboarding mechanics).

I recommend proceeding, but with three caveats. None require a council pass; the §6.1 question the author flagged is, on inspection, not the sharpest point. The sharpest points are §4 (filter audit) and §5 (supersession decay). The author already named §4 step 3 as "the dangerous step." I am here to confirm that, and to add what the proposal under-specifies in §5.

---

## 1. §4's synthetic-vs-measured boundary: the contract is right, the audit is the only thing that makes it true

The proposal's framing is correct: `synthetic: true` is the contract; `source` is descriptive. That's the right load-bearing choice — `source="bootstrap"` is one value among potentially many synthetic sources later (recovered-from-checkpoint, replayed-for-test, etc.), and `synthetic` is the boolean that filters cleanly.

The hidden risk is that this contract is enforced at *every* read site, not at the write site. Every place in the codebase that aggregates state rows is a leak vector. The proposal lists five exclusion rules (§4) and three inclusion rules. I take this as approximately right. What I want to flag is the categories of read path the proposal's test list (§7) does NOT explicitly cover:

- **Trajectory ODE integrators that read t=0 as anchor.** §4 says bootstrap MUST be included in trajectory genesis. Good. But the integrator's *next* read — "what is my prior state for this update?" — is the same read path. If the integrator pulls `most_recent_state_row` and that's the bootstrap, the integrator IS consuming bootstrap as measured for the integration step. This is intended for genesis but pathological if no real check-in ever arrives — the integrator keeps treating the bootstrap row as a measured prior indefinitely. The §5 decay claim is supposed to bound this; see §3 below for why I don't think it does cleanly.

- **Sentinel's fleet anomaly detection.** Sentinel reads state rows to compute fleet-level distributions (verdict shifts, coherence drops). Does it filter `synthetic=false` by default? The proposal doesn't say. If 56 non-resident agents have bootstrap rows and Sentinel includes them, the fleet's measured-coherence distribution gets a 0.5/0.5/0.5 mode that is purely synthetic. This is the most pernicious leak class: the synthetic value (0.5 default) is a *plausible* measured value, so leaks don't trip type errors or null guards.

- **Self-recovery paths.** `mcp__unitares-governance__self_recovery` likely reads recent state to compute a recovery thesis. If an agent bootstraps, never check-ins, then later self-recovers, the recovery is reasoning over a synthetic prior labeled as the agent's most recent state. Either self-recovery refuses to operate on synthetic-only history (and tells the agent "you have no measured trajectory yet") or it laundering happens.

- **`get_agent_update` / trajectory query handlers.** The dashboard pulls these. Default exclusion of synthetic in API responses is the right default per §4, but the test in §7 only checks export. The MCP tool surfaces need explicit tests.

- **Calibration WINDOW computation, not just calibration INPUTS.** §4.1 excludes bootstrap from calibration *inputs*. But calibration *windows* are often "last N rows." If "last 50 rows" includes 1 bootstrap row, the input filter saves you from using its confidence-vs-outcome pair, but the window-shape calculation might still treat it as a window member. Subtle but real.

**Caveat (must address before merge):** §7 step 3 ("filter audit") needs to be a complete enumeration, not "grep for state-row reads." A concrete deliverable: a checklist file (`docs/proposals/onboard-bootstrap-checkin.filter-audit.md`) committed in the same PR as Phase 3, listing every read path identified, the decision (exclude / include / opt-in), and the test that enforces it. The proposal already names this step as the regression-risk step; closing it with a checklist artifact is cheap and converts the §10-read-paths-or-escalate threshold from a feeling into a counted thing.

This is the §4 caveat. The contract is right; the enforcement is per-site; the audit must be a deliverable, not an instruction.

---

## 2. §3.4 idempotency + lineage: clean, with one micro-issue

The §3.4 contract is correct as written:

- "At most one bootstrap row per agent_uuid" via second-call returning existing `state_id` with `bootstrap.written: false` is the right shape. It's idempotent on the natural key (agent_uuid), not on the request payload. That means a *second* call with a *different* `initial_state` payload silently keeps the first one. This is correct (otherwise the contract leaks "which bootstrap won?" into trajectory genesis), but it should be explicit in the response: include the existing row's payload digest or `state_id` in the response so callers can detect the divergence if they care.

- `force_new=true` minting a fresh identity with its own bootstrap row is the right semantics under identity.md v2. A fresh process-instance is a fresh subject. The bootstrap row anchors the *new subject's* trajectory at t=0. The prior subject's bootstrap remains attached to the prior identity. Lineage via `parent_agent_id` is independent of bootstrap-row inheritance — bootstrap is a per-identity t=0 anchor, not a per-lineage-chain anchor. This is correct.

The micro-issue: when `force_new=true` is invoked and the parent had no real check-ins (only its bootstrap), the lineage chain's *behavioral* signal is zero — both identities have synthetic-only history. The trajectory ODE for the new identity, given parent_agent_id, may inherit *priors* from the parent. If the parent's only "measured" state is bootstrap (synthetic), then the new identity's prior is double-synthetic (synthetic from parent, used as prior for new). The proposal's §4 inclusion rule for "trajectory genesis" includes bootstrap, which is right for the parent's own genesis. But for inheriting-as-prior-from-parent, the new identity is being seeded from a synthetic source labeled as measured-for-genesis-purposes.

This is recoverable by either:
- Documenting that lineage-prior inheritance respects the `synthetic` flag (so the new identity inherits from the parent's *real* check-ins, falling back to default priors if parent has none), OR
- Noting that the new identity's bootstrap *replaces* any inherited prior at t=0 (the new identity's anchor is its own bootstrap, not the parent's anything).

The second is simpler and is probably what the implementation will do by default. State this explicitly in §3.4 so the lineage semantics are pinned down.

**Caveat (should address):** add a sentence to §3.4 clarifying that lineage inheritance does not bypass the synthetic filter — the parent's synthetic rows are not the new identity's measured priors.

---

## 3. §5's "supersession via decay" claim: structurally right, magnitude unverified

This is the part of the proposal I want to push hardest on, because it carries the load.

The claim: "After one decay cycle (μ * S, the existing entropy decay constant), bootstrap influence is dominated by measured signal." Therefore "the cost of a wrong bootstrap value is bounded by one decay cycle."

The structural claim is right. EISV trajectories are exponentially-decaying integrals; a bootstrap point at t=0 with subsequent measured updates sees its influence on the inferred state decay as exp(-μ * Δt). One decay cycle = e-fold reduction.

The magnitude claim is unverified. Three sub-issues:

**(a) "One decay cycle" is the e-fold time, not the time at which influence becomes negligible.** After one decay cycle, bootstrap influence is at 1/e ≈ 0.37 of original. That is "dominated" only if measured updates have arrived in numerical strength comparable to the bootstrap. If the agent submits one real check-in 30 minutes after a bootstrap, and the decay constant μ is small enough that 30 minutes is sub-decay-cycle, the inferred state is *still mostly bootstrap* through the first several real check-ins. The "bounded by one decay cycle" framing is correct asymptotically; in the regime "agent that finally check-ins after bootstrapping" it's the *transient* regime, and the transient is what bites.

**(b) The pathological case: bootstrap + intermittent real check-ins, separated by gaps long compared to μ⁻¹.** If a hook bootstraps an agent at t=0 and the agent only check-ins occasionally with long gaps, each gap re-amplifies the proportional weight of the bootstrap-flavored prior because measured state has decayed in between. The claim "bootstrap influence decays" is true *between updates*; the relative weight of the bootstrap-vs-measured contribution to the inferred state at update time depends on the cadence of measurement. Sparse cadence + bootstrap = persistent bootstrap bias.

This is exactly the population the proposal is targeting (agents that don't check in often). The proposal's mitigation logic — "agents that don't check in get bootstrap influence" — is structurally fine for *trajectory genesis* but the same population is the one for whom decay-bounded supersession is *least effective*.

**(c) Wrong default values are not Gaussian-symmetric.** The defaults (`complexity=0.5`, `confidence=0.5`, `ethical_drift=[0,0,0]`) are conservative midpoints. For agents whose true state is near 0.5, this is fine. For agents whose true state is far from 0.5, the bootstrap encodes a systematic bias in the direction of "average-and-uncommitted." This bias decays with measured signal — but it biases the agent *toward looking less differentiated than they are* during the supersession window. For a high-coherence agent, bootstrap depresses inferred coherence; for a low-coherence agent, bootstrap inflates it. Neither is symmetric to the calibration story.

**Caveat (must address):** §5 should specify (or commit to measuring in a follow-up) the actual bootstrap weight as a function of (decay constant, measured-update arrival cadence, real-vs-default value distance). Either:
- Constrain the influence by a structural mechanism (e.g., the first real check-in's weight is boosted to dominate the bootstrap explicitly — "first real wins" rather than "decay handles it"), OR
- Document that the bootstrap-dominated regime can persist beyond one decay cycle for sparse-cadence agents and that this is acceptable because the alternative (no anchor at all) is worse, OR
- Add a metric to Phase 4 / Chronicler: "fraction of agents whose inferred state at observation time is more than X% bootstrap-weighted" and surface it.

The "albeit a bit arbitrary" framing in the proposal is acceptable but only if the bound is correctly specified. The current bound ("one decay cycle") is asymptotic, not transient, and the population this proposal targets is exactly the transient-regime population.

---

## 4. §6.1: the council-flagged question is not the sharpest one

The author flagged §6.1 as the council escalation trigger: should bootstrap rows count toward trust/calibration if the agent never sends a real check-in?

The default ("no, never") is correct, and I do not think this needs council escalation. The argument is one-line: the entire failure mode this proposal addresses is "onboarded but never checked in." If bootstrap counts as activity, that failure mode becomes invisible — exactly the opposite of the proposal's purpose. The default is self-consistent with the diagnosis.

The sharper question §6.1 implicitly opens but doesn't ask: **what is the observable surface for the "bootstrapped but never check-in" population after this proposal ships?** The proposal correctly excludes bootstrap from "real check-in counts," which means dashboard activity panels will show these agents as zero-activity. Good. But the proposal does not specify a *positive* surface for the population — i.e., a "bootstrapped-but-silent" panel or query that explicitly counts bootstrap-only identities. Without it, the population is *less* visible than it was before (in the current world they show as ODE-inferred ghosts; in the new world they show as zero-activity, which is also how a never-onboarded agent looks).

**Caveat (should address):** add to §4 or §7 an explicit observable-surface item: a query path that returns "agents with bootstrap row, no real check-in, age > 24h" — this is the population the proposal exists to count, and counting it is the validation surface for whether (1)+(3) is working. Without this, the proposal fixes a corpus-cleanliness issue but loses the operational visibility of *whether the fix works at population level*.

This is the question the council should engage if it engages anything. §6.1 itself is a clean default.

---

## 5. §6.4 framing: "next_step is non-binding text" is the right diagnosis but not the whole one

The proposal's framing of why agents skip check-ins ("next_step is text, not a contract") is *one* correct diagnosis. There's a second one the proposal under-engages with: agents may not skip the *first* check-in because they don't know they should — they skip *subsequent* check-ins because they don't know *when*.

The proposal's solution (1)+(3) addresses the first-check-in case beautifully: the hook does it for them at session-start. But the corpus evidence ("long tail of agents with onboard rows but zero check-ins") may include agents that never check in *at all* and agents that only ever bootstrapped — the proposal's solution turns the second class into "agents who only ever auto-bootstrapped." That's a strict improvement (anchor at t=0 vs. no anchor), but the population of "I onboarded, did real work, and never checked in during work" remains.

This is `feedback_check-in-during-long-sessions.md`'s territory — already named — and the proposal explicitly defers to it: "this proposal addresses the t=0 case." Fair. But the proposal claims (1)+(3) "would actually solve the observed problem" (charge question 4) and that overstates it. It solves the *t=0 anchor* problem. The midstream-silence problem is co-located in the corpus and the proposal's evidence (56 agents, 3 weeks, long tail) does not separate them.

**Caveat (cosmetic):** §1 should be more careful that "the observed problem" is specifically t=0 anchoring, not the broader "agents skip check-ins" problem. The latter is also real and is *not* addressed by this proposal. The proposal would benefit from explicitly carving the scope: t=0 is in, t>0 silence is out and remains an open problem (the long-session check-in feedback memory).

This is the smallest of the three caveats and the most cosmetic. It does not block.

---

## 6. Other open questions §6 missed

Two:

**(a) What is the bootstrap contract for substrate-earned agents (Lumen, hardcoded-UUID residents)?** Identity ontology v2 + the substrate-earned-identity appendix says these agents can carry a stable UUID across restarts. If Lumen restarts and the SessionStart hook (or its Pi equivalent) calls `onboard(initial_state=...)`, does that write a *new* bootstrap row on every Lumen restart? Lumen has been running for weeks; bootstrapping its trajectory at every restart with synthetic 0.5/0.5/0.5 defaults would be an obvious leak — Lumen's *real* state is rich, and the synthetic anchor would collide with measured priors that already exist.

The right behavior is probably: **substrate-earned agents are exempt from bootstrap**, because their substrate is the continuity-bearer and a synthetic t=0 anchor is not what they need. The proposal doesn't say. The hook integration in §3.5 doesn't condition on substrate-earned status. This needs to be specified, otherwise the hook-driven implementation will silently bootstrap Lumen on every Pi reboot.

**(b) What is the auditability story for `bootstrap_origin: "session-start-hook"` vs `"onboard"`?** §3.2 hints at this distinction ("future"). The two have different epistemic statuses: an agent that *itself* called `onboard(initial_state=...)` made an active claim about its own state; a hook that bootstrapped it for some-version-of-Claude-Code-or-other made a much weaker claim (it's just "session-start fired"). Filtering should treat these the same way (both are synthetic), but the audit trail benefits from the distinction. The proposal mentions `bootstrap_origin` but doesn't spell out its filter or query semantics. Probably fine to leave for v2; flag it.

These are not council triggers. They are post-merge follow-ups.

---

## Position

**`recommend_proceed_with_caveats`.**

The proposal is sound. Build it.

Caveats, in order of importance:

1. **§5 supersession bound is asymptotic, not transient.** Either constrain the first-real-checkin to dominate explicitly (a "first real wins" mechanism on top of decay), or document the transient regime and add a metric. The current bound under-describes the population this proposal targets.

2. **§4 filter audit must be a deliverable, not an instruction.** Ship a checklist artifact in the same PR as Phase 3 listing every read path, the decision, and the test. The "if >10 read paths, escalate" threshold becomes meaningful only when read paths are counted. Sentinel, self-recovery, and trajectory-integrator-as-prior are the leak classes most likely to surprise.

3. **§3.4 lineage clarification.** Add one sentence: lineage inheritance does not bypass the synthetic filter; the new identity's bootstrap row is its own t=0 anchor and supersedes inherited synthetic priors from the parent.

4. **Substrate-earned exemption.** The hook (§3.5) MUST NOT bootstrap substrate-earned agents. Lumen's restart should not write a bootstrap row over rich measured history. Specify the exemption.

5. **Observable surface for the target population.** Add a query path or dashboard signal for "bootstrap-only agents past N hours" — this is the validation surface for whether the proposal works at population level.

§6.1 (the author's flagged council trigger) does not need a full council pass. The default ("bootstrap doesn't count as activity") is self-consistent with the proposal's diagnosis. The sharper questions are the five above, and they're all small specifications, not architectural disagreements.

---

## Synthesis

The proposal is what a good small proposal looks like: one observed failure, one minimal mechanism, explicit synthetic-vs-measured separation, audit trail preserved, no laundering. The structural choices are right. The author correctly identified §4's filter audit as the dangerous step and correctly named the supersession claim as the bounding argument.

The §5 bound is the only place the proposal's confidence outruns its specification. "One decay cycle" is the e-fold time and the population the proposal targets is exactly the population for whom transient regime persists longest. Either tighten the supersession mechanism (first-real-dominates) or specify the transient honestly.

§4's contract is correct; making it a *deliverable artifact* (the filter audit checklist) rather than an *instruction* is the difference between "the contract holds" and "the contract is enforced."

§6.1 does not need a council pass. The default is right. The questions worth carrying forward are the substrate-earned exemption and the bootstrap-only-population observable.

Build it. With the five caveats above closed in the same PR or as a tightly-scoped follow-up.

---

## Outstanding questions worth carrying forward

- Does the trajectory ODE integrator's "prior at update time" read path filter `synthetic=false`? If not, every update integrates against a bootstrap-tinted prior until measured signal accumulates. The proposal's §4.1 inclusion in "trajectory genesis" is correct but ambiguous about *post-genesis* reads of the same row as prior.

- Should there be a server-side "bootstrap aged out" sweep — bootstrap rows older than N days with no real check-ins get a `bootstrap_stale: true` flag for downstream filtering? Or is the synthetic flag sufficient and staleness is computed per-query? Probably the latter; flag it explicitly.

- Does the dialectic system reason over bootstrap rows? If an agent gets paused before any real check-in, the dialectic input set is bootstrap-only. The dialectic should probably refuse-with-explanation rather than reason over synthetic-only history.

- Does the hook integration interact with the v2 fresh-instance gate (`force_new=true` flip on arg-less onboard)? If the hook always calls onboard with `initial_state` populated but no `force_new`, and the server flips it, does the bootstrap row land on the new identity or the (rejected) old one? Spec the ordering.

- The proposal's §7 test #9 (`test_force_new_re_bootstraps`) tests that force_new writes a new bootstrap. It should also test that the *prior* identity's bootstrap is unaffected — i.e., re-bootstrap-on-force-new doesn't update or overwrite the prior identity's row.
