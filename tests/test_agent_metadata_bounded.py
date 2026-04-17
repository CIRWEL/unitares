"""
Regression tests for Watcher P002 — AgentMetadata.add_recent_update()
caps the parallel recent_update_timestamps / recent_decisions arrays so
callers can't accidentally grow them unboundedly.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agent_metadata_model import AgentMetadata


def _make():
    return AgentMetadata(agent_id="a", status="active", created_at="t", last_update="t")


def test_add_recent_update_appends_to_both_arrays():
    meta = _make()
    meta.add_recent_update("2026-04-16T10:00:00", "approve")
    assert meta.recent_update_timestamps == ["2026-04-16T10:00:00"]
    assert meta.recent_decisions == ["approve"]


def test_add_recent_update_caps_at_max():
    meta = _make()
    for i in range(meta.MAX_RECENT_UPDATES + 5):
        meta.add_recent_update(f"t{i}", f"a{i}")
    assert len(meta.recent_update_timestamps) == meta.MAX_RECENT_UPDATES
    assert len(meta.recent_decisions) == meta.MAX_RECENT_UPDATES
    # Newest entries are retained; oldest are dropped.
    assert meta.recent_update_timestamps[-1] == f"t{meta.MAX_RECENT_UPDATES + 4}"
    assert meta.recent_decisions[-1] == f"a{meta.MAX_RECENT_UPDATES + 4}"


def test_arrays_stay_parallel_after_cap():
    meta = _make()
    for i in range(meta.MAX_RECENT_UPDATES * 2):
        meta.add_recent_update(f"t{i}", f"a{i}")
    assert len(meta.recent_update_timestamps) == len(meta.recent_decisions)
    for ts, decision in zip(meta.recent_update_timestamps, meta.recent_decisions):
        assert ts.replace("t", "") == decision.replace("a", "")
