"""
Tests for the spec docs/specs/2026-04-16-sever-fingerprint-eisv-inheritance-design.md

Covers:
- State transplant is gone (agent_lifecycle.get_or_create_monitor)
- Fingerprint match on resume=False no longer sets _predecessor_uuid
- Explicit parent_agent_id still records lineage (without state transplant)
- continuity_token round-trip preserves UUID
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from src.agent_metadata_model import AgentMetadata, agent_metadata
from src.agent_monitor_state import monitors


@pytest.fixture(autouse=True)
def _clear_process_state():
    """Each test starts with fresh in-memory identity state."""
    monitors.clear()
    agent_metadata.clear()
    yield
    monitors.clear()
    agent_metadata.clear()


def test_get_or_create_monitor_does_not_transplant_state_from_predecessor():
    """
    Regression guard: once agent_lifecycle.get_or_create_monitor no longer
    transplants state from a predecessor, a new agent with parent_agent_id
    set should start with a fresh GovernanceState (empty V_history).
    """
    from src.agent_lifecycle import get_or_create_monitor
    from src.governance_monitor import UNITARESMonitor

    # Build a predecessor monitor and populate its state so
    # load_monitor_state(parent_uuid) would return something real.
    parent_uuid = "parent-uuid-1111"
    parent_monitor = UNITARESMonitor(parent_uuid)
    parent_monitor.state.V_history.extend([0.1, 0.2, 0.3])
    monitors[parent_uuid] = parent_monitor

    # Child agent metadata points to the predecessor.
    child_uuid = "child-uuid-2222"
    now_iso = "2026-04-16T00:00:00+00:00"
    agent_metadata[child_uuid] = AgentMetadata(
        agent_id=child_uuid,
        status="active",
        created_at=now_iso,
        last_update=now_iso,
        parent_agent_id=parent_uuid,
    )

    # load_monitor_state(parent_uuid) in the real code path would return
    # the parent's persisted state. Force it to return the parent's in-memory
    # state so the "if we wanted to transplant, we could" path is exercised.
    def fake_load(agent_id):
        if agent_id == parent_uuid:
            return parent_monitor.state
        return None

    with patch("src.agent_lifecycle.load_monitor_state", side_effect=fake_load):
        child_monitor = get_or_create_monitor(child_uuid)

    assert child_monitor.state.V_history == [], (
        "Child agent must not inherit predecessor V_history "
        f"(got {child_monitor.state.V_history!r})"
    )
