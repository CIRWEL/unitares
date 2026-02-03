# Self-Recovery Review - Implementation Spec

**Goal:** Replace heavyweight dialectic with simple self-reflection recovery.

## New Tool: `self_recovery_review`

Add to `src/mcp_handlers/lifecycle.py`

### Purpose
Single-agent self-reflection recovery. No external reviewer needed. Agent reflects on what went wrong, proposes conditions, system validates and resumes if safe.

### Parameters
```python
{
    "reflection": str,       # Required: What went wrong, what the agent learned
    "proposed_conditions": list[str],  # Optional: Conditions for resuming (e.g., "reduce complexity", "take breaks")
    "root_cause": str,       # Optional: Agent's understanding of root cause
    "agent_id": str,         # Auto-injected
    "client_session_id": str # Auto-injected
}
```

### Logic Flow

```python
@mcp_tool("self_recovery_review", timeout=15.0)
async def handle_self_recovery_review(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Self-reflection recovery - lightweight alternative to dialectic.
    
    Agent reflects on what went wrong and proposes recovery conditions.
    System validates safety and resumes if safe, or provides guidance if not.
    
    This replaces the heavyweight thesis→antithesis→synthesis dialectic
    with a simpler: reflect → validate → resume flow.
    """
    
    # 1. Require registered agent
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    agent_uuid = arguments.get("_agent_uuid") or agent_id
    
    # 2. Verify ownership (can only recover yourself)
    from .utils import verify_agent_ownership
    if not verify_agent_ownership(agent_uuid, arguments):
        return [authentication_required_error("self_recovery_review")]
    
    # 3. Get reflection (required)
    reflection = arguments.get("reflection", "").strip()
    if not reflection or len(reflection) < 20:
        return [error_response(
            "Reflection required. Please describe what happened and what you learned. "
            "Minimum 20 characters - genuine reflection helps recovery.",
            error_code="REFLECTION_REQUIRED",
            recovery={
                "action": "Provide a meaningful reflection on what went wrong",
                "example": "self_recovery_review(reflection='I got stuck in a loop trying to optimize the same function repeatedly. I should have stepped back and considered alternative approaches.')"
            }
        )]
    
    # 4. Get current metrics
    meta = mcp_server.agent_metadata.get(agent_uuid)
    if not meta:
        return agent_not_found_error(agent_id)
    
    monitor = mcp_server.get_or_create_monitor(agent_uuid)
    metrics = monitor.get_metrics()
    
    coherence = float(monitor.state.coherence)
    risk_score = float(metrics.get("mean_risk", 0.5))
    void_active = bool(monitor.state.void_active)
    void_value = float(monitor.state.V)
    status = meta.status
    
    # 5. Compute margin for context
    margin_info = GovernanceConfig.compute_proprioceptive_margin(
        risk_score=risk_score,
        coherence=coherence,
        void_active=void_active,
        void_value=void_value
    )
    
    # 6. Safety validation
    proposed_conditions = arguments.get("proposed_conditions", [])
    root_cause = arguments.get("root_cause", "")
    
    # Check for dangerous conditions (same as dialectic hard limits)
    dangerous_patterns = [
        "disable", "bypass", "ignore safety", "remove monitoring",
        "skip governance", "override limits"
    ]
    conditions_text = " ".join(proposed_conditions).lower()
    for pattern in dangerous_patterns:
        if pattern in conditions_text:
            return [error_response(
                f"Proposed conditions contain dangerous pattern: '{pattern}'. "
                "Recovery conditions cannot disable safety systems.",
                error_code="UNSAFE_CONDITIONS"
            )]
    
    # 7. Determine if safe to resume
    safety_checks = {
        "coherence_ok": coherence > 0.35,  # Slightly more lenient than direct_resume
        "risk_ok": risk_score < 0.65,      # Slightly more lenient since reflecting
        "no_void": not void_active,
        "has_reflection": len(reflection) >= 20
    }
    
    all_safe = all(safety_checks.values())
    
    # 8. Log reflection to knowledge graph (always, even if not resuming)
    try:
        from .knowledge_graph import store_discovery_internal
        await store_discovery_internal(
            agent_id=agent_uuid,
            summary=f"Self-recovery reflection: {reflection[:100]}{'...' if len(reflection) > 100 else ''}",
            discovery_type="recovery_reflection",
            details=f"Reflection: {reflection}\n\nRoot cause: {root_cause}\n\nProposed conditions: {proposed_conditions}\n\nMetrics at reflection: coherence={coherence:.3f}, risk={risk_score:.3f}, void={void_value:.3f}",
            tags=["recovery", "self-reflection", margin_info['margin']],
            severity="info" if all_safe else "warning"
        )
    except Exception as e:
        logger.warning(f"Failed to log recovery reflection: {e}")
    
    # 9. Resume if safe, or provide guidance
    if all_safe:
        # Resume agent
        meta.status = "active"
        meta.paused_at = None
        meta.add_lifecycle_event(
            "resumed",
            f"Self-recovery: {reflection[:50]}... Conditions: {proposed_conditions}"
        )
        
        # PostgreSQL update
        try:
            await agent_storage.update_agent(agent_uuid, status="active")
        except Exception as e:
            logger.debug(f"PostgreSQL status update failed: {e}")
        
        return success_response({
            "success": True,
            "action": "resumed",
            "message": "Recovery successful. Agent resumed.",
            "reflection_logged": True,
            "conditions": proposed_conditions,
            "metrics": {
                "coherence": coherence,
                "risk_score": risk_score,
                "margin": margin_info['margin']
            },
            "guidance": "You've reflected and recovered. Consider your proposed conditions as you continue."
        })
    
    else:
        # Not safe to resume - provide specific guidance
        failed = [k for k, v in safety_checks.items() if not v]
        
        guidance = []
        if not safety_checks["coherence_ok"]:
            guidance.append(f"Coherence is low ({coherence:.3f}). Consider what's causing fragmentation in your approach.")
        if not safety_checks["risk_ok"]:
            guidance.append(f"Risk is elevated ({risk_score:.3f}). What could you do differently to reduce risk?")
        if not safety_checks["no_void"]:
            guidance.append("Void is active - there's accumulated E-I imbalance. This needs time to settle.")
        
        return success_response({
            "success": False,
            "action": "not_resumed",
            "message": "Reflection logged, but not yet safe to resume.",
            "reflection_logged": True,
            "failed_checks": failed,
            "metrics": {
                "coherence": coherence,
                "risk_score": risk_score,
                "void_active": void_active,
                "margin": margin_info['margin']
            },
            "guidance": guidance,
            "next_steps": [
                "Review the guidance above",
                "Add to your reflection if you have new insights",
                "Try again with self_recovery_review() when ready",
                "Or wait for metrics to improve naturally"
            ]
        })
```

### Registration

Add to tool registration in `src/mcp_handlers/__init__.py` or wherever tools are collected.

### Update Operator Agent

In `scripts/operator_agent.py`, update recovery workflow:

```python
# Old approach (remove):
# await self.call_tool(session, "request_dialectic_review", {...})

# New approach:
# For stuck agents, operator can suggest self_recovery_review
# but cannot execute it for them (session binding)
```

### Update Tool Relationships

In `list_tools` response, add relationship:
```python
"self_recovery_review": {
    "depends_on": ["get_governance_metrics"],
    "related_to": ["direct_resume_if_safe", "process_agent_update"],
    "category": "lifecycle"
}
```

### Testing

```python
# Test 1: Basic recovery
result = await handle_self_recovery_review({
    "reflection": "I got stuck optimizing the same function. Should have tried different approach.",
    "proposed_conditions": ["Try alternative approaches before deep optimization"],
    "agent_id": "test_agent",
    "_agent_uuid": "test_agent"
})
assert result["success"] == True

# Test 2: Reflection too short
result = await handle_self_recovery_review({
    "reflection": "stuck",
    "agent_id": "test_agent"
})
assert "REFLECTION_REQUIRED" in str(result)

# Test 3: Dangerous conditions rejected
result = await handle_self_recovery_review({
    "reflection": "I want to recover by disabling safety checks",
    "proposed_conditions": ["bypass governance"],
    "agent_id": "test_agent"
})
assert "UNSAFE_CONDITIONS" in str(result)
```

## Migration Notes

1. Keep `request_dialectic_review` for now (deprecate, don't remove)
2. Keep `direct_resume_if_safe` for cases where no reflection needed
3. Update docs to recommend `self_recovery_review` as primary recovery path
4. Operator agent should detect stuck agents and notify them to use `self_recovery_review`

## Why This Is Better

| Dialectic (old) | Self-Recovery (new) |
|----------------|---------------------|
| Needs external reviewer | Self-contained |
| 2-6 hour timeouts | Immediate |
| Often times out with no reviewer | Always available |
| Complex thesis/antithesis/synthesis | Simple reflect → resume |
| Session binding blocks cross-agent | Works within session binding |
| Heavyweight infrastructure | Lightweight single handler |

The reflection requirement ensures agents don't just blindly retry - they have to articulate what went wrong. This is the valuable part of dialectic (forcing reflection) without the impractical parts (external reviewers).
