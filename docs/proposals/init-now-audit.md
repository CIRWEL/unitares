# `__init__`-sets-now Audit — Follow-up to PR #224

**Status**: Audit complete, no changes implemented  
**Date**: 2026-05-11  
**Context**: PR #224 deferred task #8  
**Operator action required**: Review findings; approve fixes before implementation

## Audit Scope

Broadest grep across the two files named in the PR:

```
grep -nE 'self\.\w+ = (datetime\.now\(\)|time\.monotonic\(\))' \
    src/governance_monitor.py src/dual_log/*.py
```

Plus manual trace of `_prev_checkin_time` (written in the delegated `src/monitor_calibration.py`, not in `__init__`).

---

## Findings

### MEDIUM — `created_at` not persisted across restart

**File**: `src/governance_monitor.py`  
**Lines**: `_initialize_fresh_state()` — `self.created_at = datetime.now()`;  
`load_persisted_state()` fallback — `if not hasattr(self, 'created_at'): self.created_at = datetime.now()`

**Mechanism**: `__init__` calls `load_persisted_state()` *before* `created_at` is assigned anywhere (it is only set inside `_initialize_fresh_state()`, which is *not* called when state loads successfully). When state IS found on disk, `hasattr(self, 'created_at')` is `False` and the fallback fires, setting `created_at = datetime.now()` — the restart wall clock, not the original creation time. `save_persisted_state()` does not write `created_at` to the JSON file.

**Cross-restart**: Yes. Every server restart resets `created_at` to the current time for every agent whose state file exists.

**User-visible effect**: Agent "age" (time since first check-in) resets on every restart. Any metric derived from `created_at` — agent maturity for calibration gating, age-in-dashboard displays — understates agent age after restart. For long-lived resident agents (Lumen, Vigil, Sentinel) this means perceived maturity never accumulates past one server uptime period.

**Test coverage**: `tests/test_created_at_fix.py` does **not exist** (zero search results across the repo). No test pins this behavior.

**Fix sketch** (do not implement without approval): Add `created_at_iso` to the `save_persisted_state` JSON payload, symmetric with `last_update_iso` from PR #224. In `load_persisted_state`, restore it explicitly before the `hasattr` fallback — the fallback then fires only for state files that predate the fix (backward compat preserved).

---

### N/A — `_prev_checkin_time` init value is already correct

**File**: `src/governance_monitor.py` `__init__`  
**Current value**: `self._prev_checkin_time: Optional[float] = None`  
**Actual writer**: `src/monitor_calibration.py` — `monitor._prev_checkin_time = _time.monotonic()`

**Status**: The PR description mentioned "line 158 — `_prev_checkin_time = time.monotonic()`" but the current code initializes to `None`. The `None` sentinel is correct: it causes `elapsed_since_prev = float('inf')`, satisfying the 10-second guard in `run_calibration_recording`, but the outer check `monitor._prev_verdict_action is not None` is also `False` on restart, so no spurious calibration signal fires. `time.monotonic()` is only used for within-process elapsed time (the 10s rapid-fire guard); its value is process-local by design.

**Cross-restart**: Behaves correctly. No action needed.

---

### LOW — `ContinuityLayer` previous-session state not persisted without Redis

**File**: `src/dual_log/continuity.py` — `ContinuityLayer.__init__`  
**Fields**: `_prev_session_id`, `_prev_timestamp`, `_prev_derived_complexity`, `_prev_topic_hash`  
**Call site**: `UNITARESMonitor.__init__` — `ContinuityLayer(agent_id=agent_id, redis_client=None)`

**Mechanism**: `_load_state()` and `_save_state()` are no-ops when `redis_client=None`. All four tracking fields stay at `None` / `0.0` through restart.

**Cross-restart**: `_prev_timestamp = None` → `is_session_continuation = False` for the first check-in after every restart → `S_input += 0.1` (the "new session" uncertainty penalty in `compute_continuity_metrics`). Rate-of-change complexity divergence starts at `0.0` and self-corrects after one cycle.

**User-visible effect**: First check-in after restart gets a modest false uncertainty signal (+0.1 S_input). For agents with infrequent restarts the effect is invisible. For agents with frequent restarts (e.g., during development cycles) it could slightly bias S upward systematically.

**Fix sketch** (do not implement without approval): Option (a) wire a Redis client from environment into `ContinuityLayer`; option (b) add a JSON sidecar persistence path for `_prev_session_id` and `_prev_timestamp`, mirroring the `last_update_iso` pattern. Option (a) should be evaluated together with the broader Redis-or-not architectural question for the dual-log layer.

---

### LOW — `RestorativeBalanceMonitor` activity window not persisted without Redis

**File**: `src/dual_log/restorative.py` — `RestorativeBalanceMonitor.__init__`  
**Fields**: `_timestamps: List[datetime]`, `_divergences: List[float]`  
**Call site**: `UNITARESMonitor.__init__` — `RestorativeBalanceMonitor(agent_id=agent_id, redis_client=None)`

**Mechanism**: Same Redis-or-nothing pattern. The 5-minute rolling window and divergence accumulator reset to empty on restart.

**Cross-restart**: Activity rate and cumulative divergence start at zero after every restart. An agent that was in a high-activity or high-divergence state before restart does not trigger the restorative balance check on the first few post-restart check-ins.

**User-visible effect**: Overloaded agents that restart get a brief false-clean window from the restorative balance check. Since this is an advisory signal (no hard governance gate), operational impact is low.

**Fix sketch** (do not implement without approval): Wire Redis (same path as `ContinuityLayer`), or accept this behavior as acceptable for the advisory-only use case. The 5-minute window resets are self-healing regardless.

---

## Broader Grep Results — `governance_monitor.py`

| Assignment | Clock | Status |
|---|---|---|
| `self.last_update = datetime.now()` in `__init__` (~line 130) | wall | **FIXED by PR #224** (persisted via `last_update_iso`) |
| `self.last_update = datetime.now()` in `_initialize_fresh_state()` | wall | Correct — fresh-state path only |
| `self.created_at = datetime.now()` in `_initialize_fresh_state()` | wall | **Not persisted — MEDIUM finding above** |
| `self._prev_checkin_time = None` in `__init__` | — | Correct (`None` sentinel) |

`src/dual_log/*.py`: No `datetime.now()` or `time.monotonic()` assignments in any `__init__`. Fields are initialized to `None`/`[]` and populated from Redis (no-op without client).

---

## Summary

| Finding | File | Severity | Cross-restart bug? | Needs approval? |
|---|---|---|---|---|
| `created_at` not persisted | `src/governance_monitor.py` | **MEDIUM** | Yes | Yes — fix is small and well-scoped |
| `_prev_checkin_time` init value | `src/governance_monitor.py` | N/A | Already correct | No action needed |
| `ContinuityLayer` state (no Redis) | `src/dual_log/continuity.py` | LOW | Yes (soft S bias) | Needs Redis wiring decision |
| `RestorativeBalanceMonitor` window | `src/dual_log/restorative.py` | LOW | Yes (advisory reset) | Low urgency; tied to Redis decision |

The one item ready for a small follow-up PR is `created_at` persistence — the pattern is established by PR #224 and the fix is 3–4 lines symmetric with `last_update_iso`.

---

*Filed 2026-05-11 as follow-up to PR #224, task #8. No runtime changes made.*
