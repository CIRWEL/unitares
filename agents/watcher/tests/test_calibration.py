"""Tests for the calibration primitives — Jeffreys interval, file
classifier, exponential-decay weighting, and per-(pattern, file_class)
precision aggregation."""

from datetime import datetime, timedelta, timezone

import pytest

from agents.watcher.calibration import jeffreys_lower_bound


class TestJeffreysLowerBound:
    """Beta(0.5, 0.5) prior. Posterior is Beta(0.5+s, 0.5+f). We return
    the 2.5% lower quantile, which behaves well at small N (no division
    by zero, monotonic in N) but is NOT 0.5 at N=0 — it's near zero. A
    min_n gate at the demotion callsite handles 'unmeasured' separately
    from 'measured-as-zero'."""

    def test_returns_float_in_unit_interval(self):
        for s, f in [(0, 0), (1, 0), (0, 1), (5, 5), (50, 50), (100, 0), (0, 100)]:
            lb = jeffreys_lower_bound(s, f)
            assert 0.0 <= lb <= 1.0, f"({s},{f}) → {lb} out of [0,1]"

    def test_n_zero_returns_low_value(self):
        # No observations — posterior is Beta(0.5, 0.5), 2.5% quantile ≈ 0.0015
        lb = jeffreys_lower_bound(0, 0)
        assert lb < 0.01, f"N=0 should return near-zero, got {lb}"

    def test_all_successes_high_n_high_lower_bound(self):
        # 100 successes, 0 failures: posterior tightly above 0.95
        lb = jeffreys_lower_bound(100, 0)
        assert lb > 0.95, f"100/0 should give high lower bound, got {lb}"

    def test_all_failures_high_n_zero_lower_bound(self):
        lb = jeffreys_lower_bound(0, 100)
        assert lb < 0.05, f"0/100 should give near-zero lower bound, got {lb}"

    def test_monotonic_in_successes(self):
        # Adding successes can only raise the lower bound
        lo = jeffreys_lower_bound(5, 5)
        hi = jeffreys_lower_bound(15, 5)
        assert hi > lo, f"more successes should raise lower bound: {lo} → {hi}"

    def test_negative_input_raises(self):
        with pytest.raises(ValueError):
            jeffreys_lower_bound(-1, 0)
        with pytest.raises(ValueError):
            jeffreys_lower_bound(0, -1)

    def test_fractional_input_accepted(self):
        # Decay-weighted counts are floats, not ints. The function must accept them.
        lb = jeffreys_lower_bound(2.5, 7.5)
        assert 0.0 <= lb <= 1.0


from agents.watcher.calibration import classify_file, FileClass


class TestClassifyFile:
    """File class is the second axis of the calibration bucket. Six
    coarse classes are enough to capture the heterogeneity the dialectic
    flagged (a regex that's 90% precise on app code and 10% on tests
    averages to ~50% globally and gets demoted everywhere)."""

    def test_test_files(self):
        assert classify_file("/repo/agents/watcher/tests/test_x.py") == FileClass.TEST
        assert classify_file("/repo/tests/integration/foo.py") == FileClass.TEST
        assert classify_file("/repo/foo_test.py") == FileClass.TEST
        assert classify_file("/repo/test_bar.py") == FileClass.TEST

    def test_migration_files(self):
        assert classify_file("/repo/migrations/018_foo.sql") == FileClass.MIGRATION
        assert classify_file("/repo/db/migrations/up.py") == FileClass.MIGRATION

    def test_generated_files(self):
        assert classify_file("/repo/build/foo.py") == FileClass.GENERATED
        assert classify_file("/repo/dist/bundle.js") == FileClass.GENERATED
        assert classify_file("/repo/__pycache__/x.pyc") == FileClass.GENERATED
        assert classify_file("/repo/foo.pb.go") == FileClass.GENERATED

    def test_config_files(self):
        assert classify_file("/repo/pyproject.toml") == FileClass.CONFIG
        assert classify_file("/repo/setup.cfg") == FileClass.CONFIG
        assert classify_file("/repo/.github/workflows/ci.yml") == FileClass.CONFIG
        assert classify_file("/repo/Makefile") == FileClass.CONFIG

    def test_doc_files(self):
        assert classify_file("/repo/README.md") == FileClass.DOC
        assert classify_file("/repo/docs/foo.md") == FileClass.DOC
        assert classify_file("/repo/CHANGELOG") == FileClass.DOC

    def test_app_default(self):
        assert classify_file("/repo/src/server.py") == FileClass.APP
        assert classify_file("/repo/agents/watcher/agent.py") == FileClass.APP
        assert classify_file("/repo/governance_core/eisv.py") == FileClass.APP

    def test_test_wins_over_app(self):
        # tests/ is the strongest signal — it sits inside src/ in some layouts
        assert classify_file("/repo/src/tests/foo.py") == FileClass.TEST


from agents.watcher.calibration import decay_weight, parse_iso_z


class TestDecayWeight:
    """Exponential decay replaces the 90-day hard cutoff. Half-life ~30d
    means a 60-day-old observation contributes 0.25× of a fresh one.
    Old observations don't fall off a cliff; they just matter less."""

    def test_zero_age_full_weight(self):
        now = datetime(2026, 4, 27, tzinfo=timezone.utc)
        assert decay_weight(now, now, half_life_days=30.0) == pytest.approx(1.0)

    def test_one_half_life_half_weight(self):
        now = datetime(2026, 4, 27, tzinfo=timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        assert decay_weight(thirty_days_ago, now, half_life_days=30.0) == pytest.approx(0.5, rel=1e-9)

    def test_two_half_lives_quarter_weight(self):
        now = datetime(2026, 4, 27, tzinfo=timezone.utc)
        sixty_days_ago = now - timedelta(days=60)
        assert decay_weight(sixty_days_ago, now, half_life_days=30.0) == pytest.approx(0.25, rel=1e-9)

    def test_future_timestamps_clamp_to_one(self):
        """Clock skew shouldn't manufacture > 1.0 weights."""
        now = datetime(2026, 4, 27, tzinfo=timezone.utc)
        future = now + timedelta(hours=1)
        assert decay_weight(future, now, half_life_days=30.0) == pytest.approx(1.0)

    def test_naive_datetime_raises(self):
        now = datetime.now(timezone.utc)
        naive = datetime(2026, 4, 1)
        with pytest.raises(ValueError):
            decay_weight(naive, now, half_life_days=30.0)


class TestParseIsoZ:
    """Tolerate the two timestamp formats actually present in
    findings.jsonl: '2026-04-20T12:34:56Z' (Watcher's own writes) and
    '2026-04-20T12:34:56+00:00' (governance writes via Python isoformat)."""

    def test_z_suffix(self):
        ts = parse_iso_z("2026-04-20T12:34:56Z")
        assert ts == datetime(2026, 4, 20, 12, 34, 56, tzinfo=timezone.utc)

    def test_plus_zero_suffix(self):
        ts = parse_iso_z("2026-04-20T12:34:56+00:00")
        assert ts == datetime(2026, 4, 20, 12, 34, 56, tzinfo=timezone.utc)

    def test_garbage_returns_none(self):
        assert parse_iso_z("not a date") is None
        assert parse_iso_z("") is None
        assert parse_iso_z(None) is None  # type: ignore[arg-type]
