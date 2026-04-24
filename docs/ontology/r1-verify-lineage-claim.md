# R1 — `score_trajectory_continuity` design spike

**Status:** Design doc, revision pass 3.
**Scope:** Plan row R1 (`docs/ontology/plan.md`). Produces: signature, plausibility model, implementation sketch including the series-reconstruction helper, and test-fixture plan.
**Author:** agent `8ae8cb4b-23d2-4b21-9906-b9993b4293d0` (claude_code), 2026-04-24.
**Revision history:**
- v1 (2026-04-24 morning) — one-shot draft; five-channel model, `verify_lineage_claim` naming. Dismissed as not implementable and carrying security-gate framing.
- v2 (2026-04-24 afternoon) — two-channel reduction (C1 trajectory DTW + C2 homeostatic composite); renamed `score_behavioral_continuity`. Reviewed by second council; council found the C1/C2 channels were themselves gated on agents explicitly uploading `TrajectorySignature.attractor` — both unavailable on the standard `process_agent_update` path. v2 also smuggled in a recursive-weight inconsistency (C2's internal 0.4/0.3/0.3 weights exempted from the "no weights until MI" rule applied at the outer level).
- v3 (2026-04-24 evening). Single-channel spec. Renamed `score_behavioral_continuity` → `score_trajectory_continuity` to match what the primitive actually measures. C1 retained via a new server-side helper that reconstructs per-dimension EISV series from `agent_states` rows — no agent-side cooperation required. C2/C3/C4/C5 all deferred with named prerequisites. No weighting question remains (one channel). Thresholds explicitly tagged "seeded, not earned; shadow-mode-calibrate before enforcement."
- **v3.1 (2026-04-24 late) — current.** Third council pass. Dialectic found no forcing issues (dynamics-confound noted but below primitive's resolution; `plausibility` at API boundary already scoped honestly — dialectic's own recommendation: stop iterating, let next signal come from shadow-mode data or downstream adoption). Code review found three factual errors in the implementation sketch — corrected below. No scope changes.

---

## Purpose

A fresh process-instance declaring `parent_agent_id=<uuid>` is making a *claim*, not a fact. `score_trajectory_continuity` scores how well the successor's observed EISV trajectory matches the parent's, giving a plausibility in `[0, 1]`.

This is a **single-channel primitive** that measures one thing: trajectory-shape similarity. It is not a behavioral fingerprint. It is not a five-dimensional agent identity gate. It is a narrow, implementable first step toward behavioral-continuity verification (ontology axiom, `identity.md`).

The broader "multi-channel agent fingerprint" that v1 reached for is not this row. It is a sequence of follow-up rows, each gated on the infrastructure it requires.

## Non-goals (explicit)

- **Not authentication.** Auth remains bearer-token + process-fingerprint.
- **Not a security primitive.** An adversary with KG read access can forge a passing trajectory. This primitive detects *honest over-claims*.
- **Not an identity issuer.** Output is a plausibility score; policy decides what to do with it.
- **Not a substitute for R4.** Substrate-earned agents use `verify_substrate_earned`.
- **Not an integration test.** Similarity ≠ integration. R5 discriminates integration from replay.
- **Not a behavioral fingerprint.** Trajectory shape is one facet of behavior. Calling this primitive "behavioral continuity" overclaims — v3 renames accordingly.

## Input signature

```python
def score_trajectory_continuity(
    claimed_parent_id: str,
    successor_id: str,
    *,
    min_observations: int = 5,
    window: timedelta = timedelta(days=30),
) -> TrajectoryContinuityScore:
    ...

@dataclass
class TrajectoryContinuityScore:
    plausibility: float                   # [0.0, 1.0], average of per-dimension DTW similarities
    verdict: Literal["plausible", "inconclusive", "unsupported"]
    observations: Dict[str, int]          # checkpoints used per dimension (parent, successor)
    components: Dict[str, float]          # {"E": 0.82, "I": 0.71, ...} — per-dimension similarity
    reasons: List[str]                    # human-readable drivers
    parent_mature: bool                   # parent had ≥ min_observations history in window
```

## The one channel

**C1 — Per-dimension EISV trajectory similarity.**

For each dimension `d ∈ {E, I, S, V}`:
1. Reconstruct parent's `d`-series and successor's `d`-series from `agent_states` rows over `window`.
2. `sim_d = _dtw_similarity(parent_series_d, successor_series_d)` — existing primitive at `src/trajectory_identity.py:198`.
3. If either side has < `min_observations` rows for dimension `d`, record `None` and carry the dimension in `reasons`.

`plausibility = mean(sim_d for d in dimensions if sim_d is not None)`.

If no dimensions are available, `verdict = "inconclusive"` with `plausibility = 0.0` (by convention, not score).

No weights. No composition. Four per-dimension DTW similarities, averaged.

## Deferred — what is *not* in R1 v3

Each item is deferred with a named prerequisite. When its prerequisite ships, it becomes its own plan row.

| Channel | Prerequisite to unlock |
|---|---|
| C2 Homeostatic set-point + recovery | Server-side fit machinery that produces mean/covariance/recovery-tau from `agent_states` scalars. (Current `homeostatic_similarity` expects these as agent-uploaded fields; `process_agent_update` does not populate them.) |
| C3 Calibration curve | Per-agent calibration storage (currently `calibration_checker` is a global aggregate, `src/calibration.py`). Also named in plan.md S12 as a FEP-unblock channel. |
| C4 Decision distribution | Persistent per-agent decision log (currently `AgentBaseline.recent_decisions` is a 20-entry LRU in-memory, `governance_core/ethical_drift.py`). |
| C5 Complexity distribution | Persistent complexity samples + Beta or covariance-fit machinery (currently `baseline_complexity` is a single EMA scalar). |

These four each look like 1-2 weeks of storage/fit work. None of them are blocked on R1; R1 can ship against the standard check-in path today.

## New helper: `reconstruct_eisv_series`

`src/identity/lineage_continuity.py` (new file) exposes:

```python
def reconstruct_eisv_series(
    agent_id: str,
    window: timedelta,
    conn,   # asyncpg.Connection, invoked inside run_in_executor via the
            # sync-asyncpg-in-executor pattern at tests/test_db_utils.py:36-38
) -> Dict[str, List[float]]:
    """
    Return {'E': [...], 'I': [...], 'S': [...], 'V': [...]} from core.agent_state
    rows for the agent within window, ordered by timestamp ascending.
    Dimension keys map to SQL columns: E→entropy, I→integrity, S→stability_index,
    V→volatility. Empty lists for dimensions with no rows in window.
    """
```

**SQL shape.** `core.agent_state` stores `identity_id` (BIGINT FK to `core.identities`), not the text `agent_id`, so the helper joins `core.identities` to resolve the UUID string. This matches the existing pattern in `get_latest_agent_state` at `src/db/mixins/state.py` (see the same file for `_row_to_agent_state` mapping — Python field name `void` corresponds to SQL column `volatility`; use the SQL name `volatility` in the query).

```sql
SELECT s.entropy, s.integrity, s.stability_index, s.volatility, s.recorded_at
FROM core.agent_state s
JOIN core.identities i ON i.id = s.identity_id
WHERE i.agent_id = $1
  AND s.recorded_at >= NOW() - $2::interval
ORDER BY s.recorded_at ASC;
```

Index coverage: `db/postgres/schema.sql:169` provides `idx_agent_state_identity_time ON core.agent_state(identity_id, recorded_at DESC)`. Planner resolves identity first, then range-scans the index. No new index needed.

**Schema specifics** (for implementor): columns are `REAL NOT NULL DEFAULT ...`; `recorded_at` is `TIMESTAMPTZ NOT NULL`. Group rows into per-dimension lists in Python by reading the four scalar columns in order.

## Plausibility → verdict thresholds

Initial values, synthetic-seeded:

| Condition | Verdict |
|---|---|
| `observations[successor] < min_observations` OR `parent_mature == False` | `inconclusive` |
| `plausibility >= 0.70` | `plausible` |
| `0.55 <= plausibility < 0.70` | `inconclusive` |
| `plausibility < 0.55` | `unsupported` |

**These thresholds are seeded, not earned.** They produce the right verdicts on the synthetic fixtures below. Before any caller treats a verdict as enforcement-worthy, shadow-mode production data must show the plausibility distribution separates genuine (`spawn_reason=new_session`) from non-genuine cases at the proposed cuts. If it does not, thresholds move; the primitive does not.

The synthetic fixture regression-tests the *cuts* given the generator, not the *calibration* of the cuts against reality. Honest framing matters here.

## Caller policy (the thing v2 punted on)

`inconclusive` has two reasonable caller postures. Every call-site picks one explicitly; no default.

- **Blocks (conservative):** `inconclusive` does not upgrade the lineage claim. Re-evaluate later when the successor has more observations.
- **Marks (permissive):** `inconclusive` proceeds but the lineage record is stamped `provisional=true`. Downstream consumers (trust-tier, KG provenance) can see the mark and decide independently.

Near-term call-sites and their postures:
- Onboard-time scoring of `parent_agent_id` → **Marks.** Fresh agents have few observations; blocking here is too strict.
- Promotion from `provisional` to `confirmed` after N check-ins → **Blocks.** Cannot confirm on inconclusive.
- Orphan archival (S8) re-classification with claimed lineage → **Blocks.** Archival is irreversible-ish.

## Implementation sketch

- **Location:** `src/identity/lineage_continuity.py` (new). Consumers import `score_trajectory_continuity` directly.
- **DB pattern:** sync DB read inside `run_in_executor`. The project's `src/agent_loop_detection.py:374` template uses in-memory state and does *not* generalize to DB reads. The correct template already exists at `tests/test_db_utils.py:36-38` — it runs an asyncpg connection on a fresh event loop inside the executor thread via `asyncio.run(...)`. This adds no new dependency (project already has `asyncpg>=0.29.0`; `psycopg2` is not in `pyproject.toml`). Env var is `DB_POSTGRES_URL` (see `src/db/postgres_backend.py:72`), not `DATABASE_URL`. An implementation may promote the `test_db_utils` pattern into a reusable helper, but no new driver is required.
- **Exposure:** internal policy consumers only. No MCP tool wrapper in v3.
- **Observability:** emits a KG discovery of type `trajectory_continuity_score` with `plausibility`, `verdict`, `components` (per-dimension), and `observations`. Provides audit trail.

## Test fixture (synthetic)

`tests/conftest.py` is pure isolation infrastructure (session, DB-backend stubbing, ghost cleanup) — no data-generator fixtures live there today. Adding a trajectory generator there would be a stylistic mismatch. Place the generator in a dedicated helper module instead:

- `tests/helpers/trajectory_fixtures.py` (new) — `synthetic_trajectory_pair(seed, kind) → (parent_rows, successor_rows)`: returns two lists of dicts shaped like `core.agent_state` rows. `kind ∈ {"genuine", "divergent", "drifted", "early"}`.
- The `eisv_dtw_score_fixture` pytest fixture (for mocking the DB reader in unit tests) can live as a local fixture in `tests/test_lineage_continuity.py` itself, or be promoted to a helper module later if multiple tests use it.

Test cases in `tests/test_lineage_continuity.py` (new):

1. **Genuine.** Parent 30 rows high-basin, successor 10 rows continuing same generator. Expect `verdict=plausible`, `plausibility >= 0.70`.
2. **Divergent.** Parent as above; successor from independent generator. Expect `verdict=unsupported`.
3. **Early.** Parent as above; successor with 3 rows. Expect `verdict=inconclusive`, `parent_mature=True`.
4. **Drifted.** Parent stable; successor starts matched then drifts 10 rows. Expect `verdict=inconclusive` (the policy-decision zone).
5. **Immature parent.** Parent with 4 rows. Expect `verdict=inconclusive`, `parent_mature=False`.
6. **Dimensional degradation.** Parent has all four dimensions; successor has only E (others recorded as `None`). Expect plausibility averaged over E only, dimensions named in `reasons`.

Generators are deterministic (seeded). Thresholds are regression-tested against synthetic, *not* calibrated against it — see thresholds section.

## Shadow-mode calibration path

1. Ship primitive with synthetic-seeded thresholds.
2. Log every scoring call to KG discovery-type `trajectory_continuity_score`. Do not enforce.
3. After ≥ 2 weeks or ≥ 50 declared-lineage pairs (whichever later), inspect distributions by `spawn_reason`:
   - `new_session` — expect genuine, should cluster above 0.70.
   - `subagent` — hypothesis: bimodal.
   - `compaction` — unknown.
4. If distributions don't separate at the proposed cuts, move the cuts. If they do, the seeded thresholds stand.
5. Only after shadow calibration are the `blocks` policy variants considered for enforcement.

Shadow-mode is the calibration mechanism. The synthetic fixture is a regression mechanism. Confusing these is v2's "thresholds asserted, not earned" failure.

## Dependency map

```
R1 ── provides similarity gate for ── R2 (integration test; R5 discriminates integration from replay)
R1 ── does NOT unblock ───────────── Q1 (trajectory portability — similarity ≠ integration)
R1 ── does NOT unblock ───────────── Q2 (subagent ephemerality — shadow data may inform, does not resolve)
R1 ── does NOT unblock ───────────── S9 (PATH 1/2 — honesty primitive, not verification primitive)
```

R1's near-term value is **diagnostic**: shadow-mode scoring of real declared-lineage pairs produces the evidence needed to (a) calibrate thresholds, (b) inform Q2 subagent-ephemerality analysis, (c) motivate or refute the C2/C3/C4/C5 infrastructure investments. R1 does not become load-bearing until R2 is under work and uses R1 as its similarity gate.

v1/v2 framed R1 as "the earning mechanism." v3 is narrower: R1 is a single-channel telemetry primitive that *could become* part of an earning mechanism if R2 is built on top of it. Stated directly, not hidden in a Purpose-section flourish.

## Open questions for Kenny

1. **Caller-policy defaults.** v3 proposes three call-sites (onboard, promotion, orphan). Correct list, or are there others? Any that should flip their default?
2. **Shadow-mode cutoff.** "≥ 50 pairs" is a guess based on plan.md's 56-agent 3-week corpus statement. Right order of magnitude, or closer to 200?
3. **Blocking-issue for implementation.** The sync-DB-read helper is trivial but doesn't exist. Should R1's implementation row include that helper, or should it be a separate row (one small helper, used by many future primitives)?

## Appendix: what this does NOT solve

- **Adversarial forgery.** KG-readable parent state enables trajectory synthesis. R1 is an honesty primitive, not a security one.
- **Trajectory portability (Q1).** R5's job.
- **Substrate-earned identity (R4).** Separate three-condition test.
- **Multi-channel agent fingerprint.** Not this row. See deferred table.
- **Agents with < `min_observations` rows.** Intentionally outside scope; returns `inconclusive`.
- **Weight justification.** Moot — single channel, no weights.

## Appendix: review provenance

- v1 dialectic (`a98256ccd566598cd`) — independence-citation error, content-exclusion tension, Potemkin-verifier risk, R2/Q1 overclaim, inconclusive-band framing.
- v1 code review (`ae3eec7695eafae26`) — C3/C4/C5 not implementable from current storage.
- v2 dialectic (`a57d2b9f80ee33ce3`) — C2 hidden composite weighting, 0.5/0.5 as claim not refusal, "paces with v7" conflation, thresholds asserted not earned, earning-mechanism vs telemetry-only framing gap.
- v2 code review (`a5a418ffb32f569b8`) — C1/C2 both gated on agent-uploaded `TrajectorySignature.attractor`, `run_in_executor` template does not cover DB reads, `tests/fixtures/` convention does not exist.
- v3 dialectic (`acb058f6cd6f3f4f0`) — dynamics-confound observation (post-coupling EISV may measure dynamics more than agent), seeded-thresholds epistemic-debt tension, inconclusive-flood operational concern. All three judged below forcing threshold given v3's shadow-mode-only ship posture. Dialectic's explicit recommendation: stop iterating, next signal comes from data.
- v3 code review (`a68d31899e90dea48`) — `core.agent_state` indexes on `identity_id` not `agent_id` (JOIN required); env var is `DB_POSTGRES_URL` not `DATABASE_URL`; psycopg2 is not a project dependency (use sync-asyncpg-in-executor pattern already at `tests/test_db_utils.py:36-38`); `conftest.py` is pure isolation infrastructure, data generators belong in a helper module.

v3.1 applies the v3 code-review corrections in-place (SQL JOIN, correct env var, sync-asyncpg pattern, fixture module). No spec-level changes.
