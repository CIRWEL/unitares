#!/usr/bin/env python3
"""
Report both strategic and tactical calibration bins from current state.

Shows comprehensive calibration metrics including both dimensions.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.calibration import CalibrationChecker


def report_calibration():
    """Report both strategic and tactical calibration"""
    checker = CalibrationChecker()
    
    print("=" * 70)
    print("CALIBRATION REPORT - STRATEGIC & TACTICAL")
    print("=" * 70)
    print()
    
    # Strategic calibration (trajectory health)
    print("📊 STRATEGIC CALIBRATION (Trajectory Health)")
    print("   Measures: Do agents with high confidence end up in healthy states?")
    print("   Retroactive marking: YES")
    print()
    
    strategic_bins = checker.bin_stats
    if strategic_bins:
        for bin_key in sorted(strategic_bins.keys()):
            stats = strategic_bins[bin_key]
            if stats['count'] == 0:
                continue
            
            count = stats['count']
            predicted_correct = stats['predicted_correct']
            actual_correct = stats['actual_correct']
            accuracy = actual_correct / count if count > 0 else 0.0
            expected_conf = stats['confidence_sum'] / count if count > 0 else 0.0
            
            calibration_error = abs(accuracy - expected_conf)
            # Use same threshold as check_calibration (0.2) for consistency
            error_indicator = '⚠️' if calibration_error > 0.2 else '✅'
            
            print(f"   {bin_key}:")
            print(f"      Count: {count}")
            print(f"      Predicted correct: {predicted_correct}")
            print(f"      Actual correct: {actual_correct}")
            print(f"      Accuracy: {accuracy:.2%}")
            print(f"      Expected confidence: {expected_conf:.3f}")
            print(f"      Calibration error: {calibration_error:.3f} {error_indicator}")
            print()
    else:
        print("   No strategic calibration data yet")
        print()
    
    # Tactical calibration (per-decision)
    print("🎯 TACTICAL CALIBRATION (Per-Decision)")
    print("   Measures: Are individual decisions correct at the time they were made?")
    print("   Retroactive marking: NO (fixed at decision time)")
    print()
    
    if hasattr(checker, 'tactical_bin_stats') and checker.tactical_bin_stats:
        tactical_bins = checker.tactical_bin_stats
        for bin_key in sorted(tactical_bins.keys()):
            stats = tactical_bins[bin_key]
            if stats['count'] == 0:
                continue
            
            count = stats['count']
            predicted_correct = stats['predicted_correct']
            actual_correct = stats['actual_correct']
            accuracy = actual_correct / count if count > 0 else 0.0
            expected_conf = stats['confidence_sum'] / count if count > 0 else 0.0
            
            calibration_error = abs(accuracy - expected_conf)
            # Use same threshold as check_calibration (0.2) for consistency
            error_indicator = '⚠️' if calibration_error > 0.2 else '✅'
            
            print(f"   {bin_key}:")
            print(f"      Count: {count}")
            print(f"      Predicted correct: {predicted_correct}")
            print(f"      Actual correct: {actual_correct}")
            print(f"      Decision accuracy: {accuracy:.2%}")
            print(f"      Expected confidence: {expected_conf:.3f}")
            print(f"      Calibration error: {calibration_error:.3f} {error_indicator}")
            print()
    else:
        print("   No tactical calibration data yet")
        print("   (Tactical recording is wired in - will populate as decisions are made)")
        print()
    
    # Check calibration status
    is_calibrated, result = checker.check_calibration(min_samples_per_bin=5)

    print("=" * 70)
    print(f"Overall Status: {'CALIBRATED' if is_calibrated else 'NOT CALIBRATED'}")
    print("=" * 70)

    # Failure characterization
    print()
    print("=" * 70)
    print("FAILURE CHARACTERIZATION")
    print("=" * 70)
    print()

    characterization = checker.characterize_failure_modes(min_samples=3)

    for dimension in ("strategic", "tactical"):
        dim_data = characterization.get(dimension, {})
        dim_status = dim_data.get("status", "no_data")
        label = "STRATEGIC (Trajectory Health)" if dimension == "strategic" else "TACTICAL (Per-Decision)"
        print(f"   {label}:")
        if dim_status in ("no_data", "insufficient_samples"):
            print(f"      {dim_status}")
        else:
            print(f"      ECE (Expected Calibration Error): {dim_data['ece']:.4f}")
            print(f"      Curve inverted: {'YES' if dim_data['curve_inverted'] else 'no'}")
            wb = dim_data["worst_bin"]
            print(f"      Worst bin: {wb['bin']} "
                  f"(error={wb['calibration_error']:.3f}, "
                  f"expected={wb['expected']:.3f}, actual={wb['actual']:.3f})")
            print()
            for bin_key, bin_info in dim_data.get("bins", {}).items():
                diag = bin_info["diagnosis"]
                indicator = {"overconfident": "!", "underconfident": "?", "well_calibrated": "+"}[diag]
                print(f"      [{indicator}] {bin_key}: {diag} "
                      f"(expected={bin_info['expected']:.3f}, actual={bin_info['actual']:.3f}, "
                      f"n={bin_info['count']})")
        print()

    warning = characterization.get("verdict_quality_warning")
    if warning:
        print(f"   VERDICT QUALITY: {warning}")
    else:
        print("   VERDICT QUALITY: No systemic issues detected")
    print()


if __name__ == "__main__":
    report_calibration()

