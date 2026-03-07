"""Behavioral trajectory: compute TrajectorySignature from governance history.

Pure function — no imports from governance modules. Takes extracted history lists
and returns a dict compatible with TrajectorySignature.from_dict().
"""

import math
from datetime import datetime, timezone


def compute_behavioral_trajectory(
    E_history: list,
    I_history: list,
    S_history: list,
    V_history: list,
    coherence_history: list,
    decision_history: list,
    regime_history: list,
    update_count: int,
    task_type_counts: dict | None = None,
    calibration_error: float | None = None,
) -> dict | None:
    """Compute behavioral trajectory signature from governance observables.

    Returns a dict compatible with TrajectorySignature.from_dict(), or None
    if insufficient history (< 10 entries).
    """
    if len(E_history) < 10 or len(coherence_history) < 10:
        return None

    preferences = _compute_preferences(decision_history, task_type_counts)
    beliefs = _compute_beliefs(E_history, I_history, S_history, V_history, calibration_error)
    attractor = _compute_attractor(E_history, I_history, S_history, V_history)
    recovery = _compute_recovery(coherence_history)
    relational = {"agent_type": "non_embodied", "active_sessions": 1}

    stability = _compute_stability(coherence_history)
    confidence = min(1.0, update_count / 200.0) * stability

    return {
        "preferences": preferences,
        "beliefs": beliefs,
        "attractor": attractor,
        "recovery": recovery,
        "relational": relational,
        "observation_count": update_count,
        "stability_score": stability,
        "identity_confidence": confidence,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# --- Preferences (Π): task-type distribution + decision bias ---

_DECISION_CATEGORIES = {
    "proceed": "proceed", "approve": "proceed",
    "guide": "guide",
    "revise": "guide", "reflect": "guide",
    "pause": "pause", "reject": "pause",
}


def _compute_preferences(decision_history: list, task_type_counts: dict | None) -> dict:
    # Task-type distribution
    tt_dist = {}
    if task_type_counts:
        total = sum(task_type_counts.values())
        if total > 0:
            tt_dist = {k: v / total for k, v in task_type_counts.items()}

    # Decision bias (last 20)
    window = decision_history[-20:]
    counts = {"proceed": 0, "guide": 0, "pause": 0}
    for d in window:
        cat = _DECISION_CATEGORIES.get(str(d).lower(), "guide")
        counts[cat] += 1
    total = sum(counts.values()) or 1
    bias = {k: v / total for k, v in counts.items()}

    return {"task_type_distribution": tt_dist, "decision_bias": bias}


# --- Beliefs (B): EISV center-of-gravity as values vector ---

def _compute_beliefs(
    E_history: list, I_history: list, S_history: list, V_history: list,
    calibration_error: float | None,
) -> dict:
    window = 20
    e = E_history[-window:]
    i = I_history[-window:]
    s = S_history[-window:]
    v = V_history[-window:]

    values = [
        sum(e) / len(e),
        sum(i) / len(i),
        sum(s) / len(s),
        sum(v) / len(v),
    ]

    conf = 1.0 - calibration_error if calibration_error is not None else 0.5
    conf = max(0.0, min(1.0, conf))

    return {"values": values, "confidence": conf}


# --- Attractor (A): EISV center + radius ---

def _compute_attractor(
    E_history: list, I_history: list, S_history: list, V_history: list,
) -> dict:
    window = 20
    e = E_history[-window:]
    i = I_history[-window:]
    s = S_history[-window:]
    v = V_history[-window:]

    center = [
        sum(e) / len(e),
        sum(i) / len(i),
        sum(s) / len(s),
        sum(v) / len(v),
    ]

    # Mean Euclidean distance from center
    n = min(len(e), len(i), len(s), len(v))
    distances = []
    for j in range(n):
        d = math.sqrt(
            (e[j] - center[0]) ** 2
            + (i[j] - center[1]) ** 2
            + (s[j] - center[2]) ** 2
            + (v[j] - center[3]) ** 2
        )
        distances.append(d)
    radius = sum(distances) / len(distances) if distances else 0.0

    return {"center": center, "radius": radius}


# --- Recovery (R): coherence recovery time constant ---

def _compute_recovery(coherence_history: list) -> dict:
    """Estimate recovery tau from coherence dip/recovery cycles."""
    dip_threshold = 0.48
    recovery_threshold = 0.49
    recovery_times = []

    in_dip = False
    dip_start = 0

    for idx, c in enumerate(coherence_history):
        if not in_dip and c < dip_threshold:
            in_dip = True
            dip_start = idx
        elif in_dip and c >= recovery_threshold:
            recovery_times.append(idx - dip_start)
            in_dip = False

    if recovery_times:
        tau = sum(recovery_times) / len(recovery_times)
    else:
        tau = 3.0  # Default: healthy agent, no dips observed

    return {"tau_estimate": tau}


# --- Stability score ---

def _compute_stability(coherence_history: list) -> float:
    """1.0 - std(recent coherence) * 5, clipped [0, 1]."""
    window = coherence_history[-20:]
    if len(window) < 2:
        return 0.5

    mean = sum(window) / len(window)
    variance = sum((x - mean) ** 2 for x in window) / len(window)
    std = math.sqrt(variance)

    return max(0.0, min(1.0, 1.0 - std * 5.0))
