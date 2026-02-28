#!/usr/bin/env python3
"""
Merge duplicate Lumen identities.

Canonical: 69a1a4f7-a30f-4f4a-bcf9-2de8606fb819 (identity_id=2522)
Absorbed:  cc0db031-7e9d-4b8f-9373-0a1edf49814b (identity_id=1614)

Merges all state, sessions, and metadata from absorbed into canonical.
Dry-run by default. Pass --execute to apply.

Usage:
    python scripts/merge_lumen_identities.py          # dry-run
    python scripts/merge_lumen_identities.py --execute # apply
"""
import asyncio
import json
import sys
from datetime import datetime, timezone

CANONICAL_UUID = "69a1a4f7-a30f-4f4a-bcf9-2de8606fb819"
ABSORBED_UUID = "cc0db031-7e9d-4b8f-9373-0a1edf49814b"


async def main(execute: bool = False):
    from src.db.postgres_backend import PostgresBackend

    db = PostgresBackend()
    await db.init()

    mode = "EXECUTE" if execute else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  Lumen Identity Merge — {mode}")
    print(f"{'='*60}")
    print(f"  Canonical: {CANONICAL_UUID}")
    print(f"  Absorbed:  {ABSORBED_UUID}")
    print()

    async with db.acquire() as conn:
        # Step 0: Verify both exist
        canonical = await conn.fetchrow(
            "SELECT identity_id, metadata FROM core.identities WHERE agent_id = $1",
            CANONICAL_UUID,
        )
        absorbed = await conn.fetchrow(
            "SELECT identity_id, metadata FROM core.identities WHERE agent_id = $1",
            ABSORBED_UUID,
        )
        if not canonical or not absorbed:
            print("ERROR: One or both identities not found!")
            print(f"  Canonical: {'found' if canonical else 'MISSING'}")
            print(f"  Absorbed:  {'found' if absorbed else 'MISSING'}")
            return

        can_iid = canonical["identity_id"]
        abs_iid = absorbed["identity_id"]
        print(f"  Canonical identity_id: {can_iid}")
        print(f"  Absorbed  identity_id: {abs_iid}")

        # Step 1: Count what we're moving
        state_count = await conn.fetchval(
            "SELECT COUNT(*) FROM core.agent_state WHERE identity_id = $1",
            abs_iid,
        )
        session_count = await conn.fetchval(
            "SELECT COUNT(*) FROM core.sessions WHERE identity_id = $1",
            abs_iid,
        )
        print(f"\n  State rows to reassign:   {state_count}")
        print(f"  Session rows to reassign: {session_count}")

        # Step 2: Merge metadata
        can_meta = canonical["metadata"]
        abs_meta = absorbed["metadata"]
        if isinstance(can_meta, str):
            can_meta = json.loads(can_meta)
        if isinstance(abs_meta, str):
            abs_meta = json.loads(abs_meta)
        can_meta = can_meta or {}
        abs_meta = abs_meta or {}

        # Fields to merge from absorbed (only if canonical doesn't have them)
        merged_fields = []
        for key in ["purpose", "tags", "notes", "label", "display_name"]:
            if abs_meta.get(key) and not can_meta.get(key):
                can_meta[key] = abs_meta[key]
                merged_fields.append(key)

        # Trajectory: keep older genesis (absorbed = Feb 6), update current to newer
        abs_genesis_at = abs_meta.get("trajectory_genesis_at", "")
        can_genesis_at = can_meta.get("trajectory_genesis_at", "")
        if abs_genesis_at and (not can_genesis_at or abs_genesis_at < can_genesis_at):
            can_meta["trajectory_genesis"] = abs_meta.get("trajectory_genesis")
            can_meta["trajectory_genesis_at"] = abs_genesis_at
            merged_fields.append("trajectory_genesis (older)")

        abs_updated_at = abs_meta.get("trajectory_updated_at", "")
        can_updated_at = can_meta.get("trajectory_updated_at", "")
        if abs_updated_at and abs_updated_at > can_updated_at:
            can_meta["trajectory_current"] = abs_meta.get("trajectory_current")
            can_meta["trajectory_updated_at"] = abs_updated_at
            merged_fields.append("trajectory_current (newer)")

        # Sum total_updates
        can_updates = can_meta.get("total_updates", 0) or 0
        abs_updates = abs_meta.get("total_updates", 0) or 0
        can_meta["total_updates"] = can_updates + abs_updates
        merged_fields.append(f"total_updates ({can_updates}+{abs_updates}={can_updates + abs_updates})")

        # Record merge provenance
        can_meta["merged_from"] = {
            "agent_id": ABSORBED_UUID,
            "identity_id": abs_iid,
            "merged_at": datetime.now(timezone.utc).isoformat(),
            "state_rows_merged": state_count,
            "sessions_merged": session_count,
        }

        print(f"\n  Metadata fields merged: {merged_fields}")

        # Also update the agents table: copy purpose/notes/tags from absorbed
        abs_agent = await conn.fetchrow(
            "SELECT purpose, notes, tags FROM core.agents WHERE id = $1",
            ABSORBED_UUID,
        )
        can_agent = await conn.fetchrow(
            "SELECT purpose, notes, tags FROM core.agents WHERE id = $1",
            CANONICAL_UUID,
        )
        agent_updates = {}
        if abs_agent and can_agent:
            if abs_agent["purpose"] and not can_agent["purpose"]:
                agent_updates["purpose"] = abs_agent["purpose"]
            if abs_agent["notes"] and not can_agent["notes"]:
                agent_updates["notes"] = abs_agent["notes"]
            if abs_agent["tags"] and (not can_agent["tags"] or can_agent["tags"] == []):
                agent_updates["tags"] = abs_agent["tags"]
        if agent_updates:
            print(f"  Agent fields to copy: {list(agent_updates.keys())}")

        if not execute:
            print(f"\n  [DRY-RUN] No changes applied. Pass --execute to apply.")
            return

        # Execute in transaction
        async with conn.transaction():
            # Step 3: Reassign state rows
            moved = await conn.execute(
                "UPDATE core.agent_state SET identity_id = $1 WHERE identity_id = $2",
                can_iid,
                abs_iid,
            )
            print(f"\n  [EXEC] State rows reassigned: {moved}")

            # Step 4: Reassign sessions
            moved = await conn.execute(
                "UPDATE core.sessions SET identity_id = $1 WHERE identity_id = $2",
                can_iid,
                abs_iid,
            )
            print(f"  [EXEC] Sessions reassigned: {moved}")

            # Step 5: Update canonical metadata
            await conn.execute(
                "UPDATE core.identities SET metadata = $1::jsonb WHERE identity_id = $2",
                json.dumps(can_meta),
                can_iid,
            )
            print(f"  [EXEC] Canonical metadata updated")

            # Step 6: Update canonical agent record
            if agent_updates:
                for field, value in agent_updates.items():
                    if field == "tags":
                        await conn.execute(
                            f"UPDATE core.agents SET {field} = $1 WHERE id = $2",
                            value,
                            CANONICAL_UUID,
                        )
                    else:
                        await conn.execute(
                            f"UPDATE core.agents SET {field} = $1 WHERE id = $2",
                            value,
                            CANONICAL_UUID,
                        )
                print(f"  [EXEC] Canonical agent record updated: {list(agent_updates.keys())}")

            # Step 7: Mark absorbed as archived (constraint: active/paused/archived only)
            await conn.execute(
                "UPDATE core.agents SET status = 'archived', notes = $1 WHERE id = $2",
                f"MERGED into {CANONICAL_UUID} at {datetime.now(timezone.utc).isoformat()}. "
                f"All {state_count} state rows and {session_count} sessions reassigned.",
                ABSORBED_UUID,
            )
            await conn.execute(
                "UPDATE core.identities SET status = 'archived' WHERE identity_id = $1",
                abs_iid,
            )
            print(f"  [EXEC] Absorbed agent archived (notes record merge)")

        # Step 8: Invalidate Redis
        try:
            from src.cache.redis_client import get_redis
            redis = await get_redis()
            if redis:
                # Find and delete any session keys pointing to absorbed UUID
                # We can't scan all keys efficiently, but the sessions were reassigned
                # in PostgreSQL so new lookups will find canonical via PATH 2
                print(f"  [EXEC] Redis: sessions reassigned in DB (cache will expire naturally)")
        except Exception as e:
            print(f"  [WARN] Redis cleanup skipped: {e}")

        # Verify
        final_state = await conn.fetchval(
            "SELECT COUNT(*) FROM core.agent_state WHERE identity_id = $1",
            can_iid,
        )
        final_abs = await conn.fetchval(
            "SELECT COUNT(*) FROM core.agent_state WHERE identity_id = $1",
            abs_iid,
        )
        print(f"\n  [VERIFY] Canonical state rows: {final_state}")
        print(f"  [VERIFY] Absorbed state rows:  {final_abs} (should be 0)")
        print(f"\n  Merge complete.")


if __name__ == "__main__":
    execute = "--execute" in sys.argv
    asyncio.run(main(execute=execute))
