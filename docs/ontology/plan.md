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
| S4 | Label-as-identifier flows | **Mostly resolved** (2026-04-17 `resolve_by_name_claim` cleanup + 2026-04-21 audit in `audit-notes.md`) | None | Outstanding effective action narrows to S5; remaining sites are cosmetic label-to-UUID translation. Verify no regressions. |
| S5 | `resident_fork_detected` event | Invert | R4 (needs substrate-earned pattern) | Event fires when a resident restart lacks declared lineage, not when it has one. |
| S6 | Trust-tier calculation (`compute_trust_tier`) | Re-interpret + calibration-window adjustment | R3 | Window norms adjusted for typical process-instance lifetime. Substrate-anchored agents (Lumen) use separate calibration pool per R4. |
| S7 | KG provenance (`agent_id` stamping) | Audit + shift aggregation | R3 | Queries and aggregations that assume multi-session UUID continuity migrated to role or lineage-chain. Schema audit of `knowledge_graph_postgres.py` and `knowledge_graph.py`. |
| S8 | Orphan archival heuristics (`classify_for_archival`) | **Re-scoped** (2026-04-21 audit in `audit-notes.md` — thresholds are fine; real gap is tag discipline) | None urgent | Split into S8a (tag-discipline audit) + S8b (class-tag backfill). Heuristic thresholds remain as-is. |
| S8a | Tag-discipline audit — 96% of active agents lack class tags | Audit | None | Understand why onboard flow isn't stamping class tags (pipeline broken? Agents not declaring? Something else?). Produces findings doc. |
| S8b | Class-tag backfill on active agents | Data ops | S8a findings | Backfill class tags on active agents where class is inferable (resident-labelled, `Claude_*`-labelled, etc.). |
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

---

## Appendix: Audit notes

Running log of descriptive-stance findings. Inventories and measurements only — no code changes, no commitments.

### 2026-04-21 — A2: Label-as-identifier inventory (S4)

**Scope:** Grep for code paths that resolve agents by label rather than UUID; classify each by whether load-bearing (identity-conferring) or cosmetic (UX lookup).

**Live call sites** (post-2026-04-17 `resolve_by_name_claim` cleanup):

- `src/db/base.py:224` + `src/db/mixins/agent.py:158` — `find_agent_by_label(label) -> Optional[str]`. DB primitive.
- `src/mcp_handlers/identity/persistence.py:257` — `_find_agent_by_label` handler wrapper. Re-exported from `identity/{handlers,resolution,core}.py`.
- `src/mcp_handlers/observability/handlers.py:59-60,171-172` — `observe_agent` target resolution fallback.
- `src/mcp_handlers/identity/persistence.py:463` — resident-fork detection (`structured_agent_id` collision check).
- `structured_agent_id` usages across 4 files / 8 sites: `identity_payloads.py`, `runtime_queries.py`, `agent_auth.py`, `identity/handlers.py`.

**Classification:**

| Site | Role | Classification |
|---|---|---|
| `find_agent_by_label` (DB + mixin + handler wrapper) | Primitive label → UUID translation | Cosmetic. Callers treat the returned UUID as identity. |
| `observe_agent` target resolution | Accepts label or UUID for "which agent" argument | Cosmetic. UX sugar; internals operate on UUIDs. |
| Resident-fork detection (`persistence.py:463`) | "Two agents with same label ⇒ fork" | **Load-bearing + performative.** Locus of S5 inversion. |
| `structured_agent_id` surfacings (payloads, queries) | Label carried through response layers | Mostly cosmetic; `agent_auth.py` flagged for B-track closer read. |

**Summary:** 4 of 5 active sites are cosmetic. Single load-bearing performative site is resident-fork detection, already scoped as S5. S4 downgraded; effective outstanding action is S5 alone.

### 2026-04-21 — A3: Orphan archival data check (S8)

**Scope:** Inspect `classify_for_archival` thresholds against production distribution; decide whether thresholds fit the new ontology's norm of many short-lived process-instances.

**Heuristic** (`src/agent_lifecycle.py:100-136`): `low_update_hours=3`, `unlabeled_hours=6`, `ephemeral_hours=6`, `ephemeral_max_updates=5`. Initializing agents (0 updates) never auto-archived.

**Production state (2026-04-21):**

| | Active | Archived |
|---|---|---|
| Total | 169 | 2761 |
| Persistent-tagged | 6 | — |
| Ephemeral-tagged | 0 | — |
| Embodied-tagged | 1 | — |
| Unclassified | 163 | 2761 |

Lifetime — unclassified archived avg 761hr (~32d, max 3449hr/~144d); unclassified active avg 273hr (~11d); persistent active avg 408hr (~17d).

Labels (active): 155 "other", 7 null, 5 residents (Lumen/Vigil/Sentinel/Watcher/Steward), 2 `Claude_*`.

Lineage: 81/169 active agents (48%) have `parent_agent_id`. Archived-rate 0.3% (pre-lineage-era agents).

**Observations:**

1. **Tag discipline is poor** — 96% of active agents lack class tags, despite paper §4 framework. The real gap.
2. **Lineage plumbing is actively used** — 48% of fresh agents declaring parent. Healthy.
3. **Archive aggressiveness matches new-ontology expectation** — 94% archival rate aligns with ephemeral-by-construction process-instances.
4. **Substrate-anchored agents underrepresented in calibration pool** — with only 1 `embodied`-tagged agent, Lumen's EISV norms are being averaged out.

**Action:** Thresholds remain. Real gap is tag discipline — see S8a/S8b.

