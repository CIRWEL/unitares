#!/usr/bin/env python3
"""
Backfill embeddings for well-connected discoveries that don't have embeddings yet.

This improves semantic search quality by ensuring high-value discoveries
(those with many inbound links) are findable via vector similarity.

Usage:
    python scripts/backfill_embeddings.py [--limit N] [--min-connectivity N] [--dry-run]

Environment:
    DB_POSTGRES_URL - PostgreSQL connection string
    DB_BACKEND - Must be "postgres"
"""

import argparse
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db import get_db
from src.embeddings import EmbeddingsService


async def find_discoveries_needing_embeddings(db, min_inbound: int = 1, limit: int = 100):
    """Find discoveries with inbound edges but no embeddings."""

    # Get discoveries with connectivity from AGE graph
    async with db._pool.acquire() as conn:
        await conn.execute("LOAD 'age'")
        await conn.execute("SET search_path = ag_catalog, core, public")

        # Find well-connected discoveries
        rows = await conn.fetch("""
            SELECT * FROM cypher('governance_graph', $$
                MATCH (d:Discovery)
                OPTIONAL MATCH (other:Discovery)-[:RELATED_TO]->(d)
                OPTIONAL MATCH (resp:Discovery)-[:RESPONDS_TO]->(d)
                WITH d, count(DISTINCT other) + count(DISTINCT resp) as inbound_count
                WHERE inbound_count >= 1
                RETURN d.id as id, d.summary as summary, d.details as details, inbound_count
                ORDER BY inbound_count DESC
            $$) as (id agtype, summary agtype, details agtype, inbound_count agtype)
        """)

        # Filter out those that already have embeddings
        candidates = []
        for row in rows:
            disc_id = str(row['id']).strip('"')

            # Check if embedding exists
            existing = await conn.fetchval(
                "SELECT 1 FROM core.discovery_embeddings WHERE discovery_id = $1",
                disc_id
            )

            if not existing:
                summary = str(row['summary']).strip('"') if row['summary'] else ""
                details = str(row['details']).strip('"') if row['details'] else ""
                inbound = int(str(row['inbound_count']))
                candidates.append({
                    'id': disc_id,
                    'summary': summary,
                    'details': details,
                    'inbound_count': inbound,
                    'text': f"{summary}\n\n{details}".strip()
                })

                if len(candidates) >= limit:
                    break

        return candidates


async def store_embedding(db, discovery_id: str, embedding: list):
    """Store embedding in pgvector table."""
    embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'

    async with db._pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO core.discovery_embeddings (discovery_id, embedding, model_name)
            VALUES ($1, $2::vector, 'all-MiniLM-L6-v2')
            ON CONFLICT (discovery_id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                updated_at = now()
        """, discovery_id, embedding_str)


async def main():
    parser = argparse.ArgumentParser(description='Backfill embeddings for well-connected discoveries')
    parser.add_argument('--limit', type=int, default=100, help='Max discoveries to process')
    parser.add_argument('--min-connectivity', type=int, default=1, help='Min inbound edges required')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without doing it')
    parser.add_argument('--batch-size', type=int, default=32, help='Embedding batch size')
    args = parser.parse_args()

    # Check environment
    if os.getenv('DB_BACKEND', 'postgres') != 'postgres':
        print("Error: DB_BACKEND must be 'postgres'")
        sys.exit(1)

    if not os.getenv('DB_POSTGRES_URL'):
        print("Error: DB_POSTGRES_URL not set")
        sys.exit(1)

    print(f"Backfill Embeddings for Well-Connected Discoveries")
    print(f"=" * 60)
    print(f"Limit: {args.limit} discoveries")
    print(f"Min connectivity: {args.min_connectivity} inbound edges")
    print(f"Dry run: {args.dry_run}")
    print()

    # Initialize database
    db = get_db()
    await db.init()

    # Find candidates
    print("Finding discoveries needing embeddings...")
    candidates = await find_discoveries_needing_embeddings(
        db,
        min_inbound=args.min_connectivity,
        limit=args.limit
    )

    if not candidates:
        print("No discoveries need embeddings!")
        return

    print(f"Found {len(candidates)} discoveries to process:")
    for i, c in enumerate(candidates[:10]):
        print(f"  {i+1}. [{c['inbound_count']} inbound] {c['summary'][:60]}...")
    if len(candidates) > 10:
        print(f"  ... and {len(candidates) - 10} more")
    print()

    if args.dry_run:
        print("Dry run - no embeddings generated")
        return

    # Initialize embedding service
    print("Loading embedding model...")
    embedder = EmbeddingsService()
    print()

    # Generate and store embeddings in batches
    print("Generating embeddings...")
    total = len(candidates)
    processed = 0

    for i in range(0, total, args.batch_size):
        batch = candidates[i:i + args.batch_size]
        texts = [c['text'] for c in batch]

        # Generate embeddings using async batch method
        embeddings = await embedder.embed_batch(texts, batch_size=args.batch_size)

        # Store each embedding
        for candidate, embedding in zip(batch, embeddings):
            await store_embedding(db, candidate['id'], embedding)
            processed += 1

        print(f"  Processed {processed}/{total} ({processed*100//total}%)")

    print()
    print(f"Done! Generated embeddings for {processed} discoveries.")

    # Verify
    async with db._pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM core.discovery_embeddings")
        print(f"Total embeddings in database: {count}")


if __name__ == '__main__':
    asyncio.run(main())
