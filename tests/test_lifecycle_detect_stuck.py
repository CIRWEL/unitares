"""
Tests for src/mcp_handlers/lifecycle.py - _detect_stuck_agents function.

Tests the pure detection logic by mocking mcp_server state and monitors.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, PropertyMock
from types import SimpleNamespace

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _make_agent_meta(
    status="active",
    last_update=None,
    created_at=None,
    total_updates=5,
    tags=None,
):
    """Create mock agent metadata."""
    now = datetime.now(timezone.utc)
    meta = SimpleNamespace(
        status=status,
        last_update=(last_update or now).isoformat(),
        created_at=(created_at or now).isoformat(),
        total_updates=total_updates,
        tags=tags or [],
    )
    return meta


def _make_monitor(
    coherence=0.55,
    risk=0.3,
    void_active=False,
    void_value=0.0,
):
    """Create mock UNITARESMonitor."""
    state = SimpleNamespace(
        coherence=coherence,
        V=void_value,
        void_active=void_active,
    )
    monitor = MagicMock()
    monitor.state = state
    monitor.get_metrics.return_value = {"mean_risk": risk}
    return monitor


def _margin_info(margin="comfortable", nearest_edge=None, distance=0.5):
    return {
        "margin": margin,
        "nearest_edge": nearest_edge,
        "distance_to_edge": distance,
    }


# Patches needed for every test
_PATCHES = {
    "mcp_server": "src.mcp_handlers.lifecycle.mcp_server",
    "gov_config": "src.mcp_handlers.lifecycle.GovernanceConfig",
}


class TestDetectStuckAgentsEmpty:

    @patch(_PATCHES["mcp_server"])
    def test_no_agents_returns_empty(self, mock_server):
        mock_server.agent_metadata = {}
        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents()
        assert result == []


class TestDetectStuckAgentsFiltering:

    @patch(_PATCHES["mcp_server"])
    def test_archived_agents_skipped(self, mock_server):
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(status="archived"),
        }
        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents()
        assert result == []

    @patch(_PATCHES["mcp_server"])
    def test_deleted_agents_skipped(self, mock_server):
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(status="deleted"),
        }
        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents()
        assert result == []

    @patch(_PATCHES["mcp_server"])
    def test_non_active_agents_skipped(self, mock_server):
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(status="paused"),
        }
        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents()
        assert result == []

    @patch(_PATCHES["mcp_server"])
    def test_autonomous_agents_skipped(self, mock_server):
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        mock_server.agent_metadata = {
            "lumen": _make_agent_meta(last_update=old_time, tags=["autonomous"]),
        }
        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents()
        assert result == []

    @patch(_PATCHES["mcp_server"])
    def test_embodied_agents_skipped(self, mock_server):
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        mock_server.agent_metadata = {
            "creature": _make_agent_meta(last_update=old_time, tags=["embodied"]),
        }
        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents()
        assert result == []

    @patch(_PATCHES["mcp_server"])
    def test_anima_tag_skipped(self, mock_server):
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        mock_server.agent_metadata = {
            "x": _make_agent_meta(last_update=old_time, tags=["anima"]),
        }
        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents()
        assert result == []

    @patch(_PATCHES["mcp_server"])
    def test_low_update_count_skipped(self, mock_server):
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(last_update=old_time, total_updates=0),
        }
        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(min_updates=1)
        assert result == []

    @patch(_PATCHES["mcp_server"])
    def test_custom_min_updates(self, mock_server):
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(last_update=old_time, total_updates=3),
        }
        mock_server.monitors = {}
        mock_server.load_monitor_state.return_value = None
        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(min_updates=5)
        assert result == []


class TestDetectStuckAgentsTimeout:

    @patch(_PATCHES["mcp_server"])
    def test_no_monitor_no_stuck(self, mock_server):
        """Agent with no monitor state is NOT flagged as stuck (can't determine margin)."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=45)
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(last_update=old_time),
        }
        mock_server.monitors = {}
        mock_server.load_monitor_state.return_value = None

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(max_age_minutes=30)
        # Without margin info, we can't determine if agent is stuck
        # Inactivity alone does NOT mean stuck
        assert len(result) == 0

    @patch(_PATCHES["mcp_server"])
    def test_recent_agent_not_stuck(self, mock_server):
        """Agent with recent update is not stuck."""
        recent = datetime.now(timezone.utc) - timedelta(minutes=5)
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(last_update=recent),
        }
        mock_server.monitors = {}
        mock_server.load_monitor_state.return_value = None

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(max_age_minutes=30)
        assert result == []

    @patch(_PATCHES["gov_config"])
    @patch(_PATCHES["mcp_server"])
    def test_comfortable_margin_not_stuck(self, mock_server, mock_config):
        """Agent past max_age with comfortable margin → NOT stuck (inactivity ≠ stuck)."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=45)
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(last_update=old_time),
        }
        monitor = _make_monitor()
        mock_server.monitors = {"a1": monitor}
        mock_config.compute_proprioceptive_margin.return_value = _margin_info("comfortable")

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(max_age_minutes=30, include_pattern_detection=False)
        # Inactivity alone does NOT mean stuck - comfortable margin means healthy
        assert len(result) == 0


class TestDetectStuckAgentsMarginBased:

    @patch(_PATCHES["gov_config"])
    @patch(_PATCHES["mcp_server"])
    def test_critical_margin_timeout(self, mock_server, mock_config):
        """Critical margin + timeout → critical_margin_timeout."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(last_update=old_time),
        }
        monitor = _make_monitor(risk=0.8, coherence=0.42)
        mock_server.monitors = {"a1": monitor}
        mock_config.compute_proprioceptive_margin.return_value = _margin_info(
            "critical", nearest_edge="risk", distance=0.02
        )

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(
            critical_margin_timeout_minutes=5,
            include_pattern_detection=False,
        )
        assert len(result) == 1
        assert result[0]["reason"] == "critical_margin_timeout"
        assert result[0]["margin"] == "critical"
        assert result[0]["nearest_edge"] == "risk"

    @patch(_PATCHES["gov_config"])
    @patch(_PATCHES["mcp_server"])
    def test_critical_margin_below_timeout_not_stuck(self, mock_server, mock_config):
        """Critical margin but within timeout → not stuck."""
        recent = datetime.now(timezone.utc) - timedelta(minutes=3)
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(last_update=recent),
        }
        monitor = _make_monitor(risk=0.8)
        mock_server.monitors = {"a1": monitor}
        mock_config.compute_proprioceptive_margin.return_value = _margin_info("critical")

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(
            critical_margin_timeout_minutes=5,
            max_age_minutes=30,
            include_pattern_detection=False,
        )
        assert result == []

    @patch(_PATCHES["gov_config"])
    @patch(_PATCHES["mcp_server"])
    def test_tight_margin_timeout(self, mock_server, mock_config):
        """Tight margin + timeout → tight_margin_timeout."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(last_update=old_time, total_updates=100),
        }
        monitor = _make_monitor()
        mock_server.monitors = {"a1": monitor}
        mock_config.compute_proprioceptive_margin.return_value = _margin_info(
            "tight", nearest_edge="coherence", distance=0.08
        )

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(
            tight_margin_timeout_minutes=15,
            max_age_minutes=30,
            include_pattern_detection=False,
        )
        assert len(result) == 1
        assert result[0]["reason"] == "tight_margin_timeout"
        assert result[0]["margin"] == "tight"

    @patch(_PATCHES["gov_config"])
    @patch(_PATCHES["mcp_server"])
    def test_tight_margin_below_timeout_not_stuck(self, mock_server, mock_config):
        """Tight margin within timeout → not stuck."""
        recent = datetime.now(timezone.utc) - timedelta(minutes=10)
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(last_update=recent),
        }
        monitor = _make_monitor()
        mock_server.monitors = {"a1": monitor}
        mock_config.compute_proprioceptive_margin.return_value = _margin_info("tight")

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(
            tight_margin_timeout_minutes=15,
            max_age_minutes=30,
            include_pattern_detection=False,
        )
        assert result == []


class TestDetectStuckAgentsMultiple:

    @patch(_PATCHES["gov_config"])
    @patch(_PATCHES["mcp_server"])
    def test_multiple_agents_mixed(self, mock_server, mock_config):
        """Multiple agents with different states - only margin-based issues = stuck."""
        old_45 = datetime.now(timezone.utc) - timedelta(minutes=45)
        old_10 = datetime.now(timezone.utc) - timedelta(minutes=10)
        recent_2 = datetime.now(timezone.utc) - timedelta(minutes=2)

        mock_server.agent_metadata = {
            "idle": _make_agent_meta(last_update=old_45),  # Inactive but healthy margin = NOT stuck
            "critical": _make_agent_meta(last_update=old_10),  # Critical margin = stuck
            "healthy": _make_agent_meta(last_update=recent_2),
            "archived": _make_agent_meta(status="archived", last_update=old_45),
        }
        mock_server.monitors = {
            "idle": _make_monitor(),
            "critical": _make_monitor(risk=0.9),
            "healthy": _make_monitor(),
        }
        mock_server.load_monitor_state.return_value = None

        def margin_side_effect(risk_score, coherence, void_active, void_value=0.0):
            if risk_score > 0.7:
                return _margin_info("critical", "risk")
            return _margin_info("comfortable")

        mock_config.compute_proprioceptive_margin.side_effect = margin_side_effect

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(include_pattern_detection=False)

        ids = {r["agent_id"] for r in result}
        # "idle" has comfortable margin - inactivity alone is NOT stuck
        assert "idle" not in ids
        # "critical" has critical margin + timeout - IS stuck
        assert "critical" in ids  # critical_margin_timeout
        assert "healthy" not in ids
        assert "archived" not in ids


class TestDetectStuckAgentsEdgeCases:

    @patch(_PATCHES["mcp_server"])
    def test_invalid_timestamp_skipped(self, mock_server):
        """Agent with unparseable last_update is skipped."""
        meta = _make_agent_meta()
        meta.last_update = "not-a-timestamp"
        mock_server.agent_metadata = {"a1": meta}

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents()
        assert result == []

    @patch(_PATCHES["gov_config"])
    @patch(_PATCHES["mcp_server"])
    def test_none_last_update_uses_created_at_with_margin(self, mock_server, mock_config):
        """When last_update is None, uses created_at for age calculation."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        meta = _make_agent_meta(created_at=old_time)
        meta.last_update = None
        meta.created_at = old_time.isoformat()
        mock_server.agent_metadata = {"a1": meta}
        mock_server.monitors = {"a1": _make_monitor(risk=0.9)}
        mock_server.load_monitor_state.return_value = None
        mock_config.compute_proprioceptive_margin.return_value = _margin_info("critical", "risk")

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(critical_margin_timeout_minutes=5)
        assert len(result) == 1
        assert result[0]["reason"] == "critical_margin_timeout"

    @patch(_PATCHES["gov_config"])
    @patch(_PATCHES["mcp_server"])
    def test_z_suffix_timestamp_handled(self, mock_server, mock_config):
        """Timestamps with Z suffix are correctly parsed."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        meta = _make_agent_meta()
        meta.last_update = old_time.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        mock_server.agent_metadata = {"a1": meta}
        mock_server.monitors = {"a1": _make_monitor(risk=0.9)}
        mock_server.load_monitor_state.return_value = None
        mock_config.compute_proprioceptive_margin.return_value = _margin_info("critical", "risk")

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(critical_margin_timeout_minutes=5)
        assert len(result) == 1
        assert result[0]["reason"] == "critical_margin_timeout"

    @patch(_PATCHES["gov_config"])
    @patch(_PATCHES["mcp_server"])
    def test_monitor_exception_does_not_flag_stuck(self, mock_server, mock_config):
        """If monitor.get_metrics raises, agent is NOT flagged as stuck (can't determine margin)."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=45)
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(last_update=old_time),
        }
        monitor = MagicMock()
        monitor.get_metrics.side_effect = RuntimeError("broken")
        mock_server.monitors = {"a1": monitor}

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        result = _detect_stuck_agents(max_age_minutes=30, include_pattern_detection=False)
        # Without margin info, we can't know if agent is stuck - don't assume
        assert len(result) == 0

    @patch(_PATCHES["mcp_server"])
    def test_none_tags_handled(self, mock_server):
        """Agent with tags=None should not crash.

        Also verifies that without monitor state (and therefore no margin info),
        we don't spuriously flag agents as stuck. Inactivity ≠ stuck.
        """
        old_time = datetime.now(timezone.utc) - timedelta(minutes=45)
        meta = _make_agent_meta(last_update=old_time)
        meta.tags = None
        mock_server.agent_metadata = {"a1": meta}
        mock_server.monitors = {}
        mock_server.load_monitor_state.return_value = None

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        # Function should not crash with tags=None
        result = _detect_stuck_agents(max_age_minutes=30)
        # Without margin info, can't determine if stuck - don't assume
        assert len(result) == 0

    @patch(_PATCHES["gov_config"])
    @patch(_PATCHES["mcp_server"])
    def test_persisted_state_used_when_no_monitor(self, mock_server, mock_config):
        """When no in-memory monitor, loads persisted state."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        mock_server.agent_metadata = {
            "a1": _make_agent_meta(last_update=old_time),
        }
        mock_server.monitors = {}

        # Return a mock persisted state
        persisted_state = MagicMock()
        persisted_state.coherence = 0.42
        persisted_state.V = 0.0
        persisted_state.void_active = False
        mock_server.load_monitor_state.return_value = persisted_state

        mock_config.compute_proprioceptive_margin.return_value = _margin_info(
            "critical", "coherence"
        )

        from src.mcp_handlers.lifecycle import _detect_stuck_agents
        # Need to also patch UNITARESMonitor since it's used to wrap persisted state
        with patch("src.mcp_handlers.lifecycle.UNITARESMonitor") as mock_monitor_cls:
            monitor_instance = MagicMock()
            monitor_instance.state = persisted_state
            monitor_instance.get_metrics.return_value = {"mean_risk": 0.7}
            mock_monitor_cls.return_value = monitor_instance

            result = _detect_stuck_agents(
                critical_margin_timeout_minutes=5,
                include_pattern_detection=False,
            )
            assert len(result) == 1
            assert result[0]["reason"] == "critical_margin_timeout"
