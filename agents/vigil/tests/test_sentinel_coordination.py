"""Tests for Vigil's Sentinel-coordination arc.

Vigil reads high-severity Sentinel notes from the KG at the start of each
cycle and either references them in its check-in or forces a groundskeeper
pass, depending on the finding type. These tests pin the behavior.
"""

import importlib.util
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

module_path = project_root / "agents" / "vigil" / "agent.py"
spec = importlib.util.spec_from_file_location("heartbeat_agent", module_path)
assert spec and spec.loader
_hb_module = importlib.util.module_from_spec(spec)
sys.modules["heartbeat_agent"] = _hb_module
spec.loader.exec_module(_hb_module)

from heartbeat_agent import HeartbeatAgent, _filter_sentinel_findings

from unitares_sdk.models import (
    ArchiveResult,
    AuditResult,
    CleanupResult,
    NoteResult,
    SearchResult,
)

_hb_module.LOG_FILE = Path(tempfile.gettempdir()) / "unitares-heartbeat-test.log"


# =============================================================================
# Pure filter tests
# =============================================================================

class TestFilterSentinelFindings:
    def test_extracts_sentinel_high_notes(self):
        results = [
            {
                "id": "d1",
                "summary": "[Sentinel] coordinated drop",
                "tags": ["sentinel", "coordinated_coherence_drop", "high"],
                "created_at": "2026-04-14T10:00:00+00:00",
            },
        ]
        out = _filter_sentinel_findings(results, since_iso=None)
        assert len(out) == 1
        assert out[0]["type"] == "coordinated_coherence_drop"
        assert out[0]["id"] == "d1"

    def test_drops_notes_older_than_since_iso(self):
        results = [
            {
                "id": "old",
                "summary": "stale",
                "tags": ["sentinel", "verdict_distribution_shift", "high"],
                "created_at": "2026-04-14T09:00:00+00:00",
            },
            {
                "id": "new",
                "summary": "fresh",
                "tags": ["sentinel", "verdict_distribution_shift", "high"],
                "created_at": "2026-04-14T11:00:00+00:00",
            },
        ]
        out = _filter_sentinel_findings(results, since_iso="2026-04-14T10:00:00+00:00")
        assert [f["id"] for f in out] == ["new"]

    def test_drops_non_sentinel_and_non_high(self):
        results = [
            # Missing "sentinel" tag
            {
                "id": "a",
                "tags": ["vigil", "groundskeeper", "audit"],
                "created_at": "2026-04-14T10:00:00+00:00",
            },
            # Missing "high" tag
            {
                "id": "b",
                "tags": ["sentinel", "fleet_entropy_outlier"],
                "created_at": "2026-04-14T10:00:00+00:00",
            },
            # Valid
            {
                "id": "c",
                "summary": "ok",
                "tags": ["sentinel", "correlated_governance_events", "high"],
                "created_at": "2026-04-14T10:00:00+00:00",
            },
        ]
        out = _filter_sentinel_findings(results, since_iso=None)
        assert [f["id"] for f in out] == ["c"]

    def test_handles_missing_created_at_gracefully(self):
        results = [{
            "id": "n",
            "summary": "no ts",
            "tags": ["sentinel", "verdict_distribution_shift", "high"],
        }]
        # No created_at and no since_iso → keep it
        out = _filter_sentinel_findings(results, since_iso=None)
        assert len(out) == 1
        # No created_at but since_iso set → still keep (can't prove it's old)
        out = _filter_sentinel_findings(results, since_iso="2026-04-14T10:00:00+00:00")
        assert len(out) == 1


# =============================================================================
# Read-from-KG tests
# =============================================================================

def _make_agent(with_audit: bool = True) -> HeartbeatAgent:
    agent = HeartbeatAgent(mcp_url="http://localhost:8767/mcp/", with_audit=with_audit)
    agent.client_session_id = "test-session-id"
    return agent


def _mock_search_result(results):
    return SearchResult(success=True, results=results)


class TestReadSentinelFindings:
    @pytest.mark.asyncio
    async def test_returns_filtered_findings(self):
        agent = _make_agent()
        client = MagicMock()
        client.search_knowledge = AsyncMock(return_value=_mock_search_result([
            {
                "id": "x",
                "summary": "fleet drop",
                "tags": ["sentinel", "coordinated_coherence_drop", "high"],
                "created_at": "2026-04-14T11:00:00+00:00",
            },
        ]))

        out = await agent._read_sentinel_findings(
            client, since_iso="2026-04-14T10:00:00+00:00"
        )
        assert len(out) == 1
        assert out[0]["type"] == "coordinated_coherence_drop"
        client.search_knowledge.assert_awaited_once_with(
            query="sentinel", tags=["sentinel"], limit=10, semantic=False,
        )

    @pytest.mark.asyncio
    async def test_returns_empty_on_search_error(self):
        agent = _make_agent()
        client = MagicMock()
        client.search_knowledge = AsyncMock(side_effect=RuntimeError("kg down"))

        out = await agent._read_sentinel_findings(client, since_iso=None)
        assert out == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_unsuccessful_result(self):
        agent = _make_agent()
        client = MagicMock()
        client.search_knowledge = AsyncMock(
            return_value=SearchResult(success=False, error="no index")
        )
        out = await agent._read_sentinel_findings(client, since_iso=None)
        assert out == []


# =============================================================================
# End-to-end cycle tests
# =============================================================================

def _full_mock_client(search_results=None):
    """Client with enough surface to run a full Vigil cycle in tests."""
    client = MagicMock()
    client.search_knowledge = AsyncMock(return_value=_mock_search_result(
        search_results or []
    ))
    client.audit_knowledge = AsyncMock(return_value=AuditResult(
        success=True,
        results=[{"buckets": {"healthy": 5, "aging": 2, "stale": 0, "candidate_for_archive": 0}}],
    ))
    client.cleanup_knowledge = AsyncMock(return_value=CleanupResult(success=True, cleaned=0))
    client.archive_orphan_agents = AsyncMock(return_value=ArchiveResult(success=True, archived=0))
    client.leave_note = AsyncMock(return_value=NoteResult(success=True))
    return client


def _patch_health_checks(monkeypatch):
    """Stub network health checks so run_cycle doesn't try real HTTP."""
    monkeypatch.setattr(_hb_module, "check_http_health", lambda *a, **kw: (True, "ok (1ms)"))


class TestRunCycleCoordination:
    @pytest.mark.asyncio
    async def test_audit_triggering_finding_forces_groundskeeper(self, monkeypatch):
        _patch_health_checks(monkeypatch)

        agent = _make_agent(with_audit=False)  # audit OFF by default
        agent.load_state = lambda: {"cycle_time": "2026-04-14T10:00:00+00:00"}

        client = _full_mock_client(search_results=[{
            "id": "shift1",
            "summary": "10% reject rate",
            "tags": ["sentinel", "verdict_distribution_shift", "high"],
            "created_at": "2026-04-14T11:00:00+00:00",
        }])

        result = await agent.run_cycle(client)

        assert result is not None
        # Groundskeeper ran despite with_audit=False
        client.audit_knowledge.assert_awaited()
        # Finding and the forced-audit marker both appear in the check-in summary
        assert "Sentinel/verdict_distribution_shift" in result.summary
        assert "Groundskeeper forced by Sentinel coordination" in result.summary

    @pytest.mark.asyncio
    async def test_non_audit_finding_references_but_does_not_force(self, monkeypatch):
        _patch_health_checks(monkeypatch)

        agent = _make_agent(with_audit=False)
        agent.load_state = lambda: {"cycle_time": "2026-04-14T10:00:00+00:00"}

        client = _full_mock_client(search_results=[{
            "id": "drop1",
            "summary": "coherence fell 0.2 across 3 agents",
            "tags": ["sentinel", "coordinated_coherence_drop", "high"],
            "created_at": "2026-04-14T11:00:00+00:00",
        }])

        result = await agent.run_cycle(client)

        # Coherence drop does NOT force an audit — groundskeeper stays off
        client.audit_knowledge.assert_not_awaited()
        # But the finding IS referenced in the check-in so the chain is auditable
        assert "Sentinel/coordinated_coherence_drop" in result.summary

    @pytest.mark.asyncio
    async def test_no_sentinel_findings_preserves_normal_cycle(self, monkeypatch):
        _patch_health_checks(monkeypatch)

        agent = _make_agent(with_audit=True)
        agent.load_state = lambda: {"cycle_time": "2026-04-14T10:00:00+00:00"}

        client = _full_mock_client(search_results=[])

        result = await agent.run_cycle(client)

        assert result is not None
        assert "Sentinel/" not in result.summary
        # Groundskeeper runs as normal when with_audit=True
        client.audit_knowledge.assert_awaited()

    @pytest.mark.asyncio
    async def test_broken_search_does_not_break_cycle(self, monkeypatch):
        _patch_health_checks(monkeypatch)

        agent = _make_agent(with_audit=True)
        agent.load_state = lambda: {"cycle_time": "2026-04-14T10:00:00+00:00"}

        client = _full_mock_client()
        client.search_knowledge = AsyncMock(side_effect=RuntimeError("kg timeout"))

        result = await agent.run_cycle(client)

        # Cycle completes, no Sentinel findings referenced, groundskeeper still ran
        assert result is not None
        assert "Sentinel/" not in result.summary
        client.audit_knowledge.assert_awaited()
