"""
Outcome Events Tool - Record measurable outcomes paired with EISV snapshots.

Enables validation of the EISV model by collecting real outcome data
(drawing completions, test results, task completions) alongside the
EISV state at outcome time.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
from ..utils import success_response, error_response
from ..decorators import mcp_tool
from src.logging_utils import get_logger
from src.mcp_handlers.shared import lazy_mcp_server as mcp_server
from src.services.runtime_queries import _build_eisv_semantics
logger = get_logger(__name__)

# Outcome types that are considered "bad" by default
BAD_OUTCOME_TYPES = {"test_failed", "tool_rejected", "drawing_abandoned", "task_failed"}
GOOD_OUTCOME_TYPES = {"test_passed", "drawing_completed", "task_completed"}
NEUTRAL_OUTCOME_TYPES = {"trajectory_validated"}  # is_bad determined by score
VALID_OUTCOME_TYPES = BAD_OUTCOME_TYPES | GOOD_OUTCOME_TYPES | NEUTRAL_OUTCOME_TYPES

_HARD_EXOGENOUS_DETAIL_KEYS = (
    ("tests", "tests"),
    ("commands", "commands"),
    ("files", "files"),
    ("lint", "lint"),
    ("tool_results", "tool_observations"),
)


def _classify_hard_exogenous_signal(outcome_type: str, detail: Dict[str, Any]) -> str | None:
    """Return the hard exogenous signal source when this outcome is e-process eligible."""
    if outcome_type in {"test_passed", "test_failed"}:
        return "tests"
    for key, label in _HARD_EXOGENOUS_DETAIL_KEYS:
        if detail.get(key):
            return label
    return None

@mcp_tool("outcome_event", timeout=15.0)
async def handle_outcome_event(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Record an outcome event paired with the agent's current EISV snapshot."""
    from src.db import get_db
    from ..context import get_context_agent_id, get_context_client_session_id

    outcome_type = arguments.get("outcome_type")
    if not outcome_type:
        return [error_response(
            "outcome_type is required",
            error_code="MISSING_PARAM",
            error_category="validation_error",
        )]

    if outcome_type not in VALID_OUTCOME_TYPES:
        return [error_response(
            f"Unknown outcome_type '{outcome_type}'. Valid: {sorted(VALID_OUTCOME_TYPES)}",
            error_code="INVALID_PARAM",
            error_category="validation_error",
        )]

    # Get agent_id from context
    agent_id = get_context_agent_id()
    if not agent_id:
        # Fall back to explicit argument
        agent_id = arguments.get("agent_id")
    if not agent_id:
        return [error_response(
            "Could not determine agent_id from session context. Provide agent_id explicitly.",
            error_code="NO_AGENT_ID",
            error_category="identity_error",
        )]

    # Infer is_bad if not provided
    is_bad = arguments.get("is_bad")
    if is_bad is None:
        is_bad = outcome_type in BAD_OUTCOME_TYPES

    # Infer outcome_score if not provided
    outcome_score = arguments.get("outcome_score")
    if outcome_score is None:
        outcome_score = 0.0 if is_bad else 1.0

    detail = dict(arguments.get("detail") or {})
    session_id = (
        arguments.get("session_id")
        or arguments.get("client_session_id")
        or get_context_client_session_id()
    )

    # Fetch latest EISV snapshot for this agent (ODE state from DB)
    db = get_db()
    eisv = await db.get_latest_eisv_by_agent_id(agent_id)

    eisv_e = eisv["E"] if eisv else None
    eisv_i = eisv["I"] if eisv else None
    eisv_s = eisv["S"] if eisv else None
    eisv_v = eisv["V"] if eisv else None
    eisv_phi = eisv["phi"] if eisv else None
    eisv_verdict = eisv["verdict"] if eisv else None
    eisv_coherence = eisv["coherence"] if eisv else None
    eisv_regime = eisv["regime"] if eisv else None

    # Embed behavioral EISV (observation-first, per-agent) alongside ODE snapshot
    monitor = None
    try:
        monitors = getattr(mcp_server, "monitors", None)
        if isinstance(monitors, dict):
            monitor = monitors.get(agent_id)
        if monitor:
            bstate = getattr(monitor, '_behavioral_state', None)
            if bstate and bstate.confidence > 0:
                detail['behavioral_eisv'] = {
                    'E': round(bstate.E, 4),
                    'I': round(bstate.I, 4),
                    'S': round(bstate.S, 4),
                    'V': round(bstate.V, 4),
                    'confidence': round(bstate.confidence, 4),
                }
    except Exception:
        pass  # Fail-safe: ODE snapshot still recorded

    snapshot = None
    if eisv:
        primary_e, primary_i, primary_s, primary_v = eisv_e, eisv_i, eisv_s, eisv_v
        if monitor:
            try:
                primary_e, primary_i, primary_s, primary_v = monitor.get_primary_eisv()
            except Exception:
                pass
        snapshot_metrics = {
            "E": primary_e,
            "I": primary_i,
            "S": primary_s,
            "V": primary_v,
            "phi": eisv_phi,
            "verdict": eisv_verdict,
            "coherence": eisv_coherence,
            "regime": eisv_regime,
            "ode": {
                "E": eisv_e,
                "I": eisv_i,
                "S": eisv_s,
                "V": eisv_v,
            },
        }
        snapshot = _build_eisv_semantics(snapshot_metrics, monitor)
        detail["primary_eisv"] = snapshot.get("primary_eisv")
        detail["primary_eisv_source"] = snapshot.get("primary_eisv_source")
        detail["behavioral_eisv"] = snapshot.get("behavioral_eisv")
        detail["ode_eisv"] = snapshot.get("ode_eisv")
        detail["ode_diagnostics"] = snapshot.get("ode_diagnostics")
        detail["state_semantics"] = snapshot.get("state_semantics")
        detail["snapshot_source"] = "latest_agent_state"
        detail["snapshot_missing"] = False
    else:
        detail["snapshot_source"] = "missing"
        detail["snapshot_missing"] = True

    # Resolve confidence before persisting detail so exports can reconstruct the lane.
    _confidence = arguments.get('confidence')
    if _confidence is not None:
        _confidence = float(_confidence)
    else:
        try:
            monitor = mcp_server.monitors.get(agent_id)
            prev_confidence = getattr(monitor, "_prev_confidence", None) if monitor else None
            if isinstance(prev_confidence, (int, float)):
                _confidence = float(prev_confidence)
        except Exception:
            pass

    decision_action = arguments.get("decision_action")
    if decision_action is None and outcome_type in {"test_passed", "test_failed"}:
        decision_action = "proceed"

    hard_exogenous_signal = _classify_hard_exogenous_signal(outcome_type, detail)
    eprocess_eligible = bool(hard_exogenous_signal and _confidence is not None)

    detail["reported_confidence"] = _confidence
    detail["decision_action"] = decision_action
    detail["hard_exogenous_signal"] = hard_exogenous_signal
    detail["hard_exogenous"] = bool(hard_exogenous_signal)
    detail["eprocess_eligible"] = eprocess_eligible

    # Insert
    outcome_id = await db.record_outcome_event(
        agent_id=agent_id,
        outcome_type=outcome_type,
        is_bad=is_bad,
        outcome_score=outcome_score,
        session_id=session_id,
        eisv_e=eisv_e,
        eisv_i=eisv_i,
        eisv_s=eisv_s,
        eisv_v=eisv_v,
        eisv_phi=eisv_phi,
        eisv_verdict=eisv_verdict,
        eisv_coherence=eisv_coherence,
        eisv_regime=eisv_regime,
        detail=detail,
    )

    if not outcome_id:
        return [error_response(
            "Failed to record outcome event (database error)",
            error_code="DB_ERROR",
            error_category="system_error",
        )]

    logger.info(
        "Recorded outcome: type=%s is_bad=%s score=%.2f agent=%s verdict=%s",
        outcome_type, is_bad, outcome_score, agent_id, eisv_verdict,
    )

    # Record calibration from outcome event
    if _confidence is not None:
        try:
            from src.calibration import calibration_checker
            calibration_checker.record_prediction(
                confidence=_confidence,
                predicted_correct=(_confidence >= 0.5),
                actual_correct=float(outcome_score),
            )
            # Test outcomes are strong exogenous signals — record tactical too
            if outcome_type in ('test_passed', 'test_failed'):
                calibration_checker.record_tactical_decision(
                    confidence=_confidence,
                    decision='proceed',
                    immediate_outcome=not is_bad,
                )
        except Exception as e_cal:
            logger.debug(f"Calibration from outcome_event skipped: {e_cal}")

        if eprocess_eligible:
            try:
                from src.sequential_calibration import sequential_calibration_tracker

                sequential_calibration_tracker.record_exogenous_tactical_outcome(
                    confidence=_confidence,
                    outcome_correct=not is_bad,
                    agent_id=agent_id,
                    signal_source=hard_exogenous_signal,
                    decision_action=decision_action,
                    outcome_type=outcome_type,
                )
            except Exception as e_seq:
                logger.debug(f"Sequential calibration tracking skipped: {e_seq}")

    return success_response({
        "outcome_id": outcome_id,
        "outcome_type": outcome_type,
        "is_bad": is_bad,
        "outcome_score": outcome_score,
        "eisv_snapshot": snapshot,
    })


@mcp_tool("outcome_correlation", timeout=30.0)
async def handle_outcome_correlation(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Run outcome correlation study: does EISV instability predict bad outcomes?"""
    from src.outcome_correlation import OutcomeCorrelation
    from ..context import get_context_agent_id
    import dataclasses

    agent_id = arguments.get("agent_id") or get_context_agent_id()
    since_hours = float(arguments.get("since_hours", 168))

    try:
        study = OutcomeCorrelation()
        report = await study.run(agent_id=agent_id, since_hours=since_hours)

        if report.total_outcomes == 0:
            return [error_response(
                f"No outcome events found in the last {since_hours:.0f} hours"
                + (f" for agent {agent_id}" if agent_id else ""),
                error_code="NO_DATA",
                error_category="validation_error",
            )]

        return success_response(dataclasses.asdict(report))
    except Exception as e:
        logger.error(f"Outcome correlation failed: {e}")
        return [error_response(
            f"Correlation study failed: {e}",
            error_code="STUDY_ERROR",
            error_category="system_error",
        )]
