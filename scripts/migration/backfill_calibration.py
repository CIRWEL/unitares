#!/usr/bin/env python3
"""
Backfill calibration using existing collect_ground_truth_automatically with rebuild mode.

This uses the existing auto_ground_truth infrastructure to rebuild calibration
from audit log entries with corrected predicted_correct logic.

Usage:
    python scripts/backfill_calibration.py [--dry-run] [--min-age-hours 0.1]
"""

import sys
import asyncio
import shutil
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.auto_ground_truth import collect_ground_truth_automatically


async def main(dry_run: bool = False, min_age_hours: float = 0.1):
    """Backfill calibration with corrected logic"""
    print("=" * 70)
    print("CALIBRATION BACKFILL - USING EXISTING INFRASTRUCTURE")
    print("=" * 70)
    print()
    
    # Create backup if not dry run
    if not dry_run:
        calibration_file = project_root / "data" / "calibration_state.json"
        if calibration_file.exists():
            backup_file = project_root / "data" / f"calibration_state_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            shutil.copy2(calibration_file, backup_file)
            print(f"✅ Created backup: {backup_file}")
            print()
    
    print(f"🔄 Rebuilding calibration from audit log (min_age_hours={min_age_hours})...")
    print()
    
    # Use existing function with rebuild=True
    result = await collect_ground_truth_automatically(
        min_age_hours=min_age_hours,
        max_decisions=0,  # 0 = no limit (process all)
        dry_run=dry_run,
        rebuild=True  # Reset and rebuild from scratch
    )
    
    print()
    print("=" * 70)
    print("BACKFILL COMPLETE")
    print("=" * 70)
    print(f"   Processed: {result.get('processed', 0)}")
    print(f"   Updated: {result.get('updated', 0)}")
    print(f"   Skipped: {result.get('skipped', 0)}")
    print(f"   Errors: {result.get('errors', 0)}")
    print()
    
    if dry_run:
        print("🔍 DRY RUN - No changes saved")
        print("   Run without --dry-run to apply changes")
    else:
        print("✅ Calibration rebuilt with corrected predicted_correct logic")
        print("   (confidence >= 0.5, not decision-based)")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Backfill calibration using existing infrastructure")
    parser.add_argument("--dry-run", action="store_true", help="Don't save changes")
    parser.add_argument("--min-age-hours", type=float, default=0.1, help="Minimum age of entries (default: 0.1)")
    parser.add_argument("--confirm", action="store_true", help="Skip confirmation")
    
    args = parser.parse_args()
    
    if not args.confirm:
        print("⚠️  This will rebuild calibration_state.json from audit log")
        print("   using corrected predicted_correct logic (confidence-based).")
        if not args.dry_run:
            print("   A backup will be created first.")
        response = input("\nContinue? [y/N]: ").strip().lower()
        if response != 'y':
            print("Cancelled.")
            sys.exit(0)
    
    asyncio.run(main(dry_run=args.dry_run, min_age_hours=args.min_age_hours))

