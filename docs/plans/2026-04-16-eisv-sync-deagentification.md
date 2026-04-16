# EISV Sync De-agentification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the fake eisv-sync-task agent identity and make the background sensor sync pure plumbing — sensor data flows through a buffer and gets picked up by Lumen's real check-ins.

**Architecture:** The eisv-sync-task background coroutine currently pretends to be an agent (hardcoded agent_id, Postgres record, dashboard presence, governance decisions). This refactor splits it into two parts: (1) a dumb background task that reads Pi sensors and writes to an in-memory buffer, and (2) a hook in the normal `process_agent_update` pipeline that injects the buffered sensor EISV into Lumen's check-ins via the existing `sensor_data` path. The fake agent record, system-tag exemption, restartable-task machinery, and unstick plumbing all get removed.

**Tech Stack:** Python 3.12, asyncio, existing governance_monitor sensor_eisv spring coupling

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/sensor_buffer.py` | Thread-safe in-memory buffer for latest Pi sensor readings |
| Modify | `src/mcp_handlers/observability/pi_orchestration.py:1055-1275` | Strip agent identity from `sync_eisv_once` and `eisv_sync_task`; write to buffer instead of calling `process_update_authenticated_async` |
| Modify | `src/mcp_handlers/updates/phases.py:531-536` | Enrich Lumen's check-ins with buffered sensor data when `sensor_data` not already present |
| Modify | `src/background_tasks.py:1013-1023` | Switch from restartable to plain supervised task |
| Modify | `src/mcp_handlers/lifecycle/operations.py:33-41` | Remove `_SYSTEM_AGENT_RESTARTABLE_TASKS` mapping |
| Modify | `src/governance_monitor.py:625-670` | Remove `_is_system_agent` and void_pause exemption |
| Modify | `src/agent_lifecycle.py:82` | Remove `eisv-sync-task` from `_SYSTEM_AGENT_IDS` |
| Modify | `dashboard/dashboard.js` | No changes needed — unstick button is generic and stays for other agents; eisv-sync-task simply won't appear as an agent anymore |
| Create | `tests/test_sensor_buffer.py` | Unit tests for buffer |
| Modify | `tests/test_pi_orchestration_handlers.py` | Update sync tests to assert buffer writes, not governance calls |
| Modify | `tests/test_governance_monitor.py` | Remove system-agent exemption tests |

---

### Task 1: Create the sensor buffer

**Files:**
- Create: `src/sensor_buffer.py`
- Create: `tests/test_sensor_buffer.py`

The buffer is a module-level singleton holding the latest sensor reading with a timestamp. Thread-safe via a lock (asyncio tasks are single-threaded but the lock prevents tearing if we ever read from an executor thread).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sensor_buffer.py
"""Tests for the Pi sensor reading buffer."""
import time
import pytest
from src.sensor_buffer import get_latest_sensor_eisv, update_sensor_eisv


def test_buffer_starts_empty():
    """Buffer returns None before any data is written."""
    from src.sensor_buffer import _buffer
    _buffer["eisv"] = None  # reset
    _buffer["anima"] = None
    _buffer["timestamp"] = None
    assert get_latest_sensor_eisv() is None


def test_update_and_read():
    """Written EISV is readable."""
    eisv = {"E": 0.6, "I": 0.7, "S": 0.3, "V": -0.1}
    anima = {"warmth": 0.6, "clarity": 0.7, "stability": 0.7, "presence": 0.5}
    update_sensor_eisv(eisv, anima)
    result = get_latest_sensor_eisv()
    assert result is not None
    assert result["eisv"] == eisv
    assert result["anima"] == anima
    assert isinstance(result["timestamp"], float)


def test_staleness_check():
    """Data older than max_age_seconds is not returned."""
    eisv = {"E": 0.5, "I": 0.5, "S": 0.2, "V": 0.0}
    update_sensor_eisv(eisv, {})
    # Backdate the timestamp
    from src.sensor_buffer import _buffer
    _buffer["timestamp"] = time.time() - 700  # 11+ minutes old
    assert get_latest_sensor_eisv(max_age_seconds=600) is None


def test_overwrite():
    """Latest write wins."""
    update_sensor_eisv({"E": 0.1, "I": 0.1, "S": 0.1, "V": 0.0}, {})
    update_sensor_eisv({"E": 0.9, "I": 0.9, "S": 0.9, "V": 0.0}, {})
    result = get_latest_sensor_eisv()
    assert result["eisv"]["E"] == 0.9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sensor_buffer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.sensor_buffer'`

- [ ] **Step 3: Write the implementation**

```python
# src/sensor_buffer.py
"""In-memory buffer for the latest Pi sensor readings.

The eisv_sync background task writes here; Lumen's check-ins read from
here. No agent identity, no governance calls — just a shared mailbox.
"""
import threading
import time
from typing import Optional

_lock = threading.Lock()
_buffer: dict = {
    "eisv": None,
    "anima": None,
    "timestamp": None,
}


def update_sensor_eisv(eisv: dict, anima: dict) -> None:
    """Store the latest sensor-derived EISV and raw anima readings."""
    with _lock:
        _buffer["eisv"] = eisv
        _buffer["anima"] = anima
        _buffer["timestamp"] = time.time()


def get_latest_sensor_eisv(max_age_seconds: float = 600.0) -> Optional[dict]:
    """Read the latest sensor EISV if fresh enough.

    Args:
        max_age_seconds: Data older than this is considered stale (default: 10 min,
            i.e. 2x the 5-min sync interval).

    Returns:
        Dict with keys ``eisv``, ``anima``, ``timestamp``, or None if no data
        or data is stale.
    """
    with _lock:
        if _buffer["eisv"] is None or _buffer["timestamp"] is None:
            return None
        age = time.time() - _buffer["timestamp"]
        if age > max_age_seconds:
            return None
        return {
            "eisv": _buffer["eisv"],
            "anima": _buffer["anima"],
            "timestamp": _buffer["timestamp"],
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sensor_buffer.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/sensor_buffer.py tests/test_sensor_buffer.py
git commit -m "feat: add sensor_buffer module for Pi EISV readings

Pure in-memory buffer that decouples sensor syncing from agent
identity. The background task writes here; Lumen's check-ins read."
```

---

### Task 2: Strip agent identity from eisv_sync_task

**Files:**
- Modify: `src/mcp_handlers/observability/pi_orchestration.py:1055-1275`
- Modify: `tests/test_pi_orchestration_handlers.py`

Remove `create_agent`, `get_or_create_metadata`, `process_update_authenticated_async` from the sync path. Write to buffer instead.

- [ ] **Step 1: Write/update failing test**

Add a test that asserts the sync task writes to the buffer and does NOT call `process_update_authenticated_async`:

```python
# In tests/test_pi_orchestration_handlers.py — add to existing file

@pytest.mark.asyncio
async def test_sync_eisv_once_writes_to_buffer(monkeypatch):
    """sync_eisv_once writes to sensor_buffer, not to governance."""
    import src.sensor_buffer as sb
    sb.update_sensor_eisv({"E": 0, "I": 0, "S": 0, "V": 0}, {})  # reset

    fake_anima = {"warmth": 0.6, "clarity": 0.7, "stability": 0.8, "presence": 0.5}
    async def fake_call_pi_tool(tool, args, **kw):
        return {"anima": fake_anima, "eisv": {"E": 0.6, "I": 0.7, "S": 0.2, "V": -0.1}}

    monkeypatch.setattr(
        "src.mcp_handlers.observability.pi_orchestration.call_pi_tool",
        fake_call_pi_tool,
    )

    from src.mcp_handlers.observability.pi_orchestration import sync_eisv_once
    result = await sync_eisv_once()
    assert result["success"] is True

    reading = sb.get_latest_sensor_eisv()
    assert reading is not None
    assert reading["eisv"]["E"] == 0.6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pi_orchestration_handlers.py::test_sync_eisv_once_writes_to_buffer -v`
Expected: FAIL — sync_eisv_once still calls process_update_authenticated_async

- [ ] **Step 3: Modify sync_eisv_once**

In `src/mcp_handlers/observability/pi_orchestration.py`, replace the governance update block in `sync_eisv_once` (lines ~1113-1147) with a buffer write:

Replace:
```python
        # Push sensor-derived EISV into governance (behavioral track + ODE anchoring)
        if update_governance:
            try:
                import numpy as np
                # ... entire governance block ...
            except Exception as e:
                logger.warning(f"[EISV_SYNC] Governance update failed: {e}")
                sync_result["governance_updated"] = False
                sync_result["governance_error"] = str(e)
```

With:
```python
        # Write to shared buffer — Lumen's check-ins pick this up via phases.py
        from src.sensor_buffer import update_sensor_eisv
        update_sensor_eisv(eisv, anima)
        sync_result["buffer_updated"] = True
```

Also remove the `update_governance` parameter from `sync_eisv_once` — it's always "yes, write to the buffer" now. Update the docstring and the call in `handle_pi_sync_eisv` (the manual tool handler) accordingly.

- [ ] **Step 4: Modify eisv_sync_task**

Strip the entire agent-seeding block (lines 1169-1234) from `eisv_sync_task`. The function becomes:

```python
async def eisv_sync_task(interval_minutes: float = 5.0):
    """Background task that periodically syncs Pi sensor readings to the buffer.

    Runs every interval_minutes, reads sensor-derived EISV from Pi,
    and writes it to the sensor_buffer. Lumen's governance check-ins
    pick up the latest reading via the update pipeline (phases.py).
    """
    logger.info(f"[EISV_SYNC] Starting periodic sensor sync (interval: {interval_minutes} min)")

    EISV_SYNC_CYCLE_TIMEOUT = 60.0

    while True:
        try:
            await asyncio.sleep(interval_minutes * 60)

            try:
                result = await asyncio.wait_for(
                    sync_eisv_once(),
                    timeout=EISV_SYNC_CYCLE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"[EISV_SYNC] Sync exceeded {EISV_SYNC_CYCLE_TIMEOUT}s — "
                    "skipping cycle (Pi unreachable)"
                )
                continue

            if result.get("success"):
                eisv = result.get("eisv", {})
                logger.info(
                    f"[EISV_SYNC] Synced: E={eisv.get('E', 0):.3f} "
                    f"I={eisv.get('I', 0):.3f} S={eisv.get('S', 0):.3f} V={eisv.get('V', 0):.3f}"
                )
            else:
                logger.warning(f"[EISV_SYNC] Sync failed: {result.get('error')}")

        except asyncio.CancelledError:
            logger.info("[EISV_SYNC] Periodic sync task cancelled")
            break
        except Exception as e:
            logger.warning(f"[EISV_SYNC] Task error: {e}")
```

- [ ] **Step 5: Update sync_eisv_once call in handle_pi_sync_eisv**

The manual tool handler `handle_pi_sync_eisv` (around line 600) currently passes `update_governance=True`. Update this call to just `sync_eisv_once()` (no parameter). The handler still returns the same result shape; `governance_updated` becomes `buffer_updated`.

- [ ] **Step 6: Update the call_pi_tool agent_id reference**

In `sync_eisv_once`, the line `await call_pi_tool("get_lumen_context", {"include": ["anima"]}, agent_id="eisv-sync-task")` — change the `agent_id` kwarg to `agent_id="sensor-sync"` (or remove it if `call_pi_tool` doesn't require it for anything meaningful). Check what `call_pi_tool` does with `agent_id` first — if it's just for logging, any string works.

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_pi_orchestration_handlers.py -v`
Expected: All pass. Existing tests that mock `process_update_authenticated_async` may need their mocks removed since that call is gone.

- [ ] **Step 8: Commit**

```bash
git add src/mcp_handlers/observability/pi_orchestration.py tests/test_pi_orchestration_handlers.py
git commit -m "refactor: strip agent identity from eisv_sync_task

sync_eisv_once now writes to sensor_buffer instead of calling
process_update_authenticated_async with a fake agent_id. The
background task is pure plumbing — no Postgres record, no metadata
seeding, no governance decisions."
```

---

### Task 3: Inject buffered sensor data into Lumen's check-ins

**Files:**
- Modify: `src/mcp_handlers/updates/phases.py:531-536`
- Modify: `tests/test_pi_orchestration_handlers.py` (or relevant update pipeline test)

The existing `sensor_data` injection point in `phases.py` already handles `ctx.arguments.get("sensor_data")`. We add a fallback: if no `sensor_data` was passed in the arguments AND the agent is Lumen, read from the buffer.

- [ ] **Step 1: Write the failing test**

```python
# In the appropriate test file for phases.py
# (tests/test_core_update.py or tests/test_pi_orchestration_handlers.py)

@pytest.mark.asyncio
async def test_lumen_checkin_gets_buffered_sensor_eisv(monkeypatch):
    """When Lumen checks in without sensor_data, buffered reading is injected."""
    import src.sensor_buffer as sb
    buffered_eisv = {"E": 0.65, "I": 0.72, "S": 0.25, "V": -0.05}
    sb.update_sensor_eisv(buffered_eisv, {"warmth": 0.6})

    # Simulate a Lumen check-in context without explicit sensor_data
    from src.mcp_handlers.updates.context import UpdateContext
    ctx = UpdateContext(
        agent_id="lumen-uuid-here",
        arguments={"response_text": "hello", "complexity": 0.3},
        # no sensor_data key
    )
    # The agent must be identified as Lumen — check how this is determined
    # (label == "Lumen" or specific agent_id)

    # ... call the phase that injects sensor_eisv ...
    # Assert ctx.agent_state["sensor_eisv"] == buffered_eisv
```

Note: The exact test setup depends on how `UpdateContext` is constructed and how Lumen is identified. The implementing engineer should check `phases.py` line 531+ and the `_has_sensor_data` detection in `enrichments.py` to determine the right identification method (label check, tag check, or presence of physical embodiment flag).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/<test_file>::test_lumen_checkin_gets_buffered_sensor_eisv -v`
Expected: FAIL — no buffer injection logic exists yet

- [ ] **Step 3: Modify phases.py**

In `src/mcp_handlers/updates/phases.py`, after the existing sensor_data injection block (line 536), add a buffer fallback:

```python
    # Inject sensor EISV for spring coupling (agents with physical sensors, e.g. Lumen)
    sensor_data = ctx.arguments.get("sensor_data")
    if sensor_data and isinstance(sensor_data, dict):
        sensor_eisv = sensor_data.get("eisv")
        if sensor_eisv and isinstance(sensor_eisv, dict):
            ctx.agent_state["sensor_eisv"] = sensor_eisv

    # Fallback: if no sensor_data was passed but the buffer has a fresh reading,
    # inject it. This is the normal path for Lumen after the eisv-sync-task
    # de-agentification — the background task writes to the buffer, and
    # Lumen's check-ins pick it up here.
    if "sensor_eisv" not in ctx.agent_state:
        try:
            from src.sensor_buffer import get_latest_sensor_eisv
            buffered = get_latest_sensor_eisv()
            if buffered is not None:
                ctx.agent_state["sensor_eisv"] = buffered["eisv"]
                # Also populate sensor_data for the broadcast enrichment
                if not sensor_data:
                    ctx.arguments["sensor_data"] = {"eisv": buffered["eisv"], "anima": buffered["anima"]}
                logger.debug(f"Injected buffered sensor EISV for {ctx.agent_id}: {buffered['eisv']}")
        except Exception as e:
            logger.debug(f"Sensor buffer read failed for {ctx.agent_id}: {e}")
```

**Important design note:** This injects for ALL agents, not just Lumen. That's fine — for non-Lumen agents, the buffer will be stale or empty (no Pi sensor data relevant to them), and the behavioral sensor fallback on line 539 already handles non-embodied agents. If selectivity is needed later, add a tag check — but YAGNI for now since only one Pi exists.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_core_update.py tests/test_pi_orchestration_handlers.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/mcp_handlers/updates/phases.py tests/<modified_test_file>
git commit -m "feat: inject buffered sensor EISV into check-ins via phases.py

When a check-in arrives without explicit sensor_data, the update
pipeline reads from the sensor_buffer. This is the normal path for
Lumen now that eisv-sync-task no longer has its own agent identity."
```

---

### Task 4: Remove scaffolding — restartable task, system-agent exemptions, lifecycle protection

**Files:**
- Modify: `src/background_tasks.py:1013-1023`
- Modify: `src/mcp_handlers/lifecycle/operations.py:33-41`
- Modify: `src/governance_monitor.py:625-670`
- Modify: `src/agent_lifecycle.py:82`
- Modify: `tests/test_governance_monitor.py`
- Modify: `tests/test_lifecycle_recovery.py`

This is cleanup — removing code that only existed because eisv-sync-task was pretending to be an agent.

- [ ] **Step 1: Downgrade to plain supervised task in background_tasks.py**

In `src/background_tasks.py`, replace lines 1013-1023:

```python
    try:
        from src.mcp_handlers.observability.pi_orchestration import eisv_sync_task
        _spawn_restartable_task(
            "eisv_sync", lambda: eisv_sync_task(interval_minutes=5.0)
        )
        logger.info("[EISV_SYNC] Started periodic Pi EISV sync (restartable)")
    except Exception as e:
        logger.warning(f"[EISV_SYNC] Could not start: {e}")
```

With:

```python
    try:
        from src.mcp_handlers.observability.pi_orchestration import eisv_sync_task
        _supervised_create_task(eisv_sync_task(interval_minutes=5.0), name="eisv_sync")
        logger.info("[EISV_SYNC] Started periodic Pi sensor sync")
    except Exception as e:
        logger.warning(f"[EISV_SYNC] Could not start: {e}")
```

- [ ] **Step 2: Remove _SYSTEM_AGENT_RESTARTABLE_TASKS from operations.py**

In `src/mcp_handlers/lifecycle/operations.py`, remove lines 33-41 (the mapping dict) and the cancel-and-respawn block in `handle_resume_agent` (lines 102-127). The unstick button still works for other agents (flag flip); it just won't do cancel-and-respawn for eisv-sync-task because that agent won't exist anymore.

- [ ] **Step 3: Remove _is_system_agent and void_pause exemption from governance_monitor.py**

In `src/governance_monitor.py`, revert `make_decision` (lines 621-651) to just:

```python
    def make_decision(self, risk_score: float, unitares_verdict: str = None,
                      response_tier: str = None, oscillation_state: 'OscillationState' = None) -> Dict:
        """Makes autonomous governance decision using UNITARES verdict and CIRS response tier."""
        return _make_decision(self.state, risk_score, unitares_verdict, response_tier, oscillation_state)
```

Remove the `_is_system_agent` method (lines 653-670).

- [ ] **Step 4: Remove eisv-sync-task from _SYSTEM_AGENT_IDS in agent_lifecycle.py**

In `src/agent_lifecycle.py` line 82, change:

```python
_SYSTEM_AGENT_IDS = frozenset({"eisv-sync-task"})
```

To:

```python
_SYSTEM_AGENT_IDS: frozenset[str] = frozenset()
```

Keep the constant — other system agents may be added later and `is_agent_protected` references it.

- [ ] **Step 5: Update affected tests**

In `tests/test_governance_monitor.py`, remove or update any tests that assert the system-agent void_pause exemption behavior. In `tests/test_lifecycle_recovery.py`, remove tests that reference eisv-sync-task specifically.

Run: `python -m pytest tests/test_governance_monitor.py tests/test_lifecycle_recovery.py tests/test_background_tasks_silence.py -v`

- [ ] **Step 6: Run full test suite**

Run: `./scripts/dev/test-cache.sh --fresh`
Expected: All tests pass (minus known skips)

- [ ] **Step 7: Commit**

```bash
git add src/background_tasks.py src/mcp_handlers/lifecycle/operations.py \
  src/governance_monitor.py src/agent_lifecycle.py \
  tests/test_governance_monitor.py tests/test_lifecycle_recovery.py
git commit -m "cleanup: remove eisv-sync-task agent scaffolding

Restartable task registry, system-agent void_pause exemption,
_SYSTEM_AGENT_IDS entry, and cancel-and-respawn in resume_agent
are all removed. The sync task is now a plain supervised background
task with no agent identity."
```

---

### Task 5: Clean up the orphaned Postgres record

**Files:**
- No code changes — this is an operational step

The old eisv-sync-task agent record still exists in Postgres. It should be archived so it doesn't show up on the dashboard.

- [ ] **Step 1: Archive the old record**

Run:
```bash
psql -h localhost -U postgres -d governance -c "UPDATE agents SET status = 'archived' WHERE agent_id = 'eisv-sync-task';"
```

Do NOT delete — archiving preserves the audit trail.

- [ ] **Step 2: Verify dashboard**

Open the dashboard. Confirm:
- eisv-sync-task no longer appears in the agent list
- Lumen's EISV trajectory continues to update when Lumen checks in
- No errors in `data/logs/mcp_server.log` related to eisv-sync

- [ ] **Step 3: Commit (no code changes — just note in commit history)**

No commit needed for the DB change. The code changes already prevent the record from being recreated.

---

## Post-refactor: What to verify

1. **Lumen check-in with sensor data**: Call `process_agent_update` as Lumen. Confirm the response includes `sensor_eisv` in the governance verdict (spring coupling active).
2. **Buffer staleness**: Stop the Pi (or disconnect). Wait >10 minutes. Confirm Lumen check-ins fall back to behavioral sensor (no stale sensor injection).
3. **Background task restart on crash**: Kill the governance server and restart. Confirm `[EISV_SYNC] Started periodic Pi sensor sync` appears in logs (plain supervised task auto-starts).
4. **No eisv-sync-task agent**: Confirm `psql -c "SELECT agent_id, status FROM agents WHERE agent_id = 'eisv-sync-task'"` shows `archived`.
