#!/usr/bin/env python3
"""
Archive old markdown files - Mirror of archive_old_test_agents pattern

Keeps docs/ directory lean by automatically archiving old/completed markdown files.
Mirrors the governance system's lifecycle management approach.

Usage:
    python3 scripts/archive_old_markdowns.py --dry-run    # Preview what would be archived
    python3 scripts/archive_old_markdowns.py              # Execute archival
    python3 scripts/archive_old_markdowns.py --max-age-days 90  # Custom age threshold
    python3 scripts/archive_old_markdowns.py --force     # Archive regardless of age

Thresholds:
    - Files older than max_age_days (default: 90)
    - Excludes essential docs (README.md, CHANGELOG.md, guides/*)
    - Archives to docs/archive/YYYY-MM/ by date
"""

import sys
import json
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import argparse

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Thresholds (mirror governance system)
DEFAULT_MAX_AGE_DAYS = 90

# Essential files to never archive)
ESSENTIAL_FILES = {
    'README.md',
    'CHANGELOG.md',
    'QUICK_REFERENCE.md',
    'DOC_MAP.md',
    'DOCUMENTATION_GUIDELINES.md',
    'MARKDOWN_PROLIFERATION_POLICY.md',
    'MARKDOWN_LIFECYCLE_APPROACH.md',
}

# Essential directories (keep all files)
ESSENTIAL_DIRS = {
    'guides',  # User guides - keep active
    'architecture',  # Architecture docs - keep active
}

# Archive target directories (archive these)
ARCHIVE_TARGET_DIRS = {
    'analysis',  # Analysis reports - archive when old
    'fixes',  # Fix summaries - archive when old
    'reflection',  # Reflection docs - archive when old
    'proposals',  # Proposals - archive completed ones
}


def get_file_age_days(filepath: Path) -> int:
    """Get age of file in days"""
    mtime = filepath.stat().st_mtime
    age_seconds = datetime.now().timestamp() - mtime
    return int(age_seconds / 86400)


def should_archive(filepath: Path, max_age_days: int, force: bool = False) -> tuple[bool, str]:
    """
    Determine if file should be archived.
    Returns: (should_archive, reason)
    """
    # Never archive essential files
    if filepath.name in ESSENTIAL_FILES:
        return False, "Essential file"
    
    # Never archive files in essential directories
    parent_dir = filepath.parent.name
    if parent_dir in ESSENTIAL_DIRS:
        return False, f"In essential directory: {parent_dir}"
    
    # Skip if already in archive
    if 'archive' in filepath.parts:
        return False, "Already archived"
    
    # Force mode: archive everything except essentials
    if force:
        return True, "Force mode"
    
    # Check age
    age_days = get_file_age_days(filepath)
    if age_days >= max_age_days:
        return True, f"Age: {age_days} days (threshold: {max_age_days})"
    
    # Archive target directories: archive if old OR if completed
    if parent_dir in ARCHIVE_TARGET_DIRS:
        # Check if file indicates completion
        try:
            content = filepath.read_text()
            if any(keyword in content.lower() for keyword in ['complete', 'completed', 'done', 'finished', 'resolved']):
                return True, f"Completed work in {parent_dir}"
        except:
            pass
    
    return False, "Not old enough or not archive candidate"


def archive_file(filepath: Path, archive_base: Path, dry_run: bool = False) -> dict:
    """Archive a single file to dated directory"""
    # Create archive directory structure: docs/archive/YYYY-MM/
    archive_date = datetime.fromtimestamp(filepath.stat().st_mtime)
    archive_dir = archive_base / archive_date.strftime("%Y-%m")
    
    if not dry_run:
        archive_dir.mkdir(parents=True, exist_ok=True)
    
    # Preserve relative path structure
    rel_path = filepath.relative_to(project_root / "docs")
    archive_path = archive_dir / rel_path
    
    # Create parent directories if needed
    if not dry_run:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
    
    result = {
        'source': str(filepath.relative_to(project_root)),
        'archive_path': str(archive_path.relative_to(project_root)),
        'age_days': get_file_age_days(filepath),
    }
    
    if not dry_run:
        shutil.move(str(filepath), str(archive_path))
        result['archived'] = True
    else:
        result['archived'] = False
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Archive old markdown files')
    parser.add_argument('--dry-run', action='store_true', help='Preview without archiving')
    parser.add_argument('--max-age-days', type=int, default=DEFAULT_MAX_AGE_DAYS,
                       help=f'Archive files older than this (default: {DEFAULT_MAX_AGE_DAYS})')
    parser.add_argument('--force', action='store_true',
                       help='Archive all non-essential files regardless of age')
    args = parser.parse_args()
    
    docs_dir = project_root / "docs"
    archive_base = docs_dir / "archive"
    
    # Find all markdown files
    markdown_files = list(docs_dir.rglob("*.md"))
    
    # Filter out files already in archive
    markdown_files = [f for f in markdown_files if 'archive' not in f.parts]
    
    # Classify files
    to_archive = []
    to_keep = []
    
    for filepath in markdown_files:
        should_arch, reason = should_archive(filepath, args.max_age_days, args.force)
        if should_arch:
            to_archive.append((filepath, reason))
        else:
            to_keep.append((filepath, reason))
    
    # Print summary
    print("=" * 70)
    print("MARKDOWN ARCHIVAL ANALYSIS")
    print("=" * 70)
    print(f"\nTotal markdown files: {len(markdown_files)}")
    print(f"  To archive: {len(to_archive)}")
    print(f"  To keep: {len(to_keep)}")
    print(f"  Max age threshold: {args.max_age_days} days")
    print(f"  Force mode: {args.force}")
    print(f"  Dry run: {args.dry_run}")
    
    if to_archive:
        print(f"\n{'=' * 70}")
        print("FILES TO ARCHIVE")
        print("=" * 70)
        
        # Group by reason
        by_reason = {}
        for filepath, reason in to_archive:
            if reason not in by_reason:
                by_reason[reason] = []
            by_reason[reason].append(filepath)
        
        for reason, files in sorted(by_reason.items()):
            print(f"\n{reason}: {len(files)} files")
            for filepath in files[:10]:  # Show first 10
                rel_path = filepath.relative_to(project_root)
                age = get_file_age_days(filepath)
                print(f"  - {rel_path} ({age} days old)")
            if len(files) > 10:
                print(f"  ... and {len(files) - 10} more")
        
        # Archive files
        if args.dry_run:
            print(f"\n{'=' * 70}")
            print("DRY RUN - No files will be moved")
            print("=" * 70)
        else:
            print(f"\n{'=' * 70}")
            print("ARCHIVING FILES")
            print("=" * 70)
            
            archived_results = []
            for filepath, reason in to_archive:
                try:
                    result = archive_file(filepath, archive_base, dry_run=False)
                    archived_results.append(result)
                    print(f"✅ {result['source']} → {result['archive_path']}")
                except Exception as e:
                    print(f"❌ {filepath.relative_to(project_root)}: {e}")
            
            print(f"\n✅ Archived {len(archived_results)} files")
            print(f"📁 Archive location: {archive_base}")
    else:
        print("\n✅ No files to archive")
    
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print("=" * 70)
    print(f"Active files remaining: {len(to_keep)}")
    print(f"Archived files: {len(to_archive)}")
    if not args.dry_run and to_archive:
        print(f"\n✅ Archival complete! Files moved to docs/archive/")


if __name__ == '__main__':
    main()

