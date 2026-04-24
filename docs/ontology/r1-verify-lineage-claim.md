# R1 — `verify_lineage_claim` design spike

**Status:** Design doc. No implementation commitment.
**Scope:** Plan row R1 (`docs/ontology/plan.md`). Produces: signature, confidence model, threshold analysis, implementation sketch, synthetic-data test fixture.
**Author:** agent `8ae8cb4b-23d2-4b21-9906-b9993b4293d0` (claude_code), 2026-04-24.

---

## Purpose

Under the v2 ontology, a fresh process-instance declaring `parent_agent_id=<uuid>` is making a *claim*, not a fact. The claim is credible only if the successor's observable behavior is consistent with the parent's behavioral fingerprint. `verify_lineage_claim` is the governance-side primitive that turns a claim into a probability — "this successor is behaving like a continuation of that parent, to confidence `c`."

This is the earning mechanism referenced in `identity.md` axiom §Behavioral-continuity verification. It replaces "continuity by token" with "continuity by behavior."

## Non-goals

- Does not authenticate (auth is still bearer-token + process-fingerprint).
- Does not issue identity; it produces a confidence score. The policy layer decides what to do with the score.
- Not a substitute for substrate-earned identity (R4): that pattern has its own three-condition test.

## Input signature

```python
def verify_lineage_claim(
    claimed_parent_id: str,
    successor_id: str,
    *,
    min_observations: int = 5,
    window: timedelta = timedelta(days=30),
) -> LineageVerdict:
    ...

@dataclass
class LineageVerdict:
    confidence: float                  # [0.0, 1.0]
    verdict: Literal["consistent", "inconclusive", "inconsistent"]
    observations: int                  # successor check-ins used
    components: Dict[str, float]       # per-channel similarities
    reasons: List[str]                 # human-readable drivers
    parent_mature: bool                # parent had enough history to fingerprint
```

The caller supplies UUIDs; the function pulls both agents' histories from existing storage (`agent_states`, `recent_decisions` via `AgentBaseline`, `TrajectorySignature` if cached). No new per-agent state needs to be persisted — all inputs are already being collected by existing check-in machinery.

## Confidence model

Five channels, each produces a similarity in `[0, 1]`. Weighted average yields `confidence`.

| Channel | Signal | Measure | Weight |
|---|---|---|---|
| C1 Trajectory shape | E, I, S, V time-series | DTW similarity via existing `_dtw_similarity` | 0.30 |
| C2 Homeostatic set-point | Mean/var of EISV in steady state | Bhattacharyya similarity (`bhattacharyya_similarity`) | 0.25 |
| C3 Calibration curve | Confidence vs outcome (from `auto_ground_truth`) | Jensen-Shannon distance → similarity | 0.15 |
| C4 Decision distribution | `recent_decisions` histogram (proceed/guide/pause/reject) | Cosine similarity on normalized counts | 0.15 |
| C5 Complexity distribution | `complexity` values at check-in | Bhattacharyya on fitted Gaussian | 0.15 |

**Rationale for these five:** each channel is already measured, each is reasonably independent (low mutual information in production data per v7-fhat spike), and each captures a different aspect of "how this agent operates" rather than "what this agent contains." Content signals (KG writes, response text) are intentionally excluded — they correlate with task, not agent.

Channels with insufficient data on either side degrade gracefully (weight redistributed; `components` entry set to `None`; listed in `reasons`).

## Confidence → verdict thresholds

Calibrated against synthetic data first, re-tuned against production once corpus matures.

| Condition | Verdict |
|---|---|
| `observations < min_observations` OR `parent_mature == False` | `inconclusive` |
| `confidence >= 0.75` | `consistent` |
| `0.40 <= confidence < 0.75` | `inconclusive` |
| `confidence < 0.40` | `inconsistent` |

The `inconclusive` band is wide on purpose: this primitive should rarely declare a lineage false. False-negatives cost trust; false-positives cost nothing (the claim just doesn't upgrade to confirmed).

## Implementation sketch

- **Location:** `src/identity/lineage_verification.py` (new). Imports similarity primitives from `src/trajectory_identity.py` (already subject-agnostic per R3 annotation).
- **Storage reads:** `agent_states` history (window-scoped), `AgentBaseline` for decisions + complexity, `auto_ground_truth` for calibration, `TrajectorySignature` if cached. All via existing async helpers; no schema changes.
- **Dispatch pattern:** read-only, so follows the `run_in_executor` + sync DB pattern (anyio-asyncio gotcha — see CLAUDE.md).
- **Exposure:** initial consumers are policy code only (not an MCP tool yet). An `mcp_handlers/identity/verify_lineage` wrapper can come later if external callers need it.
- **Observability:** emits a KG discovery of type `lineage_verification` with `confidence`, `verdict`, `components` — matches existing audit pattern.

## Test fixture (synthetic data)

`tests/test_lineage_verification_synthetic.py`:

1. **Genuine continuation.** Generate parent trajectory (100 check-ins, trend toward high basin, stable decision mix). Generate successor (20 check-ins) by continuing the same generator's state. Expect `verdict=consistent`, `confidence >= 0.75`.
2. **Forged (different generator).** Parent as above. Successor from an independent generator with different set-point and decision distribution. Expect `verdict=inconsistent`, `confidence < 0.40`.
3. **Early-stage successor.** Parent as above. Successor with 3 check-ins (< `min_observations`). Expect `verdict=inconclusive`, `observations=3`.
4. **Drifted-but-same.** Parent stable. Successor starts from same state but trajectory drifts over 20 check-ins. Expect `verdict=inconclusive` (in the wide band) — this is the gray zone on purpose.
5. **Immature parent.** Parent with 4 check-ins, successor genuine. Expect `verdict=inconclusive`, `parent_mature=False`.

Synthetic data generators live in `tests/fixtures/synthetic_trajectories.py` (new). The fixture is deterministic (seeded) so thresholds can be regression-tested.

## Threshold analysis — what calibration looks like

Thresholds above are initial; the correct values are empirical. Calibration path:

1. Ship the primitive with synthetic-only calibration (thresholds from fixture-tuning).
2. Run in shadow-mode on production: verify lineage claims already declared via `parent_agent_id`, but don't enforce anything. Log `confidence` distribution per declared-lineage pair.
3. After ≥ 2 weeks of shadow data, inspect:
   - Distribution for `spawn_reason=new_session` (expected genuine) — should cluster above 0.75.
   - Distribution for `spawn_reason=subagent` (Q2 — this is the bit that's "principled or pragmatic?") — hypothesis: bimodal, depending on subagent scope.
   - Any outliers in either direction become test cases.
4. Adjust thresholds if shadow data shows clear mis-calibration; re-tune weights only if a channel shows no discriminative power.

## Dependency map

```
R1 ── unblocks ──> R2 (honest memory integration)
               └── Q2 (subagents — shadow-mode gives the "N observations" number)
               └── S9 (PATH 1/2 re-scoping — verification replaces continuity-enforcement)
               └── R5 eventually (via R2)
```

## Definition of done for this row

Plan row R1 is resolved when:
- This document exists with the five sections (signature / confidence / thresholds / sketch / fixture). ✓
- The operator has accepted it, rejected it, or flagged for revision.
- A subsequent implementation-spike row is opened (or R1 is re-scoped).

This document does **not** commit to shipping the implementation. Implementation is a separate decision; this row only produces the spec.

## Open questions for Kenny

1. **Channel weights.** 0.30 / 0.25 / 0.15 / 0.15 / 0.15 are defensible-but-arbitrary. Accept as "seed weights, re-tune after shadow-mode data," or demand better motivation before shipping?
2. **Shadow-mode corpus size.** 2 weeks is a guess; might be too short given current fleet size. Happy to pace on the same "corpus maturity" gate blocking v7 empirical work?
3. **MCP exposure.** Ship as internal-only first, or is there a near-term external consumer (Discord bridge? dashboard?) that needs the tool surface earlier?

## Appendix: what this does NOT solve

- **Cross-channel impersonation.** If an adversary has read access to the parent's state history, they can plausibly replay it. Defense is bearer-token + process-fingerprint (bind_session); lineage verification is about honest claims, not adversarial ones. Worth being explicit about in the §Threat model follow-up doc.
- **Trajectory portability (Q1).** `verify_lineage_claim` measures *similarity*; it does not answer whether similarity + integration = identity. That's Q1's job, downstream of R2.
- **Substrate-earned identity (R4).** Lumen's pattern has a stronger test (three-condition pass); don't route substrate-earned agents through this primitive — use `verify_substrate_earned` instead.
