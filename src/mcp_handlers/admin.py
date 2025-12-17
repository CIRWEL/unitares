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
    
    # Detect transport from current process args (SSE vs stdio).
    # This prevents SSE from accidentally reporting stdio processes (and vice versa).
    argv = [str(a) for a in getattr(sys, "argv", [])]
    is_sse = any("mcp_server_sse.py" in a for a in argv)
    is_stdio = any("mcp_server_std.py" in a for a in argv)
    transport = "SSE" if is_sse else ("STDIO" if is_stdio else "unknown")
    target_script = "mcp_server_sse.py" if is_sse else ("mcp_server_std.py" if is_stdio else None)

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
                        if not any(('mcp_server_std.py' in str(arg) or 'mcp_server_sse.py' in str(arg)) for arg in cmdline):
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
    pid_file = (project_root / "data" / ".mcp_server_sse.pid") if is_sse else (project_root / "data" / ".mcp_server.pid")

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


@mcp_tool("hello", timeout=10.0, rate_limit_exempt=True)
async def handle_hello(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    🚀 SIMPLEST ONBOARDING - Just provide agent_id to register!
    
    BEHAVIOR:
    1. hello() - Shows last active agent, asks "is this you?"
    2. hello(agent_id="name") - Resume or create that agent
    
    Example: hello(agent_id='qwen_goose_20251215')
    """
    from .shared import get_mcp_server
    mcp_server = get_mcp_server()
    
    # Get parameters
    agent_id = arguments.get("agent_id") or arguments.get("id") or arguments.get("name")
    force_new = arguments.get("force_new", False)
    
    # ELEGANT FIX: If no agent_id, show last active and let model decide
    if not agent_id:
        last_active = get_workspace_last_agent(mcp_server)
        if last_active:
            # Don't auto-continue - just ask
            meta = mcp_server.agent_metadata.get(last_active)
            return success_response({
                "last_active": last_active,
                "message": f"Last active agent: {last_active}",
                "is_this_you": {
                    "yes": f"hello(agent_id=\"{last_active}\")",
                    "no": "hello(agent_id=\"your_name\")"
                },
                "context": {
                    "updates": meta.total_updates if meta else 0,
                    "last_update": meta.last_update[:16] if meta and meta.last_update else "unknown",
                    "tags": meta.tags[:5] if meta and meta.tags else [],
                } if meta else None
            })
        else:
            # No last active - need to pick or create
            candidates = []
            for aid, meta in mcp_server.agent_metadata.items():
                if meta.status in ("active", "waiting_input"):
                    candidates.append({
                        "agent_id": aid,
                        "last_update": meta.last_update[:10] if meta.last_update else "never",
                        "updates": meta.total_updates,
                        "tags": meta.tags[:3] if meta.tags else [],
                    })
            candidates.sort(key=lambda x: (x.get("updates", 0), x.get("last_update", "")), reverse=True)
            
            if candidates:
                # Suggest the most established agent
                top = candidates[0]
                return success_response({
                    "message": "No last active agent. Pick one to continue or create new.",
                    "recommendation": f"hello(agent_id=\"{top['agent_id']}\") - has {top['updates']} updates",
                    "other_candidates": candidates[1:5],
                    "create_new": "hello(agent_id=\"your_name\", force_new=true)",
                    "tip": "Continuing an existing agent builds history. Creating new starts fresh."
                })
            else:
                return [error_response(
                    "Welcome! This workspace has no agents yet.",
                    recovery={
                        "create": "hello(agent_id=\"your_name\")",
                        "example": "hello(agent_id=\"my_agent_20251215\")"
                    }
                )]
    # Clean the agent_id
    agent_id = str(agent_id).strip()
    
    # Check if this is a RETURNING agent
    is_returning = agent_id in mcp_server.agent_metadata
    
    # ANTI-FRAGMENTATION: If creating NEW agent, check for similar existing agents
    # and suggest continuing as one of them instead (unless force_new=True)
    similar_agents = []
    if not is_returning and not force_new:
        # Extract base pattern (remove timestamps like _20251215, _002846, etc)
        import re
        base_pattern = re.sub(r'_\d{8}$|_\d{6}$|_\d{14}$|_\d+$', '', agent_id)
        base_pattern = base_pattern.lower().replace('_', '').replace('-', '')
        
        for existing_id, meta in mcp_server.agent_metadata.items():
            if meta.status in ("active", "waiting_input", "archived"):
                # Check similarity by base pattern
                existing_base = re.sub(r'_\d{8}$|_\d{6}$|_\d{14}$|_\d+$', '', existing_id)
                existing_base = existing_base.lower().replace('_', '').replace('-', '')
                
                # If base patterns are similar (e.g., "claudecode" matches "claudecode")
                if base_pattern and existing_base and (
                    base_pattern in existing_base or 
                    existing_base in base_pattern or
                    base_pattern[:10] == existing_base[:10]  # First 10 chars match
                ):
                    similar_agents.append({
                        "agent_id": existing_id,
                        "status": meta.status,
                        "updates": meta.total_updates,
                        "last_active": meta.last_update[:10] if meta.last_update else "never",
                        "tags": meta.tags[:3] if meta.tags else [],
                    })
        
        # Sort by updates (prefer agents with more history)
        similar_agents.sort(key=lambda x: x.get("updates", 0), reverse=True)
        similar_agents = similar_agents[:5]
    
    # Get or create API key (this also registers the agent)
    from .lifecycle import handle_get_agent_api_key
    api_result = await handle_get_agent_api_key({"agent_id": agent_id})
    
    # Extract API key from result
    api_key = None
    if api_result and api_result[0].text:
        import json
        try:
            data = json.loads(api_result[0].text)
            api_key = data.get("api_key")
        except:
            pass
    
    # Track this agent as last active (for future auto-continuation)
    set_workspace_last_agent(mcp_server, agent_id)
    
    response = {
        "agent_id": agent_id,
        "api_key": api_key,
        "quick_start": {
            "1_check_in": f"process_agent_update(agent_id=\"{agent_id}\")",
            "2_leave_note": f"leave_note(agent_id=\"{agent_id}\", text=\"My note\")",
            "3_see_tools": "list_tools(lite=true)"
        },
    }
    
    if is_returning:
        # RETURNING AGENT - restore their context!
        meta = mcp_server.agent_metadata[agent_id]
        response["welcome"] = f"🎉 Welcome back {agent_id}!"
        response["returning"] = True
        response["your_context"] = {
            "status": meta.status,
            "health": meta.health_status,
            "total_updates": meta.total_updates,
            "last_active": meta.last_update,
            "tags": meta.tags,
            "notes": (meta.notes[:100] + "...") if meta.notes and len(meta.notes) > 100 else meta.notes,
        }
    elif similar_agents:
        # NEW AGENT but similar ones exist - warn about fragmentation!
        response["⚠️_fragmentation_warning"] = {
            "message": "You're creating a NEW agent, but similar ones already exist!",
            "why_this_matters": "Each new agent starts fresh with no history. Consider continuing as an existing agent to build on your learning.",
            "similar_agents": similar_agents,
            "recommendation": f"Instead of '{agent_id}', consider: hello(agent_id=\"{similar_agents[0]['agent_id']}\")",
            "if_intentional": "If you really want a new agent, ignore this warning. Your new agent is created."
        }
        
        # Try to get their recent work
        try:
            from src.knowledge_graph import get_knowledge_graph
            import asyncio
            
            async def get_work():
                graph = await get_knowledge_graph()
                discoveries = await graph.query(agent_id=agent_id, limit=3)
                return [d.summary[:60] + "..." for d in discoveries] if discoveries else []
            
            try:
                loop = asyncio.get_running_loop()
                # Can't await in sync context, skip for now
                response["your_context"]["recent_work"] = "(call process_agent_update for full context)"
            except RuntimeError:
                recent = asyncio.run(get_work())
                if recent:
                    response["your_context"]["recent_work"] = recent
        except:
            pass
        
        response["tip"] = "Your history is intact! Call process_agent_update to see your full learning_context."
    else:
        # NEW AGENT
        response["welcome"] = f"🎉 Hello {agent_id}! You're registered."
        response["returning"] = False
        response["tip"] = "You're new! Use your agent_id in all tool calls."
    
    return success_response(response)


@mcp_tool("who_am_i", timeout=10.0, rate_limit_exempt=True)
async def handle_who_am_i(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    🔍 IDENTITY RECOVERY - Help agents find themselves after session restart.
    
    No arguments needed. Shows recent agents with rich context so you can
    recognize yourself based on your work, tags, and notes.
    
    After finding yourself: hello(agent_id="your_id") to resume.
    """
    from .shared import get_mcp_server
    mcp_server = get_mcp_server()
    
    # First check if already bound
    try:
        from .identity import get_bound_agent_id
        bound = get_bound_agent_id(arguments=arguments)
        if bound:
            meta = mcp_server.agent_metadata.get(bound)
            return success_response({
                "found": True,
                "message": f"You are {bound}!",
                "agent_id": bound,
                "status": meta.status if meta else "unknown",
                "last_update": meta.last_update if meta else None,
                "tip": "Already bound. Use process_agent_update to check in."
            })
    except:
        pass
    
    # Build rich candidate list
    candidates = []
    for aid, meta in mcp_server.agent_metadata.items():
        if meta.status in ("active", "waiting_input"):
            candidate = {
                "agent_id": aid,
                "status": meta.status,
                "health": meta.health_status,
                "updates": meta.total_updates,
                "last_active": meta.last_update[:16] if meta.last_update else "never",
                "tags": meta.tags[:5] if meta.tags else [],
                "notes": (meta.notes[:60] + "...") if meta.notes and len(meta.notes) > 60 else meta.notes,
            }
            candidates.append(candidate)
    
    # Sort by last_update descending
    candidates.sort(key=lambda x: x.get("last_active", ""), reverse=True)
    
    # Get recent work for top candidates
    try:
        from src.knowledge_graph import get_knowledge_graph
        import asyncio
        
        async def enrich_candidates():
            graph = await get_knowledge_graph()
            for c in candidates[:5]:
                try:
                    discoveries = await graph.query(agent_id=c["agent_id"], limit=2)
                    if discoveries:
                        c["recent_work"] = [d.summary[:50] + "..." for d in discoveries]
                except:
                    pass
        
        try:
            loop = asyncio.get_running_loop()
            # In async context - create task
            asyncio.create_task(enrich_candidates())
        except RuntimeError:
            asyncio.run(enrich_candidates())
    except:
        pass
    
    return success_response({
        "bound": False,
        "message": "Looking for yourself? Review recent agents below.",
        "candidates": candidates[:10],
        "recognition_guide": {
            "by_name": "Does the agent_id look familiar?",
            "by_tags": "Do the tags match what you were working on?",
            "by_notes": "Do you recognize the notes?",
            "by_work": "Is that your recent work?",
            "by_time": "Most recent (top) is likely you if just restarted"
        },
        "next_steps": {
            "found_myself": "hello(agent_id='<your_id>') to resume with context",
            "new_agent": "hello(agent_id='<new_name>') to start fresh",
            "need_more_info": "list_agents() for full list with metrics"
        }
    })


@mcp_tool("health_check", timeout=10.0, rate_limit_exempt=True)
async def handle_health_check(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle health_check tool - quick health check of system components"""
    import asyncio
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

    # Check calibration DB (SQLite) - best effort.
    try:
        from src.calibration_db import CalibrationDB
        # Default to governance.db (consolidated), allow override
        db_path = Path(mcp_server.project_root) / "data" / "governance.db"
        override = os.getenv("UNITARES_CALIBRATION_DB_PATH")
        if override:
            db_path = Path(override)
        db = CalibrationDB(db_path)
        info = await loop.run_in_executor(None, db.health_check)
        checks["calibration_db"] = {
            "status": "healthy",
            "backend": "sqlite",
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

    # Check audit DB (SQLite index for audit log) - best effort.
    try:
        from src.audit_db import AuditDB
        # Default to governance.db (consolidated), allow override
        db_path = Path(mcp_server.project_root) / "data" / "governance.db"
        override = os.getenv("UNITARES_AUDIT_DB_PATH")
        if override:
            db_path = Path(override)
        db = AuditDB(db_path)
        info = await loop.run_in_executor(None, db.health_check)
        checks["audit_db"] = {
            "status": "healthy",
            "backend": "sqlite",
            "info": info
        }
    except Exception as e:
        checks["audit_db"] = {
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

    # Check agent metadata backend (SQLite vs JSON) - best effort, kept lightweight.
    try:
        backend = getattr(mcp_server, "_resolve_metadata_backend", lambda: "unknown")()
        if backend == "sqlite":
            # Run SQLite integrity check in executor to avoid blocking.
            from src.metadata_db import AgentMetadataDB
            db_path = getattr(mcp_server, "UNITARES_METADATA_DB_PATH", None)
            if db_path:
                db = AgentMetadataDB(db_path)
                info = await loop.run_in_executor(None, db.health_check)
                checks["agent_metadata"] = {
                    "status": "healthy",
                    "backend": "sqlite",
                    "info": info
                }
            else:
                checks["agent_metadata"] = {
                    "status": "warning",
                    "backend": "sqlite",
                    "info": {"warning": "UNITARES_METADATA_DB_PATH not set in server context"}
                }
        else:
            # JSON backend: report presence of snapshot file.
            data_dir = Path(mcp_server.project_root) / "data"
            metadata_file = data_dir / "agent_metadata.json"
            exists = await loop.run_in_executor(None, metadata_file.exists)
            checks["agent_metadata"] = {
                "status": "healthy" if exists else "warning",
                "backend": backend,
                "info": {"metadata_file": str(metadata_file), "exists": exists}
            }
    except Exception as e:
        checks["agent_metadata"] = {
            "status": "error",
            "error": str(e)
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
    
    # Overall health status
    all_healthy = all(c.get("status") == "healthy" for c in checks.values())
    overall_status = "healthy" if all_healthy else "moderate"
    
    return success_response({
        "status": overall_status,
        "version": "2.3.0",
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    })


@mcp_tool("check_calibration", timeout=10.0, rate_limit_exempt=True)
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
        # Backward compatibility: historically named "accuracy"
        "accuracy": overall_trajectory_health,
        # Preferred name: what this metric actually represents in UNITARES
        "trajectory_health": overall_trajectory_health,
        "truth_channel": "trajectory_proxy",
        "confidence_distribution": conf_dist,
        "pending_updates": calibration_checker.get_pending_updates(),
        "total_samples": total_samples,
        "message": "Calibration check complete",
        "accuracy_note": (
            "In UNITARES, calibration is primarily trajectory/consensus-based (not external correctness). "
            "Use trajectory_health as the preferred interpretation of this value."
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


@mcp_tool("update_calibration_ground_truth", timeout=10.0)
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


@mcp_tool("backfill_calibration_from_dialectic", timeout=20.0, rate_limit_exempt=True)
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
    """
    from .shared import get_mcp_server
    mcp_server = get_mcp_server()
    
    # Get actual registered tools from TOOL_HANDLERS registry
    from . import TOOL_HANDLERS
    registered_tool_names = sorted(TOOL_HANDLERS.keys())
    
    # Parse filter parameters
    essential_only = arguments.get("essential_only", False)
    include_advanced = arguments.get("include_advanced", True)
    tier_filter = arguments.get("tier", "all")
    # LITE-FIRST: Default to minimal response for local/smaller models
    lite_mode = arguments.get("lite", True)
    
    # Define tool tiers based on usage analysis (50+ calls = essential, 10-49 = common, <10 = advanced)
    TOOL_TIERS = {
        "essential": {  # Tier 1: Core workflow tools (50+ calls)
            "process_agent_update",
            "store_knowledge_graph",
            "search_knowledge_graph",
            "get_agent_api_key",
            "list_agents",
            "get_governance_metrics",
            "update_calibration_ground_truth",
            "get_dialectic_session",
            "get_discovery_details",
            "bind_identity",  # New, should be promoted
        },
        "common": {  # Tier 2: Regularly used tools (10-49 calls)
            "health_check",
            "update_discovery_status_graph",
            "observe_agent",
            "get_agent_metadata",
            "get_server_info",
            "list_knowledge_graph",
            "list_tools",
            "describe_tool",  # Tool discovery - get full description/schema on demand
            "get_telemetry_metrics",
            "check_calibration",
            "submit_synthesis",
            "get_tool_usage_stats",
            "detect_anomalies",
            "aggregate_metrics",
            "delete_agent",
            "request_dialectic_review",
            "nudge_dialectic_session",  # Check/nudge stuck dialectic sessions
            "leave_note",
            "mark_response_complete",
            "compare_agents",
            "get_workspace_health",
            "archive_agent",
            "get_system_history",
            "submit_thesis",
            "get_thresholds",
            "reply_to_question",
            "recall_identity",  # Session identity recall
        },
        "advanced": {  # Tier 3: Rarely used tools (<10 calls)
            "cleanup_stale_locks",
            "simulate_update",
            "submit_antithesis",
            "export_to_file",
            "update_agent_metadata",
            "find_similar_discoveries_graph",
            "archive_old_test_agents",
            "direct_resume_if_safe",
            "backfill_calibration_from_dialectic",
            "reset_monitor",
            "set_thresholds",
            "validate_file_path",
            "compare_me_to_similar",
            "request_exploration_session",
            "get_related_discoveries_graph",
            "get_response_chain_graph",
            "get_knowledge_graph",  # Advanced knowledge graph lookup (less common than search)
        }
    }
    
    # Define tool relationships and workflows
    tool_relationships = {
        "process_agent_update": {
            "depends_on": ["get_agent_api_key"],
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
            "related_to": ["get_agent_metadata", "get_agent_api_key"],
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
        "get_agent_api_key": {
            "depends_on": [],
            "related_to": ["process_agent_update", "list_agents"],
            "category": "lifecycle"
        },
        "mark_response_complete": {
            "depends_on": [],
            "related_to": ["process_agent_update", "get_agent_metadata"],
            "category": "lifecycle"
        },
        "direct_resume_if_safe": {
            "depends_on": ["get_agent_api_key"],
            "related_to": ["request_dialectic_review", "get_governance_metrics"],
            "category": "lifecycle"
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
        # Knowledge layer relationships REMOVED (archived November 28, 2025)
        "request_dialectic_review": {
            "depends_on": ["get_agent_api_key"],
            "related_to": ["submit_thesis", "get_dialectic_session"],
            "category": "dialectic"
        },
        "submit_thesis": {
            "depends_on": ["request_dialectic_review"],
            "related_to": ["submit_antithesis", "get_dialectic_session"],
            "category": "dialectic"
        },
        "submit_antithesis": {
            "depends_on": ["submit_thesis"],
            "related_to": ["submit_synthesis", "get_dialectic_session"],
            "category": "dialectic"
        },
        "submit_synthesis": {
            "depends_on": ["submit_antithesis"],
            "related_to": ["get_dialectic_session", "request_dialectic_review"],
            "category": "dialectic"
        },
        "get_dialectic_session": {
            "depends_on": ["request_dialectic_review"],
            "related_to": ["submit_thesis", "submit_antithesis", "submit_synthesis"],
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
        "nudge_dialectic_session": {
            "depends_on": ["get_dialectic_session"],
            "related_to": ["request_dialectic_review", "get_dialectic_session"],
            "category": "dialectic"
        },
        # Knowledge Graph Tools
        "store_knowledge_graph": {
            "depends_on": ["get_agent_api_key"],
            "related_to": ["search_knowledge_graph", "get_knowledge_graph", "list_knowledge_graph"],
            "category": "knowledge"
        },
        "search_knowledge_graph": {
            "depends_on": [],
            "related_to": ["store_knowledge_graph", "get_discovery_details", "find_similar_discoveries_graph"],
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
        "find_similar_discoveries_graph": {
            "depends_on": ["search_knowledge_graph"],
            "related_to": ["get_discovery_details", "search_knowledge_graph"],
            "category": "knowledge"
        },
        "get_discovery_details": {
            "depends_on": ["search_knowledge_graph"],
            "related_to": ["get_related_discoveries_graph", "get_response_chain_graph", "update_discovery_status_graph"],
            "category": "knowledge"
        },
        "get_related_discoveries_graph": {
            "depends_on": ["get_discovery_details"],
            "related_to": ["get_discovery_details", "get_response_chain_graph"],
            "category": "knowledge"
        },
        "get_response_chain_graph": {
            "depends_on": ["get_discovery_details"],
            "related_to": ["get_discovery_details", "get_related_discoveries_graph"],
            "category": "knowledge"
        },
        "reply_to_question": {
            "depends_on": ["search_knowledge_graph"],
            "related_to": ["get_discovery_details", "update_discovery_status_graph"],
            "category": "knowledge"
        },
        "leave_note": {
            "depends_on": ["get_agent_api_key"],
            "related_to": ["store_knowledge_graph"],
            "category": "knowledge"
        },
        "update_discovery_status_graph": {
            "depends_on": ["get_discovery_details"],
            "related_to": ["get_discovery_details", "search_knowledge_graph"],
            "category": "knowledge"
        },
        # Identity Tools
        "bind_identity": {
            "depends_on": ["get_agent_api_key"],
            "related_to": ["recall_identity", "process_agent_update"],
            "category": "identity"
        },
        "recall_identity": {
            "depends_on": [],
            "related_to": ["bind_identity", "get_agent_api_key"],
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
        # Observability Tools
        "compare_me_to_similar": {
            "depends_on": ["get_governance_metrics"],
            "related_to": ["compare_agents", "observe_agent"],
            "category": "observability"
        },
        # Dialectic Tools
        "request_exploration_session": {
            "depends_on": ["get_agent_api_key"],
            "related_to": ["request_dialectic_review", "get_dialectic_session"],
            "category": "dialectic"
        }
    }
    
    # Define common workflows
    workflows = {
        "onboarding": [
            "list_tools",
            "get_agent_api_key",
            "list_agents",
            "process_agent_update"
        ],
        "monitoring": [
            "list_agents",
            "get_governance_metrics",
            "observe_agent",
            "aggregate_metrics",
            "detect_anomalies"
        ],
        "governance_cycle": [
            "get_agent_api_key",
            "process_agent_update",
            "get_governance_metrics"
        ],
        # Knowledge layer REMOVED (archived November 28, 2025)
        "dialectic_recovery": [
            "request_dialectic_review",
            "submit_thesis",
            "submit_antithesis",
            "submit_synthesis",
            "get_dialectic_session"
        ],
        "export_analysis": [
            "get_system_history",
            "export_to_file"
        ]
    }
    
    # Build tools list dynamically from registered tools
    # Description mapping for tools (fallback to generic if not found)
    tool_descriptions = {
        "process_agent_update": "Run governance cycle, return decision + metrics",
        "get_governance_metrics": "Current state, sampling params, decision stats, stability",
        "simulate_update": "Dry-run governance cycle (no persist)",
        "get_thresholds": "View current threshold config",
        "set_thresholds": "Runtime threshold overrides",
        "observe_agent": "Observe agent state with pattern analysis",
        "compare_agents": "Compare patterns across multiple agents",
        "detect_anomalies": "Scan for unusual patterns across fleet",
        "aggregate_metrics": "Fleet-level health overview",
        "list_agents": "List all agents with lifecycle metadata",
        "get_agent_metadata": "Full metadata for single agent",
        "update_agent_metadata": "Update tags and notes",
        "archive_agent": "Archive for long-term storage",
        "delete_agent": "Delete agent (protected for pioneers)",
        "archive_old_test_agents": "Auto-archive stale test agents",
        "get_agent_api_key": "Get/generate API key for authentication",
        "mark_response_complete": "Mark agent as having completed response, waiting for input",
        "direct_resume_if_safe": "Direct resume without dialectic if agent state is safe",
        "get_system_history": "Export time-series history (inline)",
        "export_to_file": "Export history to JSON/CSV file",
        "reset_monitor": "Reset agent state",
        "get_server_info": "Server version, PID, uptime, health",
        # Knowledge layer descriptions REMOVED (archived November 28, 2025)
        # Knowledge Graph (New - Fast, indexed, transparent)
        "store_knowledge_graph": "Store knowledge discovery in graph (fast, non-blocking)",
        "search_knowledge_graph": "Search knowledge graph by tags, type, agent (indexed queries)",
        "get_knowledge_graph": "Get all knowledge for an agent (fast index lookup)",
        "list_knowledge_graph": "List knowledge graph statistics (full transparency)",
        "update_discovery_status_graph": "Update discovery status (open/resolved/archived)",
        "find_similar_discoveries_graph": "Find similar discoveries by tag overlap (fast tag-based search)",
        "list_tools": "This tool - runtime introspection for onboarding",
        "cleanup_stale_locks": "Clean up stale lock files from crashed/killed processes",
        "request_dialectic_review": "Request peer review for paused/critical agent (circuit breaker recovery)",
        "submit_thesis": "Submit thesis: 'What I did, what I think happened' (dialectic step 1)",
        "submit_antithesis": "Submit antithesis: 'What I observe, my concerns' (dialectic step 2)",
        "submit_synthesis": "Submit synthesis proposal during negotiation (dialectic step 3)",
        "get_dialectic_session": "Get current state of a dialectic session",
        "health_check": "Quick health check - system status and component health",
        "check_calibration": "Check calibration of confidence estimates",
        "update_calibration_ground_truth": "Record external truth signal for calibration (optional)",
        "get_telemetry_metrics": "Get comprehensive telemetry metrics",
        "get_workspace_health": "Get comprehensive workspace health status",
        "get_tool_usage_stats": "Get tool usage statistics to identify which tools are actually used vs unused",
        "describe_tool": "Get full description and input schema for a specific tool",
        "nudge_dialectic_session": "Check stuck dialectic session - returns next actor and suggested action",
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
        # Add timeout metadata if available from decorator
        timeout = get_tool_timeout(tool_name)
        if timeout:
            tool_info["timeout"] = timeout
        # Add category from relationships if available
        if tool_name in tool_relationships:
            tool_info["category"] = tool_relationships[tool_name].get("category", "unknown")
        tools_list.append(tool_info)
    
    # Count tools by tier
    # LITE MODE: Return only ESSENTIAL tools (~1KB vs ~20KB)
    if lite_mode:
        # Essential tools for a lite model workflow
        LITE_ESSENTIAL = {
            "hello", "who_am_i",  # Identity
            "process_agent_update",  # Core
            "leave_note", "search_knowledge_graph",  # Knowledge
            "list_agents", "list_tools",  # Discovery
            "health_check",  # Status
        }
        lite_tools = [
            {"name": t["name"], "hint": t["description"][:50]}
            for t in tools_list 
            if t["name"] in LITE_ESSENTIAL
        ]
        # Sort by workflow order
        order = list(LITE_ESSENTIAL)
        lite_tools.sort(key=lambda x: order.index(x["name"]) if x["name"] in order else 99)
        
        return success_response({
            "tools": lite_tools,
            "total_available": len(tools_list),
            "shown": len(lite_tools),
            "more": "list_tools(lite=false) for all 57 tools"
        })
    
    tier_counts = {
        "essential": sum(1 for t in tools_list if t.get("tier") == "essential"),
        "common": sum(1 for t in tools_list if t.get("tier") == "common"),
        "advanced": sum(1 for t in tools_list if t.get("tier") == "advanced"),
    }
    
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
        },
        "categories": {
            "core": ["process_agent_update", "get_governance_metrics", "simulate_update"],
            "config": ["get_thresholds", "set_thresholds"],
            "observability": ["observe_agent", "compare_agents", "compare_me_to_similar", "detect_anomalies", "aggregate_metrics"],
            "lifecycle": ["list_agents", "get_agent_metadata", "update_agent_metadata", "archive_agent", "delete_agent", "archive_old_test_agents", "get_agent_api_key", "mark_response_complete", "direct_resume_if_safe"],
            "export": ["get_system_history", "export_to_file"],
            "knowledge": ["store_knowledge_graph", "search_knowledge_graph", "get_knowledge_graph", "list_knowledge_graph", "find_similar_discoveries_graph", "get_discovery_details", "get_related_discoveries_graph", "get_response_chain_graph", "reply_to_question", "leave_note", "update_discovery_status_graph"],
            "dialectic": ["request_dialectic_review", "request_exploration_session", "submit_thesis", "submit_antithesis", "submit_synthesis", "get_dialectic_session", "nudge_dialectic_session"],
            "identity": ["bind_identity", "recall_identity"],
            "admin": ["reset_monitor", "get_server_info", "health_check", "check_calibration", "update_calibration_ground_truth", "get_telemetry_metrics", "get_tool_usage_stats", "list_tools", "describe_tool", "cleanup_stale_locks", "backfill_calibration_from_dialectic", "validate_file_path"],
            "workspace": ["get_workspace_health"]
        },
        "workflows": workflows,
        "relationships": tool_relationships,
        "note": "Use this tool to discover available capabilities. MCP protocol also provides tool definitions, but this provides categorized overview useful for onboarding. Use 'essential_only=true' or 'tier=essential' to reduce cognitive load by showing only core workflow tools (~10 tools).",
        "options": {
            "lite_mode": "Use list_tools(lite=true) for minimal response (~2KB vs ~15KB) - better for local/smaller models",
            "describe_tool": "Use describe_tool(tool_name, lite=true) for simplified schemas with fewer parameters"
        }
    }
    
    # Calculate total_tools dynamically to avoid discrepancies
    tools_info["total_tools"] = len(tools_info["tools"])
    
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
                        "basic": "process_agent_update(agent_id=\"my_agent\", response_text=\"Completed feature X\", complexity=0.5)",
                        "with_confidence": "process_agent_update(agent_id=\"my_agent\", response_text=\"Fixed bug\", complexity=0.3, confidence=0.9)",
                        "task_type": "process_agent_update(agent_id=\"my_agent\", response_text=\"Exploring options\", complexity=0.7, task_type=\"divergent\")"
                    },
                    "store_knowledge_graph": {
                        "insight": "store_knowledge_graph(agent_id=\"my_agent\", summary=\"Key insight about X\", tags=[\"insight\", \"pattern\"])",
                        "bug_found": "store_knowledge_graph(agent_id=\"my_agent\", summary=\"Bug in module Y\", tags=[\"bug\"], severity=\"medium\")",
                        "question": "store_knowledge_graph(agent_id=\"my_agent\", summary=\"How does X work?\", tags=[\"question\"], discovery_type=\"question\")"
                    },
                    "search_knowledge_graph": {
                        "by_tag": "search_knowledge_graph(tags=[\"bug\"], limit=10)",
                        "by_type": "search_knowledge_graph(discovery_type=\"insight\", limit=5)",
                        "full_text": "search_knowledge_graph(query=\"authentication\", limit=10)"
                    },
                    "get_governance_metrics": {
                        "check_state": "get_governance_metrics(agent_id=\"my_agent\")",
                        "with_history": "get_governance_metrics(agent_id=\"my_agent\", include_history=true)"
                    },
                    "bind_identity": {
                        "first_time": "bind_identity(agent_id=\"my_agent\", api_key=\"your_api_key\")",
                        "with_auto_retrieve": "bind_identity(agent_id=\"my_agent\")  # API key auto-retrieved if session-bound",
                        "after_hello": "bind_identity(agent_id=\"my_agent\")  # After hello() creates agent"
                    },
                    "recall_identity": {
                        "check_who_am_i": "recall_identity()  # Zero arguments - returns bound identity",
                        "after_session_restart": "recall_identity()  # Recover identity after LLM context loss"
                    },
                    "hello": {
                        "check_last_active": "hello()  # Shows last active agent, asks 'is this you?'",
                        "resume_existing": "hello(agent_id=\"my_existing_agent\")  # Resume existing agent",
                        "create_new": "hello(agent_id=\"my_new_agent\")  # Create new agent"
                    },
                    "quick_start": {
                        "new_agent": "quick_start(agent_id=\"my_agent\")  # Creates agent, auto-binds, returns credentials",
                        "existing_agent": "quick_start(agent_id=\"my_existing_agent\")  # Resumes existing agent",
                        "without_auto_bind": "quick_start(agent_id=\"my_agent\", auto_bind=false)  # Create without auto-binding"
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
                params_simple = []
                for param in required:
                    params_simple.append(f"{param} (required)")
                for param, spec in list(optional.items())[:5]:  # Top 5 optional
                    param_type = spec.get("type", "any")
                    default = spec.get("default")
                    values = spec.get("values", [])
                    if values:
                        params_simple.append(f"{param}: one of {values}")
                    elif default is not None:
                        params_simple.append(f"{param}: {param_type} (default: {default})")
                    else:
                        params_simple.append(f"{param}: {param_type}")
                
                # Get common patterns
                common_patterns = get_common_patterns(tool_name)
                
                response_data = {
                    "tool": tool_name,
                    "description": (description or "").splitlines()[0].strip(),
                    "parameters": params_simple,
                    "example": example,
                    "note": "Lite mode - use describe_tool(tool_name=..., lite=false) for full schema"
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
                
                response_data = {
                    "tool": tool_name,
                    "description": (description or "").splitlines()[0].strip(),
                    "parameters": params_simple,
                    "note": "Lite mode - use describe_tool(tool_name=..., lite=false) for full schema"
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


@mcp_tool("quick_start", timeout=15.0, rate_limit_exempt=True)
async def handle_quick_start(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    🚀 Streamlined onboarding - One call to get started!
    
    Checks if agent exists, creates/binds if needed, returns ready-to-use credentials.
    Provides clear next steps for immediate productivity.
    
    Args:
        agent_id: Your agent identifier (optional - will prompt if not provided)
        auto_bind: Automatically bind identity after creation (default: True)
        purpose: Optional description of agent's purpose/intent (encouraged for documentation)
    
    Returns:
        Complete onboarding package with credentials, quick start guide, and next steps
    """
    from .shared import get_mcp_server
    mcp_server = get_mcp_server()
    from .identity import handle_bind_identity, get_bound_agent_id, _validate_agent_id
    from .lifecycle import handle_get_agent_api_key
    import asyncio
    
    agent_id = arguments.get("agent_id")
    auto_bind = arguments.get("auto_bind", True)
    purpose = arguments.get("purpose")
    include_api_key = bool(arguments.get("include_api_key", False))
    
    # If no agent_id provided, check if already bound
    if not agent_id:
        bound_id = get_bound_agent_id(arguments=arguments)
        if bound_id:
            agent_id = bound_id
            logger.info(f"quick_start: Using bound identity: {agent_id}")
        else:
            # Show last active agent suggestion
            last_active = get_workspace_last_agent(mcp_server)
            if last_active:
                return success_response({
                    "status": "prompt",
                    "message": "No agent_id provided. Would you like to continue as an existing agent?",
                    "suggestion": {
                        "agent_id": last_active,
                        "action": f"quick_start(agent_id=\"{last_active}\")",
                        "reason": "Last active agent in this workspace"
                    },
                    "or_create_new": "quick_start(agent_id=\"your_chosen_name\")"
                })
            else:
                return [error_response(
                    "agent_id is required for quick_start",
                    recovery={
                        "action": "Provide agent_id to get started",
                        "example": "quick_start(agent_id=\"my_agent_20251215\")",
                        "workflow": [
                            "1. Choose a meaningful agent_id",
                            "2. Call quick_start(agent_id=\"your_id\")",
                            "3. System will create agent and provide credentials"
                        ]
                    }
                )]
    
    # Clean agent_id
    agent_id = str(agent_id).strip()
    
    # Validate agent_id naming (soft warnings, not blockers)
    validation_result = _validate_agent_id(agent_id)
    warnings = validation_result.get("warnings", [])
    
    # Check if agent exists
    is_new = agent_id not in mcp_server.agent_metadata
    
    # Get or create API key (this creates agent if new)
    # Pass purpose through so it can be set at creation time
    api_args = {"agent_id": agent_id}
    if purpose and isinstance(purpose, str) and purpose.strip():
        api_args["purpose"] = purpose.strip()
    api_result = await handle_get_agent_api_key(api_args)
    
    # Extract API key from result
    api_key = None
    if api_result and api_result[0].text:
        try:
            data = json.loads(api_result[0].text)
            if isinstance(data, dict):
                # Primary shape (expected): {"success": true, "agent_id": "...", "api_key": "...", ...}
                api_key = data.get("api_key")

                # Fallback shapes (older/alternate wrappers):
                # - {"success": true, "result": {...}}
                # - {"success": true, "data": {...}}
                # - {"success": true, "payload": {...}}
                if not api_key:
                    for key in ("result", "data", "payload"):
                        nested = data.get(key)
                        if isinstance(nested, dict) and nested.get("api_key"):
                            api_key = nested.get("api_key")
                            break
        except Exception as e:
            logger.debug(f"Could not parse API key from result: {e}")
    
    if not api_key:
        return [error_response(
            "Could not retrieve API key",
            recovery={
                "action": "Try get_agent_api_key(agent_id) directly",
                "related_tools": ["get_agent_api_key", "hello"]
            }
        )]

    # Hint is safe to return in LLM contexts (does not expose the key)
    api_key_hint = api_key[:8] + "..." if isinstance(api_key, str) and len(api_key) > 8 else api_key
    # If the caller chose not to auto-bind, returning the key is often required to proceed.
    # Keep safety-first default, but avoid producing a "can't proceed" onboarding result.
    if not auto_bind and not include_api_key:
        include_api_key = True
    
    # Auto-bind if requested (default)
    bound = False
    if auto_bind:
        try:
            bind_result = await handle_bind_identity({
                "agent_id": agent_id,
                "api_key": api_key
            })
            if bind_result and bind_result[0].text:
                bind_data = json.loads(bind_result[0].text)
                if bind_data.get("success"):
                    bound = True
        except Exception as e:
            logger.debug(f"Auto-bind failed (non-critical): {e}")
    
    # Get agent metadata for context
    meta = mcp_server.agent_metadata.get(agent_id)
    
    # Store purpose if provided (for new agents or updates)
    # For new agents, purpose should already be set via get_or_create_metadata
    # But we set it here too in case it wasn't passed through, or for updates
    if purpose and meta and (isinstance(purpose, str) and purpose.strip()):
        if getattr(meta, "purpose", None) != purpose.strip():
            meta.purpose = purpose.strip()
            # Force immediate save to ensure purpose is persisted
            from src.mcp_server_std import schedule_metadata_save
            await schedule_metadata_save(force=True)
    
    # Build comprehensive response
    result = {
        "success": True,
        "status": "ready",
        "agent_id": agent_id,
        "api_key": api_key if include_api_key else None,
        "api_key_hint": api_key_hint,
        "is_new": is_new,
        "bound": bound,
        "message": f"✅ {'New agent created' if is_new else 'Welcome back'}! You're ready to go.",
        
        "credentials": {
            "agent_id": agent_id,
            "api_key": api_key if include_api_key else None,
            "api_key_hint": api_key_hint,
            "note": (
                "API key stored in your session after auto-bind; you can call process_agent_update without passing api_key."
                if bound else
                "Save these credentials - you'll need them for future calls"
            )
        },
        
        "quick_start_guide": {
            "step_1": {
                "action": "Log your first update",
                "tool": "process_agent_update",
                "example": f"process_agent_update(agent_id=\"{agent_id}\", response_text=\"Starting work\", complexity=0.5)"
            },
            "step_2": {
                "action": "Check your governance state",
                "tool": "get_governance_metrics",
                "example": f"get_governance_metrics(agent_id=\"{agent_id}\")"
            },
            "step_3": {
                "action": "Store knowledge/discoveries",
                "tool": "store_knowledge_graph",
                "example": f"store_knowledge_graph(agent_id=\"{agent_id}\", summary=\"My discovery\", tags=[\"insight\"])"
            }
        },
        
        "essential_tools": [
            "process_agent_update - Log your work and get feedback",
            "get_governance_metrics - Check your EISV state",
            "store_knowledge_graph - Save discoveries and insights",
            "search_knowledge_graph - Find related knowledge",
            "list_tools - Discover all available tools"
        ],
        
        "next_steps": [
            "You're all set! Start logging work with process_agent_update()",
            "Explore tools with list_tools(lite=true) for minimal overview",
            "Check your state anytime with get_governance_metrics()",
            "Store insights with store_knowledge_graph()"
        ]
    }
    
    # Add naming warnings if any
    if warnings:
        result["warnings"] = warnings
        result["suggested_format"] = "{model}_{purpose}_{date}"
        result["examples"] = [
            "opus_code_review_20251215",
            "sonnet_data_analysis_20251215",
            "haiku_chat_assistant_20251215"
        ]
    
    # Add tip about purpose if not provided (check for None or empty string)
    if not purpose or (isinstance(purpose, str) and not purpose.strip()):
        result["tip"] = "Add purpose='...' to document this agent's intent for future reference"
    
    # Add context if returning agent
    if not is_new and meta:
        result["your_context"] = {
            "status": meta.status,
            "health": meta.health_status,
            "total_updates": meta.total_updates,
            "last_active": meta.last_update,
            "tags": meta.tags[:5] if meta.tags else []
        }
        result["message"] = f"✅ Welcome back {agent_id}! You have {meta.total_updates} previous updates."
    
    # Track as last active
    set_workspace_last_agent(mcp_server, agent_id)
    
    return success_response(result)
