"""Tests for _watcher_summary_from_rows — the pure aggregator behind
/v1/watcher/summary. We test the aggregator directly so the test doesn't need
to stand up Starlette or touch the filesystem; endpoint wiring is covered by
the dashboard-allowlist regression and the route-registration smoke."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.http_api import _watcher_summary_from_rows


NOW = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)


def _row(**kwargs):
    base = {
        "pattern": "P001",
        "severity": "high",
        "detected_at": NOW.isoformat(),
        "status": "surfaced",
    }
    base.update(kwargs)
    return base


class TestStatusAndSeverityCounts:
    def test_empty_input_returns_zeroed_shape(self):
        out = _watcher_summary_from_rows([], now=NOW, window_days=7)
        assert out["total"] == 0
        assert out["by_status"] == {}
        assert out["by_severity_open"] == {}
        assert out["patterns"] == []
        assert len(out["timeline"]) == 7
        assert all(d["detected"] == 0 for d in out["timeline"])

    def test_status_counter_counts_everything(self):
        rows = [
            _row(status="surfaced"),
            _row(status="surfaced"),
            _row(status="resolved"),
            _row(status="dismissed"),
        ]
        out = _watcher_summary_from_rows(rows, now=NOW)
        assert out["by_status"] == {"surfaced": 2, "resolved": 1, "dismissed": 1}
        assert out["total"] == 4

    def test_severity_counts_only_open_findings(self):
        """by_severity_open is the actionable queue; resolved/dismissed shouldn't
        show up there or the panel implies ongoing severity that isn't real."""
        rows = [
            _row(severity="critical", status="surfaced"),
            _row(severity="high", status="surfaced"),
            _row(severity="critical", status="resolved"),   # closed — excluded
            _row(severity="critical", status="dismissed"),  # closed — excluded
        ]
        out = _watcher_summary_from_rows(rows, now=NOW)
        assert out["by_severity_open"] == {"critical": 1, "high": 1}


class TestPatternTable:
    def test_pattern_breakdown_with_dismiss_ratio(self):
        """Patterns that get dismissed frequently are the false-positive-heavy
        rules — surfacing dismiss_ratio on the panel lets an operator spot
        noisy rules at a glance."""
        rows = [
            _row(pattern="P008", status="dismissed"),
            _row(pattern="P008", status="dismissed"),
            _row(pattern="P008", status="dismissed"),  # 3/3 dismissed — noisy
            _row(pattern="P001", status="resolved"),
            _row(pattern="P001", status="resolved"),   # 0/2 dismissed — signal
            _row(pattern="P001", status="surfaced"),   # 1 still open
        ]
        out = _watcher_summary_from_rows(rows, now=NOW)
        by = {p["pattern"]: p for p in out["patterns"]}
        assert by["P008"]["dismissed"] == 3 and by["P008"]["resolved"] == 0
        assert by["P008"]["dismiss_ratio"] == pytest.approx(1.0)
        assert by["P001"]["resolved"] == 2 and by["P001"]["dismissed"] == 0
        assert by["P001"]["dismiss_ratio"] == pytest.approx(0.0)

    def test_dismiss_ratio_is_none_when_nothing_closed(self):
        """With no closed findings for a pattern, the ratio is undefined —
        returning None lets the frontend render a dash instead of 0.0 which
        would falsely imply 'this rule is never dismissed'."""
        out = _watcher_summary_from_rows([_row(pattern="P999", status="surfaced")], now=NOW)
        p = out["patterns"][0]
        assert p["surfaced"] == 1
        assert p["dismiss_ratio"] is None

    def test_patterns_sorted_by_open_count_desc(self):
        rows = [
            _row(pattern="P_LOW", status="surfaced"),
            _row(pattern="P_HIGH", status="surfaced"),
            _row(pattern="P_HIGH", status="surfaced"),
            _row(pattern="P_HIGH", status="surfaced"),
        ]
        out = _watcher_summary_from_rows(rows, now=NOW)
        assert [p["pattern"] for p in out["patterns"]] == ["P_HIGH", "P_LOW"]


class TestTimeline:
    def test_timeline_spans_full_window_with_zeros(self):
        """Even with a single finding, the chart should have a point for every
        day in the window so the line renders continuously, not with gaps."""
        rows = [_row(detected_at=NOW.isoformat())]
        out = _watcher_summary_from_rows(rows, now=NOW, window_days=5)
        assert len(out["timeline"]) == 5
        days_with_data = [d for d in out["timeline"] if d["detected"] > 0]
        assert len(days_with_data) == 1
        assert days_with_data[0]["detected"] == 1

    def test_timeline_buckets_detections_by_day(self):
        day_a = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
        day_b = datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc)
        rows = [
            _row(detected_at=day_a.isoformat()),
            _row(detected_at=day_a.isoformat()),
            _row(detected_at=day_b.isoformat()),
        ]
        out = _watcher_summary_from_rows(rows, now=NOW, window_days=7)
        by_day = {d["day"]: d for d in out["timeline"]}
        assert by_day["2026-04-20"]["detected"] == 2
        assert by_day["2026-04-22"]["detected"] == 1

    def test_timeline_excludes_findings_outside_window(self):
        old = (NOW - timedelta(days=45)).isoformat()
        out = _watcher_summary_from_rows([_row(detected_at=old)], now=NOW, window_days=30)
        assert all(d["detected"] == 0 for d in out["timeline"])

    def test_timeline_captures_resolved_and_dismissed_timestamps(self):
        resolved_day = datetime(2026, 4, 21, 14, 0, tzinfo=timezone.utc)
        dismissed_day = datetime(2026, 4, 22, 14, 0, tzinfo=timezone.utc)
        rows = [
            _row(
                detected_at=(NOW - timedelta(days=1)).isoformat(),
                status="resolved",
                resolved_at=resolved_day.isoformat(),
            ),
            _row(
                detected_at=(NOW - timedelta(days=1)).isoformat(),
                status="dismissed",
                dismissed_at=dismissed_day.isoformat(),
            ),
        ]
        out = _watcher_summary_from_rows(rows, now=NOW, window_days=7)
        by_day = {d["day"]: d for d in out["timeline"]}
        assert by_day["2026-04-21"]["resolved"] == 1
        assert by_day["2026-04-22"]["dismissed"] == 1


class TestRobustness:
    def test_row_with_trailing_Z_timestamp_parses(self):
        """Watcher writes timestamps like '2026-04-14T10:57:11Z' — Python 3.10
        datetime.fromisoformat rejects the trailing Z, so the aggregator must
        tolerate it."""
        rows = [_row(detected_at="2026-04-23T00:00:00Z")]
        out = _watcher_summary_from_rows(rows, now=NOW, window_days=2)
        by_day = {d["day"]: d for d in out["timeline"]}
        assert by_day["2026-04-23"]["detected"] == 1

    def test_row_with_malformed_timestamp_does_not_crash(self):
        rows = [_row(detected_at="not-a-date")]
        out = _watcher_summary_from_rows(rows, now=NOW)
        # Still counted in totals, just not placed on the timeline
        assert out["total"] == 1
        assert all(d["detected"] == 0 for d in out["timeline"])

    def test_row_without_pattern_falls_under_question_mark(self):
        rows = [_row(pattern=None, status="surfaced")]
        out = _watcher_summary_from_rows(rows, now=NOW)
        assert out["patterns"][0]["pattern"] == "?"
