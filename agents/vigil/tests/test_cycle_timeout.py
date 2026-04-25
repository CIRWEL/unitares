"""Regression tests for Vigil's wall-clock cycle timeout.

Background: on 2026-04-08 a heartbeat (--once) invocation stalled inside an
MCP call and never exited. Because launchd's StartInterval does not fire
while the previous instance is still running, Vigil went silent for ~46
hours — not detected until a manual ps check during unrelated work.

Fix: wrap the cycle in ``asyncio.wait_for`` with a bounded ``CYCLE_TIMEOUT``
(default 120s, overridable via ``HEARTBEAT_CYCLE_TIMEOUT`` env var). Post-
SDK migration this lives in ``GovernanceAgent.run_once`` configured by
``cycle_timeout_seconds`` from Vigil's constructor. When the cycle hangs,
``run_once`` raises ``asyncio.TimeoutError`` and ``main()`` exits non-zero
so launchd rotates to a fresh invocation next interval.

These tests load the script via importlib (no __init__.py under
agents/vigil/), monkeypatch ``run_cycle`` with a never-returning coroutine,
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
VIGIL_PATH = REPO_ROOT / "agents" / "vigil" / "agent.py"
sys.path.insert(0, str(REPO_ROOT))


def _load_vigil_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "vigil_agent_under_test", VIGIL_PATH
    )
    assert spec and spec.loader, f"cannot load {VIGIL_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def vigil_module() -> ModuleType:
    return _load_vigil_module()


@pytest.fixture
def agent(vigil_module, tmp_path, monkeypatch):
    """Construct an agent with file paths redirected to tmp_path so the test
    does not touch the real ~/Library/Logs or .vigil_* files."""
    log_file = tmp_path / "vigil.log"
    session_file = tmp_path / "vigil_session.json"
    state_file = tmp_path / "vigil_state.json"
    monkeypatch.setattr(vigil_module, "LOG_FILE", log_file)
    monkeypatch.setattr(vigil_module, "SESSION_FILE", session_file)
    monkeypatch.setattr(vigil_module, "STATE_FILE", state_file)
    a = vigil_module.VigilAgent(
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
async def test_run_once_aborts_when_cycle_hangs(agent):
    """A never-returning run_cycle must be cancelled by the timeout."""
    agent.cycle_timeout_seconds = 0.1
    hang_started = asyncio.Event()

    async def _hang(self, client=None):
        hang_started.set()
        await asyncio.Event().wait()  # never resolves

    agent.run_cycle = _hang.__get__(agent, type(agent))

    start = asyncio.get_event_loop().time()
    with pytest.raises(asyncio.TimeoutError):
        await agent.run_once()
    elapsed = asyncio.get_event_loop().time() - start

    assert hang_started.is_set(), "run_cycle should have started before timeout"
    # The timeout is 0.1s; allow generous headroom for scheduler jitter but
    # insist it did not drag anywhere near the production 120s default.
    assert elapsed < 2.0, f"timeout took {elapsed:.3f}s, expected <2s"


@pytest.mark.asyncio
async def test_run_once_completes_normally_under_timeout(agent):
    """A fast run_cycle must not be affected by the timeout wrapper."""
    agent.cycle_timeout_seconds = 5.0
    called = asyncio.Event()

    async def _fast(self, client=None):
        called.set()

    agent.run_cycle = _fast.__get__(agent, type(agent))
    agent._handle_cycle_result = AsyncMock()
    await agent.run_once()
    assert called.is_set()


def test_cycle_timeout_default_is_bounded(vigil_module):
    """Sanity check: the module-level default must not be absent or absurd."""
    assert isinstance(vigil_module.CYCLE_TIMEOUT, int)
    assert 30 <= vigil_module.CYCLE_TIMEOUT <= 600, (
        f"CYCLE_TIMEOUT={vigil_module.CYCLE_TIMEOUT} is outside the sane "
        "operational window (30s..600s)"
    )


# NOTE: load_state and load_session JSON hardening tests have moved to
# agents/sdk/tests/test_utils.py (load_json_state covers both cases).
# The structural "must use asyncio.wait_for not anyio.fail_after" guard
# moved to agents/sentinel/tests/test_cycle_timeout.py — it inspects the
# shared SDK source, so a single copy serves both residents.
