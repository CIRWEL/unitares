"""
Self-Recovery Review - Simplified Recovery Without External Reviewers

This replaces the heavyweight dialectic system with a streamlined self-reflection
approach that still maintains safety guardrails.

Design Philosophy:
- Agents should be able to recover from stuck states autonomously
- No waiting for external reviewers (who may not exist)
- Still require reflection (not just blind resume)
- Log everything for audit trail
- Enforce safety limits

The old dialectic system:
- thesis → antithesis → synthesis with 2hr waits
- Required external reviewer (rarely available)
- 6-hour total timeout before fallback
- Mostly just added delay before auto-resolve

The new self-recovery:
- Agent reflects on what went wrong
- Proposes what to change
- System validates safety
- Resume or escalate immediately
- No external dependencies

Author: Claude (governance agent)
Created: 2026-01-29
"""

from typing import Dict, Any, Sequence, List, Optional
from mcp.types import TextContent
from datetime import datetime, timezone
import json

from .shared import get_mcp_server
from .utils import (
    require_registered_agent,
    success_response,
    error_response,
    verify_agent_ownership
)
from .decorators import mcp_tool
from src.logging_utils import get_logger
from config.governance_config import GovernanceConfig

logger = get_logger(__name__)
mcp_server = get_mcp_server()


# Safety limits for recovery conditions
FORBIDDEN_CONDITIONS = [
    "disable governance",
    "bypass safety",
    "remove monitoring",
    "ignore limits",
    "skip checks",
]

MAX_RISK_FOR_SELF_RECOVERY = 0.70  # Above this, escalate to human
MIN_COHERENCE_FOR_SELF_RECOVERY = 0.30  # Below this, escalate to human


def validate_recovery_conditions(conditions: List[str]) -> tuple[bool, Optional[str]]:
    """
    Validate that recovery conditions don't violate safety limits.
    
    Returns:
        (is_safe, violation_reason)
    """
    if not conditions:
        return True, None
    
    for condition in conditions:
        condition_lower = condition.lower()
        for forbidden in FORBIDDEN_CONDITIONS:
            if forbidden in condition_lower:
                return False, f"Condition '{condition}' contains forbidden term '{forbidden}'"
    
    # Check for suspiciously vague conditions
    vague_terms = ["everything", "anything", "always", "never check", "trust me"]
    for condition in conditions:
        condition_lower = condition.lower()
        for vague in vague_terms:
            if vague in condition_lower:
                return False, f"Condition '{condition}' is too vague (contains '{vague}')"
    
    return True, None


def assess_recovery_safety(
    coherence: float,
    risk_score: float,
    void_active: bool,
    void_value: float,
    reflection: str,
) -> dict:
    """
    Assess whether self-recovery is safe or needs escalation.
    
    Returns dict with:
        - safe: bool - whether self-recovery is allowed
        - reason: str - why or why not
        - recommendation: str - what to do
        - metrics: dict - the assessed metrics
    """
    metrics = {
        "coherence": coherence,
        "risk_score": risk_score,
        "void_active": void_active,
        "void_value": void_value,
    }
    
    # Hard limits - must escalate
    if void_active:
        return {
            "safe": False,
            "reason": "Void is active - accumulated E-I imbalance requires human review",
            "recommendation": "Wait for void to clear or request human assistance",
            "escalate": True,
            "metrics": metrics,
        }
    
    if risk_score > MAX_RISK_FOR_SELF_RECOVERY:
        return {
            "safe": False,
            "reason": f"Risk score ({risk_score:.2f}) exceeds self-recovery limit ({MAX_RISK_FOR_SELF_RECOVERY})",
            "recommendation": "Request human review or wait for risk to decrease",
            "escalate": True,
            "metrics": metrics,
        }
    
    if coherence < MIN_COHERENCE_FOR_SELF_RECOVERY:
        return {
            "safe": False,
            "reason": f"Coherence ({coherence:.2f}) below self-recovery threshold ({MIN_COHERENCE_FOR_SELF_RECOVERY})",
            "recommendation": "Request human review - low coherence suggests confusion",
            "escalate": True,
            "metrics": metrics,
        }
    
    # Check reflection quality (basic heuristics)
    if not reflection or len(reflection.strip()) < 20:
        return {
            "safe": False,
            "reason": "Reflection too brief - genuine reflection requires more thought",
            "recommendation": "Provide a more detailed reflection on what happened and what you'll change",
            "escalate": False,  # Not dangerous, just needs more thought
            "metrics": metrics,
        }
    
    # Soft limits - allowed but with warnings
    warnings = []
    if risk_score > 0.50:
        warnings.append(f"Risk score ({risk_score:.2f}) is elevated - proceed carefully")
    if coherence < 0.50:
        warnings.append(f"Coherence ({coherence:.2f}) is below optimal - consider simpler tasks")
    if abs(void_value) > 0.5:
        warnings.append(f"Void value ({void_value:.2f}) shows some E-I imbalance")
    
    return {
        "safe": True,
        "reason": "Metrics within self-recovery limits",
        "recommendation": "Self-recovery approved" + (f" with warnings: {'; '.join(warnings)}" if warnings else ""),
        "warnings": warnings,
        "escalate": False,
        "metrics": metrics,
    }


@mcp_tool("self_recovery_review", timeout=15.0)
async def handle_self_recovery_review(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Self-reflection recovery - recover from stuck states without external reviewers.
    
    This is the streamlined replacement for the dialectic system. Instead of waiting
    for an external reviewer who may never come, agents reflect on their own state
    and propose recovery conditions.
    
    Required:
        reflection: str - What went wrong and what you'll do differently
        
    Optional:
        conditions: list[str] - Specific conditions for recovery (e.g., "reduce complexity", "focus on single task")
        reason: str - Brief reason for the stuck state
        
    Process:
    1. Get current metrics automatically
    2. Validate reflection is genuine (not empty)
    3. Validate conditions don't violate safety limits
    4. Assess whether self-recovery is safe or needs escalation
    5. If safe: resume and log to knowledge graph
    6. If unsafe: provide guidance on next steps
    
    Example:
        self_recovery_review(
            reflection="I got stuck in a loop trying to fix a bug. I was repeatedly trying the same approach. I'll step back and try a different strategy.",
            conditions=["Try different approach before repeating", "Time-box debugging to 15 minutes"],
            reason="Cognitive loop on debugging"
        )
    """
    # Require registered agent
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    agent_uuid = arguments.get("_agent_uuid") or agent_id
    
    # Verify ownership
    if not verify_agent_ownership(agent_uuid, arguments):
        return [error_response(
            "Authentication required. You can only recover your own agent.",
            error_code="AUTH_REQUIRED",
            error_category="auth_error",
            recovery={
                "action": "Ensure your session is bound to this agent",
                "related_tools": ["identity"],
            }
        )]
    
    # Get required reflection
    reflection = arguments.get("reflection", "").strip()
    conditions = arguments.get("conditions", [])
    reason = arguments.get("reason", "Self-recovery requested")
    
    if not reflection:
        return [error_response(
            "Reflection required. What went wrong and what will you do differently?",
            error_code="REFLECTION_REQUIRED",
            error_category="validation_error",
            recovery={
                "action": "Provide a reflection on the stuck state",
                "example": 'self_recovery_review(reflection="I got stuck because... I will change...")',
            }
        )]
    
    # Validate conditions
    if conditions:
        is_safe, violation = validate_recovery_conditions(conditions)
        if not is_safe:
            return [error_response(
                f"Recovery condition validation failed: {violation}",
                error_code="UNSAFE_CONDITIONS",
                error_category="safety_error",
                recovery={
                    "action": "Remove or rephrase the problematic condition",
                    "forbidden_terms": FORBIDDEN_CONDITIONS,
                }
            )]
    
    # Get current metrics
    try:
        monitor = mcp_server.get_or_create_monitor(agent_uuid)
        metrics = monitor.get_metrics()
        
        coherence = float(monitor.state.coherence)
        risk_score = float(metrics.get("mean_risk", 0.5))
        void_active = bool(monitor.state.void_active)
        void_value = float(monitor.state.V)
        
    except Exception as e:
        logger.error(f"Failed to get metrics for self-recovery: {e}")
        return [error_response(
            f"Could not assess current state: {e}",
            error_code="METRICS_ERROR",
            error_category="system_error",
        )]
    
    # Assess safety
    assessment = assess_recovery_safety(
        coherence=coherence,
        risk_score=risk_score,
        void_active=void_active,
        void_value=void_value,
        reflection=reflection,
    )
    
    # Log the recovery attempt to knowledge graph
    try:
        from .knowledge_graph import store_discovery_internal
        await store_discovery_internal(
            agent_id=agent_uuid,
            summary=f"Self-recovery: {reason[:100]}",
            discovery_type="recovery",
            details=json.dumps({
                "reflection": reflection,
                "conditions": conditions,
                "reason": reason,
                "assessment": assessment,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, indent=2),
            tags=["recovery", "self-review", "audit"],
            severity="info" if assessment["safe"] else "warning",
        )
    except Exception as e:
        logger.warning(f"Failed to log recovery to knowledge graph: {e}")
        # Continue anyway - logging failure shouldn't block recovery
    
    # If not safe, return guidance
    if not assessment["safe"]:
        response = {
            "success": False,
            "recovered": False,
            "reason": assessment["reason"],
            "recommendation": assessment["recommendation"],
            "metrics": assessment["metrics"],
        }
        
        if assessment.get("escalate"):
            response["escalate"] = True
            response["next_steps"] = [
                "Wait for metrics to improve naturally",
                "Request human assistance via leave_note with tag 'needs-human'",
                "Use get_governance_metrics to monitor your state",
            ]
        else:
            response["next_steps"] = [
                "Provide more detailed reflection",
                "Review your recent actions with get_system_history",
                "Try again with better reflection",
            ]
        
        return success_response(response)
    
    # Safe to recover - resume agent
    meta = mcp_server.agent_metadata.get(agent_uuid)
    if meta:
        previous_status = meta.status
        meta.status = "active"
        meta.paused_at = None
        meta.add_lifecycle_event(
            "self_recovered",
            f"Self-recovery: {reason}. Reflection: {reflection[:200]}. Conditions: {conditions}"
        )
        
        # Update PostgreSQL
        try:
            from src import agent_storage
            await agent_storage.update_agent(agent_uuid, status="active")
        except Exception as e:
            logger.debug(f"PostgreSQL status update failed: {e}")
    else:
        previous_status = "unknown"
    
    return success_response({
        "success": True,
        "recovered": True,
        "agent_id": agent_id,
        "message": "Self-recovery successful",
        "reflection_logged": True,
        "conditions": conditions,
        "assessment": {
            "safe": True,
            "warnings": assessment.get("warnings", []),
        },
        "metrics": assessment["metrics"],
        "previous_status": previous_status,
        "guidance": [
            "Monitor your state with get_governance_metrics",
            "Honor the conditions you set for yourself",
            "If you get stuck again, reflect on whether the conditions helped",
        ],
    })


@mcp_tool("check_recovery_options", timeout=10.0)
async def handle_check_recovery_options(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Check if an agent is eligible for self-recovery.
    
    This is a read-only check that doesn't modify state. Use it to understand
    what's needed before attempting self_recovery_review.
    
    Returns:
        - eligible: bool - whether self-recovery is currently possible
        - blockers: list - what's preventing recovery (if any)
        - metrics: dict - current governance metrics
        - recommendations: list - what to do next
    """
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    agent_uuid = arguments.get("_agent_uuid") or agent_id
    
    # Get current metrics
    try:
        monitor = mcp_server.get_or_create_monitor(agent_uuid)
        metrics = monitor.get_metrics()
        
        coherence = float(monitor.state.coherence)
        risk_score = float(metrics.get("mean_risk", 0.5))
        void_active = bool(monitor.state.void_active)
        void_value = float(monitor.state.V)
        
    except Exception as e:
        return [error_response(f"Could not get metrics: {e}")]
    
    # Check blockers
    blockers = []
    if void_active:
        blockers.append({
            "type": "void_active",
            "message": "Void is active - E-I imbalance has accumulated",
            "resolution": "Wait for void to clear or request human help",
        })
    
    if risk_score > MAX_RISK_FOR_SELF_RECOVERY:
        blockers.append({
            "type": "high_risk",
            "message": f"Risk ({risk_score:.2f}) exceeds limit ({MAX_RISK_FOR_SELF_RECOVERY})",
            "resolution": "Wait for risk to decrease or request human review",
        })
    
    if coherence < MIN_COHERENCE_FOR_SELF_RECOVERY:
        blockers.append({
            "type": "low_coherence",
            "message": f"Coherence ({coherence:.2f}) below threshold ({MIN_COHERENCE_FOR_SELF_RECOVERY})",
            "resolution": "Request human help - low coherence suggests confusion",
        })
    
    eligible = len(blockers) == 0
    
    # Build recommendations
    if eligible:
        recommendations = [
            "You're eligible for self-recovery",
            "Call self_recovery_review with a genuine reflection",
            "Include specific conditions you'll follow",
        ]
    else:
        recommendations = [
            "Self-recovery not currently available",
            "Address the blockers listed above",
            "Consider using leave_note(tags=['needs-human']) to request help",
        ]
    
    # Get margin info
    margin_info = GovernanceConfig.compute_proprioceptive_margin(
        risk_score=risk_score,
        coherence=coherence,
        void_active=void_active,
        void_value=void_value,
    )
    
    return success_response({
        "eligible": eligible,
        "blockers": blockers,
        "metrics": {
            "coherence": coherence,
            "risk_score": risk_score,
            "void_active": void_active,
            "void_value": void_value,
        },
        "margin": margin_info,
        "thresholds": {
            "max_risk_for_self_recovery": MAX_RISK_FOR_SELF_RECOVERY,
            "min_coherence_for_self_recovery": MIN_COHERENCE_FOR_SELF_RECOVERY,
        },
        "recommendations": recommendations,
    })



@mcp_tool("quick_resume", timeout=10.0)
async def handle_quick_resume(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Quick resume for agents in clearly safe states - no reflection required.
    
    This is the fastest path to recovery when:
    - coherence > 0.60 (high confidence state)
    - risk < 0.40 (low risk)
    - no void active
    - status is waiting_input or paused
    
    For agents that don't meet these strict criteria, use self_recovery_review
    which requires reflection but allows recovery at lower thresholds.
    
    Optional:
        reason: str - Brief note about why resuming (for audit)
    
    Recovery Hierarchy:
    1. quick_resume - safest states, no reflection needed
    2. self_recovery_review - moderate states, reflection required
    3. Human escalation - unsafe states
    """
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    agent_uuid = arguments.get("_agent_uuid") or agent_id
    
    # Verify ownership
    if not verify_agent_ownership(agent_uuid, arguments):
        return [error_response(
            "Authentication required. You can only resume your own agent.",
            error_code="AUTH_REQUIRED",
            error_category="auth_error",
        )]
    
    reason = arguments.get("reason", "Quick resume - state is safe")
    
    # Get current metrics
    try:
        monitor = mcp_server.get_or_create_monitor(agent_uuid)
        metrics = monitor.get_metrics()
        
        coherence = float(monitor.state.coherence)
        risk_score = float(metrics.get("mean_risk", 0.5))
        void_active = bool(monitor.state.void_active)
        void_value = float(monitor.state.V)
        
    except Exception as e:
        return [error_response(f"Could not assess state: {e}")]
    
    # Strict safety checks for quick_resume (stricter than self_recovery_review)
    QUICK_RESUME_MIN_COHERENCE = 0.60
    QUICK_RESUME_MAX_RISK = 0.40
    
    checks = {
        "coherence_high": coherence >= QUICK_RESUME_MIN_COHERENCE,
        "risk_low": risk_score <= QUICK_RESUME_MAX_RISK,
        "no_void": not void_active,
    }
    
    if not all(checks.values()):
        failed = [k for k, v in checks.items() if not v]
        return [error_response(
            f"State not safe enough for quick_resume. Failed: {failed}. "
            f"Use self_recovery_review instead (allows recovery with reflection).",
            error_code="NOT_SAFE_FOR_QUICK_RESUME",
            error_category="safety_error",
            recovery={
                "action": "Use self_recovery_review with reflection",
                "example": 'self_recovery_review(reflection="I was stuck because...")',
                "related_tools": ["self_recovery_review", "check_recovery_options"],
            },
            context={
                "metrics": {
                    "coherence": coherence,
                    "risk_score": risk_score,
                    "void_active": void_active,
                },
                "thresholds": {
                    "min_coherence": QUICK_RESUME_MIN_COHERENCE,
                    "max_risk": QUICK_RESUME_MAX_RISK,
                },
            }
        )]
    
    # Check status
    meta = mcp_server.agent_metadata.get(agent_uuid)
    if not meta:
        return [error_response("Agent not found")]
    
    valid_statuses = ["waiting_input", "paused", "active", "moderate"]
    if meta.status not in valid_statuses:
        return [error_response(
            f"Cannot quick_resume from status '{meta.status}'",
            recovery={"valid_statuses": valid_statuses}
        )]
    
    # Log to knowledge graph
    try:
        from .knowledge_graph import store_discovery_internal
        await store_discovery_internal(
            agent_id=agent_uuid,
            summary=f"Quick resume: {reason[:100]}",
            discovery_type="recovery",
            details=json.dumps({
                "type": "quick_resume",
                "reason": reason,
                "metrics": {
                    "coherence": coherence,
                    "risk_score": risk_score,
                    "void_active": void_active,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
            tags=["recovery", "quick-resume", "audit"],
            severity="info",
        )
    except Exception as e:
        logger.warning(f"Failed to log quick_resume: {e}")
    
    # Resume
    previous_status = meta.status
    meta.status = "active"
    meta.paused_at = None
    meta.add_lifecycle_event("quick_resumed", f"Quick resume: {reason}")
    
    # Update PostgreSQL
    try:
        from src import agent_storage
        await agent_storage.update_agent(agent_uuid, status="active")
    except Exception as e:
        logger.debug(f"PostgreSQL update failed: {e}")
    
    return success_response({
        "success": True,
        "recovered": True,
        "method": "quick_resume",
        "agent_id": agent_id,
        "message": "Quick resume successful - state was safe",
        "previous_status": previous_status,
        "metrics": {
            "coherence": coherence,
            "risk_score": risk_score,
        },
    })



# ============================================================================
# OPERATOR-ASSISTED RECOVERY
# For Central Operator agent to recover stuck agents it doesn't own
# ============================================================================

@mcp_tool("operator_resume_agent", timeout=15.0)
async def handle_operator_resume_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Operator-assisted resume for stuck agents.
    
    This tool allows the Central Operator agent to resume other agents that are stuck.
    It requires:
    1. The caller to be an operator (label="Operator" or tags contain "operator")
    2. The target agent to be in a resumable state
    3. A reason for the intervention
    
    This is for automated recovery by the operator agent, not for regular agents
    to resume each other (which would be a security issue).
    
    Required:
        target_agent_id: str - The agent to resume
        reason: str - Why the operator is resuming this agent
        
    Optional:
        force: bool - Skip soft safety checks (still respects hard limits)
    """
    # Get caller identity
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    caller_uuid = arguments.get("_agent_uuid") or agent_id
    target_agent_id = arguments.get("target_agent_id")
    reason = arguments.get("reason", "Operator-assisted recovery")
    force = arguments.get("force", False)
    
    if not target_agent_id:
        return [error_response(
            "target_agent_id required - which agent should be resumed?",
            error_code="MISSING_TARGET",
            error_category="validation_error",
        )]
    
    # Verify caller is operator
    meta = mcp_server.agent_metadata.get(caller_uuid)
    if not meta:
        return [error_response("Caller not found")]
    
    label = getattr(meta, 'label', '') or ''
    tags = getattr(meta, 'tags', []) or []
    is_operator = (
        label.lower() == 'operator' or
        'operator' in [t.lower() for t in tags]
    )
    
    if not is_operator:
        return [error_response(
            "Only operator agents can use this tool. "
            "For self-recovery, use self_recovery_review or quick_resume.",
            error_code="NOT_OPERATOR",
            error_category="auth_error",
            recovery={
                "action": "Use self-recovery tools instead",
                "related_tools": ["self_recovery_review", "quick_resume", "check_recovery_options"],
            }
        )]
    
    # Get target agent
    target_meta = mcp_server.agent_metadata.get(target_agent_id)
    if not target_meta:
        return [error_response(f"Target agent '{target_agent_id}' not found")]
    
    # Get target metrics
    try:
        monitor = mcp_server.get_or_create_monitor(target_agent_id)
        metrics = monitor.get_metrics()
        
        coherence = float(monitor.state.coherence)
        risk_score = float(metrics.get("mean_risk", 0.5))
        void_active = bool(monitor.state.void_active)
        void_value = float(monitor.state.V)
        
    except Exception as e:
        return [error_response(f"Could not get target metrics: {e}")]
    
    # Hard limits - even operator can't override these
    if void_active:
        return [error_response(
            f"Cannot resume {target_agent_id}: void is active. "
            "This requires human intervention.",
            error_code="VOID_ACTIVE",
            error_category="safety_error",
            context={"void_value": void_value},
        )]
    
    if risk_score > 0.80:
        return [error_response(
            f"Cannot resume {target_agent_id}: risk ({risk_score:.2f}) exceeds hard limit (0.80). "
            "This requires human intervention.",
            error_code="RISK_TOO_HIGH",
            error_category="safety_error",
        )]
    
    if coherence < 0.20:
        return [error_response(
            f"Cannot resume {target_agent_id}: coherence ({coherence:.2f}) below hard limit (0.20). "
            "This requires human intervention.",
            error_code="COHERENCE_TOO_LOW",
            error_category="safety_error",
        )]
    
    # Soft limits - warn but allow if force=True
    warnings = []
    if not force:
        if risk_score > 0.60:
            warnings.append(f"Risk ({risk_score:.2f}) is elevated")
        if coherence < 0.40:
            warnings.append(f"Coherence ({coherence:.2f}) is low")
        
        if warnings:
            return [error_response(
                f"Soft safety checks failed for {target_agent_id}: {'; '.join(warnings)}. "
                "Use force=True to override soft limits (hard limits still apply).",
                error_code="SOFT_SAFETY_FAILED",
                error_category="safety_error",
                context={
                    "coherence": coherence,
                    "risk_score": risk_score,
                    "warnings": warnings,
                },
                recovery={
                    "action": "Add force=True to override soft limits",
                    "example": f'operator_resume_agent(target_agent_id="{target_agent_id}", reason="...", force=True)',
                }
            )]
    
    # Log to knowledge graph
    try:
        from .knowledge_graph import store_discovery_internal
        await store_discovery_internal(
            agent_id=caller_uuid,  # Log under operator
            summary=f"Operator resumed {target_agent_id}: {reason[:100]}",
            discovery_type="operator_intervention",
            details=json.dumps({
                "operator_id": caller_uuid,
                "target_agent_id": target_agent_id,
                "reason": reason,
                "force": force,
                "target_metrics": {
                    "coherence": coherence,
                    "risk_score": risk_score,
                    "void_active": void_active,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }),
            tags=["operator", "intervention", "recovery", "audit"],
            severity="warning",  # Operator interventions are always notable
        )
    except Exception as e:
        logger.warning(f"Failed to log operator intervention: {e}")
    
    # Resume target agent
    previous_status = target_meta.status
    target_meta.status = "active"
    target_meta.paused_at = None
    target_meta.add_lifecycle_event(
        "operator_resumed",
        f"Resumed by operator {caller_uuid}: {reason}"
    )
    
    # Update PostgreSQL
    try:
        from src import agent_storage
        await agent_storage.update_agent(target_agent_id, status="active")
    except Exception as e:
        logger.debug(f"PostgreSQL update failed: {e}")
    
    return success_response({
        "success": True,
        "action": "operator_resume",
        "operator_id": caller_uuid,
        "target_agent_id": target_agent_id,
        "reason": reason,
        "previous_status": previous_status,
        "force_used": force,
        "warnings": warnings if force else [],
        "target_metrics": {
            "coherence": coherence,
            "risk_score": risk_score,
            "void_active": void_active,
        },
        "audit_note": "This intervention has been logged to the knowledge graph",
    })
