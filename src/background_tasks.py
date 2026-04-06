"""
Background tasks for the governance MCP server.

Extracted from mcp_server.py to reduce file size and improve maintainability.
Each task runs as an asyncio coroutine, started during server initialization.
"""

import asyncio
import gzip
import os
import shutil
from datetime import datetime
from pathlib import Path

from src.logging_utils import get_logger
from src.connection_tracker import CONNECTIONS_ACTIVE

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Connection heartbeat
# ---------------------------------------------------------------------------

async def connection_heartbeat_task(connection_tracker):
    """
    Comprehensive connection health monitoring:
    - Clean up stale connections every 5 minutes
    - Check health of all connections every 2 minutes
    - Log diagnostic summary every 10 minutes
    """
    consecutive_failures = 0
    max_consecutive_failures = 5
    iteration = 0

    while True:
        try:
            await asyncio.sleep(60)
            iteration += 1

            if iteration % 2 == 0:
                for client_id in list(connection_tracker.connections.keys()):
                    try:
                        health = await connection_tracker.check_health(client_id)
                        if not health.get("healthy"):
                            logger.warning(
                                f"[HEARTBEAT] Unhealthy connection: {client_id} - {health.get('issues', [])}"
                            )
                    except Exception as e:
                        logger.debug(f"[HEARTBEAT] Health check failed for {client_id}: {e}")

            if iteration % 5 == 0:
                await connection_tracker.cleanup_stale_connections(max_idle_minutes=30.0)

            if iteration % 10 == 0:
                diagnostics = await connection_tracker.get_diagnostics()
                health_summary = diagnostics.get("health_summary", {})
                reconnect_summary = diagnostics.get("reconnection_summary", {})

                logger.info(
                    f"[HEARTBEAT] Connection summary: "
                    f"{diagnostics['total_connections']} connected, "
                    f"{health_summary.get('healthy', 0)} healthy, "
                    f"{health_summary.get('degraded', 0)} degraded"
                )

                high_reconnectors = {k: v for k, v in reconnect_summary.items() if v > 5}
                if high_reconnectors:
                    logger.warning(
                        f"[HEARTBEAT] High reconnection clients: {high_reconnectors}. "
                        f"Check network stability."
                    )

                CONNECTIONS_ACTIVE.set(diagnostics['total_connections'])

            consecutive_failures = 0

        except asyncio.CancelledError:
            logger.info("[HEARTBEAT] Connection heartbeat task cancelled")
            break
        except Exception as e:
            consecutive_failures += 1
            logger.warning(
                f"[HEARTBEAT] Error (failure {consecutive_failures}/{max_consecutive_failures}): {e}",
                exc_info=True
            )
            if consecutive_failures >= max_consecutive_failures:
                logger.error(
                    f"[HEARTBEAT] Failed {consecutive_failures} times consecutively. "
                    f"Connection monitoring degraded. Consider restarting the server."
                )
                consecutive_failures = 0


# ---------------------------------------------------------------------------
# Auto calibration / ground truth
# ---------------------------------------------------------------------------

async def startup_auto_calibration():
    """Start automatic ground truth collection at startup and periodically."""
    await asyncio.sleep(1.0)

    # Load calibration from DB now that the event loop is running.
    # sync load_state() at __init__ time can only read JSON; this gets the DB state.
    try:
        from src.calibration import get_calibration_checker
        await get_calibration_checker().load_state_async()
        logger.info("[CALIBRATION] Loaded calibration state from DB")
    except Exception as e:
        logger.warning(f"[CALIBRATION] Async calibration load failed (JSON fallback used): {e}")

    try:
        from src.auto_ground_truth import collect_ground_truth_automatically, auto_ground_truth_collector_task

        result = await collect_ground_truth_automatically(
            min_age_hours=2.0, max_decisions=50, dry_run=False
        )
        if result.get('updated', 0) > 0:
            logger.info(f"Auto-collected ground truth: {result['updated']} decisions updated")

        asyncio.create_task(auto_ground_truth_collector_task(interval_hours=6.0))
        logger.info("Started periodic auto ground truth collector (runs every 6 hours)")
    except Exception as e:
        logger.warning(f"Could not start auto ground truth collector: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# KG lifecycle cleanup
# ---------------------------------------------------------------------------

async def startup_kg_lifecycle():
    """Start periodic KG lifecycle cleanup after server init."""
    await asyncio.sleep(5.0)
    try:
        from src.knowledge_graph_lifecycle import kg_lifecycle_background_task, run_kg_lifecycle_cleanup

        result = await run_kg_lifecycle_cleanup(dry_run=False)
        archived = result.get("ephemeral_archived", 0) + result.get("discoveries_archived", 0)
        if archived > 0:
            logger.info(f"KG lifecycle startup: archived {archived} entries")

        asyncio.create_task(kg_lifecycle_background_task(interval_hours=24.0))
        logger.info("Started periodic KG lifecycle cleanup (runs every 24 hours)")
    except Exception as e:
        logger.warning(f"Could not start KG lifecycle task: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Concept extraction
# ---------------------------------------------------------------------------

async def concept_extraction_background_task(interval_hours: float = 24.0):
    """Daily concept extraction from tags + embeddings."""
    await asyncio.sleep(300)  # 5 min startup delay
    while True:
        try:
            from src.concept_extraction import ConceptExtractor
            extractor = ConceptExtractor()
            result = await extractor.run()
            logger.info(f"[CONCEPT_EXTRACTION] {result}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"[CONCEPT_EXTRACTION] Skipped: {e}")
        await asyncio.sleep(interval_hours * 3600)


# ---------------------------------------------------------------------------
# Materialized view refresh (moved from per-insert to periodic)
# ---------------------------------------------------------------------------

async def periodic_matview_refresh():
    """Refresh mv_latest_agent_states periodically instead of per-insert."""
    await asyncio.sleep(30.0)
    while True:
        try:
            from src.db import get_db
            db = get_db()
            async with db.acquire() as conn:
                await conn.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY core.mv_latest_agent_states"
                )
        except Exception as e:
            logger.debug(f"Matview refresh skipped: {e}")
        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Partition maintenance
# ---------------------------------------------------------------------------

async def periodic_partition_maintenance():
    """Run audit.partition_maintenance() weekly to create/drop partitions."""
    await asyncio.sleep(60.0)
    while True:
        try:
            from src.db import get_db
            db = get_db()
            async with db.acquire() as conn:
                result = await conn.fetchval("SELECT audit.partition_maintenance()")
            logger.info(f"Partition maintenance completed: {result}")
        except Exception as e:
            logger.debug(f"Partition maintenance skipped: {e}")
        await asyncio.sleep(7 * 24 * 3600)


# ---------------------------------------------------------------------------
# Metadata loading
# ---------------------------------------------------------------------------

async def background_metadata_load():
    """Load metadata in background after server starts accepting connections."""
    await asyncio.sleep(0.5)
    try:
        from src.agent_state import load_metadata_async
        await load_metadata_async()
        logger.info("[STARTUP] Background metadata load complete")
    except Exception as e:
        logger.warning(f"[STARTUP] Background metadata load failed: {e}. Lazy loading will handle on first access.")


# ---------------------------------------------------------------------------
# Orphan agent cleanup
# ---------------------------------------------------------------------------

async def periodic_orphan_cleanup(interval_hours: float = 2.0):
    """Periodically archive orphan and ephemeral agents to prevent proliferation."""
    await asyncio.sleep(2.0)

    while True:
        try:
            from src.agent_lifecycle import auto_archive_orphan_agents

            archived = await auto_archive_orphan_agents(
                zero_update_hours=4.0,
                low_update_hours=12.0,
                unlabeled_hours=24.0,
                ephemeral_hours=6.0,
                ephemeral_max_updates=5,
            )
            if archived > 0:
                logger.info(f"[ORPHAN_CLEANUP] Archived {archived} orphan/ephemeral agents")
        except Exception as e:
            logger.warning(f"[ORPHAN_CLEANUP] Error: {e}", exc_info=True)

        await asyncio.sleep(interval_hours * 3600)


# ---------------------------------------------------------------------------
# Stuck agent recovery
# ---------------------------------------------------------------------------

async def stuck_agent_recovery_task():
    """Automatically detect and recover stuck agents every 5 minutes."""
    await asyncio.sleep(10.0)

    interval_minutes = 5.0
    interval_seconds = interval_minutes * 60

    logger.info(f"[STUCK_AGENT_RECOVERY] Starting automatic recovery (runs every {interval_minutes} minutes)")

    while True:
        try:
            await asyncio.sleep(interval_seconds)

            from src.mcp_handlers.lifecycle.handlers import handle_detect_stuck_agents

            result = await handle_detect_stuck_agents({
                "max_age_minutes": 30.0,
                "critical_margin_timeout_minutes": 5.0,
                "tight_margin_timeout_minutes": 15.0,
                "auto_recover": True,
                "min_updates": 1,
                "note_cooldown_minutes": 120.0
            })

            if result and len(result) > 0:
                import json
                try:
                    from mcp.types import TextContent
                    result_text = result[0].text if isinstance(result[0], TextContent) else str(result[0])

                    if result_text.strip().startswith('{'):
                        result_data = json.loads(result_text)
                        stuck_agents = result_data.get('stuck_agents', [])
                        recovered = result_data.get('recovered', [])

                        if len(stuck_agents) > 0 or len(recovered) > 0:
                            logger.info(
                                f"[STUCK_AGENT_RECOVERY] Detected {len(stuck_agents)} stuck agent(s), "
                                f"recovered {len(recovered)} safe agent(s)"
                            )
                            for rec in recovered:
                                logger.debug(
                                    f"[STUCK_AGENT_RECOVERY] Recovered agent {rec.get('agent_id', 'unknown')[:8]}... "
                                    f"(reason: {rec.get('reason', 'unknown')})"
                                )
                except (json.JSONDecodeError, AttributeError, KeyError) as e:
                    logger.debug(f"[STUCK_AGENT_RECOVERY] Could not parse result: {e}")

        except asyncio.CancelledError:
            logger.info("[STUCK_AGENT_RECOVERY] Task cancelled")
            break
        except Exception as e:
            logger.warning(f"[STUCK_AGENT_RECOVERY] Error in recovery task: {e}", exc_info=True)
            await asyncio.sleep(60.0)


# ---------------------------------------------------------------------------
# Server warmup
# ---------------------------------------------------------------------------

async def server_warmup_task(set_ready):
    """Set server ready flag after short warmup to allow MCP initialization."""
    await asyncio.sleep(2.0)
    set_ready()
    logger.info("[WARMUP] Server ready to accept requests (warmup complete)")


# ---------------------------------------------------------------------------
# Session cleanup
# ---------------------------------------------------------------------------

async def session_cleanup_task(interval_hours: float = 6.0):
    """Delete expired sessions from PG and orphaned Redis session cache keys."""
    while True:
        await asyncio.sleep(interval_hours * 3600)
        pg_deleted = 0
        redis_deleted = 0

        expired_session_keys = []
        try:
            from src.db import get_db
            db = get_db()
            async with db.acquire() as conn:
                async with conn.transaction():
                    rows = await conn.fetch(
                        "SELECT session_id FROM core.sessions WHERE expires_at <= now()"
                    )
                    expired_session_keys = [r["session_id"] for r in rows]
                    result = await conn.execute("DELETE FROM core.sessions WHERE expires_at <= now()")
                    pg_deleted = int(result.split()[-1]) if result else 0
        except Exception as e:
            logger.warning(f"[SESSION_CLEANUP] PG cleanup failed: {e}")

        if expired_session_keys:
            try:
                from src.cache.redis_client import get_redis
                redis = await get_redis()
                if redis is not None:
                    for sk in expired_session_keys:
                        try:
                            removed = await redis.delete(f"session:{sk}")
                            if removed:
                                redis_deleted += 1
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"[SESSION_CLEANUP] Redis cleanup failed: {e}")

        if pg_deleted or redis_deleted:
            logger.info(
                f"[SESSION_CLEANUP] Deleted {pg_deleted} expired PG sessions, "
                f"{redis_deleted} Redis cache keys"
            )


# ---------------------------------------------------------------------------
# Coherence monitoring
# ---------------------------------------------------------------------------

async def coherence_monitoring_task(interval_minutes: float = 10.0):
    """Proactively monitor agent coherence and log warnings for declining agents."""
    from config.governance_config import config

    await asyncio.sleep(30.0)  # Let server settle
    target = config.TARGET_COHERENCE

    logger.info(f"[COHERENCE_MONITOR] Started (target={target}, interval={interval_minutes}m)")

    while True:
        try:
            await asyncio.sleep(interval_minutes * 60)

            from src.mcp_handlers.shared import lazy_mcp_server as mcp_server
            monitors = getattr(mcp_server, 'monitors', {})
            if not monitors:
                continue

            for agent_id, monitor in list(monitors.items()):
                try:
                    coherence = getattr(monitor.state, 'coherence', None)
                    if coherence is None:
                        continue
                    if coherence < 0.45:
                        logger.error(
                            f"[COHERENCE_MONITOR] CRITICAL: Agent {agent_id[:12]}... "
                            f"coherence={coherence:.3f} (target={target})"
                        )
                    elif coherence < target:
                        logger.warning(
                            f"[COHERENCE_MONITOR] Below target: Agent {agent_id[:12]}... "
                            f"coherence={coherence:.3f} (target={target})"
                        )
                except Exception:
                    pass

        except asyncio.CancelledError:
            logger.info("[COHERENCE_MONITOR] Task cancelled")
            break
        except Exception as e:
            logger.warning(f"[COHERENCE_MONITOR] Error: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Telemetry & log rotation
# ---------------------------------------------------------------------------

async def periodic_telemetry_rotation(interval_hours: float = 24.0):
    """Rotate drift_telemetry.jsonl daily when >100MB."""
    await asyncio.sleep(120.0)  # Let server settle
    while True:
        try:
            from src.drift_telemetry import get_telemetry
            telemetry = get_telemetry()
            result = telemetry.rotate(max_size_mb=50.0, archive_months=3)
            if result:
                logger.info(f"[ROTATION] Drift telemetry rotated -> {result}")
        except Exception as e:
            logger.debug(f"[ROTATION] Drift telemetry rotation skipped: {e}")
        await asyncio.sleep(interval_hours * 3600)


async def periodic_audit_log_rotation(interval_hours: float = 168.0):
    """Rotate audit_log.jsonl weekly. Data is fully duplicated in PostgreSQL."""
    await asyncio.sleep(180.0)
    while True:
        try:
            from src.audit_log import get_audit_log
            audit = get_audit_log()
            kept, archive_path = audit.rotate_log(max_age_days=30)
            if archive_path:
                logger.info(f"[ROTATION] Audit log rotated: {kept} entries kept, archived to {archive_path}")
        except Exception as e:
            logger.debug(f"[ROTATION] Audit log rotation skipped: {e}")
        await asyncio.sleep(interval_hours * 3600)


async def periodic_server_log_rotation(interval_hours: float = 24.0, max_size_mb: float = 50.0):
    """Rotate launchd-managed server log files by copy+truncate."""
    await asyncio.sleep(300.0)

    project_root = Path(__file__).parent.parent
    log_dir = project_root / "data" / "logs"
    archive_dir = log_dir / "archive"

    log_files = ["mcp_server.log", "mcp_server_error.log"]

    while True:
        for log_name in log_files:
            log_path = log_dir / log_name
            try:
                if not log_path.exists():
                    continue
                size_mb = log_path.stat().st_size / (1024 * 1024)
                if size_mb < max_size_mb:
                    continue

                archive_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                stem = log_path.stem
                archive_path = archive_dir / f"{stem}_{stamp}.log.gz"

                # Copy then truncate in-place (launchd holds the fd)
                with open(log_path, 'rb') as f_in:
                    with gzip.open(archive_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)

                # Truncate original (launchd's fd stays valid)
                with open(log_path, 'w') as f:
                    pass

                logger.info(f"[ROTATION] {log_name} ({size_mb:.0f}MB) -> {archive_path}")

                # Prune archives older than 6 months
                _prune_log_archives(archive_dir, stem, keep_months=6)

            except Exception as e:
                logger.debug(f"[ROTATION] {log_name} rotation failed: {e}")

        await asyncio.sleep(interval_hours * 3600)


def _prune_log_archives(archive_dir: Path, stem: str, keep_months: int = 6):
    """Remove log archives older than keep_months."""
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=keep_months * 30)
    for gz_file in sorted(archive_dir.glob(f"{stem}_*.log.gz")):
        try:
            date_str = gz_file.stem.replace(f"{stem}_", "").replace(".log", "")
            file_date = datetime.strptime(date_str, "%Y%m%d_%H%M%S")
            if file_date < cutoff:
                gz_file.unlink()
                logger.info(f"[ROTATION] Pruned old log archive: {gz_file.name}")
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# Orchestrator — called from mcp_server.py
# ---------------------------------------------------------------------------

_supervised_tasks: list = []


def _on_background_task_done(task: asyncio.Task) -> None:
    """Callback for background task completion — logs crashes."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(
            f"Background task '{task.get_name()}' crashed: {exc}",
            exc_info=exc,
        )


def _supervised_create_task(coro, *, name: str | None = None) -> asyncio.Task:
    """Create a background task with crash logging."""
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_on_background_task_done)
    _supervised_tasks.append(task)
    return task


def start_all_background_tasks(connection_tracker, set_ready):
    """
    Start all background tasks. Call once during server initialization.

    Args:
        connection_tracker: The ConnectionTracker instance
        set_ready: Callable that sets SERVER_READY = True
    """
    _supervised_create_task(connection_heartbeat_task(connection_tracker), name="heartbeat")
    logger.info("[HEARTBEAT] Connection health monitoring started")

    _supervised_create_task(startup_auto_calibration(), name="auto_calibration")
    _supervised_create_task(startup_kg_lifecycle(), name="kg_lifecycle")
    _supervised_create_task(concept_extraction_background_task(), name="concept_extraction")
    _supervised_create_task(periodic_matview_refresh(), name="matview_refresh")
    _supervised_create_task(periodic_partition_maintenance(), name="partition_maintenance")
    _supervised_create_task(background_metadata_load(), name="metadata_load")
    _supervised_create_task(periodic_orphan_cleanup(), name="orphan_cleanup")
    _supervised_create_task(stuck_agent_recovery_task(), name="stuck_agent_recovery")
    _supervised_create_task(server_warmup_task(set_ready), name="server_warmup")

    try:
        from src.mcp_handlers.observability.pi_orchestration import eisv_sync_task
        _supervised_create_task(eisv_sync_task(interval_minutes=5.0), name="eisv_sync")
        logger.info("[EISV_SYNC] Started periodic Pi EISV sync")
    except Exception as e:
        logger.warning(f"[EISV_SYNC] Could not start: {e}")

    _supervised_create_task(session_cleanup_task(interval_hours=6.0), name="session_cleanup")
    logger.info("[SESSION_CLEANUP] Started periodic expired session cleanup (every 6h)")

    _supervised_create_task(coherence_monitoring_task(interval_minutes=10.0), name="coherence_monitor")
    logger.info("[COHERENCE_MONITOR] Started proactive coherence monitoring (every 10m)")

    _supervised_create_task(periodic_telemetry_rotation(), name="telemetry_rotation")
    _supervised_create_task(periodic_audit_log_rotation(), name="audit_log_rotation")
    _supervised_create_task(periodic_server_log_rotation(), name="server_log_rotation")
    logger.info("[ROTATION] Started periodic log/telemetry rotation tasks")
