#!/usr/bin/env python3
"""
Regenerate embeddings for system_migration discoveries after summary cleanup.

The cleanup_migration_summaries.py script fixed summaries that had metadata
formatting ("**Date:**...") instead of semantic content. Now we need to
regenerate embeddings using the corrected summaries.

Usage:
    python scripts/regenerate_embeddings.py --dry-run   # Preview what would be updated
    python scripts/regenerate_embeddings.py              # Regenerate embeddings
"""

import argparse
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def regenerate_embeddings(dry_run: bool = True, agent_filter: str = "system_migration"):
    """Regenerate embeddings for discoveries with updated summaries."""
    from src.storage.knowledge_graph_age import KnowledgeGraphAGE
    from src.embeddings import get_embeddings_service, embeddings_available

    print(f"{'DRY RUN - ' if dry_run else ''}Regenerate Embeddings")
    print("=" * 60)

    # Check embeddings service
    if not embeddings_available():
        print("ERROR: Embeddings service not available")
        return 1

    embeddings = await get_embeddings_service()
    print(f"Embeddings model: {embeddings.model_name}")

    # Get knowledge graph
    graph = KnowledgeGraphAGE()
    db = await graph._get_db()

    if not await graph._pgvector_available():
        print("ERROR: pgvector not available")
        return 1

    print(f"pgvector: available")
    print()

    # Query discoveries to update
    print(f"Querying {agent_filter} discoveries...")
    discoveries = await graph.query(agent_id=agent_filter, limit=200)
    print(f"Found {len(discoveries)} discoveries")

    if not discoveries:
        print("No discoveries to update")
        return 0

    # Preview first few
    print("\nFirst 5 discoveries:")
    for d in discoveries[:5]:
        print(f"  [{d.id[:20]}...] {d.summary[:50]}...")

    if dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN complete. No embeddings updated.")
        print(f"Run without --dry-run to regenerate {len(discoveries)} embeddings.")
        return 0

    # Regenerate embeddings
    print("\n" + "=" * 60)
    print("Regenerating embeddings...")

    updated = 0
    failed = 0

    for i, d in enumerate(discoveries):
        try:
            # Create embedding text (same as store_discovery)
            text = f"{d.summary}\n{d.details[:500] if d.details else ''}"
            emb = await embeddings.embed(text)

            # Store embedding
            await graph._store_embedding(d.id, emb)
            updated += 1

            if (i + 1) % 20 == 0:
                print(f"  Progress: {i + 1}/{len(discoveries)} ({updated} updated, {failed} failed)")

        except Exception as e:
            print(f"  ERROR [{d.id[:20]}]: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"COMPLETE: {updated} embeddings regenerated, {failed} failed")

    return 0 if failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(description='Regenerate embeddings after summary cleanup')
    parser.add_argument('--dry-run', action='store_true', help='Preview without updating')
    parser.add_argument('--agent', type=str, default='system_migration', help='Agent ID to filter (default: system_migration)')
    args = parser.parse_args()

    return asyncio.run(regenerate_embeddings(dry_run=args.dry_run, agent_filter=args.agent))


if __name__ == '__main__':
    exit(main())
