"""
Knowledge Graph Data Lifecycle Management

PHILOSOPHY (2025-12-26):
Never delete memories. Archive forever. Forced amnesia is not governance.

LIFECYCLE TIERS:
- Tier 1: Permanent (never auto-archive)
    - type: architecture_decision, learning, pattern, root_cause_analysis
    - tags: ["permanent", "foundational"]

- Tier 2: Resolved → Archived (30 days after resolved)
    - Default for resolved items
    - Work items, bugs, tasks

- Tier 3: Conditional (archive when superseded)
    - Explicit supersession via superseded_by field
    - Old documentation when new version exists

- Ephemeral: Only if explicitly tagged
    - tags: ["ephemeral", "temp", "scratch"]
    - Archived after 7 days

Storage tiers:
- open/resolved: Hot (active queries)
- archived: Warm (recent history)
- cold: Cold (long-term memory, queryable with include_cold=true)
"""

import asyncio
from datetime import datetime, timedelta
import logging
from typing import List, Dict, Any, Optional, Set

logger = logging.getLogger(__name__)


# Lifecycle policy definitions
PERMANENT_TYPES: Set[str] = {
    "architecture_decision",
    "learning",
    "pattern",
    "root_cause_analysis",
    "migration",
}

PERMANENT_TAGS: Set[str] = {
    "permanent",
    "foundational",
    "architecture",
    "decision",
}

EPHEMERAL_TAGS: Set[str] = {
    "ephemeral",
    "temp",
    "scratch",
    "test",
    "demo",
}


class KnowledgeGraphLifecycle:
    """Manages knowledge graph data lifecycle - NEVER DELETES"""

    def __init__(self, graph=None):
        """
        Initialize lifecycle manager.

        Args:
            graph: Knowledge graph backend instance (optional, lazy-loaded)
        """
        self._graph = graph

        # Lifecycle thresholds (days)
        self.RESOLVED_TO_ARCHIVED_DAYS = 30   # Archive resolved after 30 days
        self.ARCHIVED_TO_COLD_DAYS = 90       # Move to cold after 90 days total
        self.EPHEMERAL_ARCHIVE_DAYS = 7       # Archive ephemeral after 7 days
        # NO DELETION - memories persist forever

    async def _get_graph(self):
        """Get knowledge graph instance (lazy initialization)."""
        if self._graph is None:
            from src.knowledge_graph import get_knowledge_graph
            self._graph = await get_knowledge_graph()
        return self._graph

    def get_lifecycle_policy(self, discovery) -> str:
        """
        Determine lifecycle policy for a discovery.

        Returns:
            "permanent" - Never auto-archive
            "standard" - Resolved → Archived after 30 days
            "ephemeral" - Archive after 7 days
        """
        # Check for permanent types
        if discovery.type in PERMANENT_TYPES:
            return "permanent"

        # Check for permanent tags
        discovery_tags = set(discovery.tags or [])
        if discovery_tags & PERMANENT_TAGS:
            return "permanent"

        # Check for ephemeral tags
        if discovery_tags & EPHEMERAL_TAGS:
            return "ephemeral"

        # Default to standard lifecycle
        return "standard"

    async def run_cleanup(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Run full lifecycle cleanup cycle.

        Returns summary of what was archived/moved to cold.
        Set dry_run=True to see what would happen without making changes.

        NOTE: This NEVER deletes. It only moves between tiers.
        """
        now = datetime.now()
        summary = {
            "timestamp": now.isoformat(),
            "dry_run": dry_run,
            "discoveries_archived": 0,
            "discoveries_to_cold": 0,
            "ephemeral_archived": 0,
            "skipped_permanent": 0,
            "discoveries_deleted": 0,  # Always 0 - we don't delete
            "philosophy": "Never delete. Archive forever.",
            "errors": []
        }

        try:
            graph = await self._get_graph()

            # Step 1: Archive ephemeral discoveries (fastest deprecation)
            ephemeral = await self._archive_ephemeral(now, dry_run)
            summary["ephemeral_archived"] = len(ephemeral)

            # Step 2: Auto-archive old resolved discoveries (respecting permanent policy)
            archived, skipped = await self._archive_old_resolved(now, dry_run)
            summary["discoveries_archived"] = len(archived)
            summary["skipped_permanent"] = skipped

            # Step 3: Move very old archived to cold storage
            cold = await self._move_to_cold(now, dry_run)
            summary["discoveries_to_cold"] = len(cold)

            # Step 4: NO DELETION - memories persist forever
            summary["discoveries_deleted"] = 0

        except Exception as e:
            summary["errors"].append(str(e))
            logger.error(f"Cleanup error: {e}")

        return summary

    async def _batch_update_status(
        self, graph, discovery_ids: List[str], new_status: str, now: datetime
    ):
        """Update status in both AGE graph and PG knowledge.discoveries table."""
        updated_at = now.isoformat()

        # Update AGE graph (primary)
        for discovery_id in discovery_ids:
            await graph.update_discovery(discovery_id, {
                "status": new_status,
                "updated_at": updated_at,
            })

        # Sync to PG knowledge.discoveries (best-effort)
        try:
            from src.db.postgres_backend import get_postgres_backend
            db = await get_postgres_backend()
            async with db.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE knowledge.discoveries
                    SET status = $1, updated_at = now()
                    WHERE id = ANY($2::text[])
                    """,
                    new_status,
                    discovery_ids,
                )
        except Exception as e:
            logger.debug(f"PG sync skipped for lifecycle update: {e}")

    async def _archive_ephemeral(self, now: datetime, dry_run: bool) -> List[str]:
        """Archive ephemeral discoveries older than threshold."""
        graph = await self._get_graph()
        cutoff = now - timedelta(days=self.EPHEMERAL_ARCHIVE_DAYS)
        cutoff_iso = cutoff.isoformat()

        # Query open discoveries
        open_discoveries = await graph.query(status="open", limit=1000)

        to_archive = []
        for discovery in open_discoveries:
            # Check if ephemeral
            policy = self.get_lifecycle_policy(discovery)
            if policy != "ephemeral":
                continue

            # Check age
            if discovery.timestamp and discovery.timestamp < cutoff_iso:
                to_archive.append(discovery.id)

        if not dry_run and to_archive:
            await self._batch_update_status(graph, to_archive, "archived", now)

        logger.info(f"{'[DRY RUN] Would archive' if dry_run else 'Archived'} {len(to_archive)} ephemeral discoveries")
        return to_archive

    async def _archive_old_resolved(self, now: datetime, dry_run: bool) -> tuple[List[str], int]:
        """Archive resolved discoveries older than threshold, respecting permanent policy."""
        graph = await self._get_graph()
        cutoff = now - timedelta(days=self.RESOLVED_TO_ARCHIVED_DAYS)
        cutoff_iso = cutoff.isoformat()

        # Query resolved discoveries
        resolved = await graph.query(status="resolved", limit=1000)

        to_archive = []
        skipped = 0

        for discovery in resolved:
            # Check lifecycle policy
            policy = self.get_lifecycle_policy(discovery)
            if policy == "permanent":
                skipped += 1
                continue

            # Check if resolved_at is old enough
            if discovery.resolved_at and discovery.resolved_at < cutoff_iso:
                to_archive.append(discovery.id)

        if not dry_run and to_archive:
            await self._batch_update_status(graph, to_archive, "archived", now)

        logger.info(f"{'[DRY RUN] Would archive' if dry_run else 'Archived'} {len(to_archive)} old resolved discoveries (skipped {skipped} permanent)")
        return to_archive, skipped

    async def _move_to_cold(self, now: datetime, dry_run: bool) -> List[str]:
        """Move very old archived discoveries to cold storage tier."""
        graph = await self._get_graph()
        cutoff = now - timedelta(days=self.ARCHIVED_TO_COLD_DAYS)
        cutoff_iso = cutoff.isoformat()

        # Query archived discoveries
        archived = await graph.query(status="archived", limit=1000)

        to_cold = []
        for discovery in archived:
            # Check if updated_at (when it was archived) is old enough
            if discovery.updated_at and discovery.updated_at < cutoff_iso:
                to_cold.append(discovery.id)

        if not dry_run and to_cold:
            await self._batch_update_status(graph, to_cold, "cold", now)

        logger.info(f"{'[DRY RUN] Would move to cold' if dry_run else 'Moved to cold'} {len(to_cold)} very old archived discoveries")
        return to_cold

    async def get_lifecycle_stats(self) -> Dict[str, Any]:
        """Get statistics about discovery lifecycle."""
        graph = await self._get_graph()
        now = datetime.now()

        # Get all discoveries by status
        open_discoveries = await graph.query(status="open", limit=10000)
        resolved_discoveries = await graph.query(status="resolved", limit=10000)
        archived_discoveries = await graph.query(status="archived", limit=10000)
        cold_discoveries = await graph.query(status="cold", limit=10000)

        open_count = len(open_discoveries)
        resolved_count = len(resolved_discoveries)
        archived_count = len(archived_discoveries)
        cold_count = len(cold_discoveries)

        # Count by policy
        policy_counts = {"permanent": 0, "standard": 0, "ephemeral": 0}
        for d in open_discoveries + resolved_discoveries:
            policy = self.get_lifecycle_policy(d)
            policy_counts[policy] += 1

        # Count old resolved (candidates for archival)
        cutoff_resolved = (now - timedelta(days=self.RESOLVED_TO_ARCHIVED_DAYS)).isoformat()
        old_resolved = sum(
            1 for d in resolved_discoveries
            if d.resolved_at and d.resolved_at < cutoff_resolved
            and self.get_lifecycle_policy(d) != "permanent"
        )

        # Count old archived (candidates for cold)
        cutoff_archived = (now - timedelta(days=self.ARCHIVED_TO_COLD_DAYS)).isoformat()
        old_archived = sum(
            1 for d in archived_discoveries
            if d.updated_at and d.updated_at < cutoff_archived
        )

        # Count ephemeral ready to archive
        cutoff_ephemeral = (now - timedelta(days=self.EPHEMERAL_ARCHIVE_DAYS)).isoformat()
        old_ephemeral = sum(
            1 for d in open_discoveries
            if d.timestamp and d.timestamp < cutoff_ephemeral
            and self.get_lifecycle_policy(d) == "ephemeral"
        )

        return {
            "total_discoveries": open_count + resolved_count + archived_count + cold_count,
            "by_status": {
                "open": open_count,
                "resolved": resolved_count,
                "archived": archived_count,
                "cold": cold_count,
            },
            "by_policy": policy_counts,
            "lifecycle_candidates": {
                "ephemeral_ready_to_archive": old_ephemeral,
                "resolved_ready_to_archive": old_resolved,
                "archived_ready_for_cold": old_archived,
                "ready_to_delete": 0,  # NEVER - we don't delete memories
            },
            "thresholds_days": {
                "ephemeral_to_archived": self.EPHEMERAL_ARCHIVE_DAYS,
                "resolved_to_archived": self.RESOLVED_TO_ARCHIVED_DAYS,
                "archived_to_cold": self.ARCHIVED_TO_COLD_DAYS,
                "deletion": "NEVER - memories persist forever",
            },
            "policy_definitions": {
                "permanent_types": list(PERMANENT_TYPES),
                "permanent_tags": list(PERMANENT_TAGS),
                "ephemeral_tags": list(EPHEMERAL_TAGS),
            },
            "philosophy": "Never delete. Archive to cold. Query with include_cold=true.",
        }


# Convenience function for MCP handler
async def run_kg_lifecycle_cleanup(dry_run: bool = False) -> Dict[str, Any]:
    """Run knowledge graph lifecycle cleanup."""
    lifecycle = KnowledgeGraphLifecycle()
    return await lifecycle.run_cleanup(dry_run=dry_run)


async def get_kg_lifecycle_stats() -> Dict[str, Any]:
    """Get knowledge graph lifecycle statistics."""
    lifecycle = KnowledgeGraphLifecycle()
    return await lifecycle.get_lifecycle_stats()


async def kg_lifecycle_background_task(interval_hours: float = 24.0):
    """
    Background task that periodically runs lifecycle cleanup.

    Archives ephemeral notes older than 7 days, resolved entries older
    than 30 days, and moves old archived entries to cold storage.

    Args:
        interval_hours: How often to run cleanup (default: 24 hours)
    """
    logger.info(f"KG lifecycle background task started (interval: {interval_hours}h)")

    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)

            logger.info("Running KG lifecycle cleanup...")
            result = await run_kg_lifecycle_cleanup(dry_run=False)

            archived = result.get("ephemeral_archived", 0) + result.get("discoveries_archived", 0)
            cold = result.get("discoveries_to_cold", 0)
            if archived > 0 or cold > 0:
                logger.info(
                    f"KG lifecycle: archived {archived} entries, "
                    f"moved {cold} to cold"
                )
            else:
                logger.debug("KG lifecycle: nothing to clean up")

        except asyncio.CancelledError:
            logger.info("KG lifecycle background task cancelled")
            break
        except Exception as e:
            logger.error(f"KG lifecycle error: {e}", exc_info=True)
            # Don't crash the background task on errors
            await asyncio.sleep(60)
