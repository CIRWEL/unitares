# R1 — `score_behavioral_continuity` design spike

**Status:** Design doc, revision pass 2.
**Scope:** Plan row R1 (`docs/ontology/plan.md`). Produces: signature, plausibility model, threshold analysis, implementation sketch, synthetic-data test fixture.
**Author:** agent `8ae8cb4b-23d2-4b21-9906-b9993b4293d0` (claude_code), 2026-04-24.
**Revision history:**
- v1 (2026-04-24 morning) — one-shot draft; five-channel model, verification framing.
- **v2 (2026-04-24 afternoon) — current.** Rewritten after dialectic + code review. Renamed primitive (`verify_lineage_claim` → `score_behavioral_continuity`). Channels reduced 5 → 2 after code review found C3/C4/C5 not implementable from current storage. Security-gate framing dropped. Independence claim retracted. R2/Q1 unblock claim downgraded to "similarity gate for R2."

---

## Purpose

Under the v2 ontology, a fresh process-instance declaring `parent_agent_id=<uuid>` is making a *claim*, not a fact. The claim is credible only if the successor's observable behavior is consistent with the parent's behavioral fingerprint. `score_behavioral_continuity` is the governance-side primitive that turns a claim into a *plausibility score* — "this successor behaves consistently with that parent, to score `p`."

This is the earning mechanism referenced in `identity.md` axiom §Behavioral-continuity verification.

## Non-goals (explicit)

- **Not authentication.** Auth remains bearer-token + process-fingerprint.
- **Not a security primitive.** An adversary with KG read access can forge a passing trajectory. This primitive detects *honest over-claims*, not adversarial ones.
- **Not an identity issuer.** Output is a plausibility score; policy decides what to do with it.
- **Not a substitute for R4.** Substrate-earned agents (Lumen pattern) use `verify_substrate_earned` — the three-condition test is stronger than what this primitive offers.
- **Not an integration test.** Similarity ≠ integration. Distinguishing integration from replay is R5's job.

## Input signature

```python
def score_behavioral_continuity(
    claimed_parent_id: str,
    successor_id: str,
    *,
    min_observations: int = 5,
    window: timedelta = timedelta(days=30),
) -> LineageContinuityScore:
    ...

@dataclass
class LineageContinuityScore:
    plausibility: float                # [0.0, 1.0]
    verdict: Literal["plausible", "inconclusive", "unsupported"]
    observations: int                  # successor check-ins used
    components: Dict[str, float]       # per-channel similarities
    channels_available: List[str]      # which channels actually had data
    channels_deferred: List[str]       # which were deferred (e.g. C3/C4/C5)
    reasons: List[str]                 # human-readable drivers
    parent_mature: bool                # parent had enough history
```

The caller supplies UUIDs; the function pulls both agents' histories from `agent_states` and cached `TrajectorySignature`. No schema changes.

## Channels — what ships, what defers

The v1 draft claimed five channels. Code review found three of them not implementable from current storage. v2 ships with two, honestly scoped.

### Ships

| Channel | Signal | Measure | Notes |
|---|---|---|---|
| **C1 Trajectory shape** | EISV time-series from `agent_states`, windowed | Per-dimension `_dtw_similarity` (E/I/S/V) averaged | Pure DTW. Existing primitive at `src/trajectory_identity.py:198`, subject-agnostic. |
| **C2 Homeostatic composite** | EISV set-point + recovery profile | `homeostatic_similarity(h1, h2)` at `src/trajectory_identity.py:119` | **Composite, not pure Bhattacharyya.** Wraps Bhattacharyya + recovery-tau + viability-margin. v1 mischaracterized this as a single-measure channel. |

### Deferred (named openly in output so callers can see what didn't run)

| Channel | Why deferred |
|---|---|
| **C3 Calibration curve** | `calibration_checker` is a global aggregate (`src/calibration.py`) with no per-agent partitioning. Requires new per-agent calibration storage — same "per-agent calibration state" channel named in plan.md S12 as an unblock for FEP work. |
| **C4 Decision distribution** | `AgentBaseline.recent_decisions` is capped at 20 entries and lives in-memory only (see `governance_core/ethical_drift.py:397`, LRU-bounded on `chore/fold-unitares-core`). No persistent 30-day decision log exists. Requires new decision-log storage. |
| **C5 Complexity distribution** | `baseline_complexity` is a single EMA scalar, not a sample set. Also, Gaussian on bounded [0,1] is the wrong distributional choice — codebase convention is Bhattacharyya with fitted covariance (C2's approach). Requires persistent complexity samples + Beta or covariance-fit machinery. |

**Deferral policy:** C3/C4/C5 do not ship until the underlying storage + measurement infrastructure does. They should come back through a separate row once that infrastructure matures — same pacing as v7 corpus-maturity work, not R1 scope.

## Independence — what v1 got wrong

v1 asserted "low mutual information in production data per v7-fhat spike" as justification for a weighted average. This was a citation error in the wrong direction: v7-fhat Session 1b SC2 (r=0.9949, recorded in plan.md S12) is evidence that the minimal generative model under v5 channel geometry *collapses* the state channels to a monotone transform of one latent — i.e., the channels are **not** independent.

v2 posture:
- **No weights beyond equal.** C1 and C2 both ship at 0.5 weight. This is not a claim of equal importance; it is a refusal to pretend we have the MI estimates that would justify anything else.
- **Pairwise-MI estimation is a prerequisite before any non-equal weights ship.** That analysis (C1 vs C2 on shadow-mode production data) is part of the threshold-calibration path below, not a separate row.
- **When C3/C4/C5 return**, they return with their own MI measurements against the existing channels or they don't ship.

## Plausibility → verdict thresholds

Starting point, narrow inconclusive band (callers need to decide something):

| Condition | Verdict |
|---|---|
| `observations < min_observations` OR `parent_mature == False` | `inconclusive` |
| `plausibility >= 0.70` | `plausible` |
| `0.55 <= plausibility < 0.70` | `inconclusive` |
| `plausibility < 0.55` | `unsupported` |

**Caller policy is the hard part, not the band width.** The dialectic review surfaced that a wide `inconclusive` collapses to `plausible` in practice unless callers have an explicit policy that differs from the plausible branch. v2 expects callers to define one of two postures per call-site:

- **"Inconclusive blocks":** require re-evaluation later; do not upgrade the lineage claim.
- **"Inconclusive allows with mark":** proceed, but stamp the lineage record with `provisional` so downstream consumers know.

The primitive itself does not choose.

## Implementation sketch

- **Location:** `src/identity/lineage_verification.py` (new). File name preserves searchability even though the primitive is renamed.
- **Dispatch pattern:** `run_in_executor` with sync DB client, per the project's anyio-asyncio contract (CLAUDE.md, Known Issue section). v1 incorrectly framed "read-only" as exempt — it is not. The function reads `agent_states` via async asyncpg elsewhere in the codebase, but a new caller should match `verify_agent_ownership` at `src/agent_loop_detection.py:374`.
- **Storage reads:** `agent_states` history (windowed) + `TrajectorySignature` cache. Both already populated by existing check-in machinery. No schema changes, no new background tasks.
- **Exposure:** internal policy consumers only in v2. No MCP tool wrapper unless a named external caller needs one.
- **Observability:** emits a KG discovery of type `lineage_continuity_score` with `plausibility`, `verdict`, `components`, and `channels_deferred`. The deferred-channels list is visible in the audit record so reviewers can see what didn't run.

## Test fixture (synthetic data)

`tests/test_lineage_continuity_synthetic.py`:

1. **Genuine continuation.** Parent trajectory 100 check-ins, steady high-basin. Successor 20 check-ins continuing same generator. Expect `verdict=plausible`, `plausibility >= 0.70`, `channels_available=[C1, C2]`.
2. **Divergent generator.** Parent as above. Successor from independent generator with different set-point. Expect `verdict=unsupported`, `plausibility < 0.55`.
3. **Early-stage successor.** Parent as above. Successor with 3 check-ins. Expect `verdict=inconclusive`, `observations=3`, `parent_mature=True`.
4. **Drifted-but-same.** Parent stable. Successor starts from same state; drifts over 20 check-ins. Expect `verdict=inconclusive` (the policy-decision zone).
5. **Immature parent.** Parent with 4 check-ins. Expect `verdict=inconclusive`, `parent_mature=False`.
6. **Channel degradation.** Parent has full history; successor has C1 but `TrajectorySignature` cache miss. Expect `verdict` based on C1 alone, `channels_available=[C1]`, `components={"C2": None}`.

Synthetic generators in `tests/fixtures/synthetic_trajectories.py` (new). Deterministic seeds; thresholds are regression-tested against this fixture.

## Threshold-calibration path

1. Ship synthetic-tuned thresholds (above).
2. **Shadow-mode on production:** score every declared-lineage pair; log but do not enforce. Run ≥ 2 weeks or until `N_claims ≥ 100` pairs, whichever is later. Paces with v7 corpus-maturity work.
3. **Measure pairwise MI** between C1 and C2 on shadow-mode data. If MI is high, weights stay equal (no information in weight differentiation). If MI is low, an operator can re-tune with the evidence.
4. **Inspect distributions** by `spawn_reason`: `new_session` (expected genuine), `subagent` (Q2 hypothesis: bimodal), `compaction` (unknown).
5. Adjust thresholds only if shadow data shows clear mis-calibration.

## Dependency map (revised)

```
R1 ── provides similarity gate for ── R2 (integration test; R5 discriminates integration from replay)
R1 ── provides similarity gate for ── R5
R1 ── does NOT unblock ─────────────── Q1 (trajectory portability — stuck until R5)
R1 ── does NOT unblock ─────────────── Q2 (subagent ephemerality — shadow-mode data may inform, but does not resolve)
R1 ── does NOT unblock ─────────────── S9 (PATH 1/2 — R1 is an honesty primitive, not a verification primitive; S9 needs the adversarial-grade thing that R1 explicitly is not)
```

v1 claimed R1 unblocked R2/R5/Q1/S9. Dialectic review correctly flagged this as overreach. v2 carries the narrower claim.

## Definition of done for this row

Plan row R1 resolved when:
- This spec exists with signature / channels / thresholds / sketch / fixture. ✓
- Operator accepts, rejects, or flags for revision.
- A subsequent implementation-spike row is opened (or R1 is re-scoped).

## Open questions for Kenny

1. **Ship v2 (two-channel) as R1's answer, or hold R1 open until C3/C4/C5 storage lands?** v2 shipping early gives the shadow-mode data that retroactively justifies infrastructure for C3/C4/C5. Holding gives one larger spec later. Dialectic was silent; code review implied "ship what works."
2. **Caller policy for `inconclusive`.** Who defines it — each call-site, or a global default in the primitive's wrapper? v2 punts; v3 shouldn't.
3. **Naming.** `score_behavioral_continuity` is precise but long. `continuity_score(parent, successor)` reads better; losing "behavioral" concedes ground the ontology cares about. Preference?

## Appendix: what this does NOT solve

- **Adversarial forgery.** KG-readable parent state enables trajectory synthesis. Defense remains bearer-token + process-fingerprint. This primitive is an honesty primitive, not a security one.
- **Trajectory portability (Q1).** R1 measures similarity; Q1 asks whether similarity-plus-integration = identity. R5 discriminates integration from replay. R1 is necessary but insufficient for either.
- **Substrate-earned identity (R4).** Use `verify_substrate_earned` (three-condition test). Substrate-earned agents should not be routed through this primitive.
- **Per-agent calibration (C3), decision log (C4), complexity distribution (C5).** Deferred until storage exists. These are named channels, not hidden ones — consumers can see what didn't run via `channels_deferred`.

## Appendix: review provenance

- v1 dialectic review (agent `a98256ccd566598cd`, `dialectic-knowledge-architect`, 2026-04-24): surfaced independence-citation error, content-exclusion tension, Potemkin-verifier risk, R2/Q1 unblock overclaim, inconclusive-band policy vs. technical question.
- v1 code review (agent `ae3eec7695eafae26`, `feature-dev:code-reviewer`, 2026-04-24): C3 per-agent calibration not available; C4 has no 30-day log; C5 has no sample set; `homeostatic_similarity` is composite not pure; anyio framing backwards.

Both reviews drove this revision.
