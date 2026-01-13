"""
Confidence Derivation Module

Derives confidence from observed tool outcomes and EISV state dynamics.
Uses epistemic (uncertainty-aware) penalties, not punitive measures.
"""

from typing import Dict, Any, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from src.governance_state import GovernanceState

from config.governance_config import config


def derive_confidence(
    state: 'GovernanceState', 
    agent_id: str = None,
    apply_calibration: bool = True,
    response_text: str = None,
    reported_complexity: float = 0.5
) -> Tuple[float, Dict[str, Any]]:
    """
    Derive confidence by OBSERVING what already happened - not asking for reports.
    
    The system already tracks tool outcomes. It just needs to look instead of
    pretending it can't see. This version pulls from existing trackers.
    """
    from src.tool_usage_tracker import get_tool_usage_tracker
    
    metadata = {
        'source': 'observed',
        'reliability': 'medium'
    }
    
    # === OBSERVE TOOL OUTCOMES (system already knows this) ===
    tool_confidence = 0.5  # Default neutral
    
    if agent_id:
        try:
            tracker = get_tool_usage_tracker()
            # Look at recent tool calls for this agent (last hour)
            stats = tracker.get_usage_stats(window_hours=1, agent_id=agent_id)
            
            if stats.get('total_calls', 0) > 0:
                # Calculate success rate from what we already tracked
                tools = stats.get('tools', {})
                total_success = sum(t.get('success_count', 0) for t in tools.values())
                total_calls = sum(t.get('total_calls', 0) for t in tools.values())
                
                if total_calls > 0:
                    tool_confidence = total_success / total_calls
                    metadata['tool_stats'] = {
                        'total_calls': total_calls,
                        'success_rate': tool_confidence,
                        'window': '1h'
                    }
                    metadata['reliability'] = 'high' if total_calls >= 3 else 'medium'
        except Exception as e:
            # If tracker unavailable, continue with EISV only
            metadata['tracker_error'] = str(e)
    
    # === EISV CONSISTENCY (internal but meaningful) ===
    #
    # IMPORTANT: Avoid confidence saturation.
    # We explicitly incorporate entropy (S) and void magnitude (|V|) as *uncertainty penalties*.
    # High entropy and large |V| should reduce confidence even if coherence/integrity are high.
    eisv_confidence = 0.5
    coherence_val = 0.5
    integrity_val = 0.5
    entropy_val = 0.5
    void_val = 0.0
    
    if state is not None:
        coherence_val = state.coherence if hasattr(state, 'coherence') else 0.5
        integrity_val = state.I if hasattr(state, 'I') else 0.5
        entropy_val = state.S if hasattr(state, 'S') else 0.5
        void_val = state.V if hasattr(state, 'V') else 0.0

        # Normalize void magnitude relative to threshold band (heuristic, monotonic).
        v_thresh = getattr(config, "VOID_THRESHOLD_INITIAL", 0.15) or 0.15
        void_norm = min(1.0, abs(float(void_val)) / float(v_thresh * 4.0)) if v_thresh > 0 else min(1.0, abs(float(void_val)))
        void_penalty = 0.25 * void_norm

        # Entropy penalty: higher S means more uncertainty.
        entropy_penalty = 0.20 * float(entropy_val)

        # Base EISV confidence favors coherence/integrity and (1-entropy), then applies void penalty.
        eisv_confidence = (
            (float(coherence_val) * 0.55) +
            (float(integrity_val) * 0.35) +
            ((1.0 - float(entropy_val)) * 0.10)
        ) - void_penalty - entropy_penalty

        eisv_confidence = float(max(0.0, min(1.0, eisv_confidence)))

        metadata['eisv'] = {
            'coherence': float(coherence_val),
            'integrity': float(integrity_val),
            'entropy': float(entropy_val),
            'void': float(void_val),
            'void_norm': float(void_norm),
            'void_penalty': float(void_penalty),
            'entropy_penalty': float(entropy_penalty),
        }
    
    # === COMBINE: EISV-only confidence for calibration consistency ===
    #
    # NOTE (Dec 2025): Previously blended tool_confidence with eisv_confidence.
    # This caused calibration inversion: high tool success → high confidence,
    # but trajectory_health (from phi/EISV) remained low → bins showed
    # high confidence with low health.
    #
    # FIX: Use EISV-only confidence. Tool success is still tracked in metadata
    # for observability but doesn't affect confidence used for calibration.
    # This ensures confidence and trajectory_health are derived from the same
    # source (EISV state) and should correlate properly.
    #
    final_confidence = eisv_confidence
    metadata['source'] = 'eisv_only'

    # Tool stats still recorded for transparency but not used in confidence
    if metadata.get('tool_stats'):
        metadata['tool_confidence_excluded'] = tool_confidence
        metadata['exclusion_reason'] = 'Tool success decoupled from trajectory health - using EISV-only for calibration consistency'
    
    # Bound confidence to avoid pathological extremes.
    # NOTE: We intentionally avoid 1.0 in derived mode; perfect certainty is not available here.
    final_confidence = max(0.05, min(0.95, float(final_confidence)))
    metadata['confidence'] = final_confidence
    
    return (final_confidence, metadata)

