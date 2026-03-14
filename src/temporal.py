"""
Temporal Narrator — contextual time awareness for agents.

Silence by default, signal when time matters.
Reads existing timestamped data and produces short, relative,
human-readable temporal context when thresholds are crossed.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from config.governance_config import GovernanceConfig
from src.logging_utils import get_logger

logger = get_logger(__name__)


def _format_duration(td: timedelta) -> str:
    """Format a timedelta as a human-readable relative string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}min"
    hours = minutes // 60
    remaining_min = minutes % 60
    if hours < 24:
        if remaining_min:
            return f"{hours}h {remaining_min}min"
        return f"{hours}h"
    days = hours // 24
    if days == 1:
        return "1 day"
    return f"{days} days"


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def build_temporal_context(
    agent_id: str,
    db,
    include_cross_agent: bool = True,
) -> Optional[str]:
    """
    Build temporal context string for an agent.

    Returns None if time is unremarkable. Returns a short plain-text
    string when one or more temporal thresholds are crossed.
    """
    try:
        now = datetime.now(timezone.utc)
        signals = []

        # Resolve identity
        identity = await db.get_identity(agent_id)
        if not identity:
            return None
        identity_id = identity.identity_id

        # Current session duration
        try:
            sessions = await db.get_active_sessions_for_identity(identity_id)
            if sessions:
                session_start = _ensure_utc(sessions[0].created_at)
                session_duration = now - session_start
                if session_duration > timedelta(hours=GovernanceConfig.TEMPORAL_LONG_SESSION_HOURS):
                    signals.append(f"Session: {_format_duration(session_duration)}.")
        except Exception as e:
            logger.debug(f"Temporal: session query failed: {e}")

        # Gap since last session
        last_session_end = None
        try:
            last_session = await db.get_last_inactive_session(identity_id)
            if last_session and last_session.last_active:
                last_session_end = _ensure_utc(last_session.last_active)
                gap = now - last_session_end
                if gap > timedelta(hours=GovernanceConfig.TEMPORAL_GAP_HOURS):
                    signals.append(f"Last session: {_format_duration(gap)} ago.")
        except Exception as e:
            logger.debug(f"Temporal: gap query failed: {e}")

        # Idle within session (time since last check-in)
        try:
            latest_state = await db.get_latest_agent_state(identity_id)
            if latest_state and latest_state.recorded_at:
                recorded = _ensure_utc(latest_state.recorded_at)
                idle = now - recorded
                if idle > timedelta(minutes=GovernanceConfig.TEMPORAL_IDLE_MINUTES):
                    signals.append(f"Idle: {_format_duration(idle)} since last check-in.")
        except Exception as e:
            logger.debug(f"Temporal: idle query failed: {e}")

        # High check-in density
        try:
            window = timedelta(minutes=GovernanceConfig.TEMPORAL_HIGH_CHECKIN_WINDOW_MINUTES)
            history = await db.get_agent_state_history(identity_id, limit=50)
            cutoff = now - window
            recent_count = sum(
                1 for s in history
                if _ensure_utc(s.recorded_at) > cutoff
            )
            if recent_count >= GovernanceConfig.TEMPORAL_HIGH_CHECKIN_COUNT:
                signals.append(f"High activity: {recent_count} check-ins in {_format_duration(window)}.")
        except Exception as e:
            logger.debug(f"Temporal: density query failed: {e}")

        # Cross-agent activity
        if include_cross_agent:
            try:
                cross_activity = await db.get_recent_cross_agent_activity(identity_id)
                if cross_activity:
                    entry = cross_activity[0]
                    agent_time = _ensure_utc(entry.get("recorded_at", now))
                    ago = _format_duration(now - agent_time)
                    count = entry.get("count", 1)
                    signals.append(f"Another agent active {ago} ago ({count} updates).")
            except Exception as e:
                logger.debug(f"Temporal: cross-agent query failed: {e}")

        # New discoveries since last session
        if last_session_end:
            try:
                discoveries = await db.kg_query(
                    created_after=last_session_end.isoformat(),
                    limit=50,
                )
                if discoveries:
                    count = len(discoveries)
                    signals.append(
                        f"{count} knowledge graph {'entry' if count == 1 else 'entries'} "
                        f"added since last session."
                    )
            except Exception as e:
                logger.debug(f"Temporal: discovery query failed: {e}")

        if not signals:
            return None

        return " ".join(signals)

    except Exception as e:
        logger.debug(f"Temporal narrator failed: {e}")
        return None
