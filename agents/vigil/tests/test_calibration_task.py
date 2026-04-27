"""Vigil should recompute the watcher pattern_floor.json once per day.

Vigil cycles every 30min, so we gate recompute on a 24h staleness check
against pattern_floor.json's updated_at. Avoids recomputing 48× per day
while still keeping the floor fresh enough for the demotion logic."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from agents.watcher.floor_state import FloorState


def test_vigil_recomputes_floor_when_stale():
    from agents.vigil.agent import maybe_recompute_watcher_floor

    last = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sentinel_called = []

    def fake_recompute(**kwargs):
        sentinel_called.append(True)
        return FloorState(updated_at="now", buckets={})

    with patch("agents.vigil.agent.recompute_floor", side_effect=fake_recompute), \
         patch("agents.vigil.agent._last_floor_recompute_iso", return_value=last):
        result = maybe_recompute_watcher_floor()
    assert sentinel_called == [True]
    assert result is True


def test_vigil_skips_recompute_when_fresh():
    from agents.vigil.agent import maybe_recompute_watcher_floor

    last = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sentinel_called = []

    with patch(
        "agents.vigil.agent.recompute_floor",
        side_effect=lambda **kw: sentinel_called.append(True),
    ), patch("agents.vigil.agent._last_floor_recompute_iso", return_value=last):
        result = maybe_recompute_watcher_floor()
    assert sentinel_called == []
    assert result is False


def test_vigil_recomputes_when_no_prior_state():
    """Cold start: pattern_floor.json doesn't exist yet."""
    from agents.vigil.agent import maybe_recompute_watcher_floor

    sentinel_called = []

    def fake_recompute(**kwargs):
        sentinel_called.append(True)
        return FloorState(updated_at="now", buckets={})

    with patch("agents.vigil.agent.recompute_floor", side_effect=fake_recompute), \
         patch("agents.vigil.agent._last_floor_recompute_iso", return_value=None):
        result = maybe_recompute_watcher_floor()
    assert sentinel_called == [True]
    assert result is True


def test_vigil_recomputes_when_prior_state_unparseable():
    """Garbled timestamp in pattern_floor.json → safer to refresh than skip."""
    from agents.vigil.agent import maybe_recompute_watcher_floor

    sentinel_called = []

    with patch(
        "agents.vigil.agent.recompute_floor",
        side_effect=lambda **kw: (sentinel_called.append(True),
                                   FloorState(updated_at="now", buckets={}))[1],
    ), patch("agents.vigil.agent._last_floor_recompute_iso", return_value="garbage"):
        result = maybe_recompute_watcher_floor()
    assert sentinel_called == [True]
    assert result is True
