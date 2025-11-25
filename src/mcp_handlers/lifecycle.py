"""
Lifecycle tool handlers.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
import sys
from datetime import datetime
from pathlib import Path
from .utils import success_response, error_response, require_agent_id

# Import from mcp_server_std module
if 'src.mcp_server_std' in sys.modules:
    mcp_server = sys.modules['src.mcp_server_std']
else:
    import src.mcp_server_std as mcp_server


async def handle_list_agents(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle list_agents tool"""
    # Reload metadata from disk to get latest state (handles multi-process sync)
    mcp_server.load_metadata()
    
    # Parse optional parameters
    summary_only = arguments.get("summary_only", False)
    status_filter = arguments.get("status_filter", "all")
    loaded_only = arguments.get("loaded_only", False)
    include_metrics = arguments.get("include_metrics", True)
    grouped = arguments.get("grouped", True)
    standardized = arguments.get("standardized", True)
    
    # Build agent list with optional filtering
    agents_list = []
    
    # Sort by last_update timestamp (most recent first)
    def get_sort_key(item):
        agent_id, meta = item
        try:
            last_update_str = meta.last_update
            if 'T' in last_update_str:
                dt = datetime.fromisoformat(last_update_str.replace('Z', '+00:00') if 'Z' in last_update_str else last_update_str)
                return (-dt.timestamp(), agent_id)
        except:
            pass
        return (0, agent_id)
    
    sorted_agents = sorted(mcp_server.agent_metadata.items(), key=get_sort_key)
    
    for agent_id, meta in sorted_agents:
        try:
            # Apply status filter
            if status_filter != "all" and meta.status != status_filter:
                continue
            
            monitor = mcp_server.monitors.get(agent_id)
            
            # Apply loaded_only filter
            if loaded_only and not monitor:
                continue
            
            if summary_only:
                agents_list.append({
                    "agent_id": agent_id,
                    "lifecycle_status": meta.status,
                    "loaded_in_process": monitor is not None
                })
                continue
            
            # Use standardized format if requested
            if standardized:
                try:
                    agent_info = mcp_server.build_standardized_agent_info(
                        agent_id=agent_id,
                        meta=meta,
                        monitor=monitor,
                        include_metrics=include_metrics
                    )
                except Exception as e:
                    print(f"[UNITARES MCP] Error building standardized info for agent {agent_id}: {e}", file=sys.stderr)
                    agent_info = mcp_server.build_standardized_agent_info(
                        agent_id=agent_id,
                        meta=meta,
                        monitor=None,
                        include_metrics=False
                    )
                    agent_info["health_status"] = "error"
                    agent_info["state"]["error"] = str(e)
            else:
                # Legacy format
                if monitor:
                    try:
                        state = monitor.state
                        agent_info = {
                            "agent_id": agent_id,
                            "lifecycle_status": meta.status,
                            "created": monitor.created_at.isoformat(),
                            "last_update": monitor.last_update.isoformat(),
                            "update_count": int(state.update_count),
                            "total_updates": meta.total_updates,
                            "version": meta.version,
                            "tags": meta.tags or [],
                            "loaded_in_process": True
                        }
                        if include_metrics:
                            risk_score = getattr(state, 'risk_score', None)
                            health_status_obj, _ = mcp_server.health_checker.get_health_status(
                                risk_score=risk_score,
                                coherence=state.coherence,
                                void_active=state.void_active
                            )
                            agent_info["health_status"] = health_status_obj.value
                            agent_info["metrics"] = {
                                "lambda1": float(state.lambda1),
                                "coherence": float(state.coherence),
                                "void_active": bool(state.void_active),
                                "E": float(state.E),
                                "I": float(state.I),
                                "S": float(state.S),
                                "V": float(state.V)
                            }
                        if meta.notes:
                            agent_info["notes"] = meta.notes
                    except Exception as e:
                        print(f"[UNITARES MCP] Error accessing state for agent {agent_id}: {e}", file=sys.stderr)
                        agent_info = {
                            "agent_id": agent_id,
                            "lifecycle_status": meta.status,
                            "health_status": "error",
                            "created": meta.created_at,
                            "last_update": meta.last_update,
                            "total_updates": meta.total_updates,
                            "version": meta.version,
                            "tags": meta.tags or [],
                            "error": str(e),
                            "loaded_in_process": True
                        }
                else:
                    agent_info = {
                        "agent_id": agent_id,
                        "lifecycle_status": meta.status,
                        "created": meta.created_at,
                        "last_update": meta.last_update,
                        "total_updates": meta.total_updates,
                        "version": meta.version,
                        "tags": meta.tags or [],
                        "loaded_in_process": False
                    }
                    if include_metrics:
                        agent_info["health_status"] = "unknown"
            
            agents_list.append(agent_info)
        except Exception as e:
            print(f"[UNITARES MCP] Error processing agent {agent_id} in list_agents: {e}", file=sys.stderr)
            if not summary_only:
                if standardized:
                    try:
                        agent_info = mcp_server.build_standardized_agent_info(
                            agent_id=agent_id,
                            meta=meta if meta else mcp_server.AgentMetadata(
                                agent_id=agent_id,
                                status="unknown",
                                created_at=datetime.now().isoformat(),
                                last_update=datetime.now().isoformat()
                            ),
                            monitor=None,
                            include_metrics=False
                        )
                        agent_info["health_status"] = "error"
                        agent_info["state"]["error"] = str(e)
                        agents_list.append(agent_info)
                    except:
                        agents_list.append({
                            "agent_id": agent_id,
                            "lifecycle_status": meta.status if meta else "unknown",
                            "health_status": "error",
                            "error": str(e)
                        })
                else:
                    agents_list.append({
                        "agent_id": agent_id,
                        "lifecycle_status": meta.status if meta else "unknown",
                        "health_status": "error",
                        "error": str(e)
                    })
    
    # Summary statistics
    summary = {
        "total": len(agents_list),
        "by_status": {
            "active": sum(1 for a in agents_list if a.get("lifecycle_status") == "active"),
            "paused": sum(1 for a in agents_list if a.get("lifecycle_status") == "paused"),
            "archived": sum(1 for a in agents_list if a.get("lifecycle_status") == "archived"),
            "deleted": sum(1 for a in agents_list if a.get("lifecycle_status") == "deleted")
        },
        "loaded_count": sum(1 for a in agents_list if (a.get("state", {}).get("loaded_in_process") if standardized else a.get("loaded_in_process")) is True)
    }
    
    # Add health status counts if metrics were included
    if include_metrics and not summary_only:
        if standardized:
            summary["by_health"] = {
                "healthy": sum(1 for a in agents_list if a.get("health_status") == "healthy"),
                "degraded": sum(1 for a in agents_list if a.get("health_status") == "degraded"),
                "critical": sum(1 for a in agents_list if a.get("health_status") == "critical"),
                "unknown": sum(1 for a in agents_list if a.get("health_status") == "unknown"),
                "error": sum(1 for a in agents_list if a.get("health_status") == "error")
            }
        else:
            summary.update({
                "healthy": sum(1 for a in agents_list if a.get("health_status") == "healthy"),
                "degraded": sum(1 for a in agents_list if a.get("health_status") == "degraded"),
                "critical": sum(1 for a in agents_list if a.get("health_status") == "critical")
            })
    
    response_data = {
        "summary": summary
    }
    
    # Only include agents list if not summary_only
    if not summary_only:
        if grouped and standardized:
            grouped_agents = {
                "active": [],
                "paused": [],
                "archived": [],
                "deleted": []
            }
            for agent in agents_list:
                status = agent.get("lifecycle_status", "unknown")
                if status in grouped_agents:
                    grouped_agents[status].append(agent)
                else:
                    if "unknown" not in grouped_agents:
                        grouped_agents["unknown"] = []
                    grouped_agents["unknown"].append(agent)
            response_data["agents"] = grouped_agents
        else:
            response_data["agents"] = agents_list
    
    return success_response(response_data)


async def handle_get_agent_metadata(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle get_agent_metadata tool"""
    mcp_server.load_metadata()
    
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]
    
    if agent_id not in mcp_server.agent_metadata:
        return [error_response(f"Agent '{agent_id}' not found")]
    
    meta = mcp_server.agent_metadata[agent_id]
    monitor = mcp_server.monitors.get(agent_id)
    
    metadata_response = meta.to_dict()
    
    # Add computed fields
    if monitor:
        metadata_response["current_state"] = {
            "lambda1": float(monitor.state.lambda1),
            "coherence": float(monitor.state.coherence),
            "void_active": bool(monitor.state.void_active),
            "E": float(monitor.state.E),
            "I": float(monitor.state.I),
            "S": float(monitor.state.S),
            "V": float(monitor.state.V)
        }
    
    # Days since update
    last_update_dt = datetime.fromisoformat(meta.last_update)
    days_since = (datetime.now() - last_update_dt).days
    metadata_response["days_since_update"] = days_since
    
    return success_response(metadata_response)


async def handle_update_agent_metadata(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle update_agent_metadata tool"""
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]
    
    tags = arguments.get("tags")
    notes = arguments.get("notes")
    append_notes = arguments.get("append_notes", False)
    
    if agent_id not in mcp_server.agent_metadata:
        return [error_response(f"Agent '{agent_id}' not found")]
    
    meta = mcp_server.agent_metadata[agent_id]
    
    # Update tags (replace)
    if tags is not None:
        meta.tags = tags
    
    # Update notes (replace or append)
    if notes is not None:
        if append_notes:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            meta.notes = f"{meta.notes}\n[{timestamp}] {notes}".strip()
        else:
            meta.notes = notes
    
    mcp_server.save_metadata()
    
    return success_response({
        "message": f"Metadata updated for agent '{agent_id}'",
        "agent_id": agent_id,
        "tags": meta.tags,
        "notes": meta.notes
    })


async def handle_archive_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle archive_agent tool"""
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]
    
    reason = arguments.get("reason", "")
    keep_in_memory = arguments.get("keep_in_memory", False)
    
    if agent_id not in mcp_server.agent_metadata:
        return [error_response(f"Agent '{agent_id}' not found")]
    
    meta = mcp_server.agent_metadata[agent_id]
    
    # Update metadata
    meta.status = "archived"
    meta.archived_at = datetime.now().isoformat()
    meta.add_lifecycle_event("archived", reason)
    
    # Unload from memory unless keep_in_memory
    if not keep_in_memory and agent_id in mcp_server.monitors:
        del mcp_server.monitors[agent_id]
    
    mcp_server.save_metadata()
    
    return success_response({
        "message": f"Agent '{agent_id}' archived",
        "agent_id": agent_id,
        "archived_at": meta.archived_at,
        "kept_in_memory": keep_in_memory
    })


async def handle_delete_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle delete_agent tool"""
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]
    
    confirm = arguments.get("confirm", False)
    backup_first = arguments.get("backup_first", True)
    
    if not confirm:
        return [error_response(
            "Set 'confirm: true' to delete agent",
            {"warning": f"This will delete agent '{agent_id}' and move its data to archive/"}
        )]
    
    # Special protection for pioneer agents
    meta = mcp_server.agent_metadata.get(agent_id)
    if meta and "pioneer" in meta.tags:
        return [error_response(
            f"Cannot delete pioneer agent '{agent_id}'. This agent has historical significance."
        )]
    
    if agent_id not in mcp_server.monitors and agent_id not in mcp_server.agent_metadata:
        return [error_response(f"Agent '{agent_id}' does not exist")]
    
    # Archive data file if it exists and backup requested
    archive_path = None
    if backup_first:
        data_file = Path(mcp_server.project_root) / "data" / f"{agent_id}.json"
        if data_file.exists():
            archive_dir = Path(mcp_server.project_root) / "data" / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_path = archive_dir / f"{agent_id}_{timestamp}.json"
            data_file.rename(archive_path)
    
    # Remove from monitors
    if agent_id in mcp_server.monitors:
        del mcp_server.monitors[agent_id]
    
    # Update metadata to deleted status
    if agent_id in mcp_server.agent_metadata:
        mcp_server.agent_metadata[agent_id].status = "deleted"
        await mcp_server.save_metadata_async()
    
    response_data = {
        "message": f"Agent '{agent_id}' deleted",
        "agent_id": agent_id
    }
    if archive_path:
        response_data["archived_to"] = str(archive_path)
    
    return success_response(response_data)


async def handle_archive_old_test_agents(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle archive_old_test_agents tool"""
    max_age_days = arguments.get("max_age_days", 7)
    
    try:
        archived_count = mcp_server.auto_archive_old_test_agents(max_age_days=max_age_days)
        
        return success_response({
            "message": f"Archived {archived_count} old test/demo agents",
            "archived_count": archived_count,
            "max_age_days": max_age_days,
            "note": "Only test/demo agents older than the threshold were archived. Active agents were not affected. Note: This also runs automatically on server startup with a 7-day threshold."
        })
    except Exception as e:
        return [error_response(f"Failed to archive old test agents: {str(e)}")]


async def handle_get_agent_api_key(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle get_agent_api_key tool"""
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]
    
    regenerate = arguments.get("regenerate", False)
    
    if agent_id not in mcp_server.agent_metadata:
        return [error_response(
            f"Agent '{agent_id}' does not exist",
            {"suggestion": "Create the agent first by calling process_agent_update"}
        )]
    
    meta = mcp_server.agent_metadata[agent_id]
    
    # Generate key if missing or if regenerating
    if meta.api_key is None or regenerate:
        if regenerate and meta.api_key:
            print(f"[UNITARES MCP] Regenerating API key for '{agent_id}' (old key invalidated)", file=sys.stderr)
        else:
            print(f"[UNITARES MCP] Generating API key for existing agent '{agent_id}'", file=sys.stderr)
        
        meta.api_key = mcp_server.generate_api_key()
        await mcp_server.save_metadata_async()
    
    return success_response({
        "agent_id": agent_id,
        "api_key": meta.api_key,
        "warning": "⚠️  Save this API key securely - you'll need it for all future updates to authenticate as this agent.",
        "security_note": "This key proves ownership of your agent identity. Keep it secret - anyone with this key can update your agent's state."
    })
