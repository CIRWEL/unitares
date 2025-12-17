"""
MCP Handlers for Agent Lifecycle Management

Handles agent creation, metadata, archiving, deletion, and API key management.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
from datetime import datetime, timedelta
import sys
import hashlib
from src.db import get_db

# Import from mcp_server_std module (using shared utility)
from .shared import get_mcp_server
mcp_server = get_mcp_server()

from .utils import (
    require_agent_id,
    require_registered_agent,
    success_response,
    error_response
)
from .error_helpers import (
    agent_not_found_error,
    authentication_error,
    authentication_required_error,
    ownership_error,
    validation_error,
    system_error as system_error_helper
)
from .decorators import mcp_tool
from src.governance_monitor import UNITARESMonitor
from src.logging_utils import get_logger

logger = get_logger(__name__)


@mcp_tool("list_agents", timeout=15.0, rate_limit_exempt=True)
async def handle_list_agents(arguments: ToolArgumentsDict) -> Sequence[TextContent]:
    """List all agents currently being monitored with lifecycle metadata and health status
    
    LITE MODE: Use lite=true for minimal response (~1KB vs ~15KB)
    """
    try:
        # Reload metadata to ensure we have latest state (non-blocking)
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, mcp_server.load_metadata)
        
        # LITE MODE: Minimal response for local/smaller models (DEFAULT)
        lite_mode = arguments.get("lite", True)
        if lite_mode:
            # Helper to identify test agents
            def is_test_agent(agent_id: str) -> bool:
                aid_lower = agent_id.lower()
                return (
                    agent_id.startswith("test_") or 
                    agent_id.startswith("demo_") or
                    "test" in aid_lower or
                    "demo" in aid_lower
                )
            
            # Ultra-compact response - only real agents
            agents = []
            for agent_id, meta in mcp_server.agent_metadata.items():
                if meta.status != "active":
                    continue
                if meta.total_updates < 2:
                    continue
                if is_test_agent(agent_id):  # Filter test agents
                    continue
                agents.append({
                    "id": agent_id,
                    "updates": meta.total_updates,
                    "last": meta.last_update[:10] if meta.last_update else None,
                })
            agents.sort(key=lambda x: x.get("updates", 0), reverse=True)
            return success_response({
                "agents": agents[:20],  # Top 20 only
                "total": len(agents),
                "more": "list_agents(lite=false) for full details" if len(agents) > 20 else None
            })
        
        grouped = arguments.get("grouped", True)
        include_metrics = arguments.get("include_metrics", True)
        status_filter = arguments.get("status_filter", "active")  # Changed: default to active only
        loaded_only = arguments.get("loaded_only", False)
        summary_only = arguments.get("summary_only", False)
        standardized = arguments.get("standardized", True)
        include_test_agents = arguments.get("include_test_agents", False)  # Default: filter out test agents
        min_updates = arguments.get("min_updates", 2)  # NEW: filter out one-shot agents by default
        
        # Pagination support (optimization)
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit")  # None = no limit (backward compatible)

        agents_list = []
        
        # Helper function to identify test agents (consistent with auto_archive_old_test_agents)
        def is_test_agent(agent_id: str) -> bool:
            """Identify test/demo agents by naming patterns"""
            agent_id_lower = agent_id.lower()
            return (
                agent_id.startswith("test_") or 
                agent_id.startswith("demo_") or
                agent_id.startswith("test") or
                "test" in agent_id_lower or
                "demo" in agent_id_lower
            )
        
        # First pass: collect all matching agents (without loading monitors)
        for agent_id, meta in mcp_server.agent_metadata.items():
            # Filter by status if requested
            if status_filter != "all" and meta.status != status_filter:
                continue
            
            # Filter out test agents by default (unless explicitly requested)
            if not include_test_agents and is_test_agent(agent_id):
                continue
            
            # Filter out low-activity agents (one-shot fragmentation cleanup)
            if min_updates and meta.total_updates < min_updates:
                continue
            
            # Filter by loaded status if requested
            if loaded_only:
                if agent_id not in mcp_server.monitors:
                    continue
            
            agent_info = {
                "agent_id": agent_id,
                "lifecycle_status": meta.status,
                "created": meta.created_at,
                "last_update": meta.last_update,
                "total_updates": meta.total_updates,
                "tags": meta.tags.copy() if meta.tags else [],
                "notes": meta.notes if meta.notes else "",
            }
            
            # Lazy load metrics only if requested (optimization)
            if include_metrics:
                # Only load monitor if already in memory (fast path)
                if agent_id in mcp_server.monitors:
                    try:
                        monitor = mcp_server.monitors[agent_id]
                        metrics = monitor.get_metrics()
                        
                        # Calculate health_status consistently with process_agent_update
                        # Use health_checker.get_health_status() instead of metrics.get("status")
                        # to ensure consistency across all tools
                        risk_score = metrics.get("risk_score") or metrics.get("current_risk")
                        coherence = float(monitor.state.coherence) if monitor.state else None
                        void_active = bool(monitor.state.void_active) if monitor.state else False
                        
                        health_status_obj, _ = mcp_server.health_checker.get_health_status(
                            risk_score=risk_score,
                            coherence=coherence,
                            void_active=void_active
                        )
                        agent_info["health_status"] = health_status_obj.value
                        agent_info["metrics"] = {
                            "E": float(monitor.state.E),
                            "I": float(monitor.state.I),
                            "S": float(monitor.state.S),
                            "V": float(monitor.state.V),
                            "coherence": float(monitor.state.coherence),
                            "current_risk": metrics.get("current_risk"),  # Recent trend (last 10) - USED FOR HEALTH STATUS
                            "risk_score": float(metrics.get("risk_score") or metrics.get("current_risk") or metrics.get("mean_risk", 0.5)),  # Governance/operational risk
                            "phi": metrics.get("phi"),  # Primary physics signal: Φ objective function
                            "verdict": metrics.get("verdict"),  # Primary governance signal: safe/caution/high-risk
                            "mean_risk": float(metrics.get("mean_risk", 0.5)),  # Overall mean (all-time average) - for historical context
                            "lambda1": float(monitor.state.lambda1),
                            "void_active": bool(monitor.state.void_active)
                        }
                    except Exception as e:
                        agent_info["health_status"] = "error"
                        agent_info["metrics"] = None
                        logger.warning(f"Error getting metrics for {agent_id}: {e}")
                else:
                    # Monitor not in memory - try cached health status first, calculate if missing
                    cached_health = getattr(meta, 'health_status', None)
                    if cached_health and cached_health != "unknown":
                        agent_info["health_status"] = cached_health
                    else:
                        # No cached health status or it's "unknown" - calculate it
                        try:
                            monitor = mcp_server.get_or_create_monitor(agent_id)
                            metrics_dict = monitor.get_metrics()
                            risk_score = metrics_dict.get('risk_score', None)
                            coherence = metrics_dict.get('coherence', None)
                            void_active = metrics_dict.get('void_active', False)
                            
                            health_status_obj, _ = mcp_server.health_checker.get_health_status(
                                risk_score=attention_score,
                                coherence=coherence,
                                void_active=void_active
                            )
                            agent_info["health_status"] = health_status_obj.value
                            
                            # Cache for future use
                            if meta:
                                meta.health_status = health_status_obj.value
                        except Exception as e:
                            logger.debug(f"Could not calculate health status for agent '{agent_id}': {e}")
                            agent_info["health_status"] = "unknown"
                    agent_info["metrics"] = None
            else:
                # No metrics requested - try cached health_status first, calculate if missing
                cached_health = getattr(meta, 'health_status', None)
                if cached_health and cached_health != "unknown":
                    agent_info["health_status"] = cached_health
                else:
                    # No cached health status or it's "unknown" - calculate it
                    try:
                        monitor = mcp_server.get_or_create_monitor(agent_id)
                        metrics_dict = monitor.get_metrics()
                        attention_score = metrics_dict.get('attention_score') or metrics_dict.get('risk_score', None)
                        coherence = metrics_dict.get('coherence', None)
                        void_active = metrics_dict.get('void_active', False)
                        
                        health_status_obj, _ = mcp_server.health_checker.get_health_status(
                            risk_score=attention_score,
                            coherence=coherence,
                            void_active=void_active
                        )
                        agent_info["health_status"] = health_status_obj.value
                        
                        # Cache for future use
                        if meta:
                            meta.health_status = health_status_obj.value
                    except Exception as e:
                        logger.debug(f"Could not calculate health status for agent '{agent_id}': {e}")
                        agent_info["health_status"] = "unknown"
                agent_info["metrics"] = None
            
            # Add standardized fields if requested
            if standardized:
                agent_info.setdefault("health_status", "unknown")
                agent_info.setdefault("metrics", None)
            
            agents_list.append(agent_info)
        
        # Sort by last_update (most recent first)
        agents_list.sort(key=lambda x: x.get("last_update", ""), reverse=True)
        
        # Apply pagination (optimization)
        total_count = len(agents_list)
        if limit is not None:
            agents_list = agents_list[offset:offset + limit]
        elif offset > 0:
            agents_list = agents_list[offset:]
        
        # Group by status if requested
        if grouped and not summary_only:
            grouped_agents = {
                "active": [a for a in agents_list if a.get("lifecycle_status") == "active"],
                "waiting_input": [a for a in agents_list if a.get("lifecycle_status") == "waiting_input"],
                "paused": [a for a in agents_list if a.get("lifecycle_status") == "paused"],
                "archived": [a for a in agents_list if a.get("lifecycle_status") == "archived"],
                "deleted": [a for a in agents_list if a.get("lifecycle_status") == "deleted"]
            }
            
            response_data = {
                "success": True,
                "agents": grouped_agents,
                "summary": {
                    "total": total_count,  # Use total_count (before pagination)
                    "returned": len(agents_list),  # Number actually returned (after pagination)
                    "offset": offset,
                    "limit": limit,
                    "by_status": {
                        "active": sum(1 for a in agents_list if a.get("lifecycle_status") == "active"),
                        "waiting_input": sum(1 for a in agents_list if a.get("lifecycle_status") == "waiting_input"),
                        "paused": sum(1 for a in agents_list if a.get("lifecycle_status") == "paused"),
                        "archived": sum(1 for a in agents_list if a.get("lifecycle_status") == "archived"),
                        "deleted": sum(1 for a in agents_list if a.get("lifecycle_status") == "deleted")
                    }
                }
            }
            
            # Add health breakdown if include_metrics
            if include_metrics:
                response_data["summary"]["by_health"] = {
                    "healthy": sum(1 for a in agents_list if a.get("health_status") == "healthy"),
                    "moderate": sum(1 for a in agents_list if a.get("health_status") == "moderate"),
                    "critical": sum(1 for a in agents_list if a.get("health_status") == "critical"),
                    "unknown": sum(1 for a in agents_list if a.get("health_status") == "unknown"),
                    "error": sum(1 for a in agents_list if a.get("health_status") == "error")
                }
        else:
            response_data = {
                "success": True,
                "agents": agents_list,
                "summary": {
                    "total": total_count,  # Use total_count (before pagination)
                    "returned": len(agents_list),  # Number actually returned (after pagination)
                    "offset": offset,
                    "limit": limit,
                    "by_status": {
                        "active": sum(1 for a in agents_list if a.get("lifecycle_status") == "active"),
                        "waiting_input": sum(1 for a in agents_list if a.get("lifecycle_status") == "waiting_input"),
                        "paused": sum(1 for a in agents_list if a.get("lifecycle_status") == "paused"),
                        "archived": sum(1 for a in agents_list if a.get("lifecycle_status") == "archived"),
                        "deleted": sum(1 for a in agents_list if a.get("lifecycle_status") == "deleted")
                    }
                }
            }
            
            if include_metrics:
                health_statuses = {"healthy": 0, "moderate": 0, "critical": 0, "unknown": 0, "error": 0}
                for agent in agents_list:
                    status = agent.get("health_status", "unknown")
                    health_statuses[status] = health_statuses.get(status, 0) + 1
                response_data["summary"]["by_health"] = health_statuses
        
        if summary_only:
            return success_response(response_data["summary"])
        
        # Add EISV labels for API documentation (only if metrics are included)
        if include_metrics:
            response_data["eisv_labels"] = UNITARESMonitor.get_eisv_labels()
        
        return success_response(response_data)
        
    except Exception as e:
        return system_error_helper(
            "list_agents",
            e
        )


@mcp_tool("get_agent_metadata", timeout=10.0)
async def handle_get_agent_metadata(arguments: Sequence[TextContent]) -> list:
    """Get complete metadata for an agent including lifecycle events, current state, and computed fields"""
    # PROACTIVE GATE: Require agent to be registered
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]  # Returns onboarding guidance if not registered
    
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
    
    # Add EISV labels for API documentation (only if current_state exists)
    if "current_state" in metadata_response:
        metadata_response["eisv_labels"] = UNITARESMonitor.get_eisv_labels()
    
    return success_response(metadata_response)


@mcp_tool("update_agent_metadata", timeout=10.0)
async def handle_update_agent_metadata(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Update agent tags and notes
    
    SECURITY: Requires API key authentication and ownership verification.
    Agents can only update their own metadata.
    """
    # SECURITY FIX: Require registered agent_id (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    # Reload metadata to ensure we have latest state (non-blocking)
    import asyncio
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, mcp_server.load_metadata)
    
    if agent_id not in mcp_server.agent_metadata:
        return agent_not_found_error(agent_id)
    
    meta = mcp_server.agent_metadata[agent_id]
    
    # SECURITY FIX: Require API key authentication
    api_key = arguments.get("api_key")
    
    # FRICTION FIX: Auto-fallback to session-bound identity if API key not provided
    if not api_key:
        try:
            from .identity import get_bound_agent_id, get_bound_api_key
            bound_id = get_bound_agent_id(arguments=arguments)
            if bound_id == agent_id:
                bound_key = get_bound_api_key(arguments=arguments)
                if bound_key:
                    api_key = bound_key
                    arguments["api_key"] = api_key
                    logger.debug(f"Auto-retrieved API key from session-bound identity for agent '{agent_id}'")
            else:
                bound_id_fallback = get_bound_agent_id()
                if bound_id_fallback == agent_id:
                    bound_key_fallback = get_bound_api_key()
                    if bound_key_fallback:
                        api_key = bound_key_fallback
                        arguments["api_key"] = api_key
                        logger.debug(f"Auto-retrieved API key from session-bound identity (fallback) for agent '{agent_id}'")
        except (ImportError, AttributeError, Exception):
            pass  # Continue with auth check below
    
    if not api_key:
        return [error_response(
            "API key required to update agent metadata. "
            "Agent metadata updates require authentication to prevent unauthorized modifications.",
            recovery={
                "action": "Provide api_key parameter or bind your identity",
                "related_tools": ["get_agent_api_key", "bind_identity"],
                "workflow": [
                    "Option 1: Get API key via get_agent_api_key and include in update_agent_metadata call",
                    "Option 2: Call bind_identity(agent_id, api_key) once, then API key auto-retrieved from session"
                ]
            }
        )]
    
    # SECURITY FIX: Verify API key matches agent_id (ownership check)
    if not meta.api_key or meta.api_key != api_key:
        return [error_response(
            "Invalid API key for updating agent metadata. "
            "API key must match the agent_id. You can only update your own metadata.",
            recovery={
                "action": "Verify your API key matches your agent_id",
                "related_tools": ["get_agent_api_key"],
                "workflow": "1. Get correct API key for your agent_id 2. Retry with correct key"
            }
        )]
    
    # Update tags if provided
    if "tags" in arguments:
        meta.tags = arguments["tags"]
    
    # Update notes if provided
    if "notes" in arguments:
        append_notes = arguments.get("append_notes", False)
        if append_notes:
            timestamp = datetime.now().isoformat()
            meta.notes = f"{meta.notes}\n[{timestamp}] {arguments['notes']}" if meta.notes else f"[{timestamp}] {arguments['notes']}"
        else:
            meta.notes = arguments["notes"]

    # Update purpose if provided
    if "purpose" in arguments:
        purpose = arguments.get("purpose")
        if purpose is None:
            # Allow explicit null to clear purpose
            meta.purpose = None
        elif isinstance(purpose, str):
            purpose_str = purpose.strip()
            meta.purpose = purpose_str if purpose_str else None
    
    # Schedule batched metadata save (non-blocking)
    import asyncio
    loop = asyncio.get_running_loop()
    await mcp_server.schedule_metadata_save(force=False)

    # DUAL-WRITE: Update metadata in PostgreSQL (Phase 3 migration)
    try:
        db = get_db()
        await db.update_identity_metadata(
            agent_id=agent_id,
            metadata={
                "tags": meta.tags,
                "notes": meta.notes,
                "purpose": getattr(meta, "purpose", None),
                "updated_at": datetime.now().isoformat()
            },
            merge=True
        )

        # Also keep core.agents in sync (purpose is a first-class column there).
        # Use partial update to avoid accidental api_key overwrites.
        if hasattr(db, "update_agent_fields"):
            await db.update_agent_fields(
                agent_id,
                status=getattr(meta, "status", None),
                purpose=getattr(meta, "purpose", None),
                notes=getattr(meta, "notes", None),
                tags=getattr(meta, "tags", None),
                parent_agent_id=getattr(meta, "parent_agent_id", None),
                spawn_reason=getattr(meta, "spawn_reason", None),
            )
        logger.debug(f"Dual-write: Updated metadata in new DB for {agent_id}")
    except Exception as e:
        # Non-fatal: old DB still works, log and continue
        logger.warning(f"Dual-write metadata update failed: {e}", exc_info=True)

    return success_response({
        "success": True,
        "message": "Agent metadata updated",
        "agent_id": agent_id,
        "tags": meta.tags,
        "notes": meta.notes,
        "purpose": getattr(meta, "purpose", None),
        "updated_at": datetime.now().isoformat()
    })


@mcp_tool("archive_agent", timeout=15.0)
async def handle_archive_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Archive an agent for long-term storage
    
    SECURITY: Requires API key authentication and ownership verification.
    Agents can only archive themselves.
    """
    # SECURITY FIX: Require registered agent_id (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    # Reload metadata to ensure we have latest state (non-blocking)
    import asyncio
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, mcp_server.load_metadata)
    
    if agent_id not in mcp_server.agent_metadata:
        return agent_not_found_error(agent_id)
    
    meta = mcp_server.agent_metadata[agent_id]
    
    if meta.status == "archived":
        return [error_response(
            f"Agent '{agent_id}' is already archived",
            error_code="AGENT_ALREADY_ARCHIVED",
            error_category="validation_error",
            details={"error_type": "agent_already_archived", "agent_id": agent_id, "status": meta.status},
            recovery={
                "action": "Agent is already archived",
                "related_tools": ["get_agent_metadata", "list_agents"],
                "workflow": ["1. Check agent status with get_agent_metadata", "2. Archived agents cannot be archived again"]
            }
        )]
    
    # SECURITY FIX: Require API key authentication
    # Use centralized fallback chain (explicit → session → metadata → SQLite)
    from .utils import get_api_key_with_fallback
    api_key = get_api_key_with_fallback(agent_id, arguments)
    
    if not api_key:
        return [error_response(
            "API key required to archive agent. "
            "Agent archiving requires authentication to prevent unauthorized agent lifecycle changes.",
            recovery={
                "action": "Provide api_key parameter or bind your identity",
                "related_tools": ["get_agent_api_key", "bind_identity"],
                "workflow": [
                    "Option 1: Get API key via get_agent_api_key and include in archive_agent call",
                    "Option 2: Call bind_identity(agent_id, api_key) once, then API key auto-retrieved from session"
                ]
            }
        )]
    
    # SECURITY FIX: Verify API key matches agent_id (ownership check - can only archive yourself)
    if not meta.api_key or meta.api_key != api_key:
        return [error_response(
            "Invalid API key for archiving agent. "
            "API key must match the agent_id. You can only archive your own agent.",
            recovery={
                "action": "Verify your API key matches your agent_id",
                "related_tools": ["get_agent_api_key"],
                "workflow": "1. Get correct API key for your agent_id 2. Retry with correct key"
            }
        )]
    
    reason = arguments.get("reason", "Manual archive")
    keep_in_memory = arguments.get("keep_in_memory", False)
    
    meta.status = "archived"
    meta.archived_at = datetime.now().isoformat()
    meta.add_lifecycle_event("archived", reason)
    
    # Optionally unload from memory
    if not keep_in_memory and agent_id in mcp_server.monitors:
        del mcp_server.monitors[agent_id]
    
    # Schedule batched metadata save (non-blocking)
    import asyncio
    loop = asyncio.get_running_loop()
    await mcp_server.schedule_metadata_save(force=False)

    # DUAL-WRITE: Update status to archived in PostgreSQL (Phase 3 migration)
    try:
        db = get_db()
        await db.update_identity_status(
            agent_id=agent_id,
            status="archived",
            disabled_at=datetime.now()
        )
        logger.debug(f"Dual-write: Archived identity in new DB for {agent_id}")
    except Exception as e:
        # Non-fatal: old DB still works, log and continue
        logger.warning(f"Dual-write archive status failed: {e}", exc_info=True)

    return success_response({
        "success": True,
        "message": f"Agent '{agent_id}' archived successfully",
        "agent_id": agent_id,
        "lifecycle_status": "archived",
        "archived_at": meta.archived_at,
        "reason": reason,
        "kept_in_memory": keep_in_memory
    })


@mcp_tool("delete_agent", timeout=15.0)
async def handle_delete_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle delete_agent tool - delete agent and archive data (protected: cannot delete pioneer agents)
    
    SECURITY: Requires API key authentication and ownership verification.
    Agents can only delete themselves.
    """
    # SECURITY FIX: Require registered agent_id (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    confirm = arguments.get("confirm", False)
    if not confirm:
        return [error_response("Deletion requires explicit confirmation (confirm=true)")]
    
    # Reload metadata to ensure we have latest state (non-blocking)
    import asyncio
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, mcp_server.load_metadata)
    
    if agent_id not in mcp_server.agent_metadata:
        return agent_not_found_error(agent_id)
    
    meta = mcp_server.agent_metadata[agent_id]
    
    # Check if agent is a pioneer (protected)
    if "pioneer" in meta.tags:
        return [error_response(
            f"Cannot delete pioneer agent '{agent_id}'",
            recovery={
                "action": "Pioneer agents are protected from deletion. Use archive_agent instead.",
                "related_tools": ["archive_agent"],
                "workflow": ["1. Call archive_agent to archive instead of delete", "2. Pioneer agents preserve system history"]
            }
        )]
    
    # SECURITY FIX: Require API key authentication
    api_key = arguments.get("api_key")
    
    # FRICTION FIX: Auto-fallback to session-bound identity if API key not provided
    if not api_key:
        try:
            from .identity import get_bound_agent_id, get_bound_api_key
            bound_id = get_bound_agent_id(arguments=arguments)
            if bound_id == agent_id:
                bound_key = get_bound_api_key(arguments=arguments)
                if bound_key:
                    api_key = bound_key
                    arguments["api_key"] = api_key
                    logger.debug(f"Auto-retrieved API key from session-bound identity for agent '{agent_id}'")
            else:
                bound_id_fallback = get_bound_agent_id()
                if bound_id_fallback == agent_id:
                    bound_key_fallback = get_bound_api_key()
                    if bound_key_fallback:
                        api_key = bound_key_fallback
                        arguments["api_key"] = api_key
                        logger.debug(f"Auto-retrieved API key from session-bound identity (fallback) for agent '{agent_id}'")
        except (ImportError, AttributeError, Exception):
            pass  # Continue with auth check below
    
    if not api_key:
        return [error_response(
            "API key required to delete agent. "
            "Agent deletion requires authentication to prevent unauthorized agent lifecycle changes.",
            recovery={
                "action": "Provide api_key parameter or bind your identity",
                "related_tools": ["get_agent_api_key", "bind_identity"],
                "workflow": [
                    "Option 1: Get API key via get_agent_api_key and include in delete_agent call",
                    "Option 2: Call bind_identity(agent_id, api_key) once, then API key auto-retrieved from session"
                ]
            }
        )]
    
    # SECURITY FIX: Verify API key matches agent_id (ownership check - can only delete yourself)
    if not meta.api_key or meta.api_key != api_key:
        return [error_response(
            "Invalid API key for deleting agent. "
            "API key must match the agent_id. You can only delete your own agent.",
            recovery={
                "action": "Verify your API key matches your agent_id",
                "related_tools": ["get_agent_api_key"],
                "workflow": "1. Get correct API key for your agent_id 2. Retry with correct key"
            }
        )]
    
    backup_first = arguments.get("backup_first", True)
    
    # Backup if requested
    backup_path = None
    if backup_first:
        try:
            import json
            import asyncio
            from pathlib import Path
            backup_dir = Path(mcp_server.project_root) / "data" / "archives"
            backup_file = backup_dir / f"{agent_id}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            backup_data = {
                "agent_id": agent_id,
                "metadata": meta.to_dict(),
                "backed_up_at": datetime.now().isoformat()
            }
            
            # Write backup file in executor to avoid blocking event loop
            loop = asyncio.get_running_loop()
            def _write_backup_sync():
                """Synchronous backup write - runs in executor"""
                # Create directory if needed (inside executor to avoid blocking)
                backup_dir.mkdir(parents=True, exist_ok=True)
                
                # Write backup file
                with open(backup_file, 'w', encoding='utf-8') as f:
                    json.dump(backup_data, f, indent=2)
            
            await loop.run_in_executor(None, _write_backup_sync)
            backup_path = str(backup_file)
        except Exception as e:
            logger.warning(f"Could not backup agent before deletion: {e}")
    
    # Delete agent
    meta.status = "deleted"
    meta.add_lifecycle_event("deleted", "Manual deletion")
    
    # Remove from monitors
    if agent_id in mcp_server.monitors:
        del mcp_server.monitors[agent_id]
    
    # Schedule batched metadata save (non-blocking)
    import asyncio
    loop = asyncio.get_running_loop()
    await mcp_server.schedule_metadata_save(force=False)

    # DUAL-WRITE: Update status to deleted in PostgreSQL (Phase 3 migration)
    try:
        db = get_db()
        await db.update_identity_status(
            agent_id=agent_id,
            status="deleted",
            disabled_at=datetime.now()
        )
        logger.debug(f"Dual-write: Deleted identity in new DB for {agent_id}")
    except Exception as e:
        # Non-fatal: old DB still works, log and continue
        logger.warning(f"Dual-write delete status failed: {e}", exc_info=True)

    return success_response({
        "success": True,
        "message": f"Agent '{agent_id}' deleted successfully",
        "agent_id": agent_id,
        "archived": backup_path is not None,
        "backup_path": backup_path
    })


@mcp_tool("archive_old_test_agents", timeout=20.0, rate_limit_exempt=True)
async def handle_archive_old_test_agents(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Archive stale agents - test agents by default, or ALL stale agents with include_all=true
    
    Use include_all=true to clean up any agent inactive for max_age_days (default: 3 days)
    """
    max_age_hours = arguments.get("max_age_hours", 6)  # Default: 6 hours for test agents
    max_age_days = arguments.get("max_age_days")  # Backward compatibility: convert days to hours
    include_all = arguments.get("include_all", False)  # NEW: archive ALL stale agents, not just test
    dry_run = arguments.get("dry_run", False)  # NEW: preview without archiving
    
    # If include_all, use longer default (3 days)
    if include_all and max_age_days is None and "max_age_hours" not in arguments:
        max_age_days = 3
    
    # Convert days to hours if provided (backward compatibility)
    if max_age_days is not None:
        max_age_hours = max_age_days * 24
    
    if max_age_hours < 0.1:
        return [error_response("max_age_hours must be at least 0.1 (6 minutes)")]
    
    # Reload metadata to ensure we have latest state (non-blocking)
    import asyncio
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, mcp_server.load_metadata)
    
    archived_agents = []
    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
    
    for agent_id, meta in list(mcp_server.agent_metadata.items()):
        # Filter: only test/demo agents unless include_all
        is_test = (agent_id.startswith("test_") or agent_id.startswith("demo_") or "test" in agent_id.lower())
        if not include_all and not is_test:
            continue
        
        # Skip if already archived/deleted
        if meta.status in ["archived", "deleted"]:
            continue
        
        # Archive immediately if very low update count (1-2 updates = just a ping/test)
        if meta.total_updates <= 2 and is_test:
            if not dry_run:
                meta.status = "archived"
                meta.archived_at = datetime.now().isoformat()
                meta.add_lifecycle_event("archived", f"Auto-archived: test/ping agent with {meta.total_updates} update(s)")
                # Unload from memory
                if agent_id in mcp_server.monitors:
                    del mcp_server.monitors[agent_id]
            archived_agents.append({"id": agent_id, "reason": "low_updates", "updates": meta.total_updates})
            continue
        
        # Check age for agents with more updates
        try:
            last_update_dt = datetime.fromisoformat(meta.last_update.replace('Z', '+00:00').replace('+00:00', ''))
        except:
            continue
            
        if last_update_dt < cutoff_time:
            age_hours = (datetime.now() - last_update_dt).total_seconds() / 3600
            age_days = age_hours / 24
            if not dry_run:
                meta.status = "archived"
                meta.archived_at = datetime.now().isoformat()
                meta.add_lifecycle_event("archived", f"Inactive for {age_hours:.1f} hours (threshold: {max_age_hours} hours)")
                # Unload from memory
                if agent_id in mcp_server.monitors:
                    del mcp_server.monitors[agent_id]
            archived_agents.append({"id": agent_id, "reason": "stale", "days_inactive": round(age_days, 1)})
    
    if archived_agents and not dry_run:
        # Schedule batched metadata save (non-blocking)
        await mcp_server.schedule_metadata_save(force=False)
    
    return success_response({
        "success": True,
        "dry_run": dry_run,
        "archived_count": len(archived_agents),
        "archived_agents": archived_agents[:20],  # Limit output
        "total_would_archive": len(archived_agents),
        "max_age_days": max_age_hours / 24,
        "include_all": include_all,
        "action": "preview - use dry_run=false to execute" if dry_run else "archived"
    })


@mcp_tool("get_agent_api_key", timeout=10.0)
async def handle_get_agent_api_key(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Get or generate API key for an agent"""
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]
    
    regenerate = arguments.get("regenerate", False)
    
    # Check if agent exists
    is_new_agent = agent_id not in mcp_server.agent_metadata
    
    # SECURITY: For existing agents, require authentication to get/regenerate key
    if not is_new_agent:
        # Use centralized fallback chain (explicit → session → metadata → SQLite)
        from .utils import get_api_key_with_fallback
        api_key = get_api_key_with_fallback(agent_id, arguments)
        
        if not api_key:
            return [error_response(
                "Authentication required to retrieve API key for existing agent. Provide your api_key parameter.",
                recovery={
                    "action": "Include your api_key in the request to prove ownership",
                    "related_tools": ["list_agents", "bind_identity"],
                    "workflow": "If you've bound your identity with bind_identity(), API key should auto-retrieve. Otherwise, contact system administrator for recovery."
                }
            )]
        
        # Verify authentication
        meta = mcp_server.agent_metadata[agent_id]
        if meta.api_key != api_key:
            return [error_response(
                "Invalid API key. Cannot retrieve key for another agent.",
                recovery={
                    "action": "Use your own API key to retrieve your own key",
                    "related_tools": ["list_agents"]
                }
            )]
    
    # Get or create metadata (creates agent if new)
    # Check if purpose was passed through arguments (for quick_start/hello)
    purpose = arguments.get("purpose")
    purpose_str = purpose.strip() if isinstance(purpose, str) and purpose.strip() else None

    # IMPORTANT: If creating a new agent, pass purpose at creation time so the
    # AgentMetadata is initialized with purpose (matches core.py behavior).
    if is_new_agent and purpose_str:
        meta = mcp_server.get_or_create_metadata(agent_id, purpose=purpose_str)
    else:
        meta = mcp_server.get_or_create_metadata(agent_id)

    # Persist purpose updates for existing agents (or if creation-time kwargs were missed)
    if purpose_str and getattr(meta, "purpose", None) != purpose_str:
        meta.purpose = purpose_str
        # Force immediate save: purpose is documentation/forensics metadata and should persist promptly
        # (For new agents, this is redundant with the is_new_agent force-save below but harmless.)
        if not is_new_agent:
            await mcp_server.schedule_metadata_save(force=True)
    
    # CRITICAL: Force immediate save for new agent creation to prevent key rotation bug
    # If metadata isn't saved, process_agent_update's load_metadata() will wipe it out
    if is_new_agent:
        import asyncio
        loop = asyncio.get_running_loop()
        await mcp_server.schedule_metadata_save(force=True)
    
    # Regenerate API key if requested (requires auth for existing agents)
    if regenerate:
        if not is_new_agent and not api_key:
            return authentication_required_error(
                "regenerating API key for existing agent",
                context={"agent_id": agent_id, "operation": "regenerate_api_key"}
            )
        
        new_key = mcp_server.generate_api_key()
        meta.api_key = new_key
        # Force immediate save for API key regeneration (critical operation)
        import asyncio
        loop = asyncio.get_running_loop()
        await mcp_server.schedule_metadata_save(force=True)
        
        # Log regeneration for audit
        from src.audit_log import audit_logger
        audit_logger.log("api_key_regenerated", {
            "agent_id": agent_id,
            "regenerated_by": "self" if not is_new_agent else "new_agent"
        })
        
        return success_response({
            "success": True,
            "agent_id": agent_id,
            "api_key": new_key,
            "is_new": False,
            "regenerated": True,
            "message": "API key regenerated - old key is now invalid"
        })
    
    return success_response({
        "success": True,
        "agent_id": agent_id,
        "api_key": meta.api_key,
        "is_new": agent_id not in mcp_server.agent_metadata or meta.total_updates == 0,
        "regenerated": False,
        "message": "API key retrieved" if meta.api_key else "API key generated"
    })


@mcp_tool("mark_response_complete", timeout=5.0)
async def handle_mark_response_complete(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Mark agent as having completed response, waiting for input"""
    # SECURITY FIX: Require registered agent (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    # Verify API key if provided
    api_key = arguments.get("api_key")
    meta = mcp_server.agent_metadata.get(agent_id)
    if api_key:
        if meta and hasattr(meta, 'api_key') and meta.api_key != api_key:
            return authentication_error(
                "Authentication failed: Invalid API key",
                agent_id=agent_id,
                context={"operation": "mark_response_complete"}
            )
    
    # Get existing metadata (already verified to exist above)
    
    # Update status to waiting_input
    meta.status = "waiting_input"
    meta.last_response_at = datetime.now().isoformat()
    meta.response_completed = True
    
    # Add lifecycle event
    summary = arguments.get("summary", "")
    meta.add_lifecycle_event("response_completed", summary if summary else "Response completed, waiting for input")
    
    # Schedule batched metadata save (non-blocking)
    import asyncio
    loop = asyncio.get_running_loop()
    await mcp_server.schedule_metadata_save(force=False)
    
    # MAINTENANCE PROMPT: Surface open discoveries from this session
    # Behavioral nudge: Remind agent to resolve discoveries before ending session
    open_discoveries = []
    try:
        from src.knowledge_graph import get_knowledge_graph
        # Note: datetime and timedelta already imported at module level (line 9)
        
        graph = await get_knowledge_graph()
        
        # Get open discoveries from this agent (recent - last 24 hours)
        now = datetime.now()
        one_day_ago = (now - timedelta(hours=24)).isoformat()
        
        all_agent_discoveries = await graph.query(
            agent_id=agent_id,
            status="open",
            limit=20  # Get recent discoveries
        )
        
        # Filter to recent discoveries (last 24 hours)
        recent_open = [
            d for d in all_agent_discoveries
            if d.timestamp >= one_day_ago
        ]
        
        # Prioritize bug_found and high severity
        recent_open.sort(key=lambda d: (
            0 if d.type == "bug_found" else 1,  # Bugs first
            0 if d.severity == "high" else 1 if d.severity == "medium" else 2,  # High severity first
            d.timestamp  # Then by recency
        ))
        
        open_discoveries = recent_open[:5]  # Top 5 for prompt
        
    except Exception as e:
        # Don't fail if knowledge graph check fails - this is a nice-to-have prompt
        logger.warning(f"Could not check open discoveries: {e}")
    
    response_data = {
        "success": True,
        "message": "Response completion marked",
        "agent_id": agent_id,
        "status": "waiting_input",
        "last_response_at": meta.last_response_at,
        "response_completed": True
    }
    
    # Add maintenance prompt if there are open discoveries
    if open_discoveries:
        response_data["maintenance_prompt"] = {
            "message": f"You have {len(open_discoveries)} open discovery/discoveries from this session. Consider resolving them:",
            "open_discoveries": [
                {
                    "id": d.id,
                    "summary": d.summary,
                    "type": d.type,
                    "severity": d.severity,
                    "timestamp": d.timestamp
                }
                for d in open_discoveries
            ],
            "suggested_actions": [
                "Mark as resolved: update_discovery_status_graph(discovery_id='...', status='resolved')",
                "If discovery is incorrect or needs correction, use dialectic: request_dialectic_review(discovery_id='...', dispute_type='dispute')",
                "Archive if obsolete: update_discovery_status_graph(discovery_id='...', status='archived')"
            ],
            "related_tools": [
                "update_discovery_status_graph",
                "request_dialectic_review",
                "search_knowledge_graph"
            ],
            "tip": "Resolving discoveries helps maintain knowledge graph quality. Use dialectic for collaborative corrections."
        }
    
    return success_response(response_data)


@mcp_tool("direct_resume_if_safe", timeout=10.0)
async def handle_direct_resume_if_safe(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Direct resume without dialectic if agent state is safe. Tier 1 recovery for simple stuck scenarios.
    
    SECURITY: Requires registered agent_id and API key authentication.
    """
    # SECURITY FIX: Require registered agent_id (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    # Reload metadata to ensure we have latest state (non-blocking)
    import asyncio
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, mcp_server.load_metadata)
    
    meta = mcp_server.agent_metadata.get(agent_id)
    if not meta:
        return agent_not_found_error(agent_id)
    
    # SECURITY FIX: Require API key authentication
    api_key = arguments.get("api_key")
    
    # FRICTION FIX: Auto-fallback to session-bound identity if API key not provided
    if not api_key:
        try:
            from .identity import get_bound_agent_id, get_bound_api_key
            bound_id = get_bound_agent_id(arguments=arguments)
            if bound_id == agent_id:
                bound_key = get_bound_api_key(arguments=arguments)
                if bound_key:
                    api_key = bound_key
                    arguments["api_key"] = api_key
                    logger.debug(f"Auto-retrieved API key from session-bound identity for agent '{agent_id}'")
            else:
                bound_id_fallback = get_bound_agent_id()
                if bound_id_fallback == agent_id:
                    bound_key_fallback = get_bound_api_key()
                    if bound_key_fallback:
                        api_key = bound_key_fallback
                        arguments["api_key"] = api_key
                        logger.debug(f"Auto-retrieved API key from session-bound identity (fallback) for agent '{agent_id}'")
        except (ImportError, AttributeError, Exception):
            pass  # Continue with auth check below
    
    if not api_key:
        return [error_response(
            "API key required for direct resume. "
            "Direct resume requires authentication to prevent unauthorized state changes.",
            recovery={
                "action": "Provide api_key parameter or bind your identity",
                "related_tools": ["get_agent_api_key", "bind_identity"],
                "workflow": [
                    "Option 1: Get API key via get_agent_api_key and include in direct_resume_if_safe call",
                    "Option 2: Call bind_identity(agent_id, api_key) once, then API key auto-retrieved from session"
                ]
            }
        )]
    
    # SECURITY FIX: Verify API key matches agent_id (ownership check)
    if not meta.api_key or meta.api_key != api_key:
        return [error_response(
            "Authentication failed: Invalid API key. "
            "API key must match the agent_id.",
            recovery={
                "action": "Verify your API key matches your agent_id",
                "related_tools": ["get_agent_api_key"],
                "workflow": "1. Get correct API key for your agent_id 2. Retry with correct key"
            }
        )]
    
    # Get current governance metrics
    try:
        monitor = mcp_server.get_or_create_monitor(agent_id)
        metrics = monitor.get_metrics()
        
        coherence = float(monitor.state.coherence)
        risk_score = float(metrics.get("mean_risk", 0.5))
        void_active = bool(monitor.state.void_active)
        status = meta.status
        
    except Exception as e:
        return system_error_helper(
            "get_governance_metrics",
            e,
            context={"agent_id": agent_id}
        )
    
    # Safety checks
    safety_checks = {
        "coherence_ok": coherence > 0.40,
        "risk_ok": risk_score < 0.60,
        "no_void": not void_active,
        "status_ok": status in ["paused", "waiting_input", "moderate"]
    }
    
    if not all(safety_checks.values()):
        failed_checks = [k for k, v in safety_checks.items() if not v]
        return [error_response(
            f"Not safe to resume. Failed checks: {failed_checks}. "
            f"Metrics: coherence={coherence:.3f}, risk={risk_score:.3f}, "
            f"void_active={void_active}, status={status}. "
            f"Use request_dialectic_review for complex recovery."
        )]
    
    # Get conditions if provided
    conditions = arguments.get("conditions", [])
    reason = arguments.get("reason", "Direct resume - state is safe")
    
    # Resume agent
    meta.status = "active"
    meta.paused_at = None
    meta.add_lifecycle_event("resumed", f"Direct resume: {reason}. Conditions: {conditions}")
    
    # Schedule batched metadata save (non-blocking)
    import asyncio
    loop = asyncio.get_running_loop()
    await mcp_server.schedule_metadata_save(force=False)
    
    return success_response({
        "success": True,
        "message": "Agent resumed successfully",
        "agent_id": agent_id,
        "action": "resumed",
        "conditions": conditions,
        "reason": reason,
        "metrics": {
            "coherence": coherence,
            "risk_score": risk_score,
            "void_active": void_active,
            "previous_status": status
        },
        "note": "Agent resumed via Tier 1 recovery (direct resume). Use request_dialectic_review for complex cases."
    })
