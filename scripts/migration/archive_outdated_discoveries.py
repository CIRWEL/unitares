#!/usr/bin/env python3
"""
Archive outdated discoveries that reference deprecated features.

Targets:
- SQLite fallback/backend references (deprecated - PostgreSQL only now)
- hello() tool references (replaced by identity() and onboard())
- recall_identity tool references (deprecated)
- Old session binding mechanisms

Usage:
    python scripts/archive_outdated_discoveries.py --dry-run   # Preview
    python scripts/archive_outdated_discoveries.py              # Archive
"""

import argparse
import subprocess
import sys
from datetime import datetime


def run_psql(query: str, load_age: bool = False) -> str:
    """Run a SQL query via docker exec."""
    if load_age:
        query = f'''LOAD 'age';
SET search_path = ag_catalog, "$user", public;
{query}'''

    cmd = [
        'docker', 'exec', 'postgres-age',
        'psql', '-U', 'postgres', '-d', 'governance',
        '-t', '-A', '-c', query
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"psql error: {result.stderr}")
    return result.stdout.strip()


def find_outdated_discoveries() -> list:
    """Find discoveries that reference deprecated features.

    Focus on outdated GUIDANCE, not historical documentation.
    Preserve: Migration histories, audit reports, architecture decisions
    Archive: How-to guides using deprecated tools, stale status updates
    """
    query = '''
SELECT * FROM cypher('governance_graph', $$
  MATCH (d:Discovery)
  WHERE d.status <> 'archived'
    AND (
      d.summary CONTAINS 'recall_identity' OR d.details CONTAINS 'use recall_identity'
      OR d.summary CONTAINS 'hello(' OR d.summary CONTAINS 'hello tool'
      OR d.summary CONTAINS 'SQLite fallback now covers'
      OR d.summary CONTAINS 'now works via SQLite'
      OR d.summary CONTAINS 'persistence now works via SQLite'
      OR (d.summary CONTAINS 'SQLite' AND d.summary CONTAINS 'persistence')
    )
    AND NOT (d.summary CONTAINS 'Migration' OR d.summary CONTAINS 'migrated' OR d.summary CONTAINS 'Completed PostgreSQL')
    AND NOT (d.summary CONTAINS 'Audit' OR d.summary CONTAINS 'Assessment')
    AND NOT d.summary CONTAINS 'Architecture'
  RETURN id(d), d.id, d.summary, d.status
$$) AS (graph_id agtype, doc_id agtype, summary agtype, status agtype);
'''
    output = run_psql(query, load_age=True)

    discoveries = []
    for line in output.strip().split('\n'):
        if not line or line in ('LOAD', 'SET'):
            continue
        parts = line.split('|')
        if len(parts) >= 4:
            discoveries.append({
                'graph_id': parts[0].strip(),
                'doc_id': parts[1].strip().strip('"'),
                'summary': parts[2].strip().strip('"')[:80],
                'status': parts[3].strip().strip('"'),
            })
    return discoveries


def archive_discovery(graph_id: str, deprecation_note: str) -> bool:
    """Archive a discovery and add deprecation note."""
    escaped_note = deprecation_note.replace("'", "\\'").replace('"', '\\"')

    query = f'''
SELECT * FROM cypher('governance_graph', $$
  MATCH (d:Discovery)
  WHERE id(d) = {graph_id}
  SET d.status = 'archived',
      d.archived_at = '{datetime.now().isoformat()}',
      d.deprecation_note = '{escaped_note}'
  RETURN d.id
$$) AS (doc_id agtype);
'''
    try:
        run_psql(query, load_age=True)
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Archive outdated discoveries')
    parser.add_argument('--dry-run', action='store_true', help='Preview without archiving')
    args = parser.parse_args()

    print(f"{'DRY RUN - ' if args.dry_run else ''}Archive Outdated Discoveries")
    print("=" * 60)
    print("Targets: SQLite references, hello() tool, recall_identity, JSON backend")
    print()

    discoveries = find_outdated_discoveries()
    print(f"Found {len(discoveries)} outdated discoveries:")
    print()

    for i, d in enumerate(discoveries[:20]):  # Show first 20
        print(f"[{i+1}] {d['doc_id'][:25]}...")
        print(f"    Summary: {d['summary']}...")
        print(f"    Status: {d['status']}")
        print()

    if len(discoveries) > 20:
        print(f"... and {len(discoveries) - 20} more")
        print()

    if not discoveries:
        print("No outdated discoveries found!")
        return 0

    if args.dry_run:
        print("=" * 60)
        print(f"DRY RUN complete. Would archive {len(discoveries)} discoveries.")
        print("Run without --dry-run to archive them.")
        return 0

    # Archive discoveries
    print("=" * 60)
    print("Archiving discoveries...")

    deprecation_note = (
        "HISTORICAL: This discovery references deprecated features. "
        "As of Dec 2025: PostgreSQL is the only backend (no SQLite/JSON fallback), "
        "identity() and onboard() replaced hello(), recall_identity is deprecated."
    )

    archived = 0
    failed = 0

    for d in discoveries:
        success = archive_discovery(d['graph_id'], deprecation_note)
        if success:
            archived += 1
            if archived % 5 == 0:
                print(f"  Archived {archived}/{len(discoveries)}...")
        else:
            failed += 1

    print()
    print("=" * 60)
    print(f"COMPLETE: Archived {archived}, failed {failed}")

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
