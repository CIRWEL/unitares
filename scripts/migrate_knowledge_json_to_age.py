#!/usr/bin/env python3
"""
Migrate per-agent knowledge JSON files directly to AGE backend.

Reads all data/knowledge/*_knowledge.json files and imports them
into the PostgreSQL AGE knowledge graph.

Usage:
    python3 scripts/migrate_knowledge_json_to_age.py [--dry-run]
"""

from __future__ import annotations

import sys
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.knowledge_graph import DiscoveryNode, ResponseTo


async def load_discoveries_from_file(filepath: Path) -> list[tuple[str, DiscoveryNode]]:
    """Load discoveries from a per-agent knowledge JSON file."""
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ⚠️  Error reading {filepath.name}: {e}")
        return []
    
    agent_id = data.get("agent_id")
    if not agent_id:
        # Try to extract from filename
        name = filepath.stem.replace("_knowledge", "")
        agent_id = name
    
    discoveries = data.get("discoveries", [])
    if not discoveries:
        # Try alternate format
        discoveries = list(data.get("nodes", {}).values())
    
    results = []
    for d in discoveries:
        try:
            # Parse response_to if present
            response_to = None
            if "response_to" in d and d["response_to"]:
                resp = d["response_to"]
                if isinstance(resp, dict):
                    response_to = ResponseTo(
                        discovery_id=resp.get("discovery_id", ""),
                        response_type=resp.get("response_type", "extend")
                    )
            
            node = DiscoveryNode(
                id=d.get("id") or d.get("timestamp", datetime.now().isoformat()),
                agent_id=d.get("agent_id", agent_id),
                type=d.get("type", "insight"),
                summary=d.get("summary", "")[:500],
                details=d.get("details", "")[:2000],
                tags=d.get("tags", [])[:20],
                severity=d.get("severity"),
                timestamp=d.get("timestamp", datetime.now().isoformat()),
                status=d.get("status", "open"),
                related_to=d.get("related_to", d.get("related_discoveries", []))[:10],
                response_to=response_to,
                references_files=d.get("references_files", d.get("related_files", []))[:10],
                resolved_at=d.get("resolved_at"),
                updated_at=d.get("updated_at"),
                confidence=d.get("confidence"),
                provenance=d.get("provenance"),
                provenance_chain=d.get("provenance_chain"),
            )
            results.append((agent_id, node))
        except Exception as e:
            print(f"  ⚠️  Error parsing discovery: {e}")
            continue
    
    return results


async def main():
    parser = argparse.ArgumentParser(description="Migrate knowledge JSON to AGE")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually write to AGE")
    args = parser.parse_args()
    
    print("🔄 Migrating per-agent knowledge JSON files to AGE...")
    print()
    
    # Find all knowledge files
    knowledge_dir = project_root / "data" / "knowledge"
    if not knowledge_dir.exists():
        print(f"❌ Knowledge directory not found: {knowledge_dir}")
        return 1
    
    knowledge_files = list(knowledge_dir.glob("*_knowledge.json"))
    if not knowledge_files:
        print("ℹ️  No knowledge files found to migrate")
        return 0
    
    print(f"📁 Found {len(knowledge_files)} knowledge files")
    print()
    
    # Collect all discoveries
    all_discoveries = []
    for filepath in sorted(knowledge_files):
        discoveries = await load_discoveries_from_file(filepath)
        print(f"📄 {filepath.name}: {len(discoveries)} discoveries")
        all_discoveries.extend(discoveries)
    
    print()
    print(f"📊 Total discoveries to migrate: {len(all_discoveries)}")
    
    if args.dry_run:
        print()
        print("🔍 Dry run - not writing to AGE")
        return 0
    
    # Import AGE backend
    print()
    print("🔌 Connecting to AGE backend...")
    
    from src.storage.knowledge_graph_age import KnowledgeGraphAGE
    
    graph = KnowledgeGraphAGE()
    
    # Check current state
    try:
        stats = await graph.get_stats()
        print(f"📊 Current AGE state: {stats.get('total_discoveries', 0)} discoveries")
    except Exception as e:
        print(f"⚠️  Could not get current stats: {e}")
    
    # Migrate discoveries
    print()
    print("📥 Importing discoveries...")
    
    success = 0
    errors = 0
    skipped = 0
    
    for agent_id, discovery in all_discoveries:
        try:
            # Check if already exists
            existing = await graph.get_discovery(discovery.id)
            if existing:
                skipped += 1
                continue
            
            # Bypass rate limiting for migration
            graph.rate_limit_stores_per_hour = 10000
            
            await graph.add_discovery(discovery)
            success += 1
            
            if success % 50 == 0:
                print(f"  ✅ {success} imported...")
                
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  ⚠️  Error importing {discovery.id}: {e}")
            elif errors == 6:
                print(f"  ⚠️  (suppressing further errors...)")
    
    print()
    print("📊 Migration Results:")
    print(f"  ✅ Imported: {success}")
    print(f"  ⏭️  Skipped (already exist): {skipped}")
    print(f"  ❌ Errors: {errors}")
    
    # Final stats
    try:
        stats = await graph.get_stats()
        print()
        print(f"📊 Final AGE state: {stats.get('total_discoveries', 0)} discoveries")
    except Exception as e:
        print(f"⚠️  Could not get final stats: {e}")
    
    print()
    print("✅ Migration complete!")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
