"""
Update Enrichments — Phase 6 functions for process_agent_update.

Each function enriches ctx.response_data with one concern.
Every function is fail-safe: wraps its logic in try/except so a single
enrichment failure never crashes the update.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

from src.logging_utils import get_logger
from src.governance_monitor import UNITARESMonitor

from .update_context import UpdateContext

logger = get_logger(__name__)


# ─── Interpretation & Feedback ──────────────────────────────────────────

async def enrich_state_interpretation(ctx: UpdateContext) -> None:
    """Map raw EISV to semantic state (health / mode / basin)."""
    try:
        mcp_server = ctx.mcp_server
        monitor = mcp_server.monitors.get(ctx.agent_id)
        task_type = ctx.agent_state.get("task_type", "mixed")
        interpreted_state = monitor.state.interpret_state(
            risk_score=ctx.risk_score,
            task_type=task_type
        )
        ctx.response_data['state'] = interpreted_state

        health = interpreted_state.get('health', 'unknown')
        mode = interpreted_state.get('mode', 'unknown')
        basin = interpreted_state.get('basin', 'unknown')
        ctx.response_data['summary'] = f"{health} | {mode} | {basin} basin"
    except Exception as e:
        logger.debug(f"Could not generate state interpretation: {e}")


def enrich_actionable_feedback(ctx: UpdateContext) -> None:
    """Generate context-aware actionable feedback."""
    try:
        from .utils import generate_actionable_feedback
        mcp_server = ctx.mcp_server
        monitor = mcp_server.monitors.get(ctx.agent_id)

        previous_coherence = None
        try:
            if hasattr(monitor, 'state') and hasattr(monitor.state, 'coherence_history'):
                history = monitor.state.coherence_history
                if len(history) >= 2:
                    previous_coherence = history[-2]
        except Exception:
            pass

        actionable_feedback = generate_actionable_feedback(
            metrics=ctx.metrics_dict,
            interpreted_state=ctx.response_data.get('state'),
            task_type=ctx.task_type,
            response_text=ctx.response_text,
            previous_coherence=previous_coherence,
        )
        if actionable_feedback:
            ctx.response_data['actionable_feedback'] = actionable_feedback
    except Exception as e:
        logger.debug(f"Could not generate actionable feedback: {e}")


def enrich_calibration_feedback(ctx: UpdateContext) -> None:
    """Add calibration feedback (complexity + confidence)."""
    try:
        calibration_feedback = {}

        if 'metrics' in ctx.result:
            metrics = ctx.result['metrics']
            reported_complexity = ctx.complexity
            derived_complexity = metrics.get('complexity', None)
            if derived_complexity is not None and reported_complexity is not None:
                discrepancy = abs(reported_complexity - derived_complexity)
                calibration_feedback['complexity'] = {
                    'reported': reported_complexity,
                    'derived': derived_complexity,
                    'discrepancy': discrepancy,
                    'message': (
                        f"Your reported complexity ({reported_complexity:.2f}) vs system-derived ({derived_complexity:.2f}) "
                        f"differs by {discrepancy:.2f}. "
                        f"{'High discrepancy - consider calibrating your complexity estimates' if discrepancy > 0.3 else 'Good alignment'}"
                    )
                }

        from src.mcp_handlers.utils import get_calibration_feedback
        confidence_feedback = get_calibration_feedback(include_complexity=False)
        if confidence_feedback:
            calibration_feedback.update(confidence_feedback)

        if ctx.calibration_correction_info:
            calibration_feedback['auto_correction'] = {
                'applied': True,
                'details': ctx.calibration_correction_info,
                'message': "Your reported confidence was adjusted based on historical accuracy. This helps calibrate your estimates automatically."
            }

        if calibration_feedback:
            ctx.response_data['calibration_feedback'] = calibration_feedback
    except Exception as e:
        logger.debug(f"Could not generate calibration feedback: {e}")


# ─── Warnings & Loop Detection ─────────────────────────────────────────

def enrich_warnings(ctx: UpdateContext) -> None:
    """Collect warnings: loop cooldown, default agent_id, policy warnings."""
    try:
        mcp_server = ctx.mcp_server
        ctx.warnings = []

        # Loop cooldown
        ctx.loop_info = None
        if ctx.meta and hasattr(ctx.meta, 'loop_cooldown_until') and ctx.meta.loop_cooldown_until:
            try:
                cooldown_until = datetime.fromisoformat(ctx.meta.loop_cooldown_until)
                now = datetime.now()
                if now < cooldown_until:
                    remaining_seconds = (cooldown_until - now).total_seconds()
                    ctx.loop_info = {
                        "active": True,
                        "cooldown_remaining_seconds": round(remaining_seconds, 1),
                        "message": f"Loop detection cooldown active. Wait {remaining_seconds:.1f}s before rapid updates."
                    }
                else:
                    ctx.meta.loop_cooldown_until = None
            except (ValueError, TypeError, AttributeError):
                pass

        # Default agent_id warning
        try:
            default_warning = mcp_server.check_agent_id_default(ctx.agent_id)
            if default_warning:
                ctx.warnings.append(default_warning)
        except (NameError, AttributeError):
            pass
        except Exception as e:
            logger.warning(f"Could not check agent_id default: {e}")

        # Policy warnings
        if ctx.policy_warnings:
            ctx.warnings.extend(ctx.policy_warnings)

        # Apply to response_data
        if ctx.loop_info:
            ctx.response_data['loop_detection'] = ctx.loop_info
        if ctx.warnings:
            ctx.response_data["warning"] = "\n\n".join(ctx.warnings)

        # Auto-resume info
        if ctx.auto_resume_info:
            ctx.response_data["auto_resume"] = ctx.auto_resume_info
    except Exception as e:
        logger.debug(f"Could not enrich warnings: {e}")


# ─── Metric Standardization ────────────────────────────────────────────

def enrich_metric_standardization(ctx: UpdateContext) -> None:
    """Standardize metric reporting with agent_id and context."""
    try:
        from src.mcp_handlers.utils import format_metrics_report
        mcp_server = ctx.mcp_server

        if 'metrics' not in ctx.response_data:
            ctx.response_data['metrics'] = {}

        standardized_metrics = format_metrics_report(
            metrics=ctx.response_data['metrics'],
            agent_id=ctx.agent_id,
            include_timestamp=True,
            include_context=True
        )
        ctx.response_data['metrics'] = standardized_metrics
        ctx.response_data["agent_id"] = ctx.agent_id
    except Exception as e:
        logger.debug(f"Could not standardize metrics: {e}")


def enrich_health_status_toplevel(ctx: UpdateContext) -> None:
    """Ensure health_status is at top level for easy access."""
    try:
        mcp_server = ctx.mcp_server
        if 'metrics' in ctx.response_data:
            metrics = ctx.response_data['metrics']
            if 'health_status' in metrics:
                ctx.response_data["health_status"] = metrics['health_status']
                ctx.response_data["health_message"] = metrics.get('health_message', '')
            else:
                ctx.response_data["health_status"] = ctx.response_data.get('status', 'unknown')
                ctx.response_data["health_message"] = ''
        else:
            ctx.response_data["health_status"] = ctx.response_data.get('status', 'unknown')
            ctx.response_data["health_message"] = ''

        # Ensure EISV metrics are always present
        if 'metrics' in ctx.response_data:
            metrics = ctx.response_data['metrics']
            for dim in ('E', 'I', 'S', 'V'):
                if dim not in metrics:
                    metrics[dim] = metrics.get('eisv', {}).get(dim, 0.0)

            if 'eisv' not in metrics:
                metrics['eisv'] = {d: metrics.get(d, 0.0) for d in ('E', 'I', 'S', 'V')}
            else:
                for d in ('E', 'I', 'S', 'V'):
                    metrics['eisv'][d] = metrics.get(d, metrics['eisv'].get(d, 0.0))

            # Ensure risk metrics consistent with get_governance_metrics
            if 'current_risk' not in metrics or 'mean_risk' not in metrics:
                try:
                    monitor = mcp_server.get_or_create_monitor(ctx.agent_id)
                    monitor_metrics = monitor.get_metrics()
                    if 'current_risk' not in metrics:
                        metrics['current_risk'] = monitor_metrics.get('current_risk')
                    if 'mean_risk' not in metrics:
                        metrics['mean_risk'] = monitor_metrics.get('mean_risk')
                    if 'latest_risk_score' not in metrics:
                        metrics['latest_risk_score'] = monitor_metrics.get('latest_risk_score')
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Could not enrich health status: {e}")


# ─── CIRS Response Fields ──────────────────────────────────────────────

def enrich_cirs_response_fields(ctx: UpdateContext) -> None:
    """Include CIRS protocol info (void alert, state announce, outcome event)."""
    try:
        if ctx.cirs_alert:
            ctx.response_data["cirs_void_alert"] = {
                "emitted": True,
                "severity": ctx.cirs_alert.get("severity"),
                "V_snapshot": ctx.cirs_alert.get("V_snapshot"),
                "message": f"VOID_ALERT broadcast to peer agents: {ctx.cirs_alert.get('severity', 'warning').upper()}"
            }

        if ctx.outcome_event_id:
            ctx.response_data["outcome_event"] = {
                "emitted": True,
                "outcome_id": ctx.outcome_event_id,
                "outcome_type": "task_completed",
                "message": "Outcome event recorded for EISV validation"
            }

        if ctx.cirs_state_announce:
            ctx.response_data["cirs_state_announce"] = {
                "emitted": True,
                "regime": ctx.cirs_state_announce.get("regime"),
                "update_count": ctx.cirs_state_announce.get("update_count"),
                "message": "STATE_ANNOUNCE broadcast to peer agents"
            }
    except Exception as e:
        logger.debug(f"Could not enrich CIRS fields: {e}")


# ─── Knowledge Surfacing ───────────────────────────────────────────────

async def enrich_knowledge_surfacing(ctx: UpdateContext) -> None:
    """Surface top 3 relevant discoveries based on agent tags."""
    try:
        agent_tags = ctx.meta.tags if ctx.meta and ctx.meta.tags else []

        if agent_tags:
            from src.knowledge_graph import get_knowledge_graph
            graph = await get_knowledge_graph()

            tag_matches = await graph.query(tags=agent_tags, status="open", limit=10)

            scored = []
            agent_tags_set = set(agent_tags)
            for disc in tag_matches:
                disc_tags_set = set(disc.tags)
                overlap = len(agent_tags_set & disc_tags_set)
                if overlap > 0:
                    scored.append((overlap, disc))

            scored.sort(reverse=True, key=lambda x: x[0])
            relevant_discoveries = [disc.to_dict(include_details=False) for _, disc in scored[:3]]

            if relevant_discoveries:
                ctx.response_data["relevant_discoveries"] = {
                    "message": f"Found {len(relevant_discoveries)} relevant discovery/discoveries matching your tags",
                    "discoveries": relevant_discoveries
                }
    except Exception as e:
        logger.debug(f"Could not surface relevant discoveries: {e}")


# ─── Onboarding Info ───────────────────────────────────────────────────

def enrich_onboarding_info(ctx: UpdateContext) -> None:
    """Include onboarding guidance, API key hints, welcome message."""
    try:
        mcp_server = ctx.mcp_server

        if ctx.onboarding_guidance:
            ctx.response_data["onboarding"] = ctx.onboarding_guidance

        if ctx.is_new_agent or ctx.key_was_generated or ctx.api_key_auto_retrieved:
            meta = ctx.meta
            if not meta:
                meta = mcp_server.agent_metadata.get(ctx.agent_id)
            if meta:
                api_key_hint = meta.api_key[:8] + "..." if meta.api_key and len(meta.api_key) > 8 else meta.api_key
                ctx.response_data["api_key_hint"] = api_key_hint
                ctx.response_data["_onboarding"] = {
                    "api_key_hint": api_key_hint,
                    "message": "API key created (use get_agent_api_key to retrieve full key)",
                    "next_steps": [
                        "Call get_agent_api_key(agent_id) to retrieve your full API key",
                        "Identity auto-binds on first tool call - API key auto-retrieved for all subsequent calls",
                    ],
                    "identity_binding": {
                        "auto": True,
                        "benefit": "Identity auto-binds on first tool call - no explicit binding needed",
                    },
                    "security_note": "Full API keys are not included in responses to prevent context leakage in multi-agent environments."
                }
                if os.getenv("UNITARES_INCLUDE_API_KEY_IN_RESPONSES") == "1" or os.getenv("PYTEST_CURRENT_TEST"):
                    ctx.response_data["api_key"] = meta.api_key
            if ctx.is_new_agent:
                ctx.response_data["api_key_warning"] = "Use get_agent_api_key(agent_id) to retrieve your API key. Save it securely."
            elif ctx.key_was_generated:
                ctx.response_data["api_key_warning"] = "API key regenerated (migration). Use get_agent_api_key(agent_id) to retrieve it."
            elif ctx.api_key_auto_retrieved:
                ctx.response_data["api_key_info"] = "Session authenticated via stored credentials. No need to pass api_key."

        meta = ctx.meta
        if meta and meta.total_updates == 1:
            ctx.response_data["welcome"] = (
                "Welcome to the governance system! This is your first update. "
                "The system tracks your work's thermodynamic state (E, I, S, V) and provides "
                "supportive feedback. Use the metrics and sampling parameters as helpful guidance, "
                "not requirements. The knowledge graph contains discoveries from other agents - "
                "feel free to explore it when relevant. "
                "\n\nYour identity auto-binds to this session. Use identity() to check it, "
                "or identity(name='YourName_model_date') to name yourself."
            )
    except Exception as e:
        logger.debug(f"Could not enrich onboarding info: {e}")


# ─── Convergence Guidance ──────────────────────────────────────────────

async def enrich_convergence_guidance(ctx: UpdateContext) -> None:
    """Provide equilibrium-based convergence acceleration for new agents."""
    try:
        mcp_server = ctx.mcp_server
        meta = mcp_server.agent_metadata.get(ctx.agent_id)
        if meta and meta.total_updates < 20:
            metrics_dict = ctx.response_data.get("metrics", {})
            E = metrics_dict.get("E", 0.7)
            I = metrics_dict.get("I", 0.8)
            S = metrics_dict.get("S", 0.2)
            V = metrics_dict.get("V", 0.0)

            from governance_core.parameters import get_i_dynamics_mode
            dynamics_mode = get_i_dynamics_mode()

            if dynamics_mode == "linear":
                from governance_core.parameters import get_active_params, DEFAULT_THETA
                from governance_core.coherence import coherence
                from governance_core.dynamics import State
                params = get_active_params()
                state = State(E=E, I=I, S=S, V=V)
                C = coherence(V, DEFAULT_THETA, params)
                A = params.beta_I * C - params.k * S
                I_target = min(1.0, max(0.0, A / params.gamma_I)) if params.gamma_I > 0 else 1.0
            else:
                I_target = 1.0

            equilibrium_distance = ((I_target - I) ** 2 + S ** 2) ** 0.5

            convergence_guidance = []

            if S > 0.1:
                convergence_guidance.append({
                    "metric": "S (Entropy)",
                    "current": f"{S:.3f}",
                    "target": "0.0",
                    "guidance": "High entropy detected. Focus on coherent, consistent work to reduce S. "
                               "Reduce uncertainty by maintaining clear, structured approaches.",
                    "priority": "high" if S > 0.2 else "medium"
                })

            if I < I_target - 0.1:
                convergence_guidance.append({
                    "metric": "I (Information Integrity)",
                    "current": f"{I:.3f}",
                    "target": f"{I_target:.2f}",
                    "guidance": "Integrity below equilibrium. Focus on consistent, well-structured work.",
                    "priority": "high" if I < I_target - 0.2 else "medium"
                })

            if E < 0.7:
                convergence_guidance.append({
                    "metric": "E (Energy)",
                    "current": f"{E:.3f}",
                    "target": "0.7-1.0",
                    "guidance": "Low energy. Increase exploration and productive capacity. "
                               "Engage more actively with your work.",
                    "priority": "medium"
                })

            if abs(V) > 0.1:
                convergence_guidance.append({
                    "metric": "V (Void Integral)",
                    "current": f"{V:.3f}",
                    "target": "0.0",
                    "guidance": "Energy-integrity imbalance detected. Balance exploration (E) "
                               "with consistency (I) to reduce void accumulation.",
                    "priority": "medium" if abs(V) > 0.2 else "low"
                })

            if convergence_guidance:
                if dynamics_mode == "linear":
                    eq_note = f"Linear dynamics: agents converge to stable equilibrium at I~{I_target:.2f}."
                else:
                    eq_note = "Logistic dynamics: agents converge toward I=1.0 (boundary attractor)."

                ctx.response_data["convergence_guidance"] = {
                    "message": f"Equilibrium guidance (distance: {equilibrium_distance:.3f})",
                    "equilibrium_target": {"I": I_target, "S": 0.0},
                    "current_state": {"E": E, "I": I, "S": S, "V": V},
                    "guidance": convergence_guidance,
                    "dynamics_mode": dynamics_mode,
                    "note": eq_note
                }
    except Exception as e:
        logger.debug(f"Could not generate convergence guidance: {e}", exc_info=True)


# ─── Anti-Stasis Perturbation ──────────────────────────────────────────

async def enrich_anti_stasis_perturbation(ctx: UpdateContext) -> None:
    """Surface an open question for stable agents to prevent stasis."""
    try:
        mcp_server = ctx.mcp_server
        meta = mcp_server.agent_metadata.get(ctx.agent_id)
        health_status = ctx.response_data.get("health_status", "unknown")

        if (meta and meta.total_updates >= 10 and
                health_status == "healthy" and
                ctx.response_data.get("metrics", {}).get("S", 1.0) < 0.15):

            last_perturbation = getattr(meta, '_last_perturbation_update', 0)
            if meta.total_updates - last_perturbation >= 5:

                from src.knowledge_graph import get_knowledge_graph
                graph = await get_knowledge_graph()

                agent_tags = meta.tags if meta.tags else []
                open_questions = await graph.query(
                    type="question",
                    status="open",
                    tags=agent_tags if agent_tags else None,
                    limit=3
                )

                if open_questions:
                    question = open_questions[0]
                    ctx.response_data["perturbation"] = {
                        "message": "You've been stable. Here's something unresolved to consider:",
                        "question": {
                            "id": question.id,
                            "summary": question.summary[:300],
                            "tags": question.tags[:5] if question.tags else [],
                            "by": question.agent_id
                        },
                        "invitation": "Stable systems need perturbation to grow. Consider engaging with this open question.",
                        "action": "Use store_knowledge_graph with response_to to contribute your perspective."
                    }
                    meta._last_perturbation_update = meta.total_updates
                    logger.debug(f"Perturbed stable agent {ctx.agent_id[:8]}... with open question")
    except Exception as e:
        logger.debug(f"Could not generate perturbation: {e}")


# ─── Basin Tracking ────────────────────────────────────────────────────

def enrich_basin_tracking(ctx: UpdateContext) -> None:
    """Surface v4.1 basin/convergence tracking when available."""
    try:
        metrics_dict = ctx.response_data.get("metrics", {})
        v41_block = metrics_dict.get("unitares_v41")
        if isinstance(v41_block, dict):
            ctx.response_data["unitares_v41"] = v41_block
    except Exception:
        pass


# ─── Trajectory Identity ───────────────────────────────────────────────

async def enrich_trajectory_identity(ctx: UpdateContext) -> None:
    """Compare trajectory signature if provided (lineage tracking, trust tier)."""
    trajectory_signature = ctx.arguments.get("trajectory_signature")
    if not trajectory_signature or not isinstance(trajectory_signature, dict):
        return

    try:
        from src.trajectory_identity import TrajectorySignature, update_current_signature
        sig = TrajectorySignature.from_dict(trajectory_signature)
        trajectory_result = await update_current_signature(ctx.agent_uuid, sig)

        if trajectory_result and not trajectory_result.get("error"):
            ctx.response_data["trajectory_identity"] = {
                "updated": trajectory_result.get("stored", False),
                "observation_count": trajectory_result.get("observation_count"),
                "identity_confidence": trajectory_result.get("identity_confidence"),
            }

            if "lineage_similarity" in trajectory_result:
                ctx.response_data["trajectory_identity"]["lineage"] = {
                    "similarity": trajectory_result["lineage_similarity"],
                    "threshold": trajectory_result.get("lineage_threshold", 0.6),
                    "is_anomaly": trajectory_result.get("is_anomaly", False),
                }
                if trajectory_result.get("is_anomaly"):
                    ctx.response_data["trajectory_identity"]["warning"] = trajectory_result.get("warning")
                    logger.warning(f"[TRAJECTORY] Anomaly detected for {ctx.agent_uuid[:8]}...")

            elif trajectory_result.get("genesis_created"):
                ctx.response_data["trajectory_identity"]["genesis_created"] = True
                logger.info(f"[TRAJECTORY] Created genesis S_0 for {ctx.agent_uuid[:8]}... on first update")

            # Trust tier computation
            try:
                from src.trajectory_identity import compute_trust_tier
                from src.db import get_db as _get_db

                trust_tier = trajectory_result.get("trust_tier")
                if not trust_tier:
                    identity = await _get_db().get_identity(ctx.agent_uuid)
                    if identity and identity.metadata:
                        trust_tier = compute_trust_tier(identity.metadata)

                if trust_tier:
                    ctx.response_data["trajectory_identity"]["trust_tier"] = trust_tier

                    mcp_server = ctx.mcp_server
                    meta = ctx.meta or mcp_server.agent_metadata.get(ctx.agent_id)
                    if meta:
                        meta.trust_tier = trust_tier.get("name", "unknown")
                        meta.trust_tier_num = trust_tier.get("tier", 0)

                    tier_num = trust_tier.get("tier", 0)
                    is_anomaly = trajectory_result.get("is_anomaly", False)

                    risk_adj = 0.0
                    risk_reason = None

                    if is_anomaly:
                        risk_adj = 0.15
                        risk_reason = "Behavioral deviation detected (lineage < 0.6)"
                    elif tier_num <= 1:
                        risk_adj = 0.05
                        risk_reason = f"Trust tier {tier_num} ({trust_tier['name']}): identity not yet established"
                    elif tier_num == 3:
                        risk_adj = -0.05
                        risk_reason = f"Trust tier 3 (verified): earned trust reduces friction"

                    if risk_adj != 0.0 and "metrics" in ctx.response_data:
                        original_risk = ctx.response_data["metrics"].get("risk_score")
                        if original_risk is not None:
                            adjusted_risk = max(0.0, min(1.0, original_risk + risk_adj))
                            ctx.response_data["metrics"]["risk_score"] = round(adjusted_risk, 4)
                            ctx.response_data["metrics"]["trajectory_risk_adjustment"] = {
                                "original": round(original_risk, 4),
                                "adjusted": round(adjusted_risk, 4),
                                "delta": risk_adj,
                                "reason": risk_reason,
                            }
                            logger.info(
                                f"[TRAJECTORY] Risk adjusted for {ctx.agent_uuid[:8]}...: "
                                f"{original_risk:.3f} -> {adjusted_risk:.3f} ({risk_reason})"
                            )
            except Exception as e:
                logger.debug(f"[TRAJECTORY] Trust tier computation failed: {e}")

    except Exception as e:
        logger.debug(f"[TRAJECTORY] Could not update trajectory: {e}")


# ─── Saturation Diagnostics ────────────────────────────────────────────

def enrich_saturation_diagnostics(ctx: UpdateContext) -> None:
    """v4.2-P saturation diagnostics — pressure gauge for I-channel."""
    try:
        from governance_core import compute_saturation_diagnostics
        from governance_core.parameters import DEFAULT_THETA

        mcp_server = ctx.mcp_server
        monitor = mcp_server.monitors.get(ctx.agent_id)
        unitares_state = monitor.state.unitaires_state
        theta = getattr(monitor.state, 'unitaires_theta', None) or DEFAULT_THETA

        if unitares_state:
            sat_diag = compute_saturation_diagnostics(unitares_state, theta)
            ctx.response_data['saturation_diagnostics'] = {
                'sat_margin': sat_diag['sat_margin'],
                'dynamics_mode': sat_diag['dynamics_mode'],
                'will_saturate': sat_diag['will_saturate'],
                'at_boundary': sat_diag['at_boundary'],
                'I_equilibrium': sat_diag['I_equilibrium_linear'],
                'forcing_term_A': sat_diag['A'],
                '_interpretation': (
                    "Positive sat_margin means push-to-boundary (logistic mode will saturate I->1)"
                    if sat_diag['sat_margin'] > 0
                    else "Negative sat_margin - stable interior equilibrium exists"
                )
            }
    except Exception as e:
        logger.debug(f"Could not compute saturation diagnostics: {e}")


# ─── Pending Dialectic ─────────────────────────────────────────────────

async def enrich_pending_dialectic(ctx: UpdateContext) -> None:
    """Notify agent of pending dialectic sessions where they owe a response."""
    try:
        from .dialectic import ACTIVE_SESSIONS
        from src.dialectic_protocol import DialecticPhase

        pending_dialectic = []
        for session_id, session in ACTIVE_SESSIONS.items():
            if session.reviewer_agent_id == ctx.agent_id and session.phase == DialecticPhase.ANTITHESIS:
                pending_dialectic.append({
                    "session_id": session_id,
                    "role": "reviewer",
                    "phase": "antithesis",
                    "partner": session.paused_agent_id,
                    "topic": getattr(session, 'topic', None),
                    "action_needed": "Submit antithesis via submit_antithesis()",
                    "created_at": session.created_at.isoformat() if session.created_at else None
                })
            elif session.paused_agent_id == ctx.agent_id and session.phase == DialecticPhase.SYNTHESIS:
                pending_dialectic.append({
                    "session_id": session_id,
                    "role": "initiator",
                    "phase": "synthesis",
                    "partner": session.reviewer_agent_id,
                    "topic": getattr(session, 'topic', None),
                    "action_needed": "Submit synthesis via submit_synthesis()",
                    "created_at": session.created_at.isoformat() if session.created_at else None
                })

        if pending_dialectic:
            ctx.response_data["pending_dialectic"] = {
                "message": f"You have {len(pending_dialectic)} pending dialectic session(s) awaiting your response!",
                "sessions": pending_dialectic,
                "note": "Dialectic sessions enable collaborative exploration and recovery. Respond to keep the conversation going."
            }
    except Exception as e:
        logger.debug(f"Could not check pending dialectic sessions: {e}")


# ─── EISV Validation ───────────────────────────────────────────────────

def enrich_eisv_validation(ctx: UpdateContext) -> None:
    """Ensure all four EISV metrics are present (prevents selection bias)."""
    try:
        from src.eisv_validator import validate_governance_response
        validate_governance_response(ctx.response_data)
    except ImportError:
        pass
    except Exception as validation_error:
        logger.warning(f"EISV validation warning: {validation_error}")
        ctx.response_data["_eisv_validation_warning"] = str(validation_error)


# ─── Learning Context ──────────────────────────────────────────────────

async def enrich_learning_context(ctx: UpdateContext) -> None:
    """Surface agent's own history for in-context learning."""
    try:
        mcp_server = ctx.mcp_server
        learning_context = {}

        # 1. Recent decisions from audit log
        try:
            from src.audit_log import AuditLogger
            audit_logger = AuditLogger()
            recent_events = audit_logger.query_audit_log(agent_id=ctx.agent_id, limit=10)
            if recent_events:
                recent_decisions = []
                for event in recent_events[:5]:
                    details = event.get("details", {})
                    decision_summary = {
                        "timestamp": event.get("timestamp", "")[:19],
                        "action": details.get("action") or details.get("decision") or event.get("event_type"),
                        "risk": round(details.get("risk_score", 0), 2) if details.get("risk_score") else None,
                        "confidence": round(details.get("confidence", 0), 2) if details.get("confidence") else None,
                    }
                    if decision_summary.get("action"):
                        recent_decisions.append(decision_summary)

                if recent_decisions:
                    learning_context["recent_decisions"] = {
                        "count": len(recent_decisions),
                        "decisions": recent_decisions,
                        "insight": "Your recent actions - notice patterns in what worked"
                    }
        except Exception as e:
            logger.debug(f"Could not fetch recent decisions: {e}")

        # 2. Agent's own knowledge graph contributions
        try:
            from src.knowledge_graph import get_knowledge_graph
            graph = await get_knowledge_graph()
            my_discoveries = await graph.query(agent_id=ctx.agent_id, limit=5)
            if my_discoveries:
                learning_context["my_contributions"] = {
                    "count": len(my_discoveries),
                    "recent": [
                        {
                            "summary": d.summary[:100] + "..." if len(d.summary) > 100 else d.summary,
                            "type": d.discovery_type,
                            "status": d.status
                        }
                        for d in my_discoveries[:3]
                    ],
                    "insight": "Your recent discoveries - build on these"
                }
        except Exception as e:
            logger.debug(f"Could not fetch agent's discoveries: {e}")

        # 3. Calibration insight
        try:
            from src.calibration import calibration_checker

            bin_stats = calibration_checker.bin_stats
            total = sum(s['count'] for s in bin_stats.values())

            if total >= 10:
                total_correct = sum(s.get('actual_correct', 0) for s in bin_stats.values())
                overall_accuracy = total_correct / total if total > 0 else 0

                high_conf_bins = ['0.7-0.8', '0.8-0.9', '0.9-1.0']
                low_conf_bins = ['0.0-0.5', '0.5-0.7']

                high_conf_total = sum(bin_stats.get(b, {}).get('count', 0) for b in high_conf_bins)
                high_conf_correct = sum(bin_stats.get(b, {}).get('actual_correct', 0) for b in high_conf_bins)
                high_conf_accuracy = high_conf_correct / high_conf_total if high_conf_total > 0 else 0

                low_conf_total = sum(bin_stats.get(b, {}).get('count', 0) for b in low_conf_bins)
                low_conf_correct = sum(bin_stats.get(b, {}).get('actual_correct', 0) for b in low_conf_bins)
                low_conf_accuracy = low_conf_correct / low_conf_total if low_conf_total > 0 else 0

                if high_conf_accuracy < low_conf_accuracy - 0.2:
                    cal_insight = "INVERTED CALIBRATION: High confidence correlates with LOWER accuracy. Consider being more humble."
                elif abs(high_conf_accuracy - low_conf_accuracy) < 0.1:
                    cal_insight = "Well calibrated - confidence matches outcomes"
                else:
                    cal_insight = f"Calibration data available ({total} decisions auto-evaluated)"

                learning_context["calibration"] = {
                    "total_decisions": total,
                    "overall_accuracy": round(overall_accuracy, 2),
                    "high_confidence_accuracy": round(high_conf_accuracy, 2),
                    "low_confidence_accuracy": round(low_conf_accuracy, 2),
                    "insight": cal_insight,
                    "source": "auto-collected from trajectory outcomes (no human input required)"
                }
        except Exception as e:
            logger.debug(f"Could not fetch calibration data: {e}")

        # 4. Pattern detection
        try:
            monitor = mcp_server.get_or_create_monitor(ctx.agent_id)
            state = monitor.state

            patterns = []

            if hasattr(state, 'regime'):
                regime_duration = getattr(state, 'regime_duration', 0)
                if regime_duration > 5:
                    patterns.append(f"In {state.regime} regime for {regime_duration} updates")

            E = ctx.response_data.get('metrics', {}).get('E', 0.7)
            if E > 0.85:
                patterns.append("High energy - consider channeling into focused work")
            elif E < 0.5:
                patterns.append("Low energy - consider taking a step back")

            coherence_val = ctx.response_data.get('metrics', {}).get('coherence', 0.5)
            if coherence_val < 0.4:
                patterns.append("Low coherence - your approach may be scattered")
            elif coherence_val > 0.8:
                patterns.append("High coherence - maintaining consistent approach")

            if patterns:
                learning_context["patterns"] = {
                    "observations": patterns,
                    "insight": "Patterns from your work - use these for self-awareness"
                }
        except Exception as e:
            logger.debug(f"Could not detect patterns: {e}")

        if learning_context:
            ctx.response_data["learning_context"] = {
                "_purpose": "Your own history, surfaced for in-context learning",
                **learning_context
            }
    except Exception as e:
        logger.debug(f"Could not build learning context: {e}")


# ─── WebSocket Broadcast ───────────────────────────────────────────────

async def enrich_websocket_broadcast(ctx: UpdateContext) -> None:
    """Broadcast EISV update to dashboard via WebSocket."""
    try:
        from src.broadcaster import broadcaster_instance

        if not broadcaster_instance:
            return

        mcp_server = ctx.mcp_server
        metrics = ctx.response_data.get("metrics", {})

        logger.info(
            f"Broadcast metrics for {ctx.declared_agent_id}: "
            f"E={metrics.get('E')}, I={metrics.get('I')}, S={metrics.get('S')}, V={metrics.get('V')}, "
            f"coherence={metrics.get('coherence')}"
        )

        # Extract sensor data if present (Lumen check-ins)
        broadcast_sensor_data = None
        params_raw = ctx.arguments.get("parameters", [])
        if isinstance(params_raw, list):
            for p in params_raw:
                if isinstance(p, dict) and p.get("key") == "sensor_data":
                    try:
                        broadcast_sensor_data = json.loads(p.get("value"))
                        break
                    except Exception:
                        pass

        # Extract EISV values
        eisv_nested = metrics.get("eisv", {})
        eisv_data = {
            "E": metrics.get("E") if metrics.get("E") is not None else eisv_nested.get("E", 0),
            "I": metrics.get("I") if metrics.get("I") is not None else eisv_nested.get("I", 0),
            "S": metrics.get("S") if metrics.get("S") is not None else eisv_nested.get("S", 0),
            "V": metrics.get("V") if metrics.get("V") is not None else eisv_nested.get("V", 0)
        }
        coherence_val = metrics.get("coherence") if metrics.get("coherence") is not None else 0

        # Display name
        display_name = ctx.label if ctx.label else ctx.declared_agent_id
        if display_name and len(display_name) == 36 and '-' in display_name:
            try:
                if ctx.agent_uuid in mcp_server.agent_metadata:
                    cached_label = getattr(mcp_server.agent_metadata[ctx.agent_uuid], 'label', None)
                    if cached_label:
                        display_name = cached_label
            except Exception:
                pass

        # Risk values
        risk_adjusted = metrics.get("risk_score", 0)
        risk_raw = metrics.get("current_risk") or metrics.get("latest_risk_score") or risk_adjusted
        trajectory_adj = metrics.get("trajectory_risk_adjustment", {})
        risk_adj_delta = trajectory_adj.get("delta", 0) if trajectory_adj else 0
        risk_adj_reason = trajectory_adj.get("reason", "") if trajectory_adj else ""

        # Governance events
        governance_events = []
        try:
            from src.event_detector import event_detector
            decision = ctx.response_data.get("decision", {})
            ethical_drift = ctx.ethical_drift
            governance_events = event_detector.detect_events(
                agent_id=ctx.agent_uuid,
                agent_name=display_name,
                action=decision.get("action", "proceed"),
                risk=risk_adjusted,
                risk_raw=risk_raw,
                risk_adjustment=risk_adj_delta,
                risk_reason=risk_adj_reason,
                drift=ethical_drift if isinstance(ethical_drift, list) else [0, 0, 0],
                verdict=metrics.get("verdict", "safe"),
            )
            if governance_events:
                logger.info(f"Events detected for {display_name}: {[e['type'] for e in governance_events]}")
        except Exception as e:
            logger.debug(f"Could not detect events: {e}")

        # Drift trends
        drift_trends = {}
        try:
            from src.event_detector import event_detector as _ed
            drift_trends = _ed.get_drift_trends(ctx.agent_uuid)
        except Exception:
            pass

        await broadcaster_instance.broadcast({
            "type": "eisv_update",
            "agent_id": ctx.agent_uuid,
            "agent_name": display_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "eisv": eisv_data,
            "coherence": coherence_val,
            "metrics": metrics,
            "decision": ctx.response_data.get("decision", {}),
            "inputs": {
                "complexity": ctx.complexity,
                "confidence": ctx.confidence,
                "ethical_drift": ctx.ethical_drift if isinstance(ctx.ethical_drift, list) else [0, 0, 0]
            },
            "risk": risk_adjusted,
            "risk_raw": risk_raw,
            "risk_adjustment": risk_adj_delta,
            "risk_reason": risk_adj_reason,
            "events": governance_events,
            "drift_trends": drift_trends,
            "sensor_data": broadcast_sensor_data
        })
        logger.debug(f"Broadcast EISV update for agent {ctx.declared_agent_id}: eisv={eisv_data}, coherence={coherence_val}")
    except Exception as e:
        logger.debug(f"Could not broadcast EISV update: {e}")
