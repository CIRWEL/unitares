#!/usr/bin/env python3
"""Backfill explicit primary/behavioral/ODE EISV semantics into agent-state JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import Json, execute_batch

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.eisv_state_json import normalize_agent_state_json


DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/governance"
REQUIRED_KEYS = ("primary_eisv", "primary_eisv_source", "ode_eisv", "ode_diagnostics")


def fetch_candidates(
    conn,
    *,
    epoch: int | None,
    limit: int | None,
    rewrite_legacy_source: bool,
) -> list[dict]:
    missing_any_semantic_key = """
        NOT (s.state_json ? 'primary_eisv')
        OR NOT (s.state_json ? 'primary_eisv_source')
        OR NOT (s.state_json ? 'ode_eisv')
        OR NOT (s.state_json ? 'ode_diagnostics')
    """
    candidate_parts = [f"({missing_any_semantic_key})"]
    if rewrite_legacy_source:
        candidate_parts.append("(s.state_json->>'primary_eisv_source' = 'legacy_flat')")
    where_parts = [f"({' OR '.join(candidate_parts)})"]
    params: list[object] = []

    if epoch is not None:
        where_parts.append("s.epoch = %s")
        params.append(epoch)

    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT %s"
        params.append(limit)

    query = f"""
        WITH ranked AS (
            SELECT
                s.state_id,
                s.identity_id,
                s.epoch,
                s.recorded_at,
                s.state_json,
                s.integrity,
                s.entropy,
                s.volatility,
                s.coherence,
                s.regime,
                ROW_NUMBER() OVER (
                    PARTITION BY s.identity_id, s.epoch
                    ORDER BY s.recorded_at, s.state_id
                ) AS row_index_within_epoch
            FROM core.agent_state s
            WHERE {' AND '.join(where_parts)}
        )
        SELECT
            state_id,
            identity_id,
            epoch,
            recorded_at,
            state_json::text AS state_json,
            integrity,
            entropy,
            volatility,
            coherence,
            regime,
            row_index_within_epoch
        FROM ranked
        ORDER BY state_id
        {limit_sql}
    """
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in rows]


def normalize_rows(
    rows: list[dict],
    *,
    source_strategy: str,
    rewrite_legacy_source: bool,
) -> tuple[list[tuple[int, Json]], dict]:
    updates: list[tuple[int, Json]] = []
    source_counts: dict[str, int] = {}
    inferred_count = 0

    for row in rows:
        state_json = json.loads(row["state_json"]) if isinstance(row["state_json"], str) else (row["state_json"] or {})
        effective_strategy = source_strategy
        row_index = row["row_index_within_epoch"]

        if rewrite_legacy_source and state_json.get("primary_eisv_source") == "legacy_flat":
            state_json = dict(state_json)
            state_json.pop("primary_eisv_source", None)

        if source_strategy == "epoch2_inference" and int(row.get("epoch") or 0) < 2:
            effective_strategy = "safe"
            row_index = None

        normalized, changed = normalize_agent_state_json(
            state_json,
            energy=state_json.get("E", 0.5),
            integrity=row["integrity"],
            entropy=row["entropy"],
            void=row["volatility"],
            coherence=row["coherence"],
            regime=row["regime"],
            source_strategy=effective_strategy,
            row_index_within_identity=row_index,
        )
        if not changed:
            continue

        source = normalized.get("primary_eisv_source", "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        if (normalized.get("state_semantics_meta") or {}).get("source_inferred"):
            inferred_count += 1
        updates.append((row["state_id"], Json(normalized)))

    summary = {
        "scanned_rows": len(rows),
        "rows_to_update": len(updates),
        "source_counts": source_counts,
        "inferred_source_rows": inferred_count,
    }
    return updates, summary


def apply_updates(conn, updates: list[tuple[int, Json]], *, batch_size: int) -> None:
    if not updates:
        return

    with conn.cursor() as cur:
        execute_batch(
            cur,
            """
            UPDATE core.agent_state
            SET state_json = %s::jsonb
            WHERE state_id = %s
            """,
            [(payload, state_id) for state_id, payload in updates],
            page_size=batch_size,
        )
    conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill explicit EISV semantics into state_json")
    parser.add_argument("--db-url", default=DEFAULT_DB_URL, help="PostgreSQL URL")
    parser.add_argument(
        "--source-strategy",
        choices=("safe", "epoch2_inference"),
        default="safe",
        help="How to fill missing primary_eisv_source for legacy rows",
    )
    parser.add_argument("--epoch", type=int, default=None, help="Restrict to one epoch")
    parser.add_argument("--limit", type=int, default=None, help="Limit candidate rows")
    parser.add_argument("--batch-size", type=int, default=1000, help="Update batch size")
    parser.add_argument("--apply", action="store_true", help="Persist updates instead of dry-run")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--rewrite-legacy-source",
        action="store_true",
        help="Allow a later inference pass over rows already labeled legacy_flat",
    )
    args = parser.parse_args()

    conn = psycopg2.connect(args.db_url)
    try:
        rows = fetch_candidates(
            conn,
            epoch=args.epoch,
            limit=args.limit,
            rewrite_legacy_source=args.rewrite_legacy_source,
        )
        updates, summary = normalize_rows(
            rows,
            source_strategy=args.source_strategy,
            rewrite_legacy_source=args.rewrite_legacy_source,
        )
        summary.update(
            {
                "db_url": args.db_url,
                "epoch": args.epoch,
                "batch_size": args.batch_size,
                "source_strategy": args.source_strategy,
                "rewrite_legacy_source": args.rewrite_legacy_source,
                "apply": args.apply,
                "required_keys": list(REQUIRED_KEYS),
            }
        )

        if args.apply:
            apply_updates(conn, updates, batch_size=args.batch_size)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print("EISV Semantics Backfill")
        print("=" * 24)
        print(f"Scanned rows: {summary['scanned_rows']}")
        print(f"Rows needing updates: {summary['rows_to_update']}")
        print(f"Source strategy: {summary['source_strategy']}")
        print(f"Inferred source rows: {summary['inferred_source_rows']}")
        print(f"Apply changes: {summary['apply']}")
        if summary["source_counts"]:
            print("Resulting source counts:")
            for source, count in sorted(summary["source_counts"].items()):
                print(f"  {source}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
