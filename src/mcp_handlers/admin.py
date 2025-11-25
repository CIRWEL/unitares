"""
Admin tool handlers.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
import json
import sys
from datetime import datetime
from pathlib import Path
from .utils import success_response, error_response, require_agent_id

# Import from mcp_server_std module
if 'src.mcp_server_std' in sys.modules:
    mcp_server = sys.modules['src.mcp_server_std']
else:
    import src.mcp_server_std as mcp_server
import sys


async def handle_get_server_info(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle get_server_info tool"""
    import time
    # Import from mcp_server_std module (handles both direct import and module access)
    if 'src.mcp_server_std' in sys.modules:
        mcp_server = sys.modules['src.mcp_server_std']
    else:
        import src.mcp_server_std as mcp_server
    
    if mcp_server.PSUTIL_AVAILABLE:
        import psutil
        
        # Get all MCP server processes
        server_processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'status']):
                try:
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline and any('mcp_server_std.py' in str(arg) for arg in cmdline):
                        pid = proc.info['pid']
                        create_time = proc.info.get('create_time', 0)
                        uptime_seconds = time.time() - create_time
                        uptime_minutes = int(uptime_seconds / 60)
                        uptime_hours = int(uptime_minutes / 60)
                        
                        server_processes.append({
                            "pid": pid,
                            "is_current": pid == mcp_server.CURRENT_PID,
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
            current_proc = psutil.Process(mcp_server.CURRENT_PID)
            current_uptime = time.time() - current_proc.create_time()
        except:
            current_uptime = 0
    else:
        server_processes = [{"error": "psutil not available - cannot enumerate processes"}]
        current_uptime = 0
    
    current_uptime_minutes = int(current_uptime / 60)
    current_uptime_hours = int(current_uptime_minutes / 60)
    
    return success_response({
        "server_version": mcp_server.SERVER_VERSION,
        "build_date": mcp_server.SERVER_BUILD_DATE,
        "current_pid": mcp_server.CURRENT_PID,
        "current_uptime_seconds": int(current_uptime),
        "current_uptime_formatted": f"{current_uptime_hours}h {current_uptime_minutes % 60}m",
        "total_server_processes": len([p for p in server_processes if "error" not in p]),
        "server_processes": server_processes,
        "pid_file_exists": mcp_server.PID_FILE.exists(),
        "max_keep_processes": 72,
        "health": "healthy"
    })


async def handle_health_check(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle health_check tool"""
    from src.calibration import calibration_checker
    from src.telemetry import telemetry_collector
    from src.audit_log import audit_logger
    from src.knowledge_layer import get_knowledge_manager
    
    checks = {}
    
    # Check calibration
    try:
        pending = calibration_checker.get_pending_updates()
        checks["calibration"] = {
            "status": "healthy",
            "pending_updates": pending
        }
    except Exception as e:
        checks["calibration"] = {
            "status": "error",
            "error": str(e)
        }
    
    # Check telemetry/audit log
    try:
        log_exists = audit_logger.log_file.exists()
        checks["telemetry"] = {
            "status": "healthy" if log_exists else "warning",
            "audit_log_exists": log_exists
        }
    except Exception as e:
        checks["telemetry"] = {
            "status": "error",
            "error": str(e)
        }
    
    # Check knowledge layer
    try:
        manager = get_knowledge_manager()
        stats = manager.get_stats()
        checks["knowledge"] = {
            "status": "healthy",
            "agents_with_knowledge": stats["total_agents"]
        }
    except Exception as e:
        checks["knowledge"] = {
            "status": "error",
            "error": str(e)
        }
    
    # Check data directory
    try:
        data_dir = Path(mcp_server.project_root) / "data"
        data_dir_exists = data_dir.exists()
        checks["data_directory"] = {
            "status": "healthy" if data_dir_exists else "warning",
            "exists": data_dir_exists
        }
    except Exception as e:
        checks["data_directory"] = {
            "status": "error",
            "error": str(e)
        }
    
    # Overall health status
    all_healthy = all(c.get("status") == "healthy" for c in checks.values())
    overall_status = "healthy" if all_healthy else "degraded"
    
    return success_response({
        "status": overall_status,
        "version": "2.0.0",
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    })


async def handle_check_calibration(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle check_calibration tool"""
    from src.calibration import calibration_checker
    
    is_calibrated, metrics = calibration_checker.check_calibration()
    
    return success_response({
        "is_calibrated": is_calibrated,
        "metrics": metrics,
        "note": "Calibration checks if confidence estimates match actual accuracy. Update ground truth via update_calibration_ground_truth tool."
    })


async def handle_update_calibration_ground_truth(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle update_calibration_ground_truth tool"""
    from src.calibration import calibration_checker
    
    confidence = arguments.get("confidence")
    predicted_correct = arguments.get("predicted_correct")
    actual_correct = arguments.get("actual_correct")
    
    if confidence is None or predicted_correct is None or actual_correct is None:
        return [error_response("Missing required parameters: confidence, predicted_correct, actual_correct")]
    
    try:
        calibration_checker.update_ground_truth(
            confidence=float(confidence),
            predicted_correct=bool(predicted_correct),
            actual_correct=bool(actual_correct)
        )
        
        # Save calibration state after update
        calibration_checker.save_state()
        
        return success_response({
            "message": "Ground truth updated successfully",
            "pending_updates": calibration_checker.get_pending_updates()
        })
    except Exception as e:
        return [error_response(str(e))]


async def handle_get_telemetry_metrics(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle get_telemetry_metrics tool"""
    from src.telemetry import TelemetryCollector
    
    telemetry = TelemetryCollector()
    
    agent_id = arguments.get("agent_id")
    window_hours = arguments.get("window_hours", 24)
    
    skip_metrics = telemetry.get_skip_rate_metrics(agent_id, window_hours)
    conf_dist = telemetry.get_confidence_distribution(agent_id, window_hours)
    calibration_metrics = telemetry.get_calibration_metrics()
    suspicious = telemetry.detect_suspicious_patterns(agent_id)
    
    return success_response({
        "agent_id": agent_id or "all_agents",
        "window_hours": window_hours,
        "skip_rate_metrics": skip_metrics,
        "confidence_distribution": conf_dist,
        "calibration": calibration_metrics,
        "suspicious_patterns": suspicious
    })


async def handle_reset_monitor(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle reset_monitor tool"""
    from .utils import require_agent_id
    import sys
    if 'src.mcp_server_std' in sys.modules:
        mcp_server = sys.modules['src.mcp_server_std']
    else:
        import src.mcp_server_std as mcp_server
    
    agent_id, error = require_agent_id(arguments)
    if error:
        return error
    
    if agent_id in mcp_server.monitors:
        del mcp_server.monitors[agent_id]
        message = f"Monitor reset for agent: {agent_id}"
    else:
        message = f"Monitor not found for agent: {agent_id} (may not be loaded)"
    
    return success_response({
        "message": message,
        "agent_id": agent_id
    })


async def handle_cleanup_stale_locks(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Clean up stale lock files that are no longer held by active processes.
    
    Args:
        max_age_seconds: Maximum age in seconds before considering stale (default: 300 = 5 minutes)
        dry_run: If True, only report what would be cleaned (default: False)
    
    Returns:
        Cleanup statistics
    """
    try:
        from lock_cleanup import cleanup_stale_state_locks
        
        max_age = arguments.get('max_age_seconds', 300.0)
        dry_run = arguments.get('dry_run', False)
        
        project_root = Path(__file__).parent.parent.parent
        result = cleanup_stale_state_locks(project_root=project_root, max_age_seconds=max_age, dry_run=dry_run)
        
        return [success_response({
            "success": True,
            "cleaned": result['cleaned'],
            "kept": result['kept'],
            "errors": result['errors'],
            "dry_run": dry_run,
            "max_age_seconds": max_age,
            "cleaned_locks": result.get('cleaned_locks', []),
            "kept_locks": result.get('kept_locks', []),
            "message": f"Cleaned {result['cleaned']} stale lock(s), kept {result['kept']} active lock(s)"
        })]
    except Exception as e:
        return [error_response(f"Error cleaning stale locks: {str(e)}")]


async def handle_list_tools(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle list_tools tool - runtime tool introspection"""
    if 'src.mcp_server_std' in sys.modules:
        mcp_server = sys.modules['src.mcp_server_std']
    else:
        import src.mcp_server_std as mcp_server
    
    tools_info = {
        "success": True,
        "server_version": mcp_server.SERVER_VERSION,
        "tools": [
            {"name": "process_agent_update", "description": "Run governance cycle, return decision + metrics"},
            {"name": "get_governance_metrics", "description": "Current state, sampling params, decision stats, stability"},
            {"name": "simulate_update", "description": "Dry-run governance cycle (no persist)"},
            {"name": "get_thresholds", "description": "View current threshold config"},
            {"name": "set_thresholds", "description": "Runtime threshold overrides"},
            {"name": "observe_agent", "description": "Observe agent state with pattern analysis"},
            {"name": "compare_agents", "description": "Compare patterns across multiple agents"},
            {"name": "detect_anomalies", "description": "Scan for unusual patterns across fleet"},
            {"name": "aggregate_metrics", "description": "Fleet-level health overview"},
            {"name": "list_agents", "description": "List all agents with lifecycle metadata"},
            {"name": "get_agent_metadata", "description": "Full metadata for single agent"},
            {"name": "update_agent_metadata", "description": "Update tags and notes"},
            {"name": "archive_agent", "description": "Archive for long-term storage"},
            {"name": "delete_agent", "description": "Delete agent (protected for pioneers)"},
            {"name": "archive_old_test_agents", "description": "Auto-archive stale test agents"},
            {"name": "get_agent_api_key", "description": "Get/generate API key for authentication"},
            {"name": "get_system_history", "description": "Export time-series history (inline)"},
            {"name": "export_to_file", "description": "Export history to JSON/CSV file"},
            {"name": "reset_monitor", "description": "Reset agent state"},
            {"name": "get_server_info", "description": "Server version, PID, uptime, health"},
            {"name": "store_knowledge", "description": "Store knowledge (discovery, pattern, lesson, question)"},
            {"name": "retrieve_knowledge", "description": "Retrieve agent's knowledge record"},
            {"name": "search_knowledge", "description": "Search knowledge across agents with filters"},
            {"name": "list_knowledge", "description": "List all stored knowledge (summary statistics)"},
            {"name": "list_tools", "description": "This tool - runtime introspection for onboarding"},
            {"name": "cleanup_stale_locks", "description": "Clean up stale lock files from crashed/killed processes"},
            {"name": "request_dialectic_review", "description": "Request peer review for paused/critical agent (circuit breaker recovery)"},
            {"name": "submit_thesis", "description": "Submit thesis: 'What I did, what I think happened' (dialectic step 1)"},
            {"name": "submit_antithesis", "description": "Submit antithesis: 'What I observe, my concerns' (dialectic step 2)"},
            {"name": "submit_synthesis", "description": "Submit synthesis proposal during negotiation (dialectic step 3)"},
            {"name": "get_dialectic_session", "description": "Get current state of a dialectic session"},
        ],
        "categories": {
            "core": ["process_agent_update", "get_governance_metrics", "simulate_update"],
            "config": ["get_thresholds", "set_thresholds"],
            "observability": ["observe_agent", "compare_agents", "detect_anomalies", "aggregate_metrics"],
            "lifecycle": ["list_agents", "get_agent_metadata", "update_agent_metadata", "archive_agent", "delete_agent", "archive_old_test_agents", "get_agent_api_key"],
            "export": ["get_system_history", "export_to_file"],
            "knowledge": ["store_knowledge", "retrieve_knowledge", "search_knowledge", "list_knowledge"],
            "dialectic": ["request_dialectic_review", "submit_thesis", "submit_antithesis", "submit_synthesis", "get_dialectic_session"],
            "admin": ["reset_monitor", "get_server_info", "health_check", "check_calibration", "update_calibration_ground_truth", "get_telemetry_metrics", "list_tools", "cleanup_stale_locks"]
        },
        "total_tools": 31,
        "note": "Use this tool to discover available capabilities. MCP protocol also provides tool definitions, but this provides categorized overview useful for onboarding."
    }
    
    return success_response(tools_info)
