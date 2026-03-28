"""Behavioral assessment: transparent, component-based risk from behavioral EISV.

No sigmoid/phi black box. Each risk component has a clear source and weight.
Assessment is auditable — you can trace exactly why a verdict was issued.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from src.behavioral_state import BehavioralEISV


@dataclass
class AssessmentResult:
    """Result of behavioral state assessment."""

    # Overall
    health: str          # "healthy", "moderate", "at_risk", "critical"
    verdict: str         # "safe", "caution", "high-risk"
    risk: float          # [0, 1] composite risk score

    # Coherence from rho (update coherence)
    coherence: float     # [0, 1] mapped from rho [-1, 1]

    # Component breakdown (for transparency/debugging)
    components: Dict[str, float]

    # Optional guidance text
    guidance: Optional[str] = None


# Verdict thresholds
RISK_SAFE_THRESHOLD = 0.35
RISK_CAUTION_THRESHOLD = 0.60


def assess_behavioral_state(
    state: BehavioralEISV,
    rho: float = 0.0,
    continuity_energy: float = 0.0,
    agent_context: Optional[Dict] = None,
) -> AssessmentResult:
    """Assess agent health from behavioral EISV + auxiliary signals.

    Args:
        state: Current behavioral EISV state
        rho: Update coherence from HCK [-1, 1]
        continuity_energy: CE from continuity layer [0, inf)
        agent_context: Optional dict with task_type, update_count, etc.

    Returns:
        AssessmentResult with health, verdict, risk breakdown
    """
    ctx = agent_context or {}
    components = {}

    # --- Component 1: Low Energy (weight: 0.30) ---
    # E < 0.4 → risk contribution scales linearly
    if state.E < 0.4:
        components["low_E"] = 0.30 * (0.4 - state.E) / 0.4
    else:
        components["low_E"] = 0.0

    # --- Component 2: Low Integrity (weight: 0.30) ---
    # I < 0.4 → risk contribution scales linearly
    if state.I < 0.4:
        components["low_I"] = 0.30 * (0.4 - state.I) / 0.4
    else:
        components["low_I"] = 0.0

    # --- Component 3: High Entropy (weight: 0.20) ---
    # S > 0.5 → risk contribution. Context-dependent: convergent tasks tolerate lower S.
    s_threshold = 0.5
    task_type = ctx.get("task_type", "mixed")
    if task_type == "convergent":
        s_threshold = 0.6  # convergent work naturally has lower S
    if state.S > s_threshold:
        components["high_S"] = 0.20 * min(1.0, (state.S - s_threshold) / (1.0 - s_threshold))
    else:
        components["high_S"] = 0.0

    # --- Component 4: High |V| imbalance (weight: 0.20) ---
    # Large E-I gap means imbalanced agent
    abs_v = abs(state.V)
    if abs_v > 0.15:
        components["high_V"] = 0.20 * min(1.0, (abs_v - 0.15) / 0.85)
    else:
        components["high_V"] = 0.0

    # --- Component 5: Adversarial rho (weight: 0.15) ---
    # Negative rho means updates are incoherent (E and I moving opposite)
    if rho < -0.2:
        components["adversarial_rho"] = 0.15 * min(1.0, (-0.2 - rho) / 0.8)
    else:
        components["adversarial_rho"] = 0.0

    # --- Component 6: High continuity energy (weight: 0.10) ---
    # CE > 0.5 means high state volatility
    if continuity_energy > 0.5:
        components["high_CE"] = 0.10 * min(1.0, (continuity_energy - 0.5) / 1.5)
    else:
        components["high_CE"] = 0.0

    # --- Trend bonus: improving E+I reduces risk slightly ---
    trend_bonus = 0.0
    if state.update_count >= 5:
        e_trend = state.trend("E")
        i_trend = state.trend("I")
        if e_trend > 0.005 and i_trend > 0.005:
            trend_bonus = -0.05  # small risk reduction for improving trajectory

    # --- Composite risk ---
    risk = sum(components.values()) + trend_bonus
    risk = max(0.0, min(1.0, risk))

    # --- Coherence from rho ---
    # Map rho [-1, 1] to coherence [0, 1]
    coherence = (rho + 1.0) / 2.0
    coherence = max(0.0, min(1.0, coherence))

    # --- Verdict ---
    if risk < RISK_SAFE_THRESHOLD:
        verdict = "safe"
    elif risk < RISK_CAUTION_THRESHOLD:
        verdict = "caution"
    else:
        verdict = "high-risk"

    # --- Health ---
    if risk < 0.20:
        health = "healthy"
    elif risk < RISK_SAFE_THRESHOLD:
        health = "moderate"
    elif risk < RISK_CAUTION_THRESHOLD:
        health = "at_risk"
    else:
        health = "critical"

    # --- Guidance ---
    guidance = _generate_guidance(state, components, health, verdict, task_type)

    return AssessmentResult(
        health=health,
        verdict=verdict,
        risk=round(risk, 4),
        coherence=round(coherence, 4),
        components={k: round(v, 4) for k, v in components.items()},
        guidance=guidance,
    )


def _generate_guidance(
    state: BehavioralEISV,
    components: Dict[str, float],
    health: str,
    verdict: str,
    task_type: str,
) -> Optional[str]:
    """Generate actionable guidance from assessment components."""
    if health == "healthy":
        return None

    # Find the dominant risk component
    if not components:
        return None
    top_component = max(components, key=components.get)
    top_value = components[top_component]

    if top_value < 0.01:
        return None

    guidance_map = {
        "low_E": f"Low energy (E={state.E:.2f}). Consider simplifying tasks or checking tool reliability.",
        "low_I": f"Low integrity (I={state.I:.2f}). Calibration may be off — check recent outcomes.",
        "high_S": f"High entropy (S={state.S:.2f}). Regime may be unstable — consider consolidating.",
        "high_V": f"E-I imbalance (V={state.V:.2f}). {'Running hot — slow down.' if state.V > 0 else 'Running careful — increase exploration.'}",
        "adversarial_rho": "Updates are incoherent. E and I moving in opposite directions.",
        "high_CE": "High state volatility. Agent state is changing rapidly.",
    }

    return guidance_map.get(top_component)
