"""Dashboard tool — read-only overview of all agents' EISV state.

Bypasses session binding so visualizers and dashboards can see the full system.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Sequence
from mcp.types import TextContent
from ..types import ToolArgumentsDict
from ..utils import success_response, error_response
from ..decorators import mcp_tool
from src.mcp_handlers.shared import lazy_mcp_server as mcp_server
from src.db import get_db
from src.eisv_semantics import get_state_semantics
from src.eisv_state_json import normalize_agent_state_json
from src.logging_utils import get_logger

logger = get_logger(__name__)


def _round_maybe(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(float(value), 4)
    return value


def _round_payload(payload: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {key: _round_maybe(value) for key, value in payload.items()}


def _state_views_from_record(state: Any) -> Dict[str, Any]:
    sj, _ = normalize_agent_state_json(
        state.state_json or {},
        energy=state.energy,
        integrity=state.integrity,
        entropy=state.entropy,
        void=state.void,
        coherence=state.coherence,
        regime=state.regime,
        source_strategy="safe",
    )
    primary = dict(sj.get("primary_eisv") or {})
    primary.setdefault("E", state.energy)
    primary.setdefault("I", state.integrity)
    primary.setdefault("S", state.entropy)
    primary.setdefault("V", state.void)

    ode = dict(sj.get("ode_eisv") or sj.get("ode") or {})
    ode.setdefault("E", state.energy)
    ode.setdefault("I", state.integrity)
    ode.setdefault("S", state.entropy)
    ode.setdefault("V", state.void)

    behavioral = sj.get("behavioral_eisv")
    risk = sj.get("risk_score")
    verdict = sj.get("verdict") or (sj.get("ode_diagnostics") or {}).get("verdict") or "proceed"

    ode_diagnostics = dict(sj.get("ode_diagnostics") or {})
    ode_diagnostics.setdefault("phi", sj.get("phi"))
    ode_diagnostics.setdefault("coherence", state.coherence)
    ode_diagnostics.setdefault("regime", state.regime)
    ode_diagnostics.setdefault("verdict", verdict)
    ode_diagnostics.setdefault("risk_score", risk)

    primary_rounded = _round_payload(primary)
    ode_rounded = _round_payload(ode)
    behavioral_rounded = _round_payload(behavioral)
    ode_diagnostics_rounded = _round_payload(ode_diagnostics)

    result = {
        "eisv": {
            **(primary_rounded or {}),
            "coherence": _round_maybe(state.coherence),
            "basin": state.regime,
            "risk": _round_maybe(risk) if risk is not None else 0,
            "verdict": verdict,
        },
        "primary_eisv": primary_rounded,
        "primary_eisv_source": sj.get("primary_eisv_source"),
        "ode_eisv": ode_rounded,
        "ode": ode_rounded,
        "ode_diagnostics": ode_diagnostics_rounded,
    }
    if behavioral_rounded is not None:
        result["behavioral_eisv"] = behavioral_rounded
        result["behavioral"] = behavioral_rounded
    return result


@mcp_tool("dashboard", timeout=15.0, description="Read-only system overview: primary EISV plus behavioral/ODE diagnostics for all agents. No session binding required.")
async def handle_dashboard(arguments: ToolArgumentsDict) -> Sequence[TextContent]:
    """Return all active agents with primary EISV and behavioral/ODE diagnostics."""
    try:
        db = get_db()
        states = await db.get_all_latest_agent_states()

        # Index states by agent_id — E now comes from s.energy (extracted in _row_to_agent_state)
        state_by_agent: Dict[str, Any] = {}
        for s in states:
            state_by_agent[s.agent_id] = _state_views_from_record(s)

        # Filter: recent_days=1 by default (show today's agents + Lumen)
        recent_days = int(arguments.get("recent_days", 1))
        min_updates = int(arguments.get("min_updates", 1))
        limit = int(arguments.get("limit", 15))
        offset = int(arguments.get("offset", 0))
        basin_filter = arguments.get("basin_filter", None)
        risk_threshold = arguments.get("risk_threshold", None)
        if risk_threshold is not None:
            risk_threshold = float(risk_threshold)
        cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days) if recent_days > 0 else None

        agents = []
        for agent_id, meta in list(mcp_server.agent_metadata.items()):
            if meta.status != "active":
                continue
            if meta.total_updates < min_updates:
                continue

            # Pinned agents always included regardless of recency
            is_pinned = "pinned" in (getattr(meta, "tags", None) or [])

            # Filter by recency using last_update from metadata
            if cutoff and not is_pinned and meta.last_update:
                try:
                    last_dt = datetime.fromisoformat(meta.last_update.replace("Z", "+00:00"))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if last_dt < cutoff:
                        continue
                except Exception:
                    # Unparseable timestamp — exclude agent (fail closed)
                    logger.warning(f"Dashboard: unparseable last_update for {agent_id}: {meta.last_update!r}")
                    continue

            eisv = state_by_agent.get(agent_id, None)
            agent_entry: Dict[str, Any] = {
                "id": agent_id,
                "label": getattr(meta, "label", None),
                "updates": meta.total_updates,
                "pinned": is_pinned,
                "last_update": getattr(meta, "last_update", None),
            }
            if eisv:
                agent_entry.update(eisv)

            # ODE diagnostic overlay from in-memory monitors (primary EISV
            # is now behavioral, stored in DB via process_update metrics)
            try:
                monitors = getattr(mcp_server, 'monitors', None)
                if isinstance(monitors, dict):
                    monitor = monitors.get(agent_id)
                    if monitor:
                        live_metrics = monitor.get_metrics(include_state=False)
                        primary_live = _round_payload(
                            live_metrics.get("primary_eisv")
                            or {
                                "E": live_metrics.get("E"),
                                "I": live_metrics.get("I"),
                                "S": live_metrics.get("S"),
                                "V": live_metrics.get("V"),
                            }
                        )
                        if primary_live is not None:
                            agent_entry["primary_eisv"] = primary_live
                        if live_metrics.get("primary_eisv_source"):
                            agent_entry["primary_eisv_source"] = live_metrics.get("primary_eisv_source")

                        ode_live = _round_payload(live_metrics.get("ode_eisv") or live_metrics.get("ode"))
                        if ode_live is not None:
                            agent_entry["ode_eisv"] = ode_live
                            agent_entry["ode"] = ode_live

                        behavioral_live = _round_payload(live_metrics.get("behavioral_eisv"))
                        if behavioral_live is not None:
                            agent_entry["behavioral_eisv"] = behavioral_live
                            agent_entry["behavioral"] = behavioral_live

                        ode_diagnostics_live = _round_payload(live_metrics.get("ode_diagnostics"))
                        if ode_diagnostics_live is not None:
                            agent_entry["ode_diagnostics"] = ode_diagnostics_live

                        compat_eisv = dict(agent_entry.get("eisv", {}))
                        if primary_live is not None:
                            compat_eisv.update(primary_live)
                        if live_metrics.get("coherence") is not None:
                            compat_eisv["coherence"] = _round_maybe(live_metrics.get("coherence"))
                        if live_metrics.get("regime") is not None:
                            compat_eisv["basin"] = live_metrics.get("regime")
                        if live_metrics.get("risk_score") is not None:
                            compat_eisv["risk"] = _round_maybe(live_metrics.get("risk_score"))
                        if live_metrics.get("verdict") is not None:
                            compat_eisv["verdict"] = live_metrics.get("verdict")
                        if compat_eisv:
                            agent_entry["eisv"] = compat_eisv
            except Exception:
                pass  # Overlay is best-effort

            agents.append(agent_entry)

        # Sort: pinned agents first, then by update count
        agents.sort(key=lambda a: (0 if a.get("pinned") else 1, -(a.get("updates") or 0)))

        # Apply basin_filter and risk_threshold AFTER sorting
        if basin_filter is not None:
            agents = [a for a in agents if a.get("eisv", {}).get("basin") == basin_filter]
        if risk_threshold is not None:
            agents = [a for a in agents if (a.get("eisv", {}).get("risk") or 0) >= risk_threshold]

        # Apply offset + limit
        total = len(agents)
        agents = agents[offset:offset + limit]

        return success_response({
            "agents": agents,
            "total": total,
            "showing": len(agents),
            "offset": offset,
            "has_more": (offset + len(agents)) < total,
            "state_semantics": get_state_semantics(),
            "_note": "`eisv` is the primary EISV view. Use `behavioral_eisv` and `ode_eisv` to inspect the split.",
        })

    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return error_response(f"Dashboard failed: {e}")
