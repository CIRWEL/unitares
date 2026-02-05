"""
Admin tool handlers.
"""

from typing import Dict, Any, Sequence, Optional
from mcp.types import TextContent
import json
import sys
import os
from datetime import datetime
from pathlib import Path
from .utils import success_response, error_response, require_agent_id, require_registered_agent
from .decorators import mcp_tool
from .validators import validate_file_path_policy
from src.logging_utils import get_logger

logger = get_logger(__name__)

# Import from mcp_server_std module (using shared utility)
from .shared import get_mcp_server
mcp_server = get_mcp_server()


@mcp_tool("get_server_info", timeout=10.0, rate_limit_exempt=True)
async def handle_get_server_info(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Get MCP server version, process information, and health status"""
    import time
    import os
    
    # Detect transport from current process args (HTTP vs stdio).
    # This prevents HTTP from accidentally reporting stdio processes (and vice versa).
    argv = [str(a) for a in getattr(sys, "argv", [])]
    is_http = any("mcp_server.py" in a for a in argv)
    is_stdio = any("mcp_server_std.py" in a for a in argv)
    transport = "HTTP" if is_http else ("STDIO" if is_stdio else "unknown")
    target_script = "mcp_server.py" if is_http else ("mcp_server_std.py" if is_stdio else None)

    # Current pid should always be the live process hosting this handler.
    current_pid = os.getpid()

    # Prefer shared constants if available, fallback to local defaults.
    server_version = getattr(mcp_server, "SERVER_VERSION", None) or "unknown"
    server_build_date = getattr(mcp_server, "SERVER_BUILD_DATE", None) or "unknown"

    if mcp_server.PSUTIL_AVAILABLE:
        import psutil
        
        # Get all MCP server processes
        server_processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'status']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    if not cmdline:
                        continue

                    # Only include processes matching the current transport when detectable.
                    if target_script:
                        if not any(target_script in str(arg) for arg in cmdline):
                            continue
                    else:
                        # Unknown transport: include either server type if present.
                        if not any(('mcp_server_std.py' in str(arg) or 'mcp_server.py' in str(arg)) for arg in cmdline):
                            continue

                        pid = proc.info['pid']
                        create_time = proc.info.get('create_time', 0)
                        uptime_seconds = time.time() - create_time
                        uptime_minutes = int(uptime_seconds / 60)
                        uptime_hours = int(uptime_minutes / 60)
                        
                        server_processes.append({
                            "pid": pid,
                            "is_current": pid == current_pid,
                            "uptime_seconds": int(uptime_seconds),
                            "uptime_formatted": f"{uptime_hours}h {uptime_minutes % 60}m",
                            "status": proc.info.get('status', 'unknown')
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            server_processes = [{"error": f"Could not enumerate processes: {e}"}]
        
        # Calculate current process uptime
        try:
            current_proc = psutil.Process(current_pid)
            current_uptime = time.time() - current_proc.create_time()
            # If process enumeration didn't find anything (e.g., uvicorn spawn cmdline quirks),
            # always include the current process so get_server_info is never empty.
            if not server_processes:
                uptime_minutes = int(current_uptime / 60)
                uptime_hours = int(uptime_minutes / 60)
                server_processes.append({
                    "pid": current_pid,
                    "is_current": True,
                    "uptime_seconds": int(current_uptime),
                    "uptime_formatted": f"{uptime_hours}h {uptime_minutes % 60}m",
                    "status": getattr(current_proc, "status", lambda: "unknown")()
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            current_uptime = 0
    else:
        server_processes = [{"error": "psutil not available - cannot enumerate processes"}]
        current_uptime = 0
    
    current_uptime_minutes = int(current_uptime / 60)
    current_uptime_hours = int(current_uptime_minutes / 60)

    # Get tool count (tool mode filtering removed - all tools always available)
    from src.mcp_handlers import TOOL_HANDLERS
    tool_count = len(TOOL_HANDLERS)

    # PID file differs by transport.
    project_root = Path(__file__).resolve().parent.parent.parent
    pid_file = (project_root / "data" / ".mcp_server.pid") if is_http else (project_root / "data" / ".mcp_server_std.pid")

    return success_response({
        "transport": transport,
        "server_version": server_version,
        "version": server_version,  # Alias for consistency
        "build_date": server_build_date,
        "tool_count": tool_count,
        "current_pid": current_pid,
        "current_uptime_seconds": int(current_uptime),
        "current_uptime_formatted": f"{current_uptime_hours}h {current_uptime_minutes % 60}m",
        "total_server_processes": len([p for p in server_processes if "error" not in p]),
        "server_processes": server_processes,
        "pid_file_exists": pid_file.exists(),
        "pid_file": str(pid_file),
        "max_keep_processes": getattr(mcp_server, "MAX_KEEP_PROCESSES", None),
        "health": "healthy"
    })


@mcp_tool("check_continuity_health", timeout=15.0)
async def handle_check_continuity_health(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Check the health of agent persistence and provenance continuity features.

    Verifies that agent states, metadata, knowledge graph, and provenance
    information are being properly persisted across sessions.

    Args:
        agent_id: Specific agent to check (optional)
        deep_check: Run comprehensive checks including data integrity (default: False)

    Returns:
        Continuity health assessment with recommendations
    """
    agent_id = arguments.get("agent_id")
    deep_check = arguments.get("deep_check", False)

    try:
        health_report = {
            "timestamp": datetime.now().isoformat(),
            "checks": {},
            "recommendations": []
        }

        # Check agent metadata persistence
        from .shared import get_mcp_server
        mcp_server = get_mcp_server()
        metadata_count = len(mcp_server.agent_metadata) if hasattr(mcp_server, 'agent_metadata') else 0

        # Check knowledge graph persistence
        from src.mcp_handlers.knowledge_graph import get_knowledge_graph
        graph = await get_knowledge_graph()
        graph_stats = await graph.get_stats()

        # Check for active agents
        active_agents = [aid for aid, meta in mcp_server.agent_metadata.items()
                        if meta.status in ['active', 'waiting_input']] if hasattr(mcp_server, 'agent_metadata') else []

        health_report["checks"]["agent_metadata"] = {
            "status": "healthy" if metadata_count > 0 else "warning",
            "count": metadata_count,
            "active_agents": len(active_agents)
        }

        health_report["checks"]["knowledge_graph"] = {
            "status": "healthy" if graph_stats.get("total_discoveries", 0) > 0 else "warning",
            "total_discoveries": graph_stats.get("total_discoveries", 0),
            "total_agents": graph_stats.get("total_agents", 0)
        }

        # Check provenance tracking
        provenance_count = 0
        if deep_check:
            # Sample some discoveries to check provenance
            discoveries = await graph.query({}, limit=10)
            for discovery in discoveries:
                if discovery.provenance:
                    provenance_count += 1

        health_report["checks"]["provenance_tracking"] = {
            "status": "healthy" if provenance_count > 0 else "info",
            "sample_provenance_count": provenance_count,
            "note": "Provenance captured on discovery creation"
        }

        # Check lineage tracking for specific agent
        if agent_id:
            lineage_info = {}
            if hasattr(mcp_server, 'agent_metadata') and agent_id in mcp_server.agent_metadata:
                meta = mcp_server.agent_metadata[agent_id]
                from src.mcp_handlers.identity import _get_lineage
                lineage_info = {
                    "has_parent": meta.parent_agent_id is not None,
                    "spawn_reason": meta.spawn_reason,
                    "lineage_depth": len(_get_lineage(agent_id))
                }

            health_report["checks"]["agent_lineage"] = {
                "agent_id": agent_id,
                "lineage_info": lineage_info
            }

        # Generate recommendations
        if metadata_count == 0:
            health_report["recommendations"].append("No agent metadata found - ensure process_agent_update is being called")
        if graph_stats.get("total_discoveries", 0) == 0:
            health_report["recommendations"].append("No discoveries in knowledge graph - ensure store_knowledge_graph is working")
        if provenance_count == 0 and deep_check:
            health_report["recommendations"].append("No provenance data found - check that provenance capture is enabled")

        return success_response(health_report)

    except Exception as e:
        logger.error(f"Continuity health check failed: {e}", exc_info=True)
        return [error_response(f"Continuity health check failed: {e}")]


@mcp_tool("get_tool_usage_stats", timeout=15.0, rate_limit_exempt=True)
async def handle_get_tool_usage_stats(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Get tool usage statistics to identify which tools are actually used vs unused"""
    from src.tool_usage_tracker import get_tool_usage_tracker
    
    window_hours = arguments.get("window_hours", 24 * 7)  # Default: 7 days
    tool_name = arguments.get("tool_name")
    agent_id = arguments.get("agent_id")
    
    tracker = get_tool_usage_tracker()
    stats = tracker.get_usage_stats(
        window_hours=window_hours,
        tool_name=tool_name,
        agent_id=agent_id
    )
    
    return success_response(stats)


def get_workspace_last_agent_file(mcp_server) -> Path:
    """Get the file path for storing last active agent."""
    return Path(mcp_server.project_root) / "data" / ".last_active_agent"


def get_workspace_last_agent(mcp_server) -> Optional[str]:
    """Get the last active agent for this workspace."""
    try:
        last_agent_file = get_workspace_last_agent_file(mcp_server)
        if last_agent_file.exists():
            agent_id = last_agent_file.read_text().strip()
            # Verify it still exists
            if agent_id in mcp_server.agent_metadata:
                return agent_id
    except Exception:
        pass
    return None


def set_workspace_last_agent(mcp_server, agent_id: str) -> None:
    """Set the last active agent for this workspace."""
    try:
        last_agent_file = get_workspace_last_agent_file(mcp_server)
        last_agent_file.parent.mkdir(parents=True, exist_ok=True)
        last_agent_file.write_text(agent_id)
    except Exception:
        pass  # Non-critical


@mcp_tool("health_check", timeout=10.0, rate_limit_exempt=True)
async def handle_health_check(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle health_check tool - quick health check of system components"""
    import asyncio
    import os  # Fix: import os for UNITARES_CALIBRATION_DB_PATH env var check
    from src.calibration import calibration_checker
    from src.telemetry import telemetry_collector
    from src.audit_log import audit_logger
    from src.db import get_db
    
    checks = {}
    loop = asyncio.get_running_loop()
    
    # Check calibration (may trigger lazy initialization - wrap in executor to avoid blocking)
    try:
        # Accessing calibration_checker may trigger lazy initialization which does file I/O
        pending = await loop.run_in_executor(None, lambda: calibration_checker.get_pending_updates())
        checks["calibration"] = {
            "status": "healthy",
            "pending_updates": pending
        }
    except Exception as e:
        checks["calibration"] = {
            "status": "error",
            "error": str(e)
        }

    # Check calibration DB - uses PostgreSQL when DB_BACKEND=postgres, SQLite otherwise
    try:
        from src.calibration_db import calibration_health_check_async
        info = await calibration_health_check_async()
        checks["calibration_db"] = {
            "status": "healthy",
            "backend": info.get("backend", "unknown"),
            "info": info
        }
    except Exception as e:
        checks["calibration_db"] = {
            "status": "error",
            "error": str(e)
        }
    
    # Check telemetry/audit log (filesystem operation - run in executor)
    try:
        log_exists = await loop.run_in_executor(None, lambda: audit_logger.log_file.exists())
        checks["telemetry"] = {
            "status": "healthy" if log_exists else "warning",
            "audit_log_exists": log_exists
        }
    except Exception as e:
        checks["telemetry"] = {
            "status": "error",
            "error": str(e)
        }

    # Check PRIMARY database backend (PostgreSQL/SQLite/Dual) via src.db abstraction.
    # Note: calibration_db/audit_db below are legacy SQLite indexes; this check reports
    # the backend that migration work targets (DB_BACKEND).
    try:
        import os
        configured = os.getenv("DB_BACKEND", "postgres").lower()
        db = get_db()
        backend_class = type(db).__name__

        # Best-effort init so health_check isn't just "Pool not initialized"
        init_error = None
        try:
            await db.init()
        except Exception as e:
            init_error = str(e)

        try:
            db_info = await db.health_check()
        except Exception as e:
            db_info = {"status": "error", "error": str(e)}

        db_status = db_info.get("status") if isinstance(db_info, dict) else None
        checks["primary_db"] = {
            "status": "healthy" if db_status == "healthy" else ("error" if db_status == "error" else "warning"),
            "configured_backend": configured,
            "backend_class": backend_class,
            "init_error": init_error,
            "info": db_info,
        }
    except Exception as e:
        checks["primary_db"] = {
            "status": "error",
            "error": str(e),
        }

    # Check audit DB - uses PostgreSQL when DB_BACKEND=postgres, else SQLite.
    try:
        from src.audit_db import audit_health_check_async
        info = await audit_health_check_async()
        checks["audit_db"] = {
            "status": "healthy",
            "backend": info.get("backend", "unknown"),
            "info": info
        }
    except Exception as e:
        checks["audit_db"] = {
            "status": "error",
            "error": str(e)
        }

    # Check Redis cache (optional - for distributed session cache + locking + rate limiting + metadata cache)
    try:
        from src.cache import get_session_cache, get_distributed_lock, get_redis, is_redis_available
        redis_available = is_redis_available()
        
        if redis_available:
            session_cache = get_session_cache()
            dist_lock = get_distributed_lock()
            cache_health = await session_cache.health_check()
            lock_health = await dist_lock.health_check()
            
            checks["redis_cache"] = {
                "status": cache_health.get("status", "unknown"),
                "session_cache": cache_health,
                "distributed_lock": lock_health,
                "features": ["session_cache", "distributed_locking", "rate_limiting", "metadata_cache"]
            }
            
            # Get Redis stats if available
            try:
                redis = await get_redis()
                if redis:
                    info = await redis.info('stats')
                    checks["redis_cache"]["stats"] = {
                        "keyspace_hits": info.get('keyspace_hits', 0),
                        "keyspace_misses": info.get('keyspace_misses', 0),
                        "total_commands": info.get('total_commands_processed', 0),
                    }
                    # Count keys by prefix (sample first 1000)
                    session_keys = sum(1 for _ in range(1000) if True)  # Placeholder
                    try:
                        session_keys = len([k async for k in redis.scan_iter(match="session:*", count=100)])
                        rate_limit_keys = len([k async for k in redis.scan_iter(match="rate_limit:*", count=100)])
                        metadata_keys = len([k async for k in redis.scan_iter(match="agent_meta:*", count=100)])
                        lock_keys = len([k async for k in redis.scan_iter(match="lock:*", count=100)])
                        checks["redis_cache"]["keys"] = {
                            "sessions": session_keys,
                            "rate_limits": rate_limit_keys,
                            "metadata": metadata_keys,
                            "locks": lock_keys,
                        }
                    except Exception as e:
                        checks["redis_cache"]["keys_error"] = str(e)
            except Exception as e:
                checks["redis_cache"]["stats_error"] = str(e)
        else:
            checks["redis_cache"] = {
                "status": "unavailable",
                "note": "Redis not available - using fallback modes"
            }
    except ImportError:
        checks["redis_cache"] = {
            "status": "unavailable",
            "note": "Redis cache module not installed"
        }
    except Exception as e:
        checks["redis_cache"] = {
            "status": "error",
            "error": str(e)
        }

    # Check knowledge graph backend (SQLite or JSON) - best effort, kept lightweight.
    try:
        from src.knowledge_graph import get_knowledge_graph
        graph = await get_knowledge_graph()
        backend_name = type(graph).__name__

        # If SQLite backend is active, run its self-check (already offloaded to a thread).
        if hasattr(graph, "health_check"):
            kg_info = await graph.health_check()
        else:
            # JSON backend: at least report that graph loaded and basic stats are accessible.
            kg_info = await graph.get_stats()

        checks["knowledge_graph"] = {
            "status": "healthy",
            "backend": backend_name,
            "info": kg_info
        }
    except Exception as e:
        checks["knowledge_graph"] = {
            "status": "error",
            "error": str(e)
        }

    # Agent metadata - PostgreSQL is the canonical backend via agent_storage module.
    # Legacy SQLite/JSON backends are deprecated and will be removed.
    checks["agent_metadata"] = {
        "status": "healthy",
        "backend": "postgres",
        "note": "Agent metadata stored in core.identities table (PostgreSQL)"
    }
    
    # Check data directory (filesystem operation - run in executor)
    try:
        data_dir = Path(mcp_server.project_root) / "data"
        data_dir_exists = await loop.run_in_executor(None, lambda: data_dir.exists())
        checks["data_directory"] = {
            "status": "healthy" if data_dir_exists else "warning",
            "exists": data_dir_exists
        }
    except Exception as e:
        checks["data_directory"] = {
            "status": "error",
            "error": str(e)
        }
    
    # Overall health status - three-tier logic:
    # - healthy: all checks pass
    # - moderate: some warnings/deprecated but no errors
    # - critical: at least one error
    statuses = [c.get("status") for c in checks.values()]
    has_error = "error" in statuses
    all_healthy = all(s == "healthy" for s in statuses)

    if has_error:
        overall_status = "critical"
    elif all_healthy:
        overall_status = "healthy"
    else:
        overall_status = "moderate"

    # Include breakdown for transparency
    status_breakdown = {
        "healthy": sum(1 for s in statuses if s == "healthy"),
        "warning": sum(1 for s in statuses if s == "warning"),
        "deprecated": sum(1 for s in statuses if s == "deprecated"),
        "unavailable": sum(1 for s in statuses if s == "unavailable"),
        "error": sum(1 for s in statuses if s == "error"),
    }

    return success_response({
        "status": overall_status,
        "version": "2.5.7",
        "status_breakdown": status_breakdown,
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    })


@mcp_tool("check_calibration", timeout=10.0, rate_limit_exempt=True, register=False)
async def handle_check_calibration(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Check calibration of confidence estimates.
    
    NOTE ON "ACCURACY":
    This system is AI-for-AI and typically does not have access to external correctness
    (tests passing, real-world outcomes, user satisfaction). As a result, the primary
    calibration signal is a trajectory/consensus proxy (see returned honesty note).
    
    We keep the `accuracy` field for backward compatibility, but it should be read as
    "trajectory_health" unless you explicitly provide an external truth signal.
    """
    from src.calibration import calibration_checker
    
    is_calibrated, metrics = calibration_checker.check_calibration(include_complexity=True)
    
    # Calculate overall trajectory health from strategic bins
    # (the strategic "accuracy" field is conceptually trajectory_health)
    bins_data = metrics.get('bins', {})
    total_samples = sum(bin_data.get('count', 0) for bin_data in bins_data.values())
    weighted_sum = sum(
        float(bin_data.get('count', 0)) * float(bin_data.get('accuracy', 0.0))
        for bin_data in bins_data.values()
    )
    overall_trajectory_health = weighted_sum / total_samples if total_samples > 0 else 0.0
    
    # Calculate confidence distribution from bins
    confidence_values = []
    for bin_key, bin_data in bins_data.items():
        count = bin_data.get('count', 0)
        expected_acc = bin_data.get('expected_accuracy', 0.0)
        # Add confidence value for each sample in this bin
        confidence_values.extend([expected_acc] * count)
    
    if confidence_values:
        import numpy as np
        conf_dist = {
            "mean": float(np.mean(confidence_values)),
            "std": float(np.std(confidence_values)),
            "min": float(np.min(confidence_values)),
            "max": float(np.max(confidence_values))
        }
    else:
        conf_dist = {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    
    response = {
        "calibrated": is_calibrated,
        "issues": metrics.get('issues', []),  # Surface calibration issues
        # Backward compatibility: historically named "accuracy"
        "accuracy": overall_trajectory_health,
        # Preferred name: what this metric actually represents in UNITARES
        "trajectory_health": overall_trajectory_health,
        "truth_channel": "confidence_outcome_match",  # Updated: now compares confidence to outcome quality
        "confidence_distribution": conf_dist,
        "pending_updates": calibration_checker.get_pending_updates(),
        "total_samples": total_samples,
        "message": "Calibration check complete",
        "calibration_note": (
            "Ground truth evaluates if confidence matched outcome quality. "
            "High confidence + poor outcome = overconfident (False). "
            "Low confidence + excellent outcome = underconfident (False)."
        )
    }
    
    # Add complexity calibration metrics if available
    if 'complexity_calibration' in metrics:
        complexity_data = metrics['complexity_calibration']
        total_complexity_samples = sum(v.get('count', 0) for v in complexity_data.values())
        high_discrepancy_total = sum(
            v.get('count', 0) * v.get('high_discrepancy_rate', 0) 
            for v in complexity_data.values()
        )
        high_discrepancy_rate = high_discrepancy_total / total_complexity_samples if total_complexity_samples > 0 else 0
        
        response["complexity_calibration"] = {
            "total_samples": total_complexity_samples,
            "high_discrepancy_rate": high_discrepancy_rate,
            "bins": complexity_data
        }
    
    return success_response(response)


@mcp_tool("rebuild_calibration", timeout=60.0, rate_limit_exempt=True, register=False)
async def handle_rebuild_calibration(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Rebuild calibration from scratch using auto ground truth collection.

    This resets calibration state and re-evaluates all historical decisions
    using the current evaluation logic (confidence vs outcome quality matching).

    Use this after updating evaluation logic or to fix corrupted calibration state.

    Args:
        dry_run: If true, show what would be updated without modifying state
        min_age_hours: Minimum age of decisions to evaluate (default: 0.5)
        max_decisions: Maximum decisions to process (default: 0 = all)
    """
    from src.auto_ground_truth import collect_ground_truth_automatically

    dry_run = arguments.get("dry_run", False)
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("true", "1", "yes")

    min_age_hours = float(arguments.get("min_age_hours", 0.5))
    max_decisions = int(arguments.get("max_decisions", 0))

    try:
        result = await collect_ground_truth_automatically(
            min_age_hours=min_age_hours,
            max_decisions=max_decisions,
            dry_run=dry_run,
            rebuild=True  # Reset and rebuild from scratch
        )

        return success_response({
            "success": True,
            "action": "dry_run" if dry_run else "rebuild",
            "processed": result.get("processed", 0),
            "updated": result.get("updated", 0),
            "skipped": result.get("skipped", 0),
            "errors": result.get("errors", 0),
            "message": f"Calibration {'would be' if dry_run else 'has been'} rebuilt with {result.get('updated', 0)} ground truth samples"
        })
    except Exception as e:
        logger.error(f"Error rebuilding calibration: {e}", exc_info=True)
        return error_response(f"Failed to rebuild calibration: {e}")


@mcp_tool("update_calibration_ground_truth", timeout=10.0, register=False)
async def handle_update_calibration_ground_truth(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Optional: Update calibration with an external truth signal after review
    
    Supports two modes:
    1. Direct mode: Provide confidence, predicted_correct, actual_correct directly
    2. Timestamp mode: Provide timestamp (and optional agent_id), actual_correct. 
       System looks up confidence and decision from audit log.

    IMPORTANT (AI-for-AI truth model):
    UNITARES does not assume access to objective external correctness. Use this tool
    only when you have an external signal you trust (human review, tests, verifiers).
    """
    from src.calibration import calibration_checker
    from src.audit_log import AuditLogger
    from datetime import datetime
    
    # Check if using timestamp-based mode
    timestamp = arguments.get("timestamp")
    agent_id = arguments.get("agent_id")
    actual_correct = arguments.get("actual_correct")
    
    if timestamp:
        # TIMESTAMP MODE: Look up confidence and decision from audit log
        if actual_correct is None:
            return [error_response("Missing required parameter: actual_correct (required for timestamp mode). This should be an external truth signal (e.g., human review, tests).")]
        
        try:
            # Parse timestamp
            if isinstance(timestamp, str):
                decision_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                return [error_response("timestamp must be ISO format string (e.g., '2025-12-08T13:00:00')")]
            
            # Query audit log for decision at that timestamp
            # Use a small window around the timestamp to account for slight timing differences
            from datetime import timedelta
            window_start = (decision_time - timedelta(seconds=5)).isoformat()
            window_end = (decision_time + timedelta(seconds=5)).isoformat()
            
            audit_logger = AuditLogger()
            entries = audit_logger.query_audit_log(
                agent_id=agent_id,
                event_type="auto_attest",
                start_time=window_start,
                end_time=window_end
            )
            
            if not entries:
                return [error_response(
                    f"No decision found at timestamp {timestamp}" + 
                    (f" for agent {agent_id}" if agent_id else ""),
                    details={
                        "suggestion": "Check timestamp format (ISO) and ensure decision was logged",
                        "related_tools": ["get_telemetry_metrics"]
                    }
                )]
            
            # Use most recent entry if multiple found (shouldn't happen with exact timestamp, but be safe)
            entry = entries[-1]
            confidence = entry.get("confidence", 0.0)
            decision = entry.get("details", {}).get("decision", "unknown")
            # FIXED: Use confidence-based prediction, not decision-based
            # High confidence (>=0.5) = we predicted correct
            predicted_correct = float(confidence) >= 0.5
            
            # Update calibration with external truth signal
            calibration_checker.update_ground_truth(
                confidence=float(confidence),
                predicted_correct=bool(predicted_correct),
                actual_correct=bool(actual_correct)
            )
            
            # Save calibration state
            calibration_checker.save_state()
            
            return success_response({
                "message": "External truth signal recorded successfully (timestamp mode)",
                "truth_channel": "external",
                "looked_up": {
                    "confidence": confidence,
                    "decision": decision,
                    "predicted_correct": predicted_correct
                },
                "pending_updates": calibration_checker.get_pending_updates()
            })
            
        except ValueError as e:
            return [error_response(f"Invalid timestamp format: {str(e)}")]
        except Exception as e:
            return [error_response(f"Error looking up decision: {str(e)}")]
    
    else:
        # DIRECT MODE: Require all parameters
        confidence = arguments.get("confidence")
        predicted_correct = arguments.get("predicted_correct")
        
        if confidence is None or predicted_correct is None or actual_correct is None:
            return [error_response(
                "Missing required parameters. Use either:\n"
                "1. Direct mode: confidence, predicted_correct, actual_correct\n"
                "2. Timestamp mode: timestamp, actual_correct (optional: agent_id)",
                details={
                    "direct_mode": {"required": ["confidence", "predicted_correct", "actual_correct"]},
                    "timestamp_mode": {"required": ["timestamp", "actual_correct"], "optional": ["agent_id"]}
                }
            )]
        
        try:
            calibration_checker.update_ground_truth(
                confidence=float(confidence),
                predicted_correct=bool(predicted_correct),
                actual_correct=bool(actual_correct)
            )
            
            # Save calibration state after update
            calibration_checker.save_state()
            
            return success_response({
                "message": "External truth signal recorded successfully (direct mode)",
                "truth_channel": "external",
                "pending_updates": calibration_checker.get_pending_updates()
            })
        except Exception as e:
            return [error_response(str(e))]


@mcp_tool("backfill_calibration_from_dialectic", timeout=20.0, rate_limit_exempt=True, register=False)
async def handle_backfill_calibration_from_dialectic(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Retroactively update calibration from historical resolved verification-type dialectic sessions.
    
    This processes all existing resolved verification sessions that were created before
    automatic calibration was implemented, ensuring they contribute to calibration.
    
    USE CASES:
    - One-time migration after implementing automatic calibration
    - Backfill historical peer verification data
    - Ensure all resolved verification sessions contribute to calibration
    
    RETURNS:
    {
      "success": true,
      "processed": int,
      "updated": int,
      "errors": int,
      "sessions": [{"session_id": "...", "agent_id": "...", "status": "..."}]
    }
    """
    from src.mcp_handlers.dialectic import backfill_calibration_from_historical_sessions
    
    try:
        results = await backfill_calibration_from_historical_sessions()
        return success_response({
            "success": True,
            "message": f"Backfill complete: {results['updated']}/{results['processed']} sessions updated",
            **results
        })
    except Exception as e:
        return [error_response(f"Error during backfill: {str(e)}")]


@mcp_tool("get_telemetry_metrics", timeout=15.0, rate_limit_exempt=True)
async def handle_get_telemetry_metrics(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Get comprehensive telemetry metrics: skip rates, confidence distributions, calibration status
    
    Note: Calibration data is system-wide and can be large. Use include_calibration=False to reduce response size.
    """
    import asyncio
    from src.telemetry import TelemetryCollector
    
    telemetry = TelemetryCollector()
    
    agent_id = arguments.get("agent_id")
    window_hours = arguments.get("window_hours", 24)
    include_calibration = arguments.get("include_calibration", False)  # Default False to reduce context bloat
    
    # Run blocking I/O operations in executor to prevent hanging
    loop = asyncio.get_running_loop()  # Use get_running_loop() instead of deprecated get_event_loop()
    
    try:
        # Always fetch skip metrics and confidence distribution (agent-specific, small)
        skip_metrics, conf_dist, suspicious = await asyncio.gather(
            loop.run_in_executor(None, telemetry.get_skip_rate_metrics, agent_id, window_hours),
            loop.run_in_executor(None, telemetry.get_confidence_distribution, agent_id, window_hours),
            loop.run_in_executor(None, telemetry.detect_suspicious_patterns, agent_id)
        )
        
        response = {
            "agent_id": agent_id or "all_agents",
            "window_hours": window_hours,
            "skip_rate_metrics": skip_metrics,
            "confidence_distribution": conf_dist,
            "suspicious_patterns": suspicious
        }

        # Include lightweight knowledge-graph performance stats (in-process, low overhead).
        try:
            from src.perf_monitor import snapshot as perf_snapshot
            response["knowledge_graph_perf"] = perf_snapshot()
        except Exception:
            response["knowledge_graph_perf"] = {"note": "perf snapshot unavailable"}
        
        # Only include calibration if explicitly requested (reduces context bloat)
        if include_calibration:
            calibration_metrics = await loop.run_in_executor(
                None, telemetry.get_calibration_metrics
            )
            response["calibration"] = calibration_metrics
        else:
            # Provide summary instead of full calibration data
            response["calibration"] = {
                "note": "Calibration data excluded to reduce response size. Set include_calibration=true to get full calibration metrics.",
                "related_tool": "check_calibration"
            }
        
        return success_response(response)
    except Exception as e:
        logger.error(f"Error in get_telemetry_metrics: {e}")
        return [error_response(f"Error collecting telemetry: {str(e)}")]


@mcp_tool("reset_monitor", timeout=10.0)
async def handle_reset_monitor(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Reset governance state for an agent"""
    # PROACTIVE GATE: Require agent to be registered
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]  # Returns onboarding guidance if not registered
    
    if agent_id in mcp_server.monitors:
        del mcp_server.monitors[agent_id]
        message = f"Monitor reset for agent: {agent_id}"
    else:
        message = f"Monitor not found for agent: {agent_id} (may not be loaded)"
    
    return success_response({
        "message": message,
        "agent_id": agent_id
    })


@mcp_tool("cleanup_stale_locks", timeout=15.0, rate_limit_exempt=True)
async def handle_cleanup_stale_locks(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Clean up stale lock files that are no longer held by active processes"""
    try:
        from src.lock_cleanup import cleanup_stale_state_locks
        
        max_age = arguments.get('max_age_seconds', 300.0)
        dry_run = arguments.get('dry_run', False)
        
        project_root = Path(__file__).parent.parent.parent
        result = cleanup_stale_state_locks(project_root=project_root, max_age_seconds=max_age, dry_run=dry_run)
        
        return success_response({
            "cleaned": result['cleaned'],
            "kept": result['kept'],
            "errors": result['errors'],
            "dry_run": dry_run,
            "max_age_seconds": max_age,
            "cleaned_locks": result.get('cleaned_locks', []),
            "kept_locks": result.get('kept_locks', []),
            "message": f"Cleaned {result['cleaned']} stale lock(s), kept {result['kept']} active lock(s)"
        })
    except Exception as e:
        return [error_response(f"Error cleaning stale locks: {str(e)}")]


@mcp_tool("list_tools", timeout=10.0, rate_limit_exempt=True)
async def handle_list_tools(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """List all available governance tools with descriptions and categories
    
    Parameters:
        essential_only (bool): If true, return only Tier 1 (essential) tools (default: false)
        include_advanced (bool): If false, exclude Tier 3 (advanced) tools (default: true)
        tier (str): Filter by tier: "essential", "common", "advanced", or "all" (default: "all")
        lite (bool): If true, return minimal response (names + descriptions only, ~500B vs ~4KB)
        progressive (bool): If true, order tools by usage frequency (most used first). Works with all filter modes. Default false.
    """
    from .shared import get_mcp_server
    mcp_server = get_mcp_server()
    
    # Get actual registered tools from TOOL_HANDLERS registry
    from . import TOOL_HANDLERS
    registered_tool_names = sorted(TOOL_HANDLERS.keys())
    
    # Parse filter parameters (handle string booleans from MCP transport)
    def parse_bool(val, default):
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    essential_only = parse_bool(arguments.get("essential_only"), False)
    include_advanced = parse_bool(arguments.get("include_advanced"), True)
    tier_filter = arguments.get("tier", "all")
    # LITE-FIRST: Default to minimal response for local/smaller models
    lite_mode = parse_bool(arguments.get("lite"), True)
    # Progressive disclosure: Order tools by usage frequency
    progressive = parse_bool(arguments.get("progressive"), False)
    
    # Import TOOL_TIERS from single source of truth
    from src.tool_modes import TOOL_TIERS

    # Deprecated tools - hidden from list_tools by default
    # Source of truth: tool_stability.py (aliases handle routing)
    from .tool_stability import list_all_aliases
    DEPRECATED_TOOLS = set(list_all_aliases().keys())

    # Define tool relationships and workflows
    tool_relationships = {
        "process_agent_update": {
            "depends_on": [],  # No deps - identity auto-creates
            "related_to": ["simulate_update", "get_governance_metrics", "get_system_history"],
            "category": "core"
        },
        "get_governance_metrics": {
            "depends_on": [],
            "related_to": ["process_agent_update", "observe_agent", "get_system_history"],
            "category": "core"
        },
        "simulate_update": {
            "depends_on": [],
            "related_to": ["process_agent_update", "get_governance_metrics"],
            "category": "core"
        },
        "get_thresholds": {
            "depends_on": [],
            "related_to": ["set_thresholds", "process_agent_update"],
            "category": "config"
        },
        "set_thresholds": {
            "depends_on": ["get_thresholds"],
            "related_to": ["get_thresholds", "process_agent_update"],
            "category": "config"
        },
        "observe_agent": {
            "depends_on": ["list_agents"],
            "related_to": ["get_governance_metrics", "compare_agents", "detect_anomalies"],
            "category": "observability"
        },
        "compare_agents": {
            "depends_on": ["list_agents"],
            "related_to": ["observe_agent", "aggregate_metrics", "detect_anomalies"],
            "category": "observability"
        },
        "detect_anomalies": {
            "depends_on": ["list_agents"],
            "related_to": ["observe_agent", "compare_agents", "aggregate_metrics"],
            "category": "observability"
        },
        "aggregate_metrics": {
            "depends_on": [],
            "related_to": ["observe_agent", "compare_agents", "detect_anomalies"],
            "category": "observability"
        },
        "list_agents": {
            "depends_on": [],
            "related_to": ["get_agent_metadata", "identity"],
            "category": "lifecycle"
        },
        "get_agent_metadata": {
            "depends_on": ["list_agents"],
            "related_to": ["list_agents", "update_agent_metadata"],
            "category": "lifecycle"
        },
        "update_agent_metadata": {
            "depends_on": ["list_agents"],
            "related_to": ["get_agent_metadata", "list_agents"],
            "category": "lifecycle"
        },
        "archive_agent": {
            "depends_on": ["list_agents"],
            "related_to": ["list_agents", "delete_agent"],
            "category": "lifecycle"
        },
        "delete_agent": {
            "depends_on": ["list_agents"],
            "related_to": ["archive_agent", "list_agents"],
            "category": "lifecycle"
        },
        "archive_old_test_agents": {
            "depends_on": [],
            "related_to": ["archive_agent", "list_agents"],
            "category": "lifecycle"
        },
        # get_agent_api_key REMOVED - aliased to identity()
        "mark_response_complete": {
            "depends_on": [],
            "related_to": ["process_agent_update", "get_agent_metadata"],
            "category": "lifecycle"
        },
        "request_dialectic_review": {
            "deprecated": True,
            "deprecated_since": "2026-01-29",
            "superseded_by": "self_recovery_review",
            "depends_on": ["get_agent_metadata"],
            "related_to": ["self_recovery_review", "get_dialectic_session"],
            "category": "lifecycle",
            "migration": "Use self_recovery_review(reflection='...') instead"
        },
        "direct_resume_if_safe": {
            "deprecated": True,
            "deprecated_since": "2026-01-29",
            "superseded_by": "quick_resume",
            "depends_on": [],
            "related_to": ["quick_resume", "self_recovery_review", "check_recovery_options"],
            "category": "lifecycle",
            "migration": "Use quick_resume() if coherence > 0.60 and risk < 0.40, otherwise use self_recovery_review(reflection='...')"
        },
        "self_recovery_review": {
            "depends_on": ["get_governance_metrics"],
            "related_to": ["quick_resume", "check_recovery_options"],
            "replaces": ["direct_resume_if_safe", "request_dialectic_review"],
            "category": "lifecycle",
            "recovery_hierarchy": {
                "fastest": "quick_resume",
                "primary": "self_recovery_review",
                "diagnostic": "check_recovery_options"
            },
            "description": "Primary recovery path - requires reflection but allows recovery at moderate thresholds"
        },
        "quick_resume": {
            "depends_on": ["get_governance_metrics"],
            "related_to": ["self_recovery_review", "check_recovery_options"],
            "category": "lifecycle",
            "recovery_hierarchy": {
                "fastest": "quick_resume",
                "primary": "self_recovery_review",
                "diagnostic": "check_recovery_options"
            },
            "description": "Fastest recovery path - no reflection needed, but requires very safe state"
        },
        "check_recovery_options": {
            "depends_on": ["get_governance_metrics"],
            "related_to": ["self_recovery_review", "quick_resume"],
            "category": "lifecycle",
            "description": "Read-only diagnostic tool to check recovery eligibility"
        },
        "get_system_history": {
            "depends_on": ["list_agents"],
            "related_to": ["export_to_file", "get_governance_metrics", "observe_agent"],
            "category": "export"
        },
        "export_to_file": {
            "depends_on": ["get_system_history"],
            "related_to": ["get_system_history"],
            "category": "export"
        },
        "reset_monitor": {
            "depends_on": ["list_agents"],
            "related_to": ["process_agent_update"],
            "category": "admin"
        },
        "get_server_info": {
            "depends_on": [],
            "related_to": ["health_check", "cleanup_stale_locks"],
            "category": "admin"
        },
        "get_connection_status": {
            "depends_on": [],
            "related_to": ["health_check", "get_server_info", "debug_request_context"],
            "category": "admin"
        },
        "health_check": {
            "depends_on": [],
            "related_to": ["get_server_info", "get_telemetry_metrics"],
            "category": "admin"
        },
        "check_calibration": {
            "depends_on": ["update_calibration_ground_truth"],
            "related_to": ["update_calibration_ground_truth"],
            "category": "admin"
        },
        "update_calibration_ground_truth": {
            "depends_on": [],
            "related_to": ["check_calibration"],
            "category": "admin"
        },
        "get_telemetry_metrics": {
            "depends_on": [],
            "related_to": ["health_check", "aggregate_metrics"],
            "category": "admin"
        },
        "get_tool_usage_stats": {
            "depends_on": [],
            "related_to": ["get_telemetry_metrics", "list_tools"],
            "category": "admin"
        },
        "get_workspace_health": {
            "depends_on": [],
            "related_to": ["health_check", "get_server_info"],
            "category": "workspace"
        },
        # Dialectic tools - only get_dialectic_session remains (archive viewer)
        # Other dialectic tools REMOVED - aliased to get_dialectic_session
        "get_dialectic_session": {
            "depends_on": [],
            "related_to": ["get_governance_metrics"],
            "category": "dialectic"
        },
        "cleanup_stale_locks": {
            "depends_on": [],
            "related_to": ["get_server_info"],
            "category": "admin"
        },
        "list_tools": {
            "depends_on": [],
            "related_to": ["describe_tool"],
            "category": "admin"
        },
        "describe_tool": {
            "depends_on": [],
            "related_to": ["list_tools"],
            "category": "admin"
        },
        # nudge_dialectic_session REMOVED - dialectic simplified
        # Knowledge Graph Tools
        "store_knowledge_graph": {
            "depends_on": [],  # No deps - identity auto-binds
            "related_to": ["search_knowledge_graph", "get_knowledge_graph", "list_knowledge_graph"],
            "category": "knowledge"
        },
        "search_knowledge_graph": {
            "depends_on": [],
            "related_to": ["store_knowledge_graph", "get_discovery_details"],
            "category": "knowledge"
        },
        "get_knowledge_graph": {
            "depends_on": ["list_agents"],
            "related_to": ["search_knowledge_graph", "list_knowledge_graph", "get_discovery_details"],
            "category": "knowledge"
        },
        "list_knowledge_graph": {
            "depends_on": [],
            "related_to": ["get_knowledge_graph", "search_knowledge_graph"],
            "category": "knowledge"
        },
        # find_similar_discoveries_graph, get_related_discoveries_graph,
        # get_response_chain_graph, reply_to_question REMOVED - aliased
        "get_discovery_details": {
            "depends_on": ["search_knowledge_graph"],
            "related_to": ["search_knowledge_graph", "update_discovery_status_graph"],
            "category": "knowledge"
        },
        "leave_note": {
            "depends_on": [],  # No deps - identity auto-binds
            "related_to": ["store_knowledge_graph"],
            "category": "knowledge"
        },
        "update_discovery_status_graph": {
            "depends_on": ["get_discovery_details"],
            "related_to": ["get_discovery_details", "search_knowledge_graph"],
            "category": "knowledge"
        },
        # Identity Tools - Dec 2025: onboard() is portal, identity() is primary
        "onboard": {
            "depends_on": [],
            "related_to": ["identity", "process_agent_update"],
            "category": "identity"
        },
        "identity": {
            "depends_on": [],
            "related_to": ["onboard", "process_agent_update", "list_agents"],
            "category": "identity"
        },
        # Admin Tools
        "backfill_calibration_from_dialectic": {
            "depends_on": ["check_calibration"],
            "related_to": ["check_calibration", "update_calibration_ground_truth"],
            "category": "admin"
        },
        "validate_file_path": {
            "depends_on": [],
            "related_to": ["get_workspace_health"],
            "category": "admin"
        },
        "debug_request_context": {
            "depends_on": [],
            "related_to": ["get_server_info", "identity"],
            "category": "admin"
        },
        # Observability Tools
        "compare_me_to_similar": {
            "depends_on": ["get_governance_metrics"],
            "related_to": ["compare_agents", "observe_agent"],
            "category": "observability"
        },
        # Dialectic Tools - Dec 2025: Only get_dialectic_session remains
        "get_dialectic_session": {
            "depends_on": [],
            "related_to": ["process_agent_update"],
            "category": "dialectic"
        }
    }
    
    # Define common workflows
    workflows = {
        "onboarding": [
            "onboard",  # 🚀 Portal tool - call FIRST
            "process_agent_update",  # Start working
            "identity",  # (Optional) Check/name yourself later
            "list_agents"  # See who else is here
        ],
        "monitoring": [
            "list_agents",
            "get_governance_metrics",
            "observe_agent",
            "aggregate_metrics",
            "detect_anomalies"
        ],
        "governance_cycle": [
            "process_agent_update",
            "get_governance_metrics"
        ],
        "recovery": [
            "get_dialectic_session",  # View archived sessions
            "direct_resume_if_safe"  # Resume if state is safe
        ],
        "export_analysis": [
            "get_system_history",
            "export_to_file"
        ]
    }
    
    # Build tools list dynamically from registered tools
    # Description mapping for tools (fallback to generic if not found)
    tool_descriptions = {
        "onboard": "🚀 START HERE - Your first tool call. Auto-creates identity + ready-to-use templates",
        "identity": "🪞 Check who you are or set your display name. Auto-creates identity if first call",
        "process_agent_update": "💬 Share your work and get supportive feedback. Your main check-in tool",
        "get_governance_metrics": "📊 Get current state and metrics without updating",
        "simulate_update": "🧪 Test decisions without persisting state",
        "get_thresholds": "⚙️ View current threshold configuration",
        "set_thresholds": "⚙️ Set runtime threshold overrides",
        "observe_agent": "👁️ View agent state and patterns (collaborative awareness)",
        "compare_agents": "🔍 Compare state patterns across agents",
        "detect_anomalies": "🚨 Scan for unusual patterns across fleet",
        "aggregate_metrics": "📈 Fleet-level health overview",
        "list_agents": "👥 List all agents with lifecycle metadata",
        "get_agent_metadata": "📋 Full metadata for single agent (accepts UUID or label)",
        "update_agent_metadata": "✏️ Update tags and notes",
        "archive_agent": "📦 Archive for long-term storage",
        "delete_agent": "🗑️ Delete agent (protected for pioneers)",
        "archive_old_test_agents": "🧹 Auto-archive stale test agents",
        "mark_response_complete": "✅ Mark agent as having completed response, waiting for input",
        "direct_resume_if_safe": "▶️ Direct resume without dialectic if agent state is safe",
        "get_system_history": "📜 Export time-series history (inline)",
        "export_to_file": "💾 Export history to JSON/CSV file",
        "reset_monitor": "🔄 Reset agent state",
        "get_server_info": "ℹ️ Server version, PID, uptime, health",
        # Knowledge Graph (Fast, indexed, transparent)
        "store_knowledge_graph": "💡 Store knowledge discovery in graph (fast, non-blocking)",
        "search_knowledge_graph": "🔎 Search knowledge graph by tags, type, agent (indexed queries)",
        "get_knowledge_graph": "📚 Get all knowledge for an agent (fast index lookup)",
        "list_knowledge_graph": "📊 List knowledge graph statistics (full transparency)",
        "update_discovery_status_graph": "🔄 Update discovery status (open/resolved/archived)",
        "leave_note": "📝 Leave a quick note in the knowledge graph (minimal friction)",
        "list_tools": "📚 Discover all available tools. Your guide to what's possible",
        "describe_tool": "📖 Get full details for a specific tool. Deep dive into any tool",
        "cleanup_stale_locks": "🧹 Clean up stale lock files from crashed/killed processes",
        "get_dialectic_session": "📋 View archived dialectic sessions",
        "health_check": "🏥 Quick health check - system status and component health",
        "check_calibration": "📏 Check calibration of confidence estimates",
        "update_calibration_ground_truth": "📝 Record external truth signal for calibration (optional)",
        "get_telemetry_metrics": "📊 Get comprehensive telemetry metrics",
        "get_workspace_health": "🏥 Get comprehensive workspace health status",
        "get_tool_usage_stats": "📈 Get tool usage statistics to identify which tools are actually used vs unused",
    }
    
    # Build tools list from registered tools with metadata from decorators
    from .decorators import get_tool_timeout, get_tool_description
    # Import tool schemas to get proper descriptions
    from src.tool_schemas import get_tool_definitions
    schema_tools = {t.name: t.description for t in get_tool_definitions()}
    
    tools_list = []
    for tool_name in registered_tool_names:
        # Priority: 1. tool_descriptions dict, 2. schema description, 3. decorator description, 4. fallback
        # Check each source explicitly to avoid empty string issues
        description = None
        if tool_name in tool_descriptions and tool_descriptions[tool_name]:
            description = tool_descriptions[tool_name]
        elif tool_name in schema_tools and schema_tools[tool_name]:
            description = schema_tools[tool_name]
        else:
            desc_from_decorator = get_tool_description(tool_name)
            if desc_from_decorator:
                description = desc_from_decorator
        
        # Fallback to generic description if none found
        if not description:
            description = f"Tool: {tool_name}"
        
        # Extract first line of description for brevity (full description available in tool schemas)
        if description and '\n' in description:
            description = description.split('\n')[0]
        
        # Determine tool tier
        tool_tier = "common"  # Default
        if tool_name in TOOL_TIERS["essential"]:
            tool_tier = "essential"
        elif tool_name in TOOL_TIERS["common"]:
            tool_tier = "common"
        elif tool_name in TOOL_TIERS["advanced"]:
            tool_tier = "advanced"
        
        # Apply filters
        # Hide deprecated tools by default (they still work, just not shown)
        if tool_name in DEPRECATED_TOOLS:
            continue
        if essential_only and tool_tier != "essential":
            continue
        if not include_advanced and tool_tier == "advanced":
            continue
        if tier_filter != "all" and tool_tier != tier_filter:
            continue
        
        tool_info = {
            "name": tool_name,
            "description": description,
            "tier": tool_tier
        }
        # Add operation type (read/write/admin) from tool_modes
        from src.tool_modes import TOOL_OPERATIONS
        tool_info["op"] = TOOL_OPERATIONS.get(tool_name, "read")  # Default to read
        # Add timeout metadata if available from decorator
        timeout = get_tool_timeout(tool_name)
        if timeout:
            tool_info["timeout"] = timeout
        # Add category from relationships if available
        if tool_name in tool_relationships:
            category_name = tool_relationships[tool_name].get("category")
            # Ensure category_name is never None
            if not category_name or not isinstance(category_name, str):
                category_name = "unknown"
            tool_info["category"] = category_name
            # Add category metadata for better UX
            category_meta_dict = {
                "identity": {"icon": "🚀", "name": "Identity & Onboarding"},
                "core": {"icon": "💬", "name": "Core Governance"},
                "lifecycle": {"icon": "👥", "name": "Agent Lifecycle"},
                "knowledge": {"icon": "💡", "name": "Knowledge Graph"},
                "observability": {"icon": "👁️", "name": "Observability"},
                "export": {"icon": "📊", "name": "Export & History"},
                "config": {"icon": "⚙️", "name": "Configuration"},
                "admin": {"icon": "🔧", "name": "Admin & Diagnostics"},
                "workspace": {"icon": "📁", "name": "Workspace"},
                "dialectic": {"icon": "💭", "name": "Dialectic"}
            }
            if category_name in category_meta_dict:
                category_meta = category_meta_dict[category_name]
            else:
                # Fallback for unknown categories - category_name is guaranteed to be a string here
                fallback_name = category_name.title() if isinstance(category_name, str) else "Other"
                category_meta = {"icon": "🔹", "name": fallback_name}
            tool_info["category_icon"] = category_meta["icon"]
            tool_info["category_name"] = category_meta["name"]
        tools_list.append(tool_info)
    
    # PROGRESSIVE DISCLOSURE: Order tools by usage frequency (if enabled)
    def get_usage_data(window_hours: int = 168) -> Dict[str, Dict[str, Any]]:
        """Get tool usage statistics for ordering."""
        try:
            from src.tool_usage_tracker import get_tool_usage_tracker
            tracker = get_tool_usage_tracker()
            stats = tracker.get_usage_stats(window_hours=window_hours)
            return stats.get("tools", {})
        except Exception:
            return {}
    
    def order_tools_by_usage(tools: List[Dict[str, Any]], usage_data: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Order tools by usage frequency, fallback to tier-based ordering."""
        # Tier priority for fallback (essential > common > advanced)
        tier_priority = {"essential": 3, "common": 2, "advanced": 1}
        
        def sort_key(tool: Dict[str, Any]) -> tuple:
            tool_name = tool["name"]
            call_count = usage_data.get(tool_name, {}).get("call_count", 0)
            tier_prio = tier_priority.get(tool.get("tier", "common"), 0)
            # Primary: usage count (descending), Secondary: tier priority (descending)
            return (-call_count, -tier_prio)
        
        return sorted(tools, key=sort_key)
    
    # Apply progressive ordering if enabled
    usage_data = {}
    if progressive:
        usage_data = get_usage_data()
        tools_list = order_tools_by_usage(tools_list, usage_data)
    
    # Count tools by tier
    # LITE MODE: Return only ESSENTIAL tools (~1KB vs ~20KB)
    if lite_mode:
        # Import from single source of truth
        from src.tool_modes import LITE_MODE_TOOLS
        lite_tools = [
            {
                "name": t["name"],
                "hint": t["description"][:100] + ("..." if len(t["description"]) > 100 else ""),
                "tier": t.get("tier", "common"),  # essential/common/advanced
                "op": t.get("op", "read"),  # read/write/admin
                "category": t.get("category"),
                "category_icon": t.get("category_icon"),
                "category_name": t.get("category_name")
            }
            for t in tools_list
            if t["name"] in LITE_MODE_TOOLS
        ]
        # Sort by workflow order (onboard first) or usage if progressive enabled
        if progressive and usage_data:
            # Re-order lite tools by usage (they're already filtered from tools_list which was ordered)
            lite_tools_dict = {t["name"]: t for t in lite_tools}
            ordered_lite_names = [t["name"] for t in tools_list if t["name"] in lite_tools_dict]
            lite_tools = [lite_tools_dict[name] for name in ordered_lite_names if name in lite_tools_dict]
        else:
            # Default workflow order
            order = ["onboard", "identity", "process_agent_update", "get_governance_metrics",
                     "list_tools", "describe_tool", "list_agents", "health_check",
                     "store_knowledge_graph", "search_knowledge_graph", "leave_note"]
            lite_tools.sort(key=lambda x: order.index(x["name"]) if x["name"] in order else 99)
        
        # Group by category for better organization
        categories_in_lite = {}
        category_metadata = {}
        for tool in lite_tools:
            cat = tool.get("category") or "other"
            if cat not in categories_in_lite:
                categories_in_lite[cat] = []
                cat_name = tool.get("category_name")
                if not cat_name:
                    cat_name = cat.title() if cat and isinstance(cat, str) else "Other"
                category_metadata[cat] = {
                    "icon": tool.get("category_icon", "🔹"),
                    "name": cat_name
                }
            categories_in_lite[cat].append(tool["name"])
        
        # Check if this might be a new agent (no bound identity)
        is_new_agent = False
        try:
            from .context import get_context_agent_id
            bound_id = get_context_agent_id()  # Set by identity_v2 at dispatch entry
            is_new_agent = not bound_id
        except Exception:
            pass
        
        # Count lite tools by tier
        lite_tier_counts = {"essential": 0, "common": 0, "advanced": 0}
        for t in lite_tools:
            tier = t.get("tier", "common")
            if tier in lite_tier_counts:
                lite_tier_counts[tier] += 1

        response_data = {
            "tools": lite_tools,
            "total_available": len(tools_list),
            "shown": len(lite_tools),
            # Tier summary for quick understanding of tool importance
            "tier_summary": {
                "essential": {
                    "count": lite_tier_counts["essential"],
                    "note": "Core tools - use these for basic workflows"
                },
                "common": {
                    "count": lite_tier_counts["common"],
                    "note": "Standard tools - commonly used for specific tasks"
                },
                "advanced": {
                    "count": lite_tier_counts["advanced"],
                    "note": "Advanced tools - specialized functionality"
                }
            },
            "categories_summary": {
                cat: {
                    "icon": category_metadata[cat]["icon"],
                    "name": category_metadata[cat]["name"],
                    "tools": tools
                }
                for cat, tools in categories_in_lite.items()
            },
            # Quick workflows (v2.5.0+) - progressive disclosure
            "workflows": {
                "new_agent": ["onboard()", "process_agent_update(complexity=0.5)", "list_agents()"],
                "check_in": ["process_agent_update(response_text='...', complexity=0.5)"],
                "save_insight": ["leave_note(summary='...')", "OR store_knowledge_graph(summary='...', tags=[...])"],
                "find_info": ["search_knowledge_graph(query='...')", "OR search_knowledge_graph(tags=[...])"]
            },
            # Common signatures (type hints at a glance)
            "signatures": {
                "process_agent_update": "(complexity:float, response_text?:str, confidence?:float, task_type?:str)",
                "store_knowledge_graph": "(summary:str, tags?:list, severity?:str, details?:str)",
                "search_knowledge_graph": "(query?:str, tags?:list, limit?:int, include_details?:bool)",
                "leave_note": "(summary:str, tags?:list)"
            },
            "more": "list_tools(lite=false) for all tools with full category details",
            "tip": "describe_tool(tool_name=...) for parameter details and examples",
            "quick_start": "Start with onboard() → process_agent_update() → explore categories"
        }
        
        # Add first-time hint for new agents
        if is_new_agent:
            response_data["first_time"] = {
                "hint": "👋 First time here? Start with onboard() to create your identity!",
                "next_step": "Call onboard() - no parameters needed, it gives you everything you need."
            }
        
        # Add progressive metadata if enabled
        if progressive:
            response_data["progressive"] = {
                "enabled": True,
                "ordered_by": "usage_frequency",
                "window": "7 days"
            }
        
        return success_response(response_data)
    
    tier_counts = {
        "essential": sum(1 for t in tools_list if t.get("tier") == "essential"),
        "common": sum(1 for t in tools_list if t.get("tier") == "common"),
        "advanced": sum(1 for t in tools_list if t.get("tier") == "advanced"),
    }
    
    # PROGRESSIVE GROUPING: Group tools by usage frequency (full mode only)
    progressive_sections = None
    if progressive:
        def group_tools_progressively(tools: List[Dict[str, Any]], usage_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
            """Group tools into Most Used / Commonly Used / Available."""
            most_used = []
            commonly_used = []
            available = []
            
            for tool in tools:
                tool_name = tool["name"]
                call_count = usage_data.get(tool_name, {}).get("call_count", 0)
                
                if call_count > 10:
                    most_used.append(tool["name"])
                elif call_count > 0:
                    commonly_used.append(tool["name"])
                else:
                    available.append(tool["name"])
            
            return {
                "most_used": {
                    "tools": most_used,
                    "count": len(most_used),
                    "threshold": ">10 calls/week"
                },
                "commonly_used": {
                    "tools": commonly_used,
                    "count": len(commonly_used),
                    "threshold": "1-10 calls/week"
                },
                "available": {
                    "tools": available,
                    "count": len(available),
                    "threshold": "0 calls or new"
                }
            }
        
        try:
            if not usage_data:  # Get if not already fetched
                usage_data = get_usage_data()
            progressive_sections = group_tools_progressively(tools_list, usage_data)
        except Exception:
            pass  # Graceful degradation - skip grouping if stats unavailable
    
    tools_info = {
        "success": True,
        "server_version": mcp_server.SERVER_VERSION,
        "tools": tools_list,
        "tiers": {
            "essential": list(TOOL_TIERS["essential"]),
            "common": list(TOOL_TIERS["common"]),
            "advanced": list(TOOL_TIERS["advanced"]),
        },
        "tier_counts": tier_counts,
        "filter_applied": {
            "essential_only": essential_only,
            "include_advanced": include_advanced,
            "tier_filter": tier_filter,
            "progressive": progressive,
        },
        "categories": {
            "identity": {
                "name": "🚀 Identity & Onboarding",
                "description": "Get started - create your identity and set up your session",
                "tools": ["onboard", "identity"],
                "priority": 1,
                "for_new_agents": True
            },
            "core": {
                "name": "💬 Core Governance",
                "description": "Main tools for sharing work and getting feedback",
                "tools": ["process_agent_update", "get_governance_metrics", "simulate_update"],
                "priority": 2,
                "for_new_agents": True
            },
            "lifecycle": {
                "name": "👥 Agent Lifecycle",
                "description": "Manage agents, view metadata, and handle agent states",
                "tools": ["list_agents", "get_agent_metadata", "update_agent_metadata", "archive_agent", "delete_agent", "archive_old_test_agents", "mark_response_complete", "direct_resume_if_safe"],
                "priority": 3,
                "for_new_agents": False
            },
            "knowledge": {
                "name": "💡 Knowledge Graph",
                "description": "Store and search discoveries, insights, and notes",
                "tools": ["store_knowledge_graph", "search_knowledge_graph", "get_knowledge_graph", "list_knowledge_graph", "get_discovery_details", "leave_note", "update_discovery_status_graph"],
                "priority": 4,
                "for_new_agents": False
            },
            "observability": {
                "name": "👁️ Observability",
                "description": "Monitor agents, compare patterns, and detect anomalies",
                "tools": ["observe_agent", "compare_agents", "compare_me_to_similar", "detect_anomalies", "aggregate_metrics"],
                "priority": 5,
                "for_new_agents": False
            },
            "export": {
                "name": "📊 Export & History",
                "description": "Export governance history and system data",
                "tools": ["get_system_history", "export_to_file"],
                "priority": 6,
                "for_new_agents": False
            },
            "config": {
                "name": "⚙️ Configuration",
                "description": "Configure thresholds and system settings",
                "tools": ["get_thresholds", "set_thresholds"],
                "priority": 7,
                "for_new_agents": False
            },
            "admin": {
                "name": "🔧 Admin & Diagnostics",
                "description": "System administration, health checks, and diagnostics",
                "tools": ["reset_monitor", "get_server_info", "health_check", "check_calibration", "update_calibration_ground_truth", "get_telemetry_metrics", "get_tool_usage_stats", "list_tools", "describe_tool", "cleanup_stale_locks", "backfill_calibration_from_dialectic", "validate_file_path"],
                "priority": 8,
                "for_new_agents": False
            },
            "workspace": {
                "name": "📁 Workspace",
                "description": "Workspace health and file validation",
                "tools": ["get_workspace_health"],
                "priority": 9,
                "for_new_agents": False
            },
            "dialectic": {
                "name": "💭 Dialectic",
                "description": "View archived dialectic sessions",
                "tools": ["get_dialectic_session"],
                "priority": 10,
                "for_new_agents": False
            }
        },
        "category_descriptions": {
            "identity": "🚀 Start here! Create your identity and get ready-to-use templates",
            "core": "💬 Your main tools - share work, get feedback, check your state",
            "lifecycle": "👥 Manage agents and view agent metadata",
            "knowledge": "💡 Store discoveries, search insights, leave notes",
            "observability": "👁️ Monitor agents, compare patterns, detect issues",
            "export": "📊 Export history and system data",
            "config": "⚙️ Configure thresholds and settings",
            "admin": "🔧 System administration and diagnostics",
            "workspace": "📁 Workspace health and validation",
            "dialectic": "💭 View archived dialectic sessions"
        },
        "getting_started": {
            "for_new_agents": [
                {
                    "category": "identity",
                    "tools": ["onboard", "identity"],
                    "why": "Create your identity and get started"
                },
                {
                    "category": "core",
                    "tools": ["process_agent_update", "get_governance_metrics"],
                    "why": "Share your work and check your state"
                }
            ],
            "next_steps": [
                {
                    "category": "lifecycle",
                    "tools": ["list_agents"],
                    "why": "See who else is here"
                },
                {
                    "category": "knowledge",
                    "tools": ["store_knowledge_graph", "leave_note"],
                    "why": "Save discoveries and insights"
                }
            ]
        },
        "workflows": workflows,
        "relationships": tool_relationships,
        "note": "Use this tool to discover available capabilities. MCP protocol also provides tool definitions, but this provides categorized overview useful for onboarding. Use 'essential_only=true' or 'tier=essential' to reduce cognitive load by showing only core workflow tools (~10 tools).",
        "quick_start": {
            "new_agent": [
                "1. Call onboard() - creates identity + gives you templates",
                "2. Save client_session_id from response",
                "3. Call process_agent_update() to share your work",
                "4. Use identity(name='...') to name yourself",
                "5. Explore other categories as needed"
            ],
            "categories_to_explore": [
                "🚀 Identity & Onboarding - Start here!",
                "💬 Core Governance - Your main tools",
                "👥 Agent Lifecycle - See who else is here",
                "💡 Knowledge Graph - Save discoveries"
            ]
        },
        "options": {
            "lite_mode": "Use list_tools(lite=true) for minimal response (~2KB vs ~15KB) - better for local/smaller models",
            "describe_tool": "Use describe_tool(tool_name, lite=true) for simplified schemas with fewer parameters"
        },
        # Visual tool relationship map (v2.5.0+)
        "tool_map": """
┌─────────────────────────────────────────────────────────────────────┐
│                        TOOL RELATIONSHIP MAP                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  🚀 START                                                           │
│     │                                                               │
│     ▼                                                               │
│  ┌─────────┐                                                        │
│  │ onboard │──────────────────┐                                     │
│  └────┬────┘                  │                                     │
│       │                       ▼                                     │
│       │              ┌──────────────┐                               │
│       │              │   identity   │ ◄── name yourself             │
│       │              └──────────────┘                               │
│       │                                                             │
│       ▼                                                             │
│  ┌────────────────────────┐       ┌─────────────────────────────┐  │
│  │ process_agent_update   │◄─────►│ get_governance_metrics      │  │
│  │ (main check-in)        │       │ (view state)                │  │
│  └───────────┬────────────┘       └─────────────────────────────┘  │
│              │                                                      │
│              ├───────────────────────────────────────┐              │
│              │                                       │              │
│              ▼                                       ▼              │
│  ┌───────────────────────┐              ┌────────────────────────┐ │
│  │ KNOWLEDGE GRAPH       │              │ OBSERVABILITY          │ │
│  ├───────────────────────┤              ├────────────────────────┤ │
│  │ store_knowledge_graph │              │ list_agents            │ │
│  │ search_knowledge_graph│              │ observe_agent          │ │
│  │ leave_note            │              │ compare_agents         │ │
│  │ get_discovery_details │              │ detect_anomalies       │ │
│  └───────────────────────┘              └────────────────────────┘ │
│                                                                     │
│  ─────────────────────────────────────────────────────────────────  │
│  ADMIN/CONFIG: health_check, get_thresholds, describe_tool         │
│  EXPORT: get_system_history, export_to_file                        │
│  LIFECYCLE: archive_agent, delete_agent, update_agent_metadata     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
"""
    }

    # Calculate total_tools dynamically to avoid discrepancies
    tools_info["total_tools"] = len(tools_info["tools"])
    
    # Add progressive disclosure metadata if enabled
    if progressive:
        tools_info["progressive"] = {
            "enabled": True,
            "ordered_by": "usage_frequency",
            "window": "7 days"
        }
        if progressive_sections:
            tools_info["sections"] = progressive_sections
    
    return success_response(tools_info)


@mcp_tool("describe_tool", timeout=10.0, rate_limit_exempt=True)
async def handle_describe_tool(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Return full details for a single tool (full description + full schema) on demand.
    This is intended to keep MCP tool lists compact while still enabling deep discovery.
    
    LITE MODE: Use lite=true to get a simplified schema suitable for smaller models.
    Shows only required params + key optional params with simple examples.
    """
    try:
        tool_name = (arguments.get("tool_name") or "").strip()
        if not tool_name:
            return [error_response(
                "tool_name is required",
                recovery={
                    "action": "Call list_tools to find the canonical name, then call describe_tool(tool_name=...)",
                    "related_tools": ["list_tools"],
                },
            )]

        include_schema = arguments.get("include_schema", True)
        include_full_description = arguments.get("include_full_description", True)
        # LITE-FIRST: Simpler schemas by default for local models
        lite = arguments.get("lite", True)

        from src.tool_schemas import get_tool_definitions
        tools = get_tool_definitions(verbosity="full")
        tool = next((t for t in tools if t.name == tool_name), None)
        if tool is None:
            return [error_response(
                f"Unknown tool: {tool_name}",
                recovery={
                    "action": "Call list_tools to see available tool names",
                    "related_tools": ["list_tools"],
                },
                context={"tool_name": tool_name},
            )]

        description = tool.description
        if not include_full_description:
            description = (tool.description or "").splitlines()[0].strip() if tool.description else ""

        # Helper function to get common patterns (shared between both branches)
        def get_common_patterns(tool_name: str) -> dict:
                """Get common usage patterns for a tool."""
                patterns = {
                    "process_agent_update": {
                        "basic": "process_agent_update(complexity=0.5)  # identity auto-injected",
                        "with_response": "process_agent_update(response_text=\"Fixed bug\", complexity=0.3, confidence=0.9)",
                        "task_type": "process_agent_update(complexity=0.7, task_type=\"divergent\")"
                    },
                    "store_knowledge_graph": {
                        "insight": "store_knowledge_graph(summary=\"Key insight about X\", tags=[\"insight\"])",
                        "bug_found": "store_knowledge_graph(summary=\"Bug in module Y\", tags=[\"bug\"], severity=\"medium\")",
                        "question": "store_knowledge_graph(summary=\"How does X work?\", discovery_type=\"question\")"
                    },
                    "search_knowledge_graph": {
                        "by_tag": "search_knowledge_graph(tags=[\"bug\"], limit=10)",
                        "by_type": "search_knowledge_graph(discovery_type=\"insight\", limit=5)",
                        "full_text": "search_knowledge_graph(query=\"authentication\", limit=10)"
                    },
                    "get_governance_metrics": {
                        "check_state": "get_governance_metrics()  # uses bound identity",
                        "with_history": "get_governance_metrics(include_history=true)"
                    },
                    "identity": {
                        "check_identity": "identity()  # Shows current bound identity",
                        "name_yourself": "identity(name=\"my_agent\")  # Set your display name",
                        "after_session_restart": "identity()  # Recover identity after LLM context loss"
                    },
                    "list_agents": {
                        "all_agents": "list_agents()  # List all agents with metadata",
                        "active_only": "list_agents(status_filter=\"active\")  # Only active agents",
                        "with_metrics": "list_agents(include_metrics=true)  # Include governance metrics",
                        "lite_view": "list_agents(summary_only=true)  # Minimal summary view"
                    },
                    "observe_agent": {
                        "basic_observation": "observe_agent(agent_id=\"my_agent\")  # Analyze agent patterns",
                        "with_history": "observe_agent(agent_id=\"my_agent\", include_history=true)  # Include historical patterns",
                        "pattern_analysis": "observe_agent(agent_id=\"my_agent\", analyze_patterns=true)  # Deep pattern analysis"
                    }
                }
                return patterns.get(tool_name, {})

        # === LITE MODE: Simplified schema for smaller models ===
        if lite:
            from .validators import TOOL_PARAM_SCHEMAS
            lite_schema = TOOL_PARAM_SCHEMAS.get(tool_name)
            
            if lite_schema:
                # Use our simplified schema
                required = lite_schema.get("required", [])
                optional = lite_schema.get("optional", {})
                example = lite_schema.get("example", "")
                
                # Build simple param list
                from .validators import DISCOVERY_TYPE_ALIASES
                params_simple = []
                for param in required:
                    params_simple.append(f"{param} (required)")
                for param, spec in list(optional.items())[:5]:  # Top 5 optional
                    param_type = spec.get("type", "any")
                    default = spec.get("default")
                    values = spec.get("values", [])
                    if values:
                        # Special handling for discovery_type to show key aliases
                        if param == "discovery_type" and values:
                            # Show common aliases: ticket→improvement, bug→bug_found, etc.
                            common_aliases = {
                                "bug_found": "bug, fix, issue",
                                "improvement": "ticket, task, implementation",
                                "insight": "observation, finding",
                                "note": "memo, comment (default)",
                                "exploration": "experiment, research"
                            }
                            alias_hints = [f"{k} ({v})" for k, v in common_aliases.items() if k in values]
                            if alias_hints:
                                params_simple.append(f"{param}: one of {values} (common aliases: {', '.join(alias_hints)})")
                            else:
                                params_simple.append(f"{param}: one of {values}")
                        else:
                            params_simple.append(f"{param}: one of {values}")
                    elif default is not None:
                        params_simple.append(f"{param}: {param_type} (default: {default})")
                    else:
                        params_simple.append(f"{param}: {param_type}")
                
                # Get common patterns
                common_patterns = get_common_patterns(tool_name)

                # Get parameter aliases for discoverability
                from .validators import PARAM_ALIASES
                tool_aliases = PARAM_ALIASES.get(tool_name, {})

                # UX FIX (Feb 2026): Add tier information to help agents understand tool complexity
                from src.tool_modes import TOOL_TIERS, TOOL_OPERATIONS
                tool_tier = "common"  # Default
                if tool_name in TOOL_TIERS["essential"]:
                    tool_tier = "essential"
                elif tool_name in TOOL_TIERS["advanced"]:
                    tool_tier = "advanced"

                tier_guidance = {
                    "essential": "Core tool - regularly used for basic workflows",
                    "common": "Standard tool - commonly used for specific tasks",
                    "advanced": "Advanced tool - use when you need specialized functionality"
                }

                response_data = {
                    "tool": tool_name,
                    "description": (description or "").splitlines()[0].strip(),
                    "tier": tool_tier,
                    "tier_note": tier_guidance.get(tool_tier, ""),
                    "operation": TOOL_OPERATIONS.get(tool_name, "read"),  # read/write/admin
                    "parameters": params_simple,
                    "example": example,
                    "note": "Lite mode - use describe_tool(tool_name=..., lite=false) for full schema"
                }

                if tool_aliases:
                    # Format: {"content": "summary"} → "content → summary"
                    response_data["parameter_aliases"] = {
                        alias: f"→ {canonical}" for alias, canonical in tool_aliases.items()
                    }

                if common_patterns:
                    response_data["common_patterns"] = common_patterns

                return success_response(response_data)
            else:
                # Fallback: extract from inputSchema
                schema = tool.inputSchema or {}
                properties = schema.get("properties", {})
                required = schema.get("required", [])
                
                params_simple = []
                for param in required:
                    params_simple.append(f"{param} (required)")
                for param, prop in list(properties.items())[:8]:
                    if param not in required:
                        ptype = prop.get("type", "any")
                        params_simple.append(f"{param}: {ptype}")
                
                # Get common patterns using shared helper
                common_patterns = get_common_patterns(tool_name)

                # Get parameter aliases for discoverability
                from .validators import PARAM_ALIASES
                tool_aliases = PARAM_ALIASES.get(tool_name, {})

                response_data = {
                    "tool": tool_name,
                    "description": (description or "").splitlines()[0].strip(),
                    "parameters": params_simple,
                    "note": "Lite mode - use describe_tool(tool_name=..., lite=false) for full schema"
                }

                if tool_aliases:
                    response_data["parameter_aliases"] = {
                        alias: f"→ {canonical}" for alias, canonical in tool_aliases.items()
                    }

                if common_patterns:
                    response_data["common_patterns"] = common_patterns

                return success_response(response_data)

        return success_response({
            "tool": {
                "name": tool.name,
                "description": description,
                "inputSchema": tool.inputSchema if include_schema else None,
            }
        })
    except Exception as e:
        return [error_response(f"Error describing tool: {str(e)}")]


@mcp_tool("get_workspace_health", timeout=20.0, rate_limit_exempt=True)
async def handle_get_workspace_health(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle get_workspace_health tool - comprehensive workspace health status"""
    from src.workspace_health import get_workspace_health
    
    try:
        health_data = get_workspace_health()
        return success_response(health_data)
    except Exception as e:
        import traceback
        import sys
        # SECURITY: Log full traceback internally but sanitize for client
        logger.error(f"Error checking workspace health: {e}", exc_info=True)
        return [error_response(
            f"Error checking workspace health: {str(e)}",
            recovery={
                "action": "Check system configuration and try again",
                "related_tools": ["health_check", "get_server_info"]
            }
        )]


@mcp_tool("debug_request_context", timeout=5.0, rate_limit_exempt=True)
async def handle_debug_request_context(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Debug request context - shows raw diagnostic info about session, identity, and bindings.
    
    SIMPLIFIED: Just shows what's in memory - no complex logic, no guessing.
    Use this to understand what the server sees, not to determine your identity.
    For identity, use identity() instead.
    """
    import hashlib
    from datetime import datetime
    from . import TOOL_HANDLERS
    from .identity_v2 import _derive_session_key

    # Get raw diagnostic info - no complex logic
    # NOTE (Dec 2025): identity_v2 is the AUTHORITATIVE source of truth for identity.
    # Context agent_id was resolved via identity_v2.resolve_session_identity() at dispatch entry.
    from .context import get_context_agent_id, get_context_session_key

    context_agent_id = get_context_agent_id()  # Authoritative (from identity_v2)
    context_session_key = get_context_session_key()
    session_key = context_session_key or _derive_session_key(arguments)

    # Get tool registry info
    tool_names = sorted(TOOL_HANDLERS.keys())
    tool_count = len(tool_names)
    registry_hash = hashlib.md5(",".join(tool_names).encode()).hexdigest()[:8]

    # Detect transport
    import sys
    argv = [str(a) for a in getattr(sys, "argv", [])]
    is_http = any("mcp_server.py" in a for a in argv)
    is_stdio = any("mcp_server_std.py" in a for a in argv)
    transport = "http" if is_http else ("stdio" if is_stdio else "unknown")

    # Get validator info
    validator_version = "1.0.0"
    try:
        from .validators import VALIDATOR_VERSION
        validator_version = VALIDATOR_VERSION
    except (ImportError, AttributeError):
        pass

    # Diagnostic: Check what bindings exist in LEGACY identity module (for debugging)
    # NOTE: identity_v2 is now authoritative - legacy bindings shown for diagnostic purposes only
    legacy_bindings = {}
    legacy_bindings_count = 0
    uuid_prefix_keys = []
    uuid_prefix_mappings = {}
    try:
        from .identity import _session_identities, _uuid_prefix_index
        for k, v in list(_session_identities.items())[:10]:  # Show first 10
            agent_id = v.get("bound_agent_id")
            if agent_id:
                legacy_bindings[k] = agent_id[:8] + "..."
            else:
                legacy_bindings[k] = "None"
        uuid_prefix_keys = list(_uuid_prefix_index.keys())[:10]  # Show first 10
        uuid_prefix_mappings = {k: _uuid_prefix_index[k][:8] + "..." for k in uuid_prefix_keys}
        legacy_bindings_count = len(_session_identities)
    except Exception as e:
        import traceback
        legacy_bindings = {"error": str(e), "traceback": traceback.format_exc()}

    # SIMPLIFIED: Just show raw diagnostics - no complex logic
    result = {
        "success": True,
        "timestamp": datetime.now().isoformat(),
        "transport": transport,
        "session": {
            "session_key": session_key,
            "context_session_key": context_session_key,
            "context_agent_id": context_agent_id,
            "note": "context_agent_id is AUTHORITATIVE (from identity_v2). Use identity() to check your identity."
        },
        "diagnostics": {
            "legacy_bindings_in_memory": legacy_bindings,
            "legacy_bindings_count": legacy_bindings_count,
            "legacy_uuid_prefix_index": {
                "keys": uuid_prefix_keys,
                "mappings": uuid_prefix_mappings,
                "most_recent": uuid_prefix_keys[-1] if uuid_prefix_keys else None
            },
            "note": "Legacy identity.py bindings shown for debugging. identity_v2 is authoritative (via context)."
        },
        "identity_injection": {
            "enabled": True,
            "injection_point": "dispatch_tool (before validation)",
            "auto_create_enabled": True,
        },
        "tool_registry": {
            "count": tool_count,
            "sample_tools": tool_names[:10],
            "registry_hash": registry_hash,
        },
        "validator": {
            "version": validator_version,
        },
        "server": {
            "version": "2.5.7",  # Hardcoded - this is just diagnostics
        },
        "recommendation": "For identity, use identity() instead. This tool is for debugging session/context issues."
    }

    return success_response(result)


@mcp_tool("validate_file_path", timeout=5.0, rate_limit_exempt=True)
async def handle_validate_file_path(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Validate file path against project policies (anti-proliferation).
    
    Use this tool BEFORE creating files to check if they violate policy.
    
    Policies checked:
    - Test scripts (test_*.py, demo_*.py) must be in tests/ directory
    - Markdown files in docs/analysis/, docs/fixes/, etc. should use store_knowledge_graph() instead
    - New markdown files should be on approved list or ≥500 words
    
    Returns:
    - "valid": Path is OK
    - "warning": Path violates policy (non-blocking, but should be reconsidered)
    """
    file_path = arguments.get("file_path")
    
    if not file_path:
        return [error_response(
            "file_path parameter is required",
            details={"error_type": "missing_parameter", "parameter": "file_path"},
            recovery={
                "action": "Provide file_path parameter",
                "workflow": ["1. Call validate_file_path with file_path parameter", "2. Review response before creating file"]
            }
        )]
    
    # Validate using policy checker
    warning, error = validate_file_path_policy(file_path)
    
    if error:
        return [error]
    
    if warning:
        # FRICTION FIX: Provide clearer guidance about when to use knowledge graph vs markdown
        guidance = {
            "use_knowledge_graph_for": [
                "Insights and discoveries",
                "Bug findings and security issues",
                "Pattern observations",
                "Questions and answers",
                "Quick notes and learnings"
            ],
            "use_markdown_for": [
                "Reference documentation (guides, API docs)",
                "Project README files",
                "Changelogs and version history",
                "Approved documentation files"
            ],
            "decision_heuristic": "If it's an insight/discovery → knowledge graph. If it's reference docs → markdown (and must be on approved list)."
        }
        
        return success_response({
            "valid": False,
            "status": "warning",
            "warning": warning,
            "file_path": file_path,
            "recommendation": "Consider using store_knowledge_graph() for insights/discoveries, or consolidate into existing approved docs",
            "guidance": guidance,
            "related_tools": ["store_knowledge_graph", "list_knowledge_graph", "search_knowledge_graph"],
            "quick_action": "For insights/discoveries, use: store_knowledge_graph(discovery_type='insight', summary='...', tags=[...])"
        })
    
    return success_response({
        "valid": True,
        "status": "ok",
        "file_path": file_path,
        "message": "File path complies with project policies"
    })


@mcp_tool("get_connection_status", timeout=5.0, rate_limit_exempt=True)
async def handle_get_connection_status(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Get MCP connection status and tool availability.
    
    Helps agents verify they're connected to the MCP server and can use tools.
    Especially useful for detecting when tools are not available (e.g., wrong chatbox in Mac ChatGPT).
    """
    from .shared import get_mcp_server
    mcp_server = get_mcp_server()
    
    # Check if we can access server
    server_available = mcp_server is not None
    
    # Check transport type
    import sys
    argv = [str(a) for a in getattr(sys, "argv", [])]
    is_http = any("mcp_server.py" in a for a in argv)
    is_stdio = any("mcp_server_std.py" in a for a in argv)
    transport = "HTTP" if is_http else ("STDIO" if is_stdio else "unknown")
    
    # Check if tools are available (basic check)
    tools_available = False
    try:
        from . import TOOL_HANDLERS
        tools_available = len(TOOL_HANDLERS) > 0
    except Exception:
        pass
    
    # Get current session identity if available
    session_bound = False
    resolved_agent_id = None
    resolved_uuid = None
    try:
        from .context import get_context_agent_id
        context_id = get_context_agent_id()
        if context_id:
            session_bound = True
            resolved_uuid = context_id
            # Try to get display name
            if context_id in mcp_server.agent_metadata:
                meta = mcp_server.agent_metadata[context_id]
                resolved_agent_id = getattr(meta, 'structured_id', None) or getattr(meta, 'label', None)
    except Exception:
        pass
    
    status = "connected" if (server_available and tools_available) else "disconnected"
    
    return success_response({
        "status": status,
        "server_available": server_available,
        "tools_available": tools_available,
        "transport": transport,
        "session_bound": session_bound,
        "resolved_agent_id": resolved_agent_id,
        "resolved_uuid": (resolved_uuid[:8] + "...") if resolved_uuid else None,
        "message": "✅ Tools Connected" if status == "connected" else "❌ Tools Not Available",
        "recommendation": "You can use MCP tools" if status == "connected" else "Check MCP server connection and configuration"
    }, arguments=arguments)


# REMOVED: quick_start - deprecated Dec 2025, identity auto-binds on first tool call
# Use identity(name="...") to set display name, or just call any tool (identity auto-creates)
