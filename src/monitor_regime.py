"""Regime detection for governance monitor."""


def detect_regime(state) -> str:
    """
    Detect current operational regime based on EISV state and history.

    Regimes:
    - STABLE: I >= 0.999, S <= 0.001 (requires 3 consecutive steps)
    - DIVERGENCE: S rising, |V| elevated
    - TRANSITION: S peaked, starting to fall, I increasing
    - CONVERGENCE: S low & falling, I high & stable

    Args:
        state: GovernanceState instance with I, S, V, *_history attrs.

    Returns:
        Regime string.
    """
    I = state.I
    S = state.S
    V = abs(state.V)

    eps_S = 0.001
    eps_I = 0.001
    I_STABLE_THRESHOLD = 0.999
    S_STABLE_THRESHOLD = 0.001
    V_ELEVATED_THRESHOLD = 0.1

    # STABLE (requires persistence)
    if I >= I_STABLE_THRESHOLD and S <= S_STABLE_THRESHOLD:
        state.locked_persistence_count += 1
        if state.locked_persistence_count >= 3:
            return "STABLE"
    else:
        state.locked_persistence_count = 0

    # Need at least 2 history points for delta-based detection
    if (not hasattr(state, 'S_history') or not hasattr(state, 'I_history')
            or len(state.S_history) < 2 or len(state.I_history) < 2):
        return "DIVERGENCE"

    try:
        dS = S - state.S_history[-2]
        dI = I - state.I_history[-2]
    except (IndexError, AttributeError):
        return "DIVERGENCE"

    # DIVERGENCE
    if dS > eps_S or (S > 0.1 and abs(dS) < eps_S):
        if V > V_ELEVATED_THRESHOLD:
            return "DIVERGENCE"

    # TRANSITION
    if dS < -eps_S and dI > eps_I:
        return "TRANSITION"

    # CONVERGENCE
    if S < 0.1 and dS <= 0 and I > 0.8:
        return "CONVERGENCE"

    return "DIVERGENCE"
