#!/usr/bin/env python3
"""Export outcome-event rows for offline validation studies.

This script creates a flattened CSV or JSONL dataset from `audit.outcome_events`
so predictive and causal studies can be run outside the live server.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.outcome_correlation import (  # noqa: E402
    OutcomeCorrelation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", help="Optional agent_id filter")
    parser.add_argument(
        "--since-hours",
        type=float,
        default=168.0,
        help="Lookback window in hours (default: 168)",
    )
    parser.add_argument(
        "--format",
        choices=("jsonl", "csv"),
        default="jsonl",
        help="Output format (default: jsonl)",
    )
    parser.add_argument(
        "--output",
        help="Output path. Defaults to data/analysis/outcome_dataset.<ext>",
    )
    return parser.parse_args()


def default_output_path(fmt: str) -> Path:
    suffix = "jsonl" if fmt == "jsonl" else "csv"
    return PROJECT_ROOT / "data" / "analysis" / f"outcome_dataset.{suffix}"


def write_jsonl(rows: list[dict], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, default=str, sort_keys=True) + "\n")


def write_csv(rows: list[dict], output_path: Path) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            normalized = {
                key: json.dumps(value, default=str) if isinstance(value, (dict, list)) else value
                for key, value in row.items()
            }
            writer.writerow(normalized)


async def main_async(args: argparse.Namespace) -> int:
    study = OutcomeCorrelation()
    report = await study.run(agent_id=args.agent, since_hours=args.since_hours)
    rows = await study.export_rows(agent_id=args.agent, since_hours=args.since_hours)
    output_path = Path(args.output) if args.output else default_output_path(args.format)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "jsonl":
        write_jsonl(rows, output_path)
    else:
        write_csv(rows, output_path)

    coverage = report.coverage

    print(f"Wrote {len(rows)} outcome rows to {output_path}")
    print(
        "Coverage: "
        f"exogenous={coverage['with_exogenous_signals']['count']}/{coverage['total_outcomes']}, "
        f"behavioral_primary={coverage['with_behavioral_primary']['count']}/{coverage['total_outcomes']}, "
        f"snapshot={coverage['with_snapshot']['count']}/{coverage['total_outcomes']}"
    )
    return 0


def main() -> int:
    args = parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
