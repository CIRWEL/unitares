"""
MCP Handlers for Circuit Breaker Dialectic Protocol

Implements MCP tools for peer-review dialectic resolution of circuit breaker states.
"""

from typing import Dict, Any, Sequence, Optional, List
from mcp.types import TextContent
import asyncio
import json
from datetime import datetime, timedelta, timezone
import random

# Import type definitions
from ..types import (
    ToolArgumentsDict,
    DialecticSessionDict,
    ResolutionDict
)

from src.dialectic_protocol import (
    DialecticSession,
    DialecticMessage,
    DialecticPhase,
    Resolution,
    QuorumVote,
    QuorumResult,
    tally_quorum_votes,
)
from ..utils import success_response, error_response, require_registered_agent
from ..decorators import mcp_tool
from ..support.coerce import resolve_agent_uuid
from .auth import resolve_dialectic_agent_id
from .responses import (
    default_cooldown_steps,
    default_escalate_steps,
    default_quorum_steps,
    default_resume_steps,
    get_agent_not_found_recovery,
    get_reviewer_stuck_recovery,
    get_session_exception_recovery,
    get_session_timeout_recovery,
    llm_failed_recovery,
    llm_incomplete_recovery,
    llm_missing_root_cause_recovery,
    llm_unavailable_recovery,
    missing_session_id_recovery,
    missing_session_or_agent_recovery,
    no_sessions_found_recovery,
    next_step_execution_failed,
    next_step_negotiate_synthesis,
    next_step_no_consensus,
    next_step_quorum_initiated,
    next_step_resume_not_applied,
    next_step_resumed,
    next_step_submit_antithesis,
    session_not_found_recovery,
)

async def _resolve_dialectic_agent_id(
    arguments: Dict[str, Any],
    *,
    enforce_session_ownership: bool = False,
) -> tuple:
    """Backward-compatible wrapper around shared dialectic auth policy."""
    return await resolve_dialectic_agent_id(
        arguments, enforce_session_ownership=enforce_session_ownership
    )
from src.logging_utils import get_logger
import sys
import os

logger = get_logger(__name__)

# Import from mcp_server_std module (using shared utility)
from src.mcp_handlers.shared import lazy_mcp_server as mcp_server
# Import session persistence from new module
from .session import (
    save_session,
    load_session,
    load_session_as_dict,
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
from .calibration import (
    update_calibration_from_dialectic,
    update_calibration_from_dialectic_disagreement,
    backfill_calibration_from_historical_sessions
)
from .resolution import execute_resolution
from .reviewer import select_reviewer, select_quorum_reviewers, is_agent_in_active_session

# Import PostgreSQL async functions for dialectic session storage
from src.dialectic_db import (
    create_session_async as pg_create_session,
    update_session_phase_async as pg_update_phase,
    update_session_reviewer_async as pg_update_reviewer,
    add_message_async as pg_add_message,
    resolve_session_async as pg_resolve_session,
    get_session_async as pg_get_session,
    get_session_by_agent_async as pg_get_session_by_agent,
)

# Import database abstraction for dual-write (Phase 4 migration)
from src.db import get_db

# ==============================================================================
# NOTE: Dialectic handlers (Feb 2026)
# ==============================================================================
# ACTIVE: request_dialectic_review, submit_thesis, submit_antithesis, submit_synthesis
# ACTIVE: get_dialectic_session, list_dialectic_sessions, llm_assisted_dialectic
# Still removed: request_exploration_session, nudge_dialectic_session, handle_self_recovery
# ==============================================================================

async def check_reviewer_stuck(session: DialecticSession) -> bool:
    """
    Check if reviewer is stuck (paused or hasn't responded after thesis submission).

    Only meaningful during ANTITHESIS phase — that's when the reviewer needs to respond.
    Uses thesis submission time (not session creation time) and aligns with
    the protocol's MAX_ANTITHESIS_WAIT (2 hours).

    Returns:
        True if reviewer is stuck, False otherwise
    """
    # Only check during ANTITHESIS phase — reviewer hasn't been asked in other phases
    if session.phase != DialecticPhase.ANTITHESIS:
        return False

    reviewer_id = session.reviewer_agent_id
    if not reviewer_id:
        return False  # No reviewer assigned yet — not stuck, just unassigned

    # Reload metadata from PostgreSQL (async)
    await mcp_server.load_metadata_async(force=True)

    reviewer_meta = mcp_server.agent_metadata.get(reviewer_id)
    if not reviewer_meta:
        return True  # Reviewer doesn't exist = stuck

    # Check if reviewer is paused
    if reviewer_meta.status == "paused":
        return True

    # Measure from thesis submission time (when reviewer was actually asked to respond)
    # Aligned with protocol's MAX_ANTITHESIS_WAIT (2 hours)
    try:
        thesis_time = session.get_thesis_timestamp()
        if thesis_time is None:
            return False  # No thesis yet — reviewer can't be stuck
        # Handle timezone mismatch
        if thesis_time.tzinfo is None:
            wait_time = datetime.now() - thesis_time
        else:
            wait_time = datetime.now(timezone(timedelta(0))) - thesis_time
        stuck_threshold = timedelta(hours=2)
        return wait_time > stuck_threshold
    except (ValueError, TypeError, AttributeError):
        return False  # Can't determine — don't kill the session

@mcp_tool("request_dialectic_review", timeout=60.0, register=True)
async def handle_request_dialectic_review(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Create a dialectic recovery session.

    This is a lightweight entry point restored for recovery workflows.
    It sets up the session and persists it, but does not auto-progress the protocol.
    """
    # Require a registered agent and use authoritative UUID for internal IDs
    # (Same pipeline as onboard/identity — dialectic was previously wonky using get_bound_agent_id)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    agent_uuid = resolve_agent_uuid(arguments, agent_id)

    # SECURITY: Verify ownership via session binding (UUID-based auth, Dec 2025)
    from ..utils import verify_agent_ownership
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

    # Skip auto-triggered sessions for non-reasoning agents (embodied/anima).
    # These agents can't submit theses — sessions would remain stuck at thesis phase forever.
    reviewer_mode = arguments.get("reviewer_mode", "")
    if reviewer_mode == "auto":
        agent_tags = set(t.lower() for t in (getattr(meta, "tags", None) or []))
        if agent_tags & {"autonomous", "embodied", "anima"}:
            logger.info(f"[DIALECTIC] Skipping auto-recovery for non-reasoning agent {agent_uuid[:12]}...")
            return success_response({
                "success": True,
                "skipped": True,
                "reason": "Non-reasoning agent cannot participate in dialectic",
                "agent_id": agent_uuid,
                "agent_tags": list(agent_tags & {"autonomous", "embodied", "anima"}),
                "recommendation": "Pause event logged. Recovery handled via agent lifecycle, not dialectic."
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
    reviewer_mode = arguments.get("reviewer_mode", "auto")  # auto|self|llm
    max_synthesis_rounds = arguments.get("max_synthesis_rounds", 5)

    # LLM-assisted dialectic: delegate to synthetic reviewer
    if reviewer_mode == "llm":
        llm_args = {
            "root_cause": reason,
            "proposed_conditions": arguments.get("proposed_conditions", []),
            "reasoning": arguments.get("reasoning", ""),
        }
        for key in ("agent_id", "client_session_id", "api_key", "session_type"):
            if key in arguments:
                llm_args[key] = arguments[key]
        return await handle_llm_assisted_dialectic(llm_args)

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
    elif reviewer_mode == "auto":
        # Auto-select a reviewer from eligible agents
        # Falls back to None if no eligible agents (first responder can claim via submit_antithesis)
        await mcp_server.load_metadata_async(force=True)
        try:
            reviewer_agent_id = await select_reviewer(
                paused_agent_id=agent_uuid,
                metadata=mcp_server.agent_metadata,
            )
        except Exception as e:
            logger.warning(f"Auto reviewer selection failed, session will await manual assignment: {e}")
            reviewer_agent_id = None
    else:
        # Manual mode or unknown - no reviewer assigned
        # First responder can claim via submit_antithesis
        reviewer_agent_id = None

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

    # Persist to PostgreSQL (single source of truth)
    # JSON snapshots removed - use export_dialectic_session() for debugging
    try:
        await pg_create_session(
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
        logger.info(f"Dialectic session {session.session_id} persisted to PostgreSQL")
    except Exception as e:
        logger.error(f"Dialectic session create FAILED: {e}")
        return [error_response(
            f"Failed to persist dialectic session: {e}",
            error_code="DB_WRITE_FAILED",
            error_category="system_error",
            arguments=arguments
        )]

    # Cache in-memory for quick access
    ACTIVE_SESSIONS[session.session_id] = session

    # Build response based on whether reviewer is assigned
    if session.reviewer_agent_id:
        note = "Session created with self-review. Use submit_thesis to add your thesis."
    else:
        note = "Session created. Awaiting reviewer assignment. Operator should assign a reviewer, then paused agent submits thesis."

    return success_response({
        "success": True,
        "message": "Dialectic session created",
        "session_id": session.session_id,
        "paused_agent_id": session.paused_agent_id,
        "reviewer_agent_id": session.reviewer_agent_id,
        "awaiting_reviewer": session.reviewer_agent_id is None,
        "phase": session.phase.value,
        "session_type": session.session_type,
        "note": note
    })

@mcp_tool("get_dialectic_session", timeout=10.0, rate_limit_exempt=True, register=False)
async def handle_get_dialectic_session(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    View historical dialectic sessions (archive).

    Dialectic protocol is now archived - this tool views past sessions only.
    For current state, use get_governance_metrics.
    For recovery, use self_recovery(action='quick').

    Args:
        session_id: Dialectic session ID (optional if agent_id provided)
        agent_id: Agent ID to find sessions for (optional if session_id provided)

    Returns:
        Historical session state including transcript
    """
    try:
        session_id = arguments.get('session_id')
        agent_id = arguments.get('agent_id')
        check_timeout = arguments.get('check_timeout', False)

        # If session_id provided, use it directly
        if session_id:
            # Fast path: skip object reconstruction when timeout checks disabled (dashboard use case)
            if not check_timeout:
                fast_result = await load_session_as_dict(session_id)
                if fast_result:
                    fast_result["success"] = True
                    return success_response(fast_result)

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
                    timeout_msg = DialecticMessage(
                        phase="synthesis",
                        agent_id="system",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        reasoning=f"Session auto-failed: {timeout_reason}"
                    )
                    session.transcript.append(timeout_msg)
                    # Persist to PostgreSQL
                    try:
                        await pg_add_message(
                            session_id=session_id,
                            agent_id="system",
                            message_type="failed",
                            reasoning=f"Session auto-failed: {timeout_reason}",
                        )
                        await pg_update_phase(session_id, "failed")
                    except Exception as e:
                        logger.error(f"Failed to persist timeout to PostgreSQL: {e}")
                    # QUICK WIN B: Improved error message with actionable guidance
                    return success_response({
                        "success": False,
                        "error": timeout_reason,
                        "session": session.to_dict(),
                        "recovery": get_session_timeout_recovery(timeout_reason),
                    })

                # Check if reviewer is stuck
                if await check_reviewer_stuck(session):
                    session.phase = DialecticPhase.FAILED
                    stuck_msg = DialecticMessage(
                        phase="failed",
                        agent_id="system",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        reasoning="Reviewer stuck - session aborted"
                    )
                    session.transcript.append(stuck_msg)
                    # Persist to PostgreSQL
                    try:
                        await pg_add_message(
                            session_id=session_id,
                            agent_id="system",
                            message_type="failed",
                            reasoning="Reviewer stuck - session aborted",
                        )
                        await pg_update_phase(session_id, "failed")
                    except Exception as e:
                        logger.error(f"Failed to persist reviewer stuck to PostgreSQL: {e}")
                    # QUICK WIN B: Improved error message with actionable guidance
                    return success_response({
                        "success": False,
                        "error": "Reviewer stuck - session aborted",
                        "session": session.to_dict(),
                        "recovery": get_reviewer_stuck_recovery(session.reviewer_agent_id),
                    })

            result = session.to_dict()
            result["success"] = True
            return success_response(result)
        
        # If agent_id provided, find all sessions for this agent
        if agent_id:
            # Reload metadata from PostgreSQL (async)
            await mcp_server.load_metadata_async(force=True)
            
            # Check if agent exists
            if agent_id not in mcp_server.agent_metadata:
                return [error_response(
                    f"Agent '{agent_id}' not found",
                    recovery=get_agent_not_found_recovery(),
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
                    recovery=no_sessions_found_recovery(),
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
            recovery=missing_session_or_agent_recovery(),
        )]

    except Exception as e:
        import traceback
        # SECURITY: Log full traceback internally but sanitize for client
        logger.error(f"Error getting dialectic session: {e}", exc_info=True)
        return [error_response(
            f"Error getting session: {str(e)}",
            recovery=get_session_exception_recovery(),
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

@mcp_tool("submit_thesis", timeout=10.0, register=True)
async def handle_submit_thesis(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Paused agent submits thesis: "What I did, what I think happened"

    Args:
        session_id: Dialectic session ID
        agent_id: Paused agent ID (or use bound identity)
        root_cause: Agent's understanding of what caused the issue
        proposed_conditions: List of conditions for resumption
        reasoning: Natural language explanation

    Returns:
        Status with next phase
    """
    try:
        session_id = arguments.get('session_id')
        api_key = arguments.get('api_key', '')

        if not session_id:
            return [error_response(
                "session_id is required",
                recovery=missing_session_id_recovery(),
            )]

        # Use same identity pipeline as onboard/identity (consistent UUID)
        agent_id, agent_error = await _resolve_dialectic_agent_id(
            arguments, enforce_session_ownership=True
        )
        if agent_error:
            return agent_error

        # Get session - reload from disk if not in memory
        session = ACTIVE_SESSIONS.get(session_id)
        if not session:
            session = await load_session(session_id)
            if session:
                ACTIVE_SESSIONS[session_id] = session
            else:
                return [error_response(
                    f"Session '{session_id}' not found",
                    recovery=session_not_found_recovery(),
                )]

        # Create thesis message
        message = DialecticMessage(
            phase="thesis",
            agent_id=agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            root_cause=arguments.get('root_cause'),
            proposed_conditions=arguments.get('proposed_conditions', []),
            reasoning=arguments.get('reasoning')
        )

        # Submit to session
        result = session.submit_thesis(message, api_key)

        if result["success"]:
            result["next_step"] = next_step_submit_antithesis(session.reviewer_agent_id)

            # Persist to PostgreSQL
            try:
                await pg_add_message(
                    session_id=session_id,
                    agent_id=agent_id,
                    message_type="thesis",
                    root_cause=arguments.get('root_cause'),
                    proposed_conditions=arguments.get('proposed_conditions', []),
                    reasoning=arguments.get('reasoning'),
                )
                await pg_update_phase(session_id, session.phase.value)
            except Exception as e:
                logger.warning(f"Could not update PostgreSQL after thesis: {e}")

            # Persist to JSON (export snapshot)
            try:
                await save_session(session)
            except Exception as e:
                logger.warning(f"Could not save session after thesis: {e}")

        return success_response(result)

    except Exception as e:
        return [error_response(f"Error submitting thesis: {str(e)}")]

@mcp_tool("submit_antithesis", timeout=10.0, register=True)
async def handle_submit_antithesis(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Reviewer agent submits antithesis: "What I observe, my concerns"

    Args:
        session_id: Dialectic session ID
        agent_id: Reviewer agent ID (or use bound identity)
        observed_metrics: Metrics observed about paused agent
        concerns: List of concerns
        reasoning: Natural language explanation

    Returns:
        Status with next phase
    """
    try:
        session_id = arguments.get('session_id')
        api_key = arguments.get('api_key', '')

        if not session_id:
            return [error_response(
                "session_id is required",
                recovery=missing_session_id_recovery(),
            )]

        # Use same identity pipeline as onboard/identity (consistent UUID)
        agent_id, agent_error = await _resolve_dialectic_agent_id(
            arguments, enforce_session_ownership=True
        )
        if agent_error:
            return agent_error

        # Get session
        session = ACTIVE_SESSIONS.get(session_id)
        if not session:
            session = await load_session(session_id)
            if session:
                ACTIVE_SESSIONS[session_id] = session
            else:
                return [error_response(
                    f"Session '{session_id}' not found",
                    recovery=session_not_found_recovery(),
                )]

        # First-responder eligibility: if no reviewer assigned, validate the
        # submitter before the protocol auto-assigns them as reviewer.
        # Without this, any agent could claim the reviewer slot with no checks.
        if session.reviewer_agent_id is None and agent_id != session.paused_agent_id:
            from .reviewer import _has_recently_reviewed, is_agent_in_active_session
            try:
                if await is_agent_in_active_session(agent_id):
                    return [error_response(
                        "Cannot become reviewer: already in an active dialectic session",
                        recovery={"action": "Wait for your current session to complete"}
                    )]
                if await _has_recently_reviewed(agent_id, session.paused_agent_id):
                    return [error_response(
                        "Cannot become reviewer: recently reviewed this agent (24h cooldown)",
                        recovery={"action": "A different agent should review this session"}
                    )]
            except Exception as e:
                logger.warning(f"First-responder eligibility check failed (proceeding): {e}")

        # Create antithesis message
        message = DialecticMessage(
            phase="antithesis",
            agent_id=agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            observed_metrics=arguments.get('observed_metrics', {}),
            concerns=arguments.get('concerns', []),
            reasoning=arguments.get('reasoning')
        )

        # Submit to session
        result = session.submit_antithesis(message, api_key)

        if result["success"]:
            result["next_step"] = next_step_negotiate_synthesis()

            # If reviewer was auto-assigned (first-responder pattern), persist to PG
            if result.get("reviewer_auto_assigned") or session.reviewer_agent_id == agent_id:
                try:
                    await pg_update_reviewer(session_id, agent_id)
                    result["reviewer_auto_assigned"] = True
                    logger.info(f"Reviewer auto-assigned: {agent_id[:8]}... for session {session_id[:8]}...")
                except Exception as e:
                    logger.warning(f"Could not persist reviewer assignment to PostgreSQL: {e}")

            # Persist to PostgreSQL
            try:
                await pg_add_message(
                    session_id=session_id,
                    agent_id=agent_id,
                    message_type="antithesis",
                    observed_metrics=arguments.get('observed_metrics', {}),
                    concerns=arguments.get('concerns', []),
                    reasoning=arguments.get('reasoning'),
                )
                await pg_update_phase(session_id, session.phase.value)
            except Exception as e:
                logger.warning(f"Could not update PostgreSQL after antithesis: {e}")

            # Persist to JSON
            try:
                await save_session(session)
            except Exception as e:
                logger.warning(f"Could not save session after antithesis: {e}")

        return success_response(result)

    except Exception as e:
        return [error_response(f"Error submitting antithesis: {str(e)}")]

@mcp_tool("submit_synthesis", timeout=15.0, register=True)
async def handle_submit_synthesis(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Either agent submits synthesis proposal during negotiation.

    Args:
        session_id: Dialectic session ID
        agent_id: Agent ID (either paused or reviewer)
        proposed_conditions: Proposed resumption conditions
        root_cause: Agreed understanding of root cause
        reasoning: Explanation of proposal
        agrees: Whether this agent agrees with current proposal (bool)

    Returns:
        Status with convergence info and resolution if converged
    """
    try:
        session_id = arguments.get('session_id')
        api_key = arguments.get('api_key', '')

        if not session_id:
            return [error_response(
                "session_id is required",
                recovery=missing_session_id_recovery(),
            )]

        # Use same identity pipeline as onboard/identity (consistent UUID)
        # Supports third-party synthesizer when agent_id is explicitly provided
        agent_id, agent_error = await _resolve_dialectic_agent_id(arguments)
        if agent_error:
            return agent_error

        # Always reload from disk to get latest state
        session = await load_session(session_id)
        if session:
            ACTIVE_SESSIONS[session_id] = session
        else:
            session = ACTIVE_SESSIONS.get(session_id)
            if not session:
                return [error_response(
                    f"Session '{session_id}' not found",
                    recovery=session_not_found_recovery(),
                )]

        # Coerce agrees to bool (MCP tools may send "true"/"false" strings)
        raw_agrees = arguments.get('agrees', False)
        if isinstance(raw_agrees, str):
            agrees = raw_agrees.lower() in ('true', '1', 'yes')
        else:
            agrees = bool(raw_agrees)

        # Create synthesis message
        message = DialecticMessage(
            phase="synthesis",
            agent_id=agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            proposed_conditions=arguments.get('proposed_conditions', []),
            root_cause=arguments.get('root_cause'),
            reasoning=arguments.get('reasoning'),
            agrees=agrees
        )

        # Submit to session
        result = session.submit_synthesis(message, api_key)

        if result.get("success"):
            # Persist synthesis message to PostgreSQL
            # NOTE: Defer phase update for converged sessions until after finalize_resolution
            # succeeds, to avoid "resolved" phase in PG without a resolution if finalize fails.
            try:
                await pg_add_message(
                    session_id=session_id,
                    agent_id=agent_id,
                    message_type="synthesis",
                    root_cause=arguments.get('root_cause'),
                    proposed_conditions=arguments.get('proposed_conditions', []),
                    reasoning=arguments.get('reasoning'),
                    agrees=arguments.get('agrees', False),
                )
                if not result.get("converged"):
                    await pg_update_phase(session_id, session.phase.value)
            except Exception as e:
                logger.warning(f"Could not update PostgreSQL after synthesis: {e}")

            # Persist to JSON
            try:
                await save_session(session)
            except Exception as e:
                logger.warning(f"Could not save session after synthesis: {e}")

        # If converged, finalize resolution
        if result.get("success") and result.get("converged"):
            # Generate signatures
            paused_meta = mcp_server.agent_metadata.get(session.paused_agent_id)
            reviewer_meta = mcp_server.agent_metadata.get(session.reviewer_agent_id)

            api_key_a = paused_meta.api_key if paused_meta and paused_meta.api_key else api_key
            api_key_b = reviewer_meta.api_key if reviewer_meta and reviewer_meta.api_key else ""

            synthesis_messages = [msg for msg in session.transcript if msg.phase == "synthesis" and msg.agrees]
            if synthesis_messages:
                last_msg = synthesis_messages[-1]
                signature_a = last_msg.sign(api_key_a) if api_key_a else ""
                signature_b = last_msg.sign(api_key_b) if api_key_b else ""
            else:
                import hashlib
                session_data = f"{session.session_id}:{api_key_a}"
                signature_a = hashlib.sha256(session_data.encode()).hexdigest()[:32]
                session_data = f"{session.session_id}:{api_key_b}"
                signature_b = hashlib.sha256(session_data.encode()).hexdigest()[:32] if api_key_b else ""

            resolution = session.finalize_resolution(signature_a, signature_b)
            is_safe, violation = session.check_hard_limits(resolution)

            if not is_safe:
                # Safety violation: mark session as FAILED (not RESOLVED)
                session.phase = DialecticPhase.FAILED
                result["action"] = "block"
                result["success"] = False
                result["reason"] = f"Safety violation: {violation}"
                try:
                    await pg_resolve_session(session_id=session_id, resolution={"action": "block", "reason": violation}, status="failed")
                except Exception as e:
                    logger.warning(f"Could not resolve session in PostgreSQL: {e}")
            else:
                result["action"] = "resume"
                result["resolution"] = resolution.to_dict()

                try:
                    execution_result = await execute_resolution(session, resolution)
                    result["execution"] = execution_result
                    if execution_result.get("success"):
                        result["next_step"] = next_step_resumed()
                    else:
                        result["next_step"] = next_step_resume_not_applied(
                            execution_result.get("warning")
                        )

                    # Execution succeeded - mark resolved in PG
                    try:
                        await pg_resolve_session(session_id=session_id, resolution=resolution.to_dict(), status="resolved")
                    except Exception as e:
                        logger.warning(f"Could not resolve session in PostgreSQL: {e}")
                except Exception as e:
                    # Execution failed - mark FAILED, not resolved
                    session.phase = DialecticPhase.FAILED
                    result["success"] = False
                    result["execution_error"] = str(e)
                    result["next_step"] = next_step_execution_failed(e)
                    try:
                        await pg_resolve_session(session_id=session_id, resolution=resolution.to_dict(), status="failed")
                    except Exception as pg_e:
                        logger.warning(f"Could not mark failed session in PostgreSQL: {pg_e}")

            # Update calibration from dialectic outcome
            try:
                if result.get("action") == "resume":
                    await update_calibration_from_dialectic(session)
                elif not is_safe:
                    await update_calibration_from_dialectic_disagreement(session)
            except Exception as cal_e:
                logger.debug(f"Calibration update after dialectic: {cal_e}")

            # Always invalidate cache after convergence (success or failure)
            for aid in (session.paused_agent_id, session.reviewer_agent_id):
                if aid and aid in _SESSION_METADATA_CACHE:
                    del _SESSION_METADATA_CACHE[aid]

            await save_session(session)

        elif not result.get("success"):
            # Max rounds exceeded — try quorum escalation before conservative default
            quorum_info = await _initiate_quorum(session)
            if quorum_info:
                result["autonomous_resolution"] = False
                result["resolution_type"] = "quorum_escalation"
                result["quorum"] = quorum_info
                result["next_step"] = next_step_quorum_initiated(len(quorum_info["reviewer_ids"]))
                result["next_steps"] = default_quorum_steps()
            else:
                # Not enough agents for quorum — fall back to conservative default
                result["autonomous_resolution"] = True
                result["resolution_type"] = "conservative_default"
                result["next_step"] = next_step_no_consensus()
                result["cooldown_until"] = (datetime.now() + timedelta(hours=1)).isoformat()

        return success_response(result)

    except Exception as e:
        return [error_response(f"Error submitting synthesis: {str(e)}")]


async def _initiate_quorum(session: DialecticSession) -> Optional[Dict[str, Any]]:
    """
    Attempt to initiate quorum voting for an escalated dialectic session.

    Selects 3-5 reviewers, sets session phase to QUORUM_VOTING,
    and persists quorum data to PostgreSQL.

    Returns:
        Dict with reviewer_ids, scores, and deadline if quorum formed.
        None if fewer than 3 eligible reviewers.
    """
    await mcp_server.load_metadata_async(force=True)
    metadata = mcp_server.agent_metadata or {}

    reviewers = await select_quorum_reviewers(session, metadata)
    if not reviewers:
        return None

    reviewer_ids = [r[0] for r in reviewers]
    reviewer_scores = {r[0]: r[1] for r in reviewers}
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    session.phase = DialecticPhase.QUORUM_VOTING

    # Persist to PostgreSQL
    try:
        from src.db import get_db
        db = await get_db()
        await db.execute(
            """UPDATE core.dialectic_sessions
               SET phase = 'quorum_voting',
                   status = 'quorum_voting',
                   quorum_reviewer_ids = $1::jsonb,
                   quorum_deadline = $2::timestamptz,
                   updated_at = NOW()
             WHERE session_id = $3""",
            json.dumps(reviewer_ids),
            deadline,
            session.session_id,
        )
    except Exception as e:
        logger.warning(f"Could not persist quorum to PostgreSQL: {e}")

    try:
        await save_session(session)
    except Exception as e:
        logger.warning(f"Could not save quorum session to JSON: {e}")

    return {
        "reviewer_ids": reviewer_ids,
        "reviewer_scores": reviewer_scores,
        "deadline": deadline,
        "session_id": session.session_id,
    }


@mcp_tool("submit_quorum_vote", register=True)
async def handle_submit_quorum_vote(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Submit a vote in a quorum-escalated dialectic session.

    Only agents assigned to the quorum may vote. Voting closes when all
    assigned reviewers have voted or when 3+ votes are received.
    A 2/3 authority-weighted supermajority decides the outcome.

    Args:
        session_id: Dialectic session ID
        vote: "resume", "block", or "cooldown"
        reasoning: Explanation for your vote
        conditions: Optional conditions (for resume votes)
    """
    try:
        # Require registered agent
        agent_id, error = require_registered_agent(arguments)
        if error:
            return [error]

        session_id = arguments.get("session_id")
        if not session_id:
            return [error_response(
                "session_id is required",
                recovery=missing_session_id_recovery(),
            )]

        vote_value = arguments.get("vote")
        if vote_value not in ("resume", "block", "cooldown"):
            return [error_response("vote must be 'resume', 'block', or 'cooldown'")]

        reasoning = arguments.get("reasoning", "")
        conditions = arguments.get("conditions")

        # Load session
        session = await load_session(session_id)
        if not session:
            return [error_response(
                f"Session '{session_id}' not found",
                recovery=session_not_found_recovery(),
            )]

        # Verify phase
        if session.phase != DialecticPhase.QUORUM_VOTING:
            return [error_response(
                f"Session is in phase '{session.phase.value}', not 'quorum_voting'"
            )]

        # Load quorum reviewer IDs from PostgreSQL
        quorum_reviewer_ids = []
        try:
            from src.db import get_db
            db = await get_db()
            row = await db.fetchrow(
                "SELECT quorum_reviewer_ids FROM core.dialectic_sessions WHERE session_id = $1",
                session_id,
            )
            if row and row["quorum_reviewer_ids"]:
                qr = row["quorum_reviewer_ids"]
                quorum_reviewer_ids = json.loads(qr) if isinstance(qr, str) else qr
        except Exception as e:
            logger.warning(f"Could not load quorum_reviewer_ids from PG: {e}")

        if not quorum_reviewer_ids:
            return [error_response("No quorum reviewers assigned to this session")]

        # Verify agent is in the quorum
        agent_uuid = resolve_agent_uuid(arguments, agent_id)
        if agent_uuid not in quorum_reviewer_ids and agent_id not in quorum_reviewer_ids:
            return [error_response(
                f"Agent '{agent_id}' is not in the quorum for this session"
            )]

        # Check for duplicate vote
        existing_votes = [
            msg for msg in session.transcript
            if msg.phase == "quorum_vote" and msg.agent_id in (agent_id, agent_uuid)
        ]
        if existing_votes:
            return [error_response(f"Agent '{agent_id}' has already voted in this session")]

        # Get authority weight for this voter
        await mcp_server.load_metadata_async(force=True)
        voter_meta = mcp_server.agent_metadata.get(agent_uuid) or mcp_server.agent_metadata.get(agent_id)
        meta_dict = {}
        if voter_meta and not isinstance(voter_meta, str):
            for attr in ('tags', 'total_reviews', 'successful_reviews', 'last_update'):
                val = getattr(voter_meta, attr, None) if not isinstance(voter_meta, dict) else voter_meta.get(attr)
                if val is not None:
                    meta_dict[attr] = val
        try:
            from src.dialectic_protocol import calculate_authority_score
            authority_weight = calculate_authority_score(meta_dict)
        except Exception:
            authority_weight = 0.5

        # Store vote as DialecticMessage
        vote_msg = DialecticMessage(
            phase="quorum_vote",
            agent_id=agent_uuid or agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            reasoning=reasoning,
            proposed_conditions=conditions,
            observed_metrics={"authority_weight": authority_weight, "vote": vote_value},
        )
        session.transcript.append(vote_msg)

        # Persist message to PostgreSQL
        try:
            await pg_add_message(
                session_id=session_id,
                agent_id=agent_uuid or agent_id,
                message_type="quorum_vote",
                reasoning=reasoning,
                proposed_conditions=conditions or [],
                observed_metrics={"authority_weight": authority_weight, "vote": vote_value},
            )
        except Exception as e:
            logger.warning(f"Could not persist quorum vote to PG: {e}")

        await save_session(session)

        # Collect all quorum votes from transcript
        all_vote_msgs = [
            msg for msg in session.transcript
            if msg.phase == "quorum_vote"
        ]
        vote_count = len(all_vote_msgs)

        # Tally when: all reviewers voted OR 3+ votes received
        should_tally = (vote_count >= len(quorum_reviewer_ids)) or (vote_count >= 3)

        result: Dict[str, Any] = {
            "success": True,
            "session_id": session_id,
            "vote_recorded": True,
            "votes_received": vote_count,
            "votes_needed": len(quorum_reviewer_ids),
        }

        if not should_tally:
            result["status"] = "awaiting_more_votes"
            result["next_step"] = f"Waiting for more votes ({vote_count}/{len(quorum_reviewer_ids)})"
            return success_response(result)

        # Build QuorumVote objects and tally
        quorum_votes = []
        for msg in all_vote_msgs:
            metrics = msg.observed_metrics or {}
            quorum_votes.append(QuorumVote(
                agent_id=msg.agent_id,
                vote=metrics.get("vote", "cooldown"),
                authority_weight=metrics.get("authority_weight", 0.5),
                reasoning=msg.reasoning or "",
                conditions=msg.proposed_conditions,
                timestamp=msg.timestamp,
            ))

        tally = tally_quorum_votes(quorum_votes)
        result["quorum_result"] = tally.to_dict()

        # Persist quorum result
        try:
            from src.db import get_db
            db = await get_db()
            await db.execute(
                """UPDATE core.dialectic_sessions
                   SET quorum_result = $1::jsonb, updated_at = NOW()
                 WHERE session_id = $2""",
                json.dumps(tally.to_dict()),
                session_id,
            )
        except Exception as e:
            logger.warning(f"Could not persist quorum_result to PG: {e}")

        if tally.achieved_supermajority and tally.action == "resume":
            # Merge conditions from resume voters
            merged_conditions = []
            for qv in quorum_votes:
                if qv.vote == "resume" and qv.conditions:
                    for c in qv.conditions:
                        if c not in merged_conditions:
                            merged_conditions.append(c)
            if not merged_conditions:
                merged_conditions = ["Monitor coherence for 24h"]

            # Build resolution and execute
            resolution = Resolution(
                action="resume",
                conditions=merged_conditions,
                root_cause=f"Quorum vote: {tally.vote_counts}",
                reasoning=f"Quorum supermajority ({tally.margin:.0%}) voted to resume",
                signature_a="quorum",
                signature_b="quorum",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            session.resolution = resolution
            session.phase = DialecticPhase.RESOLVED

            try:
                execution_result = await execute_resolution(session, resolution)
                result["execution"] = execution_result
                result["next_step"] = next_step_resumed()
                result["next_steps"] = default_resume_steps()
            except Exception as e:
                result["execution_error"] = str(e)
                result["next_step"] = next_step_execution_failed(e)

            try:
                await pg_resolve_session(
                    session_id=session_id,
                    resolution=resolution.to_dict(),
                    status="resolved",
                )
            except Exception as e:
                logger.warning(f"Could not mark quorum-resolved session in PG: {e}")

        elif tally.achieved_supermajority and tally.action == "block":
            session.phase = DialecticPhase.FAILED
            result["next_step"] = "Quorum voted to block. Agent remains paused."
            try:
                await pg_resolve_session(
                    session_id=session_id,
                    resolution={"action": "block", "quorum_result": tally.to_dict()},
                    status="failed",
                )
            except Exception as e:
                logger.warning(f"Could not mark quorum-blocked session in PG: {e}")

        else:
            # No supermajority (including cooldown majority) — conservative default
            session.phase = DialecticPhase.ESCALATED
            result["next_step"] = next_step_no_consensus()
            result["cooldown_until"] = (datetime.now() + timedelta(hours=1)).isoformat()
            try:
                await pg_resolve_session(
                    session_id=session_id,
                    resolution={"action": "cooldown", "quorum_result": tally.to_dict()},
                    status="escalated",
                )
            except Exception as e:
                logger.warning(f"Could not mark quorum-cooldown session in PG: {e}")

        # Invalidate cache
        for aid in (session.paused_agent_id, session.reviewer_agent_id):
            if aid and aid in _SESSION_METADATA_CACHE:
                del _SESSION_METADATA_CACHE[aid]

        await save_session(session)
        return success_response(result)

    except Exception as e:
        return [error_response(f"Error submitting quorum vote: {str(e)}")]


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
    from ..support.llm_delegation import run_full_dialectic, is_llm_available

    # Require registered agent
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    agent_uuid = resolve_agent_uuid(arguments, agent_id)

    # Check LLM availability
    if not await is_llm_available():
        return [error_response(
            "Local LLM (Ollama) not available for dialectic review",
            error_code="LLM_UNAVAILABLE",
            error_category="system_error",
            recovery=llm_unavailable_recovery(),
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
            recovery=llm_missing_root_cause_recovery(),
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
        "timestamp": datetime.now(timezone.utc).isoformat()
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
            recovery=llm_failed_recovery(),
        )]

    if not result.get("success"):
        return [error_response(
            f"Dialectic incomplete: {result.get('error', 'Unknown error')}",
            error_code="DIALECTIC_INCOMPLETE",
            error_category="system_error",
            recovery=llm_incomplete_recovery(result),
        )]

    # Format successful response
    recommendation = result.get("recommendation", "ESCALATE")
    synthesis = result.get("synthesis", {})
    antithesis_data = result.get("antithesis", {})

    # Persist as a proper dialectic session so it shows on the dashboard
    session_id = None
    try:
        from src.dialectic_protocol import DialecticSession
        session = DialecticSession(
            paused_agent_id=agent_uuid,
            reviewer_agent_id="llm-synthetic-reviewer",
            session_type=arguments.get("session_type", "recovery"),
            topic=root_cause[:200],
            max_synthesis_rounds=2,
        )
        session_id = session.session_id

        await pg_create_session(
            session_id=session_id,
            paused_agent_id=agent_uuid,
            reviewer_agent_id="llm-synthetic-reviewer",
            reason=root_cause,
            session_type=arguments.get("session_type", "recovery"),
            topic=root_cause[:200],
            max_synthesis_rounds=2,
            synthesis_round=1,
        )

        # Add thesis message
        await pg_add_message(
            session_id=session_id,
            agent_id=agent_uuid,
            message_type="thesis",
            root_cause=root_cause,
            proposed_conditions=proposed_conditions,
            reasoning=reasoning,
        )

        # Add antithesis message
        await pg_add_message(
            session_id=session_id,
            agent_id="llm-synthetic-reviewer",
            message_type="antithesis",
            reasoning=antithesis_data.get("counter_reasoning", antithesis_data.get("raw_response", "")[:500]),
            concerns=[antithesis_data.get("concerns", "")] if antithesis_data.get("concerns") else None,
        )

        # Add synthesis message
        await pg_add_message(
            session_id=session_id,
            agent_id="llm-synthetic-reviewer",
            message_type="synthesis",
            root_cause=synthesis.get("agreed_root_cause", ""),
            proposed_conditions=[synthesis.get("merged_conditions", "")] if synthesis.get("merged_conditions") else None,
            reasoning=synthesis.get("reasoning", ""),
            agrees=True,
        )

        # Resolve the session
        await pg_resolve_session(
            session_id=session_id,
            resolution={
                "action": recommendation.lower(),
                "source": "llm-assisted-dialectic",
                "agreed_root_cause": synthesis.get("agreed_root_cause", ""),
                "merged_conditions": synthesis.get("merged_conditions", ""),
            },
            status="resolved",
        )
        logger.info(f"LLM dialectic session {session_id} persisted to database")
    except Exception as e:
        logger.warning(f"Could not persist LLM dialectic session: {e}")

    response_data = {
        "success": True,
        "message": f"Dialectic complete. Recommendation: {recommendation}",
        "recommendation": recommendation,
        "session_id": session_id,
        "thesis": {
            "root_cause": thesis["root_cause"],
            "proposed_conditions": thesis["proposed_conditions"]
        },
        "antithesis": {
            "concerns": antithesis_data.get("concerns", ""),
            "counter_reasoning": antithesis_data.get("counter_reasoning", ""),
            "suggested_conditions": antithesis_data.get("suggested_conditions", "")
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
        return default_resume_steps()
    elif recommendation == "COOLDOWN":
        return default_cooldown_steps()
    else:  # ESCALATE
        return default_escalate_steps()
