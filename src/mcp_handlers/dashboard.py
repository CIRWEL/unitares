"""Dashboard tool — read-only overview of all agents' EISV state.

Bypasses session binding so visualizers and dashboards can see the full system.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Sequence
from mcp.types import TextContent
from .types import ToolArgumentsDict
from .utils import success_response, error_response
from .decorators import mcp_tool
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

        # Index states by agent_id (E lives in state_json, not a direct column)
        state_by_agent: Dict[str, Any] = {}
        for s in states:
            sj = s.state_json or {}
            E = sj.get("E", 0.5)
            risk = sj.get("risk_score", 0)
            verdict = sj.get("verdict", "proceed")
            state_by_agent[s.agent_id] = {
                "E": round(E, 4) if E is not None else None,
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
        cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days) if recent_days > 0 else None

        agents = []
        for agent_id, meta in mcp_server.agent_metadata.items():
            if meta.status != "active":
                continue
            if meta.total_updates < min_updates:
                continue

            # Always include Lumen regardless of recency
            is_lumen = getattr(meta, "label", "") == "Lumen"

            # Filter by recency using last_update from metadata
            if cutoff and not is_lumen and meta.last_update:
                try:
                    last_dt = datetime.fromisoformat(meta.last_update.replace("Z", "+00:00"))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if last_dt < cutoff:
                        continue
                except Exception:
                    pass

            eisv = state_by_agent.get(agent_id, None)
            agent_entry: Dict[str, Any] = {
                "id": agent_id,
                "label": getattr(meta, "label", None),
                "updates": meta.total_updates,
            }
            if eisv:
                agent_entry["eisv"] = eisv
            agents.append(agent_entry)

        # Sort: Lumen first, then by update count
        agents.sort(key=lambda a: (0 if a.get("label") == "Lumen" else 1, -(a.get("updates") or 0)))

        return success_response({
            "agents": agents,
            "total": len(agents),
        })

    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return error_response(f"Dashboard failed: {e}")
