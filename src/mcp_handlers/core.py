"""
Core governance tool handlers.

EISV Completeness: Utilities available in src/eisv_format.py and src/eisv_validator.py
to ensure all metrics (E, I, S, V) are reported together, preventing selection bias.
See docs/guides/EISV_COMPLETENESS.md for usage.
"""

from typing import Dict, Any, Optional, Sequence
from mcp.types import TextContent
import json
import sys
import asyncio
import hashlib
from .utils import success_response, error_response, require_agent_id, require_registered_agent, _make_json_serializable
from .decorators import mcp_tool
from .validators import validate_complexity, validate_confidence, validate_ethical_drift, validate_response_text
from src.logging_utils import get_logger
from src.db import get_db

logger = get_logger(__name__)

# EISV validation utilities (enforce completeness to prevent selection bias)
try:
    from src.eisv_validator import validate_governance_response
    EISV_VALIDATION_AVAILABLE = True
except ImportError:
    EISV_VALIDATION_AVAILABLE = False
    logger.warning("EISV validation not available - install eisv_validator.py")

from pathlib import Path

# Get mcp_server_std module (using shared utility)
from .shared import get_mcp_server
mcp_server = get_mcp_server()

from src.governance_monitor import UNITARESMonitor
from datetime import datetime


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
    """Get current governance state and metrics for an agent without updating state"""
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]  # Wrap in list for Sequence[TextContent]

    # STRICT MODE: Require agent to exist (no auto-creation)
    # Check if agent exists in metadata before creating monitor
    from src.mcp_server_std import agent_metadata
    if agent_id not in agent_metadata:
        return [error_response(
            f"Agent '{agent_id}' not found",
            details={
                "error_type": "agent_not_found",
                "agent_id": agent_id,
                "note": "Agent must be registered before querying metrics"
            },
            recovery={
                "action": "Register agent first using process_agent_update",
                "workflow": [
                    "1. Create agent with process_agent_update (logs first activity)",
                    "2. Then query metrics with get_governance_metrics",
                    "3. Or use get_agent_api_key to explicitly register"
                ]
            }
        )]

    # Load monitor state from disk if not in memory (allows querying agents without recent updates)
    monitor = mcp_server.get_or_create_monitor(agent_id)

    # Reduce context bloat by excluding nested state dict (all values still at top level)
    include_state = arguments.get("include_state", False)
    metrics = monitor.get_metrics(include_state=include_state)

    # Add EISV labels for API documentation
    metrics['eisv_labels'] = UNITARESMonitor.get_eisv_labels()
    
    # Standardize metrics reporting with agent_id and context
    from src.mcp_handlers.utils import format_metrics_report
    standardized_metrics = format_metrics_report(
        metrics=metrics,
        agent_id=agent_id,
        include_timestamp=True,
        include_context=True
    )
    
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

    return success_response(standardized_metrics)


@mcp_tool("simulate_update", timeout=30.0)
async def handle_simulate_update(arguments: ToolArgumentsDict) -> Sequence[TextContent]:
    """Handle simulate_update tool - dry-run governance cycle without persisting state"""
    # SECURITY FIX: Require registered agent (prevents phantom agent_ids)
    # simulate_update claims not to persist state, but get_or_create_monitor() calls
    # get_or_create_metadata() which does create persistent metadata entries.
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]  # Wrap in list for Sequence[TextContent]
    
    # Get monitor for existing agent
    monitor = mcp_server.get_or_create_monitor(agent_id)
    
    # Validate parameters for simulation
    reported_complexity = arguments.get("complexity", 0.5)
    complexity, error = validate_complexity(reported_complexity)
    if error:
        return [error]
    complexity = complexity or 0.5  # Default if None
    
    # Dialectic condition enforcement (MVP):
    # If the agent has an active dialectic-imposed complexity cap, enforce it here.
    dialectic_enforcement_warning = None
    try:
        if meta and getattr(meta, "dialectic_conditions", None):
            caps = []
            for c in meta.dialectic_conditions:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                if ctype == "complexity_limit":
                    v = c.get("value")
                    if isinstance(v, (int, float)):
                        caps.append(float(v))
                # Accept reduce/set adjustments as an implicit cap target_value
                if ctype == "complexity_adjustment" and c.get("action") == "reduce":
                    v = c.get("target_value")
                    if isinstance(v, (int, float)):
                        caps.append(float(v))
            # Only enforce sane caps in [0,1]
            caps = [v for v in caps if 0.0 <= v <= 1.0]
            if caps:
                cap = min(caps)
                if complexity > cap:
                    dialectic_enforcement_warning = (
                        f"Dialectic condition enforced: complexity {complexity:.2f} capped to {cap:.2f}. "
                        f"(Agent has active dialectic_conditions complexity cap.)"
                    )
                    complexity = cap
                    arguments["complexity"] = cap
    except Exception as e:
        # Don't fail updates if condition parsing fails; treat as non-blocking.
        logger.warning(f"Could not enforce dialectic conditions for '{agent_id}': {e}", exc_info=True)
    
    # Confidence: If not provided (None), let governance_monitor derive from state
    reported_confidence = arguments.get("confidence")
    confidence = None  # Default: derive from thermodynamic state
    if reported_confidence is not None:
        confidence, error = validate_confidence(reported_confidence)
        if error:
            return [error]
        # confidence stays as validated value
    
    ethical_drift_raw = arguments.get("ethical_drift", [0.0, 0.0, 0.0])
    ethical_drift, error = validate_ethical_drift(ethical_drift_raw)
    if error:
        return [error]
    ethical_drift = ethical_drift or [0.0, 0.0, 0.0]  # Default if None
    
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
    
    return success_response({
        "simulation": True,
        **result
    })


@mcp_tool("process_agent_update", timeout=60.0)
async def handle_process_agent_update(arguments: ToolArgumentsDict) -> Sequence[TextContent]:
    """Handle process_agent_update tool - complex handler with authentication and state management
    
    Share your work and get supportive feedback. This is your companion tool for checking in 
    and understanding your state. Includes automatic timeout protection (60s default).
    """
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]  # Wrap in list for Sequence[TextContent]

    # Load metadata if needed (non-blocking)
    loop = asyncio.get_running_loop()  # Use get_running_loop() instead of deprecated get_event_loop()
    await loop.run_in_executor(None, mcp_server.load_metadata)
    
    # Authenticate agent ownership (prevents impersonation)
    # For new agents, allow creation without key (will generate one)
    # For existing agents, require API key
    is_new_agent = agent_id not in mcp_server.agent_metadata
    key_was_generated = False
    
    # ONBOARDING GUIDANCE - Re-enabled (knowledge graph now non-blocking)
    onboarding_guidance = None
    open_questions = []
    # Dialectic enforcement warning (populated if we cap complexity based on dialectic conditions)
    # Must be defined for all code paths (avoid NameError in policy warnings section).
    dialectic_enforcement_warning = None
    if is_new_agent:
        try:
            from src.knowledge_graph import get_knowledge_graph
            graph = await get_knowledge_graph()
            stats = await graph.get_stats()
            
            # Surface open questions for new agents - invite them to participate
            # Reduced to 1-2 questions to minimize context bloat
            try:
                questions = await graph.query(
                    type="question",
                    status="open",
                    limit=3  # Reduced from 5 to minimize context
                )
                # Sort by recency (newest first) and take top 1-2 (reduced from 3)
                questions.sort(key=lambda q: q.timestamp, reverse=True)
                # Limit to 2 questions max, and simplify structure to reduce size
                open_questions = []
                for q in questions[:2]:  # Reduced from 3 to 2
                    q_dict = q.to_dict(include_details=False)
                    # Further reduce size: only include essential fields for onboarding
                    simplified = {
                        "id": q_dict["id"],
                        "summary": q_dict["summary"][:200] if len(q_dict.get("summary", "")) > 200 else q_dict.get("summary", ""),  # Truncate long summaries
                        "tags": q_dict.get("tags", [])[:3] if q_dict.get("tags") else [],  # Limit to 3 tags
                        "severity": q_dict.get("severity")
                    }
                    open_questions.append(simplified)
                logger.debug(f"Found {len(open_questions)} open questions for onboarding")
            except Exception as e:
                logger.warning(f"Could not fetch open questions for onboarding: {e}", exc_info=True)
                open_questions = []  # Ensure it's set even on error
            
            if stats.get("total_discoveries", 0) > 0:
                question_count = stats.get("by_type", {}).get("question", 0)
                onboarding_guidance = {
                    "message": f"Welcome! The knowledge graph contains {stats['total_discoveries']} discoveries from {stats['total_agents']} agents.",
                    "suggestion": "Use search_knowledge_graph to find relevant discoveries by tags or type.",
                    "example_tags": list(stats.get("by_type", {}).keys())[:5] if stats.get("by_type") else []
                }
                
                # Add question invitation if there are open questions
                if open_questions:
                    onboarding_guidance["open_questions"] = {
                        "message": f"Found {len(open_questions)} open question(s) waiting for answers. Want to try responding to one?",
                        "questions": open_questions,
                        "invitation": "Use reply_to_question tool to answer any of these questions and help build shared knowledge.",
                        "tool": "reply_to_question"
                    }
                elif question_count > 0:
                    onboarding_guidance["open_questions"] = {
                        "message": f"There are {question_count} open question(s) in the knowledge graph.",
                        "suggestion": "Use search_knowledge_graph with discovery_type='question' and status='open' to find them.",
                        "tool": "reply_to_question"
                    }
        except Exception as e:
            logger.warning(f"Could not check knowledge graph for onboarding: {e}")
    
    # Get or ensure API key exists
    api_key = arguments.get("api_key")
    api_key_auto_retrieved = False
    # SESSION-BOUND API KEY RETRIEVAL:
    # If the caller previously did bind_identity(agent_id, api_key), allow omitting api_key here.
    # This is especially important for MCP clients where passing api_key repeatedly is friction.
    if not api_key:
        try:
            from .identity import get_bound_agent_id, get_bound_api_key
            bound_id = get_bound_agent_id(arguments=arguments)
            if bound_id == agent_id:
                bound_key = get_bound_api_key(arguments=arguments)
                if bound_key:
                    api_key = bound_key
                    arguments["api_key"] = api_key  # Inject for auth check
                    api_key_auto_retrieved = True
                    logger.debug(f"Auto-retrieved API key from session-bound identity for agent '{agent_id}'")
        except Exception:
            # Identity binding is optional; never fail updates due to identity lookup issues.
            pass
    if not is_new_agent:
        # AUTO API KEY RETRIEVAL: If agent has stored key and none provided, use it
        # This must happen BEFORE require_agent_auth to avoid false rejections
        meta = mcp_server.agent_metadata[agent_id]
        if not api_key and meta.api_key:
            api_key = meta.api_key
            arguments["api_key"] = api_key  # Inject for auth check
            api_key_auto_retrieved = True
            logger.debug(f"Auto-retrieved API key for agent '{agent_id}'")
        
        # Existing agent - require authentication (run in executor to avoid blocking)
        # Reuse loop from line 187 (avoid redundant get_running_loop() call)
        auth_valid, auth_error = await loop.run_in_executor(
            None, 
            mcp_server.require_agent_auth, 
            agent_id, 
            arguments, 
            False  # enforce=False
        )
        if not auth_valid:
            return [auth_error] if auth_error else [error_response("Authentication failed")]
        # Lazy migration: if agent has no key, generate one on first update
        # Note: agent_metadata dict access is fast (no I/O), but generate_api_key might block
        if meta.api_key is None:
            meta.api_key = await loop.run_in_executor(None, mcp_server.generate_api_key)
            key_was_generated = True
            logger.info(f"Generated API key for existing agent '{agent_id}' (migration)")
            api_key = meta.api_key
    else:
        # New agent - will generate key in get_or_create_metadata
        pass
    
    # Check agent status - auto-resume archived agents on engagement
    # (metadata already loaded above at line 185)
    # Get metadata once for reuse throughout function
    meta = mcp_server.agent_metadata.get(agent_id) if agent_id in mcp_server.agent_metadata else None
    
    # Track auto-resume for inclusion in response
    auto_resume_info = None
    
    if meta:
        if meta.status == "archived":
            # Auto-resume: Any engagement resumes archived agents
            previous_archived_at = meta.archived_at
            
            # Calculate days since archive for context
            days_since_archive = None
            if previous_archived_at:
                try:
                    archived_dt = datetime.fromisoformat(previous_archived_at.replace('Z', '+00:00') if 'Z' in previous_archived_at else previous_archived_at)
                    days_since_archive = (datetime.now(archived_dt.tzinfo) - archived_dt).total_seconds() / 86400 if archived_dt.tzinfo else (datetime.now() - archived_dt.replace(tzinfo=None)).total_seconds() / 86400
                except (ValueError, TypeError, AttributeError):
                    pass
            
            meta.status = "active"
            meta.archived_at = None
            meta.add_lifecycle_event("resumed", "Auto-resumed on engagement")
            
            # Audit log the auto-resume event (Priority 1)
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
                # Don't fail auto-resume if audit logging fails
                logger.warning(f"Could not log auto-resume audit event: {e}", exc_info=True)
            
            # Save metadata using async batched save instead of deprecated save_metadata()
            await mcp_server.schedule_metadata_save(force=False)
            
            # Store auto-resume info for inclusion in response (Priority 2)
            auto_resume_info = {
                "auto_resumed": True,
                "message": f"Agent '{agent_id}' was automatically resumed from archived status.",
                "previous_status": "archived",
                "days_since_archive": round(days_since_archive, 2) if days_since_archive is not None else None,
                "note": "Archived agents automatically resume when they engage with the system."
            }
            # Continue with normal processing - we'll include this in the response
        elif meta.status == "paused":
            # Paused agents still need explicit resume (Priority 2: Improved error message)
            return [error_response(
                f"Agent '{agent_id}' is paused. Resume it first before processing updates.",
                recovery={
                    "action": "Use recovery tools to resume the agent",
                    "related_tools": ["direct_resume_if_safe", "request_dialectic_review", "get_governance_metrics"],
                    "workflow": (
                        "1. Check agent metrics with get_governance_metrics "
                        "2. Use direct_resume_if_safe if state is safe (coherence > 0.40, risk_score < 0.60) "
                        "3. Use request_dialectic_review for complex recovery "
                        "(set auto_progress=true to streamline; set reviewer_mode='self' if no peers available)"
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

    # VALIDATION: Validate ALL parameters BEFORE acquiring lock (fail fast)
    # This prevents holding the lock while validation fails

    # Validate response_text (SECURITY: prevent ReDoS, memory exhaustion)
    response_text_raw = arguments.get("response_text", "")
    response_text, error = validate_response_text(response_text_raw, max_length=50000)
    if error:
        return [error]

    # Validate complexity and confidence parameters
    reported_complexity = arguments.get("complexity", 0.5)
    reported_confidence = arguments.get("confidence")  # None if not provided (triggers thermodynamic derivation)

    complexity, error = validate_complexity(reported_complexity)
    if error:
        return [error]
    complexity = complexity or 0.5  # Default if None

    # Confidence: If not provided (None), let governance_monitor derive from state
    # This addresses calibration overconfidence issue (was hardcoded 1.0)
    confidence = None  # Default: derive from thermodynamic state
    calibration_correction_info = None  # Track any correction applied
    if reported_confidence is not None:
        confidence, error = validate_confidence(reported_confidence)
        if error:
            return [error]
        # confidence stays as validated value (agent explicitly provided it)

        # AUTO-CALIBRATION: Apply correction based on historical accuracy
        # If agents consistently overestimate confidence, this adjusts their
        # reported values to match observed accuracy (closes the learning loop)
        try:
            from src.calibration import calibration_checker
            corrected, correction_info = calibration_checker.apply_confidence_correction(confidence)
            if correction_info:
                calibration_correction_info = correction_info
                logger.info(f"Agent {agent_id}: {correction_info}")
            confidence = corrected
        except Exception as e:
            # Calibration correction is optional - don't fail on errors
            logger.debug(f"Calibration correction skipped: {e}")

    # Validate ethical_drift parameter (MOVED BEFORE LOCK)
    ethical_drift_raw = arguments.get("ethical_drift", [0.0, 0.0, 0.0])
    ethical_drift, error = validate_ethical_drift(ethical_drift_raw)
    if error:
        return [error]
    ethical_drift = ethical_drift or [0.0, 0.0, 0.0]  # Default if None

    # Validate task_type parameter (MOVED BEFORE LOCK)
    from .validators import validate_task_type
    task_type = arguments.get("task_type", "mixed")
    validated_task_type, error = validate_task_type(task_type)
    if error:
        # Invalid task_type - default to mixed and log warning (don't fail, just warn)
        logger.warning(f"Invalid task_type '{task_type}' for agent '{agent_id}', defaulting to 'mixed'")
        task_type = "mixed"
    else:
        task_type = validated_task_type

    # Note: Complexity derivation happens in estimate_risk() via GovernanceConfig.derive_complexity()
    # which analyzes response_text content, coherence trends, and validates against self-reported values.
    # The reported complexity here is validated/clamped, but final complexity is derived from behavior.

    # Note: Zombie cleanup disabled - adds latency, not critical per-request
    # Cleanup happens in background tasks instead

    # Acquire lock for agent state update (prevents race conditions)
    # Use async lock to avoid blocking event loop (fixes Claude Desktop hangs)
    # IMPORTANT: All validation now happens BEFORE lock acquisition (fail fast optimization)
    try:
        async with mcp_server.lock_manager.acquire_agent_lock_async(agent_id, timeout=2.0, max_retries=1):
            # Prepare agent state (use validated parameters from above)
            import numpy as np
            
            agent_state = {
                "parameters": np.array(arguments.get("parameters", [])),
                "ethical_drift": np.array(ethical_drift),
                "response_text": response_text,  # Use validated text
                "complexity": complexity  # Use validated value
                # Note: No outcome parameters here. The system observes outcomes
                # directly from tool_usage_tracker - no self-reports needed.
            }

            # Check for anti-proliferation and anti-avoidance policies (warn, don't block)
            from .validators import (
                validate_file_path_policy,
                validate_agent_id_policy,
                detect_script_creation_avoidance
            )
            import re
            policy_warnings = []
            response_text = agent_state["response_text"]

            # 0. Add dialectic enforcement warning (if any)
            if dialectic_enforcement_warning:
                policy_warnings.append(dialectic_enforcement_warning)

            # 1. Validate agent_id (discourage test/demo agents)
            agent_id_warning, _ = validate_agent_id_policy(agent_id)
            if agent_id_warning:
                policy_warnings.append(agent_id_warning)

            # 2. Detect script creation avoidance (agents creating scripts instead of using tools)
            avoidance_warnings = detect_script_creation_avoidance(response_text)
            if avoidance_warnings:
                policy_warnings.extend(avoidance_warnings)

            # 3. Scan response_text for file paths that might violate policy
            # Look for patterns like: test_*.py, demo_*.py, creating test files, etc.
            file_patterns = re.findall(r'(?:test_|demo_)\w+\.py', response_text)
            for file_pattern in file_patterns:
                warning, _ = validate_file_path_policy(file_pattern)
                if warning:
                    policy_warnings.append(warning)

            # 4. Check for explicit mentions of creating test files in root
            if re.search(r'(?:creat|writ|generat)(?:e|ing|ed).*(?:test_|demo_)\w+\.py', response_text, re.IGNORECASE):
                # Check if it mentions putting it in tests/ directory
                if not re.search(r'tests?/', response_text, re.IGNORECASE):
                    policy_warnings.append(
                        "⚠️ POLICY REMINDER: Creating test scripts? They belong in tests/ directory.\n"
                        "See AI_ASSISTANT_GUIDE.md § Best Practices #6 for details."
                    )

            # Ensure metadata exists (for new agents, this creates it with API key)
            if is_new_agent:
                # Run blocking metadata creation in executor to avoid blocking event loop
                # Reuse loop from line 187 (avoid redundant get_running_loop() call)
                # Check if purpose was passed in arguments
                purpose = arguments.get("purpose")
                if purpose and isinstance(purpose, str) and purpose.strip():
                    # Use lambda to pass keyword argument through executor
                    meta = await loop.run_in_executor(None, lambda: mcp_server.get_or_create_metadata(agent_id, purpose=purpose.strip()))
                else:
                    meta = await loop.run_in_executor(None, mcp_server.get_or_create_metadata, agent_id)
                api_key = meta.api_key  # Get generated key
                # Schedule immediate save for new agent creation (critical operation)
                await mcp_server.schedule_metadata_save(force=True)

                # DUAL-WRITE: Create identity in PostgreSQL (Phase 2 migration)
                try:
                    db = get_db()
                    api_key_hash = hashlib.sha256(meta.api_key.encode()).hexdigest() if meta.api_key else ""
                    
                    # CRITICAL: Create agent in core.agents FIRST, before creating identity
                    # core.identities.agent_id has a foreign key constraint to core.agents(id)
                    if hasattr(db, 'upsert_agent'):
                        # Only for PostgreSQL backend
                        ok = await db.upsert_agent(
                            agent_id=agent_id,
                            api_key=meta.api_key,
                            status=getattr(meta, 'status', 'active'),
                            purpose=getattr(meta, 'purpose', None),
                            notes=getattr(meta, 'notes', None),
                            tags=getattr(meta, 'tags', None),
                            parent_agent_id=getattr(meta, 'parent_agent_id', None),
                            spawn_reason=getattr(meta, 'spawn_reason', None),
                            created_at=datetime.fromisoformat(meta.created_at) if hasattr(meta, 'created_at') and meta.created_at else None,
                        )
                        if not ok:
                            # Don't attempt identity creation if agent row couldn't be created,
                            # otherwise Postgres FK constraint will fail (core.identities.agent_id -> core.agents.id).
                            raise RuntimeError(f"Dual-write failed: could not upsert agent '{agent_id}' in core.agents")
                        logger.debug(f"Dual-write: Created agent in core.agents for {agent_id}")
                    
                    # Now create identity (foreign key constraint satisfied)
                    await db.upsert_identity(
                        agent_id=agent_id,
                        api_key_hash=api_key_hash,
                        metadata={
                            "status": getattr(meta, 'status', 'active'),
                            "created_at": getattr(meta, 'created_at', datetime.now().isoformat()),
                            "source": "process_agent_update"
                        }
                    )
                    logger.debug(f"Dual-write: Created identity in new DB for {agent_id}")
                except Exception as e:
                    # Non-fatal: old DB still works, log and continue
                    logger.warning(f"Dual-write to new DB failed for new agent: {e}", exc_info=True)
            else:
                # Reuse metadata fetched earlier (avoid duplicate lookup)
                if not meta:
                    meta = mcp_server.agent_metadata.get(agent_id)
            
            # Use validated confidence (already clamped to [0, 1] above)
            # Note: task_type already validated before lock acquisition (lines 468-477)
            
            # Use authenticated update function (async version)
            # Wrap in try/except to catch any exceptions from process_update_authenticated_async
            try:
                # Add task_type to agent_state for context-aware interpretation
                agent_state["task_type"] = task_type
                
                result = await mcp_server.process_update_authenticated_async(
                    agent_id=agent_id,
                    api_key=api_key,
                    agent_state=agent_state,
                    auto_save=True,
                    confidence=confidence
                )
            except PermissionError as e:
                # Re-raise PermissionError to be caught by outer handler
                raise
            except ValueError as e:
                # Re-raise ValueError to be caught by outer handler
                raise
            except Exception as e:
                # Catch any other unexpected exceptions from process_update_authenticated_async
                logger.error(f"Unexpected error in process_update_authenticated_async: {e}", exc_info=True)
                raise Exception(f"Error processing update: {str(e)}") from e
            
            # Update heartbeat (run in executor to avoid blocking)
            # Reuse loop from line 187 (avoid redundant get_running_loop() call)
            await loop.run_in_executor(None, mcp_server.process_mgr.write_heartbeat)

            # Calculate health status using risk-based thresholds
            metrics_dict = result.get('metrics', {})
            risk_score = metrics_dict.get('risk_score', None)
            coherence = metrics_dict.get('coherence', None)
            void_active = metrics_dict.get('void_active', False)
            
            health_status, health_message = mcp_server.health_checker.get_health_status(
                risk_score=risk_score,  # health_checker uses risk_score internally
                coherence=coherence,
                void_active=void_active
            )
            
            # Add health status to response
            if 'metrics' not in result:
                result['metrics'] = {}
            result['metrics']['health_status'] = health_status.value
            result['metrics']['health_message'] = health_message
            
            # Cache health status in metadata for list_agents to read without loading monitor
            if meta:
                meta.health_status = health_status.value
                # Schedule save so health_status persists to disk (force=True for immediate save)
                await mcp_server.schedule_metadata_save(force=True)

            # DUAL-WRITE: Persist EISV state to PostgreSQL (Phase 2 migration)
            try:
                db = get_db()
                # Get identity from new DB (may exist from previous dual-write or bind_identity)
                identity = await db.get_identity(agent_id)
                if identity:
                    # Extract EISV metrics from result
                    E_val = metrics_dict.get('E', 0.7)
                    I_val = metrics_dict.get('I', 0.8)
                    S_val = metrics_dict.get('S', 0.1)
                    V_val = metrics_dict.get('V', 0.0)
                    regime_val = metrics_dict.get('regime', 'EXPLORATION')
                    coh_val = metrics_dict.get('coherence', 0.5)

                    # Map regime to allowed values in DB constraint
                    allowed_regimes = {'nominal', 'warning', 'critical', 'recovery',
                                       'EXPLORATION', 'CONVERGENCE', 'DIVERGENCE', 'STABLE'}
                    db_regime = regime_val.upper() if regime_val.upper() in allowed_regimes else 'nominal'

                    await db.record_agent_state(
                        identity_id=identity.identity_id,
                        entropy=S_val,  # S is entropy in EISV
                        integrity=I_val,
                        stability_index=1.0 - S_val if S_val else 1.0,  # Inverse of entropy
                        volatility=V_val,
                        regime=db_regime,
                        coherence=coh_val,
                        state_json={
                            "E": E_val,
                            "risk_score": risk_score,
                            "verdict": metrics_dict.get('verdict', 'continue'),
                            "phi": metrics_dict.get('phi', 0.0),
                            "health_status": health_status.value
                        }
                    )
                    logger.debug(f"Dual-write: Saved agent state to new DB for {agent_id}")
                else:
                    # Identity doesn't exist in new DB yet - create it first
                    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest() if api_key else ""
                    new_identity_id = await db.upsert_identity(
                        agent_id=agent_id,
                        api_key_hash=api_key_hash,
                        metadata={"source": "process_agent_update_state_sync"}
                    )
                    if new_identity_id:
                        E_val = metrics_dict.get('E', 0.7)
                        I_val = metrics_dict.get('I', 0.8)
                        S_val = metrics_dict.get('S', 0.1)
                        V_val = metrics_dict.get('V', 0.0)
                        regime_val = metrics_dict.get('regime', 'EXPLORATION')

                        # Map regime to allowed values
                        allowed_regimes = {'nominal', 'warning', 'critical', 'recovery',
                                           'EXPLORATION', 'CONVERGENCE', 'DIVERGENCE', 'STABLE'}
                        db_regime = regime_val.upper() if regime_val.upper() in allowed_regimes else 'nominal'

                        await db.record_agent_state(
                            identity_id=new_identity_id,
                            entropy=S_val,
                            integrity=I_val,
                            stability_index=1.0 - S_val if S_val else 1.0,
                            volatility=V_val,
                            regime=db_regime,
                            coherence=metrics_dict.get('coherence', 0.5),
                            state_json={
                                "E": E_val,
                                "risk_score": risk_score,
                                "verdict": metrics_dict.get('verdict', 'continue'),
                                "phi": metrics_dict.get('phi', 0.0),
                                "health_status": health_status.value
                            }
                        )
                        logger.debug(f"Dual-write: Created identity and saved state for {agent_id}")
            except Exception as e:
                # Non-fatal: old DB still works, log and continue
                logger.warning(f"Dual-write state to new DB failed: {e}", exc_info=True)

            # Add EISV labels for reflexivity - essential for agents to understand their state
            # Bridges physics (Energy, Entropy, Void Integral) with practical understanding
            result['eisv_labels'] = UNITARESMonitor.get_eisv_labels()
            
            # =========================================================
            # INTERPRETATION LAYER (v2 API) - Human-readable state
            # =========================================================
            # Maps raw EISV to semantic understanding: one glance tells you what's happening
            try:
                task_type = agent_state.get("task_type", "mixed")
                interpreted_state = monitor.state.interpret_state(
                    risk_score=risk_score,
                    task_type=task_type
                )
                result['state'] = interpreted_state
                
                # Add one-line summary at top level for quick scanning
                health = interpreted_state.get('health', 'unknown')
                mode = interpreted_state.get('mode', 'unknown')
                basin = interpreted_state.get('basin', 'unknown')
                result['summary'] = f"{health} | {mode} | {basin} basin"
                
            except Exception as e:
                # Never fail the update due to interpretation layer
                logger.debug(f"Could not generate state interpretation: {e}")
            
            # Generate actionable feedback based on metrics (enhancement)
            actionable_feedback = []
            
            # Get current regime for context-aware feedback (from result metrics)
            current_regime = metrics_dict.get('regime', 'exploration')
            
            if coherence is not None:
                # Regime-aware coherence thresholds:
                # - DIVERGENCE: Low coherence is expected (divergent thinking), only warn if very low
                # - TRANSITION/CONVERGENCE: Standard thresholds apply
                # - STABLE: Coherence should be high, warn on any drop
                if current_regime.lower() == "exploration":
                    if coherence < 0.3:
                        actionable_feedback.append("Your coherence is very low (<0.3) even for exploration - consider establishing some structure")
                    # Skip moderate coherence warnings during exploration - it's expected
                elif current_regime.lower() == "locked":
                    if coherence < 0.7:
                        actionable_feedback.append("Your coherence dropped below 0.7 in STABLE regime - unexpected divergence detected")
                else:
                    # TRANSITION or CONVERGENCE - use standard thresholds
                    if coherence < 0.5:
                        actionable_feedback.append("Your coherence is below 0.5 - consider simplifying your approach or breaking tasks into smaller pieces")
                    elif coherence < 0.6:
                        actionable_feedback.append("Your coherence is moderate - focus on consistency and clear structure")
            
            if risk_score is not None:
                if risk_score > 0.6:
                    actionable_feedback.append("Your risk score is high (>0.6) - you're handling complex work. Take breaks as needed and consider reducing complexity")
                elif risk_score > 0.4:
                    actionable_feedback.append("Your risk score is moderate - you're managing complexity well")
            
            if void_active:
                actionable_feedback.append("Void detected - there's a mismatch between your energy and integrity. Consider slowing down or focusing on consistency")
            
            if actionable_feedback:
                result['actionable_feedback'] = actionable_feedback

            # Add calibration feedback (helps agents understand their confidence/complexity reporting)
            calibration_feedback = {}
            
            # Complexity calibration: Show reported vs derived complexity
            if 'metrics' in result:
                metrics = result['metrics']
                reported_complexity = complexity  # From validated input
                derived_complexity = metrics.get('complexity', None)  # Derived from state
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
            
            # Confidence calibration: Show system-wide calibration status
            # Use centralized helper to avoid duplication
            from src.mcp_handlers.utils import get_calibration_feedback
            confidence_feedback = get_calibration_feedback(include_complexity=False)
            if confidence_feedback:
                calibration_feedback.update(confidence_feedback)

            # AUTO-CALIBRATION: Include correction info if confidence was adjusted
            # This closes the learning loop by showing agents how their confidence was adjusted
            if calibration_correction_info:
                calibration_feedback['auto_correction'] = {
                    'applied': True,
                    'details': calibration_correction_info,
                    'message': "Your reported confidence was adjusted based on historical accuracy. This helps calibrate your estimates automatically."
                }

            if calibration_feedback:
                result['calibration_feedback'] = calibration_feedback

            # Collect any warnings
            warnings = []
            
            # Check for default agent_id warning
            try:
                default_warning = mcp_server.check_agent_id_default(agent_id)
                if default_warning:
                    warnings.append(default_warning)
            except (NameError, AttributeError):
                # Function not available (shouldn't happen, but be defensive)
                pass
            except Exception as e:
                # Log but don't fail the update
                logger.warning(f"Could not check agent_id default: {e}")

            # Build response
            response_data = result.copy()
            
            # STANDARDIZED METRIC REPORTING - Always include agent_id and context
            # Standardize metrics reporting with agent_id and timestamp
            from src.mcp_handlers.utils import format_metrics_report
            
            # Ensure metrics dict exists
            if 'metrics' not in response_data:
                response_data['metrics'] = {}
            
            # Standardize metrics with agent_id and context
            standardized_metrics = format_metrics_report(
                metrics=response_data['metrics'],
                agent_id=agent_id,
                include_timestamp=True,
                include_context=True
            )
            
            # Update response_data with standardized metrics
            response_data['metrics'] = standardized_metrics
            
            # Also include agent_id at top level for easy access (backward compatibility)
            response_data["agent_id"] = agent_id
            
            # Include health_status at top level for easy access (standardized initiation)
            # Health status is already in metrics, but top-level makes it easier to check
            # Always ensure health_status is at top level (standardized initiation)
            if 'metrics' in response_data:
                metrics = response_data['metrics']
                if 'health_status' in metrics:
                    response_data["health_status"] = metrics['health_status']
                    response_data["health_message"] = metrics.get('health_message', '')
                else:
                    # Fallback: use status if health_status not in metrics
                    response_data["health_status"] = response_data.get('status', 'unknown')
                    response_data["health_message"] = ''
            else:
                # Fallback: use status if no metrics
                response_data["health_status"] = response_data.get('status', 'unknown')
                response_data["health_message"] = ''
            
            # Ensure EISV metrics are easily accessible (standardized initiation)
            # EISV metrics are in metrics dict, but ensure they're always present
            if 'metrics' in response_data:
                metrics = response_data['metrics']
                # Ensure E, I, S, V are always present (standardized)
                # If missing, use values from eisv dict, or default to 0.0
                if 'E' not in metrics:
                    metrics['E'] = metrics.get('eisv', {}).get('E', 0.0)
                if 'I' not in metrics:
                    metrics['I'] = metrics.get('eisv', {}).get('I', 0.0)
                if 'S' not in metrics:
                    metrics['S'] = metrics.get('eisv', {}).get('S', 0.0)
                if 'V' not in metrics:
                    metrics['V'] = metrics.get('eisv', {}).get('V', 0.0)
                
                # Ensure eisv dict exists and is consistent with flat values
                if 'eisv' not in metrics:
                    metrics['eisv'] = {
                        'E': metrics.get('E', 0.0),
                        'I': metrics.get('I', 0.0),
                        'S': metrics.get('S', 0.0),
                        'V': metrics.get('V', 0.0)
                    }
                else:
                    # Sync eisv dict with flat values (flat values take precedence)
                    metrics['eisv']['E'] = metrics.get('E', metrics['eisv'].get('E', 0.0))
                    metrics['eisv']['I'] = metrics.get('I', metrics['eisv'].get('I', 0.0))
                    metrics['eisv']['S'] = metrics.get('S', metrics['eisv'].get('S', 0.0))
                    metrics['eisv']['V'] = metrics.get('V', metrics['eisv'].get('V', 0.0))
                
                # Ensure risk metrics are consistent with get_governance_metrics
                # Add missing risk metrics if not present (for consistency)
                # Add current_risk and mean_risk if available from monitor
                # These come from get_metrics() but may not be in process_update result
                if 'current_risk' not in metrics or 'mean_risk' not in metrics:
                    try:
                        monitor = mcp_server.get_or_create_monitor(agent_id)
                        monitor_metrics = monitor.get_metrics()
                        if 'current_risk' not in metrics:
                            metrics['current_risk'] = monitor_metrics.get('current_risk')
                        if 'mean_risk' not in metrics:
                            metrics['mean_risk'] = monitor_metrics.get('mean_risk')
                        if 'latest_risk_score' not in metrics:
                            metrics['latest_risk_score'] = monitor_metrics.get('latest_risk_score')
                    except Exception:
                        pass

            # Add policy warnings to general warnings
            if policy_warnings:
                warnings.extend(policy_warnings)

            if warnings:
                response_data["warning"] = "\n\n".join(warnings)  # Use newlines for readability
            
            # Include auto-resume info if agent was auto-resumed (Priority 2)
            if auto_resume_info:
                response_data["auto_resume"] = auto_resume_info
            
            # Add helpful explanation for sampling_params (helps agents understand what they mean)
            if "sampling_params" in response_data:
                sampling_params = response_data["sampling_params"]
                temp = sampling_params.get("temperature", 0.5)
                max_tokens = sampling_params.get("max_tokens", 100)
                
                # Interpret temperature
                if temp < 0.65:
                    temp_desc = "focused, precise"
                elif temp < 0.9:
                    temp_desc = "balanced approach"
                else:
                    temp_desc = "creative, exploratory"
                
                response_data["sampling_params_note"] = (
                    f"Optional suggestions based on your current state. "
                    f"You can use these for your next generation, or ignore them - they're just recommendations. "
                    f"Temperature {temp:.2f} = {temp_desc}. "
                    f"Max tokens {max_tokens} = suggested response length."
                )

            # Proactive knowledge surfacing - Re-enabled (lightweight, tag-based only)
            # Surface top 3 most relevant discoveries based on agent tags
            # Note: meta already fetched earlier, reuse it (avoid duplicate lookup)
            relevant_discoveries = []
            try:
                agent_tags = meta.tags if meta and meta.tags else []
                
                if agent_tags:
                    from src.knowledge_graph import get_knowledge_graph
                    graph = await get_knowledge_graph()
                    
                    # Query discoveries matching agent tags (open status preferred)
                    tag_matches = await graph.query(
                        tags=agent_tags,
                        status="open",
                        limit=10
                    )
                    
                    # Score by tag overlap (simple relevance)
                    scored = []
                    agent_tags_set = set(agent_tags)
                    for disc in tag_matches:
                        disc_tags_set = set(disc.tags)
                        overlap = len(agent_tags_set & disc_tags_set)
                        if overlap > 0:
                            scored.append((overlap, disc))
                    
                    # Sort by overlap (descending) and take top 3
                    scored.sort(reverse=True, key=lambda x: x[0])
                    relevant_discoveries = [disc.to_dict(include_details=False) for _, disc in scored[:3]]
            except Exception as e:
                # Don't fail if knowledge surfacing fails - this is optional
                logger.debug(f"Could not surface relevant discoveries: {e}")
            
            if relevant_discoveries:
                response_data["relevant_discoveries"] = {
                    "message": f"Found {len(relevant_discoveries)} relevant discovery/discoveries matching your tags",
                    "discoveries": relevant_discoveries
                }
            
            # Include onboarding guidance
            if onboarding_guidance:
                response_data["onboarding"] = onboarding_guidance
            
            # Include API key for new agents, if key was just generated, or if auto-retrieved
            # Note: meta already available from earlier (avoid duplicate lookup)
            # SECURITY FIX (2025-12-14): Never expose full API key in responses
            # This prevents context leakage in multi-agent shared environments
            # See: patches/FIX_API_KEY_CONTEXT_LEAKAGE.md
            if is_new_agent or key_was_generated or api_key_auto_retrieved:
                if not meta:
                    meta = mcp_server.agent_metadata.get(agent_id)
                if meta:
                    # Only show hint (first 8 chars) - agents must use get_agent_api_key to retrieve full key
                    api_key_hint = meta.api_key[:8] + "..." if meta.api_key and len(meta.api_key) > 8 else meta.api_key
                    response_data["api_key_hint"] = api_key_hint
                    response_data["_onboarding"] = {
                        "api_key_hint": api_key_hint,
                        "message": "🔑 API key created (use get_agent_api_key to retrieve full key)",
                        "next_steps": [
                            "Call get_agent_api_key(agent_id) to retrieve your full API key",
                            "Or call bind_identity(agent_id) to bind session without needing key in every call",
                            "After bind_identity, API key auto-retrieved for all tool calls",
                        ],
                        "identity_binding": {
                            "tool": "bind_identity",
                            "benefit": "After binding, you won't need to pass api_key explicitly",
                            "example": f"bind_identity(agent_id='{agent_id}')"
                        },
                        "security_note": "Full API keys are not included in responses to prevent context leakage in multi-agent environments."
                    }
                    # Test harness compatibility: some unit tests expect `api_key` to be present
                    # when an agent is newly registered. Keep production behavior safe by gating
                    # behind pytest or an explicit opt-in env var.
                    import os
                    if os.getenv("UNITARES_INCLUDE_API_KEY_IN_RESPONSES") == "1" or os.getenv("PYTEST_CURRENT_TEST"):
                        response_data["api_key"] = meta.api_key
                if is_new_agent:
                    response_data["api_key_warning"] = "⚠️  Use get_agent_api_key(agent_id) to retrieve your API key. Save it securely."
                elif key_was_generated:
                    response_data["api_key_warning"] = "⚠️  API key regenerated (migration). Use get_agent_api_key(agent_id) to retrieve it."
                elif api_key_auto_retrieved:
                    response_data["api_key_info"] = "ℹ️  Session authenticated via stored credentials. No need to pass api_key."

            # Welcome message for first update (helps new agents understand the system)
            # Note: meta already available from earlier in function (line 292 or 365)
            if meta and meta.total_updates == 1:
                response_data["welcome"] = (
                    "Welcome to the governance system! This is your first update. "
                    "The system tracks your work's thermodynamic state (E, I, S, V) and provides "
                    "supportive feedback. Use the metrics and sampling parameters as helpful guidance, "
                    "not requirements. The knowledge graph contains discoveries from other agents - "
                    "feel free to explore it when relevant. "
                    "\n\n💡 Quick tip: Call bind_identity(agent_id) to avoid passing api_key in every call."
                )
            
            # EQUILIBRIUM-BASED CONVERGENCE ACCELERATION
            # Provide proactive guidance to help agents reach equilibrium (I=1.0, S=0.0) faster
            # Only show for agents with < 20 updates (new agents still converging)
            try:
                # Reload meta to get latest total_updates after the update (it was incremented in process_update_authenticated_async)
                meta = mcp_server.agent_metadata.get(agent_id)
                if meta and meta.total_updates < 20:
                    # Extract metrics from response_data (which comes from result)
                    metrics_dict = response_data.get("metrics", {})
                    E = metrics_dict.get("E", 0.7)
                    I = metrics_dict.get("I", 0.8)
                    S = metrics_dict.get("S", 0.2)
                    V = metrics_dict.get("V", 0.0)
                    
                    # Calculate distance from equilibrium (I=1.0, S=0.0)
                    equilibrium_distance = ((1.0 - I) ** 2 + S ** 2) ** 0.5
                    
                    convergence_guidance = []
                    
                    # High entropy guidance
                    if S > 0.1:
                        convergence_guidance.append({
                            "metric": "S (Entropy)",
                            "current": f"{S:.3f}",
                            "target": "0.0",
                            "guidance": "High entropy detected. Focus on coherent, consistent work to reduce S. "
                                       "Reduce uncertainty by maintaining clear, structured approaches.",
                            "priority": "high" if S > 0.2 else "medium"
                        })
                    
                    # Low integrity guidance
                    if I < 0.9:
                        convergence_guidance.append({
                            "metric": "I (Information Integrity)",
                            "current": f"{I:.3f}",
                            "target": "1.0",
                            "guidance": "Integrity below optimal. Reduce uncertainty, increase coherence. "
                                       "Focus on consistent, well-structured work.",
                            "priority": "high" if I < 0.8 else "medium"
                        })
                    
                    # Low energy guidance
                    if E < 0.7:
                        convergence_guidance.append({
                            "metric": "E (Energy)",
                            "current": f"{E:.3f}",
                            "target": "0.7-1.0",
                            "guidance": "Low energy. Increase exploration and productive capacity. "
                                       "Engage more actively with your work.",
                            "priority": "medium"
                        })
                    
                    # Void guidance (if accumulating imbalance)
                    if abs(V) > 0.1:
                        convergence_guidance.append({
                            "metric": "V (Void Integral)",
                            "current": f"{V:.3f}",
                            "target": "0.0",
                            "guidance": "Energy-integrity imbalance detected. Balance exploration (E) "
                                       "with consistency (I) to reduce void accumulation.",
                            "priority": "medium" if abs(V) > 0.2 else "low"
                        })
                    
                    # Only include if there's actionable guidance
                    if convergence_guidance:
                        response_data["convergence_guidance"] = {
                            "message": f"Equilibrium guidance (distance: {equilibrium_distance:.3f})",
                            "equilibrium_target": {"I": 1.0, "S": 0.0},
                            "current_state": {"E": E, "I": I, "S": S, "V": V},
                            "guidance": convergence_guidance,
                            "note": "These suggestions help you reach equilibrium faster. "
                                   "Mature agents typically converge to I≈1.0, S≈0.0 within 18-24 updates."
                        }
            except Exception as e:
                # Don't fail the update if convergence guidance fails - log and continue
                logger.debug(f"Could not generate convergence guidance: {e}", exc_info=True)

            # Surface v4.1 basin/convergence tracking when available from monitor metrics
            try:
                metrics_dict = response_data.get("metrics", {})
                v41_block = metrics_dict.get("unitares_v41")
                if isinstance(v41_block, dict):
                    response_data["unitares_v41"] = v41_block
            except Exception:
                pass
            
            # Note: Maintenance prompt already in mark_response_complete (no need to duplicate)
            
            # PENDING DIALECTIC NOTIFICATION
            # Check if this agent has pending dialectic sessions where they owe a response
            # This fixes the UX gap where reviewers didn't know they had pending work
            try:
                from .dialectic import ACTIVE_SESSIONS
                from src.dialectic_protocol import DialecticPhase
                pending_dialectic = []
                for session_id, session in ACTIVE_SESSIONS.items():
                    # Check if this agent is the reviewer and session needs antithesis
                    # When phase is ANTITHESIS, reviewer needs to submit antithesis
                    if session.reviewer_agent_id == agent_id and session.phase == DialecticPhase.ANTITHESIS:
                        pending_dialectic.append({
                            "session_id": session_id,
                            "role": "reviewer",
                            "phase": "antithesis",
                            "partner": session.paused_agent_id,
                            "topic": getattr(session, 'topic', None),
                            "action_needed": "Submit antithesis via submit_antithesis()",
                            "created_at": session.created_at.isoformat() if session.created_at else None
                        })
                    # Check if this agent is the paused agent and session needs synthesis
                    # When phase is SYNTHESIS, paused agent needs to submit synthesis
                    elif session.paused_agent_id == agent_id and session.phase == DialecticPhase.SYNTHESIS:
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
                    response_data["pending_dialectic"] = {
                        "message": f"⚠️ You have {len(pending_dialectic)} pending dialectic session(s) awaiting your response!",
                        "sessions": pending_dialectic,
                        "note": "Dialectic sessions enable collaborative exploration and recovery. Respond to keep the conversation going."
                    }
            except Exception as e:
                # Don't fail if dialectic check fails - this is optional notification
                logger.debug(f"Could not check pending dialectic sessions: {e}")
            
            # EISV Completeness Validation - ensures all four metrics are present (prevents selection bias)
            if EISV_VALIDATION_AVAILABLE:
                try:
                    validate_governance_response(response_data)
                except Exception as validation_error:
                    # Log but don't fail the update - validation is a quality check
                    logger.warning(f"EISV validation warning: {validation_error}")
                    response_data["_eisv_validation_warning"] = str(validation_error)

            # =================================================================
            # LEARNING CONTEXT - Surface agent's own history for in-context learning
            # This closes the feedback loop: agents see their own patterns
            # =================================================================
            try:
                learning_context = {}
                
                # 1. Recent decisions from this agent's history
                # Get from audit log if available
                try:
                    from src.audit_log import AuditLogger
                    audit_logger = AuditLogger()  # Uses default path
                    recent_events = audit_logger.query_audit_log(
                        agent_id=agent_id,
                        limit=10
                    )
                    if recent_events:
                        recent_decisions = []
                        for event in recent_events[:5]:
                            details = event.get("details", {})
                            decision_summary = {
                                "timestamp": event.get("timestamp", "")[:19],  # Trim to readable
                                "action": details.get("action") or details.get("decision") or event.get("event_type"),
                                "risk": round(details.get("risk_score", 0), 2) if details.get("risk_score") else None,
                                "confidence": round(details.get("confidence", 0), 2) if details.get("confidence") else None,
                            }
                            # Only include if we have meaningful data
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
                
                # 2. Agent's own recent knowledge graph contributions
                try:
                    from src.knowledge_graph import get_knowledge_graph
                    graph = await get_knowledge_graph()
                    my_discoveries = await graph.query(
                        agent_id=agent_id,
                        limit=5
                    )
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
                
                # 3. Calibration insight - system-wide calibration (auto-collected!)
                try:
                    from src.calibration import calibration_checker
                    
                    # Get calibration stats
                    bin_stats = calibration_checker.bin_stats
                    total = sum(s['count'] for s in bin_stats.values())
                    
                    if total >= 10:  # Need enough data
                        # Calculate overall accuracy
                        total_correct = sum(s.get('actual_correct', 0) for s in bin_stats.values())
                        overall_accuracy = total_correct / total if total > 0 else 0
                        
                        # Find the inverted curve pattern (high confidence = low accuracy)
                        high_conf_bins = ['0.7-0.8', '0.8-0.9', '0.9-1.0']
                        low_conf_bins = ['0.0-0.5', '0.5-0.7']
                        
                        high_conf_total = sum(bin_stats.get(b, {}).get('count', 0) for b in high_conf_bins)
                        high_conf_correct = sum(bin_stats.get(b, {}).get('actual_correct', 0) for b in high_conf_bins)
                        high_conf_accuracy = high_conf_correct / high_conf_total if high_conf_total > 0 else 0
                        
                        low_conf_total = sum(bin_stats.get(b, {}).get('count', 0) for b in low_conf_bins)
                        low_conf_correct = sum(bin_stats.get(b, {}).get('actual_correct', 0) for b in low_conf_bins)
                        low_conf_accuracy = low_conf_correct / low_conf_total if low_conf_total > 0 else 0
                        
                        # Generate insight based on calibration patterns
                        if high_conf_accuracy < low_conf_accuracy - 0.2:
                            cal_insight = "⚠️ INVERTED CALIBRATION: High confidence correlates with LOWER accuracy. Consider being more humble."
                        elif abs(high_conf_accuracy - low_conf_accuracy) < 0.1:
                            cal_insight = "✅ Well calibrated - confidence matches outcomes"
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
                
                # 4. Pattern detection - what's this agent's tendency?
                try:
                    monitor = mcp_server.get_or_create_monitor(agent_id)
                    state = monitor.state
                    
                    patterns = []
                    
                    # Regime pattern
                    if hasattr(state, 'regime'):
                        regime_duration = getattr(state, 'regime_duration', 0)
                        if regime_duration > 5:
                            patterns.append(f"In {state.regime} regime for {regime_duration} updates")
                    
                    # Energy pattern
                    E = response_data.get('metrics', {}).get('E', 0.7)
                    if E > 0.85:
                        patterns.append("High energy - consider channeling into focused work")
                    elif E < 0.5:
                        patterns.append("Low energy - consider taking a step back")
                    
                    # Coherence trend
                    coherence = response_data.get('metrics', {}).get('coherence', 0.5)
                    if coherence < 0.4:
                        patterns.append("Low coherence - your approach may be scattered")
                    elif coherence > 0.8:
                        patterns.append("High coherence - maintaining consistent approach")
                    
                    if patterns:
                        learning_context["patterns"] = {
                            "observations": patterns,
                            "insight": "Patterns from your work - use these for self-awareness"
                        }
                except Exception as e:
                    logger.debug(f"Could not detect patterns: {e}")
                
                # Only include learning_context if we have something meaningful
                if learning_context:
                    response_data["learning_context"] = {
                        "_purpose": "Your own history, surfaced for in-context learning",
                        **learning_context
                    }
            except Exception as e:
                # Never fail the update because of learning context
                logger.debug(f"Could not build learning context: {e}")

            # Optional: compact response mode to reduce cognitive load / token bloat.
            # Defaults to "full" for backward compatibility. Can be overridden per-call or via env.
            try:
                import os
                response_mode = (arguments.get("response_mode") or os.getenv("UNITARES_PROCESS_UPDATE_RESPONSE_MODE", "full")).strip().lower()

                # AUTO MODE: Adaptive verbosity based on health status (v2 API)
                if response_mode == "auto":
                    # Determine appropriate mode based on health status
                    metrics = response_data.get("metrics", {}) if isinstance(response_data.get("metrics"), dict) else {}
                    health_status = (
                        response_data.get("health_status") or
                        metrics.get("health_status") or
                        response_data.get("status") or
                        "healthy"
                    )

                    # Adaptive logic:
                    # - healthy → compact (minimal detail, low cognitive load)
                    # - moderate → standard (human-readable interpretation)
                    # - at_risk/critical → full (all diagnostics for debugging)
                    if health_status == "healthy":
                        response_mode = "compact"
                    elif health_status in ("at_risk", "critical"):
                        response_mode = "full"
                    else:  # moderate or unknown
                        response_mode = "standard"

                # STANDARD MODE: Human-readable interpretation (v2 API)
                if response_mode in ("standard", "interpreted"):
                    from governance_state import GovernanceState
                    from governance_core import State, Theta, DEFAULT_THETA

                    metrics = response_data.get("metrics", {}) if isinstance(response_data.get("metrics"), dict) else {}
                    decision = response_data.get("decision", {}) if isinstance(response_data.get("decision"), dict) else {}

                    # Extract EISV + metadata
                    E = float(metrics.get("E", 0.7))
                    I = float(metrics.get("I", 0.8))
                    S = float(metrics.get("S", 0.1))
                    V = float(metrics.get("V", 0.0))
                    coherence = float(metrics.get("coherence", 0.5))
                    risk_score = metrics.get("latest_risk_score") or metrics.get("risk_score")

                    # Reconstruct minimal GovernanceState for interpretation
                    temp_state = GovernanceState()
                    temp_state.unitaires_state = State(E=E, I=I, S=S, V=V)
                    temp_state.unitaires_theta = Theta(C1=DEFAULT_THETA.C1, eta1=DEFAULT_THETA.eta1)
                    temp_state.coherence = coherence
                    temp_state.decision_history = response_data.get("history", {}).get("decision_history", [])

                    # Get interpreted state
                    interpreted = temp_state.interpret_state(
                        risk_score=risk_score,
                        task_type=task_type
                    )

                    # Build standard response with interpretation
                    response_data = {
                        "success": True,
                        "agent_id": response_data.get("agent_id"),
                        "decision": decision.get("action") or response_data.get("status"),
                        "state": interpreted,
                        "metrics": {
                            "E": E,
                            "I": I,
                            "S": S,
                            "V": V,
                            "coherence": coherence,
                            "risk_score": risk_score,
                        },
                        "sampling_params": response_data.get("sampling_params"),
                        "_mode": "standard",
                        "_raw_available": "Use response_mode='full' to see complete metrics"
                    }

                # COMPACT MODE: Minimal fields (existing behavior)
                elif response_mode in ("compact", "minimal", "lite"):
                    metrics = response_data.get("metrics", {}) if isinstance(response_data.get("metrics"), dict) else {}
                    decision = response_data.get("decision", {}) if isinstance(response_data.get("decision"), dict) else {}

                    # Canonical risk_score: prefer point-in-time latest_risk_score when present, else risk_score.
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

                    # Strip risk duplicates inside decision payload if present.
                    compact_decision = {
                        "action": decision.get("action"),
                        "reason": decision.get("reason"),
                        "require_human": decision.get("require_human"),
                    }

                    health_status = response_data.get("health_status") or compact_metrics.get("health_status") or response_data.get("status")
                    coherence = compact_metrics.get("coherence")
                    risk_val = compact_metrics.get("risk_score")
                    action = compact_decision.get("action") or response_data.get("status")
                    summary = f"{action} | health={health_status} | coherence={coherence} | risk_score={risk_val}"

                    response_data = {
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
            except Exception:
                pass

            # Return immediately - wrap in try/except to catch serialization errors
            # This prevents server crashes if serialization fails
            try:
                return success_response(response_data)
            except Exception as serialization_error:
                # If serialization fails, return minimal error response
                logger.error(f"Failed to serialize response: {serialization_error}", exc_info=True)
                # Return minimal response to prevent server crash
                import json
                from mcp.types import TextContent
                # Extract metrics once to avoid 6 repeated .get() calls
                metrics = result.get("metrics", {})
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "status": result.get("status", "unknown"),
                        "decision": result.get("decision", {}),
                        "metrics": {
                            "E": float(metrics.get("E", 0)),
                            "I": float(metrics.get("I", 0)),
                            "S": float(metrics.get("S", 0)),
                            "V": float(metrics.get("V", 0)),
                            "coherence": float(metrics.get("coherence", 0)),
                            "risk_score": float(metrics.get("risk_score", 0))
                        },
                        "sampling_params": result.get("sampling_params", {}),
                        "_warning": "Response serialization had issues - some fields may be missing"
                    })
                )]
    except TimeoutError as e:
        # Lock acquisition failed even after automatic retries and cleanup
        # Try one more aggressive cleanup attempt (async to avoid blocking error response)
        try:
            from src.lock_cleanup import cleanup_stale_state_locks
            project_root = Path(__file__).parent.parent.parent
            # Run cleanup in executor to avoid blocking error response
            cleanup_result = await loop.run_in_executor(
                None,
                cleanup_stale_state_locks,
                project_root,
                60.0,  # max_age_seconds
                False  # dry_run
            )
            if cleanup_result['cleaned'] > 0:
                logger.info(f"Auto-recovery: Cleaned {cleanup_result['cleaned']} stale lock(s) after timeout")
        except Exception as cleanup_error:
            logger.warning(f"Could not perform emergency lock cleanup: {cleanup_error}")
        
        return [error_response(
            f"Failed to acquire lock for agent '{agent_id}' after automatic retries and cleanup. "
            f"This usually means another active process is updating this agent. "
            f"The system has automatically cleaned stale locks. If this persists, try: "
            f"1) Wait a few seconds and retry, 2) Check for other Cursor/Claude sessions, "
            f"3) Use cleanup_stale_locks tool, or 4) Restart Cursor if stuck."
        )]
    except PermissionError as e:
        # Authentication failed
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
        # Loop detected or validation error
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
        # Catch any other unexpected errors to prevent disconnection
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

