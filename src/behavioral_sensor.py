"""Behavioral sensor: compute EISV from governance observables for non-embodied agents.

Pure function — no imports from governance modules. Takes extracted history lists
and returns an EISV dict suitable for spring coupling in the ODE.
"""

import math


def compute_behavioral_sensor_eisv(
    decision_history: list,
    coherence_history: list,
    regime_history: list,
    E_history: list,
    I_history: list,
    S_history: list,
    V_history: list,
    calibration_error: float | None = None,
    drift_norm: float | None = None,
    complexity_divergence: float | None = None,
) -> dict | None:
    """Compute behavioral sensor EISV from governance observables.

    Returns {"E", "I", "S", "V"} dict or None if insufficient history (< 3 entries).
    """
    if len(decision_history) < 3 or len(coherence_history) < 3:
        return None

    E = _compute_E(decision_history, coherence_history, complexity_divergence)
    I = _compute_I(coherence_history, calibration_error)
    S = _compute_S(drift_norm, regime_history, complexity_divergence)
    V = _compute_V(E_history, I_history)

    return {"E": E, "I": I, "S": S, "V": V}


# --- E: Decision success rate, exponentially weighted ---

_DECISION_SCORES = {
    "proceed": 1.0, "approve": 1.0,
    "guide": 0.7,
    "revise": 0.5, "reflect": 0.5,
    "pause": 0.0, "reject": 0.0,
}


def _compute_E(
    decision_history: list,
    coherence_history: list | None = None,
    complexity_divergence: float | None = None,
) -> float:
    """E from decision success (40%), coherence level (30%), complexity calibration (30%).

    Pure decision-based E saturates at 1.0 for healthy agents (all "proceed").
    Blending with coherence and calibration makes E reflect actual capacity.
    """
    # Decision success (40%) — exponentially weighted
    window = decision_history[-10:]
    if not window:
        decision_e = 0.65
    else:
        n = len(window)
        alpha = 0.3
        weights = [math.exp(alpha * (i - n + 1)) for i in range(n)]
        total_w = sum(weights)
        decision_e = sum(
            w * _DECISION_SCORES.get(str(d).lower(), 0.5)
            for w, d in zip(weights, window)
        ) / total_w

    # Coherence level (30%) — map mean coherence [0.40, 0.55] → [0.3, 0.9]
    if coherence_history and len(coherence_history) >= 3:
        recent_coh = coherence_history[-10:]
        mean_coh = sum(recent_coh) / len(recent_coh)
        coh_e = 0.3 + (mean_coh - 0.40) * 4.0  # 0.40→0.3, 0.55→0.9
        coh_e = max(0.3, min(0.9, coh_e))
    else:
        coh_e = 0.6

    # Complexity calibration (30%) — low divergence = high capacity awareness
    cd = complexity_divergence if complexity_divergence is not None else 0.15
    cal_e = max(0.3, min(1.0, 1.0 - cd))

    raw = 0.40 * decision_e + 0.30 * coh_e + 0.30 * cal_e
    return max(0.0, min(1.0, raw))


# --- I: Calibration accuracy + coherence trend ---

def _compute_I(coherence_history: list, calibration_error: float | None) -> float:
    cal_I = 1.0 - calibration_error if calibration_error is not None else 0.75
    cal_I = max(0.0, min(1.0, cal_I))

    coh_I = _coherence_trend(coherence_history)

    return max(0.0, min(1.0, 0.6 * cal_I + 0.4 * coh_I))


def _coherence_trend(coherence_history: list) -> float:
    """Split-half coherence trend mapped to [0.3, 0.9]."""
    window = coherence_history[-10:]
    if len(window) < 4:
        return 0.6  # neutral default

    mid = len(window) // 2
    first_half = sum(window[:mid]) / mid
    second_half = sum(window[mid:]) / (len(window) - mid)

    # Positive diff = improving, negative = declining
    diff = second_half - first_half
    # Map diff from [-0.1, 0.1] to [0.3, 0.9]
    mapped = 0.6 + diff * 3.0
    return max(0.3, min(0.9, mapped))


# --- S: Entropy from drift, regime instability, complexity divergence ---

def _compute_S(
    drift_norm: float | None,
    regime_history: list,
    complexity_divergence: float | None,
) -> float:
    # Drift component (40%)
    dn = drift_norm if drift_norm is not None else 0.2
    drift_s = min(1.0, dn * 1.5)

    # Regime instability (35%): count transitions / window
    regime_s = _regime_instability(regime_history)

    # Complexity divergence (25%)
    cd = complexity_divergence if complexity_divergence is not None else 0.1
    cd_s = min(1.0, cd)

    raw = 0.40 * drift_s + 0.35 * regime_s + 0.25 * cd_s
    return max(0.05, min(1.0, raw))


def _regime_instability(regime_history: list) -> float:
    """Count regime transitions normalized by window size."""
    window = regime_history[-10:]
    if len(window) < 2:
        return 0.1  # default low instability

    transitions = sum(
        1 for i in range(1, len(window)) if window[i] != window[i - 1]
    )
    return min(1.0, transitions / (len(window) - 1))


# --- V: E-I trajectory slope difference ---

def _compute_V(E_history: list, I_history: list) -> float:
    """V from E-I slope difference. Does NOT read V_history."""
    window = 10
    e_win = E_history[-window:]
    i_win = I_history[-window:]

    if len(e_win) < 3 or len(i_win) < 3:
        return 0.0

    e_slope = _simple_slope(e_win)
    i_slope = _simple_slope(i_win)
    trend = e_slope - i_slope

    # Instantaneous E-I gap
    level = e_win[-1] - i_win[-1]

    # 60% trend + 40% level
    v = 0.6 * trend + 0.4 * level
    return max(-1.0, min(1.0, v))


def _simple_slope(values: list) -> float:
    """Least-squares slope over an index sequence."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    return num / den
