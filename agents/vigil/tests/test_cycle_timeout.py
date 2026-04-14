"""Regression tests for heartbeat_agent.run_once wall-clock timeout.

Background: on 2026-04-08 a heartbeat (--once) invocation stalled inside an
MCP call and never exited. Because launchd's StartInterval does not fire
while the previous instance is still running, Vigil went silent for ~46
hours — not detected until a manual ps check during unrelated work.

Fix: wrap ``run_cycle()`` in ``asyncio.wait_for`` with a bounded
``CYCLE_TIMEOUT`` (default 120s, overridable via HEARTBEAT_CYCLE_TIMEOUT
env var). When the cycle hangs, the wrapper raises ``TimeoutError``,
``run_once`` logs it, and ``main()`` exits non-zero so launchd rotates to
a fresh invocation next interval.

These tests load the script via importlib (no __init__.py under
scripts/ops), monkeypatch ``run_cycle`` with a never-returning coroutine,
and assert the timeout fires cleanly within a few milliseconds.
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
HEARTBEAT_PATH = REPO_ROOT / "agents" / "vigil" / "agent.py"
sys.path.insert(0, str(REPO_ROOT))


def _load_heartbeat_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "heartbeat_agent_under_test", HEARTBEAT_PATH
    )
    assert spec and spec.loader, f"cannot load {HEARTBEAT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def heartbeat_module() -> ModuleType:
    return _load_heartbeat_module()


@pytest.fixture
def agent(heartbeat_module, tmp_path, monkeypatch):
    """Construct an agent with file paths redirected to tmp_path so the test
    does not touch the real ~/Library/Logs or .vigil_* files."""
    log_file = tmp_path / "heartbeat.log"
    session_file = tmp_path / "vigil_session.json"
    state_file = tmp_path / "vigil_state.json"
    monkeypatch.setattr(heartbeat_module, "LOG_FILE", log_file)
    monkeypatch.setattr(heartbeat_module, "SESSION_FILE", session_file)
    monkeypatch.setattr(heartbeat_module, "STATE_FILE", state_file)
    a = heartbeat_module.HeartbeatAgent(
        mcp_url="http://127.0.0.1:8767/mcp/",
        label="VigilTest",
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
async def test_run_once_aborts_when_cycle_hangs(agent, heartbeat_module):
    """A never-returning run_cycle must be cancelled by the timeout."""
    hang_started = asyncio.Event()

    async def _hang(self, client=None):
        hang_started.set()
        await asyncio.Event().wait()  # never resolves

    # Bind the hang as the agent's run_cycle.
    agent.run_cycle = _hang.__get__(agent, type(agent))

    start = asyncio.get_event_loop().time()
    with pytest.raises(asyncio.TimeoutError):
        await agent.run_once(timeout=0.1)
    elapsed = asyncio.get_event_loop().time() - start

    assert hang_started.is_set(), "run_cycle should have started before timeout"
    # The timeout is 0.1s; allow generous headroom for scheduler jitter but
    # insist it did not drag anywhere near the production 120s default.
    assert elapsed < 2.0, f"timeout took {elapsed:.3f}s, expected <2s"


@pytest.mark.asyncio
async def test_run_once_completes_normally_under_timeout(agent, heartbeat_module):
    """A fast run_cycle must not be affected by the timeout wrapper."""
    called = asyncio.Event()

    async def _fast(self, client=None):
        called.set()

    agent.run_cycle = _fast.__get__(agent, type(agent))
    await agent.run_once(timeout=5.0)
    assert called.is_set()


@pytest.mark.asyncio
async def test_timeout_writes_readable_log_line(agent, heartbeat_module):
    """The timeout path must leave a traceable log line for operators."""

    async def _hang(self, client=None):
        await asyncio.Event().wait()

    agent.run_cycle = _hang.__get__(agent, type(agent))

    with pytest.raises(asyncio.TimeoutError):
        await agent.run_once(timeout=0.1)

    log_contents = heartbeat_module.LOG_FILE.read_text()
    assert "Heartbeat cycle start" in log_contents
    assert "CYCLE TIMEOUT" in log_contents
    assert "limit=0.1s" in log_contents or "limit=0" in log_contents


def test_cycle_timeout_default_is_bounded(heartbeat_module):
    """Sanity check: the module-level default must not be absent or absurd."""
    assert isinstance(heartbeat_module.CYCLE_TIMEOUT, int)
    assert 30 <= heartbeat_module.CYCLE_TIMEOUT <= 600, (
        f"CYCLE_TIMEOUT={heartbeat_module.CYCLE_TIMEOUT} is outside the sane "
        "operational window (30s..600s)"
    )


# NOTE: load_state and load_session JSON hardening tests have moved to
# agents/sdk/tests/test_utils.py (load_json_state covers both cases).
