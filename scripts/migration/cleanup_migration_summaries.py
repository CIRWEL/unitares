#!/usr/bin/env python3
"""
Cleanup script for system_migration discovery summaries.

Problem: Migrated discoveries have summaries that start with metadata
("**Date:**...", "**Discovered:**...") instead of semantic content.

Solution: Extract the H1 title from the details field and use it as the summary.

Usage:
    python scripts/cleanup_migration_summaries.py --dry-run   # Preview changes
    python scripts/cleanup_migration_summaries.py              # Apply changes
"""

import argparse
import json
import re
import subprocess
import sys


def run_psql(query: str, load_age: bool = False, use_json: bool = False) -> str:
    """Run a SQL query via docker exec."""
    if load_age:
        # Prepend AGE loading
        query = f'''LOAD 'age';
SET search_path = ag_catalog, "$user", public;
{query}'''

    cmd = [
        'docker', 'exec', 'postgres-age',
        'psql', '-U', 'postgres', '-d', 'governance',
        '-t', '-A'
    ]
    if use_json:
        cmd.extend(['-F', '\t'])  # Tab separator
    cmd.extend(['-c', query])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"psql error: {result.stderr}")
    return result.stdout.strip()


def extract_title_from_details(details: str) -> str | None:
    """Extract H1 title from markdown details."""
    if not details:
        return None

    # Look for H1 header at start of details
    # Pattern: # Title\n
    match = re.match(r'^#\s+(.+?)(?:\n|$)', details.strip())
    if match:
        title = match.group(1).strip()
        # Remove any trailing markdown markers
        title = re.sub(r'\s*#*\s*$', '', title)
        return title

    return None


def needs_cleanup(summary: str, details: str) -> bool:
    """Check if summary needs cleanup."""
    if not summary or not details:
        return False

    # Summary starts with markdown metadata patterns
    metadata_patterns = [
        r'^\*\*Date:\*\*',
        r'^\*\*Discovered\*\*:',
        r'^\*\*Discovered\*\*\s*:',  # Alternative spacing
        r'^\*\*Created:\*\*',
        r'^\*\*Status:\*\*',
        r'^\*\*Version:\*\*',
        r'^\*\*Issue:\*\*',
        r'^\*\*Agent:\*\*',
        r'^\*\*Purpose:\*\*',
    ]

    for pattern in metadata_patterns:
        if re.match(pattern, summary.strip()):
            return True

    return False


def main():
    parser = argparse.ArgumentParser(description='Cleanup migration summaries')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without applying')
    parser.add_argument('--limit', type=int, default=0, help='Limit number of fixes (0=all)')
    args = parser.parse_args()

    print(f"{'DRY RUN - ' if args.dry_run else ''}Cleanup Migration Summaries")
    print("=" * 60)

    # First, get all system_migration discovery IDs
    ids_query = '''
SELECT * FROM cypher('governance_graph', $$
  MATCH (d:Discovery)
  WHERE d.agent_id = 'system_migration'
  RETURN id(d), d.id
$$) AS (graph_id agtype, doc_id agtype);
'''

    try:
        output = run_psql(ids_query, load_age=True)
    except Exception as e:
        print(f"ERROR: {e}")
        return 1

    if not output:
        print("No system_migration discoveries found")
        return 0

    # Parse discovery IDs (these don't contain pipe characters)
    discovery_ids = []
    for line in output.strip().split('\n'):
        if not line or line in ('LOAD', 'SET'):
            continue
        parts = line.split('|')
        if len(parts) >= 2:
            graph_id = parts[0].strip()
            doc_id = parts[1].strip().strip('"')
            discovery_ids.append((graph_id, doc_id))

    fixes = []
    skipped = []

    # For each discovery, check if it needs cleanup
    for graph_id, doc_id in discovery_ids:
        # Query summary and details for this specific discovery
        detail_query = f'''
SELECT * FROM cypher('governance_graph', $$
  MATCH (d:Discovery)
  WHERE id(d) = {graph_id}
  RETURN d.summary, d.details
$$) AS (summary agtype, details agtype);
'''
        try:
            detail_output = run_psql(detail_query, load_age=True)
        except Exception as e:
            print(f"  Warning: Could not query {doc_id}: {e}")
            continue

        # Parse - split by first | only since details might contain |
        lines = [l for l in detail_output.strip().split('\n') if l not in ('LOAD', 'SET', '')]
        if not lines:
            continue

        # Find the | that separates summary from details
        line = lines[0]
        first_pipe = line.find('|')
        if first_pipe == -1:
            continue

        summary = line[:first_pipe].strip().strip('"')
        details = line[first_pipe+1:].strip().strip('"')

        # Unescape JSON strings
        summary = summary.replace('\\"', '"').replace('\\n', '\n')
        details = details.replace('\\"', '"').replace('\\n', '\n')

        if not needs_cleanup(summary, details):
            skipped.append(doc_id)
            continue

        new_title = extract_title_from_details(details)
        if not new_title:
            skipped.append(doc_id)
            continue

        fixes.append({
            'graph_id': graph_id,
            'doc_id': doc_id,
            'old_summary': summary[:80] + '...' if len(summary) > 80 else summary,
            'new_summary': new_title,
        })

        if args.limit and len(fixes) >= args.limit:
            break

    print(f"Found {len(fixes) + len(skipped)} system_migration discoveries")
    print(f"Discoveries to fix: {len(fixes)}")
    print(f"Skipped (no cleanup needed): {len(skipped)}")
    print()

    if not fixes:
        print("No fixes needed!")
        return 0

    print("Changes to apply:")
    print("-" * 60)
    for i, fix in enumerate(fixes[:10]):  # Show first 10
        print(f"\n[{i+1}] {fix['doc_id']}")
        print(f"  OLD: {fix['old_summary']}")
        print(f"  NEW: {fix['new_summary']}")

    if len(fixes) > 10:
        print(f"\n... and {len(fixes) - 10} more")

    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN complete. No changes applied.")
        print(f"Run without --dry-run to apply {len(fixes)} fixes.")
        return 0

    # Apply fixes
    print("\n" + "=" * 60)
    print("Applying fixes...")

    applied = 0
    failed = 0

    for fix in fixes:
        try:
            # Escape the new summary for Cypher string
            escaped_summary = fix['new_summary'].replace("'", "\\'").replace('"', '\\"')

            # Use Cypher to update the summary
            update_cypher = f'''
SELECT * FROM cypher('governance_graph', $$
  MATCH (d:Discovery)
  WHERE id(d) = {fix['graph_id']}
  SET d.summary = '{escaped_summary}'
  RETURN d.id
$$) AS (doc_id agtype);
'''

            run_psql(update_cypher, load_age=True)
            applied += 1

            if applied % 10 == 0:
                print(f"  Applied {applied}/{len(fixes)} fixes...")

        except Exception as e:
            print(f"  ERROR fixing {fix['doc_id']}: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"COMPLETE: Applied {applied} fixes, {failed} failed")

    # Regenerate embeddings hint
    if applied > 0:
        print()
        print("NOTE: Embeddings may need regeneration for updated summaries.")
        print("Consider running a re-indexing job for semantic search.")

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    exit(main())
