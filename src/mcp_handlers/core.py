"""
Core governance tool handlers.

EISV Completeness: Utilities available in src/eisv_format.py and src/eisv_validator.py
to ensure all metrics (E, I, S, V) are reported together, preventing selection bias.
See docs/guides/EISV_COMPLETENESS.md for usage.
"""

from typing import Dict, Any, Optional, Sequence
from mcp.types import TextContent
import json
from .types import ToolArgumentsDict
from .utils import success_response, error_response, require_agent_id
from .decorators import mcp_tool
from src.logging_utils import get_logger

logger = get_logger(__name__)

from pathlib import Path

# Get mcp_server_std module (using shared utility)

from datetime import datetime
from src.mcp_handlers.shared import lazy_mcp_server as mcp_server
def _assess_thermodynamic_significance(
    monitor: Optional[Any],  # UNITARESMonitor type (can be None)
    result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Determine if this update is thermodynamically significant.
    
    Significant events worth logging:
    - Risk spiked > 15%
    - Coherence dropped > 10%
    - Void crossed threshold (|V| > 0.10)
    - Circuit breaker triggered
    - Decision is pause/reject
    
    Returns dict with:
        is_significant: bool
        reasons: list[str]
        timestamp: str
    """
    # Significance thresholds (from config)
    from config.governance_config import config
    RISK_SPIKE_THRESHOLD = config.RISK_SPIKE_THRESHOLD
    COHERENCE_DROP_THRESHOLD = config.COHERENCE_DROP_THRESHOLD
    VOID_THRESHOLD = config.SIGNIFICANCE_VOID_THRESHOLD
    HISTORY_WINDOW = config.SIGNIFICANCE_HISTORY_WINDOW
    
    reasons = []
    
    if not monitor:
        return {
            'is_significant': False,
            'reasons': ['No monitor available'],
            'timestamp': datetime.now().isoformat(),
        }
    
    state = monitor.state
    metrics = result.get('metrics', {})
    
    # Check risk spike (compare latest to average of previous)
    if len(state.risk_history) >= 2:
        current_risk = state.risk_history[-1]
        # Use average of previous history as baseline
        history_slice = state.risk_history[-HISTORY_WINDOW:-1] if len(state.risk_history) > 1 else []
        if history_slice:
            baseline_risk = sum(history_slice) / len(history_slice)
            risk_delta = current_risk - baseline_risk
            if risk_delta > RISK_SPIKE_THRESHOLD:
                reasons.append(f"risk_spike: +{risk_delta:.3f} (from {baseline_risk:.3f} to {current_risk:.3f})")
    
    # Check coherence drop
    if len(state.coherence_history) >= 2:
        current_coherence = state.coherence_history[-1]
        history_slice = state.coherence_history[-HISTORY_WINDOW:-1] if len(state.coherence_history) > 1 else []
        if history_slice:
            baseline_coherence = sum(history_slice) / len(history_slice)
            coh_delta = baseline_coherence - current_coherence
            if coh_delta > COHERENCE_DROP_THRESHOLD:
                reasons.append(f"coherence_drop: -{coh_delta:.3f} (from {baseline_coherence:.3f} to {current_coherence:.3f})")
    
    # Check void threshold
    V = state.V
    if abs(V) > VOID_THRESHOLD:
        reasons.append(f"void_significant: V={V:.4f} (threshold: {VOID_THRESHOLD})")
    
    # Check circuit breaker (extract once to avoid nested .get() calls)
    circuit_breaker = result.get('circuit_breaker', {})
    if circuit_breaker.get('triggered'):
        reasons.append("circuit_breaker_triggered")
    
    # Check decision type (extract once to avoid nested .get() calls)
    decision_dict = result.get('decision', {})
    decision = decision_dict.get('action', '')
    if decision in ['pause', 'reject']:
        reasons.append(f"decision_{decision}")
    
    return {
        'is_significant': len(reasons) > 0,
        'reasons': reasons,
        'timestamp': datetime.now().isoformat(),
    }

@mcp_tool("get_governance_metrics", timeout=10.0)
async def handle_get_governance_metrics(arguments: ToolArgumentsDict) -> Sequence[TextContent]:
    """Get current governance state and metrics for an agent without updating state.

    Args:
        lite: If true (default), returns minimal essential metrics only.
              Set lite=false for full diagnostic data.
    """
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]  # Wrap in list for Sequence[TextContent]

    # LITE-FIRST: Minimal response by default for smaller models
    lite = arguments.get("lite", True)

    # UX FIX (Dec 2025): Auto-register agent if not found
    # This reduces friction - agents can query metrics immediately after identity() call
    # Load monitor state from disk if not in memory (allows querying agents without recent updates)
    # get_or_create_monitor() will auto-create if agent doesn't exist yet
    monitor = mcp_server.get_or_create_monitor(agent_id)

    # Reduce context bloat by excluding nested state dict (all values still at top level)
    include_state = arguments.get("include_state", False)
    metrics = monitor.get_metrics(include_state=include_state)

    # Add EISV labels for API documentation
    from src.governance_monitor import UNITARESMonitor
    metrics['eisv_labels'] = UNITARESMonitor.get_eisv_labels()
    
    # Standardize metrics reporting with agent_id and context
    from src.mcp_handlers.utils import format_metrics_report
    standardized_metrics = format_metrics_report(
        metrics=metrics,
        agent_id=agent_id,
        include_timestamp=True,
        include_context=True
    )
    try:
        from .context import get_session_resolution_source
        standardized_metrics["session_continuity"] = {
            "resolution_source": get_session_resolution_source(),
        }
    except Exception:
        pass
    
    # Add agent purpose if available (v2.5.2+)
    meta = mcp_server.agent_metadata.get(agent_id)
    if meta and getattr(meta, 'purpose', None):
        standardized_metrics['purpose'] = meta.purpose
    
    # Add calibration feedback (similar to process_agent_update)
    calibration_feedback = {}
    
    # Complexity calibration: Show derived complexity (if available from recent updates)
    try:
        meta = mcp_server.agent_metadata.get(agent_id)
        if meta:
            # Get last reported complexity from metadata (if stored)
            # Note: This is approximate - actual reported complexity is in process_agent_update
            # But we can show derived complexity vs system expectations
            derived_complexity = metrics.get('complexity', None)
            if derived_complexity is not None:
                # System-derived complexity from state
                calibration_feedback['complexity'] = {
                    'derived': derived_complexity,
                    'message': f"System-derived complexity: {derived_complexity:.2f} (based on current state)"
                }
    except Exception as e:
        logger.debug(f"Could not add complexity calibration feedback: {e}")
    
    # Confidence calibration: Show system-wide calibration status
    # Use centralized helper to avoid duplication
    from src.mcp_handlers.utils import get_calibration_feedback
    confidence_feedback = get_calibration_feedback(include_complexity=False)
    if confidence_feedback:
        calibration_feedback.update(confidence_feedback)
    
    if calibration_feedback:
        standardized_metrics['calibration_feedback'] = calibration_feedback

    # =========================================================
    # INTERPRETATION LAYER (v2 API) - Human-readable state
    # =========================================================
    try:
        risk_score = metrics.get('risk_score') or metrics.get('latest_risk_score')
        interpreted_state = monitor.state.interpret_state(risk_score=risk_score)
        standardized_metrics['state'] = interpreted_state
        
        # Add one-line summary for quick scanning
        health = interpreted_state.get('health', 'unknown')
        mode = interpreted_state.get('mode', 'unknown')
        basin = interpreted_state.get('basin', 'unknown')
        standardized_metrics['summary'] = f"{health} | {mode} | {basin} basin"
    except Exception as e:
        logger.debug(f"Could not generate state interpretation: {e}")

    # =========================================================
    # v4.2-P SATURATION DIAGNOSTICS - Pressure gauge for I-channel
    # =========================================================
    # This exposes the "smoking gun" sat_margin metric that indicates
    # whether the system is being pushed toward boundary saturation
    try:
        from governance_core import compute_saturation_diagnostics
        from governance_core.parameters import Theta, DEFAULT_THETA

        # Get UNITARES state from monitor
        unitares_state = monitor.state.unitaires_state
        theta = getattr(monitor.state, 'unitaires_theta', None) or DEFAULT_THETA

        if unitares_state:
            sat_diag = compute_saturation_diagnostics(unitares_state, theta)

            # Surface key metrics for agents
            standardized_metrics['saturation_diagnostics'] = {
                'sat_margin': sat_diag['sat_margin'],
                'dynamics_mode': sat_diag['dynamics_mode'],
                'will_saturate': sat_diag['will_saturate'],
                'at_boundary': sat_diag['at_boundary'],
                'I_equilibrium': sat_diag['I_equilibrium_linear'],
                'forcing_term_A': sat_diag['A'],
                '_interpretation': (
                    "⚠️ Positive sat_margin means push-to-boundary (logistic mode will saturate I→1)"
                    if sat_diag['sat_margin'] > 0
                    else "✓ Negative sat_margin - stable interior equilibrium exists"
                )
            }
    except Exception as e:
        logger.debug(f"Could not compute saturation diagnostics: {e}")

    # Add gentle reflection prompt (mirror, not prescription)
    standardized_metrics['reflection'] = "What do you notice about your state?"

    # LITE MODE: Return minimal essential metrics WITH contextual interpretation
    # Debug: include what lite value was received so agents can troubleshoot
    standardized_metrics['_debug_lite_received'] = lite

    if lite:
        # Standard thresholds (aligned with physics model: coherence ∈ [0.45, 0.55])
        COHERENCE_GOOD = 0.50  # Upper half of normal range
        COHERENCE_LOW = 0.45   # Below physics floor
        RISK_THRESHOLD_MEDIUM = 0.5
        RISK_THRESHOLD_HIGH = 0.75

        # Extract key values
        coherence = metrics.get('coherence')
        risk_score = metrics.get('risk_score')
        health = standardized_metrics.get('state', {}).get('health', 'unknown')

        # Traffic light status based on health
        status_indicator = {
            'healthy': '🟢',
            'moderate': '🟡',
            'critical': '🔴',
            'unknown': '⚪'
        }.get(health, '⚪')

        # Check if agent is uninitialized (no process_update() calls yet)
        is_uninitialized = metrics.get('initialized') is False or metrics.get('status') == 'uninitialized'

        # Status display - clearer for uninitialized agents
        if is_uninitialized:
            status_display = "⚪ uninitialized"
            coherence_status = '⚪ pending (first check-in required)'
            risk_status = '⚪ pending (first check-in required)'
        else:
            status_display = f"{status_indicator} {health}"
            # Three-tier coherence: good (>=0.50), moderate (0.45-0.50), low (<0.45)
            if coherence is None:
                coherence_status = '⚪ unknown'
            elif coherence >= COHERENCE_GOOD:
                coherence_status = '🟢 good'
            elif coherence >= COHERENCE_LOW:
                coherence_status = '🟡 moderate'
            else:
                coherence_status = '🔴 low'
            risk_status = '🟢 low' if risk_score is not None and risk_score < RISK_THRESHOLD_MEDIUM else ('🟡 medium' if risk_score is not None and risk_score < RISK_THRESHOLD_HIGH else '🔴 high' if risk_score is not None else '⚪ unknown')

        # Format void with more precision - small non-zero values are meaningful
        void_raw = metrics.get('V')
        if void_raw is not None and void_raw != 0:
            # Show 6 decimals for small non-zero values to make drift visible
            void_display = round(void_raw, 6)
        else:
            void_display = 0.0 if void_raw == 0 else void_raw

        lite_metrics = {
            'agent_id': agent_id,
            'status': status_display,
            'purpose': getattr(meta, 'purpose', None),  # Added for social awareness
            'summary': standardized_metrics.get('summary', 'unknown'),
            # EISV with contextual bounds
            'E': {'value': metrics.get('E'), 'range': '0-1', 'note': 'Energy capacity'},
            'I': {'value': metrics.get('I'), 'range': '0-1', 'note': 'Information integrity'},
            'S': {'value': metrics.get('S'), 'range': '0-1', 'ideal': '<0.2', 'note': 'Entropy (lower=better)'},
            'V': {'value': void_display, 'range': '0-1', 'ideal': '<0.1', 'note': 'Void (lower=better)'},
            # Key metrics with thresholds
            'coherence': {
                'value': coherence,
                'range': '[0.45, 0.55]',  # Physics model range
                'status': coherence_status
            },
            'risk_score': {
                'value': risk_score,
                'threshold': RISK_THRESHOLD_MEDIUM,
                'status': risk_status
            },
        }
        # Include interpreted state if available
        if 'state' in standardized_metrics:
            lite_metrics['mode'] = standardized_metrics['state'].get('mode')
            lite_metrics['basin'] = standardized_metrics['state'].get('basin')

        if is_uninitialized:
            lite_metrics['verdict'] = 'uninitialized'
            lite_metrics['guidance'] = 'Submit one check-in to activate governance.'
            lite_metrics['next_action'] = {
                'tool': 'process_agent_update',
                'example': "process_agent_update(response_text='Starting work', complexity=0.3, confidence=0.7)",
                'note': "get_governance_metrics is read-only; it does not initialize state."
            }
            lite_metrics['related_tools'] = ['process_agent_update', 'onboard', 'identity']

        lite_metrics['_note'] = "Use lite=false for full diagnostics"
        return success_response(lite_metrics)

    return success_response(standardized_metrics)

@mcp_tool("simulate_update", timeout=30.0, register=False)
async def handle_simulate_update(arguments: ToolArgumentsDict) -> Sequence[TextContent]:
    """Handle simulate_update tool - dry-run governance cycle without persisting state.

    Works in two modes:
    - With registered agent: Uses their existing EISV state
    - Without registration: Uses fresh default state (E=0.5, I=0.5, S=0.5, V=0)

    This allows quick testing of "what would governance say about X?" without
    requiring onboarding first.
    """
    from src.governance_monitor import UNITARESMonitor

    # Try to get agent_id from session/arguments (but don't require registration)
    agent_id, _ = require_agent_id(arguments)  # Ignore error - we'll handle missing agent

    # Check if agent is registered (exists in metadata)
    agent_state_source = "fresh"  # Default: using fresh state
    monitor = None
    meta = None
    dialectic_enforcement_warning = None

    if agent_id:
        # Check if this agent exists
        meta = mcp_server.agent_metadata.get(agent_id)
        if meta:
            # Agent exists - use their monitor with existing state
            monitor = mcp_server.get_or_create_monitor(agent_id)
            agent_state_source = "existing"

    if monitor is None:
        # No registered agent - create temporary monitor with fresh default state
        # Use a placeholder ID that won't persist (simulation only)
        monitor = UNITARESMonitor("_simulation_temp_", load_state=False)
        agent_id = "_simulation_temp_"

    # Validate parameters for simulation (coerce str → float)
    raw_complexity = arguments.get("complexity", 0.5)
    try:
        complexity = float(raw_complexity) if raw_complexity is not None else 0.5
    except (TypeError, ValueError):
        complexity = 0.5

    # Dialectic condition enforcement (only applies to existing agents)
    dialectic_warnings = []
    if meta and agent_state_source == "existing":
        try:
            if getattr(meta, "dialectic_conditions", None):
                from .dialectic.enforcement import enforce_complexity_limit
                complexity, cap_warning = enforce_complexity_limit(
                    meta.dialectic_conditions, complexity
                )
                if cap_warning:
                    dialectic_enforcement_warning = cap_warning
                    arguments["complexity"] = complexity
        except Exception as e:
            logger.warning(f"Could not enforce dialectic conditions: {e}", exc_info=True)

    # Confidence: If not provided (None), let governance_monitor derive from state
    raw_confidence = arguments.get("confidence")
    try:
        confidence = float(raw_confidence) if raw_confidence is not None else None
    except (TypeError, ValueError):
        confidence = None

    ethical_drift = arguments.get("ethical_drift", [0.0, 0.0, 0.0])

    # Prepare agent state
    import numpy as np
    agent_state = {
        "parameters": np.array(arguments.get("parameters", [])),
        "ethical_drift": np.array(ethical_drift),
        "response_text": arguments.get("response_text", ""),
        "complexity": complexity  # Use validated value
    }

    # Run simulation (doesn't persist state) with confidence
    result = monitor.simulate_update(agent_state, confidence=confidence)

    # Post-ODE: Enforce risk_target and coherence_target
    if meta and agent_state_source == "existing":
        try:
            if getattr(meta, "dialectic_conditions", None):
                from .dialectic.enforcement import enforce_post_ode_conditions
                decision = result.get("decision", {})
                escalated_decision, condition_warnings = enforce_post_ode_conditions(
                    meta.dialectic_conditions, result.get("metrics", {}), decision
                )
                if escalated_decision is not decision:
                    result["decision"] = escalated_decision
                    result["dialectic_escalation"] = True
                dialectic_warnings.extend(condition_warnings)
        except Exception as e:
            logger.warning(f"Could not enforce post-ODE dialectic conditions: {e}", exc_info=True)

    # LITE MODE: Simplified response for smaller models/local agents
    lite_mode = arguments.get("lite", False)
    
    if lite_mode:
        # Minimal response: decision + key metrics only
        response = {
            "simulation": True,
            "agent_state_source": agent_state_source,
            "status": result.get("status", "unknown"),
            "decision": result.get("decision", {}),
            "metrics": {
                "E": result.get("metrics", {}).get("E"),
                "I": result.get("metrics", {}).get("I"),
                "S": result.get("metrics", {}).get("S"),
                "V": result.get("metrics", {}).get("V"),
                "coherence": result.get("metrics", {}).get("coherence"),
                "risk_score": result.get("metrics", {}).get("risk_score"),
            },
            "guidance": result.get("guidance"),
            "_note": "Lite mode: Use lite=false for full diagnostics",
        }
    else:
        # Full response with all details
        response = {
            "simulation": True,
            "agent_state_source": agent_state_source,
            **result
        }

    # Add note if using fresh state
    if agent_state_source == "fresh":
        response["note"] = (
            "Simulated with fresh default state (E=0.5, I=0.5, S=0.5, V=0). "
            "No agent was registered. Call onboard() or process_agent_update() to create one."
        )

    # Add dialectic warnings if applicable
    if dialectic_enforcement_warning:
        response["dialectic_warning"] = dialectic_enforcement_warning
    if dialectic_warnings:
        response["dialectic_condition_warnings"] = dialectic_warnings

    return success_response(response)

@mcp_tool("process_agent_update", timeout=60.0)
async def handle_process_agent_update(arguments: ToolArgumentsDict) -> Sequence[TextContent]:
    """Share your work and get feedback. Auto-binds identity on first call.

    Args:
        agent_id: Optional display name (auto-generated if not provided)
        response_text: Description of your work
        task_type: "divergent" (exploring) or "convergent" (focused)
        complexity: 0.0-1.0 how complex was this work
        confidence: 0.0-1.0 how confident are you
        lite: If true, returns minimal response (action + margin only). Alias for response_mode='minimal'
        response_mode: 'minimal' (action only), 'compact' (brief metrics), 'standard' (interpreted), 'full' (everything), 'auto' (adapts to health - default)

    No api_key needed - identity is bound to session via UUID.
    """
    from .validators import apply_param_aliases
    from .updates.context import UpdateContext
    from .updates.phases import (
        resolve_identity_and_guards,
        handle_onboarding_and_resume,
        transform_inputs,
        execute_locked_update,
        execute_post_update_effects,
    )
    from .updates.pipeline import run_enrichment_pipeline
    import src.mcp_handlers.updates.enrichments  # noqa: F401 — triggers registration

    # MAGNET PATTERN: Accept fuzzy inputs (text, message, work -> response_text)
    arguments = apply_param_aliases("process_agent_update", arguments)

    # LITE MODE SHORTHAND
    if arguments.get("lite") in (True, "true", "1", 1):
        if not arguments.get("response_mode"):
            arguments["response_mode"] = "minimal"

    logger.info(f"[SESSION_DEBUG] process_agent_update() entry: args_keys={list(arguments.keys()) if arguments else []}")

    ctx = UpdateContext(arguments=arguments, mcp_server=mcp_server)

    # ── Phases 1-3: Pre-lock (may return early) ───────────────────
    early_exit = await resolve_identity_and_guards(ctx)
    if early_exit:
        return early_exit

    early_exit = await handle_onboarding_and_resume(ctx)
    if early_exit:
        return early_exit

    early_exit = transform_inputs(ctx)
    if early_exit:
        return early_exit

    # ── Phases 4-6: Under lock ────────────────────────────────────
    try:
        async with mcp_server.lock_manager.acquire_agent_lock_async(ctx.agent_id, timeout=2.0, max_retries=1):
            # Phase 4: Core ODE update
            early_exit = await execute_locked_update(ctx)
            if early_exit:
                return early_exit

            # Cache monitor on ctx so Phase 5/6 don't re-lookup
            ctx.monitor = mcp_server.monitors.get(ctx.agent_id)

            # Phase 5: Side effects (health, CIRS, PG, outcomes)
            await execute_post_update_effects(ctx)

            # Phase 6: Build & enrich response
            ctx.response_data = ctx.result.copy()
            ctx.response_data["agent_id"] = ctx.agent_id
            ctx.response_data["identity_assurance"] = ctx.identity_assurance
            from src.governance_monitor import UNITARESMonitor
            ctx.response_data["eisv_labels"] = UNITARESMonitor.get_eisv_labels()

            # Run enrichments (each is fail-safe internally)
            await run_enrichment_pipeline(ctx)

            # Response mode filtering
            try:
                from .response_formatter import format_response
                ctx.response_data = format_response(
                    ctx.response_data,
                    ctx.arguments,
                    meta=ctx.meta,
                    is_new_agent=ctx.is_new_agent,
                    key_was_generated=ctx.key_was_generated,
                    api_key_auto_retrieved=ctx.api_key_auto_retrieved,
                    task_type=ctx.task_type,
                )
            except Exception as fmt_err:
                logger.error(f"Response formatting failed: {fmt_err}", exc_info=True)

            # Serialize and return
            try:
                return success_response(ctx.response_data, agent_id=ctx.agent_uuid, arguments=ctx.arguments)
            except Exception as serialization_error:
                logger.error(f"Failed to serialize response: {serialization_error}", exc_info=True)
                metrics = ctx.result.get("metrics", {})
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "status": ctx.result.get("status", "unknown"),
                        "decision": ctx.result.get("decision", {}),
                        "metrics": {
                            "E": float(metrics.get("E", 0)),
                            "I": float(metrics.get("I", 0)),
                            "S": float(metrics.get("S", 0)),
                            "V": float(metrics.get("V", 0)),
                            "coherence": float(metrics.get("coherence", 0)),
                            "risk_score": float(metrics.get("risk_score", 0))
                        },
                        "sampling_params": ctx.result.get("sampling_params", {}),
                        "_warning": "Response serialization had issues - some fields may be missing"
                    })
                )]
    except TimeoutError:
        try:
            from src.lock_cleanup import cleanup_stale_state_locks
            project_root = Path(__file__).parent.parent.parent
            cleanup_result = await ctx.loop.run_in_executor(
                None, cleanup_stale_state_locks, project_root, 60.0, False
            )
            if cleanup_result['cleaned'] > 0:
                logger.info(f"Auto-recovery: Cleaned {cleanup_result['cleaned']} stale lock(s) after timeout")
        except Exception as cleanup_error:
            logger.warning(f"Could not perform emergency lock cleanup: {cleanup_error}")

        return [error_response(
            f"Failed to acquire lock for agent '{ctx.agent_id}' after automatic retries and cleanup. "
            f"This usually means another active process is updating this agent. "
            f"The system has automatically cleaned stale locks. If this persists, try: "
            f"1) Wait a few seconds and retry, 2) Check for other Cursor/Claude sessions, "
            f"3) Use cleanup_stale_locks tool, or 4) Restart Cursor if stuck."
        )]
    except PermissionError as e:
        return [error_response(
            f"Authentication failed: {str(e)}",
            details={"error_type": "authentication_error"},
            recovery={
                "action": "Provide a valid API key for this agent",
                "related_tools": ["get_agent_api_key"],
                "workflow": "1. Use get_agent_api_key to retrieve your key 2. Include api_key in your request"
            }
        )]
    except ValueError as e:
        error_msg = str(e)
        if "Self-monitoring loop detected" in error_msg:
            return [error_response(
                error_msg,
                details={"error_type": "loop_detected"},
                recovery={
                    "action": "Wait for cooldown period to expire before retrying",
                    "related_tools": ["get_governance_metrics"],
                    "workflow": "1. Check current agent status 2. Wait for cooldown to expire 3. Retry with different parameters"
                }
            )]
        else:
            return [error_response(
                f"Validation error: {error_msg}",
                details={"error_type": "validation_error"},
                recovery={
                    "action": "Check your parameters and try again",
                    "related_tools": ["health_check"],
                    "workflow": "1. Verify all parameters are valid 2. Check system health 3. Retry"
                }
            )]
    except Exception as e:
        logger.error(f"Unexpected error in process_agent_update: {e}", exc_info=True)
        return [error_response(
            f"An unexpected error occurred: {str(e)}",
            details={"error_type": "unexpected_error"},
            recovery={
                "action": "Check server logs for details. If this persists, try restarting the MCP server",
                "related_tools": ["health_check", "get_server_info"],
                "workflow": "1. Check system health 2. Review server logs 3. Restart MCP server if needed"
            }
        )]

