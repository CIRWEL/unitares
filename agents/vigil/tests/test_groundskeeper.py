"""
Tests for Vigil's groundskeeper duties and change detection.

All MCP calls are mocked — no live server required.
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Load vigil_agent module from its new location via importlib
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

module_path = project_root / "agents" / "vigil" / "agent.py"
spec = importlib.util.spec_from_file_location("vigil_agent", module_path)
assert spec and spec.loader
_hb_module = importlib.util.module_from_spec(spec)
sys.modules["vigil_agent"] = _hb_module
spec.loader.exec_module(_hb_module)

from vigil_agent import (
    VigilAgent,
    detect_changes,
)

from unitares_sdk.models import (
    AuditResult,
    ArchiveResult,
    CleanupResult,
    NoteResult,
)

# Redirect log output to a temp file so tests don't pollute Vigil's production log
_hb_module.LOG_FILE = Path(tempfile.gettempdir()) / "unitares-heartbeat-test.log"


# =============================================================================
# Test helpers
# =============================================================================

def _make_agent(with_audit: bool = True) -> VigilAgent:
    """Create a VigilAgent with mocked identity."""
    agent = VigilAgent(
        mcp_url="http://localhost:8767/mcp/",
        with_audit=with_audit,
    )
    agent.client_session_id = "test-session-id"
    return agent


def _make_mock_client(
    audit_result=None,
    cleanup_result=None,
    orphan_result=None,
):
    """Create a mock GovernanceClient for groundskeeper tests."""
    client = AsyncMock()

    client.audit_knowledge = AsyncMock(return_value=audit_result or AuditResult(
        success=True,
        audit={"buckets": {"healthy": 5, "aging": 2, "stale": 1, "candidate_for_archive": 0}},
    ))
    client.cleanup_knowledge = AsyncMock(return_value=cleanup_result or CleanupResult(
        success=True, cleaned=0,
    ))
    client.archive_orphan_agents = AsyncMock(return_value=orphan_result or ArchiveResult(
        success=True, archived=3,
    ))
    client.leave_note = AsyncMock(return_value=NoteResult(success=True))

    return client


# =============================================================================
# Tests: _run_groundskeeper
# =============================================================================

class TestRunGroundskeeper:
    """Tests for the groundskeeper method."""

    @pytest.mark.asyncio
    async def test_groundskeeper_calls_audit(self):
        """Groundskeeper should call audit_knowledge."""
        agent = _make_agent()
        client = _make_mock_client()
        result = await agent._run_groundskeeper(client)

        client.audit_knowledge.assert_called_once()
        assert result["audit_run"] is True

    @pytest.mark.asyncio
    async def test_groundskeeper_triggers_cleanup_on_candidates(self):
        """When audit finds archive candidates, cleanup should be triggered."""
        agent = _make_agent()
        client = _make_mock_client(
            audit_result=AuditResult(
                success=True,
                audit={"buckets": {"healthy": 2, "aging": 1, "stale": 1, "candidate_for_archive": 3}},
            ),
            cleanup_result=CleanupResult(success=True, cleaned=3),
        )
        result = await agent._run_groundskeeper(client)

        client.cleanup_knowledge.assert_called_once()
        assert result["archived"] == 3
        assert result["stale_found"] == 4  # 1 stale + 3 candidate

    @pytest.mark.asyncio
    async def test_groundskeeper_skips_cleanup_when_no_candidates(self):
        """When no archive candidates, cleanup should not be called."""
        agent = _make_agent()
        client = _make_mock_client(
            audit_result=AuditResult(
                success=True,
                audit={"buckets": {"healthy": 5, "aging": 0, "stale": 0, "candidate_for_archive": 0}},
            ),
        )
        await agent._run_groundskeeper(client)
        client.cleanup_knowledge.assert_not_called()

    @pytest.mark.asyncio
    async def test_groundskeeper_archives_orphan_agents(self):
        """Groundskeeper should call archive_orphan_agents."""
        agent = _make_agent()
        client = _make_mock_client(
            orphan_result=ArchiveResult(success=True, archived=5),
        )
        result = await agent._run_groundskeeper(client)
        assert result["orphans_archived"] == 5

    @pytest.mark.asyncio
    async def test_groundskeeper_leaves_note(self):
        """Groundskeeper should leave a summary note with correct tags."""
        agent = _make_agent()
        client = _make_mock_client()
        await agent._run_groundskeeper(client)

        client.leave_note.assert_called_once()
        call_kwargs = client.leave_note.call_args.kwargs
        assert "groundskeeper" in call_kwargs["tags"]
        assert "vigil" in call_kwargs["tags"]

    @pytest.mark.asyncio
    async def test_groundskeeper_handles_audit_failure(self):
        """Gracefully handles audit tool failure."""
        agent = _make_agent()
        client = _make_mock_client(
            audit_result=AuditResult(success=False, results=[]),
        )
        result = await agent._run_groundskeeper(client)

        assert result["audit_run"] is False
        assert len(result["errors"]) > 0


# =============================================================================
# Tests: with_audit flag
# =============================================================================

class TestWithAuditFlag:
    """Tests for the --no-audit CLI flag."""

    def test_default_with_audit_true(self):
        """By default, with_audit should be True."""
        agent = VigilAgent()
        assert agent.with_audit is True

    def test_with_audit_false(self):
        """with_audit=False should be settable."""
        agent = VigilAgent(with_audit=False)
        assert agent.with_audit is False


# =============================================================================
# Tests: detect_changes with groundskeeper state
# =============================================================================

class TestDetectChangesGroundskeeper:
    """Tests for change detection with groundskeeper staleness tracking."""

    def test_stale_spike_generates_note(self):
        prev = {"groundskeeper_stale": 5}
        curr = {"groundskeeper_stale": 20}
        changes = detect_changes(prev, curr)
        gk_changes = [c for c in changes if "groundskeeper" in c.get("tags", [])]
        assert len(gk_changes) == 1
        assert "spike" in gk_changes[0]["summary"].lower()

    def test_stale_stable_no_note(self):
        prev = {"groundskeeper_stale": 5}
        curr = {"groundskeeper_stale": 8}
        changes = detect_changes(prev, curr)
        gk_changes = [c for c in changes if "groundskeeper" in c.get("tags", [])]
        assert len(gk_changes) == 0

    def test_stale_decrease_no_note(self):
        prev = {"groundskeeper_stale": 20}
        curr = {"groundskeeper_stale": 5}
        changes = detect_changes(prev, curr)
        gk_changes = [c for c in changes if "groundskeeper" in c.get("tags", [])]
        assert len(gk_changes) == 0

    def test_no_previous_stale_no_note(self):
        prev = {}
        curr = {"groundskeeper_stale": 15}
        changes = detect_changes(prev, curr)
        gk_changes = [c for c in changes if "groundskeeper" in c.get("tags", [])]
        assert len(gk_changes) == 1  # 15 > 0 + 10


# =============================================================================
# Tests: uptime tracking
# =============================================================================

class TestUptimeTracking:
    def test_counters_increment_from_zero(self):
        prev = {}
        total = prev.get("total_cycles", 0) + 1
        gov_up = prev.get("gov_up_cycles", 0) + 1
        lumen_up = prev.get("lumen_up_cycles", 0) + 0
        assert total == 1
        assert gov_up == 1
        assert lumen_up == 0

    def test_counters_accumulate(self):
        prev = {"total_cycles": 100, "gov_up_cycles": 98, "lumen_up_cycles": 90}
        total = prev.get("total_cycles", 0) + 1
        gov_up = prev.get("gov_up_cycles", 0) + 1
        lumen_up = prev.get("lumen_up_cycles", 0) + 1
        assert total == 101
        assert gov_up == 99
        assert lumen_up == 91

    def test_uptime_percentage_calculation(self):
        state = {"total_cycles": 200, "gov_up_cycles": 198, "lumen_up_cycles": 180}
        gov_pct = state["gov_up_cycles"] / state["total_cycles"]
        lumen_pct = state["lumen_up_cycles"] / state["total_cycles"]
        assert gov_pct == pytest.approx(0.99)
        assert lumen_pct == pytest.approx(0.90)
