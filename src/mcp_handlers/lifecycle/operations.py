"""
Lifecycle operational handlers — resume, ping, response completion, archive cleanup,
and self-recovery review.

Extracted from handlers.py for maintainability.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
from datetime import datetime, timedelta, timezone

from src import agent_storage
from src.mcp_handlers.shared import lazy_mcp_server as mcp_server
from ..utils import (
    require_registered_agent,
    success_response,
    error_response,
)
from ..error_helpers import (
    agent_not_found_error,
    ownership_error,
)
from ..decorators import mcp_tool
from ..support.coerce import safe_float, resolve_agent_uuid
from src.logging_utils import get_logger
from config.governance_config import GovernanceConfig

from .helpers import _invalidate_agent_cache, _archive_one_agent, _is_test_agent

logger = get_logger(__name__)


# Map agent_id -> registered restartable task name in src/background_tasks.py.
# When the dashboard's unstick button is pressed for one of these agents, we
# don't just flip a status flag — we cancel the wedged asyncio Task and spawn
# a fresh one via its factory. Without this mapping, "unstick" was theater:
# meta.status = "active" + Postgres write, but the underlying hung await
# stayed hung. See dogfood finding 2026-04-14.
_SYSTEM_AGENT_RESTARTABLE_TASKS: Dict[str, str] = {
    "eisv-sync-task": "eisv_sync",
}


@mcp_tool("resume_agent", timeout=15.0, register=False)
async def handle_resume_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Resume a paused/stuck agent from the dashboard.

    Lightweight resume handler for human operators (dashboard).
    No ownership check -- mirrors archive_agent pattern.
    Only resumes agents in paused or waiting_input status.
    """
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    agent_uuid = resolve_agent_uuid(arguments, agent_id)

    # Reload metadata from PostgreSQL (async)
    await mcp_server.load_metadata_async(force=True)

    if agent_uuid not in mcp_server.agent_metadata:
        return agent_not_found_error(agent_id)

    meta = mcp_server.agent_metadata[agent_uuid]

    # Allow resuming paused/waiting_input agents AND "unsticking" active agents
    # Stuck agents are typically still "active" but caught in a timeout/loop
    is_stuck_unstick = meta.status == "active" and arguments.get("unstick", False)
    if meta.status not in ("paused", "waiting_input") and not is_stuck_unstick:
        return [error_response(
            f"Agent '{agent_id}' is '{meta.status}', not resumable (must be paused or waiting_input)",
            error_code="AGENT_NOT_RESUMABLE",
            error_category="validation_error",
            details={"error_type": "agent_not_resumable", "agent_id": agent_id, "status": meta.status},
            recovery={
                "action": "Agent must be in paused or waiting_input status to resume",
                "related_tools": ["get_agent_metadata", "list_agents"],
                "workflow": ["1. Check agent status with get_agent_metadata", "2. Only paused/waiting_input agents can be resumed"]
            }
        )]

    reason = arguments.get("reason", "Resumed from dashboard")
    previous_status = meta.status

    meta.status = "active"
    meta.paused_at = None
    # Clear loop detector state to prevent immediate re-pause
    from .self_recovery import clear_loop_detector_state
    clear_loop_detector_state(meta)
    meta.add_lifecycle_event("resumed" if not is_stuck_unstick else "unstuck", reason)

    # PostgreSQL: Update status and refresh last_update to clear stuck detection
    try:
        await agent_storage.update_agent(agent_uuid, status="active")
        # status update already sets updated_at = now() in DB, clearing stuck detection
        logger.debug(f"PostgreSQL: {'Unstuck' if is_stuck_unstick else 'Resumed'} agent {agent_id}")

        await _invalidate_agent_cache(agent_id)
    except Exception as e:
        logger.warning(f"PostgreSQL update_agent failed: {e}", exc_info=True)

    # For system-task agents (eisv-sync-task, etc), the flag flip above is not
    # sufficient — those agents map to background asyncio Tasks that may be
    # stuck in a hung await. The flag flip alone leaves the wedged task in
    # place. Cancel-and-respawn the registered restartable task so the unstick
    # button actually unsticks. Best-effort: failure here logs but does not
    # fail the resume (the flag flip already succeeded).
    task_restart_info = None
    restartable_name = _SYSTEM_AGENT_RESTARTABLE_TASKS.get(agent_id)
    if is_stuck_unstick and restartable_name is not None:
        try:
            from src.background_tasks import cancel_and_respawn_task
            task_restart_info = cancel_and_respawn_task(restartable_name)
            logger.info(
                f"Unstick {agent_id}: task '{restartable_name}' restart "
                f"result={task_restart_info}"
            )
        except Exception as e:
            logger.warning(
                f"Unstick {agent_id}: cancel_and_respawn_task('{restartable_name}') "
                f"failed: {e}", exc_info=True
            )
            task_restart_info = {
                "restarted": False,
                "previous_state": "unknown",
                "reason": f"exception during cancel_and_respawn: {e}",
            }

    response_payload = {
        "success": True,
        "message": f"Agent '{agent_id}' resumed successfully",
        "agent_id": agent_id,
        "lifecycle_status": "active",
        "previous_status": previous_status,
        "reason": reason,
        "resumed_at": datetime.now(timezone.utc).isoformat()
    }
    if task_restart_info is not None:
        response_payload["task_restart"] = task_restart_info
    return success_response(response_payload)

@mcp_tool("mark_response_complete", timeout=5.0, register=False)
async def handle_mark_response_complete(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Mark agent as having completed response, waiting for input"""
    # SECURITY FIX: Require registered agent (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    # Use authoritative UUID for internal lookups
    agent_uuid = resolve_agent_uuid(arguments, agent_id)

    # SECURITY: Verify ownership via session binding (UUID-based auth, Dec 2025)
    from ..utils import verify_agent_ownership
    if not verify_agent_ownership(agent_uuid, arguments):
        from ..identity.shared import get_bound_agent_id
        caller_id = get_bound_agent_id(arguments) or "unknown"
        return ownership_error(
            resource_type="agent_response",
            resource_id=agent_uuid,
            owner_agent_id=agent_uuid,
            caller_agent_id=caller_id,
        )

    meta = mcp_server.agent_metadata.get(agent_uuid)

    # Get existing metadata (already verified to exist above)

    # Update status to waiting_input
    meta.status = "waiting_input"
    meta.last_response_at = datetime.now(timezone.utc).isoformat()
    meta.response_completed = True

    # Add lifecycle event
    summary = arguments.get("summary", "")
    meta.add_lifecycle_event("response_completed", summary if summary else "Response completed, waiting for input")

    # PostgreSQL: Update status (single source of truth)
    try:
        await agent_storage.update_agent(agent_uuid, status="waiting_input")
    except Exception as e:
        logger.debug(f"PostgreSQL status update failed: {e}")

    # MAINTENANCE PROMPT: Surface open discoveries from this session
    # Behavioral nudge: Remind agent to resolve discoveries before ending session
    open_discoveries = []
    try:
        from src.knowledge_graph import get_knowledge_graph
        # Note: datetime and timedelta already imported at module level

        graph = await get_knowledge_graph()

        # Get open discoveries from this agent (recent - last 24 hours)
        now = datetime.now()
        one_day_ago = (now - timedelta(hours=24)).isoformat()

        all_agent_discoveries = await graph.query(
            agent_id=agent_id,
            status="open",
            limit=20  # Get recent discoveries
        )

        # Filter to recent discoveries (last 24 hours)
        recent_open = [
            d for d in all_agent_discoveries
            if d.timestamp >= one_day_ago
        ]

        # Prioritize bug_found and high severity
        recent_open.sort(key=lambda d: (
            0 if d.type == "bug_found" else 1,  # Bugs first
            0 if d.severity == "high" else 1 if d.severity == "medium" else 2,  # High severity first
            d.timestamp  # Then by recency
        ))

        open_discoveries = recent_open[:5]  # Top 5 for prompt

    except Exception as e:
        # Don't fail if knowledge graph check fails - this is a nice-to-have prompt
        logger.warning(f"Could not check open discoveries: {e}")

    response_data = {
        "success": True,
        "message": "Response completion marked",
        "agent_id": agent_id,
        "status": "waiting_input",
        "last_response_at": meta.last_response_at,
        "response_completed": True
    }

    # Add maintenance prompt if there are open discoveries
    if open_discoveries:
        response_data["maintenance_prompt"] = {
            "message": f"You have {len(open_discoveries)} open discovery/discoveries from this session. Consider resolving them:",
            "open_discoveries": [
                {
                    "id": d.id,
                    "summary": d.summary,
                    "type": d.type,
                    "severity": d.severity,
                    "timestamp": d.timestamp
                }
                for d in open_discoveries
            ],
            "suggested_actions": [
                "Mark as resolved: update_discovery_status_graph(discovery_id='...', status='resolved')",
                "Add correction: store_knowledge_graph(response_to={discovery_id='...', response_type='correction'}, ...)",
                "Archive if obsolete: update_discovery_status_graph(discovery_id='...', status='archived')"
            ],
            "related_tools": [
                "update_discovery_status_graph",
                "store_knowledge_graph",
                "search_knowledge_graph"
            ],
            "tip": "Resolving discoveries helps maintain knowledge graph quality. Use response_to for corrections or additions."
        }

    return success_response(response_data)

@mcp_tool("self_recovery_review", timeout=15.0, register=False)  # Use self_recovery(action="review") instead
async def handle_self_recovery_review(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Self-reflection recovery - lightweight alternative to dialectic.

    Agent reflects on what went wrong and proposes recovery conditions.
    System validates safety and resumes if safe, or provides guidance if not.

    This replaces the heavyweight thesis->antithesis->synthesis dialectic
    with a simpler: reflect -> validate -> resume flow.

    Required:
        reflection: str - What went wrong and what you learned (minimum 20 characters)

    Optional:
        proposed_conditions: list[str] - Conditions for resuming (e.g., "reduce complexity", "take breaks")
        root_cause: str - Agent's understanding of root cause
    """

    # 1. Require registered agent
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    agent_uuid = resolve_agent_uuid(arguments, agent_id)

    # 2. Verify ownership (can only recover yourself)
    from ..utils import verify_agent_ownership
    if not verify_agent_ownership(agent_uuid, arguments):
        from ..identity.shared import get_bound_agent_id
        caller_id = get_bound_agent_id(arguments) or "unknown"
        return ownership_error(
            resource_type="agent_recovery",
            resource_id=agent_uuid,
            owner_agent_id=agent_uuid,
            caller_agent_id=caller_id,
        )

    # 3. Get reflection (required)
    reflection = arguments.get("reflection", "").strip()
    if not reflection or len(reflection) < 20:
        return [error_response(
            "Reflection required. Please describe what happened and what you learned. "
            "Minimum 20 characters - genuine reflection helps recovery.",
            error_code="REFLECTION_REQUIRED",
            recovery={
                "action": "Provide a meaningful reflection on what went wrong",
                "example": "self_recovery(action='review', reflection='I got stuck in a loop trying to optimize the same function repeatedly. I should have stepped back and considered alternative approaches.')"
            }
        )]

    # 4. Get current metrics
    meta = mcp_server.agent_metadata.get(agent_uuid)
    if not meta:
        return agent_not_found_error(agent_id)

    # Mark recovery attempt before safety checks so loop detector grants a 120s
    # grace period even if this review attempt fails (agent not yet safe to resume).
    from datetime import timezone as _tz
    meta.recovery_attempt_at = datetime.now(_tz.utc).isoformat()

    monitor = mcp_server.get_or_create_monitor(agent_uuid)
    metrics = monitor.get_metrics()

    coherence = safe_float(monitor.state.coherence, 0.5)
    risk_score = safe_float(metrics.get("mean_risk"), 0.5)
    void_active = bool(monitor.state.void_active)
    void_value = safe_float(monitor.state.V, 0.0)
    status = meta.status

    # 5. Compute margin for context
    margin_info = GovernanceConfig.compute_proprioceptive_margin(
        risk_score=risk_score,
        coherence=coherence,
        void_active=void_active,
        void_value=void_value,
        coherence_history=monitor.state.coherence_history,
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
    reflection_logged = False
    try:
        from ..knowledge.handlers import store_discovery_internal
        await store_discovery_internal(
            agent_id=agent_uuid,
            summary=f"Self-recovery reflection: {reflection[:100]}{'...' if len(reflection) > 100 else ''}",
            discovery_type="recovery_reflection",
            details=f"Reflection: {reflection}\n\nRoot cause: {root_cause}\n\nProposed conditions: {proposed_conditions}\n\nMetrics at reflection: coherence={coherence:.3f}, risk={risk_score:.3f}, void={void_value:.3f}",
            tags=["recovery", "self-reflection", margin_info.get('margin', 'unknown')],
            severity="info" if all_safe else "warning"
        )
        reflection_logged = True
    except Exception as e:
        logger.warning(f"Failed to log recovery reflection: {e}")

    # 9. Resume if safe, or provide guidance
    if all_safe:
        # Resume agent
        from .self_recovery import clear_loop_detector_state
        meta.status = "active"
        meta.paused_at = None
        clear_loop_detector_state(meta)
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
            "reflection_logged": reflection_logged,
            "conditions": proposed_conditions,
            "metrics": {
                "coherence": coherence,
                "risk_score": risk_score,
                "margin": margin_info.get('margin', 'unknown')
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
            "message": "Reflection logged, but not yet safe to resume." if reflection_logged else "Not yet safe to resume (reflection failed to log).",
            "reflection_logged": reflection_logged,
            "failed_checks": failed,
            "metrics": {
                "coherence": coherence,
                "risk_score": risk_score,
                "void_active": void_active,
                "margin": margin_info.get('margin', 'unknown')
            },
            "guidance": guidance,
            "next_steps": [
                "Review the guidance above",
                "Add to your reflection if you have new insights",
                "Try again with self_recovery(action='review') when ready",
                "Or wait for metrics to improve naturally"
            ]
        })

@mcp_tool("ping_agent", timeout=5.0, rate_limit_exempt=True, register=False)
async def handle_ping_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Ping an agent to check if it's responsive/alive.

    Checks if agent can respond by attempting to get its metrics.
    Useful for distinguishing between:
    - Agent is stuck but responsive (can call tools)
    - Agent is dead/unresponsive (can't call tools)

    Args:
        agent_id: Agent ID to ping (optional - defaults to calling agent)

    Returns:
        {
            "agent_id": "...",
            "responsive": true/false,
            "last_update": "...",
            "age_minutes": float,
            "status": "alive" | "stuck" | "unresponsive"
        }
    """
    try:
        # Reload metadata
        await mcp_server.load_metadata_async()

        # Get agent_id (default to calling agent)
        agent_id = arguments.get("agent_id")
        if not agent_id:
            # Use bound agent_id
            from ..utils import get_bound_agent_id
            agent_id = get_bound_agent_id(arguments)

        if not agent_id:
            return [error_response("agent_id required or must be bound to session")]

        # Check if agent exists
        meta = mcp_server.agent_metadata.get(agent_id)
        if not meta:
            return [error_response(f"Agent {agent_id} not found")]

        # Try to get agent's metrics (this is the "ping")
        responsive = False
        try:
            monitor = mcp_server.get_or_create_monitor(agent_id)
            metrics = monitor.get_metrics()
            responsive = True  # If we can get metrics, agent is responsive
        except Exception as e:
            logger.debug(f"Could not ping agent {agent_id}: {e}")
            responsive = False

        # Calculate age
        try:
            last_update_str = meta.last_update or meta.created_at
            if isinstance(last_update_str, str):
                last_update_dt = datetime.fromisoformat(
                    last_update_str.replace('Z', '+00:00') if 'Z' in last_update_str else last_update_str
                )
                if last_update_dt.tzinfo is None:
                    last_update_dt = last_update_dt.replace(tzinfo=timezone.utc)
            else:
                last_update_dt = last_update_str

            age_delta = datetime.now(timezone.utc) - last_update_dt
            age_minutes = age_delta.total_seconds() / 60
        except (ValueError, TypeError, AttributeError):
            age_minutes = None

        # Determine status
        if responsive:
            if age_minutes and age_minutes > 30:
                status = "stuck"  # Responsive but inactive
            else:
                status = "alive"  # Responsive and active
        else:
            status = "unresponsive"  # Can't get metrics

        return success_response({
            "agent_id": agent_id,
            "responsive": responsive,
            "last_update": meta.last_update or meta.created_at,
            "age_minutes": round(age_minutes, 1) if age_minutes else None,
            "status": status,
            "lifecycle_status": meta.status
        })

    except Exception as e:
        logger.error(f"Error pinging agent: {e}", exc_info=True)
        return [error_response(f"Error pinging agent: {str(e)}")]

@mcp_tool("archive_old_test_agents", timeout=20.0, rate_limit_exempt=True, register=False)
async def handle_archive_old_test_agents(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Archive stale agents - test agents by default, or ALL stale agents with include_all=true

    Use include_all=true to clean up any agent inactive for max_age_days (default: 3 days)
    """
    max_age_hours = arguments.get("max_age_hours", 6)  # Default: 6 hours for test agents
    max_age_days = arguments.get("max_age_days")  # Backward compatibility: convert days to hours
    include_all = arguments.get("include_all", False)  # NEW: archive ALL stale agents, not just test
    dry_run = arguments.get("dry_run", False)  # NEW: preview without archiving

    # If include_all, use longer default (3 days)
    if include_all and max_age_days is None and "max_age_hours" not in arguments:
        max_age_days = 3

    # Convert days to hours if provided (backward compatibility)
    if max_age_days is not None:
        max_age_hours = max_age_days * 24

    if max_age_hours < 0.1:
        return [error_response("max_age_hours must be at least 0.1 (6 minutes)")]

    # Reload metadata from PostgreSQL (async)
    await mcp_server.load_metadata_async(force=True)

    archived_agents = []
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    for agent_id, meta in list(mcp_server.agent_metadata.items()):
        # Filter: only test/demo agents unless include_all.
        #
        # Check both agent_id (auto-generated structured ID) AND the display
        # label, because clients like tests/test_unitares_cli_script.py set
        # test names on the label (e.g. "cli-pytest-1776...") while agent_id
        # stays as the model-generated "Claude_20260414". Without the label
        # check those test stragglers leak through and Vigil never sweeps
        # them, producing the `cli-pytest-*` pile the operator flagged on
        # 2026-04-14.
        label = (getattr(meta, "label", None) or getattr(meta, "display_name", None) or "").lower()
        is_test_id = (
            agent_id.startswith("test_")
            or agent_id.startswith("demo_")
            or "test" in agent_id.lower()
        )
        is_test_label = (
            label.startswith("test_")
            or label.startswith("test-")
            or label.startswith("demo_")
            or label.startswith("demo-")
            or "pytest" in label
            or "test" in label
        )
        is_test = is_test_id or is_test_label
        if not include_all and not is_test:
            continue

        # Skip if already archived/deleted
        if meta.status in ["archived", "deleted"]:
            continue

        # Archive immediately if very low update count (1-2 updates = just a ping/test)
        if meta.total_updates <= 2 and is_test:
            if not dry_run:
                meta.status = "archived"
                meta.archived_at = datetime.now(timezone.utc).isoformat()
                meta.add_lifecycle_event("archived", f"Auto-archived: test/ping agent with {meta.total_updates} update(s)")
                # Unload from memory
                if agent_id in mcp_server.monitors:
                    del mcp_server.monitors[agent_id]
                # PostgreSQL: Archive agent
                try:
                    await agent_storage.archive_agent(agent_id)
                except Exception as e:
                    logger.debug(f"PostgreSQL archive failed for {agent_id}: {e}")
            archived_agents.append({"id": agent_id, "reason": "low_updates", "updates": meta.total_updates})
            continue

        # Check age for agents with more updates
        try:
            last_update_dt = datetime.fromisoformat(meta.last_update.replace('Z', '+00:00'))
            if last_update_dt.tzinfo is None:
                last_update_dt = last_update_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if last_update_dt < cutoff_time:
            age_hours = (datetime.now(timezone.utc) - last_update_dt).total_seconds() / 3600
            age_days = age_hours / 24
            if not dry_run:
                meta.status = "archived"
                meta.archived_at = datetime.now(timezone.utc).isoformat()
                meta.add_lifecycle_event("archived", f"Inactive for {age_hours:.1f} hours (threshold: {max_age_hours} hours)")
                # Unload from memory
                if agent_id in mcp_server.monitors:
                    del mcp_server.monitors[agent_id]
                # PostgreSQL: Archive agent
                try:
                    await agent_storage.archive_agent(agent_id)
                except Exception as e:
                    logger.debug(f"PostgreSQL archive failed for {agent_id}: {e}")
            archived_agents.append({"id": agent_id, "reason": "stale", "days_inactive": round(age_days, 1)})

    return success_response({
        "success": True,
        "dry_run": dry_run,
        "archived_count": len(archived_agents),
        "archived_agents": archived_agents[:20],  # Limit output
        "total_would_archive": len(archived_agents),
        "max_age_days": max_age_hours / 24,
        "include_all": include_all,
        "action": "preview - use dry_run=false to execute" if dry_run else "archived"
    })

@mcp_tool("archive_orphan_agents", timeout=30.0, rate_limit_exempt=True)
async def handle_archive_orphan_agents(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Aggressively archive orphan agents to prevent proliferation.

    Targets UUID-named agents without labels that have low/no updates.
    Much more aggressive than archive_old_test_agents.

    Parameters:
    - max_age_hours: Maximum inactivity before evaluation (default: 6h). Scales internal tiers.
    - max_updates: Skip agents with more updates than this (default: 3).

    Preserves:
    - Agents with labels/display names
    - Agents with "pioneer" tag
    - Recently active agents
    """
    import re
    UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

    max_age_hours = float(arguments.get("max_age_hours", 6))
    max_updates = int(arguments.get("max_updates", 3))
    dry_run = arguments.get("dry_run", True)

    # Derive tier thresholds from max_age_hours, capped to sensible minimums
    zero_update_hours = min(max(max_age_hours / 6, 0.5), max_age_hours)   # ~1h at default 6
    low_update_hours = min(max(max_age_hours / 2, 1.0), max_age_hours)    # ~3h at default 6
    unlabeled_hours = max_age_hours                                        # 6h at default 6

    # Reload metadata from PostgreSQL (async)
    await mcp_server.load_metadata_async(force=True)

    archived_agents = []
    current_time = datetime.now(timezone.utc)

    for agent_id, meta in list(mcp_server.agent_metadata.items()):
        # Skip if already archived or deleted
        if meta.status in ["archived", "deleted"]:
            continue

        # Never archive pioneers
        if "pioneer" in (meta.tags or []):
            continue

        # Check if agent has a meaningful label
        has_label = bool(getattr(meta, 'label', None) or getattr(meta, 'display_name', None))
        is_uuid_named = bool(UUID_PATTERN.match(agent_id))

        # Calculate age
        try:
            last_update_str = meta.last_update or meta.created_at
            last_update_dt = datetime.fromisoformat(
                last_update_str.replace('Z', '+00:00') if 'Z' in last_update_str else last_update_str
            )
            if last_update_dt.tzinfo is None:
                last_update_dt = last_update_dt.replace(tzinfo=timezone.utc)
            age_delta = current_time - last_update_dt
            age_hours = age_delta.total_seconds() / 3600
        except (ValueError, TypeError, AttributeError):
            continue

        updates = getattr(meta, 'total_updates', 0) or 0

        # Skip agents with more updates than max_updates threshold
        if updates > max_updates:
            continue

        should_archive = False
        reason = ""

        # Rule 1: UUID-named, 0 updates, older than zero_update_hours
        if is_uuid_named and updates == 0 and age_hours >= zero_update_hours:
            should_archive = True
            reason = f"orphan UUID, 0 updates, {age_hours:.1f}h"

        # Rule 2: Unlabeled, 0-1 updates, older than low_update_hours
        elif not has_label and updates <= 1 and age_hours >= low_update_hours:
            should_archive = True
            reason = f"unlabeled, {updates} updates, {age_hours:.1f}h"

        # Rule 3: UUID-named + unlabeled, low updates but old
        elif is_uuid_named and not has_label and updates >= 2 and age_hours >= unlabeled_hours:
            should_archive = True
            reason = f"stale UUID, {updates} updates, {age_hours:.1f}h"

        if should_archive:
            if not dry_run:
                meta.status = "archived"
                meta.archived_at = current_time.isoformat()
                meta.add_lifecycle_event("archived", f"Orphan cleanup: {reason}")
                # Unload from memory
                if agent_id in mcp_server.monitors:
                    del mcp_server.monitors[agent_id]
                # PostgreSQL: Archive agent
                try:
                    await agent_storage.archive_agent(agent_id)
                except Exception as e:
                    logger.debug(f"PostgreSQL archive failed for {agent_id}: {e}")
            archived_agents.append({
                "id": agent_id[:12] + "...",
                "reason": reason,
                "updates": updates,
                "label": getattr(meta, 'label', None)
            })

    return success_response({
        "success": True,
        "dry_run": dry_run,
        "archived_count": len(archived_agents),
        "archived_agents": archived_agents[:30],  # Limit output
        "total_would_archive": len(archived_agents),
        "thresholds": {
            "max_age_hours": max_age_hours,
            "max_updates": max_updates,
            "zero_update_hours": zero_update_hours,
            "low_update_hours": low_update_hours,
            "unlabeled_hours": unlabeled_hours
        },
        "action": "preview - set dry_run=false to execute" if dry_run else "archived"
    })
