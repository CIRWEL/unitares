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
from .utils import success_response, error_response
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
# NOTE: Most dialectic handlers removed (Dec 2025)
# ==============================================================================
# Removed: request_dialectic_review, request_exploration_session, 
#          submit_thesis, submit_antithesis, submit_synthesis,
#          nudge_dialectic_session, handle_self_recovery
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

@mcp_tool("get_dialectic_session", timeout=10.0, rate_limit_exempt=True)
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

