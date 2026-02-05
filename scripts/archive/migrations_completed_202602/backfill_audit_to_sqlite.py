#!/usr/bin/env python3
"""
Backfill audit_log.jsonl -> audit.db (SQLite index)

This is intentionally a SCRIPT (not an MCP tool) to avoid tool surface bloat.
Agents can run it once to populate the SQLite query/index from historical JSONL.

Usage:
  python3 scripts/backfill_audit_to_sqlite.py --max-lines 200000

Environment overrides:
  UNITARES_AUDIT_DB_PATH: path to audit.db (default: data/audit.db)
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.audit_db import AuditDB


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", default=None, help="Path to audit_log.jsonl (default: data/audit_log.jsonl)")
    parser.add_argument("--db", default=None, help="Path to audit.db (default: data/audit.db or UNITARES_AUDIT_DB_PATH)")
    parser.add_argument("--max-lines", type=int, default=50000, help="Max lines to backfill (bounded)")
    parser.add_argument("--batch-size", type=int, default=2000, help="Commit every N processed lines")
    parser.add_argument("--fts", action="store_true", help="Also backfill FTS index (bounded by --fts-limit)")
    parser.add_argument("--fts-limit", type=int, default=50000, help="Max rows to FTS-index (bounded)")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    jsonl_path = Path(args.jsonl) if args.jsonl else (project_root / "data" / "audit_log.jsonl")

    db_path = args.db or os.getenv("UNITARES_AUDIT_DB_PATH")
    db_path = Path(db_path) if db_path else (project_root / "data" / "audit.db")

    db = AuditDB(db_path)
    res = db.backfill_from_jsonl(jsonl_path, max_lines=args.max_lines, batch_size=args.batch_size)
    if args.fts:
        res["fts_backfill"] = db.backfill_fts(limit=args.fts_limit)
    print(res)
    return 0 if res.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())


