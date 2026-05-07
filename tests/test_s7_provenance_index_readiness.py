from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.identity.provenance_index_readiness import (
    S7ProvenanceIndexSnapshot,
    assess_s7_provenance_index_readiness,
    collect_s7_provenance_index_snapshot,
)


def test_s7_index_readiness_defers_when_no_jsonb_rows():
    assessment = assess_s7_provenance_index_readiness(
        S7ProvenanceIndexSnapshot(total_discoveries=42)
    )

    assert assessment["decision"] == "defer"
    assert assessment["reason"] == "no_s7_or_s22_jsonb_rows"
    assert assessment["candidate_indexes"] == []


def test_s7_index_readiness_defers_below_row_threshold():
    snapshot = S7ProvenanceIndexSnapshot(
        total_discoveries=200,
        provenance_chain_rows=50,
        s7_lineage_link_rows=50,
        observed_jsonb_query_count=100,
        query_observation_source="manual",
    )

    assessment = assess_s7_provenance_index_readiness(snapshot)

    assert assessment["decision"] == "defer"
    assert assessment["reason"] == "below_row_volume_threshold"


def test_s7_index_readiness_defers_without_query_pressure():
    snapshot = S7ProvenanceIndexSnapshot(
        total_discoveries=5000,
        provenance_chain_rows=2000,
        s7_lineage_link_rows=2000,
        observed_jsonb_query_count=3,
        query_observation_source="pg_stat_statements",
    )

    assessment = assess_s7_provenance_index_readiness(snapshot)

    assert assessment["decision"] == "defer"
    assert assessment["reason"] == "below_query_pressure_threshold"


def test_s7_index_readiness_recommends_partial_gin_when_thresholds_cross():
    snapshot = S7ProvenanceIndexSnapshot(
        total_discoveries=5000,
        provenance_chain_rows=2000,
        s7_lineage_link_rows=2000,
        s22_context_rows=1500,
        observed_jsonb_query_count=40,
        query_observation_source="manual",
    )

    assessment = assess_s7_provenance_index_readiness(snapshot)

    assert assessment["decision"] == "candidate"
    assert assessment["reason"] == "row_volume_and_query_pressure_crossed_thresholds"
    assert [idx["surface"] for idx in assessment["candidate_indexes"]] == [
        "provenance_chain",
        "s22_context",
    ]
    assert "jsonb_path_ops" in assessment["candidate_indexes"][0]["sql"]
    assert "CONCURRENTLY" in assessment["candidate_indexes"][0]["sql"]


def test_s7_index_readiness_detects_existing_jsonb_index():
    snapshot = S7ProvenanceIndexSnapshot(
        total_discoveries=5000,
        provenance_chain_rows=2000,
        s7_lineage_link_rows=2000,
        observed_jsonb_query_count=40,
        query_observation_source="manual",
        existing_indexes=(
            "idx_knowledge_discoveries_provenance_chain_s7_gin: "
            "CREATE INDEX idx_knowledge_discoveries_provenance_chain_s7_gin "
            "ON knowledge.discoveries USING gin (provenance_chain jsonb_path_ops)",
        ),
    )

    assessment = assess_s7_provenance_index_readiness(snapshot)

    assert assessment["decision"] == "already_indexed"
    assert assessment["indexed_surfaces"] == ["provenance_chain"]
    assert assessment["candidate_indexes"] == []


@pytest.mark.asyncio
async def test_collect_s7_provenance_index_snapshot_reads_counts_and_indexes():
    conn, db = _fake_db()

    snapshot = await collect_s7_provenance_index_snapshot(
        db=db,
        observed_jsonb_query_count=12,
    )

    assert snapshot.total_discoveries == 10
    assert snapshot.provenance_chain_rows == 4
    assert snapshot.s7_lineage_link_rows == 3
    assert snapshot.s22_context_rows == 2
    assert snapshot.observed_jsonb_query_count == 12
    assert snapshot.query_observation_source == "manual"
    assert snapshot.existing_indexes == (
        "idx_knowledge_discoveries_agent: "
        "CREATE INDEX idx_knowledge_discoveries_agent ON knowledge.discoveries(agent_id)",
    )


@pytest.mark.asyncio
async def test_collect_s7_provenance_index_snapshot_uses_pg_stat_statements():
    conn, db = _fake_db()
    conn.fetchval = AsyncMock(return_value=27)

    snapshot = await collect_s7_provenance_index_snapshot(db=db)

    assert snapshot.observed_jsonb_query_count == 27
    assert snapshot.query_observation_source == "pg_stat_statements"
    query = conn.fetchval.call_args.args[0]
    assert "pg_stat_statements" in query
    assert "query NOT ILIKE '%COUNT(*) FILTER%'" in query


@pytest.mark.asyncio
async def test_collect_s7_provenance_index_snapshot_handles_missing_pg_stat():
    conn, db = _fake_db()
    conn.fetchval = AsyncMock(side_effect=Exception("missing extension"))

    snapshot = await collect_s7_provenance_index_snapshot(db=db)

    assert snapshot.observed_jsonb_query_count == 0
    assert snapshot.query_observation_source == "unavailable"


def _fake_db():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={
        "total_discoveries": 10,
        "provenance_chain_rows": 4,
        "s7_lineage_link_rows": 3,
        "s22_context_rows": 2,
    })
    conn.fetch = AsyncMock(return_value=[
        {
            "indexname": "idx_knowledge_discoveries_agent",
            "indexdef": "CREATE INDEX idx_knowledge_discoveries_agent ON knowledge.discoveries(agent_id)",
        }
    ])

    acquire = AsyncMock()
    acquire.__aenter__.return_value = conn
    acquire.__aexit__.return_value = False

    db = MagicMock()
    db.acquire.return_value = acquire
    return conn, db
