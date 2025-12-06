"""
Knowledge Graph Data Lifecycle Management

Automatic archival and cleanup to prevent unbounded growth.
Keeps knowledge graph performant as data accumulates.

Strategy:
1. Auto-archive resolved discoveries older than 30 days
2. Delete archived discoveries older than 90 days
3. Export before deletion for historical record
4. Run cleanup on server startup and periodically
"""

from datetime import datetime, timedelta
from pathlib import Path
import json
import logging
from typing import List, Dict, Any
import asyncio

logger = logging.getLogger(__name__)


class KnowledgeGraphLifecycle:
    """Manages knowledge graph data lifecycle and archival"""

    def __init__(self, graph, archive_dir: Path):
        self.graph = graph
        self.archive_dir = Path(archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        # Lifecycle thresholds (days)
        self.RESOLVED_TO_ARCHIVED_DAYS = 30  # Auto-archive resolved after 30 days
        self.ARCHIVED_TO_DELETED_DAYS = 90   # Delete archived after 90 days total

    async def run_cleanup(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Run full lifecycle cleanup cycle.

        Returns summary of what was archived/deleted.
        Set dry_run=True to see what would happen without making changes.
        """
        now = datetime.now()
        summary = {
            "timestamp": now.isoformat(),
            "dry_run": dry_run,
            "discoveries_archived": 0,
            "discoveries_deleted": 0,
            "discoveries_exported": 0,
            "errors": []
        }

        try:
            # Step 1: Auto-archive old resolved discoveries
            archived = await self._archive_old_resolved(now, dry_run)
            summary["discoveries_archived"] = len(archived)

            # Step 2: Export archived discoveries before deletion
            if not dry_run:
                exported = await self._export_archived(now)
                summary["discoveries_exported"] = len(exported)

            # Step 3: Delete very old archived discoveries
            deleted = await self._delete_old_archived(now, dry_run)
            summary["discoveries_deleted"] = len(deleted)

        except Exception as e:
            summary["errors"].append(str(e))
            logger.error(f"Cleanup error: {e}")

        return summary

    async def _archive_old_resolved(self, now: datetime, dry_run: bool) -> List[str]:
        """Archive resolved discoveries older than threshold"""
        cutoff = now - timedelta(days=self.RESOLVED_TO_ARCHIVED_DAYS)
        cutoff_iso = cutoff.isoformat()

        # Query resolved discoveries
        resolved = await self.graph.query(status="resolved", limit=1000)

        to_archive = []
        for discovery in resolved:
            # Check if resolved_at is old enough
            if discovery.resolved_at and discovery.resolved_at < cutoff_iso:
                to_archive.append(discovery.id)

        if not dry_run:
            for discovery_id in to_archive:
                await self.graph.update_discovery(discovery_id, {
                    "status": "archived",
                    "updated_at": now.isoformat()
                })

        logger.info(f"{'[DRY RUN] Would archive' if dry_run else 'Archived'} {len(to_archive)} old resolved discoveries")
        return to_archive

    async def _export_archived(self, now: datetime) -> List[str]:
        """Export archived discoveries to JSON file before deletion"""
        archived = await self.graph.query(status="archived", limit=1000)

        if not archived:
            return []

        # Create export file
        export_file = self.archive_dir / f"archived_discoveries_{now.strftime('%Y%m%d_%H%M%S')}.json"

        export_data = {
            "exported_at": now.isoformat(),
            "total_discoveries": len(archived),
            "discoveries": [d.to_dict() for d in archived]
        }

        with open(export_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2)

        logger.info(f"Exported {len(archived)} archived discoveries to {export_file}")
        return [d.id for d in archived]

    async def _delete_old_archived(self, now: datetime, dry_run: bool) -> List[str]:
        """Delete archived discoveries older than threshold"""
        cutoff = now - timedelta(days=self.ARCHIVED_TO_DELETED_DAYS)
        cutoff_iso = cutoff.isoformat()

        # Query archived discoveries
        archived = await self.graph.query(status="archived", limit=1000)

        to_delete = []
        for discovery in archived:
            # Check if updated_at (when it was archived) is old enough
            if discovery.updated_at and discovery.updated_at < cutoff_iso:
                to_delete.append(discovery.id)

        if not dry_run:
            for discovery_id in to_delete:
                await self.graph.delete_discovery(discovery_id)

        logger.info(f"{'[DRY RUN] Would delete' if dry_run else 'Deleted'} {len(to_delete)} very old archived discoveries")
        return to_delete

    async def get_lifecycle_stats(self) -> Dict[str, Any]:
        """Get statistics about discovery lifecycle"""
        now = datetime.now()

        # Get all discoveries by status
        open_count = len(await self.graph.query(status="open", limit=1000))
        resolved_count = len(await self.graph.query(status="resolved", limit=1000))
        archived_count = len(await self.graph.query(status="archived", limit=1000))

        # Count old resolved (candidates for archival)
        cutoff_resolved = (now - timedelta(days=self.RESOLVED_TO_ARCHIVED_DAYS)).isoformat()
        resolved = await self.graph.query(status="resolved", limit=1000)
        old_resolved = sum(1 for d in resolved if d.resolved_at and d.resolved_at < cutoff_resolved)

        # Count old archived (candidates for deletion)
        cutoff_archived = (now - timedelta(days=self.ARCHIVED_TO_DELETED_DAYS)).isoformat()
        archived = await self.graph.query(status="archived", limit=1000)
        old_archived = sum(1 for d in archived if d.updated_at and d.updated_at < cutoff_archived)

        return {
            "total_discoveries": open_count + resolved_count + archived_count,
            "by_status": {
                "open": open_count,
                "resolved": resolved_count,
                "archived": archived_count
            },
            "cleanup_candidates": {
                "old_resolved_ready_to_archive": old_resolved,
                "old_archived_ready_to_delete": old_archived
            },
            "thresholds_days": {
                "resolved_to_archived": self.RESOLVED_TO_ARCHIVED_DAYS,
                "archived_to_deleted": self.ARCHIVED_TO_DELETED_DAYS
            }
        }
