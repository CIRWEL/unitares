#!/usr/bin/env python3
"""
Test calibration persistence (save_state/load_state).

Tests that calibration data persists across restarts.
"""

import sys
import os
import tempfile
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from src.calibration import CalibrationChecker


def test_calibration_save_load():
    """Test that calibration state persists across restarts"""
    print("\n1. Testing calibration save/load...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "calibration_state.json"
        
        # Create checker and record predictions
        checker1 = CalibrationChecker(state_file=state_file)
        checker1.record_prediction(0.85, True, True)  # High confidence, correct
        checker1.record_prediction(0.75, True, False)  # Medium-high, incorrect
        checker1.record_prediction(0.60, False, False)  # Medium-low, correct (predicted wrong)
        checker1.save_state()
        
        # Verify file exists
        assert state_file.exists(), "State file should exist after save"
        print(f"   ✅ State file created: {state_file}")
        
        # Create new checker and load state
        checker2 = CalibrationChecker(state_file=state_file)
        checker2.load_state()
        
        # Verify data matches
        assert checker2.bin_stats['0.8-0.9']['count'] == 1, "High confidence bin should have 1 count"
        assert checker2.bin_stats['0.8-0.9']['actual_correct'] == 1, "High confidence bin should have 1 correct"
        assert checker2.bin_stats['0.7-0.8']['count'] == 1, "Medium-high bin should have 1 count"
        assert checker2.bin_stats['0.5-0.7']['count'] == 1, "Medium-low bin should have 1 count"
        
        print("   ✅ Calibration state loaded correctly")
        print(f"   - High confidence bin: {checker2.bin_stats['0.8-0.9']}")
        print(f"   - Medium-high bin: {checker2.bin_stats['0.7-0.8']}")
        print(f"   - Medium-low bin: {checker2.bin_stats['0.5-0.7']}")
        
        return True


def test_calibration_update_ground_truth():
    """Test that updating ground truth persists"""
    print("\n2. Testing ground truth update persistence...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "calibration_state.json"
        
        # Record prediction without ground truth
        checker1 = CalibrationChecker(state_file=state_file)
        checker1.record_prediction(0.85, True, None)  # No ground truth yet
        checker1.save_state()
        
        # Load and update ground truth
        checker2 = CalibrationChecker(state_file=state_file)
        checker2.load_state()
        checker2.update_ground_truth(0.85, True, True)  # Now provide ground truth
        checker2.save_state()
        
        # Verify update persisted
        checker3 = CalibrationChecker(state_file=state_file)
        checker3.load_state()
        assert checker3.bin_stats['0.8-0.9']['actual_correct'] == 1, "Ground truth should be persisted"
        
        print("   ✅ Ground truth update persisted")
        return True


def test_calibration_empty_state():
    """Test that empty state loads gracefully"""
    print("\n3. Testing empty state handling...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "calibration_state.json"
        
        # Create checker with non-existent file
        checker = CalibrationChecker(state_file=state_file)
        checker.load_state()  # Should not crash
        
        # Should have empty stats
        assert len(checker.bin_stats) == 0 or all(s['count'] == 0 for s in checker.bin_stats.values()), \
            "Empty state should have no counts"
        
        print("   ✅ Empty state handled gracefully")
        return True


def run_all_tests():
    """Run all calibration persistence tests"""
    print("=" * 60)
    print("CALIBRATION PERSISTENCE TEST SUITE")
    print("=" * 60)
    
    tests = [
        test_calibration_save_load,
        test_calibration_update_ground_truth,
        test_calibration_empty_state,
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {sum(results)}/{len(results)} tests passed")
    print("=" * 60)
    
    if all(results):
        print("\n🎉 All calibration persistence tests passed!")
        return 0
    else:
        print("\n⚠️  Some tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())

