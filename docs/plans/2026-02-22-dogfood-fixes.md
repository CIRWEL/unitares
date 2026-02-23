# Dogfood Bug Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the top 10 bugs found by the dogfood squad (Archivist, Sentinel, Dialectician, Cartographer)

**Architecture:** Targeted fixes across error messages, input validation, loop detector, rate limiting, search, and tool schemas. No architectural changes — surgical corrections to existing code.

**Tech Stack:** Python 3, asyncio, PostgreSQL/AGE, Redis, MCP protocol

---

### Task 1: Fix recovery error messages — wrong tool names

All error messages that reference `self_recovery(action='resume')` or `direct_resume_if_safe` need updating to reference the actual tool actions: `self_recovery(action='quick')` and `self_recovery(action='review')`.

**Files:**
- Modify: `src/mcp_handlers/core.py:538`
- Modify: `src/mcp_handlers/core.py:780-784`
- Modify: `src/mcp_handlers/utils.py:185`
- Modify: `src/mcp_server_std.py:2186-2202`
- Modify: `src/mcp_handlers/dialectic.py:323,386,389,420,423,493`
- Modify: `src/mcp_handlers/self_recovery.py:387,391-393,529`
- Modify: `src/mcp_handlers/admin.py:1057-1060,1292,1321,1677`

**Step 1: Fix core.py line 538**

Change:
```python
"action": "Use self_recovery(action='resume') or wait for dialectic recovery to complete",
```
To:
```python
"action": "Use self_recovery(action='quick') for safe states, or self_recovery(action='review', reflection='...') for recovery with reflection",
```

**Step 2: Fix core.py lines 780-784**

Change:
```python
"related_tools": ["get_governance_metrics", "quick_resume", "self_recovery"],
```
To:
```python
"related_tools": ["get_governance_metrics", "self_recovery"],
```

Change:
```python
"3. Use quick_resume() if safe (coherence > 0.60, risk < 0.40), otherwise use self_recovery(action='resume')"
```
To:
```python
"3. Use self_recovery(action='quick') if safe (coherence > 0.60, risk < 0.40), otherwise use self_recovery(action='review', reflection='...')"
```

**Step 3: Fix utils.py line 185**

Change:
```python
"action": "Use self_recovery(action='resume') to request recovery",
```
To:
```python
"action": "Use self_recovery(action='quick') or self_recovery(action='review', reflection='...') to request recovery",
```

**Step 4: Fix mcp_server_std.py lines 2186-2202**

Replace the recovery_tools section:
```python
recovery_tools = []
if cooldown_seconds <= 5:
    recovery_tools.append("direct_resume_if_safe (if state is safe)")
else:
    recovery_tools.append("direct_resume_if_safe (if state is safe)")
    recovery_tools.append("request_dialectic_review (for peer assistance)")
```
With:
```python
recovery_tools = []
if cooldown_seconds <= 5:
    recovery_tools.append("self_recovery(action='quick') (if state is safe)")
else:
    recovery_tools.append("self_recovery(action='quick') or self_recovery(action='review', reflection='...') for recovery")
    recovery_tools.append("request_dialectic_review (for peer assistance)")
```

**Step 5: Fix dialectic.py references to direct_resume_if_safe**

Replace all `direct_resume_if_safe` references with `self_recovery(action='quick')` in:
- Line 323: description text
- Lines 386, 389: recovery suggestions
- Lines 420, 423: recovery suggestions
- Line 493: note text

**Step 6: Fix self_recovery.py line 387-393**

Change `self_recovery_review` references to `self_recovery(action='review')`:
```python
"action": "Use self_recovery(action='review', reflection='...') with reflection",
"example": 'self_recovery(action="review", reflection="I was stuck because...")',
"related_tools": ["self_recovery"],
```

**Step 7: Fix admin.py references**

Update `direct_resume_if_safe` references to `self_recovery(action='quick')`:
- Line 1292: recovery tool list
- Line 1321: tool description map
- Line 1677: lifecycle tools list

**Step 8: Run tests**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -x -q --timeout=30 2>&1 | tail -20`
Expected: All passing

**Step 9: Commit**

```bash
git add src/mcp_handlers/core.py src/mcp_handlers/utils.py src/mcp_server_std.py src/mcp_handlers/dialectic.py src/mcp_handlers/self_recovery.py src/mcp_handlers/admin.py
git commit -m "fix: update recovery error messages to reference correct self_recovery actions"
```

---

### Task 2: Fix operator_resume_agent schema mismatch

**Files:**
- Modify: `src/tool_schemas.py:4748-4757`

**Step 1: Fix schema parameter name**

Change:
```python
"agent_id": {
    "type": "string",
    "description": "Agent to resume"
},
```
To:
```python
"target_agent_id": {
    "type": "string",
    "description": "UUID of the agent to resume (target, not caller)"
},
```

And update required:
```python
"required": ["target_agent_id", "reason"]
```

**Step 2: Run tests**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -x -q --timeout=30 -k "operator" 2>&1 | tail -20`

**Step 3: Commit**

```bash
git add src/tool_schemas.py
git commit -m "fix: operator_resume_agent schema uses target_agent_id to match handler"
```

---

### Task 3: Fix loop detector — clear state after successful self_recovery

The core bug: `self_recovery(action='review')` resumes the agent but doesn't clear loop detector history. The stale pause timestamps then immediately re-trigger the detector.

**Files:**
- Modify: `src/mcp_handlers/self_recovery.py` (handle_quick_resume, around line 443-447)
- Modify: `src/mcp_handlers/lifecycle.py` (handle_self_recovery_review, find the resume section)
- Test: `tests/test_loop_detector_recovery.py` (new)

**Step 1: Write failing test**

Create `tests/test_loop_detector_recovery.py`:
```python
"""Test that self_recovery clears loop detector state."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta


@pytest.fixture
def agent_metadata_with_loop():
    """Create agent metadata that has loop detector state."""
    meta = MagicMock()
    meta.status = "paused"
    meta.paused_at = datetime.now().isoformat()
    meta.loop_cooldown_until = (datetime.now() + timedelta(seconds=30)).isoformat()
    meta.loop_detected_at = datetime.now().isoformat()
    meta.recent_update_timestamps = [
        (datetime.now() - timedelta(seconds=i)).isoformat()
        for i in range(5, 0, -1)
    ]
    meta.recent_decisions = ["pause", "pause", "pause", "proceed", "proceed"]
    meta.loop_incidents = [{"detected_at": datetime.now().isoformat(), "reason": "test"}]
    return meta


def test_clear_loop_state_helper():
    """Test the clear_loop_detector_state helper function."""
    from src.mcp_handlers.self_recovery import clear_loop_detector_state

    meta = MagicMock()
    meta.loop_cooldown_until = "2026-02-22T12:00:00"
    meta.loop_detected_at = "2026-02-22T12:00:00"
    meta.recent_update_timestamps = ["ts1", "ts2", "ts3"]
    meta.recent_decisions = ["pause", "pause", "proceed"]

    clear_loop_detector_state(meta)

    assert meta.loop_cooldown_until is None
    assert meta.loop_detected_at is None
    assert meta.recent_decisions == []
    assert meta.recent_update_timestamps == []
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_loop_detector_recovery.py -v 2>&1 | tail -20`
Expected: ImportError — `clear_loop_detector_state` doesn't exist yet

**Step 3: Implement clear_loop_detector_state helper**

Add to `src/mcp_handlers/self_recovery.py` near the top (after imports, before the first function):

```python
def clear_loop_detector_state(meta) -> None:
    """Clear loop detector state after successful recovery.

    This prevents the stale pause history from immediately re-triggering
    the loop detector after self_recovery succeeds.
    """
    meta.loop_cooldown_until = None
    meta.loop_detected_at = None
    meta.recent_update_timestamps = []
    meta.recent_decisions = []
```

**Step 4: Call it from handle_quick_resume (self_recovery.py ~line 445)**

After `meta.status = "active"` and `meta.paused_at = None`, add:
```python
clear_loop_detector_state(meta)
```

**Step 5: Call it from handle_self_recovery_review (lifecycle.py)**

Find where status is set to "active" after successful review, add:
```python
from .self_recovery import clear_loop_detector_state
clear_loop_detector_state(meta)
```

**Step 6: Run test to verify it passes**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_loop_detector_recovery.py -v`
Expected: PASS

**Step 7: Run full test suite**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -x -q --timeout=30 2>&1 | tail -20`

**Step 8: Commit**

```bash
git add src/mcp_handlers/self_recovery.py src/mcp_handlers/lifecycle.py tests/test_loop_detector_recovery.py
git commit -m "fix: clear loop detector state after successful self_recovery

Prevents permanent lockout where stale pause timestamps immediately
re-trigger the loop detector after recovery."
```

---

### Task 4: Validate empty response_text before state mutation

**Files:**
- Modify: `src/mcp_handlers/validators.py:1018-1019`

**Step 1: Write failing test**

Add to an existing test file or create `tests/test_empty_response_text.py`:
```python
"""Test that empty response_text is rejected."""
import pytest
from src.mcp_handlers.validators import validate_response_text


def test_empty_response_text_rejected():
    """Empty string response_text should return an error."""
    result, error = validate_response_text("")
    assert error is not None
    assert result is None


def test_whitespace_only_response_text_rejected():
    """Whitespace-only response_text should return an error."""
    result, error = validate_response_text("   \n\t  ")
    assert error is not None
    assert result is None


def test_none_response_text_returns_empty():
    """None response_text returns empty string (backward compat)."""
    result, error = validate_response_text(None)
    assert result == ""
    assert error is None


def test_valid_response_text_passes():
    """Normal response_text passes validation."""
    result, error = validate_response_text("Completed the audit task")
    assert result == "Completed the audit task"
    assert error is None
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_empty_response_text.py -v`
Expected: `test_empty_response_text_rejected` FAILS (currently returns `("", None)`)

**Step 3: Fix validate_response_text**

In `src/mcp_handlers/validators.py`, after the `if value is None:` check (line 1018-1019), add:

```python
if isinstance(value, str) and not value.strip():
    return None, error_response(
        "response_text cannot be empty. Provide a brief summary of what you did.",
        details={"error_type": "empty_value", "param_name": "response_text"},
        recovery={
            "action": "Provide a non-empty response_text describing your work",
            "example": 'process_agent_update(response_text="Completed code review", complexity=0.5)',
        }
    )
```

**Step 4: Run tests**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_empty_response_text.py -v`
Expected: All PASS

**Step 5: Run full test suite** (some existing tests may send empty response_text)

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -x -q --timeout=30 2>&1 | tail -20`
Fix any tests that relied on empty response_text being accepted.

**Step 6: Commit**

```bash
git add src/mcp_handlers/validators.py tests/test_empty_response_text.py
git commit -m "fix: reject empty response_text before state mutation

Prevents empty strings from cascading into zero-quality processing,
risk spikes, and circuit breaker activation."
```

---

### Task 5: Add search_knowledge_graph to rate limit exemption

**Files:**
- Modify: `src/mcp_handlers/middleware.py:428`

**Step 1: Add to read_only_tools set**

Change:
```python
read_only_tools = {'health_check', 'get_server_info', 'list_tools', 'get_thresholds'}
```
To:
```python
read_only_tools = {'health_check', 'get_server_info', 'list_tools', 'get_thresholds', 'search_knowledge_graph', 'get_governance_metrics'}
```

**Step 2: Run tests**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -x -q --timeout=30 -k "rate_limit or middleware" 2>&1 | tail -20`

**Step 3: Commit**

```bash
git add src/mcp_handlers/middleware.py
git commit -m "fix: exempt search_knowledge_graph and get_governance_metrics from rate limiting

Read-only tools should not count toward circuit breaker thresholds.
Audit/dogfood workloads naturally involve many reads."
```

---

### Task 6: Fix single-term search falling back to broken substring_scan

Single-word queries should use semantic search when available, not fall back to substring_scan.

**Files:**
- Modify: `src/mcp_handlers/knowledge_graph.py:520-523`

**Step 1: Fix auto-detect logic**

Change:
```python
# Auto-detect: use semantic for multi-word queries when available
query_words = len(str(query_text).split())
use_semantic = has_semantic and query_words >= 2
```
To:
```python
# Auto-detect: use semantic search when available for any text query
# Single-word queries benefit from semantic search too (substring_scan
# is limited to 50 recent entries and misses most results)
use_semantic = has_semantic
```

**Step 2: Run tests**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -x -q --timeout=30 -k "knowledge_graph or search" 2>&1 | tail -20`

**Step 3: Commit**

```bash
git add src/mcp_handlers/knowledge_graph.py
git commit -m "fix: use semantic search for single-word queries when available

substring_scan only checks 50 recent entries and returns 0 results
for most single-term queries. Semantic search handles these correctly."
```

---

### Task 7: Fix loop detector cooldown not resetting on rejected retries

When `detect_loop_pattern` finds an existing cooldown active (line 1854-1858), it correctly returns the remaining time. But when it detects a NEW loop pattern (lines 2138-2151), it unconditionally sets a NEW cooldown — even if the agent was retrying after the previous cooldown expired. The problem: the stale pause timestamps in `recent_decisions` trigger a new pattern detection.

This is already fixed by Task 3 (clearing state on recovery). But we also need to prevent cooldown reset on re-detection when the agent hasn't actually done anything new.

**Files:**
- Modify: `src/mcp_server_std.py:2118-2125`

**Step 1: Don't set new cooldown if one is already active**

The current code at line 2123-2136 already handles active cooldowns by returning remaining time without setting a new one. Verify this is working correctly by checking that the existing cooldown check (line 1854-1858) runs BEFORE the pattern detection.

This should already be correct — the cooldown check at 1854 returns early if active. The real issue is the stale timestamps causing re-detection AFTER cooldown expires, which Task 3 fixes.

No additional code change needed here — Task 3's `clear_loop_detector_state` is the proper fix.

**Step 2: Verify with tests from Task 3**

---

### Task 8: Run full test suite and verify

**Step 1: Run all tests**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -x -q --timeout=30 2>&1 | tail -30`
Expected: All passing (same count as before, ~5727)

**Step 2: Restart governance service to pick up changes**

Run:
```bash
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

**Step 3: Verify service is running**

Run: `curl -s http://localhost:8767/mcp/ | head -5`

---

### Task 9: Second dogfood wave

Launch a new round of dogfooding agents to verify the fixes work and find any remaining issues.
