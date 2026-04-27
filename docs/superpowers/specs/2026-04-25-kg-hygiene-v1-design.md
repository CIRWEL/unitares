# KG Hygiene v1 — Design

**Status:** Draft
**Date:** 2026-04-25
**Scope:** UNITARES knowledge-graph robustness — close the feedback loop on a write-strong / feedback-weak corpus.
**Successor planned:** v2 (deferred items below)

## Problem

The KG corpus has 647 discoveries (91 open / 68 resolved / 224 archived / 264 cold). Three concrete gaps:

1. **Awareness** — `knowledge action=store` does no embedding-based dedup; near-duplicates accumulate.
2. **Resolution** — open discoveries don't get marked resolved unless an agent explicitly calls `knowledge action=update`. There is no signal-driven path. The 91-open backlog reflects this.
3. **Search-correctness verification** — the eval harness at `tests/retrieval_eval/` exists with five baselines from 2026-04-19/20, but is not on a schedule. Most recent baseline is six days stale; nothing alerts on regression.

The unifying frame: the KG today is **write-strong, feedback-weak** — entries land, but no closed loop tells you whether search retrieves them, whether "open" is still true, or whether a new note duplicates an old one.

## Decisions Locked During Brainstorm

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Scope = both KG discoveries and Watcher findings** with shared lifecycle/surfacing where genuinely shared | Both are "agent-facing memory hygiene"; lifecycle UX overlaps even if detection algorithms differ |
| 2 | **Action authority = tiered.** Auto-act on cheap/reversible. Propose-only on lossy/inferred | Matches Watcher's existing `--resolve/--dismiss` discipline; respects past Vigil-aggression episode |
| 3 | **Auto-act signals = `supersedes:` field only in v1** | We control writers when authoring discoveries; immediately useful with no adoption dependency |
| 4 | **Architecture = place each concern where its signal already lives** | Write-time can't live elsewhere (data is in hand); commit-time and 30-min sweeps reuse existing operational surfaces (Vigil, post-commit hook) |

## Decisions Reversed During Council Review

| # | Original | Revised | Why |
|---|----------|---------|-----|
| R1 | Extend Watcher to read commits | New `hooks/post-commit` script (deferred to v2) | Watcher is purely PostToolUse-on-edit; does not read commits today (`agents/watcher/agent.py`, `findings.py` verified). The CLAUDE.md "fingerprints in commit messages" line means Watcher *writes* audit trails on resolve/dismiss, not reads them back. |
| R2 | "Shared dedup primitive" between KG and Watcher | Detection layers stay separate; only lifecycle/surfacing is shared | Watcher uses fingerprint hashes (file:line + pattern); KG would use embedding cosine. Different algorithms — forcing one base class produces a leaky abstraction. |
| R3 | Write-time embedding dedup in v1 | Deferred to v2 | Adds new latency on every `knowledge.store` call inside an asyncpg-deadlock-prone handler; needs measured data on store-call frequency before justifying. Existing tag-overlap `auto_link_related` (handlers.py:576) already runs as a baseline. |
| R4 | First-class `knowledge.hygiene_proposals` table | Vigil's existing summary output | At expected steady-state volume (single-digit proposals/week), a new table + writer interface + reader UI is over-built. PR #140 already gives Vigil's summary a dashboard panel. |
| R5 | `Resolves KG#<id>` commit-message parser in v1 | Deferred to v2 | Adoption is zero today; `Resolves` channel will be near-empty for weeks. Optimizing an empty channel is premature. Revisit after the v1 stale-opens sweep produces real volume data. |

## v1 Scope (3 items)

### Item 1 — `supersedes:` field with permanent-tag guard

**Where:** `src/mcp_handlers/knowledge/handlers.py:handle_store_knowledge_graph` (entrypoint at L331; current `await graph.add_discovery(discovery)` at L601).

**What:**
- Accept new optional `supersedes: <discovery_id>` parameter on `knowledge action=store`.
- Before the store call, look up the predecessor discovery.
- If predecessor is `permanent`-policy (per `get_lifecycle_policy(discovery)` in `src/knowledge_graph_lifecycle.py:117`) → reject with explicit error: "cannot supersede a permanent discovery; explicit operator action required."
- Otherwise → flip predecessor `status` from its current value to `superseded`, write `superseded_by` field pointing at the new discovery, then proceed with normal store.
- Add `superseded` to `DiscoveryNode.status` docstring (`src/knowledge_graph.py:88`) and to any handler-level allowlist (verify in `handle_update_discovery_status_graph`).

**Lifecycle interaction:** `_archive_old_resolved` in `knowledge_graph_lifecycle.py:235` queries `status="resolved"` only — it does not act on `superseded`. v1 leaves this alone: `superseded` entries become hot-but-quiet until a future v2 sweep decides what to do with them. Documenting the unhandled state is the v1 deliverable; treating it is v2.

**Tests:**
- `tests/test_kg_store.py` — extend with: store with `supersedes:` flips predecessor; store with `supersedes:` of permanent → rejection; store with `supersedes:` of nonexistent ID → error.
- New: `tests/test_kg_supersedes_lifecycle.py` — confirm `_archive_old_resolved` does not touch `superseded` entries.

### Item 2 — Vigil step 4.7: `retrieval_eval --json`

**Where:** `agents/vigil/agent.py:run_cycle()` at L392, fits the existing numbered-step pattern.

**What:**
- Add `with_eval: bool = False` flag to Vigil cycle (mirrors existing `with_tests`/`with_audit` pattern at L263–L265).
- When enabled, run `scripts/eval/retrieval_eval.py --json` via `loop.run_in_executor(None, ...)` (mirror the pytest pattern at L451; do NOT `await` directly — would hit the anyio deadlock surface).
- Capture `nDCG@10`, `Recall@20`, `MRR`, `latency_p50`, `latency_p95` from JSON output.
- Diff against the baseline file matching the **live retrieval configuration**: derive a config tag from `UNITARES_EMBEDDING_MODEL`, `UNITARES_ENABLE_HYBRID`, and `UNITARES_ENABLE_GRAPH_EXPANSION` env vars (e.g. `bge_m3`, `bge_m3_reranked`, `hybrid_rrf`, `hybrid_graph`), then pick the newest `tests/retrieval_eval/baseline_*_<config>.json` by mtime. There are five existing baselines covering different configs; picking by mtime alone would compare apples to oranges.
- If no baseline matches the live config: emit the run output and log a warning (`no matching baseline for config=<tag>`); no regression alert. Operator decides when to promote that output as the new baseline (manual checkin to `tests/retrieval_eval/`).
- Post a one-line delta into Vigil's existing summary: e.g. `eval: nDCG@10 0.74 (Δ -0.02 vs baseline_2026-04-20_hybrid_rrf), p95 142ms (Δ +8ms)`.
- If `nDCG@10` regresses by more than a configurable threshold (default 0.05), tag the Vigil cycle as `degraded_retrieval` so the existing dashboard panel surfaces it.

**Environment requirement:** Vigil's launchd plist must inherit `UNITARES_EMBEDDING_MODEL=bge-m3` and `UNITARES_ENABLE_HYBRID=1` from the governance-mcp plist environment, and have live PG access. (Verified: it does.)

**Tests:**
- Mock the eval-harness JSON output; verify Vigil parses, diffs, and emits the summary line correctly.
- Verify the `run_in_executor` wrapping (no bare `await` on retrieval-eval entrypoint).

### Item 3 — Vigil step 4.5: stale-opens sweep

**Where:** Same Vigil cycle, before the eval step. Add `with_hygiene: bool = False` flag.

**What:**
- Query `knowledge.discoveries WHERE status='open' AND updated_at < now() - interval '30 days'` via the same `run_in_executor` pattern.
- For each stale open: emit a one-line entry into Vigil's summary as a propose-only candidate: `stale_open: <discovery_id> "<summary[:60]>" age=<N>d`.
- Order results by age descending (oldest stale first); cap at top 20 per cycle to avoid summary flooding.
- Do NOT auto-flip status. v1 surfaces; humans/agents act.

**Future-friendly:** if v2 chooses to promote these into a real `knowledge.hygiene_proposals` table, the sweep logic moves verbatim — only the output sink changes.

**Tests:**
- Fixture-based: seed N stale-open discoveries, run sweep, assert summary contains them ordered by age.
- Verify cap (>20 stale opens → only top 20 surfaced).

## Cross-Cutting Concerns

**Anyio-asyncpg deadlock surface.** Both Vigil-cycle additions (Items 2 + 3) MUST use `loop.run_in_executor(None, sync_func, ...)` and never `await` asyncpg/embedding calls directly from the cycle's async context. This is the same rule documented in `unitares/CLAUDE.md` for MCP handlers; Vigil's pytest step at L451 is the canonical pattern.

**Permanent-policy invariant.** Item 1's auto-flip MUST veto on `get_lifecycle_policy() == "permanent"`. This is coded as a pre-flight check at the store entrypoint, NOT delegated to the lifecycle sweeper (which doesn't query `superseded` and so cannot enforce the invariant after the fact).

**No new resident agents.** v1 deliberately adds no new launchd plists. All work lands in existing processes (Vigil, governance-mcp handler).

**No schema migrations.** v1 reuses the `knowledge.discoveries` table as-is. The new `superseded` status string is a value, not a schema change. `superseded_by` is added as an optional field on `DiscoveryNode`; if storage is JSON-blob-flexible (verify), no migration needed.

## Out of Scope (deferred to v2)

| Item | Why deferred | Trigger to revisit |
|------|--------------|---------------------|
| Write-time embedding dedup | Latency unmeasured; existing `auto_link_related` already runs | After 2 weeks of v1 in production: measure store-call latency baseline + near-dup arrival rate from stale-opens sweep |
| `Resolves KG#<id>` post-commit hook | Zero adoption channel today | After stale-opens sweep produces volume data showing humans WOULD have used it |
| First-class `knowledge.hygiene_proposals` table | Premature abstraction at expected v1 volume | When Vigil's summary line for hygiene exceeds ~5 lines/cycle consistently |
| Watcher findings ↔ KG discovery cross-resolution | Detection layers are different; cross-link adds complexity | When agents start storing KG discoveries that mirror Watcher findings (observed pattern, not theoretical) |
| Auto-resolution from `auto_ground_truth.py` test signals | Requires per-discovery test mapping; new metadata on every `bug_found` discovery | When `bug_found`-typed discoveries become a meaningful share of opens |

## Success Criteria for v1

- After 2 weeks running:
  - At least one `superseded` discovery flipped via `supersedes:` field (proves Item 1 works end-to-end).
  - Vigil's summary contains an `eval:` line every cycle, and the `nDCG@10` delta is observable in the dashboard.
  - Vigil's summary contains a `stale_open:` block whenever stale opens exist.
  - Zero new alerts/incidents attributed to either the Vigil eval-step latency or the store-path supersedes-check latency.
- Volume data captured:
  - Count of `supersedes:` invocations / week.
  - Count of stale-open candidates / cycle (used to size v2 propose-queue).
  - Count of nDCG regressions caught (used to validate eval threshold).

## Implementation Order

1. Item 1 (`supersedes:` field) — smallest change, highest confidence, ships first.
2. Item 3 (stale-opens sweep) — pure additive Vigil step, no new external deps.
3. Item 2 (eval harness in Vigil) — depends on `run_in_executor` plumbing also used by Item 3, easier to land second.

Each is independently shippable; failed verification on one does not block the others.

## Open Questions for Implementation Plan

- Exact threshold for "stale" — 30 days from `updated_at` is a starting guess. Sweep against the live corpus during planning to confirm 30d gives a sane volume (not 0, not 91).
- Exact threshold for nDCG regression alert — 0.05 absolute is a starting guess. Validate against the variance across the existing five baselines before committing.
- Whether `superseded_by` lives as a top-level field on `DiscoveryNode` or in the JSON tags/metadata blob — depends on what `DiscoveryNode.to_dict()` and the Postgres schema currently allow.

These are plan-level questions, not spec-level. The writing-plans skill resolves them with code reads.
