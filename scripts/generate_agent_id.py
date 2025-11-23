#!/usr/bin/env python3
"""
Quick script to generate a new agent ID

Usage:
    python scripts/generate_agent_id.py
    python scripts/generate_agent_id.py --purpose "debugging"
    python scripts/generate_agent_id.py --custom "my_custom_id"
    python scripts/generate_agent_id.py --auto
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agent_id_manager import AgentIDManager, get_agent_id
import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Generate a unique agent ID for governance monitoring"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-generate session ID (recommended)"
    )
    parser.add_argument(
        "--purpose",
        type=str,
        help="Generate purpose-based ID (e.g., 'debugging', 'analysis')"
    )
    parser.add_argument(
        "--custom",
        type=str,
        help="Use custom agent ID (will validate for collisions)"
    )
    parser.add_argument(
        "--check",
        type=str,
        metavar="AGENT_ID",
        help="Check if agent ID is already active"
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Non-interactive mode (no prompts)"
    )
    
    args = parser.parse_args()
    
    metadata_file = project_root / "data" / "agent_metadata.json"
    
    # Check mode
    if args.check:
        is_active = AgentIDManager.check_active_agents(args.check, metadata_file)
        if is_active:
            print(f"⚠️  '{args.check}' is already ACTIVE")
            print("   Using this ID will cause state collisions!")
        else:
            print(f"✅ '{args.check}' is available")
        return
    
    # Generate mode
    if args.auto:
        manager = AgentIDManager()
        agent_id = manager._generate_session_id()
        print(f"✅ Generated session ID: {agent_id}")
    elif args.purpose:
        manager = AgentIDManager()
        agent_id = manager._generate_purpose_id(args.purpose)
        print(f"✅ Generated purpose-based ID: {agent_id}")
    elif args.custom:
        manager = AgentIDManager()
        agent_id = manager._validate_custom_id(args.custom, interactive=not args.non_interactive)
        print(f"✅ Custom agent ID: {agent_id}")
    else:
        # Interactive mode - use the full manager
        agent_id = get_agent_id(interactive=not args.non_interactive)
        print(f"✅ Generated agent ID: {agent_id}")
    
    # Check for collisions
    if AgentIDManager.check_active_agents(agent_id, metadata_file):
        print(f"\n🚨 WARNING: '{agent_id}' is already active!")
        print("   This will cause state collisions. Consider using a different ID.")
    else:
        print(f"\n✅ '{agent_id}' is available and ready to use")
    
    print(f"\n📋 Copy this agent ID:")
    print(f"   {agent_id}")


if __name__ == "__main__":
    main()

