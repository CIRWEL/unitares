---
title: Dialectic Review (Round 3) — Compute Meter v2.1
reviewer: dialectic-knowledge-architect
of: compute-meter-v2.1.md
date: 2026-04-25
posture: hardest pass yet; the bar is "could I ship this and not regret it in 18 months?"
---

# Dialectic Review — Round 3

v2 was a substantively better proposal than v1, and v2.1 is a substantively more honest proposal than v2. The honesty is the thing that has improved most. v1 had a rhetorical firewall pretending to be a doctrine; v2 had a structural firewall pretending to be implementable; v2.1 has a partial firewall correctly labeled partial. That progression is the right shape.

But "more honest" is not the same as "good enough to build." The bar for round 3 is whether v2.1 *as specified* gives you a system you can defend in 18 months. On that bar v2.1 is close, with two specific sharp edges that I'd want filed before I called it shippable, and one place where the honesty is doing rhetorical work the structure doesn't earn.

The nine prompts in order.

---

## 1. Did the firewall reframe (3 layers + Layer 4 future) actually fix round 2, or just rename the gap?

**It substantively fixed it. But Layer 3 is doing more rhetorical work than it earns — it should be relabeled to match what it actually does.**

Round 2's complaint was: v2 claimed three layers of architectural enforcement, one of which (the role denial) was impossible in this codebase as written, and the AST test alone was decorative without it.

v2.1's response is structurally correct:
- **Layer 1 (schema separation)**: is real DDL. `meter.*` distinct from `core.*` and `audit.*`. Verified achievable.
- **Layer 2 (AST contract test)**: walks `governance_core/` imports for `meter` references. Real test, real CI gate. Acknowledges its bound (catches imports, not data flow).
- **Layer 3 (runtime startup assertion)**: this is where v2.1 quietly slips. As specified (v2.1 §Layer 3), the assertion does this: "from the basin path, attempt `SELECT meter.compute_emissions LIMIT 0`. If it succeeds, log a WARN."

A WARN that fires every startup, by design, because the codebase shares one pool today (verified: `src/db/postgres_backend.py:134` creates a single `_pool: Optional[asyncpg.Pool]`) — that is not a firewall. It is a permanent log line. A firewall is something an attacker (including an absent-minded contributor) cannot cross without being stopped or making a noise that someone will hear. A WARN that fires unconditionally on every startup is the textbook example of an alert that gets filtered out within two weeks of going live, then ignored forever. v2.1 even acknowledges this implicitly when it says "the WARN flips to ERROR once Layer 4 lands" — but Layer 4 is named-as-future and explicitly out of scope.

So the operational state at end-of-Phase-1 is: a WARN that fires every startup, looks like normal noise, and is documented to fire forever-until-Layer-4. That isn't enforcement. It is *documentation that the basin can read meter data, written into the log stream*. That is more honest than v2's claim of architectural enforcement, but it is not the equivalent of the role denial that v2 imagined.

**The fix is a one-line correction**: stop calling Layer 3 a layer of the firewall. Call it what it is — a *flip-point* preparation: a check that exists today as a self-test (the pool *can* reach meter, as expected) and *will* be inverted by Layer 4 to fail-the-process if it ever can. Until Layer 4 lands, the firewall is two layers (schema + AST), and the WARN is honest scaffolding for future enforcement. That framing matches the truth and avoids the load-bearing-on-decoration trap that round 2 named.

If the proposal insists Layer 3 is a current layer of protection, then it must specify what reading the WARN is supposed to *do*. v2.1 leaves this blank. A reader on call seeing `WARN: basin pool can reach meter.compute_emissions (Layer 4 not yet shipped)` on every restart has no action to take. It is a notification, not a control.

**Verdict on prompt 1**: the reframe substantively closed round 2's structural critique (no more impossible-to-implement role denial), but Layer 3 is mislabeled. Relabel it as flip-point scaffolding for Layer 4, not as a current layer of enforcement, and the proposal earns its honesty claim.

---

## 2. The action meter gating is policy-level. Is the acknowledgement enough?

**The acknowledgement is necessary but not sufficient. v2.1 still over-promises by using the word "gating" for what is actually "convention plus a checklist item."**

Round 2 argued the action meter is more dangerous than the compute meter (homogeneous units, looks like a productivity signal, three locally-reasonable PRs from being a Sentinel input). Round 2's recommendation was: tighter firewall for actions than for compute, OR ship actions in a separate proposal with its own threat model.

v2.1 chose neither. It kept actions packaged with compute, and substituted four policy controls (§Action meter — stricter gating):
1. Per-agent dashboard panes only at first.
2. Cross-agent action analysis requires its own proposal.
3. Action types are tightly scoped.
4. Calibration view operates on ratios, not raw counts.

Items 1, 3, 4 are reasonable defaults but enforced by code review and PR discipline. Item 2 is enforced by a `// CHECKLIST: cross-agent-action-analysis` PR template item.

The proposal acknowledges this in plain text: "These are policy controls, not code controls. They are weaker than schema controls. That is acknowledged." Good — the acknowledgement is real.

But: a checklist item in a PR template is not a *gate*. It is a *prompt*. The implementation of "any PR that introduces a query joining action counts across agents must cite a passing council review" depends entirely on (a) reviewers reading the PR template, (b) reviewers correctly identifying that a given query "joins action counts across agents," and (c) reviewers refusing to merge without the citation. Each of those is a reviewer-attention failure away from gone. The dashboard skill (`unitares-governance:unitares-dashboard`) is the only structural backstop, and it codifies layout conventions, not query semantics.

The honest fix that v2.1 has the materials for, and could adopt without a major rewrite:

- **Make item 2 (the checklist) self-falsifying**. Add a tiny pre-commit / CI check that grep-greps SQL files for patterns like `action.*GROUP BY agent_id` or `COUNT.*action.*agent_id` and fails CI unless the diff includes the magic comment `// council-reviewed: <PR-link>`. This is a 30-line script. It catches 80% of the "naive PR adds a cross-agent action ranking query" cases. The remaining 20% (queries built from string formatting at runtime, queries in dashboard JS) get caught at code review, but at least the dumb cases are blocked.

Without this, "stricter gating" is overstatement. The action meter ships with the same actual enforcement as the compute meter (schema + AST), plus a sticky note. v2.1 should either (a) downgrade "stricter gating" to "stricter convention" in the section header, or (b) implement the grep-CI check. Either is fine; the current state — the *header says gating, the body says policy* — is the small remaining over-promise.

This is the single biggest place where the v2.1 honesty improvement isn't quite finished.

**Verdict on prompt 2**: the acknowledgement is *not* enough on its own. Either rename the section to match the policy-level reality, or add the cheap CI check that turns the policy into actual structural enforcement. Both are within the spirit of v2.1; neither is in v2.1 as written.

---

## 3. Is the complexity demotion threshold (MAE ≤ 0.15 over 90d, ≥10 agents) actually falsifiable?

**Yes — and verified meetable in this codebase. But the threshold is doing one thing the proposal doesn't acknowledge: it is a *per-substrate quantile* threshold dressed as a global threshold.**

I checked the codebase. The threshold's data prerequisites are concretely meetable:

- `core.agent_baselines`: 776 agents with non-null `prev_complexity` over the last 90 days. 42 agents with `update_count ≥ 50`, 19 with `≥100`, 9 with `≥200`. The "≥10 distinct agents" floor is met today; the "90-day rolling window" is met today.
- `audit.outcome_events`: 429 distinct agents over 90 days, 26 with ≥50 events, 14 with ≥100, 4 with ≥500. So the *outcome side* of the calibration is also data-rich.

That's not the worry. The worry is what the threshold is actually measuring once Phase 4a runs:

`MAE(predicted_complexity_quantile, observed_compute_quantile) per (agent_id, substrate, 7-day rolling window)`. Then the demotion criterion is "median per-agent MAE is ≤0.15."

Three structural concerns the proposal doesn't address:

**(a) The quantile transform hides the substrate problem.** Quantile-on-quantile MAE is a rank-correlation-flavored measure. By definition it normalizes both sides to [0,1], which means an agent that always reports `complexity=0.5` regardless of work and always uses ~5000 tokens will score *perfectly* (both quantile distributions degenerate to a point, MAE = 0). This is the Vigil and Chronicler case in the codebase right now (`agents/vigil/agent.py` shows complexity computed from a small set of additive signals that mostly land in 0.15-0.6; `agents/chronicler/agent.py` literally has `complexity = 0.4 if failures > 0 else 0.1`). Quantile MAE ≤ 0.15 is achievable by being *self-consistently degenerate*, which is not the same as "self-reported complexity tracks observed compute."

**(b) "Median per-agent" is a robust statistic over the wrong axis.** The fleet's 4 high-volume agents (the ones with ≥500 events) will dominate the input data but contribute one median bin each. A small number of high-quality calibrators can satisfy the threshold while the long tail of 400+ low-volume agents is a calibration mess. v2.1 should specify whether the threshold is "median across agents weighted equally" or "median across observations weighted by event count" — these will give different verdicts on the same data.

**(c) The threshold has no asymmetry for false positives.** Demotion is a one-way move: once `complexity` is removed as primary S input, the basin's S coefficient gets recalibrated, and the data path that produces self-reported complexity may atrophy. If the threshold accidentally flips positive due to (a) or (b) — passing the numerical bar via degenerate distributions — the demotion is hard to reverse. The threshold needs a falsification asymmetry: ≤0.15 for at least N consecutive 90-day windows, OR a test that the per-agent quantile distributions are non-degenerate (e.g., complexity stddev > 0.1 within agent before that agent counts toward the median).

**Verdict on prompt 3**: the threshold is falsifiable in the sense that "fails to be met" is a defined and detectable state. It is meetable in this codebase. But it is *too easy to pass spuriously* due to the quantile transform plus the degenerate self-report distributions of the existing residents (which I verified). v2.1 should add a non-degeneracy precondition before agents count toward the median — otherwise Phase 4c could trigger on a fleet that is self-consistent but not actually calibrated. This is fixable in a paragraph, not a redesign.

The deeper concern — "is the threshold structurally unmeetable, leaving the proposal in limbo?" — is not the failure mode. The failure mode is the opposite: the threshold is structurally *too easy* to meet via the existing fleet's tendency toward self-consistent low-variance complexity reporting, which would cause a premature flip in 4c.

---

## 4. The "substrate is convenience" admission. What stops the 6th-substrate sprawl?

**Nothing in v2.1 stops it. The schema is field-driven and accepts new labels without migration, exactly as the proposal acknowledges. The honest read is that this is a *governance question for the human review process*, not a structural constraint, and the proposal should say so.**

Verifying the claim: `meter.compute_emissions.substrate` has a Postgres CHECK constraint with five values. Adding `gpu_local` requires changing the CHECK constraint, which is a migration — so the schema is *not* purely field-driven; the constraint enforces enum membership. But Pydantic's `Literal[...]` just rejects unknown labels at the API boundary — adding a sixth literal is a one-line PR. So the structural friction for adding `gpu_local` is: one Pydantic literal addition, one DDL migration to alter the CHECK constraint.

That is not zero friction. But it is *less* friction than the proposal's own treatment of the problem suggests. The proposal says "new substrate value requires explicit code review, not a migration" — but actually it requires both, because the CHECK constraint is in Phase 1's DDL.

So we have a small contradiction inside v2.1:
- §Conceptual model: "all fields are nullable; new agent classes get a new label without breaking the schema."
- §Schema: `substrate TEXT NOT NULL CHECK (substrate IN ('llm_api', ..., 'mixed'))`.

The first is true if and only if the second's CHECK is dropped. v2.1 should pick:

- **Option A (true field-driven)**: drop the CHECK constraint. `substrate` becomes free-form text, validated at write-time only by Pydantic (which is expanded by PR). The dashboard partition logic explicitly handles unknown values (probably collapsing them to `mixed` for display). This makes the "convenience, not physics" claim structural.
- **Option B (enum-enforced)**: keep the CHECK. Acknowledge that "new substrate" is a *migration*, not a label addition. Document the criteria for adding one: must be justified by a real new agent class, not a refinement of an existing class. This is what v2.1 nearly says but doesn't quite commit to.

The deeper question prompt 4 raises — "does substrate convenience mean a 6th substrate creates a new pseudo-physics axis?" — has a clear answer: *yes, it would, if the substrate column ends up being read by anything beyond the dashboard partition logic.* The risk vector is exactly the one round 2 identified for `slop_index`: a categorical signal that *correlates* with something (in this case, agent class) gets adopted by a downstream system that treats the categorical as substantive. The mitigation v2.1 *should* adopt is the same shape: substrate is allowed in `meter.*`, never propagated into anything outside `meter.*`. Make this a parametrized contract test, symmetric with the AST test in Layer 2: `governance_core/` and `audit/` have no import path that reads `compute_emissions.substrate`. That closes the sprawl vector at the same kind of CI-enforced boundary the proposal already accepts for Layer 2.

**Verdict on prompt 4**: the admission documents the concession but does not address the propagation risk. The concrete fix is a CI test that bars `substrate` from being read outside `meter.*` and the dashboard module. Without it, every time someone wants to "use substrate as a feature in X" — and X will always have a locally-reasonable rationale — the convenience-becomes-physics slip is one PR away. This is fixable in v2.1, not a v3 issue.

Also: the schema constraint contradiction (CHECK vs "no migration needed") should be resolved in the doc.

---

## 5. What did v2.1 NOT change from v2 that should have?

**Three things:**

**(a) The conceptual model.** The "two meters never combined" → "no cross-substrate combination" rename is the only conceptual shift. The two-meter ontology, the substrate-polymorphic compute model, the universal action model, the audit-only doctrine — all carry over. I think this is *correct*: the conceptual frame from v2 was load-bearing and round 2 didn't fundamentally challenge it. v2.1 hardening rather than re-conceptualizing is right call.

**(b) The "single emission API for both meters" coupling.** Round 2 §1(b) noted: "the firewall is now the only thing keeping the two halves apart, and they share an emission API (`meter_emit`), a schema namespace, an MCP tool, and a code module path." v2.1 did not split these. It strengthened the action meter's policy gating, but the structural coupling — one tool, one namespace, one Pydantic schema module — is unchanged. Given that v2.1 acknowledges actions are more dangerous than compute, the structural coupling means any future refactor that "simplifies" the meter MCP surface (a locally-reasonable PR) can erode the action/compute distinction silently. This is the v2.1 equivalent of v2's role-denial-bolt-can-fall problem: the *structural* protection of the action/compute split is one shared module path. The fix would be `meter_compute_emit` and `meter_action_emit` as distinct tools with distinct Pydantic modules, leaving the cosmetic shared "meter" namespace but separating the API surface. v2.1 chose not to do this. Round 3 thinks it should.

**(c) The Goodhart treatment of within-substrate ratios.** Round 2 §2 raised the harder question: "is `kg_writes_per_dollar` for dispatch-claude itself a Goodhart target?" v2.1 acknowledges within-substrate Goodhart pressure exists ("an LLM-API agent that learns 'high tokens correlates with operator-flagged slop' will compress") but treats the action-meter gating as the structural mitigation. That is misallocated: the action meter gating addresses cross-agent action ranking, not within-substrate compute compression. v2.1 has no specific defense against the LLM-API agent learning to be Haiku-shaped — and the dashboard is *designed to show* `tokens_per_kg_write` per agent, which is exactly the surface where this pressure operates. The proposal should say plainly: "within-substrate ratios are operator-facing diagnostics; we accept that surfacing them creates compression pressure; we do not have a structural mitigation, only the distribution-not-ranking dashboard discipline; if the pressure becomes operationally visible, we revisit." That paragraph doesn't exist in v2.1.

**Verdict on prompt 5**: the unchanged conceptual frame is the right call. Two specific structural decisions from v2 should have been changed in v2.1 and weren't: (i) splitting the meter API surface into compute and action MCP tools, and (ii) explicit treatment of within-substrate Goodhart pressure beyond the action-meter discussion. Neither is a fatal omission. Both would strengthen v2.1.

---

## 6. Is "no cross-substrate combination" still doctrine after Phase 4 calibration?

**Strictly read, no — the calibration view violates it. Loose-read, yes — but the proposal needs to say which reading is the operative one.**

The doctrine: "Across substrates, no combination. The dashboard never aggregates Lumen's `watt_hours_per_kg_write` with dispatch-claude's `dollars_per_kg_write` into a single number."

The Phase 4a metric: "MAE per (agent_id, substrate, 7-day rolling window). Stored in `metrics.series`." Then the demotion threshold is "median per-agent MAE is ≤0.15."

The demotion threshold is *median across agents*. Agents have different substrates. So "median per-agent MAE" is a single scalar computed by combining MAE values that were themselves computed within a substrate, but the median operation reduces them across substrates. That is a cross-substrate reduction.

You can defend this as not-a-violation by saying: "the doctrine forbids combining *units*, not combining *normalized errors*. MAE in quantile space is unitless; combining unitless metrics across substrates is fine." That is a defensible read. But v2.1 doesn't make this distinction. The doctrine paragraph (§Doctrine) and the calibration paragraph (§Phase 4b) sit in the same document without acknowledging the tension.

The proposal needs one sentence in §Doctrine that says: "the prohibition is on combining substrate-specific *units of effort*; substrate-invariant derived quantities (e.g., quantile-MAE, rank-correlations, fractions-of-distribution) may be combined across substrates because they have already been normalized." Without that sentence, the doctrine as stated is internally inconsistent with the calibration plan, and the next person to read v2.1 will either (a) break the doctrine in good faith because the calibration view does, or (b) refuse to ship the calibration view because it violates doctrine.

**Verdict on prompt 6**: the doctrine is internally inconsistent with §Phase 4b as written. The fix is a single clarifying sentence about what "combination" means (units vs normalized derived metrics). Without it, the doctrine self-collapses on its own example.

---

## 7. Phase 4b/4c structure: honesty or scope-shedding?

**Honesty, with a small risk that the boundary creates a no-owner zone.**

The structure: 4a accumulates data, 4b defines the threshold, 4c is "a separate proposal owns the flip." The proposal says: "v2.1 does not write it. v2.1 makes the data exist and defines the threshold that triggers it."

This is the right pattern in principle — and the proposal cites `feedback_design-doc-council-review.md` and `feedback_eisv-bounds-drift.md` as precedent. Both of those entries are real and the precedent is correctly applied. So calling this scope-shedding would be unfair.

But the implementation creates a specific risk: nobody owns the threshold-trip event. The data accumulates in `metrics.series`. The threshold is a number in a doc. There is no automated check, no alert, no Chronicler routine that says "the threshold has been met for the past 30 days; someone needs to write the demotion proposal." Without that, the threshold acts as a low-friction signal that the codebase produces but doesn't surface — exactly the failure mode round 1 critiqued for `slop_index` ("the calibration data sitting in a dashboard nobody promotes to action").

The fix is small: Phase 4b should include a Chronicler probe that reads `metrics.series`, computes the threshold over the 90-day window, and emits a `compute_meter_threshold_eligible` event when it flips eligible (with hysteresis to avoid flapping). That event then surfaces in the dashboard or Discord as "ready for demotion proposal." The probe is a few dozen lines; the proposal already establishes Chronicler as the right owner.

Without this: 4b is a number that exists in a doc, plus data that exists in a table, and the connection between them is "a future contributor will notice and write 4c." In two years that contributor will not have noticed.

**Verdict on prompt 7**: the deferral itself is honest, not scope-shed. The implementation is incomplete: 4b needs a probe-and-event, not just a number-in-a-doc. Cheap to add. Should be added.

---

## 8. Single sharpest weakness of v2.1

**In 18 months, this proposal embarrasses itself when an early-Phase-4 dashboard ships per-substrate `tokens_per_kg_write` panes for the LLM-API agents (dispatch-claude, watcher's local-LLM, vigil's mixed cycles), an operator notices that one agent has 3x the token cost for similar `kg_write` rates, and a contributor writes a one-line PR adding `ORDER BY tokens_per_kg_write DESC` to the per-substrate pane.**

The PR passes:
- AST test (no `governance_core` import).
- Schema separation (query is in dashboard JS).
- Layer 3 startup assertion (it doesn't read meter from the basin, it reads meter from the dashboard).
- Action meter gating (it's compute, not actions; the checklist doesn't apply).
- Dashboard skill convention (per-substrate, not cross-substrate; the doctrine permits it).
- Within-substrate doctrine (it IS within-substrate).

What it does: ranks LLM-API agents by token efficiency. Agent prompts adapt (or their authors do) toward terseness. The action meter remains protected, but the compute meter — which v2.1 treats as the *less* dangerous of the two — has just become a Goodhart input through the within-substrate-ratio path that v2.1 acknowledged but did not structurally constrain.

This is the same structural shape as round 2's "well-meaning GRANT" critique, just translated for v2.1's actual surface. The load-bearing-on-one-bolt has moved: in v2 it was the role denial; in v2.1 it is *the dashboard's distribution-not-ranking discipline*, which is enforced by `unitares-governance:unitares-dashboard` skill convention and code review. That is the single thinnest layer of the v2.1 protection, and it is the one that the proposal's own §Doctrine plus §Phase 4 cheerfully invites traffic across.

The fix: the dashboard skill needs an explicit rubric line — "no agent-level rankings on within-substrate ratios; distributions only" — and this rubric line needs to be a CI-checked artifact (a comment in the dashboard module that a script greps for, similar to the action-meter checklist proposal). Otherwise the only thing standing between v2.1 and a token-efficiency leaderboard is human attention, which is exactly the protection round 1 named as rhetorical.

This is what "sharpest weakness" means in round 3 terms: not a structural impossibility (the protection layers are real), but the layer that *will* be tested by the proposal's own design and that does *not* have CI backing.

---

## 9. The verdict question: build or v3?

**Build. With three small, named follow-ups that should land before Phase 4 ships, and one paragraph that should land before Phase 1 ships.**

The conceptual frame is mature across three rounds. The implementation specifics are credibly closed against the round-2 critique. The honesty about what is and isn't enforced is, on balance, accurate. The concrete data prerequisites are met in this codebase. The cross-repo and resident-emission paths are correctly specified. Phase 1 ships partition functions, three-file tool registration, AgentIdentityMixin inheritance, run_in_executor, schema-qualified queries — all the round-2 code-review findings landed.

A v3 is not warranted. v3 would be a re-conceptualization, and the conceptual frame doesn't need re-conceptualizing — it needs three small structural follow-ups that the v2.1 honesty *invites* but doesn't itself implement. Each is small enough to land as a Phase 1 amendment or a same-PR addition rather than a new proposal:

**Before Phase 1 ships:**
- **Resolve the substrate-as-convenience contradiction** (§4 above): either drop the CHECK constraint or document that "new substrate" requires a migration. The current state — schema enforces enum, doc says it doesn't — is a small lie that will be quoted out of context.
- **Relabel Layer 3** (§1 above): not a layer of the firewall, but a flip-point preparation for Layer 4. Or specify the on-call action when the WARN fires. Either fixes the slip; the current state has Layer 3 doing decoration work the round 2 critique tried to remove.

**Before Phase 4 ships:**
- **The action-meter cross-agent CI grep** (§2 above): turn the PR-template checklist into a 30-line script that fails CI on naive cross-agent action queries. Without this, "stricter gating" is not gating.
- **The within-substrate-ratio dashboard rubric** (§8 above): add a CI-checked line to the dashboard skill that bans agent-level rankings on within-substrate ratios. Without this, the within-substrate Goodhart vector is unprotected.
- **The 4b probe-and-event** (§7 above): Chronicler reads `metrics.series` and emits a threshold-eligible event with hysteresis. Without this, the demotion path is data-without-an-owner.
- **The doctrine clarifying sentence** (§6 above): "the prohibition is on combining substrate-specific units of effort; normalized derived metrics may be combined." Without this, the doctrine self-contradicts on its own calibration plan.
- **A non-degeneracy precondition for the calibration threshold** (§3 above): require complexity stddev > 0.1 within agent before that agent counts. Without this, the threshold flips spuriously on the existing fleet.

Five small additions to v2.1 (or six — the substrate contradiction is two-line). None require re-architecting. None block Phase 0 or Phase 1 if they ship as Phase 4-gated. Each closes a specific load-bearing-on-attention failure mode.

**The verdict**: v2.1 is good enough to build, and the right shape is "build Phase 0+1 now with the two pre-Phase-1 fixes inline; add the four pre-Phase-4 fixes as gating items on the Phase 4 PR." That is faster than a v3 round, gives the proposal real CI-checked enforcement at each layer it claims, and avoids the round-3 honesty-without-structure trap that is the single biggest risk in v2.1 as currently written.

---

## Synthesis across three rounds

- **Round 1** said: receipt is the wrong word; the firewall is rhetorical; phase 2 (per-call check-in receipts) is perversely incentivized.
- **Round 2** said: the firewall has one bolt that doesn't fit this codebase; the action meter is more dangerous than the compute meter; complexity demotion is aspirational.
- **Round 3** says: the conceptual frame is mature, the structural critique is mostly closed, the remaining gap is *honesty without CI backing* — every layer the proposal claims is enforceable should actually have a script or a test backing it. The five small fixes above are the difference between "v2.1 is honest about its limits" and "v2.1 has structural protections matching its honesty."

The progression is healthy. v1→v2→v2.1 is the right shape for a hardened proposal: re-conceptualize, then specify, then close the specifics. The author has visibly engaged each round's critique and the proposal is structurally sounder for it. The remaining work is implementation-level, not design-level.

Build it.

---

## Outstanding questions to carry forward

- The `agent_id UUID NOT NULL` in the meter schema versus `agent_id text` in `audit.outcome_events` — that's a real inconsistency that will bite the Chronicler join in Phase 4. Decide whether agent_id is UUID (and the meter schema is right) or text (and audit is right), and align before Phase 1 ships. Verified in `\d audit.outcome_events`: column is `text`. The meter schema's UUID type will cause join failures.
- The Steward memory entry cleanup is named-as-deferred. If `eisv-sync-task` is the actor and it's Pi-side, then `feedback_check-in-during-long-sessions.md` and `project_eisv-sync-agent-identity.md` should both be updated when this proposal merges, not as a separate task. Memory drift is not free.
- Watcher's role in v2.1 §Risks #5 — "Watcher should be configured to flag any code path that calls `meter.*` from inside a `governance_core` import context" — is a good idea but not specified. If you want Watcher backing for Layer 2, add the pattern to its rule set in this proposal, not in a future one.

These are not blocking. They are the load-bearing details that v2.1 names but does not close.
