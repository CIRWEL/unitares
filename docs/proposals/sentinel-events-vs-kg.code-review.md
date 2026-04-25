---
title: Code review — sentinel-events-vs-kg
reviewer: feature-dev:code-reviewer (subagent)
date: 2026-04-25
status: blocking issues found
---

# Code Review: sentinel-events-vs-kg.md

Reviewing `/Users/cirwel/projects/unitares/docs/proposals/sentinel-events-vs-kg.md` against the live codebase. All claims below reference actual file paths and line numbers read during this review.

## BLOCKING Issues

### 1. `/api/findings` GET does not exist — Confidence: 100

**File:** `src/http_api.py:2345`

The route table contains:
```python
app.routes.append(Route("/api/findings", http_record_finding, methods=["POST"]))
```

`http_record_finding` (line 1657) is POST-only and writes to `event_detector.record_event()`. There is no GET handler registered for `/api/findings` anywhere in the file. The proposal says "Confirm `/api/findings` supports GET with filters (or what the gap is)" but then recommends Option B as a "single PR" without naming the missing GET endpoint as a prerequisite deliverable. This is a self-contradicting recommendation — the plan acknowledges uncertainty and then proceeds as if it is resolved.

The closest existing endpoint is `GET /api/events` (`http_api.py:2344`, handler at line 922), which queries `event_detector.get_recent_events()` with `event_type`, `agent_id`, `limit`, and integer `since` cursor. That endpoint can filter `?type=sentinel_finding` today without any new code.

**Fix:** Either (a) add "build GET `/api/findings` with filter support" as a required Step 0 in the proposal, or (b) redirect Option B to use the already-existing `GET /api/events?type=sentinel_finding`. If (b), see Issue 4 below for the `since` cursor semantics mismatch.

### 2. `post_finding` does NOT persist to `audit.events` — Confidence: 95

**Files:** `src/event_detector.py:381-418`, `src/broadcaster.py:87-132`, `src/http_api.py:1690-1696`

The proposal says: "Confirm findings stream survives MCP server restart for at least the Vigil cycle interval (30 min). `audit.events` persistence is fire-and-forget per `src/broadcaster.py:114`."

The actual data flow breaks this assumption for sentinel findings specifically:

- `http_record_finding` calls `event_detector.record_event(payload)` (line 1691) — this stores to the in-memory ring buffer only (`_recent_events` list, max 500 entries).
- `broadcaster._persist_event` (lines 118-132) is only called from `broadcast_event` (line 112-116). `record_event` does not call `broadcast_event` and does not trigger `_persist_event`.
- `event_detector` is a module-level singleton (`event_detector.py:531`) initialized with an empty `_recent_events` list. On MCP server restart it is empty.
- The `GET /api/events` endpoint (`http_events` at line 922) does supplement from `audit.events` via `query_audit_events_async` (line 946-986) when the in-memory buffer is thin. But this only helps for events that were previously persisted — and sentinel findings via `post_finding` are never persisted.

Result: a Vigil cycle that runs 5 minutes after an MCP server restart will see zero sentinel findings from the previous 25 minutes, even if Sentinel was actively emitting findings up until the restart. The proposal's 30-minute reliability claim is wrong for `sentinel_finding` events.

**Fix:** Either (a) make `http_record_finding` call `await broadcaster_instance.broadcast_event(...)` after accepting a finding (which triggers `_persist_event` to `audit.events`), or (b) explicitly scope a separate persistence fix and document in the proposal that Option B coordination is unreliable across restarts.

## Important (Non-Blocking) Issues

### 3. Sentinel's note tag set and Vigil's filter: severity=high is load-bearing — Confidence: 90

**Files:** `agents/sentinel/agent.py:554-557`, `agents/vigil/agent.py:235-236`

Sentinel's `notes` tag set is `["sentinel", f["type"], f["severity"]] + ([vcls.lower()] if vcls else [])`. Vigil's `_filter_sentinel_findings` requires both `"sentinel"` AND `"high"` present in the tags (line 235-236). Medium and low severity sentinel findings in KG are silently ignored by Vigil.

The proposal's test plan says "Vigil's `_read_findings_stream` returns the same shape as `_read_sentinel_findings` for the same conceptual input" but does not specify that the stream query must also filter `severity=high`. If `_read_findings_stream` queries `event_type=sentinel_finding` without a severity filter, it will surface medium/low findings that the current KG path discards, and `sentinel_force_audit` would trigger on lower-severity signals than it does today.

**Fix:** Option B implementation note and test plan must specify `severity=high` as a required query filter, not just `event_type=sentinel_finding`.

### 4. ISO timestamp vs integer event_id cursor — semantics mismatch — Confidence: 88

**Files:** `agents/vigil/agent.py:238`, `src/event_detector.py:516`, `src/http_api.py:934`

Vigil's existing filter uses `created_at <= since_iso` where `since_iso` is an ISO 8601 string from the state file (`prev_state.get("cycle_time")`). The `event_detector.get_recent_events` `since` parameter is an integer event_id cursor (line 516): `events = [e for e in events if e.get("event_id", 0) > since]`. `GET /api/events` exposes this as `int(since_raw)` (line 934).

These two approaches are not semantically equivalent:
- The ISO timestamp filter works correctly across restarts because `cycle_time` is persisted in the state file (`.vigil_state`).
- The integer event_id cursor resets to 0 on MCP server restart. After a restart, any stored `since=<old_id>` would match all new events (new IDs start from 0 again), causing Vigil to receive the entire buffer instead of just findings since its last cycle.
- Alternatively, parsing Vigil's ISO `cycle_time` into a unix timestamp for the `since` parameter requires explicit code; the endpoint does not accept ISO timestamps natively.

**Fix:** The proposal must specify the filter adapter strategy explicitly — either convert ISO `cycle_time` to unix timestamp at the call site (and document the type), or use a time-based query that the endpoint actually supports.

### 5. `tests/test_sentinel_coordination.py` does not exist — Confidence: 88

**Path checked:** `/Users/cirwel/projects/unitares/tests/test_sentinel_coordination.py` — file does not exist.

The proposal's test plan references updating this file as part of Option B. It must be created from scratch, which adds scope not reflected in the LoC estimate. (Note: an existing test exists at `agents/vigil/tests/test_sentinel_coordination.py` covering Vigil-side coordination; that file would be modified, not created.)

### 6. LoC estimate is materially too low — Confidence: 88

The proposal estimates "~150 LoC across 3-4 files." Actual scope:

- `_read_sentinel_findings` (vigil/agent.py:289-313): 25 lines to replace
- `_filter_sentinel_findings` (vigil/agent.py:221-251): 31 lines — logic must be ported plus adapted for stream format, ISO/int cursor adapter
- Sentinel `note_tuples` block (sentinel/agent.py:548-565): ~18 lines to remove
- New `_read_findings_stream` in Vigil: comparable complexity to current path, plus HTTP call, restart-gap handling, severity filter
- New GET `/api/findings` handler if not using `/api/events`: 60-100 lines including route registration, filter params, DB fallback for persistence
- New / adapted Vigil tests: 50-100 lines minimum for the 3 test cases in the test plan

Realistic estimate: 250-350 LoC if redirecting to `GET /api/events`, 400-500 LoC if building a proper `GET /api/findings` endpoint with persistence.

### 7. Option C `CycleResult.events` routing requires SDK base class extension — Confidence: 85

**File:** `agents/sdk/src/unitares_sdk/agent.py:374-380`

`_process_cycle_result` routes `result.notes` through `client.leave_note()`. Adding an `events` field to `CycleResult` would require explicit routing logic in `_process_cycle_result` to call `post_finding` for each event. There is no existing hook for this. The proposal says "SDK routes `events` through `post_finding()`" — that routing must be explicitly added to the base class, it does not happen automatically. No Python-level name collision with existing fields, but the implementation is more than a dataclass field addition.

## Verified Claims

- Proposal line 14: `post_finding` at `agents/sentinel/agent.py:524` — CONFIRMED.
- Proposal line 15: `leave_note` via SDK at `agents/sentinel/agent.py:549-557` — CONFIRMED. `note_tuples` built at lines 548-557, passed as `CycleResult.notes`, routed through SDK `_process_cycle_result` at `agents/sdk/src/unitares_sdk/agent.py:374-380`.
- Proposal line 19: Vigil reads `tags=["sentinel"]` via `_read_sentinel_findings` — CONFIRMED. `agents/vigil/agent.py:289-313`.
- Proposal line 19: `_filter_sentinel_findings` — CONFIRMED at `agents/vigil/agent.py:221-251`.
- Proposal line 84: "Watcher already uses post_finding correctly" — CONFIRMED. `agents/watcher/agent.py:79` imports `post_finding`; no `leave_note` for findings.
- `audit.events` fire-and-forget in `broadcaster.py:114` — CONFIRMED, but this path is NOT triggered by `post_finding`.

## Verified Files

- `agents/sentinel/agent.py:490-565`
- `agents/vigil/agent.py:221-313`
- `agents/common/findings.py` — POST-only helper, no GET capability
- `src/http_api.py:1657-1699, 2344-2358`
- `src/event_detector.py:170-418, 516, 531`
- `src/broadcaster.py:87-132`
- `agents/sdk/src/unitares_sdk/agent.py:46-57, 360-408`
- `agents/sdk/src/unitares_sdk/models.py`
- `agents/watcher/agent.py:79`
