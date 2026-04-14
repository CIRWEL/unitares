"""Regression tests for Sentinel's ``_bounded_analysis_cycle`` wrapper.

Background: on 2026-04-08, Sentinel hung inside ``session.call_tool(
"process_agent_update", ...)`` because the governance server's
anyio/asyncpg deadlock made the MCP call never return. With no timeout
on ``run_analysis_cycle``, the entire main loop was blocked for ~30
hours. This test asserts that the bounded wrapper converts such a hang
into a recoverable ``TimeoutError`` so the main loop can continue.

Post-SDK migration: Sentinel now extends GovernanceAgent and the
bounded wrapper calls ``super().run_once()`` (connect -> identity ->
run_cycle -> checkin -> disconnect).  Tests mock the SDK connection
layer to avoid real MCP connections.
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
async def test_bounded_cycle_times_out_on_hang(agent, sentinel_module, monkeypatch):
    """A hung cycle must return a TIMEOUT marker instead of blocking forever."""
    monkeypatch.setattr(sentinel_module, "CYCLE_TIMEOUT", 0.2)

    async def _hang(self, client=None):
        await asyncio.sleep(30)  # well past the timeout
        return None

    agent.run_cycle = _hang.__get__(agent, type(agent))

    result = await asyncio.wait_for(agent._bounded_analysis_cycle(), timeout=2.0)
    assert result.startswith("TIMEOUT")


@pytest.mark.asyncio
async def test_bounded_cycle_returns_normal_result(agent, sentinel_module, monkeypatch):
    """A well-behaved cycle passes through without error."""
    monkeypatch.setattr(sentinel_module, "CYCLE_TIMEOUT", 2.0)

    from unitares_sdk.agent import CycleResult

    async def _fast(self, client=None):
        return CycleResult.simple("Sentinel analysis: Cycle 1 | Fleet: 0 agents | WS: DISCONNECTED")

    agent.run_cycle = _fast.__get__(agent, type(agent))

    # Mock _handle_cycle_result to avoid needing a real client.checkin
    agent._handle_cycle_result = AsyncMock()

    result = await agent._bounded_analysis_cycle()
    assert not result.startswith("TIMEOUT")


@pytest.mark.asyncio
async def test_main_loop_recovers_after_hung_cycle(agent, sentinel_module, monkeypatch):
    """After a hung cycle times out, the next cycle must still run.

    Prior to the fix, a single hung ``run_analysis_cycle`` blocked the
    outer ``while self.running`` loop in ``run_continuous`` indefinitely.
    This test simulates that loop in miniature and confirms that a
    second cycle is reached after the first hangs.
    """
    monkeypatch.setattr(sentinel_module, "CYCLE_TIMEOUT", 0.1)

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

    first = await agent._bounded_analysis_cycle()
    second = await agent._bounded_analysis_cycle()

    assert first.startswith("TIMEOUT")
    assert not second.startswith("TIMEOUT")
    assert calls["n"] == 2


def test_cycle_timeout_default_is_bounded(sentinel_module):
    """Sanity check: the module-level default must not be absent or absurd."""
    assert isinstance(sentinel_module.CYCLE_TIMEOUT, int)
    assert 30 <= sentinel_module.CYCLE_TIMEOUT <= 600, (
        f"CYCLE_TIMEOUT={sentinel_module.CYCLE_TIMEOUT} is outside the sane "
        "operational window (30s..600s)"
    )
