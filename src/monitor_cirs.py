"""CIRS oscillation detection and resonance damping for governance monitor."""

from config.governance_config import config
from src.logging_utils import get_logger
from src.cirs import OscillationState, classify_response, CIRS_DEFAULTS

logger = get_logger(__name__)


def run_cirs(monitor, risk_score: float, unitares_verdict: str):
    """Run CIRS oscillation detection and resonance damping.

    Returns (oscillation_state, response_tier, cirs_result_or_none, damping_result_or_none).
    Mutates monitor._last_oscillation_state and various monitor.state history fields.
    """
    from config.governance_config import GovernanceConfig as GovConfig

    if GovConfig.ADAPTIVE_GOVERNOR_ENABLED and monitor.adaptive_governor is not None:
        # CIRS v2: Adaptive Governor — PID-based threshold management
        cirs_result = monitor.adaptive_governor.update(
            coherence=float(monitor.state.coherence),
            risk=float(risk_score),
            verdict=unitares_verdict,
            E_history=list(getattr(monitor.state, 'E_history', [0.5]*6)),
            I_history=list(getattr(monitor.state, 'I_history', [0.5]*6)),
            S_history=list(getattr(monitor.state, 'S_history', [0.5]*6)),
            complexity_history=list(getattr(monitor.state, 'complexity_history', [0.3]*6)),
            V_history=list(getattr(monitor.state, 'V_history', [0.0]*6)),
        )
        oscillation_state = OscillationState(
            oi=cirs_result['oi'],
            flips=cirs_result['flips'],
            resonant=cirs_result['resonant'],
            trigger=cirs_result['trigger'],
        )
        monitor._last_oscillation_state = oscillation_state
        response_tier = cirs_result['verdict']
        damping_result = None  # Damping is built into the PID cycle
    else:
        # Legacy v0.1 path
        cirs_result = None
        oscillation_state = monitor.oscillation_detector.update(
            coherence=float(monitor.state.coherence),
            risk=float(risk_score),
            route=unitares_verdict,
            threshold_coherence=config.COHERENCE_CRITICAL_THRESHOLD,
            threshold_risk=config.RISK_REVISE_THRESHOLD
        )
        monitor._last_oscillation_state = oscillation_state

        # Track OI in history
        monitor.state.oi_history.append(oscillation_state.oi)

        # Apply resonance damping if needed
        damping_result = None
        if oscillation_state.resonant:
            monitor.state.resonance_events += 1

            damping_result = monitor.resonance_damper.apply_damping(
                current_coherence=float(monitor.state.coherence),
                current_risk=float(risk_score),
                tau=config.COHERENCE_CRITICAL_THRESHOLD,
                beta=config.RISK_REVISE_THRESHOLD,
                oscillation_state=oscillation_state
            )

            if damping_result.damping_applied:
                monitor.state.damping_applied_count += 1

                logger.info(
                    f"CIRS resonance damping for {monitor.agent_id}: "
                    f"OI={oscillation_state.oi:.3f}, flips={oscillation_state.flips}, "
                    f"trigger={oscillation_state.trigger}"
                )

        # Use damped thresholds if damping was applied, otherwise static config
        effective_tau = (damping_result.tau_new
                        if damping_result and damping_result.damping_applied
                        else config.COHERENCE_CRITICAL_THRESHOLD)
        effective_beta = (damping_result.beta_new
                          if damping_result and damping_result.damping_applied
                          else config.RISK_REVISE_THRESHOLD)

        # Classify response tier (proceed/soft_dampen/hard_block)
        response_tier = classify_response(
            coherence=float(monitor.state.coherence),
            risk=float(risk_score),
            tau=effective_tau,
            beta=effective_beta,
            tau_low=CIRS_DEFAULTS['tau_low'],
            beta_high=CIRS_DEFAULTS['beta_high'],
            oscillation_state=oscillation_state
        )

    return oscillation_state, response_tier, cirs_result, damping_result
