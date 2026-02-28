#!/usr/bin/env python3
"""
Backfill missing AGE graph edges.

Problem: Migration created Discovery and Agent nodes but skipped edge creation.
Missing:
- AUTHORED edges (Agent -> Discovery) - 0 exist, ~773 expected
- RESPONDS_TO edges (Discovery -> Discovery) - 0 exist

This script creates the missing edges by reading existing node data.

Usage:
    python scripts/backfill_age_edges.py --dry-run   # Preview
    python scripts/backfill_age_edges.py              # Apply
"""

import argparse
import subprocess
import sys


def run_psql(query: str, load_age: bool = True) -> str:
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


def get_discovery_agent_pairs() -> list:
    """Get all (discovery_id, agent_id) pairs for AUTHORED edges."""
    query = '''
SELECT * FROM cypher('governance_graph', $$
  MATCH (d:Discovery)
  RETURN d.id, d.agent_id
$$) AS (discovery_id agtype, agent_id agtype);
'''
    output = run_psql(query)

    pairs = []
    for line in output.strip().split('\n'):
        if not line or line in ('LOAD', 'SET'):
            continue
        parts = line.split('|')
        if len(parts) >= 2:
            discovery_id = parts[0].strip().strip('"')
            agent_id = parts[1].strip().strip('"')
            if discovery_id and agent_id:
                pairs.append((discovery_id, agent_id))
    return pairs


def get_response_to_pairs() -> list:
    """Get all (from_id, to_id) pairs for RESPONDS_TO edges."""
    # Check for response_to_id property on Discovery nodes
    query = '''
SELECT * FROM cypher('governance_graph', $$
  MATCH (d:Discovery)
  WHERE d.response_to_id IS NOT NULL
  RETURN d.id, d.response_to_id
$$) AS (from_id agtype, to_id agtype);
'''
    output = run_psql(query)

    pairs = []
    for line in output.strip().split('\n'):
        if not line or line in ('LOAD', 'SET'):
            continue
        parts = line.split('|')
        if len(parts) >= 2:
            from_id = parts[0].strip().strip('"')
            to_id = parts[1].strip().strip('"')
            if from_id and to_id:
                pairs.append((from_id, to_id))
    return pairs


def count_existing_edges(edge_type: str) -> int:
    """Count existing edges of a type."""
    query = f'''
SELECT * FROM cypher('governance_graph', $$
  MATCH ()-[r:{edge_type}]->()
  RETURN count(r)
$$) AS (count agtype);
'''
    output = run_psql(query)
    for line in output.strip().split('\n'):
        if line and line not in ('LOAD', 'SET'):
            try:
                return int(line.strip())
            except ValueError:
                pass
    return 0


def create_authored_edge(discovery_id: str, agent_id: str) -> bool:
    """Create AUTHORED edge between Agent and Discovery."""
    # Escape single quotes
    d_id = discovery_id.replace("'", "\\'")
    a_id = agent_id.replace("'", "\\'")

    query = f'''
SELECT * FROM cypher('governance_graph', $$
  MATCH (a:Agent {{id: '{a_id}'}})
  MATCH (d:Discovery {{id: '{d_id}'}})
  MERGE (a)-[r:AUTHORED]->(d)
  RETURN r
$$) AS (r agtype);
'''
    try:
        run_psql(query)
        return True
    except Exception as e:
        print(f"  ERROR creating AUTHORED edge {agent_id} -> {discovery_id}: {e}")
        return False


def create_responds_to_edge(from_id: str, to_id: str) -> bool:
    """Create RESPONDS_TO edge between Discoveries."""
    f_id = from_id.replace("'", "\\'")
    t_id = to_id.replace("'", "\\'")

    query = f'''
SELECT * FROM cypher('governance_graph', $$
  MATCH (d1:Discovery {{id: '{f_id}'}})
  MATCH (d2:Discovery {{id: '{t_id}'}})
  MERGE (d1)-[r:RESPONDS_TO]->(d2)
  RETURN r
$$) AS (r agtype);
'''
    try:
        run_psql(query)
        return True
    except Exception as e:
        print(f"  ERROR creating RESPONDS_TO edge {from_id} -> {to_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Backfill missing AGE graph edges')
    parser.add_argument('--dry-run', action='store_true', help='Preview without creating edges')
    parser.add_argument('--authored-only', action='store_true', help='Only create AUTHORED edges')
    parser.add_argument('--responds-only', action='store_true', help='Only create RESPONDS_TO edges')
    args = parser.parse_args()

    print(f"{'DRY RUN - ' if args.dry_run else ''}Backfill AGE Graph Edges")
    print("=" * 60)

    # Check current state
    print("\nCurrent edge counts:")
    authored_count = count_existing_edges("AUTHORED")
    responds_count = count_existing_edges("RESPONDS_TO")
    print(f"  AUTHORED: {authored_count}")
    print(f"  RESPONDS_TO: {responds_count}")
    print()

    # Get pairs for edges
    authored_pairs = [] if args.responds_only else get_discovery_agent_pairs()
    responds_pairs = [] if args.authored_only else get_response_to_pairs()

    print(f"Edges to create:")
    print(f"  AUTHORED: {len(authored_pairs)} (Discovery -> Agent relationships)")
    print(f"  RESPONDS_TO: {len(responds_pairs)} (Discovery -> Discovery responses)")
    print()

    if not authored_pairs and not responds_pairs:
        print("No edges to create!")
        return 0

    if args.dry_run:
        # Show sample
        if authored_pairs:
            print("Sample AUTHORED edges (first 5):")
            for d_id, a_id in authored_pairs[:5]:
                print(f"  Agent({a_id[:30]}...) -[:AUTHORED]-> Discovery({d_id[:30]}...)")
        if responds_pairs:
            print("\nSample RESPONDS_TO edges (first 5):")
            for f_id, t_id in responds_pairs[:5]:
                print(f"  Discovery({f_id[:30]}...) -[:RESPONDS_TO]-> Discovery({t_id[:30]}...)")

        print("\n" + "=" * 60)
        print(f"DRY RUN complete. Would create {len(authored_pairs)} AUTHORED + {len(responds_pairs)} RESPONDS_TO edges.")
        print("Run without --dry-run to apply.")
        return 0

    # Create edges
    print("=" * 60)
    print("Creating edges...")

    # AUTHORED edges
    if authored_pairs:
        print(f"\nCreating {len(authored_pairs)} AUTHORED edges...")
        created = 0
        failed = 0
        for i, (d_id, a_id) in enumerate(authored_pairs):
            if create_authored_edge(d_id, a_id):
                created += 1
            else:
                failed += 1

            if (i + 1) % 50 == 0:
                print(f"  Progress: {i + 1}/{len(authored_pairs)} ({created} created, {failed} failed)")

        print(f"  AUTHORED: {created} created, {failed} failed")

    # RESPONDS_TO edges
    if responds_pairs:
        print(f"\nCreating {len(responds_pairs)} RESPONDS_TO edges...")
        created = 0
        failed = 0
        for i, (f_id, t_id) in enumerate(responds_pairs):
            if create_responds_to_edge(f_id, t_id):
                created += 1
            else:
                failed += 1

            if (i + 1) % 10 == 0:
                print(f"  Progress: {i + 1}/{len(responds_pairs)} ({created} created, {failed} failed)")

        print(f"  RESPONDS_TO: {created} created, {failed} failed")

    # Verify
    print("\n" + "=" * 60)
    print("Verification - new edge counts:")
    print(f"  AUTHORED: {count_existing_edges('AUTHORED')}")
    print(f"  RESPONDS_TO: {count_existing_edges('RESPONDS_TO')}")
    print("\nDone!")

    return 0


if __name__ == '__main__':
    sys.exit(main())
