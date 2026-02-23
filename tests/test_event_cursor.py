"""
Tests for event IDs and ?since= cursor support in event_detector.

The Discord bridge needs stable event IDs so it can resume from where it
left off after restarts. Events get auto-incrementing event_id fields,
and get_recent_events(since=N) filters to events with event_id > N.
"""

import pytest
from src.event_detector import GovernanceEventDetector


@pytest.fixture
def detector():
    """Fresh event detector for each test."""
    return GovernanceEventDetector(max_stored_events=100)


def _trigger_event(detector, agent_id="agent-1", agent_name="TestAgent", action="allow", risk=0.1):
    """Helper: call detect_events with enough state change to produce an event."""
    # First call with a different action to set previous state
    detector.detect_events(
        agent_id=agent_id,
        agent_name=agent_name,
        action="observe",  # initial state
        risk=0.0,
        risk_raw=0.0,
        risk_adjustment=0.0,
        risk_reason="",
        drift=[0, 0, 0],
        verdict="observe",
    )
    # Second call changes the action, which triggers a verdict_change event
    events = detector.detect_events(
        agent_id=agent_id,
        agent_name=agent_name,
        action=action,
        risk=risk,
        risk_raw=risk,
        risk_adjustment=0.0,
        risk_reason="",
        drift=[0, 0, 0],
        verdict=action,
    )
    return events


class TestEventIds:
    """Events in the ring buffer should have an event_id field with auto-incrementing integers."""

    def test_events_have_sequential_ids(self, detector):
        """Each event stored in the ring buffer should get a unique, increasing event_id."""
        # Trigger multiple events from different agents (so each triggers agent_new + verdict_change)
        _trigger_event(detector, agent_id="a1", agent_name="Alpha", action="allow")
        _trigger_event(detector, agent_id="a2", agent_name="Beta", action="pause")

        events = detector.get_recent_events(limit=100)
        assert len(events) > 0, "Should have produced events"

        # All events should have event_id
        for ev in events:
            assert "event_id" in ev, f"Event missing event_id: {ev}"

        # IDs should be strictly increasing (events are returned newest-first)
        ids = [ev["event_id"] for ev in events]
        ids_ascending = list(reversed(ids))
        for i in range(1, len(ids_ascending)):
            assert ids_ascending[i] > ids_ascending[i - 1], (
                f"event_ids should be strictly increasing, got {ids_ascending}"
            )

    def test_event_ids_start_at_1(self, detector):
        """First event should have event_id=1 (not 0)."""
        _trigger_event(detector, agent_id="a1", agent_name="Alpha", action="allow")
        events = detector.get_recent_events(limit=100)
        ids = sorted(ev["event_id"] for ev in events)
        assert ids[0] == 1, f"First event_id should be 1, got {ids[0]}"

    def test_event_ids_survive_ring_buffer_trim(self, detector):
        """Event IDs should keep incrementing even after the ring buffer trims old events."""
        small_detector = GovernanceEventDetector(max_stored_events=5)

        # Generate more events than the buffer can hold
        for i in range(10):
            agent_id = f"agent-{i}"
            # First call sets initial state, second triggers verdict_change
            small_detector.detect_events(
                agent_id=agent_id, agent_name=f"Agent{i}", action="observe",
                risk=0.0, risk_raw=0.0, risk_adjustment=0.0, risk_reason="",
                drift=[0, 0, 0], verdict="observe",
            )
            small_detector.detect_events(
                agent_id=agent_id, agent_name=f"Agent{i}", action="pause",
                risk=0.5, risk_raw=0.5, risk_adjustment=0.0, risk_reason="",
                drift=[0, 0, 0], verdict="pause",
            )

        events = small_detector.get_recent_events(limit=100)
        assert len(events) <= 5, "Ring buffer should have trimmed"

        # IDs should still be high (not reset)
        min_id = min(ev["event_id"] for ev in events)
        assert min_id > 5, f"After trimming, min event_id should be > 5, got {min_id}"


class TestSinceFilter:
    """get_recent_events(since=N) should only return events with event_id > N."""

    def test_since_filter_returns_only_newer_events(self, detector):
        """Passing since=N should filter out events with event_id <= N."""
        # Generate some events
        _trigger_event(detector, agent_id="a1", agent_name="Alpha", action="allow")
        _trigger_event(detector, agent_id="a2", agent_name="Beta", action="pause")

        all_events = detector.get_recent_events(limit=100)
        assert len(all_events) >= 2, "Need at least 2 events for this test"

        # Pick a midpoint event_id
        midpoint_id = all_events[len(all_events) // 2]["event_id"]

        # Filter with since
        newer_events = detector.get_recent_events(limit=100, since=midpoint_id)

        # All returned events should have event_id > midpoint
        for ev in newer_events:
            assert ev["event_id"] > midpoint_id, (
                f"Event {ev['event_id']} should not be returned with since={midpoint_id}"
            )

    def test_since_zero_returns_all(self, detector):
        """since=0 should return all events (all IDs are > 0)."""
        _trigger_event(detector, agent_id="a1", agent_name="Alpha", action="allow")

        all_events = detector.get_recent_events(limit=100)
        since_zero = detector.get_recent_events(limit=100, since=0)

        assert len(since_zero) == len(all_events)

    def test_since_high_value_returns_empty(self, detector):
        """since=999999 should return empty if no events have that high an ID."""
        _trigger_event(detector, agent_id="a1", agent_name="Alpha", action="allow")

        events = detector.get_recent_events(limit=100, since=999999)
        assert events == []

    def test_since_combines_with_other_filters(self, detector):
        """since should work together with agent_id and event_type filters."""
        _trigger_event(detector, agent_id="a1", agent_name="Alpha", action="allow")
        _trigger_event(detector, agent_id="a2", agent_name="Beta", action="pause")

        all_events = detector.get_recent_events(limit=100)
        if not all_events:
            pytest.skip("No events generated")

        first_id = min(ev["event_id"] for ev in all_events)

        # Combine since + agent_id filter
        filtered = detector.get_recent_events(limit=100, since=first_id - 1, agent_id="a2")
        for ev in filtered:
            assert ev["agent_id"] == "a2"
            assert ev["event_id"] > first_id - 1
