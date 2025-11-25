"""
Core governance tool handlers.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
import json
import sys
from .utils import success_response, error_response, require_agent_id
# Import from parent module - use importlib to avoid circular imports
import importlib
import sys
from pathlib import Path

# Get mcp_server_std module
if 'src.mcp_server_std' in sys.modules:
    mcp_server = sys.modules['src.mcp_server_std']
else:
    # Import if not already loaded
    import src.mcp_server_std as mcp_server

from src.governance_monitor import UNITARESMonitor


async def handle_get_governance_metrics(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle get_governance_metrics tool"""
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]  # Wrap in list for Sequence[TextContent]

    # Validate agent exists
    monitor, error_msg = mcp_server.get_agent_or_error(agent_id)
    if error_msg:
        return [error_response(error_msg)]

    metrics = monitor.get_metrics()

    # Add EISV labels for API documentation
    metrics['eisv_labels'] = UNITARESMonitor.get_eisv_labels()

    return success_response(metrics)


async def handle_simulate_update(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle simulate_update tool"""
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]  # Wrap in list for Sequence[TextContent]
    
    # Get or create monitor
    monitor = mcp_server.get_or_create_monitor(agent_id)
    
    # Prepare agent state
    import numpy as np
    agent_state = {
        "parameters": np.array(arguments.get("parameters", [])),
        "ethical_drift": np.array(arguments.get("ethical_drift", [0.0, 0.0, 0.0])),
        "response_text": arguments.get("response_text", ""),
        "complexity": arguments.get("complexity", 0.5)
    }
    
    # Extract confidence parameter (defaults to 1.0 for backward compatibility)
    confidence = float(arguments.get("confidence", 1.0))
    confidence = max(0.0, min(1.0, confidence))  # Clamp to [0, 1]
    
    # Run simulation (doesn't persist state) with confidence
    result = monitor.simulate_update(agent_state, confidence=confidence)
    
    return success_response({
        "simulation": True,
        **result
    })


async def handle_process_agent_update(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle process_agent_update tool - complex handler with authentication and state management"""
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]  # Wrap in list for Sequence[TextContent]

    # Authenticate agent ownership (prevents impersonation)
    # For new agents, allow creation without key (will generate one)
    # For existing agents, require API key
    is_new_agent = agent_id not in mcp_server.agent_metadata
    key_was_generated = False
    
    # Get or ensure API key exists
    api_key = arguments.get("api_key")
    if not is_new_agent:
        # Existing agent - require authentication
        auth_valid, auth_error = mcp_server.require_agent_auth(agent_id, arguments, enforce=False)
        if not auth_valid:
            return [auth_error] if auth_error else [error_response("Authentication failed")]
        # Lazy migration: if agent has no key, generate one on first update
        meta = mcp_server.agent_metadata[agent_id]
        if meta.api_key is None:
            meta.api_key = mcp_server.generate_api_key()
            key_was_generated = True
            print(f"[UNITARES MCP] Generated API key for existing agent '{agent_id}' (migration)", file=sys.stderr)
        # Use metadata key if not provided in arguments
        if not api_key:
            api_key = meta.api_key
    else:
        # New agent - will generate key in get_or_create_metadata
        pass
    
    # Check agent status - auto-resume archived agents on engagement
    if agent_id in mcp_server.agent_metadata:
        meta = mcp_server.agent_metadata[agent_id]
        if meta.status == "archived":
            # Auto-resume: Any engagement resumes archived agents
            meta.status = "active"
            meta.archived_at = None
            meta.add_lifecycle_event("resumed", "Auto-resumed on engagement")
            await mcp_server.save_metadata_async()
        elif meta.status == "paused":
            # Paused agents still need explicit resume
            return [error_response(
                f"Agent '{agent_id}' is paused. Resume it first before processing updates."
            )]
        elif meta.status == "deleted":
            return [error_response(f"Agent '{agent_id}' is deleted and cannot be used.")]

    # Clean up zombies before processing
    try:
        cleaned = mcp_server.process_mgr.cleanup_zombies(max_keep_processes=mcp_server.MAX_KEEP_PROCESSES)
        if cleaned:
            print(f"[UNITARES MCP] Cleaned up {len(cleaned)} zombie processes", file=sys.stderr)
    except Exception as e:
        print(f"[UNITARES MCP] Warning: Could not clean zombies: {e}", file=sys.stderr)

    # Acquire lock for agent state update (prevents race conditions)
    # The lock manager now has automatic retry with stale lock cleanup built-in
    try:
        with mcp_server.lock_manager.acquire_agent_lock(agent_id, timeout=5.0, max_retries=3):
            # Prepare agent state
            import numpy as np
            agent_state = {
                "parameters": np.array(arguments.get("parameters", [])),
                "ethical_drift": np.array(arguments.get("ethical_drift", [0.0, 0.0, 0.0])),
                "response_text": arguments.get("response_text", ""),
                "complexity": arguments.get("complexity", 0.5)
            }

            # Ensure metadata exists (for new agents, this creates it with API key)
            if is_new_agent:
                meta = mcp_server.get_or_create_metadata(agent_id)
                api_key = meta.api_key  # Get generated key
            
            # Extract confidence parameter (defaults to 1.0 for backward compatibility)
            confidence = float(arguments.get("confidence", 1.0))
            confidence = max(0.0, min(1.0, confidence))  # Clamp to [0, 1]
            
            # Use authenticated update function (async version)
            result = await mcp_server.process_update_authenticated_async(
                agent_id=agent_id,
                api_key=api_key,
                agent_state=agent_state,
                auto_save=True,
                confidence=confidence
            )
            
            # Update heartbeat
            mcp_server.process_mgr.write_heartbeat()

            # Calculate health status using risk-based thresholds
            risk_score = result.get('metrics', {}).get('risk_score', None)
            coherence = result.get('metrics', {}).get('coherence', None)
            void_active = result.get('metrics', {}).get('void_active', False)
            
            health_status, health_message = mcp_server.health_checker.get_health_status(
                risk_score=risk_score,
                coherence=coherence,
                void_active=void_active
            )
            
            # Add health status to response
            if 'metrics' not in result:
                result['metrics'] = {}
            result['metrics']['health_status'] = health_status.value
            result['metrics']['health_message'] = health_message

            # Add EISV labels for API documentation
            result['eisv_labels'] = UNITARESMonitor.get_eisv_labels()

            # Collect any warnings
            warnings = []
            
            # Check for default agent_id warning
            try:
                default_warning = mcp_server.check_agent_id_default(agent_id)
                if default_warning:
                    warnings.append(default_warning)
            except (NameError, AttributeError):
                # Function not available (shouldn't happen, but be defensive)
                pass
            except Exception as e:
                # Log but don't fail the update
                print(f"[UNITARES MCP] Warning: Could not check agent_id default: {e}", file=sys.stderr)

            # Build response
            response_data = result.copy()
            if warnings:
                response_data["warning"] = "; ".join(warnings)
            
            # Include API key for new agents or if key was just generated (one-time display)
            if is_new_agent or key_was_generated:
                meta = mcp_server.agent_metadata[agent_id]
                response_data["api_key"] = meta.api_key
                if is_new_agent:
                    response_data["api_key_warning"] = "⚠️  Save this API key - you'll need it for future updates to authenticate as this agent."
                else:
                    response_data["api_key_warning"] = "⚠️  API key generated (migration). Save this key - you'll need it for future updates to authenticate as this agent."

            return success_response(response_data)
    except TimeoutError as e:
        # Lock acquisition failed even after automatic retries and cleanup
        # Try one more aggressive cleanup attempt
        try:
            from src.lock_cleanup import cleanup_stale_state_locks
            project_root = Path(__file__).parent.parent.parent
            cleanup_result = cleanup_stale_state_locks(project_root=project_root, max_age_seconds=60.0, dry_run=False)
            if cleanup_result['cleaned'] > 0:
                print(f"[UNITARES MCP] Auto-recovery: Cleaned {cleanup_result['cleaned']} stale lock(s) after timeout", file=sys.stderr)
        except Exception as cleanup_error:
            print(f"[UNITARES MCP] Warning: Could not perform emergency lock cleanup: {cleanup_error}", file=sys.stderr)
        
        return [error_response(
            f"Failed to acquire lock for agent '{agent_id}' after automatic retries and cleanup. "
            f"This usually means another active process is updating this agent. "
            f"The system has automatically cleaned stale locks. If this persists, try: "
            f"1) Wait a few seconds and retry, 2) Check for other Cursor/Claude sessions, "
            f"3) Use cleanup_stale_locks tool, or 4) Restart Cursor if stuck."
        )]

