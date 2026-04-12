#!/usr/bin/env python3
"""
Backfill calibration from historical outcome_events.

Replays test_passed/test_failed outcomes that were recorded without confidence
(eprocess_eligible=false) by pairing each with the nearest prior audit trail
confidence. Feeds the results into the sequential calibration tracker.

Usage:
    python3 scripts/ops/backfill_calibration.py              # dry run
    python3 scripts/ops/backfill_calibration.py --apply       # apply
    python3 scripts/ops/backfill_calibration.py --apply -v    # verbose
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


async def backfill(apply: bool = False, verbose: bool = False) -> dict:
    from src.db import get_db
    from src.sequential_calibration import SequentialCalibrationTracker

    db = get_db()
    await db.init()

    tracker = SequentialCalibrationTracker()

    # Fetch all test outcomes that weren't e-process eligible
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT agent_id, outcome_type,
                   detail->>'reported_confidence' as reported_conf,
                   detail->>'eprocess_eligible' as eligible,
                   ts
            FROM audit.outcome_events
            WHERE outcome_type IN ('test_passed', 'test_failed')
            ORDER BY ts ASC
            """
        )

    total = len(rows)
    paired = 0
    skipped_has_conf = 0
    skipped_no_match = 0

    for row in rows:
        outcome_ts = row["ts"]
        outcome_type = row["outcome_type"]
        reported_conf = row["reported_conf"]

        # Skip if already had confidence (was already e-process eligible)
        if reported_conf and reported_conf != "null":
            skipped_has_conf += 1
            continue

        # Find nearest prior confidence from audit events
        confidence = await db.get_latest_confidence_before(
            before_ts=outcome_ts,
            agent_id=row["agent_id"],
        )

        if confidence is None:
            skipped_no_match += 1
            if verbose:
                print(f"  SKIP {outcome_type} at {outcome_ts} — no prior confidence found")
            continue

        outcome_correct = outcome_type == "test_passed"
        paired += 1

        if verbose:
            print(
                f"  PAIR {outcome_type} at {outcome_ts} "
                f"← confidence={confidence:.3f} → correct={outcome_correct}"
            )

        if apply:
            tracker.record_exogenous_tactical_outcome(
                confidence=confidence,
                outcome_correct=outcome_correct,
                agent_id=row["agent_id"],
                signal_source="tests",
                outcome_type=outcome_type,
            )

    if apply and paired > 0:
        tracker.save_state()

    result = {
        "total_outcomes": total,
        "paired": paired,
        "skipped_has_confidence": skipped_has_conf,
        "skipped_no_match": skipped_no_match,
        "applied": apply,
    }

    if apply:
        metrics = tracker.compute_metrics()
        result["tracker_state"] = {
            "eligible_samples": metrics.get("eligible_samples", 0),
            "log_evidence": metrics.get("log_evidence", 0),
            "capped_alarm": metrics.get("capped_alarm", 0),
        }

    return result


def main():
    parser = argparse.ArgumentParser(description="Backfill calibration from outcome_events")
    parser.add_argument("--apply", action="store_true", help="Actually record to tracker (default: dry run)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each pairing")
    args = parser.parse_args()

    if not args.apply:
        print("DRY RUN — pass --apply to record to sequential calibration tracker\n")

    result = asyncio.run(backfill(apply=args.apply, verbose=args.verbose))

    print(f"\nResults:")
    print(f"  Total test outcomes:       {result['total_outcomes']}")
    print(f"  Paired with confidence:    {result['paired']}")
    print(f"  Skipped (already had):     {result['skipped_has_confidence']}")
    print(f"  Skipped (no match):        {result['skipped_no_match']}")
    print(f"  Applied:                   {result['applied']}")

    if "tracker_state" in result:
        ts = result["tracker_state"]
        print(f"\n  Tracker state after backfill:")
        print(f"    eligible_samples: {ts['eligible_samples']}")
        print(f"    log_evidence:     {ts['log_evidence']:.4f}")
        print(f"    capped_alarm:     {ts['capped_alarm']:.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
