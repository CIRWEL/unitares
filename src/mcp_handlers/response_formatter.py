"""
Response Formatter — Filters process_agent_update response by verbosity mode.

Extracted from core.py to reduce its size and make response modes independently testable.
"""

import os
from typing import Any, Dict, Optional

from src.logging_utils import get_logger
from src.mcp_handlers.shared import lazy_mcp_server as mcp_server
logger = get_logger(__name__)

def format_response(
    response_data: dict,
    arguments: dict,
    *,
    meta: Any = None,
    is_new_agent: bool = False,
    key_was_generated: bool = False,
    api_key_auto_retrieved: bool = False,
    task_type: str = "mixed",
) -> dict:
    """
    Apply response mode filtering to fully-built response_data.

    Priority: per-call response_mode > agent preferences > env var > auto

    Modes:
    - "auto": Select mode based on health_status
    - "standard"/"interpreted": Human-readable interpretation via GovernanceState
    - "minimal": Action + EISV snapshot + margin
    - "compact"/"lite": Brief metrics + decision summary
    - "full": No filtering (return as-is)

    Args:
        response_data: The complete response dict built by process_agent_update
        arguments: Original tool arguments (for response_mode param)
        meta: Agent metadata object (for preferences.verbosity)
        is_new_agent: Whether this is the agent's first check-in
        key_was_generated: Whether an API key was just generated
        api_key_auto_retrieved: Whether an API key was auto-retrieved
        task_type: Task type for state interpretation

    Returns:
        Filtered response_data dict
    """
    # Check agent preferences
    agent_verbosity_pref = None
    if meta and hasattr(meta, 'preferences') and meta.preferences:
        agent_verbosity_pref = meta.preferences.get("verbosity")

    # Preserve trust_tier across filtering
    saved_trust_tier = None
    try:
        saved_trust_tier = response_data.get("trajectory_identity", {}).get("trust_tier", {}).get("name")
    except Exception:
        pass

    # Priority: per-call > agent pref > env var > auto
    response_mode = (
        arguments.get("response_mode") or
        agent_verbosity_pref or
        os.getenv("UNITARES_PROCESS_UPDATE_RESPONSE_MODE", "auto")
    ).strip().lower()

    using_default_mode = not arguments.get("response_mode") and not agent_verbosity_pref

    # Full mode: no filtering
    if response_mode == "full":
        return response_data

    # AUTO MODE: Adaptive verbosity based on health status
    if response_mode == "auto":
        metrics = response_data.get("metrics", {}) if isinstance(response_data.get("metrics"), dict) else {}
        health_status = (
            response_data.get("health_status") or
            metrics.get("health_status") or
            response_data.get("status") or
            "healthy"
        )
        if health_status == "healthy":
            response_mode = "minimal"
        elif health_status in ("at_risk", "critical"):
            response_mode = "standard"
        else:
            response_mode = "compact"

    # STANDARD MODE: Human-readable interpretation
    if response_mode in ("standard", "interpreted"):
        response_data = _format_standard(response_data, task_type)

    # MINIMAL MODE: Bare essentials
    elif response_mode == "minimal":
        response_data = _format_minimal(response_data, using_default_mode, saved_trust_tier)

    # COMPACT MODE: Brief metrics + decision
    elif response_mode in ("compact", "lite"):
        response_data = _format_compact(response_data, using_default_mode, saved_trust_tier)

    # Strip optional context for minimal/compact (reduce noise for established agents)
    if response_mode in ("minimal", "compact"):
        _strip_context(response_data, is_new_agent, key_was_generated, api_key_auto_retrieved)

    return response_data

def _format_standard(response_data: dict, task_type: str) -> dict:
    """Build standard (interpreted) response."""
    from governance_state import GovernanceState
    from governance_core import State, Theta, DEFAULT_THETA

    metrics = response_data.get("metrics", {}) if isinstance(response_data.get("metrics"), dict) else {}
    decision = response_data.get("decision", {}) if isinstance(response_data.get("decision"), dict) else {}

    E = float(metrics.get("E", 0.7))
    I = float(metrics.get("I", 0.8))
    S = float(metrics.get("S", 0.1))
    V = float(metrics.get("V", 0.0))
    coherence = float(metrics.get("coherence", 0.5))
    risk_score = metrics.get("latest_risk_score") or metrics.get("risk_score")

    temp_state = GovernanceState()
    temp_state.unitaires_state = State(E=E, I=I, S=S, V=V)
    temp_state.unitaires_theta = Theta(C1=DEFAULT_THETA.C1, eta1=DEFAULT_THETA.eta1)
    temp_state.coherence = coherence
    temp_state.decision_history = response_data.get("history", {}).get("decision_history", [])

    interpreted = temp_state.interpret_state(risk_score=risk_score, task_type=task_type)

    result = {
        "success": True,
        "agent_id": response_data.get("agent_id"),
        "decision": decision.get("action") or response_data.get("status"),
        "state": interpreted,
        "metrics": {
            "E": E, "I": I, "S": S, "V": V,
            "coherence": coherence, "risk_score": risk_score,
        },
        "sampling_params": response_data.get("sampling_params"),
        "_mode": "standard",
        "_raw_available": "Use response_mode='full' to see complete metrics",
    }
    if "thread_context" in response_data:
        result["thread_context"] = response_data["thread_context"]
    return result

def _format_minimal(response_data: dict, using_default_mode: bool, saved_trust_tier: Optional[str]) -> dict:
    """Build minimal response: action + EISV + margin."""
    decision = response_data.get("decision", {}) if isinstance(response_data.get("decision"), dict) else {}
    metrics = response_data.get("metrics", {}) if isinstance(response_data.get("metrics"), dict) else {}

    result = {
        "action": decision.get("action", "continue"),
        "_mode": "minimal",
        "E": metrics.get("E"),
        "I": metrics.get("I"),
        "S": metrics.get("S"),
        "V": metrics.get("V"),
        "coherence": metrics.get("coherence"),
        "risk_score": metrics.get("latest_risk_score") or metrics.get("risk_score"),
    }

    margin = decision.get("margin")
    if margin:
        result["margin"] = margin
    nearest_edge = decision.get("nearest_edge")
    if nearest_edge:
        result["nearest_edge"] = nearest_edge
    if using_default_mode:
        result["_tip"] = "Set verbosity: update_agent_metadata(preferences={'verbosity':'minimal'})"
    if saved_trust_tier:
        result["trust_tier"] = saved_trust_tier
    if "thread_context" in response_data:
        result["thread_context"] = response_data["thread_context"]

    return result

def _format_compact(response_data: dict, using_default_mode: bool, saved_trust_tier: Optional[str]) -> dict:
    """Build compact response: brief metrics + decision summary."""
    metrics = response_data.get("metrics", {}) if isinstance(response_data.get("metrics"), dict) else {}
    decision = response_data.get("decision", {}) if isinstance(response_data.get("decision"), dict) else {}

    canonical_risk = metrics.get("latest_risk_score")
    if canonical_risk is None:
        canonical_risk = metrics.get("risk_score")

    compact_metrics = {
        "E": metrics.get("E"),
        "I": metrics.get("I"),
        "S": metrics.get("S"),
        "V": metrics.get("V"),
        "coherence": metrics.get("coherence"),
        "risk_score": canonical_risk,
        "phi": metrics.get("phi"),
        "verdict": metrics.get("verdict"),
        "lambda1": metrics.get("lambda1"),
        "health_status": metrics.get("health_status"),
        "health_message": metrics.get("health_message"),
    }

    compact_decision = {
        "action": decision.get("action"),
        "reason": decision.get("reason"),
        "require_human": decision.get("require_human"),
        "margin": decision.get("margin"),
        "nearest_edge": decision.get("nearest_edge"),
    }

    health_status = response_data.get("health_status") or compact_metrics.get("health_status") or response_data.get("status")
    coherence = compact_metrics.get("coherence")
    risk_val = compact_metrics.get("risk_score")
    action = compact_decision.get("action") or response_data.get("status")
    summary = f"{action} | health={health_status} | coherence={coherence} | risk_score={risk_val}"

    result = {
        "success": True,
        "agent_id": response_data.get("agent_id"),
        "status": response_data.get("status"),
        "health_status": health_status,
        "health_message": response_data.get("health_message"),
        "decision": compact_decision,
        "metrics": compact_metrics,
        "sampling_params": response_data.get("sampling_params"),
        "summary": summary,
        "_mode": "compact",
    }

    if saved_trust_tier:
        result["trust_tier"] = saved_trust_tier
    if using_default_mode:
        result["_tip"] = "Verbosity options: response_mode='minimal'|'compact'|'full', or set permanently via update_agent_metadata(preferences={'verbosity':'minimal'})"
    if "thread_context" in response_data:
        result["thread_context"] = response_data["thread_context"]

    return result

def _strip_context(response_data: dict, is_new_agent: bool, key_was_generated: bool, api_key_auto_retrieved: bool):
    """Strip optional context fields for minimal/compact modes (in-place)."""
    response_data.pop("eisv_labels", None)
    response_data.pop("sampling_params_note", None)

    if not is_new_agent:
        response_data.pop("learning_context", None)
        response_data.pop("relevant_discoveries", None)
        response_data.pop("onboarding", None)
        response_data.pop("welcome", None)
        if not (key_was_generated or api_key_auto_retrieved):
            response_data.pop("api_key_hint", None)
            response_data.pop("_onboarding", None)
