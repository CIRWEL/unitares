"""
Tests for pure functions in src/calibration.py - Calibration weight + metrics.

Tests get_complexity_calibration_weight (pure piecewise function)
and compute_*_metrics (pure aggregation from stats dicts).
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.calibration import CalibrationChecker


@pytest.fixture
def checker():
    """Fresh CalibrationChecker with no state."""
    c = CalibrationChecker()
    c.reset()
    return c


# ============================================================================
# get_complexity_calibration_weight
# ============================================================================

class TestGetComplexityCalibrationWeight:

    def test_none_returns_1(self, checker):
        assert checker.get_complexity_calibration_weight(None) == 1.0

    def test_zero_discrepancy(self, checker):
        assert checker.get_complexity_calibration_weight(0.0) == 1.0

    def test_low_discrepancy(self, checker):
        """< 0.1 → weight = 1.0"""
        assert checker.get_complexity_calibration_weight(0.05) == 1.0
        assert checker.get_complexity_calibration_weight(0.09) == 1.0

    def test_at_boundary_0_1(self, checker):
        """At 0.1 → weight = 1.0 (< 0.1 condition)"""
        # 0.1 is NOT < 0.1, so it falls into medium range
        w = checker.get_complexity_calibration_weight(0.1)
        assert w == pytest.approx(1.0)

    def test_medium_discrepancy(self, checker):
        """0.1-0.3 → linear interpolation 1.0 to 0.7"""
        w_mid = checker.get_complexity_calibration_weight(0.2)
        assert 0.7 < w_mid < 1.0

    def test_at_boundary_0_3(self, checker):
        """At 0.3 → enters high discrepancy branch, weight ≈ 0.4"""
        w = checker.get_complexity_calibration_weight(0.3)
        assert w == pytest.approx(0.4, abs=0.05)

    def test_high_discrepancy(self, checker):
        """> 0.3 → weight decreases toward 0"""
        w = checker.get_complexity_calibration_weight(0.5)
        assert w < 0.4

    def test_at_1_0(self, checker):
        """Discrepancy of 1.0 → weight = 0"""
        w = checker.get_complexity_calibration_weight(1.0)
        assert w == 0.0

    def test_above_1_0(self, checker):
        """Discrepancy > 1.0 → weight = 0"""
        w = checker.get_complexity_calibration_weight(1.5)
        assert w == 0.0

    def test_negative_discrepancy(self, checker):
        """Negative uses abs() → same as positive"""
        w_pos = checker.get_complexity_calibration_weight(0.2)
        w_neg = checker.get_complexity_calibration_weight(-0.2)
        assert w_pos == w_neg

    def test_monotonically_decreasing(self, checker):
        """Weight should decrease as discrepancy increases"""
        vals = [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
        weights = [checker.get_complexity_calibration_weight(v) for v in vals]
        for i in range(1, len(weights)):
            assert weights[i] <= weights[i-1], f"Not monotonic at {vals[i]}: {weights[i]} > {weights[i-1]}"


# ============================================================================
# compute_complexity_calibration_metrics
# ============================================================================

class TestComputeComplexityCalibrationMetrics:

    def test_empty_stats(self, checker):
        """No data → empty results"""
        result = checker.compute_complexity_calibration_metrics()
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_with_data(self, checker):
        """Record some discrepancies and compute metrics"""
        checker.record_complexity_discrepancy(0.2, 0.3, 0.1)
        checker.record_complexity_discrepancy(0.25, 0.35, 0.1)
        result = checker.compute_complexity_calibration_metrics()
        assert len(result) >= 1
        # Should have at least one bin with count=2
        bins = list(result.values())
        assert any(b.count >= 1 for b in bins)


# ============================================================================
# compute_calibration_metrics
# ============================================================================

class TestComputeCalibrationMetrics:

    def test_empty_stats(self, checker):
        result = checker.compute_calibration_metrics()
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_with_predictions(self, checker):
        """Record predictions and compute metrics"""
        checker.record_prediction(0.8, True, 1.0)
        checker.record_prediction(0.8, True, 1.0)
        checker.record_prediction(0.8, False, 0.0)
        result = checker.compute_calibration_metrics()
        assert len(result) >= 1
        for bin_data in result.values():
            assert bin_data.count >= 1
            assert 0.0 <= bin_data.accuracy <= 1.0
            assert bin_data.calibration_error >= 0.0


# ============================================================================
# compute_tactical_metrics
# ============================================================================

class TestComputeTacticalMetrics:

    def test_empty_stats(self, checker):
        result = checker.compute_tactical_metrics()
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_with_decisions(self, checker):
        checker.record_tactical_decision(0.7, "proceed", True)
        checker.record_tactical_decision(0.3, "pause", False)
        result = checker.compute_tactical_metrics()
        assert len(result) >= 1


# ============================================================================
# CalibrationChecker reset
# ============================================================================

class TestCalibrationReset:

    def test_reset_clears_stats(self, checker):
        checker.record_prediction(0.5, True, 1.0)
        checker.reset()
        result = checker.compute_calibration_metrics()
        assert len(result) == 0

    def test_reset_returns_nothing(self, checker):
        result = checker.reset()
        assert result is None
