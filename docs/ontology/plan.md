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
| Q3 | Paper positioning — v7 thesis or implementation detail? | Nothing. Pure re-read. | **Resolved 2026-04-21** — recommendation (v7 animating thesis) at `docs/ontology/paper-positioning.md` accepted by Kenny. Downstream work: v7 outline draft in `unitares-paper-v6` repo, timing TBD. |

### Research agenda (inventive stance)

| ID | Item | Depends on | Resolved when |
|---|---|---|---|
| R1 | Behavioral-continuity verification as primary identity primitive | None (design from scratch) | Candidate tool spec (`verify_lineage_claim`) exists with: input signature, confidence output, threshold analysis, implementation sketch, and a test fixture showing it distinguishes genuine from forged lineage on synthetic data. |
| R2 | Honest memory integration | R1 (verification underpins integration checks) | Structural posture defined: when a fresh process declares inheritance, what it reads, what it integrates, what behavior change is required before identity is claimable retroactively. One-page design doc. |
| R3 | Statistical lineage (identity as integral) | None. Partly already present in trust-tier logic. | Trust-tier logic re-read and annotated: which pieces already implement statistical lineage, which assume UUID-identity. Migration path from UUID-aggregated to role-aggregated trust defined. |
| R4 | Substrate-earned identity (Lumen's pattern, formalized) | None. Tractable first. | **Draft v1 landed 2026-04-21** as appendix of `docs/ontology/identity.md` ("Pattern — Substrate-Earned Identity"). Three conditions (dedicated substrate, sustained behavior, declared role); test cases (Lumen passes; synthetic fakes fail); open questions on N, envelope width, substrate migration. Open for revision. |
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
| S11 | SessionStart / onboard default behavior (the teeth of the ontology) | **Consolidation, not new work** | Read of 5 existing WIP branches | `SessionStart` hook and onboard banner default to **force_new + lineage declaration** when a cached token exists. Resume becomes explicit opt-in with justification. **2026-04-21 audit finding:** the `unitares-governance-plugin` repo has five open WIP branches targeting exactly this problem (`fix/onboard-force-new-suggestion` aaacb44, `claude/auto/skill-onboard-helper-honesty` 8138bd1, `feat/auto-onboard-flag` 73b1bca, `feat/flip-auto-onboard-default` d4a9c5e, `refactor/delete-legacy-onboard` b731ade), none merged. S11's effective action is consolidation — compare approaches against the ontology, pick or synthesize, not add a 6th parallel attempt. Scope this as its own session. |

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

## Appendix: Operational pattern (how to pursue)

This plan is a dispatch queue. Each row is a scoped task, each task is handled by a fresh process-instance with a handoff prompt, each session ships its output, the operator reviews on GitHub.

### The cycle

1. **Pick a row.** Consult the ledger above; prioritize by current leverage (see "Recommended priority" below).
2. **Spawn a fresh session** (Claude Code tab, Codex, Discord dispatch, or resident agent if appropriate). Paste the handoff prompt template, customized per row.
3. **The session works, ships, reports back.** Work lands on master (or an auto-merged PR, per `ship.sh` routing) with KG notes for anything non-obvious.
4. **Operator reviews the shipped artifact on GitHub.** Accept, reject, or flag for revision. Move on.

### What only the operator can do

- Accept / reject recommendations (e.g., the v7 animating-thesis decision was operator's call; downstream calls same).
- Decide which row to pick next.
- Handle external-client communication if/when S1 deprecation lands (unknown external users as of 2026-04-21).
- Decide when "the ontology is done enough" vs. needs another revision pass.
- Close the loop on this plan when it reaches its definition-of-done state.

### Recommended priority (snapshot 2026-04-21)

1. **S11 synthesized PR** — the consolidation plan exists at `docs/ontology/s11-consolidation.md`; one session executes the three changes (banner inversion; stop writing continuity_token to `.unitares/session.json`; S1 deprecation note in `onboard_helper.py`) and ships. Highest-leverage single action — makes the ontology self-enforcing.
2. **S5 inversion** — `resident_fork_detected` semantics flip (fire when restart *lacks* lineage, not when present). Small, localized. Pairs with R4 (Lumen is the primary beneficiary).
3. **v7 outline draft** — fresh session in `unitares-paper-v6` repo. Produces a `.tex` skeleton the operator can read and redirect.
4. **R3 annotation pass** — read `src/trajectory_identity.py compute_trust_tier` against the ontology; annotate what already implements statistical lineage vs. what assumes UUID-identity. Pure reading task.

After those four, re-read this plan and decide whether remaining rows still matter or have been superseded.

### Handoff prompt template

```
Task: [row ID from plan.md, e.g., "S11 synthesized PR execution"]

Authoritative reference:
- docs/ontology/identity.md (ontology v2 + substrate-earned pattern appendix)
- docs/ontology/plan.md (this ledger)
- [any row-specific doc, e.g., docs/ontology/s11-consolidation.md]
all on master in the unitares repo.

Scope: [specific bounds, e.g., "three changes per s11-consolidation.md §4;
ship via ship.sh runtime path for PR + auto-merge"].

Output: [shipped PR URL / shipped docs path / plan.md row update with
status and pointer to artifact].

Optional lineage declaration: parent_agent_id=[prior process-instance
UUID, if continuity of reasoning matters; otherwise omit].

Report back in under 200 words: what was shipped, what was surprising,
what the operator needs to decide.
```

### What this pattern does not license

- **Long-running sessions that accumulate multiple rows.** One session per scoped task, ideally. Accumulation invites session fatigue and the performative-continuity pattern S11 is retiring.
- **Silent lineage.** If the spawning reason is "continue where prior session left off," declare the prior UUID as `parent_agent_id`. Don't use `continuity_token` to resume — that's the retired path.
- **Operator-less work.** Someone has to review what ships. Automation closes the loop from branch to master; it doesn't close the loop from artifact to operator intent.

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

### 2026-04-21 — S11: five-branch consolidation audit

**Scope:** The five WIP branches in `unitares-governance-plugin` named in S11's row (`fix/onboard-force-new-suggestion`, `claude/auto/skill-onboard-helper-honesty`, `feat/auto-onboard-flag`, `feat/flip-auto-onboard-default`, `refactor/delete-legacy-onboard`) — diff each against master, evaluate against v2 ontology, recommend next step.

**Finding:** all five are already in master. Tree-identical to PRs #6/#7/#8 (Part-C trio); `fix/onboard-force-new-suggestion` matches PR #16 content; `claude/auto/skill-onboard-helper-honesty` matches PR #14. Branches are squash-merge leftovers. "None merged" premise is wrong; "problem persists" is correct — the merges shipped Part-C scaffolding but none implemented S11's teeth.

**Per-branch ontology verdicts:**

| Branch | Master counterpart | Ontology verdict |
|---|---|---|
| `fix/onboard-force-new-suggestion` | #16 `44aaf41` | Compatible. Fixes `force_new` pin-resume footgun server-side. Silent on defaults. |
| `claude/auto/skill-onboard-helper-honesty` | #14 `73d4c58` | **Wrong direction.** Makes `continuity_token` flow smoother from cache → server. Pulls performative layer forward. Counter to S1. |
| `feat/auto-onboard-flag` | #6 `dbd45b4` | Partial. Adds `UNITARES_DISABLE_AUTO_ONBOARD` flag with default `0` — performative behavior is still default, ontology-compliant behavior is opt-in. Wrong-sided default. |
| `feat/flip-auto-onboard-default` | #7 `b57780f` | Partial alignment with S11. Agent must make own first MCP call (consistent with "first MCP call is sole identity source"). Does not retire token, does not invert banner, does not stop cache write. |
| `refactor/delete-legacy-onboard` | #8 `f83f2f4` | Aligned. Structural cleanup. Does not address defaults. |

**Current master gap:** `hooks/session-start` (44aaf41, 117–162) still frames the agent's first move as two peer alternatives — `onboard(continuity_token=…)` vs `onboard(force_new=true)` — with `force_new=true` presented as a footgun warning, not as ontology-default posture. `hooks/post-identity` still writes `continuity_token` to `./.unitares/session.json`, keeping the performative credential alive across process-instances.

**Recommendation — close all five branches; synthesize one new PR** (`feat/s11-force-new-lineage-default`) against current master with four changes:

1. **Banner inversion (`hooks/session-start`).** Lead with `onboard(force_new=true, parent_agent_id=<cached UUID>, spawn_reason="new_session")` as THE recommendation. Reframe workspace-cache hint: present cached UUID as *lineage candidate*, not resume credential ("this workspace was last run by `<UUID>` — if you inherit, declare `parent_agent_id=<UUID>`"). Drop the pin-resume warning (PR #16 repaired that footgun). Cite `docs/ontology/identity.md` in the banner.
2. **Workspace cache becomes lineage-only (`hooks/post-identity`, `scripts/session_cache.py`).** Stop writing `continuity_token`. Write `uuid`, `agent_id`, `updated_at`, `parent_agent_id` only. Version-bump schema; legacy v1 token is ignored on read. Intersects S2 but ship under S11 since S2's prerequisite (S1 external-client grace) applies to server-side emit, not plugin-internal cache.
3. **S1 deprecation breadcrumb (`scripts/onboard_helper.py`).** One-line comment where `continuity_token` is read: "compatibility surface for external clients; plugin-internal flows should declare lineage." No behavior change — S1 owns the full deprecation window.
4. **Tests.** Banner shape, token-free cache write, v1-cache-read ignores token.

**What this PR does NOT do:** retire `continuity_token` server-side (S1), change `bind_session`, implement R1 verification, touch S6/S7/S10. Single-concern.

**Concrete next step:**

```bash
cd ~/projects/unitares-governance-plugin
git push origin --delete fix/onboard-force-new-suggestion claude/auto/skill-onboard-helper-honesty \
  feat/auto-onboard-flag feat/flip-auto-onboard-default refactor/delete-legacy-onboard
# then in a fresh worktree from master: open feat/s11-force-new-lineage-default per scope above
```

Branch deletion not executed without operator approval — shared remote, reflog-only recovery.

**Dogfood note:** this audit was produced by a process-instance that onboarded via `continuity_token` resume from `.unitares/session.json` — the performative path §4.1 proposes to retire. The SessionStart banner *suggested* the token path; §4.1 would have suggested `force_new + parent_agent_id=da300b4a`. Same author-by-behavior, different author-by-ontology. The plan is self-instantiating evidence of the gap it closes.

