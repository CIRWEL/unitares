"""
Outcome Events Tool - Record measurable outcomes paired with EISV snapshots.

Enables validation of the EISV model by collecting real outcome data
(drawing completions, test results, task completions) alongside the
EISV state at outcome time.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
from .utils import success_response, error_response
from .decorators import mcp_tool
from src.logging_utils import get_logger

logger = get_logger(__name__)

# Outcome types that are considered "bad" by default
BAD_OUTCOME_TYPES = {"test_failed", "tool_rejected", "drawing_abandoned", "task_failed"}
GOOD_OUTCOME_TYPES = {"test_passed", "drawing_completed", "task_completed"}
VALID_OUTCOME_TYPES = BAD_OUTCOME_TYPES | GOOD_OUTCOME_TYPES


@mcp_tool("outcome_event", timeout=15.0)
async def handle_outcome_event(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Record an outcome event paired with the agent's current EISV snapshot."""
    from src.db import get_db
    from .context import get_context_agent_id

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

    detail = arguments.get("detail") or {}

    # Fetch latest EISV snapshot for this agent
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

    # Insert
    outcome_id = await db.record_outcome_event(
        agent_id=agent_id,
        outcome_type=outcome_type,
        is_bad=is_bad,
        outcome_score=outcome_score,
        session_id=arguments.get("session_id"),
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

    return success_response({
        "outcome_id": outcome_id,
        "outcome_type": outcome_type,
        "is_bad": is_bad,
        "outcome_score": outcome_score,
        "eisv_snapshot": {
            "E": eisv_e,
            "I": eisv_i,
            "S": eisv_s,
            "V": eisv_v,
            "phi": eisv_phi,
            "verdict": eisv_verdict,
            "coherence": eisv_coherence,
            "regime": eisv_regime,
        } if eisv else None,
    })
