from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.resident_progress.heartbeat import HeartbeatEvaluator, HeartbeatStatus


class _FakeMetadataStore:
    def __init__(self, rows: dict[str, dict]):
        self._rows = rows

    async def get(self, agent_uuid: str) -> dict | None:
        return self._rows.get(agent_uuid)


@pytest.mark.asyncio
async def test_evaluate_alive_when_recent_update():
    now = datetime.now(timezone.utc)
    store = _FakeMetadataStore({
        "u1": {"last_update": now - timedelta(seconds=30), "expected_cadence_s": 60},
    })
    ev = HeartbeatEvaluator(store, _now=lambda: now)
    status = await ev.evaluate("u1")
    assert status.alive is True
    assert status.in_critical_silence is False
    assert status.eval_error is None


@pytest.mark.asyncio
async def test_evaluate_silent_when_stale_update():
    now = datetime.now(timezone.utc)
    store = _FakeMetadataStore({
        "u1": {"last_update": now - timedelta(minutes=30), "expected_cadence_s": 60},
    })
    ev = HeartbeatEvaluator(store, _now=lambda: now)
    status = await ev.evaluate("u1")
    assert status.alive is False
    assert status.in_critical_silence is True


@pytest.mark.asyncio
async def test_evaluate_unknown_agent_returns_not_alive():
    ev = HeartbeatEvaluator(_FakeMetadataStore({}), _now=lambda: datetime.now(timezone.utc))
    status = await ev.evaluate("missing-uuid")
    assert status.alive is False
    assert status.eval_error is None  # missing agent is a known-not-alive, not an error


@pytest.mark.asyncio
async def test_evaluate_returns_error_on_store_exception():
    class _Boom:
        async def get(self, _): raise RuntimeError("db down")
    ev = HeartbeatEvaluator(_Boom(), _now=lambda: datetime.now(timezone.utc))
    status = await ev.evaluate("u1")
    assert status.alive is False
    assert "db down" in (status.eval_error or "")
