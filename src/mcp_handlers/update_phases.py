"""
Update Phases — Extracted from handle_process_agent_update in core.py.

Phases 1-5 of the process_agent_update pipeline:
  1. resolve_identity_and_guards  — UUID, circuit breaker, lazy persist, label
  2. handle_onboarding_and_resume — KG guidance, auto-resume archived agents
  3. validate_inputs              — Param validation (fail-fast before lock)
  4. execute_locked_update        — Policy, agent creation, ODE update
  5. execute_post_update_effects  — Health, CIRS, PG record, outcomes
"""

import asyncio
import re
import secrets
from datetime import datetime
from typing import Optional, Sequence

from mcp.types import TextContent

from src.logging_utils import get_logger
from src import agent_storage

from .update_context import UpdateContext
from .utils import error_response
from .validators import (
    validate_complexity,
    validate_confidence,
    validate_ethical_drift,
    validate_response_text,
    validate_task_type,
)

logger = get_logger(__name__)


# ─── Phase 1: Identity Resolution & Guards ─────────────────────────────

async def resolve_identity_and_guards(ctx: UpdateContext) -> Optional[Sequence[TextContent]]:
    """Resolve UUID identity, check circuit breaker, lazy-persist, set label.

    Returns an early-exit error response, or None to continue.
    """
    mcp_server = ctx.mcp_server

    from .context import get_context_agent_id, get_context_session_key
    ctx.agent_uuid = get_context_agent_id()
    ctx.session_key = get_context_session_key()

    if not ctx.agent_uuid:
        logger.error("No agent_uuid in context - identity_v2 resolution failed at dispatch")
        return [error_response("Identity not resolved. Try calling identity() first.")]

    # Circuit breaker: paused / archived agents cannot update
    if ctx.agent_uuid in mcp_server.agent_metadata:
        meta = mcp_server.agent_metadata[ctx.agent_uuid]
        if meta.status == "paused":
            return [error_response(
                "Agent is paused and cannot process updates",
                error_code="AGENT_PAUSED",
                details={
                    "agent_id": ctx.agent_uuid[:12],
                    "paused_at": meta.paused_at,
                    "status": "paused",
                },
                recovery={
                    "action": "Use self_recovery(action='quick') for safe states, or self_recovery(action='review', reflection='...') for full recovery",
                    "note": "Circuit breaker triggered due to governance threshold violation",
                    "auto_recovery": "Dialectic recovery may already be in progress",
                }
            )]
        elif meta.status == "archived":
            return [error_response(
                "Agent is archived and cannot process updates",
                error_code="AGENT_ARCHIVED",
                details={"agent_id": ctx.agent_uuid[:12], "status": "archived"},
                recovery={
                    "action": "Use self_recovery(action='quick') to restore yourself, or onboard(force_new=true) for a new identity",
                    "related_tools": ["self_recovery", "onboard"],
                }
            )]

    # Lazy creation: persist agent in PostgreSQL on first real work
    from .identity_v2 import ensure_agent_persisted
    if ctx.session_key:
        newly_persisted = await ensure_agent_persisted(ctx.agent_uuid, ctx.session_key)
        if newly_persisted:
            logger.info(f"Lazy-persisted agent {ctx.agent_uuid[:8]}... on first process_agent_update")

    ctx.is_new_agent = ctx.agent_uuid not in mcp_server.agent_metadata

    # Label from arguments or existing metadata
    ctx.label = ctx.arguments.get("agent_id") or ctx.arguments.get("id") or ctx.arguments.get("name")
    if not ctx.label and ctx.agent_uuid in mcp_server.agent_metadata:
        meta = mcp_server.agent_metadata[ctx.agent_uuid]
        ctx.label = getattr(meta, 'label', None)

    # Set up identity aliases
    ctx.agent_id = ctx.agent_uuid
    ctx.declared_agent_id = ctx.label or ctx.agent_uuid
    ctx.arguments["agent_id"] = ctx.declared_agent_id
    ctx.arguments["_agent_uuid"] = ctx.agent_uuid
    ctx.arguments["_agent_label"] = ctx.declared_agent_id

    # Store label in PostgreSQL
    if ctx.label and ctx.label != ctx.agent_uuid:
        try:
            from src.db import get_db
            db = get_db()
            await db.update_agent_fields(ctx.agent_uuid, label=ctx.label)
            logger.debug(f"PostgreSQL: Set label '{ctx.label}' for agent {ctx.agent_uuid[:8]}...")
        except Exception as e:
            logger.debug(f"Could not set label in PostgreSQL: {e}")
        if ctx.agent_uuid in mcp_server.agent_metadata:
            meta = mcp_server.agent_metadata[ctx.agent_uuid]
            meta.label = ctx.label

    ctx.loop = asyncio.get_running_loop()
    ctx.key_was_generated = False
    ctx.api_key_auto_retrieved = False
    ctx.dialectic_enforcement_warning = None

    return None  # Continue to next phase


# ─── Phase 2: Onboarding & Auto-Resume ─────────────────────────────────

async def handle_onboarding_and_resume(ctx: UpdateContext) -> Optional[Sequence[TextContent]]:
    """Surface KG guidance for new agents; auto-resume archived agents.

    Returns an early-exit error response, or None to continue.
    """
    mcp_server = ctx.mcp_server
    agent_id = ctx.agent_id

    # Onboarding guidance for new agents
    if ctx.is_new_agent:
        try:
            from src.knowledge_graph import get_knowledge_graph
            graph = await get_knowledge_graph()
            stats = await graph.get_stats()

            # Surface open questions
            open_questions = []
            try:
                questions = await graph.query(type="question", status="open", limit=3)
                questions.sort(key=lambda q: q.timestamp, reverse=True)
                for q in questions[:2]:
                    q_dict = q.to_dict(include_details=False)
                    simplified = {
                        "id": q_dict["id"],
                        "summary": q_dict["summary"][:200] if len(q_dict.get("summary", "")) > 200 else q_dict.get("summary", ""),
                        "tags": q_dict.get("tags", [])[:3] if q_dict.get("tags") else [],
                        "severity": q_dict.get("severity")
                    }
                    open_questions.append(simplified)
                logger.debug(f"Found {len(open_questions)} open questions for onboarding")
            except Exception as e:
                logger.warning(f"Could not fetch open questions for onboarding: {e}", exc_info=True)
                open_questions = []

            if stats.get("total_discoveries", 0) > 0:
                question_count = stats.get("by_type", {}).get("question", 0)
                ctx.onboarding_guidance = {
                    "message": f"Welcome! The knowledge graph contains {stats['total_discoveries']} discoveries from {stats['total_agents']} agents.",
                    "suggestion": "Use search_knowledge_graph to find relevant discoveries by tags or type.",
                    "example_tags": list(stats.get("by_type", {}).keys())[:5] if stats.get("by_type") else []
                }

                # Naming suggestions
                try:
                    from .naming_helpers import (
                        detect_interface_context,
                        generate_name_suggestions,
                        format_naming_guidance
                    )
                    existing_names = [
                        getattr(m, 'label', None)
                        for m in mcp_server.agent_metadata.values()
                        if getattr(m, 'label', None)
                    ]
                    context = detect_interface_context()
                    purpose_hint = None
                    response_text = ctx.arguments.get("response_text", "")
                    if response_text:
                        purpose_keywords = ["debug", "fix", "implement", "test", "explore", "analyze", "refactor", "review"]
                        response_lower = response_text.lower()
                        for keyword in purpose_keywords:
                            if keyword in response_lower:
                                purpose_hint = keyword
                                break
                    suggestions = generate_name_suggestions(
                        context=context,
                        purpose=purpose_hint,
                        existing_names=existing_names
                    )
                    ctx.onboarding_guidance["naming"] = {
                        "message": "Name yourself to make your work easier to find",
                        "action": "Call identity(name='your_chosen_name') to set your name",
                        "suggestions": suggestions[:3],
                        "quick_example": suggestions[0]["name"] if suggestions else None
                    }
                except Exception as e:
                    logger.debug(f"Could not generate naming suggestions for onboarding: {e}")

                if open_questions:
                    ctx.onboarding_guidance["open_questions"] = {
                        "message": f"Found {len(open_questions)} open question(s) waiting for answers. Want to try responding to one?",
                        "questions": open_questions,
                        "invitation": "Use reply_to_question tool to answer any of these questions and help build shared knowledge.",
                        "tool": "reply_to_question"
                    }
                elif question_count > 0:
                    ctx.onboarding_guidance["open_questions"] = {
                        "message": f"There are {question_count} open question(s) in the knowledge graph.",
                        "suggestion": "Use search_knowledge_graph with discovery_type='question' and status='open' to find them.",
                        "tool": "reply_to_question"
                    }
        except Exception as e:
            logger.warning(f"Could not check knowledge graph for onboarding: {e}")

    # Auto-resume check
    meta = mcp_server.agent_metadata.get(ctx.agent_uuid)
    ctx.meta = meta

    if meta:
        if meta.status == "archived":
            previous_archived_at = meta.archived_at
            days_since_archive = None
            if previous_archived_at:
                try:
                    archived_dt = datetime.fromisoformat(
                        previous_archived_at.replace('Z', '+00:00') if 'Z' in previous_archived_at else previous_archived_at
                    )
                    days_since_archive = (
                        (datetime.now(archived_dt.tzinfo) - archived_dt).total_seconds() / 86400
                        if archived_dt.tzinfo
                        else (datetime.now() - archived_dt.replace(tzinfo=None)).total_seconds() / 86400
                    )
                except (ValueError, TypeError, AttributeError):
                    pass

            agent_notes = getattr(meta, 'notes', '') or ''
            explicitly_archived = bool(agent_notes and "user requested" in agent_notes.lower())
            too_old = days_since_archive is not None and days_since_archive > 2.0
            too_few_updates = (getattr(meta, 'total_updates', 0) or 0) < 2

            if explicitly_archived or (too_old and too_few_updates):
                reasons = []
                if explicitly_archived:
                    reasons.append(f"explicitly archived: {agent_notes}")
                if too_old:
                    reasons.append(f"archived {days_since_archive:.1f} days ago")
                if too_few_updates:
                    reasons.append(f"only {getattr(meta, 'total_updates', 0) or 0} update(s)")
                logger.warning(
                    f"Blocked auto-resume of agent {agent_id[:12]}... ({', '.join(reasons)}). "
                    f"Use self_recovery(action='quick') to restore, or onboard(force_new=true) for new identity."
                )
                return [error_response(
                    f"Agent '{agent_id}' is archived and cannot be auto-resumed ({', '.join(reasons)}).",
                    recovery={
                        "action": "Use self_recovery(action='quick') to restore yourself, or onboard(force_new=true) for a new identity",
                        "related_tools": ["self_recovery", "onboard"],
                    },
                    context={
                        "agent_id": agent_id,
                        "status": "archived",
                        "days_since_archive": round(days_since_archive, 2) if days_since_archive is not None else None,
                        "total_updates": getattr(meta, 'total_updates', 0) or 0,
                    }
                )]

            meta.status = "active"
            meta.archived_at = None
            meta.add_lifecycle_event("resumed", "Auto-resumed on engagement")

            try:
                await agent_storage.update_agent(agent_id, status="active")
                logger.debug(f"PostgreSQL: Auto-resumed agent {agent_id}")
            except Exception as e:
                logger.warning(f"PostgreSQL auto-resume failed: {e}", exc_info=True)

            try:
                from src.cache import get_metadata_cache
                await get_metadata_cache().invalidate(ctx.agent_uuid)
            except Exception:
                pass

            try:
                from src.audit_log import audit_logger
                audit_logger.log_auto_resume(
                    agent_id=agent_id,
                    previous_status="archived",
                    trigger="process_agent_update",
                    archived_at=previous_archived_at,
                    details={
                        "days_since_archive": round(days_since_archive, 2) if days_since_archive is not None else None,
                        "total_updates": meta.total_updates
                    }
                )
            except Exception as e:
                logger.warning(f"Could not log auto-resume audit event: {e}", exc_info=True)

            ctx.auto_resume_info = {
                "auto_resumed": True,
                "message": f"Agent '{agent_id}' was automatically resumed from archived status.",
                "previous_status": "archived",
                "days_since_archive": round(days_since_archive, 2) if days_since_archive is not None else None,
                "note": "Archived agents automatically resume when they engage with the system."
            }

        elif meta.status == "paused":
            return [error_response(
                f"Agent '{agent_id}' is paused. Resume it first before processing updates.",
                recovery={
                    "action": "Check your state and resume when ready",
                    "related_tools": ["get_governance_metrics", "self_recovery"],
                    "workflow": (
                        "1. Check your state with get_governance_metrics "
                        "2. Reflect on what triggered the pause "
                        "3. Use self_recovery(action='quick') if safe (coherence > 0.60, risk < 0.40), otherwise use self_recovery(action='review', reflection='...')"
                    )
                },
                context={
                    "agent_id": agent_id,
                    "status": "paused",
                    "reason": "Circuit breaker triggered - governance threshold exceeded",
                    "note": "Paused agents require explicit recovery. Archived agents auto-resume on engagement."
                }
            )]

        elif meta.status == "deleted":
            return [error_response(
                f"Agent '{agent_id}' is deleted and cannot be used.",
                recovery={
                    "action": "Cannot recover deleted agents",
                    "related_tools": ["list_agents"],
                    "workflow": "Deleted agents are permanently removed. Use list_agents to see available agents."
                },
                context={
                    "agent_id": agent_id,
                    "status": "deleted",
                    "note": "Deleted agents cannot be recovered. Use archive_agent instead of delete_agent to preserve agent state."
                }
            )]

    return None  # Continue


# ─── Phase 3: Validate Inputs ──────────────────────────────────────────

def validate_inputs(ctx: UpdateContext) -> Optional[Sequence[TextContent]]:
    """Validate all parameters BEFORE acquiring lock (fail fast).

    Returns an early-exit error response, or None to continue.
    """
    # Validate response_text
    response_text_raw = ctx.arguments.get("response_text", "")
    response_text, error = validate_response_text(response_text_raw, max_length=50000)
    if error:
        return [error]
    ctx.response_text = response_text

    # Validate complexity
    reported_complexity = ctx.arguments.get("complexity", 0.5)
    complexity, error = validate_complexity(reported_complexity)
    if error:
        return [error]
    ctx.complexity = complexity or 0.5

    # Validate confidence
    reported_confidence = ctx.arguments.get("confidence")
    ctx.confidence = None
    ctx.calibration_correction_info = None
    if reported_confidence is not None:
        confidence, error = validate_confidence(reported_confidence)
        if error:
            return [error]
        # Auto-calibration correction
        try:
            from src.calibration import calibration_checker
            corrected, correction_info = calibration_checker.apply_confidence_correction(confidence)
            if correction_info:
                ctx.calibration_correction_info = correction_info
                logger.info(f"Agent {ctx.agent_id}: {correction_info}")
            confidence = corrected
        except Exception as e:
            logger.debug(f"Calibration correction skipped: {e}")
        ctx.confidence = confidence

    # Validate ethical_drift
    ethical_drift_raw = ctx.arguments.get("ethical_drift", [0.0, 0.0, 0.0])
    ethical_drift, error = validate_ethical_drift(ethical_drift_raw)
    if error:
        return [error]
    ctx.ethical_drift = ethical_drift or [0.0, 0.0, 0.0]

    # Validate task_type
    task_type = ctx.arguments.get("task_type", "mixed")
    validated_task_type, error = validate_task_type(task_type)
    if error:
        logger.warning(f"Invalid task_type '{task_type}' for agent '{ctx.agent_id}', defaulting to 'mixed'")
        ctx.task_type = "mixed"
    else:
        ctx.task_type = validated_task_type

    return None  # Continue


# ─── Phase 4: Locked Update ────────────────────────────────────────────

async def execute_locked_update(ctx: UpdateContext) -> Optional[Sequence[TextContent]]:
    """Prepare agent state, run policy checks, ensure agent exists, call ODE update.

    Must be called inside the agent lock context manager.
    Returns an early-exit error response, or None to continue.
    """
    mcp_server = ctx.mcp_server
    import numpy as np

    ctx.agent_state = {
        "parameters": np.array(ctx.arguments.get("parameters", [])),
        "ethical_drift": np.array(ctx.ethical_drift),
        "response_text": ctx.response_text,
        "complexity": ctx.complexity
    }

    # Policy checks
    from .validators import (
        validate_file_path_policy,
        validate_agent_id_policy,
        detect_script_creation_avoidance
    )

    ctx.policy_warnings = []
    response_text = ctx.agent_state["response_text"]

    if ctx.dialectic_enforcement_warning:
        ctx.policy_warnings.append(ctx.dialectic_enforcement_warning)

    agent_id_warning, _ = validate_agent_id_policy(ctx.agent_id)
    if agent_id_warning:
        ctx.policy_warnings.append(agent_id_warning)

    avoidance_warnings = detect_script_creation_avoidance(response_text)
    if avoidance_warnings:
        ctx.policy_warnings.extend(avoidance_warnings)

    file_patterns = re.findall(r'(?:test_|demo_)\w+\.py', response_text)
    for file_pattern in file_patterns:
        warning, _ = validate_file_path_policy(file_pattern)
        if warning:
            ctx.policy_warnings.append(warning)

    if re.search(r'(?:creat|writ|generat)(?:e|ing|ed).*(?:test_|demo_)\w+\.py', response_text, re.IGNORECASE):
        if not re.search(r'tests?/', response_text, re.IGNORECASE):
            ctx.policy_warnings.append(
                "POLICY REMINDER: Creating test scripts? They belong in tests/ directory.\n"
                "See AI_ASSISTANT_GUIDE.md for details."
            )

    # Ensure agent exists
    if ctx.is_new_agent:
        purpose = ctx.arguments.get("purpose")
        purpose_str = purpose.strip() if purpose and isinstance(purpose, str) else None
        ctx.api_key = secrets.token_urlsafe(32)

        try:
            agent_record, _ = await agent_storage.get_or_create_agent(
                agent_id=ctx.agent_id,
                api_key=ctx.api_key,
                status='active',
                purpose=purpose_str,
            )
            logger.debug(f"PostgreSQL: Created agent {ctx.agent_id}")
            await ctx.loop.run_in_executor(
                None,
                lambda: mcp_server.get_or_create_metadata(ctx.agent_id, purpose=purpose_str)
            )
            ctx.meta = mcp_server.agent_metadata.get(ctx.agent_id)
            if ctx.meta:
                ctx.meta.api_key = ctx.api_key
        except Exception as e:
            logger.warning(f"PostgreSQL create agent failed: {e}", exc_info=True)
            ctx.meta = await ctx.loop.run_in_executor(
                None,
                lambda: mcp_server.get_or_create_metadata(ctx.agent_id, purpose=purpose_str)
            )
            ctx.api_key = ctx.meta.api_key if ctx.meta else None
    else:
        try:
            agent_record = await agent_storage.get_agent(ctx.agent_id)
            if agent_record:
                ctx.api_key = agent_record.api_key if agent_record.api_key else None
                if ctx.agent_id not in mcp_server.agent_metadata:
                    await ctx.loop.run_in_executor(None, mcp_server.get_or_create_metadata, ctx.agent_id)
                ctx.meta = mcp_server.agent_metadata.get(ctx.agent_id)
                if ctx.meta and ctx.api_key:
                    ctx.meta.api_key = ctx.api_key
            else:
                ctx.meta = mcp_server.agent_metadata.get(ctx.agent_id)
                ctx.api_key = ctx.meta.api_key if ctx.meta else None
        except Exception:
            ctx.meta = mcp_server.agent_metadata.get(ctx.agent_id)
            ctx.api_key = ctx.meta.api_key if ctx.meta else None

    # Capture previous void state for CIRS
    ctx.previous_void_active = False
    try:
        monitor = mcp_server.monitors.get(ctx.agent_id)
        if monitor and hasattr(monitor.state, 'void_active'):
            ctx.previous_void_active = bool(monitor.state.void_active)
    except Exception:
        pass

    # Execute ODE update
    ctx.agent_state["task_type"] = ctx.task_type

    try:
        ctx.result = await mcp_server.process_update_authenticated_async(
            agent_id=ctx.agent_id,
            api_key=ctx.api_key,
            agent_state=ctx.agent_state,
            auto_save=True,
            confidence=ctx.confidence,
            session_bound=True
        )
    except PermissionError:
        raise
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in process_update_authenticated_async: {e}", exc_info=True)
        raise Exception(f"Error processing update: {str(e)}") from e

    return None  # Continue


# ─── Phase 5: Post-Update Side Effects ─────────────────────────────────

async def execute_post_update_effects(ctx: UpdateContext) -> None:
    """Health check, CIRS emissions, PG record, outcome events. All fail-safe."""
    mcp_server = ctx.mcp_server
    agent_id = ctx.agent_id

    # Heartbeat
    await ctx.loop.run_in_executor(None, mcp_server.process_mgr.write_heartbeat)

    # Health status
    ctx.metrics_dict = ctx.result.get('metrics', {})
    ctx.risk_score = ctx.metrics_dict.get('risk_score', None)
    ctx.coherence = ctx.metrics_dict.get('coherence', None)
    void_active = ctx.metrics_dict.get('void_active', False)

    ctx.health_status, ctx.health_message = mcp_server.health_checker.get_health_status(
        risk_score=ctx.risk_score,
        coherence=ctx.coherence,
        void_active=void_active
    )

    if 'metrics' not in ctx.result:
        ctx.result['metrics'] = {}
    ctx.result['metrics']['health_status'] = ctx.health_status.value
    ctx.result['metrics']['health_message'] = ctx.health_message

    if ctx.meta:
        ctx.meta.health_status = ctx.health_status.value

    # CIRS: Void alert
    ctx.cirs_alert = None
    try:
        from .cirs_protocol import maybe_emit_void_alert
        V_value = ctx.metrics_dict.get('V', 0.0)
        ctx.cirs_alert = maybe_emit_void_alert(
            agent_id=agent_id,
            V=V_value,
            void_active=void_active,
            coherence=ctx.coherence or 0.5,
            risk_score=ctx.risk_score or 0.0,
            previous_void_active=ctx.previous_void_active
        )
    except Exception as e:
        logger.debug(f"CIRS void_alert auto-emit skipped: {e}")

    # CIRS: State announce
    ctx.cirs_state_announce = None
    try:
        from .cirs_protocol import auto_emit_state_announce
        monitor = mcp_server.monitors.get(agent_id)
        ctx.cirs_state_announce = auto_emit_state_announce(
            agent_id=agent_id,
            metrics=ctx.metrics_dict,
            monitor_state=monitor.state
        )
    except Exception as e:
        logger.debug(f"CIRS state_announce auto-emit skipped: {e}")

    # CIRS: Resonance signal
    try:
        from .cirs_protocol import maybe_emit_resonance_signal
        cirs_data = ctx.result.get('cirs', {})
        monitor = mcp_server.monitors.get(agent_id)
        was_resonant = False
        if monitor and hasattr(monitor, 'adaptive_governor') and monitor.adaptive_governor:
            was_resonant = monitor.adaptive_governor.state.was_resonant
        maybe_emit_resonance_signal(
            agent_id=agent_id,
            cirs_result=cirs_data,
            was_resonant=was_resonant,
        )
    except Exception as e:
        logger.debug(f"CIRS resonance auto-emit skipped: {e}")

    # CIRS: Neighbor pressure
    try:
        from .cirs_protocol import maybe_apply_neighbor_pressure
        monitor = mcp_server.monitors.get(agent_id)
        if monitor and hasattr(monitor, 'adaptive_governor'):
            maybe_apply_neighbor_pressure(
                agent_id=agent_id,
                governor=monitor.adaptive_governor,
            )
    except Exception as e:
        logger.debug(f"CIRS neighbor pressure skipped: {e}")

    # PostgreSQL: Record EISV state
    try:
        await agent_storage.record_agent_state(
            agent_id=agent_id,
            E=ctx.metrics_dict.get('E', 0.7),
            I=ctx.metrics_dict.get('I', 0.8),
            S=ctx.metrics_dict.get('S', 0.1),
            V=ctx.metrics_dict.get('V', 0.0),
            regime=ctx.metrics_dict.get('regime', 'EXPLORATION'),
            coherence=ctx.metrics_dict.get('coherence', 0.5),
            health_status=ctx.health_status.value,
            risk_score=ctx.risk_score,
            phi=ctx.metrics_dict.get('phi', 0.0),
            verdict=ctx.metrics_dict.get('verdict', 'continue'),
        )
        logger.debug(f"PostgreSQL: Recorded state for {agent_id}")
    except ValueError:
        logger.debug(f"Agent {agent_id} not found, creating...")
        try:
            await agent_storage.create_agent(
                agent_id=agent_id,
                api_key=ctx.api_key or "",
                status='active',
            )
            await agent_storage.record_agent_state(
                agent_id=agent_id,
                E=ctx.metrics_dict.get('E', 0.7),
                I=ctx.metrics_dict.get('I', 0.8),
                S=ctx.metrics_dict.get('S', 0.1),
                V=ctx.metrics_dict.get('V', 0.0),
                regime=ctx.metrics_dict.get('regime', 'EXPLORATION'),
                coherence=ctx.metrics_dict.get('coherence', 0.5),
                health_status=ctx.health_status.value,
                risk_score=ctx.risk_score,
                phi=ctx.metrics_dict.get('phi', 0.0),
                verdict=ctx.metrics_dict.get('verdict', 'continue'),
            )
            logger.debug(f"PostgreSQL: Created agent and recorded state for {agent_id}")
        except Exception as create_error:
            logger.warning(f"PostgreSQL create+record failed: {create_error}", exc_info=True)
    except Exception as e:
        logger.warning(f"PostgreSQL record_agent_state failed: {e}", exc_info=True)

    # Auto-emit outcome event
    ctx.outcome_event_id = None
    try:
        if ctx.response_text and ctx.complexity >= 0.3:
            _rt_lower = ctx.response_text.lower()
            _completion_signals = (
                'completed', 'implemented', 'deployed', 'finished',
                'fixed', 'resolved', 'shipped', 'merged', 'built',
                'created', 'added', 'refactored', 'migrated',
            )
            if any(sig in _rt_lower for sig in _completion_signals):
                from src.db import get_db
                _db = get_db()
                if _db:
                    _summary = ctx.response_text[:500] if len(ctx.response_text) > 500 else ctx.response_text
                    ctx.outcome_event_id = await _db.record_outcome_event(
                        agent_id=agent_id,
                        outcome_type='task_completed',
                        is_bad=False,
                        outcome_score=min(1.0, ctx.metrics_dict.get('coherence', 0.5) * 1.5),
                        session_id=ctx.arguments.get('client_session_id'),
                        eisv_e=ctx.metrics_dict.get('E'),
                        eisv_i=ctx.metrics_dict.get('I'),
                        eisv_s=ctx.metrics_dict.get('S'),
                        eisv_v=ctx.metrics_dict.get('V'),
                        eisv_phi=ctx.metrics_dict.get('phi'),
                        eisv_verdict=ctx.metrics_dict.get('verdict'),
                        eisv_coherence=ctx.metrics_dict.get('coherence'),
                        eisv_regime=ctx.metrics_dict.get('regime'),
                        detail={
                            'source': 'auto_checkin',
                            'complexity': ctx.complexity,
                            'confidence': ctx.arguments.get('confidence'),
                            'summary': _summary,
                        },
                    )
                    if ctx.outcome_event_id:
                        logger.debug(f"Auto-emitted outcome event {ctx.outcome_event_id} for {agent_id}")
    except Exception as e:
        logger.debug(f"Outcome event auto-emit skipped: {e}")
