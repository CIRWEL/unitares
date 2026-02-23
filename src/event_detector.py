"""
Event detection for governance dashboard.

Tracks previous state per agent and detects meaningful transitions:
- Verdict/action changes
- Risk threshold crossings
- Trajectory adjustments
- Drift alerts (with trend awareness: oscillating vs drifting)
- New agents
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Risk thresholds that trigger events when crossed
RISK_THRESHOLDS = [0.35, 0.60, 0.70]

# Drift configuration
DRIFT_ALERT_THRESHOLD = 0.1  # Alert when |drift| > this
DRIFT_HISTORY_SIZE = 5       # Number of samples to track for trend
DRIFT_STABLE_THRESHOLD = 0.05  # Below this is considered stable

# Axis names for drift
DRIFT_AXES = ["emotional", "epistemic", "behavioral"]

# Trend classifications
TREND_STABLE = "stable"           # Low magnitude, not moving
TREND_OSCILLATING = "oscillating" # Alternating direction, self-correcting
TREND_DRIFTING_UP = "drifting_up"     # Consistent positive movement
TREND_DRIFTING_DOWN = "drifting_down" # Consistent negative movement


def classify_drift_trend(history: List[float]) -> Tuple[str, float]:
    """
    Classify drift trend from history.

    Returns (trend_type, trend_strength) where:
    - trend_type: stable, oscillating, drifting_up, drifting_down
    - trend_strength: 0-1 indicating confidence in the classification
    """
    if not history or len(history) < 2:
        return TREND_STABLE, 0.0

    # Check if values are all small (stable)
    if all(abs(v) < DRIFT_STABLE_THRESHOLD for v in history):
        return TREND_STABLE, 1.0

    # Calculate deltas between consecutive values
    deltas = [history[i] - history[i-1] for i in range(1, len(history))]

    if not deltas:
        return TREND_STABLE, 0.0

    # Count direction changes (oscillation detection)
    direction_changes = 0
    for i in range(1, len(deltas)):
        if deltas[i] * deltas[i-1] < 0:  # Sign change
            direction_changes += 1

    # Calculate consistency of direction
    positive_deltas = sum(1 for d in deltas if d > 0.01)
    negative_deltas = sum(1 for d in deltas if d < -0.01)
    total_significant = positive_deltas + negative_deltas

    # Oscillation: frequent direction changes relative to samples
    oscillation_ratio = direction_changes / max(1, len(deltas) - 1)

    if oscillation_ratio >= 0.5 and total_significant >= 2:
        # More than half the deltas change direction = oscillating
        strength = min(1.0, oscillation_ratio)
        return TREND_OSCILLATING, strength

    # Check for consistent drift
    if total_significant > 0:
        if positive_deltas >= len(deltas) * 0.6:
            # Mostly positive movement
            strength = positive_deltas / total_significant
            return TREND_DRIFTING_UP, strength
        elif negative_deltas >= len(deltas) * 0.6:
            # Mostly negative movement
            strength = negative_deltas / total_significant
            return TREND_DRIFTING_DOWN, strength

    # Default to stable if no clear pattern
    return TREND_STABLE, 0.5


class GovernanceEventDetector:
    """Detects governance events by comparing current state to previous state."""

    def __init__(self, max_stored_events: int = 100):
        # Previous state per agent: {agent_id: {action, risk, drift, ...}}
        self._prev_state: Dict[str, Dict[str, Any]] = {}
        # Recent events for API retrieval (ring buffer)
        self._recent_events: List[Dict[str, Any]] = []
        self._max_stored_events = max_stored_events
        # Monotonically increasing event ID counter
        self._event_counter: int = 0

    def detect_events(
        self,
        agent_id: str,
        agent_name: str,
        action: str,
        risk: float,
        risk_raw: float,
        risk_adjustment: float,
        risk_reason: str,
        drift: List[float],
        verdict: str,
    ) -> List[Dict[str, Any]]:
        """
        Compare current state to previous and return list of events.

        Returns list of event dicts with: type, severity, message, details
        """
        events = []
        prev = self._prev_state.get(agent_id)
        now = datetime.now(timezone.utc).isoformat()

        # New agent event
        if prev is None:
            # Only fire event if this isn't the first agent ever (avoid noise on startup)
            if len(self._prev_state) > 0:
                events.append({
                    "type": "agent_new",
                    "severity": "info",
                    "message": f"New agent: {agent_name}",
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "timestamp": now
                })
        else:
            # Action/verdict change
            prev_action = prev.get("action")
            if prev_action and prev_action != action:
                severity = "critical" if action in ["pause", "critical", "reject"] else "warning"
                events.append({
                    "type": "verdict_change",
                    "severity": severity,
                    "message": f"{agent_name}: {prev_action.upper()} → {action.upper()}",
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "from": prev_action,
                    "to": action,
                    "timestamp": now
                })

            # Risk threshold crossing
            prev_risk = prev.get("risk", 0)
            for threshold in RISK_THRESHOLDS:
                crossed_up = prev_risk < threshold <= risk
                crossed_down = risk < threshold <= prev_risk
                if crossed_up or crossed_down:
                    direction = "up" if crossed_up else "down"
                    severity = "critical" if threshold >= 0.70 else ("warning" if threshold >= 0.60 else "info")
                    pct = int(threshold * 100)
                    events.append({
                        "type": "risk_threshold",
                        "severity": severity,
                        "message": f"{agent_name}: risk {'crossed' if crossed_up else 'dropped below'} {pct}% (now {risk*100:.1f}%)",
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "threshold": threshold,
                        "direction": direction,
                        "value": risk,
                        "timestamp": now
                    })

            # Drift alerts - check each axis with trend awareness
            prev_drift = prev.get("drift", [0, 0, 0])
            drift_history = prev.get("drift_history", {axis: [] for axis in DRIFT_AXES})
            drift_trends = {}

            if drift and len(drift) >= 3:
                for i, axis in enumerate(DRIFT_AXES):
                    curr_val = drift[i] if i < len(drift) else 0
                    prev_val = prev_drift[i] if i < len(prev_drift) else 0

                    # Update history for this axis
                    axis_history = drift_history.get(axis, [])
                    axis_history.append(curr_val)
                    if len(axis_history) > DRIFT_HISTORY_SIZE:
                        axis_history = axis_history[-DRIFT_HISTORY_SIZE:]
                    drift_history[axis] = axis_history

                    # Classify trend
                    trend_type, trend_strength = classify_drift_trend(axis_history)
                    drift_trends[axis] = {"trend": trend_type, "strength": trend_strength}

                    # Only alert on sustained drift, not oscillation
                    threshold_crossed = abs(curr_val) > DRIFT_ALERT_THRESHOLD and abs(prev_val) <= DRIFT_ALERT_THRESHOLD
                    is_concerning = trend_type in [TREND_DRIFTING_UP, TREND_DRIFTING_DOWN]

                    if threshold_crossed and is_concerning:
                        sign = "+" if curr_val > 0 else ""
                        direction = "↑" if trend_type == TREND_DRIFTING_UP else "↓"
                        events.append({
                            "type": "drift_alert",
                            "severity": "warning",
                            "message": f"{agent_name}: {axis} drift {sign}{curr_val:.2f} {direction}",
                            "agent_id": agent_id,
                            "agent_name": agent_name,
                            "axis": axis,
                            "value": curr_val,
                            "trend": trend_type,
                            "trend_strength": trend_strength,
                            "timestamp": now
                        })
                    elif threshold_crossed and trend_type == TREND_OSCILLATING:
                        # Log oscillation at info level, not warning - it's self-correcting
                        events.append({
                            "type": "drift_oscillation",
                            "severity": "info",
                            "message": f"{agent_name}: {axis} oscillating ±{abs(curr_val):.2f}",
                            "agent_id": agent_id,
                            "agent_name": agent_name,
                            "axis": axis,
                            "value": curr_val,
                            "trend": trend_type,
                            "timestamp": now
                        })

        # Trajectory adjustment (always report if non-zero, as it's contextually important)
        if risk_adjustment != 0:
            # Only report if this is a new adjustment or significantly different
            prev_adj = prev.get("risk_adjustment", 0) if prev else 0
            if abs(risk_adjustment - prev_adj) > 0.01:  # Changed by more than 1%
                sign = "+" if risk_adjustment > 0 else ""
                severity = "warning" if risk_adjustment > 0.1 else "info"
                events.append({
                    "type": "trajectory_adjustment",
                    "severity": severity,
                    "message": f"{agent_name}: {sign}{risk_adjustment*100:.0f}% trajectory adjustment",
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "delta": risk_adjustment,
                    "reason": risk_reason,
                    "timestamp": now
                })

        # Initialize drift tracking if not already set (for new agents or first update)
        if 'drift_history' not in locals():
            drift_history = prev.get("drift_history", {axis: [] for axis in DRIFT_AXES}) if prev else {axis: [] for axis in DRIFT_AXES}
        if 'drift_trends' not in locals():
            drift_trends = {}

        # Update stored state
        self._prev_state[agent_id] = {
            "action": action,
            "risk": risk,
            "risk_adjustment": risk_adjustment,
            "drift": drift if drift else [0, 0, 0],
            "drift_history": drift_history,
            "drift_trends": drift_trends,
            "verdict": verdict,
            "last_seen": now,
            "agent_name": agent_name
        }

        # Store events for API retrieval, assigning sequential IDs
        if events:
            for event in events:
                self._event_counter += 1
                event["event_id"] = self._event_counter
            self._recent_events.extend(events)
            # Trim to max size
            if len(self._recent_events) > self._max_stored_events:
                self._recent_events = self._recent_events[-self._max_stored_events:]

        return events

    def check_idle_agents(self, idle_threshold_minutes: float = 5.0) -> List[Dict[str, Any]]:
        """
        Check for agents that haven't checked in recently.
        Call this periodically (e.g., every minute).

        Returns list of idle agent events.
        """
        events = []
        now = datetime.now(timezone.utc)

        for agent_id, state in list(self._prev_state.items()):
            last_seen_str = state.get("last_seen")
            if not last_seen_str:
                continue

            try:
                last_seen = datetime.fromisoformat(last_seen_str.replace('Z', '+00:00'))
                idle_minutes = (now - last_seen).total_seconds() / 60

                # Check if newly idle (crossed threshold)
                was_idle = state.get("_idle_alerted", False)
                is_idle = idle_minutes >= idle_threshold_minutes

                if is_idle and not was_idle:
                    agent_name = state.get("agent_name", agent_id[:8])
                    events.append({
                        "type": "agent_idle",
                        "severity": "warning",
                        "message": f"{agent_name} idle ({int(idle_minutes)}m)",
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "duration_minutes": idle_minutes,
                        "timestamp": now.isoformat()
                    })
                    state["_idle_alerted"] = True
                elif not is_idle and was_idle:
                    # Agent came back - clear the flag
                    state["_idle_alerted"] = False

            except Exception as e:
                logger.debug(f"Error checking idle for {agent_id}: {e}")

        return events

    def get_recent_events_for_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get the last known state for an agent."""
        return self._prev_state.get(agent_id)

    def get_drift_trends(self, agent_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Get current drift trends for an agent.

        Returns dict of {axis: {trend, strength, current_value}} for each axis.
        """
        state = self._prev_state.get(agent_id)
        if not state:
            return {}

        drift = state.get("drift", [0, 0, 0])
        drift_trends = state.get("drift_trends", {})

        result = {}
        for i, axis in enumerate(DRIFT_AXES):
            curr_val = drift[i] if i < len(drift) else 0
            trend_info = drift_trends.get(axis, {"trend": TREND_STABLE, "strength": 0.0})
            result[axis] = {
                "trend": trend_info.get("trend", TREND_STABLE),
                "strength": trend_info.get("strength", 0.0),
                "value": curr_val
            }

        return result

    def get_recent_events(
        self,
        limit: int = 50,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get recent events, optionally filtered.

        Args:
            limit: Maximum number of events to return
            agent_id: Filter to specific agent
            event_type: Filter to specific event type
            since: Only return events with event_id > since (cursor for resumption)

        Returns:
            List of events, newest first
        """
        events = self._recent_events.copy()

        # Apply filters
        if since is not None:
            events = [e for e in events if e.get("event_id", 0) > since]
        if agent_id:
            events = [e for e in events if e.get("agent_id") == agent_id]
        if event_type:
            events = [e for e in events if e.get("type") == event_type]

        # Return newest first, limited
        return list(reversed(events))[:limit]

    def clear_events(self):
        """Clear stored events (for testing)."""
        self._recent_events.clear()


# Singleton instance
event_detector = GovernanceEventDetector()
