#!/usr/bin/env python3
"""
Automatic Metadata Archival

Keeps agent_metadata.json lean by automatically archiving non-active agents.
Runs on thresholds (file size or agent count) or can be scheduled via cron.

Usage:
    python3 scripts/auto_archive_metadata.py              # Check and archive if needed
    python3 scripts/auto_archive_metadata.py --force      # Archive regardless of thresholds
    python3 scripts/auto_archive_metadata.py --dry-run    # Show what would be archived
    python3 scripts/auto_archive_metadata.py --check      # Just check status, don't archive

Thresholds:
    - File size > 50KB
    - Active agents > 40
    - Non-active agents > 20

Add to cron for automatic maintenance:
    0 2 * * 0 python3 /path/to/scripts/auto_archive_metadata.py  # Weekly Sunday 2am
"""

import json
import sys
from pathlib import Path
from datetime import datetime
import argparse


# Thresholds
MAX_FILE_SIZE_KB = 50
MAX_TOTAL_AGENTS = 40
MAX_NON_ACTIVE = 20

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
METADATA_FILE = DATA_DIR / "agent_metadata.json"
ARCHIVE_DIR = DATA_DIR / "archive"
BACKUP_DIR = DATA_DIR / "backups"
AUDIT_LOG = DATA_DIR / "audit_log.jsonl"


def load_metadata():
    """Load agent metadata"""
    if not METADATA_FILE.exists():
        return {}
    with open(METADATA_FILE) as f:
        return json.load(f)


def save_metadata(metadata):
    """Save agent metadata"""
    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)


def check_thresholds(metadata):
    """Check if archival is needed"""
    file_size_kb = METADATA_FILE.stat().st_size / 1024
    total_agents = len(metadata)

    active = {k: v for k, v in metadata.items() if v.get('status') == 'active'}
    non_active = {k: v for k, v in metadata.items() if v.get('status') != 'active'}

    reasons = []

    if file_size_kb > MAX_FILE_SIZE_KB:
        reasons.append(f"File size ({file_size_kb:.1f} KB > {MAX_FILE_SIZE_KB} KB)")

    if total_agents > MAX_TOTAL_AGENTS:
        reasons.append(f"Total agents ({total_agents} > {MAX_TOTAL_AGENTS})")

    if len(non_active) > MAX_NON_ACTIVE:
        reasons.append(f"Non-active agents ({len(non_active)} > {MAX_NON_ACTIVE})")

    return {
        'needed': len(reasons) > 0,
        'reasons': reasons,
        'file_size_kb': file_size_kb,
        'total_agents': total_agents,
        'active_count': len(active),
        'non_active_count': len(non_active)
    }


def archive_non_active(metadata, dry_run=False):
    """Archive non-active agents"""

    # Split into active and non-active
    active = {k: v for k, v in metadata.items() if v.get('status') == 'active'}
    non_active = {k: v for k, v in metadata.items() if v.get('status') != 'active'}

    if not non_active:
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create archive data
    archive_data = {
        "_archive_info": {
            "created_at": datetime.now().isoformat(),
            "reason": "Automatic archival - threshold exceeded",
            "original_file_size_kb": METADATA_FILE.stat().st_size / 1024,
            "agents_archived": len(non_active),
            "statuses": {}
        },
        "agents": non_active
    }

    # Count by status
    for data in non_active.values():
        status = data.get('status', 'unknown')
        archive_data["_archive_info"]["statuses"][status] = \
            archive_data["_archive_info"]["statuses"].get(status, 0) + 1

    if dry_run:
        return {
            'archive_file': f"agent_metadata_archive_{timestamp}.json",
            'agents_archived': len(non_active),
            'statuses': archive_data["_archive_info"]["statuses"],
            'active_remaining': len(active)
        }

    # Create directories
    ARCHIVE_DIR.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(exist_ok=True)

    # Backup current metadata first
    backup_file = BACKUP_DIR / f"agent_metadata_pre_archive_{timestamp}.json"
    with open(backup_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    # Save archive
    archive_file = ARCHIVE_DIR / f"agent_metadata_archive_{timestamp}.json"
    with open(archive_file, 'w') as f:
        json.dump(archive_data, f, indent=2)

    # Update main metadata to active-only
    save_metadata(active)

    # Log to audit
    audit_entry = {
        "timestamp": datetime.now().isoformat(),
        "operation": "auto_archive_metadata",
        "trigger": "threshold_exceeded",
        "actions": [
            {
                "action": "backup_created",
                "file": backup_file.name,
                "agents_backed_up": len(metadata)
            },
            {
                "action": "agents_archived",
                "file": archive_file.name,
                "agents_archived": len(non_active),
                "by_status": archive_data["_archive_info"]["statuses"]
            },
            {
                "action": "main_metadata_updated",
                "before": {"agents": len(metadata), "size_kb": archive_data["_archive_info"]["original_file_size_kb"]},
                "after": {"agents": len(active), "size_kb": METADATA_FILE.stat().st_size / 1024}
            }
        ],
        "result": "success"
    }

    with open(AUDIT_LOG, 'a') as f:
        f.write(json.dumps(audit_entry) + '\n')

    return {
        'archive_file': archive_file.name,
        'backup_file': backup_file.name,
        'agents_archived': len(non_active),
        'statuses': archive_data["_archive_info"]["statuses"],
        'active_remaining': len(active),
        'size_reduction_kb': archive_data["_archive_info"]["original_file_size_kb"] - METADATA_FILE.stat().st_size / 1024
    }


def main():
    parser = argparse.ArgumentParser(description="Automatic metadata archival")
    parser.add_argument('--force', action='store_true', help='Archive regardless of thresholds')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be archived without doing it')
    parser.add_argument('--check', action='store_true', help='Check status only, no archival')

    args = parser.parse_args()

    # Load metadata
    metadata = load_metadata()
    if not metadata:
        print("No metadata found")
        return 0

    # Check thresholds
    status = check_thresholds(metadata)

    print(f"Metadata status:")
    print(f"  File size: {status['file_size_kb']:.1f} KB (threshold: {MAX_FILE_SIZE_KB} KB)")
    print(f"  Total agents: {status['total_agents']} (threshold: {MAX_TOTAL_AGENTS})")
    print(f"  Active: {status['active_count']}")
    print(f"  Non-active: {status['non_active_count']} (threshold: {MAX_NON_ACTIVE})")
    print()

    if args.check:
        if status['needed']:
            print("⚠️  Archival recommended:")
            for reason in status['reasons']:
                print(f"  - {reason}")
        else:
            print("✓ No archival needed")
        return 0

    # Determine if we should archive
    should_archive = args.force or status['needed']

    if not should_archive:
        print("✓ No archival needed")
        return 0

    if status['needed']:
        print("Archival needed:")
        for reason in status['reasons']:
            print(f"  - {reason}")
        print()
    elif args.force:
        print("Force archival requested")
        print()

    # Archive
    result = archive_non_active(metadata, dry_run=args.dry_run)

    if not result:
        print("No non-active agents to archive")
        return 0

    if args.dry_run:
        print("Dry run - would archive:")
        print(f"  Archive file: {result['archive_file']}")
        print(f"  Agents to archive: {result['agents_archived']}")
        print(f"  By status:")
        for status, count in sorted(result['statuses'].items()):
            print(f"    {status}: {count}")
        print(f"  Active remaining: {result['active_remaining']}")
    else:
        print("✓ Archival complete:")
        print(f"  Archive: {result['archive_file']}")
        print(f"  Backup: {result['backup_file']}")
        print(f"  Archived: {result['agents_archived']} agents")
        print(f"  By status:")
        for status, count in sorted(result['statuses'].items()):
            print(f"    {status}: {count}")
        print(f"  Active remaining: {result['active_remaining']}")
        print(f"  Size reduction: {result['size_reduction_kb']:.1f} KB")
        print()
        print(f"Logged to {AUDIT_LOG.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
