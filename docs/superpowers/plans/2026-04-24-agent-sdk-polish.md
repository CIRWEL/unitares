# Agent SDK Polish — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `GovernanceAgent` (in `agents/sdk/src/unitares_sdk/agent.py`) from "usable base class" to "ergonomic plug-and-play template" — a third-party human or AI agent should be able to subclass it and get a production-quality resident in ~30 lines, without overriding any private methods.

**Architecture:** Keep the subclass contract (`run_cycle` returns `CycleResult`) unchanged. Add three constructor knobs (`cycle_timeout_seconds`, `log_file`, `state_file`) and two post-cycle hooks (`on_after_checkin`, `on_verdict_pause`) so customization happens by **extension**, not **override**. Migrate vigil, sentinel, and chronicler onto the new surface to prove it. Ship a `agents/sdk/README.md` walkthrough.

**Tech Stack:** Python 3.12, asyncio, pytest with pytest-asyncio. SDK package is `unitares_sdk` at `agents/sdk/src/unitares_sdk/`. Tests at `agents/sdk/tests/`.

**Scope boundary:** This plan does **not** touch watcher (sync/hook-driven execution model, separate Phase 2 plan) and does **not** introduce a scaffolding CLI (Phase 3 if demand materializes). This plan only touches `agents/sdk/`, `agents/vigil/`, `agents/sentinel/`, `agents/chronicler/`.

**Invariants preserved:**
- `RESIDENT_TAGS` stays `["persistent", "autonomous"]` — do not change
- `refuse_fresh_onboard=True` gate stays intact
- UUID-based identity resolution flow in `_ensure_identity` unchanged
- Existing `run_once()` / `run_forever()` signatures backward-compatible (new params must have defaults)

---

## File Structure

| File | Role | Change |
|---|---|---|
| `agents/sdk/src/unitares_sdk/agent.py` | Base class | Add params + hooks |
| `agents/sdk/tests/test_agent.py` | Base class tests | Add tests for each new surface |
| `agents/sdk/README.md` | Third-party onboarding | **Create** — minimal example + hook reference |
| `agents/vigil/agent.py` | Reference resident | Delete `_handle_cycle_result` + `run_once` overrides; wire hooks |
| `agents/sentinel/agent.py` | Reference resident | Delete `_handle_cycle_result` + `_bounded_analysis_cycle`; wire hooks |
| `agents/chronicler/agent.py` | Reference resident | Wire `log_file` + `cycle_timeout_seconds` (no hook override needed) |

---

## Task 1: Add `cycle_timeout_seconds` to `GovernanceAgent`

**Files:**
- Modify: `agents/sdk/src/unitares_sdk/agent.py:81-140` (constructor and run_once)
- Test: `agents/sdk/tests/test_agent.py` (add to end)

**Context:** Vigil and Sentinel both wrap `super().run_once()` in `asyncio.wait_for(..., CYCLE_TIMEOUT)` to prevent a stuck MCP session from hanging the agent forever. Sentinel even has a comment (sentinel/agent.py:617) explaining why `asyncio.wait_for` is required over `anyio.fail_after` (cancel-scope mismatch with MCP's task group). That behavior belongs in the base class.

- [ ] **Step 1: Write the failing test**

Append to `agents/sdk/tests/test_agent.py`:

```python
class TestCycleTimeout:
    async def test_cycle_timeout_fires(self):
        """run_once raises TimeoutError if the cycle exceeds cycle_timeout_seconds."""

        class SlowAgent(GovernanceAgent):
            async def run_cycle(self, client):
                await asyncio.sleep(10.0)
                return CycleResult.simple("never reached")

        agent = SlowAgent(
            name="Slow",
            mcp_url="http://127.0.0.1:9999/mcp/",
            cycle_timeout_seconds=0.05,
        )
        # Bypass network: patch the client context manager and identity
        with patch("unitares_sdk.agent.GovernanceClient") as mock_cm:
            mock_client = AsyncMock()
            mock_cm.return_value.__aenter__.return_value = mock_client
            mock_cm.return_value.__aexit__.return_value = None
            with patch.object(SlowAgent, "_ensure_identity", AsyncMock()):
                with pytest.raises(asyncio.TimeoutError):
                    await agent.run_once()

    async def test_cycle_timeout_none_means_no_bound(self):
        """cycle_timeout_seconds=None disables the wrapper (default)."""

        class QuickAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return CycleResult.simple("done")

        agent = QuickAgent(name="Quick", mcp_url="http://127.0.0.1:9999/mcp/")
        assert agent.cycle_timeout_seconds is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents/sdk && pytest tests/test_agent.py::TestCycleTimeout -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'cycle_timeout_seconds'`

- [ ] **Step 3: Add the parameter and timeout wrap**

In `agents/sdk/src/unitares_sdk/agent.py`, add to `__init__` signature (insert after `timeout: float = 30.0,`):

```python
        cycle_timeout_seconds: float | None = None,
```

Store it on the instance (add after `self.timeout = timeout`):

```python
        # Hard cap on a single cycle (connect + run_cycle + checkin). Used by
        # residents whose cycles can stall on an MCP session that never
        # finishes initialize. None = unbounded. Vigil and Sentinel
        # previously implemented this as an asyncio.wait_for wrapper in
        # their own run_once; hoisted here so subclasses don't reinvent it.
        self.cycle_timeout_seconds = cycle_timeout_seconds
```

Replace the body of `run_once` (around agent.py:144-149) with:

```python
    async def run_once(self) -> None:
        """Single cycle: connect -> ensure_identity -> run_cycle -> checkin -> disconnect.

        Bounded by ``cycle_timeout_seconds`` if set.
        """
        async def _cycle() -> None:
            async with GovernanceClient(mcp_url=self.mcp_url, timeout=self.timeout) as client:
                await self._ensure_identity(client)
                result = await self.run_cycle(client)
                await self._handle_cycle_result(client, result)

        if self.cycle_timeout_seconds is None:
            await _cycle()
        else:
            await asyncio.wait_for(_cycle(), self.cycle_timeout_seconds)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agents/sdk && pytest tests/test_agent.py::TestCycleTimeout -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run full SDK test suite to confirm no regression**

Run: `cd agents/sdk && pytest tests/ --no-cov --tb=short -q 2>&1 | tail -20`
Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add agents/sdk/src/unitares_sdk/agent.py agents/sdk/tests/test_agent.py
git commit -m "sdk: add cycle_timeout_seconds to GovernanceAgent

Hoists the asyncio.wait_for wrapper that vigil and sentinel both
reinvent around super().run_once(). None by default (backward
compatible); residents opt in via constructor kwarg."
```

---

## Task 2: Add `log_file` / `max_log_lines` auto-trim

**Files:**
- Modify: `agents/sdk/src/unitares_sdk/agent.py` (constructor + new helper + run_forever)
- Test: `agents/sdk/tests/test_agent.py`

**Context:** Vigil, Sentinel, and Watcher all call `trim_log(LOG_FILE, MAX_LOG_LINES)` after each cycle. The helper lives at `agents/common/log.py:7`. Hoist the call into the base, reading a module already in the SDK so consumers don't need `agents.common`. Copy `trim_log` into SDK as a private utility.

- [ ] **Step 1: Write the failing test**

Append to `agents/sdk/tests/test_agent.py`:

```python
class TestLogFileTrim:
    async def test_log_file_trimmed_after_cycle(self, tmp_path):
        """Base class trims log_file to max_log_lines after each cycle."""
        log_path = tmp_path / "agent.log"
        log_path.write_text("\n".join(f"line {i}" for i in range(100)) + "\n")

        class LoggingAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return None  # skip checkin

        agent = LoggingAgent(
            name="Logger",
            mcp_url="http://127.0.0.1:9999/mcp/",
            log_file=log_path,
            max_log_lines=10,
        )
        with patch("unitares_sdk.agent.GovernanceClient") as mock_cm:
            mock_client = AsyncMock()
            mock_cm.return_value.__aenter__.return_value = mock_client
            mock_cm.return_value.__aexit__.return_value = None
            with patch.object(LoggingAgent, "_ensure_identity", AsyncMock()):
                await agent.run_once()

        surviving = log_path.read_text().splitlines()
        assert len(surviving) == 10
        assert surviving[-1] == "line 99"

    async def test_log_file_none_is_noop(self, tmp_path):
        """log_file=None (default) does not error and trims nothing."""

        class QuietAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return None

        agent = QuietAgent(name="Quiet", mcp_url="http://127.0.0.1:9999/mcp/")
        assert agent.log_file is None
        # run once without error
        with patch("unitares_sdk.agent.GovernanceClient") as mock_cm:
            mock_client = AsyncMock()
            mock_cm.return_value.__aenter__.return_value = mock_client
            mock_cm.return_value.__aexit__.return_value = None
            with patch.object(QuietAgent, "_ensure_identity", AsyncMock()):
                await agent.run_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents/sdk && pytest tests/test_agent.py::TestLogFileTrim -v`
Expected: FAIL on `log_file`/`max_log_lines` kwargs not recognized.

- [ ] **Step 3: Add `_trim_log` utility to SDK utils**

In `agents/sdk/src/unitares_sdk/utils.py`, append:

```python
def trim_log(log_file: Path, max_lines: int) -> None:
    """Keep log_file bounded to the last ``max_lines`` lines.

    Silent no-op on OSError or if the file doesn't exist — log rotation
    should never be the reason an agent crashes.
    """
    if not log_file.exists():
        return
    try:
        lines = log_file.read_text().splitlines()
    except OSError:
        return
    if len(lines) <= max_lines:
        return
    try:
        log_file.write_text("\n".join(lines[-max_lines:]) + "\n")
    except OSError:
        pass
```

- [ ] **Step 4: Wire it into `GovernanceAgent`**

In `agents/sdk/src/unitares_sdk/agent.py`:

Add to the imports near the top:

```python
from unitares_sdk.utils import (
    load_json_state,
    notify,
    save_json_state,
    trim_log,
)
```

Add to `__init__` signature (after `cycle_timeout_seconds`):

```python
        log_file: Path | None = None,
        max_log_lines: int = 10_000,
```

Store them (after `self.cycle_timeout_seconds`):

```python
        # Optional bounded log file. When set, the base class trims it to
        # max_log_lines after each run_once completes. Set to None (default)
        # to disable log rotation entirely — callers that manage their own
        # rotation (logrotate, launchd StandardOutPath+StandardErrorPath)
        # should leave this unset.
        self.log_file = log_file
        self.max_log_lines = max_log_lines
```

Update `run_once` body to trim after the cycle (replace the body from Task 1):

```python
    async def run_once(self) -> None:
        """Single cycle: connect -> ensure_identity -> run_cycle -> checkin -> disconnect.

        Bounded by ``cycle_timeout_seconds`` if set. Trims ``log_file`` after
        completion (success or failure).
        """
        async def _cycle() -> None:
            async with GovernanceClient(mcp_url=self.mcp_url, timeout=self.timeout) as client:
                await self._ensure_identity(client)
                result = await self.run_cycle(client)
                await self._handle_cycle_result(client, result)

        try:
            if self.cycle_timeout_seconds is None:
                await _cycle()
            else:
                await asyncio.wait_for(_cycle(), self.cycle_timeout_seconds)
        finally:
            if self.log_file is not None:
                trim_log(self.log_file, self.max_log_lines)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd agents/sdk && pytest tests/test_agent.py::TestLogFileTrim -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run full SDK test suite**

Run: `cd agents/sdk && pytest tests/ --no-cov --tb=short -q 2>&1 | tail -20`
Expected: all existing tests still pass

- [ ] **Step 7: Commit**

```bash
git add agents/sdk/src/unitares_sdk/agent.py agents/sdk/src/unitares_sdk/utils.py agents/sdk/tests/test_agent.py
git commit -m "sdk: auto-trim log_file after each run_once

Adds log_file + max_log_lines init params to GovernanceAgent. Base
class calls trim_log in run_once's finally block. Matches the pattern
vigil/sentinel/watcher all implement independently."
```

---

## Task 3: Add `on_after_checkin` hook

**Files:**
- Modify: `agents/sdk/src/unitares_sdk/agent.py` (`_handle_cycle_result`)
- Test: `agents/sdk/tests/test_agent.py`

**Context:** Vigil (agents/vigil/agent.py:543) and Sentinel (agents/sentinel/agent.py:565) both override the entire `_handle_cycle_result` method just to log EISV after check-in and post a few extra notes. The override re-implements the base's checkin → leave_note → verdict-surfacing logic. A narrow post-checkin hook lets subclasses extend instead.

- [ ] **Step 1: Write the failing test**

Append to `agents/sdk/tests/test_agent.py`:

```python
class TestOnAfterCheckin:
    async def test_hook_called_with_checkin_result(self):
        """on_after_checkin runs after a successful checkin with the result."""
        captured: dict = {}

        class HookedAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return CycleResult.simple("did work")

            async def on_after_checkin(self, client, checkin_result, cycle_result):
                captured["checkin_verdict"] = checkin_result.verdict
                captured["cycle_summary"] = cycle_result.summary

        agent = HookedAgent(name="Hooked", mcp_url="http://127.0.0.1:9999/mcp/")
        mock_client = AsyncMock()
        mock_client.checkin = AsyncMock(
            return_value=CheckinResult(
                success=True, verdict="proceed", coherence=0.9,
                guidance="", metrics={}, _raw={},
            )
        )
        await agent._handle_cycle_result(mock_client, CycleResult.simple("did work"))

        assert captured["checkin_verdict"] == "proceed"
        assert captured["cycle_summary"] == "did work"

    async def test_hook_not_called_when_result_is_none(self):
        """on_after_checkin is skipped when run_cycle returned None."""
        captured: dict = {"called": False}

        class HookedAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return None

            async def on_after_checkin(self, client, checkin_result, cycle_result):
                captured["called"] = True

        agent = HookedAgent(name="Hooked", mcp_url="http://127.0.0.1:9999/mcp/")
        mock_client = AsyncMock()
        await agent._handle_cycle_result(mock_client, None)
        assert captured["called"] is False

    async def test_hook_not_called_on_pause_verdict_by_default(self):
        """When checkin returns pause, VerdictError is raised before hook runs."""
        captured: dict = {"called": False}

        class HookedAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return CycleResult.simple("work")

            async def on_after_checkin(self, client, checkin_result, cycle_result):
                captured["called"] = True

        agent = HookedAgent(name="Hooked", mcp_url="http://127.0.0.1:9999/mcp/")
        mock_client = AsyncMock()
        mock_client.checkin = AsyncMock(
            return_value=CheckinResult(
                success=True, verdict="pause", coherence=0.5,
                guidance="slow down", metrics={}, _raw={},
            )
        )
        with pytest.raises(VerdictError):
            await agent._handle_cycle_result(mock_client, CycleResult.simple("work"))
        # Hook runs BEFORE verdict-raising: state tracking must happen even on pause.
        assert captured["called"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents/sdk && pytest tests/test_agent.py::TestOnAfterCheckin -v`
Expected: FAIL — `on_after_checkin` doesn't exist yet.

- [ ] **Step 3: Add the hook method and wire it**

In `agents/sdk/src/unitares_sdk/agent.py`, add a method in the "Subclass interface" section (after `run_cycle`):

```python
    async def on_after_checkin(
        self,
        client: GovernanceClient,
        checkin_result: "CheckinResult",
        cycle_result: CycleResult,
    ) -> None:
        """Post-checkin extension hook. Override to log EISV, track state,
        or do any bookkeeping that needs the server's response.

        Called after a successful checkin AND after notes are posted, but
        before a ``pause`` or ``reject`` verdict raises ``VerdictError``.
        Runs on every verdict so state trackers see paused/rejected cycles
        too. Default: no-op.
        """
        return None
```

Add the `CheckinResult` import (top of file):

```python
from unitares_sdk.models import CheckinResult
```

Replace the body of `_handle_cycle_result` (currently at agent.py:274-300):

```python
    async def _handle_cycle_result(
        self, client: GovernanceClient, result: CycleResult | None
    ) -> None:
        """Process a cycle result: check in, post notes, run hook, raise on pause/reject."""
        if result is None:
            return

        checkin_result = await client.checkin(
            response_text=result.summary,
            complexity=result.complexity,
            confidence=result.confidence,
            response_mode=result.response_mode,
        )
        self._last_checkin_time = time.monotonic()

        # Post any notes
        if result.notes:
            for summary, tags in result.notes:
                try:
                    await client.leave_note(summary=summary, tags=tags)
                except Exception as e:
                    logger.warning("%s: failed to leave note: %s", self.name, e)

        # Extension point: subclasses do state tracking / EISV logging here.
        # Runs on every verdict so paused cycles are observed before raising.
        try:
            await self.on_after_checkin(client, checkin_result, result)
        except Exception as e:
            logger.warning("%s: on_after_checkin raised: %s", self.name, e)

        # Surface verdict
        verdict = checkin_result.verdict
        if verdict in ("pause", "reject"):
            raise VerdictError(verdict, checkin_result.guidance)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agents/sdk && pytest tests/test_agent.py::TestOnAfterCheckin -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run full SDK test suite**

Run: `cd agents/sdk && pytest tests/ --no-cov --tb=short -q 2>&1 | tail -20`
Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add agents/sdk/src/unitares_sdk/agent.py agents/sdk/tests/test_agent.py
git commit -m "sdk: add on_after_checkin extension hook

Narrow post-checkin hook so residents can log EISV / track coherence
without re-implementing the full _handle_cycle_result body (which
vigil and sentinel both do today). Runs before verdict-raising so
state trackers see paused/rejected cycles too."
```

---

## Task 4: Add `on_verdict_pause` recovery hook

**Files:**
- Modify: `agents/sdk/src/unitares_sdk/agent.py` (`_handle_cycle_result`)
- Test: `agents/sdk/tests/test_agent.py`

**Context:** Vigil's `_handle_cycle_result` override has self-recovery logic: on `pause` it calls `client.self_recovery(action="quick")` and retries the checkin once (vigil/agent.py:560-575). This is bespoke but useful behavior worth exposing as a hook.

- [ ] **Step 1: Write the failing test**

Append to `agents/sdk/tests/test_agent.py`:

```python
class TestOnVerdictPause:
    async def test_hook_can_request_retry(self):
        """on_verdict_pause returning True triggers a single checkin retry."""
        attempts: list = []

        class RecoveringAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return CycleResult.simple("work")

            async def on_verdict_pause(self, client, cycle_result, checkin_result):
                attempts.append("recovery called")
                await client.self_recovery(action="quick")
                return True  # request retry

        agent = RecoveringAgent(name="Recoverer", mcp_url="http://127.0.0.1:9999/mcp/")
        mock_client = AsyncMock()
        first = CheckinResult(
            success=True, verdict="pause", coherence=0.5,
            guidance="slow", metrics={}, _raw={},
        )
        second = CheckinResult(
            success=True, verdict="proceed", coherence=0.8,
            guidance="", metrics={}, _raw={},
        )
        mock_client.checkin = AsyncMock(side_effect=[first, second])
        mock_client.self_recovery = AsyncMock()

        # Should NOT raise: retry succeeded.
        await agent._handle_cycle_result(mock_client, CycleResult.simple("work"))

        assert attempts == ["recovery called"]
        assert mock_client.checkin.await_count == 2
        assert mock_client.self_recovery.await_count == 1

    async def test_hook_returning_false_surfaces_pause(self):
        """on_verdict_pause returning False lets VerdictError propagate."""

        class PassiveAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return CycleResult.simple("work")

            async def on_verdict_pause(self, client, cycle_result, checkin_result):
                return False

        agent = PassiveAgent(name="Passive", mcp_url="http://127.0.0.1:9999/mcp/")
        mock_client = AsyncMock()
        mock_client.checkin = AsyncMock(
            return_value=CheckinResult(
                success=True, verdict="pause", coherence=0.5,
                guidance="slow", metrics={}, _raw={},
            )
        )
        with pytest.raises(VerdictError):
            await agent._handle_cycle_result(mock_client, CycleResult.simple("work"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents/sdk && pytest tests/test_agent.py::TestOnVerdictPause -v`
Expected: FAIL — `on_verdict_pause` doesn't exist.

- [ ] **Step 3: Add the hook and retry-on-true logic**

In `agents/sdk/src/unitares_sdk/agent.py`, add after `on_after_checkin`:

```python
    async def on_verdict_pause(
        self,
        client: GovernanceClient,
        cycle_result: CycleResult,
        checkin_result: "CheckinResult",
    ) -> bool:
        """Pause-recovery hook. Called when checkin returns ``pause``.

        Return ``True`` to retry the checkin once (e.g. after
        ``client.self_recovery(action="quick")``); ``False`` to let the
        ``VerdictError`` propagate. Default: no recovery — return False.
        """
        return False
```

Replace `_handle_cycle_result` again (update Task 3's body):

```python
    async def _handle_cycle_result(
        self, client: GovernanceClient, result: CycleResult | None
    ) -> None:
        """Process a cycle result: check in, post notes, run hooks, raise on unrecovered pause/reject."""
        if result is None:
            return

        checkin_result = await client.checkin(
            response_text=result.summary,
            complexity=result.complexity,
            confidence=result.confidence,
            response_mode=result.response_mode,
        )
        self._last_checkin_time = time.monotonic()

        # Post any notes
        if result.notes:
            for summary, tags in result.notes:
                try:
                    await client.leave_note(summary=summary, tags=tags)
                except Exception as e:
                    logger.warning("%s: failed to leave note: %s", self.name, e)

        # Pause-recovery hook: retry once if the subclass recovered.
        if checkin_result.verdict == "pause":
            try:
                retry = await self.on_verdict_pause(client, result, checkin_result)
            except Exception as e:
                logger.warning("%s: on_verdict_pause raised: %s", self.name, e)
                retry = False
            if retry:
                checkin_result = await client.checkin(
                    response_text=result.summary,
                    complexity=result.complexity,
                    confidence=result.confidence,
                    response_mode=result.response_mode,
                )
                self._last_checkin_time = time.monotonic()

        # State-tracking hook: runs on the FINAL checkin_result (post-retry).
        try:
            await self.on_after_checkin(client, checkin_result, result)
        except Exception as e:
            logger.warning("%s: on_after_checkin raised: %s", self.name, e)

        # Surface verdict if still bad
        if checkin_result.verdict in ("pause", "reject"):
            raise VerdictError(checkin_result.verdict, checkin_result.guidance)
```

- [ ] **Step 4: Update Task 3's third test for new ordering**

The `test_hook_not_called_on_pause_verdict_by_default` test asserted that `on_after_checkin` runs BEFORE raising. That behavior now still holds (on_after_checkin runs on the final result). But the default `on_verdict_pause` returns False, so behavior is unchanged — the existing test should still pass. **Verify without edits.**

- [ ] **Step 5: Run test to verify it passes**

Run: `cd agents/sdk && pytest tests/test_agent.py::TestOnVerdictPause tests/test_agent.py::TestOnAfterCheckin -v`
Expected: PASS (5 tests total)

- [ ] **Step 6: Run full SDK test suite**

Run: `cd agents/sdk && pytest tests/ --no-cov --tb=short -q 2>&1 | tail -20`
Expected: all existing tests still pass

- [ ] **Step 7: Commit**

```bash
git add agents/sdk/src/unitares_sdk/agent.py agents/sdk/tests/test_agent.py
git commit -m "sdk: add on_verdict_pause recovery hook

Subclasses can return True to request a single checkin retry after
self_recovery. Default returns False (preserves existing behavior).
Lets vigil delete its full _handle_cycle_result override in a
follow-up migration."
```

---

## Task 5: Add `state_file` override

**Files:**
- Modify: `agents/sdk/src/unitares_sdk/agent.py` (constructor + load_state/save_state)
- Test: `agents/sdk/tests/test_agent.py`

**Context:** Base class stores state at `state_dir/state.json`. Vigil overrides `load_state`/`save_state` to use `STATE_FILE` (`.vigil_state` under data root) — that override exists *only* to pick a different path. Expose it as a constructor param.

- [ ] **Step 1: Write the failing test**

Append to `agents/sdk/tests/test_agent.py`:

```python
class TestStateFileOverride:
    def test_state_file_override_used_for_persistence(self, tmp_path):
        """load_state / save_state use state_file when provided."""
        custom = tmp_path / "my_state.json"

        class Agent(GovernanceAgent):
            async def run_cycle(self, client):
                return None

        agent = Agent(
            name="Custom", mcp_url="http://127.0.0.1:9999/mcp/",
            state_file=custom,
        )
        agent.save_state({"cycles": 42})
        assert custom.exists()

        agent2 = Agent(
            name="Custom", mcp_url="http://127.0.0.1:9999/mcp/",
            state_file=custom,
        )
        assert agent2.load_state() == {"cycles": 42}

    def test_state_file_default_is_state_dir_over_state_json(self, tmp_path):
        """Default state path unchanged: state_dir/state.json."""

        class Agent(GovernanceAgent):
            async def run_cycle(self, client):
                return None

        agent = Agent(
            name="Default", mcp_url="http://127.0.0.1:9999/mcp/",
            state_dir=tmp_path,
        )
        agent.save_state({"k": "v"})
        assert (tmp_path / "state.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents/sdk && pytest tests/test_agent.py::TestStateFileOverride -v`
Expected: FAIL — `state_file` kwarg not recognized.

- [ ] **Step 3: Add `state_file` and update methods**

In `agents/sdk/src/unitares_sdk/agent.py` constructor signature (after `state_dir`):

```python
        state_file: Path | None = None,
```

Store it (replacing the single state_dir line):

```python
        self.state_dir = state_dir or default_root / "data" / name_lower
        # state_file overrides the default state_dir/state.json when the
        # caller wants a specific path (e.g. a versioned filename or a
        # non-default data root). When None, falls back to the old default.
        self.state_file = state_file
```

Update `load_state` and `save_state` (around agent.py:370-376):

```python
    def load_state(self) -> dict:
        """Load agent-specific cross-cycle state."""
        path = self.state_file or (self.state_dir / "state.json")
        return load_json_state(path)

    def save_state(self, state: dict) -> None:
        """Save agent-specific cross-cycle state."""
        path = self.state_file or (self.state_dir / "state.json")
        save_json_state(path, state)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agents/sdk && pytest tests/test_agent.py::TestStateFileOverride -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run full SDK test suite**

Run: `cd agents/sdk && pytest tests/ --no-cov --tb=short -q 2>&1 | tail -20`
Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add agents/sdk/src/unitares_sdk/agent.py agents/sdk/tests/test_agent.py
git commit -m "sdk: add state_file param to GovernanceAgent

Lets residents specify an explicit state-persistence path without
overriding load_state/save_state. Vigil's override was there only to
pick a different path; this removes the need."
```

---

## Task 6: Migrate Chronicler to `cycle_timeout_seconds` + `log_file`

**Files:**
- Modify: `agents/chronicler/agent.py`

**Context:** Chronicler is the smallest consumer. Migrate first to prove the new surface works before tackling the bigger residents. Chronicler currently doesn't use log_file or cycle_timeout — this task adds both for parity.

- [ ] **Step 1: Wire the new params into `ChroniclerAgent.__init__`**

In `agents/chronicler/agent.py`, modify the `super().__init__` call (around line 146):

```python
        # Resolve log file: launchd plist owns stdout/stderr, but when run
        # manually we still want bounded logs under data/logs.
        log_file_path = Path(
            os.environ.get("CHRONICLER_LOG_FILE", "")
        ) or None
        super().__init__(
            name="Chronicler",
            mcp_url=mcp_url,
            persistent=True,
            refuse_fresh_onboard=True,
            log_file=log_file_path,
            max_log_lines=10_000,
            cycle_timeout_seconds=120.0,
        )
```

- [ ] **Step 2: Verify chronicler still imports and constructs**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/agent-sdk-polish && python3 -c "from agents.chronicler.agent import ChroniclerAgent; a = ChroniclerAgent('http://localhost:8767', None, Path('/tmp'), dry_run=True); print('ok', a.cycle_timeout_seconds, a.max_log_lines)"`
Expected: `ok 120.0 10000`

- [ ] **Step 3: Run chronicler in dry mode to confirm the CLI path is intact**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/agent-sdk-polish && python3 agents/chronicler/agent.py --dry 2>&1 | tail -5`
Expected: scraper lines + `chronicler done: success=N fail=0` (or skipped if scrapers can't run in worktree, which is fine — the point is the import chain is intact).

- [ ] **Step 4: Commit**

```bash
git add agents/chronicler/agent.py
git commit -m "chronicler: adopt sdk cycle_timeout_seconds + log_file

Proves the new GovernanceAgent surface on the smallest resident
before migrating vigil and sentinel."
```

---

## Task 7: Migrate Sentinel — delete `_handle_cycle_result` + `_bounded_analysis_cycle`

**Files:**
- Modify: `agents/sentinel/agent.py`

**Context:** Sentinel's `_handle_cycle_result` (lines 565-611) does exactly three things the base class didn't support: (a) swallow check-in errors silently, (b) log an EISV one-liner, (c) call `log("CHECK-IN FAILED | ...")`. With `on_after_checkin`, (b) moves to a hook and (a)/(c) become irrelevant — base's own logger handles check-in errors. `_bounded_analysis_cycle` (lines 614-631) becomes `cycle_timeout_seconds=CYCLE_TIMEOUT`.

- [ ] **Step 1: Read current sentinel to locate the constructor**

Run: `grep -n "super().__init__\|class SentinelAgent" agents/sentinel/agent.py`

- [ ] **Step 2: Add `on_after_checkin`, delete `_handle_cycle_result`**

In `agents/sentinel/agent.py`, delete the entire `_handle_cycle_result` method (lines ~565-610). Add an `on_after_checkin` method on `SentinelAgent` in its place:

```python
    async def on_after_checkin(
        self, client, checkin_result, cycle_result,
    ) -> None:
        """Log one-line EISV summary after each check-in."""
        if not checkin_result.success:
            log(f"CHECK-IN FAILED | {cycle_result.summary}")
            return
        metrics = checkin_result.metrics or {}
        try:
            eisv = (
                f"E={float(metrics['E']):.3f} "
                f"I={float(metrics['I']):.3f} "
                f"S={float(metrics['S']):.3f} "
                f"V={float(metrics['V']):.3f}"
            )
        except (KeyError, TypeError, ValueError):
            eisv = "EISV=?"
        log(f"{checkin_result.verdict} | {eisv} | {cycle_result.summary}")
```

- [ ] **Step 3: Pass `cycle_timeout_seconds` to base and delete `_bounded_analysis_cycle`**

Find the `super().__init__(...)` call in `SentinelAgent.__init__` and add:

```python
            cycle_timeout_seconds=CYCLE_TIMEOUT,
            log_file=LOG_FILE,
            max_log_lines=MAX_LOG_LINES,
```

Delete the `_bounded_analysis_cycle` method (lines ~614-631).

Replace its call sites (should be three: inside `run_continuous` and `run_once_mode`). Each looks like:

```python
await self._bounded_analysis_cycle()
```

Replace with:

```python
try:
    await self.run_once()
    result = f"cycle {self._cycle_count} complete"
except asyncio.TimeoutError:
    log(f"Analysis cycle exceeded {CYCLE_TIMEOUT}s — skipping")
    result = f"TIMEOUT after {CYCLE_TIMEOUT}s"
```

If `result` is not used at the call site (e.g. it's only used in `run_once_mode`'s return), keep the variable; if not, collapse to the try/except without assignment. Audit each call site and apply accordingly.

Delete the `_trim_log` import at the top (line 45) and any direct `_trim_log(LOG_FILE, MAX_LOG_LINES)` calls inside `run_continuous` / `run_once_mode` / the shutdown path — the base now trims on every `run_once`.

- [ ] **Step 4: Quick import + construction check**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/agent-sdk-polish && python3 -c "from agents.sentinel.agent import SentinelAgent; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Run sentinel's tests if any, plus a repo-wide test pass**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/agent-sdk-polish && find tests -name '*sentinel*' -name '*.py' 2>/dev/null`

If files found: `pytest <each file> --no-cov --tb=short -q`

Then run the full SDK test suite to catch any cross-impact:
`cd agents/sdk && pytest tests/ --no-cov --tb=short -q 2>&1 | tail -10`
Expected: pass

- [ ] **Step 6: Commit**

```bash
git add agents/sentinel/agent.py
git commit -m "sentinel: migrate to sdk hooks

Replace the full _handle_cycle_result override with on_after_checkin
(EISV log line only). Replace _bounded_analysis_cycle with
cycle_timeout_seconds=CYCLE_TIMEOUT. Drop direct trim_log calls —
base class now handles log rotation."
```

---

## Task 8: Migrate Vigil — delete `_handle_cycle_result` + `run_once` overrides + custom state methods

**Files:**
- Modify: `agents/vigil/agent.py`

**Context:** Vigil is the most complex migration. Its `_handle_cycle_result` (lines 543-628) includes:
1. Self-recovery on pause → `on_verdict_pause` (Task 4)
2. EISV / verdict logging → `on_after_checkin` (Task 3)
3. Post-checkin state tracking via `detect_changes` → `on_after_checkin`
4. Cycle-state persistence → base's `save_state` (Task 5's `state_file`)

Its `run_once(self, timeout=CYCLE_TIMEOUT)` override wraps `super().run_once()` in `asyncio.wait_for` and calls `_trim_log` — both now in base.

Its `load_state`/`save_state` overrides (lines 632-649) only pick a non-default path — now handled by Task 5's `state_file`.

- [ ] **Step 1: Wire the base class params in vigil's constructor**

Find `VigilAgent.__init__`'s `super().__init__(...)` call. Add:

```python
            cycle_timeout_seconds=CYCLE_TIMEOUT,
            log_file=LOG_FILE,
            max_log_lines=MAX_LOG_LINES,
            state_file=STATE_FILE,
```

- [ ] **Step 2: Replace `_handle_cycle_result` with two hooks**

Delete the entire `_handle_cycle_result` method (lines ~543-628). Add in its place two methods:

```python
    async def on_verdict_pause(
        self, client, cycle_result, checkin_result,
    ) -> bool:
        """Attempt quick self-recovery on pause, then retry check-in once."""
        log("Paused — attempting self-recovery")
        try:
            await client.self_recovery(action="quick")
            log("Self-recovery succeeded, retrying check-in")
            return True
        except Exception as retry_err:
            log(f"Self-recovery failed: {retry_err}")
            self.save_state(self._cycle_state)
            return False

    async def on_after_checkin(
        self, client, checkin_result, cycle_result,
    ) -> None:
        """Track coherence changes, persist state, log a one-line EISV summary."""
        coherence = checkin_result.coherence
        verdict = checkin_result.verdict
        metrics = checkin_result.metrics or {}

        self._cycle_state["coherence"] = coherence
        self._cycle_state["verdict"] = verdict

        # Post any late-appearing notes (coherence/verdict changes)
        late_changes = detect_changes(self._cycle_prev_state, self._cycle_state)
        existing_summaries = {n[0] for n in (cycle_result.notes or [])}
        for change in late_changes:
            if change["summary"] not in existing_summaries:
                try:
                    await client.leave_note(
                        summary=change["summary"], tags=change["tags"]
                    )
                    log(f"NOTE: {change['summary']}")
                except Exception:
                    pass

        self.save_state(self._cycle_state)

        if checkin_result.success:
            try:
                eisv = (
                    f"E={float(metrics['E']):.3f} "
                    f"I={float(metrics['I']):.3f} "
                    f"S={float(metrics['S']):.3f} "
                    f"V={float(metrics['V']):.3f}"
                )
            except (KeyError, TypeError, ValueError):
                eisv = "EISV=?"
            total_cycles = self._cycle_state.get("total_cycles", 0)
            gov_up = self._cycle_state.get("gov_up_cycles", 0)
            lumen_up = self._cycle_state.get("lumen_up_cycles", 0)
            uptime = (
                f" | uptime: gov={gov_up/total_cycles:.0%} lumen={lumen_up/total_cycles:.0%}"
                if total_cycles > 0 else ""
            )
            log(f"{verdict or '?'} | {eisv} | {cycle_result.summary}{uptime}")
```

- [ ] **Step 3: Delete the `run_once` override**

Find and delete the `async def run_once(self, timeout: float = CYCLE_TIMEOUT):` method (lines ~653-674). It was just an `asyncio.wait_for` wrapper plus two `_trim_log` calls — the base class now does both.

Update any call site that passed a timeout argument. In `main()` (around line 713), `await agent.run_once()` should continue to work unchanged (base's run_once takes no args).

- [ ] **Step 4: Delete the `load_state` / `save_state` overrides**

Delete both methods (lines ~632-649). Base class now handles via `state_file=STATE_FILE`.

- [ ] **Step 5: Delete the `_trim_log` import and any direct calls**

Remove `from agents.common.log import trim_log as _trim_log` (line 44). Grep for remaining `_trim_log` references and remove them — base handles trimming.

- [ ] **Step 6: Quick import + construction check**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/agent-sdk-polish && python3 -c "from agents.vigil.agent import VigilAgent; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Run vigil tests if any**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/agent-sdk-polish && find tests -name '*vigil*' -name '*.py' 2>/dev/null`

If files found: `pytest <each file> --no-cov --tb=short -q`

Then: `cd agents/sdk && pytest tests/ --no-cov --tb=short -q 2>&1 | tail -10`
Expected: pass

- [ ] **Step 8: Run vigil once in --once mode to exercise the new wiring**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/agent-sdk-polish && python3 agents/vigil/agent.py --once 2>&1 | tail -20`

This exercises the full wiring against the live governance server. Expected: completes with a verdict line. If the server isn't up or vigil's anchor isn't available in the worktree, a clean error is fine — the goal is to catch import / signature errors, not to verify server behavior.

- [ ] **Step 9: Commit**

```bash
git add agents/vigil/agent.py
git commit -m "vigil: migrate to sdk hooks

Replace _handle_cycle_result with on_after_checkin + on_verdict_pause.
Delete run_once override (asyncio.wait_for wrapper now lives in base,
triggered via cycle_timeout_seconds). Delete load_state/save_state
overrides (state_file param picks the path). Drop _trim_log import —
base class trims log_file automatically."
```

---

## Task 9: Write `agents/sdk/README.md` — building your own resident

**Files:**
- Create: `agents/sdk/README.md`

**Context:** This is the elegant-vs-clanky payoff. A third-party (human or AI) should be able to read this file and ship a resident agent in 30 lines. Today there's only a terse top-level `agents/README.md` that points into the SDK but doesn't teach it.

- [ ] **Step 1: Write the README**

Create `agents/sdk/README.md`:

````markdown
# unitares-sdk

Build your own UNITARES resident agent. A resident is a long-running (or
scheduled) process that checks in to governance, carries an EISV state
vector, and participates in the shared knowledge graph. Vigil, Sentinel,
and Chronicler are reference implementations.

## The 30-line resident

```python
from pathlib import Path
from unitares_sdk.agent import CycleResult, GovernanceAgent
from unitares_sdk.client import GovernanceClient


class MyResident(GovernanceAgent):
    def __init__(self):
        super().__init__(
            name="MyResident",
            mcp_url="http://127.0.0.1:8767/mcp/",
            persistent=True,               # protects from auto-archive
            refuse_fresh_onboard=True,     # explicit bootstrap required
            cycle_timeout_seconds=60.0,    # hard cap on one cycle
            log_file=Path("/tmp/my_resident.log"),
            max_log_lines=10_000,
        )

    async def run_cycle(self, client: GovernanceClient) -> CycleResult | None:
        # Do your work here. Return a CycleResult to trigger a check-in,
        # or None to skip (useful for "nothing to do this tick" paths).
        count = await self.do_scan(client)
        if count == 0:
            return None
        return CycleResult(
            summary=f"scanned {count} items",
            complexity=0.2,
            confidence=0.9,
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(MyResident().run_forever(interval=60))
```

First run: `UNITARES_FIRST_RUN=1 python my_resident.py` — this mints
the identity and stores its UUID anchor at
`~/.unitares/anchors/myresident.json`. Every subsequent run resumes
that anchor automatically. Never delete anchors: if you do, set
`UNITARES_FIRST_RUN=1` again to re-bootstrap (you will get a new UUID).

## Extension points

The base class handles MCP connect, identity resolve, check-in,
heartbeat, log rotation, state persistence, and graceful shutdown.
Override these to extend behavior:

| Hook | When | Return |
|---|---|---|
| `run_cycle(client)` | Each iteration. The only required override. | `CycleResult` or `None` |
| `on_after_checkin(client, checkin_result, cycle_result)` | After each successful check-in. Use for EISV logging, coherence tracking, state writes that need the server response. | `None` |
| `on_verdict_pause(client, cycle_result, checkin_result)` | When check-in returns `pause`. Use for self-recovery. | `True` to retry the check-in once; `False` to let `VerdictError` propagate. |

Do **not** override `_ensure_identity`, `_handle_cycle_result`, or
`_send_heartbeat` — those are load-bearing and change across versions.

## Constructor reference

| Parameter | Type | Default | Purpose |
|---|---|---|---|
| `name` | `str` | required | Agent display name; drives anchor path (`~/.unitares/anchors/<name_lower>.json`). |
| `mcp_url` | `str` | `http://127.0.0.1:8767/mcp/` | Governance MCP endpoint. |
| `persistent` | `bool` | `False` | Stamp the `persistent` + `autonomous` tags on fresh onboard. Set `True` for long-running residents. |
| `refuse_fresh_onboard` | `bool` | `False` | Require `UNITARES_FIRST_RUN=1` to mint a new identity. Set `True` to prevent silent ghost-forks. |
| `cycle_timeout_seconds` | `float \| None` | `None` | Hard cap on a single `run_once`. MCP's anyio task group can hang on `session.initialize` if the server flakes — use 60–120s. |
| `log_file` | `Path \| None` | `None` | Log file to auto-trim after each cycle. Leave unset if launchd / logrotate owns rotation. |
| `max_log_lines` | `int` | `10_000` | Trim threshold for `log_file`. |
| `state_file` | `Path \| None` | `None` | Override cross-cycle state path. Default is `<state_dir>/state.json`. |
| `state_dir` | `Path \| None` | `<repo>/data/<name_lower>` | Default directory for state persistence. |
| `parent_agent_id` | `str \| None` | `None` | Forked-from UUID. Forwards to server on fresh onboard. |
| `spawn_reason` | `str \| None` | `None` | One of `compaction`, `subagent`, `new_session`, `explicit`. |

## Lifecycle shapes

- **Daemon**: `asyncio.run(agent.run_forever(interval=60))` — loops
  forever with heartbeats when idle. Reference: `agents/sentinel/agent.py`.
- **Scheduled**: `asyncio.run(agent.run_once())` under launchd /
  systemd cron. Reference: `agents/chronicler/agent.py`,
  `agents/vigil/agent.py`.

## Identity rules

1. The agent's first MCP call (`onboard` or `identity`) is the sole
   source of identity. Do not set identity out-of-band.
2. UUID is the ground truth. `client_session_id` and
   `continuity_token` are cache keys for ephemeral clients; residents
   don't need them.
3. Anchors live at `~/.unitares/anchors/<name_lower>.json`. One
   anchor per host per role. The file contains `agent_uuid` and is
   written atomically via `save_json_state`.
4. Never silent-swap an identity. If the anchor is missing and
   `refuse_fresh_onboard=True`, `_ensure_identity` raises
   `IdentityBootstrapRefused` — the operator must explicitly set
   `UNITARES_FIRST_RUN=1` once to mint a new one.

## Not in the SDK (on purpose)

- `agents/common/findings.py`, `agents/common/taxonomy.py`, and
  `agents/common/config.py` are internal to the reference residents
  in this repo. If you need findings-posting in your own resident,
  vendor the helper or POST to `/api/findings` yourself — the REST
  contract is the public surface.
- Watcher (`agents/watcher/agent.py`) uses a different execution
  model (sync, hook-driven, one-shot per tool-use event) and does not
  subclass `GovernanceAgent`.

````

- [ ] **Step 2: Commit**

```bash
git add agents/sdk/README.md
git commit -m "sdk: add README walkthrough for building a custom resident

30-line example + hook reference + constructor table + identity
rules. The agents/ README points at the SDK; this is what happens
when a reader lands there."
```

---

## Task 10: Verification + pre-commit test pass

- [ ] **Step 1: Full SDK tests**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/agent-sdk-polish/agents/sdk && pytest tests/ --no-cov --tb=short -q 2>&1 | tail -20`
Expected: all tests pass (pre-existing count + ~10 new tests from Tasks 1-5)

- [ ] **Step 2: Project-wide test-cache**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/agent-sdk-polish && ./scripts/dev/test-cache.sh 2>&1 | tail -30`
Expected: pass

- [ ] **Step 3: Import smoke-test for each migrated resident**

Run:
```bash
cd /Users/cirwel/projects/unitares/.worktrees/agent-sdk-polish
python3 -c "from agents.chronicler.agent import ChroniclerAgent; print('chronicler ok')"
python3 -c "from agents.vigil.agent import VigilAgent; print('vigil ok')"
python3 -c "from agents.sentinel.agent import SentinelAgent; print('sentinel ok')"
```
Expected: three `ok` lines.

- [ ] **Step 4: Line-count diff**

Run:
```bash
cd /Users/cirwel/projects/unitares/.worktrees/agent-sdk-polish
wc -l agents/vigil/agent.py agents/sentinel/agent.py agents/chronicler/agent.py agents/sdk/src/unitares_sdk/agent.py
```

Baseline (master): vigil=723, sentinel=745, chronicler=212, sdk/agent.py=389.
Expected on branch: vigil lower by ~100, sentinel lower by ~70, chronicler unchanged-or-slightly-up, sdk/agent.py higher by ~50.

Report actual deltas — if vigil/sentinel didn't shrink meaningfully, the migration didn't land and needs re-checking.

- [ ] **Step 5: Offer the ship decision**

Report the final state to the user with:
- line-count deltas (baseline vs. branch)
- SDK test count (before vs. after)
- whether `test-cache.sh` passed
- any resident that didn't import cleanly

Let the user run `scripts/dev/ship.sh` or equivalent — don't self-ship.

---

## Self-Review Notes

- Spec coverage: Phase 1 scope covers `cycle_timeout_seconds`, `log_file`, `state_file`, `on_after_checkin`, `on_verdict_pause`, migration of three residents, README. All scoped items map to Tasks 1–9.
- Watcher is explicitly out of scope (documented in scope boundary).
- `agents/common/*` is explicitly NOT promoted into the SDK (documented in README Task 9).
- Types used: `CycleResult`, `CheckinResult`, `GovernanceClient`, `VerdictError`, `Path`, `asyncio.TimeoutError`. All exist in the SDK today.
- Method names: `run_cycle`, `run_once`, `run_forever`, `on_after_checkin`, `on_verdict_pause`, `save_state`, `load_state`, `_handle_cycle_result`, `_ensure_identity` — consistent across tasks.
- Frequent commits: every task ends in a commit. 9 commits expected.
