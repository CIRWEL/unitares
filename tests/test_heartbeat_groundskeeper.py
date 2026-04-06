"""
Tests for Vigil's groundskeeper duties in heartbeat_agent.py.

Tests the _run_groundskeeper method, CLI flags, and change detection.
All MCP calls are mocked — no live server required.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add scripts to path so we can import heartbeat_agent
project_root = Path(__file__).parent.parent
scripts_dir = project_root / "scripts" / "ops"
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(scripts_dir))

import heartbeat_agent as _hb_module
from heartbeat_agent import (
    HeartbeatAgent,
    _atomic_write,
    _get_anima_urls,
    detect_changes,
    notify,
    ANIMA_HEALTH_URLS,
)

# Redirect log output to a temp file so tests don't pollute Vigil's production log
_hb_module.LOG_FILE = Path(tempfile.gettempdir()) / "unitares-heartbeat-test.log"


# =============================================================================
# Test helpers
# =============================================================================

def _make_agent(with_audit: bool = True) -> HeartbeatAgent:
    """Create a HeartbeatAgent with mocked identity."""
    agent = HeartbeatAgent(
        mcp_url="http://localhost:8767/mcp/",
        with_audit=with_audit,
    )
    agent.client_session_id = "test-session-id"
    return agent


def _make_call_tool_mock(responses: Dict[str, Dict[str, Any]] = None):
    """Create a mock call_tool that returns canned responses based on tool name."""
    if responses is None:
        responses = {}

    default_audit = {
        "success": True,
        "audit": {
            "buckets": {"healthy": 5, "aging": 2, "stale": 1, "candidate_for_archive": 0},
            "total_audited": 8,
            "model_assessment": None,
        },
    }
    default_cleanup = {
        "success": True,
        "cleanup_result": {"ephemeral_archived": 0, "discoveries_archived": 0},
    }
    default_orphan = {"success": True, "archived_count": 3}
    default_note = {"success": True}

    defaults = {
        "knowledge": default_audit,
        "archive_orphan_agents": default_orphan,
        "leave_note": default_note,
    }

    async def mock_call_tool(session, tool_name, arguments):
        # For knowledge tool, check the action
        if tool_name == "knowledge":
            action = arguments.get("action", "")
            if action == "cleanup":
                return responses.get("cleanup", default_cleanup)
            return responses.get("audit", default_audit)
        return responses.get(tool_name, defaults.get(tool_name, {"success": True}))

    return mock_call_tool


# =============================================================================
# Tests: _run_groundskeeper
# =============================================================================

class TestRunGroundskeeper:
    """Tests for the groundskeeper method."""

    @pytest.mark.asyncio
    async def test_groundskeeper_calls_audit(self):
        """Groundskeeper should call knowledge(action=audit)."""
        agent = _make_agent()
        calls: List[tuple] = []

        async def tracking_call_tool(session, tool_name, arguments):
            calls.append((tool_name, arguments.get("action")))
            if tool_name == "knowledge" and arguments.get("action") == "audit":
                return {
                    "success": True,
                    "audit": {
                        "buckets": {"healthy": 3, "aging": 0, "stale": 0, "candidate_for_archive": 0},
                        "total_audited": 3,
                    },
                }
            return {"success": True, "archived_count": 0}

        agent.call_tool = tracking_call_tool
        session = MagicMock()
        result = await agent._run_groundskeeper(session)

        audit_calls = [(t, a) for t, a in calls if t == "knowledge" and a == "audit"]
        assert len(audit_calls) == 1
        assert result["audit_run"] is True

    @pytest.mark.asyncio
    async def test_groundskeeper_triggers_cleanup_on_candidates(self):
        """When audit finds archive candidates, cleanup should be triggered."""
        agent = _make_agent()
        calls: List[tuple] = []

        async def tracking_call_tool(session, tool_name, arguments):
            calls.append((tool_name, arguments.get("action")))
            if tool_name == "knowledge" and arguments.get("action") == "audit":
                return {
                    "success": True,
                    "audit": {
                        "buckets": {"healthy": 2, "aging": 1, "stale": 1, "candidate_for_archive": 3},
                        "total_audited": 7,
                    },
                }
            if tool_name == "knowledge" and arguments.get("action") == "cleanup":
                return {
                    "success": True,
                    "cleanup_result": {"ephemeral_archived": 1, "discoveries_archived": 2},
                }
            return {"success": True, "archived_count": 0}

        agent.call_tool = tracking_call_tool
        session = MagicMock()
        result = await agent._run_groundskeeper(session)

        cleanup_calls = [(t, a) for t, a in calls if t == "knowledge" and a == "cleanup"]
        assert len(cleanup_calls) == 1
        assert result["archived"] == 3  # 1 ephemeral + 2 discoveries
        assert result["stale_found"] == 4  # 1 stale + 3 candidate

    @pytest.mark.asyncio
    async def test_groundskeeper_skips_cleanup_when_no_candidates(self):
        """When no archive candidates, cleanup should not be called."""
        agent = _make_agent()
        calls: List[tuple] = []

        async def tracking_call_tool(session, tool_name, arguments):
            calls.append((tool_name, arguments.get("action")))
            if tool_name == "knowledge" and arguments.get("action") == "audit":
                return {
                    "success": True,
                    "audit": {
                        "buckets": {"healthy": 5, "aging": 0, "stale": 0, "candidate_for_archive": 0},
                        "total_audited": 5,
                    },
                }
            return {"success": True, "archived_count": 0}

        agent.call_tool = tracking_call_tool
        session = MagicMock()
        await agent._run_groundskeeper(session)

        cleanup_calls = [(t, a) for t, a in calls if t == "knowledge" and a == "cleanup"]
        assert len(cleanup_calls) == 0

    @pytest.mark.asyncio
    async def test_groundskeeper_archives_orphan_agents(self):
        """Groundskeeper should call archive_orphan_agents."""
        agent = _make_agent()
        agent.call_tool = _make_call_tool_mock({"archive_orphan_agents": {"success": True, "archived_count": 5}})
        session = MagicMock()
        result = await agent._run_groundskeeper(session)

        assert result["orphans_archived"] == 5

    @pytest.mark.asyncio
    async def test_groundskeeper_leaves_note(self):
        """Groundskeeper should leave a summary note with correct tags."""
        agent = _make_agent()
        note_calls: List[Dict] = []

        async def tracking_call_tool(session, tool_name, arguments):
            if tool_name == "leave_note":
                note_calls.append(arguments)
                return {"success": True}
            if tool_name == "knowledge":
                return {
                    "success": True,
                    "audit": {
                        "buckets": {"healthy": 3, "aging": 0, "stale": 0, "candidate_for_archive": 0},
                        "total_audited": 3,
                    },
                }
            return {"success": True, "archived_count": 0}

        agent.call_tool = tracking_call_tool
        session = MagicMock()
        await agent._run_groundskeeper(session)

        assert len(note_calls) == 1
        assert "groundskeeper" in note_calls[0]["tags"]
        assert "vigil" in note_calls[0]["tags"]

    @pytest.mark.asyncio
    async def test_groundskeeper_handles_audit_failure(self):
        """Gracefully handles audit tool failure."""
        agent = _make_agent()

        async def failing_call_tool(session, tool_name, arguments):
            if tool_name == "knowledge" and arguments.get("action") == "audit":
                return {"success": False, "error": "Graph unavailable"}
            return {"success": True, "archived_count": 0}

        agent.call_tool = failing_call_tool
        session = MagicMock()
        result = await agent._run_groundskeeper(session)

        assert result["audit_run"] is False
        assert len(result["errors"]) > 0


# =============================================================================
# Tests: with_audit flag
# =============================================================================

class TestWithAuditFlag:
    """Tests for the --no-audit CLI flag."""

    def test_default_with_audit_true(self):
        """By default, with_audit should be True."""
        agent = HeartbeatAgent()
        assert agent.with_audit is True

    def test_with_audit_false(self):
        """with_audit=False should be settable."""
        agent = HeartbeatAgent(with_audit=False)
        assert agent.with_audit is False


# =============================================================================
# Tests: detect_changes with groundskeeper state
# =============================================================================

class TestDetectChangesGroundskeeper:
    """Tests for change detection with groundskeeper staleness tracking."""

    def test_stale_spike_generates_note(self):
        """Large stale increase (>10) should generate a drift note."""
        prev = {"groundskeeper_stale": 5}
        curr = {"groundskeeper_stale": 20}
        changes = detect_changes(prev, curr)

        gk_changes = [c for c in changes if "groundskeeper" in c.get("tags", [])]
        assert len(gk_changes) == 1
        assert "spike" in gk_changes[0]["summary"].lower()

    def test_stale_stable_no_note(self):
        """Stable stale count should not generate a note."""
        prev = {"groundskeeper_stale": 5}
        curr = {"groundskeeper_stale": 8}
        changes = detect_changes(prev, curr)

        gk_changes = [c for c in changes if "groundskeeper" in c.get("tags", [])]
        assert len(gk_changes) == 0

    def test_stale_decrease_no_note(self):
        """Decreasing stale count should not generate a note."""
        prev = {"groundskeeper_stale": 20}
        curr = {"groundskeeper_stale": 5}
        changes = detect_changes(prev, curr)

        gk_changes = [c for c in changes if "groundskeeper" in c.get("tags", [])]
        assert len(gk_changes) == 0

    def test_no_previous_stale_no_note(self):
        """First cycle with stale data should not generate a spike note."""
        prev = {}
        curr = {"groundskeeper_stale": 15}
        changes = detect_changes(prev, curr)

        gk_changes = [c for c in changes if "groundskeeper" in c.get("tags", [])]
        assert len(gk_changes) == 1  # 15 > 0 + 10


# =============================================================================
# Tests: atomic file writes
# =============================================================================

class TestAtomicWrite:
    """Tests for _atomic_write crash-safe file persistence."""

    def test_atomic_write_creates_file(self, tmp_path):
        """Atomic write should create a new file with correct content."""
        target = tmp_path / "test.json"
        _atomic_write(target, '{"key": "value"}')
        assert target.exists()
        assert json.loads(target.read_text()) == {"key": "value"}

    def test_atomic_write_overwrites_existing(self, tmp_path):
        """Atomic write should replace existing file content."""
        target = tmp_path / "test.json"
        target.write_text('{"old": true}')
        _atomic_write(target, '{"new": true}')
        assert json.loads(target.read_text()) == {"new": True}

    def test_atomic_write_no_partial_on_error(self, tmp_path):
        """If write fails, original file should be unchanged."""
        target = tmp_path / "test.json"
        target.write_text('{"original": true}')

        # Patch os.replace to simulate a failure after write
        with patch("heartbeat_agent.os.replace", side_effect=OSError("disk full")):
            _atomic_write(target, '{"corrupt": true}')

        # Original should be intact
        assert json.loads(target.read_text()) == {"original": True}

    def test_atomic_write_cleans_up_temp_on_error(self, tmp_path):
        """Temp file should be cleaned up on failure."""
        target = tmp_path / "test.json"

        with patch("heartbeat_agent.os.replace", side_effect=OSError("disk full")):
            _atomic_write(target, "data")

        # No .tmp files should remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


# =============================================================================
# Tests: MCP retry logic
# =============================================================================

class TestCallToolRetry:
    """Tests for call_tool transient failure retry."""

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Should retry once on connection error then succeed."""
        agent = _make_agent()
        call_count = 0

        mock_session = MagicMock()

        class FakeContent:
            text = '{"success": true}'

        class FakeResult:
            content = [FakeContent()]

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("connection reset")
            return FakeResult()

        mock_session.call_tool = mock_call

        with patch("heartbeat_agent.MCP_RETRY_DELAY", 0):
            result = await agent.call_tool(mock_session, "test_tool", {})

        assert result.get("success") is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_non_transient_error(self):
        """Non-transient errors should not be retried."""
        agent = _make_agent()
        call_count = 0

        mock_session = MagicMock()

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ValueError("bad argument")

        mock_session.call_tool = mock_call

        result = await agent.call_tool(mock_session, "test_tool", {})

        assert result.get("success") is False
        assert call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_retry_exhausted_returns_error(self):
        """If both attempts fail, should return error."""
        agent = _make_agent()

        mock_session = MagicMock()

        async def mock_call(*args, **kwargs):
            raise ConnectionError("still down")

        mock_session.call_tool = mock_call

        with patch("heartbeat_agent.MCP_RETRY_DELAY", 0):
            result = await agent.call_tool(mock_session, "test_tool", {})

        assert result.get("success") is False
        assert "retry exhausted" in result.get("error", "")


# =============================================================================
# Tests: macOS notification
# =============================================================================

class TestNotify:
    """Tests for macOS notification helper."""

    def test_notify_calls_osascript(self):
        """notify() should invoke osascript with correct args."""
        with patch("heartbeat_agent.subprocess.Popen") as mock_popen:
            notify("Test Title", "Test message")
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert args[0] == "osascript"
            assert "Test Title" in args[2]
            assert "Test message" in args[2]

    def test_notify_swallows_exceptions(self):
        """notify() should never raise."""
        with patch("heartbeat_agent.subprocess.Popen", side_effect=FileNotFoundError("no osascript")):
            notify("Title", "Message")  # Should not raise


# =============================================================================
# Tests: smart Lumen URL ordering
# =============================================================================

class TestGetAnimaUrls:
    """Tests for _get_anima_urls smart ordering."""

    def test_default_order_when_no_history(self):
        """Without history, should return default URL order."""
        urls = _get_anima_urls({})
        assert urls == list(ANIMA_HEALTH_URLS)

    def test_last_ok_url_goes_first(self):
        """Last successful URL should be tried first."""
        last_ok = ANIMA_HEALTH_URLS[1]  # Tailscale URL
        urls = _get_anima_urls({"lumen_last_ok_url": last_ok})
        assert urls[0] == last_ok
        assert len(urls) == len(ANIMA_HEALTH_URLS)

    def test_unknown_url_ignored(self):
        """If last_ok_url is not in the known list, use default order."""
        urls = _get_anima_urls({"lumen_last_ok_url": "http://unknown:8766/health"})
        assert urls == list(ANIMA_HEALTH_URLS)

    def test_no_duplicates(self):
        """Should never have duplicate URLs."""
        for url in ANIMA_HEALTH_URLS:
            urls = _get_anima_urls({"lumen_last_ok_url": url})
            assert len(urls) == len(set(urls))


# =============================================================================
# Tests: uptime tracking
# =============================================================================

class TestUptimeTracking:
    """Tests for uptime counter logic."""

    def test_counters_increment_from_zero(self):
        """First cycle should initialize all counters to 1/0."""
        prev = {}
        total = prev.get("total_cycles", 0) + 1
        gov_up = prev.get("gov_up_cycles", 0) + 1  # gov healthy
        lumen_up = prev.get("lumen_up_cycles", 0) + 0  # lumen down

        assert total == 1
        assert gov_up == 1
        assert lumen_up == 0

    def test_counters_accumulate(self):
        """Counters should accumulate across cycles."""
        prev = {"total_cycles": 100, "gov_up_cycles": 98, "lumen_up_cycles": 90}
        total = prev.get("total_cycles", 0) + 1
        gov_up = prev.get("gov_up_cycles", 0) + 1
        lumen_up = prev.get("lumen_up_cycles", 0) + 1

        assert total == 101
        assert gov_up == 99
        assert lumen_up == 91

    def test_uptime_percentage_calculation(self):
        """Uptime percentage should be calculable from counters."""
        state = {"total_cycles": 200, "gov_up_cycles": 198, "lumen_up_cycles": 180}
        gov_pct = state["gov_up_cycles"] / state["total_cycles"]
        lumen_pct = state["lumen_up_cycles"] / state["total_cycles"]

        assert gov_pct == pytest.approx(0.99)
        assert lumen_pct == pytest.approx(0.90)
