"""Tests for Vigil's stale-opens propose-only sweep (KG hygiene v1).

The sweep reads audit_knowledge's existing top_stale output (entries already
scored by src/knowledge_graph_lifecycle.py:_score_discovery with age_days,
last_activity_days, bucket). We do NOT re-parse timestamps or re-rank.
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _make_audit_response(top_stale):
    """Mimic GovernanceClient.audit_knowledge response shape."""
    resp = MagicMock()
    resp.success = True
    resp.audit = {
        "top_stale": top_stale,
        "buckets": {"stale": len(top_stale), "candidate_for_archive": 0},
        "total_audited": len(top_stale),
    }
    return resp


@pytest.mark.asyncio
async def test_stale_opens_sweep_returns_top_n_oldest_first():
    """Sweep returns at most 20 entries from top_stale, oldest first."""
    from agents.vigil.agent import VigilAgent

    top_stale = [
        {
            "id": f"d-{i}",
            "summary": f"summary {i}",
            "type": "note",
            "age_days": 60 + i,
            "last_activity_days": 31 + i,
            "bucket": "stale",
            "tags": [],
        }
        for i in range(25)
    ]
    top_stale.sort(key=lambda x: x["last_activity_days"], reverse=True)

    mock_client = MagicMock()
    mock_client.audit_knowledge = AsyncMock(return_value=_make_audit_response(top_stale))

    vigil = VigilAgent(with_hygiene=True)
    result = await vigil._run_stale_opens_sweep(mock_client)

    assert isinstance(result, list)
    assert len(result) == 20
    assert result[0]["id"] == "d-24"  # last_activity_days=55, oldest first
    assert result[-1]["id"] == "d-5"  # 20th-oldest


@pytest.mark.asyncio
async def test_stale_opens_sweep_no_action_taken():
    """Sweep is propose-only — never calls update_discovery or cleanup."""
    from agents.vigil.agent import VigilAgent

    top_stale = [{
        "id": "d-1",
        "summary": "stale",
        "type": "note",
        "age_days": 50,
        "last_activity_days": 45,
        "bucket": "stale",
        "tags": [],
    }]

    mock_client = MagicMock()
    mock_client.audit_knowledge = AsyncMock(return_value=_make_audit_response(top_stale))
    mock_client.cleanup_knowledge = AsyncMock()

    vigil = VigilAgent(with_hygiene=True)
    await vigil._run_stale_opens_sweep(mock_client)

    mock_client.cleanup_knowledge.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_opens_sweep_disabled_by_default():
    """with_hygiene=False → sweep returns [] without calling client."""
    from agents.vigil.agent import VigilAgent

    mock_client = MagicMock()
    mock_client.audit_knowledge = AsyncMock()

    vigil = VigilAgent()
    assert vigil.with_hygiene is False
    result = await vigil._run_stale_opens_sweep(mock_client)
    assert result == []
    mock_client.audit_knowledge.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_opens_sweep_audit_failure_returns_empty():
    """audit_knowledge failure → sweep returns [], does not raise."""
    from agents.vigil.agent import VigilAgent

    failed = MagicMock()
    failed.success = False
    mock_client = MagicMock()
    mock_client.audit_knowledge = AsyncMock(return_value=failed)

    vigil = VigilAgent(with_hygiene=True)
    result = await vigil._run_stale_opens_sweep(mock_client)
    assert result == []


@pytest.mark.asyncio
async def test_stale_opens_sweep_exception_returns_empty():
    """audit_knowledge raising → sweep returns [], does not raise."""
    from agents.vigil.agent import VigilAgent

    mock_client = MagicMock()
    mock_client.audit_knowledge = AsyncMock(side_effect=RuntimeError("boom"))

    vigil = VigilAgent(with_hygiene=True)
    result = await vigil._run_stale_opens_sweep(mock_client)
    assert result == []
