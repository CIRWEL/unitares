#!/usr/bin/env python3
"""
Archive inactive test agents and old CLI sessions
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load metadata
metadata_file = project_root / "data" / "agent_metadata.json"

with open(metadata_file, 'r') as f:
    metadata = json.load(f)

# Agents to archive
agents_to_archive = [
    # Test agents (completed/inactive)
    ("test_integration", "Test completed, no updates"),
    ("test_metadata_fix", "Test completed, no updates"),
    ("test_eisv_labels", "EISV label testing complete"),
    ("test_ticket_123", "Ticket testing complete"),
    # Old CLI sessions (superseded)
    ("claude_code_cli_discovery", "Old CLI session, superseded by claude_cli_cirwel_20251120_0011"),
    ("claude_code_cli", "Early CLI testing, superseded"),
    ("claude_code_cli_cirwel", "Transitional session, superseded"),
]

archived_count = 0
not_found = []

for agent_id, reason in agents_to_archive:
    if agent_id in metadata:
        agent = metadata[agent_id]

        # Skip if already archived
        if agent.get('status') == 'archived':
            print(f"⏭️  {agent_id}: Already archived")
            continue

        # Archive the agent
        agent['status'] = 'archived'
        agent['archived_at'] = datetime.now().isoformat()

        # Add lifecycle event
        if 'lifecycle_events' not in agent:
            agent['lifecycle_events'] = []

        agent['lifecycle_events'].append({
            'event': 'archived',
            'timestamp': datetime.now().isoformat(),
            'reason': reason
        })

        print(f"✅ {agent_id}: Archived")
        archived_count += 1
    else:
        print(f"❌ {agent_id}: Not found")
        not_found.append(agent_id)

# Save updated metadata
if archived_count > 0:
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n📦 Archived {archived_count} agents")
    print(f"💾 Metadata saved to {metadata_file}")
else:
    print("\n⚠️  No agents were archived")

if not_found:
    print(f"\n⚠️  Agents not found: {', '.join(not_found)}")
