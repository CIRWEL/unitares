"""Tests for R1 v3.3-D consumer patch: provisional_lineage gate in
resolve_trust_tier.

Per docs/ontology/r1-verify-lineage-claim.md §v3.3-D consumer table:
  Trust-tier (S6): Read provisional_lineage; if true, do not contribute to
  tier upgrades.

Implementation: provisional gate runs FIRST in resolve_trust_tier, returning
tier=1 with source='provisional_lineage_gate' regardless of substrate or
compute_trust_tier verdict. Callers can pass prefetched_provisional to skip
the DB lookup; otherwise the gate does its own read against core.identities.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_resolve_trust_tier_returns_tier_1_when_prefetched_provisional_true():
    """Prefetched provisional=True → tier=1 with source='provisional_lineage_gate'.
    Substrate-earned + compute_trust_tier paths are NOT consulted."""
    from src.identity.trust_tier_routing import resolve_trust_tier

    result = await resolve_trust_tier(
        agent_uuid="successor-uuid",
        metadata={"tags": ["persistent", "autonomous"]},  # would be tier=3 otherwise
        prefetched_tags=["persistent", "autonomous"],
        prefetched_provisional=True,
    )

    assert result["tier"] == 1
    assert result["name"] == "provisional"
    assert result["source"] == "provisional_lineage_gate"
    assert "v3.3-D" in result["reason"]


@pytest.mark.asyncio
async def test_resolve_trust_tier_substrate_earned_path_when_prefetched_provisional_false():
    """Prefetched provisional=False → normal substrate-earned flow runs.
    For an agent with substrate-class tags + a metadata-recognized substrate
    earn, the substrate-earned tier_dict (tier=3) is returned."""
    from src.identity.trust_tier_routing import resolve_trust_tier

    # evaluate_substrate_earned returns earned=True
    with patch("src.identity.substrate.evaluate_substrate_earned") as mock_eval:
        mock_eval.return_value = {
            "earned": True,
            "evidence": {"observation_count": 100},
            "conditions": {},
        }
        result = await resolve_trust_tier(
            agent_uuid="lumen-uuid",
            metadata={"trajectory_current": {"identity_confidence": 0.95}},
            prefetched_tags=["persistent", "autonomous"],
            prefetched_provisional=False,
        )

    assert result["tier"] == 3
    assert result["source"] == "substrate_earned"


@pytest.mark.asyncio
async def test_resolve_trust_tier_compute_path_when_no_substrate_no_provisional():
    """Prefetched provisional=False and no substrate tags → falls through to
    compute_trust_tier (per-UUID lifecycle)."""
    from src.identity.trust_tier_routing import resolve_trust_tier

    with patch("src.trajectory_identity.compute_trust_tier") as mock_compute:
        mock_compute.return_value = {
            "tier": 2,
            "name": "session_like",
            "observation_count": 30,
            "identity_confidence": 0.8,
            "lineage_similarity": 0.9,
            "reason": "compute_trust_tier",
        }
        result = await resolve_trust_tier(
            agent_uuid="ephemeral-uuid",
            metadata={},
            prefetched_tags=["ephemeral"],
            prefetched_provisional=False,
        )

    assert result["tier"] == 2
    mock_compute.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_trust_tier_db_lookup_when_provisional_not_prefetched(monkeypatch):
    """When prefetched_provisional=None (default), the gate calls
    backend.is_lineage_provisional. With provisional=True, returns tier=1."""
    from src.identity.trust_tier_routing import resolve_trust_tier

    backend = AsyncMock()
    backend.is_lineage_provisional = AsyncMock(return_value=True)
    monkeypatch.setattr("src.db.get_db", lambda: backend)

    result = await resolve_trust_tier(
        agent_uuid="provisional-uuid",
        metadata={},
    )

    assert result["tier"] == 1
    assert result["source"] == "provisional_lineage_gate"
    backend.is_lineage_provisional.assert_awaited_once_with("provisional-uuid")


@pytest.mark.asyncio
async def test_resolve_trust_tier_db_lookup_provisional_false_proceeds_normally(monkeypatch):
    """is_lineage_provisional → False → normal flow proceeds."""
    from src.identity.trust_tier_routing import resolve_trust_tier

    backend = AsyncMock()
    backend.is_lineage_provisional = AsyncMock(return_value=False)
    monkeypatch.setattr("src.db.get_db", lambda: backend)

    with patch("src.trajectory_identity.compute_trust_tier") as mock_compute:
        mock_compute.return_value = {"tier": 1, "name": "ephemeral",
                                     "observation_count": 0, "identity_confidence": 0.0,
                                     "lineage_similarity": None, "reason": "ephemeral"}
        result = await resolve_trust_tier(
            agent_uuid="non-provisional-uuid",
            metadata={},
            prefetched_tags=["ephemeral"],
        )

    mock_compute.assert_called_once()
    assert result.get("source") != "provisional_lineage_gate"


@pytest.mark.asyncio
async def test_resolve_trust_tier_db_lookup_failure_fails_soft(monkeypatch):
    """is_lineage_provisional raises → treated as not-provisional, normal flow.
    A failed lookup should not silently gate legitimate tier upgrades."""
    from src.identity.trust_tier_routing import resolve_trust_tier

    backend = AsyncMock()
    backend.is_lineage_provisional = AsyncMock(side_effect=RuntimeError("DB offline"))
    monkeypatch.setattr("src.db.get_db", lambda: backend)

    with patch("src.trajectory_identity.compute_trust_tier") as mock_compute:
        mock_compute.return_value = {"tier": 1, "name": "ephemeral",
                                     "observation_count": 0, "identity_confidence": 0.0,
                                     "lineage_similarity": None, "reason": "ephemeral"}
        result = await resolve_trust_tier(
            agent_uuid="error-uuid",
            metadata={},
            prefetched_tags=["ephemeral"],
        )

    assert result.get("source") != "provisional_lineage_gate"
    mock_compute.assert_called_once()


@pytest.mark.asyncio
async def test_provisional_gate_runs_before_substrate_earned_check():
    """A substrate-anchored agent (Vigil/Lumen) whose lineage is provisional
    is gated to tier=1 — the substrate-earned shortcut to tier=3 is
    correctly bypassed. Critical contract: provisional > substrate_earned."""
    from src.identity.trust_tier_routing import resolve_trust_tier

    # Even though we'd be substrate-earned (persistent + autonomous), the
    # provisional gate runs first and returns tier=1.
    with patch("src.identity.substrate.evaluate_substrate_earned") as mock_eval:
        mock_eval.return_value = {
            "earned": True,
            "evidence": {"observation_count": 1000},
            "conditions": {},
        }
        result = await resolve_trust_tier(
            agent_uuid="provisional-substrate-uuid",
            metadata={"trajectory_current": {"identity_confidence": 0.99}},
            prefetched_tags=["persistent", "autonomous"],
            prefetched_provisional=True,  # gate fires
        )

    assert result["tier"] == 1
    assert result["source"] == "provisional_lineage_gate"
    # Substrate-earned was NOT consulted
    mock_eval.assert_not_called()
