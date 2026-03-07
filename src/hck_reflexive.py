"""
HCK v3.0: Update Coherence and Continuity Energy functions.

Extracted from governance_monitor.py. These are pure, stateless functions
used for reflexive control — measuring directional alignment of EISV updates,
tracking system stability (continuity energy), and modulating PI gains.
"""

from typing import Dict, List, Tuple


def compute_update_coherence(delta_E: float, delta_I: float,
                              epsilon: float = 1e-8) -> float:
    """
    Compute update coherence rho(t) per HCK v3.0.

    Measures directional alignment between E and I updates.

    Interpretation:
    - rho ~ 1: Coherent updates (E and I moving together)
    - rho ~ 0: Misaligned or unstable
    - rho < 0: Adversarial movement (E and I diverging)

    Args:
        delta_E: Change in Energy since last update
        delta_I: Change in Information Integrity since last update
        epsilon: Small value to prevent division by zero

    Returns:
        float in [-1, 1]: Update coherence value
    """
    norm_E = abs(delta_E) + epsilon
    norm_I = abs(delta_I) + epsilon

    # Normalized product gives directional alignment
    rho = (delta_E * delta_I) / (norm_E * norm_I)

    return float(max(-1.0, min(1.0, rho)))


def compute_continuity_energy(state_history: List[Dict],
                               window: int = 10,
                               alpha_state: float = 0.6,
                               alpha_decision: float = 0.4) -> float:
    """
    Compute Continuity Energy CE(t) per HCK v3.0.

    CE tracks how much the system state is changing - the "work required
    to maintain consistency as system evolves."

    Interpretation:
    - High CE: Major state changes requiring stabilization
    - Low CE: Stable operation

    Args:
        state_history: List of recent state snapshots with E, I, S, V, route keys
        window: Number of recent states to consider
        alpha_state: Weight for EISV state changes (default 0.6)
        alpha_decision: Weight for decision/route changes (default 0.4)

    Returns:
        CE value (non-negative float)
    """
    if len(state_history) < 2:
        return 0.0

    recent = state_history[-window:] if len(state_history) > window else state_history

    # State change component: sum of absolute EISV deltas
    state_deltas = []
    for i in range(1, len(recent)):
        prev, curr = recent[i-1], recent[i]
        delta = (
            abs(curr.get('E', 0) - prev.get('E', 0)) +
            abs(curr.get('I', 0) - prev.get('I', 0)) +
            abs(curr.get('S', 0) - prev.get('S', 0)) +
            abs(curr.get('V', 0) - prev.get('V', 0))
        )
        state_deltas.append(delta)

    avg_state_delta = sum(state_deltas) / len(state_deltas) if state_deltas else 0.0

    # Decision change component: count route/decision flips
    decision_changes = 0
    for i in range(1, len(recent)):
        prev_route = recent[i-1].get('route') or recent[i-1].get('decision')
        curr_route = recent[i].get('route') or recent[i].get('decision')
        if prev_route and curr_route and prev_route != curr_route:
            decision_changes += 1

    decision_change_rate = decision_changes / (len(recent) - 1) if len(recent) > 1 else 0.0

    # Weighted combination
    CE = alpha_state * avg_state_delta + alpha_decision * decision_change_rate

    return float(CE)


def modulate_gains(K_p: float, K_i: float, rho: float,
                   min_factor: float = 0.5) -> Tuple[float, float]:
    """
    Adjust PI gains based on update coherence per HCK v3.0.

    When rho(t) is low (misaligned updates), reduce controller aggressiveness
    to prevent instability.

    Args:
        K_p: Base proportional gain
        K_i: Base integral gain
        rho: Update coherence [-1, 1]
        min_factor: Minimum gain multiplier (default 0.5)

    Returns:
        (K_p_adjusted, K_i_adjusted)
    """
    # Map rho from [-1, 1] to [min_factor, 1.0]
    # rho=1 -> factor=1.0, rho=0 -> factor=0.75, rho=-1 -> factor=0.5
    coherence_factor = max(min_factor, (rho + 1) / 2)

    return K_p * coherence_factor, K_i * coherence_factor
