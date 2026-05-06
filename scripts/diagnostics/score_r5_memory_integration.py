#!/usr/bin/env python3
"""Run the R5 KG cite-and-extend scorer for one parent/successor pair.

This is a read-only shadow diagnostic. It queries existing KG discoveries and
prints the advisory score as JSON. It does not write audit rows, KG rows, or
R2 lineage state.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

from src.identity.memory_integration import score_memory_integration


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-id", required=True, help="Immediate declared parent agent id.")
    parser.add_argument("--successor-id", required=True, help="Successor agent id to score.")
    parser.add_argument("--window-days", type=int, default=30, help="KG scoring window.")
    parser.add_argument(
        "--min-parent-discoveries",
        type=int,
        default=3,
        help="Minimum parent KG corpus size before absence can count.",
    )
    parser.add_argument(
        "--min-strong-extensions",
        type=int,
        default=2,
        help="Strong constructive response count needed for integrated_candidate.",
    )
    parser.add_argument(
        "--min-distinct-parent-targets",
        type=int,
        default=2,
        help="Distinct parent discoveries that must be cited for integrated_candidate.",
    )
    parser.add_argument(
        "--max-discoveries",
        type=int,
        default=500,
        help="Maximum KG discoveries to load per agent.",
    )
    args = parser.parse_args()

    score = await score_memory_integration(
        args.parent_id,
        args.successor_id,
        window_days=args.window_days,
        min_parent_discoveries=args.min_parent_discoveries,
        min_strong_extensions=args.min_strong_extensions,
        min_distinct_parent_targets=args.min_distinct_parent_targets,
        max_discoveries=args.max_discoveries,
    )
    print(json.dumps(score.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
