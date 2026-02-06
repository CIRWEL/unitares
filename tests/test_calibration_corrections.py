"""
Tests for calibration correction functions in src/calibration.py.

Tests compute_correction_factors, apply_confidence_correction,
check_calibration, and update_ground_truth - the uncovered methods.
"""

import pytest
import sys
from pathlib import Path
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.calibration import CalibrationChecker, CalibrationBin


@pytest.fixture
def checker(tmp_path):
    """Create a CalibrationChecker with tmp state file."""
    state_file = tmp_path / "cal_state.json"
    c = CalibrationChecker(state_file=state_file)
    c.reset()
    return c


# ============================================================================
# compute_correction_factors
# ============================================================================

class TestComputeCorrectionFactors:

    def test_empty_bins(self, checker):
        factors = checker.compute_correction_factors()
        assert factors == {}

    def test_insufficient_samples(self, checker):
        checker.tactical_bin_stats["0.8-0.9"] = {
            "count": 2, "actual_correct": 1, "predicted_correct": 2,
            "confidence_sum": 1.7
        }
        factors = checker.compute_correction_factors(min_samples=5)
        assert factors == {}

    def test_well_calibrated_factor_near_one(self, checker):
        # Expected accuracy ~0.85, actual accuracy ~0.85
        checker.tactical_bin_stats["0.8-0.9"] = {
            "count": 20, "actual_correct": 17, "predicted_correct": 20,
            "confidence_sum": 17.0  # avg confidence = 0.85
        }
        factors = checker.compute_correction_factors(min_samples=5)
        assert "0.8-0.9" in factors
        assert factors["0.8-0.9"] == pytest.approx(1.0, abs=0.05)

    def test_overconfident_factor_below_one(self, checker):
        # Expected accuracy ~0.85 but actual only ~0.50
        checker.tactical_bin_stats["0.8-0.9"] = {
            "count": 20, "actual_correct": 10, "predicted_correct": 20,
            "confidence_sum": 17.0  # avg confidence = 0.85
        }
        factors = checker.compute_correction_factors(min_samples=5)
        assert factors["0.8-0.9"] < 1.0

    def test_underconfident_factor_above_one(self, checker):
        # Expected accuracy ~0.55 but actual ~0.80
        checker.tactical_bin_stats["0.5-0.7"] = {
            "count": 20, "actual_correct": 16, "predicted_correct": 20,
            "confidence_sum": 11.0  # avg confidence = 0.55
        }
        factors = checker.compute_correction_factors(min_samples=5)
        assert factors["0.5-0.7"] > 1.0

    def test_factor_clipped_to_range(self, checker):
        # Extreme case: expected ~0.85 but actual ~0.05
        checker.tactical_bin_stats["0.8-0.9"] = {
            "count": 20, "actual_correct": 1, "predicted_correct": 20,
            "confidence_sum": 17.0
        }
        factors = checker.compute_correction_factors(min_samples=5)
        assert factors["0.8-0.9"] >= 0.5
        assert factors["0.8-0.9"] <= 1.5

    def test_multiple_bins(self, checker):
        checker.tactical_bin_stats["0.5-0.7"] = {
            "count": 10, "actual_correct": 6, "predicted_correct": 10,
            "confidence_sum": 6.0
        }
        checker.tactical_bin_stats["0.8-0.9"] = {
            "count": 10, "actual_correct": 8, "predicted_correct": 10,
            "confidence_sum": 8.5
        }
        factors = checker.compute_correction_factors(min_samples=5)
        assert len(factors) == 2


# ============================================================================
# apply_confidence_correction
# ============================================================================

class TestApplyConfidenceCorrection:

    def test_no_data_returns_unchanged(self, checker):
        corrected, info = checker.apply_confidence_correction(0.85)
        assert corrected == 0.85
        assert info is None

    def test_insufficient_samples_returns_unchanged(self, checker):
        checker.tactical_bin_stats["0.8-0.9"] = {
            "count": 2, "actual_correct": 1, "predicted_correct": 2,
            "confidence_sum": 1.7
        }
        corrected, info = checker.apply_confidence_correction(0.85, min_samples=5)
        assert corrected == 0.85
        assert info is None

    def test_significant_correction_reported(self, checker):
        # Overconfident: expected ~0.85 but actual ~0.50
        checker.tactical_bin_stats["0.8-0.9"] = {
            "count": 20, "actual_correct": 10, "predicted_correct": 20,
            "confidence_sum": 17.0
        }
        corrected, info = checker.apply_confidence_correction(0.85, min_samples=5)
        assert corrected < 0.85
        assert info is not None
        assert "calibration_adjusted" in info

    def test_small_correction_not_reported(self, checker):
        # Well-calibrated: expected ~0.85 actual ~0.83
        checker.tactical_bin_stats["0.8-0.9"] = {
            "count": 20, "actual_correct": 17, "predicted_correct": 20,
            "confidence_sum": 17.0 + 0.3  # avg = 0.865
        }
        corrected, info = checker.apply_confidence_correction(0.85, min_samples=5)
        # Factor close to 1.0, correction < 5%
        assert info is None

    def test_clamps_to_valid_range(self, checker):
        # Even extreme corrections stay in [0, 1]
        checker.tactical_bin_stats["0.8-0.9"] = {
            "count": 20, "actual_correct": 20, "predicted_correct": 20,
            "confidence_sum": 17.0
        }
        corrected, info = checker.apply_confidence_correction(0.85, min_samples=5)
        assert 0.0 <= corrected <= 1.0

    def test_input_clamped(self, checker):
        # Values outside [0,1] should be clamped
        corrected, info = checker.apply_confidence_correction(1.5)
        assert corrected == 1.0

    def test_negative_input_clamped(self, checker):
        corrected, info = checker.apply_confidence_correction(-0.5)
        assert corrected == 0.0

    def test_confidence_1_0_handled(self, checker):
        # Edge case: confidence exactly 1.0 should find the 0.9-1.0 bin
        checker.tactical_bin_stats["0.9-1.0"] = {
            "count": 10, "actual_correct": 7, "predicted_correct": 10,
            "confidence_sum": 9.5
        }
        corrected, info = checker.apply_confidence_correction(1.0, min_samples=5)
        assert 0.0 <= corrected <= 1.0


# ============================================================================
# update_ground_truth
# ============================================================================

class TestUpdateGroundTruth:

    def test_basic_update(self, checker):
        checker.update_ground_truth(
            confidence=0.85,
            predicted_correct=True,
            actual_correct=True
        )
        # Should have 1 entry in bin_stats
        total = sum(s['count'] for s in checker.bin_stats.values())
        assert total == 1

    def test_multiple_updates(self, checker):
        for i in range(10):
            checker.update_ground_truth(
                confidence=0.85,
                predicted_correct=True,
                actual_correct=(i % 3 != 0)
            )
        total = sum(s['count'] for s in checker.bin_stats.values())
        assert total == 10

    def test_correct_bin_assignment(self, checker):
        checker.update_ground_truth(confidence=0.55, predicted_correct=True, actual_correct=True)
        # Should be in 0.5-0.7 bin
        assert checker.bin_stats.get("0.5-0.7", {}).get("count", 0) == 1

    def test_actual_correct_counted(self, checker):
        checker.update_ground_truth(confidence=0.85, predicted_correct=True, actual_correct=True)
        checker.update_ground_truth(confidence=0.85, predicted_correct=True, actual_correct=False)
        stats = checker.bin_stats.get("0.8-0.9", {})
        assert stats["count"] == 2
        assert stats["actual_correct"] == 1

    def test_low_confidence_bin(self, checker):
        checker.update_ground_truth(confidence=0.3, predicted_correct=False, actual_correct=False)
        assert checker.bin_stats.get("0.0-0.5", {}).get("count", 0) == 1


# ============================================================================
# check_calibration
# ============================================================================

class TestCheckCalibration:

    def test_no_data(self, checker):
        is_cal, metrics = checker.check_calibration()
        assert is_cal is False
        assert "error" in metrics

    def test_with_data(self, checker):
        # Add enough data for meaningful calibration
        for i in range(20):
            checker.update_ground_truth(
                confidence=0.85,
                predicted_correct=True,
                actual_correct=True
            )
        is_cal, metrics = checker.check_calibration()
        assert isinstance(is_cal, bool)
        assert "bins" in metrics
        assert "honesty_note" in metrics

    def test_well_calibrated(self, checker):
        # High confidence + high accuracy = calibrated
        for i in range(20):
            checker.update_ground_truth(confidence=0.85, predicted_correct=True, actual_correct=True)
        is_cal, metrics = checker.check_calibration(min_samples_per_bin=5)
        assert is_cal is True

    def test_miscalibrated(self, checker):
        # High confidence but low accuracy = miscalibrated
        for i in range(20):
            actual = i < 5  # Only 25% correct
            checker.update_ground_truth(confidence=0.85, predicted_correct=True, actual_correct=actual)
        is_cal, metrics = checker.check_calibration(min_samples_per_bin=5)
        assert is_cal is False
        assert len(metrics.get("issues", [])) > 0

    def test_strategic_calibration_in_result(self, checker):
        for i in range(10):
            checker.update_ground_truth(confidence=0.85, predicted_correct=True, actual_correct=True)
        _, metrics = checker.check_calibration(min_samples_per_bin=5)
        assert "strategic_calibration" in metrics

    def test_tactical_calibration_in_result(self, checker):
        for i in range(10):
            checker.update_ground_truth(confidence=0.85, predicted_correct=True, actual_correct=True)
        _, metrics = checker.check_calibration(min_samples_per_bin=5)
        assert "tactical_calibration" in metrics

    def test_insufficient_samples_per_bin(self, checker):
        checker.update_ground_truth(confidence=0.85, predicted_correct=True, actual_correct=True)
        is_cal, metrics = checker.check_calibration(min_samples_per_bin=10)
        # With only 1 sample and min=10, should report insufficient
        issues = metrics.get("issues", [])
        assert any("insufficient" in i.lower() for i in issues)
