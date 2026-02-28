#!/usr/bin/env python3
"""
Reset calibration state after fixing predicted_correct bug.

This script resets calibration_state.json to clear data that was collected
with the inverted predicted_correct logic (decision-based instead of confidence-based).

Usage:
    python scripts/reset_calibration.py [--backup]
"""

import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.calibration import CalibrationChecker


def reset_calibration(backup: bool = True):
    """
    Reset calibration state after fixing predicted_correct bug.
    
    Args:
        backup: If True, create a backup of existing state before resetting
    """
    calibration_file = project_root / "data" / "calibration_state.json"
    
    # Create backup if requested and file exists
    if backup and calibration_file.exists():
        backup_file = project_root / "data" / f"calibration_state_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        shutil.copy2(calibration_file, backup_file)
        print(f"✅ Created backup: {backup_file}")
    
    # Reset calibration checker
    checker = CalibrationChecker()
    checker.reset()
    checker.save_state()
    
    print(f"✅ Calibration state reset")
    print(f"   File: {calibration_file}")
    print(f"   All bins cleared, ready for fresh data collection")
    print(f"\n   Note: New data will use confidence-based predicted_correct (>=0.5)")
    print(f"   instead of decision-based predicted_correct (proceed/pause)")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Reset calibration state after bug fix")
    parser.add_argument("--no-backup", action="store_true", help="Don't create backup before resetting")
    parser.add_argument("--confirm", action="store_true", help="Skip confirmation prompt")
    
    args = parser.parse_args()
    
    if not args.confirm:
        print("⚠️  This will reset calibration_state.json")
        print("   All calibration data will be cleared.")
        if not args.no_backup:
            print("   A backup will be created first.")
        response = input("\nContinue? [y/N]: ").strip().lower()
        if response != 'y':
            print("Cancelled.")
            sys.exit(0)
    
    reset_calibration(backup=not args.no_backup)

