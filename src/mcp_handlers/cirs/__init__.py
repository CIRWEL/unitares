"""CIRS Protocol — Multi-agent resonance layer."""

from .protocol import (
    handle_cirs_protocol,
    handle_void_alert,
    handle_state_announce,
    handle_coherence_report,
    handle_boundary_contract,
    handle_governance_action,
    maybe_emit_void_alert,
    auto_emit_state_announce,
    maybe_emit_resonance_signal,
)

__all__ = [
    "handle_cirs_protocol",
    "handle_void_alert",
    "handle_state_announce",
    "handle_coherence_report",
    "handle_boundary_contract",
    "handle_governance_action",
    "maybe_emit_void_alert",
    "auto_emit_state_announce",
    "maybe_emit_resonance_signal",
]
