"""
Auto-Resolve Stuck Dialectic Sessions

Quick Win A: Automatically resolve sessions that are stuck/inactive for >2 hours.
This removes artificial barriers and prevents session conflicts while giving
agents sufficient time to engage in thoughtful dialectic (matching DialecticProtocol timeouts).
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from src.logging_utils import get_logger
from src.dialectic_db import (
    get_dialectic_db,
    get_active_sessions_async,
    update_session_status_async,
    add_message_async,
)

logger = get_logger(__name__)

# Stuck session threshold: 2 hours of inactivity
# Increased from 5 min → 30 min → 2 hours
# Rationale: DialecticProtocol.MAX_ANTITHESIS_WAIT is 2 hours - agents need time to think
# 30 min was still too aggressive for real dialectic interactions (see session 5551079c40546c65)
STUCK_SESSION_THRESHOLD = timedelta(hours=2)


async def auto_resolve_stuck_sessions() -> Dict[str, Any]:
    """
    Automatically resolve sessions that are stuck/inactive for >2 hours.

    A session is considered "stuck" if:
    1. Status is 'active' but no activity for >2 hours
    2. Phase is AWAITING_THESIS and created >2 hours ago
    3. Phase is ANTITHESIS and thesis submitted >2 hours ago with no antithesis
    4. Phase is SYNTHESIS and last update >2 hours ago

    Returns:
        Dict with counts of resolved sessions and details
    """
    try:
        # Use UTC for consistent comparison with PostgreSQL timestamps
        now = datetime.now(timezone.utc)
        threshold_time = now - STUCK_SESSION_THRESHOLD

        # Get active sessions using the async backend (PostgreSQL or SQLite based on env)
        active_sessions = await get_active_sessions_async(limit=100)

        if not active_sessions:
            return {
                "resolved_count": 0,
                "message": "No active sessions found"
            }

        # Filter to stuck sessions (inactive for >2 hours)
        stuck_sessions = []
        for session in active_sessions:
            # Get updated_at or created_at
            updated_at = session.get("updated_at")
            created_at = session.get("created_at")

            # Parse timestamp if it's a string
            check_time = updated_at or created_at
            if isinstance(check_time, str):
                try:
                    if 'T' in check_time:
                        check_time = datetime.fromisoformat(check_time.replace('Z', '+00:00'))
                    else:
                        # Assume naive strings are UTC
                        check_time = datetime.strptime(check_time, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                except Exception:
                    continue

            # Ensure timezone-aware for comparison
            if check_time is not None:
                if check_time.tzinfo is None:
                    # Assume naive datetimes are UTC (PostgreSQL default)
                    check_time = check_time.replace(tzinfo=timezone.utc)

            if check_time and check_time < threshold_time:
                stuck_sessions.append(session)

        if not stuck_sessions:
            return {
                "resolved_count": 0,
                "message": "No stuck sessions found"
            }

        # Resolve each stuck session
        resolved_count = 0
        resolved_details = []
        db = await get_dialectic_db()

        for session in stuck_sessions:
            session_id = session.get("session_id")
            paused_agent_id = session.get("paused_agent_id")
            phase = session.get("phase")

            if not session_id:
                continue

            # Check if synthesis was reached with agreement
            # For now, just mark as failed (can enhance later to check for agreement)
            try:
                await update_session_status_async(session_id, "failed")

                # Add failure message
                failure_reason = f"Session auto-resolved: inactive for >{STUCK_SESSION_THRESHOLD.total_seconds()/60:.0f} minutes"
                try:
                    await add_message_async(
                        session_id=session_id,
                        agent_id="system",
                        message_type="failed",
                        reasoning=failure_reason,
                    )
                except Exception as msg_error:
                    logger.warning(f"Could not add failure message: {msg_error}")

                resolved_count += 1
                resolved_details.append({
                    "session_id": session_id,
                    "paused_agent_id": paused_agent_id,
                    "phase": phase,
                    "reason": "inactive_too_long"
                })

                logger.info(f"Auto-resolved stuck session {session_id[:16]}... as FAILED (paused_agent: {paused_agent_id}, phase: {phase})")

            except Exception as e:
                logger.warning(f"Could not resolve session {session_id}: {e}")

        return {
            "resolved_count": resolved_count,
            "resolved_sessions": resolved_details,
            "message": f"Auto-resolved {resolved_count} stuck session(s)"
        }

    except Exception as e:
        logger.error(f"Error auto-resolving stuck sessions: {e}", exc_info=True)
        return {
            "resolved_count": 0,
            "error": str(e),
            "message": "Failed to auto-resolve stuck sessions"
        }


async def check_and_resolve_stuck_sessions() -> Dict[str, Any]:
    """
    Check for stuck sessions and auto-resolve them.
    Called automatically when checking for active sessions.

    Returns:
        Dict with resolution results
    """
    try:
        return await auto_resolve_stuck_sessions()
    except Exception as e:
        logger.warning(f"Could not auto-resolve stuck sessions: {e}")
        return {"resolved_count": 0, "error": str(e)}
