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
from src.logging_utils import get_logger

logger = get_logger(__name__)


@mcp_tool("dashboard", timeout=15.0, description="Read-only system overview: all agents with EISV state. No session binding required.")
async def handle_dashboard(arguments: ToolArgumentsDict) -> Sequence[TextContent]:
    """Return all active agents with their current EISV vectors."""
    try:
        db = get_db()
        states = await db.get_all_latest_agent_states()

        # Index states by agent_id — E now comes from s.energy (extracted in _row_to_agent_state)
        state_by_agent: Dict[str, Any] = {}
        for s in states:
            sj = s.state_json or {}
            risk = sj.get("risk_score", 0)
            verdict = sj.get("verdict", "proceed")
            state_by_agent[s.agent_id] = {
                "E": round(s.energy, 4) if s.energy is not None else None,
                "I": round(s.integrity, 4) if s.integrity is not None else None,
                "S": round(s.entropy, 4) if s.entropy is not None else None,
                "V": round(s.void, 4) if s.void is not None else None,
                "coherence": round(s.coherence, 4) if s.coherence is not None else None,
                "basin": s.regime,
                "risk": round(risk, 4) if risk else 0,
                "verdict": verdict,
            }

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
                agent_entry["eisv"] = eisv
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
        })

    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return error_response(f"Dashboard failed: {e}")
