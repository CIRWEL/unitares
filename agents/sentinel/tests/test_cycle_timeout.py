"""Regression tests for Sentinel's cycle-timeout behavior.

Background: on 2026-04-08, Sentinel hung inside ``session.call_tool(
"process_agent_update", ...)`` because the governance server's
anyio/asyncpg deadlock made the MCP call never return. With no timeout
on the analysis cycle, the entire main loop was blocked for ~30 hours.
This module asserts that the bounded wrapper converts such a hang into
a recoverable ``asyncio.TimeoutError`` so the main loop can continue.

Post-SDK migration: the bounded wrapper lives in
``GovernanceAgent.run_once`` (configured by ``cycle_timeout_seconds``
in the constructor). Sentinel's per-cycle timeout flows through
``CYCLE_TIMEOUT`` -> ``super().__init__(cycle_timeout_seconds=...)``.
The structural assertion that the wrapper uses ``asyncio.wait_for``
(not ``anyio.fail_after``) now applies to the SDK source — see the
2026-04-17 cancel-scope regression note in the bottom test.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SENTINEL_PATH = REPO_ROOT / "agents" / "sentinel" / "agent.py"
SDK_AGENT_PATH = REPO_ROOT / "agents" / "sdk" / "src" / "unitares_sdk" / "agent.py"
sys.path.insert(0, str(REPO_ROOT))


def _load_sentinel_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sentinel_agent_under_test", SENTINEL_PATH
    )
    assert spec and spec.loader, f"cannot load {SENTINEL_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sentinel_module() -> ModuleType:
    return _load_sentinel_module()


@pytest.fixture
def agent(sentinel_module, tmp_path, monkeypatch):
    """Construct an agent with file paths redirected to tmp_path so the test
    does not touch the real ~/Library/Logs or .sentinel_* files."""
    log_file = tmp_path / "sentinel.log"
    session_file = tmp_path / "sentinel_session.json"
    state_file = tmp_path / "sentinel_state.json"
    monkeypatch.setattr(sentinel_module, "LOG_FILE", log_file)
    monkeypatch.setattr(sentinel_module, "SESSION_FILE", session_file)
    monkeypatch.setattr(sentinel_module, "STATE_FILE", state_file)
    a = sentinel_module.SentinelAgent(
        mcp_url="http://127.0.0.1:0/mcp/",
        ws_url="ws://127.0.0.1:0/ws/eisv",
        analysis_interval=1,
    )
    a.session_file = session_file
    return a


@pytest.fixture(autouse=True)
def _mock_sdk_connection():
    """Prevent SDK from opening real MCP connections during timeout tests."""
    with patch("unitares_sdk.client.GovernanceClient.connect", new_callable=AsyncMock), \
         patch("unitares_sdk.client.GovernanceClient.disconnect", new_callable=AsyncMock), \
         patch("unitares_sdk.agent.GovernanceAgent._ensure_identity", new_callable=AsyncMock):
        yield


@pytest.mark.asyncio
async def test_bounded_cycle_times_out_on_hang(agent):
    """A hung cycle must raise asyncio.TimeoutError, not block forever."""
    agent.cycle_timeout_seconds = 0.2

    async def _hang(self, client=None):
        await asyncio.sleep(30)  # well past the timeout
        return None

    agent.run_cycle = _hang.__get__(agent, type(agent))

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(agent.run_once(), timeout=2.0)


@pytest.mark.asyncio
async def test_bounded_cycle_returns_normal_result(agent):
    """A well-behaved cycle passes through without error."""
    agent.cycle_timeout_seconds = 2.0

    from unitares_sdk.agent import CycleResult

    async def _fast(self, client=None):
        return CycleResult.simple("Sentinel analysis: Cycle 1 | Fleet: 0 agents | WS: DISCONNECTED")

    agent.run_cycle = _fast.__get__(agent, type(agent))
    agent._handle_cycle_result = AsyncMock()

    # Must not raise — completes cleanly within the timeout budget.
    await agent.run_once()


@pytest.mark.asyncio
async def test_main_loop_recovers_after_hung_cycle(agent):
    """After a hung cycle times out, the next cycle must still run.

    Prior to the fix, a single hung analysis cycle blocked the outer
    ``while self.running`` loop in ``run_continuous`` indefinitely. This
    test simulates that loop in miniature and confirms a second cycle
    is reached after the first hangs.
    """
    agent.cycle_timeout_seconds = 0.1

    calls = {"n": 0}

    from unitares_sdk.agent import CycleResult

    async def _hang_then_recover(self, client=None):
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(30)  # force the first cycle to time out
            return None
        return CycleResult.simple("Sentinel analysis: recovered")

    agent.run_cycle = _hang_then_recover.__get__(agent, type(agent))
    agent._handle_cycle_result = AsyncMock()

    with pytest.raises(asyncio.TimeoutError):
        await agent.run_once()

    # Recovery: next call must succeed (the timeout did not poison the agent).
    await agent.run_once()
    assert calls["n"] == 2


def test_cycle_timeout_default_is_bounded(sentinel_module):
    """Sanity check: the module-level default must not be absent or absurd."""
    assert isinstance(sentinel_module.CYCLE_TIMEOUT, int)
    assert 30 <= sentinel_module.CYCLE_TIMEOUT <= 600, (
        f"CYCLE_TIMEOUT={sentinel_module.CYCLE_TIMEOUT} is outside the sane "
        "operational window (30s..600s)"
    )


def test_sdk_run_once_uses_asyncio_wait_for_not_anyio_fail_after():
    """Structural check: the bounded-cycle wrapper MUST use asyncio.wait_for.

    Why: ``anyio.fail_after`` creates a cancel scope owned by the caller task.
    Inside ``run_once``, ``GovernanceClient`` opens a ClientSession that
    spawns an internal reader task for the MCP memory stream. When the outer
    ``fail_after`` fires during ``session.initialize``, cancellation
    propagates across the reader-task boundary and unwinding the cancel scope
    crashes with ``RuntimeError: Attempted to exit a cancel scope that isn't
    the current task's current cancel scope``. In production (2026-04-17)
    this caused Sentinel to exit 1 on every cycle, riding 45 launchd
    restarts.

    ``asyncio.wait_for`` wraps the coroutine in its own task, so MCP's
    internal task group is entered and exited within a single task boundary
    — no cross-task cancel-scope ownership issue.

    Post-SDK-migration this guard moved from ``sentinel.agent`` to
    ``unitares_sdk.agent`` along with the bounded wrapper itself.
    """
    import re

    source = SDK_AGENT_PATH.read_text()
    match = re.search(
        r"async def run_once.*?(?=\n    async def |\nclass |\Z)",
        source,
        re.DOTALL,
    )
    assert match, "run_once not found in SDK agent source"
    body = match.group(0)
    no_docstring = re.sub(r'""".*?"""', "", body, count=1, flags=re.DOTALL)
    assert "asyncio.wait_for(" in no_docstring, (
        "run_once must use asyncio.wait_for — anyio.fail_after violates "
        "cancel-scope ownership against MCP SDK's reader task"
    )
    assert "anyio.fail_after(" not in no_docstring, (
        "anyio.fail_after inside run_once reintroduces the cross-task "
        "cancel-scope crash; keep it out of this wrapper"
    )
