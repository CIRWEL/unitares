"""
CIRS Protocol Handlers - Continuity Integration and Resonance Subsystem

Implements the multi-agent resonance layer from the UARG Whitepaper.
See: UARG Whitepaper (UNITARES + CIRS integration specification)

Message Types (per UARG spec) - ALL IMPLEMENTED:
1. VOID_ALERT: Notify peers of local/global void events
   - Auto-emits on void state transitions
   - Query recent alerts from all agents

2. STATE_ANNOUNCE: Broadcast EISV + trajectory state
   - Auto-emits every 5 updates
   - Includes trajectory signature components (Σ)
   - Query peer states for coordination

3. COHERENCE_REPORT: Share pairwise similarity metrics
   - Compute EISV + trajectory similarity
   - Maps to trajectory identity theory
   - Generates coordination recommendations

4. BOUNDARY_CONTRACT: Declare trust policies and void response rules
   - Set default trust level (full/partial/observe/none)
   - Override trust for specific agents
   - Define void response policy

5. GOVERNANCE_ACTION: Coordinate interventions across agents
   - Void interventions, coherence boosts
   - Task delegation requests/responses
   - Coordination sync between agents

6. RESONANCE_ALERT: Notify peers of sustained oscillation
   - Emitted when governor detects resonance
   - Peers with high similarity tighten thresholds defensively

7. STABILITY_RESTORED: Signal exit from resonance
   - Emitted when agent stabilizes after resonance
   - Peers decay their defensive neighbor pressure
"""

from typing import Dict, Any, Sequence, Optional, List
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from collections import deque
import json

from mcp.types import TextContent
from .decorators import mcp_tool
from .utils import success_response, error_response, require_registered_agent
from src.logging_utils import get_logger

logger = get_logger(__name__)

# Import shared server access
from .shared import get_mcp_server


# =============================================================================
# CIRS Protocol Constants
# =============================================================================

class VoidSeverity(str, Enum):
    """Void alert severity levels per UARG spec"""
    WARNING = "warning"   # |V| > threshold, not yet critical
    CRITICAL = "critical"  # |V| significantly elevated, system at risk


class AgentRegime(str, Enum):
    """Agent operational regime per trajectory identity theory"""
    DIVERGENCE = "divergence"    # Exploring, high entropy acceptable
    TRANSITION = "transition"    # Moving between regimes
    CONVERGENCE = "convergence"  # Focusing, reducing entropy
    STABLE = "stable"            # At equilibrium


@dataclass
class VoidAlert:
    """
    VOID_ALERT message structure per UARG Whitepaper.

    Fields:
        agent_id: Source agent identifier
        timestamp: ISO timestamp of void event
        severity: warning | critical
        V_snapshot: V value at time of alert
        context_ref: Optional pointer to logs/traces for debugging
        coherence_at_event: System coherence when void detected (helpful for peers)
        risk_at_event: Risk score when void detected
    """
    agent_id: str
    timestamp: str
    severity: VoidSeverity
    V_snapshot: float
    context_ref: Optional[str] = None
    coherence_at_event: Optional[float] = None
    risk_at_event: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "severity": self.severity.value,
            "V_snapshot": self.V_snapshot,
            "context_ref": self.context_ref,
            "coherence_at_event": self.coherence_at_event,
            "risk_at_event": self.risk_at_event,
        }


@dataclass
class StateAnnounce:
    """
    STATE_ANNOUNCE message structure per UARG Whitepaper.

    Broadcasts EISV + trajectory state to enable multi-agent coordination.
    This is the foundational heartbeat for CIRS resonance.

    Fields:
        agent_id: Source agent identifier
        timestamp: ISO timestamp of announcement
        eisv: Dict with E, I, S, V values
        coherence: Current coherence score
        regime: Current operational regime (divergence/transition/convergence/stable)
        phi: Φ objective function value (physics signal)
        verdict: Governance verdict (safe/caution/high-risk)
        risk_score: Current governance risk score
        trajectory_signature: Optional trajectory signature components (Σ)
        purpose: Agent's declared purpose (if set)
        update_count: Total updates processed
    """
    agent_id: str
    timestamp: str
    eisv: Dict[str, float]
    coherence: float
    regime: str
    phi: float
    verdict: str
    risk_score: float
    trajectory_signature: Optional[Dict[str, Any]] = None
    purpose: Optional[str] = None
    update_count: int = 0
    trust_tier: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "eisv": self.eisv,
            "coherence": self.coherence,
            "regime": self.regime,
            "phi": self.phi,
            "verdict": self.verdict,
            "risk_score": self.risk_score,
            "update_count": self.update_count,
        }
        if self.trajectory_signature:
            result["trajectory_signature"] = self.trajectory_signature
        if self.purpose:
            result["purpose"] = self.purpose
        if self.trust_tier:
            result["trust_tier"] = self.trust_tier
        return result


@dataclass
class ResonanceAlert:
    """RESONANCE_ALERT: Emitted when agent's governor detects sustained oscillation."""
    agent_id: str
    timestamp: str
    oi: float
    phase: str
    tau_current: float
    beta_current: float
    flips: int
    duration_updates: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "RESONANCE_ALERT",
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "oi": self.oi,
            "phase": self.phase,
            "tau_current": self.tau_current,
            "beta_current": self.beta_current,
            "flips": self.flips,
            "duration_updates": self.duration_updates,
        }


@dataclass
class StabilityRestored:
    """STABILITY_RESTORED: Emitted when agent exits resonance."""
    agent_id: str
    timestamp: str
    oi: float
    tau_settled: float
    beta_settled: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "STABILITY_RESTORED",
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "oi": self.oi,
            "tau_settled": self.tau_settled,
            "beta_settled": self.beta_settled,
        }


# =============================================================================
# In-Memory Message Storage (will be persisted to PostgreSQL in future)
# =============================================================================

# Thread-safe deque for recent void alerts (last 1000 alerts, ~24h retention)
_void_alert_buffer: deque = deque(maxlen=1000)

# Thread-safe deque for state announcements (last announcement per agent)
# Key: agent_id, Value: StateAnnounce dict
_state_announce_buffer: Dict[str, Dict[str, Any]] = {}

# Message TTL for cleanup
ALERT_TTL_HOURS = 24
STATE_ANNOUNCE_TTL_HOURS = 1  # State announcements are more ephemeral


def _cleanup_old_alerts():
    """Remove alerts older than TTL"""
    cutoff = datetime.now() - timedelta(hours=ALERT_TTL_HOURS)
    cutoff_iso = cutoff.isoformat()

    # Remove from front (oldest first) until we hit a recent alert
    while _void_alert_buffer and _void_alert_buffer[0]["timestamp"] < cutoff_iso:
        _void_alert_buffer.popleft()


def _store_void_alert(alert: VoidAlert):
    """Store a void alert in the buffer"""
    _cleanup_old_alerts()
    _void_alert_buffer.append(alert.to_dict())

    # Also log for persistence layer (future: write to PostgreSQL)
    logger.info(f"[CIRS/VOID_ALERT] {alert.severity.value.upper()}: agent={alert.agent_id}, V={alert.V_snapshot:.4f}")


def _get_recent_void_alerts(
    agent_id: Optional[str] = None,
    severity: Optional[VoidSeverity] = None,
    since_hours: float = 1.0,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Query recent void alerts.

    Args:
        agent_id: Filter by source agent (None = all agents)
        severity: Filter by severity level (None = all severities)
        since_hours: Look back N hours (default: 1 hour)
        limit: Maximum alerts to return

    Returns:
        List of void alert dicts, newest first
    """
    _cleanup_old_alerts()

    cutoff = datetime.now() - timedelta(hours=since_hours)
    cutoff_iso = cutoff.isoformat()

    results = []
    # Iterate in reverse (newest first)
    for alert in reversed(_void_alert_buffer):
        if alert["timestamp"] < cutoff_iso:
            continue
        if agent_id and alert["agent_id"] != agent_id:
            continue
        if severity and alert["severity"] != severity.value:
            continue
        results.append(alert)
        if len(results) >= limit:
            break

    return results


# =============================================================================
# State Announce Storage
# =============================================================================

def _cleanup_old_state_announces():
    """Remove state announcements older than TTL"""
    cutoff = datetime.now() - timedelta(hours=STATE_ANNOUNCE_TTL_HOURS)
    cutoff_iso = cutoff.isoformat()

    # Remove stale entries
    stale_agents = [
        agent_id for agent_id, announce in _state_announce_buffer.items()
        if announce["timestamp"] < cutoff_iso
    ]
    for agent_id in stale_agents:
        del _state_announce_buffer[agent_id]


def _store_state_announce(announce: StateAnnounce):
    """Store a state announcement (overwrites previous for same agent)"""
    _cleanup_old_state_announces()
    _state_announce_buffer[announce.agent_id] = announce.to_dict()
    logger.debug(f"[CIRS/STATE_ANNOUNCE] agent={announce.agent_id}, regime={announce.regime}, phi={announce.phi:.3f}")


def _get_state_announces(
    agent_ids: Optional[List[str]] = None,
    regime: Optional[str] = None,
    min_coherence: Optional[float] = None,
    max_risk: Optional[float] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Query recent state announcements.

    Args:
        agent_ids: Filter by specific agents (None = all agents)
        regime: Filter by regime (divergence/transition/convergence/stable)
        min_coherence: Only return agents with coherence >= this value
        max_risk: Only return agents with risk_score <= this value
        limit: Maximum results to return

    Returns:
        List of state announce dicts, sorted by timestamp (newest first)
    """
    _cleanup_old_state_announces()

    results = []
    for agent_id, announce in _state_announce_buffer.items():
        # Apply filters
        if agent_ids and agent_id not in agent_ids:
            continue
        if regime and announce.get("regime") != regime:
            continue
        if min_coherence is not None and announce.get("coherence", 0) < min_coherence:
            continue
        if max_risk is not None and announce.get("risk_score", 1.0) > max_risk:
            continue
        results.append(announce)

    # Sort by timestamp (newest first)
    results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    return results[:limit]


# =============================================================================
# Resonance Alert / Stability Restored Storage
# =============================================================================

_resonance_alert_buffer: deque = deque(maxlen=100)


def _emit_resonance_alert(alert: ResonanceAlert):
    """Store a resonance alert."""
    _resonance_alert_buffer.append(alert.to_dict())


def _emit_stability_restored(restored: StabilityRestored):
    """Store a stability restored signal."""
    _resonance_alert_buffer.append(restored.to_dict())


def _get_recent_resonance_signals(
    max_age_minutes: int = 30,
    agent_id: Optional[str] = None,
    signal_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get recent resonance-related signals."""
    cutoff = (datetime.utcnow() - timedelta(minutes=max_age_minutes)).isoformat()
    results = []
    for signal in reversed(_resonance_alert_buffer):
        if signal["timestamp"] < cutoff:
            break
        if agent_id and signal["agent_id"] != agent_id:
            continue
        if signal_type and signal["type"] != signal_type:
            continue
        results.append(signal)
    return results


# =============================================================================
# VOID_ALERT Tool Handler
# =============================================================================

@mcp_tool("void_alert", timeout=10.0, register=False, description="CIRS Protocol: Broadcast or query void state alerts for multi-agent coordination")
async def handle_void_alert(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    CIRS VOID_ALERT - Multi-agent void state coordination.

    Two modes:
    1. EMIT mode (action='emit'): Broadcast a void alert to peers
       - Automatically triggered by process_agent_update when void detected
       - Can also be called manually for explicit void signaling

    2. QUERY mode (action='query'): Get recent void alerts from the system
       - Query all agents or filter by specific agent_id
       - Filter by severity level
       - Useful for situational awareness

    Args:
        action: 'emit' | 'query' (required)

        For emit:
            severity: 'warning' | 'critical' (default: auto-detect from V)
            context_ref: Optional reference to logs/traces

        For query:
            filter_agent_id: Filter by source agent (optional)
            filter_severity: Filter by severity (optional)
            since_hours: Look back window in hours (default: 1.0)
            limit: Max results (default: 50)

    Returns:
        For emit: Confirmation with alert details
        For query: List of recent void alerts

    Example emit:
        void_alert(action='emit', severity='warning', context_ref='high entropy detected')

    Example query:
        void_alert(action='query', filter_severity='critical', since_hours=0.5)
    """
    action = arguments.get("action", "").lower()

    if not action or action not in ("emit", "query"):
        return [error_response(
            "action parameter required: 'emit' or 'query'",
            recovery={
                "valid_actions": ["emit", "query"],
                "emit_example": "void_alert(action='emit', severity='warning')",
                "query_example": "void_alert(action='query', since_hours=1.0)"
            }
        )]

    if action == "emit":
        return await _handle_void_alert_emit(arguments)
    else:
        return await _handle_void_alert_query(arguments)


async def _handle_void_alert_emit(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle VOID_ALERT emit action"""
    # Require registered agent for emit
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    mcp_server = get_mcp_server()

    # Get current state for auto-detection
    monitor = mcp_server.get_or_create_monitor(agent_id)
    current_V = float(monitor.state.V)
    current_coherence = float(monitor.state.coherence)

    # Get risk score from metrics
    metrics = monitor.get_metrics()
    current_risk = metrics.get("risk_score") or metrics.get("current_risk") or 0.0

    # Determine severity
    severity_str = arguments.get("severity", "").lower()
    if severity_str:
        if severity_str not in ("warning", "critical"):
            return [error_response(
                f"Invalid severity: {severity_str}",
                recovery={"valid_values": ["warning", "critical"]}
            )]
        severity = VoidSeverity(severity_str)
    else:
        # Auto-detect severity from V value
        # Use adaptive threshold from config
        from config.governance_config import config
        import numpy as np
        V_history = np.array(monitor.state.V_history) if monitor.state.V_history else np.array([current_V])
        threshold = config.get_void_threshold(V_history, adaptive=True)

        if abs(current_V) > threshold * 1.5:  # Significantly above threshold
            severity = VoidSeverity.CRITICAL
        elif abs(current_V) > threshold:
            severity = VoidSeverity.WARNING
        else:
            # V below threshold - warn but allow explicit emit
            return [error_response(
                f"V value ({current_V:.4f}) is below void threshold ({threshold:.4f}). "
                f"Set severity='warning' or severity='critical' to emit anyway.",
                recovery={
                    "current_V": current_V,
                    "threshold": threshold,
                    "void_active": monitor.state.void_active,
                    "note": "Void alerts should reflect actual void state"
                }
            )]

    # Create and store the alert
    alert = VoidAlert(
        agent_id=agent_id,
        timestamp=datetime.now().isoformat(),
        severity=severity,
        V_snapshot=current_V,
        context_ref=arguments.get("context_ref"),
        coherence_at_event=current_coherence,
        risk_at_event=current_risk
    )

    _store_void_alert(alert)

    # Return confirmation
    return success_response({
        "action": "emit",
        "alert": alert.to_dict(),
        "message": f"VOID_ALERT broadcast: {severity.value.upper()} from {agent_id}",
        "cirs_protocol": "VOID_ALERT",
        "active_alerts_count": len(_void_alert_buffer)
    }, agent_id=agent_id)


async def _handle_void_alert_query(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle VOID_ALERT query action"""
    # Query doesn't require registered agent (read-only)
    filter_agent_id = arguments.get("filter_agent_id")
    filter_severity_str = arguments.get("filter_severity", "").lower()
    since_hours = float(arguments.get("since_hours", 1.0))
    limit = int(arguments.get("limit", 50))

    # Parse severity filter
    filter_severity = None
    if filter_severity_str:
        if filter_severity_str not in ("warning", "critical"):
            return [error_response(
                f"Invalid filter_severity: {filter_severity_str}",
                recovery={"valid_values": ["warning", "critical"]}
            )]
        filter_severity = VoidSeverity(filter_severity_str)

    # Query alerts
    alerts = _get_recent_void_alerts(
        agent_id=filter_agent_id,
        severity=filter_severity,
        since_hours=since_hours,
        limit=limit
    )

    # Compute summary stats
    summary = {
        "total_alerts": len(alerts),
        "by_severity": {
            "warning": sum(1 for a in alerts if a["severity"] == "warning"),
            "critical": sum(1 for a in alerts if a["severity"] == "critical")
        },
        "unique_agents": len(set(a["agent_id"] for a in alerts)),
        "query_window_hours": since_hours
    }

    return success_response({
        "action": "query",
        "alerts": alerts,
        "summary": summary,
        "cirs_protocol": "VOID_ALERT",
        "filters_applied": {
            "agent_id": filter_agent_id,
            "severity": filter_severity_str or None,
            "since_hours": since_hours,
            "limit": limit
        }
    })


# =============================================================================
# STATE_ANNOUNCE Tool Handler
# =============================================================================

@mcp_tool("state_announce", timeout=10.0, register=False, description="CIRS Protocol: Broadcast or query agent EISV + trajectory state for multi-agent coordination")
async def handle_state_announce(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    CIRS STATE_ANNOUNCE - Multi-agent state broadcasting.

    The foundational heartbeat for CIRS resonance. Agents broadcast their
    EISV state + trajectory information so peers can coordinate.

    Two modes:
    1. EMIT mode (action='emit'): Broadcast your current state
       - Automatically triggered by process_agent_update
       - Can also be called manually for explicit state sharing

    2. QUERY mode (action='query'): Get recent state announcements from peers
       - Query all agents or filter by specific criteria
       - Useful for understanding the multi-agent landscape

    Args:
        action: 'emit' | 'query' (required)

        For emit:
            include_trajectory: Include trajectory signature (default: True)

        For query:
            agent_ids: List of specific agents to query (optional)
            regime: Filter by regime (divergence/transition/convergence/stable)
            min_coherence: Only agents with coherence >= this value
            max_risk: Only agents with risk_score <= this value
            limit: Max results (default: 50)

    Returns:
        For emit: Confirmation with announced state
        For query: List of recent state announcements

    Example emit:
        state_announce(action='emit')

    Example query:
        state_announce(action='query', regime='convergence', min_coherence=0.6)
    """
    action = arguments.get("action", "").lower()

    if not action or action not in ("emit", "query"):
        return [error_response(
            "action parameter required: 'emit' or 'query'",
            recovery={
                "valid_actions": ["emit", "query"],
                "emit_example": "state_announce(action='emit')",
                "query_example": "state_announce(action='query', regime='convergence')"
            }
        )]

    if action == "emit":
        return await _handle_state_announce_emit(arguments)
    else:
        return await _handle_state_announce_query(arguments)


async def _handle_state_announce_emit(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle STATE_ANNOUNCE emit action"""
    # Require registered agent for emit
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    mcp_server = get_mcp_server()

    # Get current state
    monitor = mcp_server.get_or_create_monitor(agent_id)
    metrics = monitor.get_metrics()

    # Build EISV dict
    eisv = {
        "E": float(metrics.get("E", 0.7)),
        "I": float(metrics.get("I", 0.8)),
        "S": float(metrics.get("S", 0.2)),
        "V": float(metrics.get("V", 0.0)),
    }

    # Get trajectory signature if requested
    trajectory_signature = None
    include_trajectory = arguments.get("include_trajectory", True)
    if include_trajectory:
        try:
            # Build trajectory signature from available state
            # Per trajectory identity theory: Σ = (Π, β, α, ρ, Δ, η)
            state = monitor.state
            trajectory_signature = {
                "pi": {  # Purpose/Intent vector
                    "regime": str(getattr(state, 'regime', 'divergence')),
                    "task_type": str(getattr(state, 'task_type', 'mixed')),
                },
                "beta": {  # Behavioral patterns
                    "lambda1": float(state.lambda1),
                    "decision_bias": _compute_decision_bias(state),
                },
                "alpha": {  # Attentional focus
                    "coherence": float(state.coherence),
                    "focus_stability": _compute_focus_stability(state),
                },
                "rho": {  # Relational patterns (placeholder for multi-agent)
                    "update_count": int(state.update_count),
                },
                "delta": {  # Developmental trajectory
                    "maturity": _compute_maturity(state),
                    "convergence_rate": _compute_convergence_rate(state),
                },
                "eta": {  # Environmental coupling
                    "void_frequency": float(metrics.get("void_frequency", 0.0)),
                    "risk_trend": _compute_risk_trend(state),
                },
            }
        except Exception as e:
            logger.debug(f"Could not compute trajectory signature: {e}")
            trajectory_signature = None

    # Get agent purpose and trust tier if available
    purpose = None
    trust_tier_name = None
    meta = mcp_server.agent_metadata.get(agent_id)
    if meta:
        purpose = getattr(meta, 'purpose', None)
        trust_tier_name = getattr(meta, 'trust_tier', None)

    # Create and store the announcement
    announce = StateAnnounce(
        agent_id=agent_id,
        timestamp=datetime.now().isoformat(),
        eisv=eisv,
        coherence=float(metrics.get("coherence", 0.5)),
        regime=str(metrics.get("regime", "divergence")),
        phi=float(metrics.get("phi", 0.0)),
        verdict=str(metrics.get("verdict", "caution")),
        risk_score=float(metrics.get("risk_score") or metrics.get("current_risk") or 0.0),
        trajectory_signature=trajectory_signature,
        purpose=purpose,
        update_count=int(metrics.get("updates", 0)),
        trust_tier=trust_tier_name,
    )

    _store_state_announce(announce)

    return success_response({
        "action": "emit",
        "announcement": announce.to_dict(),
        "message": f"STATE_ANNOUNCE broadcast from {agent_id}",
        "cirs_protocol": "STATE_ANNOUNCE",
        "active_agents": len(_state_announce_buffer)
    }, agent_id=agent_id)


async def _handle_state_announce_query(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle STATE_ANNOUNCE query action"""
    # Query doesn't require registered agent (read-only)
    agent_ids = arguments.get("agent_ids")
    regime = arguments.get("regime")
    min_coherence = arguments.get("min_coherence")
    max_risk = arguments.get("max_risk")
    limit = int(arguments.get("limit", 50))

    # Validate regime if provided
    valid_regimes = ["divergence", "transition", "convergence", "stable"]
    if regime and regime.lower() not in valid_regimes:
        return [error_response(
            f"Invalid regime: {regime}",
            recovery={"valid_values": valid_regimes}
        )]

    # Query announcements
    announces = _get_state_announces(
        agent_ids=agent_ids,
        regime=regime.lower() if regime else None,
        min_coherence=float(min_coherence) if min_coherence is not None else None,
        max_risk=float(max_risk) if max_risk is not None else None,
        limit=limit
    )

    # Compute summary stats
    regimes = [a.get("regime", "unknown") for a in announces]
    verdicts = [a.get("verdict", "unknown") for a in announces]

    summary = {
        "total_agents": len(announces),
        "by_regime": {r: regimes.count(r) for r in set(regimes)},
        "by_verdict": {v: verdicts.count(v) for v in set(verdicts)},
        "avg_coherence": sum(a.get("coherence", 0) for a in announces) / len(announces) if announces else 0,
        "avg_risk": sum(a.get("risk_score", 0) for a in announces) / len(announces) if announces else 0,
    }

    return success_response({
        "action": "query",
        "announcements": announces,
        "summary": summary,
        "cirs_protocol": "STATE_ANNOUNCE",
        "filters_applied": {
            "agent_ids": agent_ids,
            "regime": regime,
            "min_coherence": min_coherence,
            "max_risk": max_risk,
            "limit": limit
        }
    })


# =============================================================================
# Trajectory Signature Helper Functions
# =============================================================================

def _compute_decision_bias(state) -> str:
    """Compute decision bias from decision history"""
    if not hasattr(state, 'decision_history') or not state.decision_history:
        return "neutral"

    recent = state.decision_history[-10:]  # Last 10 decisions
    proceed_count = sum(1 for d in recent if d in ["proceed", "approve"])
    pause_count = sum(1 for d in recent if d in ["pause", "reject"])

    if proceed_count > pause_count * 2:
        return "proceed_bias"
    elif pause_count > proceed_count * 2:
        return "pause_bias"
    return "balanced"


def _compute_focus_stability(state) -> float:
    """Compute focus stability from coherence history"""
    if not hasattr(state, 'coherence_history') or len(state.coherence_history) < 5:
        return 0.5

    recent = state.coherence_history[-10:]
    if len(recent) < 2:
        return 0.5

    # Stability = 1 - normalized variance
    import numpy as np
    variance = np.var(recent)
    return float(max(0, 1 - variance * 4))  # Scale variance


def _compute_maturity(state) -> str:
    """Compute agent maturity from update count"""
    updates = getattr(state, 'update_count', 0)
    if updates < 5:
        return "nascent"
    elif updates < 20:
        return "developing"
    elif updates < 50:
        return "maturing"
    else:
        return "mature"


def _compute_convergence_rate(state) -> float:
    """Compute convergence rate from entropy history"""
    if not hasattr(state, 'S_history') or len(state.S_history) < 5:
        return 0.0

    recent = state.S_history[-10:]
    if len(recent) < 2:
        return 0.0

    # Convergence rate = negative slope of entropy (positive = converging)
    import numpy as np
    x = np.arange(len(recent))
    slope, _ = np.polyfit(x, recent, 1)
    return float(-slope)  # Positive when entropy decreasing


def _compute_risk_trend(state) -> str:
    """Compute risk trend from risk history"""
    if not hasattr(state, 'risk_history') or len(state.risk_history) < 3:
        return "stable"

    recent = state.risk_history[-5:]
    if len(recent) < 2:
        return "stable"

    first_half = sum(recent[:len(recent)//2]) / (len(recent)//2)
    second_half = sum(recent[len(recent)//2:]) / (len(recent) - len(recent)//2)

    diff = second_half - first_half
    if diff > 0.1:
        return "increasing"
    elif diff < -0.1:
        return "decreasing"
    return "stable"


# =============================================================================
# Auto-emit integration hook (called from process_agent_update)
# =============================================================================

def maybe_emit_void_alert(
    agent_id: str,
    V: float,
    void_active: bool,
    coherence: float,
    risk_score: float,
    previous_void_active: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Check if a void alert should be auto-emitted after state update.

    Called from process_agent_update to enable automatic CIRS coordination.

    Args:
        agent_id: Agent identifier
        V: Current V value
        void_active: Current void state
        coherence: Current coherence
        risk_score: Current risk score
        previous_void_active: Void state before this update

    Returns:
        Alert dict if emitted, None otherwise
    """
    # Only emit on void state TRANSITIONS (entering void, not staying in void)
    if void_active and not previous_void_active:
        # Determine severity based on V magnitude and risk
        if abs(V) > 0.15 or risk_score > 0.6:  # Critical thresholds
            severity = VoidSeverity.CRITICAL
        else:
            severity = VoidSeverity.WARNING

        alert = VoidAlert(
            agent_id=agent_id,
            timestamp=datetime.now().isoformat(),
            severity=severity,
            V_snapshot=V,
            context_ref="auto-emit from process_agent_update",
            coherence_at_event=coherence,
            risk_at_event=risk_score
        )

        _store_void_alert(alert)
        logger.info(f"[CIRS/AUTO_EMIT] VOID_ALERT {severity.value}: agent={agent_id}, V={V:.4f}")

        return alert.to_dict()

    return None


def auto_emit_state_announce(
    agent_id: str,
    metrics: Dict[str, Any],
    monitor_state: Any
) -> Optional[Dict[str, Any]]:
    """
    Auto-emit STATE_ANNOUNCE after state update.

    Called from process_agent_update to enable automatic CIRS state broadcasting.
    Emits every N updates to avoid flooding (configurable).

    Args:
        agent_id: Agent identifier
        metrics: Current metrics dict from process_update
        monitor_state: Current monitor state object

    Returns:
        Announcement dict if emitted, None otherwise
    """
    # Emit every 5 updates to avoid flooding
    update_count = metrics.get("updates", 0)
    if update_count % 5 != 0 and update_count > 1:
        return None

    try:
        # Build EISV dict
        eisv = {
            "E": float(metrics.get("E", 0.7)),
            "I": float(metrics.get("I", 0.8)),
            "S": float(metrics.get("S", 0.2)),
            "V": float(metrics.get("V", 0.0)),
        }

        # Get trust tier from cache if available
        trust_tier_name = None
        try:
            from .shared import get_mcp_server
            _meta = get_mcp_server().agent_metadata.get(agent_id)
            if _meta:
                trust_tier_name = getattr(_meta, 'trust_tier', None)
        except Exception:
            pass

        # Create announcement (simplified - no trajectory signature in auto-emit)
        announce = StateAnnounce(
            agent_id=agent_id,
            timestamp=datetime.now().isoformat(),
            eisv=eisv,
            coherence=float(metrics.get("coherence", 0.5)),
            regime=str(metrics.get("regime", "divergence")),
            phi=float(metrics.get("phi", 0.0)),
            verdict=str(metrics.get("verdict", "caution")),
            risk_score=float(metrics.get("risk_score") or metrics.get("current_risk") or 0.0),
            trajectory_signature=None,  # Skip in auto-emit for performance
            purpose=None,
            update_count=int(update_count),
            trust_tier=trust_tier_name,
        )

        _store_state_announce(announce)
        logger.debug(f"[CIRS/AUTO_EMIT] STATE_ANNOUNCE: agent={agent_id}, update={update_count}")

        return announce.to_dict()

    except Exception as e:
        logger.debug(f"Auto-emit state_announce failed: {e}")
        return None


def maybe_emit_resonance_signal(
    agent_id: str,
    cirs_result: Dict[str, Any],
    was_resonant: bool,
) -> Optional[Dict[str, Any]]:
    """
    Auto-emit RESONANCE_ALERT or STABILITY_RESTORED on state transitions.

    Called from process_agent_update after the AdaptiveGovernor runs.
    Only emits on transitions to avoid flooding the buffer.

    Args:
        agent_id: Agent identifier
        cirs_result: Result dict from AdaptiveGovernor.update()
        was_resonant: Previous resonant state (from GovernorState.was_resonant)

    Returns:
        Signal dict if emitted, None otherwise
    """
    resonant = cirs_result.get("resonant", False)

    # Only emit on transitions
    if resonant == was_resonant:
        return None

    if resonant and not was_resonant:
        # Entering resonance -> emit RESONANCE_ALERT
        alert = ResonanceAlert(
            agent_id=agent_id,
            timestamp=datetime.utcnow().isoformat(),
            oi=float(cirs_result.get("oi", 0.0)),
            phase=str(cirs_result.get("phase", "unknown")),
            tau_current=float(cirs_result.get("tau", 0.40)),
            beta_current=float(cirs_result.get("beta", 0.60)),
            flips=int(cirs_result.get("flips", 0)),
        )
        _emit_resonance_alert(alert)
        logger.info(
            f"[CIRS/AUTO_EMIT] RESONANCE_ALERT: agent={agent_id}, "
            f"OI={alert.oi:.3f}, trigger={cirs_result.get('trigger')}"
        )
        return alert.to_dict()

    else:
        # Exiting resonance -> emit STABILITY_RESTORED
        restored = StabilityRestored(
            agent_id=agent_id,
            timestamp=datetime.utcnow().isoformat(),
            oi=float(cirs_result.get("oi", 0.0)),
            tau_settled=float(cirs_result.get("tau", 0.40)),
            beta_settled=float(cirs_result.get("beta", 0.60)),
        )
        _emit_stability_restored(restored)
        logger.info(
            f"[CIRS/AUTO_EMIT] STABILITY_RESTORED: agent={agent_id}, "
            f"OI={restored.oi:.3f}"
        )
        return restored.to_dict()


def maybe_apply_neighbor_pressure(
    agent_id: str,
    governor,  # AdaptiveGovernor instance
) -> None:
    """
    Apply neighbor pressure from peer resonance alerts.

    Reads recent RESONANCE_ALERT signals from other agents.
    For each alert, looks up coherence similarity. If similar enough,
    applies defensive threshold tightening to the local governor.

    Also decays pressure on STABILITY_RESTORED signals.

    Args:
        agent_id: This agent's identifier (to exclude self-alerts)
        governor: The agent's AdaptiveGovernor instance
    """
    if governor is None:
        return

    # Get recent resonance signals (last 30 min)
    signals = _get_recent_resonance_signals(max_age_minutes=30)

    for signal in signals:
        peer_id = signal.get("agent_id")

        # Skip self
        if peer_id == agent_id:
            continue

        signal_type = signal.get("type")

        if signal_type == "RESONANCE_ALERT":
            # Look up coherence similarity (check both directions)
            similarity = _lookup_similarity(agent_id, peer_id)
            if similarity is not None:
                governor.apply_neighbor_pressure(similarity=similarity)
                logger.debug(
                    f"[CIRS/NEIGHBOR] Pressure applied to {agent_id} "
                    f"from {peer_id} (similarity={similarity:.3f})"
                )

        elif signal_type == "STABILITY_RESTORED":
            # Decay pressure from this stabilized peer
            governor.decay_neighbor_pressure()
            logger.debug(
                f"[CIRS/NEIGHBOR] Pressure decayed for {agent_id} "
                f"(peer {peer_id} stabilized)"
            )


def _lookup_similarity(agent_id: str, peer_id: str) -> Optional[float]:
    """
    Look up pairwise coherence similarity between two agents.

    Checks both directions in the coherence report buffer.
    Returns None if no report exists (conservative: don't guess).
    """
    # Check agent->peer direction
    key = f"{agent_id}:{peer_id}"
    report = _coherence_report_buffer.get(key)
    if report:
        return report.get("similarity_score")

    # Check peer->agent direction
    key_reverse = f"{peer_id}:{agent_id}"
    report_reverse = _coherence_report_buffer.get(key_reverse)
    if report_reverse:
        return report_reverse.get("similarity_score")

    return None


# =============================================================================
# COHERENCE_REPORT Data Structures
# =============================================================================

@dataclass
class CoherenceReport:
    """
    COHERENCE_REPORT message structure per UARG Whitepaper.

    Shares pairwise similarity metrics between agents for multi-agent coordination.
    Maps to trajectory similarity in trajectory identity theory.

    Fields:
        source_agent_id: Agent computing the report
        timestamp: ISO timestamp of report
        target_agent_id: Agent being compared to (or 'all' for fleet comparison)
        similarity_score: 0-1 overall similarity (trajectory distance inverse)
        eisv_similarity: Per-dimension EISV similarity
        trajectory_similarity: Optional trajectory signature comparison
        regime_match: Whether agents are in same operational regime
        verdict_match: Whether agents have same governance verdict
        recommendation: Suggested coordination action
    """
    source_agent_id: str
    timestamp: str
    target_agent_id: str
    similarity_score: float
    eisv_similarity: Dict[str, float]
    regime_match: bool
    verdict_match: bool
    trajectory_similarity: Optional[Dict[str, float]] = None
    recommendation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "source_agent_id": self.source_agent_id,
            "timestamp": self.timestamp,
            "target_agent_id": self.target_agent_id,
            "similarity_score": self.similarity_score,
            "eisv_similarity": self.eisv_similarity,
            "regime_match": self.regime_match,
            "verdict_match": self.verdict_match,
        }
        if self.trajectory_similarity:
            result["trajectory_similarity"] = self.trajectory_similarity
        if self.recommendation:
            result["recommendation"] = self.recommendation
        return result


# Thread-safe storage for coherence reports (last report per agent pair)
# Key: "source_agent_id:target_agent_id", Value: CoherenceReport dict
_coherence_report_buffer: Dict[str, Dict[str, Any]] = {}
COHERENCE_REPORT_TTL_HOURS = 1


def _cleanup_old_coherence_reports():
    """Remove coherence reports older than TTL"""
    cutoff = datetime.now() - timedelta(hours=COHERENCE_REPORT_TTL_HOURS)
    cutoff_iso = cutoff.isoformat()

    stale_keys = [
        key for key, report in _coherence_report_buffer.items()
        if report["timestamp"] < cutoff_iso
    ]
    for key in stale_keys:
        del _coherence_report_buffer[key]


def _store_coherence_report(report: CoherenceReport):
    """Store a coherence report (overwrites previous for same pair)"""
    _cleanup_old_coherence_reports()
    key = f"{report.source_agent_id}:{report.target_agent_id}"
    _coherence_report_buffer[key] = report.to_dict()
    logger.debug(f"[CIRS/COHERENCE_REPORT] {report.source_agent_id} -> {report.target_agent_id}: similarity={report.similarity_score:.3f}")


def _get_coherence_reports(
    source_agent_id: Optional[str] = None,
    target_agent_id: Optional[str] = None,
    min_similarity: Optional[float] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Query recent coherence reports.

    Args:
        source_agent_id: Filter by source agent
        target_agent_id: Filter by target agent
        min_similarity: Only return reports with similarity >= this value
        limit: Maximum results

    Returns:
        List of coherence report dicts, sorted by similarity (highest first)
    """
    _cleanup_old_coherence_reports()

    results = []
    for key, report in _coherence_report_buffer.items():
        if source_agent_id and report["source_agent_id"] != source_agent_id:
            continue
        if target_agent_id and report["target_agent_id"] != target_agent_id:
            continue
        if min_similarity is not None and report.get("similarity_score", 0) < min_similarity:
            continue
        results.append(report)

    # Sort by similarity (highest first)
    results.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)

    return results[:limit]


# =============================================================================
# COHERENCE_REPORT Tool Handler
# =============================================================================

@mcp_tool("coherence_report", timeout=15.0, register=False, description="CIRS Protocol: Compute and share pairwise similarity metrics between agents")
async def handle_coherence_report(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    CIRS COHERENCE_REPORT - Multi-agent similarity analysis.

    Computes pairwise similarity metrics between agents based on EISV state
    and trajectory signatures. Essential for multi-agent coordination.

    Two modes:
    1. COMPUTE mode (action='compute'): Compute similarity to another agent
       - Returns detailed EISV and trajectory similarity breakdown
       - Stores report for peer access

    2. QUERY mode (action='query'): Get recent coherence reports
       - Find agents similar to you
       - Identify potential coordination partners

    Args:
        action: 'compute' | 'query' (required)

        For compute:
            target_agent_id: Agent to compare against (required)

        For query:
            source_agent_id: Filter by source agent (optional)
            target_agent_id: Filter by target agent (optional)
            min_similarity: Only reports with similarity >= this (optional)
            limit: Max results (default: 50)

    Returns:
        For compute: Detailed similarity report
        For query: List of recent coherence reports

    Example compute:
        coherence_report(action='compute', target_agent_id='other-agent-uuid')

    Example query:
        coherence_report(action='query', min_similarity=0.7)
    """
    action = arguments.get("action", "").lower()

    if not action or action not in ("compute", "query"):
        return [error_response(
            "action parameter required: 'compute' or 'query'",
            recovery={
                "valid_actions": ["compute", "query"],
                "compute_example": "coherence_report(action='compute', target_agent_id='...')",
                "query_example": "coherence_report(action='query', min_similarity=0.7)"
            }
        )]

    if action == "compute":
        return await _handle_coherence_report_compute(arguments)
    else:
        return await _handle_coherence_report_query(arguments)


async def _handle_coherence_report_compute(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle COHERENCE_REPORT compute action"""
    # Require registered agent for compute
    source_agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    target_agent_id = arguments.get("target_agent_id")
    if not target_agent_id:
        return [error_response(
            "target_agent_id required for compute action",
            recovery={
                "action": "Provide target_agent_id parameter",
                "example": "coherence_report(action='compute', target_agent_id='other-agent')"
            }
        )]

    mcp_server = get_mcp_server()

    # Get source agent state
    source_monitor = mcp_server.get_or_create_monitor(source_agent_id)
    source_metrics = source_monitor.get_metrics()

    # Get target agent state
    target_monitor = mcp_server.monitors.get(target_agent_id)
    if target_monitor is None:
        # Try to load from disk
        import asyncio
        loop = asyncio.get_running_loop()
        persisted_state = await loop.run_in_executor(None, mcp_server.load_monitor_state, target_agent_id)
        if persisted_state:
            from src.governance_monitor import UNITARESMonitor
            target_monitor = UNITARESMonitor(target_agent_id, load_state=False)
            target_monitor.state = persisted_state
        else:
            return [error_response(
                f"Target agent '{target_agent_id}' not found or has no state",
                recovery={
                    "action": "Ensure target agent exists and has been initialized",
                    "related_tools": ["list_agents", "state_announce(action='query')"]
                }
            )]

    target_metrics = target_monitor.get_metrics()

    # Compute EISV similarity (inverse of normalized distance)
    source_eisv = {
        "E": float(source_metrics.get("E", 0.7)),
        "I": float(source_metrics.get("I", 0.8)),
        "S": float(source_metrics.get("S", 0.2)),
        "V": float(source_metrics.get("V", 0.0)),
    }
    target_eisv = {
        "E": float(target_metrics.get("E", 0.7)),
        "I": float(target_metrics.get("I", 0.8)),
        "S": float(target_metrics.get("S", 0.2)),
        "V": float(target_metrics.get("V", 0.0)),
    }

    eisv_similarity = {}
    for dim in ["E", "I", "S", "V"]:
        diff = abs(source_eisv[dim] - target_eisv[dim])
        # Similarity = 1 - normalized difference (V can be negative, so handle range)
        if dim == "V":
            # V typically ranges from -0.2 to 0.2
            sim = 1.0 - min(1.0, diff / 0.4)
        else:
            # E, I, S range from 0 to 1
            sim = 1.0 - diff
        eisv_similarity[dim] = round(sim, 3)

    # Overall EISV similarity (weighted average)
    overall_eisv_sim = (
        eisv_similarity["E"] * 0.25 +
        eisv_similarity["I"] * 0.35 +  # I weighted higher (integrity matters more)
        eisv_similarity["S"] * 0.25 +
        eisv_similarity["V"] * 0.15   # V weighted lower (more volatile)
    )

    # Check regime and verdict match
    source_regime = str(source_metrics.get("regime", "divergence"))
    target_regime = str(target_metrics.get("regime", "divergence"))
    regime_match = source_regime == target_regime

    source_verdict = str(source_metrics.get("verdict", "caution"))
    target_verdict = str(target_metrics.get("verdict", "caution"))
    verdict_match = source_verdict == target_verdict

    # Compute trajectory similarity if both have state
    trajectory_similarity = None
    try:
        source_state = source_monitor.state
        target_state = target_monitor.state

        # Compare key trajectory components
        traj_sims = {}

        # Lambda1 similarity (behavioral adaptation)
        lambda_diff = abs(float(source_state.lambda1) - float(target_state.lambda1))
        traj_sims["lambda1"] = 1.0 - min(1.0, lambda_diff / 2.0)

        # Coherence similarity
        coh_diff = abs(float(source_state.coherence) - float(target_state.coherence))
        traj_sims["coherence"] = 1.0 - coh_diff

        # Update count similarity (normalized)
        max_updates = max(source_state.update_count, target_state.update_count, 1)
        update_diff = abs(source_state.update_count - target_state.update_count)
        traj_sims["maturity"] = 1.0 - min(1.0, update_diff / max_updates)

        trajectory_similarity = {k: round(v, 3) for k, v in traj_sims.items()}
    except Exception as e:
        logger.debug(f"Could not compute trajectory similarity: {e}")

    # Compute overall similarity score
    traj_factor = 1.0
    if trajectory_similarity:
        traj_factor = sum(trajectory_similarity.values()) / len(trajectory_similarity)

    similarity_score = round(
        overall_eisv_sim * 0.6 +
        traj_factor * 0.2 +
        (0.1 if regime_match else 0.0) +
        (0.1 if verdict_match else 0.0),
        3
    )

    # Generate recommendation
    recommendation = _generate_coherence_recommendation(
        similarity_score, regime_match, verdict_match,
        source_regime, target_regime
    )

    # Create and store the report
    report = CoherenceReport(
        source_agent_id=source_agent_id,
        timestamp=datetime.now().isoformat(),
        target_agent_id=target_agent_id,
        similarity_score=similarity_score,
        eisv_similarity=eisv_similarity,
        regime_match=regime_match,
        verdict_match=verdict_match,
        trajectory_similarity=trajectory_similarity,
        recommendation=recommendation
    )

    _store_coherence_report(report)

    return success_response({
        "action": "compute",
        "report": report.to_dict(),
        "details": {
            "source_eisv": source_eisv,
            "target_eisv": target_eisv,
            "source_regime": source_regime,
            "target_regime": target_regime,
            "source_verdict": source_verdict,
            "target_verdict": target_verdict,
        },
        "message": f"Coherence report: {similarity_score:.1%} similarity with {target_agent_id}",
        "cirs_protocol": "COHERENCE_REPORT"
    }, agent_id=source_agent_id)


async def _handle_coherence_report_query(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle COHERENCE_REPORT query action"""
    source_agent_id = arguments.get("source_agent_id")
    target_agent_id = arguments.get("target_agent_id")
    min_similarity = arguments.get("min_similarity")
    limit = int(arguments.get("limit", 50))

    if min_similarity is not None:
        min_similarity = float(min_similarity)

    reports = _get_coherence_reports(
        source_agent_id=source_agent_id,
        target_agent_id=target_agent_id,
        min_similarity=min_similarity,
        limit=limit
    )

    # Compute summary
    summary = {
        "total_reports": len(reports),
        "avg_similarity": sum(r.get("similarity_score", 0) for r in reports) / len(reports) if reports else 0,
        "regime_matches": sum(1 for r in reports if r.get("regime_match")),
        "verdict_matches": sum(1 for r in reports if r.get("verdict_match")),
    }

    return success_response({
        "action": "query",
        "reports": reports,
        "summary": summary,
        "cirs_protocol": "COHERENCE_REPORT",
        "filters_applied": {
            "source_agent_id": source_agent_id,
            "target_agent_id": target_agent_id,
            "min_similarity": min_similarity,
            "limit": limit
        }
    })


def _generate_coherence_recommendation(
    similarity: float,
    regime_match: bool,
    verdict_match: bool,
    source_regime: str,
    target_regime: str
) -> str:
    """Generate coordination recommendation based on similarity metrics"""
    if similarity >= 0.8:
        if regime_match and verdict_match:
            return "High alignment - potential for direct collaboration or task delegation"
        elif regime_match:
            return "Same regime, different verdict - coordinate on risk assessment"
        else:
            return "High EISV similarity despite regime difference - monitor for convergence"

    elif similarity >= 0.6:
        if regime_match:
            return "Moderate alignment in same regime - share learnings, coordinate approach"
        else:
            return "Moderate similarity, different regimes - complementary capabilities possible"

    elif similarity >= 0.4:
        if verdict_match:
            return "Different EISV patterns but same verdict - diverse perspectives on similar problems"
        else:
            return "Low-moderate alignment - limited coordination value unless contexts align"

    else:
        return "Low similarity - independent operation recommended, minimal coordination overhead"


# =============================================================================
# BOUNDARY_CONTRACT Data Structures
# =============================================================================

class TrustLevel(str, Enum):
    """Trust levels for boundary contracts"""
    FULL = "full"           # Full trust - share all state, accept delegations
    PARTIAL = "partial"     # Partial trust - share EISV, limited delegation
    OBSERVE = "observe"     # Observe only - share state, no delegation
    NONE = "none"           # No trust - minimal interaction


class VoidResponsePolicy(str, Enum):
    """How to respond when peer enters void state"""
    NOTIFY = "notify"       # Send alert, continue operation
    ASSIST = "assist"       # Offer assistance, share resources
    ISOLATE = "isolate"     # Reduce interaction until void resolves
    COORDINATE = "coordinate"  # Active coordination to help resolve


@dataclass
class BoundaryContract:
    """
    BOUNDARY_CONTRACT message structure per UARG Whitepaper.

    Declares trust policies and void response rules between agents.
    Establishes the "social contract" for multi-agent coordination.

    Fields:
        agent_id: Agent declaring the contract
        timestamp: ISO timestamp of contract
        trust_default: Default trust level for unknown agents
        trust_overrides: Specific trust levels for known agents
        void_response_policy: How to respond to peer void states
        max_delegation_complexity: Maximum complexity of delegated tasks (0-1)
        accept_coherence_threshold: Minimum coherence to accept delegations
        boundary_violations: Count of boundary violations detected
    """
    agent_id: str
    timestamp: str
    trust_default: TrustLevel
    trust_overrides: Dict[str, str]  # agent_id -> TrustLevel value
    void_response_policy: VoidResponsePolicy
    max_delegation_complexity: float
    accept_coherence_threshold: float
    boundary_violations: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "trust_default": self.trust_default.value,
            "trust_overrides": self.trust_overrides,
            "void_response_policy": self.void_response_policy.value,
            "max_delegation_complexity": self.max_delegation_complexity,
            "accept_coherence_threshold": self.accept_coherence_threshold,
            "boundary_violations": self.boundary_violations,
        }


# Storage for boundary contracts (one per agent)
_boundary_contract_buffer: Dict[str, Dict[str, Any]] = {}


def _store_boundary_contract(contract: BoundaryContract):
    """Store a boundary contract (overwrites previous for same agent)"""
    _boundary_contract_buffer[contract.agent_id] = contract.to_dict()
    logger.debug(f"[CIRS/BOUNDARY_CONTRACT] agent={contract.agent_id}, trust_default={contract.trust_default.value}")


def _get_boundary_contract(agent_id: str) -> Optional[Dict[str, Any]]:
    """Get boundary contract for an agent"""
    return _boundary_contract_buffer.get(agent_id)


def _get_all_boundary_contracts() -> List[Dict[str, Any]]:
    """Get all boundary contracts"""
    return list(_boundary_contract_buffer.values())


# =============================================================================
# BOUNDARY_CONTRACT Tool Handler
# =============================================================================

@mcp_tool("boundary_contract", timeout=10.0, register=False, description="CIRS Protocol: Declare trust policies and void response rules for multi-agent coordination")
async def handle_boundary_contract(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    CIRS BOUNDARY_CONTRACT - Multi-agent trust and boundary management.

    Declares trust policies and void response rules. Establishes how this
    agent interacts with peers in the multi-agent ecosystem.

    Three modes:
    1. SET mode (action='set'): Declare your boundary contract
       - Set default trust level for unknown agents
       - Override trust for specific known agents
       - Define void response policy

    2. GET mode (action='get'): Get an agent's boundary contract
       - See how a specific agent has declared trust policies
       - Useful for understanding interaction boundaries

    3. LIST mode (action='list'): List all boundary contracts
       - See the multi-agent trust landscape
       - Identify potential coordination partners

    Args:
        action: 'set' | 'get' | 'list' (required)

        For set:
            trust_default: 'full' | 'partial' | 'observe' | 'none' (default: 'partial')
            trust_overrides: Dict mapping agent_ids to trust levels (optional)
            void_response_policy: 'notify' | 'assist' | 'isolate' | 'coordinate' (default: 'notify')
            max_delegation_complexity: 0.0-1.0 (default: 0.5)
            accept_coherence_threshold: 0.0-1.0 (default: 0.4)

        For get:
            target_agent_id: Agent to get contract for (required)

    Returns:
        For set: Confirmation with contract details
        For get: Agent's boundary contract
        For list: All boundary contracts

    Example set:
        boundary_contract(action='set', trust_default='partial', void_response_policy='assist')

    Example get:
        boundary_contract(action='get', target_agent_id='other-agent')
    """
    action = arguments.get("action", "").lower()

    if not action or action not in ("set", "get", "list"):
        return [error_response(
            "action parameter required: 'set', 'get', or 'list'",
            recovery={
                "valid_actions": ["set", "get", "list"],
                "set_example": "boundary_contract(action='set', trust_default='partial')",
                "get_example": "boundary_contract(action='get', target_agent_id='...')"
            }
        )]

    if action == "set":
        return await _handle_boundary_contract_set(arguments)
    elif action == "get":
        return await _handle_boundary_contract_get(arguments)
    else:
        return await _handle_boundary_contract_list(arguments)


async def _handle_boundary_contract_set(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle BOUNDARY_CONTRACT set action"""
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    # Parse trust_default
    trust_default_str = arguments.get("trust_default", "partial").lower()
    valid_trust = ["full", "partial", "observe", "none"]
    if trust_default_str not in valid_trust:
        return [error_response(
            f"Invalid trust_default: {trust_default_str}",
            recovery={"valid_values": valid_trust}
        )]
    trust_default = TrustLevel(trust_default_str)

    # Parse trust_overrides
    trust_overrides = arguments.get("trust_overrides", {})
    if trust_overrides:
        for target_id, level in trust_overrides.items():
            if level.lower() not in valid_trust:
                return [error_response(
                    f"Invalid trust level '{level}' for agent '{target_id}'",
                    recovery={"valid_values": valid_trust}
                )]
        trust_overrides = {k: v.lower() for k, v in trust_overrides.items()}

    # Parse void_response_policy
    void_policy_str = arguments.get("void_response_policy", "notify").lower()
    valid_policies = ["notify", "assist", "isolate", "coordinate"]
    if void_policy_str not in valid_policies:
        return [error_response(
            f"Invalid void_response_policy: {void_policy_str}",
            recovery={"valid_values": valid_policies}
        )]
    void_response_policy = VoidResponsePolicy(void_policy_str)

    # Parse complexity and coherence thresholds
    max_delegation_complexity = float(arguments.get("max_delegation_complexity", 0.5))
    max_delegation_complexity = max(0.0, min(1.0, max_delegation_complexity))

    accept_coherence_threshold = float(arguments.get("accept_coherence_threshold", 0.4))
    accept_coherence_threshold = max(0.0, min(1.0, accept_coherence_threshold))

    # Get existing contract to preserve violation count
    existing = _get_boundary_contract(agent_id)
    boundary_violations = existing.get("boundary_violations", 0) if existing else 0

    # Create and store contract
    contract = BoundaryContract(
        agent_id=agent_id,
        timestamp=datetime.now().isoformat(),
        trust_default=trust_default,
        trust_overrides=trust_overrides,
        void_response_policy=void_response_policy,
        max_delegation_complexity=max_delegation_complexity,
        accept_coherence_threshold=accept_coherence_threshold,
        boundary_violations=boundary_violations
    )

    _store_boundary_contract(contract)

    return success_response({
        "action": "set",
        "contract": contract.to_dict(),
        "message": f"Boundary contract set: trust_default={trust_default.value}, void_policy={void_response_policy.value}",
        "cirs_protocol": "BOUNDARY_CONTRACT"
    }, agent_id=agent_id)


async def _handle_boundary_contract_get(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle BOUNDARY_CONTRACT get action"""
    target_agent_id = arguments.get("target_agent_id")
    if not target_agent_id:
        return [error_response(
            "target_agent_id required for get action",
            recovery={"example": "boundary_contract(action='get', target_agent_id='...')"}
        )]

    contract = _get_boundary_contract(target_agent_id)
    if not contract:
        return [error_response(
            f"No boundary contract found for agent '{target_agent_id}'",
            recovery={
                "note": "Agent has not declared a boundary contract",
                "suggestion": "Use default trust assumptions or ask agent to set contract",
                "default_assumption": {
                    "trust_default": "partial",
                    "void_response_policy": "notify"
                }
            }
        )]

    return success_response({
        "action": "get",
        "contract": contract,
        "cirs_protocol": "BOUNDARY_CONTRACT"
    })


async def _handle_boundary_contract_list(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle BOUNDARY_CONTRACT list action"""
    contracts = _get_all_boundary_contracts()

    # Compute summary
    trust_distribution = {}
    policy_distribution = {}
    for c in contracts:
        trust = c.get("trust_default", "unknown")
        policy = c.get("void_response_policy", "unknown")
        trust_distribution[trust] = trust_distribution.get(trust, 0) + 1
        policy_distribution[policy] = policy_distribution.get(policy, 0) + 1

    summary = {
        "total_contracts": len(contracts),
        "trust_distribution": trust_distribution,
        "policy_distribution": policy_distribution,
    }

    return success_response({
        "action": "list",
        "contracts": contracts,
        "summary": summary,
        "cirs_protocol": "BOUNDARY_CONTRACT"
    })


# =============================================================================
# GOVERNANCE_ACTION Data Structures
# =============================================================================

class GovernanceActionType(str, Enum):
    """Types of governance actions for multi-agent coordination"""
    VOID_INTERVENTION = "void_intervention"    # Help agent exit void state
    COHERENCE_BOOST = "coherence_boost"        # Share resources to improve coherence
    DELEGATION_REQUEST = "delegation_request"  # Request task delegation
    DELEGATION_RESPONSE = "delegation_response"  # Response to delegation request
    COORDINATION_SYNC = "coordination_sync"    # Sync on shared task progress


@dataclass
class GovernanceAction:
    """
    GOVERNANCE_ACTION message structure per UARG Whitepaper.

    Coordinates interventions across agents. Enables collaborative
    governance when individual agents face challenges.

    Fields:
        action_id: Unique action identifier
        timestamp: ISO timestamp of action
        action_type: Type of governance action
        initiator_agent_id: Agent initiating the action
        target_agent_id: Agent targeted by the action
        payload: Action-specific data
        status: pending | accepted | rejected | completed
        response: Response from target agent (if any)
    """
    action_id: str
    timestamp: str
    action_type: GovernanceActionType
    initiator_agent_id: str
    target_agent_id: str
    payload: Dict[str, Any]
    status: str = "pending"
    response: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "action_id": self.action_id,
            "timestamp": self.timestamp,
            "action_type": self.action_type.value,
            "initiator_agent_id": self.initiator_agent_id,
            "target_agent_id": self.target_agent_id,
            "payload": self.payload,
            "status": self.status,
        }
        if self.response:
            result["response"] = self.response
        return result


# Storage for governance actions (by action_id)
_governance_action_buffer: Dict[str, Dict[str, Any]] = {}
GOVERNANCE_ACTION_TTL_HOURS = 24


def _cleanup_old_governance_actions():
    """Remove old governance actions"""
    cutoff = datetime.now() - timedelta(hours=GOVERNANCE_ACTION_TTL_HOURS)
    cutoff_iso = cutoff.isoformat()

    stale_ids = [
        aid for aid, action in _governance_action_buffer.items()
        if action["timestamp"] < cutoff_iso
    ]
    for aid in stale_ids:
        del _governance_action_buffer[aid]


def _store_governance_action(action: GovernanceAction):
    """Store a governance action"""
    _cleanup_old_governance_actions()
    _governance_action_buffer[action.action_id] = action.to_dict()
    logger.info(f"[CIRS/GOVERNANCE_ACTION] {action.action_type.value}: {action.initiator_agent_id} -> {action.target_agent_id}")


def _get_governance_action(action_id: str) -> Optional[Dict[str, Any]]:
    """Get a governance action by ID"""
    return _governance_action_buffer.get(action_id)


def _get_governance_actions_for_agent(
    agent_id: str,
    as_initiator: bool = True,
    as_target: bool = True,
    status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get governance actions involving an agent"""
    _cleanup_old_governance_actions()

    results = []
    for action in _governance_action_buffer.values():
        is_initiator = action["initiator_agent_id"] == agent_id
        is_target = action["target_agent_id"] == agent_id

        if (as_initiator and is_initiator) or (as_target and is_target):
            if status is None or action["status"] == status:
                results.append(action)

    # Sort by timestamp (newest first)
    results.sort(key=lambda x: x["timestamp"], reverse=True)
    return results


# =============================================================================
# GOVERNANCE_ACTION Tool Handler
# =============================================================================

@mcp_tool("governance_action", timeout=15.0, register=False, description="CIRS Protocol: Coordinate interventions across agents for collaborative governance")
async def handle_governance_action(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    CIRS GOVERNANCE_ACTION - Multi-agent intervention coordination.

    Enables collaborative governance when agents need assistance.
    Supports void interventions, coherence boosts, and task delegation.

    Four modes:
    1. INITIATE mode (action='initiate'): Start a governance action
       - Request help from another agent
       - Offer assistance to struggling agent

    2. RESPOND mode (action='respond'): Respond to a governance action
       - Accept or reject incoming requests
       - Provide response data

    3. QUERY mode (action='query'): Get governance actions for an agent
       - See pending requests/offers
       - Track action history

    4. STATUS mode (action='status'): Get status of a specific action
       - Check if action was accepted/rejected
       - Get response details

    Args:
        action: 'initiate' | 'respond' | 'query' | 'status' (required)

        For initiate:
            action_type: 'void_intervention' | 'coherence_boost' | 'delegation_request' | 'coordination_sync'
            target_agent_id: Agent to target (required)
            payload: Action-specific data (optional)

        For respond:
            action_id: Action to respond to (required)
            accept: True to accept, False to reject
            response_data: Additional response data (optional)

        For query:
            as_initiator: Include actions where you're initiator (default: True)
            as_target: Include actions where you're target (default: True)
            status_filter: Filter by status (optional)

        For status:
            action_id: Action to check (required)

    Returns:
        Action details and status

    Example initiate:
        governance_action(action='initiate', action_type='void_intervention', target_agent_id='...')

    Example respond:
        governance_action(action='respond', action_id='...', accept=True)
    """
    action = arguments.get("action", "").lower()

    if not action or action not in ("initiate", "respond", "query", "status"):
        return [error_response(
            "action parameter required: 'initiate', 'respond', 'query', or 'status'",
            recovery={
                "valid_actions": ["initiate", "respond", "query", "status"],
                "initiate_example": "governance_action(action='initiate', action_type='void_intervention', target_agent_id='...')",
                "respond_example": "governance_action(action='respond', action_id='...', accept=True)"
            }
        )]

    if action == "initiate":
        return await _handle_governance_action_initiate(arguments)
    elif action == "respond":
        return await _handle_governance_action_respond(arguments)
    elif action == "query":
        return await _handle_governance_action_query(arguments)
    else:
        return await _handle_governance_action_status(arguments)


async def _handle_governance_action_initiate(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle GOVERNANCE_ACTION initiate"""
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    # Parse action_type
    action_type_str = arguments.get("action_type", "").lower()
    valid_types = ["void_intervention", "coherence_boost", "delegation_request", "delegation_response", "coordination_sync"]
    if not action_type_str or action_type_str not in valid_types:
        return [error_response(
            f"Invalid or missing action_type: {action_type_str}",
            recovery={"valid_values": valid_types}
        )]
    action_type = GovernanceActionType(action_type_str)

    target_agent_id = arguments.get("target_agent_id")
    if not target_agent_id:
        return [error_response(
            "target_agent_id required for initiate action",
            recovery={"example": "governance_action(action='initiate', action_type='...', target_agent_id='...')"}
        )]

    # Check target's boundary contract for acceptance
    target_contract = _get_boundary_contract(target_agent_id)
    trust_warning = None
    if target_contract:
        # Check if initiator is trusted
        trust_level = target_contract.get("trust_overrides", {}).get(agent_id)
        if trust_level is None:
            trust_level = target_contract.get("trust_default", "partial")

        if trust_level == "none":
            return [error_response(
                f"Target agent '{target_agent_id}' has trust level 'none' for you",
                recovery={
                    "note": "Target does not accept interactions from this agent",
                    "suggestion": "Contact target through other channels to establish trust"
                }
            )]
        elif trust_level == "observe":
            trust_warning = "Target agent has 'observe' trust level - may reject active interventions"

    # Generate action ID
    import uuid
    action_id = str(uuid.uuid4())[:12]

    # Get payload
    payload = arguments.get("payload", {})

    # For void_intervention, add initiator's current state
    if action_type == GovernanceActionType.VOID_INTERVENTION:
        mcp_server = get_mcp_server()
        monitor = mcp_server.get_or_create_monitor(agent_id)
        metrics = monitor.get_metrics()
        payload["initiator_state"] = {
            "coherence": float(metrics.get("coherence", 0.5)),
            "risk_score": float(metrics.get("risk_score") or 0.3),
            "verdict": str(metrics.get("verdict", "caution"))
        }

    # Create and store action
    gov_action = GovernanceAction(
        action_id=action_id,
        timestamp=datetime.now().isoformat(),
        action_type=action_type,
        initiator_agent_id=agent_id,
        target_agent_id=target_agent_id,
        payload=payload,
        status="pending"
    )

    _store_governance_action(gov_action)

    response = {
        "action": "initiate",
        "governance_action": gov_action.to_dict(),
        "message": f"Governance action '{action_type.value}' initiated for {target_agent_id}",
        "cirs_protocol": "GOVERNANCE_ACTION"
    }

    if trust_warning:
        response["warning"] = trust_warning

    return success_response(response, agent_id=agent_id)


async def _handle_governance_action_respond(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle GOVERNANCE_ACTION respond"""
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    action_id = arguments.get("action_id")
    if not action_id:
        return [error_response(
            "action_id required for respond action",
            recovery={"example": "governance_action(action='respond', action_id='...', accept=True)"}
        )]

    gov_action = _get_governance_action(action_id)
    if not gov_action:
        return [error_response(
            f"Governance action '{action_id}' not found",
            recovery={"suggestion": "Use governance_action(action='query') to see your pending actions"}
        )]

    # Verify agent is the target
    if gov_action["target_agent_id"] != agent_id:
        return [error_response(
            "You are not the target of this governance action",
            recovery={"note": f"Target is {gov_action['target_agent_id']}"}
        )]

    # Check if already responded
    if gov_action["status"] != "pending":
        return [error_response(
            f"Action already has status '{gov_action['status']}'",
            recovery={"note": "Cannot respond to non-pending actions"}
        )]

    # Process response
    accept = arguments.get("accept", False)
    response_data = arguments.get("response_data", {})

    new_status = "accepted" if accept else "rejected"
    gov_action["status"] = new_status
    gov_action["response"] = {
        "responder_agent_id": agent_id,
        "accepted": accept,
        "response_time": datetime.now().isoformat(),
        "data": response_data
    }

    # Update storage
    _governance_action_buffer[action_id] = gov_action

    return success_response({
        "action": "respond",
        "governance_action": gov_action,
        "message": f"Governance action {new_status}: {gov_action['action_type']}",
        "cirs_protocol": "GOVERNANCE_ACTION"
    }, agent_id=agent_id)


async def _handle_governance_action_query(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle GOVERNANCE_ACTION query"""
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    as_initiator = arguments.get("as_initiator", True)
    as_target = arguments.get("as_target", True)
    status_filter = arguments.get("status_filter")

    actions = _get_governance_actions_for_agent(
        agent_id,
        as_initiator=as_initiator,
        as_target=as_target,
        status=status_filter
    )

    # Compute summary
    pending = sum(1 for a in actions if a["status"] == "pending")
    accepted = sum(1 for a in actions if a["status"] == "accepted")
    rejected = sum(1 for a in actions if a["status"] == "rejected")

    summary = {
        "total_actions": len(actions),
        "pending": pending,
        "accepted": accepted,
        "rejected": rejected,
    }

    return success_response({
        "action": "query",
        "actions": actions,
        "summary": summary,
        "cirs_protocol": "GOVERNANCE_ACTION"
    }, agent_id=agent_id)


async def _handle_governance_action_status(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle GOVERNANCE_ACTION status"""
    action_id = arguments.get("action_id")
    if not action_id:
        return [error_response(
            "action_id required for status action",
            recovery={"example": "governance_action(action='status', action_id='...')"}
        )]

    gov_action = _get_governance_action(action_id)
    if not gov_action:
        return [error_response(
            f"Governance action '{action_id}' not found",
            recovery={"note": "Action may have expired (24h TTL)"}
        )]

    return success_response({
        "action": "status",
        "governance_action": gov_action,
        "cirs_protocol": "GOVERNANCE_ACTION"
    })


# =============================================================================
# RESONANCE_ALERT Tool Handler
# =============================================================================

@mcp_tool("resonance_alert", timeout=10.0, register=False, description="CIRS Protocol: Emit or query resonance alerts for multi-agent oscillation coordination")
async def handle_resonance_alert(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    CIRS RESONANCE_ALERT - Multi-agent oscillation coordination.

    Emitted when an agent's governor detects sustained oscillation.
    Peers with high similarity should tighten thresholds defensively.

    Two modes:
    1. EMIT mode (action='emit'): Broadcast a resonance alert
    2. QUERY mode (action='query'): Get recent resonance alerts

    Args:
        action: 'emit' | 'query' (default: 'query')

        For emit:
            oi: Oscillation index (default: 0.0)
            phase: Current phase (default: 'unknown')
            tau_current: Current tau threshold (default: 0.4)
            beta_current: Current beta threshold (default: 0.6)
            flips: Number of verdict flips (default: 0)
            duration_updates: How long oscillation has persisted (default: 0)

        For query:
            max_age_minutes: Look back window in minutes (default: 30)
            agent_id: Filter by source agent (optional)
    """
    action = arguments.get("action", "query").lower()

    if action == "emit":
        # Require registered agent
        agent_id, error = require_registered_agent(arguments)
        if error:
            return [error]

        alert = ResonanceAlert(
            agent_id=agent_id,
            timestamp=datetime.utcnow().isoformat(),
            oi=float(arguments.get("oi", 0.0)),
            phase=str(arguments.get("phase", "unknown")),
            tau_current=float(arguments.get("tau_current", 0.4)),
            beta_current=float(arguments.get("beta_current", 0.6)),
            flips=int(arguments.get("flips", 0)),
            duration_updates=int(arguments.get("duration_updates", 0)),
        )
        _emit_resonance_alert(alert)
        return success_response(
            f"RESONANCE_ALERT emitted for {agent_id}",
            alert.to_dict()
        )

    elif action == "query":
        signals = _get_recent_resonance_signals(
            max_age_minutes=int(arguments.get("max_age_minutes", 30)),
            agent_id=arguments.get("agent_id"),
            signal_type="RESONANCE_ALERT",
        )
        return success_response({
            "action": "query",
            "alerts": signals,
            "count": len(signals),
            "cirs_protocol": "RESONANCE_ALERT",
        })

    else:
        return [error_response(
            f"Invalid action: {action}",
            recovery={"valid_actions": ["emit", "query"]}
        )]


# =============================================================================
# STABILITY_RESTORED Tool Handler
# =============================================================================

@mcp_tool("stability_restored", timeout=10.0, register=False, description="CIRS Protocol: Emit stability restored signal when agent exits resonance")
async def handle_stability_restored(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    CIRS STABILITY_RESTORED - Signal that agent has exited resonance.

    Emitted when a previously-resonating agent stabilizes. Peers should
    decay their defensive neighbor pressure.

    Args:
        oi: Current oscillation index (default: 0.0)
        tau_settled: Settled tau threshold (default: 0.4)
        beta_settled: Settled beta threshold (default: 0.6)
    """
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    restored = StabilityRestored(
        agent_id=agent_id,
        timestamp=datetime.utcnow().isoformat(),
        oi=float(arguments.get("oi", 0.0)),
        tau_settled=float(arguments.get("tau_settled", 0.4)),
        beta_settled=float(arguments.get("beta_settled", 0.6)),
    )
    _emit_stability_restored(restored)
    return success_response(
        f"STABILITY_RESTORED emitted for {agent_id}",
        restored.to_dict()
    )


# =============================================================================
# CONSOLIDATED ENTRY POINT
# =============================================================================

# Dispatch table for consolidated tool
_CIRS_DISPATCHERS = {
    "void_alert": handle_void_alert,
    "state_announce": handle_state_announce,
    "coherence_report": handle_coherence_report,
    "boundary_contract": handle_boundary_contract,
    "governance_action": handle_governance_action,
    "resonance_alert": handle_resonance_alert,
    "stability_restored": handle_stability_restored,
}


@mcp_tool("cirs_protocol", timeout=15.0, description="CIRS Protocol: Unified multi-agent coordination (void alerts, state announce, coherence, boundaries, governance)")
async def handle_cirs_protocol(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    CIRS Protocol - Unified entry point for multi-agent coordination.

    Consolidates all CIRS protocol tools into a single interface.
    Use 'protocol' to select which operation:

    Protocols:
        - void_alert: Broadcast/query void state alerts
        - state_announce: Broadcast/query EISV + trajectory state
        - coherence_report: Compute pairwise agent similarity
        - boundary_contract: Declare trust policies
        - governance_action: Coordinate interventions
        - resonance_alert: Emit/query oscillation alerts
        - stability_restored: Signal exit from resonance

    Args:
        protocol: Which CIRS protocol to use (required)
        action: The action within that protocol (emit/query/compute/set/get/etc.)
        ... (other args passed to the specific protocol handler)

    Examples:
        cirs_protocol(protocol='void_alert', action='query', limit=10)
        cirs_protocol(protocol='state_announce', action='emit')
        cirs_protocol(protocol='coherence_report', action='compute', target_agent_id='agent-123')
    """
    protocol = arguments.get("protocol")

    if not protocol:
        return [error_response(
            "Missing 'protocol' parameter",
            recovery={
                "available_protocols": list(_CIRS_DISPATCHERS.keys()),
                "example": "cirs_protocol(protocol='void_alert', action='query')"
            }
        )]

    protocol = protocol.lower().strip()

    if protocol not in _CIRS_DISPATCHERS:
        return [error_response(
            f"Unknown protocol: {protocol}",
            recovery={
                "available_protocols": list(_CIRS_DISPATCHERS.keys()),
                "example": f"cirs_protocol(protocol='void_alert', action='query')"
            }
        )]

    # Dispatch to the specific handler
    handler = _CIRS_DISPATCHERS[protocol]
    return await handler(arguments)
