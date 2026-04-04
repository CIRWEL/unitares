"""Transport-neutral read/query services for core governance state."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from config.governance_config import GovernanceConfig
from src.eisv_semantics import get_state_semantics
from src.logging_utils import get_logger
from src.mcp_handlers.shared import lazy_mcp_server as mcp_server
from src.services.identity_continuity import get_identity_continuity_status
from src.services.identity_payloads import attach_identity_handles

logger = get_logger(__name__)


def _generate_contextual_reflection(metrics: dict, interpreted: dict) -> str | None:
    """Generate a reflection prompt only when state warrants attention."""
    is_uninit = metrics.get('initialized') is False or metrics.get('status') == 'uninitialized'
    if is_uninit:
        return "First check-in — submit a process_agent_update to activate governance."

    verdict = metrics.get('verdict', 'proceed')
    if verdict in ('guide', 'pause', 'reject'):
        return f"Your state triggered a {verdict} verdict. What changed?"

    state = interpreted.get('state', {})
    borderline = state.get('borderline')
    if borderline:
        return "You're near a basin boundary. Proceed carefully."

    S = metrics.get('S')
    if S is not None and S > 0.3:
        return f"Entropy is elevated ({S:.2f}). What's contributing to disorder?"

    return None


async def get_governance_metrics_data(agent_id: str, arguments: Dict[str, Any], server=None) -> Dict[str, Any]:
    """Build plain governance metrics data for an agent."""
    server = server or mcp_server
    verbosity = arguments.get("verbosity")
    if verbosity and verbosity in ("minimal", "standard", "full"):
        lite = verbosity == "minimal"
    else:
        lite = arguments.get("lite", True)
        verbosity = "minimal" if lite else "full"

    monitor = server.get_or_create_monitor(agent_id)
    include_state = arguments.get("include_state", False)
    metrics = monitor.get_metrics(include_state=include_state)

    from src.governance_monitor import UNITARESMonitor
    from src.mcp_handlers.utils import format_metrics_report, get_calibration_feedback

    metrics["eisv_labels"] = UNITARESMonitor.get_eisv_labels()
    standardized_metrics = format_metrics_report(
        metrics=metrics,
        agent_id=agent_id,
        include_timestamp=True,
        include_context=True,
    )
    standardized_metrics["state_semantics"] = get_state_semantics()
    try:
        from src.mcp_handlers.context import get_session_resolution_source
        standardized_metrics["session_continuity"] = {
            "resolution_source": get_session_resolution_source(),
        }
    except Exception:
        pass

    meta = server.agent_metadata.get(agent_id)
    display_name = None
    public_agent_id = agent_id
    if meta:
        display_name = getattr(meta, "display_name", None) or getattr(meta, "label", None)
        public_agent_id = getattr(meta, "structured_id", None) or public_agent_id
    if public_agent_id == agent_id or display_name is None:
        try:
            from src.db import get_db

            db = get_db()
            identity = await db.get_identity(agent_id)
            if identity and identity.metadata:
                metadata = identity.metadata
                public_agent_id = (
                    metadata.get("public_agent_id")
                    or metadata.get("agent_id")
                    or metadata.get("structured_id")
                    or public_agent_id
                )
                display_name = display_name or metadata.get("label")
            if display_name is None:
                display_name = await db.get_agent_label(agent_id)
        except Exception:
            pass
    attach_identity_handles(
        standardized_metrics,
        agent_uuid=agent_id,
        public_agent_id=public_agent_id,
        display_name=display_name,
    )
    if meta and getattr(meta, "purpose", None):
        standardized_metrics["purpose"] = meta.purpose

    calibration_feedback = {}
    try:
        if meta:
            derived_complexity = metrics.get("complexity", None)
            if derived_complexity is not None:
                calibration_feedback["complexity"] = {
                    "derived": derived_complexity,
                    "message": f"System-derived complexity: {derived_complexity:.2f} (based on current state)",
                }
    except Exception as e:
        logger.debug(f"Could not add complexity calibration feedback: {e}")

    confidence_feedback = get_calibration_feedback(include_complexity=False)
    if confidence_feedback:
        calibration_feedback.update(confidence_feedback)
    if calibration_feedback:
        standardized_metrics["calibration_feedback"] = calibration_feedback

    try:
        risk_score = metrics.get("risk_score") or metrics.get("latest_risk_score")
        interpreted_state = monitor.state.interpret_state(risk_score=risk_score)
        standardized_metrics["state"] = interpreted_state
        health = interpreted_state.get("health", "unknown")
        mode = interpreted_state.get("mode", "unknown")
        basin = interpreted_state.get("basin", "unknown")
        standardized_metrics["summary"] = f"{health} | {mode} | {basin} basin"
    except Exception as e:
        logger.debug(f"Could not generate state interpretation: {e}")

    try:
        from governance_core import compute_saturation_diagnostics
        from governance_core.parameters import DEFAULT_THETA

        unitares_state = monitor.state.unitaires_state
        theta = getattr(monitor.state, "unitaires_theta", None) or DEFAULT_THETA

        if unitares_state:
            sat_diag = compute_saturation_diagnostics(unitares_state, theta)
            standardized_metrics["saturation_diagnostics"] = {
                "sat_margin": sat_diag["sat_margin"],
                "dynamics_mode": sat_diag["dynamics_mode"],
                "will_saturate": sat_diag["will_saturate"],
                "at_boundary": sat_diag["at_boundary"],
                "I_equilibrium": sat_diag["I_equilibrium_linear"],
                "forcing_term_A": sat_diag["A"],
                "_interpretation": (
                    "⚠️ Positive sat_margin means push-to-boundary (logistic mode will saturate I→1)"
                    if sat_diag["sat_margin"] > 0
                    else "✓ Negative sat_margin - stable interior equilibrium exists"
                ),
            }
    except Exception as e:
        logger.debug(f"Could not compute saturation diagnostics: {e}")

    reflection = _generate_contextual_reflection(metrics, standardized_metrics)
    if reflection:
        standardized_metrics["reflection"] = reflection

    if verbosity == "standard":
        state = standardized_metrics.get("state", {})
        standard_metrics = {
            "agent_id": agent_id,
            "E": metrics.get("E"),
            "I": metrics.get("I"),
            "S": metrics.get("S"),
            "V": metrics.get("V"),
            "coherence": metrics.get("coherence"),
            "verdict": metrics.get("verdict", "uninitialized"),
            "risk_score": metrics.get("risk_score"),
            "basin": state.get("basin"),
            "mode": state.get("mode"),
            "summary": standardized_metrics.get("summary"),
            "guidance": state.get("guidance"),
            "state_semantics": standardized_metrics.get("state_semantics"),
            "primary_eisv_source": metrics.get("primary_eisv_source"),
            "primary_eisv": metrics.get("primary_eisv"),
            "behavioral_eisv": metrics.get("behavioral_eisv"),
            "ode_eisv": metrics.get("ode_eisv") or metrics.get("ode"),
            "ode_diagnostics": metrics.get("ode_diagnostics"),
        }
        attach_identity_handles(
            standard_metrics,
            agent_uuid=agent_id,
            public_agent_id=public_agent_id,
            display_name=display_name,
        )
        if reflection:
            standard_metrics["reflection"] = reflection
        standard_metrics["_note"] = (
            "Flat E/I/S/V alias primary_eisv. "
            "Use behavioral_eisv and ode_eisv to inspect the split explicitly."
        )
        return standard_metrics

    standardized_metrics["_debug_lite_received"] = lite

    if lite:
        coherence = metrics.get("coherence")
        risk_score = metrics.get("risk_score")
        health = standardized_metrics.get("state", {}).get("health", "unknown")
        status_indicator = {
            "healthy": "🟢",
            "moderate": "🟡",
            "critical": "🔴",
            "unknown": "⚪",
        }.get(health, "⚪")
        is_uninitialized = metrics.get("initialized") is False or metrics.get("status") == "uninitialized"

        if is_uninitialized:
            status_display = "⚪ uninitialized"
            coherence_status = "⚪ pending (first check-in required)"
            risk_status = "⚪ pending (first check-in required)"
        else:
            status_display = f"{status_indicator} {health}"
            if coherence is None:
                coherence_status = "⚪ unknown"
            elif coherence >= 0.50:
                coherence_status = "🟢 good"
            elif coherence >= 0.45:
                coherence_status = "🟡 moderate"
            else:
                coherence_status = "🔴 low"
            risk_status = (
                "🟢 low" if risk_score is not None and risk_score < 0.5 else
                "🟡 medium" if risk_score is not None and risk_score < 0.75 else
                "🔴 high" if risk_score is not None else
                "⚪ unknown"
            )

        void_raw = metrics.get("V")
        if void_raw is not None and void_raw != 0:
            void_display = round(void_raw, 6)
        else:
            void_display = 0.0 if void_raw == 0 else void_raw

        lite_metrics = {
            "agent_id": agent_id,
            "status": status_display,
            "purpose": getattr(meta, "purpose", None),
            "summary": standardized_metrics.get("summary", "unknown"),
            "primary_eisv_source": metrics.get("primary_eisv_source"),
            "state_semantics": {
                "flat_fields": standardized_metrics["state_semantics"]["flat_fields"],
                "primary_eisv_source": standardized_metrics["state_semantics"]["primary_eisv_source"],
            },
            "E": {"value": metrics.get("E"), "range": "[0, 1]", "note": "Energy capacity"},
            "I": {"value": metrics.get("I"), "range": "[0, 1]", "note": "Information integrity"},
            "S": {"value": metrics.get("S"), "range": "[0, 1]", "ideal": "<0.2", "note": "Entropy (lower=better)"},
            "V": {"value": void_display, "range": "[-1, 1]", "ideal": "near 0", "note": "Void (E-I imbalance, settles toward 0)"},
            "coherence": {"value": coherence, "range": "[0, 1]", "status": coherence_status},
            "risk_score": {"value": risk_score, "threshold": 0.5, "status": risk_status},
        }
        attach_identity_handles(
            lite_metrics,
            agent_uuid=agent_id,
            public_agent_id=public_agent_id,
            display_name=display_name,
        )
        if "state" in standardized_metrics:
            lite_metrics["mode"] = standardized_metrics["state"].get("mode")
            lite_metrics["basin"] = standardized_metrics["state"].get("basin")
        if is_uninitialized:
            lite_metrics["verdict"] = "uninitialized"
            lite_metrics["guidance"] = "Submit one check-in to activate governance."
            lite_metrics["next_action"] = {
                "tool": "process_agent_update",
                "example": "process_agent_update(response_text='Starting work', complexity=0.3, confidence=0.7)",
                "note": "get_governance_metrics is read-only; it does not initialize state.",
            }
            lite_metrics["related_tools"] = ["process_agent_update", "onboard", "identity"]
        lite_metrics["thresholds"] = {
            "coherence_critical": GovernanceConfig.COHERENCE_CRITICAL_THRESHOLD,
            "coherence_good": 0.50,
            "risk_medium": 0.5,
            "risk_high": 0.75,
            "target_coherence": GovernanceConfig.TARGET_COHERENCE,
        }
        lite_metrics["_note"] = (
            "Flat E/I/S/V shown here are the primary EISV. "
            "Use lite=false for the behavioral/ODE split."
        )
        return lite_metrics

    return standardized_metrics


async def get_health_check_data(arguments: Dict[str, Any], server=None) -> Dict[str, Any]:
    """Build plain health-check data for operators and transports."""
    server = server or mcp_server
    import asyncio
    import os
    import time as _time

    from src.audit_log import audit_logger
    from src.calibration import calibration_checker
    from src.db import get_db

    checks = {}
    loop = asyncio.get_running_loop()
    continuity_status = None

    try:
        pending = await loop.run_in_executor(None, lambda: calibration_checker.get_pending_updates())
        checks["calibration"] = {"status": "healthy", "pending_updates": pending}
    except Exception as e:
        checks["calibration"] = {"status": "error", "error": str(e)}

    try:
        from src.calibration_db import calibration_health_check_async
        info = await calibration_health_check_async()
        checks["calibration_db"] = {"status": "healthy", "backend": info.get("backend", "unknown"), "info": info}
    except Exception as e:
        checks["calibration_db"] = {"status": "error", "error": str(e)}

    try:
        log_exists = await loop.run_in_executor(None, lambda: audit_logger.log_file.exists())
        checks["telemetry"] = {"status": "healthy" if log_exists else "warning", "audit_log_exists": log_exists}
    except Exception as e:
        checks["telemetry"] = {"status": "error", "error": str(e)}

    try:
        configured = os.getenv("DB_BACKEND", "postgres").lower()
        db = get_db()
        backend_class = type(db).__name__
        init_error = None
        try:
            await db.init()
        except Exception as e:
            init_error = str(e)
        try:
            db_info = await db.health_check()
        except Exception as e:
            db_info = {"status": "error", "error": str(e)}
        db_status = db_info.get("status") if isinstance(db_info, dict) else None
        checks["primary_db"] = {
            "status": "healthy" if db_status == "healthy" else ("error" if db_status == "error" else "warning"),
            "configured_backend": configured,
            "backend_class": backend_class,
            "init_error": init_error,
            "info": db_info,
        }
    except Exception as e:
        checks["primary_db"] = {"status": "error", "error": str(e)}

    try:
        from src.audit_db import audit_health_check_async
        info = await audit_health_check_async()
        checks["audit_db"] = {"status": "healthy", "backend": info.get("backend", "unknown"), "info": info}
    except Exception as e:
        checks["audit_db"] = {"status": "error", "error": str(e)}

    try:
        from src.cache import get_distributed_lock, get_redis, get_session_cache, is_redis_available
        redis_available = is_redis_available()
        if redis_available:
            session_cache = get_session_cache()
            dist_lock = get_distributed_lock()
            cache_health = await session_cache.health_check()
            lock_health = await dist_lock.health_check()
            checks["redis_cache"] = {
                "status": cache_health.get("status", "unknown"),
                "present": True,
                "session_cache": cache_health,
                "distributed_lock": lock_health,
                "features": ["session_cache", "distributed_locking", "rate_limiting", "metadata_cache"],
            }
            try:
                redis = await get_redis()
                if redis:
                    info = await redis.info("stats")
                    hits = info.get("keyspace_hits", 0)
                    misses = info.get("keyspace_misses", 0)
                    total_lookups = hits + misses
                    checks["redis_cache"]["stats"] = {
                        "keyspace_hits": hits,
                        "keyspace_misses": misses,
                        "keyspace_hit_rate_percent": round((hits / total_lookups) * 100, 1) if total_lookups else None,
                        "total_commands": info.get("total_commands_processed", 0),
                        "scope": "redis_instance_wide",
                        "note": "Keyspace hit/miss counts cover the whole Redis instance, not just session_cache lookups.",
                    }
                    try:
                        checks["redis_cache"]["keys"] = {
                            "sessions": len([k async for k in redis.scan_iter(match="session:*", count=100)]),
                            "rate_limits": len([k async for k in redis.scan_iter(match="rate_limit:*", count=100)]),
                            "metadata": len([k async for k in redis.scan_iter(match="agent_meta:*", count=100)]),
                            "locks": len([k async for k in redis.scan_iter(match="lock:*", count=100)]),
                        }
                    except Exception as e:
                        checks["redis_cache"]["keys_error"] = str(e)
            except Exception as e:
                checks["redis_cache"]["stats_error"] = str(e)
        else:
            checks["redis_cache"] = {
                "status": "unavailable",
                "present": False,
                "note": "Redis not available - using fallback modes",
            }
    except ImportError:
        checks["redis_cache"] = {
            "status": "unavailable",
            "present": False,
            "note": "Redis cache module not installed",
        }
    except Exception as e:
        checks["redis_cache"] = {"status": "error", "present": False, "error": str(e)}

    continuity_status = get_identity_continuity_status(
        redis_present=checks.get("redis_cache", {}).get("present"),
        redis_operational=checks.get("redis_cache", {}).get("status") not in {"error", "unavailable"},
    )
    checks["identity_continuity"] = continuity_status

    try:
        from src.knowledge_graph import get_knowledge_graph
        graph = await get_knowledge_graph()
        backend_name = type(graph).__name__
        kg_info = await graph.health_check() if hasattr(graph, "health_check") else await graph.get_stats()
        embeddings_ok = False
        try:
            from src.embeddings import embeddings_available
            embeddings_ok = embeddings_available()
        except Exception:
            pass
        kg_status = "healthy" if embeddings_ok else "degraded"
        kg_check = {
            "status": kg_status,
            "backend": backend_name,
            "info": kg_info,
            "embeddings_available": embeddings_ok,
        }
        if not embeddings_ok:
            kg_check["warning"] = "Semantic search unavailable — embeddings service not loaded. KG search will fall back to text search."
        try:
            from src.knowledge_graph_lifecycle import get_kg_lifecycle_health
            lifecycle_health = get_kg_lifecycle_health()
            kg_check["lifecycle"] = lifecycle_health
            if lifecycle_health.get("status") == "error":
                kg_check["status"] = "warning" if kg_check["status"] == "healthy" else kg_check["status"]
                kg_check["warning"] = f"KG lifecycle cleanup is failing: {lifecycle_health.get('last_error')}"
        except Exception as e:
            kg_check["lifecycle_error"] = str(e)
        checks["knowledge_graph"] = kg_check
    except Exception as e:
        checks["knowledge_graph"] = {"status": "error", "error": str(e)}

    checks["agent_metadata"] = {
        "status": "healthy",
        "backend": "postgres",
        "note": "Agent metadata stored in core.identities table (PostgreSQL)",
    }

    try:
        data_dir = Path(server.project_root) / "data"
        data_dir_exists = await loop.run_in_executor(None, lambda: data_dir.exists())
        checks["data_directory"] = {"status": "healthy" if data_dir_exists else "warning", "exists": data_dir_exists}
    except Exception as e:
        checks["data_directory"] = {"status": "error", "error": str(e)}

    try:
        from src.mcp_handlers.observability.pi_orchestration import PI_MCP_URLS, call_pi_tool
        pi_start = _time.time()
        pi_result = await asyncio.wait_for(call_pi_tool("get_health", {}, timeout=3.0), timeout=4.0)
        pi_latency = (_time.time() - pi_start) * 1000
        if isinstance(pi_result, dict) and "error" not in pi_result:
            checks["pi_connectivity"] = {
                "status": "healthy",
                "reachable": True,
                "latency_ms": round(pi_latency, 1),
                "urls_configured": PI_MCP_URLS,
            }
        else:
            error_msg = str(pi_result.get("error", "unknown")) if isinstance(pi_result, dict) else str(pi_result)
            checks["pi_connectivity"] = {
                "status": "warning",
                "reachable": False,
                "error": error_msg,
                "urls_configured": PI_MCP_URLS,
            }
    except (asyncio.TimeoutError, Exception) as e:
        checks["pi_connectivity"] = {"status": "warning", "reachable": False, "error": str(e)}

    statuses = [c.get("status") for c in checks.values()]
    overall_status = "critical" if "error" in statuses else ("healthy" if all(s == "healthy" for s in statuses) else "moderate")
    status_breakdown = {
        "healthy": sum(1 for s in statuses if s == "healthy"),
        "warning": sum(1 for s in statuses if s == "warning"),
        "deprecated": sum(1 for s in statuses if s == "deprecated"),
        "unavailable": sum(1 for s in statuses if s == "unavailable"),
        "error": sum(1 for s in statuses if s == "error"),
    }
    failing_checks = sorted(name for name, check in checks.items() if check.get("status") == "error")
    degraded_checks = sorted(name for name, check in checks.items() if check.get("status") in {"warning", "deprecated", "unavailable"})

    first_action = "No action needed."
    if "primary_db" in failing_checks:
        first_action = "Check PostgreSQL availability and database initialization first."
    elif "redis_cache" in failing_checks:
        first_action = "Check Redis connectivity or continue in fallback mode if Redis is optional."
    elif continuity_status and continuity_status.get("mode") == "degraded-local":
        first_action = (
            "Redis is absent; identity continuity is running in degraded-local mode. "
            "Restore Redis if you need cross-process session continuity."
        )
    elif "knowledge_graph" in failing_checks:
        first_action = "Check knowledge graph backend and embeddings availability."
    elif "pi_connectivity" in degraded_checks or "pi_connectivity" in failing_checks:
        first_action = "Check Pi/anima connectivity only if Pi orchestration is required."
    elif failing_checks:
        first_action = f"Inspect the first failing component: {failing_checks[0]}."
    elif degraded_checks:
        first_action = f"Review the first degraded component: {degraded_checks[0]}."

    response = {
        "status": overall_status,
        "version": getattr(server, "SERVER_VERSION", "unknown"),
        "redis_present": continuity_status.get("redis_present", False) if continuity_status else False,
        "identity_continuity_mode": continuity_status.get("mode", "unknown") if continuity_status else "unknown",
        "status_breakdown": status_breakdown,
        "operator_summary": {
            "overall_status": overall_status,
            "failing_checks": failing_checks,
            "degraded_checks": degraded_checks,
            "first_action": first_action,
        },
        "timestamp": datetime.now().isoformat(),
    }

    lite = arguments.get("lite", True)
    if lite:
        lite_checks = {}
        for name, check in checks.items():
            lite_checks[name] = {"status": check.get("status", "unknown")}
            for key in ("mode", "redis_present", "present", "source_of_truth", "session_binding_backend"):
                if key in check:
                    lite_checks[name][key] = check[key]
            if "warning" in check:
                lite_checks[name]["warning"] = check["warning"]
            if "note" in check:
                lite_checks[name]["note"] = check["note"]
        response["checks"] = lite_checks
        response["_note"] = "Use lite=false for full diagnostic detail"
    else:
        response["checks"] = checks

    return response
