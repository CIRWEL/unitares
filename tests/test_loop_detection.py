"""Tests for agent loop detection patterns and safety-net resume.

Covers:
- Pattern 4: lowered proceed threshold (15 → 10)
- Pattern 7: slow proceed loop (8+ proceed in 5 min)
- _safety_net_resume: fallback auto-resume when dialectic fails
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metadata(
    recent_timestamps: list[str] | None = None,
    recent_decisions: list[str] | None = None,
    created_at: str | None = None,
    loop_cooldown_until: str | None = None,
    recovery_attempt_at: str | None = None,
    tags: list[str] | None = None,
    status: str = "active",
):
    """Build a minimal metadata object for detect_loop_pattern."""
    now = datetime.now()
    meta = SimpleNamespace(
        recent_update_timestamps=recent_timestamps or [],
        recent_decisions=recent_decisions or [],
        loop_cooldown_until=loop_cooldown_until,
        recovery_attempt_at=recovery_attempt_at,
        created_at=created_at or (now - timedelta(hours=1)).isoformat(),
        tags=tags or [],
        status=status,
        api_key="test-key",
        paused_at=now.isoformat() if status == "paused" else None,
        loop_detected_at=None,
        loop_incidents=[],
        total_updates=10,
        last_update=now.isoformat(),
    )

    def add_lifecycle_event(event_type, detail):
        if not hasattr(meta, "_lifecycle_events"):
            meta._lifecycle_events = []
        meta._lifecycle_events.append((event_type, detail))

    meta.add_lifecycle_event = add_lifecycle_event
    return meta


def _timestamps_spaced(count: int, spacing_seconds: float, start_offset_seconds: float = 0) -> list[str]:
    """Generate `count` timestamps spaced evenly, ending near now."""
    now = datetime.now()
    start = now - timedelta(seconds=start_offset_seconds + spacing_seconds * (count - 1))
    return [(start + timedelta(seconds=i * spacing_seconds)).isoformat() for i in range(count)]


# ---------------------------------------------------------------------------
# Pattern 4: lowered proceed threshold (10, was 15)
# ---------------------------------------------------------------------------


class TestPattern4LoweredThreshold:
    """Pattern 4 should now trigger at 10 proceed decisions instead of 15."""

    def test_10_proceed_decisions_triggers(self):
        """10 proceed decisions in the last 10 updates should trigger."""
        timestamps = _timestamps_spaced(10, spacing_seconds=60)
        decisions = ["proceed"] * 10

        meta = _make_metadata(recent_timestamps=timestamps, recent_decisions=decisions)

        with (
            patch("src.agent_loop_detection.agent_metadata", {"test-agent": meta}),
            patch("src.agent_process_mgmt.SERVER_START_TIME", datetime.now() - timedelta(hours=1)),
        ):
            from src.agent_loop_detection import detect_loop_pattern
            is_loop, reason = detect_loop_pattern("test-agent")

        assert is_loop, f"10 proceed decisions should trigger Pattern 4, got: {reason}"
        assert "Decision loop" in reason

    def test_9_proceed_decisions_does_not_trigger(self):
        """9 proceed decisions should NOT trigger Pattern 4."""
        timestamps = _timestamps_spaced(10, spacing_seconds=60)
        decisions = ["proceed"] * 9 + ["pause"]

        meta = _make_metadata(recent_timestamps=timestamps, recent_decisions=decisions)

        with (
            patch("src.agent_loop_detection.agent_metadata", {"test-agent": meta}),
            patch("src.agent_process_mgmt.SERVER_START_TIME", datetime.now() - timedelta(hours=1)),
        ):
            from src.agent_loop_detection import detect_loop_pattern
            is_loop, reason = detect_loop_pattern("test-agent")

        # Should NOT trigger Pattern 4 (but might trigger other patterns
        # if timestamps are close — we spaced them 60s apart to avoid that)
        if is_loop:
            assert "Decision loop" not in reason, \
                f"9 proceed decisions should not trigger Pattern 4, but got: {reason}"


# ---------------------------------------------------------------------------
# Pattern 7: slow proceed loop
# ---------------------------------------------------------------------------


class TestPattern7SlowProceedLoop:
    """Pattern 7 detects 8+ proceed decisions within 5 minutes."""

    def test_8_proceed_in_5min_triggers(self):
        """8 proceed decisions in a 5-min window should trigger Pattern 7."""
        # 10 timestamps over ~4 minutes (30s apart), all proceed
        timestamps = _timestamps_spaced(10, spacing_seconds=30)
        decisions = ["proceed"] * 10

        meta = _make_metadata(recent_timestamps=timestamps, recent_decisions=decisions)

        with (
            patch("src.agent_loop_detection.agent_metadata", {"test-agent": meta}),
            patch("src.agent_process_mgmt.SERVER_START_TIME", datetime.now() - timedelta(hours=1)),
        ):
            from src.agent_loop_detection import detect_loop_pattern
            is_loop, reason = detect_loop_pattern("test-agent")

        assert is_loop, f"8+ proceed in 5 min should trigger, got: {reason}"
        # Could be Pattern 4 or 7 — both should fire for 10 proceeds
        assert "loop" in reason.lower() or "proceed" in reason.lower()

    def test_8_proceed_over_10min_does_not_trigger_pattern7(self):
        """8 proceed decisions spread over 10 minutes should NOT trigger Pattern 7."""
        # 10 timestamps over ~10 minutes (75s apart) — outside the 5-min window
        timestamps = _timestamps_spaced(10, spacing_seconds=75)
        decisions = ["proceed"] * 8 + ["pause", "pause"]

        meta = _make_metadata(recent_timestamps=timestamps, recent_decisions=decisions)

        with (
            patch("src.agent_loop_detection.agent_metadata", {"test-agent": meta}),
            patch("src.agent_process_mgmt.SERVER_START_TIME", datetime.now() - timedelta(hours=1)),
        ):
            from src.agent_loop_detection import detect_loop_pattern
            is_loop, reason = detect_loop_pattern("test-agent")

        if is_loop:
            assert "Slow proceed loop" not in reason, \
                f"8 proceeds over 10 min should not trigger Pattern 7, got: {reason}"

    def test_autonomous_agents_skip_pattern7(self):
        """Autonomous/embodied agents skip decision-based patterns including Pattern 7."""
        timestamps = _timestamps_spaced(10, spacing_seconds=30)
        decisions = ["proceed"] * 10

        meta = _make_metadata(
            recent_timestamps=timestamps,
            recent_decisions=decisions,
            tags=["autonomous"],
        )

        with (
            patch("src.agent_loop_detection.agent_metadata", {"test-agent": meta}),
            patch("src.agent_process_mgmt.SERVER_START_TIME", datetime.now() - timedelta(hours=1)),
        ):
            from src.agent_loop_detection import detect_loop_pattern
            is_loop, reason = detect_loop_pattern("test-agent")

        # Autonomous agents skip patterns 4-7 (decision-based)
        if is_loop:
            assert "Decision loop" not in reason
            assert "Slow proceed loop" not in reason


# ---------------------------------------------------------------------------
# _safety_net_resume
# ---------------------------------------------------------------------------


class TestSafetyNetResume:
    """_safety_net_resume should auto-resume safe agents when dialectic fails."""

    @pytest.fixture
    def safe_monitor(self):
        state = SimpleNamespace(coherence=0.55)
        monitor = MagicMock()
        monitor.state = state
        monitor.get_metrics.return_value = {"mean_risk": 0.3}
        return monitor

    @pytest.fixture
    def unsafe_monitor(self):
        state = SimpleNamespace(coherence=0.30)
        monitor = MagicMock()
        monitor.state = state
        monitor.get_metrics.return_value = {"mean_risk": 0.7}
        return monitor

    @pytest.mark.asyncio
    async def test_safe_agent_is_resumed(self, safe_monitor):
        """Agent with coherence > 0.40 and risk < 0.60 should be auto-resumed."""
        meta = _make_metadata(status="paused")

        with (
            patch("src.agent_loop_detection.agent_metadata", {"agent-1": meta}),
            patch("src.agent_loop_detection.monitors", {"agent-1": safe_monitor}),
        ):
            from src.agent_loop_detection import _safety_net_resume
            await _safety_net_resume("agent-1", reason="LLM unavailable")

        assert meta.status == "active"
        assert meta.paused_at is None
        assert meta.loop_cooldown_until is None
        assert any("safety_net_resumed" in str(e) for e in meta._lifecycle_events)

    @pytest.mark.asyncio
    async def test_unsafe_agent_stays_paused(self, unsafe_monitor):
        """Agent with low coherence or high risk should NOT be resumed."""
        meta = _make_metadata(status="paused")

        with (
            patch("src.agent_loop_detection.agent_metadata", {"agent-1": meta}),
            patch("src.agent_loop_detection.monitors", {"agent-1": unsafe_monitor}),
        ):
            from src.agent_loop_detection import _safety_net_resume
            await _safety_net_resume("agent-1", reason="LLM unavailable")

        assert meta.status == "paused", "unsafe agent should stay paused"

    @pytest.mark.asyncio
    async def test_already_active_agent_is_noop(self, safe_monitor):
        """If agent is already active, safety net should do nothing."""
        meta = _make_metadata(status="active")

        with (
            patch("src.agent_loop_detection.agent_metadata", {"agent-1": meta}),
            patch("src.agent_loop_detection.monitors", {"agent-1": safe_monitor}),
        ):
            from src.agent_loop_detection import _safety_net_resume
            await _safety_net_resume("agent-1", reason="test")

        assert meta.status == "active"
        assert not hasattr(meta, "_lifecycle_events") or len(meta._lifecycle_events) == 0

    @pytest.mark.asyncio
    async def test_missing_agent_is_noop(self):
        """If agent doesn't exist in metadata, safety net should not crash."""
        with patch("src.agent_loop_detection.agent_metadata", {}):
            from src.agent_loop_detection import _safety_net_resume
            await _safety_net_resume("nonexistent", reason="test")
        # No exception = pass
