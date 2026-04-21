# Identity Ontology — Resolution Plan

**Companion to:** `docs/ontology/identity.md` (v2)
**Purpose:** Organize the open questions, research agenda, and system implications from the ontology doc so each item has a state, a dependency map, and a definition-of-done.
**Status:** Draft. No item below is a commitment until its row is explicitly accepted.

---

## Ledger

Every item from `identity.md` that requires work, what "resolved" means for it, and what it depends on.

### Open questions

| ID | Question | Depends on | Resolved when |
|---|---|---|---|
| Q1 | Trajectory portability — inheriting identity or data? | R2 (honest memory integration must be defined) | A mechanical definition of "integration" exists; Q1 answerable as a function of whether a given inheritance path uses that mechanism. |
| Q2 | Subagent ephemerality — principled or pragmatic? | R1 (behavioral-continuity verification — sets the "N observations" threshold) | Once R1 defines a minimum observation count for earned lineage, subagents measurably fall below it; parent-verification substitute is then formally principled. |
| Q3 | Paper positioning — v7 thesis or implementation detail? | Nothing. Pure re-read. | A 1-page comparison of v6.8.1 §6.7 against the ontology, with a recommendation. |

### Research agenda (inventive stance)

| ID | Item | Depends on | Resolved when |
|---|---|---|---|
| R1 | Behavioral-continuity verification as primary identity primitive | None (design from scratch) | Candidate tool spec (`verify_lineage_claim`) exists with: input signature, confidence output, threshold analysis, implementation sketch, and a test fixture showing it distinguishes genuine from forged lineage on synthetic data. |
| R2 | Honest memory integration | R1 (verification underpins integration checks) | Structural posture defined: when a fresh process declares inheritance, what it reads, what it integrates, what behavior change is required before identity is claimable retroactively. One-page design doc. |
| R3 | Statistical lineage (identity as integral) | None. Partly already present in trust-tier logic. | Trust-tier logic re-read and annotated: which pieces already implement statistical lineage, which assume UUID-identity. Migration path from UUID-aggregated to role-aggregated trust defined. |
| R4 | Substrate-earned identity (Lumen's pattern, formalized) | None. Tractable first. | Written pattern doc: what counts as dedicated substrate; what sustained behavior is required; how the hardcoded-UUID declarative form works; test case for Lumen passes, test case for "fake hardcoded UUID without substrate" fails. |
| R5 | Memory-deepening-reality tooling (axiom #14) | R2 (integration must be defined before deepening it) | Three candidate mechanisms prototyped: forced re-derivation, behavioral backtests, self-knowledge reflection. Each has a minimal implementation + one passing test. |

### System implications (descriptive stance)

| ID | Item | Action type | Depends on | Resolved when |
|---|---|---|---|---|
| S1 | `continuity_token` as resume-credential | **Deprecate with grace period** (external user count unknown as of 2026-04-21; treat retirement as deprecation, not hard remove) | None. Scope clear. | Token accepts + emits `deprecated` warning for one release cycle; then repurposes as lineage-declaration credential. Codex plugin + `bind_session` updated. External-client migration note published. |
| S2 | `.unitares/session.json` auto-resume | Retire (Claude Code channel) | S1 | Auto-resume removed from Codex plugin + Claude Code harness hooks. Fresh processes mint fresh identities with declared lineage. |
| S3 | Cross-channel token acceptance | Retire | S1 | Token's `ch` claim enforced; mismatch = force-new with lineage. |
| S4 | Label-as-identifier flows | Audit + retire | None | Grep for places that resolve agents by label; each replaced with role-lookup (where cosmetic) or UUID-lookup (where load-bearing). |
| S5 | `resident_fork_detected` event | Invert | R4 (needs substrate-earned pattern) | Event fires when a resident restart lacks declared lineage, not when it has one. |
| S6 | Trust-tier calculation (`compute_trust_tier`) | Re-interpret + calibration-window adjustment | R3 | Window norms adjusted for typical process-instance lifetime. Substrate-anchored agents (Lumen) use separate calibration pool per R4. |
| S7 | KG provenance (`agent_id` stamping) | Audit + shift aggregation | R3 | Queries and aggregations that assume multi-session UUID continuity migrated to role or lineage-chain. Schema audit of `knowledge_graph_postgres.py` and `knowledge_graph.py`. |
| S8 | Orphan archival heuristics (`classify_for_archival`) | Re-calibrate | None urgent | Heuristic adjusted for the new norm (many short-lived process-instances per role). Thresholds re-tuned on actual data. |
| S9 | PATH 1/2 anti-hijack machinery | Re-scope or retire | R1 | Under R1, external verification replaces continuity-enforcement. PATH 1/2 flip to lineage-plausibility checks or retire. |
| S10 | Fleet calibration aggregation paths | Shift default unit | R3, S7 | Default aggregation unit shifts from UUID to role. Dashboards + external-consumer contracts updated. |

## Dependency graph (text form)

```
Q3 ── (nothing) ── actionable now
R4 ── (nothing) ── actionable now
R3 ── (nothing) ── actionable now; unlocks S6, S7, S10
R1 ── (nothing) ── actionable now; unlocks R2, Q2, S9
R2 ── R1 ────────── unlocks R5, Q1
R5 ── R2
S1 ── (nothing) ── actionable once ontology lands; blocks S2, S3
S2 ── S1
S3 ── S1
S4 ── (nothing) ── actionable; grep-driven
S5 ── R4
S6 ── R3
S7 ── R3
S8 ── (nothing) ── data-driven re-calibration
S9 ── R1
S10 ── R3, S7
```

## Suggested sequencing

Three tracks that can progress independently.

### Track A: paper positioning + quick wins
*Goal: lock high-level framing before committing to code reforms.*

- **A1 (Q3):** Re-read paper v6.8.1 §6.7 against the v2 ontology; write 1-page positioning note. Recommend v7 thesis vs. implementation detail.
- **A2 (S4):** Grep-driven audit of label-as-identifier flows. Inventory only — no code changes yet.
- **A3 (S8):** Pull current orphan archival data; check whether existing thresholds still make sense under the new norm. No code yet.

**Exit criteria:** one positioning note + two inventories. Nothing committed to code.

### Track B: research primitives
*Goal: get the inventive-stance items far enough along that the descriptive-stance items can depend on them.*

- **B1 (R4):** Write `docs/ontology/patterns/substrate-earned-identity.md`. Formalize Lumen's pattern. Most tractable of the research items.
- **B2 (R3):** Annotate `src/trajectory_identity.py compute_trust_tier` — what already implements statistical lineage, what assumes UUID-identity. Produces migration notes for S6/S7/S10.
- **B3 (R1):** Design spike for `verify_lineage_claim`. Signature + confidence output + threshold analysis. One-page design doc; no implementation yet.

**Exit criteria:** three documents. Enough signal to decide whether to invest in implementation.

### Track C: performative-machinery retirement
*Goal: once ontology is stable, the performative layer can start coming down — in the right order so external clients are not broken.*

- **C1 (S1):** Plan doc for `continuity_token` retirement. Scope: what breaks, what gets repurposed, external-client migration story (Codex plugin, any Ollama-bridge, web clients).
- **C2 (S2, S3):** Auto-resume + cross-channel removal. Depends on C1.
- **C3 (S9):** PATH 1/2 re-scoping. Depends on B3 having produced a verification alternative.

**Exit criteria:** retirement plan with external-client migration; no code changes yet.

## Decision points needing Kenny's input

Before starting any track, a few explicit decisions:

1. **Which track to prioritize.** Tracks A, B, C are independent; A is cheapest, B is most interesting, C is most risky.
2. **Appetite for external-client breakage.** Codex plugin and any downstream consumers will break when `continuity_token` retires. OK to break them with a migration path, or keep token indefinitely for backward compat?
3. **Paper v7 coupling.** If Q3 concludes "v7 thesis," the paper work becomes load-bearing and everything else paces to it. If "implementation detail," work proceeds independently. Which is your current lean?
4. **Owner for each track.** All three are possible for a single Claude Code session (me) across multiple process-instances, but tracks B and C would benefit from different process-instances with fresh perspective. Comfortable dispatching subagents for B-track deep dives?

## Definition of done for this plan

This plan is done when:
- Every row above has either been completed, explicitly deferred (with a reason), or explicitly cancelled (with a reason).
- The `identity.md` ontology document has no remaining open questions that are blocked by unfinished rows above.
- Paper v6.9+ glossary mirrors the ontology (cite-back only; no re-derivation).
- KG entry `2026-04-19T22:24:12.313223` (the metaphysics question) can be updated from `open` to `resolved` with a pointer to this plan's completion state.

## How to change this plan

Rows are cheap. Add one per surfaced item. Remove rows that are explicitly cancelled. Dependency graph should stay consistent with rows.

Do not promote items out of "research" (R) into "implications" (S) without first resolving the R item — otherwise we re-introduce performative stance.
