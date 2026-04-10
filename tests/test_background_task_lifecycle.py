"""Regression tests for background task ownership and broadcaster cleanup."""

from __future__ import annotations

import asyncio
import inspect

import pytest

from src import background_tasks
from src.broadcaster import EISVBroadcaster


@pytest.mark.asyncio
async def test_stop_all_background_tasks_cancels_supervised_tasks():
    background_tasks._supervised_tasks.clear()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def sleeper():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = background_tasks._supervised_create_task(sleeper(), name="test_supervised")
    await started.wait()

    await background_tasks.stop_all_background_tasks()

    assert cancelled.is_set()
    assert task.cancelled()
    assert background_tasks._supervised_tasks == []


@pytest.mark.asyncio
async def test_startup_auto_calibration_supervises_ground_truth_collector(monkeypatch):
    background_tasks._supervised_tasks.clear()
    created: list[tuple[str | None, asyncio.Task]] = []

    async def fake_sleep(_seconds):
        return None

    async def fake_collect_ground_truth_automatically(**_kwargs):
        return {"updated": 0}

    async def fake_collector_task(interval_hours: float = 6.0):
        await asyncio.Event().wait()

    def fake_supervised_create_task(coro, *, name: str | None = None):
        task = asyncio.create_task(coro, name=name)
        created.append((name, task))
        task.cancel()
        return task

    import src.auto_ground_truth as auto_ground_truth

    monkeypatch.setattr(background_tasks.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        auto_ground_truth,
        "collect_ground_truth_automatically",
        fake_collect_ground_truth_automatically,
    )
    monkeypatch.setattr(
        auto_ground_truth,
        "auto_ground_truth_collector_task",
        fake_collector_task,
    )
    monkeypatch.setattr(
        background_tasks,
        "_supervised_create_task",
        fake_supervised_create_task,
    )

    await background_tasks.startup_auto_calibration()
    await asyncio.gather(*(task for _, task in created), return_exceptions=True)

    assert [name for name, _ in created] == ["auto_ground_truth_collector"]


def test_mcp_server_stops_background_tasks_before_closing_db():
    import src.mcp_server as mcp_server

    source = inspect.getsource(mcp_server.main)
    assert "await stop_all_background_tasks()" in source
    assert source.index("await stop_all_background_tasks()") < source.index("await close_db()")


class _HealthySocket:
    def __init__(self):
        self.sent = []
        self.close_calls = 0

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self):
        self.close_calls += 1


class _SlowSocket:
    def __init__(self):
        self.close_calls = 0

    async def send_json(self, data):
        await asyncio.sleep(10)

    async def close(self):
        self.close_calls += 1


@pytest.mark.asyncio
async def test_broadcaster_closes_dead_sockets_after_timeout():
    broadcaster = EISVBroadcaster()
    broadcaster._SEND_TIMEOUT_SECONDS = 0.01

    healthy = _HealthySocket()
    slow = _SlowSocket()
    broadcaster.connections = [healthy, slow]

    payload = {"type": "eisv_update"}
    await broadcaster._send_to_clients(payload)

    assert healthy.sent == [payload]
    assert slow.close_calls == 1
    assert slow not in broadcaster.connections
    assert healthy in broadcaster.connections
