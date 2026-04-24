"""Bounds tests for governance_core.ethical_drift.

Watcher P002 (#ce53e83b, #b00276b6) flagged unbounded growth in:
  - AgentBaseline.recent_decisions  (line 216)
  - _baseline_cache global dict     (line 398)

Both are now structurally bounded — recent_decisions via deque(maxlen=...),
_baseline_cache via OrderedDict + LRU eviction at _BASELINE_CACHE_MAXLEN.
These tests pin that behavior so regressions fail in CI rather than as
slow memory growth in production.
"""
from __future__ import annotations

from collections import deque

import pytest

from governance_core import (
    AgentBaseline,
    clear_baseline,
    get_agent_baseline,
    get_baseline_or_none,
    set_agent_baseline,
)
from governance_core import ethical_drift as ed


@pytest.fixture(autouse=True)
def _isolate_cache():
    """Each test gets a clean baseline cache."""
    snapshot = ed._baseline_cache.copy()
    ed._baseline_cache.clear()
    yield
    ed._baseline_cache.clear()
    ed._baseline_cache.update(snapshot)


def test_recent_decisions_capped_at_maxlen():
    baseline = AgentBaseline(agent_id="cap-test")
    for i in range(ed._RECENT_DECISIONS_MAXLEN * 5):
        baseline.update(decision=f"d{i}")
    assert len(baseline.recent_decisions) == ed._RECENT_DECISIONS_MAXLEN
    # Most recent decision is preserved; oldest is evicted
    assert baseline.recent_decisions[-1] == f"d{ed._RECENT_DECISIONS_MAXLEN * 5 - 1}"
    assert baseline.recent_decisions[0] == f"d{ed._RECENT_DECISIONS_MAXLEN * 4}"


def test_recent_decisions_is_deque():
    baseline = AgentBaseline(agent_id="type-test")
    assert isinstance(baseline.recent_decisions, deque)
    assert baseline.recent_decisions.maxlen == ed._RECENT_DECISIONS_MAXLEN


def test_recent_decisions_roundtrip_serializes_as_list():
    """to_dict/from_dict preserve content and re-bound on deserialize."""
    baseline = AgentBaseline(agent_id="roundtrip")
    for i in range(50):
        baseline.update(decision=f"d{i}")
    serialized = baseline.to_dict()
    assert isinstance(serialized["recent_decisions"], list)
    assert len(serialized["recent_decisions"]) == ed._RECENT_DECISIONS_MAXLEN

    restored = AgentBaseline.from_dict(serialized)
    assert isinstance(restored.recent_decisions, deque)
    assert restored.recent_decisions.maxlen == ed._RECENT_DECISIONS_MAXLEN
    assert list(restored.recent_decisions) == serialized["recent_decisions"]


def test_from_dict_caps_oversized_input():
    """from_dict on a list larger than maxlen drops the oldest entries."""
    oversized = [f"d{i}" for i in range(ed._RECENT_DECISIONS_MAXLEN + 100)]
    baseline = AgentBaseline.from_dict({"agent_id": "oversized", "recent_decisions": oversized})
    assert len(baseline.recent_decisions) == ed._RECENT_DECISIONS_MAXLEN
    assert baseline.recent_decisions[-1] == oversized[-1]


def test_baseline_cache_evicts_lru(monkeypatch):
    """Beyond _BASELINE_CACHE_MAXLEN, oldest-touched entry is evicted."""
    monkeypatch.setattr(ed, "_BASELINE_CACHE_MAXLEN", 3)
    a = get_agent_baseline("a")
    b = get_agent_baseline("b")
    c = get_agent_baseline("c")
    assert set(ed._baseline_cache.keys()) == {"a", "b", "c"}

    # 'a' is now LRU. Touching 'b' moves it to MRU.
    get_agent_baseline("b")
    # Adding 'd' triggers eviction of 'a' (still LRU), not 'b' or 'c'.
    get_agent_baseline("d")
    assert set(ed._baseline_cache.keys()) == {"b", "c", "d"}


def test_baseline_cache_get_baseline_or_none_touches_lru(monkeypatch):
    monkeypatch.setattr(ed, "_BASELINE_CACHE_MAXLEN", 2)
    get_agent_baseline("x")
    get_agent_baseline("y")
    # 'x' is LRU.
    assert get_baseline_or_none("x") is not None  # touches → MRU
    get_agent_baseline("z")  # evicts LRU, which is now 'y'
    assert "x" in ed._baseline_cache
    assert "y" not in ed._baseline_cache
    assert "z" in ed._baseline_cache


def test_baseline_cache_set_evicts(monkeypatch):
    monkeypatch.setattr(ed, "_BASELINE_CACHE_MAXLEN", 2)
    set_agent_baseline("a", AgentBaseline(agent_id="a"))
    set_agent_baseline("b", AgentBaseline(agent_id="b"))
    set_agent_baseline("c", AgentBaseline(agent_id="c"))
    assert "a" not in ed._baseline_cache
    assert {"b", "c"} <= set(ed._baseline_cache.keys())


def test_clear_baseline_pop_missing_is_noop():
    """clear_baseline is safe to call on an absent agent_id."""
    clear_baseline("never-existed")  # must not raise
