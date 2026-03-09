"""Void state detection and frequency calculation for governance monitor."""

import numpy as np

from config.governance_config import config


def check_void_state(state) -> bool:
    """
    Check if system is in void state: |V| > adaptive threshold.

    Updates state.void_active in place.

    Args:
        state: GovernanceState instance with V, V_history, void_active attrs.

    Returns:
        True if system is in void state.
    """
    V_history = np.array(state.V_history) if state.V_history else np.array([state.V])
    threshold = config.get_void_threshold(V_history, adaptive=True)

    void_active = bool(abs(state.V) > threshold)
    state.void_active = void_active

    return void_active


def calculate_void_frequency(state) -> float:
    """
    Calculate void frequency from V history.

    Returns fraction of time system was in void state (|V| > threshold).
    Uses adaptive threshold for each historical point.

    Args:
        state: GovernanceState instance with V_history attr.
    """
    if not state.V_history or len(state.V_history) < 10:
        return 0.0

    window = min(100, len(state.V_history))
    recent_V = np.array(state.V_history[-window:])

    threshold = config.get_void_threshold(recent_V, adaptive=True)

    void_count = np.sum(np.abs(recent_V) > threshold)
    return float(void_count) / len(recent_V)
