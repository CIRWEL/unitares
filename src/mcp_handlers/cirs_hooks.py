"""
CIRS auto-emit hooks — called from process_agent_update.

Houses maybe_emit_void_alert, auto_emit_state_announce,
maybe_emit_resonance_signal, maybe_apply_neighbor_pressure.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone

from src.logging_utils import get_logger
from .cirs_types import (
    VoidAlert, VoidSeverity, StateAnnounce,
    ResonanceAlert, StabilityRestored,
)
from .cirs_storage import (
    _store_void_alert, _store_state_announce,
    _emit_resonance_alert, _emit_stability_restored,
    _get_recent_resonance_signals, _coherence_report_buffer,
)

logger = get_logger(__name__)


class _LazyMCPServer:
    def __getattr__(self, name):
        from src.mcp_handlers.shared import get_mcp_server
        return getattr(get_mcp_server(), name)

mcp_server = _LazyMCPServer()


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
    Only emits on void state TRANSITIONS (entering void, not staying in void).
    """
    if void_active and not previous_void_active:
        if abs(V) > 0.15 or risk_score > 0.6:
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

    Called from process_agent_update. Emits every 5 updates to avoid flooding.
    """
    update_count = metrics.get("updates", 0)
    if update_count % 5 != 0 and update_count > 1:
        return None

    try:
        eisv = {
            "E": float(metrics.get("E", 0.7)),
            "I": float(metrics.get("I", 0.8)),
            "S": float(metrics.get("S", 0.2)),
            "V": float(metrics.get("V", 0.0)),
        }

        trust_tier_name = None
        try:
            _meta = mcp_server.agent_metadata.get(agent_id)
            if _meta:
                trust_tier_name = getattr(_meta, 'trust_tier', None)
        except Exception:
            pass

        announce = StateAnnounce(
            agent_id=agent_id,
            timestamp=datetime.now().isoformat(),
            eisv=eisv,
            coherence=float(metrics.get("coherence", 0.5)),
            regime=str(metrics.get("regime", "divergence")),
            phi=float(metrics.get("phi", 0.0)),
            verdict=str(metrics.get("verdict", "caution")),
            risk_score=float(metrics.get("risk_score") or metrics.get("current_risk") or 0.0),
            trajectory_signature=None,
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
    """
    resonant = cirs_result.get("resonant", False)

    if resonant == was_resonant:
        return None

    if resonant and not was_resonant:
        alert = ResonanceAlert(
            agent_id=agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
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
        restored = StabilityRestored(
            agent_id=agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
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
    governor,
) -> None:
    """
    Apply neighbor pressure from peer resonance alerts.

    Reads recent RESONANCE_ALERT signals from other agents.
    For each alert, looks up coherence similarity. If similar enough,
    applies defensive threshold tightening to the local governor.
    """
    if governor is None:
        return

    signals = _get_recent_resonance_signals(max_age_minutes=30)

    for signal in signals:
        peer_id = signal.get("agent_id")

        if peer_id == agent_id:
            continue

        signal_type = signal.get("type")

        if signal_type == "RESONANCE_ALERT":
            similarity = _lookup_similarity(agent_id, peer_id)
            if similarity is not None:
                governor.apply_neighbor_pressure(similarity=similarity)
                logger.debug(
                    f"[CIRS/NEIGHBOR] Pressure applied to {agent_id} "
                    f"from {peer_id} (similarity={similarity:.3f})"
                )

        elif signal_type == "STABILITY_RESTORED":
            governor.decay_neighbor_pressure()
            logger.debug(
                f"[CIRS/NEIGHBOR] Pressure decayed for {agent_id} "
                f"(peer {peer_id} stabilized)"
            )


def _lookup_similarity(agent_id: str, peer_id: str) -> Optional[float]:
    """
    Look up pairwise coherence similarity between two agents.
    Checks both directions in the coherence report buffer.
    """
    key = f"{agent_id}:{peer_id}"
    report = _coherence_report_buffer.get(key)
    if report:
        return report.get("similarity_score")

    key_reverse = f"{peer_id}:{agent_id}"
    report_reverse = _coherence_report_buffer.get(key_reverse)
    if report_reverse:
        return report_reverse.get("similarity_score")

    return None
