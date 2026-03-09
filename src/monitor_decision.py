"""Decision logic for governance monitor."""

from typing import Dict, Optional, TYPE_CHECKING

from config.governance_config import config
from src.logging_utils import get_logger

if TYPE_CHECKING:
    from src.cirs import OscillationState

logger = get_logger(__name__)


def get_effective_threshold(name: str, default: float) -> float:
    """Get effective threshold, allowing runtime overrides."""
    try:
        from src.runtime_config import get_effective_threshold as _get
        return _get(name, default=default)
    except ImportError:
        return default


def make_decision(
    state,
    risk_score: float,
    unitares_verdict: Optional[str] = None,
    response_tier: Optional[str] = None,
    oscillation_state: Optional['OscillationState'] = None,
) -> Dict:
    """
    Make autonomous governance decision using UNITARES verdict and CIRS response tier.

    Args:
        state: GovernanceState instance.
        risk_score: Risk score [0, 1].
        unitares_verdict: "safe", "caution", or "high-risk".
        response_tier: CIRS tier — "hard_block", "soft_dampen", or "proceed".
        oscillation_state: CIRS oscillation state (for hard_block details).

    Returns:
        Decision dict with action, reason, guidance, critical, margin, nearest_edge.
    """
    margin_info = config.compute_proprioceptive_margin(
        risk_score=risk_score,
        coherence=state.coherence,
        void_active=state.void_active,
        void_value=state.V,
        coherence_history=state.coherence_history,
    )

    # CIRS hard_block override
    if response_tier == 'hard_block':
        oi = oscillation_state.oi if oscillation_state else 0.0
        flips = oscillation_state.flips if oscillation_state else 0
        return {
            'action': 'pause',
            'reason': f'CIRS resonance detected (OI={oi:.2f}, flips={flips}) — decision oscillating',
            'guidance': 'Governance is flip-flopping. Reduce complexity or wait for state to settle.',
            'critical': False,
            'margin': 'critical',
            'nearest_edge': 'oscillation',
        }

    # CIRS soft_dampen: upgrade safe to caution
    if response_tier == 'soft_dampen' and unitares_verdict == 'safe':
        unitares_verdict = 'caution'

    if unitares_verdict == "high-risk":
        try:
            reject_threshold = config.RISK_REJECT_THRESHOLD
        except AttributeError:
            reject_threshold = config.RISK_REVISE_THRESHOLD + 0.20
        effective_reject = get_effective_threshold("risk_reject_threshold", default=reject_threshold)
        is_critical = risk_score >= effective_reject
        return {
            'action': 'pause',
            'reason': f'UNITARES high-risk verdict (risk_score={risk_score:.2f}) - safety pause suggested',
            'guidance': 'This is a safety check, not a failure. The system detected high ethical risk and is protecting you from potential issues. Consider simplifying your approach.',
            'critical': is_critical,
            'margin': 'critical',
            'nearest_edge': 'risk',
        }

    if unitares_verdict == "caution":
        if risk_score < config.RISK_APPROVE_THRESHOLD:
            return {
                'action': 'proceed',
                'reason': f'Proceeding mindfully (risk: {risk_score:.2f})',
                'guidance': 'Navigating complexity. Worth a moment of reflection.',
                'critical': False,
                'verdict_context': 'aware',
                'margin': margin_info['margin'],
                'nearest_edge': margin_info['nearest_edge'],
            }
        else:
            return config.make_decision(
                risk_score=risk_score,
                coherence=state.coherence,
                void_active=state.void_active,
                void_value=state.V,
                coherence_history=state.coherence_history,
            )

    # Safe verdict or no verdict: standard decision
    return config.make_decision(
        risk_score=risk_score,
        coherence=state.coherence,
        void_active=state.void_active,
        void_value=state.V,
        coherence_history=state.coherence_history,
    )
