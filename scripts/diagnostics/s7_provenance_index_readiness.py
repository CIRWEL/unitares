#!/usr/bin/env python3
"""Assess whether S7/S22 provenance JSONB fields need indexes.

This is a read-only diagnostic. It counts provenance rows, checks existing
``knowledge.discoveries`` indexes, optionally reads ``pg_stat_statements``,
and prints the ontology indexing decision as JSON or text. It does not create
indexes or write database rows.
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

from src.db import close_db
from src.identity.provenance_index_readiness import (
    DEFAULT_MIN_JSONB_QUERY_COUNT,
    DEFAULT_MIN_JSONB_ROWS,
    assess_s7_provenance_index_readiness,
    collect_s7_provenance_index_snapshot,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--observed-jsonb-query-count",
        type=int,
        default=None,
        help=(
            "Observed S7/S22 JSONB predicate count from external telemetry. "
            "When omitted, the script tries pg_stat_statements and falls back "
            "to zero if it is unavailable."
        ),
    )
    parser.add_argument(
        "--min-jsonb-rows",
        type=int,
        default=DEFAULT_MIN_JSONB_ROWS,
        help="Minimum provenance row count before an index can be recommended.",
    )
    parser.add_argument(
        "--min-jsonb-query-count",
        type=int,
        default=DEFAULT_MIN_JSONB_QUERY_COUNT,
        help="Minimum observed JSONB predicate count before recommending DDL.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full assessment payload as JSON.",
    )
    args = parser.parse_args()

    try:
        snapshot = await collect_s7_provenance_index_snapshot(
            observed_jsonb_query_count=args.observed_jsonb_query_count,
        )
        assessment = assess_s7_provenance_index_readiness(
            snapshot,
            min_jsonb_rows=args.min_jsonb_rows,
            min_jsonb_query_count=args.min_jsonb_query_count,
        )
    finally:
        await close_db()

    if args.json:
        print(json.dumps(assessment, indent=2, sort_keys=True))
        return 0

    _print_text_report(assessment)
    return 0


def _print_text_report(assessment: dict) -> None:
    snapshot = assessment["snapshot"]
    thresholds = assessment["thresholds"]
    print(f"decision: {assessment['decision']}")
    print(f"reason: {assessment['reason']}")
    print(
        "rows: "
        f"total={snapshot['total_discoveries']} "
        f"provenance_chain={snapshot['provenance_chain_rows']} "
        f"s7_links={snapshot['s7_lineage_link_rows']} "
        f"s22_context={snapshot['s22_context_rows']}"
    )
    print(
        "query pressure: "
        f"{snapshot['observed_jsonb_query_count']} "
        f"source={snapshot['query_observation_source']} "
        f"threshold={thresholds['min_jsonb_query_count']}"
    )
    print(f"row threshold: {thresholds['min_jsonb_rows']}")

    indexed = assessment.get("indexed_surfaces") or []
    missing = assessment.get("missing_surfaces") or []
    print(f"indexed surfaces: {', '.join(indexed) if indexed else 'none'}")
    print(f"missing surfaces: {', '.join(missing) if missing else 'none'}")

    for recommendation in assessment.get("recommendations", []):
        print(f"recommendation: {recommendation}")

    candidates = assessment.get("candidate_indexes") or []
    for candidate in candidates:
        print(f"candidate index ({candidate['surface']}): {candidate['sql']}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
