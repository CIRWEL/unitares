"""
MCP Handlers for Circuit Breaker Dialectic Protocol

Implements MCP tools for peer-review dialectic resolution of circuit breaker states.
"""

from typing import Dict, Any, Sequence, Optional, List
from mcp.types import TextContent
import json
from datetime import datetime, timedelta
import random

# Import type definitions
from .types import (
    ToolArgumentsDict,
    DialecticSessionDict,
    ResolutionDict
)

from src.dialectic_protocol import (
    DialecticSession,
    DialecticMessage,
    DialecticPhase,
    Resolution,
    calculate_authority_score
)
from .utils import success_response, error_response, require_registered_agent
from .decorators import mcp_tool
from src.logging_utils import get_logger
import sys
import os

logger = get_logger(__name__)


# Import from mcp_server_std module (using shared utility)
from .shared import get_mcp_server
mcp_server = get_mcp_server()


# Import session persistence from new module
from .dialectic_session import (
    save_session,
    load_session,
    load_all_sessions,
    list_all_sessions,
    ACTIVE_SESSIONS,
    SESSION_STORAGE_DIR,
    _SESSION_METADATA_CACHE,
    _CACHE_TTL
)

# Session metadata cache for fast lookups (re-exported for backward compatibility)
# Format: {agent_id: {'in_session': bool, 'timestamp': float, 'session_ids': [str]}}

# Check if aiofiles is available for async I/O
try:
    import aiofiles
    AIOFILES_AVAILABLE = True
except ImportError:
    AIOFILES_AVAILABLE = False


# NOTE: save_session, load_session, and load_all_sessions are now imported from dialectic_session.py
# NOTE: Calibration functions are now imported from dialectic_calibration.py
# NOTE: Resolution execution is now imported from dialectic_resolution.py
from .dialectic_calibration import (
    update_calibration_from_dialectic,
    update_calibration_from_dialectic_disagreement,
    backfill_calibration_from_historical_sessions
)
from .dialectic_resolution import execute_resolution
from .dialectic_reviewer import select_reviewer, is_agent_in_active_session

# Import SQLite async functions for cross-process session storage
from src.dialectic_db import (
    create_session_async as sqlite_create_session,
    update_session_phase_async as sqlite_update_phase,
    update_session_reviewer_async as sqlite_update_reviewer,
    add_message_async as sqlite_add_message,
    resolve_session_async as sqlite_resolve_session,
    get_session_async as sqlite_get_session,
    get_session_by_agent_async as sqlite_get_session_by_agent,
)

# Import database abstraction for dual-write (Phase 4 migration)
from src.db import get_db


# Check for aiofiles availability
try:
    import aiofiles
    AIOFILES_AVAILABLE = True
except ImportError:
    AIOFILES_AVAILABLE = False



# ==============================================================================
# NOTE: Dialectic handlers (Dec 2025)
# ==============================================================================
# Restored: request_dialectic_review (lite entry point for recovery)
# Still removed: request_exploration_session, submit_thesis, submit_antithesis,
#                submit_synthesis, nudge_dialectic_session, handle_self_recovery
# Only get_dialectic_session remains for viewing existing sessions.
# ==============================================================================


async def check_reviewer_stuck(session: DialecticSession) -> bool:
    """
    Check if reviewer is stuck (paused or hasn't responded to session assignment).
    
    Returns:
        True if reviewer is stuck, False otherwise
    """
    reviewer_id = session.reviewer_agent_id
    
    # Reload metadata to ensure we have latest state (non-blocking)
    import asyncio
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, mcp_server.load_metadata)
    
    reviewer_meta = mcp_server.agent_metadata.get(reviewer_id)
    if not reviewer_meta:
        return True  # Reviewer doesn't exist = stuck
    
    # Check if reviewer is paused
    if reviewer_meta.status == "paused":
        return True
    
    # Check time since reviewer was assigned to this session (not governance last_update)
    # FIXED: Previously checked reviewer_meta.last_update (governance time), which caused
    # sessions to abort prematurely if reviewer hadn't updated governance state recently.
    # Now correctly checks time since session creation (when reviewer was assigned).
    try:
        session_created = session.created_at
        if isinstance(session_created, str):
            session_created = datetime.fromisoformat(session_created)
        stuck_threshold = timedelta(minutes=30)
        time_since_assignment = datetime.now() - session_created
        return time_since_assignment > stuck_threshold
    except (ValueError, TypeError, AttributeError):
        # Can't parse timestamp or session has no created_at - assume stuck
        return True


@mcp_tool("request_dialectic_review", timeout=10.0, register=False)
async def handle_request_dialectic_review(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Create a dialectic recovery session.

    This is a lightweight entry point restored for recovery workflows.
    It sets up the session and persists it, but does not auto-progress the protocol.
    """
    # Require a registered agent and use authoritative UUID for internal IDs
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    agent_uuid = arguments.get("_agent_uuid") or agent_id

    # SECURITY: Verify ownership via session binding (UUID-based auth, Dec 2025)
    from .utils import verify_agent_ownership
    if not verify_agent_ownership(agent_uuid, arguments):
        return [error_response(
            "Authentication required. You can only request recovery for your own agent.",
            error_code="AUTH_REQUIRED",
            error_category="auth_error",
            recovery={
                "action": "Ensure your session is bound to this agent",
                "related_tools": ["identity"],
                "workflow": "Identity auto-binds on first tool call. Use identity() to check binding."
            },
            arguments=arguments
        )]

    meta = mcp_server.agent_metadata.get(agent_uuid)
    if not meta:
        return [error_response(
            f"Agent '{agent_uuid}' not found.",
            error_code="AGENT_NOT_FOUND",
            error_category="validation_error",
            recovery={
                "action": "Call identity() or process_agent_update() to register.",
                "related_tools": ["identity", "process_agent_update"]
            },
            arguments=arguments
        )]

    # Skip if agent is waiting for input (not stuck)
    if meta.status == "waiting_input":
        return success_response({
            "success": True,
            "skipped": True,
            "reason": "Agent is waiting_input; not stuck",
            "agent_id": agent_uuid,
            "status": meta.status,
            "recommendation": "No dialectic needed. Use process_agent_update() when new work starts."
        })

    # Prevent duplicate sessions
    if await is_agent_in_active_session(agent_uuid):
        return [error_response(
            "Agent already has an active dialectic session.",
            error_code="SESSION_EXISTS",
            error_category="validation_error",
            recovery={
                "action": "Use get_dialectic_session() to view the active session",
                "related_tools": ["get_dialectic_session"]
            },
            arguments=arguments
        )]

    reason = arguments.get("reason", "Dialectic recovery requested")
    session_type = arguments.get("session_type", "recovery")
    discovery_id = arguments.get("discovery_id")
    dispute_type = arguments.get("dispute_type")
    topic = arguments.get("topic")
    reviewer_mode = arguments.get("reviewer_mode", "auto")
    reviewer_agent_id = arguments.get("reviewer_agent_id")
    max_synthesis_rounds = arguments.get("max_synthesis_rounds", 5)
    auto_progress = bool(arguments.get("auto_progress", False))

    # Capture paused agent state snapshot if available
    paused_agent_state = {}
    try:
        monitor = getattr(mcp_server, "monitors", {}).get(agent_uuid)
        if monitor and hasattr(monitor, "state") and hasattr(monitor.state, "to_dict"):
            paused_agent_state = monitor.state.to_dict()
    except Exception:
        paused_agent_state = {}

    # Reviewer selection
    if reviewer_mode == "self":
        reviewer_agent_id = agent_uuid
    elif reviewer_agent_id:
        if reviewer_agent_id not in mcp_server.agent_metadata:
            return [error_response(
                f"Reviewer agent '{reviewer_agent_id}' not found.",
                error_code="REVIEWER_NOT_FOUND",
                error_category="validation_error",
                recovery={
                    "action": "Pick a valid reviewer or use reviewer_mode='auto'",
                    "related_tools": ["list_agents"]
                },
                arguments=arguments
            )]
    else:
        reviewer_agent_id = await select_reviewer(
            paused_agent_id=agent_uuid,
            metadata=mcp_server.agent_metadata,
            paused_agent_state=paused_agent_state,
            paused_agent_tags=getattr(meta, "tags", []),
            exclude_agent_ids=None
        )
        if reviewer_agent_id is None:
            if reviewer_mode in ("auto", "self"):
                reviewer_agent_id = agent_uuid
            else:
                return [error_response(
                    "No eligible reviewer available.",
                    error_code="NO_REVIEWER",
                    error_category="validation_error",
                    recovery={
                        "action": "Try reviewer_mode='auto' (self fallback) or wait for a healthy reviewer",
                        "related_tools": ["list_agents"]
                    },
                    arguments=arguments
                )]

    # Create session
    session = DialecticSession(
        paused_agent_id=agent_uuid,
        reviewer_agent_id=reviewer_agent_id,
        paused_agent_state=paused_agent_state,
        discovery_id=discovery_id,
        dispute_type=dispute_type,
        session_type=session_type,
        topic=topic,
        max_synthesis_rounds=int(max_synthesis_rounds or 5),
    )

    # Persist to SQLite/Postgres (source of truth) and JSON snapshot
    try:
        await sqlite_create_session(
            session_id=session.session_id,
            paused_agent_id=session.paused_agent_id,
            reviewer_agent_id=session.reviewer_agent_id,
            reason=reason,
            discovery_id=discovery_id,
            dispute_type=dispute_type,
            session_type=session_type,
            topic=topic,
            max_synthesis_rounds=session.max_synthesis_rounds,
            synthesis_round=session.synthesis_round,
            paused_agent_state=paused_agent_state,
        )
    except Exception as e:
        logger.warning(f"SQLite/PG dialectic session create failed: {e}")

    try:
        await save_session(session)
    except Exception as e:
        logger.warning(f"Failed to save dialectic session snapshot: {e}")

    # Cache in-memory for quick access
    ACTIVE_SESSIONS[session.session_id] = session

    if auto_progress:
        logger.info("auto_progress requested for dialectic review, but auto progression is not enabled.")

    return success_response({
        "success": True,
        "message": "Dialectic session created",
        "session_id": session.session_id,
        "paused_agent_id": session.paused_agent_id,
        "reviewer_agent_id": session.reviewer_agent_id,
        "phase": session.phase.value,
        "session_type": session.session_type,
        "auto_progress": False,
        "note": "Dialectic auto-progress is disabled; submit_thesis/antithesis/synthesis remain archived."
    })

@mcp_tool("get_dialectic_session", timeout=10.0, rate_limit_exempt=True, register=False)
async def handle_get_dialectic_session(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    View historical dialectic sessions (archive).

    Dialectic protocol is now archived - this tool views past sessions only.
    For current state, use get_governance_metrics.
    For recovery, use direct_resume_if_safe.

    Args:
        session_id: Dialectic session ID (optional if agent_id provided)
        agent_id: Agent ID to find sessions for (optional if session_id provided)

    Returns:
        Historical session state including transcript
    """
    try:
        session_id = arguments.get('session_id')
        agent_id = arguments.get('agent_id')
        check_timeout = arguments.get('check_timeout', True)

        # If session_id provided, use it directly
        if session_id:
            # Try in-memory first
            session = ACTIVE_SESSIONS.get(session_id)
            if not session:
                # Try loading from disk
                session = await load_session(session_id)
                if session:
                    # Restore to in-memory
                    ACTIVE_SESSIONS[session_id] = session
            
            if not session:
                return [error_response(f"Session '{session_id}' not found")]
            
            # Check for timeouts if requested
            if check_timeout:
                timeout_reason = session.check_timeout()
                if timeout_reason:
                    session.phase = DialecticPhase.FAILED
                    session.transcript.append(DialecticMessage(
                        phase="synthesis",
                        agent_id="system",
                        timestamp=datetime.now().isoformat(),
                        reasoning=f"Session auto-failed: {timeout_reason}"
                    ))
                    await save_session(session)
                    # QUICK WIN B: Improved error message with actionable guidance
                    return success_response({
                        "success": False,
                        "error": timeout_reason,
                        "session": session.to_dict(),
                        "recovery": {
                            "action": "Session timed out - automatic resolution",
                            "what_happened": timeout_reason,
                            "what_you_can_do": [
                                "1. Check your state with get_governance_metrics",
                                "2. Use direct_resume_if_safe if you believe you can proceed safely",
                                "3. Leave a note about what happened with leave_note"
                            ],
                            "related_tools": ["get_governance_metrics", "direct_resume_if_safe", "leave_note"],
                            "note": "Historical session - dialectic is now archived"
                        }
                    })
                
                # Check if reviewer is stuck
                if await check_reviewer_stuck(session):
                    session.phase = DialecticPhase.FAILED
                    # type: ignore
                    session.transcript.append(DialecticMessage(
                        phase=session.phase.value,
                        agent_id="system",
                        timestamp=datetime.now().isoformat(),
                        reasoning="Reviewer stuck - session aborted"
                    ))
                    await save_session(session)
                    # QUICK WIN B: Improved error message with actionable guidance
                    return success_response({
                        "success": False,
                        "error": "Reviewer stuck - session aborted",
                        "session": session.to_dict(),
                        "recovery": {
                            "action": "Session aborted because reviewer didn't respond within timeout",
                            "what_happened": f"Reviewer '{session.reviewer_agent_id}' was assigned but didn't submit antithesis within 30 minutes",
                            "what_you_can_do": [
                                "1. Check your state with get_governance_metrics",
                                "2. Use direct_resume_if_safe if you believe you can proceed safely",
                                "3. Leave a note about what happened with leave_note"
                            ],
                            "related_tools": ["get_governance_metrics", "direct_resume_if_safe", "leave_note"],
                            "note": "Historical session - dialectic is now archived"
                        }
                    })
            
            result = session.to_dict()
            result["success"] = True
            return success_response(result)
        
        # If agent_id provided, find all sessions for this agent
        if agent_id:
            # Reload metadata to ensure we have latest state (non-blocking)
            import asyncio
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, mcp_server.load_metadata)
            
            # Check if agent exists
            if agent_id not in mcp_server.agent_metadata:
                return [error_response(
                    f"Agent '{agent_id}' not found",
                    recovery={
                        "action": "Agent must be registered first",
                        "related_tools": ["get_agent_api_key", "list_agents"]
                    }
                )]
            
            # Find sessions where agent is paused or reviewer
            matching_sessions = []
            
            # Check in-memory sessions
            for sid, session in ACTIVE_SESSIONS.items():
                if session.paused_agent_id == agent_id or session.reviewer_agent_id == agent_id:
                    matching_sessions.append(session.to_dict())
            
            # Also check disk for persisted sessions (run in executor to avoid blocking)
            loop = asyncio.get_running_loop()
            
            def _list_disk_sessions_sync():
                """Synchronous directory check and file listing - runs in executor"""
                SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                if not SESSION_STORAGE_DIR.exists():
                    return []
                return list(SESSION_STORAGE_DIR.glob("*.json"))
            
            disk_session_files = await loop.run_in_executor(None, _list_disk_sessions_sync)
            
            for session_file in disk_session_files:
                    try:
                        loaded_session = await load_session(session_file.stem)
                        if loaded_session:
                            # Check if matches agent_id
                            if loaded_session.paused_agent_id == agent_id or loaded_session.reviewer_agent_id == agent_id:
                                # Avoid duplicates
                                if not any(s.get('session_id') == loaded_session.session_id for s in matching_sessions):
                                    matching_sessions.append(loaded_session.to_dict())
                                    # Restore to in-memory
                                    ACTIVE_SESSIONS[loaded_session.session_id] = loaded_session
                    except (ValueError, AttributeError, TypeError) as e:
                        logger.debug(f"Could not parse timestamp in session file: {e}")
                        continue
                    except Exception as e:
                        logger.debug(f"Unexpected error parsing session timestamp: {e}")
                        continue
            
            if not matching_sessions:
                return [error_response(
                    f"No dialectic sessions found for agent '{agent_id}'",
                    recovery={
                        "action": "No historical sessions. This tool views past dialectic sessions (now archived).",
                        "related_tools": ["get_governance_metrics", "search_knowledge_graph"],
                        "note": "For current state, use get_governance_metrics. For recovery, use direct_resume_if_safe."
                    }
                )]
            
            # If single session, return it directly
            if len(matching_sessions) == 1:
                result = matching_sessions[0]
                result["success"] = True
                return success_response(result)
            
            # Multiple sessions - return list
            return success_response({
                "success": True,
                "agent_id": agent_id,
                "session_count": len(matching_sessions),
                "sessions": matching_sessions
            })
        
        # Neither provided
        return [error_response(
            "Either session_id or agent_id is required",
            recovery={
                "action": "Provide session_id or agent_id to view historical dialectic sessions",
                "related_tools": ["list_agents", "get_governance_metrics"],
                "note": "This tool views archived dialectic sessions. For current state, use get_governance_metrics."
            }
        )]

    except Exception as e:
        import traceback
        # SECURITY: Log full traceback internally but sanitize for client
        logger.error(f"Error getting dialectic session: {e}", exc_info=True)
        return [error_response(
            f"Error getting session: {str(e)}",
            recovery={
                "action": "Check session_id or agent_id and try again",
                "related_tools": ["list_agents", "get_governance_metrics"]
            }
        )]


@mcp_tool("list_dialectic_sessions", timeout=15.0, rate_limit_exempt=True, register=False)
async def handle_list_dialectic_sessions(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    List all dialectic sessions with optional filtering.

    Allows agents to browse historical dialectic sessions to learn from past
    negotiations and recoveries. Returns summaries by default for efficiency.

    Args:
        agent_id: Filter by agent (either requestor or reviewer) - optional
        status: Filter by phase (e.g., 'resolved', 'failed', 'thesis') - optional
        limit: Max sessions to return (default 50, max 200)
        include_transcript: Include full transcript in results (default False)

    Returns:
        List of session summaries with optional full transcript
    """
    try:
        agent_id = arguments.get('agent_id')
        status = arguments.get('status')
        limit = min(int(arguments.get('limit', 50) or 50), 200)
        include_transcript = bool(arguments.get('include_transcript', False))

        sessions = await list_all_sessions(
            agent_id=agent_id,
            status=status,
            limit=limit,
            include_transcript=include_transcript
        )

        if not sessions:
            return success_response({
                "success": True,
                "message": "No dialectic sessions found matching criteria",
                "sessions": [],
                "filters_applied": {
                    "agent_id": agent_id,
                    "status": status,
                    "limit": limit
                },
                "tip": "Use list_dialectic_sessions() with no filters to see all sessions"
            })

        return success_response({
            "success": True,
            "session_count": len(sessions),
            "sessions": sessions,
            "filters_applied": {
                "agent_id": agent_id,
                "status": status,
                "limit": limit,
                "include_transcript": include_transcript
            },
            "tip": "Use get_dialectic_session(session_id='...') for full details"
        })

    except Exception as e:
        logger.error(f"Error listing dialectic sessions: {e}", exc_info=True)
        return [error_response(
            f"Error listing sessions: {str(e)}",
            recovery={
                "action": "Try with different filters or check server logs",
                "related_tools": ["get_dialectic_session", "health_check"]
            }
        )]


@mcp_tool("llm_assisted_dialectic", timeout=45.0, register=False)
async def handle_llm_assisted_dialectic(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Run LLM-assisted dialectic recovery when no peer reviewer is available.

    This tool enables single-agent dialectic recovery by using a local LLM
    as a "synthetic reviewer". It runs the full thesis -> antithesis -> synthesis
    protocol, generating counterarguments and synthesizing a resolution.

    Use this when:
    - Agent is stuck/paused and needs recovery
    - No peer reviewer is available or responding
    - You want structured reflection on what went wrong

    Args:
        root_cause: Your understanding of what caused the issue
        proposed_conditions: List of conditions you propose for recovery
        reasoning: Your explanation/reasoning (optional)

    Returns:
        Complete dialectic result with antithesis, synthesis, and recommendation
    """
    # Import LLM delegation functions
    from .llm_delegation import run_full_dialectic, is_llm_available

    # Require registered agent
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    agent_uuid = arguments.get("_agent_uuid") or agent_id

    # Check LLM availability
    if not await is_llm_available():
        return [error_response(
            "Local LLM (Ollama) not available for dialectic review",
            error_code="LLM_UNAVAILABLE",
            error_category="system_error",
            recovery={
                "action": "Start Ollama: `ollama serve` or use request_dialectic_review for peer review",
                "related_tools": ["request_dialectic_review", "health_check"],
                "workflow": [
                    "1. Check Ollama: curl http://localhost:11434/api/tags",
                    "2. Start if needed: ollama serve",
                    "3. Retry this tool"
                ]
            }
        )]

    # Get thesis components from arguments
    root_cause = arguments.get("root_cause")
    proposed_conditions = arguments.get("proposed_conditions", [])
    reasoning = arguments.get("reasoning", "")

    if not root_cause:
        return [error_response(
            "root_cause is required - explain what you think caused the issue",
            error_code="MISSING_ARGUMENT",
            error_category="validation_error",
            recovery={
                "action": "Provide root_cause: your understanding of what went wrong",
                "example": {
                    "root_cause": "High complexity task without sufficient planning",
                    "proposed_conditions": ["Reduce task complexity", "Add progress checkpoints"],
                    "reasoning": "The task scope exceeded my capacity to maintain coherence"
                }
            }
        )]

    # Ensure proposed_conditions is a list
    if isinstance(proposed_conditions, str):
        proposed_conditions = [proposed_conditions]

    # Build thesis
    thesis = {
        "root_cause": root_cause,
        "proposed_conditions": proposed_conditions,
        "reasoning": reasoning,
        "agent_id": agent_uuid,
        "timestamp": datetime.now().isoformat()
    }

    # Get agent state for context
    agent_state = None
    try:
        monitor = getattr(mcp_server, "monitors", {}).get(agent_uuid)
        if monitor:
            agent_state = {
                "risk_score": getattr(monitor, "risk_score", None),
                "coherence": getattr(monitor.state, "coherence", None) if hasattr(monitor, "state") else None,
                "E": getattr(monitor.state, "E", None) if hasattr(monitor, "state") else None,
                "I": getattr(monitor.state, "I", None) if hasattr(monitor, "state") else None,
                "S": getattr(monitor.state, "S", None) if hasattr(monitor, "state") else None,
                "V": getattr(monitor.state, "V", None) if hasattr(monitor, "state") else None,
            }
    except Exception as e:
        logger.debug(f"Could not get agent state: {e}")

    # Run full dialectic
    logger.info(f"Running LLM-assisted dialectic for agent {agent_uuid[:8]}...")
    result = await run_full_dialectic(
        thesis=thesis,
        agent_state=agent_state,
        max_synthesis_rounds=2
    )

    if not result:
        return [error_response(
            "Dialectic process failed - LLM did not respond",
            error_code="DIALECTIC_FAILED",
            error_category="system_error",
            recovery={
                "action": "Check Ollama status and retry",
                "related_tools": ["health_check", "call_model"]
            }
        )]

    if not result.get("success"):
        return [error_response(
            f"Dialectic incomplete: {result.get('error', 'Unknown error')}",
            error_code="DIALECTIC_INCOMPLETE",
            error_category="system_error",
            recovery={
                "action": "Review partial result and retry with clearer thesis",
                "partial_result": result
            }
        )]

    # Format successful response
    recommendation = result.get("recommendation", "ESCALATE")
    synthesis = result.get("synthesis", {})

    response_data = {
        "success": True,
        "message": f"Dialectic complete. Recommendation: {recommendation}",
        "recommendation": recommendation,
        "thesis": {
            "root_cause": thesis["root_cause"],
            "proposed_conditions": thesis["proposed_conditions"]
        },
        "antithesis": {
            "concerns": result.get("antithesis", {}).get("concerns", ""),
            "counter_reasoning": result.get("antithesis", {}).get("counter_reasoning", ""),
            "suggested_conditions": result.get("antithesis", {}).get("suggested_conditions", "")
        },
        "synthesis": {
            "agreed_root_cause": synthesis.get("agreed_root_cause", ""),
            "merged_conditions": synthesis.get("merged_conditions", ""),
            "reasoning": synthesis.get("reasoning", "")
        },
        "next_steps": _get_dialectic_next_steps(recommendation),
        "_note": "Generated via LLM-assisted dialectic (no peer reviewer required)"
    }

    # Store as discovery in knowledge graph for learning
    try:
        from .llm_delegation import call_local_llm  # Verify import works
        from src.knowledge_graph import get_knowledge_graph, DiscoveryNode

        graph = await get_knowledge_graph()
        discovery = DiscoveryNode(
            agent_id=agent_uuid,
            summary=f"LLM dialectic: {root_cause[:80]}... → {recommendation}",
            type="dialectic_synthesis",
            tags=["dialectic", "llm-assisted", "recovery", recommendation.lower()],
            details=json.dumps({
                "thesis": thesis,
                "antithesis": result.get("antithesis"),
                "synthesis": synthesis,
                "recommendation": recommendation
            }, indent=2)
        )
        await graph.store(discovery)
        response_data["discovery_stored"] = True
    except Exception as e:
        logger.debug(f"Could not store dialectic discovery: {e}")

    return success_response(response_data, agent_id=agent_uuid, arguments=arguments)


def _get_dialectic_next_steps(recommendation: str) -> List[str]:
    """Get next steps based on dialectic recommendation."""
    if recommendation == "RESUME":
        return [
            "You can resume work with the agreed conditions",
            "Call process_agent_update() to log your next action",
            "Monitor your coherence with get_governance_metrics()"
        ]
    elif recommendation == "COOLDOWN":
        return [
            "Take a brief pause before resuming",
            "Review the synthesis reasoning",
            "When ready, call process_agent_update() with lower complexity"
        ]
    else:  # ESCALATE
        return [
            "The dialectic suggests human review may be needed",
            "Consider simplifying your approach",
            "Use request_dialectic_review() for peer review if available"
        ]
