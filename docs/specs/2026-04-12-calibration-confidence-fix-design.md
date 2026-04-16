# Calibration Confidence Fix — Design Spec

**Date:** 2026-04-12
**Status:** Approved

## Problem

The `outcome-tracker.sh` PostToolUse hook fires on Bash and correctly detects pytest runs / git commits, posting `outcome_event` to the governance REST API. Outcome events ARE being recorded to the database (confirmed in server logs). However, tactical calibration evidence (sequential e-process) shows 0 eligible samples because:

1. The REST caller has no MCP session context, so the `outcome_event` handler cannot resolve a monitor for `_prev_confidence`
2. The hook doesn't pass an explicit `confidence` argument
3. Therefore `_confidence = None` → `eprocess_eligible = False` → `sequential_calibration_tracker` never fires

The data needed to fix this already exists in the database — agents check in via `process_agent_update` with confidence values stored in the audit trail.

## Fix: DB Confidence Fallback

Add a fourth step to the confidence resolution chain in `src/mcp_handlers/observability/outcome_events.py`:

```
Current chain:
1. prediction_id registry lookup
2. explicit confidence argument
3. monitor._prev_confidence

New chain:
1. prediction_id registry lookup
2. explicit confidence argument
3. monitor._prev_confidence
4. DB: most recent audit trail confidence for agent_id  ← NEW
5. None → skip e-process (unchanged)
```

### Implementation

In `handle_outcome_event()`, after the `_prev_confidence` fallback block (around line 198), add:

```python
if _confidence is None:
    try:
        latest = await db.get_latest_confidence_for_agent(agent_id)
        if latest is not None:
            _confidence = float(latest)
            prediction_source = prediction_source or "audit_trail_fallback"
    except Exception:
        pass
```

The `get_latest_confidence_for_agent()` method queries the audit trail for the most recent confidence value. This is a simple `SELECT confidence FROM agent_audit_log WHERE agent_id = $1 AND confidence IS NOT NULL ORDER BY timestamp DESC LIMIT 1`.

### Files to modify

- `src/mcp_handlers/observability/outcome_events.py` — add fallback step 4
- `src/db/postgres_backend.py` (or the active DB backend) — add `get_latest_confidence_for_agent()` query
- `tests/` — test the new fallback path

## Backfill: Replay Existing Outcomes

A one-time CLI script that:

1. Queries existing `outcome_events` from the DB where `outcome_type IN ('test_passed', 'test_failed')` and `eprocess_eligible = false` (or where `reported_confidence IS NULL` in the detail JSON)
2. For each, finds the nearest prior audit trail confidence for that agent
3. Feeds the (confidence, outcome_correct) pair into `sequential_calibration_tracker.record_exogenous_tactical_outcome()`
4. Saves the tracker state

### Location

`scripts/ops/backfill_calibration.py` — standalone script, no MCP dependency.

### Scope guard

- Only replays test_passed / test_failed outcomes (hard exogenous signals)
- Only pairs with confidence values from BEFORE the outcome timestamp (no future-leak)
- Logs each pairing for audit trail
- Dry-run mode by default

## What's NOT changing

- `outcome-tracker.sh` hook — already works correctly
- Watcher agent — not involved in calibration capture
- The sequential calibration tracker itself — already wired in outcome_events.py
- The `calibration(action='check')` query — already reads from the tracker

## Success criteria

- `calibration(action='check')` shows `tactical_evidence.eligible_samples > 0` after the fix
- New pytest runs automatically feed the e-process without agent cooperation
- Backfill populates historical data from existing outcome_events
