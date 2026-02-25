"""
MCP Handlers for Agent Lifecycle Management

Handles agent creation, metadata, archiving, deletion, and API key management.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
from datetime import datetime, timedelta
import sys
import hashlib
# PostgreSQL-only agent storage (single source of truth)
from src import agent_storage

# Import from mcp_server_std module (using shared utility)
from .shared import get_mcp_server
mcp_server = get_mcp_server()

from .types import ToolArgumentsDict
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
from config.governance_config import GovernanceConfig

logger = get_logger(__name__)


def _is_test_agent(agent_id: str) -> bool:
    """Identify test/demo agents by naming patterns.
    
    Used consistently across list_agents handlers to filter test agents.
    """
    agent_id_lower = agent_id.lower()
    return (
        agent_id.startswith("test_") or 
        agent_id.startswith("demo_") or
        agent_id.startswith("test") or
        "test" in agent_id_lower or
        "demo" in agent_id_lower
    )


@mcp_tool("list_agents", timeout=15.0, rate_limit_exempt=True, register=False)
async def handle_list_agents(arguments: ToolArgumentsDict) -> Sequence[TextContent]:
    """List all agents currently being monitored with lifecycle metadata and health status
    
    LITE MODE: Use lite=true for minimal response (~1KB vs ~15KB)
    """
    try:
        # Reload metadata from DB to pick up external changes (archival, etc.)
        import time
        try:
            cache_age = time.time() - mcp_server._metadata_cache_state.get("last_load_time", 0)
            if cache_age > 60:  # Refresh from DB at most every 60s
                await mcp_server.load_metadata_async(force=True)
        except (AttributeError, TypeError):
            pass  # Mock or missing cache state — skip reload
        
        # LITE MODE: Minimal response for local/smaller models (DEFAULT)
        lite_explicit = "lite" in arguments
        lite_mode = arguments.get("lite", True)
        # If caller is asking for non-lite behavior (metrics/pagination/filters), honor it
        # even if they didn't explicitly set lite=false.
        if not lite_explicit:
            if arguments.get("include_metrics") is True:
                lite_mode = False
            elif arguments.get("limit") is not None or arguments.get("offset") is not None:
                lite_mode = False
            elif arguments.get("status_filter") not in (None, "active"):
                lite_mode = False
            elif arguments.get("include_test_agents") is True:
                lite_mode = False
            elif arguments.get("summary_only") is True or arguments.get("grouped") is False:
                lite_mode = False
        if lite_mode:
            from datetime import datetime, timedelta, timezone

            # Ultra-compact response - only real agents
            limit = arguments.get("limit", 20)
            status_filter = arguments.get("status_filter", "active")
            include_test_agents = arguments.get("include_test_agents", False)
            # Default: include zero-update agents so newly created agents are discoverable.
            # Callers can still pass min_updates=1 to hide ghost agents.
            min_updates = arguments.get("min_updates", 0)
            # Smart default: show labeled agents first; if none, show active unlabeled ones
            named_only = arguments.get("named_only")  # None = auto, True/False = explicit
            # NEW: Filter by recency - default 7 days to reduce noise from stale agents
            recent_days = arguments.get("recent_days", 7)

            # Calculate cutoff time for recency filter
            cutoff_time = None
            if recent_days and recent_days > 0:
                cutoff_time = datetime.now(timezone.utc) - timedelta(days=recent_days)

            agents = []
            total_all = 0  # Count all agents before filtering
            for agent_id, meta in mcp_server.agent_metadata.items():
                total_all += 1
                if status_filter != "all" and meta.status != status_filter:
                    continue
                if min_updates and meta.total_updates < min_updates:
                    continue
                if not include_test_agents and _is_test_agent(agent_id):  # Filter test agents
                    continue
                if named_only is True and not getattr(meta, 'label', None):
                    continue
                if named_only is False:
                    pass  # Show everything
                elif named_only is None:
                    # Auto mode: skip unlabeled agents with 0 updates (ghosts)
                    if not getattr(meta, 'label', None) and meta.total_updates < 1:
                        continue

                # Apply recency filter
                if cutoff_time and meta.last_update:
                    try:
                        last_dt = datetime.fromisoformat(meta.last_update.replace('Z', '+00:00'))
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        if last_dt < cutoff_time:
                            continue  # Skip stale agents
                    except Exception:
                        pass  # Keep agents with unparseable dates

                agents.append({
                    "id": agent_id,
                    "label": getattr(meta, 'label', None),
                    "purpose": getattr(meta, 'purpose', None),  # Added for social awareness
                    "updates": meta.total_updates,
                    "last": meta.last_update[:10] if meta.last_update else None,
                    "last_update": meta.last_update,
                    "trust_tier": getattr(meta, 'trust_tier', None),
                })
            # Sort: labeled first, then by most recent activity
            agents.sort(key=lambda x: (0 if x.get("label") else 1, -(x.get("updates") or 0), x.get("last_update", "") or ""), reverse=False)
            for a in agents:
                a.pop("last_update", None)

            result = {
                "agents": agents[: max(0, int(limit))] if limit is not None else agents,
                "shown": min(len(agents), int(limit)) if limit else len(agents),
                "matching": len(agents),  # How many matched filters
                "total_all": total_all,  # Total agents in system
            }

            # Add helpful hints
            if len(agents) > int(limit):
                result["more"] = f"Showing {limit} of {len(agents)} recent. Use limit=50 or recent_days=30 to see more."
            if recent_days:
                result["filter"] = f"Active in last {recent_days} days. Use recent_days=0 for all."

            return success_response(result)
        
        grouped = arguments.get("grouped", True)
        include_metrics = arguments.get("include_metrics", True)
        status_filter = arguments.get("status_filter", "active")  # Changed: default to active only
        loaded_only = arguments.get("loaded_only", False)
        summary_only = arguments.get("summary_only", False)
        standardized = arguments.get("standardized", True)
        include_test_agents = arguments.get("include_test_agents", False)  # Default: filter out test agents
        # Default: include zero-update agents so newly created agents are discoverable.
        # Callers can still pass min_updates=2 to hide one-shot / placeholder agents.
        min_updates = arguments.get("min_updates", 0)
        
        # Pagination support (optimization)
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit")  # None = no limit (backward compatible)

        agents_list = []
        
        # First pass: collect all matching agents (without loading monitors)
        for agent_id, meta in mcp_server.agent_metadata.items():
            # Filter by status if requested
            if status_filter != "all" and meta.status != status_filter:
                continue
            
            # Filter out test agents by default (unless explicitly requested)
            if not include_test_agents and _is_test_agent(agent_id):
                continue
            
            # Filter out low-activity agents (one-shot fragmentation cleanup)
            if min_updates and meta.total_updates < min_updates:
                continue
            
            # Filter by loaded status if requested
            if loaded_only:
                if agent_id not in mcp_server.monitors:
                    continue
            
            # Infer status for agents with None/unrecognized status
            inferred_status = meta.status
            if inferred_status not in ["active", "waiting_input", "paused", "archived", "deleted"]:
                # Infer status based on activity patterns
                now = datetime.now(timezone.utc)
                
                # Check if agent has any activity
                has_updates = meta.total_updates > 0
                is_recent = False
                days_since_update = None
                
                if meta.last_update:
                    try:
                        last_dt = datetime.fromisoformat(meta.last_update.replace('Z', '+00:00'))
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        days_since_update = (now - last_dt).total_seconds() / 86400
                        is_recent = days_since_update < 7  # Active within last week
                    except Exception:
                        pass
                
                # Infer status:
                # - No updates or no last_update = archived (inactive)
                # - Recent activity (<7 days) = active
                # - Old activity (>7 days) = archived
                if not has_updates or meta.last_update is None:
                    inferred_status = "archived"  # No activity = archived
                elif is_recent:
                    inferred_status = "active"  # Recent activity = active
                else:
                    inferred_status = "archived"  # Old activity = archived
            
            agent_info = {
                "agent_id": agent_id,
                "label": getattr(meta, 'label', None),
                "purpose": getattr(meta, 'purpose', None),
                "lifecycle_status": inferred_status,
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
                        # Safely convert to float, handling None values
                        def safe_float(val, default=0.0):
                            if val is None:
                                return default
                            try:
                                return float(val)
                            except (TypeError, ValueError):
                                return default
                        
                        agent_info["metrics"] = {
                            "E": safe_float(monitor.state.E),
                            "I": safe_float(monitor.state.I),
                            "S": safe_float(monitor.state.S),
                            "V": safe_float(monitor.state.V),
                            "coherence": safe_float(monitor.state.coherence),
                            "current_risk": metrics.get("current_risk"),  # Recent trend (last 10) - USED FOR HEALTH STATUS
                            "risk_score": safe_float(metrics.get("risk_score") or metrics.get("current_risk") or metrics.get("mean_risk", 0.5)),  # Governance/operational risk
                            "phi": metrics.get("phi"),  # Primary physics signal: Φ objective function
                            "verdict": metrics.get("verdict"),  # Primary governance signal: safe/caution/high-risk
                            "mean_risk": safe_float(metrics.get("mean_risk", 0.5)),  # Overall mean (all-time average) - for historical context
                            "lambda1": safe_float(monitor.state.lambda1),
                            "void_active": bool(monitor.state.void_active) if monitor.state.void_active is not None else False
                        }
                    except Exception as e:
                        agent_info["health_status"] = "error"
                        agent_info["metrics"] = None
                        logger.warning(f"Error getting metrics for {agent_id}: {e}")
                else:
                    # Monitor not in memory - load it to get metrics
                    cached_health = getattr(meta, 'health_status', None)
                    try:
                        monitor = mcp_server.get_or_create_monitor(agent_id)
                        metrics_dict = monitor.get_metrics()
                        
                        # Get health status
                        if cached_health and cached_health != "unknown":
                            agent_info["health_status"] = cached_health
                        else:
                            risk_score = metrics_dict.get('risk_score', None)
                            coherence = float(monitor.state.coherence) if monitor.state else metrics_dict.get('coherence', None)
                            void_active = bool(monitor.state.void_active) if monitor.state else metrics_dict.get('void_active', False)

                            health_status_obj, _ = mcp_server.health_checker.get_health_status(
                                risk_score=risk_score,
                                coherence=coherence,
                                void_active=void_active
                            )
                            agent_info["health_status"] = health_status_obj.value
                            
                            # Cache for future use
                            if meta:
                                meta.health_status = health_status_obj.value
                        
                        # Populate metrics from monitor state
                        if monitor.state:
                            # Safely convert to float, handling None values
                            def safe_float(val, default=0.0):
                                if val is None:
                                    return default
                                try:
                                    return float(val)
                                except (TypeError, ValueError):
                                    return default
                            
                            agent_info["metrics"] = {
                                "E": safe_float(monitor.state.E),
                                "I": safe_float(monitor.state.I),
                                "S": safe_float(monitor.state.S),
                                "V": safe_float(monitor.state.V),
                                "coherence": safe_float(monitor.state.coherence),
                                "current_risk": metrics_dict.get("current_risk"),
                                "risk_score": safe_float(metrics_dict.get("risk_score") or metrics_dict.get("current_risk") or metrics_dict.get("mean_risk", 0.5)),
                                "phi": metrics_dict.get("phi"),
                                "verdict": metrics_dict.get("verdict"),
                                "mean_risk": safe_float(metrics_dict.get("mean_risk", 0.5)),
                                "lambda1": safe_float(monitor.state.lambda1),
                                "void_active": bool(monitor.state.void_active) if monitor.state.void_active is not None else False
                            }
                        else:
                            agent_info["metrics"] = None
                    except Exception as e:
                        logger.debug(f"Could not load metrics for agent '{agent_id}': {e}")
                        agent_info["health_status"] = cached_health or "unknown"
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

            # Trust tier from cached trajectory data, with DB fallback
            cached_tier = getattr(meta, 'trust_tier', None)
            if cached_tier is None:
                try:
                    from src.trajectory_identity import compute_trust_tier
                    from src.db import get_db as _get_db
                    identity = await _get_db().get_identity(agent_id)
                    if identity and identity.metadata:
                        tier_info = compute_trust_tier(identity.metadata)
                        cached_tier = tier_info.get("name", "unknown")
                        # Cache for next time
                        meta.trust_tier = cached_tier
                        meta.trust_tier_num = tier_info.get("tier", 0)
                except Exception as e:
                    logger.debug(f"Trust tier DB fallback failed for {agent_id[:8]}: {e}")
            agent_info["trust_tier"] = cached_tier

            agents_list.append(agent_info)
        
        # Sort by last_update (most recent first)
        agents_list.sort(key=lambda x: x.get("last_update", ""), reverse=True)
        
        # Calculate status counts BEFORE pagination (for accurate totals)
        total_count = len(agents_list)
        status_counts = {
            "active": sum(1 for a in agents_list if a.get("lifecycle_status") == "active"),
            "waiting_input": sum(1 for a in agents_list if a.get("lifecycle_status") == "waiting_input"),
            "paused": sum(1 for a in agents_list if a.get("lifecycle_status") == "paused"),
            "archived": sum(1 for a in agents_list if a.get("lifecycle_status") == "archived"),
            "deleted": sum(1 for a in agents_list if a.get("lifecycle_status") == "deleted"),
            "unknown": sum(1 for a in agents_list if a.get("lifecycle_status") not in ["active", "waiting_input", "paused", "archived", "deleted"])
        }
        
        # Apply pagination (optimization)
        if limit is not None:
            agents_list = agents_list[offset:offset + limit]
        elif offset > 0:
            agents_list = agents_list[offset:]
        
        # Group by status if requested (for returned agents only)
        if grouped and not summary_only:
            grouped_agents = {
                "active": [a for a in agents_list if a.get("lifecycle_status") == "active"],
                "waiting_input": [a for a in agents_list if a.get("lifecycle_status") == "waiting_input"],
                "paused": [a for a in agents_list if a.get("lifecycle_status") == "paused"],
                "archived": [a for a in agents_list if a.get("lifecycle_status") == "archived"],
                "deleted": [a for a in agents_list if a.get("lifecycle_status") == "deleted"],
                "unknown": [a for a in agents_list if a.get("lifecycle_status") not in ["active", "waiting_input", "paused", "archived", "deleted"]]
            }
            
            response_data = {
                "success": True,
                "agents": grouped_agents,
                "summary": {
                    "total": total_count,  # Use total_count (before pagination)
                    "returned": len(agents_list),  # Number actually returned (after pagination)
                    "offset": offset,
                    "limit": limit,
                    "by_status": status_counts  # Use counts from BEFORE pagination
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
                    "by_status": status_counts  # Use counts from BEFORE pagination
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


@mcp_tool("get_agent_metadata", timeout=10.0, register=False)
async def handle_get_agent_metadata(arguments: Sequence[TextContent]) -> list:
    """Get complete metadata for an agent including lifecycle events, current state, and computed fields.

    Args:
        target_agent: Optional UUID or label of agent to look up.
                      If not provided, returns calling agent's metadata.
    """
    # Check for target_agent parameter (allows looking up other agents by UUID or label)
    target_agent = arguments.get("target_agent") or arguments.get("agent_id")

    if target_agent:
        # FAST PATH: Check Redis cache first (by UUID)
        try:
            from src.cache import get_metadata_cache
            metadata_cache = get_metadata_cache()
            cached_meta = await metadata_cache.get(target_agent)
            if cached_meta:
                # Found in Redis cache - use it directly
                logger.debug(f"Metadata cache hit: {target_agent[:8]}...")
                agent_id = target_agent
                # Convert cached dict back to AgentMetadata for consistency
                from src.mcp_server_std import AgentMetadata
                meta = AgentMetadata(**cached_meta)
                # Update in-memory cache for consistency
                mcp_server.agent_metadata[agent_id] = meta
                # Skip to response building (meta already loaded)
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
                        "V": float(monitor.state.V),
                    }
                else:
                    metadata_response["current_state"] = None
                # Add EISV labels (UNITARESMonitor imported at module level)
                metadata_response["eisv_labels"] = UNITARESMonitor.get_eisv_labels()
                return success_response(metadata_response)
        except Exception as e:
            logger.debug(f"Metadata cache check failed: {e}")
        
        # Look up by UUID first (in-memory cache)
        if target_agent in mcp_server.agent_metadata:
            agent_id = target_agent
        else:
            # Try label lookup in cache
            agent_id = None
            for uuid_key, m in mcp_server.agent_metadata.items():
                if getattr(m, 'label', None) == target_agent:
                    agent_id = uuid_key
                    break
            
            # If not found in cache, reload metadata and try again (might be new agent)
            if not agent_id:
                try:
                    # Reload metadata to get latest agents
                    await mcp_server.load_metadata_async()
                    # Try UUID lookup again after reload
                    if target_agent in mcp_server.agent_metadata:
                        agent_id = target_agent
                    else:
                        # Try label lookup again after reload
                        for uuid_key, m in mcp_server.agent_metadata.items():
                            if getattr(m, 'label', None) == target_agent:
                                agent_id = uuid_key
                                break
                except Exception as e:
                    logger.debug(f"Metadata reload failed: {e}")
            
            if not agent_id:
                # Provide helpful error message
                return [error_response(
                    f"Agent not found: '{target_agent}'. Use UUID or label.",
                    recovery={
                        "action": "Use list_agents() to find valid agent IDs",
                        "tip": "Labels are case-sensitive. Use list_agents(named_only=true) to see agents with labels.",
                        "note": "If you just set a label with identity(name='...'), it may take a moment to persist. Try again in a few seconds."
                    },
                    details={
                        "searched_in": "in-memory cache and PostgreSQL",
                        "suggestion": "Use UUID from list_agents() output, or wait a moment if you just set a label"
                    }
                )]
    else:
        # Default: get calling agent's metadata
        agent_id, error = require_registered_agent(arguments)
        if error:
            return [error]  # Returns onboarding guidance if not registered

    meta = mcp_server.agent_metadata[agent_id]
    monitor = mcp_server.monitors.get(agent_id)
    
    # Populate Redis cache for future lookups (best effort, non-blocking)
    try:
        from src.cache import get_metadata_cache
        await get_metadata_cache().set(agent_id, meta.to_dict(), ttl=300)
    except Exception as e:
        logger.debug(f"Failed to cache metadata: {e}")
    
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
    try:
        from datetime import timezone
        if meta.last_update:
            # Handle various datetime formats
            last_update_str = meta.last_update.replace('Z', '+00:00')
            last_update_dt = datetime.fromisoformat(last_update_str)
            if last_update_dt.tzinfo is None:
                last_update_dt = last_update_dt.replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            days_since = (now_dt - last_update_dt).days
            metadata_response["days_since_update"] = days_since
        else:
            metadata_response["days_since_update"] = None
    except Exception as e:
        logger.debug(f"Could not calculate days_since_update: {e}")
        metadata_response["days_since_update"] = None
    
    # Add EISV labels for API documentation (only if current_state exists)
    if "current_state" in metadata_response:
        metadata_response["eisv_labels"] = UNITARESMonitor.get_eisv_labels()
    
    return success_response(metadata_response)


@mcp_tool("update_agent_metadata", timeout=10.0, register=False)
async def handle_update_agent_metadata(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Update agent tags and notes

    SECURITY: Requires API key authentication and ownership verification.
    Agents can only update their own metadata.
    """
    # === KWARGS STRING UNWRAPPING ===
    if arguments and "kwargs" in arguments and isinstance(arguments["kwargs"], str):
        try:
            import json
            kwargs_parsed = json.loads(arguments["kwargs"])
            if isinstance(kwargs_parsed, dict):
                del arguments["kwargs"]
                arguments.update(kwargs_parsed)
        except (json.JSONDecodeError, TypeError):
            pass

    # Check write permission (bound=true required for writes)
    from .identity_shared import require_write_permission
    allowed, write_error = require_write_permission(arguments=arguments)
    if not allowed:
        return [write_error]
    
    # SECURITY FIX: Require registered agent_id (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    # Reload metadata from PostgreSQL (async)
    await mcp_server.load_metadata_async(force=True)

    if agent_id not in mcp_server.agent_metadata:
        return agent_not_found_error(agent_id)
    
    meta = mcp_server.agent_metadata[agent_id]

    # SECURITY: Verify ownership via session binding (UUID-based auth, Dec 2025)
    from .utils import verify_agent_ownership
    if not verify_agent_ownership(agent_id, arguments):
        return [error_response(
            "Authentication required. You can only update your own metadata.",
            error_code="AUTH_REQUIRED",
            error_category="auth_error",
            recovery={
                "action": "Ensure your session is bound to this agent",
                "related_tools": ["identity"],
                "workflow": "Identity auto-binds on first tool call. Use identity() to check binding."
            }
        )]

    # Update status if provided (reactivation from archived)
    if "status" in arguments:
        new_status = arguments["status"]
        if new_status != "active":
            return [error_response(
                f"Only status='active' is supported (to reactivate archived agents). Got '{new_status}'.",
                error_code="INVALID_STATUS_TRANSITION",
            )]
        if getattr(meta, "status", None) != "archived":
            return [error_response(
                f"Agent is already '{getattr(meta, 'status', 'unknown')}', no status change needed.",
                error_code="INVALID_STATUS_TRANSITION",
            )]
        meta.status = "active"
        meta.archived_at = None

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

    # Update preferences if provided (v2.5.0+)
    if "preferences" in arguments:
        prefs = arguments.get("preferences")
        if prefs is None:
            meta.preferences = None
        elif isinstance(prefs, dict):
            # Validate verbosity if present
            if "verbosity" in prefs:
                valid_verbosity = {"minimal", "compact", "standard", "full", "auto"}
                if prefs["verbosity"] not in valid_verbosity:
                    return [error_response(
                        f"Invalid verbosity '{prefs['verbosity']}'. Valid options: {', '.join(valid_verbosity)}",
                        error_code="INVALID_PREFERENCE"
                    )]
            meta.preferences = prefs

    # PostgreSQL: Update metadata (single source of truth)
    try:
        await agent_storage.update_agent(
            agent_id=agent_id,
            status=getattr(meta, "status", None),
            tags=meta.tags,
            notes=meta.notes,
            purpose=getattr(meta, "purpose", None),
            parent_agent_id=getattr(meta, "parent_agent_id", None),
            spawn_reason=getattr(meta, "spawn_reason", None),
        )
        logger.debug(f"PostgreSQL: Updated metadata for {agent_id}")
        
        # Invalidate Redis cache
        try:
            from src.cache import get_metadata_cache
            await get_metadata_cache().invalidate(agent_id)
        except Exception as e:
            logger.debug(f"Cache invalidation failed: {e}")
    except Exception as e:
        logger.warning(f"PostgreSQL update_agent failed: {e}", exc_info=True)

    return success_response({
        "success": True,
        "message": "Agent metadata updated",
        "agent_id": agent_id,
        "tags": meta.tags,
        "notes": meta.notes,
        "purpose": getattr(meta, "purpose", None),
        "preferences": getattr(meta, "preferences", None),
        "updated_at": datetime.now().isoformat()
    })


@mcp_tool("archive_agent", timeout=15.0, register=False)
async def handle_archive_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Archive an agent for long-term storage
    
    SECURITY: Requires API key authentication and ownership verification.
    Agents can only archive themselves.
    """
    # SECURITY FIX: Require registered agent_id (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    # Use authoritative UUID for internal lookups (agent_id might be a label)
    # require_registered_agent sets this after validating registration
    agent_uuid = arguments.get("_agent_uuid") or agent_id

    # Reload metadata from PostgreSQL (async)
    await mcp_server.load_metadata_async(force=True)
    
    if agent_uuid not in mcp_server.agent_metadata:
        return agent_not_found_error(agent_id)
    
    meta = mcp_server.agent_metadata[agent_uuid]
    
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
    
    # SECURITY: Verify ownership via session binding (UUID-based auth, Dec 2025)
    from .utils import verify_agent_ownership
    if not verify_agent_ownership(agent_uuid, arguments):
        return [error_response(
            "Authentication required. You can only archive your own agent.",
            error_code="AUTH_REQUIRED",
            error_category="auth_error",
            recovery={
                "action": "Ensure your session is bound to this agent",
                "related_tools": ["identity"],
                "workflow": "Identity auto-binds on first tool call. Use identity() to check binding."
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
    
    # PostgreSQL: Archive agent (single source of truth)
    try:
        await agent_storage.archive_agent(agent_id)
        logger.debug(f"PostgreSQL: Archived agent {agent_id}")
        
        # Invalidate Redis cache
        try:
            from src.cache import get_metadata_cache
            await get_metadata_cache().invalidate(agent_id)
        except Exception as e:
            logger.debug(f"Cache invalidation failed: {e}")
    except Exception as e:
        logger.warning(f"PostgreSQL archive_agent failed: {e}", exc_info=True)

    return success_response({
        "success": True,
        "message": f"Agent '{agent_id}' archived successfully",
        "agent_id": agent_id,
        "lifecycle_status": "archived",
        "archived_at": meta.archived_at,
        "reason": reason,
        "kept_in_memory": keep_in_memory
    })


@mcp_tool("resume_agent", timeout=15.0, register=False)
async def handle_resume_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Resume a paused/stuck agent from the dashboard.

    Lightweight resume handler for human operators (dashboard).
    No ownership check — mirrors archive_agent pattern.
    Only resumes agents in paused or waiting_input status.
    """
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    agent_uuid = arguments.get("_agent_uuid") or agent_id

    # Reload metadata from PostgreSQL (async)
    await mcp_server.load_metadata_async(force=True)

    if agent_uuid not in mcp_server.agent_metadata:
        return agent_not_found_error(agent_id)

    meta = mcp_server.agent_metadata[agent_uuid]

    # Allow resuming paused/waiting_input agents AND "unsticking" active agents
    # Stuck agents are typically still "active" but caught in a timeout/loop
    is_stuck_unstick = meta.status == "active" and arguments.get("unstick", False)
    if meta.status not in ("paused", "waiting_input") and not is_stuck_unstick:
        return [error_response(
            f"Agent '{agent_id}' is '{meta.status}', not resumable (must be paused or waiting_input)",
            error_code="AGENT_NOT_RESUMABLE",
            error_category="validation_error",
            details={"error_type": "agent_not_resumable", "agent_id": agent_id, "status": meta.status},
            recovery={
                "action": "Agent must be in paused or waiting_input status to resume",
                "related_tools": ["get_agent_metadata", "list_agents"],
                "workflow": ["1. Check agent status with get_agent_metadata", "2. Only paused/waiting_input agents can be resumed"]
            }
        )]

    reason = arguments.get("reason", "Resumed from dashboard")
    previous_status = meta.status

    meta.status = "active"
    meta.paused_at = None
    meta.add_lifecycle_event("resumed" if not is_stuck_unstick else "unstuck", reason)

    # PostgreSQL: Update status and refresh last_update to clear stuck detection
    try:
        await agent_storage.update_agent(agent_uuid, status="active")
        # Refresh last_update so detect_stuck_agents no longer flags this agent
        if is_stuck_unstick:
            await agent_storage.update_agent(agent_uuid, last_update=datetime.now().isoformat())
        logger.debug(f"PostgreSQL: {'Unstuck' if is_stuck_unstick else 'Resumed'} agent {agent_id}")

        # Invalidate Redis cache
        try:
            from src.cache import get_metadata_cache
            await get_metadata_cache().invalidate(agent_id)
        except Exception as e:
            logger.debug(f"Cache invalidation failed: {e}")
    except Exception as e:
        logger.warning(f"PostgreSQL update_agent failed: {e}", exc_info=True)

    return success_response({
        "success": True,
        "message": f"Agent '{agent_id}' resumed successfully",
        "agent_id": agent_id,
        "lifecycle_status": "active",
        "previous_status": previous_status,
        "reason": reason,
        "resumed_at": datetime.now().isoformat()
    })


@mcp_tool("delete_agent", timeout=15.0, register=False)
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
    
    # Use authoritative UUID for internal lookups
    agent_uuid = arguments.get("_agent_uuid") or agent_id

    # Reload metadata from PostgreSQL (async)
    await mcp_server.load_metadata_async(force=True)
    
    if agent_uuid not in mcp_server.agent_metadata:
        return agent_not_found_error(agent_id)
    
    meta = mcp_server.agent_metadata[agent_uuid]
    
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
    
    # SECURITY: Verify ownership via session binding (UUID-based auth, Dec 2025)
    from .utils import verify_agent_ownership
    if not verify_agent_ownership(agent_uuid, arguments):
        return [error_response(
            "Authentication required. You can only delete your own agent.",
            error_code="AUTH_REQUIRED",
            error_category="auth_error",
            recovery={
                "action": "Ensure your session is bound to this agent",
                "related_tools": ["identity"],
                "workflow": "Identity auto-binds on first tool call. Use identity() to check binding."
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
    
    # PostgreSQL: Delete agent (single source of truth)
    try:
        await agent_storage.delete_agent(agent_id)
        logger.debug(f"PostgreSQL: Deleted agent {agent_id}")
        
        # Invalidate Redis cache
        try:
            from src.cache import get_metadata_cache
            await get_metadata_cache().invalidate(agent_id)
        except Exception as e:
            logger.debug(f"Cache invalidation failed: {e}")
    except Exception as e:
        logger.warning(f"PostgreSQL delete_agent failed: {e}", exc_info=True)

    return success_response({
        "success": True,
        "message": f"Agent '{agent_id}' deleted successfully",
        "agent_id": agent_id,
        "archived": backup_path is not None,
        "backup_path": backup_path
    })


@mcp_tool("archive_old_test_agents", timeout=20.0, rate_limit_exempt=True, register=False)
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
    
    # Reload metadata from PostgreSQL (async)
    await mcp_server.load_metadata_async(force=True)
    
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
                # PostgreSQL: Archive agent
                try:
                    await agent_storage.archive_agent(agent_id)
                except Exception as e:
                    logger.debug(f"PostgreSQL archive failed for {agent_id}: {e}")
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
                # PostgreSQL: Archive agent
                try:
                    await agent_storage.archive_agent(agent_id)
                except Exception as e:
                    logger.debug(f"PostgreSQL archive failed for {agent_id}: {e}")
            archived_agents.append({"id": agent_id, "reason": "stale", "days_inactive": round(age_days, 1)})
    
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


@mcp_tool("archive_orphan_agents", timeout=30.0, rate_limit_exempt=True)
async def handle_archive_orphan_agents(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Aggressively archive orphan agents to prevent proliferation.

    Targets UUID-named agents without labels that have low/no updates.
    Much more aggressive than archive_old_test_agents.

    Thresholds (configurable):
    - zero_update_hours: Archive UUID agents with 0 updates after this (default: 1h)
    - low_update_hours: Archive unlabeled agents with 0-1 updates after this (default: 3h)
    - unlabeled_hours: Archive unlabeled UUID agents with 2+ updates after this (default: 6h)

    Preserves:
    - Agents with labels/display names
    - Agents with "pioneer" tag
    - Recently active agents
    """
    import re
    UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

    zero_update_hours = float(arguments.get("zero_update_hours", 1.0))
    low_update_hours = float(arguments.get("low_update_hours", 3.0))
    unlabeled_hours = float(arguments.get("unlabeled_hours", 6.0))
    dry_run = arguments.get("dry_run", False)

    # Reload metadata from PostgreSQL (async)
    await mcp_server.load_metadata_async(force=True)

    archived_agents = []
    current_time = datetime.now()

    for agent_id, meta in list(mcp_server.agent_metadata.items()):
        # Skip if already archived or deleted
        if meta.status in ["archived", "deleted"]:
            continue

        # Never archive pioneers
        if "pioneer" in (meta.tags or []):
            continue

        # Check if agent has a meaningful label
        has_label = bool(getattr(meta, 'label', None) or getattr(meta, 'display_name', None))
        is_uuid_named = bool(UUID_PATTERN.match(agent_id))

        # Calculate age
        try:
            last_update_str = meta.last_update or meta.created_at
            last_update_dt = datetime.fromisoformat(
                last_update_str.replace('Z', '+00:00') if 'Z' in last_update_str else last_update_str
            )
            if last_update_dt.tzinfo:
                from datetime import timezone
                age_delta = datetime.now(timezone.utc) - last_update_dt
            else:
                age_delta = current_time - last_update_dt
            age_hours = age_delta.total_seconds() / 3600
        except (ValueError, TypeError, AttributeError):
            continue

        updates = getattr(meta, 'total_updates', 0) or 0
        should_archive = False
        reason = ""

        # Rule 1: UUID-named, 0 updates, older than zero_update_hours
        if is_uuid_named and updates == 0 and age_hours >= zero_update_hours:
            should_archive = True
            reason = f"orphan UUID, 0 updates, {age_hours:.1f}h"

        # Rule 2: Unlabeled, 0-1 updates, older than low_update_hours
        elif not has_label and updates <= 1 and age_hours >= low_update_hours:
            should_archive = True
            reason = f"unlabeled, {updates} updates, {age_hours:.1f}h"

        # Rule 3: UUID-named + unlabeled, 2+ updates but very old
        elif is_uuid_named and not has_label and updates >= 2 and age_hours >= unlabeled_hours:
            should_archive = True
            reason = f"stale UUID, {updates} updates, {age_hours:.1f}h"

        if should_archive:
            if not dry_run:
                meta.status = "archived"
                meta.archived_at = current_time.isoformat()
                meta.add_lifecycle_event("archived", f"Orphan cleanup: {reason}")
                # Unload from memory
                if agent_id in mcp_server.monitors:
                    del mcp_server.monitors[agent_id]
                # PostgreSQL: Archive agent
                try:
                    await agent_storage.archive_agent(agent_id)
                except Exception as e:
                    logger.debug(f"PostgreSQL archive failed for {agent_id}: {e}")
            archived_agents.append({
                "id": agent_id[:12] + "...",
                "reason": reason,
                "updates": updates,
                "label": getattr(meta, 'label', None)
            })

    return success_response({
        "success": True,
        "dry_run": dry_run,
        "archived_count": len(archived_agents),
        "archived_agents": archived_agents[:30],  # Limit output
        "total_would_archive": len(archived_agents),
        "thresholds": {
            "zero_update_hours": zero_update_hours,
            "low_update_hours": low_update_hours,
            "unlabeled_hours": unlabeled_hours
        },
        "action": "preview - set dry_run=false to execute" if dry_run else "archived"
    })


# REMOVED: get_agent_api_key (Dec 2025)
# API keys deprecated - UUID-based session auth is now primary.
# Calls to get_agent_api_key are aliased to identity() via tool_stability.py


@mcp_tool("mark_response_complete", timeout=5.0, register=False)
async def handle_mark_response_complete(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Mark agent as having completed response, waiting for input"""
    # SECURITY FIX: Require registered agent (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    # Use authoritative UUID for internal lookups
    agent_uuid = arguments.get("_agent_uuid") or agent_id

    # SECURITY: Verify ownership via session binding (UUID-based auth, Dec 2025)
    from .utils import verify_agent_ownership
    if not verify_agent_ownership(agent_uuid, arguments):
        return [error_response(
            "Authentication required. You can only mark your own agent's response complete.",
            error_code="AUTH_REQUIRED",
            error_category="auth_error",
            recovery={
                "action": "Ensure your session is bound to this agent",
                "related_tools": ["identity"],
                "workflow": "Identity auto-binds on first tool call. Use identity() to check binding."
            }
        )]

    meta = mcp_server.agent_metadata.get(agent_uuid)
    
    # Get existing metadata (already verified to exist above)
    
    # Update status to waiting_input
    meta.status = "waiting_input"
    meta.last_response_at = datetime.now().isoformat()
    meta.response_completed = True

    # Add lifecycle event
    summary = arguments.get("summary", "")
    meta.add_lifecycle_event("response_completed", summary if summary else "Response completed, waiting for input")

    # PostgreSQL: Update status (single source of truth)
    try:
        await agent_storage.update_agent(agent_id, status="waiting_input")
    except Exception as e:
        logger.debug(f"PostgreSQL status update failed: {e}")

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
                "Add correction: store_knowledge_graph(response_to={discovery_id='...', response_type='correction'}, ...)",
                "Archive if obsolete: update_discovery_status_graph(discovery_id='...', status='archived')"
            ],
            "related_tools": [
                "update_discovery_status_graph",
                "store_knowledge_graph",
                "search_knowledge_graph"
            ],
            "tip": "Resolving discoveries helps maintain knowledge graph quality. Use response_to for corrections or additions."
        }
    
    return success_response(response_data)


@mcp_tool("direct_resume_if_safe", timeout=10.0, deprecated=True, superseded_by="quick_resume or self_recovery_review")
async def handle_direct_resume_if_safe(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """⚠️ DEPRECATED: Use quick_resume() or self_recovery_review() instead.
    
    This tool is deprecated in favor of clearer recovery paths:
    - quick_resume() - for clearly safe states (coherence > 0.60, risk < 0.40, no reflection needed)
    - self_recovery_review() - for moderate states with reflection (coherence > 0.35, risk < 0.65)
    
    Migration guidance:
    - If coherence > 0.60 and risk < 0.40 → use quick_resume()
    - Otherwise → use self_recovery_review(reflection="...")
    
    This tool will be removed in v2.0. Current thresholds: coherence > 0.40, risk < 0.60.
    
    SECURITY: Requires registered agent_id and API key authentication.
    """
    # SECURITY FIX: Require registered agent_id (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    # Use authoritative UUID for internal lookups
    agent_uuid = arguments.get("_agent_uuid") or agent_id

    # Reload metadata from PostgreSQL (async)
    await mcp_server.load_metadata_async(force=True)
    
    meta = mcp_server.agent_metadata.get(agent_uuid)
    if not meta:
        return agent_not_found_error(agent_id)
    
    # SECURITY: Verify ownership via session binding (UUID-based auth, Dec 2025)
    from .utils import verify_agent_ownership
    if not verify_agent_ownership(agent_uuid, arguments):
        return [error_response(
            "Authentication required. You can only resume your own agent.",
            error_code="AUTH_REQUIRED",
            error_category="auth_error",
            recovery={
                "action": "Ensure your session is bound to this agent",
                "related_tools": ["identity"],
                "workflow": "Identity auto-binds on first tool call. Use identity() to check binding."
            }
        )]
    
    # Get current governance metrics
    try:
        monitor = mcp_server.get_or_create_monitor(agent_uuid)
        metrics = monitor.get_metrics()
        
        coherence = float(monitor.state.coherence)
        risk_score = float(metrics.get("mean_risk") or 0.5)
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
            f"Check get_governance_metrics and reflect on what needs to change."
        )]
    
    # Get conditions if provided
    conditions = arguments.get("conditions", [])
    reason = arguments.get("reason", "Direct resume - state is safe")
    
    # Resume agent
    meta.status = "active"
    meta.paused_at = None
    meta.add_lifecycle_event("resumed", f"Direct resume: {reason}. Conditions: {conditions}")

    # PostgreSQL: Update status (single source of truth)
    try:
        await agent_storage.update_agent(agent_id, status="active")
    except Exception as e:
        logger.debug(f"PostgreSQL status update failed: {e}")

    response_data = {
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
        "note": "Agent resumed. Check get_governance_metrics periodically to stay aware of your state.",
        "deprecation_warning": {
            "tool": "direct_resume_if_safe",
            "status": "deprecated",
            "message": "This tool is deprecated. Use quick_resume() or self_recovery_review() instead.",
            "migration": {
                "if_coherence_gt_0_60_and_risk_lt_0_40": "Use quick_resume() - fastest path, no reflection needed",
                "otherwise": "Use self_recovery_review(reflection='...') - requires reflection but allows recovery at lower thresholds",
                "related_tools": ["quick_resume", "self_recovery_review", "check_recovery_options"]
            },
            "removal_version": "v2.0"
        }
    }
    return success_response(response_data)


@mcp_tool("self_recovery_review", timeout=15.0, register=False)  # Use self_recovery(action="review") instead
async def handle_self_recovery_review(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Self-reflection recovery - lightweight alternative to dialectic.
    
    Agent reflects on what went wrong and proposes recovery conditions.
    System validates safety and resumes if safe, or provides guidance if not.
    
    This replaces the heavyweight thesis→antithesis→synthesis dialectic
    with a simpler: reflect → validate → resume flow.
    
    Required:
        reflection: str - What went wrong and what you learned (minimum 20 characters)
    
    Optional:
        proposed_conditions: list[str] - Conditions for resuming (e.g., "reduce complexity", "take breaks")
        root_cause: str - Agent's understanding of root cause
    """
    
    # 1. Require registered agent
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    agent_uuid = arguments.get("_agent_uuid") or agent_id
    
    # 2. Verify ownership (can only recover yourself)
    from .utils import verify_agent_ownership
    if not verify_agent_ownership(agent_uuid, arguments):
        return [error_response(
            "Authentication required. You can only recover your own agent.",
            error_code="AUTH_REQUIRED",
            error_category="auth_error",
            recovery={
                "action": "Ensure your session is bound to this agent",
                "related_tools": ["identity"],
            }
        )]
    
    # 3. Get reflection (required)
    reflection = arguments.get("reflection", "").strip()
    if not reflection or len(reflection) < 20:
        return [error_response(
            "Reflection required. Please describe what happened and what you learned. "
            "Minimum 20 characters - genuine reflection helps recovery.",
            error_code="REFLECTION_REQUIRED",
            recovery={
                "action": "Provide a meaningful reflection on what went wrong",
                "example": "self_recovery_review(reflection='I got stuck in a loop trying to optimize the same function repeatedly. I should have stepped back and considered alternative approaches.')"
            }
        )]
    
    # 4. Get current metrics
    meta = mcp_server.agent_metadata.get(agent_uuid)
    if not meta:
        return agent_not_found_error(agent_id)
    
    monitor = mcp_server.get_or_create_monitor(agent_uuid)
    metrics = monitor.get_metrics()
    
    coherence = float(monitor.state.coherence)
    risk_score = float(metrics.get("mean_risk") or 0.5)
    void_active = bool(monitor.state.void_active)
    void_value = float(monitor.state.V)
    status = meta.status
    
    # 5. Compute margin for context
    margin_info = GovernanceConfig.compute_proprioceptive_margin(
        risk_score=risk_score,
        coherence=coherence,
        void_active=void_active,
        void_value=void_value
    )
    
    # 6. Safety validation
    proposed_conditions = arguments.get("proposed_conditions", [])
    root_cause = arguments.get("root_cause", "")
    
    # Check for dangerous conditions (same as dialectic hard limits)
    dangerous_patterns = [
        "disable", "bypass", "ignore safety", "remove monitoring",
        "skip governance", "override limits"
    ]
    conditions_text = " ".join(proposed_conditions).lower()
    for pattern in dangerous_patterns:
        if pattern in conditions_text:
            return [error_response(
                f"Proposed conditions contain dangerous pattern: '{pattern}'. "
                "Recovery conditions cannot disable safety systems.",
                error_code="UNSAFE_CONDITIONS"
            )]
    
    # 7. Determine if safe to resume
    safety_checks = {
        "coherence_ok": coherence > 0.35,  # Slightly more lenient than direct_resume
        "risk_ok": risk_score < 0.65,      # Slightly more lenient since reflecting
        "no_void": not void_active,
        "has_reflection": len(reflection) >= 20
    }
    
    all_safe = all(safety_checks.values())
    
    # 8. Log reflection to knowledge graph (always, even if not resuming)
    try:
        from .knowledge_graph import store_discovery_internal
        await store_discovery_internal(
            agent_id=agent_uuid,
            summary=f"Self-recovery reflection: {reflection[:100]}{'...' if len(reflection) > 100 else ''}",
            discovery_type="recovery_reflection",
            details=f"Reflection: {reflection}\n\nRoot cause: {root_cause}\n\nProposed conditions: {proposed_conditions}\n\nMetrics at reflection: coherence={coherence:.3f}, risk={risk_score:.3f}, void={void_value:.3f}",
            tags=["recovery", "self-reflection", margin_info.get('margin', 'unknown')],
            severity="info" if all_safe else "warning"
        )
    except Exception as e:
        logger.warning(f"Failed to log recovery reflection: {e}")
    
    # 9. Resume if safe, or provide guidance
    if all_safe:
        # Resume agent
        from .self_recovery import clear_loop_detector_state
        meta.status = "active"
        meta.paused_at = None
        clear_loop_detector_state(meta)
        meta.add_lifecycle_event(
            "resumed",
            f"Self-recovery: {reflection[:50]}... Conditions: {proposed_conditions}"
        )
        
        # PostgreSQL update
        try:
            await agent_storage.update_agent(agent_uuid, status="active")
        except Exception as e:
            logger.debug(f"PostgreSQL status update failed: {e}")
        
        return success_response({
            "success": True,
            "action": "resumed",
            "message": "Recovery successful. Agent resumed.",
            "reflection_logged": True,
            "conditions": proposed_conditions,
            "metrics": {
                "coherence": coherence,
                "risk_score": risk_score,
                "margin": margin_info.get('margin', 'unknown')
            },
            "guidance": "You've reflected and recovered. Consider your proposed conditions as you continue."
        })
    
    else:
        # Not safe to resume - provide specific guidance
        failed = [k for k, v in safety_checks.items() if not v]
        
        guidance = []
        if not safety_checks["coherence_ok"]:
            guidance.append(f"Coherence is low ({coherence:.3f}). Consider what's causing fragmentation in your approach.")
        if not safety_checks["risk_ok"]:
            guidance.append(f"Risk is elevated ({risk_score:.3f}). What could you do differently to reduce risk?")
        if not safety_checks["no_void"]:
            guidance.append("Void is active - there's accumulated E-I imbalance. This needs time to settle.")
        
        return success_response({
            "success": False,
            "action": "not_resumed",
            "message": "Reflection logged, but not yet safe to resume.",
            "reflection_logged": True,
            "failed_checks": failed,
            "metrics": {
                "coherence": coherence,
                "risk_score": risk_score,
                "void_active": void_active,
                "margin": margin_info.get('margin', 'unknown')
            },
            "guidance": guidance,
            "next_steps": [
                "Review the guidance above",
                "Add to your reflection if you have new insights",
                "Try again with self_recovery_review() when ready",
                "Or wait for metrics to improve naturally"
            ]
        })


def _detect_stuck_agents(
    max_age_minutes: float = 30.0,  # Unused, kept for API compatibility
    critical_margin_timeout_minutes: float = 5.0,
    tight_margin_timeout_minutes: float = 15.0,
    include_pattern_detection: bool = True,
    min_updates: int = 3,
) -> list:
    """
    Detect stuck agents using proprioceptive margin + patterns.

    IMPORTANT: Inactivity alone does NOT mean stuck!
    An agent is stuck when it's in a problematic state AND not recovering.

    Detection rules:
    1. Critical margin + no updates > 5 min → stuck (can't proceed safely)
    2. Tight margin + no updates > 15 min → potentially stuck (struggling)
    3. Cognitive loop pattern → stuck (repeating unproductive behavior)
    4. Time box exceeded → stuck (taking too long on a task)

    NOT stuck:
    - Simply being idle/inactive (that's normal, not stuck)
    - Low update count (that's orphan/test agent, not stuck)

    Args:
        critical_margin_timeout_minutes: Timeout for critical margin state
        tight_margin_timeout_minutes: Timeout for tight margin state
        min_updates: Minimum updates before an agent can be considered stuck.
            Agents with fewer updates are likely orphans/one-shots, not stuck.

    Returns:
        List of stuck agents with detection reasons
    """
    from datetime import timezone
    stuck_agents = []
    current_time = datetime.now(timezone.utc)
    
    for agent_id, meta in mcp_server.agent_metadata.items():
        # Skip if already archived/deleted
        if meta.status in ["archived", "deleted"]:
            continue
        
        # Skip if not active
        if meta.status != "active":
            continue

        # Skip autonomous/embodied agents - they operate on different timescales
        # (e.g., Lumen, creatures) and shouldn't be flagged as "stuck" by timeout
        agent_tags = getattr(meta, "tags", []) or []
        if any(tag in agent_tags for tag in ["autonomous", "embodied", "creature", "anima"]):
            continue

        # Skip agents with too few updates (likely orphan/test agents)
        total_updates = getattr(meta, "total_updates", 0) or 0
        if total_updates < min_updates:
            continue
        
        # Calculate age since last update
        try:
            last_update_str = meta.last_update or meta.created_at
            if isinstance(last_update_str, str):
                last_update_dt = datetime.fromisoformat(
                    last_update_str.replace('Z', '+00:00') if 'Z' in last_update_str else last_update_str
                )
                if last_update_dt.tzinfo is None:
                    last_update_dt = last_update_dt.replace(tzinfo=timezone.utc)
            else:
                last_update_dt = last_update_str
            
            age_delta = current_time - last_update_dt
            age_minutes = age_delta.total_seconds() / 60
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"Could not parse last_update for {agent_id}: {e}")
            continue
        
        # Get current metrics to compute margin
        try:
            monitor = mcp_server.monitors.get(agent_id)
            if monitor is None:
                # Try to load state
                persisted_state = mcp_server.load_monitor_state(agent_id)
                if persisted_state:
                    monitor = UNITARESMonitor(agent_id, load_state=False)
                    monitor.state = persisted_state
                else:
                    # No state - can't compute margin, can't determine if stuck
                    # Inactivity alone does NOT mean stuck
                    continue
            
            # Pattern detection: check for cognitive loops and unproductive behavior
            if include_pattern_detection:
                try:
                    from src.pattern_tracker import get_pattern_tracker
                    tracker = get_pattern_tracker()
                    patterns = tracker.get_patterns(agent_id)
                    
                    # Add pattern-based stuck detection
                    for pattern in patterns.get("patterns", []):
                        if pattern["type"] == "loop":
                            stuck_agents.append({
                                "agent_id": agent_id,
                                "reason": "cognitive_loop",
                                "age_minutes": None,  # Pattern-based, not time-based
                                "pattern": pattern,
                                "details": pattern["message"]
                            })
                        elif pattern["type"] == "time_box":
                            stuck_agents.append({
                                "agent_id": agent_id,
                                "reason": "time_box_exceeded",
                                "age_minutes": pattern["total_minutes"],
                                "pattern": pattern,
                                "details": pattern["message"]
                            })
                        elif pattern["type"] == "untested_hypothesis":
                            # Don't mark as stuck, but include in details for context
                            # (This is more of a warning than stuck state)
                            pass
                except Exception as e:
                    logger.debug(f"Pattern detection failed for {agent_id}: {e}")
            
            if monitor:
                metrics = monitor.get_metrics()
                risk_score = float(metrics.get("mean_risk") or 0.5)
                coherence = float(monitor.state.coherence)
                void_active = bool(monitor.state.void_active)
                void_value = float(monitor.state.V)
                
                # Compute margin
                margin_info = GovernanceConfig.compute_proprioceptive_margin(
                    risk_score=risk_score,
                    coherence=coherence,
                    void_active=void_active,
                    void_value=void_value
                )
                margin = margin_info['margin']
                
                # Detection rule 1: Critical margin + timeout
                if margin == "critical" and age_minutes > critical_margin_timeout_minutes:
                    stuck_agents.append({
                        "agent_id": agent_id,
                        "reason": "critical_margin_timeout",
                        "age_minutes": round(age_minutes, 1),
                        "margin": margin,
                        "nearest_edge": margin_info.get('nearest_edge'),
                        "details": "Critical margin ({}) for {:.1f} minutes".format(
                            margin_info.get('nearest_edge', 'unknown'), age_minutes
                        )
                    })
                    continue
                
                # Detection rule 2: Tight margin + inactivity + unhealthy state
                # Tight margin alone is NOT stuck — coherence ~0.49 is the steady state
                # for ALL agents. Only flag if the agent also has genuinely degraded
                # metrics (high risk, low coherence, or high entropy).
                # Skip low-update agents (<50) - their EISV dynamics are noise, not signal
                _is_actually_degraded = (
                    risk_score > 0.45  # Approaching pause threshold
                    or coherence < 0.42  # Near critical coherence
                    or float(monitor.state.S) > 0.5  # High entropy
                )
                if margin == "tight" and age_minutes > max(tight_margin_timeout_minutes, 60.0) and total_updates >= 50 and _is_actually_degraded:
                    stuck_agents.append({
                        "agent_id": agent_id,
                        "reason": "tight_margin_timeout",
                        "age_minutes": round(age_minutes, 1),
                        "margin": margin,
                        "nearest_edge": margin_info.get('nearest_edge'),
                        "details": "Tight margin ({}) for {:.1f} minutes".format(
                            margin_info.get('nearest_edge', 'unknown'), age_minutes
                        )
                    })
                    continue
                
        except Exception as e:
            logger.debug(f"Error computing margin for {agent_id}: {e}")
            # Don't fall back to timeout-only detection - inactivity ≠ stuck
            # An agent can be legitimately idle without being stuck

    return stuck_agents


@mcp_tool("detect_stuck_agents", timeout=15.0, rate_limit_exempt=True)
async def handle_detect_stuck_agents(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Detect stuck agents using proprioceptive margin + patterns.

    IMPORTANT: Inactivity alone does NOT mean stuck!

    Detection rules:
    1. Critical margin + no updates > 5 min → stuck
    2. Tight margin + no updates > 15 min → potentially stuck
    3. Cognitive loop / time box exceeded → stuck

    NOT stuck: Simply being idle (that's normal behavior).

    Args:
        critical_margin_timeout_minutes: Timeout for critical margin (default: 5)
        tight_margin_timeout_minutes: Timeout for tight margin (default: 15)
        auto_recover: If True, automatically recover safe stuck agents (default: False)

    Returns:
        List of stuck agents with detection reasons and recovery status
    """
    try:
        # Reload metadata to ensure we have latest state (async for PostgreSQL)
        import asyncio
        await mcp_server.load_metadata_async()
        
        max_age_minutes = float(arguments.get("max_age_minutes", 30.0))
        critical_timeout = float(arguments.get("critical_margin_timeout_minutes", 5.0))
        tight_timeout = float(arguments.get("tight_margin_timeout_minutes", 15.0))
        min_updates = int(arguments.get("min_updates", 1))
        auto_recover = arguments.get("auto_recover", False)
        note_cooldown_minutes = float(arguments.get("note_cooldown_minutes", 120.0))
        
        # Detect stuck agents (run in executor since _detect_stuck_agents is sync)
        import asyncio
        loop = asyncio.get_running_loop()
        include_patterns = arguments.get("include_pattern_detection", True)
        stuck_agents = await loop.run_in_executor(
            None,
            _detect_stuck_agents,
            max_age_minutes,
            critical_timeout,
            tight_timeout,
            include_patterns,
            min_updates
        )
        
        # Auto-recover if requested
        recovered = []
        if auto_recover and stuck_agents:
            for stuck in stuck_agents:
                agent_id = stuck["agent_id"]
                try:
                    # Check if agent is responsive (can get metrics)
                    responsive = True
                    try:
                        monitor = mcp_server.get_or_create_monitor(agent_id)
                        metrics = monitor.get_metrics()
                        coherence = float(monitor.state.coherence)
                        risk_score = float(metrics.get("mean_risk") or 0.5)
                        void_active = bool(monitor.state.void_active)
                    except Exception as e:
                        # Agent is unresponsive - can't get metrics
                        logger.warning(f"[STUCK_AGENT_RECOVERY] Agent {agent_id[:8]}... is unresponsive: {e}")
                        responsive = False
                        # Use defaults for unresponsive agents
                        coherence = 0.5
                        risk_score = 0.5
                        void_active = False
                    
                    # If unresponsive AND stuck, trigger dialectic immediately (can't self-rescue)
                    if not responsive:
                        try:
                            from src.dialectic_protocol import DialecticSession, DialecticPhase
                            from src.mcp_handlers.dialectic_reviewer import select_reviewer
                            from .dialectic_session import save_session

                            # Check if agent already has active dialectic session
                            from src.dialectic_db import is_agent_in_active_session_async
                            has_session = await is_agent_in_active_session_async(agent_id)

                            if not has_session:
                                # Random reviewer selection, self-fallback if none available
                                reviewer_id = await select_reviewer(paused_agent_id=agent_id)
                                if reviewer_id is None:
                                    reviewer_id = agent_id  # Self-review fallback

                                if reviewer_id:
                                    # Create dialectic session
                                    session = DialecticSession(
                                        paused_agent_id=agent_id,
                                        reviewer_agent_id=reviewer_id,
                                        paused_agent_state={
                                            "risk_score": risk_score,
                                            "coherence": coherence,
                                            "void_active": void_active,
                                            "stuck_reason": stuck["reason"],
                                            "unresponsive": True,
                                            "age_minutes": stuck.get("age_minutes", 0)
                                        }
                                    )
                                    
                                    # Save session
                                    await save_session(session)
                                    
                                    # NOTE: Disabled KG writes for dialectic triggers (Feb 2026)
                                    # Dialectic sessions tracked separately
                                    
                                    recovered.append({
                                        "agent_id": agent_id,
                                        "action": "dialectic_triggered",
                                        "reason": stuck["reason"],
                                        "reviewer_id": reviewer_id,
                                        "session_id": session.session_id,
                                        "note": "Unresponsive - triggered dialectic immediately"
                                    })
                                    logger.info(
                                        f"[STUCK_AGENT_RECOVERY] Triggered dialectic for unresponsive stuck agent {agent_id[:8]}... "
                                        f"(reviewer: {reviewer_id[:8]}..., session: {session.session_id[:8]}...)"
                                    )
                                    continue  # Skip to next stuck agent
                                else:
                                    logger.warning(f"[STUCK_AGENT_RECOVERY] Could not find reviewer for unresponsive stuck agent {agent_id[:8]}...")
                            else:
                                logger.debug(f"[STUCK_AGENT_RECOVERY] Agent {agent_id[:8]}... already has active dialectic session")
                        except Exception as e:
                            logger.warning(f"[STUCK_AGENT_RECOVERY] Could not trigger dialectic for unresponsive {agent_id[:8]}...: {e}", exc_info=True)
                        continue  # Skip to next stuck agent
                    
                    # Agent is responsive - proceed with normal recovery logic
                    # Check if safe to auto-resume
                    
                    # Safe if: coherence > 0.40, risk < 0.60, void_active == False
                    if coherence > 0.40 and risk_score < 0.60 and not void_active:
                        meta = mcp_server.agent_metadata.get(agent_id)
                        if meta:
                            # Handle paused/waiting_input agents - resume them
                            if meta.status in ["paused", "waiting_input"]:
                                meta.status = "active"
                                recovered.append({
                                    "agent_id": agent_id,
                                    "action": "auto_resumed",
                                    "reason": stuck["reason"]
                                })
                            # Handle active stuck agents - trigger dialectic if stuck long enough
                            elif meta.status == "active":
                                # Check how long agent has been stuck
                                from datetime import datetime, timezone
                                try:
                                    last_update_str = meta.last_update or meta.created_at
                                    if isinstance(last_update_str, str):
                                        last_update_dt = datetime.fromisoformat(
                                            last_update_str.replace('Z', '+00:00') if 'Z' in last_update_str else last_update_str
                                        )
                                        if last_update_dt.tzinfo is None:
                                            last_update_dt = last_update_dt.replace(tzinfo=timezone.utc)
                                    else:
                                        last_update_dt = last_update_str
                                    
                                    age_minutes = (datetime.now(timezone.utc) - last_update_dt).total_seconds() / 60
                                    
                                    # Trigger dialectic for safe stuck agents if stuck > 1 hour
                                    if age_minutes > 60.0:
                                        # Safe but stuck long enough - trigger dialectic
                                        try:
                                            from src.dialectic_protocol import DialecticSession, DialecticPhase
                                            from src.mcp_handlers.dialectic_reviewer import select_reviewer
                                            from .dialectic_session import save_session

                                            # Check if agent already has active dialectic session
                                            from src.dialectic_db import is_agent_in_active_session_async
                                            has_session = await is_agent_in_active_session_async(agent_id)

                                            if not has_session:
                                                # Random reviewer selection, self-fallback if none available
                                                reviewer_id = await select_reviewer(paused_agent_id=agent_id)
                                                if reviewer_id is None:
                                                    reviewer_id = agent_id  # Self-review fallback

                                                if reviewer_id:
                                                    # Create dialectic session
                                                    session = DialecticSession(
                                                        paused_agent_id=agent_id,
                                                        reviewer_agent_id=reviewer_id,
                                                        paused_agent_state={
                                                            "risk_score": risk_score,
                                                            "coherence": coherence,
                                                            "void_active": void_active,
                                                            "stuck_reason": stuck["reason"],
                                                            "safe_but_stuck": True,
                                                            "age_minutes": age_minutes
                                                        }
                                                    )
                                                    
                                                    # Save session
                                                    await save_session(session)
                                                    
                                                    # NOTE: Disabled KG writes for dialectic triggers (Feb 2026)
                                                    # Dialectic sessions tracked separately
                                                    
                                                    recovered.append({
                                                        "agent_id": agent_id,
                                                        "action": "dialectic_triggered",
                                                        "reason": stuck["reason"],
                                                        "reviewer_id": reviewer_id,
                                                        "session_id": session.session_id,
                                                        "note": f"Safe but stuck {age_minutes:.1f} min - triggered dialectic"
                                                    })
                                                    logger.info(
                                                        f"[STUCK_AGENT_RECOVERY] Triggered dialectic for safe stuck agent {agent_id[:8]}... "
                                                        f"(stuck {age_minutes:.1f} min, reviewer: {reviewer_id[:8]}..., session: {session.session_id[:8]}...)"
                                                    )
                                                else:
                                                    logger.warning(f"[STUCK_AGENT_RECOVERY] Could not find reviewer for safe stuck agent {agent_id[:8]}...")
                                            else:
                                                logger.debug(f"[STUCK_AGENT_RECOVERY] Agent {agent_id[:8]}... already has active dialectic session")
                                        except Exception as e:
                                            logger.warning(f"[STUCK_AGENT_RECOVERY] Could not trigger dialectic for safe stuck {agent_id[:8]}...: {e}", exc_info=True)
                                    else:
                                        # Stuck but not long enough - leave note (deduped by KG check + cooldown)
                                        should_note = True

                                        # DEDUP FIX: Check KG for existing open stuck-agent note for this agent
                                        try:
                                            from src.db import get_db
                                            db = get_db()
                                            if hasattr(db, '_pool') and db._pool:
                                                async with db._pool.acquire() as conn:
                                                    existing_note = await conn.fetchval("""
                                                        SELECT 1 FROM knowledge.discoveries
                                                        WHERE agent_id = $1
                                                        AND tags @> ARRAY['stuck-agent']
                                                        AND status = 'open'
                                                        LIMIT 1
                                                    """, agent_id)
                                                    if existing_note:
                                                        should_note = False
                                                        logger.debug(f"[STUCK_AGENT] Skipped note for {agent_id[:8]}... - already has open stuck-agent note")
                                        except Exception as e:
                                            logger.debug(f"[STUCK_AGENT] Could not check KG for existing note: {e}")

                                        # Also check lifecycle events as fallback
                                        if should_note:
                                            try:
                                                if note_cooldown_minutes > 0 and meta:
                                                    for event in reversed(meta.lifecycle_events or []):
                                                        if event.get("event") != "stuck_note":
                                                            continue
                                                        ts = event.get("timestamp")
                                                        if not ts:
                                                            continue
                                                        try:
                                                            last_note = datetime.fromisoformat(ts)
                                                            if last_note.tzinfo is None:
                                                                last_note = last_note.replace(tzinfo=timezone.utc)
                                                            if (datetime.now(timezone.utc) - last_note).total_seconds() < note_cooldown_minutes * 60:
                                                                should_note = False
                                                                break
                                                        except Exception:
                                                            continue
                                            except Exception:
                                                pass

                                        if should_note:
                                            # NOTE: Disabled KG writes for stuck agents (Feb 2026)
                                            # Stuck agents are shown in dashboard via detect_stuck_agents API.
                                            # Writing to KG just creates noise without adding value.
                                            if meta:
                                                meta.add_lifecycle_event("stuck_detected", f"{stuck['reason']} ({age_minutes:.1f} min)")

                                            recovered.append({
                                                "agent_id": agent_id,
                                                "action": "stuck_tracked",
                                                "reason": stuck["reason"],
                                                "note": f"Stuck {age_minutes:.1f} min - tracked via detect_stuck_agents (no KG write)"
                                            })
                                        else:
                                            recovered.append({
                                                "agent_id": agent_id,
                                                "action": "note_skipped_recent",
                                                "reason": stuck["reason"],
                                                "note": f"Skipped note - recent note within {note_cooldown_minutes:.0f} min"
                                            })
                                except (ValueError, TypeError, AttributeError) as e:
                                    logger.debug(f"Could not calculate age for stuck agent: {e}")
                                    # Fallback: leave note (with KG dedup + cooldown check)
                                    should_note = True

                                    # DEDUP FIX: Check KG for existing open stuck-agent note
                                    try:
                                        from src.db import get_db
                                        db = get_db()
                                        if hasattr(db, '_pool') and db._pool:
                                            async with db._pool.acquire() as conn:
                                                existing_note = await conn.fetchval("""
                                                    SELECT 1 FROM knowledge.discoveries
                                                    WHERE agent_id = $1
                                                    AND tags @> ARRAY['stuck-agent']
                                                    AND status = 'open'
                                                    LIMIT 1
                                                """, agent_id)
                                                if existing_note:
                                                    should_note = False
                                    except Exception:
                                        pass

                                    # Also check lifecycle events as fallback
                                    if should_note:
                                        try:
                                            if note_cooldown_minutes > 0 and meta:
                                                for event in reversed(meta.lifecycle_events or []):
                                                    if event.get("event") != "stuck_note":
                                                        continue
                                                    ts = event.get("timestamp")
                                                    if not ts:
                                                        continue
                                                    try:
                                                        last_note = datetime.fromisoformat(ts)
                                                        if last_note.tzinfo is None:
                                                            last_note = last_note.replace(tzinfo=timezone.utc)
                                                        if (datetime.now(timezone.utc) - last_note).total_seconds() < note_cooldown_minutes * 60:
                                                            should_note = False
                                                            break
                                                    except Exception:
                                                        continue
                                        except Exception:
                                            pass

                                    if should_note:
                                        # NOTE: Disabled KG writes for stuck agents (Feb 2026)
                                        # Stuck agents tracked via detect_stuck_agents API instead
                                        if meta:
                                            meta.add_lifecycle_event("stuck_detected", stuck["reason"])

                                        recovered.append({
                                            "agent_id": agent_id,
                                            "action": "stuck_tracked",
                                            "reason": stuck["reason"],
                                            "note": "Tracked via detect_stuck_agents (no KG write)"
                                        })
                                    else:
                                        recovered.append({
                                            "agent_id": agent_id,
                                            "action": "note_skipped_recent",
                                            "reason": stuck["reason"],
                                            "note": f"Skipped note - recent note within {note_cooldown_minutes:.0f} min"
                                        })
                            # Log intervention (optional - deduped, don't fail)
                            try:
                                # Dedup: skip if open stuck-agent note already exists for this agent
                                from src.knowledge_graph import get_knowledge_graph
                                kg = await get_knowledge_graph()
                                existing = await kg.query(status="open", agent_id=agent_id, limit=50)
                                has_open_stuck = any(
                                    "stuck-agent" in (d.tags or []) for d in existing
                                )
                                if not has_open_stuck:
                                    from .knowledge_graph import handle_leave_note
                                    await handle_leave_note({
                                        "summary": f"Auto-recovered stuck agent {agent_id[:8]}... (Reason: {stuck['reason']}, Action: auto-resume)",
                                        "tags": ["auto-recovery", "stuck-agent"]
                                    })
                            except Exception as e:
                                logger.debug(f"Could not log auto-recovery: {e}")
                    else:
                        # Not safe - trigger dialectic review
                        try:
                            from src.dialectic_protocol import DialecticSession, DialecticPhase
                            from src.mcp_handlers.dialectic_reviewer import select_reviewer
                            from .dialectic_session import save_session
                            from datetime import datetime

                            # Check if agent already has active dialectic session
                            from src.dialectic_db import is_agent_in_active_session_async
                            has_session = await is_agent_in_active_session_async(agent_id)

                            if not has_session:
                                # Random reviewer selection, self-fallback if none available
                                reviewer_id = await select_reviewer(paused_agent_id=agent_id)
                                if reviewer_id is None:
                                    reviewer_id = agent_id  # Self-review fallback

                                if reviewer_id:
                                    # Create dialectic session
                                    session = DialecticSession(
                                        paused_agent_id=agent_id,
                                        reviewer_agent_id=reviewer_id,
                                        paused_agent_state={
                                            "risk_score": risk_score,
                                            "coherence": coherence,
                                            "void_active": void_active,
                                            "stuck_reason": stuck["reason"]
                                        }
                                    )
                                    
                                    # Save session
                                    await save_session(session)
                                    
                                    # NOTE: Disabled KG writes for dialectic triggers (Feb 2026)
                                    # Dialectic sessions are tracked separately; no need to duplicate in KG
                                    
                                    recovered.append({
                                        "agent_id": agent_id,
                                        "action": "dialectic_triggered",
                                        "reason": stuck["reason"],
                                        "reviewer_id": reviewer_id,
                                        "session_id": session.session_id
                                    })
                                    logger.info(
                                        f"[STUCK_AGENT_RECOVERY] Triggered dialectic for unsafe stuck agent {agent_id[:8]}... "
                                        f"(reviewer: {reviewer_id[:8]}..., session: {session.session_id[:8]}...)"
                                    )
                                else:
                                    logger.warning(f"[STUCK_AGENT_RECOVERY] Could not find reviewer for stuck agent {agent_id[:8]}...")
                            else:
                                logger.debug(f"[STUCK_AGENT_RECOVERY] Agent {agent_id[:8]}... already has active dialectic session")
                        except Exception as e:
                            logger.warning(f"[STUCK_AGENT_RECOVERY] Could not trigger dialectic for {agent_id[:8]}...: {e}", exc_info=True)
                except Exception as e:
                    logger.debug(f"Could not auto-recover {agent_id}: {e}")
        
        return success_response({
            "stuck_agents": stuck_agents,
            "recovered": recovered if auto_recover else [],
            "summary": {
                "total_stuck": len(stuck_agents),
                "min_updates": min_updates,
                "note_cooldown_minutes": note_cooldown_minutes,
                "total_recovered": len(recovered) if auto_recover else 0,
                "by_reason": {
                    reason: sum(1 for s in stuck_agents if s["reason"] == reason)
                    for reason in ["critical_margin_timeout", "tight_margin_timeout", "activity_timeout"]
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Error detecting stuck agents: {e}", exc_info=True)
        return [error_response(f"Error detecting stuck agents: {str(e)}")]


@mcp_tool("ping_agent", timeout=5.0, rate_limit_exempt=True, register=False)
async def handle_ping_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Ping an agent to check if it's responsive/alive.
    
    Checks if agent can respond by attempting to get its metrics.
    Useful for distinguishing between:
    - Agent is stuck but responsive (can call tools)
    - Agent is dead/unresponsive (can't call tools)
    
    Args:
        agent_id: Agent ID to ping (optional - defaults to calling agent)
    
    Returns:
        {
            "agent_id": "...",
            "responsive": true/false,
            "last_update": "...",
            "age_minutes": float,
            "status": "alive" | "stuck" | "unresponsive"
        }
    """
    try:
        # Reload metadata
        await mcp_server.load_metadata_async()
        
        # Get agent_id (default to calling agent)
        agent_id = arguments.get("agent_id")
        if not agent_id:
            # Use bound agent_id
            from .utils import get_bound_agent_id
            agent_id = get_bound_agent_id(arguments)
        
        if not agent_id:
            return [error_response("agent_id required or must be bound to session")]
        
        # Check if agent exists
        meta = mcp_server.agent_metadata.get(agent_id)
        if not meta:
            return [error_response(f"Agent {agent_id} not found")]
        
        # Try to get agent's metrics (this is the "ping")
        responsive = False
        try:
            monitor = mcp_server.get_or_create_monitor(agent_id)
            metrics = monitor.get_metrics()
            responsive = True  # If we can get metrics, agent is responsive
        except Exception as e:
            logger.debug(f"Could not ping agent {agent_id}: {e}")
            responsive = False
        
        # Calculate age
        from datetime import datetime, timezone
        try:
            last_update_str = meta.last_update or meta.created_at
            if isinstance(last_update_str, str):
                last_update_dt = datetime.fromisoformat(
                    last_update_str.replace('Z', '+00:00') if 'Z' in last_update_str else last_update_str
                )
                if last_update_dt.tzinfo is None:
                    last_update_dt = last_update_dt.replace(tzinfo=timezone.utc)
            else:
                last_update_dt = last_update_str
            
            age_delta = datetime.now(timezone.utc) - last_update_dt
            age_minutes = age_delta.total_seconds() / 60
        except (ValueError, TypeError, AttributeError):
            age_minutes = None
        
        # Determine status
        if responsive:
            if age_minutes and age_minutes > 30:
                status = "stuck"  # Responsive but inactive
            else:
                status = "alive"  # Responsive and active
        else:
            status = "unresponsive"  # Can't get metrics
        
        return success_response({
            "agent_id": agent_id,
            "responsive": responsive,
            "last_update": meta.last_update or meta.created_at,
            "age_minutes": round(age_minutes, 1) if age_minutes else None,
            "status": status,
            "lifecycle_status": meta.status
        })
        
    except Exception as e:
        logger.error(f"Error pinging agent: {e}", exc_info=True)
        return [error_response(f"Error pinging agent: {str(e)}")]
