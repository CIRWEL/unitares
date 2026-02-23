"""
Dialectic Reviewer Selection

Handles selecting appropriate reviewer agents for dialectic sessions.
Implements collusion prevention and expertise matching.

NOTE: Cross-process visibility is now provided by PostgreSQL (dialectic_db.py).
The in-memory ACTIVE_SESSIONS dict is kept for backward compat but PostgreSQL
is the source of truth for queries that need cross-process visibility.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import random
import json
import asyncio

from src.dialectic_protocol import calculate_authority_score, DialecticPhase
from src.logging_utils import get_logger
from .dialectic_session import (
    SESSION_STORAGE_DIR,
    ACTIVE_SESSIONS,
    _SESSION_METADATA_CACHE,
    _CACHE_TTL
)

# Import PostgreSQL async functions for cross-process visibility
from src.dialectic_db import (
    is_agent_in_active_session_async as pg_is_agent_in_active_session,
    has_recently_reviewed_async as pg_has_recently_reviewed,
)

logger = get_logger(__name__)


async def _has_recently_reviewed(reviewer_id: str, paused_agent_id: str, hours: int = 24) -> bool:
    """
    Check if reviewer has recently reviewed the paused agent - ASYNC to prevent blocking.

    Prevents collusion by ensuring reviewers don't repeatedly review the same agent.

    Uses PostgreSQL for cross-process visibility (CLI and SSE can see each other's sessions).

    Args:
        reviewer_id: Potential reviewer agent ID
        paused_agent_id: Paused agent ID
        hours: Time window in hours (default: 24)

    Returns:
        True if reviewer reviewed paused agent within the time window, False otherwise
    """
    # PRIMARY: Use PostgreSQL for cross-process visibility
    try:
        return await pg_has_recently_reviewed(reviewer_id, paused_agent_id, hours)
    except Exception as e:
        logger.warning(f"PostgreSQL check failed for _has_recently_reviewed, falling back to disk: {e}")

    # FALLBACK: Check JSON files on disk (backward compat)
    cutoff_time = datetime.now() - timedelta(hours=hours)

    try:
        loop = asyncio.get_running_loop()

        def _check_sessions_sync():
            """Synchronous session check - runs in executor"""
            SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

            if not SESSION_STORAGE_DIR.exists():
                return False

            session_files = sorted(SESSION_STORAGE_DIR.glob("*.json"),
                                     key=lambda p: p.stat().st_mtime,
                                     reverse=True)[:100]

            for session_file in session_files:
                try:
                    with open(session_file, 'r') as f:
                        session_data = json.load(f)

                    if (session_data.get('reviewer_agent_id') == reviewer_id and
                        session_data.get('paused_agent_id') == paused_agent_id):
                        phase = session_data.get('phase')
                        if phase == 'resolved':
                            created_at_str = session_data.get('created_at')
                            if created_at_str:
                                try:
                                    created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                                    if created_at >= cutoff_time:
                                        return True
                                except (ValueError, AttributeError):
                                    continue
                except (json.JSONDecodeError, KeyError, IOError, OSError) as e:
                    logger.debug(f"Skipping unreadable session file: {e}")
                    continue
            return False

        return await loop.run_in_executor(None, _check_sessions_sync)
    except Exception as e:
        logger.warning(f"Fallback disk check failed for _has_recently_reviewed: {e}")
        return False


async def is_agent_in_active_session(agent_id: str) -> bool:
    """
    Check if agent is already participating in an active dialectic session - ASYNC to prevent blocking.

    Prevents recursive assignment where an agent reviewing someone else
    gets assigned as a reviewer in another session.

    Uses PostgreSQL for cross-process visibility (CLI and SSE can see each other's sessions).
    Falls back to in-memory + disk for backward compat.

    QUICK WIN A: Auto-resolves stuck sessions before checking to prevent false positives.

    Args:
        agent_id: Agent ID to check

    Returns:
        True if agent is in an active session (as paused agent or reviewer), False otherwise
    """
    import time
    
    # QUICK WIN A: Auto-resolve stuck sessions before checking
    # This prevents "session conflict" errors when sessions are actually stuck
    try:
        from src.mcp_handlers.dialectic_auto_resolve import check_and_resolve_stuck_sessions
        resolution_result = await check_and_resolve_stuck_sessions()
        if resolution_result.get("resolved_count", 0) > 0:
            logger.info(f"Auto-resolved {resolution_result['resolved_count']} stuck session(s) before checking active sessions")
    except Exception as e:
        # Best-effort: don't block reviewer selection if auto-resolve fails
        logger.warning(f"Auto-resolve pre-check failed in is_agent_in_active_session: {e}")

    # PRIMARY: Use PostgreSQL for cross-process visibility
    # This is the key fix - CLI and SSE processes now share session state
    try:
        result = await pg_is_agent_in_active_session(agent_id)
        if result:
            # Update local cache for faster repeated lookups
            _SESSION_METADATA_CACHE[agent_id] = {
                'in_session': True,
                'timestamp': time.time(),
                'session_ids': []  # Could query for IDs if needed
            }
            return True
        # CRITICAL: If PostgreSQL says "not active", override any stale local cache.
        # Otherwise, we can incorrectly treat RESOLVED sessions as active for _CACHE_TTL.
        _SESSION_METADATA_CACHE[agent_id] = {
            'in_session': False,
            'timestamp': time.time(),
            'session_ids': []
        }
    except Exception as e:
        logger.warning(f"PostgreSQL check failed for is_agent_in_active_session, falling back: {e}")

    # FALLBACK Step 1: Check in-memory sessions (process-local cache)
    for session in ACTIVE_SESSIONS.values():
        if (session.paused_agent_id == agent_id or
            session.reviewer_agent_id == agent_id):
            if session.phase not in [DialecticPhase.RESOLVED, DialecticPhase.FAILED, DialecticPhase.ESCALATED]:
                _SESSION_METADATA_CACHE[agent_id] = {
                    'in_session': True,
                    'timestamp': time.time(),
                    'session_ids': [session.session_id]
                }
                return True

    # FALLBACK Step 2: Check cache
    cache_key = agent_id
    if cache_key in _SESSION_METADATA_CACHE:
        cached = _SESSION_METADATA_CACHE[cache_key]
        cache_age = time.time() - cached['timestamp']

        if cache_age < _CACHE_TTL:
            return cached['in_session']
        else:
            del _SESSION_METADATA_CACHE[cache_key]

    # FALLBACK Step 3: Check disk sessions (JSON files)
    try:
        loop = asyncio.get_running_loop()

        def _check_disk_sessions_sync():
            """Synchronous disk check - runs in executor"""
            SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

            if not SESSION_STORAGE_DIR.exists():
                return False, []

            session_files = sorted(SESSION_STORAGE_DIR.glob("*.json"),
                                     key=lambda p: p.stat().st_mtime,
                                     reverse=True)[:50]

            found_sessions = []
            for session_file in session_files:
                try:
                    with open(session_file, 'r') as f:
                        session_data = json.load(f)

                    if (session_data.get('paused_agent_id') == agent_id or
                        session_data.get('reviewer_agent_id') == agent_id):
                        phase = session_data.get('phase')
                        if phase not in ['resolved', 'failed', 'escalated']:
                            found_sessions.append(session_data.get('session_id', session_file.stem))
                            return True, found_sessions
                except (json.JSONDecodeError, KeyError, IOError, OSError) as e:
                    logger.debug(f"Skipping unreadable session file: {e}")
                    continue

            return False, []

        found, found_sessions = await loop.run_in_executor(None, _check_disk_sessions_sync)

        if found:
            _SESSION_METADATA_CACHE[agent_id] = {
                'in_session': True,
                'timestamp': time.time(),
                'session_ids': found_sessions
            }
            return True

        _SESSION_METADATA_CACHE[agent_id] = {
            'in_session': False,
            'timestamp': time.time(),
            'session_ids': []
        }
    except Exception as e:
        logger.warning(f"Fallback disk check failed for is_agent_in_active_session: {e}")
        _SESSION_METADATA_CACHE[agent_id] = {
            'in_session': False,
            'timestamp': time.time(),
            'session_ids': []
        }

    return False


async def select_reviewer(paused_agent_id: str,
                   metadata: Dict[str, Any] = None,
                   paused_agent_state: Dict[str, Any] = None,
                   paused_agent_tags: List[str] = None,
                   exclude_agent_ids: List[str] = None) -> Optional[str]:
    """
    Select a reviewer agent for dialectic session via random selection.

    Selection criteria (simple eligibility, then random):
    - Not the paused agent
    - Not in exclude_agent_ids list
    - Not already in another active session (prevents recursive assignment)
    - Not recently reviewed this agent (prevent collusion)
    - Status is 'active'

    No arbitrary authority metrics - just random from eligible pool.
    Self-review is fallback when no eligible agents found.

    Args:
        paused_agent_id: ID of paused agent
        metadata: All agent metadata (dict mapping agent_id -> AgentMetadata)
        paused_agent_state: State of paused agent (unused, kept for API compat)
        paused_agent_tags: Tags of paused agent (unused, kept for API compat)
        exclude_agent_ids: Optional list of agent IDs to exclude from selection

    Returns:
        Selected reviewer agent_id, or None if no reviewer available
    """
    # Handle missing or invalid metadata
    if not metadata or not isinstance(metadata, dict):
        return None

    candidates = []

    for agent_id, agent_meta in metadata.items():
        # Validate agent_id is a string
        if not isinstance(agent_id, str):
            continue

        # Skip paused agent (can't review yourself unless fallback)
        if agent_id == paused_agent_id:
            continue

        # Skip explicitly excluded agents
        if exclude_agent_ids and agent_id in exclude_agent_ids:
            continue

        # Skip agents already in active sessions (prevents recursive assignment)
        if await is_agent_in_active_session(agent_id):
            continue

        # Skip agents who recently reviewed this paused agent (prevent collusion)
        if await _has_recently_reviewed(agent_id, paused_agent_id, hours=24):
            continue

        # Skip invalid metadata entries
        if isinstance(agent_meta, str) or agent_meta is None:
            continue

        # Skip non-active agents
        status = agent_meta.get('status') if isinstance(agent_meta, dict) else getattr(agent_meta, 'status', None)
        if status and status != 'active':
            continue

        # Eligible - add to candidates
        candidates.append(agent_id)

    if not candidates:
        return None

    # Simple random selection - no arbitrary authority metrics
    return random.choice(candidates)

