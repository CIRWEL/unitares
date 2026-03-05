"""
Agent lifecycle management.

Monitor creation, agent archival, standardized info building.
"""

from __future__ import annotations

import re
from datetime import datetime

from src.logging_utils import get_logger
from src.agent_metadata_model import AgentMetadata, agent_metadata
from src.agent_monitor_state import monitors, load_monitor_state
from src.agent_metadata_persistence import get_or_create_metadata
from src.governance_monitor import UNITARESMonitor

logger = get_logger(__name__)


def get_or_create_monitor(agent_id: str) -> UNITARESMonitor:
    """Get existing monitor or create new one with metadata, loading state if it exists"""
    get_or_create_metadata(agent_id)

    if agent_id not in monitors:
        monitor = UNITARESMonitor(agent_id)

        persisted_state = load_monitor_state(agent_id)
        if persisted_state is not None:
            monitor.state = persisted_state
            logger.info(f"Loaded persisted state for {agent_id} ({len(persisted_state.V_history)} history entries)")
        else:
            logger.info(f"Initialized new monitor for {agent_id}")

        monitors[agent_id] = monitor

    return monitors[agent_id]


async def auto_archive_old_test_agents(max_age_hours: float = 6.0) -> int:
    """
    Automatically archive old test/demo agents that haven't been updated recently.

    Test/ping agents (1-2 updates) are archived immediately.
    Other test agents are archived after inactivity threshold.

    Returns:
        Number of agents archived
    """
    archived_count = 0
    current_time = datetime.now()

    for agent_id, meta in list(agent_metadata.items()):
        if meta.status in ["archived", "deleted"]:
            continue

        is_test_agent = (
            agent_id.startswith("test_") or
            agent_id.startswith("demo_") or
            agent_id.startswith("test") or
            "test" in agent_id.lower() or
            "demo" in agent_id.lower()
        )

        if not is_test_agent:
            continue

        if meta.total_updates <= 2:
            meta.status = "archived"
            meta.archived_at = current_time.isoformat()
            meta.add_lifecycle_event(
                "archived",
                f"Auto-archived: test/ping agent with {meta.total_updates} update(s)"
            )
            archived_count += 1
            logger.info(f"Auto-archived test/ping agent: {agent_id} ({meta.total_updates} updates)")
            continue

        try:
            last_update_dt = datetime.fromisoformat(meta.last_update.replace('Z', '+00:00') if 'Z' in meta.last_update else meta.last_update)
            age_delta = (current_time.replace(tzinfo=last_update_dt.tzinfo) if last_update_dt.tzinfo else current_time) - last_update_dt
            age_hours = age_delta.total_seconds() / 3600
        except (ValueError, TypeError, AttributeError):
            continue

        if age_hours >= max_age_hours:
            meta.status = "archived"
            meta.archived_at = current_time.isoformat()
            meta.add_lifecycle_event(
                "archived",
                f"Auto-archived: inactive test/demo agent ({age_hours:.1f} hours old, threshold: {max_age_hours} hours)"
            )
            archived_count += 1
            logger.info(f"Auto-archived old test agent: {agent_id} ({age_hours:.1f} hours old)")

    return archived_count


async def auto_archive_orphan_agents(
    zero_update_hours: float = 1.0,
    low_update_hours: float = 3.0,
    unlabeled_hours: float = 6.0
) -> int:
    """
    Aggressively archive orphan agents to prevent proliferation.

    Returns:
        Number of agents archived
    """
    UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

    archived_count = 0
    current_time = datetime.now()

    for agent_id, meta in list(agent_metadata.items()):
        if meta.status in ["archived", "deleted"]:
            continue

        if "pioneer" in (meta.tags or []):
            continue

        has_label = bool(getattr(meta, 'label', None) or getattr(meta, 'display_name', None))
        is_uuid_named = bool(UUID_PATTERN.match(agent_id))

        try:
            last_update_str = meta.last_update or meta.created_at
            last_update_dt = datetime.fromisoformat(
                last_update_str.replace('Z', '+00:00') if 'Z' in last_update_str else last_update_str
            )
            if last_update_dt.tzinfo:
                age_delta = datetime.now(last_update_dt.tzinfo) - last_update_dt
            else:
                age_delta = current_time - last_update_dt
            age_hours = age_delta.total_seconds() / 3600
        except (ValueError, TypeError, AttributeError):
            continue

        raw_updates = getattr(meta, 'total_updates', 0)
        try:
            updates = int(raw_updates or 0)
        except (TypeError, ValueError):
            updates = 0
        should_archive = False
        reason = ""

        if is_uuid_named and updates == 0 and age_hours >= zero_update_hours:
            should_archive = True
            reason = f"orphan UUID agent, 0 updates, {age_hours:.1f}h old"

        elif not has_label and updates <= 1 and age_hours >= low_update_hours:
            should_archive = True
            reason = f"unlabeled agent, {updates} updates, {age_hours:.1f}h old"

        elif is_uuid_named and not has_label and updates >= 2 and age_hours >= unlabeled_hours:
            should_archive = True
            reason = f"stale UUID agent, {updates} updates, {age_hours:.1f}h old"

        if should_archive:
            meta.status = "archived"
            meta.archived_at = current_time.isoformat()
            meta.add_lifecycle_event("archived", f"Auto-archived: {reason}")
            archived_count += 1
            logger.info(f"Auto-archived orphan agent: {agent_id[:12]}... ({reason})")

    return archived_count


def get_agent_or_error(agent_id: str) -> tuple[UNITARESMonitor | None, str | None]:
    """Get agent with friendly error message if not found"""
    if agent_id not in monitors:
        available = list(monitors.keys())
        if available:
            error = f"Agent '{agent_id}' not found. Available agents: {available}. Call process_agent_update first to initialize."
        else:
            error = f"Agent '{agent_id}' not found. No agents initialized yet. Call process_agent_update first."
        return None, error
    return monitors[agent_id], None


def build_standardized_agent_info(
    agent_id: str,
    meta: AgentMetadata,
    monitor: UNITARESMonitor | None = None,
    include_metrics: bool = True
) -> dict:
    """
    Build standardized agent info structure.
    Always returns same fields, null if unavailable.
    """
    from src.agent_process_mgmt import health_checker

    if monitor:
        if hasattr(monitor, 'created_at') and monitor.created_at:
            created_ts = monitor.created_at.isoformat()
        else:
            created_ts = meta.created_at

        if hasattr(monitor, 'last_update') and monitor.last_update:
            last_update_ts = monitor.last_update.isoformat()
        else:
            last_update_ts = meta.last_update

        update_count = meta.total_updates
    else:
        created_ts = meta.created_at
        last_update_ts = meta.last_update
        update_count = meta.total_updates

    try:
        created_dt = datetime.fromisoformat(created_ts.replace('Z', '+00:00') if 'Z' in created_ts else created_ts)
        age_days = (datetime.now(created_dt.tzinfo) - created_dt).days
    except (ValueError, TypeError, AttributeError):
        age_days = None

    primary_tags = (meta.tags or [])[:3] if meta.tags else []

    notes_preview = None
    if meta.notes:
        notes_preview = meta.notes[:100] + "..." if len(meta.notes) > 100 else meta.notes

    summary = {
        "updates": update_count,
        "last_activity": last_update_ts,
        "age_days": age_days,
        "primary_tags": primary_tags
    }

    metrics = None
    health_status = "unknown"
    state_info = {
        "loaded_in_process": monitor is not None,
        "metrics_available": False,
        "error": None
    }

    if monitor and include_metrics:
        try:
            monitor_state = monitor.state
            risk_score = getattr(monitor_state, 'risk_score', None)
            health_status_obj, _ = health_checker.get_health_status(
                risk_score=risk_score,
                coherence=monitor_state.coherence,
                void_active=monitor_state.void_active
            )
            health_status = health_status_obj.value

            monitor_metrics = monitor.get_metrics() if hasattr(monitor, 'get_metrics') else {}
            risk_score_value = monitor_metrics.get("risk_score") or risk_score

            metrics = {
                "risk_score": float(risk_score_value) if risk_score_value is not None else None,
                "phi": monitor_metrics.get("phi"),
                "verdict": monitor_metrics.get("verdict"),
                "coherence": float(monitor_state.coherence),
                "void_active": bool(monitor_state.void_active),
                "E": float(monitor_state.E),
                "I": float(monitor_state.I),
                "S": float(monitor_state.S),
                "V": float(monitor_state.V),
                "lambda1": float(monitor_state.lambda1)
            }
            state_info["metrics_available"] = True
        except Exception as e:
            health_status = "error"
            state_info["error"] = str(e)
            state_info["metrics_available"] = False

    lineage_info = None
    if meta.parent_agent_id:
        lineage_info = {
            "parent_agent_id": meta.parent_agent_id,
            "creation_reason": meta.spawn_reason or "created",
            "has_lineage": True
        }
        if meta.parent_agent_id in agent_metadata:
            parent_meta = agent_metadata[meta.parent_agent_id]
            lineage_info["parent_status"] = parent_meta.status
        else:
            lineage_info["parent_status"] = "deleted"

    return {
        "agent_id": agent_id,
        "lifecycle_status": meta.status,
        "health_status": health_status,
        "summary": summary,
        "metrics": metrics,
        "metadata": {
            "created": created_ts,
            "last_update": last_update_ts,
            "version": meta.version,
            "total_updates": meta.total_updates,
            "tags": meta.tags or [],
            "notes_preview": notes_preview,
            "lineage_info": lineage_info
        },
        "state": state_info
    }
