---
title: Dialectic Review — Sentinel ephemeral events vs KG
reviewer: dialectic-knowledge-architect
of: sentinel-events-vs-kg.md
date: 2026-04-25
posture: the seam is real and the diagnosis is correct, but the recommended option ships a contract change against an unverified substrate; the sharpest objection is not in the alternatives the proposal canvassed
---

# Dialectic Review

The diagnosis is right. KG-as-coordination-bus IS a category error, the four KG sweeps cited at `agents/sentinel/agent.py:549-557` (notes path) vs `agents/sentinel/agent.py:524-535` (post_finding path) are visibly redundant, and the residue Vigil currently fishes out via `search_knowledge(query="sentinel", tags=["sentinel"], limit=10, semantic=False)` at `agents/vigil/agent.py:300-302` is exactly the kind of cross-process coupling that ought to live in a stream, not in memory. The synthesis the proposal reaches — KG=memory, findings=signal — is the right axis to draw.

But the recommendation (B, single PR) has three load-bearing problems the proposal does not engage with, plus a hidden assumption in the verification list that, if checked, would force a different option. This review is structured around those.

---

## 1. The verification list checks the wrong invariant

The proposal lists three verification items before committing to B (`§ Verification before code`). Two of them are answerable from the existing codebase — and one of them, taken seriously, eliminates B as currently specified.

### 1a. `/api/findings` GET path: does not exist, but the equivalent does

The proposal says "verify before committing to the path." The path does not exist for arbitrary GET-by-filter, but a more specific path *already does*: `GET /v1/sentinel/summary` at `src/http_api.py:1435-1468` already aggregates `sentinel_finding` events from `event_detector.get_recent_events(event_type="sentinel_finding", limit=500)` with a `window_hours` filter. Vigil's `_read_sentinel_findings` could call this endpoint today (auth-gated by `UNITARES_HTTP_API_TOKEN` per `_check_http_auth`). The "small enhancement" in the proposal is in fact a stylistic question — does Vigil call `/v1/sentinel/summary` or do we add `GET /api/findings?type=sentinel_finding&since=...`?

This matters because the proposal sized B at "~150 LoC across 3-4 files." If `/v1/sentinel/summary` is the path, B is closer to 30 LoC: swap the `client.search_knowledge(...)` call at `agents/vigil/agent.py:300` for an `httpx.get` against the existing endpoint, drop the `tags=["sentinel"]` write path in `agents/sentinel/agent.py:549-557`, update one filter helper. The sizing tells the council the wrong thing.

### 1b. Restart survival: this is the load-bearing flaw and B does not survive it

The proposal says: "Confirm findings stream survives MCP server restart for at least the Vigil cycle interval (30 min). `audit.events` persistence is fire-and-forget per `src/broadcaster.py:114`."

Read more carefully. `src/broadcaster.py:111-116` persists *broadcaster events* to `audit.events` via `create_tracked_task(self._persist_event(...))`. But Sentinel's findings do NOT go through `broadcaster.broadcast_event`. They go through `post_finding()` (`agents/common/findings.py:41-92`) → HTTP POST `/api/findings` (`src/http_api.py:1657-1699`) → `event_detector.record_event` (`src/event_detector.py:381-418`).

`event_detector.record_event` does not persist anywhere. There is no `_persist_event` call, no `audit_db.append_audit_event_async`, no DB write at all. The event is appended to `self._recent_events` in-memory and that is the entirety of its durability story. A `governance-mcp` restart wipes every Sentinel finding. The dedup fingerprint dict at `event_detector.py:180` is also memory-only and resets to empty on restart.

This is not a small gap. It means:

- **30-min Vigil cycles + the gov-mcp restart cadence is collision-prone.** Restart while a Sentinel finding is in flight, or in the gap between Sentinel cycles (15s) and the next Vigil cycle (30 min): Vigil sees nothing where the KG path would have surfaced the finding. Today's KG path survives restart because KG is Postgres-backed.
- **The dedup window degrades silently across restarts.** Sentinel re-emits the same finding next cycle; the dedup fingerprint is empty; Discord pings again. Watcher's audit trail (`data/watcher/findings.jsonl`) avoids this by being on disk; the proposal's chosen substrate is not.
- **The `since=cycle_time` query Vigil needs is racy against the ring-buffer eviction.** `event_history` is a `deque(maxlen=2000)` per `src/broadcaster.py:15,24`, but `event_detector._recent_events` is bounded at `max_stored_events=500` (`src/event_detector.py:170`). At fleet-wide event rates >16/min, a 30-min Vigil window can evict findings before Vigil reads them. The current KG path has no such cap.

The proposal's verification item *names* this risk and then waves at it with "verify." Once verified, the answer is: the findings stream as it stands today is *not a coordination substrate, it is a dashboard cache*. Building Vigil-Sentinel coordination on it is building load-bearing structure on a deck designed for pageviews.

The honest options are:
1. **Make `event_detector.record_event` persist to `audit.events`** the same way `broadcaster.broadcast_event` does — small change in `src/event_detector.py:381` and `src/http_api.py:1691`. This is itself a spec-worthy change because findings lifecycle is *unlike* broadcaster events (no agent_id semantics, fingerprint-keyed dedup, externally-sourced auth boundary) — should they collide in `audit.events`?
2. **Persist to a dedicated `audit.findings` table** with its own schema and retention. More honest about what the data is, but this is now a schema migration, not a 150-LoC refactor.
3. **Keep findings in-memory and drop the cross-process coordination requirement entirely** — Sentinel writes, dashboard reads, Vigil does NOT couple to Sentinel. This regresses the coordination arc the proposal is trying to preserve.
4. **Option A, on the grounds that KG's Postgres-backed durability is exactly the property the coordination path needs**, even if the rest of KG is a category mismatch. KG's wrongness as a search index is a real cost; its rightness as a durable cross-process queue is also real.

B as written silently picks option 3 and packages it as option 1+2.

### 1c. The fingerprint stability check is the wrong question

Item #3: "Confirm the dedup fingerprint key Sentinel uses (`["sentinel", type, violation_class, agent_id]`) is stable across cycles — Vigil's coordination relies on the *occurrence* not the persistent fingerprint."

The fingerprint *is* stable across cycles for a recurring condition — that's the whole point of the dedup window at `src/event_detector.py:181` (`_dedup_window_seconds = 1800`, 30 min). Which means: a Sentinel finding that recurs every cycle (Sentinel cycle interval is shorter than 30 min) gets dedup-suppressed at `record_event`. The HTTP response is `{"success": true, "deduped": true}` and `event_detector._recent_events` does not get a new entry.

So Vigil reading "all sentinel findings since last cycle" might see *zero new entries* even when the fleet condition is actively persisting. Today's KG path doesn't have this collision because `leave_note` doesn't dedup at the storage layer. The proposal's coordination contract (Vigil reads new findings since last cycle to decide on `_SENTINEL_AUDIT_TRIGGERS`) is incompatible with the dedup window aligned to the same 30-min cadence as Vigil's cycle. They are within an order of magnitude of each other and the system needs them to be cleanly separated.

Concretely: a `verdict_distribution_shift` finding emitted by Sentinel at t=0 dedups successive emissions until t=30min. Vigil reads at t=30min with `since=t-30min` and finds the original event (still in `_recent_events`). Good. But Vigil reads at t=60min with `since=t-30min` and finds *nothing* — the original event is older than 30min, the dedup window just expired so Sentinel re-emits at t=60min, but there's a race between the re-emit and Vigil's read. If Vigil reads first: empty. If Sentinel re-emits first: non-empty.

This race does not exist in the KG path. KG entries are timestamped at write and persist; Vigil's `since_iso` filter is a read-side filter against an immutable corpus.

---

## 2. KG=memory / findings=signal — where the line actually blurs

The proposal asserts the seam is clean. Three cases where it isn't:

### 2a. Recurring findings ARE structural, not ephemeral

A `coordinated_coherence_drop` that fires once is a fleet snapshot. The same finding recurring 8 times in 24h IS a pattern — and patterns are exactly the thing KG was designed to hold. The proposal's framing ("the 10-minute window has passed, the agents involved may not even still be running, and the dashboard already captured the signal in real time") is correct for the *single occurrence* and incorrect for the *recurrence pattern*.

The current architecture accidentally captures recurrence via KG accumulation. After B, *nothing* captures recurrence: the dashboard's `_sentinel_summary_from_events` window is 24h (`_SENTINEL_DEFAULT_WINDOW_HOURS` at `src/http_api.py:1342`), the ring buffer holds 500 events fleet-wide, and Vigil reads the 30-min window. A 4-week pattern of weekly `verdict_distribution_shift` events at the same time-of-day disappears from every readable surface.

This is the dialectic generalization the proposal misses: ephemeral occurrences are signal, recurrence patterns are memory, and the line between them is *count over a window*. A clean version of B needs an explicit upgrade path — when does a finding-pattern get promoted to a KG entry? Sentinel detecting the pattern itself? A nightly Chronicler scrape that aggregates `audit.events` (which won't help because findings don't land there)? A new "recurring finding" tag in KG that Sentinel writes only when it has detected its own recurrence?

The proposal's "Out of scope" section silently elides this. The KG=memory side is *not* fully served by today's KG content — it would need promoted-pattern entries that the current architecture has no producer for.

### 2b. Findings whose dialectic resolution becomes a KG entry

The dialectic system (`mcp__unitares-governance__dialectic`) takes finding-shaped triggers (the proposal's own coordination loop) and produces resolution outcomes that *should* end up in KG (insights, decided positions). After B, the path is: Sentinel finding → Vigil audit → dialectic invocation → resolution. The resolution belongs in KG; the trigger does not.

Today this is implicit because Vigil reads KG, sees the trigger and the resolution co-located, and the audit trail threads through the same store. After B, the trigger lives in a memory ring buffer that's already gone by the time the resolution is committed. Reconstructing the chain in audit log requires joining `audit.events` (resolution) against `event_detector._recent_events` (trigger, ephemeral) — and the ephemeral side is gone after restart.

The proposal needs to specify: when a finding causes a downstream KG action, does the finding get a stable reference (URI, fingerprint, canonical event_id) that the KG action can cite? Without this, B *reduces* audit-trail completeness.

### 2c. Vigil's own KG writes blur the same line

Vigil ALSO writes `leave_note` calls — `agents/vigil/agent.py:382` and `agents/vigil/agent.py:578`. These are groundskeeper summaries (KG state changes) and gov-down/Lumen-unreachable findings. The latter is *exactly the kind of thing the proposal wants out of KG* (operational alerts, ephemeral, dedup'd, dashboard-visible). The former (groundskeeper summary: "5 stale archived") is genuinely durable.

If B ships and Sentinel's findings move to the stream, the natural follow-up is "do Vigil's findings also move?" — at which point we discover that Vigil writes BOTH kinds of notes through the same `leave_note` call, distinguishable only by tags. The KG=memory doctrine then forces a Vigil-side split that the proposal doesn't anticipate. That split is a real refactor (agents/vigil/agent.py:574-585 vs the groundskeeper summary site at line 380-ish), and it's not in scope but it's now a foreseeable consequence.

This generalization point matters: **the proposal's contract isn't "Sentinel writes findings via stream" — it's "any agent's ephemeral fleet-state findings go to stream, durable insights go to KG."** Specify the contract at that level and the per-agent migrations become rote. Specify it at Sentinel's level only and every future resident replays this dialectic.

---

## 3. Steward and Chronicler: the contract IS general, but for different reasons than B suggests

The proposal claims B "doesn't generalize" to Steward and Chronicler is a feature ("solving the actual problem is enough for now"). Re-examined:

- **Steward** lives in-process (`project_eisv-sync-agent-identity.md` per memory). It does not currently write to KG (verified: no `leave_note`/`knowledge_action` calls in `src/background_tasks.py`). Its "findings" — Pi→Mac sync gaps, drift between observed and synced EISV — are exactly the kind of fleet-state signal that *would* be a leak if surfaced. Today they're invisible. B's contract gives Steward a clean place to surface them tomorrow.

- **Chronicler** writes to `metrics.series` per memory; doesn't write KG. Its emitted shape is longitudinal samples, not findings. If Chronicler ever detects an anomaly in its own series ("test count regressed >20% week-over-week"), that anomaly is a finding and belongs in the stream. Today Chronicler has no surface for that.

The contract IS general — which means C (the typed `CycleResult.events` SDK channel) is more right than the proposal credits. The argument against C in the proposal is "the generality is speculative." It is not speculative: Steward and Chronicler are concrete agents that don't have findings *yet* but will. The cost of C is one SDK field; the saving is that future residents don't replay this whole dialectic.

The argument for B over C is sequencing, not architecture. C+B together is a strictly better outcome: C makes the contract general at the SDK level, B does the Sentinel-specific cut. The proposal frames them as alternatives. They are phases.

The right packaging:
1. **Phase 1**: Ship C (add `events: list[FindingEvent] | None` field to `CycleResult`, route in `agents/sdk/src/unitares_sdk/agent.py:374-378` near the existing notes-routing logic). One SDK file, one model file, no behavioral change yet — Sentinel still uses `notes`.
2. **Phase 2**: Migrate Sentinel from `notes` to `events` for the high-severity-finding emissions at `agents/sentinel/agent.py:549-557`. KG writes stop. Findings stream is the producer side.
3. **Phase 3**: Switch Vigil's reader from `_read_sentinel_findings` (KG) to a new `_read_sentinel_findings_stream` (HTTP GET against the chosen endpoint). This is what the proposal calls B.
4. **Phase 4 (post-blocker)**: Make `event_detector.record_event` persist to `audit.events` so Phase 3 isn't on volatile substrate.

Phase 4 is a blocker for Phase 3 per §1b. Phase 1+2 can ship without it.

---

## 4. The "two-step migration" objection to C is incorrectly costed

The proposal says C is "two-step" (still need B's Vigil change later) and treats this as a cost. But B is *also* two-step in practice — see Phase 4 above. The proposal's B is presented as a single PR; it's actually B-without-durability, which is option 3 from §1b. The "single PR" framing is a sleight of hand.

Compare honest costs:
- **A**: 10 LoC, no contract change, leaves doctrine half-applied. Re-emerges next quarter.
- **B (as proposed)**: ~30 LoC if `/v1/sentinel/summary` is reused, but requires a separate persistence change (~50 LoC) to be safe. Two-step.
- **C (full path)**: ~80 LoC for SDK channel + Sentinel migration + Vigil migration, plus the same persistence change. Three-step but each step is independently shippable.

C is bigger but each step is smaller and each step is council-reviewable in isolation. B-as-written is "one PR that lies about its scope."

---

## 5. Hidden assumptions in the proposal

Three assumptions the proposal treats as obvious that aren't:

### 5a. "Dashboard already captured the signal in real time" assumes the dashboard is the canonical observer

It isn't, especially for Vigil-Sentinel coordination. The dashboard is a human-facing surface; Vigil is an agent-facing consumer. They have different latency, durability, and filter requirements. The proposal collapses them into a single "the findings stream" abstraction, which is exactly the kind of confusion that produces the very leak it's trying to fix at a different layer.

### 5b. "Removing the writes breaks that coordination path" assumes the path is correctly designed

It might not be. The current path is: Sentinel writes high-severity finding to KG → Vigil reads KG every 30 min → Vigil decides whether to force `_run_groundskeeper`. The 30-min latency between detection and reaction is *terrible* for actual fleet coordination. If Sentinel detects a `coordinated_coherence_drop` at t=0, Vigil doesn't know until t≤30min. A real coordination path would be event-pushed: Sentinel finds something high-severity → Sentinel directly invokes Vigil's audit (or invokes the groundskeeper handler directly). The KG-as-bus design is a *latency artifact* of using a shared store as a pull-based coordination channel.

The proposal treats the existing coordination path as a constraint to preserve. It might be a bug to obsolete. Worth at least naming.

### 5c. "Single PR" assumes no test coverage gap

The proposal's test plan covers the unit/integration/regression of the new path but does NOT cover:
- The dedup-window-vs-Vigil-cycle interaction in §1c.
- The ring-buffer eviction case in §1b.
- The cross-restart Sentinel-finding-loss case in §1b.
- The fingerprint-extraction-from-tags fragility: `agents/vigil/agent.py:240-243` does `next((t for t in tags if t not in ("sentinel", "high", "note")), "unknown")` against tags written at `agents/sentinel/agent.py:556` as `["sentinel", f["type"], f["severity"]] + ([vcls.lower()] if vcls else [])`. The "type" wins by *list ordering* (it's appended before `vcls`). Any tag-rewrite that swaps the order silently breaks Vigil's coordination. After B, this fragility moves into the new endpoint's filter contract — surface it explicitly.

The "regression" test in the proposal ("KG search for `tags=['sentinel']` returns nothing new") tests the cut, not the new path's robustness against the failure modes it inherits.

---

## Synthesis

The proposal is correct that the seam is real, correct that B is the right *architectural endpoint*, and incorrect that B is one PR.

**Recommended re-shaping**:

1. **Reframe as "coordination substrate migration," not "drop the KG writes."** The KG cut is the *easy* half. The hard half is finding a substrate that has KG's durability without KG's semantic-search overhead. `event_detector` as it exists is not that substrate.

2. **Phase the work as C+B, not C-or-B.** SDK channel first (1 PR, low risk, blocks nothing). Sentinel producer migration second. Vigil consumer migration third, gated on substrate durability.

3. **Make substrate durability a Phase 4 blocker, not a verification footnote.** Either persist `event_detector.record_event` events to `audit.events` (small) or add `audit.findings` table (right). Without one of these, B is unsafe in the failure modes the proposal lists "to verify" without verifying.

4. **Specify the "recurring finding → KG entry" upgrade path.** Otherwise B silently regresses pattern visibility from "accidentally captured by KG accumulation" to "captured nowhere."

5. **Surface the dedup-window-vs-cycle-cadence interaction.** Either widen the fingerprint to include cycle counter / decision-relevant context so each Vigil-relevant emission is a fresh fingerprint, or shorten the dedup window below the Vigil cycle, or document that Vigil reads of `since=last_cycle` are *expected to be empty* on stable conditions and that's fine.

6. **Drop the "single PR" claim.** The honesty trade is: smaller per-PR scope, more PRs, council-reviewable steps, vs. one PR that's actually three changes wearing a trenchcoat.

The proposal's intuition is right. The packaging is over-tightened in a way that hides three real problems. A v2 with §1b's substrate question answered, §3's phasing, and §5's hidden assumptions surfaced is ready to build.

---

## Outstanding questions worth carrying forward

- Should `event_detector.record_event` and `broadcaster.broadcast_event` converge on a single event-write path with a single persistence policy? They diverged organically (broadcaster persists, event_detector doesn't) and the divergence is now load-bearing for this proposal.
- Does the dialectic system have a stable URI for findings it dialecticizes? If not, post-B audit trails lose the trigger→resolution chain.
- Is the 30-min Vigil cycle the right cadence for Sentinel-coordinated audits, or is the right answer event-push from Sentinel to Vigil's groundskeeper, with the cycle just for unprovoked sweeps?
- Does Lumen's substrate-anchored identity pattern apply to findings? — i.e., should a Lumen-emitted finding survive Pi reboot the way a Lumen-emitted KG entry does today via `audit.events`? If yes, this is another argument for finding-persistence as a Phase 4 blocker.
