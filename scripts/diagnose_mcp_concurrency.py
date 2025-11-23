#!/usr/bin/env python3
"""
Diagnostic script to examine why multiple agents can't use the MCP simultaneously.

Identifies:
1. Lock contention issues
2. Metadata file conflicts
3. Process conflicts
4. Resource contention
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def check_lock_files():
    """Check for active lock files"""
    lock_dir = project_root / "data" / "locks"
    print("\n" + "=" * 80)
    print("LOCK FILES ANALYSIS")
    print("=" * 80)
    
    if not lock_dir.exists():
        print("✅ No lock directory - no locks active")
        return []
    
    lock_files = list(lock_dir.glob("*.lock"))
    if not lock_files:
        print("✅ No active lock files")
        return []
    
    print(f"⚠️  Found {len(lock_files)} lock file(s):")
    print()
    
    locks_info = []
    for lock_file in sorted(lock_files):
        agent_id = lock_file.stem
        age_seconds = time.time() - lock_file.stat().st_mtime
        age_minutes = age_seconds / 60
        
        # Try to read lock info
        try:
            with open(lock_file, 'r') as f:
                lock_data = json.load(f)
                pid = lock_data.get('pid', 'unknown')
                timestamp = lock_data.get('timestamp', 0)
                lock_age = time.time() - timestamp if timestamp else age_seconds
        except:
            pid = 'unknown'
            lock_age = age_seconds
        
        locks_info.append({
            'agent_id': agent_id,
            'pid': pid,
            'age_minutes': age_minutes,
            'lock_age': lock_age
        })
        
        status = "⚠️  STALE" if age_minutes > 5 else "✅ Active"
        print(f"  {status} {agent_id}")
        print(f"    PID: {pid}, Age: {age_minutes:.1f}m")
        print()
    
    return locks_info


def check_metadata_file():
    """Check metadata file for conflicts"""
    metadata_file = project_root / "data" / "agent_metadata.json"
    print("=" * 80)
    print("METADATA FILE ANALYSIS")
    print("=" * 80)
    
    if not metadata_file.exists():
        print("⚠️  Metadata file doesn't exist")
        return
    
    # Check file permissions
    stat = metadata_file.stat()
    print(f"File: {metadata_file}")
    print(f"Size: {stat.st_size} bytes")
    print(f"Modified: {datetime.fromtimestamp(stat.st_mtime)}")
    print()
    
    # Check if file is readable
    try:
        with open(metadata_file, 'r') as f:
            data = json.load(f)
        print(f"✅ Metadata file is valid JSON")
        print(f"   Contains {len(data)} agents")
    except json.JSONDecodeError as e:
        print(f"❌ Metadata file is corrupted!")
        print(f"   Error: {e}")
        return
    except Exception as e:
        print(f"❌ Cannot read metadata file: {e}")
        return
    
    # Check for metadata conflicts
    print("\nAgent Status Summary:")
    status_counts = {}
    for agent_id, meta in data.items():
        status = meta.get('status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
    
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")


def check_mcp_processes():
    """Check for multiple MCP server processes"""
    print("\n" + "=" * 80)
    print("MCP SERVER PROCESSES")
    print("=" * 80)
    
    try:
        import psutil
    except ImportError:
        print("⚠️  psutil not available - cannot check processes")
        print("   Install with: pip install psutil")
        return
    
    mcp_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if cmdline and any('mcp_server' in str(arg) for arg in cmdline):
                mcp_processes.append({
                    'pid': proc.info['pid'],
                    'cmdline': ' '.join(cmdline[:3]),
                    'age': time.time() - proc.info['create_time']
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    if not mcp_processes:
        print("✅ No MCP server processes found")
        return
    
    print(f"⚠️  Found {len(mcp_processes)} MCP server process(es):")
    for proc in mcp_processes:
        age_min = proc['age'] / 60
        print(f"  PID {proc['pid']}: {age_min:.1f}m old")
        print(f"    {proc['cmdline']}")
        print()


def analyze_concurrency_issue():
    """Main analysis"""
    print("\n" + "=" * 80)
    print("MCP CONCURRENCY DIAGNOSTIC")
    print("=" * 80)
    print(f"Time: {datetime.now().isoformat()}")
    
    locks_info = check_lock_files()
    check_metadata_file()
    check_mcp_processes()
    
    print("\n" + "=" * 80)
    print("ROOT CAUSE ANALYSIS")
    print("=" * 80)
    
    # Identify the issue
    print("\n🔍 IDENTIFIED ISSUE: Metadata File Race Condition")
    print()
    print("Problem:")
    print("  • Each agent has its own lock file ({agent_id}.lock)")
    print("  • But ALL agents write to the SAME metadata file (agent_metadata.json)")
    print("  • Per-agent locks don't protect the shared metadata file!")
    print()
    print("What happens:")
    print("  1. Agent A acquires lock_A, reads metadata, modifies it")
    print("  2. Agent B acquires lock_B, reads metadata, modifies it")
    print("  3. Agent A writes metadata (overwrites Agent B's changes)")
    print("  4. Agent B writes metadata (overwrites Agent A's changes)")
    print("  5. Result: Lost updates, metadata corruption, or file conflicts")
    print()
    print("Solution needed:")
    print("  • Add a global metadata lock (separate from agent locks)")
    print("  • OR use file-based locking for metadata writes")
    print("  • OR use atomic writes (write to temp file, then rename)")
    print()
    
    if locks_info:
        print("⚠️  RECOMMENDATION:")
        print("  • Multiple agents detected - they may be conflicting")
        print("  • Consider using unique agent IDs (already implemented)")
        print("  • But metadata writes still need protection")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    analyze_concurrency_issue()

