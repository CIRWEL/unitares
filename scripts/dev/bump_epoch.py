#!/usr/bin/env python3
"""
Bump the governance epoch.

Run this when a model change invalidates existing stored data
(e.g., EISV coupling constants, coherence formulas, calibration logic).

Most changes (bug fixes, new tools, docs) do NOT require an epoch bump.

Usage:
    python3 scripts/bump_epoch.py --reason "changed EISV coupling model"
    python3 scripts/bump_epoch.py --reason "restructured calibration" --dry-run
"""

import argparse
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def bump_epoch(reason: str, dry_run: bool = False):
    from config.governance_config import GovernanceConfig

    current = GovernanceConfig.CURRENT_EPOCH
    new_epoch = current + 1

    print(f"Current epoch: {current}")
    print(f"New epoch:     {new_epoch}")
    print(f"Reason:        {reason}")
    print()

    if dry_run:
        print("[DRY RUN] No changes made. Remove --dry-run to apply.")
        return

    # 1. Update the config file
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "governance_config.py",
    )
    with open(config_path, "r") as f:
        content = f.read()

    old_line = f"CURRENT_EPOCH = {current}"
    new_line = f"CURRENT_EPOCH = {new_epoch}"
    if old_line not in content:
        print(f"ERROR: Could not find '{old_line}' in {config_path}")
        sys.exit(1)

    content = content.replace(old_line, new_line, 1)
    with open(config_path, "w") as f:
        f.write(content)
    print(f"[OK] Updated CURRENT_EPOCH to {new_epoch} in governance_config.py")

    # 2. Record the new epoch in the database
    from src.db import get_db
    db = get_db()
    await db.init()

    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO core.epochs (epoch, reason, started_by) VALUES ($1, $2, $3)",
            new_epoch, reason, "manual",
        )
    print(f"[OK] Recorded epoch {new_epoch} in core.epochs table")

    # 3. Reset agent baselines (they don't transfer across model changes)
    async with db.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM core.agent_baselines WHERE epoch < $1", new_epoch,
        )
        print(f"[OK] Cleared old-epoch baselines: {result}")

    # 4. Log summary
    print()
    print(f"Epoch bumped: {current} -> {new_epoch}")
    print(f"Old data (epoch {current}) remains in the database but is excluded from active queries.")
    print()
    print("Next steps:")
    print("  1. Restart the governance-mcp service")
    print("  2. All agents will start fresh in the new epoch on next check-in")

    await db.close()


def main():
    parser = argparse.ArgumentParser(description="Bump the governance epoch")
    parser.add_argument("--reason", required=True, help="Why this epoch bump is needed")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    args = parser.parse_args()

    asyncio.run(bump_epoch(args.reason, args.dry_run))


if __name__ == "__main__":
    main()
