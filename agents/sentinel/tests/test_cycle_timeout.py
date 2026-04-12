"""Regression tests for Sentinel's ``_bounded_analysis_cycle`` wrapper.

Background: on 2026-04-08, Sentinel hung inside ``session.call_tool(
"process_agent_update", ...)`` because the governance server's
anyio/asyncpg deadlock made the MCP call never return. With no timeout
on ``run_analysis_cycle``, the entire main loop was blocked for ~30
hours. This test asserts that the bounded wrapper converts such a hang
into a recoverable ``TimeoutError`` so the main loop can continue.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(scope="module")
def sentinel_module():
    """Load ``agents/sentinel/agent.py`` as a module without executing
    its ``__main__`` block."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    module_path = project_root / "agents" / "sentinel" / "agent.py"
    spec = importlib.util.spec_from_file_location("sentinel_agent", module_path)
    assert spec and spec.loader, "could not load sentinel_agent module"
    module = importlib.util.module_from_spec(spec)
    sys.modules["sentinel_agent"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _isolate_sentinel_log(tmp_path, monkeypatch, sentinel_module):
    """Redirect the sentinel's LOG_FILE into a tmp path so tests never
    write to the production log (~/Library/Logs/unitares-sentinel.log)."""
    tmp_log = tmp_path / "sentinel-test.log"
    monkeypatch.setattr(sentinel_module, "LOG_FILE", tmp_log)
    yield


def _build_agent(sentinel_module):
    return sentinel_module.SentinelAgent(
        mcp_url="http://127.0.0.1:0/mcp/",
        ws_url="ws://127.0.0.1:0/ws/eisv",
        analysis_interval=1,
    )


@pytest.mark.asyncio
async def test_bounded_cycle_times_out_on_hang(sentinel_module, monkeypatch):
    """A hung cycle must return a TIMEOUT marker instead of blocking forever."""
    monkeypatch.setattr(sentinel_module, "CYCLE_TIMEOUT", 0.2)
    agent = _build_agent(sentinel_module)

    async def _hang_forever() -> str:
        await asyncio.sleep(30)  # well past the timeout
        return "should-not-see-this"

    agent.run_analysis_cycle = _hang_forever  # type: ignore[assignment]

    result = await asyncio.wait_for(agent._bounded_analysis_cycle(), timeout=2.0)
    assert result.startswith("TIMEOUT")


@pytest.mark.asyncio
async def test_bounded_cycle_returns_normal_result(sentinel_module, monkeypatch):
    """A well-behaved cycle passes its return value through unchanged."""
    monkeypatch.setattr(sentinel_module, "CYCLE_TIMEOUT", 2.0)
    agent = _build_agent(sentinel_module)

    sentinel_value = "proceed | E=0.7 I=0.8 S=0.1 V=0.0 | Cycle 1"
    agent.run_analysis_cycle = AsyncMock(return_value=sentinel_value)

    result = await agent._bounded_analysis_cycle()
    assert result == sentinel_value


@pytest.mark.asyncio
async def test_main_loop_recovers_after_hung_cycle(sentinel_module, monkeypatch):
    """After a hung cycle times out, the next cycle must still run.

    Prior to the fix, a single hung ``run_analysis_cycle`` blocked the
    outer ``while self.running`` loop in ``run_continuous`` indefinitely.
    This test simulates that loop in miniature and confirms that a
    second cycle is reached after the first hangs.
    """
    monkeypatch.setattr(sentinel_module, "CYCLE_TIMEOUT", 0.1)
    agent = _build_agent(sentinel_module)

    calls = {"n": 0}

    async def _hang_then_recover() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(30)  # force the first cycle to time out
            return "unreachable"
        return "proceed | recovered"

    agent.run_analysis_cycle = _hang_then_recover  # type: ignore[assignment]

    first = await agent._bounded_analysis_cycle()
    second = await agent._bounded_analysis_cycle()

    assert first.startswith("TIMEOUT")
    assert second == "proceed | recovered"
    assert calls["n"] == 2
