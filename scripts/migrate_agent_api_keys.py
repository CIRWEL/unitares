#!/usr/bin/env python3
"""
Migration Script: Add API Keys to Existing Agents

This script adds API keys to all agents that don't have them yet.
This is needed because authentication was added after some agents were created.

Usage:
    python scripts/migrate_agent_api_keys.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import only what we need, avoiding server startup
import secrets
import base64
from dataclasses import dataclass, asdict
from datetime import datetime

def generate_api_key() -> str:
    """Generate a secure 32-byte API key for agent authentication."""
    key_bytes = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(key_bytes).decode('ascii').rstrip('=')

# Load metadata directly
METADATA_FILE = project_root / "data" / "agent_metadata.json"

def migrate_agent_api_keys():
    """Add API keys to all agents that don't have them"""
    print("="*70)
    print("AGENT API KEY MIGRATION")
    print("="*70)
    
    # Load metadata directly
    if not METADATA_FILE.exists():
        print(f"\n❌ Metadata file not found: {METADATA_FILE}")
        return 1
    
    with open(METADATA_FILE, 'r') as f:
        metadata = json.load(f)
    
    agents_needing_keys = []
    agents_with_keys = []
    
    for agent_id, meta_dict in metadata.items():
        if meta_dict.get('api_key') is None:
            agents_needing_keys.append(agent_id)
        else:
            agents_with_keys.append(agent_id)
    
    print(f"\n📊 Status:")
    print(f"   ✅ Agents with keys: {len(agents_with_keys)}")
    print(f"   ❌ Agents needing keys: {len(agents_needing_keys)}")
    
    if not agents_needing_keys:
        print("\n✅ All agents already have API keys!")
        return 0
    
    print(f"\n🔑 Generating API keys for {len(agents_needing_keys)} agents...")
    
    generated_keys = {}
    for agent_id in agents_needing_keys:
        api_key = generate_api_key()
        metadata[agent_id]['api_key'] = api_key
        generated_keys[agent_id] = api_key
        print(f"   ✅ {agent_id}: {api_key[:20]}...")
    
    # Save metadata
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"\n✅ Migration complete! Generated {len(generated_keys)} API keys.")
    print("\n⚠️  IMPORTANT: Save these API keys - you'll need them for future updates!")
    print("\nGenerated Keys:")
    for agent_id, api_key in generated_keys.items():
        print(f"   {agent_id}: {api_key}")
    
    return 0

if __name__ == "__main__":
    sys.exit(migrate_agent_api_keys())

