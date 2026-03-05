"""
CIRS resonance_alert and stability_restored handlers.
"""

from typing import Dict, Any, Sequence
from datetime import datetime, timezone

from mcp.types import TextContent
from .decorators import mcp_tool
from .utils import success_response, error_response, require_registered_agent
from src.logging_utils import get_logger
from .cirs_types import ResonanceAlert, StabilityRestored
from .cirs_storage import (
    _emit_resonance_alert, _emit_stability_restored,
    _get_recent_resonance_signals,
)

logger = get_logger(__name__)


@mcp_tool("resonance_alert", timeout=10.0, register=False, description="CIRS Protocol: Emit or query resonance alerts for multi-agent oscillation coordination")
async def handle_resonance_alert(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    CIRS RESONANCE_ALERT - Multi-agent oscillation coordination.

    Two modes:
    1. EMIT mode (action='emit'): Broadcast a resonance alert
    2. QUERY mode (action='query'): Get recent resonance alerts
    """
    action = arguments.get("action", "query").lower()

    if action == "emit":
        agent_id, error = require_registered_agent(arguments)
        if error:
            return [error]

        alert = ResonanceAlert(
            agent_id=agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
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


@mcp_tool("stability_restored", timeout=10.0, register=False, description="CIRS Protocol: Emit stability restored signal when agent exits resonance")
async def handle_stability_restored(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    CIRS STABILITY_RESTORED - Signal that agent has exited resonance.
    """
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    restored = StabilityRestored(
        agent_id=agent_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        oi=float(arguments.get("oi", 0.0)),
        tau_settled=float(arguments.get("tau_settled", 0.4)),
        beta_settled=float(arguments.get("beta_settled", 0.6)),
    )
    _emit_stability_restored(restored)
    return success_response(
        f"STABILITY_RESTORED emitted for {agent_id}",
        restored.to_dict()
    )
