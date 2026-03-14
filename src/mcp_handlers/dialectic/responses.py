"""Shared response builders for dialectic handlers.

Keep user-facing response text in one place so submit handlers stay consistent
as flows evolve.
"""

from __future__ import annotations

from typing import Any, Dict, List


def missing_session_id_recovery() -> Dict[str, Any]:
    """Recovery payload for submit handlers missing `session_id`."""
    return {
        "action": "Provide session_id",
        "related_tools": ["get_dialectic_session", "identity"],
    }


def session_not_found_recovery() -> Dict[str, Any]:
    """Recovery payload when a dialectic session cannot be loaded."""
    return {
        "action": "Session may have expired or been resolved",
        "related_tools": ["get_dialectic_session", "request_dialectic_review"],
    }


def next_step_submit_antithesis(reviewer_agent_id: str | None) -> str:
    """Next-step guidance after successful thesis submission."""
    return f"Reviewer '{reviewer_agent_id}' should submit antithesis"


def next_step_negotiate_synthesis() -> str:
    """Next-step guidance after successful antithesis submission."""
    return "Both agents should negotiate via submit_synthesis() until convergence"


def next_step_resumed() -> str:
    """Guidance when resolution execution resumed the paused agent."""
    return "Agent resumed successfully with agreed conditions"


def next_step_resume_not_applied(warning: str | None) -> str:
    """Guidance when synthesis converges but no resume transition executes."""
    detail = warning or "No lifecycle transition was applied."
    return f"Resolution recorded, but no resume action applied: {detail}"


def next_step_execution_failed(error: Exception) -> str:
    """Guidance when resolution execution raises an exception."""
    return f"Failed to execute resolution: {error}"


def next_step_no_consensus() -> str:
    """Guidance when synthesis reaches conservative no-consensus path."""
    return "Peers could not reach consensus. Maintaining current state."


def default_resume_steps() -> List[str]:
    return [
        "You can resume work with the agreed conditions",
        "Call process_agent_update() to log your next action",
        "Monitor your coherence with get_governance_metrics()",
    ]


def default_cooldown_steps() -> List[str]:
    return [
        "Take a brief pause before resuming",
        "Review the synthesis reasoning",
        "When ready, call process_agent_update() with lower complexity",
    ]


def default_escalate_steps() -> List[str]:
    return [
        "The dialectic suggests human review may be needed",
        "Consider simplifying your approach",
        "Use request_dialectic_review() for peer review if available",
    ]
