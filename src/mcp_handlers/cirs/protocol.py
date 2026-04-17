"""
CIRS Protocol Handlers - Continuity Integration and Resonance Subsystem

Re-export facade — functions have moved to focused modules.
Existing imports continue to work unchanged.

Modules:
  cirs_types              — enums and dataclasses
  cirs_storage            — in-memory message buffers and CRUD helpers
  cirs_void               — void_alert handler
  cirs_state              — state_announce handler + trajectory helpers
  cirs_hooks              — auto-emit hooks (called from process_agent_update)
  cirs_coherence          — coherence_report handler
  cirs_boundary           — boundary_contract handler
  cirs_governance_action  — governance_action handler
  cirs_resonance          — resonance_alert + stability_restored handlers
"""

from typing import Dict, Any, Sequence

from mcp.types import TextContent
from ..decorators import mcp_tool
from ..utils import error_response

# --- cirs_types (leaf) ---
from .types import (
    VoidSeverity,
    AgentRegime,
    VoidAlert,
    StateAnnounce,
    ResonanceAlert,
    StabilityRestored,
    CoherenceReport,
    TrustLevel,
    VoidResponsePolicy,
    BoundaryContract,
    GovernanceActionType,
    GovernanceAction,
)

# --- cirs_storage ---
from .storage import (
    _void_alert_buffer,
    _state_announce_buffer,
    _resonance_alert_buffer,
    _coherence_report_buffer,
    _boundary_contract_buffer,
    _governance_action_buffer,
    ALERT_TTL_HOURS,
    STATE_ANNOUNCE_TTL_HOURS,
    COHERENCE_REPORT_TTL_HOURS,
    GOVERNANCE_ACTION_TTL_HOURS,
    _cleanup_old_alerts,
    _store_void_alert,
    _get_recent_void_alerts,
    _cleanup_old_state_announces,
    _store_state_announce,
    _get_state_announces,
    _emit_resonance_alert,
    _emit_stability_restored,
    _get_recent_resonance_signals,
    _cleanup_old_coherence_reports,
    _store_coherence_report,
    _get_coherence_reports,
    _store_boundary_contract,
    _get_boundary_contract,
    _get_all_boundary_contracts,
    _cleanup_old_governance_actions,
    _store_governance_action,
    _get_governance_action,
    _get_governance_actions_for_agent,
)

# --- cirs_void ---
from .void import handle_void_alert

# --- cirs_state ---
from .state import (
    handle_state_announce,
    _compute_decision_bias,
    _compute_focus_stability,
    _compute_maturity,
    _compute_convergence_rate,
    _compute_risk_trend,
)

# --- cirs_hooks ---
from .hooks import (
    maybe_emit_void_alert,
    auto_emit_state_announce,
    maybe_emit_resonance_signal,
)

# --- cirs_coherence ---
from .coherence import (
    handle_coherence_report,
)

# --- cirs_boundary ---
from .boundary import handle_boundary_contract

# --- cirs_governance_action ---
from .governance_action import handle_governance_action

# --- cirs_resonance ---
from .resonance import handle_resonance_alert, handle_stability_restored


# =============================================================================
# CONSOLIDATED ENTRY POINT (stays here — dispatches to sub-module handlers)
# =============================================================================

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

    Use 'protocol' to select which operation:
    - void_alert, state_announce, coherence_report, boundary_contract,
      governance_action, resonance_alert, stability_restored
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
                "example": "cirs_protocol(protocol='void_alert', action='query')"
            }
        )]

    handler = _CIRS_DISPATCHERS[protocol]
    return await handler(arguments)
