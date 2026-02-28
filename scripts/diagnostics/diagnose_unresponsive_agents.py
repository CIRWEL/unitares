#!/usr/bin/env python3
"""
Diagnose and fix unresponsive agents.

This script helps identify why agents might be unresponsive and provides
options to fix common issues.

Usage:
    python3 scripts/diagnose_unresponsive_agents.py [--fix]
"""

import asyncio
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def diagnose_agents(fix=False):
    """Diagnose agent responsiveness issues."""
    os.environ['DB_BACKEND'] = os.environ.get('DB_BACKEND', 'postgres')
    os.environ['DB_POSTGRES_URL'] = os.environ.get(
        'DB_POSTGRES_URL',
        'postgresql://postgres:postgres@localhost:5432/governance'
    )
    
    try:
        from src.db import init_db, get_db, close_db
        
        await init_db()
        db = get_db()
        
        print("=" * 70)
        print("Agent Responsiveness Diagnostic")
        print("=" * 70)
        
        # Get all identities
        identities = await db.list_identities(limit=1000)
        
        print(f"\n📊 Total agents: {len(identities)}")
        
        # Categorize agents
        by_status = {}
        for identity in identities:
            status = identity.status
            if status not in by_status:
                by_status[status] = []
            by_status[status].append(identity)
        
        print("\n📈 Status Distribution:")
        for status, agents in sorted(by_status.items()):
            print(f"  {status}: {len(agents)}")
        
        # Check waiting_input agents
        waiting_agents = by_status.get('waiting_input', [])
        if waiting_agents:
            print(f"\n⏸️  Agents in 'waiting_input' status ({len(waiting_agents)}):")
            print("   Note: This is NORMAL - agents completed work and are waiting for user input")
            print("   These agents are NOT stuck - they're waiting for you to respond")
            
            for agent in waiting_agents[:5]:
                print(f"\n   • {agent.agent_id}")
                if hasattr(agent, 'updated_at') and agent.updated_at:
                    try:
                        if isinstance(agent.updated_at, str):
                            updated = datetime.fromisoformat(agent.updated_at.replace('Z', '+00:00'))
                        else:
                            updated = agent.updated_at
                        if isinstance(updated, datetime):
                            age = datetime.now(timezone.utc) - updated.replace(tzinfo=timezone.utc) if updated.tzinfo else datetime.now() - updated
                            print(f"     Last updated: {age.days} days ago")
                    except:
                        pass
        
        # Check for agents in dialectic sessions
        print("\n💬 Checking for agents blocked by dialectic sessions...")
        blocked_agents = []
        for identity in identities[:50]:  # Check first 50
            try:
                in_session = await db.is_agent_in_active_dialectic_session(identity.agent_id)
                if in_session:
                    blocked_agents.append(identity.agent_id)
            except Exception as e:
                pass
        
        if blocked_agents:
            print(f"   ⚠️  Found {len(blocked_agents)} agents in active dialectic sessions:")
            for agent_id in blocked_agents[:5]:
                print(f"     • {agent_id}")
        else:
            print("   ✅ No agents blocked by dialectic sessions")
        
        # Check active sessions
        print("\n🔐 Checking active sessions...")
        agents_with_sessions = []
        for identity in identities[:50]:
            try:
                sessions = await db.get_active_sessions_for_identity(identity.identity_id)
                if sessions:
                    agents_with_sessions.append((identity.agent_id, len(sessions)))
            except:
                pass
        
        if agents_with_sessions:
            print(f"   Found {len(agents_with_sessions)} agents with active sessions")
        else:
            print("   ✅ No active sessions found")
        
        # Check for stale lock files
        print("\n🔒 Checking for stale lock files...")
        lock_dir = Path(__file__).parent.parent.parent / "data" / "locks"
        if lock_dir.exists():
            lock_files = list(lock_dir.glob("*.lock"))
            if lock_files:
                print(f"   Found {len(lock_files)} lock files")
                for lock_file in lock_files[:5]:
                    age = datetime.now() - datetime.fromtimestamp(lock_file.stat().st_mtime)
                    if age.days > 1:
                        print(f"     ⚠️  Stale: {lock_file.name} ({age.days} days old)")
            else:
                print("   ✅ No lock files found")
        else:
            print("   ✅ Lock directory doesn't exist")
        
        # Recommendations
        print("\n" + "=" * 70)
        print("💡 Recommendations:")
        print("=" * 70)
        
        if waiting_agents:
            print("\n1. Agents in 'waiting_input' are NOT unresponsive:")
            print("   • They completed their work and are waiting for user input")
            print("   • This is expected behavior - no action needed")
            print("   • They will resume when you send them a new message")
        
        if blocked_agents:
            print("\n2. Agents blocked by dialectic sessions:")
            print("   • These agents are paused for peer review")
            print("   • Check dialectic sessions: python3 scripts/mcp_call.py get_dialectic_session <session_id>")
            print("   • Resolve sessions if needed")
        
        if agents_with_sessions:
            print("\n3. Agents with active sessions:")
            print("   • These agents have active MCP connections")
            print("   • Check if connections are healthy in server logs")
        
        # SSE connection health check
        print("\n4. SSE Connection Health:")
        print("   • Check server logs for 'Unhealthy connection' warnings")
        print("   • Idle connections > 5 minutes may indicate client issues")
        print("   • Restart clients if connections are stale")
        
        if fix:
            print("\n" + "=" * 70)
            print("🔧 Fix Mode:")
            print("=" * 70)
            print("\nTo manually resume agents:")
            print("  1. Use 'direct_resume_if_safe' for safe agents")
            print("  2. Use 'request_dialectic_review' for complex cases")
            print("  3. Use 'mark_response_complete' if agent just finished work")
        
        await close_db()
        
        print("\n" + "=" * 70)
        print("✅ Diagnostic complete")
        print("=" * 70)
        
    except Exception as e:
        import traceback
        print(f"\n❌ Error: {e}")
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnose unresponsive agents")
    parser.add_argument("--fix", action="store_true", help="Show fix recommendations")
    args = parser.parse_args()
    
    success = asyncio.run(diagnose_agents(fix=args.fix))
    sys.exit(0 if success else 1)

