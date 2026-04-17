"""Regression guards for agent_lifecycle timezone handling.

These tests ensure that naive-UTC timestamps (the format UNITARES stores
when no tzinfo is embedded) don't get compared against naive-local
datetime.now(), which would produce off-by-local-offset age values and
silently break orphan archival in non-UTC locales.

Spawned by the 2026-04-16 Watcher follow-up remediation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.agent_lifecycle import _agent_age_hours, build_standardized_agent_info
from src.agent_metadata_model import AgentMetadata


@pytest.fixture
def _now_utc():
    return datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)


def _meta(*, last_update: str | None, created_at: str | None = None) -> AgentMetadata:
    return AgentMetadata(
        agent_id="dummy",
        status="active",
        created_at=created_at or last_update or "",
        last_update=last_update or created_at or "",
    )


class TestAgentAgeHoursTimezoneNormalization:
    def test_naive_utc_timestamp_computes_correct_age(self, _now_utc):
        """Naive-UTC stored timestamps must be interpreted as UTC, not local."""
        six_hours_ago_utc_naive = (_now_utc - timedelta(hours=6)).replace(tzinfo=None).isoformat()
        meta = _meta(last_update=six_hours_ago_utc_naive)

        with patch("src.agent_lifecycle.datetime") as mock_dt:
            # Pass through real fromisoformat and real datetime constants
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.now.return_value = _now_utc
            hours = _agent_age_hours(meta)

        assert hours is not None
        assert hours == pytest.approx(6.0, abs=0.001), (
            f"naive-UTC timestamp 6 hours ago should yield 6.0 hours, got {hours}"
        )

    def test_aware_utc_timestamp_computes_correct_age(self, _now_utc):
        """tz-aware UTC timestamp works the same as before."""
        ts = (_now_utc - timedelta(hours=2)).isoformat()
        meta = _meta(last_update=ts)

        with patch("src.agent_lifecycle.datetime") as mock_dt:
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.now.return_value = _now_utc
            hours = _agent_age_hours(meta)

        assert hours == pytest.approx(2.0, abs=0.001)

    def test_z_suffix_timestamp_computes_correct_age(self, _now_utc):
        """'Z' suffix (common ISO-8601 UTC form) normalizes correctly."""
        ts = (_now_utc - timedelta(hours=3)).replace(tzinfo=None).isoformat() + "Z"
        meta = _meta(last_update=ts)

        with patch("src.agent_lifecycle.datetime") as mock_dt:
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.now.return_value = _now_utc
            hours = _agent_age_hours(meta)

        assert hours == pytest.approx(3.0, abs=0.001)

    def test_unparseable_returns_none(self):
        meta = _meta(last_update="not a date")
        assert _agent_age_hours(meta) is None

    def test_empty_string_returns_none(self):
        meta = _meta(last_update="")
        assert _agent_age_hours(meta) is None
