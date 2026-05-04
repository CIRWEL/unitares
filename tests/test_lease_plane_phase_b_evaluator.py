"""
Tests for ``scripts/lease_plane/evaluate_phase_b_promotion.py`` — the
deterministic evaluator for §6.1 Phase B promotion criteria.

The evaluator is anchored in audit SQL; these tests stub the cursor with
canned rows so the verdict logic can be exercised without a live DB.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "lease_plane" / "evaluate_phase_b_promotion.py"


@pytest.fixture(scope="module")
def evaluator():
    """Load the script as a module without putting scripts/ on sys.path."""
    name = "evaluate_phase_b_promotion"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # required: dataclass module-name lookup
    spec.loader.exec_module(module)
    return module


class FakeCursor:
    """Stand-in for a RealDictCursor that returns canned rows in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._responses.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *args, **kwargs):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patched_conn(monkeypatch, evaluator, cursor):
    monkeypatch.setattr(evaluator, "_conn", lambda db_url=None: FakeConn(cursor))


def test_unknown_surface_kind_raises(evaluator):
    with pytest.raises(evaluator.UnknownSurfaceKindError):
        evaluator.evaluate("not_a_real_kind", window_days=14)


def test_dialectic_fails_when_window_too_short(evaluator, monkeypatch):
    """Recently-started advisory traffic for a non-write surface_kind:
    criterion 1 fails (calendar gate), 5 is N/A, 4+6 NOT_YET_EVALUABLE."""
    earliest = datetime.now(timezone.utc) - timedelta(days=2)
    cursor = FakeCursor(
        [
            # criterion 1
            {"earliest": earliest, "latest": datetime.now(timezone.utc), "n": 70},
            # criterion 2: has audit.events table
            {"has_table": True},
            # criterion 2: 0 down events
            {"n": 0},
            # criterion 3
            {"distinct_surfaces": 2, "total_conflicts": 2},
            # criterion 4: no audit_session column
            None,
            # criterion 5 is N/A for dialectic — no SQL runs
            # criterion 6: no observation table
            {"has_table": False},
        ]
    )
    _patched_conn(monkeypatch, evaluator, cursor)

    report = evaluator.evaluate("dialectic", window_days=14)

    statuses = {c.number: c.status for c in report.criteria}
    assert statuses[1] == "FAIL"  # window too short
    assert statuses[2] == "PASS"  # 0 down events
    assert statuses[3] == "FAIL"  # only 2 distinct surfaces
    assert statuses[4] == "NOT_YET_EVALUABLE"
    assert statuses[5] == "NOT_APPLICABLE"  # non-write
    assert statuses[6] == "NOT_YET_EVALUABLE"
    assert report.promotable is False


def test_dialectic_eligible_when_all_pass(evaluator, monkeypatch):
    """Counterfactual: §6.1 with full advisory window, sufficient conflicts,
    and instrumentation in place would mark dialectic PROMOTABLE."""
    earliest = datetime.now(timezone.utc) - timedelta(days=20)
    cursor = FakeCursor(
        [
            {"earliest": earliest, "latest": datetime.now(timezone.utc), "n": 500},
            {"has_table": True},
            {"n": 0},
            {"distinct_surfaces": 5, "total_conflicts": 12},
            # criterion 4: pretend audit_session column exists
            {"column_name": "audit_session"},
            # criterion 5 is N/A for dialectic
            # criterion 6: pretend observation table exists
            {"has_table": True},
        ]
    )
    _patched_conn(monkeypatch, evaluator, cursor)

    report = evaluator.evaluate("dialectic", window_days=14)
    statuses = {c.number: c.status for c in report.criteria}
    assert statuses[1] == "PASS"
    assert statuses[3] == "PASS"
    assert statuses[5] == "NOT_APPLICABLE"
    # 4 and 6 still mark NOT_YET_EVALUABLE because the join SQL is reserved
    # for when the instrumentation actually finalizes — this is intentional.
    assert statuses[4] == "NOT_YET_EVALUABLE"
    assert statuses[6] == "NOT_YET_EVALUABLE"
    # Until 4 and 6 stop being NOT_YET_EVALUABLE, even a "fully-passing"
    # window cannot be marked promotable. This is the honest posture.
    assert report.promotable is False


def test_file_coverage_ratio_low(evaluator, monkeypatch):
    """Write surface with low coverage_ratio fails criterion 5."""
    earliest = datetime.now(timezone.utc) - timedelta(days=20)
    cursor = FakeCursor(
        [
            {"earliest": earliest, "latest": datetime.now(timezone.utc), "n": 5000},
            {"has_table": True},
            {"n": 0},
            {"distinct_surfaces": 7, "total_conflicts": 9},
            None,  # criterion 4 — no audit_session
            # criterion 5: low coverage
            {"writes": 100, "acquires": 60, "coverage_ratio": 0.6},
            {"has_table": False},  # criterion 6 — no observation table
        ]
    )
    _patched_conn(monkeypatch, evaluator, cursor)

    report = evaluator.evaluate("file", window_days=14)
    statuses = {c.number: c.status for c in report.criteria}
    assert statuses[5] == "FAIL"
    assert "coverage_ratio=0.600" in next(
        c.detail for c in report.criteria if c.number == 5
    )
    assert report.promotable is False


def test_file_coverage_ratio_no_writes_yet(evaluator, monkeypatch):
    """Write surface with zero write.* audit events → criterion 5 NOT_YET_EVALUABLE,
    not silently FAIL or PASS."""
    earliest = datetime.now(timezone.utc) - timedelta(days=20)
    cursor = FakeCursor(
        [
            {"earliest": earliest, "latest": datetime.now(timezone.utc), "n": 5000},
            {"has_table": True},
            {"n": 0},
            {"distinct_surfaces": 7, "total_conflicts": 9},
            None,
            {"writes": 0, "acquires": 60, "coverage_ratio": None},
            {"has_table": False},
        ]
    )
    _patched_conn(monkeypatch, evaluator, cursor)

    report = evaluator.evaluate("file", window_days=14)
    c5 = next(c for c in report.criteria if c.number == 5)
    assert c5.status == "NOT_YET_EVALUABLE"
    assert "write-class tool emission" in c5.detail


def test_no_advisory_traffic_at_all(evaluator, monkeypatch):
    """A surface_kind with zero advisory events — criterion 1 FAIL, not PASS."""
    cursor = FakeCursor(
        [
            {"earliest": None, "latest": None, "n": 0},
            {"has_table": True},
            {"n": 0},
            {"distinct_surfaces": 0, "total_conflicts": 0},
            None,
            # capture is a write surface_kind, so criterion 5 runs
            {"writes": 0, "acquires": 0, "coverage_ratio": None},
            {"has_table": False},
        ]
    )
    _patched_conn(monkeypatch, evaluator, cursor)

    report = evaluator.evaluate("capture", window_days=14)
    c1 = next(c for c in report.criteria if c.number == 1)
    assert c1.status == "FAIL"
    assert "no advisory traffic" in c1.detail


def test_uptime_fails_with_down_events(evaluator, monkeypatch):
    earliest = datetime.now(timezone.utc) - timedelta(days=20)
    cursor = FakeCursor(
        [
            {"earliest": earliest, "latest": datetime.now(timezone.utc), "n": 100},
            {"has_table": True},
            {"n": 4},  # 4 down events in window
            {"distinct_surfaces": 5, "total_conflicts": 7},
            None,
            {"has_table": False},
        ]
    )
    _patched_conn(monkeypatch, evaluator, cursor)

    report = evaluator.evaluate("dialectic", window_days=14)
    c2 = next(c for c in report.criteria if c.number == 2)
    assert c2.status == "FAIL"
    assert c2.measured["down_events"] == 4


def test_text_format_mentions_eligibility_date(evaluator, monkeypatch):
    """Text output should surface the eligibility-date hint when criterion 1 fails."""
    earliest = datetime.now(timezone.utc) - timedelta(days=2)
    cursor = FakeCursor(
        [
            {"earliest": earliest, "latest": datetime.now(timezone.utc), "n": 70},
            {"has_table": True},
            {"n": 0},
            {"distinct_surfaces": 2, "total_conflicts": 2},
            None,
            {"has_table": False},
        ]
    )
    _patched_conn(monkeypatch, evaluator, cursor)

    report = evaluator.evaluate("dialectic", window_days=14)
    text = evaluator._format_text(report)
    assert "eligible " in text
    assert "VERDICT: NOT PROMOTABLE" in text


def test_main_exit_codes(evaluator, monkeypatch):
    """Exit code contract: 1 not-promotable, 3 unknown surface_kind."""
    # unknown surface_kind path — must not touch DB
    monkeypatch.setattr(
        evaluator, "_conn", lambda db_url=None: pytest.fail("DB must not be touched")
    )
    rc = evaluator.main(["bogus_kind"])
    assert rc == 3
