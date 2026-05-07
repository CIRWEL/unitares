from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.identity.r2_phase1_telemetry import (
    AUDIT_TELEMETRY_SQL,
    IDENTITY_TELEMETRY_SQL,
    LINEAGE_AUDIT_EVENT_TYPES,
    R2Phase1Thresholds,
    assess_r2_phase1_telemetry,
    build_r2_phase1_snapshot,
    collect_r2_phase1_telemetry,
    parse_since,
)


SINCE = datetime(2026, 5, 5, tzinfo=timezone.utc)
NOW = datetime(2026, 6, 5, tzinfo=timezone.utc)


def _identity_row(**overrides):
    row = {
        "lineage_total": 70,
        "active_provisional": 7,
        "active_confirmed": 55,
        "demoted_total": 12,
        "archived_total": 2,
        "declared_since": 68,
        "confirmed_since": 55,
        "demoted_since": 12,
        "archived_since": 2,
        "first_declared_since": SINCE,
        "last_eval_since": NOW,
    }
    row.update(overrides)
    return row


def test_r2_phase1_assessment_defers_until_all_thresholds_pass():
    snapshot = build_r2_phase1_snapshot(
        _identity_row(confirmed_since=3, demoted_since=0),
        [{"event_type": "lineage_promoted", "event_count": 3}],
        since=SINCE,
        observed_at=datetime(2026, 5, 6, tzinfo=timezone.utc),
    )

    assessment = assess_r2_phase1_telemetry(snapshot)

    assert assessment["decision"] == "defer"
    assert assessment["reason"] == "phase2_telemetry_thresholds_unmet"
    assert assessment["checks"]["telemetry_window_days"]["passed"] is False
    assert assessment["checks"]["confirmed_pairs"]["passed"] is False
    assert assessment["checks"]["demoted_pairs"]["passed"] is False
    assert assessment["checks"]["cross_role_rejections"]["passed"] is False
    assert [item["name"] for item in assessment["failed_checks"]] == [
        "telemetry_window_days",
        "confirmed_pairs",
        "demoted_pairs",
        "cross_role_rejections",
    ]
    assert assessment["failed_checks"][1]["remaining"] == 47.0
    assert "Remaining R2 Phase 2 deficits" in assessment["recommendations"][1]


def test_r2_phase1_assessment_allows_phase2_candidate_when_thresholds_pass():
    snapshot = build_r2_phase1_snapshot(
        _identity_row(),
        [
            {"event_type": "lineage_demoted", "event_count": 12},
            {"event_type": "lineage_cross_role_rejected", "event_count": 2},
        ],
        since=SINCE,
        observed_at=NOW,
    )

    assessment = assess_r2_phase1_telemetry(snapshot)

    assert assessment["decision"] == "candidate"
    assert assessment["reason"] == "phase2_telemetry_thresholds_satisfied"
    assert all(check["passed"] for check in assessment["checks"].values())
    assert assessment["failed_checks"] == []


def test_parse_since_accepts_zulu_and_naive_values():
    assert parse_since("2026-05-05T00:00:00Z") == SINCE
    assert parse_since("2026-05-05T00:00:00") == SINCE


@pytest.mark.asyncio
async def test_collect_r2_phase1_telemetry_reads_identity_and_audit_counts():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=_identity_row())
    conn.fetch = AsyncMock(return_value=[
        {
            "event_type": "lineage_demoted",
            "event_count": 12,
            "first_seen_at": SINCE,
            "last_seen_at": NOW,
        },
        {
            "event_type": "lineage_cross_role_rejected",
            "event_count": 2,
            "first_seen_at": SINCE,
            "last_seen_at": NOW,
        },
    ])
    acquire = AsyncMock()
    acquire.__aenter__.return_value = conn
    acquire.__aexit__.return_value = False
    db = MagicMock()
    db.acquire.return_value = acquire

    assessment = await collect_r2_phase1_telemetry(
        db=db,
        since=SINCE,
        now=NOW,
        thresholds=R2Phase1Thresholds(),
    )

    assert assessment["decision"] == "candidate"
    assert conn.fetchrow.await_args.args == (IDENTITY_TELEMETRY_SQL, SINCE)
    assert conn.fetch.await_args.args == (
        AUDIT_TELEMETRY_SQL,
        SINCE,
        list(LINEAGE_AUDIT_EVENT_TYPES),
    )
    assert assessment["snapshot"]["audit_event_counts"]["lineage_demoted"] == 12
