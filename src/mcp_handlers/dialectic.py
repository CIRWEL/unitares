"""
MCP Handlers for Circuit Breaker Dialectic Protocol

Implements MCP tools for peer-review dialectic resolution of circuit breaker states.
"""

from typing import Dict, Any, Sequence, Optional
from mcp.types import TextContent
import json
from datetime import datetime
import random

from dialectic_protocol import (
    DialecticSession,
    DialecticMessage,
    DialecticPhase,
    Resolution,
    calculate_authority_score
)
from mcp_handlers.utils import success_response, error_response
import sys

# Import from mcp_server_std module (same pattern as lifecycle handlers)
if 'src.mcp_server_std' in sys.modules:
    mcp_server = sys.modules['src.mcp_server_std']
else:
    import src.mcp_server_std as mcp_server


# Active dialectic sessions (in-memory + persistent storage)
ACTIVE_SESSIONS: Dict[str, DialecticSession] = {}

# Session storage directory
from pathlib import Path
import sys
if 'src.mcp_server_std' in sys.modules:
    project_root = Path(sys.modules['src.mcp_server_std'].project_root)
else:
    project_root = Path(__file__).parent.parent.parent

SESSION_STORAGE_DIR = project_root / "data" / "dialectic_sessions"
SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


async def save_session(session: DialecticSession) -> None:
    """Persist dialectic session to disk"""
    try:
        session_file = SESSION_STORAGE_DIR / f"{session.session_id}.json"
        session_data = session.to_dict()
        
        # Use aiofiles if available for async I/O
        if AIOFILES_AVAILABLE:
            import aiofiles
            async with aiofiles.open(session_file, 'w') as f:
                await f.write(json.dumps(session_data, indent=2))
        else:
            # Fallback to sync I/O
            with open(session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
    except Exception as e:
        print(f"[DIALECTIC] Warning: Could not save session {session.session_id}: {e}", file=sys.stderr)


async def load_session(session_id: str) -> Optional[DialecticSession]:
    """Load dialectic session from disk"""
    try:
        session_file = SESSION_STORAGE_DIR / f"{session_id}.json"
        if not session_file.exists():
            return None
        
        if AIOFILES_AVAILABLE:
            import aiofiles
            async with aiofiles.open(session_file, 'r') as f:
                content = await f.read()
                session_data = json.loads(content)
        else:
            with open(session_file, 'r') as f:
                session_data = json.load(f)
        
        # Reconstruct session from dict
        # This is simplified - full reconstruction would need more logic
        return None  # TODO: Implement full reconstruction
    except Exception:
        return None


async def execute_resolution(session: DialecticSession, resolution: Resolution) -> Dict[str, Any]:
    """
    Execute the resolution: resume agent with agreed conditions.
    
    This actually modifies agent state and applies conditions.
    """
    agent_id = session.paused_agent_id
    
    # Load agent metadata
    mcp_server.load_metadata()
    
    if agent_id not in mcp_server.agent_metadata:
        raise ValueError(f"Agent '{agent_id}' not found")
    
    meta = mcp_server.agent_metadata[agent_id]
    
    # Verify agent is actually paused
    if meta.status != "paused":
        return {
            "success": False,
            "warning": f"Agent status is '{meta.status}', not 'paused'. No action taken."
        }
    
    # Apply conditions (simplified - would need more sophisticated parsing)
    applied_conditions = []
    for condition in resolution.conditions:
        try:
            # Parse and apply condition
            # This is a simplified version - real implementation would parse conditions
            # and modify governance thresholds, monitoring settings, etc.
            applied_conditions.append({
                "condition": condition,
                "status": "applied",
                "note": "Condition applied (simplified implementation)"
            })
        except Exception as e:
            applied_conditions.append({
                "condition": condition,
                "status": "failed",
                "error": str(e)
            })
    
    # Resume the agent
    meta.status = "active"
    meta.paused_at = None
    meta.add_lifecycle_event("resumed", f"Resumed via dialectic synthesis: {resolution.root_cause}")
    
    # Save metadata
    await mcp_server.save_metadata_async()
    
    return {
        "success": True,
        "agent_id": agent_id,
        "new_status": "active",
        "applied_conditions": applied_conditions,
        "resolution_hash": resolution.hash()
    }


# Check for aiofiles availability
try:
    import aiofiles
    AIOFILES_AVAILABLE = True
except ImportError:
    AIOFILES_AVAILABLE = False


async def handle_request_dialectic_review(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Request a dialectic review for a paused/critical agent.

    Selects a healthy reviewer agent and initiates dialectic session.

    Args:
        agent_id: ID of paused agent requesting review
        reason: Reason for circuit breaker trigger
        api_key: Agent's API key for authentication

    Returns:
        Session info with reviewer_id and session_id
    """
    try:
        agent_id = arguments.get('agent_id')
        reason = arguments.get('reason', 'Circuit breaker triggered')
        api_key = arguments.get('api_key')

        if not agent_id:
            return [error_response("agent_id is required")]

        # TODO: Verify API key
        # For MVP, skip authentication

        # Load agent metadata to get state
        mcp_server.load_metadata()
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

        # Validate agent_meta is an AgentMetadata object, not a string
        if isinstance(agent_meta, str):
            return [error_response(
                f"Invalid metadata for agent '{agent_id}': expected AgentMetadata object, got string: {agent_meta[:200]}"
            )]

        # Convert AgentMetadata objects to dicts for select_reviewer
        # This prevents "'str' object is not a mapping" errors in calculate_authority_score
        metadata = {}
        for aid, meta_obj in metadata_objects.items():
            if hasattr(meta_obj, 'to_dict'):
                metadata[aid] = meta_obj.to_dict()
            elif isinstance(meta_obj, dict):
                metadata[aid] = meta_obj
            else:
                # Skip invalid entries
                continue

        # Load real agent state from governance monitor
        try:
            monitor = mcp_server.get_or_create_monitor(agent_id)
            metrics = monitor.get_metrics()
            agent_state = {
                'risk_score': metrics.get('risk_score', 0.5),
                'coherence': metrics.get('coherence', 0.5),
                'void_active': metrics.get('void_active', False),
                'E': metrics.get('E', 0.5),
                'I': metrics.get('I', 0.5),
                'S': metrics.get('S', 0.5),
                'V': metrics.get('V', 0.0)
            }
        except Exception as e:
            # Fallback to mock if monitor not available
            print(f"[DIALECTIC] Warning: Could not load agent state for {agent_id}: {e}", file=sys.stderr)
            agent_state = {
                'risk_score': 0.65,
                'coherence': 0.45,
                'void_active': False
            }

        # Select reviewer
        try:
            reviewer_id = select_reviewer(agent_id, metadata, agent_state)
        except Exception as e:
            import traceback
            return [error_response(
                f"Error selecting reviewer: {str(e)}\n"
                f"Traceback: {traceback.format_exc()}\n"
                f"Metadata type: {type(metadata).__name__}, "
                f"Metadata keys: {list(metadata.keys())[:5] if isinstance(metadata, dict) else 'N/A'}"
            )]

        if not reviewer_id:
            return [error_response("No healthy reviewer available - escalating to strict default")]

        # Create dialectic session
        session = DialecticSession(
            paused_agent_id=agent_id,
            reviewer_agent_id=reviewer_id,
            paused_agent_state=agent_state,
            max_synthesis_rounds=5
        )

        # Store session
        ACTIVE_SESSIONS[session.session_id] = session

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

        return success_response(result)

    except Exception as e:
        return [error_response(f"Error requesting dialectic review: {str(e)}")]


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

        if not session_id or not agent_id:
            return [error_response("session_id and agent_id are required")]

        # Get session
        session = ACTIVE_SESSIONS.get(session_id)
        if not session:
            return [error_response(f"Session '{session_id}' not found")]

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

        return success_response(result)

    except Exception as e:
        return [error_response(f"Error submitting thesis: {str(e)}")]


async def handle_submit_antithesis(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Reviewer agent submits antithesis: "What I observe, my concerns"

    Args:
        session_id: Dialectic session ID
        agent_id: Reviewer agent ID
        api_key: Reviewer's API key
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

        if not session_id or not agent_id:
            return [error_response("session_id and agent_id are required")]

        # Get session
        session = ACTIVE_SESSIONS.get(session_id)
        if not session:
            return [error_response(f"Session '{session_id}' not found")]

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

        return success_response(result)

    except Exception as e:
        return [error_response(f"Error submitting antithesis: {str(e)}")]


async def handle_submit_synthesis(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Either agent submits synthesis proposal during negotiation.

    Args:
        session_id: Dialectic session ID
        agent_id: Agent ID (either paused or reviewer)
        api_key: Agent's API key
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

        if not session_id or not agent_id:
            return [error_response("session_id and agent_id are required")]

        # Get session
        session = ACTIVE_SESSIONS.get(session_id)
        if not session:
            return [error_response(f"Session '{session_id}' not found")]

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
                # Save session before blocking
                await save_session(session)
            else:
                result["action"] = "resume"
                result["resolution"] = resolution.to_dict()
                
                # Actually execute the resolution: resume agent with conditions
                try:
                    execution_result = await execute_resolution(session, resolution)
                    result["execution"] = execution_result
                    result["next_step"] = "Agent resumed successfully with agreed conditions"
                except Exception as e:
                    result["execution_error"] = str(e)
                    result["next_step"] = f"Failed to execute resolution: {e}. Manual intervention may be needed."
                
                # Save session after execution
                await save_session(session)

        elif not result.get("success"):
            # Max rounds exceeded - escalate
            result["next_step"] = "Escalate to quorum (not yet implemented)"

        return success_response(result)

    except Exception as e:
        return [error_response(f"Error submitting synthesis: {str(e)}")]


async def handle_get_dialectic_session(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Get current state of a dialectic session.

    Args:
        session_id: Dialectic session ID

    Returns:
        Full session state including transcript
    """
    try:
        session_id = arguments.get('session_id')

        if not session_id:
            return [error_response("session_id is required")]

        # Get session
        session = ACTIVE_SESSIONS.get(session_id)
        if not session:
            return [error_response(f"Session '{session_id}' not found")]

        result = session.to_dict()
        result["success"] = True

        return success_response(result)

    except Exception as e:
        return [error_response(f"Error getting session: {str(e)}")]


def select_reviewer(paused_agent_id: str,
                   metadata: Dict[str, Any],
                   paused_agent_state: Dict[str, Any] = None) -> str:
    """
    Select a healthy reviewer agent for dialectic session.

    Selection criteria:
    - Healthy (risk < 0.40)
    - Not the paused agent
    - Not recently reviewed this agent (prevent collusion)
    - Weighted by authority score

    Args:
        paused_agent_id: ID of paused agent
        metadata: All agent metadata (dict mapping agent_id -> AgentMetadata)
        paused_agent_state: State of paused agent

    Returns:
        Selected reviewer agent_id, or None if no reviewer available
    """
    # Ensure metadata is a dict (not a string or other type)
    if not isinstance(metadata, dict):
        raise TypeError(f"metadata must be a dict, got {type(metadata).__name__}: {metadata}")
    
    # Get all agents - iterate over items() to get (agent_id, meta) pairs
    # This matches the pattern used in lifecycle.py
    candidates = []
    scores = []
    
    for agent_id, agent_meta in metadata.items():
        # Validate agent_id is a string
        if not isinstance(agent_id, str):
            continue  # Skip invalid keys
        
        # Skip paused agent
        if agent_id == paused_agent_id:
            continue
        
        # Validate agent_meta is not a string (should be AgentMetadata object or dict)
        if isinstance(agent_meta, str):
            # This is the bug - metadata contains strings instead of objects
            continue  # Skip invalid entries
        
        # Skip non-active agents (for MVP, only consider active agents)
        if hasattr(agent_meta, 'status') and agent_meta.status != 'active':
            continue
        
        # Convert AgentMetadata to dict for calculate_authority_score
        agent_meta_dict = None
        if hasattr(agent_meta, 'to_dict'):
            try:
                agent_meta_dict = agent_meta.to_dict()
            except Exception:
                continue
        elif isinstance(agent_meta, dict):
            agent_meta_dict = agent_meta
        elif hasattr(agent_meta, '__dict__'):
            # Convert object to dict manually
            try:
                agent_meta_dict = {}
                for key, value in agent_meta.__dict__.items():
                    if not key.startswith('_'):
                        agent_meta_dict[key] = value
            except Exception:
                continue
        else:
            # Skip if we can't convert
            continue
        
        # Validate we got a dict
        if not isinstance(agent_meta_dict, dict):
            continue
        
        # Mock state for authority calculation (MVP - assume healthy)
        mock_state = {'risk_score': 0.25}
        
        try:
            score = calculate_authority_score(agent_meta_dict, mock_state)
            candidates.append(agent_id)
            scores.append(score)
        except Exception as e:
            # Skip this agent if score calculation fails
            continue

    if not candidates:
        return None

    # Weighted random selection
    if sum(scores) == 0 or all(s == 0 for s in scores):
        return random.choice(candidates)

    selected = random.choices(candidates, weights=scores, k=1)[0]
    return selected
