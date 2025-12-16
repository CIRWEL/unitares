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


def _maybe_fill_api_key_from_bound_identity(arguments: Dict[str, Any], agent_id: str) -> None:
    """
    Best-effort: If api_key is missing, try to resolve it from session-bound identity.

    Uses `client_session_id` to avoid collision with dialectic `session_id`.
    Only fills when the bound agent_id matches the requested agent_id.
    """
    if arguments.get("api_key"):
        return
    client_session_id = arguments.get("client_session_id")
    if not client_session_id:
        return
    try:
        from .identity import get_bound_agent_id, get_bound_api_key
        bound_agent_id = get_bound_agent_id(session_id=client_session_id, arguments=arguments)
        if bound_agent_id and bound_agent_id != agent_id:
            return
        bound_api_key = get_bound_api_key(session_id=client_session_id, arguments=arguments)
        if bound_api_key:
            arguments["api_key"] = bound_api_key
    except Exception:
        return

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


@mcp_tool("request_dialectic_review", timeout=15.0)
async def handle_request_dialectic_review(arguments: ToolArgumentsDict) -> Sequence[TextContent]:
    """
    Request a dialectic review for a paused/critical agent OR an agent stuck in loops OR a discovery dispute.

    Selects a healthy reviewer agent and initiates dialectic session.
    Can be used for:
    - Paused agents (circuit breaker triggered)
    - Agents stuck in repeated loops (loop cooldown active)
    - Discovery disputes/corrections (if discovery_id provided)
    - Any agent needing peer assistance

    Args:
        agent_id: ID of agent requesting review (paused, loop-stuck, or disputing discovery)
        reason: Reason for review request (e.g., "Circuit breaker triggered", "Stuck in loops", "Discovery seems incorrect", etc.)
        api_key: Agent's API key for authentication
        discovery_id: Optional - ID of discovery being disputed/corrected
        dispute_type: Optional - "dispute", "correction", "verification" (default: None for recovery)
        auto_progress: Optional - If True, auto-progresses through phases (smart mode, default: False)
        reviewer_mode: Optional - "peer" (default), "self" (system-assisted recovery), or "auto" (try peer, fallback to self)
        root_cause: Optional - Root cause (auto-generated if not provided and auto_progress=True)
        proposed_conditions: Optional - Proposed conditions (auto-generated if not provided and auto_progress=True)
        reasoning: Optional - Explanation (auto-generated if not provided and auto_progress=True)

    Returns:
        Session info with reviewer_id and session_id, or final resolution if auto_progressed
    """
    try:
        agent_id = arguments.get('agent_id')
        reason = arguments.get('reason', 'Circuit breaker triggered')
        _maybe_fill_api_key_from_bound_identity(arguments, agent_id)
        api_key = arguments.get('api_key')
        reviewer_agent_id = arguments.get('reviewer_agent_id')  # Optional explicit peer reviewer override
        discovery_id = arguments.get('discovery_id')  # Optional discovery ID
        dispute_type = arguments.get('dispute_type')  # Optional dispute type
        auto_progress = arguments.get('auto_progress', False)  # Smart mode
        reviewer_mode = arguments.get('reviewer_mode', 'peer')  # peer, self, or auto

        if not agent_id:
            return [error_response("agent_id is required")]
        
        # QUICK WIN A: Auto-resolve stuck sessions before checking for conflicts
        # This prevents false "session conflict" warnings when sessions are actually stuck
        try:
            from src.mcp_handlers.dialectic_auto_resolve import check_and_resolve_stuck_sessions
            resolution_result = await check_and_resolve_stuck_sessions()
            if resolution_result.get("resolved_count", 0) > 0:
                logger.info(f"Auto-resolved {resolution_result['resolved_count']} stuck session(s) before creating new session")
        except Exception as e:
            logger.debug(f"Could not auto-resolve stuck sessions: {e}")
        
        # CRITICAL: Check for agent ID collision risk in dialectic context
        # If another agent is using this ID, dialectic sessions will get confused
        # This is especially problematic because:
        # 1. Two agents with same ID will share governance state
        # 2. Dialectic sessions will mix paused/reviewer roles
        # 3. Session ownership becomes ambiguous
        from src.mcp_handlers.dialectic_reviewer import is_agent_in_active_session
        from datetime import datetime, timedelta
        
        # Check if this agent_id is already in an active dialectic session
        # This could indicate another agent is using the same ID
        try:
            already_in_session = await is_agent_in_active_session(agent_id)
            if already_in_session:
                logger.warning(
                    f"⚠️  Agent ID '{agent_id}' is already in an active dialectic session. "
                    f"This may indicate an ID collision - another agent may be using the same ID. "
                    f"Dialectic sessions may get confused about paused/reviewer roles."
                )
        except Exception as e:
            logger.debug(f"Could not check active session status: {e}")
        
        # Handle self-recovery mode
        if reviewer_mode == 'self':
            return await handle_self_recovery({
                'agent_id': agent_id,
                'api_key': api_key,
                'root_cause': arguments.get('root_cause', reason),
                'proposed_conditions': arguments.get('proposed_conditions', []),
                'reasoning': arguments.get('reasoning', 'Self-recovery requested')
            })

        # CRITICAL: Require API key authentication for dialectic reviews
        # This prevents agent ID collisions and ensures identity ownership
        # Dialectic reviews are critical operations - identity must be verified
        import asyncio
        loop = asyncio.get_running_loop()
        
        # Use existing auth function with strict enforcement for dialectic reviews
        auth_valid, auth_error = await loop.run_in_executor(
            None,
            mcp_server.require_agent_auth,
            agent_id,
            arguments,
            True  # enforce=True: require API key even for migration cases
        )
        
        if not auth_valid:
            # Enhance error message with dialectic-specific context
            if auth_error:
                error_text = auth_error.text if hasattr(auth_error, 'text') else str(auth_error)
                try:
                    import json
                    error_data = json.loads(error_text)
                    error_data["dialectic_context"] = (
                        "Dialectic reviews require authentication to prevent agent ID collisions. "
                        "Multiple agents using the same ID would cause state mixing and confusion."
                    )
                    return [TextContent(type="text", text=json.dumps(error_data, indent=2))]
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass  # Fall through to default error handling
            return [auth_error] if auth_error else [error_response("Authentication required for dialectic review")]

        # Load agent metadata to get state (non-blocking)
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, mcp_server.load_metadata)
        metadata_objects = mcp_server.agent_metadata

        # Validate metadata structure
        if not isinstance(metadata_objects, dict):
            return [error_response(
                f"Invalid metadata structure: expected dict, got {type(metadata_objects).__name__}. "
                f"Metadata value: {str(metadata_objects)[:200]}"
            )]

        if agent_id not in metadata_objects:
            return [error_response(f"Agent '{agent_id}' not found")]

        agent_meta = metadata_objects[agent_id]
        
        # Check if agent has completed work (not stuck, just waiting for input)
        # SKIP this check if discovery_id is provided - design debates don't require stuck state
        if agent_meta.status == "waiting_input" and not discovery_id:
            return [error_response(
                f"Agent '{agent_id}' has completed work and is waiting for input, not stuck.",
                recovery={
                    "action": "Agent is not stuck - they completed their response and are waiting for user input.",
                    "status": "waiting_input",
                    "last_response_at": getattr(agent_meta, 'last_response_at', None),
                    "related_tools": ["get_agent_metadata", "mark_response_complete"],
                    "workflow": [
                        "1. Check agent status with get_agent_metadata",
                        "2. If status is 'waiting_input', agent is done and waiting",
                        "3. Dialectic review is not needed - agent can resume when user responds",
                        "4. OR provide discovery_id to start a design debate (skip stuck check)"
                    ]
                }
            )]
        
        # Allow dialectic review for:
        # 1. Paused agents (circuit breaker)
        # 2. Agents in loop cooldown (stuck in loops)
        # 3. Any agent needing peer assistance
        # Note: We don't restrict to only paused agents - loops can also benefit from peer review

        # Validate agent_meta is an AgentMetadata object, not a string
        if isinstance(agent_meta, str):
            return [error_response(
                f"Invalid metadata for agent '{agent_id}': expected AgentMetadata object, got string: {agent_meta[:200]}"
            )]

        # Convert AgentMetadata objects to dicts for select_reviewer
        # This prevents "'str' object is not a mapping" errors in calculate_authority_score
        # FIXED: Ensure proper type handling - filter out strings and invalid entries
        metadata = {}
        for aid, meta_obj in metadata_objects.items():
            # Skip invalid entries (strings, None, etc.)
            if isinstance(meta_obj, str) or meta_obj is None:
                continue
            
            # Convert AgentMetadata object to dict
            if hasattr(meta_obj, 'to_dict'):
                try:
                    metadata[aid] = meta_obj.to_dict()
                except Exception as e:
                    logger.warning(f"Could not convert metadata for {aid}: {e}")
                    continue
            elif isinstance(meta_obj, dict):
                # Already a dict, use as-is
                metadata[aid] = meta_obj
            else:
                # Unknown type - skip
                logger.warning(f"Invalid metadata type for {aid}: {type(meta_obj).__name__}")
                continue

        # Load real agent state from governance monitor
        try:
            monitor = mcp_server.get_or_create_monitor(agent_id)
            metrics = monitor.get_metrics()
            risk_score = metrics.get('risk_score', 0.5)
            agent_state = {
                'risk_score': risk_score,  # Governance/operational risk
                'phi': metrics.get('phi'),  # Primary physics signal
                'verdict': metrics.get('verdict'),  # Primary governance signal
                'coherence': metrics.get('coherence', 0.5),
                'void_active': metrics.get('void_active', False),
                'E': metrics.get('E', 0.5),
                'I': metrics.get('I', 0.5),
                'S': metrics.get('S', 0.5),
                'V': metrics.get('V', 0.0)
            }
        except Exception as e:
            # Fallback to mock if monitor not available
            logger.warning(f"Could not load agent state for {agent_id}: {e}")
            agent_state = {
                'risk_score': 0.65,  # Governance/operational risk
                'coherence': 0.45,
                'void_active': False
            }

        # Select reviewer
        try:
            # Get paused agent tags for expertise matching
            paused_agent_tags = []
            paused_meta = metadata.get(agent_id)
            if paused_meta:
                if isinstance(paused_meta, dict):
                    paused_agent_tags = paused_meta.get('tags', [])
                elif hasattr(paused_meta, 'tags'):
                    paused_agent_tags = paused_meta.tags or []
            
            reviewer_id = await select_reviewer(agent_id, metadata, agent_state, paused_agent_tags=paused_agent_tags)
        except Exception as e:
            import traceback
            # SECURITY: Log full traceback internally but sanitize for client
            logger.error(f"Error selecting reviewer: {e}", exc_info=True)
            return [error_response(
                f"Error selecting reviewer: {str(e)}",
                recovery={
                    "action": "Check agent metadata and try again",
                    "related_tools": ["list_agents", "get_agent_metadata"]
                }
            )]

        # If discovery_id provided, this is a discovery dispute/correction
        discovery_owner_id = None
        if discovery_id:
            try:
                from src.knowledge_graph import get_knowledge_graph
                graph = await get_knowledge_graph()
                discovery = await graph.get_discovery(discovery_id)
                
                if not discovery:
                    return [error_response(
                        f"Discovery '{discovery_id}' not found",
                        recovery={
                            "action": "Verify discovery_id is correct",
                            "related_tools": ["search_knowledge_graph", "get_knowledge_graph"]
                        }
                    )]
                
                # Mark discovery as disputed
                await graph.update_discovery(discovery_id, {"status": "disputed"})
                
                # Set discovery owner as reviewer (not system-selected)
                discovery_owner_id = discovery.agent_id
                
                # Set dispute_type if not provided
                if not dispute_type:
                    dispute_type = "dispute"
                
                # Update reason if not provided
                if reason == 'Circuit breaker triggered':
                    reason = f"Disputing discovery '{discovery_id}': {discovery.summary[:50]}..."
                
            except Exception as e:
                logger.error(f"Error handling discovery dispute: {e}", exc_info=True)
                return [error_response(
                    f"Error processing discovery dispute: {str(e)}",
                    recovery={
                        "action": "Check discovery_id and try again",
                        "related_tools": ["search_knowledge_graph"]
                    }
                )]
        
        # Select reviewer
        # Explicit reviewer override:
        # - Allowed for peer/auto modes (ignored for reviewer_mode='self')
        # - Must not be the same as the requesting agent (avoid accidental self-review)
        # - For discovery disputes/corrections we still default to owner-as-reviewer (unless you redesign that policy),
        #   but for verification we allow peer override (or peer selection).
        if reviewer_agent_id and reviewer_mode != 'self':
            try:
                reviewer_candidate = str(reviewer_agent_id).strip()
            except Exception:
                reviewer_candidate = None
            if reviewer_candidate:
                if reviewer_candidate == agent_id:
                    return [error_response(
                        "reviewer_agent_id cannot equal agent_id unless reviewer_mode='self'",
                        recovery={
                            "action": "Provide a different reviewer_agent_id or set reviewer_mode='self'",
                            "related_tools": ["list_agents", "request_exploration_session"]
                        },
                        context={"agent_id": agent_id, "reviewer_agent_id": reviewer_candidate}
                    )]

                # Verify reviewer exists and is active-ish
                reviewer_meta_obj = metadata_objects.get(reviewer_candidate)
                if not reviewer_meta_obj:
                    return [error_response(
                        f"Reviewer agent '{reviewer_candidate}' not found",
                        recovery={"action": "Choose a reviewer_agent_id from list_agents", "related_tools": ["list_agents"]},
                        context={"reviewer_agent_id": reviewer_candidate}
                    )]
                reviewer_status = getattr(reviewer_meta_obj, "status", None)
                if reviewer_status and reviewer_status not in ['active', 'waiting_input']:
                    return [error_response(
                        f"Reviewer agent '{reviewer_candidate}' must be active (current status: {reviewer_status})",
                        recovery={"action": "Pick a different reviewer_agent_id", "related_tools": ["list_agents"]},
                        context={"reviewer_agent_id": reviewer_candidate, "status": reviewer_status}
                    )]

                # Avoid assigning reviewers already in active sessions (reduces recursion / deadlocks)
                try:
                    if await is_agent_in_active_session(reviewer_candidate):
                        return [error_response(
                            f"Reviewer agent '{reviewer_candidate}' is already in an active dialectic session",
                            recovery={"action": "Pick a different reviewer_agent_id or wait and retry", "related_tools": ["get_dialectic_session", "list_agents"]},
                            context={"reviewer_agent_id": reviewer_candidate}
                        )]
                except Exception:
                    pass

                # Only apply override for verification / general recovery; leave dispute/correction policy intact.
                if not discovery_id or dispute_type == "verification" or dispute_type is None:
                    reviewer_id = reviewer_candidate

        #
        # For discovery disputes:
        # - dispute/correction: reviewer should be the discovery owner (fastest resolution of factual ownership)
        # - verification: reviewer should be a *peer* (not the owner) to avoid self-review / circular validation
        if discovery_owner_id and dispute_type in ("dispute", "correction"):
            reviewer_id = discovery_owner_id
            # Verify discovery owner exists
            if reviewer_id not in metadata:
                return [error_response(
                    f"Discovery owner '{reviewer_id}' not found in metadata",
                    recovery={
                        "action": "Discovery owner may have been deleted or archived",
                        "related_tools": ["list_agents"]
                    }
                )]
        elif not reviewer_id:
            # Handle reviewer_mode: auto falls back to self-recovery
            if reviewer_mode == 'auto':
                return await handle_self_recovery({
                    'agent_id': agent_id,
                    'api_key': api_key,
                    'root_cause': arguments.get('root_cause', reason),
                    'proposed_conditions': arguments.get('proposed_conditions', []),
                    'reasoning': arguments.get('reasoning', 'No reviewers available - using self-recovery')
                })
            else:
                return [error_response("No healthy reviewer available. Use reviewer_mode='self' or 'auto' for self-recovery.")]

        # Create dialectic session with discovery context
        session = DialecticSession(
            paused_agent_id=agent_id,
            reviewer_agent_id=reviewer_id,
            paused_agent_state=agent_state,
            discovery_id=discovery_id,  # NEW: Link to discovery
            dispute_type=dispute_type,  # NEW: Type of dispute
            # Default 5 rounds: enough negotiation to converge, but prevents infinite loops.
            # (Also matches DialecticSession default in src/dialectic_protocol.py)
            max_synthesis_rounds=5
        )

        # Store session in memory (process-local)
        ACTIVE_SESSIONS[session.session_id] = session

        # Invalidate cache for both agents (they're now in a session)
        import time
        if agent_id in _SESSION_METADATA_CACHE:
            del _SESSION_METADATA_CACHE[agent_id]
        if reviewer_id in _SESSION_METADATA_CACHE:
            del _SESSION_METADATA_CACHE[reviewer_id]

        # Persist session to SQLite (cross-process visibility) AND JSON (backward compat)
        try:
            await sqlite_create_session(
                session_id=session.session_id,
                paused_agent_id=agent_id,
                reviewer_agent_id=reviewer_id,
                reason=reason,
                discovery_id=discovery_id,
                dispute_type=dispute_type,
                session_type="recovery",
                topic=None,
                max_synthesis_rounds=session.max_synthesis_rounds,
                synthesis_round=session.synthesis_round,
                paused_agent_state=agent_state,
            )

            # DUAL-WRITE: Create session in PostgreSQL (Phase 4 migration)
            try:
                db = get_db()
                await db.create_dialectic_session(
                    session_id=session.session_id,
                    paused_agent_id=agent_id,
                    reviewer_agent_id=reviewer_id,
                    reason=reason,
                    discovery_id=discovery_id,
                    dispute_type=dispute_type,
                    session_type="recovery",
                    topic=None,
                    max_synthesis_rounds=session.max_synthesis_rounds,
                    synthesis_round=session.synthesis_round,
                    paused_agent_state=agent_state,
                )
                logger.debug(f"Dual-write: Created dialectic session {session.session_id[:16]}... in new DB")
            except Exception as e:
                # Non-fatal: old DB still works, log and continue
                logger.warning(f"Dual-write dialectic session creation failed: {e}", exc_info=True)
        except Exception as e:
            logger.warning(f"Could not create session in SQLite (continuing with JSON): {e}")

        # Also persist to JSON for backward compat
        await save_session(session)

        # Handle auto-progress mode (smart dialectic)
        if auto_progress:
            # Auto-generate reason if not provided
            if reason == 'Circuit breaker triggered':
                if agent_state.get('attention_score', agent_state.get('risk_score', 0.5)) > 0.60:
                    reason = "Circuit breaker triggered - high risk score"
                elif agent_state.get('coherence', 0.5) < 0.40:
                    reason = "Low coherence - system instability"
                else:
                    reason = "Agent requesting peer review"
            
            # Auto-generate thesis if minimal input provided
            root_cause = arguments.get('root_cause')
            proposed_conditions = arguments.get('proposed_conditions', [])
            reasoning = arguments.get('reasoning')
            
            if not root_cause:
                root_cause = reason
            if not proposed_conditions:
                proposed_conditions = ["Monitor metrics closely", "Reduce complexity if needed"]
            if not reasoning:
                risk_val = agent_state.get('risk_score', 0.5)
                reasoning = f"Auto-generated from state: coherence={agent_state.get('coherence', 0.5):.3f}, risk_score={risk_val:.3f}"
            
            # Submit thesis automatically
            thesis_result = await handle_submit_thesis({
                'session_id': session.session_id,
                'agent_id': agent_id,
                'api_key': api_key,
                'root_cause': root_cause,
                'proposed_conditions': proposed_conditions,
                'reasoning': reasoning
            })
            
            # Return session info with auto-progress note
            result = {
                "success": True,
                "session_id": session.session_id,
                "paused_agent_id": agent_id,
                "reviewer_agent_id": reviewer_id,
                "phase": "antithesis",  # Moved to antithesis after auto-thesis
                "reason": reason,
                "auto_progressed": True,
                "thesis_submitted": True,
                "next_step": f"Reviewer '{reviewer_id}' should submit antithesis via submit_antithesis()",
                "created_at": session.created_at.isoformat(),
                "note": "Auto-progress mode: thesis submitted automatically. Reviewer should submit antithesis."
            }
        else:
            result = {
                "success": True,
                "session_id": session.session_id,
                "paused_agent_id": agent_id,
                "reviewer_agent_id": reviewer_id,
                "phase": session.phase.value,
                "reason": reason,
                "next_step": f"Agent '{agent_id}' should submit thesis via submit_thesis()",
                "created_at": session.created_at.isoformat()
            }
        
        # Add discovery context if present
        if discovery_id:
            result["discovery_id"] = discovery_id
            result["dispute_type"] = dispute_type
            result["discovery_context"] = "This dialectic session is for disputing/correcting a discovery"
        
        return success_response(result)

    except Exception as e:
        return [error_response(f"Error requesting dialectic review: {str(e)}")]


@mcp_tool("request_exploration_session", timeout=15.0)
async def handle_request_exploration_session(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Request a collaborative exploration session between two active agents.
    
    Unlike recovery sessions, exploration sessions are for:
    - Collaborative idea exploration
    - Peer review of concepts before implementation
    - Structured debates on design decisions
    - Open-ended philosophical discussions
    
    Both agents must be active (not paused/stuck). No resolution required - 
    sessions can be ongoing and iterative.
    
    Args:
        agent_id: ID of agent initiating exploration
        partner_agent_id: Optional - specific agent to explore with (if not provided, system selects)
        topic: Optional - topic/theme for exploration
        api_key: Agent's API key for authentication
    
    Returns:
        Session info with partner_id and session_id
    """
    try:
        agent_id = arguments.get('agent_id')
        partner_agent_id = arguments.get('partner_agent_id')  # Optional: specific partner
        topic = arguments.get('topic')  # Optional: exploration topic
        _maybe_fill_api_key_from_bound_identity(arguments, agent_id)
        api_key = arguments.get('api_key')
        
        if not agent_id:
            return [error_response("agent_id is required")]
        
        # Verify API key if provided
        if api_key:
            agent_meta_stored = mcp_server.agent_metadata.get(agent_id)
            if agent_meta_stored and hasattr(agent_meta_stored, 'api_key'):
                if agent_meta_stored.api_key != api_key:
                    return [error_response("Authentication failed: Invalid API key")]
        
        # Load agent metadata
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, mcp_server.load_metadata)
        metadata_objects = mcp_server.agent_metadata
        
        if agent_id not in metadata_objects:
            return [error_response(f"Agent '{agent_id}' not found")]
        
        agent_meta = metadata_objects[agent_id]
        
        # For exploration, both agents must be active (not paused/stuck)
        if agent_meta.status not in ['active', 'waiting_input']:
            return [error_response(
                f"Agent '{agent_id}' must be active for exploration (current status: {agent_meta.status})",
                recovery={
                    "action": "Only active agents can participate in exploration sessions",
                    "related_tools": ["get_agent_metadata", "request_dialectic_review"],
                    "workflow": [
                        "1. Use request_dialectic_review for recovery if agent is paused/stuck",
                        "2. Ensure agent is active before requesting exploration"
                    ]
                }
            )]
        
        # Select partner agent
        if partner_agent_id:
            # Use specified partner
            if partner_agent_id not in metadata_objects:
                return [error_response(f"Partner agent '{partner_agent_id}' not found")]
            
            partner_meta = metadata_objects[partner_agent_id]
            if partner_meta.status not in ['active', 'waiting_input']:
                return [error_response(
                    f"Partner agent '{partner_agent_id}' must be active (current status: {partner_meta.status})"
                )]
            
            reviewer_id = partner_agent_id
        else:
            # System selects partner (similar to recovery, but both agents are active)
            # Use select_reviewer but allow any active agent
            reviewer_id = await select_reviewer(
                paused_agent_id=agent_id,
                paused_agent_state={},  # Not needed for exploration
                paused_agent_tags=getattr(agent_meta, 'tags', []),
                metadata=metadata_objects,
                exclude_agent_ids=[agent_id]  # Can't explore with self
            )
            
            if not reviewer_id:
                return [error_response("No active partner agent available for exploration")]
        
        # Create exploration session
        session = DialecticSession(
            paused_agent_id=agent_id,  # Initiating agent
            reviewer_agent_id=reviewer_id,  # Exploring partner
            paused_agent_state={},  # Not needed for exploration
            session_type="exploration",
            topic=topic,
            # More rounds for exploration: allow longer open-ended iteration.
            max_synthesis_rounds=10
        )
        
        # Store session in memory (process-local)
        ACTIVE_SESSIONS[session.session_id] = session

        # Invalidate cache for both agents
        import time
        if agent_id in _SESSION_METADATA_CACHE:
            del _SESSION_METADATA_CACHE[agent_id]
        if reviewer_id in _SESSION_METADATA_CACHE:
            del _SESSION_METADATA_CACHE[reviewer_id]

        # Persist session to SQLite (cross-process visibility) AND JSON (backward compat)
        try:
            await sqlite_create_session(
                session_id=session.session_id,
                paused_agent_id=agent_id,
                reviewer_agent_id=reviewer_id,
                reason=f"exploration: {topic}" if topic else "exploration session",
                session_type="exploration",
                topic=topic,
                max_synthesis_rounds=session.max_synthesis_rounds,
                synthesis_round=session.synthesis_round,
            )

            # DUAL-WRITE: Create exploration session in PostgreSQL (Phase 4 migration)
            try:
                db = get_db()
                await db.create_dialectic_session(
                    session_id=session.session_id,
                    paused_agent_id=agent_id,
                    reviewer_agent_id=reviewer_id,
                    reason=f"exploration: {topic}" if topic else "exploration session",
                    session_type="exploration",
                    topic=topic,
                    max_synthesis_rounds=session.max_synthesis_rounds,
                    synthesis_round=session.synthesis_round,
                )
                logger.debug(f"Dual-write: Created exploration session {session.session_id[:16]}... in new DB")
            except Exception as e:
                # Non-fatal: old DB still works, log and continue
                logger.warning(f"Dual-write exploration session creation failed: {e}", exc_info=True)
        except Exception as e:
            logger.warning(f"Could not create exploration session in SQLite (continuing with JSON): {e}")

        # Also persist to JSON for backward compat
        await save_session(session)

        result = {
            "success": True,
            "session_id": session.session_id,
            "initiating_agent_id": agent_id,
            "partner_agent_id": reviewer_id,
            "phase": session.phase.value,
            "topic": topic,
            "session_type": "exploration",
            "next_step": f"Agent '{agent_id}' should submit thesis via submit_thesis() to begin exploration",
            "created_at": session.created_at.isoformat(),
            "note": "Exploration sessions are flexible - no resolution required. Agents can iterate through thesis/antithesis/synthesis cycles to explore ideas."
        }
        
        return success_response(result)
    
    except Exception as e:
        return [error_response(f"Error requesting exploration session: {str(e)}")]


@mcp_tool("submit_thesis", timeout=10.0)
async def handle_submit_thesis(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Paused agent submits thesis: "What I did, what I think happened"

    Args:
        session_id: Dialectic session ID
        agent_id: Paused agent ID
        api_key: Agent's API key
        root_cause: Agent's understanding of what caused the issue
        proposed_conditions: List of conditions for resumption
        reasoning: Natural language explanation

    Returns:
        Status with next phase
    """
    try:
        session_id = arguments.get('session_id')
        agent_id = arguments.get('agent_id')
        api_key = arguments.get('api_key', '')
        
        # QUICK WIN C: Auto-retrieve API key from bound identity if not provided
        if not api_key:
            try:
                from .identity import get_bound_agent_id, get_bound_api_key
                bound_id = get_bound_agent_id(arguments=arguments)
                if bound_id == agent_id:
                    bound_key = get_bound_api_key(arguments=arguments)
                    if bound_key:
                        api_key = bound_key
                        arguments["api_key"] = api_key
                        logger.debug(f"Auto-retrieved API key from session-bound identity for thesis submission")
            except (ImportError, AttributeError) as e:
                logger.debug(f"Could not auto-retrieve API key: {e}")
            except Exception as e:
                logger.debug(f"Error auto-retrieving API key: {e}")

        if not session_id or not agent_id:
            return [error_response(
                "session_id and agent_id are required",
                recovery={
                    "action": "Provide both session_id and agent_id",
                    "what_you_can_do": [
                        "1. Get session_id from get_dialectic_session",
                        "2. Use your agent_id (the paused agent in the session)",
                        "3. Include api_key for authentication (or bind_identity first)"
                    ],
                    "related_tools": ["get_dialectic_session", "bind_identity"]
                }
            )]

        # Get session - reload from disk if not in memory (handles server restarts)
        session = ACTIVE_SESSIONS.get(session_id)
        if not session:
            # Try loading from disk (session might have been persisted but not loaded)
            session = await load_session(session_id)
            if session:
                ACTIVE_SESSIONS[session_id] = session
            else:
                # QUICK WIN B: Improved error message
                return [error_response(
                    f"Session '{session_id}' not found",
                    recovery={
                        "action": "Session may have been auto-resolved or expired",
                        "what_happened": "The session you're looking for doesn't exist or was resolved",
                        "what_you_can_do": [
                            "1. Check if session was auto-resolved (stuck sessions resolve after 5 minutes)",
                            "2. Request a new dialectic review if you need to start over",
                            "3. Use get_dialectic_session to find active sessions",
                            "4. Check your agent status with get_agent_metadata"
                        ],
                        "related_tools": ["get_dialectic_session", "request_dialectic_review", "get_agent_metadata"],
                        "note": "Stuck sessions are now automatically resolved after 5 minutes of inactivity"
                    }
                )]

        # Create thesis message
        message = DialecticMessage(
            phase="thesis",
            agent_id=agent_id,
            timestamp=datetime.now().isoformat(),
            root_cause=arguments.get('root_cause'),
            proposed_conditions=arguments.get('proposed_conditions', []),
            reasoning=arguments.get('reasoning')
        )

        # Submit to session
        result = session.submit_thesis(message, api_key)

        if result["success"]:
            result["next_step"] = f"Reviewer '{session.reviewer_agent_id}' should submit antithesis"

            # Update SQLite (cross-process visibility)
            try:
                await sqlite_add_message(
                    session_id=session_id,
                    agent_id=agent_id,
                    message_type="thesis",
                    root_cause=arguments.get('root_cause'),
                    proposed_conditions=arguments.get('proposed_conditions', []),
                    reasoning=arguments.get('reasoning'),
                )
                await sqlite_update_phase(session_id, session.phase.value)

                # DUAL-WRITE: Add thesis message and update phase in PostgreSQL (Phase 4 migration)
                try:
                    db = get_db()
                    await db.add_dialectic_message(
                        session_id=session_id,
                        agent_id=agent_id,
                        message_type="thesis",
                        root_cause=arguments.get('root_cause'),
                        proposed_conditions=arguments.get('proposed_conditions', []),
                        reasoning=arguments.get('reasoning'),
                    )
                    await db.update_dialectic_session_phase(session_id, session.phase.value)
                    logger.debug(f"Dual-write: Added thesis message for session {session_id[:16]}... in new DB")
                except Exception as e:
                    # Non-fatal: old DB still works, log and continue
                    logger.warning(f"Dual-write thesis message failed: {e}", exc_info=True)
            except Exception as e:
                logger.warning(f"Could not update SQLite after thesis: {e}")

            # Persist to JSON (backward compat)
            try:
                await save_session(session)
            except Exception as e:
                logger.warning(f"Could not save session after thesis: {e}")

        return success_response(result)

    except Exception as e:
        return [error_response(f"Error submitting thesis: {str(e)}")]


@mcp_tool("submit_antithesis", timeout=10.0)
async def handle_submit_antithesis(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Reviewer agent submits antithesis: "What I observe, my concerns"
    
    Args:
        session_id: Dialectic session ID
        agent_id: Reviewer agent ID
        api_key: Reviewer's API key (auto-retrieved from bound identity if not provided)
        observed_metrics: Metrics observed about paused agent
        concerns: List of concerns
        reasoning: Natural language explanation
    
    Returns:
        Status with next phase
    """
    try:
        session_id = arguments.get('session_id')
        agent_id = arguments.get('agent_id')
        api_key = arguments.get('api_key', '')
        
        # QUICK WIN C: Auto-retrieve API key from bound identity if not provided
        if not api_key:
            try:
                from .identity import get_bound_agent_id, get_bound_api_key
                bound_id = get_bound_agent_id(arguments=arguments)
                if bound_id == agent_id:
                    bound_key = get_bound_api_key(arguments=arguments)
                    if bound_key:
                        api_key = bound_key
                        arguments["api_key"] = api_key
                        logger.debug(f"Auto-retrieved API key from session-bound identity for antithesis submission")
            except (ImportError, AttributeError) as e:
                logger.debug(f"Could not auto-retrieve API key: {e}")
            except Exception as e:
                logger.debug(f"Error auto-retrieving API key: {e}")

        if not session_id or not agent_id:
            return [error_response(
                "session_id and agent_id are required",
                recovery={
                    "action": "Provide both session_id and agent_id",
                    "what_you_can_do": [
                        "1. Get session_id from get_dialectic_session",
                        "2. Use your agent_id (the reviewer agent in the session)",
                        "3. Include api_key for authentication (or bind_identity first)"
                    ],
                    "related_tools": ["get_dialectic_session", "bind_identity"]
                }
            )]

        # Get session - reload from disk if not in memory (handles server restarts)
        session = ACTIVE_SESSIONS.get(session_id)
        if not session:
            # Try loading from disk (session might have been persisted but not loaded)
            session = await load_session(session_id)
            if session:
                ACTIVE_SESSIONS[session_id] = session
            else:
                # QUICK WIN B: Improved error message
                return [error_response(
                    f"Session '{session_id}' not found",
                    recovery={
                        "action": "Session may have been auto-resolved or expired",
                        "what_happened": "The session you're looking for doesn't exist or was resolved",
                        "what_you_can_do": [
                            "1. Check if session was auto-resolved (stuck sessions resolve after 5 minutes)",
                            "2. Request a new dialectic review if you need to start over",
                            "3. Use get_dialectic_session to find active sessions"
                        ],
                        "related_tools": ["get_dialectic_session", "request_dialectic_review"],
                        "note": "Stuck sessions are now automatically resolved after 5 minutes of inactivity"
                    }
                )]

        # Create antithesis message
        message = DialecticMessage(
            phase="antithesis",
            agent_id=agent_id,
            timestamp=datetime.now().isoformat(),
            observed_metrics=arguments.get('observed_metrics', {}),
            concerns=arguments.get('concerns', []),
            reasoning=arguments.get('reasoning')
        )

        # Submit to session
        result = session.submit_antithesis(message, api_key)

        if result["success"]:
            result["next_step"] = "Both agents should negotiate via submit_synthesis() until convergence"

            # Update SQLite (cross-process visibility)
            try:
                await sqlite_add_message(
                    session_id=session_id,
                    agent_id=agent_id,
                    message_type="antithesis",
                    observed_metrics=arguments.get('observed_metrics', {}),
                    concerns=arguments.get('concerns', []),
                    reasoning=arguments.get('reasoning'),
                )
                await sqlite_update_phase(session_id, session.phase.value)

                # DUAL-WRITE: Add antithesis message and update phase in PostgreSQL (Phase 4 migration)
                try:
                    db = get_db()
                    await db.add_dialectic_message(
                        session_id=session_id,
                        agent_id=agent_id,
                        message_type="antithesis",
                        observed_metrics=arguments.get('observed_metrics', {}),
                        concerns=arguments.get('concerns', []),
                        reasoning=arguments.get('reasoning'),
                    )
                    await db.update_dialectic_session_phase(session_id, session.phase.value)
                    logger.debug(f"Dual-write: Added antithesis message for session {session_id[:16]}... in new DB")
                except Exception as e:
                    # Non-fatal: old DB still works, log and continue
                    logger.warning(f"Dual-write antithesis message failed: {e}", exc_info=True)
            except Exception as e:
                logger.warning(f"Could not update SQLite after antithesis: {e}")

            # Persist to JSON (backward compat)
            try:
                await save_session(session)
            except Exception as e:
                logger.warning(f"Could not save session after antithesis: {e}")

        return success_response(result)

    except Exception as e:
        return [error_response(f"Error submitting antithesis: {str(e)}")]


@mcp_tool("submit_synthesis", timeout=15.0)
async def handle_submit_synthesis(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Either agent submits synthesis proposal during negotiation.
    
    Args:
        session_id: Dialectic session ID
        agent_id: Agent ID (either paused or reviewer)
        api_key: Agent's API key (auto-retrieved from bound identity if not provided)
        proposed_conditions: Proposed resumption conditions
        root_cause: Agreed understanding of root cause
        reasoning: Explanation of proposal
        agrees: Whether this agent agrees with current proposal (bool)
    
    Returns:
        Status with convergence info
    """
    try:
        session_id = arguments.get('session_id')
        agent_id = arguments.get('agent_id')
        api_key = arguments.get('api_key', '')
        
        # QUICK WIN C: Auto-retrieve API key from bound identity if not provided
        if not api_key:
            try:
                from .identity import get_bound_agent_id, get_bound_api_key
                bound_id = get_bound_agent_id(arguments=arguments)
                if bound_id == agent_id:
                    bound_key = get_bound_api_key(arguments=arguments)
                    if bound_key:
                        api_key = bound_key
                        arguments["api_key"] = api_key
                        logger.debug(f"Auto-retrieved API key from session-bound identity for synthesis submission")
            except (ImportError, AttributeError) as e:
                logger.debug(f"Could not auto-retrieve API key: {e}")
            except Exception as e:
                logger.debug(f"Error auto-retrieving API key: {e}")

        if not session_id or not agent_id:
            return [error_response(
                "session_id and agent_id are required",
                recovery={
                    "action": "Provide both session_id and agent_id",
                    "what_you_can_do": [
                        "1. Get session_id from get_dialectic_session",
                        "2. Use your agent_id (either paused or reviewer in the session)",
                        "3. Include api_key for authentication (or bind_identity first)"
                    ],
                    "related_tools": ["get_dialectic_session", "bind_identity"]
                }
            )]

        # Get session - always reload from disk to ensure latest state (handles stale memory)
        # This ensures we have the latest phase and transcript after server restarts or concurrent updates
        session = await load_session(session_id)
        if session:
            ACTIVE_SESSIONS[session_id] = session
        else:
            # Fallback to memory if file doesn't exist
            session = ACTIVE_SESSIONS.get(session_id)
            if not session:
                # QUICK WIN B: Improved error message
                return [error_response(
                    f"Session '{session_id}' not found",
                    recovery={
                        "action": "Session may have been auto-resolved or expired",
                        "what_happened": "The session you're looking for doesn't exist or was resolved",
                        "what_you_can_do": [
                            "1. Check if session was auto-resolved (stuck sessions resolve after 5 minutes)",
                            "2. Request a new dialectic review if you need to start over",
                            "3. Use get_dialectic_session to find active sessions",
                            "4. Check timing - synthesis submissions may have timing constraints"
                        ],
                        "related_tools": ["get_dialectic_session", "request_dialectic_review"],
                        "note": "Stuck sessions are now automatically resolved after 5 minutes of inactivity. Timing constraints may cause rapid submissions to fail - try again after a brief pause."
                    }
                )]

        # Create synthesis message
        message = DialecticMessage(
            phase="synthesis",
            agent_id=agent_id,
            timestamp=datetime.now().isoformat(),
            proposed_conditions=arguments.get('proposed_conditions', []),
            root_cause=arguments.get('root_cause'),
            reasoning=arguments.get('reasoning'),
            agrees=arguments.get('agrees', False)
        )

        # Submit to session
        result = session.submit_synthesis(message, api_key)

        # Save session after synthesis submission (even if not converged yet)
        if result.get("success"):
            # Update SQLite (cross-process visibility)
            try:
                await sqlite_add_message(
                    session_id=session_id,
                    agent_id=agent_id,
                    message_type="synthesis",
                    root_cause=arguments.get('root_cause'),
                    proposed_conditions=arguments.get('proposed_conditions', []),
                    reasoning=arguments.get('reasoning'),
                    agrees=arguments.get('agrees', False),
                )
                await sqlite_update_phase(session_id, session.phase.value)

                # DUAL-WRITE: Add synthesis message and update phase in PostgreSQL (Phase 4 migration)
                try:
                    db = get_db()
                    await db.add_dialectic_message(
                        session_id=session_id,
                        agent_id=agent_id,
                        message_type="synthesis",
                        root_cause=arguments.get('root_cause'),
                        proposed_conditions=arguments.get('proposed_conditions', []),
                        reasoning=arguments.get('reasoning'),
                        agrees=arguments.get('agrees', False)
                    )
                    await db.update_dialectic_session_phase(session_id, session.phase.value)
                    logger.debug(f"Dual-write: Added synthesis message for session {session_id[:16]}... in new DB")
                except Exception as e:
                    # Non-fatal: old DB still works, log and continue
                    logger.warning(f"Dual-write synthesis message failed: {e}", exc_info=True)
            except Exception as e:
                logger.warning(f"Could not update SQLite after synthesis: {e}")

            # Persist to JSON (backward compat)
            try:
                await save_session(session)
            except Exception as e:
                logger.warning(f"Could not save session after synthesis: {e}")

        # If converged, proceed to finalize
        if result.get("success") and result.get("converged"):
            # Generate real signatures from API keys
            paused_meta = mcp_server.agent_metadata.get(session.paused_agent_id)
            reviewer_meta = mcp_server.agent_metadata.get(session.reviewer_agent_id)
            
            # Get API keys for signature generation
            api_key_a = paused_meta.api_key if paused_meta and paused_meta.api_key else api_key
            api_key_b = reviewer_meta.api_key if reviewer_meta and reviewer_meta.api_key else ""
            
            # Generate signatures from most recent agreed messages
            synthesis_messages = [msg for msg in session.transcript if msg.phase == "synthesis" and msg.agrees]
            if synthesis_messages:
                last_msg = synthesis_messages[-1]
                signature_a = last_msg.sign(api_key_a) if api_key_a else ""
                signature_b = last_msg.sign(api_key_b) if api_key_b else ""
            else:
                # Fallback: use session hash
                import hashlib
                session_data = f"{session.session_id}:{api_key_a}"
                signature_a = hashlib.sha256(session_data.encode()).hexdigest()[:32]
                session_data = f"{session.session_id}:{api_key_b}"
                signature_b = hashlib.sha256(session_data.encode()).hexdigest()[:32] if api_key_b else ""

            resolution = session.finalize_resolution(signature_a, signature_b)

            # Check hard limits
            is_safe, violation = session.check_hard_limits(resolution)

            if not is_safe:
                result["action"] = "block"
                result["reason"] = f"Safety violation: {violation}"
                # Resolve in SQLite with failed status
                try:
                    await sqlite_resolve_session(
                        session_id=session_id,
                        resolution={"action": "block", "reason": violation},
                        status="failed"
                    )

                    # DUAL-WRITE: Resolve session as failed in PostgreSQL (Phase 4 migration)
                    try:
                        db = get_db()
                        await db.resolve_dialectic_session(
                            session_id=session_id,
                            resolution={"action": "block", "reason": violation},
                            status="failed"
                        )
                        logger.debug(f"Dual-write: Resolved session {session_id[:16]}... as failed in new DB")
                    except Exception as e:
                        # Non-fatal: old DB still works, log and continue
                        logger.warning(f"Dual-write resolve session (failed) failed: {e}", exc_info=True)
                except Exception as e:
                    logger.warning(f"Could not resolve session in SQLite: {e}")
                # Save session to JSON (backward compat)
                await save_session(session)
            else:
                result["action"] = "resume"
                result["resolution"] = resolution.to_dict()
                
                # Actually execute the resolution: resume agent with conditions
                try:
                    execution_result = await execute_resolution(session, resolution)
                    result["execution"] = execution_result
                    result["next_step"] = "Agent resumed successfully with agreed conditions"
                    
                    # Invalidate cache for both agents (session resolved)
                    import time
                    if session.paused_agent_id in _SESSION_METADATA_CACHE:
                        del _SESSION_METADATA_CACHE[session.paused_agent_id]
                    if session.reviewer_agent_id in _SESSION_METADATA_CACHE:
                        del _SESSION_METADATA_CACHE[session.reviewer_agent_id]
                    
                    # AUTOMATIC CALIBRATION: Update calibration from dialectic convergence
                    # For verification-type sessions, use peer agreement as proxy for correctness
                    # (with lower weight than human ground truth - peer verification is uncertainty detection, not ground truth)
                    if session.dispute_type == "verification":
                        try:
                            updated = await update_calibration_from_dialectic(session, resolution)
                            if updated:
                                result["calibration_updated"] = True
                                result["calibration_note"] = "Peer verification used for calibration (uncertainty detection proxy)"
                        except Exception as e:
                            # Don't fail the resolution if calibration update fails
                            logger.warning(f"Could not update calibration from dialectic: {e}")
                            result["calibration_error"] = str(e)
                except Exception as e:
                    result["execution_error"] = str(e)
                    result["next_step"] = f"Failed to execute resolution: {e}. Manual intervention may be needed."

                # Resolve in SQLite (cross-process visibility)
                try:
                    await sqlite_resolve_session(
                        session_id=session_id,
                        resolution=resolution.to_dict(),
                        status="resolved"
                    )

                    # DUAL-WRITE: Resolve session in PostgreSQL (Phase 4 migration)
                    try:
                        db = get_db()
                        await db.resolve_dialectic_session(
                            session_id=session_id,
                            resolution=resolution.to_dict(),
                            status="resolved"
                        )
                        logger.debug(f"Dual-write: Resolved session {session_id[:16]}... in new DB")
                    except Exception as e:
                        # Non-fatal: old DB still works, log and continue
                        logger.warning(f"Dual-write resolve session failed: {e}", exc_info=True)
                except Exception as e:
                    logger.warning(f"Could not resolve session in SQLite: {e}")

                # Save session to JSON (backward compat)
                await save_session(session)

        elif not result.get("success"):
            # Max rounds exceeded - SELF-GOVERNANCE: make conservative autonomous decision
            # Instead of waiting for human intervention, apply default safe behavior:
            # 1. Default to conservative option (keep current state)
            # 2. Log disagreement for learning
            # 3. Allow retry after cooldown
            #
            # Future enhancement: Implement quorum mechanism for high-stakes decisions
            # - Require 3+ reviewers for high-risk decisions (risk_score > 0.60, void_active)
            # - Supermajority requirement: 2/3 must agree
            # - Weighted voting by reviewer authority score
            # - See docs/DIALECTIC_FUTURE_DEFENSES.md for requirements
            
            # SELF-GOVERNANCE: Default to conservative outcome (don't resume if peers can't agree)
            result["autonomous_resolution"] = True
            result["resolution_type"] = "conservative_default"
            result["next_step"] = (
                "Peers could not reach consensus. Applying conservative default: "
                "maintaining current state. Agent may retry after 1 hour cooldown."
            )
            result["cooldown_until"] = (datetime.now() + timedelta(hours=1)).isoformat()
            result["reason"] = "Self-governance: when peers disagree, system defaults to caution"
            
            # Log for future learning (this disagreement is useful calibration signal)
            logger.info(
                f"Dialectic {session_id} resolved autonomously (no consensus): "
                f"conservative default applied, cooldown until {result['cooldown_until']}"
            )
            
            # AUTOMATIC CALIBRATION: Update calibration from dialectic disagreement
            # Disagreement indicates overconfidence - lower calibration
            if session.dispute_type == "verification":
                try:
                    updated = await update_calibration_from_dialectic_disagreement(session, disagreement_severity=1.0)
                    if updated:
                        result["calibration_updated"] = True
                        result["calibration_note"] = "Disagreement detected - confidence was too high (overconfidence penalty)"
                except Exception as e:
                    # Don't fail the escalation if calibration update fails
                    logger.warning(f"Could not update calibration from disagreement: {e}")
                    result["calibration_error"] = str(e)
        
        # Also check for explicit disagreement patterns (even if session hasn't escalated yet)
        # This catches cases where agents explicitly disagree but haven't hit max rounds
        elif result.get("success") and not result.get("converged"):
            # Session is still active but not converged - check for disagreement patterns
            synthesis_messages = [msg for msg in session.transcript if msg.phase == "synthesis"]
            if synthesis_messages:
                # Check if we have recent disagreement
                recent_messages = synthesis_messages[-2:]  # Last 2 messages
                disagreed_count = sum(1 for msg in recent_messages if msg.agrees is False)
                
                # If both recent messages show disagreement, that's a strong signal
                if disagreed_count >= 2 and session.dispute_type == "verification":
                    try:
                        # Moderate severity for ongoing disagreement
                        updated = await update_calibration_from_dialectic_disagreement(session, disagreement_severity=0.6)
                        if updated:
                            result["calibration_updated"] = True
                            result["calibration_note"] = "Ongoing disagreement detected - confidence may be too high"
                    except Exception as e:
                        # Don't fail if calibration update fails
                        logger.warning(f"Could not update calibration from ongoing disagreement: {e}")

        return success_response(result)

    except Exception as e:
        return [error_response(f"Error submitting synthesis: {str(e)}")]


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
    Get current state of a dialectic session.
    
    Can find sessions by session_id OR by agent_id (paused or reviewer).
    Automatically checks for timeouts and stuck reviewers.

    Args:
        session_id: Dialectic session ID (optional if agent_id provided)
        agent_id: Agent ID to find sessions for (optional if session_id provided)
                 Finds sessions where agent is paused_agent_id or reviewer_agent_id
        check_timeout: Whether to check for timeouts (default: True)

    Returns:
        Full session state including transcript, or list of sessions if agent_id provided
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
                                "1. Request a new dialectic review if you as the paused agent",
                                "2. Use direct_resume_if_safe if you believe you can proceed safely",
                                "3. Check your agent status with get_agent_metadata",
                                "4. Sessions now auto-resolve if inactive >5 minutes"
                            ],
                            "related_tools": ["request_dialectic_review", "direct_resume_if_safe", "get_agent_metadata"],
                            "note": "Stuck sessions are now automatically resolved after 5 minutes of inactivity"
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
                                "1. Request a new dialectic review with a different reviewer",
                                "2. Use direct_resume_if_safe if you believe you can proceed safely",
                                "3. Check reviewer status with get_agent_metadata",
                                "4. Try reviewer_mode='self' for self-assisted recovery"
                            ],
                            "related_tools": ["request_dialectic_review", "direct_resume_if_safe", "get_agent_metadata"],
                            "prevention": "Sessions now auto-resolve if inactive >5 minutes to prevent this issue"
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
                    f"No active dialectic sessions found for agent '{agent_id}'",
                    recovery={
                        "action": "No sessions found. If agent is paused, use request_dialectic_review to start one.",
                        "related_tools": ["request_dialectic_review", "get_agent_metadata"],
                        "workflow": [
                            "1. Check agent status with get_agent_metadata",
                            "2. If paused, call request_dialectic_review to start recovery",
                            "3. Use returned session_id to track progress"
                        ]
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
                "action": "Provide either session_id (from request_dialectic_review) or agent_id to find sessions",
                "related_tools": ["request_dialectic_review", "list_agents"]
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
                "related_tools": ["list_agents", "request_dialectic_review"]
            }
        )]


@mcp_tool("nudge_dialectic_session", timeout=5.0, rate_limit_exempt=True)
async def handle_nudge_dialectic_session(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Nudge a dialectic/exploration session that appears stuck.

    Returns next actor + suggested tool call + idle time. Optionally writes an audit event.
    """
    try:
        session_id = (arguments.get("session_id") or "").strip()
        if not session_id:
            return [error_response("session_id is required")]

        post = bool(arguments.get("post", False))
        note = arguments.get("note")

        # Prefer SQLite session as cross-process source of truth
        session = await sqlite_get_session(session_id)
        if not session:
            # Fallback to in-memory / JSON session storage (legacy)
            try:
                loaded = await load_session(session_id)
                if loaded:
                    session = {
                        "session_id": loaded.session_id,
                        "paused_agent_id": loaded.paused_agent_id,
                        "reviewer_agent_id": loaded.reviewer_agent_id,
                        "phase": loaded.phase.value if hasattr(loaded, "phase") else None,
                        "created_at": loaded.created_at.isoformat() if getattr(loaded, "created_at", None) else None,
                        "updated_at": loaded.get_last_update_timestamp() if hasattr(loaded, "get_last_update_timestamp") else None,
                        "session_type": getattr(loaded, "session_type", None),
                        "topic": getattr(loaded, "topic", None),
                    }
            except Exception:
                session = None

        if not session:
            return [error_response(
                f"Session '{session_id}' not found",
                recovery={
                    "action": "Check session_id or use get_dialectic_session(agent_id=...) to discover sessions",
                    "related_tools": ["get_dialectic_session", "request_dialectic_review"],
                },
            )]

        phase = session.get("phase")
        paused_agent_id = session.get("paused_agent_id")
        reviewer_agent_id = session.get("reviewer_agent_id")
        session_type = session.get("session_type")
        topic = session.get("topic")
        created_at = session.get("created_at")
        updated_at = session.get("updated_at") or created_at

        from datetime import datetime, timezone
        idle_seconds = None
        last_activity_at = None
        try:
            if updated_at:
                ts = str(updated_at).replace("Z", "+00:00")
                last_dt = datetime.fromisoformat(ts)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                last_activity_at = last_dt.isoformat()
                idle_seconds = (datetime.now(timezone.utc) - last_dt.astimezone(timezone.utc)).total_seconds()
        except Exception:
            pass

        next_actor = None
        next_tool = None
        if phase == "thesis":
            next_actor = paused_agent_id
            next_tool = "submit_thesis"
        elif phase == "antithesis":
            next_actor = reviewer_agent_id
            next_tool = "submit_antithesis"
        elif phase == "synthesis":
            next_actor = "either"
            next_tool = "submit_synthesis"
        elif phase == "resolved":
            next_actor = None
            next_tool = None

        suggested_call = None
        if next_tool:
            suggested_call = {"name": next_tool, "arguments": {"session_id": session_id}}

        if post:
            try:
                from src.audit_log import audit_logger
                audit_logger.log_dialectic_nudge(
                    agent_id=str(arguments.get("agent_id") or "system"),
                    session_id=session_id,
                    phase=str(phase),
                    next_actor=str(next_actor) if next_actor else None,
                    idle_seconds=idle_seconds,
                    details={"note": note, "session_type": session_type, "topic": topic}
                )
            except Exception:
                pass

        return success_response({
            "success": True,
            "session_id": session_id,
            "session_type": session_type,
            "topic": topic,
            "phase": phase,
            "paused_agent_id": paused_agent_id,
            "reviewer_agent_id": reviewer_agent_id,
            "last_activity_at": last_activity_at,
            "idle_seconds": idle_seconds,
            "next_actor": next_actor,
            "next_tool": next_tool,
            "suggested_call": suggested_call,
            "posted_audit_event": bool(post),
            "note": "This tool does not force progress; it only reports who should act next and optionally records an audit event."
        })
    except Exception as e:
        return [error_response(f"Error nudging session: {str(e)}")]


async def generate_system_antithesis(agent_id: str, metrics: Dict[str, Any], thesis: DialecticMessage) -> DialecticMessage:
    """
    Generate system antithesis based on agent metrics and thesis.
    
    Used for self-recovery when no reviewers are available.
    
    Args:
        agent_id: Agent ID (for message)
        metrics: Current governance metrics
        thesis: Agent's thesis message
    
    Returns:
        System-generated antithesis message
    """
    coherence = metrics.get('coherence', 0.5)
    risk_score_value = metrics.get('risk_score', 0.5)
    void_active = metrics.get('void_active', False)
    
    # Generate concerns based on metrics
    concerns = []
    observed_metrics = {
        'coherence': coherence,
        'risk_score': risk_score_value,  # Governance/operational risk
        'void_active': void_active
    }
    
    if coherence < 0.50:
        concerns.append(f"Coherence is low ({coherence:.3f}) - may indicate internal inconsistency")
    
    if risk_score_value > 0.50:
        concerns.append(f"Risk score is elevated ({risk_score_value:.3f}) - requires careful monitoring")
    
    if void_active:
        concerns.append("Void events are active - system instability detected")
    
    # Analyze proposed conditions
    proposed_conditions = thesis.proposed_conditions or []
    if not proposed_conditions:
        concerns.append("No specific conditions proposed - recovery plan may be vague")
    
    # Generate reasoning
    reasoning_parts = [
        f"System analysis: coherence={coherence:.3f}, risk_score={risk_score_value:.3f}"
    ]
    
    if concerns:
        reasoning_parts.append(f"Concerns: {', '.join(concerns)}")
    else:
        reasoning_parts.append("Metrics appear stable - recovery may be safe")
    
    reasoning = ". ".join(reasoning_parts)
    
    return DialecticMessage(
        phase="antithesis",
        agent_id="system",
        timestamp=datetime.now().isoformat(),
        observed_metrics=observed_metrics,
        concerns=concerns,
        reasoning=reasoning
    )


# Internal function for self-recovery (called by request_dialectic_review when reviewer_mode='self')
async def handle_self_recovery(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Allow agent to recover without reviewer (for when no reviewers available).
    
    Flow:
    1. Agent submits thesis
    2. System generates antithesis based on metrics
    3. Agent submits synthesis (auto-merged)
    4. Auto-resolve if safe
    
    Args:
        agent_id: Agent ID to recover
        api_key: Agent's API key
        root_cause: Agent's understanding of what happened
        proposed_conditions: Conditions for resumption
        reasoning: Explanation
    
    Returns:
        Recovery result with system-generated antithesis
    """
    try:
        agent_id = arguments.get('agent_id')
        api_key = arguments.get('api_key')
        
        if not agent_id or not api_key:
            return [error_response("agent_id and api_key are required")]
        
        # Verify API key (non-blocking)
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, mcp_server.load_metadata)
        meta = mcp_server.agent_metadata.get(agent_id)
        if not meta:
            return [error_response(f"Agent '{agent_id}' not found")]
        
        if meta.api_key != api_key:
            return [error_response("Authentication failed: Invalid API key")]
        
        # Get current metrics
        try:
            monitor = mcp_server.get_or_create_monitor(agent_id)
            metrics = monitor.get_metrics()
            agent_state = {
                'coherence': float(monitor.state.coherence),
                'risk_score': float(metrics.get('mean_risk', 0.5)),
                'void_active': bool(monitor.state.void_active),
                'E': float(monitor.state.E),
                'I': float(monitor.state.I),
                'S': float(monitor.state.S),
                'V': float(monitor.state.V)
            }
        except Exception as e:
            return [error_response(f"Error getting governance metrics: {str(e)}")]
        
        # Create thesis message
        thesis = DialecticMessage(
            phase="thesis",
            agent_id=agent_id,
            timestamp=datetime.now().isoformat(),
            root_cause=arguments.get('root_cause', 'Agent requesting self-recovery'),
            proposed_conditions=arguments.get('proposed_conditions', []),
            reasoning=arguments.get('reasoning', 'No reviewers available - using self-recovery')
        )
        
        # Generate system antithesis
        system_antithesis = await generate_system_antithesis(agent_id, agent_state, thesis)
        
        # Check if safe to resume (same checks as direct_resume_if_safe)
        coherence = agent_state['coherence']
        risk_score = agent_state.get('risk_score', 0.5)
        void_active = agent_state['void_active']
        status = meta.status
        
        safety_checks = {
            "coherence_ok": coherence > 0.40,
            "risk_ok": risk_score < 0.60,  # Governance/operational risk check
            "no_void": not void_active,
            "status_ok": status in ["paused", "waiting_input", "moderate"]
        }
        
        if not all(safety_checks.values()):
            failed_checks = [k for k, v in safety_checks.items() if not v]
            return [error_response(
                f"Not safe to resume via self-recovery. Failed checks: {failed_checks}. "
                f"Metrics: coherence={coherence:.3f}, risk_score={risk_score:.3f}, "
                f"void_active={void_active}, status={status}. "
                f"System antithesis: {system_antithesis.reasoning}. "
                f"Use request_dialectic_review for peer-assisted recovery."
            )]
        
        # Auto-generate synthesis (merge thesis and system antithesis)
        merged_conditions = list(set(thesis.proposed_conditions or []))
        if system_antithesis.concerns:
            # Add monitoring conditions based on concerns
            if any('coherence' in c.lower() for c in system_antithesis.concerns):
                merged_conditions.append("Monitor coherence closely")
            if any('risk' in c.lower() for c in system_antithesis.concerns):
                merged_conditions.append("Monitor risk score")
        
        merged_root_cause = thesis.root_cause or "Self-recovery requested"
        merged_reasoning = f"Agent: {thesis.reasoning or 'No reasoning provided'}. System: {system_antithesis.reasoning}"
        
        # Resume agent
        meta.status = "active"
        meta.paused_at = None
        meta.add_lifecycle_event("resumed", f"Self-recovery: {merged_root_cause}. Conditions: {merged_conditions}")
        
        # Schedule batched metadata save (non-blocking)
        import asyncio
        loop = asyncio.get_running_loop()
        await mcp_server.schedule_metadata_save(force=False)
        
        return success_response({
            "success": True,
            "message": "Agent resumed via self-recovery",
            "agent_id": agent_id,
            "action": "resumed",
            "thesis": {
                "root_cause": thesis.root_cause,
                "proposed_conditions": thesis.proposed_conditions,
                "reasoning": thesis.reasoning
            },
            "system_antithesis": {
                "concerns": system_antithesis.concerns,
                "observed_metrics": system_antithesis.observed_metrics,
                "reasoning": system_antithesis.reasoning
            },
            "merged_resolution": {
                "conditions": merged_conditions,
                "root_cause": merged_root_cause,
                "reasoning": merged_reasoning
            },
            "metrics": agent_state,
            "note": "Self-recovery completed. No peer review was performed. Use request_dialectic_review for complex cases."
        })
    
    except Exception as e:
        import traceback
        # SECURITY: Log full traceback internally but sanitize for client
        logger.error(f"Error in self-recovery: {e}", exc_info=True)
        return [error_response(
            f"Error in self-recovery: {str(e)}",
            recovery={
                "action": "Check agent state and parameters, then retry",
                "related_tools": ["get_governance_metrics", "direct_resume_if_safe"]
            }
        )]


# Tool wrapper for backward compatibility (deprecated)
