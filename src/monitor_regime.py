"""Regime detection for governance monitor.

Thresholds calibrated against observed agent distributions (2026-03-16):
  - Healthy agents: S ≈ 0.17 (p25=0.15, p75=0.19), I ≈ 0.80, C ≈ 0.50
  - Previous thresholds were unreachable (STABLE: I≥0.999, S≤0.001)
    causing 80% of agents to fall through to DIVERGENCE default.
"""


def detect_regime(state, behavioral=None) -> str:
    """
    Detect current operational regime based on EISV state and history.

    Prefers behavioral EISV values when available and confident (>= 0.3),
    falls back to ODE state otherwise. Persistence counter stays on
    the GovernanceState object (metadata, not EISV).

    Regimes:
    - STABLE: I high, S low (requires 3 consecutive steps)
    - CONVERGENCE: S moderate & not rising, I healthy
    - TRANSITION: S falling while I rising
    - EXPLORATION: New agent, insufficient history
    - DIVERGENCE: S actively rising with elevated V

    Args:
        state: GovernanceState instance with I, S, V, *_history attrs.
        behavioral: Optional BehavioralEISV instance. Used when confident.

    Returns:
        Regime string.
    """
    # Behavioral-first: use per-agent EMA observations when confident
    if behavioral is not None and behavioral.confidence >= 0.3:
        I = behavioral.I
        S = behavioral.S
        V = abs(behavioral.V)
        s_hist = behavioral.S_history
        i_hist = behavioral.I_history
    else:
        I = state.I
        S = state.S
        V = abs(state.V)
        s_hist = getattr(state, 'S_history', [])
        i_hist = getattr(state, 'I_history', [])

    eps_S = 0.002
    eps_I = 0.002

    # STABLE (requires persistence) — achievable by healthy agents
    # locked_persistence_count lives on state (persistence metadata)
    if I >= 0.85 and S <= 0.10:
        state.locked_persistence_count += 1
        if state.locked_persistence_count >= 3:
            return "STABLE"
    else:
        state.locked_persistence_count = 0

    # Need at least 2 history points for delta-based detection
    if len(s_hist) < 2 or len(i_hist) < 2:
        return "EXPLORATION"

    try:
        dS = S - s_hist[-2]
        dI = I - i_hist[-2]
    except (IndexError, AttributeError):
        return "EXPLORATION"

    # DIVERGENCE — S actively rising AND V elevated (real divergence, not just noise)
    if dS > eps_S and V > 0.05:
        return "DIVERGENCE"

    # TRANSITION — S falling while I rising (recovering)
    if dS < -eps_S and dI > eps_I:
        return "TRANSITION"

    # CONVERGENCE — S moderate and not rising, I healthy
    if S < 0.25 and dS <= eps_S and I > 0.70:
        return "CONVERGENCE"

    # Default: EXPLORATION (unknown territory, not assumed bad)
    return "EXPLORATION"
