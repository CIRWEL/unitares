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
| R3 | Statistical lineage (identity as integral) | None. Partly already present in trust-tier logic. | **Annotation pass landed 2026-04-21** — `src/trajectory_identity.py` audited; classification + migration path in this file's Appendix entry "2026-04-21 — R3: Trust-tier annotation". Math primitives are subject-agnostic; storage + tier computation assume UUID continuity. Migration unblocks S6/S7/S10. |
| R4 | Substrate-earned identity (Lumen's pattern, formalized) | None. Tractable first. | **Draft v1 landed 2026-04-21** as appendix of `docs/ontology/identity.md` ("Pattern — Substrate-Earned Identity"). Three conditions (dedicated substrate, sustained behavior, declared role); test cases (Lumen passes; synthetic fakes fail); open questions on N, envelope width, substrate migration. Open for revision. |
| R5 | Memory-deepening-reality tooling (axiom #14) | R2 (integration must be defined before deepening it) | Three candidate mechanisms prototyped: forced re-derivation, behavioral backtests, self-knowledge reflection. Each has a minimal implementation + one passing test. |

### System implications (descriptive stance)

| ID | Item | Action type | Depends on | Resolved when |
|---|---|---|---|---|
| S1 | `continuity_token` as resume-credential | **Deprecate with grace period** (external user count unknown as of 2026-04-21; treat retirement as deprecation, not hard remove) | None. Scope clear. | Token accepts + emits `deprecated` warning for one release cycle; then repurposes as lineage-declaration credential. Codex plugin + `bind_session` updated. External-client migration note published. |
| S2 | `.unitares/session.json` auto-resume | Retire (Claude Code channel) | S1 | Auto-resume removed from Codex plugin + Claude Code harness hooks. Fresh processes mint fresh identities with declared lineage. |
| S3 | Cross-channel token acceptance | Retire | S1 | Token's `ch` claim enforced; mismatch = force-new with lineage. |
| S4 | Label-as-identifier flows | **Mostly resolved** (2026-04-17 `resolve_by_name_claim` cleanup + 2026-04-21 audit in `audit-notes.md`) | None | Outstanding effective action narrows to S5; remaining sites are cosmetic label-to-UUID translation. Verify no regressions. |
| S5 | `resident_fork_detected` event | **Resolved 2026-04-23** | R4 | Event inverted in `src/mcp_handlers/identity/persistence.py:set_agent_label` — fires only when a persistent-label collision occurs *without* the new agent declaring `parent_agent_id=<existing_uuid>`. Lineage-declared restarts log at INFO with `[RESIDENT_LINEAGE]`; broadcast payload gains `declared_parent` for consumer taxonomy. Signal chosen: declared `parent_agent_id` (the substrate commitment available at onboard time — full `verify_substrate_earned` fails fresh processes on condition 2). Tests in `tests/test_resident_fork_detector.py`. |
| S6 | Trust-tier calculation (`compute_trust_tier`) | **Partially resolved 2026-04-23** — Option B routing + Q2 reseed primitive shipped; onboard-flow wiring follow-up shipped same day | R3 | `resolve_trust_tier` in `src/identity/trust_tier_routing.py` shortcuts substrate-earned agents (R4 three-condition pass) to tier=3; session-like agents continue through `compute_trust_tier` unchanged. Lineage-seeded genesis primitive `seed_genesis_from_parent` in `src/trajectory_identity.py` (Q2); wired into onboard via `_seed_genesis_from_parent_bg` in `src/mcp_handlers/identity/handlers.py`, scheduled alongside `_create_spawned_edge_bg` on both `created_fresh_identity` and `force_new` branches. Remaining: empirically recalibrate session-like thresholds once S8a tag-discipline lands. |
| S7 | KG provenance (`agent_id` stamping) | Audit + shift aggregation | R3 | Queries and aggregations that assume multi-session UUID continuity migrated to role or lineage-chain. Schema audit of `knowledge_graph_postgres.py` and `knowledge_graph.py`. |
| S8 | Orphan archival heuristics (`classify_for_archival`) | **Re-scoped** (2026-04-21 audit in `audit-notes.md` — thresholds are fine; real gap is tag discipline) | None urgent | Split into S8a (tag-discipline audit) + S8b (class-tag backfill). Heuristic thresholds remain as-is. |
| S8a | Tag-discipline audit — 96% of active agents lack class tags | **Resolved 2026-04-23** — findings doc shipped | None | Root cause: only the SDK resident-branch stamps tags via `update_agent_metadata`; onboard defaults to `metadata={}` and no inference fires. See `docs/ontology/s8a-tag-discipline-audit.md` for measurements, write-path trace, and phased recommendation (default-stamp at onboard + later promotion sweep). Operator decisions pending: Phase-1 rule set, `session_like` class addition, Phase-2 timing. |
| S8b | Class-tag backfill on active agents | Data ops | S8a findings | Backfill class tags on active agents where class is inferable (resident-labelled, `Claude_*`-labelled, etc.). |
| S9 | PATH 1/2 anti-hijack machinery | Re-scope or retire | R1 | Under R1, external verification replaces continuity-enforcement. PATH 1/2 flip to lineage-plausibility checks or retire. |
| S10 | Fleet calibration aggregation paths | Shift default unit | R3, S7 | Default aggregation unit shifts from UUID to role. Dashboards + external-consumer contracts updated. |
| S11 | SessionStart / onboard default behavior (the teeth of the ontology) | **Resolved 2026-04-21** | Audit + plugin PR | Landed as `unitares-governance-plugin#17` (commit `743952ab`) — banner inversion, cache becomes lineage-only (schema_version=2, no continuity_token write), S1 deprecation breadcrumb. Audit + duplicate-PR dogfood story in this file's Appendix entries "2026-04-21 — S11" (initial) and "2026-04-21 — S11 execution" (landing + lesson). |

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

- **B1 (R4):** ~~Write `patterns/substrate-earned-identity.md`.~~ **Done 2026-04-21** — landed inline as appendix of `docs/ontology/identity.md` ("Pattern — Substrate-Earned Identity"). Formalizes Lumen's pattern with three conditions, test cases, open questions.
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

### `WIP-PR:` field (parallel-work avoidance)

When a process-instance starts code work on a row, add a `WIP-PR:` line to that row's cell pointing to the open PR (or branch, pre-push). Example:

```
| S8a | Tag-discipline audit — ... | Resolved 2026-04-23 — findings doc shipped | ... |
      WIP-PR: unitares#118 (opened by agent-59e966aa-7b8)
```

Remove the field when the PR merges or closes. Before opening a new PR for any row, dispatcher (human or subagent) runs the pre-flight check in the handoff template below — this is the cure for the S11-execution dogfood where two agents independently wrote the same PR 7 hours apart.

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

### Recommended priority (snapshot 2026-04-23)

S5 and S6-Option-B (plus Q2 `seed_genesis_from_parent` primitive) both shipped this session. The S6 options appendix below is kept for historical reading but its "operator decision needed" framing is superseded — PR #107 picked Option B and landed the Q2 primitive in the same commit. The onboard-flow wiring (Q2 into live call sites) ships separately. Refreshed priority:

1. **S6 follow-up: wire `seed_genesis_from_parent` into onboard** — **Shipped 2026-04-23** as PR #112 (`a8bf5d71`). `_seed_genesis_from_parent_bg` in `src/mcp_handlers/identity/handlers.py:1790` scheduled alongside `_create_spawned_edge_bg` on both fresh-identity and force_new branches.
2. **v7 outline draft** — fresh session in `unitares-paper-v6` repo. Produces a `.tex` skeleton you can read and redirect. Independent of all code work.
3. **Pre-dispatch PR-scan checkpoint** — **Resolved 2026-04-23** as the lighter `WIP-PR:` convention + handoff-template pre-flight (see "How to change this plan" and "Handoff prompt template" below). Docs-only; no enforcement hook. If the convention fails to prevent duplicates in practice, escalate to a dispatch-path hook.
4. **S8a follow-up: Phase-1 default-stamp at onboard** — S8a findings doc shipped (`docs/ontology/s8a-tag-discipline-audit.md`); recommendation is Option 1 (default-stamp at onboard) + partial Option 2 (later promotion sweep). Needs operator sign-off on the Phase-1 rule set and the `session_like` class addition before implementation. Unblocks S6 recalibration and S8b backfill.

After those, re-read this plan and decide whether remaining rows still matter or have been superseded.

### Handoff prompt template

```
Task: [row ID from plan.md, e.g., "S11 synthesized PR execution"]

Authoritative reference:
- docs/ontology/identity.md (ontology v2 + substrate-earned pattern appendix)
- docs/ontology/plan.md (this ledger)
- [any row-specific doc, e.g., docs/ontology/s11-consolidation.md]
all on master in the unitares repo.

Pre-flight (parallel-work avoidance):
1. Read plan.md row for this task — check for existing `WIP-PR:` field.
   If present and not stale (<48h), abort and report the existing PR
   rather than open a duplicate.
2. Run `gh pr list --state open --search "<row ID>"` in the target repo.
   If any open PR references this row ID in title/body/branch, abort and
   report the existing PR.
3. Before pushing a branch, stamp `WIP-PR:` into the plan.md row cell in
   the same commit as the first push (or in a preceding docs-only commit).

Scope: [specific bounds, e.g., "three changes per s11-consolidation.md §4;
ship via ship.sh runtime path for PR + auto-merge"].

Output: [shipped PR URL / shipped docs path / plan.md row update with
status and pointer to artifact]. On merge, remove the `WIP-PR:` field
and update the row's "Resolved when" cell.

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
- `src/mcp_handlers/observability/handlers.py:59-60` and `src/mcp_handlers/observability/handlers.py:171-172` — `observe_agent` target resolution fallback.
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
2. **Workspace cache becomes lineage-only** (in `unitares-governance-plugin`: `hooks/post-identity` + `session_cache.py`). Stop writing `continuity_token`. Write `uuid`, `agent_id`, `updated_at`, `parent_agent_id` only. Version-bump schema; legacy v1 token is ignored on read. Intersects S2 but ship under S11 since S2's prerequisite (S1 external-client grace) applies to server-side emit, not plugin-internal cache.
3. **S1 deprecation breadcrumb** (in `unitares-governance-plugin`: `onboard_helper.py`). One-line comment where `continuity_token` is read: "compatibility surface for external clients; plugin-internal flows should declare lineage." No behavior change — S1 owns the full deprecation window.
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

### 2026-04-21 — R3: Trust-tier annotation

**Scope:** Read `src/trajectory_identity.py` end-to-end against ontology v2; classify each meaningful piece as statistical-lineage compatible, UUID-identity assuming, or mixed; sketch migration path for shifting aggregation unit from UUID to role.

**Functions / sections inspected:**

- `src/trajectory_identity.py:34-73` — `bhattacharyya_similarity`
- `src/trajectory_identity.py:76-116` — `_det`, `_inv` linear-algebra helpers
- `src/trajectory_identity.py:119-172` — `homeostatic_similarity`, `_viability_margin`
- `src/trajectory_identity.py:175-234` — `_dtw_distance`, `_dtw_similarity`, `_eisv_trajectory_similarity`
- `src/trajectory_identity.py:237-373` — `TrajectorySignature` dataclass + `.similarity()` + `.trajectory_shape_similarity()` + `_cosine_similarity`
- `src/trajectory_identity.py:376-449` — `store_genesis_signature`
- `src/trajectory_identity.py:452-583` — `update_current_signature`
- `src/trajectory_identity.py:586-681` — `compute_trust_tier` (the named target)
- `src/trajectory_identity.py:684-725` — `get_trajectory_status`
- `src/trajectory_identity.py:728-800` — `verify_trajectory_identity` (paper §6.1.2 two-tier)

**Classification:**

| Site | Category | Notes |
|---|---|---|
| `bhattacharyya_similarity`, `_det`, `_inv` | Statistical-lineage compatible | Pure math on two distributions. Subject-agnostic. Survives any aggregation regrouping. |
| `homeostatic_similarity`, `_viability_margin` | Statistical-lineage compatible | Pure math. Compares two `eta` dicts; doesn't care whose. |
| `_dtw_*`, `_eisv_trajectory_similarity` | Statistical-lineage compatible | DTW on two EISV trajectories; subject-agnostic. Already shaped like a "is this trajectory consistent with that fingerprint" primitive — exactly what R1 (`verify_lineage_claim`) needs. |
| `TrajectorySignature` dataclass + `.similarity()` + `.trajectory_shape_similarity()` | Statistical-lineage compatible | Pairwise comparison of two signatures, no UUID dependency. The paper's six-component model lives here; it operates on signature-pairs, not on subject-identity. This is the load-bearing primitive that survives ontology migration intact. |
| `compute_trust_tier` (pure function) | **Mixed** | Takes a single `metadata` dict, reads `trajectory_genesis` + `trajectory_current` + prior `trust_tier` from it, returns tier. The math (compare current to genesis, threshold on observation_count + confidence + lineage similarity) is subject-agnostic *if* genesis and current are both honest signatures of the same subject. The function itself doesn't reach across UUIDs — it's its **input** (`metadata`, scoped to one `agent_id`) that bakes in the UUID assumption. Re-key the input and the function survives. |
| `compute_trust_tier` thresholds (200 obs / 50 obs) | UUID-assumes | The thresholds were calibrated against a world where one UUID = one long-lived subject. Under v2, most process-instances die before accumulating 50 observations, let alone 200. The numbers are honest only for substrate-earned cases (Lumen) or for role-aggregated input. Already flagged in identity.md §"Implications" — "window norms change since most process-instances will never accumulate 200+ observations." |
| `store_genesis_signature` | UUID-assumes | Σ₀ is keyed by `agent_id` and gated by per-UUID immutability rules (immutable at tier ≥ 2; reseed allowed at tier ≤ 1). Under v2, "this agent_id's genesis" conflates substrate-anchored agents (where Σ₀ is honest across restarts) with session-like agents (where Σ₀ should be the *role's* historical fingerprint, not this process-instance's first 10 samples). The reseed-when-lineage-low logic at lines 416-426 is a partial admission that genesis-by-UUID isn't quite right. |
| `update_current_signature` | UUID-assumes | Writes per-UUID `trajectory_current` + computes lineage vs. that UUID's stored Σ₀. Anomaly detection ("trajectory drift") fires when one UUID's behavior diverges from its own past — meaningful for substrate-earned agents, but for session-like agents under one role, a "drift" event may just be a fresh process-instance whose behavior is closer to another sibling under the role than to its own ten-sample genesis. The drift-event broadcast at lines 524-545 will be noisy in the role-aggregated world. |
| `verify_trajectory_identity` (paper §6.1.2 two-tier) | UUID-assumes | This is the canonical "behavioral-continuity-by-UUID-match" case identity.md §"Performative" calls out by name. Submitted signature is verified against `metadata[trajectory_genesis]` and `metadata[trajectory_current]` keyed by `agent_id`. Under v2, the same verification against role-aggregated norms would be more honest; the math (comparing two signatures) is unchanged, only the reference distribution changes. |
| `get_trajectory_status` | UUID-assumes (read-only) | Read-side mirror of `update_current_signature`. Same caveat. Cosmetic to migrate. |

**Mixed / unclear:** `compute_trust_tier` is the only genuinely mixed case — its body is honest math but its input shape encodes the UUID assumption. The function is small and simple; the load-bearing decision is upstream (what gets put in `metadata`).

**Migration path (UUID → role aggregation):**

1. **Math survives unchanged.** All six similarity primitives (Bhattacharyya, DTW, cosine, homeostatic, recovery-tau, valence-L1) are pairwise on signatures. Re-keying the storage layer doesn't touch them.
2. **Storage layer is the migration surface.** `store_genesis_signature` and `update_current_signature` currently write `metadata.trajectory_genesis` and `metadata.trajectory_current` on the agent record (UUID-keyed). Migration: introduce a parallel role-keyed store (`role_trajectory[role].genesis`, `role_trajectory[role].current_distribution`) where "current" is a distribution over recent process-instances under the role rather than one process's snapshot. Per-agent storage stays — substrate-earned agents (Lumen) keep using it; session-like agents read from the role pool.
3. **`compute_trust_tier` gets a second input mode.** Today: `compute_trust_tier(metadata)`. Tomorrow: `compute_trust_tier(metadata, role_baseline=None)` where `role_baseline` (when provided) replaces or augments the per-UUID genesis. Logic stays — thresholds compare current sig to *some* baseline. Identity of the baseline-source is the open call.
4. **Threshold recalibration is independent of the keying change.** 200 obs / 50 obs were chosen for long-lived subjects. Even under role-aggregation, the right thresholds depend on per-role data (how fast does a typical role accumulate 50 honest observations across its process-instances?). Empirical work, blocked on tag-discipline (see S8a) — without class tags, role-aggregated calibration has no clean partition.
5. **Anomaly semantics flip.** Under UUID-keying, "drift" = this subject changed. Under role-keying, "drift" = this subject's behavior left the role's envelope (fresh-process atypicality), which is a different signal entirely. The `trajectory_drift` audit event at line 528 needs its taxonomy revisited; today it implies a single subject changed, tomorrow it might mean "this process-instance is an outlier under its declared role" — those are not the same incident.
6. **Substrate-earned escape hatch.** Per R4 (substrate-earned identity pattern), agents passing the three conditions keep UUID-keyed trust-tier semantics intact. Migration needs a routing decision at the input layer: substrate-earned → per-UUID metadata path (current); session-like → role-baseline path (new). The `embodied` / `persistent` / `ephemeral` class tags are the routing key — tag-discipline gap (S8a) is the precondition for this routing to work in production.

**What breaks:** `verify_trajectory_identity` callers currently get a per-UUID verdict; under role-aggregation they'd get an under-role verdict, semantically distinct. Drift event consumers (audit + dashboard broadcast) would need to re-interpret incident type. Genesis immutability rules at tier ≥ 2 stop making sense for session-like agents — there's no "this UUID's first signature" in the role-aggregated world; the equivalent is "this role's accumulated distribution," which is by construction not immutable.

**What stays the same:** All six similarity primitives. The `TrajectorySignature` dataclass. The hysteresis margins in `compute_trust_tier`. The threshold *shape* (count + confidence + lineage triple-gate), only the numbers and the input source change.

**Action — what S6 actually needs to do:**

1. **Don't rewrite `compute_trust_tier`.** It's small, pure, honest within its scope. The work is at the storage and routing layers.
2. **Add a role-baseline storage path** in `store_genesis_signature` / `update_current_signature` — write role-aggregated EISV distributions in parallel with per-UUID metadata. Schema-add, not schema-change.
3. **Add a routing layer** at handler entry (where these functions are called from MCP) that picks per-UUID vs. role-baseline based on class tag — substrate-earned routes to per-UUID; session-like routes to role-baseline. Default to per-UUID (current behavior) when class tag is absent — preserves backward compatibility during the S8a/S8b tag-discipline rollout.
4. **Recalibrate thresholds per-class** once tag-discipline is in place. Substrate-earned thresholds can stay near 200/50; session-like thresholds drop to whatever number reflects "enough observations under this role to trust the fingerprint" — empirically derived, not chosen.
5. **Re-taxonomize `trajectory_drift`** into two events: `subject_drift` (per-UUID, current semantics, fires for substrate-earned agents only) and `role_outlier` (per-role, fires when a process-instance under a role exhibits behavior far from the role's distribution). Audit consumers and dashboard updated. Inverts cleanly with S5's `resident_fork_detected` flip.
6. **Document `verify_trajectory_identity` as substrate-earned-only** in its docstring until role-aggregated alternative is built. Today it can't honestly verify a session-like agent's identity because there's no honest baseline.

S6 as scoped above is consistent with identity.md §"Implications" — "Re-interpret (not re-derive)" — and consistent with the "math survives within a process lifetime; window norms change" framing. No new math. No deletion. Additive routing + recalibration. Substrate-earned agents get a separate calibration pool (per R4), which the routing layer makes structural rather than ad-hoc.

**Callers of `compute_trust_tier`** (all UUID-aggregated read-side sites):

| Site | File:line | Role |
|---|---|---|
| Update enrichment — tier + risk adjust | `src/mcp_handlers/updates/enrichments.py:729-773` | Recomputes tier post-signature, stamps `meta.trust_tier`, adjusts current update's `risk_score` ±0.05 / ±0.15 by tier and drift flag |
| Batch tier load | `src/agent_metadata_persistence.py:173-192` | Fleet metadata load: batch-fetches identities, populates `meta.trust_tier_num` per record |
| Lifecycle query | `src/mcp_handlers/lifecycle/query.py:413-433` | Backfills missing `trust_tier` when listing agents |
| Identity status endpoint | `src/mcp_handlers/identity/handlers.py:1713-1717` | `get_trajectory_status` response decoration |

**KG provenance — `agent_id` stamping and aggregation** (S7's territory; tightly coupled to R3):

| Site | File:line | Class |
|---|---|---|
| `DiscoveryNode.agent_id` | `src/knowledge_graph.py:81` | UUID-aggregated stamp; load-bearing for attribution |
| `DiscoveryNode.provenance_chain` | `src/knowledge_graph.py:97-99` | Mixed — exists, role-friendly, but underused (open question 5) |
| PG `kg_add_discovery` / `query` / `get_stats(by_agent)` / `get_agent_discoveries` | `src/storage/knowledge_graph_postgres.py:56-208` | UUID-aggregated; `total_agents` stat = "distinct process-instances that authored this epoch", not "total agents" under v2 |
| AGE backend mirror + rate limiter | `src/storage/knowledge_graph_age.py:937-1006` | UUID-aggregated; rate-limit-by-UUID means a churning role gets `N x budget` writes (feature or leak — open question 4) |

**Fleet-level aggregation** (S10's territory):

| Site | File:line | Class |
|---|---|---|
| `handle_aggregate_metrics` | `src/mcp_handlers/observability/handlers.py:671-771` | **Already statistical** — UUID is iteration key, not aggregation key; mean/count over observations is identity-agnostic in spirit |
| `calibrate_class_conditional.py` | `scripts/calibrate_class_conditional.py:90-134` | **Already statistical and role-aware** — groups by `classify_from_db_row(label, tags)`; integral-over-role semantics R3 calls for |
| `classify_agent` | `src/grounding/class_indicator.py` | Role-aware primitive; class tags map to known residents + ephemeral/persistent/embodied/default |
| `get_recent_cross_agent_activity` | `src/db/mixins/state.py:120-148` | UUID-aggregated (`GROUP BY i.agent_id`) |
| `SequentialCalibrationTracker` | `src/sequential_calibration.py:104` and `:204-252` | Mixed — `global_state` (statistical) parallel to `agent_states[agent_id]` (UUID-aggregated); callers choose |

**Audit machinery** (UUID-aggregated at stamp time): `audit_log.log_*(agent_id=...)` across `src/audit_log.py:20-170`; `trajectory_drift` event at `src/trajectory_identity.py:527-543`; `identity_assurance_change` broadcast at `src/trajectory_identity.py:561-574`.

**Open questions for S6/S7/S10 owner:**

1. **Substrate-earned: class-arg or parallel path?** `compute_trust_tier` could take a `calibration_class` argument and branch internally, or substrate-earned could bypass `compute_trust_tier` entirely (tier=3 by R4's three-condition check). Latter is cleaner; requires a parallel "substrate-earned path" alongside the per-UUID metadata path.
2. **Reseed ceiling.** `store_genesis_signature` already has a partial-admission patch (lines 416-426): reseed when lineage drops. A principled extension: "at tier ≤ 1 with declared parent, seed genesis from parent's `trajectory_current`." Module-scope win that may obviate the heavier role-aggregation lift.
3. **`observation_count >= 200` as substrate-earned-only.** Under v2, this threshold is unreachable for session-like agents. If we keep it, tier 3 ("verified") becomes substrate-earned-only by accident — intentional? Maybe yes (consistent with R4); if so, name it.
4. **AGE rate limiter — feature or leak?** Per-UUID budget means churning roles exceed the limit `N` times. Intended elasticity or a hole.
5. **`provenance_chain` is dormant.** Field exists, is serialized, is role-friendly. Few writers populate it. Is this the cheapest place to start role-aware write-stamping, or is there a reason it's underused.

**Unblocking table:**

| Row | Unblocked? | What remains |
|---|---|---|
| **S6** (`compute_trust_tier` re-interpret) | Yes, partially | (a) operator answer to question 1 above, (b) empirical window-size for `default` class (likely from S8 archival data) |
| **S7** (KG provenance audit) | Yes, largely | (a) lineage-chain column schema decision, (b) `total_agents` stat semantics migration |
| **S10** (fleet aggregation paths) | Partially | (a) dashboard + external-consumer contract reshape, (b) coordination with R4 (substrate-earned visible as N=1 classes); still blocked on S7 for KG slice |

**Re-scope observation:** R3's bulk is at the storage layer (KG stamping/query/stats — S7 territory) and audit (G section above). The trust-tier function itself is small. **R3 and S7 are tightly coupled** in a way the dependency graph treats as one-directional. A joint pass may be more coherent than sequential. The pure-trust-tier slice (B-tier item 3 above) can ship module-scope without S7/S10, but consumers will want KG primitives migrated soon after.


### 2026-04-21 — S11 execution: landing + duplicate-PR lesson

**Landed:** `unitares-governance-plugin#17` merged 2026-04-21 23:55 UTC as squash commit `743952ab`. Implements all four S11 spec items per the prior appendix entry (banner inversion citing identity.md; lineage-only cache write with `schema_version: 2`; S1 deprecation comment in `onboard_helper.py`). Author: Codex auto-shipped via plugin's `ship.sh` runtime path.

**Dogfood lesson:** an independent agent (Claude Code subagent dispatched 7+ hours after #17 was opened) wrote the same PR from scratch as #18, file-for-file overlap on the same six files. Both PRs converged on the same banner posture (force_new lead, bare UUID surface for `parent_agent_id` declaration). #18 was closed in favor of #17 (smaller diff, earlier author, equivalent ontological outcome).

**The pattern that was not prevented.** S11's audit was scoped to consolidate the 5 prior parallel WIP branches that triggered this row. The execution session then **spawned a 6th parallel attempt** without first running `gh pr list --state open` to scan for in-flight work. The audit identified the symptom (multiple agents independently reaching for the same problem with no cross-visibility) but did not produce a code-level cure (no pre-dispatch PR-scan checkpoint).

**Followup candidate (not committed):** a small pre-dispatch hook for parallel-work avoidance — when an agent is about to open a PR, scan open PRs in the same repo for matching scope tags and require explicit acknowledgment before proceeding. Lighter alternative: the plan.md row format gains a `WIP-PR:` field that owner-of-row updates when work is in flight, and the dispatcher (Claude/Codex subagent) is instructed to grep for that field before opening a new PR. Either way, the durable fix lives in the dispatcher's pre-flight, not in operator vigilance.

### 2026-04-23 — S5 shipped: resident-fork inversion

**Landed:** `src/mcp_handlers/identity/persistence.py:set_agent_label` + `tests/test_resident_fork_detector.py` on master via this session's ship. Under ontology v2, a resident restart (Watcher, Sentinel, Vigil, Steward, Lumen) is the expected case and should declare `parent_agent_id=<existing_uuid>` at onboard. The event now fires only when that declaration is missing or points elsewhere; lineage-declared restarts log at INFO (`[RESIDENT_LINEAGE]`) and rename silently. Broadcast payload gains `declared_parent` so dashboard/Discord consumers can distinguish unlineaged forks from lineage-mismatch cases.

**Signal choice.** The full R4 `verify_substrate_earned` predicate (three conditions: dedicated substrate, sustained behavior, declared role) was considered but rejected as the inversion signal — condition 2 (observation_count ≥ N=5) is structurally false for a fresh process. The substrate commitment available at onboard time is the lineage declaration itself; R4's full check is for *post-facto* earned-identity verification, not restart admission. Documented in the S5 row.

**What this does not do.** No change to the *existing* agent's tagging or tier. No change to ephemeral-collision path. `resident_fork_detected` event name unchanged (payload additive). Downstream consumers (dashboard, Discord bridge) receive the same event shape plus one new field — no breaking change.

### 2026-04-23 — S6 options: substrate-earned routing

> **Superseded 2026-04-23.** PR #107 picked Option B and shipped the Q2 reseed primitive (`seed_genesis_from_parent`) in the same commit. Onboard-flow wiring for the primitive followed the same day. Appendix retained for historical reading of the A/B tradeoffs; no decision is outstanding.

**Context:** The open question from the 2026-04-21 R3 appendix ("Q1: substrate-earned as class-arg or parallel path?") needs an operator decision before S6 implementation. This appendix lays out both options with tradeoffs; decision unblocks the R3-appendix "Action — what S6 actually needs to do" work.

**The choice.** `compute_trust_tier(metadata)` today takes one metadata dict (per-UUID) and returns a tier. Under v2, substrate-earned agents (Lumen and eventually verified residents) have honest per-UUID semantics; session-like agents need role-aggregated baselines. Two ways to route:

**Option A — class-arg branch inside `compute_trust_tier`.**

- Signature becomes `compute_trust_tier(metadata, *, calibration_class=None, role_baseline=None)`.
- When `calibration_class == "substrate_earned"` or class tag is `embodied`: run current per-UUID logic against `metadata["trajectory_genesis"]`.
- When `calibration_class == "session_like"` or class tag is `ephemeral`/absent: compare `metadata["trajectory_current"]` against `role_baseline` (role-aggregated distribution).
- Thresholds parameterize per class — substrate-earned keeps 200/50, session-like uses empirically-derived numbers (blocked on S8a).

Pros:
- Single entry point. All four callers (`enrichments.py:729`, `agent_metadata_persistence.py:173`, `lifecycle/query.py:413`, `identity/handlers.py:1713`) stay on one function. Routing decision is internal.
- Small blast radius. Existing callers that don't pass `calibration_class` get current behavior (backward-compat default).
- Migration is in-place — no new functions to wire up.

Cons:
- Conflates two different questions inside one function: "has this subject behaved consistently?" (per-UUID) and "does this process-instance fit its role's envelope?" (role-aggregated). The math is similar but the interpretation differs — keeping them inside one function masks the semantic split.
- `metadata` parameter carries two different meanings depending on class. Callers that get it wrong silently pick the wrong path.
- Threshold table balloons — per-class tuples inside the function, hard to audit.

**Option B — parallel path; substrate-earned bypasses `compute_trust_tier`.**

- New function: `tier_from_substrate_earned(verify_result) -> int`. Takes the `verify_substrate_earned()` dict, returns tier=3 when `earned=True`, tier=2 when two-of-three conditions met, tier ≤ 1 otherwise.
- `compute_trust_tier` keeps its current body but gets documented as "session-like / per-UUID path"; its callers pick which path based on class tag.
- Routing layer at handler entry (the four call sites) — cheap dispatch: class tag `embodied` → substrate path; otherwise → existing `compute_trust_tier`.

Pros:
- Semantic split is structural. Two paths, two stories. Readers can't confuse them.
- R4's three-condition check becomes the *source of truth* for substrate-earned tier — no duplication with `trajectory_current` heuristics. Matches the R4 spec direction.
- Session-like recalibration (blocked on S8a) is isolated to one function. Substrate-earned agents get tier=3 immediately once tagged; no empirical threshold work required for them.
- Future retirement of UUID-keyed trust-tier logic (when role-aggregation is fleet-wide) leaves the substrate-earned path intact — it was never UUID-keyed in spirit.

Cons:
- Four call sites need the routing decision. Each caller grows a branch.
- Two functions to maintain — divergence risk if the trust-tier semantics drift.
- `tier_from_substrate_earned` has its own ramp-up: need to decide what 2/3 conditions earns (tier 2? tier 1? refuse?).

**Tradeoff.** Option A is faster to ship and has smaller call-site churn. Option B matches the ontology's semantic split and makes the R4 pattern the authoritative path for substrate-earned agents. The R3 appendix's Q1 framing ("Latter is cleaner; requires a parallel substrate-earned path alongside the per-UUID metadata path") leans B.

**Secondary question (regardless of A vs B).** Reseed ceiling from the R3 appendix Q2 — "at tier ≤ 1 with declared parent, seed genesis from parent's `trajectory_current`" — is a module-scope win that may obviate part of the heavier role-aggregation lift. Worth implementing independently of the A/B call; can ship in the same PR as whichever path wins, or before.

**Recommendation.** B, with Q2's reseed as part of the same ship. B aligns with the R4 spec direction, isolates the empirical-threshold work (S8a-blocked) to the session-like function alone, and matches how `verify_substrate_earned` was designed (predicate-first, not metadata-augmenter). The call-site churn is four branches — small enough. Substrate-earned `tier_from_substrate_earned` starts with `earned → tier 3; otherwise → fall through to compute_trust_tier` (skip the 2/3-conditions question initially; defer until we see real counterexamples).

**Operator decision needed.** A or B (or a third framing). Once picked, fresh session can implement per the R3 appendix's "Action — what S6 actually needs to do" list, scoped to the chosen path.
