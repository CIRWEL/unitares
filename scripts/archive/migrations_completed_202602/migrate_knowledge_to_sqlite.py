#!/usr/bin/env python3
"""
Migrate knowledge graph from JSON to SQLite.

Usage:
    python scripts/migrate_knowledge_to_sqlite.py [--dry-run] [--verify]

Options:
    --dry-run   Show what would be migrated without writing to DB
    --verify    After migration, verify data integrity
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.knowledge_db import KnowledgeGraphDB, DiscoveryNode, ResponseTo


def load_json_data(json_path: Path) -> dict:
    """Load existing JSON knowledge graph"""
    if not json_path.exists():
        print(f"Error: JSON file not found at {json_path}")
        sys.exit(1)

    with open(json_path, 'r') as f:
        return json.load(f)


def convert_node(node_id: str, node_data: dict) -> DiscoveryNode:
    """Convert JSON node to DiscoveryNode"""
    # Handle response_to
    response_to = None
    if node_data.get("response_to"):
        resp = node_data["response_to"]
        if isinstance(resp, dict):
            response_to = ResponseTo(
                discovery_id=resp.get("discovery_id", ""),
                response_type=resp.get("response_type", "extend")
            )

    return DiscoveryNode(
        id=node_id,
        agent_id=node_data.get("agent_id", "unknown"),
        type=node_data.get("type", "insight"),
        summary=node_data.get("summary", ""),
        details=node_data.get("details", ""),
        tags=node_data.get("tags", []),
        severity=node_data.get("severity"),
        timestamp=node_data.get("timestamp", datetime.now().isoformat()),
        status=node_data.get("status", "open"),
        related_to=node_data.get("related_to", []),
        response_to=response_to,
        responses_from=node_data.get("responses_from", []),
        references_files=node_data.get("references_files", []),
        resolved_at=node_data.get("resolved_at"),
        updated_at=node_data.get("updated_at"),
        confidence=node_data.get("confidence")
    )


def migrate(dry_run: bool = False, verify: bool = False):
    """Run the migration"""
    json_path = project_root / "data" / "knowledge_graph.json"
    db_path = project_root / "data" / "knowledge.db"

    print(f"Loading JSON from: {json_path}")
    data = load_json_data(json_path)

    nodes = data.get("nodes", {})
    print(f"Found {len(nodes)} discoveries to migrate")

    if dry_run:
        print("\n=== DRY RUN - No changes will be made ===\n")

        # Show sample
        for i, (node_id, node_data) in enumerate(nodes.items()):
            if i >= 3:
                print(f"... and {len(nodes) - 3} more")
                break
            node = convert_node(node_id, node_data)
            print(f"  [{i+1}] {node.id[:30]}...")
            print(f"      Agent: {node.agent_id}")
            print(f"      Type: {node.type}")
            print(f"      Tags: {node.tags[:3]}{'...' if len(node.tags) > 3 else ''}")
            print(f"      Response to: {node.response_to.discovery_id[:30] if node.response_to else 'None'}...")
            print()

        # Stats
        types = {}
        agents = set()
        with_response_to = 0
        with_related_to = 0

        for node_data in nodes.values():
            t = node_data.get("type", "unknown")
            types[t] = types.get(t, 0) + 1
            agents.add(node_data.get("agent_id", "unknown"))
            if node_data.get("response_to"):
                with_response_to += 1
            if node_data.get("related_to"):
                with_related_to += len(node_data["related_to"])

        print("=== Migration Summary ===")
        print(f"Total discoveries: {len(nodes)}")
        print(f"Unique agents: {len(agents)}")
        print(f"Response edges: {with_response_to}")
        print(f"Related edges: {with_related_to}")
        print(f"\nBy type:")
        for t, count in sorted(types.items(), key=lambda x: -x[1]):
            print(f"  {t}: {count}")

        return

    # Backup existing DB if exists
    if db_path.exists():
        backup_path = db_path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        print(f"Backing up existing DB to: {backup_path}")
        import shutil
        shutil.copy(db_path, backup_path)
        db_path.unlink()

    # Create new DB
    print(f"Creating new SQLite DB at: {db_path}")
    db = KnowledgeGraphDB(db_path)

    # Migrate nodes
    import asyncio

    async def do_migrate():
        success = 0
        failed = 0
        edges_created = 0
        orphan_edges = 0

        # First pass: insert all discoveries (without rate limiting)
        # Temporarily disable rate limiting for migration
        original_limit = db.rate_limit_stores_per_hour
        db.rate_limit_stores_per_hour = 999999

        # Collect all valid node IDs first
        valid_ids = set(nodes.keys())

        for node_id, node_data in nodes.items():
            try:
                node = convert_node(node_id, node_data)

                # Filter out invalid related_to references
                original_related = node.related_to
                node.related_to = [r for r in node.related_to if r in valid_ids]
                orphan_edges += len(original_related) - len(node.related_to)

                # Filter out invalid response_to reference
                if node.response_to and node.response_to.discovery_id not in valid_ids:
                    print(f"  Warning: {node_id[:30]} has orphan response_to -> {node.response_to.discovery_id[:30]}")
                    node.response_to = None
                    orphan_edges += 1

                await db.add_discovery(node)
                success += 1

                if node.response_to:
                    edges_created += 1
                edges_created += len(node.related_to)

                if success % 50 == 0:
                    print(f"  Migrated {success}/{len(nodes)}...")

            except Exception as e:
                print(f"  Error migrating {node_id}: {e}")
                failed += 1

        # Restore rate limiting
        db.rate_limit_stores_per_hour = original_limit

        print(f"\n=== Migration Complete ===")
        print(f"Success: {success}")
        print(f"Failed: {failed}")
        print(f"Edges created: {edges_created}")
        print(f"Orphan edges skipped: {orphan_edges}")

        if verify:
            print("\n=== Verifying Migration ===")
            stats = await db.get_stats()
            print(f"DB discoveries: {stats['total_discoveries']}")
            print(f"DB agents: {stats['total_agents']}")
            print(f"DB edges: {stats['total_edges']}")
            print(f"DB tags: {stats['total_tags']}")

            # Spot check a few
            print("\n=== Spot Check ===")
            first_ids = list(nodes.keys())[:3]
            for node_id in first_ids:
                db_node = await db.get_discovery(node_id)
                if db_node:
                    print(f"  ✓ {node_id[:30]}... found")
                else:
                    print(f"  ✗ {node_id[:30]}... MISSING")

            # Test FTS
            print("\n=== Testing Full-Text Search ===")
            results = await db.full_text_search("coherence")
            print(f"  Search 'coherence': {len(results)} results")

            # Test graph traversal
            print("\n=== Testing Graph Traversal ===")
            for node_id, node_data in nodes.items():
                if node_data.get("response_to"):
                    related = await db.get_related_discoveries(node_id)
                    print(f"  Node {node_id[:20]}... has {len(related)} related discoveries")
                    break

    asyncio.run(do_migrate())

    print(f"\n✓ Migration complete! DB at: {db_path}")


def main():
    parser = argparse.ArgumentParser(description="Migrate knowledge graph from JSON to SQLite")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated")
    parser.add_argument("--verify", action="store_true", help="Verify migration after completion")
    args = parser.parse_args()

    migrate(dry_run=args.dry_run, verify=args.verify)


if __name__ == "__main__":
    main()
